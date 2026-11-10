"""Кубик и монетка: клик — бросок. Когда надо решить и не хочется думать."""
from lang import tr
import random

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen

from core import DesktopWidget, config, grid
from widgets import kit

PIPS = {1: [(1, 1)], 2: [(0, 0), (2, 2)], 3: [(0, 0), (1, 1), (2, 2)], 4: [(0, 0), (2, 0), (0, 2), (2, 2)],
        5: [(0, 0), (2, 0), (1, 1), (0, 2), (2, 2)], 6: [(0, 0), (2, 0), (0, 1), (2, 1), (0, 2), (2, 2)]}
FRAMES = 11


class DiceWidget(DesktopWidget):
    key = "dice"
    title = tr("Кубик")
    description = tr("Кубик или монетка: клик — бросок")
    SHAPES = {"tile": (tr("Плитка"), grid(1, 1))}

    def __init__(self, **kw):
        super().__init__(**kw)
        self.apply_shape()
        self.cfg.setdefault("mode", "dice")
        self.value = random.randint(1, 6) if self.cfg["mode"] == "dice" else random.randint(0, 1)
        self.left = 0
        self.history = []  # последние броски — только в памяти
        self.spin = QTimer(self, interval=55, timeout=self.step)

    def add_actions(self, menu):
        sub = menu.addMenu(tr("Что бросать"))
        for name, text in (("dice", tr("Кубик")), ("coin", tr("Монетка"))):
            a = sub.addAction(text, lambda n=name: self.set_mode(n))
            a.setCheckable(True)
            a.setChecked(self.cfg["mode"] == name)

    def set_mode(self, name):
        self.cfg["mode"] = name
        config.save()
        self.history = []
        self.value = random.randint(1, 6) if name == "dice" else random.randint(0, 1)
        self.update()

    def click(self, pos):
        self.left = FRAMES
        self.spin.start()
        return True

    def step(self):
        self.left -= 1
        self.value = random.randint(1, 6) if self.cfg["mode"] == "dice" else 1 - self.value
        if self.left <= 0:
            self.spin.stop()
            if self.cfg["mode"] == "coin":  # чередование кадрами не должно решать исход
                self.value = random.randint(0, 1)
            self.history = (self.history + [self.value])[-4:]
        self.update()

    def push_interval(self):
        return 60 if self.left > 0 else 1000

    def paintEvent(self, event):
        super().paintEvent(event)  # стекло
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        # раскладка «Луны»: заголовок, крупный результат, картинка справа сверху, строка внизу
        r = QRectF(self.card()).adjusted(16, 14, -16, -14)
        fg, dim, track = kit.ink(self)
        coin = self.cfg["mode"] == "coin"
        side = 72
        wobble = (self.left % 3 - 1) * 3 if self.left else 0
        box = QRectF(r.right() - side + wobble, r.top(), side, side)
        if coin:
            grad = QLinearGradient(box.topLeft(), box.bottomLeft())
            grad.setColorAt(0, QColor("#ffd86b"))
            grad.setColorAt(1, QColor("#e09a1f"))
            p.setPen(QPen(QColor("#b97a10"), 2))
            p.setBrush(grad)
            # пока крутится — монетка сплющивается, как при вращении
            squeeze = abs(self.left % 4 - 2) / 2 if self.left else 1
            p.drawEllipse(box.center(), side / 2 * max(0.15, squeeze), side / 2)
            if not self.left:
                p.setPen(QPen(QColor(120, 75, 0, 150), 2))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(box.center(), side / 2 - 7, side / 2 - 7)
                kit.text(p, box, tr("О") if self.value else tr("Р"), QColor("#7a4b00"), 28, "Bahnschrift SemiBold", Qt.AlignCenter)
            result = tr("Орёл") if self.value else tr("Решка")
        else:
            p.setPen(QPen(QColor(255, 255, 255, 170), 1))
            grad = QLinearGradient(box.topLeft(), box.bottomLeft())
            grad.setColorAt(0, QColor("#ffffff"))
            grad.setColorAt(1, QColor("#d6dae3"))
            p.setBrush(grad)
            p.drawRoundedRect(box, 18, 18)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#e5484d") if self.value == 1 else QColor("#20232c"))
            step = side / 4
            pip = 7.5 if self.value == 1 else 6
            for cx, cy in PIPS[max(1, min(6, self.value))]:
                p.drawEllipse(QPointF(box.left() + step * (cx + 1), box.top() + step * (cy + 1)), pip, pip)
            result = str(self.value)
        kit.text(p, QRectF(r.left(), r.top(), r.width() - side, 20), tr("Монетка") if coin else tr("Кубик"), fg, 15,
                 "Segoe UI Semibold")
        kit.text(p, QRectF(r.left(), r.top() + 26, r.width() - side, 32), "…" if self.left else result, fg, 26,
                 "Bahnschrift SemiBold")
        kit.text(p, QRectF(r.left(), r.top() + 56, r.width() - side, 14), tr("50 на 50") if coin else tr("из 6"), dim, 11)
        names = [(tr("Орёл") if v else tr("Решка")) if coin else str(v) for v in self.history[-4:]]
        kit.text(p, QRectF(r.left(), r.bottom() - 38, r.width(), 18), " · ".join(reversed(names)) if names else tr("ещё не бросали"),
                 fg, 13, "Segoe UI Semibold", elide=True)
        kit.text(p, QRectF(r.left(), r.bottom() - 18, r.width(), 16), tr("клик — бросок"), dim, 11)
