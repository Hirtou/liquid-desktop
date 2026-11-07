"""Солнце: восход и закат в городе из «Погоды», дуга с солнцем на ней сейчас, длина дня."""
from lang import tr
import math
import threading
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen

import icons
from core import DesktopWidget, config, grid
from widgets.weather import find_places, get_json

ORANGE, GOLD = QColor("#ff9f1c"), QColor("#ffd54a")


def fetch_sun(place):
    """Восход и закат для места из «Погоды» (точные координаты, если выбраны из списка)."""
    try:
        if "lat" in place:
            name, lat, lon = place.get("city", ""), place["lat"], place["lon"]
        else:
            found = find_places(place.get("city", tr("Москва")))
            if not found:
                return {"error": tr("город не найден")}
            name, lat, lon = found[0]["city"], found[0]["lat"], found[0]["lon"]
        data = get_json("https://api.open-meteo.com/v1/forecast", latitude=lat, longitude=lon,
                        daily="sunrise,sunset", timezone="auto", forecast_days=2)
        data["name"] = name
        return data
    except Exception as ex:
        return {"error": tr("нет связи ({})").format(type(ex).__name__)}


class SunWidget(DesktopWidget):
    key = "sun"
    title = tr("Солнце")
    description = tr("Восход, закат и длина дня")
    SHAPES = {"arc": (tr("Дуга"), grid(2, 1)), "compact": (tr("Коротко"), grid(1, 1))}
    loaded = Signal(object)

    def __init__(self, **kw):
        super().__init__(**kw)
        self.apply_shape()
        self.data = None
        self.loaded.connect(self.on_data)
        self.timer = QTimer(self, interval=60 * 1000, timeout=self.on_minute)  # солнце сдвигается за минуту
        self.timer.start()
        self.refresh()

    def refresh(self):
        place = dict(config.section("weather"))
        threading.Thread(target=self._fetch, args=(place,), daemon=True).start()

    def _fetch(self, place):
        data = fetch_sun(place)
        try:
            self.loaded.emit(data)
        except RuntimeError:
            pass

    def on_data(self, data):
        self.data = data
        self.update()

    def on_minute(self):
        if self.data and "error" not in self.data and self.local_now().date().isoformat() != self.data["daily"]["time"][0]:
            self.refresh()  # наступил новый день — новые восход и закат
        self.update()

    def local_now(self):
        offset = timedelta(seconds=self.data.get("utc_offset_seconds", 0))
        return datetime.now(timezone.utc).astimezone(timezone(offset)).replace(tzinfo=None)

    def paintEvent(self, event):
        super().paintEvent(event)  # стекло
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        r = QRectF(self.card()).adjusted(18, 12, -18, -12)
        dark = bool(self.dark)
        fg = QColor("#ededf0") if dark else QColor("#151517")
        dim = QColor(fg)
        dim.setAlpha(130)
        head = QFont("Segoe UI Semibold")
        head.setPixelSize(15)
        p.setFont(head)
        p.setPen(fg)
        name = self.data.get("name", "") if self.data else ""
        p.drawText(QRectF(r.left(), r.top(), r.width(), 22), Qt.AlignLeft | Qt.AlignVCenter,
                   tr("Солнце · {}").format(name) if name and self.shape() != "compact" else tr("Солнце"))  # 1×1 — без города
        if not self.data or "error" in self.data:
            p.setPen(dim)
            p.drawText(r, Qt.AlignCenter, self.data["error"] if self.data else tr("загрузка…"))
            return

        rise = datetime.fromisoformat(self.data["daily"]["sunrise"][0])
        set_ = datetime.fromisoformat(self.data["daily"]["sunset"][0])
        now = self.local_now()
        frac = (now - rise) / (set_ - rise)
        if self.shape() == "compact":
            self._compact(p, r, rise, set_, fg, dim)
            return

        # дуга: полуэллипс от восхода (слева) до заката (справа)
        base = r.bottom() - 34
        arc = QRectF(r.left() + 20, base - (r.height() - 70), r.width() - 40, 2 * (r.height() - 70))
        track = QColor(fg)
        track.setAlpha(60)
        p.setPen(QPen(track, 2, Qt.DashLine))
        p.drawArc(arc, 0, 180 * 16)
        p.setPen(QPen(track, 1))
        p.drawLine(QPointF(r.left(), base), QPointF(r.right(), base))
        if 0 < frac < 1:  # пройденная часть дня — тёплым цветом
            grad = QLinearGradient(arc.left(), 0, arc.right(), 0)
            grad.setColorAt(0, ORANGE)
            grad.setColorAt(1, GOLD)
            p.setPen(QPen(grad, 3, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(arc, 180 * 16, int(-frac * 180 * 16))
            a = math.pi * (1 - frac)
            pos = QPointF(arc.center().x() + math.cos(a) * arc.width() / 2,
                          arc.center().y() - math.sin(a) * arc.height() / 2)
            p.drawPixmap(pos - QPointF(13, 13), icons.pixmap("sun", 26))
        else:
            p.drawPixmap(QPointF(arc.center().x() - 13, base - 40), icons.pixmap("moon", 26))

        small = QFont("Segoe UI Semibold")
        small.setPixelSize(13)
        p.setFont(small)
        for x, align, label, t in ((r.left(), Qt.AlignLeft, tr("восход"), rise), (r.right() - 120, Qt.AlignRight,
                                                                            tr("закат"), set_)):
            p.setPen(fg)
            p.drawText(QRectF(x, base + 4, 120, 16), align | Qt.AlignVCenter, t.strftime("%H:%M"))
            p.setPen(dim)
            p.setFont(QFont("Segoe UI", 8))
            p.drawText(QRectF(x, base + 18, 120, 14), align | Qt.AlignVCenter, label)
            p.setFont(small)
        length = set_ - rise
        h, m = divmod(int(length.total_seconds() // 60), 60)
        p.setPen(dim)
        p.drawText(QRectF(r.left(), base + 4, r.width(), 16), Qt.AlignHCenter | Qt.AlignVCenter, tr("день {} ч {} мин").format(h, m))

    def _compact(self, p, r, rise, set_, fg, dim):
        """Вид «Коротко» (1×1): восход и закат столбиком — значок, крупное время, подпись; внизу длина дня."""
        h, m = divmod(int((set_ - rise).total_seconds() // 60), 60)
        big = QFont("Bahnschrift SemiBold")
        big.setPixelSize(24)
        label = QFont("Segoe UI")
        label.setPixelSize(11)
        for i, (icon, t, text) in enumerate((("sun", rise, tr("восход")), ("moon", set_, tr("закат")))):
            top = r.top() + 30 + i * 46
            p.drawPixmap(QPointF(r.left(), top + 6), icons.pixmap(icon, 24))
            p.setFont(big)
            p.setPen(fg)
            p.drawText(QRectF(r.left() + 32, top, r.width() - 32, 28), Qt.AlignLeft | Qt.AlignVCenter,
                       t.strftime("%H:%M"))
            p.setFont(label)
            p.setPen(dim)
            p.drawText(QRectF(r.left() + 32, top + 26, r.width() - 32, 14), Qt.AlignLeft | Qt.AlignVCenter, text)
        p.drawText(QRectF(r.left(), r.bottom() - 14, r.width(), 14), Qt.AlignLeft | Qt.AlignVCenter,
                   tr("день {} ч {} мин").format(h, m))
