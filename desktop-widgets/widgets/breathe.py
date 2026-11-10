"""Дыхание: минута спокойного дыхания. Кольцо наполняется на вдохе и пустеет на выдохе, в центре — сколько секунд
осталось в фазе. Вид — как у «Таймера»: кольцо сверху, под ним круглая кнопка. Анимация — только пока идёт сеанс."""
from lang import tr
import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter

from core import DesktopWidget, activity, grid
from widgets import kit

PHASES = ((4.0, tr("Вдох")), (4.0, tr("Пауза")), (6.0, tr("Выдох")))
CYCLE = sum(sec for sec, _ in PHASES)
SESSION = 4 * CYCLE  # 56 секунд
TEAL, GREEN = QColor("#2dd4bf"), QColor("#4ade80")


def breath(t):
    """Секунда сеанса -> (подпись, наполненность кольца 0..1, секунд до конца фазы)."""
    t %= CYCLE
    for i, (sec, name) in enumerate(PHASES):
        if t < sec:
            part = t / sec
            ease = (1 - math.cos(math.pi * part)) / 2
            size = ease if i == 0 else 1.0 if i == 1 else 1 - ease
            return name, size, sec - t
        t -= sec
    return PHASES[-1][1], 0.0, 0.0


class BreatheWidget(DesktopWidget):
    key = "breathe"
    title = tr("Дыхание")
    description = tr("Минута спокойного дыхания: клик — начать")
    SHAPES = {"tile": (tr("Плитка"), grid(1, 1))}

    def __init__(self, **kw):
        super().__init__(**kw)
        self.apply_shape()
        self.started = None
        self.timer = QTimer(self, interval=33, timeout=self.tick)

    def tap(self, pos):
        if self.started is None:
            self.started = time.time()
            self.timer.start()
        else:
            self.stop()
        self.update()
        return True

    def stop(self):
        self.started = None
        self.timer.stop()

    def tick(self):
        if self.started is not None and time.time() - self.started >= SESSION:
            self.stop()
            self.update()
        elif not activity.covered(self):
            self.update()

    def push_interval(self):
        return 66 if self.started is not None else 1000

    def paintEvent(self, event):
        super().paintEvent(event)  # стекло
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        r = QRectF(self.card())
        fg, dim, track = kit.ink(self)
        dark = bool(self.dark)
        # те же размеры, что у «Таймера»: кольцо сверху, под ним ряд кнопок
        R = min(r.width(), r.height()) * 0.27
        c = QPointF(r.center().x(), r.top() + 14 + R)
        if self.started is None:
            name, size, big = tr("дыхание"), 0.0, f"0:{SESSION:.0f}"
        else:
            name, size, left = breath(time.time() - self.started)
            name, big = name.lower(), str(math.ceil(left))
        kit.ring(p, c, R, size, TEAL, track, 11, GREEN)
        kit.text(p, QRectF(c.x() - R, c.y() - R * 0.4, 2 * R, R * 0.6), big, fg, int(R * 0.5), "Bahnschrift SemiBold",
                 Qt.AlignCenter)
        kit.text(p, QRectF(c.x() - R, c.y() + R * 0.22, 2 * R, 18), name, dim, 12, align=Qt.AlignCenter)

        y = r.bottom() - 26
        running = self.started is not None
        kit.round_button(p, QRectF(c.x() - 19, y - 19, 38, 38), "stop" if running else "play", fg, dark, kit.ACCENT)
        if running:  # сколько осталось от сеанса — тонкой полоской по бокам от кнопки
            remain = max(0.0, SESSION - (time.time() - self.started)) / SESSION
            kit.bar(p, QRectF(r.left() + 16, y - 2, c.x() - 19 - 10 - r.left() - 16, 4), remain, TEAL, track)
            kit.text(p, QRectF(c.x() + 29, y - 8, r.right() - 16 - c.x() - 29, 16),
                     f"{math.ceil(remain * SESSION)} " + tr("с"), dim, 11, align=Qt.AlignRight | Qt.AlignVCenter)
