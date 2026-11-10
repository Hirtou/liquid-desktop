"""Секундомер: старт/пауза, круги, сброс. Идёт по часам компьютера, поэтому переживает перезапуск программы."""
from lang import tr
import time

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter

from core import DesktopWidget, activity, config, grid
from widgets import kit

RED = QColor("#e5484d")


def fmt(sec):
    sec = max(0.0, sec)
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    tenth = int(sec * 10) % 10
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}.{tenth}"


class StopwatchWidget(DesktopWidget):
    key = "stopwatch"
    title = tr("Секундомер")
    description = tr("Старт, пауза, круги и сброс")
    SHAPES = {"full": (tr("Полный"), grid(2, 1))}

    def __init__(self, **kw):
        super().__init__(**kw)
        self.apply_shape()
        self.cfg.setdefault("base", 0.0)      # накоплено до последнего старта, с
        self.cfg.setdefault("started", None)  # когда нажали «старт» (время компьютера)
        self.cfg.setdefault("laps", [])
        self.buttons = {}
        self.timer = QTimer(self, interval=100, timeout=self.tick)
        self.timer.start()

    def push_interval(self):
        return 200 if self.cfg["started"] else 1000

    def tick(self):
        if self.cfg["started"] and not activity.covered(self):
            self.update()

    def elapsed(self):
        started = self.cfg["started"]
        return self.cfg["base"] + (time.time() - started if started else 0.0)

    def click(self, pos):
        for name, rect in self.buttons.items():
            if rect.contains(pos):
                self.press(name)
                return True
        return False

    def press(self, name):
        now = self.elapsed()
        if name == "main":
            if self.cfg["started"]:
                self.cfg["base"], self.cfg["started"] = now, None
            else:
                self.cfg["started"] = time.time()
        elif name == "lap":
            self.cfg["laps"] = ([now] + self.cfg["laps"])[:20]
        elif name == "reset":
            self.cfg.update(base=0.0, started=None, laps=[])
        config.save()
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)  # стекло
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        r = QRectF(self.card())
        fg, dim, track = kit.ink(self)
        dark = bool(self.dark)
        running = bool(self.cfg["started"])
        now = self.elapsed()

        # слева: кольцо — бегущая минута (как у «Таймера»: перелив голубой → синий), внутри время
        c, R, tile = kit.ring_tile(r)
        kit.ring(p, c, R, (now % 60) / 60 if now else 0, kit.CYAN, track, 11, kit.ACCENT)
        m, s = divmod(int(now), 60)
        h, m = divmod(m, 60)
        big = f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
        kit.text(p, QRectF(c.x() - R, c.y() - R * 0.36, 2 * R, R * 0.55), big, fg, int(R * (0.36 if h else 0.46)),
                 "Bahnschrift SemiBold", Qt.AlignCenter)
        kit.text(p, QRectF(c.x() - R, c.y() + R * 0.22, 2 * R, 16), f".{int(now * 10) % 10} " + tr("с"), dim, 11,
                 align=Qt.AlignCenter)

        # справа: заголовок и чип, последние круги, кнопки
        x = tile.right() + 16
        w = r.right() - 16 - x
        state = (tr("идёт"), kit.GREEN) if running else (tr("пауза"), kit.AMBER) if now else (tr("готов"), kit.GRAY)
        cw = kit.chip(p, r, state[0], state[1], dark)
        kit.text(p, QRectF(x, r.top() + 14, w - cw - 6, 22), tr("Секундомер"), fg, 16, "Segoe UI Semibold", elide=True)
        laps = self.cfg["laps"]
        for i, lap in enumerate(laps[:3]):
            y = r.top() + 42 + i * 17
            kit.text(p, QRectF(x, y, w, 16), tr("круг {}").format(len(laps) - i), dim, 11)
            kit.text(p, QRectF(x, y, w, 16), fmt(lap), fg, 12, align=Qt.AlignRight | Qt.AlignVCenter)
        if not laps:
            kit.text(p, QRectF(x, r.top() + 42, w, 16), tr("кругов нет"), dim, 11)

        cy = r.bottom() - 26
        cx = x + w / 2
        self.buttons = {}
        for name, dx, glyph in (("reset", -48, "reset"), ("main", 0, "pause" if running else "play"), ("lap", 48, "flag")):
            rad = 19 if name == "main" else 16
            rect = QRectF(cx + dx - rad, cy - rad, 2 * rad, 2 * rad)
            self.buttons[name] = rect
            kit.round_button(p, rect, glyph, fg, dark, (RED if running else kit.ACCENT) if name == "main" else None)
