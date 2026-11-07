"""Стрелочные часы: круглый циферблат на стекле, плавная синяя секундная стрелка."""
from lang import tr
import math
from datetime import datetime

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap

from core import DesktopWidget, activity, grid, open_uri

BLUE = QColor("#2f6bff")


class AnalogClockWidget(DesktopWidget):
    key = "analog"
    title = tr("Циферблат")
    description = tr("Стрелочные часы, плавная секундная")
    SHAPES = {"classic": (tr("Классика"), grid(1, 1)), "minimal": (tr("Минимал"), grid(1, 1))}

    def __init__(self, **kw):
        super().__init__(**kw)
        self.apply_shape()
        self.face, self.face_key = None, None  # кэш циферблата
        self.tick = QTimer(self, interval=1000, timeout=self.on_tick, timerType=Qt.PreciseTimer)
        self.tick.start()

    def double_click(self):
        open_uri("ms-clock:")

    def push_interval(self):
        return 33 if activity.mode == "desktop" else 1000

    def on_tick(self):
        interval = 33 if activity.mode == "desktop" and self.isVisible() else 1000
        if self.tick.interval() != interval:
            self.tick.setInterval(interval)
        if not activity.covered(self):  # закрыт окном или игрой — кадр не нужен (откроют — нарисуется сам)
            self.update()

    def paintEvent(self, event):
        super().paintEvent(event)  # стекло
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        r = QRectF(self.card())
        c = r.center()
        R = min(r.width(), r.height()) / 2 - 14
        dark = bool(self.dark)
        fg = QColor("#ededf0") if dark else QColor("#151517")
        # циферблат не меняется — рисуем его в картинку один раз, каждый кадр только стрелки
        key = (self.card().size(), dark, self.devicePixelRatioF(), self.shape())
        if key != self.face_key:
            self.face_key = key
            dpr = self.devicePixelRatioF()
            self.face = QPixmap(int(r.width() * dpr), int(r.height() * dpr))
            self.face.setDevicePixelRatio(dpr)
            self.face.fill(Qt.transparent)
            fp = QPainter(self.face)
            fp.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
            self._face(fp, QPointF(r.width() / 2, r.height() / 2), R, fg, self.shape())
            fp.end()
        p.drawPixmap(r.topLeft(), self.face)
        self._hands(p, c, R, dark, fg)

    @staticmethod
    def _face(p, c, R, fg, shape):
        # 60 рисок, часовые длиннее; «Минимал» — только 12 часовых точек, без цифр
        for i in range(60):
            a = i * math.pi / 30
            major = i % 5 == 0
            if shape == "minimal":
                if major:
                    color = QColor(fg)
                    color.setAlpha(255 if i % 15 == 0 else 150)
                    p.setPen(Qt.NoPen)
                    p.setBrush(color)
                    dot = 4.5 if i % 15 == 0 else 3
                    p.drawEllipse(QPointF(c.x() + math.sin(a) * (R - 6), c.y() - math.cos(a) * (R - 6)), dot, dot)
                continue
            color = QColor(fg)
            color.setAlpha(230 if major else 80)
            p.setPen(QPen(color, 2.4 if major else 1.2, Qt.SolidLine, Qt.RoundCap))
            inner = R - (12 if major else 6)
            p.drawLine(QPointF(c.x() + math.sin(a) * inner, c.y() - math.cos(a) * inner),
                       QPointF(c.x() + math.sin(a) * R, c.y() - math.cos(a) * R))
        if shape == "minimal":
            return
        # цифры 12, 3, 6, 9
        f = QFont("Bahnschrift SemiBold")
        f.setPixelSize(int(R * 0.24))
        p.setFont(f)
        p.setPen(fg)
        for n, a in ((12, 0), (3, 90), (6, 180), (9, 270)):
            rad = math.radians(a)
            pos = QPointF(c.x() + math.sin(rad) * R * 0.7, c.y() - math.cos(rad) * R * 0.7)
            p.drawText(QRectF(pos.x() - 20, pos.y() - 14, 40, 28), Qt.AlignCenter, str(n))

    @staticmethod
    def _hands(p, c, R, dark, fg):
        now = datetime.now()
        s = now.second + now.microsecond / 1e6
        m = now.minute + s / 60
        h = now.hour % 12 + m / 60
        shadow = QColor(0, 0, 0, 70)

        def hand(angle, length, width, color, tail=0.0):
            p.save()
            p.translate(c)
            p.rotate(angle)
            p.setPen(QPen(shadow, width + 1, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(1.2, tail + 2), QPointF(1.2, -length + 2))
            p.setPen(QPen(color, width, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(0, tail), QPointF(0, -length))
            p.restore()

        hand(h * 30, R * 0.5, 6, fg)
        hand(m * 6, R * 0.78, 4, fg)
        hand(s * 6, R * 0.9, 1.8, BLUE, tail=R * 0.18)
        p.setPen(Qt.NoPen)
        p.setBrush(BLUE)
        p.drawEllipse(c, 6, 6)
        p.setBrush(QColor("#1d1d22") if dark else QColor("white"))
        p.drawEllipse(c, 2.6, 2.6)
