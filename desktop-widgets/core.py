# Liquid Desktop — © 2026 Hirtou (https://github.com/Hirtou) · MIT License
"""Общее для всех виджетов: настройки (config.json) и окно-виджет на рабочем столе."""
import applog
import skins
from lang import tr
import ctypes
import json
import os
import sys
from ctypes import wintypes as wt
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PySide6.QtCore import QEvent, QPoint, QPointF, QPropertyAnimation, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QCursor, QGuiApplication, QLinearGradient, QPainter, QPainterPath, QPen,
                           QPixmap, QRadialGradient)
from PySide6.QtWidgets import QApplication, QMenu, QWidget

import glass
from desktop_host import DesktopHost

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(ROOT, "config.json")

SHADOW = 18   # поле под тень вокруг карточки
RADIUS = 26   # скругление карточки

# снимок экрана и рендер стекла — в фоне, чтобы окна не подтормаживали
POOL = ThreadPoolExecutor(max_workers=4)
SNAP_SECONDS = 3.0  # столько виджеты видны после клавиши скриншота
SNAP_DIST = 14      # магнит при перетаскивании: с какого расстояния липнет, px
HOLD_TO_MOVE = 0.45  # у виджета со свайпом (фото, гифки): подержал столько, с, потом потянул — виджет едет
GAP = 12            # зазор между виджетами и от края экрана при прилипании, px

# Сетка, как у виджетов на телефоне: все карточки — целое число ячеек (1×1, 2×1, 2×2) с зазором GAP,
# поэтому любые виджеты встают рядом ровно, а магнит при перетаскивании держит тот же зазор.
CELL = 170


def grid(cols, rows):
    """Размер карточки cols×rows ячеек (без поля под тень)."""
    return cols * CELL + (cols - 1) * GAP, rows * CELL + (rows - 1) * GAP


def grid_rows(height):
    """Сколько ячеек по высоте нужно, чтобы влезло height (минимум одна)."""
    rows = 1
    while grid(1, rows)[1] < height:
        rows += 1
    return rows


def open_uri(uri):
    """Открыть ссылку, приложение (ms-clock:, ms-settings:…) или файл — только по действию пользователя."""
    try:
        os.startfile(uri)
    except OSError:
        traceback.print_exc()

STYLE = """
QLabel {{ color: {fg}; background: transparent; }}
QLabel#dim {{ color: {dim}; }}
QToolTip {{ color: #f5f6fb; background: #23252d; border: 1px solid #4a4d5a; padding: 5px 8px; font-size: 12px; }}
QPlainTextEdit {{ background: {field}; color: {fg}; border: none; border-radius: 12px;
                  padding: 6px; font-size: 14px; }}
QProgressBar {{ background: {track}; border: none; border-radius: 3px; }}
QLineEdit {{ background: {field}; color: {fg}; border: none; border-radius: 10px; padding: 6px 10px;
             font-size: 13px; }}
QCheckBox {{ color: {fg}; spacing: 10px; font-size: 14px; background: transparent; }}
QCheckBox:checked {{ color: {dim}; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 9px; border: 2px solid {dim}; }}
QCheckBox::indicator:checked {{ background: #2f6bff; border-color: #2f6bff; }}
QFrame#card {{ background: {card}; border: 1px solid {cardline}; border-radius: 20px; }}
QFrame#card:hover {{ background: {cardhover}; }}
QLabel#bubble {{ background: {bubble}; border: 1px solid {cardline}; border-radius: 22px; font-size: 22px; }}
"""


class Config:
    def __init__(self):
        try:
            with open(CONFIG_PATH, encoding="utf-8-sig") as f:  # -sig: Блокнот мог дописать BOM
                self.data = json.load(f)
            if not isinstance(self.data, dict):
                raise ValueError("не словарь")
        except FileNotFoundError:
            self.data = {}
        except (OSError, ValueError):
            # файл испорчен (обрыв записи, правили руками) — не затирать молча: отложить копию, начать с чистого
            self.data = {}
            try:
                os.replace(CONFIG_PATH, CONFIG_PATH[:-5] + time.strftime(".broken-%Y%m%d-%H%M%S.json"))
            except OSError:
                pass

    def section(self, name):
        return self.data.setdefault(name, {})

    def save(self):
        # сначала во временный файл, потом подмена целиком: выключат свет посреди записи — старый файл цел
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        # файл в этот миг читает остров (или антивирус) — Windows не даёт его заменить. Раньше это роняло
        # всю программу (редактор своей темы сохранял на каждое движение). Ждём и пробуем ещё раз.
        for attempt in range(8):
            try:
                os.replace(tmp, CONFIG_PATH)
                return
            except PermissionError:
                time.sleep(0.03 * (attempt + 1))
        applog.line("настройки: config.json занят другой программой — сохраню при следующем изменении")


config = Config()


# замер перерисовок: переменная окружения WIDGETS_PROFILE=1 — раз в 20 с в журнал, кто сколько рисовался
PROFILE = {} if os.environ.get("WIDGETS_PROFILE") else None


def profile_report():
    if not PROFILE:
        return
    top = sorted(PROFILE.items(), key=lambda kv: (-kv[1][1], -kv[1][0]))
    applog.line("замер 20 с: " + ", ".join(f"{k} {n} кадров {ms * 1000:.0f} мс" for k, (n, ms) in top[:14]))
    PROFILE.clear()


CHANGE = 1.5  # средняя разница кадров (0..255), с которой стекло пересчитывается
JUMP = 0.12   # скачок яркости фона (0..1) — окно, а не живые обои: тема берётся из памяти (см. theme_prev)


def changed(src, last):
    """Заметно ли поменялось то, что под стеклом. Живые обои со снегом меняют каждый кадр на ~0.5–1 —
    это стекло не трогает (оно размыто, снежинок в нём не видно); перелив неба копится и пересчитывает."""
    if last is None or src.shape != last.shape:
        return True
    # снимок экрана уже уменьшен в 4 раза (glass.small_size) — сравниваем целиком; полный (обои) — через 4 px
    step = 1 if src.shape[1] < 200 else 4
    return float(np.abs(src[::step, ::step].astype(np.int16) - last[::step, ::step]).mean()) > CHANGE


