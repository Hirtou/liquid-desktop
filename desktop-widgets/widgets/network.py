"""Скорость интернета: загрузка и отдача сейчас и график за последнюю минуту."""
from lang import tr
from collections import deque

import psutil
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen

from core import DesktopWidget, grid, open_uri

DOWN = QColor("#2f8bff")
UP = QColor("#34c77b")
SAMPLES = 60  # секунд на графике


def speed(bps):
    """Байт/с -> «12.3 Мбит/с»."""
    bits = bps * 8
    for unit, k in ((tr("Гбит/с"), 1e9), (tr("Мбит/с"), 1e6), (tr("Кбит/с"), 1e3)):
        if bits >= k:
            return f"{bits / k:.1f} {unit}" if bits / k < 100 else f"{bits / k:.0f} {unit}"
    return tr("{:.0f} бит/с").format(bits)


class NetworkWidget(DesktopWidget):
    key = "network"
    title = tr("Сеть")
    description = tr("Скорость загрузки и отдачи, график")
    SHAPES = {"graph": (tr("С графиком"), grid(2, 1)), "numbers": (tr("Только цифры"), grid(1, 1))}

    def __init__(self, **kw):
        super().__init__(**kw)
        self.apply_shape()
        self.down = deque([0.0] * SAMPLES, maxlen=SAMPLES)
        self.up = deque([0.0] * SAMPLES, maxlen=SAMPLES)
        c = psutil.net_io_counters()
        self.last = (c.bytes_recv, c.bytes_sent)
        self.timer = QTimer(self, interval=1000, timeout=self.sample)
        self.timer.start()

    def double_click(self):
        open_uri("ms-settings:network-status")  # параметры сети

    def sample(self):
        c = psutil.net_io_counters()
        self.down.append(max(0, c.bytes_recv - self.last[0]))
        self.up.append(max(0, c.bytes_sent - self.last[1]))
        self.last = (c.bytes_recv, c.bytes_sent)
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)  # стекло
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        r = QRectF(self.card()).adjusted(18, 14, -18, -14)
        dark = bool(self.dark)
        fg = QColor("#ededf0") if dark else QColor("#151517")
        dim = QColor(fg)
        dim.setAlpha(130)

        title = QFont("Segoe UI Semibold")
        title.setPixelSize(15)
        p.setFont(title)
        p.setPen(fg)
        p.drawText(QRectF(r.left(), r.top(), r.width(), 20), Qt.AlignLeft | Qt.AlignVCenter, tr("Сеть"))

        # две цифры: ↓ загрузка, ↑ отдача — стрелки рисуем сами
        big = QFont("Segoe UI Semibold")
        big.setPixelSize(17)
        if self.shape() == "numbers":  # 1×1: цифры столбиком, крупнее, с подписями
            big.setPixelSize(20)
            small = QFont("Segoe UI")
            small.setPixelSize(11)
            for i, (color, values, down, text) in enumerate(((DOWN, self.down, True, tr("загрузка")),
                                                             (UP, self.up, False, tr("отдача")))):
                y = r.top() + 34 + i * 50
                self._arrow(p, QPointF(r.left() + 7, y + 13), down, color)
                p.setFont(big)
                p.setPen(fg)
                p.drawText(QRectF(r.left() + 22, y, r.width() - 22, 26), Qt.AlignLeft | Qt.AlignVCenter,
                           speed(values[-1]))
                p.setFont(small)
                p.setPen(dim)
                p.drawText(QRectF(r.left() + 22, y + 25, r.width() - 22, 14), Qt.AlignLeft | Qt.AlignVCenter, text)
            return
        for i, (color, values, down) in enumerate(((DOWN, self.down, True), (UP, self.up, False))):
            x = r.left() + i * r.width() / 2
            y = r.top() + 30
            self._arrow(p, QPointF(x + 7, y + 11), down, color)
            p.setFont(big)
            p.setPen(fg)
            p.drawText(QRectF(x + 20, y, r.width() / 2 - 20, 22), Qt.AlignLeft | Qt.AlignVCenter, speed(values[-1]))

        # график: обе линии с мягкой заливкой, масштаб — по максимуму за минуту
        g = QRectF(r.left(), r.top() + 62, r.width(), r.bottom() - r.top() - 62)
        peak = max(max(self.down), max(self.up), 1.0)
        p.setPen(QPen(dim, 1, Qt.DotLine))
        p.drawLine(g.bottomLeft(), g.bottomRight())
        for color, values in ((UP, self.up), (DOWN, self.down)):
            pts = [QPointF(g.left() + g.width() * i / (SAMPLES - 1), g.bottom() - g.height() * v / peak * 0.95)
                   for i, v in enumerate(values)]
            line = QPainterPath(pts[0])
            for a, b in zip(pts, pts[1:]):  # сглаженная линия
                mid = (a.x() + b.x()) / 2
                line.cubicTo(QPointF(mid, a.y()), QPointF(mid, b.y()), b)
            fill = QPainterPath(line)
            fill.lineTo(g.bottomRight())
            fill.lineTo(g.bottomLeft())
            fill.closeSubpath()
            grad = QLinearGradient(0, g.top(), 0, g.bottom())
            top = QColor(color)
            top.setAlpha(90)
            bottom = QColor(color)
            bottom.setAlpha(0)
            grad.setColorAt(0, top)
            grad.setColorAt(1, bottom)
            p.setPen(Qt.NoPen)
            p.setBrush(grad)
            p.drawPath(fill)
            p.setPen(QPen(color, 2))
            p.setBrush(Qt.NoBrush)
            p.drawPath(line)

    @staticmethod
    def _arrow(p, c, down, color):
        p.setPen(QPen(color, 2.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        s = 6
        d = 1 if down else -1
        p.drawLine(QPointF(c.x(), c.y() - s * d), QPointF(c.x(), c.y() + s * d))
        p.drawPolyline([QPointF(c.x() - s * 0.75, c.y() + s * d * 0.25), QPointF(c.x(), c.y() + s * d),
                        QPointF(c.x() + s * 0.75, c.y() + s * d * 0.25)])
