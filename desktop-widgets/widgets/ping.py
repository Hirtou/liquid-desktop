"""Пинг: задержка до Google, Cloudflare и Steam (время TCP-соединения, раз в 2 с в фоне) и график за минуту.
ICMP-пинг в Windows требует прав или запуска ping.exe — TCP-соединение честно показывает задержку без этого."""
from lang import tr
import socket
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPen

from core import DesktopWidget, activity, grid, open_uri

HOSTS = [("Google", "google.com", 443), ("Cloudflare", "1.1.1.1", 443), ("Steam", "steamcommunity.com", 443)]
SAMPLES = 30  # по 2 с — минута
GREEN, AMBER, RED, BLUE = QColor("#4ade80"), QColor("#ffb547"), QColor("#ff5a5f"), QColor("#60a5fa")


POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ping")  # один поток на все замеры


def measure(host, port, cache={}):
    """Время TCP-соединения, мс; None — не достучались. Адрес ищем один раз (иначе в пинг попадёт DNS)."""
    try:
        if host not in cache:
            cache[host] = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)[0][4]
        t = time.perf_counter()
        with socket.create_connection(cache[host], timeout=2):
            return (time.perf_counter() - t) * 1000
    except OSError:
        cache.pop(host, None)  # сеть могла смениться — в следующий раз искать заново
        return None


def quality(ms):
    if ms is None:
        return tr("нет связи"), RED
    return (tr("хороший"), GREEN) if ms < 60 else (tr("средний"), AMBER) if ms < 120 else (tr("плохой"), RED)


