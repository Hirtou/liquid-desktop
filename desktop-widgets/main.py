"""Каталог виджетов: стеклянное окно (Liquid Acrylic), включает/выключает виджеты, живёт в трее."""
from lang import LANG, LANGS, tr
import os

# numpy считает поэлементно, матрицы не перемножает — пул потоков OpenBLAS ему не нужен, а без этого
# он при импорте заводит поток на каждое ядро и резервирует ~350 МБ памяти. Ставить до импорта numpy.
for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import ctypes
import json
import sys
import threading
import time
import traceback
import winreg
from functools import lru_cache

import numpy as np
from PySide6.QtCore import QEasingCurve, QEvent, QPointF, QProcess, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetricsF, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (QAbstractButton, QApplication, QFrame, QGraphicsOpacityEffect, QGridLayout,
                               QHBoxLayout, QLabel,
                               QMenu, QScrollArea, QSlider, QStackedWidget, QSystemTrayIcon, QToolTip, QVBoxLayout,
                               QWidget)

import applog
import bugreport
import updater
import skins
import core
import glass
import icons
import sections
import widgets
from core import RADIUS, ROOT, SHADOW, DesktopWidget, activity, config


def fix_https():
    """Сертификаты для https (погода, тексты песен, Spotify): системные Windows + свежий набор certifi.
    Только системных мало: в хранилище Windows бывает просроченный промежуточный сертификат, Python выбирает его
    и считает сайт «просроченным» (так было с Open-Meteo) — погода уходила на http, а тот подвисал до таймаута.
    Системные оставляем: там корневые сертификаты антивирусов, которые проверяют https."""
    import ssl
    try:
        import certifi
    except ImportError:
        return

    def context(*args, **kwargs):
        ctx = ssl.create_default_context(*args, **kwargs)
        try:
            ctx.load_verify_locations(certifi.where())
        except (OSError, ssl.SSLError) as ex:
            applog.error("https: certifi", ex)
        return ctx
    ssl._create_default_https_context = context


fix_https()

ACCENT = skins.ACCENT
COLUMNS = 4  # карточек в ряд
SCROLL_STYLE = """
QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 6px; margin: 4px 0; }
QScrollBar::handle:vertical { background: rgba(128,128,140,110); border-radius: 3px; min-height: 40px; }
QScrollBar::handle:vertical:hover { background: rgba(128,128,140,170); }
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page { height: 0; background: none; }
"""
GWL_STYLE, WS_MINIMIZEBOX, WS_SYSMENU = -16, 0x00020000, 0x00080000
APP_ID = "Liquid.DesktopWidgets"  # своё имя для панели задач (значок не от Python)


def make_icon():
    pix = QPixmap(64, 64)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    for i, color in enumerate(["#4b7bff", "#5ad1a0", "#ffc861", "#ff6b6b"]):
        p.setBrush(QColor(color))
        p.drawRoundedRect(4 + (i % 2) * 30, 4 + (i // 2) * 30, 26, 26, 6, 6)
    p.end()
    return QIcon(pix)


def _mix(a, b, t):
    return QColor(*(int(x + (y - x) * t) for x, y in zip(a.getRgb(), b.getRgb())))


class Switch(QAbstractButton):
    """Тумблер в духе ColorOS: бегунок едет с лёгким перелётом и пружинит назад,
    в пути вытягивается каплей, цвет перетекает; при нажатии бегунок растягивается."""

    def __init__(self):
        super().__init__(checkable=True, cursor=Qt.PointingHandCursor)
        self.setFixedSize(52, 30)
        self.pos_ = 0.0     # 0 — выкл, 1 — вкл (может чуть перелететь)
        self.color_ = 0.0   # 0..1 — цвет дорожки
        self.press = 0.0    # 0..1 — бегунок нажат
        curve = QEasingCurve(QEasingCurve.OutBack)
        curve.setOvershoot(2.2)
        self.anim = QVariantAnimation(self, duration=420, easingCurve=curve)
        self.anim.valueChanged.connect(lambda v: self._set("pos_", v))
        self.fade = QVariantAnimation(self, duration=260, easingCurve=QEasingCurve.InOutSine)
        self.fade.valueChanged.connect(lambda v: self._set("color_", v))
        self.squash = QVariantAnimation(self, duration=140, easingCurve=QEasingCurve.OutCubic)
        self.squash.valueChanged.connect(lambda v: self._set("press", v))
        self.toggled.connect(self._animate)
        self.pressed.connect(lambda: self._run(self.squash, self.press, 1.0))
        self.released.connect(lambda: self._run(self.squash, self.press, 0.0))

    def _set(self, name, v):
        setattr(self, name, v)
        self.update()

    @staticmethod
    def _run(anim, start, end):
        anim.stop()
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.start()

    def _animate(self, on):
        self._run(self.anim, self.pos_, 1.0 if on else 0.0)
        self._run(self.fade, self.color_, 1.0 if on else 0.0)

    def set_quiet(self, on):
        """Переключить без анимации (при запуске)."""
        self.blockSignals(True)
        self.setChecked(on)
        self.blockSignals(False)
        self.pos_ = self.color_ = 1.0 if on else 0.0
        self.update()

    _cache = {}  # готовые картинки тумблеров в покое: все одного размера — общий кэш на всё окно

    def paintEvent(self, event):
        moving = self.press or self.pos_ not in (0.0, 1.0) or self.color_ not in (0.0, 1.0)
        if moving:  # анимация — рисуем как есть
            p = QPainter(self)
            self._paint(p)
            p.end()
            return
        dpr = self.devicePixelRatioF()
        key = (self.pos_, self.color_, bool(self.window().dark), self.isEnabled(),
               skins.version, dpr, self.size().toTuple())
        pix = Switch._cache.get(key)
        if pix is None:  # в покое — готовой картинкой (каталог: 37 тумблеров в каждом кадре прокрутки)
            pix = QPixmap(int(self.width() * dpr), int(self.height() * dpr))
            pix.setDevicePixelRatio(dpr)
            pix.fill(Qt.transparent)
            q = QPainter(pix)
            self._paint(q)
            q.end()
            if len(Switch._cache) > 64:
                Switch._cache.clear()
            Switch._cache[key] = pix
        p = QPainter(self)
        p.drawPixmap(0, 0, pix)
        p.end()

    def _paint(self, p):
        p.setRenderHint(QPainter.Antialiasing)
        if not self.isEnabled():  # сейчас не поменять — бледный (без QGraphicsEffect: см. sections.set_active)
            p.setOpacity(0.4)
        dark = bool(self.window().dark)
        off = QColor(255, 255, 255, 46) if dark else QColor(0, 0, 0, 40)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(Qt.NoPen)
        p.setBrush(_mix(off, ACCENT, self.color_))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        # капля: в середине пути и при нажатии бегунок шире
        t = self.pos_
        d = r.height() - 6
        stretch = max(0.0, 4 * t * (1 - t)) * 9 + self.press * 6
        w = d + stretch
        lo, hi = r.left() + 3, r.right() - 3 - w
        x = lo + (hi - lo) * t
        x = min(max(x, lo - 2), hi + 2)  # перелёт — чуть-чуть за край, как пружина
        knob = QRectF(x, r.top() + 3, w, d)
        p.setBrush(QColor(0, 0, 0, 45))  # тень бегунка
        p.drawRoundedRect(knob.translated(0, 1.2), d / 2, d / 2)
        p.setBrush(QColor("white"))
        p.drawRoundedRect(knob, d / 2, d / 2)


class TitleButton(QAbstractButton):
    """Круглая стеклянная кнопка окна: ✕ (закрыть), – (свернуть), жучок («Сообщить о баге»), сердечко («Поддержать автора»)."""

    def __init__(self, kind="close", text=""):
        super().__init__(cursor=Qt.PointingHandCursor)
        self.kind = kind
        self.label = text  # с надписью кнопка — капсула: значок слева, текст справа
        f = QFont("Segoe UI")
        f.setPixelSize(13)
        self.setFont(f)
        self.setFixedSize(32 + (int(QFontMetricsF(f).horizontalAdvance(text)) + 12 if text else 0), 32)
        self.setAttribute(Qt.WA_Hover)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = bool(self.window().dark)
        hover = self.underMouse()
        p.setPen(QPen(QColor(255, 255, 255, 60 if dark else 170), 1))
        p.setBrush(QColor(255, 255, 255, (45 if hover else 25) if dark else (190 if hover else 130)))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 15.5, 15.5)
        p.setPen(QPen(QColor("#f5f6fb" if dark else "#2a2c33"), 1.6, Qt.SolidLine, Qt.RoundCap))
        if self.label:
            p.drawText(QRectF(30, 0, self.width() - 38, 31), Qt.AlignVCenter | Qt.AlignLeft, self.label)
        c, s = QPointF(16, 16), 4.5
        if self.kind == "min":
            p.drawLine(c + QPointF(-s, 0), c + QPointF(s, 0))
        elif self.kind == "bug":  # жучок: тельце, голова, усики и по три лапки с боков
            p.setPen(QPen(p.pen().color(), 1.4, Qt.SolidLine, Qt.RoundCap))
            p.drawEllipse(QRectF(12.2, 13.2, 7.6, 9.4))
            p.drawLine(QPointF(16, 13.6), QPointF(16, 22.2))
            p.drawEllipse(QRectF(14, 9.6, 4, 3.6))
            p.drawLine(QPointF(14.8, 10), QPointF(13.2, 8))
            p.drawLine(QPointF(17.2, 10), QPointF(18.8, 8))
            for y, d in ((15, -1.2), (18, 0), (21, 1.2)):
                p.drawLine(QPointF(12.2, y), QPointF(9.4, y + d))
                p.drawLine(QPointF(19.8, y), QPointF(22.6, y + d))
        elif self.kind == "heart":  # сердечко — «Поддержать автора»
            heart = QPainterPath()
            heart.moveTo(16, 22.6)
            heart.cubicTo(9.2, 17.8, 8.6, 13.6, 10.6, 11.4)
            heart.cubicTo(12.4, 9.5, 15.0, 10.0, 16, 12.2)
            heart.cubicTo(17.0, 10.0, 19.6, 9.5, 21.4, 11.4)
            heart.cubicTo(23.4, 13.6, 22.8, 17.8, 16, 22.6)
            p.setPen(QPen(QColor("#ff5c7a"), 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(QColor(255, 92, 122, 150 if hover else 70))
            p.drawPath(heart)
        else:
            p.drawLine(c + QPointF(-s, -s), c + QPointF(s, s))
            p.drawLine(c + QPointF(-s, s), c + QPointF(s, -s))


class PillButton(QAbstractButton):
    """Стеклянная кнопка-капсула с текстом."""

    def __init__(self, text, accent=False):
        super().__init__(cursor=Qt.PointingHandCursor)
        self.accent = accent  # синяя (как выбранный вариант) — заметная: «Установить обновление»
        self.setText(text)
        self.setAttribute(Qt.WA_Hover)
        self.setFixedHeight(32)
        self.setMinimumWidth(QFontMetricsF(self.font()).horizontalAdvance(text) + 36)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.accent:
            r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            hover = self.underMouse()
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(ACCENT).lighter(112 if hover else 100) if self.isEnabled() else QColor(47, 107, 255, 120))
            p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
            p.setPen(QColor("#ffffff"))
            p.drawText(r, Qt.AlignCenter, self.text())
            return
        dark = bool(self.window().dark)
        hover = self.underMouse()
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(255, 255, 255, 60 if dark else 170), 1))
        p.setBrush(QColor(255, 255, 255, (45 if hover else 25) if dark else (190 if hover else 130)))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        p.setPen(QColor("#f5f6fb" if dark else "#2a2c33"))
        p.drawText(r, Qt.AlignCenter, self.text())


