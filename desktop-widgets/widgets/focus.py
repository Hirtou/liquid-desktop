"""Фокус (помидор): 25 минут работы, 5 отдыха. Клик — старт/пауза; правый клик — сбросить, 50/10.
Работа закончилась — сам начинается перерыв, помидор засчитывается (счёт за день)."""
from lang import tr
import math
import time
from datetime import date

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QConicalGradient, QFont, QPainter, QPen

from core import DesktopWidget, config, grid

TOMATO, TOMATO2, GREEN, GREEN2 = QColor("#ff6b5a"), QColor("#e5486b"), QColor("#4ade80"), QColor("#22a06b")
PRESETS = {"25/5": (25, 5), "50/10": (50, 10)}


class FocusWidget(DesktopWidget):
    key = "focus"
    title = tr("Фокус")
    description = tr("Помидор 25/5: работа, перерыв, счёт за день")
    SHAPES = {"tile": (tr("Плитка"), grid(1, 1))}

    def __init__(self, **kw):
        super().__init__(**kw)
        self.apply_shape()
        self.cfg.setdefault("preset", "25/5")
        self.cfg.setdefault("mode", "work")
        self.timer = QTimer(self, interval=1000, timeout=self.tick)
        self.timer.start()

    # ---------- состояние: mode (work/break), end (идёт) или left (пауза) ----------

    def length(self, mode=None):
        work, rest = PRESETS.get(self.cfg["preset"], (25, 5))
        return (work if (mode or self.cfg["mode"]) == "work" else rest) * 60

    def remaining(self):
        if self.cfg.get("end"):
            return max(0.0, self.cfg["end"] - time.time())
        return self.cfg.get("left", self.length())

    def running(self):
        return bool(self.cfg.get("end"))

    def today(self):
        d = self.cfg.get("done", {})
        return d.get("count", 0) if d.get("day") == date.today().isoformat() else 0

    def tick(self):
        if self.running() and self.remaining() <= 0:
            if self.cfg["mode"] == "work":  # помидор готов — засчитать и начать перерыв
                self.cfg["done"] = {"day": date.today().isoformat(), "count": self.today() + 1}
                self.cfg["mode"] = "break"
                self.cfg["end"] = time.time() + self.length("break")
            else:  # перерыв кончился — ждём, когда снова нажмут
                self.cfg["mode"] = "work"
                self.cfg.pop("end", None)
                self.cfg.pop("left", None)
            config.save()
        self.update()

    def click(self, pos):
        if self.running():
            self.cfg["left"] = self.remaining()
            self.cfg.pop("end", None)
        else:
            self.cfg["end"] = time.time() + self.cfg.pop("left", self.length())
        config.save()
        self.update()
        return True

    def add_actions(self, menu):
        menu.addAction(tr("Сбросить"), self.reset)
        sub = menu.addMenu(tr("Время"))
        for name in PRESETS:
            a = sub.addAction(tr("{} мин").format(name), lambda n=name: self.set_preset(n))
            a.setCheckable(True)
            a.setChecked(self.cfg["preset"] == name)

    def reset(self):
        for k in ("end", "left"):
            self.cfg.pop(k, None)
        self.cfg["mode"] = "work"
        config.save()
        self.update()

    def set_preset(self, name):
        self.cfg["preset"] = name
        self.reset()

    # ---------- рисование ----------

    def paintEvent(self, event):
        super().paintEvent(event)  # стекло
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        r = QRectF(self.card())
        dark = bool(self.dark)
        fg = QColor("#ededf0") if dark else QColor("#151517")
        dim = QColor(fg)
        dim.setAlpha(140)
        work = self.cfg["mode"] == "work"
        left, total = self.remaining(), self.length()
        frac = left / total if total else 0
        c1, c2 = (TOMATO, TOMATO2) if work else (GREEN, GREEN2)

        R = min(r.width(), r.height()) * 0.33
        c = QPointF(r.center().x(), r.top() + 16 + R)
        track = QColor(fg)
        track.setAlpha(28)
        p.setPen(QPen(track, 11, Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(c, R, R)
        if frac > 0:
            grad = QConicalGradient(c, 90)
            grad.setColorAt(0, c1)
            grad.setColorAt(1, c2)
            p.setPen(QPen(grad, 11, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(QRectF(c.x() - R, c.y() - R, 2 * R, 2 * R), 90 * 16, int(-frac * 360 * 16))
        # листик помидора над кольцом (в работе) — свой рисунок
        if work:
            p.setPen(Qt.NoPen)
            p.setBrush(GREEN2)
            for a in (-35, 0, 35):
                rad = math.radians(a - 90)
                tip = QPointF(c.x() + math.cos(rad) * 9, c.y() - R + math.sin(rad) * 9 + 1)
                p.drawPolygon([QPointF(c.x() - 3, c.y() - R), QPointF(c.x() + 3, c.y() - R), tip])

        big = QFont("Bahnschrift SemiBold")
        big.setPixelSize(int(R * 0.5))
        p.setFont(big)
        p.setPen(fg)
        m, s = divmod(int(left + 0.999), 60)
        p.drawText(QRectF(c.x() - R, c.y() - R * 0.4, 2 * R, R * 0.6), Qt.AlignCenter, f"{m}:{s:02d}")
        small = QFont("Segoe UI")
        small.setPixelSize(11)
        p.setFont(small)
        p.setPen(dim)
        state = (tr("фокус") if work else tr("перерыв")) if self.running() else (tr("пауза") if "left" in self.cfg else tr("нажми"))
        p.drawText(QRectF(c.x() - R, c.y() + R * 0.2, 2 * R, 16), Qt.AlignCenter, state)
        n = self.today()
        p.drawText(QRectF(r.left(), r.bottom() - 26, r.width(), 16), Qt.AlignCenter,
                   tr("{} {} сегодня").format(n, tr('помидор') if n % 10 == 1 and n % 100 != 11 else tr('помидора') if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else tr('помидоров')))