class PingWidget(DesktopWidget):
    key = "ping"
    title = tr("Пинг")
    description = tr("Задержка до Google, Cloudflare, Steam и график")
    SHAPES = {"full": (tr("С графиком"), grid(2, 1)), "small": (tr("Только цифра"), grid(1, 1))}
    measured = Signal(object)

    def __init__(self, **kw):
        super().__init__(**kw)
        self.apply_shape()
        self.last = [None] * len(HOSTS)
        self.history = deque([None] * SAMPLES, maxlen=SAMPLES)
        self.busy = False
        self.measured.connect(self.on_result)
        self.timer = QTimer(self, interval=2000, timeout=self.refresh)
        self.timer.start()
        self.refresh()

    def refresh(self):
        if not self.busy and not activity.paused(self):  # в игре и под окном не шлём соединения: цифр всё равно не видно
            self.busy = True
            POOL.submit(self._measure)

    def _measure(self):
        result = [measure(h, port) for _, h, port in HOSTS]
        try:
            self.measured.emit(result)
        except RuntimeError:
            pass

    def on_result(self, result):
        self.busy = False
        self.last = result
        ok = [v for v in result if v is not None]
        self.history.append(min(ok) if ok else None)
        self.update()

    def double_click(self):
        open_uri("ms-settings:network-status")

    def best(self):
        ok = [v for v in self.last if v is not None]
        return min(ok) if ok else None

    def paintEvent(self, event):
        super().paintEvent(event)  # стекло
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        r = QRectF(self.card()).adjusted(18, 14, -18, -14)
        dark = bool(self.dark)
        fg = QColor("#ededf0") if dark else QColor("#151517")
        dim = QColor(fg)
        dim.setAlpha(140)
        best = self.best()
        chip, color = quality(best)
        if self.history.count(None) == SAMPLES and best is None and not any(self.last):
            chip, color = tr("меряю…"), QColor("#9aa0aa")

        title = QFont("Segoe UI Semibold")
        title.setPixelSize(15)
        p.setFont(title)
        p.setPen(fg)
        p.drawText(QRectF(r.left(), r.top(), r.width(), 20), Qt.AlignLeft | Qt.AlignVCenter, tr("Пинг"))
        cf = QFont("Segoe UI Semibold")
        cf.setPixelSize(11)
        cw = QFontMetricsF(cf).horizontalAdvance(chip) + 24
        pill = QRectF(r.right() - cw, r.top(), cw, 20)
        bg = QColor(color)
        bg.setAlpha(55 if dark else 70)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(pill, 10, 10)
        p.setBrush(color)
        p.drawEllipse(QRectF(pill.left() + 8, pill.center().y() - 3.5, 7, 7))
        p.setFont(cf)
        p.setPen(color.lighter(130) if dark else color.darker(170))
        p.drawText(pill.adjusted(19, 0, -6, 0), Qt.AlignVCenter | Qt.AlignLeft, chip)

        num = QFont("Bahnschrift SemiBold")
        small = QFont("Segoe UI")
        small.setPixelSize(11)
        if self.shape() == "small":  # 1×1: лучшая задержка крупно
            num.setPixelSize(40)
            p.setFont(num)
            p.setPen(fg)
            p.drawText(QRectF(r.left(), r.top() + 34, r.width(), 50), Qt.AlignLeft | Qt.AlignVCenter,
                       f"{best:.0f}" if best is not None else "—")
            p.setFont(small)
            p.setPen(dim)
            p.drawText(QRectF(r.left(), r.top() + 84, r.width(), 16), Qt.AlignLeft | Qt.AlignVCenter, tr("мс, лучший"))
            line = " · ".join(f"{v:.0f}" if v is not None else "—" for v in self.last)
            p.drawText(QRectF(r.left(), r.bottom() - 16, r.width(), 16), Qt.AlignLeft | Qt.AlignVCenter, line)
            return

        # три цифры: Google, Cloudflare, Steam
        num.setPixelSize(20)
        col_w = r.width() / len(HOSTS)
        for i, (name, _, _) in enumerate(HOSTS):
            v = self.last[i]
            x = r.left() + i * col_w
            p.setFont(num)
            p.setPen((quality(v)[1] if dark else quality(v)[1].darker(150)) if v is not None else dim)  # на светлом — темнее, иначе жёлтое не видно
            p.drawText(QRectF(x, r.top() + 28, col_w, 24), Qt.AlignLeft | Qt.AlignVCenter,
                       tr("{:.0f} мс").format(v) if v is not None else "—")
            p.setFont(small)
            p.setPen(dim)
            p.drawText(QRectF(x, r.top() + 52, col_w, 14), Qt.AlignLeft | Qt.AlignVCenter, name)

        # график лучшей задержки за минуту
        g = QRectF(r.left(), r.top() + 74, r.width(), r.bottom() - r.top() - 74)
        vals = list(self.history)
        known = [v for v in vals if v is not None]
        top = max(max(known) * 1.2 if known else 100, 60)
        p.setPen(QPen(dim, 1, Qt.DotLine))
        p.drawLine(g.bottomLeft(), g.bottomRight())
        pts = [QPointF(g.left() + g.width() * i / (SAMPLES - 1), g.bottom() - g.height() * min(v, top) / top)
               for i, v in enumerate(vals) if v is not None]
        if len(pts) >= 2:
            line = QPainterPath(pts[0])
            for a, b in zip(pts, pts[1:]):
                mid = (a.x() + b.x()) / 2
                line.cubicTo(QPointF(mid, a.y()), QPointF(mid, b.y()), b)
            fill = QPainterPath(line)
            fill.lineTo(pts[-1].x(), g.bottom())
            fill.lineTo(pts[0].x(), g.bottom())
            fill.closeSubpath()
            grad = QLinearGradient(0, g.top(), 0, g.bottom())
            c1, c2 = QColor(BLUE), QColor(BLUE)
            c1.setAlpha(90)
            c2.setAlpha(0)
            grad.setColorAt(0, c1)
            grad.setColorAt(1, c2)
            p.setPen(Qt.NoPen)
            p.setBrush(grad)
            p.drawPath(fill)
            p.setPen(QPen(BLUE, 2))
            p.setBrush(Qt.NoBrush)
            p.drawPath(line)
        if known and None in vals[vals.index(known[0]):]:  # после первого замера были пропуски
            p.setPen(RED)
            p.setFont(small)
            p.drawText(g, Qt.AlignRight | Qt.AlignTop, tr("были обрывы"))