class Segmented(QWidget):
    """Капсула с вариантами (как переключатель в iOS/ColorOS): выбранный — синим. changed(имя варианта)."""

    changed = Signal(str)

    def __init__(self, options, current):
        super().__init__(cursor=Qt.PointingHandCursor)
        self.options = options  # [(имя, подпись)]
        self.current = current
        self.setAttribute(Qt.WA_Hover)
        self.setMouseTracking(True)
        fm = QFontMetricsF(self.font())
        self.cell = max(fm.horizontalAdvance(t) for _, t in options) + 26
        self.setFixedSize(int(self.cell * len(options)) + 4, 32)
        # плашка выбора — капля жидкости: два края на своих пружинах. Передний край убегает быстрее, задний
        # догоняет — капля вытягивается, сплющивается и с лёгким перелётом собирается на новом месте
        i = self.index(current)
        self.edges = [2 + i * self.cell, 2 + (i + 1) * self.cell]   # левый, правый край
        self.speed = [0.0, 0.0]
        self.goal = list(self.edges)
        self.stiff = [520.0, 520.0]
        self.tick = QTimer(self, interval=8, timeout=self.step)
        self.last = 0.0

    def index(self, name):
        return next((i for i, (n, _) in enumerate(self.options) if n == name), 0)

    def move_to(self, name, animate=True):
        i = self.index(name)
        goal = [2 + i * self.cell, 2 + (i + 1) * self.cell]
        if not animate or not self.isVisible():
            self.edges, self.speed, self.goal = list(goal), [0.0, 0.0], goal
            self.tick.stop()
            self.update()
            return
        if goal == self.goal:  # уже там (или едет туда) — ничего не начинать
            return
        right = goal[0] > self.goal[0]
        # ведущий край (по ходу движения) — жёсткая пружина, хвост — мягкая: так капля тянется
        self.stiff = [260.0, 700.0] if right else [700.0, 260.0]
        self.goal = goal
        self.last = time.monotonic()
        if not self.tick.isActive():
            self.tick.start()

    def step(self):
        now = time.monotonic()
        dt = min(1 / 30, now - self.last)
        self.last = now
        moving = False
        for k in (0, 1):
            w = self.stiff[k] ** 0.5
            zeta = 0.62  # чуть меньше 1 — с перелётом, «пружинит»
            # несколько мелких шагов — пружина устойчива при любом dt
            for _ in range(4):
                h = dt / 4
                acc = -self.stiff[k] * (self.edges[k] - self.goal[k]) - 2 * zeta * w * self.speed[k]
                self.speed[k] += acc * h
                self.edges[k] += self.speed[k] * h
            if abs(self.edges[k] - self.goal[k]) > 0.05 or abs(self.speed[k]) > 0.5:
                moving = True
        if not moving:
            self.edges, self.speed = list(self.goal), [0.0, 0.0]
            self.tick.stop()
        self.update()

    def set_quiet(self, name):
        self.current = name
        self.move_to(name, animate=self.isVisible())

    def showEvent(self, event):
        super().showEvent(event)
        self.move_to(self.current, animate=False)

    def mouseReleaseEvent(self, event):
        i = int((event.position().x() - 2) // self.cell)
        if 0 <= i < len(self.options) and self.options[i][0] != self.current:
            self.current = self.options[i][0]
            self.move_to(self.current)
            self.changed.emit(self.current)

    def mouseMoveEvent(self, event):
        self.update()

    def leaveEvent(self, event):
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self.isEnabled():
            p.setOpacity(0.4)
        dark = bool(self.window().dark)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(255, 255, 255, 60 if dark else 170), 1))
        p.setBrush(QColor(255, 255, 255, 25 if dark else 130))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        mouse = self.mapFromGlobal(QCursor.pos()) if self.underMouse() else None
        full_h = r.height() - 4
        cells = [QRectF(2 + i * self.cell, 2, self.cell, full_h) for i in range(len(self.options))]
        for i, cell in enumerate(cells):  # наведение — мягкая подсветка под мышью
            if mouse is not None and cell.contains(QPointF(mouse)) and self.options[i][0] != self.current:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(255, 255, 255, 30 if dark else 120))
                p.drawRoundedRect(cell, cell.height() / 2, cell.height() / 2)
        # капля: вытянулась — сплющивается по высоте (объём сохраняется), чуть светлее в движении
        left, right = self.edges
        # у стенки капсулы капля не вылезает, а упирается и сжимается, как жидкость
        left, right = max(2.0, left), min(self.width() - 2.0, right)
        if right - left < full_h:
            left = min(left, self.width() - 2.0 - full_h)
            right = max(right, left + full_h)
        width = max(full_h, right - left)
        stretch = max(0.0, width / self.cell - 1)
        h = full_h * max(0.72, 1 - 0.22 * stretch)
        drop = QRectF(left, 2 + (full_h - h) / 2, width, h)
        path = QPainterPath()
        path.addRoundedRect(drop, h / 2, h / 2)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(skins.ACCENT).lighter(100 + int(min(1.0, stretch) * 18)))
        p.drawPath(path)
        # текст: обычный везде, белый — ровно там, где сейчас капля (перетекает с буквы на букву)
        p.setPen(QColor("#f5f6fb" if dark else "#2a2c33"))
        for cell, (_, text) in zip(cells, self.options):
            p.drawText(cell, Qt.AlignCenter, text)
        p.setClipPath(path)
        p.setPen(QColor("white"))
        for cell, (_, text) in zip(cells, self.options):
            p.drawText(cell, Qt.AlignCenter, text)


