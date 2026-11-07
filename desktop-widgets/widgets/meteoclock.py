"""Метеочасы в духе ColorOS: риски по краю, большие цифры, стрелки поверх, дата и погода."""
from lang import tr
import math
import threading
from datetime import datetime

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen, QPixmap

import icons
from core import DesktopWidget, activity, config, grid, open_uri
from widgets.weather import fetch, now_values

# такт плавной секундной стрелки: она проходит ~9 px в секунду — при 15 кадрах это 0.6 px за кадр,
# глазу так же плавно, как при 30, а рисовать вдвое меньше
SMOOTH = 66

MONTHS = [tr("янв."), tr("февр."), tr("мар."), tr("апр."), tr("мая"), tr("июн."), tr("июл."), tr("авг."), tr("сент."), tr("окт."), tr("нояб."), tr("дек.")]
DAYS = [tr("пн"), tr("вт"), tr("ср"), tr("чт"), tr("пт"), tr("сб"), tr("вс")]
BLUE = QColor("#2f6bff")


class MeteoClockWidget(DesktopWidget):
    key = "meteoclock"
    title = tr("Метеочасы")
    description = tr("Стрелки, цифры, дата и погода")
    SHAPES = {"wide": (tr("Широкие"), grid(2, 1)), "square": (tr("Квадратные"), grid(1, 1))}
    loaded = Signal(object)

    def __init__(self, **kw):
        super().__init__(**kw)
        self.weather = None
        self.face, self.face_key = None, None  # кэш циферблата (без стрелок)
        self.apply_shape()
        self.loaded.connect(self.on_weather)
        # секундная стрелка: плавно, пока смотришь на стол; в окнах — раз в секунду
        self.tick = QTimer(self, interval=1000, timeout=self.on_tick, timerType=Qt.PreciseTimer)
        self.tick.start()
        self.weather_timer = QTimer(self, interval=15 * 60 * 1000, timeout=self.refresh_weather)
        self.weather_timer.start()
        self.refresh_weather()

    # ---------- форма и данные ----------

    def double_click(self):
        open_uri("ms-clock:")

    def push_interval(self):
        # под ярлыками: плавная секундная стрелка, пока смотришь на стол; иначе раз в секунду
        return SMOOTH if activity.mode == "desktop" else 1000

    def on_tick(self):
        interval = SMOOTH if activity.mode == "desktop" and self.isVisible() else 1000
        if self.tick.interval() != interval:
            self.tick.setInterval(interval)
        if activity.covered(self):  # закрыт окном или игрой — кадр не нужен (откроют — нарисуется сам)
            return
        minute = datetime.now().minute
        if interval == SMOOTH and minute == getattr(self, "_minute", None):
            self.update(self.hands_rect())  # плавная стрелка: каждый кадр — только квадрат со стрелками
        else:
            self._minute = minute
            self.update()  # новая минута (цифры, дата) или редкий такт — весь виджет

    def hands_rect(self):
        """Где ходят стрелки (с тенью), в координатах окна — с масштабом виджета."""
        r = QRectF(self.card())
        R = min(r.width(), r.height()) / 2 + 6
        k = self.scale()
        c = r.center() * k
        return QRectF(c.x() - R * k, c.y() - R * k, 2 * R * k, 2 * R * k).toAlignedRect()

    def refresh_weather(self):
        place = dict(config.section("weather"))  # место — как у виджета «Погода»
        threading.Thread(target=self._fetch, args=(place,), daemon=True).start()

    def _fetch(self, place):
        data = fetch(place)
        try:
            self.loaded.emit(data)
        except RuntimeError:  # виджет уже закрыли
            pass

    def on_weather(self, data):
        if "error" not in data:
            self.weather = now_values(data)  # «сейчас» — с метеостанции, если она рядом
            self.update()

    # ---------- рисование ----------

    def paintEvent(self, event):
        super().paintEvent(event)  # стекло
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        r = QRectF(self.card())
        now = datetime.now()
        # всё, кроме стрелок, меняется раз в минуту — рисуем в картинку один раз и кладём каждый кадр
        weather = tuple(sorted(self.weather.items())) if self.weather else None
        key = (self.card().size(), bool(self.dark), now.strftime("%Y%m%d%H%M"), weather, self.devicePixelRatioF())
        if key != self.face_key:
            self.face_key = key
            dpr = self.devicePixelRatioF()
            self.face = QPixmap(int(r.width() * dpr), int(r.height() * dpr))
            self.face.setDevicePixelRatio(dpr)
            self.face.fill(Qt.transparent)
            fp = QPainter(self.face)
            fp.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
            self._face(fp, QRectF(0, 0, r.width(), r.height()), now)
            fp.end()
        # часовая и минутная почти стоят (минутная — 0.1° в секунду): кладём их в ту же картинку, что и циферблат,
        # и перерисовываем, когда минутная сдвинулась на 0.15° (~раз в 1.5 с, это меньше трети пикселя);
        # каждый кадр — одна картинка, тонкая секундная и центр
        s = now.second + now.microsecond / 1e6
        m = now.minute + s / 60
        slow_key = (self.face_key, int(m * 6 / 0.15))
        if slow_key != getattr(self, "slow_key", None):
            self.slow_key = slow_key
            self.slow = QPixmap(self.face)
            bp = QPainter(self.slow)
            bp.setRenderHints(QPainter.Antialiasing)
            box = QRectF(0, 0, r.width(), r.height())
            self._slow_hands(bp, box.center(), min(r.width(), r.height()) / 2, now.hour % 12 + m / 60, m,
                             bool(self.dark))
            bp.end()
        p.drawPixmap(r.topLeft(), self.slow)
        self._second(p, r.center(), min(r.width(), r.height()) / 2, s, bool(self.dark))

    def _face(self, p, r, now):
        """Циферблат без стрелок: риски, цифры, дата, погода."""
        W, H = r.width(), r.height()
        c = r.center()
        wide = W > H * 1.3
        dark = bool(self.dark)
        fg = QColor("#ededf0") if dark else QColor("#151517")
        dim = QColor(fg)
        dim.setAlpha(150)

        self._ticks(p, r, c, fg)

        # цифры: часы слева, минуты справа
        digits = QFont("Bahnschrift SemiBold Condensed")
        digits.setPixelSize(int(H * (0.5 if wide else 0.34)))
        p.setFont(digits)
        p.setPen(fg)
        if wide:
            left = QRectF(c.x() - W * 0.46, r.top(), W * 0.4, H)
            right = QRectF(c.x() + W * 0.06, r.top(), W * 0.4, H)
            p.drawText(left, Qt.AlignCenter, now.strftime("%H"))
            p.drawText(right, Qt.AlignCenter, now.strftime("%M"))
        else:
            p.drawText(QRectF(r.left(), r.top(), W / 2 - W * 0.04, H), Qt.AlignRight | Qt.AlignVCenter,
                       now.strftime("%H"))
            p.drawText(QRectF(c.x() + W * 0.04, r.top(), W / 2, H), Qt.AlignLeft | Qt.AlignVCenter,
                       now.strftime("%M"))

        # дата сверху: «нояб. 1-го, вс», день недели — синим
        small = QFont("Segoe UI Semibold")
        small.setPixelSize(int(H * (0.085 if wide else 0.08)))
        p.setFont(small)
        fm = QFontMetricsF(small)
        a = tr("{} {}-го, ").format(MONTHS[now.month - 1], now.day)
        b = DAYS[now.weekday()]
        x = c.x() - (fm.horizontalAdvance(a) + fm.horizontalAdvance(b)) / 2
        y = r.top() + H * (0.25 if wide else 0.22)
        p.setPen(dim)
        p.drawText(QPointF(x, y), a)
        p.setPen(BLUE)
        p.drawText(QPointF(x + fm.horizontalAdvance(a), y), b)

        # погода снизу: значок и температура (в широких — ещё «Ясно»)
        if self.weather:
            temp = f"{self.weather['temp']:.0f}°"
            label = f"{self.weather['text'].capitalize()} {temp}" if wide else temp
            pic = icons.pixmap(icons.weather_kind(self.weather["code"], self.weather["is_day"]), small.pixelSize() * 1.7)
            side = pic.width() / pic.devicePixelRatio()
            gap = side * 0.2
            total = side + gap + fm.horizontalAdvance(label)
            x = c.x() - total / 2
            yc = r.top() + H * 0.78
            p.drawPixmap(QPointF(x, yc - side / 2), pic)
            p.setPen(dim)
            p.drawText(QPointF(x + side + gap, yc + fm.capHeight() / 2), label)

    def _ticks(self, p, r, c, fg):
        """60 рисок по краю, по лучам из центра; часовые длиннее и ярче."""
        m = 12
        hw, hh = r.width() / 2 - m, r.height() / 2 - m
        base = min(r.width(), r.height())
        for i in range(60):
            a = i / 60 * 2 * math.pi
            dx, dy = math.sin(a), -math.cos(a)
            t = min(hw / abs(dx) if abs(dx) > 1e-6 else 1e9, hh / abs(dy) if abs(dy) > 1e-6 else 1e9)
            major = i % 5 == 0
            length = base * (0.12 if major else 0.065)
            color = QColor(fg)
            color.setAlpha(230 if major else 85)
            p.setPen(QPen(color, 2.4 if major else 1.4, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(c.x() + dx * t, c.y() + dy * t),
                       QPointF(c.x() + dx * (t - length), c.y() + dy * (t - length)))

    def _slow_hands(self, p, c, R, h, m, dark):
        """Часовая и минутная (h — часы с долями, m — минуты с долями)."""
        body = QColor("#d9d9de") if dark else QColor("#141416")
        stem = QColor("#9a9aa2") if dark else QColor("#141416")
        shadow = QColor(0, 0, 0, 70)

        def hand(angle, length, width):
            """Стрелка как у ColorOS: тонкая ножка у центра, дальше широкое тело, мягкая тень."""
            foot = R * 0.14
            p.save()
            p.translate(c)
            p.rotate(angle)
            p.setPen(QPen(shadow, width + 1, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(1.2, -foot + 2), QPointF(1.2, -length + 2))
            p.setPen(QPen(stem, 3.2, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(0, 0), QPointF(0, -foot))
            p.setPen(QPen(body, width, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(0, -foot), QPointF(0, -length))
            p.restore()

        hand(h * 30, R * 0.55, 8)
        hand(m * 6, R * 0.86, 6)

    @staticmethod
    def _second(p, c, R, s, dark):
        """Секундная (каждый кадр) и центр поверх всех стрелок."""
        # секундная — тонкая синяя, с хвостиком
        p.save()
        p.translate(c)
        p.rotate(s * 6)
        p.setPen(QPen(BLUE, 2.2, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(0, R * 0.22), QPointF(0, -R * 0.95))
        p.restore()
        # центр: синий кружок с колечком
        p.setPen(Qt.NoPen)
        p.setBrush(BLUE)
        p.drawEllipse(c, 7, 7)
        p.setBrush(QColor("#1d1d22") if dark else QColor("white"))
        p.drawEllipse(c, 3.2, 3.2)
