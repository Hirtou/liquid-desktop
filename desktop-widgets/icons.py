"""Свои значки, нарисованные кодом, — вместо эмодзи Windows.

Погода: pixmap(weather_kind(код, день?), размер). Значки виджетов для каталога: app_icon(имя, размер).
Всё рисуется в квадрате 100×100 и масштабируется, кэшируется.
"""
import math
from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient

DPR = 2.0  # рисуем в двойном разрешении — чётко и на 150–200% масштабе

SUN_IN, SUN_OUT = QColor("#FFD54A"), QColor("#FFA62B")
MOON_IN, MOON_OUT = QColor("#FFE38A"), QColor("#F7B733")
CLOUD_TOP, CLOUD_BOT = QColor("#FFFFFF"), QColor("#C9D3E3")
DARK_TOP, DARK_BOT = QColor("#B9C2D0"), QColor("#7D889B")
RAIN = QColor("#47A3FF")
BOLT = QColor("#FFC93C")


def weather_kind(code, is_day=True):
    """Код погоды WMO -> вид значка."""
    night = not is_day
    if code == 0:
        return "moon" if night else "sun"
    if code in (1, 2):
        return "moon_cloud" if night else "sun_cloud"
    if code == 3:
        return "cloud"
    if code in (45, 48):
        return "fog"
    if 51 <= code <= 57:
        return "drizzle"
    if 61 <= code <= 67 or 80 <= code <= 82:
        return "rain"
    if 71 <= code <= 77 or code in (85, 86):
        return "snow"
    if code >= 95:
        return "storm"
    return "cloud"


# ---------- кирпичики ----------

def _sun(p, cx, cy, r, rays=True):
    if rays:
        p.setPen(QPen(SUN_OUT, r * 0.16, Qt.SolidLine, Qt.RoundCap))
        for i in range(8):
            a = i * math.pi / 4
            p.drawLine(QPointF(cx + math.cos(a) * r * 1.35, cy + math.sin(a) * r * 1.35),
                       QPointF(cx + math.cos(a) * r * 1.7, cy + math.sin(a) * r * 1.7))
    g = QRadialGradient(QPointF(cx - r * 0.3, cy - r * 0.3), r * 1.3)
    g.setColorAt(0, SUN_IN)
    g.setColorAt(1, SUN_OUT)
    p.setPen(Qt.NoPen)
    p.setBrush(g)
    p.drawEllipse(QPointF(cx, cy), r, r)


def _moon(p, cx, cy, r, stars=True):
    full = QPainterPath()
    full.addEllipse(QPointF(cx, cy), r, r)
    bite = QPainterPath()
    bite.addEllipse(QPointF(cx + r * 0.55, cy - r * 0.45), r * 0.85, r * 0.85)
    g = QLinearGradient(cx - r, cy - r, cx + r, cy + r)
    g.setColorAt(0, MOON_IN)
    g.setColorAt(1, MOON_OUT)
    p.setPen(Qt.NoPen)
    p.setBrush(g)
    p.drawPath(full.subtracted(bite))
    if stars:  # искорки, как у ColorOS
        for sx, sy, s in ((cx + r * 0.95, cy - r * 0.9, r * 0.32), (cx + r * 1.35, cy - r * 0.2, r * 0.2)):
            _sparkle(p, sx, sy, s, MOON_IN)


def _sparkle(p, x, y, s, color):
    path = QPainterPath()
    path.moveTo(x, y - s)
    path.quadTo(x, y, x + s, y)
    path.quadTo(x, y, x, y + s)
    path.quadTo(x, y, x - s, y)
    path.quadTo(x, y, x, y - s)
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    p.drawPath(path)


def _cloud(p, x, y, w, dark=False):
    """Облако: левый бок (x, y) — низ облака, ширина w."""
    h = w * 0.5
    base, left, right = QPainterPath(), QPainterPath(), QPainterPath()
    base.addRoundedRect(QRectF(x, y - h * 0.62, w, h * 0.62), h * 0.31, h * 0.31)
    left.addEllipse(QPointF(x + w * 0.32, y - h * 0.62), w * 0.2, w * 0.2)
    right.addEllipse(QPointF(x + w * 0.6, y - h * 0.7), w * 0.27, w * 0.27)
    path = base.united(left).united(right)  # склеить в один контур, без дырок на пересечениях
    g = QLinearGradient(0, y - h * 1.3, 0, y)
    g.setColorAt(0, DARK_TOP if dark else CLOUD_TOP)
    g.setColorAt(1, DARK_BOT if dark else CLOUD_BOT)
    p.setPen(QPen(QColor(0, 0, 0, 22), w * 0.012))
    p.setBrush(g)
    p.drawPath(path)