@lru_cache(maxsize=8)
def _scene(w, h, dark):
    """Фон превью: мягкий градиент с цветными пятнами (как обои), чтобы было видно стекло."""
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    u, v = x / w, y / h
    if dark:
        img = np.dstack([0.10 + 0.12 * v, 0.10 + 0.06 * u, 0.20 + 0.10 * (1 - u)])
        blobs = [(0.18, 0.30, (0.95, 0.42, 0.30)), (0.80, 0.25, (0.30, 0.55, 1.0)), (0.55, 0.85, (0.75, 0.35, 0.95))]
    else:
        img = np.dstack([0.93 - 0.08 * v, 0.88 + 0.06 * u, 0.92 + 0.05 * v])
        blobs = [(0.15, 0.25, (1.0, 0.55, 0.42)), (0.85, 0.30, (0.35, 0.70, 1.0)), (0.55, 0.90, (0.98, 0.80, 0.30))]
    for bx, by, color in blobs:
        a = np.exp(-(((u - bx) / 0.22) ** 2 + ((v - by) / 0.30) ** 2))[..., None]
        img = img * (1 - a * 0.85) + np.array(color, np.float32) * a * 0.85
    return np.clip(img * 255, 0, 255).astype(np.uint8)


class FlowGrid(QWidget):
    """Сетка карточек одного размера на всю ширину: колонок — сколько влезает, лишнее место делится
    поровну между колонками (справа не остаётся пустоты). Раскладка пересчитывается при смене ширины."""

    def __init__(self, cell_w, cell_h, gap, right=0):
        super().__init__()
        self.cell_w, self.cell_h, self.gap, self.right = cell_w, cell_h, gap, right
        self.items = []
        self._laid = None

    def add(self, w):
        w.setParent(self)
        self.items.append(w)
        self._laid = None
        self.relayout()

    def columns(self, width):
        return max(1, (width + self.gap) // (self.cell_w + self.gap))

    def relayout(self):
        width = max(self.cell_w, self.width() - self.right)
        cols = self.columns(width)
        key = (width, cols, len(self.items))
        if key == self._laid:
            return
        self._laid = key
        step_x = (width - self.cell_w) / (cols - 1) if cols > 1 else 0
        for i, w in enumerate(self.items):
            r, c = divmod(i, cols)
            w.move(round(c * step_x), r * (self.cell_h + self.gap))
            w.show()
        rows = (len(self.items) + cols - 1) // cols
        self.setMinimumHeight(max(0, rows * (self.cell_h + self.gap) - self.gap))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.relayout()


class Preview(QWidget):
    """Живое превью: скрытая копия виджета на красивом фоне, с настоящим стеклом.
    Каталог раз в секунду её фотографирует — часы идут, нагрузка и погода настоящие."""

    W, H = 222, 112

    def __init__(self, cls):
        super().__init__()
        self.setFixedSize(self.W, self.H)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.cls = cls
        self.copy = None
        self.key = None
        self.pix = None
        self.bg = None

    def ready(self):
        """Копия виджета уже есть — обновить её дёшево (снимок ~1–2 мс). Нет — создавать дорого (20–350 мс)."""
        return self.copy is not None

    def refresh(self, dark):
        if self.copy is None:
            self.copy = self.cls()
            self.copy.preview = True  # превью — всегда обычного размера (настройка «Размер» — у самого виджета)
            if self.copy.base:
                QWidget.setFixedSize(self.copy, *self.copy.base)
        w = self.copy
        w.sync_preview()
        if w.layout():  # у метеочасов раскладки нет — они рисуются сами
            w.layout().activate()
            w.adjustSize()
        if (w.width(), w.height(), dark) != self.key:
            self.key = (w.width(), w.height(), dark)
            self._build(dark)
        self.pix = w.grab()
        # куда класть снимок — запоминаем: после release() копии нет, а последний кадр каталог показывает
        self.dst = QRectF(self.ox * self.s, self.oy * self.s, w.width() * self.s, w.height() * self.s)
        self.compose()
        self.update()

    def compose(self):
        """Фон + уменьшенный снимок, скруглённые — одной картинкой: прокрутка каталога рисует превью каждый кадр,
        а сглаженное уменьшение снимка — дорогое; делаем его раз на обновление (раз в 2 с), а не на кадр."""
        if self.bg is None:
            self.final = None
            return
        dpr = self.devicePixelRatioF()
        pix = QPixmap(int(self.W * dpr), int(self.H * dpr))
        pix.setDevicePixelRatio(dpr)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self.W, self.H), 14, 14)
        p.setClipPath(path)
        p.drawImage(QRectF(0, 0, self.W, self.H), self.bg)
        if self.pix is not None and getattr(self, "dst", None) is not None:
            p.drawPixmap(self.dst, self.pix, QRectF(self.pix.rect()))
        p.end()
        self.final = pix

    def release(self):
        """Каталог закрыли: копия виджета не нужна. Она — целый виджет со своими таймерами, запросами
        погоды и стеклом; 25 таких копий, оставленных жить, — десятки МБ и лишняя работа в фоне.
        Последний кадр (pix, bg) остаётся — при открытии каталог сразу его покажет и обновит."""
        if self.copy is not None:
            self.copy.deleteLater()
            self.copy = None
            self.key = None

    def _build(self, dark):
        """Стекло копии — из фона превью (масштаб: виджет целиком влезает в карточку)."""
        w = self.copy
        self.s = s = min((self.W - 10) / w.width(), (self.H - 6) / w.height(), 0.8)
        BW, BH = int(self.W / s) + 1, int(self.H / s) + 1
        scene = _scene(BW, BH, dark)
        self.ox, self.oy = (BW - w.width()) / 2, (BH - w.height()) / 2
        card = w.card()
        src = glass._crop(scene, int(self.ox) + card.x() - glass.PAD, int(self.oy) + card.y() - glass.PAD,
                          card.width() + 2 * glass.PAD, card.height() + 2 * glass.PAD)
        app = config.section("app")
        w.glass_img, d = glass.render(src, card.width(), card.height(), RADIUS, "dark" if dark else "light",
                                      app.get("fill"), app.get("blur"), app.get("haze"))
        w.shadow_img = glass.render_shadow(card.width(), card.height(), RADIUS, SHADOW, d)
        w.set_dark(d)
        rgba = np.dstack([scene, np.full(scene.shape[:2], 255, np.uint8)])
        self.bg = glass.to_image(rgba).scaled(self.W, self.H, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)

    def paintEvent(self, event):
        if getattr(self, "final", None) is None:
            self.compose()
            if self.final is None:
                return
        p = QPainter(self)
        p.drawPixmap(0, 0, self.final)
        p.end()


def css_color(text):
    """«rgba(255,255,255,20)» / «#rrggbb» из glass.THEMES -> QColor."""
    text = text.strip()
    if text.startswith("rgba("):
        r, g, b, a = (int(float(v)) for v in text[5:-1].split(","))
        return QColor(r, g, b, a)
    return QColor(text)


class CardText(QWidget):
    """Значок, название и описание карточки каталога (две строки, лишнее — многоточием; целиком — в подсказке).
    Рисуется один раз в картинку под ширину и тему — при прокрутке только копируется."""

    def __init__(self, icon, title, text):
        super().__init__()
        self.icon, self.title, self.text = icon, title, text
        self.name_font = QFont("Segoe UI")
        self.name_font.setPixelSize(15)
        self.name_font.setWeight(QFont.DemiBold)
        self.desc_font = QFont("Segoe UI")
        self.desc_font.setPixelSize(12)
        self.line = QFontMetricsF(self.desc_font).lineSpacing()
        self.setFixedHeight(22 + 1 + int(self.line * 2) + 2)
        self.setToolTip(text)
        self._key, self._pix = None, None

    def paintEvent(self, event):
        dark = bool(self.window().dark)
        dpr = self.devicePixelRatioF()
        key = (self.width(), dark, dpr)
        if key != self._key:
            self._key = key
            pix = QPixmap(int(self.width() * dpr), int(self.height() * dpr))
            pix.setDevicePixelRatio(dpr)
            pix.fill(Qt.transparent)
            p = QPainter(pix)
            p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
            th = glass.THEMES[dark]
            p.drawPixmap(QRectF(0, 0, 22, 22), self.icon, QRectF(self.icon.rect()))
            p.setFont(self.name_font)
            p.setPen(QColor(th["fg"]))
            p.drawText(QRectF(30, 0, self.width() - 30, 22), Qt.AlignLeft | Qt.AlignVCenter, self.title)
            p.setFont(self.desc_font)
            p.setPen(QColor(th["dim"]))
            fm, width = QFontMetricsF(self.desc_font), self.width()
            words, first = self.text.split(), ""
            while words and fm.horizontalAdvance((first + " " + words[0]).strip()) <= width:
                first = (first + " " + words.pop(0)).strip()
            if not first and words:  # одно слово шире строки
                first = words.pop(0)
            y = 23
            p.drawText(QRectF(0, y, width, self.line), Qt.AlignLeft | Qt.AlignVCenter, first)
            if words:
                p.drawText(QRectF(0, y + self.line, width, self.line), Qt.AlignLeft | Qt.AlignVCenter,
                           fm.elidedText(" ".join(words), Qt.ElideRight, width))
            p.end()
            self._pix = pix
        p = QPainter(self)
        p.drawPixmap(0, 0, self._pix)
        p.end()


