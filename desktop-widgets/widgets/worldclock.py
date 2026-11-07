"""Мировое время: до 5 городов, время, разница с твоим, день/ночь."""
from lang import tr
from datetime import datetime
from zoneinfo import ZoneInfo

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter

import icons
from core import SHADOW, DesktopWidget, config, grid, grid_rows, open_uri

CITIES = {
    "Алматы": "Asia/Almaty", "Астана": "Asia/Almaty", "Ташкент": "Asia/Tashkent", "Бишкек": "Asia/Bishkek",
    "Москва": "Europe/Moscow", "Киев": "Europe/Kyiv", "Стамбул": "Europe/Istanbul", "Берлин": "Europe/Berlin",
    "Париж": "Europe/Paris", "Лондон": "Europe/London", "Дубай": "Asia/Dubai", "Пекин": "Asia/Shanghai",
    "Сеул": "Asia/Seoul", "Токио": "Asia/Tokyo", "Бангкок": "Asia/Bangkok", "Сидней": "Australia/Sydney",
    "Нью-Йорк": "America/New_York", "Лос-Анджелес": "America/Los_Angeles",
}
DEFAULT = ["Москва", "Лондон", "Нью-Йорк", "Токио"]  # в настройках города хранятся по-русски, на экране — tr()
MAX = 5
ROW = 44
TILE = 60  # высота плитки в виде «Плитки» (4 города — ровно 2×1 ячейки сетки)


def hours(delta):
    h = delta.total_seconds() / 3600
    if abs(h) < 0.01:
        return tr("как у тебя")
    sign = "+" if h > 0 else "−"
    return tr("{}{:g} ч").format(sign, abs(h))


class WorldClockWidget(DesktopWidget):
    key = "worldclock"
    title = tr("Мировое время")
    description = tr("Города, разница во времени, день/ночь")
    # высота зависит от числа городов — считает apply_shape
    SHAPES = {"list": (tr("Список"), None), "tiles": (tr("Плитки"), None)}

    def __init__(self, **kw):
        super().__init__(**kw)
        self.cfg.setdefault("cities", list(DEFAULT))
        self.apply_shape()
        self.timer = QTimer(self, interval=5000, timeout=self.update)  # минуты меняются редко
        self.timer.start()

    def apply_shape(self):
        # высота по числу городов — округляем до целых ячеек сетки
        n = len(self.cfg["cities"])
        need = 44 + TILE * ((n + 1) // 2) if self.shape() == "tiles" else 50 + ROW * n
        w, h = grid(2, grid_rows(need))
        self.setFixedSize(w + 2 * SHADOW, h + 2 * SHADOW)

    def add_actions(self, menu):
        sub = menu.addMenu(tr("Города"))
        for name in CITIES:
            a = sub.addAction(tr(name), lambda n=name: self.toggle_city(n))
            a.setCheckable(True)
            a.setChecked(name in self.cfg["cities"])

    def toggle_city(self, name):
        cities = self.cfg["cities"]
        if name in cities:
            if len(cities) > 1:
                cities.remove(name)
        elif len(cities) < MAX:
            cities.append(name)
        config.save()
        self.apply_shape()
        self.update()

    def double_click(self):
        open_uri("ms-clock:")

    def paintEvent(self, event):
        super().paintEvent(event)  # стекло
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        r = QRectF(self.card()).adjusted(18, 12, -18, -10)
        dark = bool(self.dark)
        fg = QColor("#ededf0") if dark else QColor("#151517")
        dim = QColor(fg)
        dim.setAlpha(130)
        head = QFont("Segoe UI Semibold")
        head.setPixelSize(15)
        p.setFont(head)
        p.setPen(fg)
        p.drawText(QRectF(r.left(), r.top(), r.width(), 22), Qt.AlignLeft | Qt.AlignVCenter, tr("Мировое время"))

        here = datetime.now().astimezone()
        name_font = QFont("Segoe UI Semibold")
        name_font.setPixelSize(14)
        sub_font = QFont("Segoe UI")
        sub_font.setPixelSize(11)
        time_font = QFont("Bahnschrift SemiBold")
        time_font.setPixelSize(24)
        if self.shape() == "tiles":
            self._tiles(p, r, here, fg, dim, name_font, sub_font, time_font)
            return
        step = max(ROW, (r.height() - 32) / len(self.cfg["cities"]))  # строки — на всю высоту ячеек сетки
        for i, city in enumerate(self.cfg["cities"]):
            t = datetime.now(ZoneInfo(CITIES[city]))
            top = r.top() + 32 + i * step + (step - ROW) / 2
            day = 7 <= t.hour < 19
            p.drawPixmap(QPointF(r.left(), top + 8), icons.pixmap("sun" if day else "moon", 24))
            p.setFont(name_font)
            p.setPen(fg)
            p.drawText(QRectF(r.left() + 34, top + 3, 150, 20), Qt.AlignLeft | Qt.AlignVCenter, tr(city))
            p.setFont(sub_font)
            p.setPen(dim)
            when = "" if t.date() == here.date() else (tr(" · завтра") if t.date() > here.date() else tr(" · вчера"))
            p.drawText(QRectF(r.left() + 34, top + 21, 170, 16), Qt.AlignLeft | Qt.AlignVCenter,
                       hours(t.utcoffset() - here.utcoffset()) + when)
            p.setFont(time_font)
            p.setPen(fg)
            p.drawText(QRectF(r.left(), top, r.width(), 40), Qt.AlignRight | Qt.AlignVCenter, t.strftime("%H:%M"))

    def _tiles(self, p, r, here, fg, dim, name_font, sub_font, time_font):
        """Вид «Плитки»: города по два в ряд — плашка с городом, крупным временем и разницей."""
        w = (r.width() - 10) / 2
        tile_bg = QColor(fg)
        tile_bg.setAlpha(18)
        time_font.setPixelSize(22)
        rows = (len(self.cfg["cities"]) + 1) // 2
        step = max(TILE, (r.height() - 32) / rows)  # плитки — на всю высоту ячеек сетки
        for i, city in enumerate(self.cfg["cities"]):
            t = datetime.now(ZoneInfo(CITIES[city]))
            box = QRectF(r.left() + (i % 2) * (w + 10), r.top() + 32 + (i // 2) * step, w, step - 8)
            p.setPen(Qt.NoPen)
            p.setBrush(tile_bg)
            p.drawRoundedRect(box, 12, 12)
            inner = box.adjusted(10, 3, -10, -3)
            p.setFont(name_font)
            p.setPen(fg)
            p.drawText(QRectF(inner.left(), inner.top(), inner.width() - 20, 18), Qt.AlignLeft | Qt.AlignVCenter, tr(city))
            p.drawPixmap(QPointF(inner.right() - 18, inner.top() + 1), icons.pixmap("sun" if 7 <= t.hour < 19 else "moon", 18))
            p.setFont(time_font)
            p.drawText(QRectF(inner.left(), inner.bottom() - 26, inner.width(), 26), Qt.AlignLeft | Qt.AlignVCenter,
                       t.strftime("%H:%M"))
            p.setFont(sub_font)
            p.setPen(dim)
            p.drawText(QRectF(inner.left(), inner.bottom() - 26, inner.width(), 26), Qt.AlignRight | Qt.AlignVCenter,
                       hours(t.utcoffset() - here.utcoffset()))