class Activity:
    spawned = 0  # сколько новых виджетов уже поставили в центр за этот запуск (лесенка)

    """Один общий такт на все виджеты: 30 раз в секунду снимает экран под теми, кому пора
    (одним снимком на монитор), и 4 раза в секунду смотрит, чем занят пользователь."""

    def __init__(self):
        self.mode = "desktop"
        self.timer = None
        self.ticks = 0
        self.cursor = None
        self.moved = 0.0  # когда последний раз двигалась мышь
        self.snap_until = 0.0  # до этого момента идёт скриншот: виджеты видны, стекло замерло
        self.editing = False   # «Двигать виджеты»: виджеты подняты наверх, иначе вшиты под ярлыки
        self.wpe = None        # идут живые обои (Wallpaper Engine) — под ярлыками ничего не видно
        self.under_icons = False  # режим: вшиты под ярлыки или обычные окна на рабочем столе (под всеми окнами)
        self.copies = None     # каталог: ещё одна копия виджета (фото, гифка) — add(база, рядом_с), remove(виджет)
        self.checks = 0
        self.last_check = 0.0
        # сколько кадров в работе на каждом мониторе: новый не снимаем, пока старый не готов
        self.inflight = {}
        self.cover = None  # окно впереди (физ. пиксели), если пользователь в окне
        self.desk_front = False  # впереди сам рабочий стол (Win+D) — виджеты временно «поверх всех»
        self.fs_monitor = None  # монитор игры на весь экран
        self.on_game = None  # началась / закончилась игра на весь экран: on_game(True/False) — подпись в трее

    def start(self):
        if self.timer is None:
            self.wpe = glass.live_wallpaper_running()
            # «Под ярлыками» и «В рабочем столе» убраны (20.11.2026): виджеты — всегда обычные окна на рабочем столе,
            # даже если в старых настройках режим был включён
            self.under_icons = False
            self.hook = glass.watch_screenshot_keys(self.on_screenshot)
            if PROFILE is not None:
                self.prof_timer = QTimer(interval=20000, timeout=profile_report)
                self.prof_timer.start()
            # точный таймер: обычный в Windows шагает по ~15.6 мс, и 33 мс превращаются в 47
            self.timer = QTimer(interval=33, timeout=self.tick, timerType=Qt.PreciseTimer)
            self.timer.start()
            # монитор отключили / сменили разрешение — виджеты, оставшиеся за краем, вернуть на экран
            app = QGuiApplication.instance()
            app.screenRemoved.connect(self.screens_changed)
            app.primaryScreenChanged.connect(self.screens_changed)
            for s in app.screens():
                s.geometryChanged.connect(self.screens_changed)
            app.screenAdded.connect(lambda s: s.geometryChanged.connect(self.screens_changed))

    def screens_changed(self, *_):
        """Сменилось разрешение (игра со своим разрешением, отключили монитор). Windows сама сдвигает окна внутрь
        маленького экрана и обратно их не возвращает — виджеты оставались сбитыми в кучу у края. Ждём, пока
        смены утихнут (игра дёргает разрешение несколько раз), и ставим каждый виджет на его сохранённое место."""
        if getattr(self, "_screens_timer", None) is None:
            self._screens_timer = QTimer(singleShot=True, interval=1500, timeout=self.screens_settled)
        self._screens_timer.start()

    def screens_settled(self):
        applog.line("экраны: " + ", ".join(
            f"{s.geometry().width()}x{s.geometry().height()}@{s.devicePixelRatio():g}"
            for s in QGuiApplication.screens()))
        for w in self.widgets():
            w._rect_cache = None
            w.restore_place()

    def widgets(self):
        """Все виджеты. Список окон Qt собирать дорого (окон много: превью каталога, меню), а зовём его
        несколько раз за такт — пересобираем не чаще двух раз в секунду."""
        now = time.monotonic()
        cache = getattr(self, "_widgets", None)
        if cache is None or now - cache[0] > 0.5:
            cache = self._widgets = (now, [w for w in QApplication.topLevelWidgets() if isinstance(w, DesktopWidget)])
        return cache[1]

    @staticmethod
    def forget_widgets(*_):
        activity._widgets = None

    def on_screenshot(self):
        """Нажали клавишу скриншота: показать виджеты снимку (стекло замрёт, иначе оно снимет само себя)."""
        self.snap_until = time.monotonic() + SNAP_SECONDS
        for w in self.widgets():
            if w.isVisible() and w.live:
                glass.include_in_capture(int(w.winId()))
        QTimer.singleShot(int(SNAP_SECONDS * 1000), self.after_screenshot)

    def after_screenshot(self):
        if time.monotonic() < self.snap_until - 0.05:  # нажали ещё раз — ждём дальше
            return
        for w in self.widgets():
            if w.isVisible() and w.live:
                glass.exclude_from_capture(int(w.winId()))
                w.due = 0.0

    def tick(self):
        self.ticks += 1
        now = time.monotonic()
        if now - self.last_check >= 0.19:  # 4–5 раз в секунду — чем занят пользователь (при любом такте)
            self.last_check = now
            self.check()
        if now < self.snap_until:
            return
        # рабочий стол сам по себе не меняется — только когда двигаешь мышь;
        # мышь замерла на 1 с — виджеты на столе смотрят под себя 2 раза в секунду (и реже, если ничего не меняется)
        pos = QCursor.pos()
        if pos != self.cursor:
            if now - self.moved > 1.0:  # мышь ожила — сразу свежее стекло
                for w in self.widgets():
                    w.due, w.same = 0.0, 0
            self.cursor, self.moved = pos, now
        idle = now - self.moved > 1.0
        # сам такт: 20 раз в секунду, пока двигается мышь (30 — разницы на размытом стекле не видно, а процессор
        # заметно занят); в покое хватает 5; в игре на весь экран — 4
        moving = idle and any(getattr(w, "streak", 0) >= 2 for w in self.widgets())  # живые обои в движении
        # живые обои в движении — 5 раз в секунду (было 10): под размытым стеклом медленные обои и так плавные,
        # а каждый такт — снимок экрана и пересчёт стекла у всех виджетов
        rate = 250 if self.mode == "fullscreen" else 200 if moving else 200 if idle else 50
        if self.timer.interval() != rate:
            self.timer.setInterval(rate)
        groups = {}
        cur = wt.POINT()  # где мышь (физические пиксели): виджетам на другом мониторе она ничего не меняет
        glass.user32.GetCursorPos(ctypes.byref(cur))
        # окно впереди (физ. пиксели): виджеты, которые оно закрывает целиком, не видны — их стекло не снимаем
        cover = self.front_cover()
        for w in self.widgets():
            # кому пора — и заодно тем, кому скоро (до 40% интервала, не больше 0.2 с): один снимок монитора
            # на всех, а не по одному
            if w.interval is None or not w.isVisible() or w.isMinimized() \
                    or now < w.due - min(0.2, w.interval * 0.0004):
                continue
            win, monitor = self.win_rect(w, True)
            if self.inflight.get(monitor, 0) >= 1:
                continue
            # закрыт окном целиком — не видно, снимать незачем. Закрыт частью — снимаем: видимый край
            # иначе так и показывал бы то, что было под ним раньше (чёрное окно, которое уже свернули)
            if cover and not w.on_top() and glass.hides(cover, win, SHADOW * w.devicePixelRatioF()):
                continue
            interval = w.interval
            # мышь стоит или далеко (курсор в снимок не попадает, а на столе под мышью меняется только то,
            # что рядом: подсветка ярлыка, рамка выделения) — для этого виджета покой
            near = 250 * w.devicePixelRatioF()
            calm = idle or not (win[0] - near <= cur.x < win[2] + near and win[1] - near <= cur.y < win[3] + near)
            if calm and self.mode in ("desktop", "window") and not w.on_top():
                # под ним только рабочий стол, а он без мыши не меняется; снимки одинаковые — ещё реже (до 4 с:
                # мышь ожила или сменилось окно впереди — снимок сразу, due сбрасывается)
                # мышь совсем стоит — раз в секунду и при живых обоях: стекло размыто, разницы с двумя кадрами не видно
                interval = max(1000 if idle else 500, 500 * (1 + min(7, w.same // 2)))
                # под стеклом всё время движется (яркие быстрые живые обои): раз в полсекунды-секунду стекло
                # заметно дёргалось и отставало от обоев. Два снимка подряд разные — смотрим 8 раз в секунду,
                # пока движение не остановится (одинаковые снимки сразу возвращают редкий опрос)
                # 20.11.2026: 125 мс давали ~10% ядра на одно стекло над живыми обоями — теперь ~3 раза в секунду:
                # через размытие колыхание обоев почти не отличить, а процессор — вдвое свободнее
                if getattr(w, "streak", 0) >= 2:
                    interval = 300
            w.due = now + interval / 1000
            args, (win, monitor, *rest) = w._job()
            groups.setdefault(monitor, []).append((w, args, glass.capture_rect(win, *rest)))
        for monitor, items in groups.items():
            self.inflight[monitor] = self.inflight.get(monitor, 0) + 1
            POOL.submit(self.capture_group, monitor, items)

    @staticmethod
    def capture_group(monitor, items):
        """Фоновый поток: один снимок на монитор, дальше каждый виджет — своё стекло."""
        try:
            shots = glass.capture_many(monitor, [rect for _, _, rect in items])
        except Exception as _err:
            applog.error("core.Activity.capture_group", _err)
            shots = [None] * len(items)
        try:
            for (w, args, _), src in zip(items, shots):
                w._deliver(DesktopWidget._render(args, src))
        finally:
            activity.inflight[monitor] -= 1

    def check(self):
        self.checks += 1
        if self.checks % 20 == 0:  # раз в ~5 с: пояс системы могли сменить; не запустили/закрыли живые обои?
            glass.refresh_timezone()
            if not self.editing and config.section("app").get("desktop_child", False):
                for w in self.widgets():
                    if w.keep_bottom and w.placed and w.desktop_host is not None and not w.desktop_host.valid():
                        w.place()  # Проводник перезапускали — вложить заново
            desk = glass.desktop_window()
            if desk != getattr(self, "desk", desk):  # ярлыки переехали в другое окно (запустили живые обои) —
                for w in self.widgets():             # виджеты снова положить прямо над рабочим столом
                    if w.placed and w.keep_bottom:
                        if w.pinned:
                            w.pinned.destroy()
                            w.pinned = None
                            w.pin()
                        else:
                            w.sync_topmost()
            self.desk = desk
            wpe = glass.live_wallpaper_running()
            if wpe != self.wpe:
                self.wpe = wpe
                for w in self.widgets():
                    if w.placed:
                        w.place()
        mode = glass.foreground()
        refresh = False
        # Впереди сам рабочий стол (Win+D, «Свернуть все», клик по пустому столу). На «Показать рабочий стол»
        # Windows выносит окно рабочего стола НАД всеми обычными окнами — виджеты оказывались под ним
        # и пропадали. Пока впереди стол, держим виджеты «поверх всех» (так делает и Rainmeter); открыли
        # любое окно — снова обычные окна прямо над рабочим столом.
        # Не просто «щёлкнули по пустому столу» (на втором мониторе — окна на первом при этом открыты),
        # а стол действительно встал НАД виджетами. Поднялись — держим, пока впереди стол
        # (поднятые, они уже выше стола, и проверка сама по себе сразу отпустила бы их обратно).
        desk = glass.foreground_class() in glass.DESKTOP_CLASSES
        if not desk and self.desk_front and not glass.foreground_shown():
            # После Win+D Windows через секунду-две отдаёт фокус свёрнутому окну (браузеру), хотя его не видно:
            # раньше виджеты в этот момент опускались — и рабочий стол снова их закрывал. Пока окно впереди
            # свёрнуто или спрятано, считаем, что впереди всё ещё стол.
            front = True
        elif not desk:
            front = False
        elif self.desk_front:
            front = True
        else:
            front = any(w.placed and w.keep_bottom and not w.pinned and w.isVisible() and not w.desktop_attached()
                        and glass.desktop_over(int(w.winId())) for w in self.widgets())
        if front != self.desk_front:
            self.desk_front = front
            for w in self.widgets():
                if w.placed and w.keep_bottom and not w.pinned and w.isVisible():
                    w.sync_topmost()
        if mode is not None and mode != self.mode:  # панель задач не меняет режим
            game = (mode == "fullscreen") != (self.mode == "fullscreen")
            self.mode = mode
            refresh = True
            for w in self.widgets():
                w.set_rate()
            if mode == "desktop":
                # «Показать рабочий стол» (Win+D, кнопка в углу панели задач): Windows поднимает рабочий стол
                # над всеми окнами — и над виджетами тоже, они пропадали. Возвращаем их на место над столом:
                # сразу и ещё дважды, пока Windows доигрывает своё.
                self.raise_over_desktop()
                for delay in (250, 700):
                    QTimer.singleShot(delay, self.raise_over_desktop)
            if game and self.on_game:
                self.on_game(mode == "fullscreen")
        if mode == "fullscreen":  # на каком мониторе игра (её могли перетащить — смотрим каждый раз, это дёшево)
            self.fs_monitor = glass.window_rect(glass.user32.GetForegroundWindow())[1]
        # окно впереди: виджеты, которые оно закрывает целиком, анимацию не рисуют (см. covered)
        cover = self.front_cover()
        if cover != self.cover or refresh:
            self.cover = cover
            self.changed_at = now = time.monotonic()
            # Окно свернули — впереди снова рабочий стол. Но Windows сворачивает с анимацией (~0.3 с), и снимок
            # в этот момент ловит ещё тёмное окно: виджеты на полсекунды становились тёмными («свернул браузер —
            # и тут такое, потом исчезает»). Поэтому сразу ставим стекло, которое было над чистым столом в прошлый
            # раз, а переснимаем, когда анимация закончится.
            to_desk = self.mode == "desktop"
            for w in self.widgets():  # открылись — сразу свежий кадр и стекло, а не то, что было до окна
                if w.isVisible():
                    saved = getattr(w, "desk_glass", None) if to_desk and not w.on_top() else None
                    if saved is not None and saved[1].size() == w.card().size():
                        w.gen += 1  # снимки, заказанные раньше (с окном в кадре), отбросятся
                        w.apply((w.gen, saved))
                        w.due, w.same = now + 0.35, 0
                    else:
                        w.due, w.same = 0.0, 0
                    w.update()
            for delay in (420, 800):  # и ещё раз после анимации — на случай, если она шла дольше
                QTimer.singleShot(delay, self.refresh_glass)

    def raise_over_desktop(self):
        if self.mode != "desktop" or self.editing:
            return
        for w in self.widgets():
            if w.placed and w.keep_bottom and not w.pinned:
                if not w.isVisible():
                    w.show()
                w.sync_topmost()

    def refresh_glass(self):
        """Всем видимым виджетам — свежий снимок под стеклом прямо сейчас."""
        for w in self.widgets():
            if w.isVisible():
                w.due, w.same = 0.0, 0
        self.tick()

    def front_cover(self):
        """Где окно впереди (физ. пиксели) или None. Кликнули по самому виджету — впереди его же окно: раньше оно
        «закрывало» само себя, и визуализатор, часы и стекло замирали до клика по другому окну. Свои виджеты
        окном впереди не считаем."""
        if self.mode != "window":
            return None
        fg = glass.user32.GetForegroundWindow()
        if not fg or any(int(w.winId()) == int(fg) for w in self.widgets() if w.placed):
            return None
        return glass.cover_rect(fg)

    def covered(self, w):
        """Виджета сейчас не видно: игра на весь экран или окно впереди закрывает его целиком.
        Тогда часы, слова песни и персонаж не рисуют кадры зря (Windows всё равно их рисует, даже под окном)."""
        if w.on_top() or not w.isVisible():
            return not w.isVisible()
        if self.mode == "fullscreen":
            # игровой режим (по умолчанию): замирает всё, и на других мониторах — ни кадров, ни опросов
            if config.section("app").get("game_pause", True):
                return True
            # выключен: игра закрывает только свой монитор, на втором виджеты живут (температура и пинг во время игры)
            return self.fs_monitor is None or self.win_rect(w, True)[1] == self.fs_monitor
        if self.cover is None:
            return False
        return glass.hides(self.cover, self.win_rect(w, True)[0], SHADOW * w.devicePixelRatioF())

    def win_rect(self, w, both=False):
        """Где окно виджета и его монитор (физ. пиксели) — из кэша на 0.5 с: такт (30 раз в секунду, пока двигается
        мышь) и covered() у анимаций спрашивали это у Windows для каждого окна — три вызова на окно, заметная доля
        процессора. Виджет двигают — кэш сбрасывает moveEvent. both=False — только окно."""
        now = time.monotonic()
        hit = getattr(w, "_rect_cache", None)
        if hit is None or now - hit[0] > 0.5:
            hit = w._rect_cache = (now, glass.window_rect(int(w.winId())))
        return hit[1] if both else hit[1][0]

    def paused(self, w):
        """Опрашивать данные незачем: окно видно системе, но его закрыли игрой или окном (откроют — следующий такт
        покажет свежее). Скрытые окна опрос не останавливают: это превью каталога и виджет под ярлыками."""
        return w.isVisible() and self.covered(w)


activity = Activity()


class ScaledPainter(QPainter):
    """QPainter, который на виджете сразу ставит его масштаб: код виджета рисует в обычных координатах."""

    def __init__(self, *args):
        super().__init__(*args)
        if args and isinstance(args[0], DesktopWidget):
            k = args[0].scale()
            if k != 1:
                self.scale(k, k)


_GLOW_CACHE = {}  # свечение темы «Неон»: (ш, в, тема, плотность пикселей) -> картинка


def set_skin(skin_id):
    """Сменить тему оформления: запомнить, перекрасить акцент и пересчитать стекло у всех виджетов сразу."""
    config.section("app")["skin"] = skin_id
    config.save()
    skins.apply(skin_id, config.section("app").get("custom_skin"))
    applog.line(f"тема оформления: {skins.current_id()}")
    redraw_skin()


def set_custom(spec):
    """Своя тема поменялась в редакторе: запомнить и сразу показать на виджетах (если она включена)."""
    config.section("app")["custom_skin"] = spec
    skins.apply(skins.current_id(), spec)
    redraw_skin()
    # на диск — когда перестали двигать (ползунок цвета даёт десятки правок в секунду), остров подхватит оттуда
    global _custom_save
    if _custom_save is None:
        _custom_save = QTimer(singleShot=True, interval=600, timeout=config.save)
        # закрыли программу раньше, чем таймер сработал, — сохранить сразу, иначе последняя правка теряется
        QApplication.instance().aboutToQuit.connect(
            lambda: config.save() if _custom_save.isActive() else None)
    _custom_save.start()


_custom_save = None


def accent_palette():
    """Ползунки, выделение текста и прочее стандартное Qt — цветом акцента темы. Раньше они брали синий акцент
    Windows и оставались синими в оранжевой / своей теме."""
    from PySide6.QtGui import QPalette
    app = QApplication.instance()
    pal = app.palette()
    for group in (QPalette.Active, QPalette.Inactive):
        pal.setColor(group, QPalette.Highlight, skins.ACCENT)
        if hasattr(QPalette, "Accent"):
            pal.setColor(group, QPalette.Accent, skins.ACCENT)
    app.setPalette(pal)
    # Ползунки внутри областей со своим styleSheet (страницы каталога) запоминают палитру при создании и смену
    # темы на ходу не видят — красим каждый напрямую.
    from PySide6.QtWidgets import QAbstractSlider
    for w in app.allWidgets():
        if isinstance(w, QAbstractSlider) and not w.styleSheet():
            own = w.palette()
            for group in (QPalette.Active, QPalette.Inactive):
                own.setColor(group, QPalette.Highlight, skins.ACCENT)
                if hasattr(QPalette, "Accent"):
                    own.setColor(group, QPalette.Accent, skins.ACCENT)
            w.setPalette(own)
            w.update()


def redraw_skin():
    """Перерисовать всё в новой теме: стекло, кромку, свечение."""
    accent_palette()
    for w in QApplication.topLevelWidgets():
        if isinstance(w, DesktopWidget):
            w.last_src = None      # иначе «фон не изменился» — и стекло не пересчитается
            w.desk_glass = None    # запасное стекло «над чистым столом» — в старой теме
            w.flat_key = None
            w._chrome_key = None
            w.rebuild()
            w.update()
        else:
            w.update()


def skin_menu(menu):
    """Подменю «Тема» (в меню виджета и в трее)."""
    sub = menu.addMenu(tr("Тема"))
    acts = {}
    for sid in skins.ORDER:
        s = skins.SKINS[sid]
        a = acts[sid] = sub.addAction(f"{s['name']} — {s['sub']}", lambda i=sid: set_skin(i))
        a.setCheckable(True)

    def mark():  # галочка у текущей — при каждом открытии (меню в трее живёт всё время)
        for sid, a in acts.items():
            a.setChecked(skins.current_id() == sid)
    sub.aboutToShow.connect(mark)
    mark()
    return sub


class DesktopWidget(QWidget):
    """Окно без рамки на рабочем столе: карточка из «жидкого акрила», таскается мышью."""

    key = ""
    title = ""
    description = ""
    keep_bottom = True  # держать под окнами (у окна программы — нет)
    copy_of = None  # у копии (ещё одно «Фото», ещё одна «Гифка») — ключ исходного виджета
    wall_checked = 0.0  # когда последний раз смотрели, не сменились ли обои (общее на все виджеты)
    glass_ready = Signal(object)  # из фонового потока: (снимок, стекло, тёмное?) или None

    def __init_subclass__(cls, **kw):
        """Рисовальщики в модуле виджета — с масштабом (см. ScaledPainter)."""
        super().__init_subclass__(**kw)
        mod = sys.modules.get(cls.__module__)
        if mod is not None and getattr(mod, "QPainter", None) is QPainter:
            mod.QPainter = ScaledPainter

    def __init__(self, on_closed=None):
        super().__init__(None)
        self.base = None  # обычный размер окна (без масштаба), если виджет задаёт его сам
        self.cfg = config.section(self.key)
        self.on_closed = on_closed
        self._drag = None
        self.dark = None
        self.lum = None        # яркость фона под прошлым стеклом
        self.theme_mem = {}    # яркость фона (шагами по 0.05) -> какая тема была над таким фоном
        self.glass_img = None
        self.shadow_img = None
        self.live = False      # видно ли живой экран под стеклом
        self.last_src = None
        self.busy = False      # стекло считается в фоне
        self.pending = False   # пока считалось, просили ещё раз
        self.gen = 0           # номер последнего заказа стекла
        self.shown_gen = 0     # номер показанного (старые результаты из фона отбрасываем)
        self.glass_ready.connect(self.on_glass)
        # окно удалили (выключили виджет, закрыли каталог с превью) — список виджетов собрать заново,
        # иначе такт ещё полсекунды трогает уже удалённое окно (RuntimeError «already deleted»)
        self.destroyed.connect(Activity.forget_widgets)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setContentsMargins(SHADOW, SHADOW, SHADOW, SHADOW)
        self.apply_flags()
        self.set_dark(False)
        if "x" not in self.cfg:
            # первый раз — по центру главного экрана, где его сразу видно (окончательный размер виджет узнает
            # позже — тогда и доцентрируется, см. center_new); каждый следующий новый — чуть ниже и правее,
            # чтобы два только что включённых не легли ровно друг на друга
            self.new_spot = True
        self.move(self.cfg.get("x", 0), self.cfg.get("y", 0))

        # свет под курсором
        self.hover = QTimer(self, interval=33, timeout=self.update)
        # обои сменились — перерисовать стекло
        self.wall_timer = QTimer(self, interval=5000, timeout=self.check_wallpaper)
        self.wall_timer.start()
        # как часто смотреть под стекло (мс или None — не смотреть); выбирает set_rate
        self.interval = None
        self.due = 0.0
        self.same = 0          # сколько снимков подряд под стеклом ничего не менялось (реже смотрим)
        activity.start()
        # под ярлыками: окно WinAPI с картинкой виджета (см. pin)
        self.pinned = None
        self.flat_key = None
        self.placed = False  # виджет включён и разложен (place)
        self.desktop_host = None  # внутри рабочего стола (app.desktop_child) — см. desktop_host.py
        self.push_timer = QTimer(self, interval=1000, timeout=self.push)

    # ---------- окно ----------

    def desktop_attached(self):
        host = getattr(self, "desktop_host", None)  # move() зовут и из __init__, до появления host
        return bool(host and host.attached)

    def pos(self):
        if self.desktop_attached():
            return self.desktop_host.global_pos()
        return QWidget.pos(self)

    def x(self):
        return self.pos().x()

    def y(self):
        return self.pos().y()

    def move(self, *args):
        if self.desktop_attached():
            self.desktop_host.move_global(QPoint(args[0]) if len(args) == 1 else QPoint(args[0], args[1]))
        else:
            QWidget.move(self, *args)

    def frameGeometry(self):
        if self.desktop_attached():
            return QRect(self.pos(), self.size())
        return QWidget.frameGeometry(self)

    def ensure_desktop(self):
        """Вложить в рабочий стол (если включено). -> вложен ли сейчас."""
        if True:  # режим «В рабочем столе» убран — виджеты всегда отдельными окнами
            return False
        if self.desktop_host is None:
            self.desktop_host = DesktopHost(self)
        if not self.desktop_host.attached:
            self.push_timer.stop()
            if self.pinned:
                self.pinned.destroy()
                self.pinned = None
            self.apply_flags()  # снять «поверх всех» от «Двигать виджеты» до того, как вкладывать
        was_valid, old_peer = self.desktop_host.valid(), self.desktop_host.peer
        self.desktop_host.attach(activity.under_icons)
        if self.desktop_host.valid():
            if not was_valid or old_peer != self.desktop_host.peer:
                self.gen = max(self.gen, self.shown_gen) + 1  # кадры, заказанные до смены — отбросить
                self.shown_gen = self.gen
                self.last_src = None
                self.flat_key = None
                self.live = False
                self.apply_backdrop()
                self.setup_capture()
            return True
        position = self.desktop_host.global_pos() if self.desktop_host.attached else self.pos()
        self.desktop_host.detach()
        QWidget.move(self, position)
        return False

    def on_top(self):
        """Окно виджета поверх всего — только пока «Двигать виджеты»; обычно виджет вшит под ярлыки."""
        return activity.editing

    def place(self):
        """Куда положить виджет:
        «Двигать виджеты» — наверх, поверх всего;
        режим «обычно» — обычное окно под всеми окнами, над ярлыками;
        иначе — под ярлыки, как обои. С живыми обоями (Wallpaper Engine) под ярлыками ничего не видно
        (их видео закрывает) — тогда тоже обычное окно, чтобы виджеты не пропадали."""
        self.placed = True
        if activity.editing:
            if self.desktop_host:
                self.desktop_host.detach()
            self.unpin()
        elif self.ensure_desktop():
            pass  # внутри рабочего стола (app.desktop_child)
        elif not activity.under_icons or activity.wpe:
            self.unpin()
        else:
            self.pin()
        QTimer.singleShot(0, self.center_new)  # под ярлыками окно скрыто — showEvent не придёт
        QTimer.singleShot(0, self.keep_on_screen)

    def nativeEvent(self, event_type, message):
        if self.desktop_attached():  # внутри рабочего стола: свой фокус для полей ввода, порядком окон не командуем
            self.desktop_host.native_focus(wt.MSG.from_address(int(message)).message)
            return super().nativeEvent(event_type, message)
        if wt.MSG.from_address(int(message)).message == 0x001E:  # WM_TIMECHANGE: перевели часы или сменили пояс
            glass.refresh_timezone()
            self.update()
        # не поверх окон: что бы ни делали (клик, перетаскивание), окно остаётся в самом низу
        if self.keep_bottom and not activity.editing and not self.pinned and activity.desk_front:
            # Впереди сам рабочий стол (Win+D) — встаём «поверх всех». Сами, и сообщение Qt не отдаём:
            # у окна «всегда снизу» Qt тут же меняет «поверх всех» обратно на «в самый низ», и виджет
            # оставался под рабочим столом.
            msg = wt.MSG.from_address(int(message))
            if msg.message == 0x0046:  # WM_WINDOWPOSCHANGING
                pos = glass.WINDOWPOS.from_address(msg.lParam)
                pos.hwndInsertAfter = -1  # HWND_TOPMOST
                pos.flags &= ~0x0004      # без SWP_NOZORDER
                return True, 0
        if getattr(self, "_dropping", False):  # первый шаг «снять поверх всех» — пропускаем как есть, мимо Qt
            msg = wt.MSG.from_address(int(message))
            if msg.message == 0x0046:
                return True, 0
        if self.keep_bottom and not activity.editing and not self.pinned and not activity.desk_front:
            msg = wt.MSG.from_address(int(message))
            if msg.message == 0x0046:  # WM_WINDOWPOSCHANGING
                pos = glass.WINDOWPOS.from_address(msg.lParam)
                # прямо над рабочим столом (окно с ярлыками), а не «в самый низ»: в некоторых сборках Windows 11
                # рабочий стол не самый нижний, и HWND_BOTTOM прятал виджет под ним — видно было только
                # при «Двигать виджеты»
                above = glass.above_desktop(int(msg.hWnd or 0))  # не winId(): окно может ещё создаваться
                if above == -1:  # уже прямо над рабочим столом — порядок не трогаем
                    pos.flags |= 0x0004  # SWP_NOZORDER
                else:
                    pos.hwndInsertAfter = above
                    pos.flags &= ~0x0004  # без SWP_NOZORDER
            elif msg.message == 0x0047:  # WM_WINDOWPOSCHANGED: ушли в самый низ — подложку снова под себя
                self.follow_backdrop()
        return super().nativeEvent(event_type, message)

    def apply_flags(self):
        flags = Qt.FramelessWindowHint | Qt.Tool
        flags |= Qt.WindowStaysOnTopHint if self.on_top() else Qt.WindowStaysOnBottomHint
        visible = self.isVisible()
        self.setWindowFlags(flags)
        if visible:
            self.show()
        self.sync_topmost()

    def sync_topmost(self):
        """Поверх всех окон — сами: Qt при смене флага у окна-инструмента «поверх» в Windows не ставит
        (флаг Qt есть, WS_EX_TOPMOST нет — «Двигать виджеты» не поднимал их над окнами)."""
        if not self.isVisible() or self.pinned or self.desktop_attached():
            return
        # -1 — поверх всех, -2 — снять «поверх всех»; дальше nativeEvent сам опустит виджет к рабочему столу
        top = self.on_top() or (self.keep_bottom and activity.desk_front)
        hwnd = int(self.winId())
        was_top = bool(glass.user32.GetWindowLongW(hwnd, -20) & 0x8)  # WS_EX_TOPMOST
        self._dropping = was_top and not top
        glass.user32.SetWindowPos(hwnd, wt.HWND(-1 if top else -2), 0, 0, 0, 0,
                                  0x0001 | 0x0002 | 0x0010)  # без сдвига, размера и активации
        if self._dropping:
            # Сняли «поверх всех» — Windows кладёт окно на верх обычных окон, то есть над открытым окном
            # (виджет висел поверх браузера после Win+D). Вторым шагом опускаем к рабочему столу.
            self._dropping = False
            if self.keep_bottom and not self.on_top():
                glass.user32.SetWindowPos(hwnd, wt.HWND(1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)

    # ---------- под ярлыками ----------

    def pin(self):
        """Вшить под ярлыки рабочего стола: окно Qt прячем, его картинку кладём в окно под ярлыками."""
        if self.pinned:
            return
        self.pinned = glass.Pin()
        self.flat_key = None
        self.hide()
        self.push()
        self.push_timer.start()

    def unpin(self):
        """Поднять наверх (двигать, печатать, правый клик): обычное окно с живым стеклом."""
        self.push_timer.stop()
        if self.pinned:
            self.pinned.destroy()
            self.pinned = None
        self.glass_img = None
        self.flat_key = None  # стекло посчитать заново (живое или изморозь — по режиму)
        self.apply_flags()
        self.show()

    def push_interval(self):
        """Как часто обновлять картинку под ярлыками (метеочасы — чаще, ради секундной стрелки)."""
        return 1000

    def physical_pos(self):
        """Где окно на экране в физических пикселях (окно под ярлыками живёт в них)."""
        p = self.pos()
        s = QGuiApplication.screenAt(p + QPoint(SHADOW, SHADOW)) or QGuiApplication.primaryScreen()
        g, d = s.geometry(), s.devicePixelRatio()
        return round(g.x() + (p.x() - g.x()) * d), round(g.y() + (p.y() - g.y()) * d)

    def push(self):
        """Нарисовать виджет скрыто и положить картинку под ярлыки."""
        if not self.pinned:
            return
        if self.layout():
            self.layout().activate()
            self.adjustSize()
        self.update_flat()
        self.pinned.show(self.grab().toImage(), *self.physical_pos())
        interval = self.push_interval()
        if self.push_timer.interval() != interval:
            self.push_timer.setInterval(interval)

    def card(self):
        """Карточка в координатах рисования (без масштаба — виджеты рисуют в своём обычном размере)."""
        if self.base:
            return QRect(SHADOW, SHADOW, self.base[0] - 2 * SHADOW, self.base[1] - 2 * SHADOW)
        return self.rect().adjusted(SHADOW, SHADOW, -SHADOW, -SHADOW)

    # ---------- размер (масштаб) ----------
    # Виджет рисует в обычном размере, а окно и вся картинка растягиваются в scale() раз:
    # ядро и рисовальщики виджетов (ScaledPainter) сами ставят масштаб, клики пересчитываются обратно.
    # Виджеты из готовых подписей (раскладка Qt) так не растянуть — у них размер не меняется.

    SIZES = (0.75, 0.9, 1.0, 1.15, 1.3, 1.5)

    def resizable(self):
        return self.layout() is None

    def scale(self):
        if getattr(self, "preview", False) or not self.resizable():
            return 1.0
        return float(self.cfg.get("scale", 1.0))

    def setFixedSize(self, w, h=None):
        if h is None:
            w, h = w.width(), w.height()
        self.base = (w, h)
        k = self.scale()
        super().setFixedSize(round(w * k), round(h * k))

    def card_on_screen(self, pos=None):
        """Где карточка на экране (логические пиксели, с масштабом) при левом верхнем углу окна в pos."""
        pos = self.pos() if pos is None else pos
        c, k = self.card(), self.scale()
        return QRect(pos.x() + round(c.x() * k), pos.y() + round(c.y() * k),
                     round(c.width() * k), round(c.height() * k))

    def set_scale(self, k):
        self.cfg["scale"] = k
        config.save()
        if self.base:
            super().setFixedSize(round(self.base[0] * k), round(self.base[1] * k))
        self.flat_key = None
        self.last_src = None
        self.rebuild()
        if self.pinned:
            self.push()
        self.update()

    def fit_grid(self, cols=2, min_rows=1):
        """Виджет из готовых подписей (раскладка Qt): ширина — cols ячеек, высота — сколько нужно содержимому,
        округлённо вверх до целых ячеек (не меньше min_rows). Зовётся сама, когда содержимое меняется."""
        self._grid_cols, self._grid_min = cols, min_rows
        lay = self.layout()
        if lay is None:
            return
        w = grid(cols, 1)[0] + 2 * SHADOW
        lay.activate()
        need = lay.totalHeightForWidth(w) if lay.hasHeightForWidth() else lay.totalSizeHint().height()
        h = grid(1, max(min_rows, grid_rows(need - 2 * SHADOW)))[1] + 2 * SHADOW
        if (self.width(), self.height()) != (w, h):
            QWidget.setFixedSize(self, w, h)

    def event(self, e):
        if PROFILE is not None and e.type() == QEvent.Paint and self.key:  # замер: кто сколько раз и как долго рисуется
            t = time.perf_counter()
            result = super().event(e)
            rec = PROFILE.setdefault(self.key, [0, 0.0])
            rec[0] += 1
            rec[1] += time.perf_counter() - t
            return result
        if e.type() == QEvent.LayoutRequest and getattr(self, "_grid_cols", None):
            result = super().event(e)
            self.fit_grid(self._grid_cols, self._grid_min)
            return result
        # Ctrl + колесо — размер (у некоторых виджетов колесо занято своим: листать, стаканы)
        if e.type() == QEvent.Wheel and e.modifiers() & Qt.ControlModifier and self.resizable() and self.base:
            sizes = self.SIZES
            i = min(range(len(sizes)), key=lambda n: abs(sizes[n] - self.scale()))
            i = max(0, min(len(sizes) - 1, i + (1 if e.angleDelta().y() > 0 else -1)))
            if sizes[i] != self.scale():
                self.set_scale(sizes[i])
            return True
        return super().event(e)

    @staticmethod
    def seen_on_screen(card):
        for s in QGuiApplication.screens():
            seen = s.geometry().intersected(card)
            if seen.width() >= 48 and seen.height() >= 48:
                return True
        return False

    def keep_on_screen(self, save=True):
        """Виджет остался за краем экрана (отключили второй монитор, уменьшили разрешение) — его не видно
        и не достать. Вернуть на главный экран, к ближайшему краю. save=False — место в настройках не трогать:
        разрешение сменилось на время (игра), вернётся — виджет встанет обратно (restore_place)."""
        if getattr(self, "preview", False) or not self.keep_bottom or not self.placed:
            return
        card = self.card_on_screen()
        if self.seen_on_screen(card):
            return
        g = QGuiApplication.primaryScreen().availableGeometry()
        dx = max(g.left() + GAP - card.left(), 0) + min(g.right() - GAP - card.right(), 0)
        dy = max(g.top() + GAP - card.top(), 0) + min(g.bottom() - GAP - card.bottom(), 0)
        self.move(self.pos() + QPoint(dx, dy))
        if save:
            self.cfg["x"], self.cfg["y"] = self.x(), self.y()
            config.save()
        if self.pinned:
            self.push()

    def restore_place(self):
        """После смены разрешения: на сохранённое место, если оно видно на нынешних экранах; иначе — временно
        к краю, не перезаписывая сохранённое. И заново вложить в рабочий стол: слой ярлыков Проводника мог
        остаться размером с игровое разрешение — тогда виджет, утащенный за его край, пропадал."""
        if getattr(self, "preview", False) or not self.keep_bottom or not self.placed or self._drag is not None:
            return
        if "x" in self.cfg and "y" in self.cfg:
            saved = QPoint(int(self.cfg["x"]), int(self.cfg["y"]))
            if self.seen_on_screen(self.card_on_screen(saved)) and saved != self.pos():
                self.move(saved)
        self.keep_on_screen(save=False)  # до place(): его проверка края уже ничего не сдвинет и не сохранит
        if self.desktop_host is not None and self.desktop_host.attached:
            self.desktop_host.detach()
        self.last_src = None
        self.desk_glass = None
        self.place()
        if self.pinned:
            self.push()

    def center_new(self):
        """Новый виджет — в центр главного экрана (уже зная свой размер), и запомнить место."""
        if not getattr(self, "new_spot", False) or getattr(self, "preview", False):
            return
        self.new_spot = False
        g = QGuiApplication.primaryScreen().availableGeometry()
        step = 36 * (Activity.spawned % 5)  # подряд включённые — лесенкой
        Activity.spawned += 1
        x = g.center().x() - self.width() // 2 + step
        y = g.center().y() - self.height() // 2 + step
        self.move(max(g.left(), min(x, g.right() - self.width())), max(g.top(), min(y, g.bottom() - self.height())))
        self.cfg["x"], self.cfg["y"] = self.x(), self.y()
        config.save()
        if self.pinned:
            self.push()

    def showEvent(self, event):
        super().showEvent(event)
        activity._widgets = None  # список виджетов — собрать заново
        QTimer.singleShot(0, self.center_new)
        QTimer.singleShot(0, self.keep_on_screen)
        self.setup_capture()
        self.sync_topmost()
        # разворачивают из свёрнутого (значок на панели задач, Alt+Tab) — показ от самой Windows (spontaneous),
        # со своей анимацией: наше плавное появление поверх неё гасило уже показанное окно до нуля —
        # «открылось, пропало, снова открылось»
        if getattr(self, "_skip_fade", False) or self.desktop_attached() or event.spontaneous():
            self._skip_fade = False
            if event.spontaneous() and self.windowOpacity() < 1:
                self.setWindowOpacity(1.0)
            return
        self.setWindowOpacity(0)
        self.fade = QPropertyAnimation(self, b"windowOpacity", self, duration=260, startValue=0.0, endValue=1.0)
        self.fade.start()

    # ---------- стекло ----------

    def glass_theme(self):
        """Светлое/тёмное/авто стекло: своё у виджета, а если не задано — общее из каталога («Тема» внизу окна).
        Без этого виджет, появившийся после выбора темы, брал «авто» и над светлым фоном был белым, не как все."""
        return self.cfg.get("theme") or config.section("app").get("theme", "auto")

    def set_dark(self, dark):
        if dark == self.dark:
            return
        self.dark = dark
        self.setStyleSheet(STYLE.format(**glass.THEMES[dark]))
        self.theme_changed()

    def theme_changed(self):
        """Тема стекла сменилась (переопределяется)."""

    def sync_preview(self):
        """Скрытая копия для превью в каталоге: подтянуть данные из настроек (переопределяется)."""

    def _job(self):
        """Что посчитать: номер заказа, размер, тема, прошлый снимок и откуда брать картинку."""
        card = self.card()
        self.gen += 1
        app = config.section("app")
        # у живого акрила стекло сплошное (просвечивает размытое, а не резкое) — «Заливка» только у изморози
        fill = None if app.get("acrylic", True) else app.get("fill")
        blur, haze = skins.glass_params(app.get("blur"), app.get("haze"))
        # Тему сменили, пока считалось прошлое стекло: оно вернулось в старой теме и запомнило фон — следующий
        # заказ видел «фон тот же» и не пересчитывал. Поэтому снимок, посчитанный в другой теме, — не «прошлый».
        self._gen_ver = getattr(self, "_gen_ver", {})
        self._gen_ver[self.gen] = skins.version
        last = self.last_src if getattr(self, "glass_ver", None) == skins.version else None
        args = (self.gen, card.width(), card.height(), skins.theme(self.glass_theme()), last,
                (fill, blur, haze), self.theme_prev())
        if self.live:
            # масштаб виджета — как лишний «dpr»: снимаем увеличенный кусок экрана, ужимаем до обычного размера
            win, monitor = glass.window_rect(int(self.winId()))
            return args, (win, monitor, SHADOW, card.width(), card.height(), self.devicePixelRatioF() * self.scale())
        return args, glass.from_wallpaper(self.screen().geometry(), self.card_on_screen())

    def theme_prev(self):
        """С какой темы считать порог (у порога тема не дёргается, см. glass.theme_for).
        Фон меняется плавно (живые обои) — с нынешней. Скачком (окно проехало или свернулось) — с той,
        что была над таким же фоном раньше: иначе тёмное окно оставляло карточку тёмной и над светлым столом."""
        cur, last, mem = self.dark, self.lum, dict(self.theme_mem)

        def prev(lum):
            if last is None or abs(lum - last) < JUMP:
                return cur
            return mem.get(round(lum * 20))
        return prev

    @staticmethod
    def _render(args, src):
        """Сравнить с прошлым снимком и отрендерить. Окна Qt здесь не трогаем — можно в фоне."""
        gen, w, h, theme, last, (fill, blur_r, haze), prev = args
        try:
            if src is not None and changed(src, last):
                img, dark = glass.render(src, w, h, RADIUS, theme, fill, blur_r, haze, prev)
                return gen, (src, img, dark)
        except Exception as _err:
            applog.error("core.DesktopWidget._render", _err)
        return gen, None

    @staticmethod
    def _compute(args, how):
        try:
            src = glass.capture(*how) if isinstance(how, tuple) else how
        except Exception as _err:
            applog.error("core.DesktopWidget._compute", _err)
            src = None
        return DesktopWidget._render(args, src)

    def rebuild(self):
        """Заказать новое стекло в фоне. Пока прошлое считается — запомнить и заказать потом (склейка)."""
        if PROFILE is not None:
            PROFILE.setdefault("стекло " + self.key, [0, 0.0])[0] += 1
        if not self.isVisible() or self.snapping():
            return
        if self.flat_mode():
            self.update_flat()
            return
        if self.busy:
            self.pending = True
            return
        self.busy = True
        POOL.submit(self._work, *self._job())

    def setup_capture(self):
        """Живое стекло (окно скрыто от снимков экрана, видно, что под ним) или
        «видно на скриншотах всегда» (стекло из обоев). Окно пересоздаётся при смене флагов —
        поэтому зовём при каждом показе."""
        hwnd = int(self.winId())
        app = config.section("app")
        if self.desktop_attached():  # ребёнок рабочего стола не прячется от снимков — стекло из обоев
            self.live = False
            self.set_rate()
            self.last_src = None
            self.rebuild()
            return
        if self.flat_mode() or (app.get("on_screenshots") and not app.get("acrylic", True)):
            glass.include_in_capture(hwnd)
            self.live = False
        else:  # акрил — всегда живой: снимаем то, что под окном (для PrtSc окно на миг показывается само)
            self.live = glass.exclude_from_capture(hwnd)
        self.set_rate()
        self.last_src = None
        self.rebuild()

    def flat_mode(self):
        """Стекло без снимков экрана: при системном акриле (размывает сама Windows) или под живыми обоями
        (их видео просвечивает сквозь полупрозрачное окно). Сверху — наша тонировка с заливкой."""
        app = config.section("app")
        if self.desktop_attached():
            return False
        if self.keep_bottom and app.get("system_acrylic", False):
            return True
        if app.get("acrylic", True) and not self.pinned:
            return False  # свой акрил из снимка экрана — снимок теперь видит и живые обои
        return self.keep_bottom and bool(activity.wpe) and not activity.editing

    def apply_backdrop(self, dark=None):
        """Системный акрил Windows под карточкой — отдельная подложка (glass.Backdrop) ровно по скруглённой
        карточке, сразу под окном виджета. Размытие и замутнение — из настроек. Выключен, под ярлыками,
        окно скрыто — подложку убрать."""
        app = config.section("app")
        # системный акрил Windows скругляет углы только на 8 px (у карточки 26) — по умолчанию выключен
        want = self.keep_bottom and app.get("system_acrylic", False) and not self.pinned and self.isVisible() \
            and not self.isMinimized() and not self.desktop_attached()
        bd = getattr(self, "_bd", None)
        if not want:
            if bd:
                bd.hide()
            return
        if bd is None:
            bd = self._bd = glass.Backdrop()
        dark = self.dark if dark is None else dark
        bd.style(app.get("blur", glass.BLUR), app.get("haze", 50), bool(dark))
        self.follow_backdrop()

    def follow_backdrop(self):
        """Подложка — точно под карточкой и сразу под окном виджета (после любого сдвига и смены места в стопке)."""
        bd = getattr(self, "_bd", None)
        if not bd or not bd.hwnd or not self.isVisible():
            return
        hwnd = int(self.winId())
        r = wt.RECT()
        glass.user32.GetWindowRect(hwnd, ctypes.byref(r))
        k = (r.right - r.left) / max(1, self.width())  # физических пикселей на логический (с масштабом экрана)
        s = self.scale()
        c = self.card()
        bd.follow(hwnd, r.left + round(c.x() * s * k), r.top + round(c.y() * s * k),
                  round(c.width() * s * k), round(c.height() * s * k), round(RADIUS * s * k))

    def hideEvent(self, event):
        super().hideEvent(event)
        activity._widgets = None
        if getattr(self, "_bd", None):
            self._bd.hide()

    def update_flat(self):
        """Стекло-изморозь (под ярлыками и под окнами при живых обоях): считается один раз на размер и тему."""
        card = self.card()
        theme = skins.theme(self.glass_theme())
        if theme == "auto":
            screen = QGuiApplication.screenAt(self.pos()) or QGuiApplication.primaryScreen()
            dark = glass.wallpaper_is_dark(screen.geometry(), card.translated(self.pos()))
        else:
            dark = theme == "dark"
        fill = config.section("app").get("fill")
        if self.flat_key != (card.size(), dark, fill, skins.version):
            self.flat_key = (card.size(), dark, fill, skins.version)
            self.glass_img = glass.render_flat(card.width(), card.height(), RADIUS, dark, fill)
            self.shadow_img = glass.render_shadow(card.width(), card.height(), RADIUS, SHADOW, dark)
            self.set_dark(dark)
            self.update()
        self.apply_backdrop(dark)

    def snapping(self):
        """Идёт скриншот — живое стекло не снимаем (иначе снимет само себя)."""
        return self.live and time.monotonic() < activity.snap_until

    def rebuild_now(self):
        """Посчитать сразу — при перетаскивании, чтобы стекло не отставало от окна."""
        if self.isVisible() and not self.snapping():
            if self.flat_mode():  # сплошное стекло (окно настроек, изморозь) от места не зависит
                self.update_flat()
                return
            self.apply(self._compute(*self._job()))

    def _work(self, args, how):
        self._deliver(self._compute(args, how))

    def _deliver(self, result):
        """Из фонового потока — в окно (сигнал сам перейдёт в главный поток)."""
        try:
            self.glass_ready.emit(result)
        except RuntimeError:  # виджет уже удалён
            pass

    def on_glass(self, result):
        self.busy = False
        self.apply(result)
        if self.pending:
            self.pending = False
            self.rebuild()

    def apply(self, result):
        gen, payload = result
        ver = getattr(self, "_gen_ver", {}).pop(gen, None)
        for g in [g for g in getattr(self, "_gen_ver", {}) if g < gen]:
            self._gen_ver.pop(g, None)
        if gen < self.shown_gen:  # пока считалось, уже показали стекло новее
            return
        if self.flat_mode():
            # Окну со сплошным стеклом (настройки) живое стекло не нужно. Раньше при перетаскивании окна сюда
            # всё равно приходило стекло «из обоев» и подменяло сплошное: окно настроек становилось то
            # прозрачным, то матовым.
            return
        self.same = 0 if payload else self.same + 1
        self.streak = getattr(self, "streak", 0) + 1 if payload else 0  # сколько снимков подряд фон менялся
        if payload:
            self.shown_gen = gen
            self.last_src, self.glass_img, dark = payload
            self.glass_ver = ver
            if ver != skins.version:  # посчитано в старой теме — сразу заказать заново
                QTimer.singleShot(0, self.rebuild)
            # стекло над чистым рабочим столом (впереди ничего нет и уже секунду ничего не менялось) —
            # запоминаем: его покажем сразу, когда окно свернут (см. Activity.check)
            if activity.mode == "desktop" and time.monotonic() - getattr(activity, "changed_at", 0.0) > 1.0:
                self.desk_glass = payload
            self.lum = glass.luminance(self.last_src)
            self.theme_mem[round(self.lum * 20)] = dark
            card = self.card()
            if dark != self.dark or self.shadow_img is None or \
                    self.shadow_img.size() != card.size() + QSize(2 * SHADOW, 2 * SHADOW):
                self.make_shadow(card, dark)
            self.set_dark(dark)
            self.update()

    def make_shadow(self, card, dark):
        """Тень под карточкой (переопределяется: большому окну — в фоне)."""
        self.shadow_img = glass.render_shadow(card.width(), card.height(), RADIUS, SHADOW, dark)

    def set_rate(self):
        """Как часто смотреть под стекло — по тому, чем занят пользователь:
        на рабочем столе — 15 раз в секунду; в окне — как на столе, но виджеты, которые это окно закрывает,
        замирают (см. Activity.tick); поверх окон — раз в секунду; полный экран — всё замирает."""
        mode = activity.mode
        if not self.live or not self.isVisible():
            interval = None
        elif mode == "desktop":
            interval = 66  # 15 кадров в секунду, пока двигается мышь (в покое — 2 в секунду, см. tick)
        elif mode == "window" and self.on_top():
            interval = 1000
        elif mode == "window":
            # окно впереди закрывает не всех: виджеты на другом мониторе и рядом с окном видны — их стекло живое
            interval = 66
        else:
            interval = None
        if interval != self.interval:
            self.interval = interval
            self.due = 0.0  # режим сменился — сразу свежее стекло

    def check_wallpaper(self):
        # таймер есть у каждого виджета, а обои одни — проверяем не чаще раза в 4 с на всех
        now = time.monotonic()
        if now - DesktopWidget.wall_checked < 4:
            return
        DesktopWidget.wall_checked = now
        if glass.wallpaper.changed():
            for w in QApplication.topLevelWidgets():
                if isinstance(w, DesktopWidget):
                    w.last_src = None
                    w.rebuild()

    def moveEvent(self, event):
        # было два moveEvent — второй перекрывал первый, и подложка Windows не ехала за виджетом
        super().moveEvent(event)
        self._rect_cache = None  # covered() — снова спросить Windows, где окно
        self.follow_backdrop()
        # и при перетаскивании — в фоне: снимок + стекло ~10–15 мс, а мышь шлёт сотни сдвигов в секунду;
        # считать на каждом сдвиге в главном потоке — окно не поспевало за мышью и дёргалось.
        # Заказы склеиваются (rebuild: busy/pending) — стекло догоняет окно за кадр, окно едет без задержки
        self.rebuild()

    def resizeEvent(self, event):
        self.rebuild()

    def paintEvent(self, event):
        # тень, стекло и кромка меняются только с новым стеклом — склеены в одну картинку (_chrome),
        # каждый кадр это одно быстрое копирование вместо трёх смешиваний и обводки градиентом
        chrome = self._chrome()
        if chrome is not None:
            raw = QPainter(self)
            raw.drawPixmap(0, 0, chrome)
            raw.end()

        # «凝光» — мягкий рассеянный свет, который идёт за курсором (у ColorOS — за пальцем)
        if self.hover.isActive():
            p = ScaledPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            card = QRectF(self.card())
            path = QPainterPath()
            path.addRoundedRect(card, RADIUS, RADIUS)
            p.setClipPath(path)
            pos = QPointF(self.mapFromGlobal(QCursor.pos())) / self.scale()
            light = QRadialGradient(pos, 190)
            light.setColorAt(0, glass.THEMES[self.dark]["glow"])
            light.setColorAt(1, QColor(255, 255, 255, 0))
            p.fillRect(card, light)
            p.setClipping(False)
            self._rim(p, card)  # кромка — поверх света
            p.end()

    def _chrome(self):
        """Тень + стекло + кромка одной картинкой размером с окно (с масштабом и чёткостью экрана)."""
        glass_ok = self.glass_img is not None and self.glass_img.size() == self.card().size()
        card = self.card()
        if self.shadow_img is not None and type(self).make_shadow is DesktopWidget.make_shadow and \
                self.shadow_img.size() != card.size() + QSize(2 * SHADOW, 2 * SHADOW):
            # размер поменяли (фото 2×2 → 1×1) — тень сразу под новый, не ждать стекла: иначе сбоку висела
            # полоска старой тени (маленькая, считается за миллисекунды; большим окнам — свой фоновый расчёт)
            self.make_shadow(card, bool(self.dark))
        if self.shadow_img is None and not glass_ok:
            return None
        dpr = self.devicePixelRatioF()
        key = (self.glass_img.cacheKey() if glass_ok else 0, self.shadow_img.cacheKey() if self.shadow_img else 0,
               bool(self.dark), self.size().toTuple(), self.scale(), dpr, skins.version)
        if getattr(self, "_chrome_key", None) != key:
            self._chrome_key = key
            pix = QPixmap(int(self.width() * dpr), int(self.height() * dpr))
            pix.setDevicePixelRatio(dpr)
            pix.fill(Qt.transparent)
            p = QPainter(pix)
            k = self.scale()
            if k != 1:
                p.scale(k, k)
            p.setRenderHint(QPainter.Antialiasing)
            card = QRectF(self.card())
            if self.shadow_img:
                p.drawImage(0, 0, self.shadow_img)
            self._glow(p, card)
            if glass_ok:
                p.drawImage(card.topLeft(), self.glass_img)
            self._rim(p, card)
            p.end()
            self._chrome_pix = pix
        return self._chrome_pix

    def _rim(self, p, card):
        # тонкая световая обводка (光感描边): чуть ярче сверху и снизу, тоньше по бокам; цвет — от темы оформления
        rim, width = skins.rim_pen(card, self.dark)
        p.setPen(QPen(rim, width))
        p.setBrush(Qt.NoBrush)
        inset = width / 2
        p.drawRoundedRect(card.adjusted(inset, inset, -inset, -inset), RADIUS, RADIUS)

    def _glow(self, p, card):
        """Ореол вокруг карточки (тема «Неон»): кромка, размытая в мягкое свечение, в поле тени.
        От фона не зависит — считается раз на размер карточки и тему, дальше копируется картинка."""
        cols = skins.glow_colors()
        if cols is None:
            return
        res = p.device().devicePixelRatioF() * p.transform().m11()
        key = (round(card.width()), round(card.height()), skins.version, round(res, 3))
        img = _GLOW_CACHE.get(key)
        M = SHADOW  # ореол помещается в поле тени вокруг карточки
        if img is None:
            shape = QPainterPath()
            shape.addRoundedRect(QRectF(0, 0, card.width(), card.height()), RADIUS, RADIUS)
            img = skins.glow_image(shape, card.width(), card.height(), M, cols[0], cols[1], res=res)
            if len(_GLOW_CACHE) > 64:
                _GLOW_CACHE.clear()
            _GLOW_CACHE[key] = img
        p.save()
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawImage(QRectF(card.x() - M, card.y() - M, card.width() + 2 * M, card.height() + 2 * M), img)
        p.restore()

    def changeEvent(self, event):
        # виджет — часть рабочего стола: «свернуть все» (Win+D и т.п.) не должно его сворачивать
        if event.type() == QEvent.WindowStateChange and self.keep_bottom and self.isMinimized():
            QTimer.singleShot(0, self.showNormal)
        super().changeEvent(event)

    def enterEvent(self, event):
        self.hover.start()

    def leaveEvent(self, event):
        self.hover.stop()
        self.update()

    # ---------- мышь и меню ----------

    def click(self, pos):
        """Клик по своей кнопке внутри виджета (переопределяется). True — клик съеден, окно не тащим."""
        return False

    def tap(self, pos):
        """Короткий клик без перетаскивания (переопределяется): для виджетов, где кнопка — весь виджет.
        Зажал и потянул — виджет едет, просто клик — срабатывает tap."""

    def double_click(self):
        """Двойной клик по виджету (переопределяется): открыть что-то по теме."""

    def swiping(self):
        """Листать свайпом (переопределяется): True — тянут вбок — swipe_move/swipe_end, вверх-вниз — виджет едет."""
        return False

    def swipe_move(self, dx):
        """Палец (мышь) ведёт вбок: dx — сдвиг от нажатия, px."""

    def swipe_end(self, dx):
        """Отпустили после свайпа вбок."""

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.click(event.position() / self.scale()):  # кнопки виджета — в его обычных координатах
                return
            self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._press = (event.globalPosition().toPoint(), event.position() / self.scale())
            self._swipe = None
            self._decide = not activity.editing and self.swiping()  # куда тянут — решим по первым пикселям
            self._press_at = time.monotonic()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.double_click()

    def mouseMoveEvent(self, event):
        if getattr(self, "_decide", False) and event.buttons() & Qt.LeftButton:
            d = event.globalPosition().toPoint() - self._press[0]
            if max(abs(d.x()), abs(d.y())) < 8:
                return  # ещё не понятно, куда тянут
            self._decide = False
            held = time.monotonic() - getattr(self, "_press_at", 0.0) >= HOLD_TO_MOVE
            if abs(d.x()) > abs(d.y()) and not held:
                self._swipe, self._drag = self._press[0], None  # вбок — листаем, виджет стоит
            # подержал и потом потянул — двигаем виджет в любую сторону, как на телефоне
        if getattr(self, "_swipe", None) is not None:
            self.swipe_move((event.globalPosition().toPoint() - self._swipe).x())
            return
        if self._drag is not None and event.buttons() & Qt.LeftButton:
            if config.section("app").get("locked", False) and not activity.editing:
                return  # «Закрепить» в каталоге — виджет стоит на месте
            pos = event.globalPosition().toPoint() - self._drag
            self.move(pos if event.modifiers() & Qt.AltModifier else self.snap(pos))  # Alt — без магнита

    def snap(self, pos):
        """Магнит: край карточки липнет к краю экрана и к соседним виджетам (с ровным зазором)."""
        if not config.section("app").get("snap", True):  # «Магнит» выключен в каталоге
            return pos
        # два прохода: прилип сбоку — и уже с этого места выровнять верх/низ по соседу (иначе отпустил в 13–14 px
        # от соседа — встал вплотную, но на пару точек выше или ниже него)
        first = self._snap_once(pos)
        return self._snap_once(first) if first != pos else first

    def _snap_once(self, pos):
        card = self.card_on_screen(pos)
        screen = QGuiApplication.screenAt(card.center()) or QGuiApplication.primaryScreen()
        g = screen.availableGeometry()
        xs = [g.left() + GAP - card.left(), g.right() - GAP - card.right()]
        ys = [g.top() + GAP - card.top(), g.bottom() - GAP - card.bottom()]
        for w in activity.widgets():
            if w is self or not w.keep_bottom or not w.isVisible():
                continue
            o = w.card_on_screen()
            if o.top() - SNAP_DIST < card.bottom() and card.top() < o.bottom() + SNAP_DIST:  # рядом по высоте
                xs += [o.right() + GAP - card.left(), o.left() - GAP - card.right(),
                       o.left() - card.left(), o.right() - card.right()]
            if o.left() - SNAP_DIST < card.right() and card.left() < o.right() + SNAP_DIST:  # рядом по ширине
                ys += [o.bottom() + GAP - card.top(), o.top() - GAP - card.bottom(),
                       o.top() - card.top(), o.bottom() - card.bottom()]
        dx, dy = min(xs, key=abs), min(ys, key=abs)
        return pos + QPoint(dx if abs(dx) <= SNAP_DIST else 0, dy if abs(dy) <= SNAP_DIST else 0)

    def mouseReleaseEvent(self, event):
        self._decide = False
        if getattr(self, "_swipe", None) is not None:
            dx = (event.globalPosition().toPoint() - self._swipe).x()
            self._swipe = None
            self.swipe_end(dx)
            return
        if self._drag is not None:
            self._drag = None
            start, local = getattr(self, "_press", (None, None))
            if start is not None and (event.globalPosition().toPoint() - start).manhattanLength() < 5:
                self.tap(local)  # не тащили — это нажатие
                return
            self.cfg["x"], self.cfg["y"] = self.x(), self.y()
            config.save()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        self.add_shapes(menu)
        if self.resizable() and self.base:
            sizes = menu.addMenu(tr("Размер"))
            for k in self.SIZES:
                a = sizes.addAction(f"{k * 100:.0f}%", lambda k=k: self.set_scale(k))
                a.setCheckable(True)
                a.setChecked(abs(self.scale() - k) < 0.01)
            sizes.addSeparator()
            sizes.addAction(tr("Ctrl + колесо мыши — плавнее")).setEnabled(False)
        self.add_actions(menu)
        skin_menu(menu)
        themes = menu.addMenu(tr("Стекло"))
        for name, text in (("auto", tr("Авто (по обоям)")), ("light", tr("Светлое")), ("dark", tr("Тёмное"))):
            a = themes.addAction(text, lambda n=name: self.set_theme(n))
            a.setCheckable(True)
            a.setChecked(self.glass_theme() == name)
        menu.addAction(tr("Скрыть"), self.hide_by_user)
        if self.copy_of and activity.copies:  # копия фото / гифки — можно убрать совсем
            menu.addAction(tr("Удалить этот виджет"), lambda: activity.copies.remove_copy(self.key))
        menu.exec(event.globalPos())

    def hide_by_user(self):
        """«Скрыть» из меню — решение пользователя, запоминаем. Простое закрытие окна (выключение Windows) — нет."""
        self.cfg["visible"] = False
        config.save()
        self.close()

    def add_actions(self, menu):
        """Свои пункты меню виджета (переопределяется)."""

    # ---------- вид (размер и раскладка) ----------

    SHAPES = {}  # имя -> (подпись в меню, (ширина, высота) карточки); первый — по умолчанию

    def shape(self):
        name = self.cfg.get("shape")
        return name if name in self.SHAPES else next(iter(self.SHAPES), "")

    def apply_shape(self):
        if self.SHAPES:
            w, h = self.SHAPES[self.shape()][1]
            self.setFixedSize(w + 2 * SHADOW, h + 2 * SHADOW)

    def add_shapes(self, menu):
        if len(self.SHAPES) < 2:
            return
        sub = menu.addMenu(tr("Вид"))
        for name, (text, _) in self.SHAPES.items():
            a = sub.addAction(text, lambda n=name: self.set_shape(n))
            a.setCheckable(True)
            a.setChecked(self.shape() == name)

    def set_shape(self, name):
        self.cfg["shape"] = name
        config.save()
        self.apply_shape()
        self.flat_key = None
        if self.pinned:
            self.push()
        self.update()

    def set_theme(self, name):
        self.cfg["theme"] = name
        config.save()
        self.last_src = None
        self.rebuild()

    def closeEvent(self, event):
        # Закрыть виджет «снаружи» (Alt+F4, когда фокус на виджете, особенно внутри рабочего стола) — нельзя:
        # виджет пропадал без следа (в журнале — «закрыт виджет analog»). Выключают его в каталоге или «Скрыть».
        if self.keep_bottom and event.spontaneous() and not QApplication.closingDown()                 and not getattr(self, "preview", False):
            event.ignore()
            return
        self.placed = False
        activity._widgets = None
        if getattr(self, "_bd", None):
            self._bd.destroy()
            self._bd = None
        self.push_timer.stop()
        if self.pinned:
            self.pinned.destroy()
            self.pinned = None
        if self.on_closed:
            self.on_closed(self)
        super().closeEvent(event)