class Card(QFrame):
    """Карточка виджета: живое превью, название, описание, тумблер. Клик по карточке — тоже переключает."""

    def __init__(self, cls, on_click):
        # фон рисуется сам (paintEvent), а не стилем QFrame#card: стиль со скруглением — самое дорогое
        # в кадре прокрутки
        super().__init__(objectName="tile", cursor=Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover)
        self.on_click = on_click
        self._bg_key, self._bg = None, None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 14, 12)
        lay.setSpacing(10)
        self.preview = Preview(cls)
        lay.addWidget(self.preview, alignment=Qt.AlignHCenter)
        row = QHBoxLayout()
        row.setContentsMargins(6, 0, 0, 0)
        # значок, название и описание — одна готовая картинка (CardText), а не QLabel'ы со стилем:
        # при прокрутке каталога каждый кадр перерисовывает ~20 видимых карточек, по 0.7 мс каждая было
        row.addWidget(CardText(icons.app_icon(cls.key, 22), cls.title, cls.description), 1)
        self.switch = Switch()
        self.switch.setToolTip(tr("Включить или выключить этот виджет на рабочем столе"))
        self.switch.clicked.connect(lambda: on_click())  # clicked передаёт bool — его не пускаем дальше
        row.addWidget(self.switch, alignment=Qt.AlignVCenter)
        lay.addLayout(row)

    def enterEvent(self, event):
        self.update()

    def leaveEvent(self, event):
        self.update()

    def paintEvent(self, event):
        """Фон карточки — как был стилем (заливка, тонкая кромка, скругление 20), но готовой картинкой."""
        dark = bool(self.window().dark)
        hover = self.underMouse()
        dpr = self.devicePixelRatioF()
        key = (self.size().toTuple(), dark, hover, dpr)
        if key != self._bg_key:
            self._bg_key = key
            th = glass.THEMES[dark]
            pix = QPixmap(int(self.width() * dpr), int(self.height() * dpr))
            pix.setDevicePixelRatio(dpr)
            pix.fill(Qt.transparent)
            p = QPainter(pix)
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(QPen(css_color(th["cardline"]), 1))
            p.setBrush(css_color(th["cardhover" if hover else "card"]))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 20, 20)
            p.end()
            self._bg = pix
        p = QPainter(self)
        p.drawPixmap(0, 0, self._bg)
        p.end()

    def mousePressEvent(self, event):
        event.accept()  # не таскать окно за карточку

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.switch.toggle()
            self.on_click()