def _drops(p, xs, y, length, color=RAIN, width=6):
    p.setPen(QPen(color, width, Qt.SolidLine, Qt.RoundCap))
    for x in xs:
        p.drawLine(QPointF(x, y), QPointF(x - length * 0.35, y + length))


def _flakes(p, xs, y, s):
    p.setPen(QPen(QColor("#8CC4FF"), s * 0.28, Qt.SolidLine, Qt.RoundCap))
    for i, x in enumerate(xs):
        cy = y + (i % 2) * s * 1.2
        for k in range(3):
            a = k * math.pi / 3
            p.drawLine(QPointF(x - math.cos(a) * s, cy - math.sin(a) * s),
                       QPointF(x + math.cos(a) * s, cy + math.sin(a) * s))


def _bolt(p, x, y, s):
    path = QPainterPath()
    pts = [(0.15, 0), (0.65, 0), (0.45, 0.42), (0.8, 0.42), (0.2, 1.1), (0.35, 0.58), (0.0, 0.58)]
    path.moveTo(x + pts[0][0] * s, y + pts[0][1] * s)
    for a, b in pts[1:]:
        path.lineTo(x + a * s, y + b * s)
    path.closeSubpath()
    p.setPen(Qt.NoPen)
    p.setBrush(BOLT)
    p.drawPath(path)


# ---------- погода ----------

def _draw_weather(p, kind):
    if kind == "sun":
        _sun(p, 50, 50, 22)
    elif kind == "moon":
        _moon(p, 44, 54, 28)
    elif kind == "sun_cloud":
        _sun(p, 38, 38, 17)
        _cloud(p, 22, 82, 70)
    elif kind == "moon_cloud":
        _moon(p, 38, 40, 20, stars=False)
        _cloud(p, 22, 82, 70)
    elif kind == "cloud":
        _cloud(p, 10, 76, 80)
    elif kind == "fog":
        _cloud(p, 14, 58, 72)
        p.setPen(QPen(QColor("#AEB8C8"), 6, Qt.SolidLine, Qt.RoundCap))
        for i, (a, b) in enumerate(((18, 70), (28, 84))):
            p.drawLine(QPointF(a, 70 + i * 13), QPointF(b, 70 + i * 13))
    elif kind in ("drizzle", "rain"):
        _cloud(p, 12, 62, 76, dark=kind == "rain")
        _drops(p, (36, 54, 72) if kind == "rain" else (40, 62), 70, 18 if kind == "rain" else 11)
    elif kind == "snow":
        _cloud(p, 12, 60, 76)
        _flakes(p, (34, 52, 70), 76, 7)
    elif kind == "storm":
        _cloud(p, 12, 60, 76, dark=True)
        _bolt(p, 42, 58, 34)
        _drops(p, (30, 76), 70, 12)


@lru_cache(maxsize=128)
def pixmap(kind, size):
    """Значок погоды размером size×size (логические пиксели)."""
    pix = QPixmap(int(size * DPR), int(size * DPR))
    pix.setDevicePixelRatio(DPR)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 100, size / 100)
    _draw_weather(p, kind)
    p.end()
    return pix


# ---------- значки виджетов (плитки для каталога) ----------

