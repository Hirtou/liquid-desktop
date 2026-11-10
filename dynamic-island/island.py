"""Динамический остров — как «Жидкое облако» в ColorOS 17: капсула из тёмного стекла вверху по центру главного экрана.

Пока ничего не происходит, её нет. Появляется, когда что-то идёт: музыка, таймер, помидор; на пару секунд — громкость, «скопировано», Caps Lock, смена устройства звука.
Наведи мышь (или кликни) — перетекает в карточку с кнопками. Колесо над островом — громкость.
Сменился трек, таймер дозвенел, помидор готов — раскрывается сама.
Два дела сразу — второе отделяется каплей справа (клик по ней — поменять местами). В игре на весь экран прячется.

Как в ColorOS 17: стекло размывает то, что под ним; по кромке свет (ярче снизу); вокруг — свечение цветом дела,
при касании вспыхивает; по нажатию расходится волна; по прогрессу музыки бежит свет.
Движение — на пружинах: ширина и высота догоняют цель по-разному, капля отрывается с перемычкой.
"""
import lang
from lang import tr
import ctypes
import math
import os
import sys
import threading
import time
import winsound
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, QPointF, QProcess, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                           QRadialGradient)
from PySide6.QtWidgets import QApplication, QMenu, QWidget

import screen
from bridge import (Audio, focus_cfg, focus_left, focus_length, focus_today, settings, timer_cfg, timer_left,
                    widgets)
from media import Media, YT_MUSIC_URL, accent, glyph, toggle_glyph

POOL = ThreadPoolExecutor(max_workers=1)
WIN_W, WIN_H = 520, 200  # окно с запасом под самую большую карточку и свечение; пустое место пропускает мышь
TOP = 8                  # отступ капсулы от верха экрана
H = 36                   # высота капсулы
GAP = 8                  # между капсулой и каплей второго дела
SNAP_SECONDS = 3.0       # после клавиши скриншота остров виден снимкам
FG = QColor("#f4f4f7")          # текст; светлая тема меняет палитру (set_palette)
DIM = QColor(244, 244, 247, 135)
INV = QColor("#0a0a0e")         # значок на светлой круглой кнопке (⏯)
DARK = True

# стекло по умолчанию — как у виджетов: акрил, размытие 6, замутнение 50, заливка 62, тёмная тема
LOOK_DEFAULT = {"acrylic": True, "blur": 6, "haze": 50, "fill": 62, "theme": "dark"}
TO_LIGHT, TO_DARK = 0.40, 0.34  # авто: фон светлее — светлая тема, темнее — тёмная (между — как была)


def set_palette(dark):
    global FG, DIM, INV, DARK
    DARK = dark
    if dark:
        FG, DIM, INV = QColor("#f4f4f7"), QColor(244, 244, 247, 135), QColor("#0a0a0e")
    else:
        FG, DIM, INV = QColor("#151517"), QColor(21, 21, 23, 140), QColor("#f6f6f8")


def soft(a):
    """Полупрозрачная подложка (дорожка ползунка, кнопка): белая на тёмном стекле, чёрная на светлом."""
    return QColor(255, 255, 255, a) if DARK else QColor(0, 0, 0, int(a * 0.8))
ORANGE, RED, GREEN, YELLOW = QColor("#ff9f0a"), QColor("#ff453a"), QColor("#30d158"), QColor("#ffd60a")
TOMATO, BLUE = QColor("#ff6b5a"), QColor("#4c8dff")

# размер капсулы: (дело, раскрыта) -> (ширина, высота)
SIZES = {("music", False): (236, H), ("music", True): (384, 156), ("music", "mini"): (372, H),
         ("timer", False): (164, H), ("timer", True): (364, 100),
         ("focus", False): (172, H), ("focus", True): (364, 100)}
# короткие сообщения: ширина; не раскрываются
TOASTS = {"volume": 270, "clip": 300, "caps": 196, "device": 290, "island": 260, "weather": 300}
HOTKEY_ID = 1


FONT_K = 1.0  # размер текста (настройка «Размер текста», 80–140%)
_fonts = {}


def font(size, family="Segoe UI Semibold"):
    """Шрифт нужного размера с учётом настройки; одинаковые не создаём заново каждый кадр."""
    key = (size, family, FONT_K)
    f = _fonts.get(key)
    if f is None:
        f = _fonts[key] = QFont(family)
        f.setPixelSize(max(6, round(size * FONT_K)))
    return f


def set_font_scale(k):
    global FONT_K
    FONT_K = max(0.8, min(1.4, k))
    _fonts.clear()


def mmss(sec):
    sec = max(0, int(math.ceil(sec)))
    h, rest = divmod(sec, 3600)
    return f"{h}:{rest // 60:02d}:{rest % 60:02d}" if h else f"{rest // 60}:{rest % 60:02d}"