class Catalog(DesktopWidget):
    key = "catalog"
    title = tr("Каталог")
    keep_bottom = False  # окно программы — обычное, его можно поднимать

    def __init__(self):
        super().__init__()
        # своя тема у каталога не задана — та же, что выбрана для всех виджетов («Тема» внизу каталога)
        self.cfg.setdefault("theme", config.section("app").get("theme", "auto"))
        self.setWindowTitle(tr("Виджеты"))
        self.setWindowIcon(make_icon())
        self.instances = {}
        self.cards = {}
        self.quitting = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 18, 22)
        lay.setSpacing(14)
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(0)
        title = QLabel(tr("Виджеты"))
        title.setStyleSheet("font-size: 26px; font-weight: 600;")
        sub = QLabel(tr("Liquid Acrylic · виджет таскается мышью, правый клик по нему — меню"), objectName="dim")
        sub.setStyleSheet("font-size: 12px;")
        titles.addWidget(title)
        titles.addWidget(sub)
        # заголовок и подпись у разделов разной длины — место под них постоянное, по самому длинному:
        # иначе при переключении разделов вкладки справа от заголовка «убегают»
        big, small = QFont("Segoe UI Semibold"), QFont("Segoe UI")
        big.setPixelSize(26)
        small.setPixelSize(12)
        names = (tr("Виджеты"), tr("Остров"), tr("Погода"), tr("Темы"))
        width = max([QFontMetricsF(big).horizontalAdvance(t) for t in names] +
                    [QFontMetricsF(small).horizontalAdvance(tr(t)) for t in self.SECTION_SUBS.values()])
        for w in (title, sub):
            w.setFixedWidth(int(width) + 12)
        head.addLayout(titles)
        head.addSpacing(18)
        # одно приложение — три раздела: виджеты, остров, погода (место — общее для виджетов и острова)
        self.section_bar = Segmented([("widgets", tr("Виджеты")), ("island", tr("Остров")), ("weather", tr("Погода")),
                                      ("themes", tr("Темы"))],
                                     "widgets")
        self.section_bar.setToolTip(tr("Разделы настроек: виджеты, динамический остров, погода и место, темы"))
        self.section_bar.changed.connect(self.show_section)
        head.addWidget(self.section_bar, alignment=Qt.AlignTop)
        head.addStretch()
        # появляется в шапке, когда на GitHub вышла новая версия (её находит updater раз в 6 часов)
        self.update_btn = PillButton(tr("Установить обновление"), accent=True)
        self.update_btn.setToolTip(tr("Вышла новая версия. Скачается и встанет поверх — виджеты и настройки останутся."))
        self.update_btn.hide()
        head.addWidget(self.update_btn, alignment=Qt.AlignTop)
        head.addSpacing(8)
        self.title_label, self.sub_label = title, sub
        # язык — в шапке: в нижней строке настроек ему не хватало места (окно расползалось вширь)
        lang_tip = tr("Язык меняется перезапуском программы (пара секунд).")
        self.lang = Segmented(list(LANGS), LANG)
        self.lang.setToolTip(lang_tip)
        self.lang.changed.connect(self.set_lang)
        head.addWidget(self.lang, alignment=Qt.AlignTop)
        head.addSpacing(8)
        support_btn = TitleButton("heart", tr("Поддержать автора"))
        support_btn.setToolTip(tr("Поддержать автора") + "\n"
                               + tr("Откроет страницу проекта на Boosty. Программа бесплатная — это по желанию."))
        support_btn.clicked.connect(bugreport.support)
        head.addWidget(support_btn, alignment=Qt.AlignTop)
        head.addSpacing(6)
        bug_btn = TitleButton("bug", tr("Сообщить о баге"))
        bug_btn.setToolTip(tr("Сообщить о баге") + "\n" + tr("Откроет наш Telegram-канал — напиши в комментариях, что случилось."))
        bug_btn.clicked.connect(lambda: self.report_bug(bug_btn))
        head.addWidget(bug_btn, alignment=Qt.AlignTop)
        head.addSpacing(6)
        minimize = TitleButton("min")
        minimize.setToolTip(tr("Свернуть"))
        minimize.clicked.connect(self.showMinimized)
        head.addWidget(minimize, alignment=Qt.AlignTop)
        close = TitleButton("close")
        close.setToolTip(tr("Закрыть (виджеты продолжат работать, значок — в трее)"))
        close.clicked.connect(self.close)
        head.addWidget(close, alignment=Qt.AlignTop)
        lay.addLayout(head)

        # карточки — в прокрутке: виджетов много, окно не должно вылезать за экран
        content = FlowGrid(244, 196, 12, right=6)
        content.setAttribute(Qt.WA_TranslucentBackground)
        for cls in widgets.ALL:
            card = Card(cls, lambda c=cls: self.toggle(c))
            card.setFixedSize(244, 196)
            content.add(card)
            self.cards[cls.key] = card
        self.scroll = QScrollArea(widgetResizable=True, frameShape=QFrame.NoFrame)
        self.scroll.setWidget(content)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet(SCROLL_STYLE)
        self.scroll.viewport().setAutoFillBackground(False)
        rows = (len(widgets.ALL) + COLUMNS - 1) // COLUMNS
        avail = (self.screen() or QApplication.primaryScreen()).availableGeometry().height()
        self.scroll.setFixedHeight(min(rows * 208 - 12, avail - 320))
        # ширина — по окну (её задаёт нижняя панель настроек): карточки раскладываются на всю ширину, см. FlowGrid
        self.scroll.setMinimumWidth(COLUMNS * 256 - 12 + 6 + 10)
        # крутят колёсико — превью не трогаем; догоняют, когда прокрутка остановилась
        self.scroll_rest = QTimer(self, singleShot=True, interval=150, timeout=self.refresh_previews)
        self.scroll.verticalScrollBar().valueChanged.connect(lambda _: self.scroll_rest.start())
        page = QWidget()
        page.setAttribute(Qt.WA_TranslucentBackground)
        page_lay = QVBoxLayout(page)
        page_lay.setContentsMargins(0, 0, 0, 0)
        page_lay.setSpacing(14)
        page_lay.addWidget(self.scroll)

        # настройки приложения
        bar = QFrame(objectName="card")
        rows = QVBoxLayout(bar)
        rows.setContentsMargins(16, 10, 10, 10)
        rows.setSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(12)
        rows.addLayout(row)
        glass_row = QHBoxLayout()  # вторая строка — стекло: заливка, размытие, замутнение
        glass_row.setSpacing(12)
        rows.addLayout(glass_row)
        auto_label = QLabel(tr("Запускать с Windows"))
        auto_label.setToolTip(tr("Виджеты сами запускаются при входе в Windows — тихо, значком в трее."))
        row.addWidget(auto_label)
        self.autostart = Switch()
        self.autostart.setToolTip(auto_label.toolTip())
        self.autostart.set_quiet(autostart_enabled())
        self.autostart.toggled.connect(set_autostart)
        row.addWidget(self.autostart)
        row.addSpacing(10)
        shots = QLabel(tr("Видно на скриншотах всегда"))
        shots.setToolTip(tr("Обычно виджеты сами показываются при PrtSc и Win+Shift+S.\n"
                         "Включи, если снимаешь кнопкой в «Ножницах», OBS или записью экрана —\n"
                         "тогда стекло берётся из обоев, а не живое."))
        row.addWidget(shots)
        self.on_shots = Switch()
        self.on_shots.setToolTip(shots.toolTip())
        self.on_shots.set_quiet(bool(config.section("app").get("on_screenshots")))
        self.on_shots.toggled.connect(self.set_on_screenshots)
        row.addWidget(self.on_shots)
        row.addSpacing(10)
        self.under_label = QLabel(tr("Под ярлыками"))
        self.under_label.setToolTip(tr("Вкл — виджеты как обои: ярлыки и папки лежат на них.\n"
                                    "Выкл — обычные окна на рабочем столе: под всеми окнами, но над ярлыками.\n"
                                    "С Wallpaper Engine не работает: его видео закрывает всё под ярлыками —\n"
                                    "тогда виджеты остаются обычными окнами."))
        row.addWidget(self.under_label)
        child_label = QLabel(tr("В рабочем столе (тест)"))
        child_label.setToolTip(tr("Вкл — виджеты становятся частью рабочего стола, как ярлыки: Win+D и окна других программ их не двигают и не прячут. Стекло тогда берётся из обоев (живого акрила нет). Пока проверяем — может глючить."))
        self.desktop_child = Switch()
        self.desktop_child.setToolTip(child_label.toolTip())
        self.desktop_child.set_quiet(bool(config.section("app").get("desktop_child", False)))
        self.desktop_child.toggled.connect(self.set_desktop_child)
        self.under_icons = Switch()
        self.under_icons.setToolTip(self.under_label.toolTip())
        self.under_icons.set_quiet(config.section("app").get("under_icons", False))
        self.under_icons.toggled.connect(self.set_under_icons)
        row.addWidget(self.under_icons)
        row.addSpacing(10)
        row.addWidget(child_label)
        row.addWidget(self.desktop_child)
        row.addSpacing(10)
        game_tip = tr("Пока открыта игра или видео на весь экран, виджеты замирают на всех мониторах:\n"
                      "не рисуют, не снимают стекло и не опрашивают датчики, пинг и плеер.\n"
                      "Закрыл или свернул игру — сразу оживают со свежими данными.\n"
                      "Выкл — замирают только виджеты на мониторе с игрой, на втором видны пинг и температура.")
        game = QLabel(tr("Игровой режим"))
        game.setToolTip(game_tip)
        row.addWidget(game)
        self.game_pause = Switch()
        self.game_pause.setToolTip(game_tip)
        self.game_pause.set_quiet(config.section("app").get("game_pause", True))
        self.game_pause.toggled.connect(self.set_game_pause)
        row.addWidget(self.game_pause)
        app = config.section("app")
        self.glass_labels = {}
        for key, text, lo, hi, default, unit, tip in (
                ("fill", tr("Заливка"), 20, 100, 62, "%",
                 tr("Насколько плотное стекло у всех виджетов (и живое, и изморозь).\n"
                 "100% — сплошная плитка, ничего не просвечивает; 20% — почти прозрачное.")),
                ("blur", tr("Размытие"), 0, 10, glass.BLUR, "",
                 tr("Насколько размыто то, что под стеклом.\n"
                 "С акрилом Windows: 0 — без размытия, 1–4 — лёгкое размытие, 5–10 — полный акрил.\n"
                 "Без него: 0 — видно чётко, 10 — сплошные мягкие пятна.")),
                ("haze", tr("Замутнение"), glass.HAZE_MIN, 100, 50, "%",
                 tr("Сколько серой (тёмное стекло) или молочной (светлое) дымки поверх размытого.\n"
                 "0 — чистые цвета, 100 — почти сплошная дымка.\n"
                 "В минусе — ещё и без приглушения: под стеклом сочные, яркие цвета."))):
            value = app.get(key, default)
            label = QLabel(f"{text} {value}{unit}")
            label.setToolTip(tip)
            glass_row.addWidget(label)
            slider = QSlider(Qt.Horizontal, minimum=lo, maximum=hi, value=value)
            slider.setFixedWidth(140)
            slider.setToolTip(tip)
            slider.valueChanged.connect(lambda v, k=key: self.set_glass(k, v))
            glass_row.addWidget(slider)
            glass_row.addSpacing(14)
            self.glass_labels[key] = (label, text, unit)
        theme_tip = (tr("Тема всех виджетов разом.\n"
                     "Авто — каждый виджет сам по цвету обоев под ним: над светлым — светлое стекло и тёмный текст,\n"
                     "над тёмным — тёмное стекло и белый текст.\n"
                     "Тёмная / Светлая — у всех одинаково. Одному виджету — в его меню (правый клик → Стекло)."))
        theme_label = QLabel(tr("Тема"))
        theme_label.setToolTip(theme_tip)
        glass_row.addWidget(theme_label)
        self.theme_all = Segmented([("auto", tr("Авто")), ("dark", tr("Тёмная")), ("light", tr("Светлая"))],
                                   app.get("theme", "auto"))
        self.theme_all.setToolTip(theme_tip)
        self.theme_all.changed.connect(self.set_theme_all)
        glass_row.addWidget(self.theme_all)
        glass_row.addSpacing(14)
        acrylic = QLabel(tr("Акрил"))
        acrylic.setToolTip(tr("Вкл — настоящий акрил: под виджетом размыто то, что за ним (и живые обои),\n"
                           "«Размытие» и «Замутнение» его настраивают; «Заливка» не нужна — стекло сплошное.\n"
                           "Выкл — простая полупрозрачная изморозь, её плотность — «Заливка»."))
        glass_row.addWidget(acrylic)
        self.acrylic = Switch()
        self.acrylic.setToolTip(acrylic.toolTip())
        self.acrylic.set_quiet(app.get("acrylic", True))
        self.acrylic.toggled.connect(self.set_acrylic)
        glass_row.addWidget(self.acrylic)
        glass_row.addStretch()
        row.addStretch()
        self.move_btn = PillButton(tr("Двигать виджеты"))
        self.move_btn.setToolTip(tr("Виджеты вшиты под ярлыки рабочего стола — мышь до них не достаёт.\n"
                                 "Нажми, чтобы поднять их наверх: таскать, писать в заметках, правый клик."))
        self.move_btn.clicked.connect(lambda: self.set_editing(not activity.editing))
        row.addWidget(self.move_btn)
        quit_btn = PillButton(tr("Выйти из программы"))
        quit_btn.setToolTip(tr("Закрыть программу совсем: виджеты уберутся с рабочего стола, значок в трее пропадёт."))
        quit_btn.clicked.connect(self.quit)
        row.addWidget(quit_btn)
        page_lay.addWidget(bar)
        self.stack = QStackedWidget()
        self.stack.setAttribute(Qt.WA_TranslucentBackground)
        self.stack.addWidget(page)
        self.pages = {"widgets": page}
        for name, sec in (("island", sections.IslandPage(Switch, Segmented)),
                          ("weather", sections.WeatherPage(Switch, Segmented, PillButton)),
                          ("themes", sections.ThemesPage())):
            holder = QScrollArea(widgetResizable=True, frameShape=QFrame.NoFrame)
            holder.setWidget(sec)
            holder.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            holder.setStyleSheet(SCROLL_STYLE)
            holder.viewport().setAutoFillBackground(False)
            self.stack.addWidget(holder)
            self.pages[name] = holder
        lay.addWidget(self.stack)
        self.tray = None
        self.tray_move = None
        self.told_tray = False

        for cls in widgets.ALL:
            if config.section(cls.key).get("visible"):
                try:
                    self.toggle(cls)
                except Exception as _err:  # один сломанный виджет (испорченные настройки, нет нужной службы Windows)
                    applog.error("main.Catalog.__init__", _err)
                    self.instances.pop(cls.key, None)
                    self.cards[cls.key].switch.set_quiet(False)
            else:
                self.cards[cls.key].switch.set_quiet(False)

        # превью обновляются раз в секунду, только пока каталог открыт
        self.preview_timer = QTimer(self, interval=2000, timeout=self.refresh_previews)  # чаще — зря грузит процессор
        self.shadow_ready.connect(self.on_shadow)
        # тема задана — оформление на все сотни элементов окна (~240 мс) сейчас, пока окно скрыто,
        # а не рывком при первом открытии
        if self.cfg.get("theme") in ("dark", "light"):
            self.set_dark(self.cfg["theme"] == "dark")
        self.build_queue = []
        self.build_timer = QTimer(self, interval=16, timeout=self.build_next)

    shadow_ready = Signal(object, object)

    def make_shadow(self, card, dark):
        """Тень под окном каталога — ~350 мс (окно большое): считаем в фоне, пока — прежняя или без неё."""
        want = (card.width(), card.height(), bool(dark))
        if getattr(self, "_shadow_want", None) == want:
            return
        self._shadow_want = want

        def work():
            img = glass.render_shadow(want[0], want[1], RADIUS, SHADOW, want[2])
            try:
                self.shadow_ready.emit(want, img)
            except RuntimeError:  # окно уже закрыли
                pass
        threading.Thread(target=work, daemon=True).start()

    def on_shadow(self, want, img):
        if want == getattr(self, "_shadow_want", None):
            self.shadow_img = img
            self.update()

    def rebuild_now(self):
        """Каталог большой: стекло под ним — ~80 мс (у виджета ~12). Считать его на каждом движении мыши
        в главном потоке — окно едет рывками. Пока тащат — в фоне, заказы склеиваются; окно едет плавно."""
        self.rebuild()

    SECTION_SUBS = {
        "widgets": "Liquid Acrylic · виджет таскается мышью, правый клик по нему — меню",
        "island": "Динамический остров вверху экрана: вид, стекло и что на нём показывать",
        "weather": "Место и сайт погоды — для виджетов погоды и пилюли острова",
        "themes": "Цвет стекла и кнопок — у всех виджетов и острова сразу",
    }

    def show_section(self, name):
        """Раздел окна: «Виджеты» (каталог), «Остров», «Погода»."""
        if name not in self.pages:
            return
        self.section_bar.set_quiet(name)
        old, new = self.stack.currentWidget(), self.pages[name]
        self.title_label.setText({"widgets": tr("Виджеты"), "island": tr("Остров"), "weather": tr("Погода"),
                                  "themes": tr("Темы")}[name])
        self.sub_label.setText(tr(self.SECTION_SUBS[name]))
        if new is not old:
            order = list(self.pages.values())
            self.stack.setCurrentWidget(new)
            if self.isVisible():
                self.slide_in(new, 1 if order.index(new) > order.index(old) else -1)
            for w in (self.title_label, self.sub_label):  # заголовок тоже приезжает вместе со страницей
                if self.isVisible():
                    self.slide_in(w, 1 if order.index(new) > order.index(old) else -1, 18, 260)
        if name == "widgets":
            self.refresh_previews()

    def slide_in(self, w, direction, shift=40, ms=340):
        """Страница въезжает со стороны выбранного раздела и проявляется — вслед за каплей переключателя."""
        prev = getattr(w, "_slide", None)
        if prev is not None:
            prev.stop()
            prev.finished.emit()
        eff = QGraphicsOpacityEffect(w)
        w.setGraphicsEffect(eff)
        base = w.pos()
        anim = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=ms, easingCurve=QEasingCurve.OutCubic)

        def frame(t):
            eff.setOpacity(min(1.0, t * 1.4))
            w.move(base.x() + round(shift * direction * (1 - t)), base.y())

        def done():
            w._slide = None
            w.setGraphicsEffect(None)
            w.move(base)
        anim.valueChanged.connect(frame)
        anim.finished.connect(done)
        w._slide = anim
        frame(0.0)
        anim.start()

    def mouseReleaseEvent(self, event):
        was = self._drag is not None
        super().mouseReleaseEvent(event)
        if was:
            self.rebuild()  # отпустили — свежее стекло на новом месте

    def refresh_previews(self):
        if self._drag is not None:  # тащат окно — превью подождут, иначе секундные рывки
            return
        if self.scroll_rest.isActive():
            return
        # только карточки, которые сейчас видно в прокрутке — остальные не рисуем зря.
        # Готовые — обновить сразу (дёшево); новые — в очередь, по одной между кадрами (иначе зависание на секунды)
        self.build_queue = []
        for card in self.cards.values():
            if card.visibleRegion().isEmpty():
                continue
            if card.preview.ready():
                card.preview.refresh(bool(self.dark))
            else:
                self.build_queue.append(card)
        if self.build_queue and not self.build_timer.isActive():
            self.build_timer.start()

    def build_next(self):
        """Одно новое превью за раз; окно между ними успевает отрисоваться и ответить мыши."""
        while self.build_queue:
            card = self.build_queue.pop(0)
            if self.isVisible() and not self.isMinimized() and self._drag is None                     and not card.visibleRegion().isEmpty() and not card.preview.ready():
                card.preview.refresh(bool(self.dark))
                break
        if not self.build_queue:
            self.build_timer.stop()

    def showEvent(self, event):
        super().showEvent(event)
        # окно без рамки, но сворачивается как обычное: кнопкой, кликом по значку на панели задач, Win+D
        hwnd = int(self.winId())
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_STYLE)
        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_STYLE, style | WS_MINIMIZEBOX | WS_SYSMENU)
        # превью — после плавного появления окна (260 мс): новое превью строится 20–350 мс и рвало анимацию;
        # пока — последние кадры превью, они сохраняются между открытиями
        QTimer.singleShot(350, self.refresh_previews)
        self.preview_timer.start()
        self.update_under_label()

    def update_under_label(self):
        """Подпись у «Под ярлыками»: с Wallpaper Engine режим не работает — так и пишем."""
        # коротко: длинная подпись раздвигала окно каталога шире сетки; пояснение — в подсказке и серым цветом
        self.under_label.setText(tr("Под ярлыками") + (" *" if activity.wpe else ""))
        self.under_label.setObjectName("dim" if activity.wpe else "")  # серым: с Wallpaper Engine не работает
        self.under_label.style().unpolish(self.under_label)
        self.under_label.style().polish(self.under_label)

    def release(self):
        """Окно убрали с глаз: отпустить превью и своё стекло (окно большое — снимок под ним,
        стекло и картинка рамки вместе с чёткостью экрана — это десятки МБ). При показе всё соберётся заново."""
        self.preview_timer.stop()
        for card in self.cards.values():
            card.preview.release()
        self.glass_img = self.last_src = self._chrome_pix = None
        self._chrome_key = None
        # стекло отпустили — значит и пометку «уже нарисовано» снять: иначе при следующем показе окно считало,
        # что матовое стекло на месте, не рисовало его заново и открывалось прозрачным (через раз)
        self.flat_key = None
        self.due, self.same = 0.0, 0  # покажут снова — стекло снять сразу

    def hideEvent(self, event):
        self.release()
        super().hideEvent(event)

    def changeEvent(self, event):
        # свёрнуто — превью не обновляем
        if event.type() == QEvent.WindowStateChange:
            if self.isMinimized():
                self.release()
            elif self.isVisible():
                self.refresh_previews()
                self.preview_timer.start()
        super().changeEvent(event)

    # ---------- окно ----------

    def apply_flags(self):
        # главное окно приложения: есть на панели задач, сворачивается; рамку рисуем сами
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window | Qt.WindowMinimizeButtonHint)

    # окно настроек — сплошное, без акрила (пользователь: «убери акрил в этих настройках»): не снимает экран,
    # не прячется от скриншотов и не зависит от того, что за ним (чёрные обои давали чёрное окно)
    def flat_mode(self):
        return True

    def update_flat(self):
        card = self.card()
        theme = self.cfg.get("theme", "auto")
        dark = self.auto_dark() if theme == "auto" else theme == "dark"
        if self.flat_key != (card.size(), dark, "solid"):
            self.flat_key = (card.size(), dark, "solid")
            self.glass_img = glass.render_flat(card.width(), card.height(), RADIUS, dark, 100)
            # тень огромного окна — ~250 мс: в фоне (make_shadow), а не здесь — это звалось прямо при показе,
            # и все 250 мс Windows показывало старый кадр окна (каталог «открывался, пропадал и открывался»)
            self.make_shadow(card, dark)
            self.set_dark(dark)
            self.update()

    @staticmethod
    def auto_dark():
        """Тема «Авто» у окна: как у Windows (тёмный режим приложений)."""
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
                return not winreg.QueryValueEx(k, "AppsUseLightTheme")[0]
        except OSError:
            return True

    def open(self):
        if "x" not in self.cfg:  # первый раз — по центру экрана
            self.adjustSize()
            self.move(self.screen().availableGeometry().center() - self.rect().center())
        if not self.isVisible():
            # прозрачным — ещё ДО показа: окно с прозрачностью Windows при повторном показе сперва выводит
            # последний кадр перед закрытием в полную яркость, а плавное появление (showEvent) ставит 0 уже
            # после — каталог мигал: открылся, пропал, снова открылся
            self.setWindowOpacity(0.0)
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def contextMenuEvent(self, event):
        pass

    def theme_changed(self):
        self.update()  # переключатели и ✕ берут тему у окна
        if hasattr(self, "cards") and self.isVisible():
            self.refresh_previews()  # превью — в тон окну

    def set_editing(self, on):
        """«Двигать виджеты»: поднять их наверх (обычные окна) или вшить обратно под ярлыки."""
        activity.editing = on
        self.move_btn.setText(tr("Готово") if on else tr("Двигать виджеты"))
        self.move_btn.update()
        if self.tray_move:
            self.tray_move.setText(tr("Готово (вшить виджеты)") if on else tr("Двигать виджеты"))
        for w in list(self.instances.values()):
            w.place()

    def closeEvent(self, event):
        # окно прячется в трей, виджеты остаются; выйти совсем — «Выйти из программы»
        if self.quitting:  # отказ здесь отменил бы выход: процесс остался бы висеть без части виджетов
            super().closeEvent(event)
            return
        event.ignore()
        if activity.editing:
            self.set_editing(False)  # закрыли окно — виджеты обратно под ярлыки
        # последний кадр окна — прозрачный: при следующем показе Windows сперва выводит именно его.
        # Прозрачность применяется только с отрисовкой — поэтому repaint() сразу, до hide()
        self.setWindowOpacity(0.0)
        self.repaint()
        QApplication.processEvents()
        self.hide()
        if self.tray and not self.told_tray:
            self.told_tray = True
            self.tray.showMessage(tr("Виджеты работают"), tr("Окно открывается значком в трее. "
                                  "Выйти совсем — кнопка «Выйти из программы»."), make_icon(), 4000)

    def set_lang(self, name):
        """Язык: сохранить и перезапуститься — подписи меню и списков собираются при запуске."""
        config.section("app")["lang"] = name
        config.save()
        QProcess.startDetached(sys.executable, [os.path.join(ROOT, "main.py"), "--restart"])
        self.quit()

    def set_game_pause(self, on):
        config.section("app")["game_pause"] = on
        config.save()
        for w in activity.widgets():  # прямо во время игры (виджет «поверх окон» на втором мониторе) — сразу
            w.update()

    def set_under_icons(self, on):
        """Режим: под ярлыками (как обои) или обычно (окна на рабочем столе)."""
        config.section("app")["under_icons"] = on
        config.save()
        activity.under_icons = on
        self.update_under_label()
        for w in list(self.instances.values()):
            w.place()

    def set_theme_all(self, name):
        """Тема сразу у всех виджетов (и у выключенных — когда включишь, будет такая же)."""
        config.section("app")["theme"] = name
        for cls in widgets.ALL:
            config.section(cls.key)["theme"] = name
        self.cfg["theme"] = name  # и сам каталог (у него тоже стекло) — иначе над светлыми обоями он белый
        config.save()
        for w in [self, *self.instances.values()]:
            w.last_src = None
            w.flat_key = None
            w.rebuild()
        self.refresh_previews()

    def set_desktop_child(self, on):
        """Виджеты внутри рабочего стола (desktop_host.py) — или снова отдельными окнами."""
        config.section("app")["desktop_child"] = bool(on)
        config.save()
        for w in list(self.instances.values()):
            if not w.placed:
                continue
            if not on and w.desktop_host is not None:
                w.desktop_host.detach()
            w.place()

    def set_acrylic(self, on):
        config.section("app")["acrylic"] = on
        config.save()
        for w in list(self.instances.values()):
            w.apply_backdrop(w.dark)  # выключили — убрать размытие и скругление окна
            w.flat_key = None
            if w.isVisible():
                w.setup_capture()  # живое стекло из снимков или тонировка поверх акрила

    def set_glass(self, key, value):
        """Заливка / размытие / замутнение стекла: виджеты и превью перерисовываются сразу."""
        label, text, unit = self.glass_labels[key]
        label.setText(f"{text} {value}{unit}")
        config.section("app")[key] = value
        config.save()
        for w in list(self.instances.values()):
            if w.pinned:
                w.push()
            elif w.flat_mode():
                w.update_flat()
            else:  # живой акрил: тот же снимок, но перерисовать с новыми настройками
                w.last_src = None
                w.rebuild()
        self.refresh_previews()

    def set_on_screenshots(self, on):
        config.section("app")["on_screenshots"] = on
        config.save()
        for w in QApplication.topLevelWidgets():
            if isinstance(w, DesktopWidget) and w.isVisible():
                w.setup_capture()

    # ---------- виджеты ----------

    def toggle(self, cls):
        w = self.instances.get(cls.key)
        if w:
            # «выключен» запоминаем только здесь, по клику: при выключении Windows окна закрывает система —
            # если писать это при закрытии окна, утром не откроется ни один виджет
            config.section(cls.key)["visible"] = False
            config.save()
            w.close()
            return
        w = cls(on_closed=self.closed)
        self.instances[cls.key] = w
        w.place()  # под ярлыки (или под окна, если идут живые обои)
        if self.isVisible() and hasattr(w, "first_setup"):  # включили руками — сразу спросить настройку
            w.first_setup()
        config.section(cls.key)["visible"] = True
        config.save()
        switch = self.cards[cls.key].switch
        if not switch.isChecked():  # включили не кликом (при запуске) — без анимации
            switch.set_quiet(True)

    def closed(self, w):
        if self.quitting:
            return
        if config.section(w.key).get("visible"):  # не сам пользователь (он сперва снимает visible)
            # кто закрыл виджет — в widgets.log: ловим случай, когда виджеты выключаются сами
            print(f"закрыт виджет {w.key}; стек:", file=sys.stderr)
            traceback.print_stack(limit=6, file=sys.stderr)
        self.instances.pop(w.key, None)
        # удалить окно сейчас и здесь, в главном потоке; иначе последняя ссылка может остаться
        # у фонового потока (снимок экрана, погода), и окно удалится оттуда — это вылет
        w.deleteLater()
        card = self.cards[w.key]
        if card.switch.isChecked():
            card.switch.toggle()

    def report_bug(self, button):
        bugreport.report_telegram()

    def quit(self):
        self.quitting = True
        QApplication.quit()


