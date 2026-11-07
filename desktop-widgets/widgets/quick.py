"""Быстрые кнопки: заблокировать, выключить экран, ножницы, корзина, параметры — по клику.
Ничего опасного: выключить или перезагрузить компьютер отсюда нельзя."""
from lang import tr
import ctypes
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen

from core import DesktopWidget, grid, open_uri

BUTTONS = [("lock", tr("Блок"), "#2f6bff"), ("screen", tr("Экран"), "#3c4a63"), ("snip", tr("Ножницы"), "#e5486b"),
           ("bin", tr("Корзина"), "#16a3c9"), ("settings", tr("Параметры"), "#6b7280")]


def do(action):
    user32 = ctypes.windll.user32
    if action == "lock":
        user32.LockWorkStation()
    elif action == "screen":  # выключить экран (компьютер работает дальше; мышь или клавиша — включат)
        user32.PostMessageW(0xFFFF, 0x0112, 0xF170, 2)  # HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER
    elif action == "snip":
        open_uri("ms-screenclip:")
    elif action == "bin":
        open_uri("shell:RecycleBinFolder")
    elif action == "settings":
        open_uri("ms-settings:")


class QuickWidget(DesktopWidget):
    key = "quick"
    title = tr("Быстрые кнопки")
    description = tr("Блок, выключить экран, ножницы, корзина, параметры")
    SHAPES = {"row": (tr("В ряд"), grid(2, 1))}

    def __init__(self, **kw):
        super().__init__(**kw)
        self.apply_shape()
        self.buttons = {}

    def click(self, pos):
        for name, rect in self.buttons.items():
            if rect.contains(pos):
                do(name)
                return True
        return False

    def paintEvent(self, event):
        super().paintEvent(event)  # стекло
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        r = QRectF(self.card()).adjusted(16, 14, -16, -14)
        dark = bool(self.dark)
        fg = QColor("#ededf0") if dark else QColor("#151517")
        dim = QColor(fg)
        dim.setAlpha(150)
        head = QFont("Segoe UI Semibold")
        head.setPixelSize(15)
        p.setFont(head)
        p.setPen(fg)
        p.drawText(QRectF(r.left(), r.top(), r.width(), 20), Qt.AlignLeft | Qt.AlignVCenter, tr("Быстрые кнопки"))
        col = r.width() / len(BUTTONS)
        side = min(col - 10, 52)
        label = QFont("Segoe UI")
        label.setPixelSize(11)
        self.buttons = {}
        for i, (name, text, color) in enumerate(BUTTONS):
            cx = r.left() + col * i + col / 2
            top = r.top() + 22 + (r.height() - 22 - side - 20) / 2  # ряд — посередине под заголовком
            tile = QRectF(cx - side / 2, top, side, side)
            self.buttons[name] = tile.adjusted(-4, -4, 4, 22)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(color))
            p.drawRoundedRect(tile, side * 0.28, side * 0.28)
            self._glyph(p, name, tile.center(), side * 0.42)
            p.setFont(label)
            p.setPen(dim)
            p.drawText(QRectF(cx - col / 2, tile.bottom() + 4, col, 16), Qt.AlignCenter, text)

    @staticmethod
    def _glyph(p, name, c, s):
        """Белый рисунок на плитке, в квадрате со стороной s."""
        h = s / 2
        white = QColor("white")
        pen = QPen(white, s * 0.12, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        x, y = c.x(), c.y()
        if name == "lock":  # замок: дужка и корпус
            p.drawArc(QRectF(x - h * 0.55, y - h, h * 1.1, h * 1.2), 0, 180 * 16)
            p.drawLine(QPointF(x - h * 0.55, y - h * 0.4), QPointF(x - h * 0.55, y - h * 0.1))
            p.drawLine(QPointF(x + h * 0.55, y - h * 0.4), QPointF(x + h * 0.55, y - h * 0.1))
            p.setPen(Qt.NoPen)
            p.setBrush(white)
            p.drawRoundedRect(QRectF(x - h * 0.85, y - h * 0.15, h * 1.7, h * 1.15), h * 0.2, h * 0.2)
        elif name == "screen":  # монитор с полумесяцем
            p.drawRoundedRect(QRectF(x - h, y - h * 0.75, 2 * h, h * 1.3), h * 0.15, h * 0.15)
            p.drawLine(QPointF(x - h * 0.4, y + h * 0.9), QPointF(x + h * 0.4, y + h * 0.9))
            moon = QPainterPath()
            moon.addEllipse(QPointF(x, y - h * 0.1), h * 0.35, h * 0.35)
            cut = QPainterPath()
            cut.addEllipse(QPointF(x + h * 0.18, y - h * 0.22), h * 0.3, h * 0.3)
            p.setPen(Qt.NoPen)
            p.setBrush(white)
            p.drawPath(moon.subtracted(cut))
        elif name == "snip":  # ножницы
            p.drawEllipse(QPointF(x - h * 0.45, y + h * 0.55), h * 0.28, h * 0.28)
            p.drawEllipse(QPointF(x + h * 0.45, y + h * 0.55), h * 0.28, h * 0.28)
            p.drawLine(QPointF(x - h * 0.25, y + h * 0.35), QPointF(x + h * 0.55, y - h * 0.9))
            p.drawLine(QPointF(x + h * 0.25, y + h * 0.35), QPointF(x - h * 0.55, y - h * 0.9))
        elif name == "bin":  # корзина: крышка и ведро с полосками
            p.drawLine(QPointF(x - h, y - h * 0.6), QPointF(x + h, y - h * 0.6))
            p.drawLine(QPointF(x - h * 0.3, y - h * 0.85), QPointF(x + h * 0.3, y - h * 0.85))
            body = QPainterPath(QPointF(x - h * 0.75, y - h * 0.45))
            body.lineTo(x - h * 0.55, y + h)
            body.lineTo(x + h * 0.55, y + h)
            body.lineTo(x + h * 0.75, y - h * 0.45)
            p.drawPath(body)
            for dx in (-0.25, 0.25):
                p.drawLine(QPointF(x + dx * h, y - h * 0.2), QPointF(x + dx * h, y + h * 0.7))
        elif name == "settings":  # шестерёнка
            for k in range(8):
                a = k * math.pi / 4
                p.drawLine(QPointF(x + math.cos(a) * h * 0.6, y + math.sin(a) * h * 0.6),
                           QPointF(x + math.cos(a) * h * 0.98, y + math.sin(a) * h * 0.98))
            p.drawEllipse(c, h * 0.62, h * 0.62)
            p.drawEllipse(c, h * 0.22, h * 0.22)