TILES = {
    "meteoclock": ("#3B4152", "#1E2230"), "clock": ("#5B8CFF", "#2F5BEA"), "analog": ("#F2F4F8", "#C9D0DC"),
    "system": ("#36C08E", "#159A6B"), "notes": ("#FFD25E", "#F5A623"), "weather": ("#5AB8FF", "#2C7BEA"),
    "calendar": ("#FFFFFF", "#E7EAF0"), "network": ("#8A6CFF", "#5B3FE0"), "photo": ("#FF8A7A", "#E5486B"),
    "timer": ("#FF8F5A", "#F2542D"), "todo": ("#4CD3A5", "#1FA37A"), "worldclock": ("#3EC7E0", "#1F86C9"),
    "sun": ("#FFB547", "#FF7A2F"), "currency": ("#5ED39B", "#22A06B"), "player": ("#2A2D36", "#121318"),
    "countdown": ("#FF8A5C", "#E5486B"), "water": ("#36D1FF", "#2F6BFF"),
    "gpu": ("#8BD12F", "#4F8A10"), "ping": ("#5AB8FF", "#2C7BEA"), "focus": ("#FF8A7A", "#E5486B"),
    "moon": ("#3B4152", "#1E2230"), "quick": ("#FFC93C", "#F5A623"), "lyrics": ("#2A2D36", "#121318"),
    "progress": ("#FFC93C", "#F2842D"), "stopwatch": ("#FF6B6B", "#D92D4A"), "calc": ("#4B5263", "#262A36"),
    "processes": ("#60A5FA", "#2F5BEA"), "clipboard": ("#A78BFA", "#6D4AE8"), "habits": ("#4ADE80", "#159A6B"),
    "air": ("#7DD3FC", "#2AA3C9"), "volume": ("#7C5CFF", "#4338CA"), "dice": ("#F87171", "#C92A3E"),
    "breathe": ("#2DD4BF", "#0E8F83"),
}


