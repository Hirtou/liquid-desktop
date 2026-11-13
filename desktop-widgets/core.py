"""Общее для всех виджетов: настройки (config.json) и окно-виджет на рабочем столе."""
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

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(ROOT, "config.json")

SHADOW = 18   # поле под тень вокруг карточки
RADIUS = 26   # скругление карточки

# снимок экрана и рендер стекла — в фоне, чтобы окна не подтормаживали
POOL = ThreadPoolExecutor(max_workers=4)
SNAP_SECONDS = 3.0  # столько виджеты видны после клавиши скриншота
SNAP_DIST = 14      # магнит при перетаскивании: с какого расстояния липнет, px
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
        os.replace(tmp, CONFIG_PATH)


config = Config()


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
        self.checks = 0
        self.last_check = 0.0
        # сколько кадров в работе на каждом мониторе: новый не снимаем, пока старый не готов
        self.inflight = {}
        self.cover = None  # окно впереди (физ. пиксели), если пользователь в окне
        self.fs_monitor = None  # монитор игры на весь экран
        self.on_game = None  # началась / закончилась игра на весь экран: on_game(True/False) — подпись в трее

    def start(self):
        if self.timer is None:
            self.wpe = glass.live_wallpaper_running()
            self.under_icons = config.section("app").get("under_icons", False)
            self.hook = glass.watch_screenshot_keys(self.on_screenshot)
            # точный таймер: обычный в Windows шагает по ~15.6 мс, и 33 мс превращаются в 47
            self.timer = QTimer(interval=33, timeout=self.tick, timerType=Qt.PreciseTimer)
            self.timer.start()

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
        # сам такт: 30 раз в секунду, пока двигается мышь; в покое хватает 5; в игре на весь экран — 4
        rate = 250 if self.mode == "fullscreen" else 200 if idle else 33
        if self.timer.interval() != rate:
            self.timer.setInterval(rate)
        groups = {}
        cur = wt.POINT()  # где мышь (физические пиксели): виджетам на другом мониторе она ничего не меняет
        glass.user32.GetCursorPos(ctypes.byref(cur))
        # окно впереди (физ. пиксели): виджеты, которые оно закрывает целиком, не видны — их стекло не снимаем
        cover = glass.cover_rect(glass.user32.GetForegroundWindow()) if self.mode == "window" else None
        for w in self.widgets():
            # кому пора — и заодно тем, кому скоро (до 40% интервала, не больше 0.2 с): один снимок монитора
            # на всех, а не по одному
            if w.interval is None or not w.isVisible() or w.isMinimized() \
                    or now < w.due - min(0.2, w.interval * 0.0004):
                continue
            win, monitor = glass.window_rect(int(w.winId()))
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
        except Exception:
            traceback.print_exc()
            shots = [None] * len(items)
        try:
            for (w, args, _), src in zip(items, shots):
                w._deliver(DesktopWidget._render(args, src))
        finally:
            activity.inflight[monitor] -= 1

    def check(self):
        self.checks += 1
        if self.checks % 20 == 0:  # раз в ~5 с: не запустили/закрыли живые обои?
            wpe = glass.live_wallpaper_running()
            if wpe != self.wpe:
                self.wpe = wpe
                for w in self.widgets():
                    if w.placed:
                        w.place()
        mode = glass.foreground()
        refresh = False
        if mode is not None and mode != self.mode:  # панель задач не меняет режим
            game = (mode == "fullscreen") != (self.mode == "fullscreen")
            self.mode = mode
            refresh = True
            for w in self.widgets():
                w.set_rate()
            if game and self.on_game:
                self.on_game(mode == "fullscreen")
        if mode == "fullscreen":  # на каком мониторе игра (её могли перетащить — смотрим каждый раз, это дёшево)
            self.fs_monitor = glass.window_rect(glass.user32.GetForegroundWindow())[1]
        # окно впереди: виджеты, которые оно закрывает целиком, анимацию не рисуют (см. covered)
        cover = glass.cover_rect(glass.user32.GetForegroundWindow()) if self.mode == "window" else None
        if cover != self.cover or refresh:
            self.cover = cover
            for w in self.widgets():  # открылись — сразу свежий кадр и стекло, а не то, что было до окна
                if w.isVisible():
                    w.due, w.same = 0.0, 0
                    w.update()

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
            return self.fs_monitor is None or glass.window_rect(int(w.winId()))[1] == self.fs_monitor
        if self.cover is None:
            return False
        return glass.hides(self.cover, glass.window_rect(int(w.winId()))[0], SHADOW * w.devicePixelRatioF())

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


