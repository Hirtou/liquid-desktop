"""Таймер с кольцом: старт/пауза, +1 минута, сброс; колесо мыши — минуты; по окончании — звук и мигание.
Идёт и после перезапуска программы (время окончания хранится в настройках)."""
from lang import tr
import math
import time
import winsound

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QConicalGradient, QFont, QPainter, QPen

from core import DesktopWidget, SHADOW, config, grid

BLUE, CYAN, RED = QColor("#2f6bff"), QColor("#36c6ff"), QColor("#ff5a5f")
PRESETS = (1, 3, 5, 10, 15, 25, 45, 60)


def mmss(sec):
    sec = max(0, int(math.ceil(sec)))
    h, rest = divmod(sec, 3600)
    return f"{h}:{rest // 60:02d}:{rest % 60:02d}" if h else f"{rest // 60:02d}:{rest % 60:02d}"


class TimerWidget(DesktopWidget):
    key = "timer"
    title = tr("Таймер")
    description = tr("Кольцо, старт/пауза, звук в конце")

    def __init__(self, **kw):
        super().__init__(**kw)
        self.setFixedSize(*(v + 2 * SHADOW for v in grid(1, 1)))
        self.cfg.setdefault("duration", 5 * 60)
        self.done_at = None
        self.buttons = {}
        self.timer = QTimer(self, interval=100, timeout=self.on_tick)
        self.timer.start()

    # ---------- состояние: duration, end (идёт), left (пауза) ----------

    def remaining(self):
        if self.cfg.get("end"):
            return max(0.0, self.cfg["end"] - time.time())
        return float(self.cfg.get("left", self.cfg["duration"]))

    def running(self):
        return bool(self.cfg.get("end"))

    def save(self):
        config.save()
        self.update()

    def start_pause(self):
        if self.running():
            self.cfg["left"] = self.remaining()
            self.cfg.pop("end", None)
        else:
            left = self.remaining() or self.cfg["duration"]
            self.cfg["end"] = time.time() + left
            self.cfg.pop("left", None)
            self.done_at = None
        self.save()

    def reset(self):
        self.cfg.pop("end", None)
        self.cfg.pop("left", None)
        self.done_at = None
        self.save()

    def add(self, minutes):
        if self.running():
            self.cfg["end"] += minutes * 60
        else:
            self.cfg["duration"] = max(60, min(24 * 3600, self.cfg["duration"] + minutes * 60))
            self.cfg.pop("left", None)
        self.done_at = None
        self.save()

    def set_preset(self, minutes):
        self.cfg["duration"] = minutes * 60
        self.reset()

    def on_tick(self):
        # менять состояние и пищать может только настоящий виджет (не превью в каталоге — у них общие настройки)
        if self.placed and self.running() and self.remaining() <= 0:
            self.cfg.pop("end", None)
            self.cfg["left"] = 0
            self.done_at = time.monotonic()
            config.save()
            winsound.PlaySound("SystemExclamation", winsound.SND_ALIAS | winsound.SND_ASYNC)
        if self.placed and self.done_at and time.monotonic() - self.done_at > 12:
            self.done_at = None
            self.reset()
        # часто — только пока идёт или мигает; иначе раз в секунду
        busy = self.running() or self.done_at
        interval = 100 if busy else 1000
        if self.timer.interval() != interval:
            self.timer.setInterval(interval)
        self.update()

    def push_interval(self):
        return 250 if (self.running() or self.done_at) else 1000

    # ---------- мышь ----------

    def click(self, pos):
        for name, rect in self.buttons.items():
            if rect.contains(pos):
                {"reset": self.reset, "play": self.start_pause, "plus": lambda: self.add(1)}[name]()
                return True
        return False

    def wheelEvent(self, event):
        self.add(1 if event.angleDelta().y() > 0 else -1)

    def add_actions(self, menu):
        presets = menu.addMenu(tr("Время"))
        for m in PRESETS:
            presets.addAction(tr("{} мин").format(m), lambda m=m: self.set_preset(m))

    # ---------- рисование ----------

    def paintEvent(self, event):
        super().paintEvent(event)  # стекло
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        r = QRectF(self.card())
        dark = bool(self.dark)
        fg = QColor("#ededf0") if dark else QColor("#151517")
        dim = QColor(fg)
        dim.setAlpha(130)
        # кольцо сверху, под ним ряд кнопок — всё внутри ячейки 1×1
        R = min(r.width(), r.height()) * 0.27
        c = QPointF(r.center().x(), r.top() + 14 + R)
        left = self.remaining()
        total = self.cfg["duration"] if not self.running() else max(self.cfg["duration"], left)
        frac = left / total if total else 0

        track = QColor(fg)
        track.setAlpha(28)
        p.setPen(QPen(track, 11, Qt.SolidLine, Qt.RoundCap))
        p.drawEllipse(c, R, R)
        if self.done_at:  # конец — кольцо мигает красным
            pulse = 0.5 + 0.5 * math.sin((time.monotonic() - self.done_at) * 8)
            red = QColor(RED)
            red.setAlpha(int(110 + 145 * pulse))
            p.setPen(QPen(red, 11, Qt.SolidLine, Qt.RoundCap))
            p.drawEllipse(c, R, R)
        elif frac > 0:
            grad = QConicalGradient(c, 90)
            grad.setColorAt(0, CYAN)
            grad.setColorAt(1, BLUE)
            p.setPen(QPen(grad, 11, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(QRectF(c.x() - R, c.y() - R, 2 * R, 2 * R), 90 * 16, int(-frac * 360 * 16))

        big = QFont("Bahnschrift SemiBold")
        big.setPixelSize(int(R * 0.5))
        p.setFont(big)
        p.setPen(fg)
        p.drawText(QRectF(c.x() - R, c.y() - R * 0.4, 2 * R, R * 0.6), Qt.AlignCenter, mmss(left))
        small = QFont("Segoe UI")
        small.setPixelSize(12)
        p.setFont(small)
        p.setPen(dim)
        state = tr("готово!") if self.done_at else tr("идёт") if self.running() else tr("пауза") if "left" in self.cfg else tr("таймер")
        p.drawText(QRectF(c.x() - R, c.y() + R * 0.22, 2 * R, 18), Qt.AlignCenter, state)

        # кнопки: сброс, старт/пауза, +1 мин
        y = r.bottom() - 26
        self.buttons = {}
        for name, dx in (("reset", -48), ("play", 0), ("plus", 48)):
            rad = 19 if name == "play" else 16
            rect = QRectF(c.x() + dx - rad, y - rad, 2 * rad, 2 * rad)
            self.buttons[name] = rect
            p.setPen(QPen(QColor(255, 255, 255, 70 if dark else 170), 1))
            p.setBrush(BLUE if name == "play" else QColor(255, 255, 255, 30 if dark else 140))
            p.drawEllipse(rect)
            self._glyph(p, name, rect.center(), QColor("white") if name == "play" else fg)

    def _glyph(self, p, name, c, color):
        p.setPen(QPen(color, 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        if name == "plus":
            p.drawLine(QPointF(c.x() - 6, c.y()), QPointF(c.x() + 6, c.y()))
            p.drawLine(QPointF(c.x(), c.y() - 6), QPointF(c.x(), c.y() + 6))
        elif name == "reset":  # круговая стрелка
            p.drawArc(QRectF(c.x() - 6.5, c.y() - 6.5, 13, 13), 60 * 16, 290 * 16)
            p.drawPolyline([QPointF(c.x() + 1, c.y() - 9), QPointF(c.x() + 4.5, c.y() - 5.8),
                            QPointF(c.x() + 0.5, c.y() - 3)])
        elif self.running():  # пауза
            p.setPen(QPen(color, 3, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(c.x() - 3.5, c.y() - 6), QPointF(c.x() - 3.5, c.y() + 6))
            p.drawLine(QPointF(c.x() + 3.5, c.y() - 6), QPointF(c.x() + 3.5, c.y() + 6))
        else:  # старт
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            p.drawPolygon([QPointF(c.x() - 4, c.y() - 7), QPointF(c.x() + 7, c.y()), QPointF(c.x() - 4, c.y() + 7)])
