"""Воздух: индекс качества и частицы по месту из виджета «Погода» (Open-Meteo, без ключа).
Данные модельные, не с датчика у дома: обновляются раз в час, запрашиваем раз в 30 минут."""
from lang import tr
import threading
import time

from PySide6.QtCore import QRectF, QTimer, Signal
from PySide6.QtGui import QColor, QPainter

from core import DesktopWidget, config, grid
from widgets import kit
from widgets.weather import get_json

URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
LEVELS = [(20, tr("чистый"), "#4ade80"), (40, tr("хороший"), "#a3e635"), (60, tr("средний"), "#fbbf24"),
          (80, tr("плохой"), "#fb923c"), (100, tr("очень плохой"), "#f87171"), (10 ** 6, tr("опасный"), "#c084fc")]


def level(aqi):
    return next((text, QColor(color)) for limit, text, color in LEVELS if aqi <= limit)


class AirWidget(DesktopWidget):
    key = "air"
    title = tr("Воздух")
    description = tr("Качество воздуха и пыль PM2.5 там же, где погода")
    SHAPES = {"full": (tr("Полный"), grid(2, 1)), "ring": (tr("Кольцо"), grid(1, 1))}
    loaded = Signal(dict)
    cache = {}  # последний ответ на все копии: каталог не дёргает сервер на каждое открытие

    def __init__(self, **kw):
        super().__init__(**kw)
        self.apply_shape()
        self.data = AirWidget.cache.get("data", {})
        self.error = ""
        self.loaded.connect(self.show_data)
        self.timer = QTimer(self, interval=30 * 60 * 1000, timeout=self.refresh)
        self.timer.start()
        self.refresh()

    def add_actions(self, menu):
        menu.addAction(tr("Обновить"), lambda: self.refresh(force=True))

    def refresh(self, force=False):
        if not force and time.time() - AirWidget.cache.get("time", 0) < 25 * 60:
            return
        place = config.section("weather")
        if "lat" not in place or "lon" not in place:
            self.error = tr("Сначала выбери город в «Погоде»")
            self.update()
            return
        threading.Thread(target=self._fetch, args=(place["lat"], place["lon"]), daemon=True).start()

    def retry(self):
        self.refresh(force=True)

    def _fetch(self, lat, lon):
        try:
            answer = get_json(URL, latitude=lat, longitude=lon, current="european_aqi,pm2_5,pm10,nitrogen_dioxide", timezone="auto")
            data = {k: answer["current"][k] for k in ("european_aqi", "pm2_5", "pm10", "nitrogen_dioxide")}
            if data["european_aqi"] is None:
                raise ValueError("нет данных")
        except Exception as ex:
            data = {"error": type(ex).__name__}
        try:
            self.loaded.emit(data)
        except RuntimeError:  # виджет уже закрыли
            pass

    def show_data(self, data):
        if "error" in data:
            self.error = tr("нет связи ({})").format(data["error"])
            QTimer.singleShot(60 * 1000, self.retry)
        else:
            self.error = ""
            self.data = data
            AirWidget.cache.update(data=data, time=time.time())
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)  # стекло
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        r = QRectF(self.card())
        fg, dim, track = kit.ink(self)
        dark = bool(self.dark)
        d = self.data
        aqi = d.get("european_aqi")
        name, color = level(aqi) if aqi is not None else (tr("нет данных"), kit.GRAY)
        c, R, tile = kit.ring_tile(r)
        kit.ring(p, c, R, (aqi or 0) / 100, color, track)
        kit.ring_label(p, c, R, "—" if aqi is None else f"{aqi:.0f}", "AQI", fg, dim)
        if self.shape() == "ring":
            return
        x = tile.right() + 16
        w = r.right() - 16 - x
        cw = kit.chip(p, r, name, color, dark)
        kit.text(p, QRectF(x, r.top() + 14, w - cw - 6, 22), tr("Воздух"), fg, 16, "Segoe UI Semibold", elide=True)
        place = config.section("weather").get("city", "")
        kit.text(p, QRectF(x, r.top() + 40, w, 18), self.error or place, kit.RED if self.error else fg, 13, "Segoe UI Semibold", elide=True)
        col = w / 3
        rows = (("pm2_5", "PM2.5"), ("pm10", "PM10"), ("nitrogen_dioxide", "NO₂"))
        for i, (k, label) in enumerate(rows):
            value = d.get(k)
            cx = x + i * col
            kit.text(p, QRectF(cx, r.bottom() - 56, col, 26), "—" if value is None else f"{value:.0f}", fg, 22, "Bahnschrift SemiBold")
            kit.text(p, QRectF(cx, r.bottom() - 30, col, 14), label, dim, 11)
        kit.text(p, QRectF(x, r.top() + 60, w, 16), tr("мкг/м³, модель Open-Meteo"), dim, 11, elide=True)