LOG_PATH = os.path.join(ROOT, "widgets.log")
SERVER = "DesktopWidgets-Liquid"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def setup_log():
    """Всё, что пошло не так, — в widgets.log (окна консоли нет, иначе не увидеть): см. applog.py."""
    log = applog.setup(LOG_PATH, "Виджеты", f"язык {LANG}")
    applog.line("виджеты на столе: " + bugreport.visible_widgets())
    return log


def already_running():
    """Уже запущено? Тогда передать той копии команду: по умолчанию «открыть окно»;
    main.py --cmd snap — показать виджеты снимкам экрана на несколько секунд; --cmd edit / pin — «Двигать» / «Готово»."""
    cmd = sys.argv[sys.argv.index("--cmd") + 1] if "--cmd" in sys.argv else "show"
    sock = QLocalSocket()
    sock.connectToServer(SERVER)
    if sock.waitForConnected(300):
        sock.write(cmd.encode())
        sock.waitForBytesWritten(300)
        return True
    return False


def autostart_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, "DesktopWidgets")
            return True
    except OSError:
        return False


def set_autostart(on):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
            winreg.SetValueEx(k, "DesktopWidgets", 0, winreg.REG_SZ,
                              f'"{pyw}" "{os.path.join(ROOT, "main.py")}" --tray')  # при входе — без окна
        else:
            try:
                winreg.DeleteValue(k, "DesktopWidgets")
            except OSError:
                pass