def _tile_glyph(p, name):
    white = QColor("white")
    if name in ("clock", "meteoclock", "analog"):
        ink = QColor("#20232c") if name == "analog" else white
        p.setPen(QPen(ink, 5))
        p.setBrush(Qt.NoBrush)
        if name != "meteoclock":
            p.drawEllipse(QPointF(50, 50), 28, 28)
        else:
            p.setPen(QPen(QColor(255, 255, 255, 150), 3, Qt.SolidLine, Qt.RoundCap))
            for i in range(12):
                a = i * math.pi / 6
                p.drawLine(QPointF(50 + math.sin(a) * 26, 50 - math.cos(a) * 26),
                           QPointF(50 + math.sin(a) * 32, 50 - math.cos(a) * 32))
        p.setPen(QPen(ink, 6, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(50, 50), QPointF(50, 32))
        p.drawLine(QPointF(50, 50), QPointF(63, 57))
        p.setPen(QPen(QColor("#2f6bff"), 3, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(50, 58), QPointF(42, 26))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#2f6bff"))
        p.drawEllipse(QPointF(50, 50), 4.5, 4.5)
    elif name == "system":
        p.setPen(Qt.NoPen)
        p.setBrush(white)
        for i, h in enumerate((22, 38, 30, 48)):
            p.drawRoundedRect(QRectF(24 + i * 14, 74 - h, 9, h), 4, 4)
    elif name == "notes":
        p.setPen(Qt.NoPen)
        p.setBrush(white)
        p.drawRoundedRect(QRectF(27, 22, 46, 56), 8, 8)
        p.setPen(QPen(QColor("#F5A623"), 4.5, Qt.SolidLine, Qt.RoundCap))
        for i, w in enumerate((30, 30, 20)):
            p.drawLine(QPointF(35, 38 + i * 11), QPointF(35 + w, 38 + i * 11))
    elif name == "weather":
        _sun(p, 40, 40, 13)
        _cloud(p, 24, 78, 60)
    elif name == "calendar":
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#FF4D4F"))
        top = QPainterPath()
        top.addRoundedRect(QRectF(0, 0, 100, 34), 0, 0)
        p.drawPath(top)
        p.setPen(QColor("#20232c"))
        f = p.font()
        f.setPixelSize(42)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(0, 36, 100, 56), Qt.AlignCenter, "2")
    elif name == "network":
        p.setPen(QPen(white, 7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawLine(QPointF(38, 72), QPointF(38, 28))
        p.drawPolyline([QPointF(26, 40), QPointF(38, 28), QPointF(50, 40)])
        p.drawLine(QPointF(62, 28), QPointF(62, 72))
        p.drawPolyline([QPointF(50, 60), QPointF(62, 72), QPointF(74, 60)])
    elif name == "timer":
        p.setPen(QPen(QColor(255, 255, 255, 90), 7))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(50, 54), 26, 26)
        p.setPen(QPen(white, 7, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(QRectF(24, 28, 52, 52), 90 * 16, -250 * 16)
        p.drawLine(QPointF(44, 16), QPointF(56, 16))
        p.setPen(QPen(white, 5, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(50, 54), QPointF(50, 40))
    elif name == "todo":
        p.setPen(QPen(white, 6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        for i in range(3):
            y = 30 + i * 20
            p.drawPolyline([QPointF(22, y), QPointF(27, y + 5), QPointF(35, y - 4)])
            p.drawLine(QPointF(44, y), QPointF(76, y))
    elif name == "worldclock":
        p.setPen(QPen(white, 5))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(50, 50), 27, 27)
        p.drawEllipse(QRectF(38, 23, 24, 54))
        p.drawLine(QPointF(23, 50), QPointF(77, 50))
        p.drawArc(QRectF(27, 20, 46, 22), 200 * 16, 140 * 16)
        p.drawArc(QRectF(27, 58, 46, 22), 20 * 16, 140 * 16)
    elif name == "sun":
        p.setPen(QPen(white, 5, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(16, 70), QPointF(84, 70))
        p.setPen(Qt.NoPen)
        p.setBrush(white)
        p.drawPie(QRectF(32, 50, 36, 36), 0, 180 * 16)
        p.setPen(QPen(white, 5, Qt.SolidLine, Qt.RoundCap))
        for a in (30, 60, 90, 120, 150):
            rad = math.radians(a)
            p.drawLine(QPointF(50 + math.cos(rad) * 25, 66 - math.sin(rad) * 25),
                       QPointF(50 + math.cos(rad) * 34, 66 - math.sin(rad) * 34))
    elif name == "countdown":  # песочные часы
        p.setPen(QPen(white, 6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawLine(QPointF(30, 22), QPointF(70, 22))
        p.drawLine(QPointF(30, 78), QPointF(70, 78))
        p.setBrush(Qt.NoBrush)
        p.drawPolyline([QPointF(35, 22), QPointF(35, 32), QPointF(50, 50), QPointF(35, 68), QPointF(35, 78)])
        p.drawPolyline([QPointF(65, 22), QPointF(65, 32), QPointF(50, 50), QPointF(65, 68), QPointF(65, 78)])
        p.setPen(Qt.NoPen)
        p.setBrush(white)
        p.drawPolygon([QPointF(40, 72), QPointF(60, 72), QPointF(50, 60)])
    elif name == "gpu":  # чип с ножками
        p.setPen(QPen(white, 5, Qt.SolidLine, Qt.RoundCap))
        for i in range(3):
            o = 34 + i * 16
            for a, b in (((o, 18), (o, 28)), ((o, 72), (o, 82)), ((18, o), (28, o)), ((72, o), (82, o))):
                p.drawLine(QPointF(*a), QPointF(*b))
        p.setPen(Qt.NoPen)
        p.setBrush(white)
        p.drawRoundedRect(QRectF(28, 28, 44, 44), 8, 8)
        p.setBrush(QColor("#4F8A10"))
        p.drawRoundedRect(QRectF(40, 40, 20, 20), 4, 4)
    elif name == "ping":  # столбики сигнала
        p.setPen(Qt.NoPen)
        p.setBrush(white)
        for i, hgt in enumerate((18, 32, 46, 60)):
            p.drawRoundedRect(QRectF(22 + i * 15, 78 - hgt, 10, hgt), 3, 3)
    elif name == "focus":  # помидор с листиком
        p.setPen(Qt.NoPen)
        p.setBrush(white)
        p.drawEllipse(QPointF(50, 56), 28, 25)
        p.setBrush(QColor("#22a06b"))
        for a in (-40, 0, 40):
            rad = math.radians(a - 90)
            p.drawPolygon([QPointF(45, 33), QPointF(55, 33), QPointF(50 + math.cos(rad) * 16, 33 + math.sin(rad) * 16)])
    elif name == "moon":  # полумесяц
        moon = QPainterPath()
        moon.addEllipse(QPointF(50, 50), 28, 28)
        cut = QPainterPath()
        cut.addEllipse(QPointF(64, 40), 24, 24)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#f2eee2"))
        p.drawPath(moon.subtracted(cut))
    elif name == "quick":  # молния
        p.setPen(Qt.NoPen)
        p.setBrush(white)
        p.drawPolygon([QPointF(56, 16), QPointF(28, 56), QPointF(48, 56), QPointF(42, 84), QPointF(72, 42),
                       QPointF(52, 42)])
    elif name == "water":  # капля
        path = QPainterPath()
        path.moveTo(50, 18)
        path.cubicTo(72, 42, 74, 56, 70, 66)
        path.cubicTo(64, 82, 36, 82, 30, 66)
        path.cubicTo(26, 56, 28, 42, 50, 18)
        p.setPen(Qt.NoPen)
        p.setBrush(white)
        p.drawPath(path)
    elif name == "lyrics":  # строки текста, средняя — зелёная (поётся сейчас)
        p.setPen(Qt.NoPen)
        for y, w, col in ((30, 46, QColor(255, 255, 255, 90)), (46, 60, QColor("#1ED760")),
                          (62, 40, QColor(255, 255, 255, 90))):
            p.setBrush(col)
            p.drawRoundedRect(QRectF(20, y, w, 9), 4.5, 4.5)
        p.setBrush(QColor("#1ED760"))
        p.drawEllipse(QPointF(76, 72), 7, 7)
        p.setPen(QPen(QColor("#1ED760"), 3, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(82, 72), QPointF(82, 50))
    elif name == "player":  # зелёная пластинка с нотой
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#1ED760"))
        p.drawEllipse(QPointF(50, 50), 30, 30)
        p.setBrush(QColor("#121318"))
        p.drawEllipse(QPointF(50, 50), 7, 7)
        p.setPen(QPen(QColor(0, 0, 0, 70), 2.5))
        p.setBrush(Qt.NoBrush)
        for rad in (14, 21):
            p.drawEllipse(QPointF(50, 50), rad, rad)
    elif name == "currency":
        p.setPen(QColor("white"))
        f = p.font()
        f.setPixelSize(54)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(0, 0, 100, 100), Qt.AlignCenter, "$")
    elif name == "photo":
        p.setPen(Qt.NoPen)
        p.setBrush(white)
        p.drawRoundedRect(QRectF(20, 26, 60, 48), 8, 8)
        p.setBrush(QColor("#E5486B"))
        path = QPainterPath()
        path.moveTo(26, 68)
        path.lineTo(44, 46)
        path.lineTo(56, 60)
        path.lineTo(63, 52)
        path.lineTo(74, 68)
        path.closeSubpath()
        p.drawPath(path)
        p.setBrush(QColor("#FFC93C"))
        p.drawEllipse(QPointF(64, 38), 6, 6)
    elif name == "progress":  # три полоски разной длины
        for i, w in enumerate((46, 30, 54)):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 70))
            p.drawRoundedRect(QRectF(22, 30 + i * 16, 56, 9), 4.5, 4.5)
            p.setBrush(white)
            p.drawRoundedRect(QRectF(22, 30 + i * 16, w, 9), 4.5, 4.5)
    elif name == "stopwatch":  # циферблат с кнопкой сверху
        p.setPen(QPen(white, 6))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(50, 56), 25, 25)
        p.setPen(QPen(white, 6, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(50, 56), QPointF(50, 41))
        p.drawLine(QPointF(42, 21), QPointF(58, 21))
        p.drawLine(QPointF(50, 21), QPointF(50, 30))
    elif name == "calc":  # экран и кнопки
        p.setPen(Qt.NoPen)
        p.setBrush(white)
        p.drawRoundedRect(QRectF(24, 20, 52, 16), 4, 4)
        for row in range(3):
            for col in range(3):
                p.setBrush(QColor("#ff9f0a") if col == 2 else white)
                p.drawRoundedRect(QRectF(24 + col * 19, 42 + row * 13, 14, 9), 3, 3)
    elif name == "processes":  # строки разной длины с точками
        for i, w in enumerate((48, 36, 26)):
            p.setPen(Qt.NoPen)
            p.setBrush(white)
            p.drawEllipse(QPointF(26, 34 + i * 16), 4.5, 4.5)
            p.drawRoundedRect(QRectF(36, 30 + i * 16, w, 8), 4, 4)
    elif name == "clipboard":  # планшет с зажимом
        p.setPen(Qt.NoPen)
        p.setBrush(white)
        p.drawRoundedRect(QRectF(27, 24, 46, 56), 8, 8)
        p.setBrush(QColor("#6D4AE8"))
        p.drawRoundedRect(QRectF(39, 18, 22, 13), 4, 4)
        p.setPen(QPen(QColor("#6D4AE8"), 4, Qt.SolidLine, Qt.RoundCap))
        for i, w in enumerate((28, 28, 18)):
            p.drawLine(QPointF(36, 44 + i * 11), QPointF(36 + w, 44 + i * 11))
    elif name == "habits":  # большая галочка в кружке
        p.setPen(QPen(white, 6))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(50, 50), 28, 28)
        p.setPen(QPen(white, 7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPolyline([QPointF(38, 51), QPointF(47, 60), QPointF(63, 41)])
    elif name == "air":  # три потока ветра
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(white, 6.5, Qt.SolidLine, Qt.RoundCap))
        for y, x2, arc in ((36, 62, False), (50, 72, True), (64, 54, False)):
            p.drawLine(QPointF(22, y), QPointF(x2, y))
        p.drawArc(QRectF(56, 24, 12, 12), -90 * 16, 180 * 16)
        p.drawArc(QRectF(66, 38, 12, 12), -90 * 16, 180 * 16)
        p.drawArc(QRectF(48, 64, 12, 12), -90 * 16, -180 * 16 + 360 * 16)
    elif name == "volume":  # динамик и волны
        body = QPainterPath(QPointF(24, 42))
        for x, y in ((35, 42), (50, 28), (50, 72), (35, 58), (24, 58)):
            body.lineTo(x, y)
        body.closeSubpath()
        p.setPen(QPen(white, 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(white)
        p.drawPath(body)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(white, 5.5, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(QRectF(44, 38, 24, 24), -50 * 16, 100 * 16)
        p.drawArc(QRectF(40, 28, 44, 44), -48 * 16, 96 * 16)
    elif name == "dice":  # кубик с тремя точками
        p.setPen(Qt.NoPen)
        p.setBrush(white)
        p.drawRoundedRect(QRectF(24, 24, 52, 52), 12, 12)
        p.setBrush(QColor("#C92A3E"))
        for x, y in ((37, 37), (50, 50), (63, 63)):
            p.drawEllipse(QPointF(x, y), 5.5, 5.5)
    elif name == "breathe":  # расходящиеся круги
        p.setBrush(Qt.NoBrush)
        for radius, alpha in ((30, 90), (21, 170)):
            p.setPen(QPen(QColor(255, 255, 255, alpha), 5))
            p.drawEllipse(QPointF(50, 50), radius, radius)
        p.setPen(Qt.NoPen)
        p.setBrush(white)
        p.drawEllipse(QPointF(50, 50), 11, 11)


@lru_cache(maxsize=32)
def app_icon(name, size):
    """Значок виджета: скруглённая «плитка» с градиентом и белым рисунком."""
    pix = QPixmap(int(size * DPR), int(size * DPR))
    pix.setDevicePixelRatio(DPR)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
    p.scale(size / 100, size / 100)
    top, bot = TILES.get(name, ("#9aa3b5", "#6b7489"))
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(0, 0, 100, 100), 26, 26)
    p.setClipPath(clip)
    g = QLinearGradient(0, 0, 0, 100)
    g.setColorAt(0, QColor(top))
    g.setColorAt(1, QColor(bot))
    p.fillRect(QRectF(0, 0, 100, 100), g)
    hi = QLinearGradient(0, 0, 0, 50)  # лёгкий блик сверху
    hi.setColorAt(0, QColor(255, 255, 255, 60))
    hi.setColorAt(1, QColor(255, 255, 255, 0))
    p.fillRect(QRectF(0, 0, 100, 50), hi)
    _tile_glyph(p, name)
    p.end()
    return pix