class DesktopWidget(QWidget):
    """Окно без рамки на рабочем столе: карточка из «жидкого акрила», таскается мышью."""

    key = ""
    title = ""
    description = ""
    keep_bottom = True  # держать под окнами (у окна программы — нет)
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
            # первый раз — справа (ярлыки обычно слева), лесенкой, чтобы не налезали друг на друга
            g = QGuiApplication.primaryScreen().availableGeometry()
            n = sum(1 for v in config.data.values() if isinstance(v, dict) and "x" in v)
            self.cfg["x"], self.cfg["y"] = g.right() - 420 - (n % 3) * 60, g.top() + 40 + (n % 5) * 70
        self.move(self.cfg["x"], self.cfg["y"])

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
        self.push_timer = QTimer(self, interval=1000, timeout=self.push)

    # ---------- окно ----------

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
        if activity.editing or not activity.under_icons or activity.wpe:
            self.unpin()
        else:
            self.pin()

    def nativeEvent(self, event_type, message):
        # не поверх окон: что бы ни делали (клик, перетаскивание), окно остаётся в самом низу
        if self.keep_bottom and not activity.editing and not self.pinned:
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
        if not self.isVisible() or self.pinned:
            return
        # -1 — поверх всех, -2 — снять «поверх всех»; дальше nativeEvent сам опустит виджет к рабочему столу
        glass.user32.SetWindowPos(int(self.winId()), wt.HWND(-1 if self.on_top() else -2), 0, 0, 0, 0,
                                  0x0001 | 0x0002 | 0x0010)  # без сдвига, размера и активации

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

    def showEvent(self, event):
        super().showEvent(event)
        activity._widgets = None  # список виджетов — собрать заново
        self.setup_capture()
        self.sync_topmost()
        self.setWindowOpacity(0)
        self.fade = QPropertyAnimation(self, b"windowOpacity", self, duration=260, startValue=0.0, endValue=1.0)
        self.fade.start()

    # ---------- стекло ----------

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
        args = (self.gen, card.width(), card.height(), self.cfg.get("theme", "auto"), self.last_src,
                (fill, app.get("blur"), app.get("haze")), self.theme_prev())
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
        except Exception:
            traceback.print_exc()
        return gen, None

    @staticmethod
    def _compute(args, how):
        try:
            src = glass.capture(*how) if isinstance(how, tuple) else how
        except Exception:
            traceback.print_exc()
            src = None
        return DesktopWidget._render(args, src)

    def rebuild(self):
        """Заказать новое стекло в фоне. Пока прошлое считается — запомнить и заказать потом (склейка)."""
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
            and not self.isMinimized()
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
        theme = self.cfg.get("theme", "auto")
        if theme == "auto":
            screen = QGuiApplication.screenAt(self.pos()) or QGuiApplication.primaryScreen()
            dark = glass.wallpaper_is_dark(screen.geometry(), card.translated(self.pos()))
        else:
            dark = theme == "dark"
        fill = config.section("app").get("fill")
        if self.flat_key != (card.size(), dark, fill):
            self.flat_key = (card.size(), dark, fill)
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
        if gen < self.shown_gen:  # пока считалось, уже показали стекло новее
            return
        self.same = 0 if payload else self.same + 1
        if payload:
            self.shown_gen = gen
            self.last_src, self.glass_img, dark = payload
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
        self.follow_backdrop()
        if self._drag is not None:
            self.rebuild_now()
        else:
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
        if self.shadow_img is None and not glass_ok:
            return None
        dpr = self.devicePixelRatioF()
        key = (self.glass_img.cacheKey() if glass_ok else 0, self.shadow_img.cacheKey() if self.shadow_img else 0,
               bool(self.dark), self.size().toTuple(), self.scale(), dpr)
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
            if glass_ok:
                p.drawImage(card.topLeft(), self.glass_img)
            self._rim(p, card)
            p.end()
            self._chrome_pix = pix
        return self._chrome_pix

    def _rim(self, p, card):
        # тонкая световая обводка (光感描边): чуть ярче сверху и снизу, тоньше по бокам
        rim = QLinearGradient(card.topLeft(), card.bottomLeft())
        a = 0.55 if self.dark else 1.0
        rim.setColorAt(0, QColor(255, 255, 255, int(150 * a)))
        rim.setColorAt(0.5, QColor(255, 255, 255, int(45 * a)))
        rim.setColorAt(1, QColor(255, 255, 255, int(130 * a)))
        p.setPen(QPen(rim, 1.0))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(card.adjusted(0.5, 0.5, -0.5, -0.5), RADIUS, RADIUS)

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

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.click(event.position() / self.scale()):  # кнопки виджета — в его обычных координатах
                return
            self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._press = (event.globalPosition().toPoint(), event.position() / self.scale())

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.double_click()

    def mouseMoveEvent(self, event):
        if self._drag is not None and event.buttons() & Qt.LeftButton:
            pos = event.globalPosition().toPoint() - self._drag
            self.move(pos if event.modifiers() & Qt.AltModifier else self.snap(pos))  # Alt — без магнита

    def snap(self, pos):
        """Магнит: край карточки липнет к краю экрана и к соседним виджетам (с ровным зазором)."""
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
        themes = menu.addMenu(tr("Стекло"))
        for name, text in (("auto", tr("Авто (по обоям)")), ("light", tr("Светлое")), ("dark", tr("Тёмное"))):
            a = themes.addAction(text, lambda n=name: self.set_theme(n))
            a.setCheckable(True)
            a.setChecked(self.cfg.get("theme", "auto") == name)
        menu.addAction(tr("Скрыть"), self.hide_by_user)
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
