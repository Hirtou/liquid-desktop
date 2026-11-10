"""Прогресс: сколько прошло от года (кольцо), дня, недели и месяца. Считается без интернета."""
from lang import tr
import calendar
from datetime import datetime

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter

from core import DesktopWidget, grid
from widgets import kit

COLORS = {"day": QColor("#60a5fa"), "week": QColor("#a78bfa"), "month": QColor("#f472b6"), "year": QColor("#fbbf24")}


def fractions(now=None):
    """Доли (день, неделя, месяц, год) от 0 до 1 и сколько дней осталось в году."""
    now = now or datetime.now()
    sec = now.hour * 3600 + now.minute * 60 + now.second
    day = sec / 86400
    week = (now.weekday() + day) / 7
    month = (now.day - 1 + day) / calendar.monthrange(now.year, now.month)[1]
    total = 366 if calendar.isleap(now.year) else 365
    number = now.timetuple().tm_yday
    return day, week, month, (number - 1 + day) / total, total - number


class ProgressWidget(DesktopWidget):
    key = "progress"
    title = tr("Прогресс")
    description = tr("Сколько прошло от дня, недели, месяца и года")
    SHAPES = {"full": (tr("Полный"), grid(2, 1)), "ring": (tr("Кольцо"), grid(1, 1))}

    def __init__(self, **kw):
        super().__init__(**kw)
        self.apply_shape()
        self.timer = QTimer(self, interval=60 * 1000, timeout=self.update)
        self.timer.start()

    def paintEvent(self, event):
        super().paintEvent(event)  # стекло
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        r = QRectF(self.card())
        fg, dim, track = kit.ink(self)
        dark = bool(self.dark)
        day, week, month, year, left = fractions()
        c, R, tile = kit.ring_tile(r)
        kit.ring(p, c, R, year, COLORS["year"], track, color2=QColor("#ff8a3d"))
        kit.ring_label(p, c, R, f"{year * 100:.0f}%", str(datetime.now().year), fg, dim)
        if self.shape() == "ring":
            return
        x = tile.right() + 16
        w = r.right() - 16 - x
        cw = kit.chip(p, r, tr("ещё {} дн").format(left), COLORS["year"], dark)
        kit.text(p, QRectF(x, r.top() + 14, w - cw - 6, 22), tr("Прогресс"), fg, 16, "Segoe UI Semibold", elide=True)
        rows = ((tr("День"), day, "day"), (tr("Неделя"), week, "week"), (tr("Месяц"), month, "month"))
        for i, (label, frac, name) in enumerate(rows):
            y = r.top() + 46 + i * 36
            kit.text(p, QRectF(x, y, w, 16), label, fg)
            kit.text(p, QRectF(x, y, w, 16), f"{frac * 100:.0f}%", dim, align=Qt.AlignRight | Qt.AlignVCenter)
            kit.bar(p, QRectF(x, y + 19, w, 6), frac, COLORS[name], track)