def ease(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def with_alpha(color, a):
    c = QColor(color)
    c.setAlphaF(max(0.0, min(1.0, a)))
    return c


def elide(text, f, w):
    return QFontMetricsF(f).elidedText(text, Qt.ElideRight, w)


class Spring:
    """Пружина: капсула растягивается и мягко садится на место, как в ColorOS.
    zeta — затухание: 1 — без перелёта, меньше — чуть «отыгрывает»; жёсткость k можно менять на ходу."""

    def __init__(self, value, k=300.0, zeta=0.86):
        self.x = self.target = float(value)
        self.v = 0.0
        self.zeta = zeta
        self.k = k

    @property
    def c(self):
        return 2 * self.zeta * math.sqrt(self.k)

    def set(self, target):
        self.target = float(target)

    def jump(self, value):
        self.x = self.target = float(value)
        self.v = 0.0

    def step(self, dt):
        """Шаг; False — уже на месте."""
        if self.x == self.target and self.v == 0:
            return False
        n = max(1, math.ceil(dt / 0.004))  # мелкие шаги — движение ровное при любом такте
        c = self.c
        for _ in range(n):
            a = self.k * (self.target - self.x) - c * self.v
            self.v += a * dt / n
            self.x += self.v * dt / n
        if abs(self.target - self.x) < 0.02 and abs(self.v) < 0.3:
            self.x, self.v = self.target, 0.0
        return True


class VSync(QObject):
    """Фоновый поток ждёт следующий кадр монитора (DwmFlush) и зовёт главный поток — анимация кадр в кадр
    с монитором (180 Гц — каждые 5.6 мс). Работает только пока капсула движется; кадр не готов — новый не шлём."""

    tick = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.running = False
        self.pending = False
        self.wake = threading.Event()
        self.dwm = ctypes.WinDLL("dwmapi")
        threading.Thread(target=self.loop, daemon=True).start()

    def start(self):
        self.running = True
        self.wake.set()

    def stop(self):
        self.running = False
        self.wake.clear()

    def loop(self):
        while True:
            self.wake.wait()
            t = time.perf_counter()
            if self.dwm.DwmFlush() != 0 or time.perf_counter() - t < 0.001:
                time.sleep(0.005)  # композиция выключена — хотя бы ~200 кадров/с по часам
            if self.running and not self.pending:
                self.pending = True
                try:
                    self.tick.emit()
                except RuntimeError:
                    return


class Island(QWidget):
    bg_ready = Signal(object)

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setWindowTitle(tr("Динамический остров"))
        hz = QApplication.primaryScreen().refreshRate() or 60
        self.frame = max(5, round(1000 / hz))  # мс на кадр движения: 180 Гц — 6 мс, каждый кадр монитора свой
        self.w, self.h = Spring(H, 300, 0.84), Spring(H, 240, 0.86)
        self.bubble = Spring(0, 220, 0.72)    # 0..1 — капля второго дела (чуть перелетает — «отрывается»)
        self.want_bubble = False              # второе дело есть — капля выйдет, когда капсула свёрнута
        self.alpha = Spring(0, 200, 1.0)      # появление / исчезновение
        self.glow = Spring(0, 120, 1.0)       # свечения вокруг больше нет; держим, чтобы не трогать логику «зовёт»
        self.flash = 0.0                      # вспышка при касании, гаснет сама
        self.ripples = []                     # волны: (центр, когда, цвет)
        self.view = None                      # (дело, раскрыта) — что нарисовано
        self.old_view = None                  # прошлый вид — растворяется, пока проявляется новый
        self.fade = 1.0
        self.music = None
        self.cover_key = None
        self.color = None
        self.last_play = 0.0
        self.paused_at = None
        self.done_seen = None
        self.focus_prev = None
        self.focus_paused_at = None
        self.focus_ready_until = 0.0
        self.peek_kind, self.peek_until = None, 0.0
        self.mini_until = 0.0                 # до когда показывать «сменился трек» (капсула с названием)
        self.hover = False
        self.pinned = None
        self.items = []                       # дела по важности: [(дело, состояние), ...]
        self.buttons = {}
        self.bars = {}                        # ползунки: имя -> полоска (перемотка, громкость)
        self.drag, self.drag_value = None, 0.0  # какой ползунок тянут и куда (0..1)
        self.bubble_rect = QRectF()
        self.last_step = time.monotonic()
        self.bg = None                        # размытое то, что под островом
        self.bg_busy = False
        self.look = {}                        # настройки стекла сейчас (refresh_look)
        self.auto_dark = True                 # авто-тема: тёмная ли по фону под островом
        self.bg_gen = 0                       # номер снимка под островом (для кэша стекла)
        self.snap_until = 0.0
        self.toast = None                     # короткое сообщение: {"kind", "until", ...}
        self.audio = Audio()
        self.vol = self.audio.read()
        self.audio_checked = time.monotonic()
        self.caps = screen.caps_lock()
        self.started = time.monotonic()
        self.weather_key = None
        self.bg_ready.connect(self.on_bg)
        QApplication.clipboard().dataChanged.connect(self.on_clip)
        Media.get().changed.connect(self.on_media)
        self.hook = screen.watch_screenshot_keys(self.on_screenshot)
        self.poller = QTimer(self, interval=250, timeout=self.poll)
        self.poller.start()
        self.bg_timer = QTimer(self, interval=700, timeout=self.grab_bg)
        # окна открылись/закрылись под островом — стекло сразу, и ещё раз после анимации окна
        self.bg_again, self.bg_kicked = False, 0.0
        self.bg_follow0 = QTimer(self, singleShot=True, interval=50, timeout=self.grab_bg)  # окно успело нарисоваться
        self.bg_follow1 = QTimer(self, singleShot=True, interval=150, timeout=self.grab_bg)
        self.bg_follow2 = QTimer(self, singleShot=True, interval=420, timeout=self.grab_bg)
        self.win_hooks = []  # подписка на окна — только пока остров виден и с акрилом (update_hooks)
        self.anim = QTimer(self, interval=self.frame, timeout=self.step, timerType=Qt.PreciseTimer)
        self.vsync = VSync(self)
        self.vsync.tick.connect(self.on_vsync)
        self.enter_timer = QTimer(self, singleShot=True, interval=120, timeout=lambda: self.set_hover(True))
        self.leave_timer = QTimer(self, singleShot=True, interval=450, timeout=lambda: self.set_hover(False))
        self.anim.setInterval(self.frame)
        self.place()
        QApplication.primaryScreen().geometryChanged.connect(lambda _: self.place())
        # горячая клавиша «спрятать / вернуть» (в config.json: "hotkey", например "ctrl+alt+i" или "win+shift+f9")
        self.hotkey = settings.get("hotkey", "ctrl+alt+i")
        self.hotkey_ok = screen.register_hotkey(int(self.winId()), HOTKEY_ID, self.hotkey)
        if not self.hotkey_ok:
            print(f"горячая клавиша {self.hotkey} не назначена: занята другой программой или не разобрана",
                  file=sys.stderr)
        self.refresh_look(force=True)  # стекло, тема, размер текста — до первого показа
        self.warm_up()
        self.poll()

    def nativeEvent(self, event_type, message):
        if event_type == b"windows_generic_MSG" and screen.is_hotkey(message, HOTKEY_ID):
            self.toggle()
            return True, 0
        return False, 0

    def open_settings(self):
        from settings_window import SettingsWindow
        if getattr(self, "settings_win", None) is None:
            self.settings_win = SettingsWindow(self)
        self.settings_win.open()

    def toggle(self):
        """Горячая клавиша: спрятать остров или вернуть (вернули — коротко «Остров включён»)."""
        on = not self.enabled()
        self.set_enabled(on)
        if on:
            self.show_toast("island", 1.4)

    def place(self):
        g = QApplication.primaryScreen().geometry()
        self.setGeometry(g.x() + (g.width() - WIN_W) // 2, g.y(), WIN_W, WIN_H)

    def showEvent(self, event):
        super().showEvent(event)
        screen.exclude_from_capture(int(self.winId()))  # сами в свой снимок не попадаем — видно, что под нами
        self.grab_bg()
        if self.look["acrylic"]:
            self.bg_timer.start()
        self.update_hooks()

    def update_hooks(self):
        """Следить за окнами нужно только живому стеклу: остров виден и акрил включён; иначе — отписаться."""
        want = self.isVisible() and bool(self.look.get("acrylic"))
        if want and not self.win_hooks:
            self.win_hooks = screen.watch_windows(self.on_window)
        elif not want and self.win_hooks:
            screen.unwatch_windows(self.win_hooks)
            self.win_hooks = []

    def hideEvent(self, event):
        self.bg_timer.stop()
        self.bg = None
        QTimer.singleShot(0, self.update_hooks)

    def enabled(self):
        return settings.get("enabled", True)

    def wanted_look(self):
        """Настройки стекла: как у виджетов (их раздел «app», меняется в каталоге) или свои (окно настроек)."""
        if settings.get("follow_widgets", True):
            app = widgets.section("app")
            src = {k: app.get(k, v) for k, v in LOOK_DEFAULT.items()}
        else:
            own = settings.get("look", {})
            src = {k: own.get(k, v) for k, v in LOOK_DEFAULT.items()}
        return src

    def warm_up(self):
        """Один раз нарисовать невидимо все шрифты острова: иначе первое раскрытие ждёт загрузки шрифтов (~25 мс —
        заметный рывок). Зовём при запуске и при смене размера текста."""
        img = QImage(64, 32, QImage.Format_ARGB32_Premultiplied)
        img.fill(0)
        p = QPainter(img)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        sample = tr("АБВГДЕЖЗИКЛМНОПРСТУФХЦЧШЩЭЮЯабвгдежзиклмнопрстуфхцчшщыьэюя ABCxyz 0123456789:—·…%+")
        for size, fam in ((11, "Bahnschrift"), (12, "Segoe UI"), (13, "Segoe UI Semibold"), (15, "Segoe UI Semibold"),
                          (17, "Segoe UI Semibold"), (13, "Bahnschrift"), (13, "Bahnschrift SemiBold"),
                          (14, "Bahnschrift SemiBold"), (17, "Bahnschrift SemiBold"), (24, "Bahnschrift SemiBold"),
                          (26, "Bahnschrift SemiBold"), (34, "Bahnschrift SemiBold")):
            p.setFont(font(size, fam))
            p.drawText(0, 20, sample)
        p.end()

    def refresh_look(self, force=False):
        k = max(80, min(140, int(settings.get("font_scale", 100)))) / 100
        if k != FONT_K:  # размер текста поменяли в настройках
            set_font_scale(k)
            self.warm_up()
            force = True
            if self.view is not None:
                QTimer.singleShot(0, self.retarget)  # капсула под новый размер — плавно, пружиной
        look = self.wanted_look()
        dark = look["theme"] == "dark" if look["theme"] in ("dark", "light") else self.auto_dark
        if not force and look == self.look and dark == DARK:
            return
        acrylic_was = self.look.get("acrylic") if self.look else None
        self.look = look
        set_palette(dark)
        self._chrome_key = None
        if look["acrylic"] != acrylic_was and self.isVisible():
            if look["acrylic"]:
                self.bg_timer.start()
                self.grab_bg()
            else:  # без акрила экран не снимаем вовсе — дешевле
                self.bg_timer.stop()
                self.bg = None
        elif look["acrylic"] and self.isVisible():
            self.grab_bg()  # новое размытие — сразу
        self.update_hooks()
        self.repaint_area()

    def set_enabled(self, on):
        settings.set("enabled", bool(on))
        self.poll()

    # ---------- стекло и скриншоты ----------

    def on_screenshot(self):
        """PrtSc / Win+Shift+S: на миг показаться снимку (обычно нас в снимках нет — так стекло видит, что под ним)."""
        self.snap_until = time.monotonic() + SNAP_SECONDS
        if self.isVisible():
            screen.include_in_capture(int(self.winId()))
        QTimer.singleShot(int(SNAP_SECONDS * 1000), self.after_screenshot)

    def after_screenshot(self):
        if time.monotonic() < self.snap_until - 0.05:  # нажали ещё раз — ждём дальше
            return
        if self.isVisible():
            screen.exclude_from_capture(int(self.winId()))

    def grab_bg(self):
        look = self.look
        radius = round(max(0, min(10, look["blur"])) / 3)  # 6 (как у виджетов) — то же размытие, что было
        vivid = 1.35 + 0.5 * self.juice()
        if self.bg_busy:  # прошлый снимок ещё считается — снять сразу после него
            self.bg_again = True
            return
        if not self.isVisible() or time.monotonic() < self.snap_until or not look.get("acrylic"):
            return
        self.bg_busy = True
        k = self.devicePixelRatioF()
        g = self.geometry()
        rect = (round(g.x() * k), round(g.y() * k), round(g.width() * k), round(g.height() * k))

        def work():
            try:
                img = screen.frosted(*rect, radius=radius, vivid=vivid)
            except Exception:
                img = None
            try:
                self.bg_ready.emit(img)
            except RuntimeError:
                pass
        POOL.submit(work)

    def on_window(self, hwnd, rect, foreground):
        """Окно открылось/закрылось/свернулось/сдвинулось над или под островом, или сменилось активное —
        стекло сразу переснимаем (а не ждём таймера), и ещё раз, когда анимация окна в Windows доиграет."""
        if not self.isVisible() or not self.look.get("acrylic"):
            return
        if not foreground and rect is not None:
            k = self.devicePixelRatioF()
            g = self.geometry()
            x0, y0, x1, y1 = g.x() * k, g.y() * k, (g.x() + g.width()) * k, (g.y() + g.height()) * k
            if rect[2] <= x0 or rect[0] >= x1 or rect[3] <= y0 or rect[1] >= y1:
                return  # окно не там, где остров
        self.bg_timer.setInterval(700)
        now = time.monotonic()
        if now - self.bg_kicked > 0.04:  # окно тащат — не чаще ~25 раз в секунду
            self.bg_kicked = now
            self.grab_bg()
        self.bg_follow0.start()
        self.bg_follow1.start()  # анимация открытия/сворачивания в Windows ~0.25 с — снять и после неё
        self.bg_follow2.start()

    def on_bg(self, img):
        self.bg_busy = False
        if self.bg_again:  # пока считали, под островом ещё что-то поменялось
            self.bg_again = False
            QTimer.singleShot(0, self.grab_bg)
        if img is not None and self.isVisible():
            # под островом то же самое — снимаем всё реже (до раза в 3 с); поменялось — снова часто
            same = self.bg is not None and img == self.bg
            self.bg_timer.setInterval(min(3000, self.bg_timer.interval() + 500) if same else 700)
            if same:
                return
            self.bg = img
            # авто-тема: по яркости того, что под островом (между порогами — как была)
            c = img.scaled(1, 1, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).pixelColor(0, 0)
            lum = (c.red() * 0.3 + c.green() * 0.59 + c.blue() * 0.11) / 255
            self.auto_dark = lum < (TO_LIGHT if self.auto_dark else TO_DARK)
            if self.look.get("theme") == "auto" and self.auto_dark != DARK:
                self.refresh_look(force=True)
            self.bg_gen += 1
            self.repaint_area()

    # ---------- музыка ----------

    def on_media(self, state):
        music = state if state and "key" in state else None
        if music and music["key"] != self.cover_key:
            had = self.cover_key is not None
            self.cover_key = music["key"]
            img = music.get("cover")
            self.color = accent(img) if img is not None else None
            if had and music.get("playing"):  # сменился трек — показать какой, с волной
                self.mini_until = time.monotonic() + 3.5  # сменился трек — капсула чуть шире, с названием
                self.ripple(None, self.color)
        elif music and self.color is None and music.get("cover") is not None:  # обложка браузера приходит позже трека
            self.color = accent(music["cover"])
        if music and self.music and music.get("playing") != self.music.get("playing") and self.view \
                and self.view[0] == "music":
            self.ripple(None, self.color)
        if music and music.get("playing"):
            self.last_play = time.monotonic()
        self.music = music

    def music_pos(self):
        s = self.music
        pos = s["position"] + (time.monotonic() - s["read"] if s["playing"] else 0)
        return min(pos, s["duration"]) if s["duration"] else pos

    # ---------- таймер, помидор ----------

    def timer_state(self, now):
        c = timer_cfg()
        end = c.get("end")
        own = not widgets.widget_open("timer")  # виджета на столе нет — пищим и сбрасываем сами
        done = (end and now >= end) or ("left" in c and c["left"] == 0)
        if done:
            if self.done_seen is None:
                self.done_seen = now
                self.peek("timer", 8)
                self.ripple(None, RED)
                if own:
                    winsound.PlaySound("SystemExclamation", winsound.SND_ALIAS | winsound.SND_ASYNC)
            if own and end:
                widgets.patch("timer", {"end": None, "left": 0})
            if now - self.done_seen < 12:
                return "done"
            if own:
                widgets.patch("timer", {"left": None})
            return None
        self.done_seen = None
        if end:
            self.paused_at = None
            return "run"
        if c.get("left"):  # пауза: держим 2 минуты, потом прячем (таймер не сбрасываем)
            self.paused_at = self.paused_at or now
            return "pause" if now - self.paused_at < 120 else None
        self.paused_at = None
        return None

    def focus_state(self, now):
        c = focus_cfg()
        if c.get("end") and now >= c["end"] and not widgets.widget_open("focus"):  # виджета нет — переключаем сами
            if c["mode"] == "work":
                widgets.patch("focus", {"done": {"day": time.strftime("%Y-%m-%d"), "count": focus_today(c) + 1},
                                        "mode": "break", "end": now + focus_length(c, "break")})
            else:
                widgets.patch("focus", {"mode": "work", "end": None, "left": None})
            c = focus_cfg()
        state = c["mode"] if c.get("end") else "pause" if c.get("left") else None
        prev, self.focus_prev = self.focus_prev, state
        if prev == "work" and state == "break":  # помидор готов — перерыв
            self.peek("focus", 5)
            self.ripple(None, GREEN)
            winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC)
        elif prev == "break" and state is None:  # перерыв кончился — показать и минуту ждать нажатия
            self.peek("focus", 5)
            self.ripple(None, TOMATO)
            winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC)
            self.focus_ready_until = now + 60
        if state == "pause":  # пауза: держим 2 минуты
            self.focus_paused_at = self.focus_paused_at or now
            return state if now - self.focus_paused_at < 120 else None
        self.focus_paused_at = None
        if state is None and now < self.focus_ready_until:
            return "ready"
        return state

    # ---------- короткие сообщения ----------

    def show_toast(self, kind, seconds, **data):
        self.toast = {"kind": kind, "until": time.monotonic() + seconds, **data}
        self.poll()

    def check_audio(self):
        vol = self.audio.read()
        now = time.monotonic()
        if now - self.audio_checked > 5:  # подключили наушники / сменили устройство (дорого — раз в 5 с)
            self.audio_checked = now
            name = self.audio.name
            self.audio.refresh()
            if self.audio.name and name and self.audio.name != name:
                self.vol = self.audio.read()
                self.show_toast("device", 2.5, name=self.audio.name)
                return
            vol = self.audio.read()
        if vol is not None and self.vol is not None and vol != self.vol:
            self.vol = vol
            self.show_toast("volume", 1.8)
        self.vol = vol

    def check_weather(self):
        """«Через 40 мин дождь» / «Дождь закончится к 16:00» — из виджета «Погода», каждое — один раз."""
        alert = widgets.weather_alert()
        if alert and alert["key"] != self.weather_key:
            self.weather_key = alert["key"]
            if time.monotonic() - self.started > 5:  # не при запуске острова: это было бы старое
                self.show_toast("weather", 5, precip=alert.get("kind"),
                                **{k: alert.get(k) for k in ("event", "at", "minutes", "temp")})

    def check_caps(self):
        caps = screen.caps_lock()
        if caps != self.caps:
            self.caps = caps
            self.show_toast("caps", 1.5)

    def on_clip(self):
        if time.monotonic() - self.started < 3:
            return
        cb = QApplication.clipboard()
        md = cb.mimeData()
        if md is None:
            return
        # менеджеры паролей помечают буфер «не показывать» — тогда без текста
        secret = any("ExcludeClipboardContentFromMonitorProcessing" in f or "CanIncludeInClipboardHistory" in f
                     for f in md.formats())
        if md.hasImage():
            img = cb.image()
            if img.isNull():
                return
            shot = time.monotonic() < self.snap_until  # только что жали PrtSc
            self.show_toast("clip", 2.4, text=tr("Снимок экрана") if shot else tr("Картинка"),
                            thumb=img.scaled(96, 96, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
        elif md.hasText():
            text = " ".join(md.text().split())
            if text:
                self.show_toast("clip", 2.0, text="" if secret else text, thumb=None)

    def wheelEvent(self, event):
        """Колесо над островом — громкость."""
        steps = event.angleDelta().y() / 120
        if steps:
            self.audio.change(0.02 * steps)
            self.vol = self.audio.read()
            self.show_toast("volume", 1.8)

    # ---------- что показывать ----------

    def peek(self, kind, seconds):
        self.peek_kind, self.peek_until = kind, time.monotonic() + seconds

    def full_screen(self):
        """Игра или видео на весь главный экран — острова не видно."""
        monitor = screen.fullscreen_monitor()
        if monitor is None:
            return False
        g = QApplication.primaryScreen().geometry()
        k = QApplication.primaryScreen().devicePixelRatio()
        return monitor[0] == round(g.x() * k) and monitor[1] == round(g.y() * k)

    def wanted_lang(self):
        """Язык острова: свой (настройки острова) или как у виджетов."""
        return settings.get("lang") or widgets.section("app").get("lang", "ru")

    def restart(self):
        """Язык читается при запуске (подписи меню собираются тогда же) — сменили язык: перезапуск."""
        QProcess.startDetached(sys.executable, [os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py"),
                                                "--restart"])
        QApplication.quit()

    def poll(self):
        now = time.time()
        if self.wanted_lang() != lang.LANG:  # язык виджетов поменяли, а остров «как у виджетов»
            self.restart()
            return
        self.refresh_look()
        self.check_audio()
        self.check_caps()
        self.check_weather()
        if self.toast and time.monotonic() >= self.toast["until"]:
            self.toast = None
        ts = self.timer_state(now)
        fs = self.focus_state(now)
        items = []
        if self.toast:
            items.append((-1, "toast", self.toast["kind"]))
        if ts == "done":
            items.append((0, "timer", ts))
        if fs == "ready":
            items.append((2.5, "focus", fs))
        if ts == "run":
            items.append((3, "timer", ts))
        if fs in ("work", "break"):
            items.append((3.5, "focus", fs))
        m = self.music
        if m and m.get("playing"):
            items.append((4, "music", "play"))
        if ts == "pause":
            items.append((6, "timer", ts))
        if fs == "pause":
            items.append((6.5, "focus", fs))
        if m and not m.get("playing") and time.monotonic() - self.last_play < 30:
            items.append((7, "music", "pause"))
        if not self.enabled() or self.full_screen():
            items = []
        self.items = [(k, s) for _, k, s in sorted(items)]
        self.retarget()

    def state_of(self, kind):
        for k, s in self.items:
            if k == kind:
                return s
        return None

    def primary(self):
        # всплывашку уже убрали (клик, истекла), а список дел пересчитается только на опросе — её не считаем
        kinds = [k for k, _ in self.items if k != "toast" or self.toast is not None]
        if not kinds:
            return None, None
        if kinds[0] == "toast":
            first = "toast"
        elif self.peek_kind in kinds and time.monotonic() < self.peek_until:
            first = self.peek_kind
        elif self.pinned in kinds:
            first = self.pinned
        else:
            first = kinds[0]
        rest = [k for k in kinds if k not in (first, "toast")]
        return first, (rest[0] if rest else None)

    def expanded(self):
        return self.hover or time.monotonic() < self.peek_until

    def calling(self):
        """Дело зовёт (таймер дозвенел, перерыв кончился) — свечение дышит."""
        return self.state_of("timer") == "done" or self.state_of("focus") == "ready"

    def view_size(self, view):
        """Размер капсулы под вид; крупнее текст — шире капсула (высота свёрнутой та же)."""
        if view[0] == "toast":
            w, h = TOASTS.get(self.toast["kind"] if self.toast else view[1], 240), H
        else:
            w, h = SIZES[view]
        if view == ("music", False):  # там только обложка и эквалайзер
            return w, h
        grow = (FONT_K - 1) * (0.5 if h > H else 0.9)
        return round(w * (1 + grow)), h

    def retarget(self):
        first, second = self.primary()
        if first is None:
            view = None
            self.alpha.set(0)
            self.w.set(H)
            self.h.set(H)
            self.want_bubble = False
            self.place_bubble()
            self.glow.set(0)
        else:
            if not self.isVisible():
                self.w.jump(H * 0.6)
                self.h.jump(H * 0.6)
                self.alpha.jump(0)
                self.show()
            if first == "toast":
                view = ("toast", self.toast["kind"])
            elif first == "music" and not self.expanded() and time.monotonic() < self.mini_until:
                view = ("music", "mini")
            else:
                view = (first, self.expanded())
            tw, th = self.view_size(view)
            # как жидкость: раскрываясь, сперва тянется вширь, потом вниз; сворачиваясь — наоборот
            if th > self.h.target:
                self.w.k, self.h.k = 340, 220
            elif th < self.h.target:
                self.w.k, self.h.k = 230, 320
            self.w.set(tw)
            self.h.set(th)
            self.alpha.set(1)
            self.want_bubble = bool(second) and th <= H
            self.place_bubble()
            self.glow.set(1 if (view[1] is True) or self.calling() else 0)
        if view != self.view:
            if view is not None and self.view is not None:
                self.old_view = self.view if self.fade > 0.5 else self.old_view
                self.fade = 0.0
            elif view is not None:
                self.old_view, self.fade = None, 0.0
            self.view = view
        if first is not None or self.isVisible():
            if any(s.x != s.target for s in (self.w, self.h, self.bubble, self.alpha, self.glow)) \
                    or self.fade < 1:
                self.go_vsync()  # пошло движение — сразу кадр в кадр с монитором
            elif not self.anim.isActive() and not self.vsync.running:
                self.last_step = time.monotonic()
                self.anim.start()
            self.repaint_area()

    def go_vsync(self):
        """Движение: такт — сам монитор (DwmFlush), а не таймер: кадры не двоятся и не теряются."""
        if not self.vsync.running:
            self.anim.stop()
            self.last_step = time.monotonic()
            self.vsync.start()

    def place_bubble(self):
        """Капля второго дела выходит только из уже свёрнутой капсулы (иначе прилипает к углу большой карточки),
        а при раскрытии прячется быстро — раньше, чем карточка вырастет."""
        if self.want_bubble:
            if self.h.x <= H + 3 and self.bubble.target != 1:
                self.bubble.k, self.bubble.zeta = 220, 0.72  # выходит мягко, с перелётом — «отрывается»
                self.bubble.set(1)
        elif self.bubble.target != 0:
            self.bubble.k, self.bubble.zeta = 900, 1.0  # прячется быстро и без перелёта
            self.bubble.set(0)

    def repaint_area(self):
        """Перерисовать только место вокруг капсулы (со свечением) и где она была в прошлый раз:
        окно 520×200 целиком Windows перекладывает заметно дороже."""
        area = self.shapes()[2].boundingRect().adjusted(-4, -4, 4, 4).toAlignedRect()
        last = getattr(self, "_painted", None)
        self._painted = area
        self.update(area.united(last) if last is not None else area)

    def ripple(self, center, color):
        """Волна от точки (None — от середины капсулы), гаснет сама."""
        self.ripples.append((center, time.monotonic(), QColor(color) if color is not None else QColor(FG)))
        self.flash = 1.0
        if self.isVisible():
            self.retarget()

    def on_vsync(self):
        self.vsync.pending = False
        self.step()

    def step(self):
        now = time.monotonic()
        dt = min(1 / 30, now - self.last_step)
        self.last_step = now
        moving = False
        for s in (self.w, self.h, self.bubble, self.alpha, self.glow):
            moving = s.step(dt) or moving
        if self.fade < 1:
            self.fade = min(1.0, self.fade + dt / 0.32)
            moving = True
        self.flash = 0.0  # вспышки (свечения) больше нет
        self.ripples = [r for r in self.ripples if now - r[1] < 0.8]
        moving = moving or bool(self.ripples)
        if self.peek_until and now >= self.peek_until:  # подсмотр кончился — свернуть
            self.peek_until = 0
            self.peek_kind = None
            self.retarget()
        if self.want_bubble and self.bubble.target == 0:
            self.place_bubble()  # карточка свернулась — теперь капле можно выйти
            moving = moving or self.bubble.x != self.bubble.target
        if self.mini_until and now >= self.mini_until:  # подсказка о треке — обратно в капсулу
            self.mini_until = 0
            self.retarget()
        if self.view is None and self.alpha.x <= 0.01 and not moving:
            self.anim.stop()
            self.vsync.stop()
            self.hide()
            return
        # двигается — кадр в кадр с монитором; зовёт или раскрытая музыка (бегущий свет) — 30 к/с;
        # эквалайзер — 15; персонаж — со скоростью своих кадров; иначе хватает 4 (секунды таймера)
        kind = self.view[0] if self.view else None
        playing = kind == "music" and self.music and self.music.get("playing")
        if moving:
            self.go_vsync()
            self.repaint_area()
            return
        self.vsync.stop()  # встало на место — дальше редкий таймер
        if self.calling() or (playing and self.view[1]):
            interval = 33
        elif playing:
            interval = 66
        else:
            interval = 250
        if self.anim.interval() != interval:
            self.anim.setInterval(interval)
        if not self.anim.isActive():
            self.anim.start()
        self.repaint_area()

    # ---------- форма ----------

    def shapes(self):
        """Капсула, капля второго дела и общий контур (с перемычкой, пока капля рядом)."""
        w, h, b = self.w.x, self.h.x, max(0.0, self.bubble.x)
        key = (round(w, 2), round(h, 2), round(b, 3))
        if getattr(self, "_shape_key", None) == key:  # стоит на месте — тот же контур, не пересчитываем
            return self._shape
        self._shape_key = key
        self._shape = self._shapes(w, h, b)
        return self._shape

    def _shapes(self, w, h, b):
        if h > H + 4:  # карточка раскрыта (или растёт) — капли нет: иначе она «прилипает» к её углу
            b = 0.0
        d = H * min(1.0, 0.3 + 0.7 * b) if b > 0.02 else 0.0
        gap = GAP * b
        total = w + (gap + d if d else 0)
        left = (WIN_W - total) / 2
        pill = QRectF(left, TOP, w, h)
        bub = QRectF(pill.right() + gap, TOP + (H - d) / 2, d, d) if d else QRectF()
        path = QPainterPath()
        radius = min(h / 2, 30)
        path.addRoundedRect(pill, radius, radius)
        if d:
            drop = QPainterPath()
            drop.addEllipse(bub)
            path = path.united(drop)
            # перемычка: пока капля близко, её тянет к капсуле, как жидкость
            neck = (H / 2) * max(0.0, 1 - gap / 7.0) * 0.75
            if neck > 0.6:
                cy = TOP + H / 2
                x1, x2 = pill.right() - 8, bub.left() + 6
                mid = (x1 + x2) / 2
                bridge = QPainterPath(QPointF(x1, cy - H / 2 * 0.86))
                bridge.quadTo(QPointF(mid, cy - neck), QPointF(x2, cy - d / 2 * 0.86))
                bridge.lineTo(QPointF(x2, cy + d / 2 * 0.86))
                bridge.quadTo(QPointF(mid, cy + neck), QPointF(x1, cy + H / 2 * 0.86))
                bridge.closeSubpath()
                path = path.united(bridge)
        return pill, bub, path

    # ---------- мышь ----------

    def enterEvent(self, event):
        self.leave_timer.stop()
        self.hover_check(event.position())

    def hover_check(self, pos):
        """Раскрываться только над самой капсулой: над каплей второго дела — нет (клик по ней — поменять местами)."""
        if self.shapes()[0].contains(pos) and not self.over_arrows(pos):
            if not self.hover and not self.enter_timer.isActive():
                self.enter_timer.start()
        else:
            self.enter_timer.stop()

    def over_arrows(self, pos):
        """Мышь над ⏮ ⏯ ⏭ свёрнутой капсулы с музыкой: тут не раскрываться, иначе по ним не попасть."""
        if self.hover or self.view not in (("music", False), ("music", "mini")):
            return False
        return any(self.buttons[n].contains(pos) for n in ("prev", "play", "next") if n in self.buttons)

    def leaveEvent(self, event):
        self.enter_timer.stop()
        self.leave_timer.start()
        self.unsetCursor()

    def set_hover(self, on):
        if on == self.hover:
            return
        self.hover = on
        if not on:
            self.peek_until = 0
        self.retarget()

    def drag_to(self, pos):
        """Ползунок под мышью: громкость меняется сразу, перемотка — когда отпустят (Spotify не любит частую)."""
        bar = self.bars.get(self.drag)
        if bar is None or bar.width() <= 0:
            return
        f = max(0.0, min(1.0, (pos.x() - bar.left()) / bar.width()))
        if self.drag == "vol":
            self.audio.set(f)
            self.vol = self.audio.read()
            if self.toast and self.toast["kind"] == "volume":
                self.toast["until"] = time.monotonic() + 1.8
        else:
            self.drag_value = f
        self.repaint_area()

    def mouseReleaseEvent(self, event):
        if self.drag is None:
            return
        self.drag_to(event.position())
        if self.drag == "seek" and self.music:
            sec = self.drag_value * (self.music.get("duration") or 0)
            Media.get().command("seek", sec)
            self.music = {**self.music, "position": sec, "read": time.monotonic()}
        self.drag = None
        self.repaint_area()

    def mouseMoveEvent(self, event):
        pos = event.position()
        if self.drag is not None:
            self.drag_to(pos)
            return
        self.hover_check(pos)
        hot = any(r.contains(pos) for r in self.buttons.values()) or self.bubble_rect.contains(pos)
        self.setCursor(Qt.PointingHandCursor if hot else Qt.ArrowCursor)

    def mousePressEvent(self, event):
        pos = event.position()
        if event.button() == Qt.RightButton:
            menu = QMenu()
            menu.addAction(tr("Настройки…"), self.open_settings)
            menu.addAction(tr("Выключить остров (включить — в трее)"), lambda: self.set_enabled(False))
            menu.exec(event.globalPosition().toPoint())
            return
        if event.button() != Qt.LeftButton:
            return
        kind = self.view[0] if self.view else None
        if self.bubble.x > 0.5 and self.bubble_rect.contains(pos):
            self.pinned = self.primary()[1]
            self.toast = None
            self.poll()  # сначала пересчитать дела (всплывашки уже нет), потом волна
            self.ripple(pos, self.kind_color(self.pinned))
            return
        for name, rect in self.buttons.items():
            if rect.contains(pos) and name in self.bars:  # ползунок — тянуть, без волны
                self.drag = name
                self.drag_to(pos)
                return
            if rect.contains(pos):
                self.ripple(rect.center(), self.kind_color(kind))
                self.press(name)
                return
        self.ripple(pos, self.kind_color(kind))
        if kind == "toast":  # клик по сообщению — убрать его
            self.toast = None
            self.poll()
        elif not self.expanded():
            self.hover = True
            self.retarget()
        elif kind == "music":
            import os
            os.startfile(YT_MUSIC_URL if (self.music or {}).get("source") == "ytmusic" else "spotify:")

    def press(self, name):
        now = time.time()
        if name in ("shuffle", "repeat") and self.music:  # сразу показать новое, не ждать опроса
            value = (not self.music.get("shuffle")) if name == "shuffle" else \
                {0: 2, 2: 1, 1: 0}[self.music.get("repeat") or 0]
            Media.get().command(name, value)
            self.music = {**self.music, name: value}
            self.repaint_area()
            return
        if name in ("prev", "play", "next"):
            Media.get().command(name)
            if name == "play" and self.music:  # сразу перерисовать кнопку, не ждать опроса
                self.music = {**self.music, "playing": not self.music["playing"], "position": self.music_pos(),
                              "read": time.monotonic()}
                self.last_play = time.monotonic()
            self.update()
            return
        if name.startswith("t_"):
            c = timer_cfg()
            if name == "t_play":
                if c.get("end"):
                    ch = {"left": timer_left(c, now), "end": None}
                else:
                    ch = {"end": now + (timer_left(c, now) or c["duration"]), "left": None}
            elif name == "t_add":
                if c.get("end"):
                    ch = {"end": c["end"] + 60}
                elif c.get("left") == 0:  # дозвенел — ещё минуту
                    ch = {"end": now + 60, "left": None}
                else:
                    ch = {"left": timer_left(c, now) + 60}
            else:
                ch = {"end": None, "left": None}
            self.done_seen = None
            widgets.patch("timer", ch)
        else:
            c = focus_cfg()
            if name == "f_play":
                if c.get("end"):
                    ch = {"left": focus_left(c, now), "end": None}
                else:
                    ch = {"end": now + float(c.get("left", focus_length(c))), "left": None}
                self.focus_ready_until = 0
            else:
                ch = {"end": None, "left": None, "mode": "work"}
                self.focus_ready_until = 0
            widgets.patch("focus", ch)
            self.focus_prev = None
        self.poll()

    # ---------- рисование ----------

    def kind_color(self, kind):
        if kind == "music":
            c = QColor(self.color) if self.color is not None else QColor(GREEN)
            if DARK and c.lightness() < 120:  # тёмная обложка на тёмном стекле — светлее, иначе не видно
                c = c.lighter(170)
            elif not DARK and c.lightness() > 150:  # светлая обложка на светлом стекле — темнее
                c = c.darker(190)
            return c
        if kind == "timer":
            return RED if self.state_of("timer") == "done" else ORANGE
        if kind == "focus":
            return GREEN if self.state_of("focus") == "break" else TOMATO
        if kind == "toast" and self.toast:
            return BLUE if self.toast["kind"] in ("clip", "device") else QColor(FG)
        return QColor(FG)

    def juice(self):
        """Замутнение в минусе (как у виджетов) -> насколько сочнее цвета под стеклом: 0..1."""
        haze = self.look["haze"]
        return 0.0 if haze >= 0 else min(1.0, haze / -50)

    def tint(self):
        """Дымка поверх размытого: цвет и плотность — как у виджетов (замутнение; без акрила — заливка)."""
        look = self.look
        if not look["acrylic"]:
            a = max(0.3, min(1.0, look["fill"] / 100))
        else:
            t = max(0, min(100, look["haze"])) / 100
            a = 0.45 + 0.52 * t ** 0.9 if DARK else 0.40 + 0.55 * t ** 0.5
        a = min(0.98, a)
        return QColor(10, 10, 14, int(a * 255)) if DARK else QColor(242, 242, 246, int(a * 255))

    def chrome(self, path):
        """Стекло + блик + кромка одной картинкой (кэш: форма, снимок под островом, настройки стекла)."""
        key = (self._shape_key, self.bg_gen, tuple(sorted(self.look.items())), DARK)
        if getattr(self, "_chrome_key", None) == key:
            return self._chrome_pm
        dpr = self.devicePixelRatioF()
        pm = QPixmap(round(WIN_W * dpr), round(WIN_H * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        # стекло: размытое то, что под островом, притемнённое дымкой
        p.save()
        p.setClipPath(path)
        tint = self.tint()
        if self.bg is not None and self.look["acrylic"]:
            p.drawImage(QRectF(0, 0, WIN_W, WIN_H), self.bg)
            p.fillPath(path, tint)
        else:  # без акрила (или снимка ещё нет) — плотнее, чтобы текст читался
            if self.look["acrylic"]:
                tint.setAlpha(max(tint.alpha(), 236))
            p.fillPath(path, tint)
        # лёгкий блик сверху и цветной отсвет дела снизу — свет «копится» в толще стекла
        box = path.boundingRect()
        sheen = QLinearGradient(box.topLeft(), box.bottomLeft())
        sheen.setColorAt(0, QColor(255, 255, 255, 20))
        sheen.setColorAt(0.45, QColor(255, 255, 255, 0))
        sheen.setColorAt(1, QColor(255, 255, 255, 8))
        p.fillPath(path, sheen)
        p.restore()
        # кромка: тонкий свет, ярче снизу, с оттенком дела
        rim = QLinearGradient(box.topLeft(), box.bottomLeft())
        rim.setColorAt(0, QColor(255, 255, 255, 70))
        rim.setColorAt(0.5, QColor(255, 255, 255, 18))
        rim.setColorAt(1, QColor(255, 255, 255, 46))
        p.setPen(QPen(rim, 1.1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        p.end()
        self._chrome_key, self._chrome_pm = key, pm
        return pm

    def paintEvent(self, event):
        a = max(0.0, min(1.0, self.alpha.x))
        self.buttons = {}
        self.bars = {}
        self.bubble_rect = QRectF()
        if a <= 0.01:
            return
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        p.setOpacity(a)
        pill, bub, path = self.shapes()
        first, second = self.primary()
        now = time.monotonic()

        # стекло, блик и кромка меняются только с формой и снимком под островом — готовая картинка;
        # каждый кадр это одно копирование, а не размытое стекло, градиенты и обводка заново
        p.drawPixmap(0, 0, self.chrome(path))
        if self.ripples:  # волны от касаний
            p.save()
            p.setClipPath(path)
            for center, t0, rc in self.ripples:
                t = (now - t0) / 0.8
                c = center if center is not None else QPointF(pill.center().x(),
                                                              pill.top() + min(pill.height(), 60) / 2)
                rad = 12 + ease(t) * max(pill.width(), 120) * 0.75
                grad = QRadialGradient(c, rad)
                grad.setColorAt(0, with_alpha(rc, 0))
                grad.setColorAt(0.82, with_alpha(rc, 0.20 * (1 - t)))
                grad.setColorAt(1, with_alpha(rc, 0))
                p.fillRect(QRectF(c.x() - rad, c.y() - rad, 2 * rad, 2 * rad), grad)
            p.restore()

        # содержимое: старое уходит за первую треть, новое проявляется со второй четверти и «доплывает»
        pill_path = QPainterPath()
        radius = min(pill.height() / 2, 30)
        pill_path.addRoundedRect(pill, radius, radius)
        out, inn = ease(self.fade / 0.35), ease((self.fade - 0.25) / 0.75)
        for view, alpha, scale in ((self.old_view, 1 - out, 1 - 0.06 * out), (self.view, inn, 0.94 + 0.06 * inn)):
            if view is None or alpha <= 0.01 or (view[0] == "toast" and not self.toast):
                continue
            tw, th = self.view_size(view)
            area = QRectF(pill.center().x() - tw / 2, TOP, tw, th)
            p.save()
            p.setClipPath(pill_path)
            p.setOpacity(a * alpha)
            p.translate(area.center().x(), TOP)
            p.scale(scale, scale)
            p.translate(-area.center().x(), -TOP)
            keep = self.buttons
            if view is not self.view:
                self.buttons = {}
            getattr(self, f"draw_{view[0]}")(p, area, view[1])
            if view is not self.view:
                self.buttons = keep
            p.restore()
        if bub.width() > H * 0.6 and second:
            self.bubble_rect = bub
            p.save()
            p.setOpacity(a * min(1.0, (bub.width() / H - 0.6) / 0.4))
            self.draw_mini(p, bub, second)
            p.restore()

    # музыка

    def eq(self, p, x, cy, playing, height=12, bar=3.0):
        """Эквалайзер: 4 столбика пляшут, пока играет; на паузе — низкие."""
        t = time.monotonic()
        color = self.kind_color("music")
        p.setPen(Qt.NoPen)
        for i, (sp, ph) in enumerate(((7.0, 0.0), (9.5, 1.3), (6.2, 2.1), (8.3, 0.7))):
            hgt = 3 + (height - 3) * abs(math.sin(t * sp + ph)) ** 1.4 if playing else 3
            grad = QLinearGradient(0, cy - hgt / 2, 0, cy + hgt / 2)
            grad.setColorAt(0, color.lighter(140))
            grad.setColorAt(1, color)
            p.setBrush(grad)
            p.drawRoundedRect(QRectF(x + i * (bar + 2.5), cy - hgt / 2, bar, hgt), bar / 2, bar / 2)

    def cover(self, p, rect, rad, img=None):
        clip = QPainterPath()
        clip.addRoundedRect(rect, rad, rad)
        if img is None and self.music:
            img = self.music.get("cover")
        if img is not None:
            p.save()
            p.setClipPath(clip, Qt.IntersectClip)
            crop = min(img.width(), img.height())
            p.drawImage(rect, img, QRectF((img.width() - crop) / 2, (img.height() - crop) / 2, crop, crop))
            p.restore()
            p.setPen(QPen(soft(40), 1))
            p.setBrush(Qt.NoBrush)
            p.drawPath(clip)
        else:  # нота
            p.setPen(Qt.NoPen)
            p.setBrush(soft(40))
            p.drawPath(clip)
            c = rect.center()
            k = rect.width() / 24
            p.setBrush(FG)
            p.drawEllipse(QPointF(c.x() - 3 * k, c.y() + 4 * k), 3 * k, 2.4 * k)
            p.drawRect(QRectF(c.x() - 0.6 * k, c.y() - 7 * k, 1.6 * k, 11 * k))
            p.drawRect(QRectF(c.x() - 0.6 * k, c.y() - 7 * k, 5.5 * k, 1.8 * k))

    def track_arrows(self, p, r, playing):
        """⏮ ⏯ ⏭ у правого края свёрнутой капсулы (обычной и «сменился трек»): переключать и ставить на паузу,
        не раскрывая."""
        for name, dx in (("prev", -84), ("play", -52), ("next", -20)):
            c = QPointF(r.right() + dx, r.center().y())
            self.buttons[name] = QRectF(c.x() - 15, r.top(), 30, r.height())  # по высоте всей капсулы — легко попасть
            p.save()
            p.translate(c)
            p.scale(0.82, 0.82)  # значки те же, что в раскрытой карточке, чуть мельче под высоту капсулы
            glyph(p, name, QPointF(0, 0), FG, playing)
            p.restore()

    def draw_music(self, p, r, big):
        s = self.music
        if not s:
            return
        playing = s.get("playing")
        if big == "mini":  # сменился трек: обложка, название · исполнитель, эквалайзер и ⏮ ⏯ ⏭
            self.cover(p, QRectF(r.left() + 6, r.top() + 6, 24, 24), 8)
            self.track_arrows(p, r, playing)
            x, w = r.left() + 40, r.width() - 40 - 46 - 96
            title = s.get("title") or "—"
            f1, f2 = font(13), font(12, "Segoe UI")
            tw = min(QFontMetricsF(f1).horizontalAdvance(title), w)
            p.setFont(f1)
            p.setPen(FG)
            p.drawText(QRectF(x, r.top(), tw + 1, r.height()), Qt.AlignLeft | Qt.AlignVCenter, elide(title, f1, w))
            if s.get("artist") and w - tw > 30:
                p.setFont(f2)
                p.setPen(DIM)
                p.drawText(QRectF(x + tw + 6, r.top(), w - tw - 6, r.height()), Qt.AlignLeft | Qt.AlignVCenter,
                           elide(s["artist"], f2, w - tw - 6))
            self.eq(p, r.right() - 36 - 96, r.center().y(), playing)
            return
        if not big:  # капсула: обложка, эквалайзер и ⏮ ⏯ ⏭ — переключать и ставить на паузу, не раскрывая
            self.cover(p, QRectF(r.left() + 6, r.top() + 6, 24, 24), 8)
            self.eq(p, r.left() + 40, r.center().y(), playing)
            self.track_arrows(p, r, playing)
            return
        color = self.kind_color("music")
        self.cover(p, QRectF(r.left() + 16, r.top() + 16, 66, 66), 16)
        x, w = r.left() + 98, r.width() - 98 - 54
        p.setFont(font(15))
        p.setPen(FG)
        p.drawText(QRectF(x, r.top() + 22, w, 22), Qt.AlignLeft | Qt.AlignVCenter,
                   elide(s.get("title") or "—", font(15), w))
        p.setFont(font(12, "Segoe UI"))
        p.setPen(DIM)
        p.drawText(QRectF(x, r.top() + 46, w, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   elide(s.get("artist") or "", font(12, "Segoe UI"), w))
        self.eq(p, r.right() - 40, r.top() + 33, playing, 16, 3.5)
        # прогресс с бегущим светом
        pos, dur = self.music_pos(), s.get("duration") or 0
        bar = QRectF(r.left() + 58, r.top() + 98, r.width() - 116, 5)
        if dur and s.get("can_seek", True):  # ползунок: клик или перетаскивание — перемотка
            self.buttons["seek"] = bar.adjusted(-8, -11, 8, 11)
            self.bars["seek"] = bar
            if self.drag == "seek":  # тянут — показываем, куда, пока не отпустят
                pos = self.drag_value * dur
        p.setPen(Qt.NoPen)
        p.setBrush(soft(46))
        p.drawRoundedRect(bar, 2.5, 2.5)
        if dur:
            done = QRectF(bar.left(), bar.top(), max(5.0, bar.width() * min(1, pos / dur)), bar.height())
            grad = QLinearGradient(done.topLeft(), done.topRight())
            grad.setColorAt(0, with_alpha(color, 0.75))
            grad.setColorAt(1, FG)
            p.setBrush(grad)
            p.drawRoundedRect(done, 2.5, 2.5)
            if playing:  # свет бежит по пройденному к бегунку
                t = (time.monotonic() % 2.4) / 2.4
                hx = done.left() + done.width() * ease(t)
                light = QRadialGradient(QPointF(hx, done.center().y()), 18)
                light.setColorAt(0, QColor(255, 255, 255, int(200 * (1 - t))))
                light.setColorAt(1, QColor(255, 255, 255, 0))
                p.save()
                clip = QPainterPath()
                clip.addRoundedRect(done, 2.5, 2.5)
                p.setClipPath(clip, Qt.IntersectClip)
                p.fillRect(done, light)
                p.restore()
            knob = QPointF(done.right(), done.center().y())
            halo = QRadialGradient(knob, 12)
            halo.setColorAt(0, with_alpha(color.lighter(150), 0.55))
            halo.setColorAt(1, with_alpha(color, 0))
            p.setBrush(halo)
            p.drawEllipse(knob, 12, 12)
            p.setBrush(FG)
            p.drawEllipse(knob, 4.5, 4.5)
        p.setFont(font(11, "Bahnschrift"))
        p.setPen(DIM)
        p.drawText(QRectF(r.left() + 12, bar.center().y() - 8, 40, 16), Qt.AlignRight | Qt.AlignVCenter, mmss(pos))
        p.drawText(QRectF(bar.right() + 6, bar.center().y() - 8, 40, 16), Qt.AlignLeft | Qt.AlignVCenter, mmss(dur))
        cy, cx = r.bottom() - 28, r.center().x()
        for name, dx, rad in (("shuffle", -118, 14), ("prev", -60, 16), ("play", 0, 21), ("next", 60, 16),
                              ("repeat", 118, 14)):
            if name in ("shuffle", "repeat") and not s.get("can_" + name, True):
                continue
            rect = QRectF(cx + dx - rad, cy - rad, 2 * rad, 2 * rad)
            self.buttons[name] = rect
            if name in ("shuffle", "repeat"):  # как в Spotify: включено — зелёным и точка снизу
                on = s.get("shuffle") if name == "shuffle" else s.get("repeat")
                toggle_glyph(p, name, rect.center(), GREEN if on else DIM, s.get("repeat") == 1)
                if on:
                    p.setPen(Qt.NoPen)
                    p.setBrush(GREEN)
                    p.drawEllipse(QPointF(rect.center().x(), rect.center().y() + 11), 1.6, 1.6)
            elif name == "play":
                p.setPen(Qt.NoPen)
                p.setBrush(FG)
                p.drawEllipse(rect)
                glyph(p, name, rect.center(), INV, playing)
            else:
                glyph(p, name, rect.center(), FG, playing)

    # таймер и помидор

    def ring(self, p, c, rad, width, frac, color):
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(with_alpha(color, 0.22), width))
        p.drawEllipse(c, rad, rad)
        if frac > 0:
            p.setPen(QPen(color, width, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(QRectF(c.x() - rad, c.y() - rad, 2 * rad, 2 * rad), 90 * 16, int(-360 * 16 * frac))

    def timer_look(self):
        c = timer_cfg()
        st = self.state_of("timer") or "pause"
        left = timer_left(c, time.time())
        total = max(c["duration"], left) or 1
        if st == "done":
            return st, 0, 1.0, with_alpha(RED, 0.55 + 0.45 * abs(math.sin(time.monotonic() * 4)))
        return st, left, left / total, ORANGE if st == "run" else DIM

    def focus_look(self):
        c = focus_cfg()
        st = self.state_of("focus") or "pause"
        if st == "ready":
            pulse = 0.55 + 0.45 * abs(math.sin(time.monotonic() * 3))
            return st, focus_length(c, "work"), 1.0, with_alpha(TOMATO, pulse)
        left = focus_left(c, time.time())
        total = focus_length(c) or 1
        color = GREEN if st == "break" else TOMATO if st == "work" else DIM
        return st, left, left / total, color

    def big_counter(self, p, r, label, text, color, ring_frac, ring_color, buttons, accent_btn):
        """Раскрытые таймер и помидор: кольцо, подпись, крупное время, кнопки справа."""
        self.ring(p, QPointF(r.left() + 50, r.center().y()), 27, 5, ring_frac, ring_color)
        p.setFont(font(12, "Segoe UI"))
        p.setPen(DIM)
        p.drawText(QRectF(r.left() + 96, r.top() + 18, 170, 18), Qt.AlignLeft | Qt.AlignVCenter, label)
        size = 34 if len(text) <= 6 else 24
        p.setFont(font(size, "Bahnschrift SemiBold"))
        p.setPen(color)
        p.drawText(QRectF(r.left() + 94, r.top() + 36, 170, 46), Qt.AlignLeft | Qt.AlignVCenter, text)
        cy = r.center().y()
        xs = {2: (r.right() - 86, r.right() - 38), 3: (r.right() - 130, r.right() - 86, r.right() - 38)}[len(buttons)]
        for (name, kind, playing), x in zip(buttons, xs):
            rad = 21 if kind == "play" else 17
            rect = QRectF(x - rad, cy - rad, 2 * rad, 2 * rad)
            self.buttons[name] = rect
            p.setPen(Qt.NoPen)
            p.setBrush(accent_btn if kind == "play" else soft(34))
            p.drawEllipse(rect)
            m = rect.center()
            if kind == "reset":  # крестик
                p.setPen(QPen(FG, 2.2, Qt.SolidLine, Qt.RoundCap))
                p.drawLine(QPointF(m.x() - 5, m.y() - 5), QPointF(m.x() + 5, m.y() + 5))
                p.drawLine(QPointF(m.x() + 5, m.y() - 5), QPointF(m.x() - 5, m.y() + 5))
            elif kind == "add":
                p.setFont(font(13, "Bahnschrift SemiBold"))
                p.setPen(FG)
                p.drawText(rect, Qt.AlignCenter, "+1")
            else:
                glyph(p, "play", m, INV, playing)

    def small_counter(self, p, r, frac, color, text):
        self.ring(p, QPointF(r.left() + 20, r.center().y()), 9, 3, frac, color)
        p.setFont(font(17 if len(text) <= 6 else 14, "Bahnschrift SemiBold"))
        p.setPen(color)
        p.drawText(QRectF(r.left() + 40, r.top(), r.width() - 56, r.height()), Qt.AlignRight | Qt.AlignVCenter, text)

    def draw_timer(self, p, r, big):
        st, left, frac, color = self.timer_look()
        if not big:
            self.small_counter(p, r, frac, color, tr("Готово") if st == "done" else mmss(left))
            return
        label = {"run": tr("Таймер · идёт"), "pause": tr("Таймер · пауза"), "done": tr("Таймер")}[st]
        self.big_counter(p, r, label, tr("Время вышло") if st == "done" else mmss(left),
                         color if st != "pause" else FG, frac, color,
                         [("t_reset", "reset", False), ("t_add", "add", False), ("t_play", "play", st == "run")],
                         ORANGE)

    def draw_focus(self, p, r, big):
        st, left, frac, color = self.focus_look()
        count = focus_today(focus_cfg())
        if not big:
            self.small_counter(p, r, frac, color, tr("Пора!") if st == "ready" else mmss(left))
            return
        mode = {"work": tr("работа"), "break": tr("перерыв"), "pause": tr("пауза"), "ready": tr("перерыв окончен")}[st]
        label = tr("Фокус · {}").format(mode) + (tr(" · {} за день").format(count) if count else "")
        text = tr("За работу") if st == "ready" else mmss(left)
        running = st in ("work", "break")
        self.big_counter(p, r, label, text, color if st != "pause" else FG, frac, color,
                         [("f_reset", "reset", False), ("f_play", "play", running)],
                         GREEN if st == "break" else TOMATO)

    # короткие сообщения

    def draw_toast(self, p, r, kind):
        t = self.toast or {}
        cy = r.center().y()
        if kind == "volume":
            vol = self.vol or (0.0, False)
            level, muted = vol
            self.speaker_icon(p, QPointF(r.left() + 22, cy), 0 if muted else level, muted)
            bar = QRectF(r.left() + 46, cy - 3, r.width() - 46 - 56, 6)
            self.buttons["vol"] = bar.adjusted(-6, -12, 6, 12)  # ползунок громкости: клик или перетаскивание
            self.bars["vol"] = bar
            p.setPen(Qt.NoPen)
            p.setBrush(soft(46))
            p.drawRoundedRect(bar, 3, 3)
            if level > 0 and not muted:
                done = QRectF(bar.left(), bar.top(), max(6.0, bar.width() * level), bar.height())
                grad = QLinearGradient(done.topLeft(), done.topRight())
                grad.setColorAt(0, QColor(255, 255, 255, 170))
                grad.setColorAt(1, FG)
                p.setBrush(grad)
                p.drawRoundedRect(done, 3, 3)
            p.setFont(font(14, "Bahnschrift SemiBold"))
            p.setPen(DIM if muted else FG)
            p.drawText(QRectF(r.right() - 52, r.top(), 38, r.height()), Qt.AlignRight | Qt.AlignVCenter,
                       "—" if muted else f"{round(level * 100)}")
        elif kind == "clip":
            thumb = t.get("thumb")
            if thumb is not None:
                self.cover(p, QRectF(r.left() + 6, r.top() + 6, 24, 24), 7, thumb)
            else:
                self.clip_icon(p, QPointF(r.left() + 20, cy))
            text = t.get("text", "")
            x = r.left() + 42
            p.setFont(font(13))
            p.setPen(FG)
            head = tr("Скопировано") if thumb is None else tr("{} скопирован").format(text) + ("" if text == tr("Снимок экрана") else tr("а"))
            hw = QFontMetricsF(font(13)).horizontalAdvance(head)
            p.drawText(QRectF(x, r.top(), hw + 2, r.height()), Qt.AlignLeft | Qt.AlignVCenter, head)
            if thumb is None and text:
                w = r.right() - 16 - (x + hw + 10)
                p.setFont(font(12, "Segoe UI"))
                p.setPen(DIM)
                p.drawText(QRectF(x + hw + 10, r.top(), w, r.height()), Qt.AlignLeft | Qt.AlignVCenter,
                           elide(text, font(12, "Segoe UI"), w))
        elif kind == "caps":
            self.caps_icon(p, QPointF(r.left() + 22, cy), self.caps)
            p.setFont(font(13))
            p.setPen(FG)
            p.drawText(QRectF(r.left() + 44, r.top(), 100, r.height()), Qt.AlignLeft | Qt.AlignVCenter, "Caps Lock")
            p.setPen(BLUE if self.caps else DIM)
            p.drawText(QRectF(r.right() - 64, r.top(), 50, r.height()), Qt.AlignRight | Qt.AlignVCenter,
                       tr("вкл") if self.caps else tr("выкл"))
        elif kind == "device":
            self.headphones_icon(p, QPointF(r.left() + 22, cy))
            w = r.width() - 44 - 16
            p.setFont(font(13))
            p.setPen(FG)
            p.drawText(QRectF(r.left() + 44, r.top(), w, r.height()), Qt.AlignLeft | Qt.AlignVCenter,
                       elide(tr("Звук: ") + t.get("name", ""), font(13), w))
        elif kind == "weather":
            self.weather_icon(p, QPointF(r.left() + 22, cy), t.get("precip"), t.get("event") == "stop")
            name = {"rain": tr("Дождь"), "snow": tr("Снег"), "storm": tr("Гроза")}.get(t.get("precip"), tr("Дождь"))
            if t.get("event") == "stop":
                text = tr("{} закончится к {}").format(name, t.get("at", ""))
            elif (t.get("minutes") or 0) <= 75:
                text = tr("{} через {} мин").format(name, max(5, round((t.get("minutes") or 0) / 5) * 5))
            else:
                text = tr("{} около {}").format(name, t.get("at", ""))
            temp = t.get("temp")
            tw = 46 if temp is not None else 0
            w = r.width() - 44 - 14 - tw
            p.setFont(font(13))
            p.setPen(FG)
            p.drawText(QRectF(r.left() + 44, r.top(), w, r.height()), Qt.AlignLeft | Qt.AlignVCenter,
                       elide(text, font(13), w))
            if temp is not None:
                p.setFont(font(13, "Bahnschrift SemiBold"))
                p.setPen(DIM)
                p.drawText(QRectF(r.right() - 14 - tw, r.top(), tw, r.height()), Qt.AlignRight | Qt.AlignVCenter,
                           f"{temp:+d}°")
        elif kind == "island":  # вернули горячей клавишей
            p.setPen(Qt.NoPen)
            p.setBrush(GREEN)
            p.drawEllipse(QPointF(r.left() + 22, cy), 4.5, 4.5)
            p.setFont(font(13))
            p.setPen(FG)
            p.drawText(QRectF(r.left() + 38, r.top(), r.width() - 52, r.height()), Qt.AlignLeft | Qt.AlignVCenter,
                       tr("Остров включён"))
            p.setFont(font(11, "Segoe UI"))
            p.setPen(DIM)
            p.drawText(QRectF(r.left() + 38, r.top(), r.width() - 54, r.height()), Qt.AlignRight | Qt.AlignVCenter,
                       self.hotkey.title())

    # значки — свои, нарисованные кодом

    def speaker_icon(self, p, c, level, muted):
        p.setPen(Qt.NoPen)
        p.setBrush(FG)
        body = QPainterPath(QPointF(c.x() - 8, c.y() - 3))
        body.lineTo(c.x() - 4.5, c.y() - 3)
        body.lineTo(c.x() + 0.5, c.y() - 7.5)
        body.lineTo(c.x() + 0.5, c.y() + 7.5)
        body.lineTo(c.x() - 4.5, c.y() + 3)
        body.lineTo(c.x() - 8, c.y() + 3)
        body.closeSubpath()
        p.drawPath(body)
        p.setBrush(Qt.NoBrush)
        if muted:
            p.setPen(QPen(FG, 1.8, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(c.x() + 4, c.y() - 3.5), QPointF(c.x() + 11, c.y() + 3.5))
            p.drawLine(QPointF(c.x() + 11, c.y() - 3.5), QPointF(c.x() + 4, c.y() + 3.5))
            return
        for i, rad in enumerate((4.5, 8.5)):
            if level > (0.02 if i == 0 else 0.5):
                p.setPen(QPen(FG, 1.7, Qt.SolidLine, Qt.RoundCap))
                p.drawArc(QRectF(c.x() + 0.5 - rad, c.y() - rad, 2 * rad, 2 * rad), -50 * 16, 100 * 16)

    def clip_icon(self, p, c):
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(BLUE, 1.7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawRoundedRect(QRectF(c.x() - 6.5, c.y() - 7, 13, 15), 2.5, 2.5)
        p.setBrush(BLUE)
        p.drawRoundedRect(QRectF(c.x() - 3.5, c.y() - 9, 7, 4), 1.5, 1.5)
        p.drawLine(QPointF(c.x() - 3, c.y() + 0.5), QPointF(c.x() - 0.5, c.y() + 3))  # галочка
        p.drawLine(QPointF(c.x() - 0.5, c.y() + 3), QPointF(c.x() + 3.5, c.y() - 2))

    def caps_icon(self, p, c, on):
        color = BLUE if on else FG
        p.setPen(QPen(color, 1.7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(color if on else Qt.NoBrush)
        arrow = QPainterPath(QPointF(c.x(), c.y() - 8))
        arrow.lineTo(c.x() + 7, c.y() - 1)
        arrow.lineTo(c.x() + 3, c.y() - 1)
        arrow.lineTo(c.x() + 3, c.y() + 3)
        arrow.lineTo(c.x() - 3, c.y() + 3)
        arrow.lineTo(c.x() - 3, c.y() - 1)
        arrow.lineTo(c.x() - 7, c.y() - 1)
        arrow.closeSubpath()
        p.drawPath(arrow)
        p.drawLine(QPointF(c.x() - 3, c.y() + 7), QPointF(c.x() + 3, c.y() + 7))

    def weather_icon(self, p, c, kind, clearing):
        """Облако; под ним капли / снежинки / молния. Осадки кончаются — солнце выглядывает из-за облака."""
        cloud = QPainterPath()
        cloud.setFillRule(Qt.WindingFill)  # иначе там, где круги перекрываются, — дырки
        cloud.addEllipse(QPointF(c.x() - 4, c.y() - 1), 5, 5)
        cloud.addEllipse(QPointF(c.x() + 2.5, c.y() - 3.5), 6.5, 6.5)
        cloud.addRoundedRect(QRectF(c.x() - 9.5, c.y() - 1, 19, 6.5), 3.2, 3.2)
        cloud = cloud.simplified().translated(0, -2 if not clearing else 1)
        p.setPen(Qt.NoPen)
        if clearing:
            p.setBrush(YELLOW)
            p.drawEllipse(QPointF(c.x() + 5, c.y() - 5), 5, 5)
            p.setBrush(FG)
            p.drawPath(cloud)
            return
        p.setBrush(FG)
        p.drawPath(cloud)
        y = c.y() + 7
        if kind == "storm":
            bolt = QPainterPath(QPointF(c.x() + 1, y - 2.5))
            for dx, dy in ((-3.5, 4.5), (-0.5, 4.5), (-2, 8.5), (3, 2.8), (0, 2.8), (1.5, -2.5)):
                bolt.lineTo(c.x() + dx, y + dy - 2.5)
            bolt.closeSubpath()
            p.setBrush(YELLOW)
            p.drawPath(bolt)
        elif kind == "snow":
            p.setBrush(FG)
            for dx, dy in ((-5, 1), (0, 3), (5, 1)):
                p.drawEllipse(QPointF(c.x() + dx, y + dy), 1.6, 1.6)
        else:
            p.setPen(QPen(BLUE, 1.8, Qt.SolidLine, Qt.RoundCap))
            for dx in (-5, 0, 5):
                p.drawLine(QPointF(c.x() + dx + 1, y), QPointF(c.x() + dx - 0.5, y + 4))

    def headphones_icon(self, p, c):
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(BLUE, 1.8, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(QRectF(c.x() - 8, c.y() - 8, 16, 16), 0, 180 * 16)
        p.setPen(Qt.NoPen)
        p.setBrush(BLUE)
        p.drawRoundedRect(QRectF(c.x() - 9, c.y() - 1, 4.5, 8), 2, 2)
        p.drawRoundedRect(QRectF(c.x() + 4.5, c.y() - 1, 4.5, 8), 2, 2)

    # капля второго дела

    def draw_mini(self, p, r, kind):
        c = r.center()
        if kind == "music":
            inner = r.adjusted(5, 5, -5, -5)
            clip = QPainterPath()
            clip.addEllipse(inner)
            p.setClipPath(clip, Qt.IntersectClip)
            self.cover(p, inner, inner.width() / 2)
        elif kind == "timer":
            frac, color = self.timer_look()[2:]
            self.ring(p, c, 10.5, 3, frac, color)
        elif kind == "focus":
            frac, color = self.focus_look()[2:]
            self.ring(p, c, 10.5, 3, frac, color)