ISLAND_SERVER = "DynamicIsland-Fluid"


def island_launch():
    """Как запускать динамический остров — из его же записи автозапуска: (pythonw, main.py) или строка — почему не запускать.
    Записи нет — автозапуск острова выключен; есть файл «stopped» рядом — остров закрыли через «Выход»."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            cmd = winreg.QueryValueEx(k, "DynamicIsland")[0]
    except OSError:
        return "нет записи автозапуска острова"
    parts = [p.strip('"') for p in cmd.split('" "')]
    if len(parts) < 2 or not os.path.isfile(parts[0]) or not os.path.isfile(parts[1]):
        return "в записи автозапуска не найден файл: " + cmd
    if os.path.exists(os.path.join(os.path.dirname(parts[1]), "stopped")):
        return "остров закрыт через «Выход» (файл stopped)"
    return parts[0], parts[1]


def island_alive():
    probe = QLocalSocket()
    probe.connectToServer(ISLAND_SERVER)
    alive = probe.waitForConnected(200)
    probe.abort()
    return alive


def watch_island(app):
    """Windows иногда пропускает остров при входе (в журнале Shell-Core его запуска нет вовсе, а виджеты — есть),
    и после падения он тоже не вернётся сам. Виджеты стартуют надёжно — они и поднимают остров. Два промаха подряд
    (минута), чтобы не влезть в перезапуск острова при смене языка."""
    misses = [0]
    last = [None]

    def note(state):
        if state != last[0]:  # в журнал — только смена состояния, без спама раз в 30 с
            last[0] = state
            print("сторож острова:", state, flush=True)

    def check():
        launch = island_launch()
        if isinstance(launch, str):
            note("не поднимаю: " + launch)
            misses[0] = 0
            return
        if island_alive():
            note("остров работает")
            misses[0] = 0
            return
        note("остров не отвечает")
        misses[0] += 1
        if misses[0] >= 2:
            misses[0] = 0
            ok = QProcess.startDetached(launch[0], [launch[1]], os.path.dirname(launch[1]))
            print("остров не запущен — запускаю:", "да" if ok else "не вышло", flush=True)
    timer = QTimer(app, interval=30_000, timeout=check)
    timer.start()
    QTimer.singleShot(15_000, check)
    return timer


def apply_cfg(text):
    """Команда динамического острова (папка «остров» рядом с виджетами): поменять раздел настроек и перерисовать его виджет."""
    try:
        data = json.loads(text)
        sec = config.section(data["section"])
        for k, v in data["set"].items():
            if v is None:
                sec.pop(k, None)
            else:
                sec[k] = v
    except (ValueError, KeyError, TypeError, AttributeError):
        return
    config.save()
    if data["section"] == "app" and "skin" in data["set"]:  # тема оформления — у всех виджетов сразу
        core.set_skin(data["set"]["skin"] or "liquid")
        return
    for w in QApplication.topLevelWidgets():
        if getattr(w, "key", None) == data["section"]:
            if hasattr(w, "done_at"):
                w.done_at = None
            w.update()


def main():
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    app = QApplication(sys.argv)
    app.setApplicationDisplayName(tr("Виджеты"))
    app.setWindowIcon(make_icon())
    if "--restart" in sys.argv:  # перезапуск (смена языка): подождать, пока прошлая копия закроется
        for _ in range(50):
            probe = QLocalSocket()
            probe.connectToServer(SERVER)
            if not probe.waitForConnected(100):
                break
            probe.abort()
            time.sleep(0.1)
    elif already_running():
        return
    setup_log()  # после проверки: вторая копия (просит открыть окно и выходит) журнал не трогает
    skins.apply(config.section("app").get("skin", "liquid"))
    applog.log_screens(app)
    app.setQuitOnLastWindowClosed(False)
    app.setFont(QFont("Segoe UI", 10))
    catalog = Catalog()
    if autostart_enabled():
        set_autostart(True)  # обновить запись автозапуска до текущей (с --tray)

    # вторая копия программы просит открыть каталог
    QLocalServer.removeServer(SERVER)
    server = QLocalServer(app)
    def on_connection():
        """Подключения идут постоянно (остров проверяет нас раз в 3 с): сокет обязательно удалить, иначе у каждого
        остаётся 3 дескриптора Windows и память; и ждать данные нельзя в главном потоке — читаем по готовности."""
        while server.hasPendingConnections():
            sock = server.nextPendingConnection()
            parts = []

            def finish(sock=sock, parts=parts):
                parts.append(bytes(sock.readAll()))
                on_command(b"".join(parts))
                parts.clear()  # disconnected приходит и после abort/ошибки: команду выполнить один раз
                sock.deleteLater()

            sock.readyRead.connect(lambda sock=sock, parts=parts: parts.append(bytes(sock.readAll())))
            sock.disconnected.connect(finish)
            if sock.state() != QLocalSocket.ConnectedState:  # клиент успел отключиться раньше, чем мы подписались
                finish()

    def on_command(data):
        # пусто — только проверили, что мы запущены, окно не открываем; вторая копия шлёт «show» явно
        cmd = data.decode(errors="ignore").strip()
        if not cmd:
            return
        if cmd == "snap":
            activity.on_screenshot()
        elif cmd == "ping":  # динамический остров проверяет, запущены ли виджеты
            pass
        elif cmd.startswith("cfg "):  # остров меняет таймер / «Фокус»: {"section", "set": {ключ: значение, None — убрать}}
            apply_cfg(cmd[4:])
        elif cmd in ("edit", "pin"):
            catalog.set_editing(cmd == "edit")
        elif cmd.startswith("section "):  # остров: «Настройки…» — открыть общее окно на его разделе
            catalog.open()
            catalog.show_section(cmd.split(" ", 1)[1])
        else:
            catalog.open()

    server.newConnection.connect(on_connection)
    server.listen(SERVER)
    watch_island(app)

    # погода для пилюли острова: виджет «Погода» на столе обновляет её сам, без него — раз в 15 минут здесь
    def weather_for_island():
        if config.section("weather").get("city") and not any(w.key == "weather" for w in activity.widgets()):
            sections.update_snapshot()
    weather_timer = QTimer(app, interval=15 * 60 * 1000, timeout=weather_for_island)
    weather_timer.start()
    QTimer.singleShot(20_000, weather_for_island)
    if "--cmd" in sys.argv and sys.argv[sys.argv.index("--cmd") + 1] == "edit":
        QTimer.singleShot(1500, lambda: catalog.set_editing(True))  # перезапуск в режиме «Двигать»

    tray = QSystemTrayIcon(make_icon(), app)
    tray.setToolTip(tr("Виджеты"))
    menu = QMenu()
    menu.addAction(tr("Открыть"), catalog.open)
    core.skin_menu(menu)
    catalog.tray_move = menu.addAction(tr("Двигать виджеты"), lambda: catalog.set_editing(not activity.editing))
    menu.addAction(tr("Сообщить об ошибке"), bugreport.report)
    menu.addAction(tr("Поддержать автора"), bugreport.support)
    sep = menu.addSeparator()
    menu.addAction(tr("Выход"), catalog.quit)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda reason: catalog.open() if reason == QSystemTrayIcon.Trigger else None)
    tray.show()
    catalog.tray = tray
    if glass.boot_seconds() < 300:
        # запуск вместе с Windows: панель задач бывает ещё не готова, и значок не появлялся вовсе —
        # поставить его ещё раз, когда вход в систему закончится
        for delay in (15000, 60000):
            QTimer.singleShot(delay, lambda: (tray.hide(), tray.show()))
    catalog.updater = updater.Updater(tray, menu, sep, catalog.quit, catalog.update_btn)

    def on_game(playing):
        tray.setToolTip(tr("Виджеты — игровой режим: всё на паузе")
                        if playing and config.section("app").get("game_pause", True) else tr("Виджеты"))
        print("игра на весь экран:",
              f"началась ({glass.foreground_class()})" if playing else "закончилась", flush=True)
    activity.on_game = on_game

    # как обычное приложение: при запуске открывается окно; автозапуск с Windows — тихо, в трей
    if "--tray" not in sys.argv:
        catalog.open()
    if "--section" in sys.argv[:-1]:  # остров открывает свои настройки, а виджеты ещё не были запущены
        catalog.show_section(sys.argv[sys.argv.index("--section") + 1])
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
