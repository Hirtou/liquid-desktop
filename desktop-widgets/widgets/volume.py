"""Громкость: общий звук Windows — ползунок (тянуть или крутить колесо), кнопка «без звука», устройство."""
from lang import tr

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen

from core import DesktopWidget, activity, grid, open_uri
from widgets import kit


class Audio:
    """Windows Core Audio через pycaw (подгружается только когда виджет включён)."""

    def __init__(self):
        self.endpoint, self.name = None, ""
        self.refresh()

    def refresh(self):
        try:
            from pycaw.pycaw import AudioUtilities
            dev = AudioUtilities.GetSpeakers()
            self.endpoint = dev.EndpointVolume
            name = dev.FriendlyName or ""
            # «Динамики (fifine Headset)» -> «fifine Headset»
            self.name = name[name.find("(") + 1:name.rfind(")")] if "(" in name and name.endswith(")") else name
        except Exception:
            self.endpoint = None

    def read(self):
        try:
            return self.endpoint.GetMasterVolumeLevelScalar(), bool(self.endpoint.GetMute())
        except Exception:
            return None

    def set(self, v):
        try:
            self.endpoint.SetMasterVolumeLevelScalar(max(0.0, min(1.0, v)), None)
            if v > 0 and self.endpoint.GetMute():
                self.endpoint.SetMute(0, None)
        except Exception:
            pass

    def toggle_mute(self):
        try:
            self.endpoint.SetMute(0 if self.endpoint.GetMute() else 1, None)
        except Exception:
            pass


class VolumeWidget(DesktopWidget):
    key = "volume"
    title = tr("Громкость")
    description = tr("Звук Windows: ползунок, колесо, без звука")
    SHAPES = {"full": (tr("Полный"), grid(2, 1))}

    def __init__(self, **kw):
        super().__init__(**kw)
        self.apply_shape()
        self.audio = Audio()
        self.value, self.muted = 0.0, False
        self.track_rect = self.mute_rect = self.tile = None
        self.sliding = False
        self.polls = 0
        self.timer = QTimer(self, interval=1000, timeout=self.poll)  # громкость могли поменять клавишами
        self.timer.start()
        self.poll()

    def poll(self):
        self.polls += 1
        if self.polls % 30 == 0 or self.audio.endpoint is None:  # сменились наушники/динамики
            self.audio.refresh()
        if activity.covered(self) and self.polls > 1:
            return
        state = self.audio.read()
        if state is None:
            return
        value, muted = state
        if not self.sliding and (abs(value - self.value) > 0.004 or muted != self.muted):
            self.value, self.muted = value, muted
            self.update()

    def set_value(self, v):
        self.value = max(0.0, min(1.0, v))
        self.muted = False if self.value > 0 else self.muted
        self.audio.set(self.value)
        self.update()

    def click(self, pos):
        if self.mute_rect is not None and self.mute_rect.contains(pos):
            self.audio.toggle_mute()
            self.muted = not self.muted
            self.update()
            return True
        if self.track_rect is not None and self.track_rect.adjusted(-8, -12, 8, 12).contains(pos):
            self.sliding = True
            self.slide(pos)
            return True
        return False

    def slide(self, pos):
        self.set_value((pos.x() - self.track_rect.left()) / self.track_rect.width())

    def mouseMoveEvent(self, event):
        if self.sliding:
            self.slide(event.position() / self.scale())
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.sliding = False
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        self.set_value(self.value + (0.02 if event.angleDelta().y() > 0 else -0.02))

    def double_click(self):
        open_uri("ms-settings:sound")

    def paintEvent(self, event):
        super().paintEvent(event)  # стекло
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        r = QRectF(self.card())
        fg, dim, track = kit.ink(self)
        dark = bool(self.dark)
        ready = self.audio.endpoint is not None
        pct = round(self.value * 100)

        tile = QRectF(r.left() + 14, r.top() + 14, r.height() - 28, r.height() - 28)
        self.mute_rect = tile
        grad = QLinearGradient(tile.topLeft(), tile.bottomLeft())
        grad.setColorAt(0, QColor("#6b7280" if self.muted else "#7c5cff"))
        grad.setColorAt(1, QColor("#3f4552" if self.muted else "#4338ca"))
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        p.drawRoundedRect(tile, 22, 22)
        self._speaker(p, tile.center(), tile.width() * 0.5)

        x = tile.right() + 16
        w = r.right() - 18 - x
        if not ready:
            name, color = tr("нет устройства"), kit.GRAY
        elif self.muted:
            name, color = tr("без звука"), kit.RED
        else:
            name, color = tr("тихо") if pct < 25 else tr("громко") if pct > 75 else tr("средне"), kit.GREEN
        cw = kit.chip(p, r, name, color, dark)
        kit.text(p, QRectF(x, r.top() + 14, w - cw, 22), tr("Звук"), fg, 16, "Segoe UI Semibold", elide=True)
        kit.text(p, QRectF(x, r.top() + 42, w, 46), f"{pct}%", dim if self.muted else fg, 38, "Bahnschrift SemiBold")
        kit.text(p, QRectF(x, r.top() + 88, w, 16), self.audio.name or tr("нужен пакет pycaw"), dim, 11, elide=True)
        self.track_rect = QRectF(x + 2, r.bottom() - 30, w - 4, 8)
        kit.bar(p, self.track_rect, self.value, kit.GRAY if self.muted else kit.ACCENT, track)
        knob = QPointF(self.track_rect.left() + self.track_rect.width() * self.value, self.track_rect.center().y())
        p.setPen(QPen(QColor(0, 0, 0, 40), 1))
        p.setBrush(QColor("white"))
        p.drawEllipse(knob, 9, 9)

    def _speaker(self, p, c, s):
        white = QColor("white")
        h = s / 2
        body = QPainterPath(QPointF(c.x() - h * 0.9, c.y() - h * 0.32))
        body.lineTo(c.x() - h * 0.42, c.y() - h * 0.32)
        body.lineTo(c.x() + h * 0.08, c.y() - h * 0.78)
        body.lineTo(c.x() + h * 0.08, c.y() + h * 0.78)
        body.lineTo(c.x() - h * 0.42, c.y() + h * 0.32)
        body.lineTo(c.x() - h * 0.9, c.y() + h * 0.32)
        body.closeSubpath()
        p.setPen(QPen(white, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(white)
        p.drawPath(body)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(white, s * 0.09, Qt.SolidLine, Qt.RoundCap))
        if self.muted:
            p.drawLine(QPointF(c.x() + h * 0.35, c.y() - h * 0.3), QPointF(c.x() + h * 0.95, c.y() + h * 0.3))
            p.drawLine(QPointF(c.x() + h * 0.95, c.y() - h * 0.3), QPointF(c.x() + h * 0.35, c.y() + h * 0.3))
            return
        waves = (1 if self.value > 0 else 0) + (1 if self.value > 0.5 else 0)
        for i in range(waves):
            d = h * (0.55 + i * 0.42)
            p.drawArc(QRectF(c.x() + h * 0.08 - d, c.y() - d, 2 * d, 2 * d), -45 * 16, 90 * 16)
