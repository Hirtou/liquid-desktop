"""Общее рисование новых виджетов — те же размеры и приёмы, что у старых («Вода», «Таймер», «Луна»):
цвета текста, шрифты, плашка-чип, кольцо в плитке слева, круглые стеклянные кнопки со значками, полоска."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QConicalGradient, QFont, QFontMetricsF, QPen

ACCENT = QColor("#2f6bff")
CYAN = QColor("#36c6ff")
GREEN, AMBER, RED, GRAY = QColor("#4ade80"), QColor("#ffb547"), QColor("#ff5a5f"), QColor("#9aa0aa")


def ring_tile(r):
    """Кольцо в квадратной плитке слева, как у «Воды» и «Видеокарты»: (центр, радиус, плитка)."""
    tile = QRectF(r.left() + 14, r.top() + 14, r.height() - 28, r.height() - 28)
    return tile.center(), tile.width() / 2 - 10, tile


def ring_label(p, c, R, big, small, fg, dim):
    """Подпись в кольце, как у «Воды»: крупно Bahnschrift и мелкая серая подпись под ним."""
    text(p, QRectF(c.x() - R, c.y() - R * 0.36, 2 * R, R * 0.55), big, fg, int(R * 0.5), "Bahnschrift SemiBold", Qt.AlignCenter)
    text(p, QRectF(c.x() - R, c.y() + R * 0.22, 2 * R, 16), small, dim, 11, align=Qt.AlignCenter)


def ink(widget):
    """(текст, второстепенный текст, дорожка полосок) под тему виджета."""
    fg = QColor("#ededf0") if widget.dark else QColor("#151517")
    dim, track = QColor(fg), QColor(fg)
    dim.setAlpha(140)
    track.setAlpha(30)
    return fg, dim, track


def font(size, family="Segoe UI"):
    f = QFont(family)
    f.setPixelSize(size)
    return f


def text(p, rect, value, color, size=12, family="Segoe UI", align=Qt.AlignLeft | Qt.AlignVCenter, elide=False):
    f = font(size, family)
    p.setFont(f)
    p.setPen(color)
    if elide:
        value = QFontMetricsF(f).elidedText(value, Qt.ElideRight, rect.width())
    p.drawText(rect, align, value)


def chip(p, r, label, color, dark):
    """Плашка состояния в правом верхнем углу карточки r. Возвращает её ширину (заголовку — оставшееся)."""
    f = font(11, "Segoe UI Semibold")
    w = QFontMetricsF(f).horizontalAdvance(label) + 24
    pill = QRectF(r.right() - 16 - w, r.top() + 15, w, 20)
    bg = QColor(color)
    bg.setAlpha(55 if dark else 70)
    p.setPen(Qt.NoPen)
    p.setBrush(bg)
    p.drawRoundedRect(pill, 10, 10)
    p.setBrush(color)
    p.drawEllipse(QRectF(pill.left() + 8, pill.center().y() - 3.5, 7, 7))
    p.setFont(f)
    p.setPen(QColor(color).lighter(130) if dark else QColor(color).darker(190))
    p.drawText(pill.adjusted(19, 0, -6, 0), Qt.AlignVCenter | Qt.AlignLeft, label)
    return w


def button(p, rect, label, fg, dark, color=None, size=12, tint=None):
    """Кнопка-таблетка с обводкой, как у «Таймера»: с цветом — главная; tint — стеклянная с цветной подписью."""
    p.setPen(QPen(QColor(255, 255, 255, 70 if dark else 170), 1))
    if color is not None:
        p.setBrush(color)
    elif tint is not None:
        bg = QColor(tint)
        bg.setAlpha(55 if dark else 70)  # как плашка-чип
        p.setBrush(bg)
    else:
        p.setBrush(QColor(255, 255, 255, 30 if dark else 140))
    p.drawRoundedRect(rect, min(rect.height(), rect.width()) / 2, min(rect.height(), rect.width()) / 2)
    ink = QColor("white") if color is not None else \
        (QColor(tint).lighter(130) if dark else QColor(tint).darker(170)) if tint is not None else fg
    text(p, rect, label, ink, size, "Segoe UI Semibold", Qt.AlignCenter)


def ring(p, center, radius, frac, color, track, width=12, color2=None):
    """Кольцо прогресса; color2 — второй цвет: дуга с переливом по кругу, как у «Воды» и «Таймера»."""
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(track, width, Qt.SolidLine, Qt.RoundCap))
    p.drawEllipse(center, radius, radius)
    if frac > 0:
        brush = color
        if color2 is not None:
            brush = QConicalGradient(center, 90)
            brush.setColorAt(0, color)
            brush.setColorAt(1, color2)
        p.setPen(QPen(brush, width, Qt.SolidLine, Qt.RoundCap))
        box = QRectF(center.x() - radius, center.y() - radius, 2 * radius, 2 * radius)
        p.drawArc(box, 90 * 16, int(-min(1.0, frac) * 360 * 16))


def round_button(p, rect, glyph, fg, dark, color=None):
    """Круглая стеклянная кнопка со значком, как у «Таймера»; с цветом — главная (белый значок)."""
    p.setPen(QPen(QColor(255, 255, 255, 70 if dark else 170), 1))
    p.setBrush(color if color is not None else QColor(255, 255, 255, 30 if dark else 140))
    p.drawEllipse(rect)
    draw_glyph(p, glyph, rect.center(), QColor("white") if color is not None else fg)


def draw_glyph(p, name, c, color):
    """Значки кнопок, нарисованные линиями (эмодзи не используем): play, pause, stop, reset, plus, flag, dice."""
    p.setPen(QPen(color, 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    x, y = c.x(), c.y()
    if name == "plus":
        p.drawLine(QPointF(x - 6, y), QPointF(x + 6, y))
        p.drawLine(QPointF(x, y - 6), QPointF(x, y + 6))
    elif name == "reset":  # круговая стрелка
        p.drawArc(QRectF(x - 6.5, y - 6.5, 13, 13), 60 * 16, 290 * 16)
        p.drawPolyline([QPointF(x + 1, y - 9), QPointF(x + 4.5, y - 5.8), QPointF(x + 0.5, y - 3)])
    elif name == "pause":
        p.setPen(QPen(color, 3, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(x - 3.5, y - 6), QPointF(x - 3.5, y + 6))
        p.drawLine(QPointF(x + 3.5, y - 6), QPointF(x + 3.5, y + 6))
    elif name == "stop":
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(QRectF(x - 5.5, y - 5.5, 11, 11), 2.5, 2.5)
    elif name == "flag":  # круг секундомера — флажок
        p.drawLine(QPointF(x - 4.5, y + 7), QPointF(x - 4.5, y - 7))
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawPolygon([QPointF(x - 4.5, y - 7), QPointF(x + 6, y - 4), QPointF(x - 4.5, y - 0.5)])
    elif name == "dice":  # бросить — кубик с точками
        p.drawRoundedRect(QRectF(x - 6.5, y - 6.5, 13, 13), 3, 3)
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        for dx, dy in ((-2.6, -2.6), (2.6, 2.6), (0, 0)):
            p.drawEllipse(QPointF(x + dx, y + dy), 1.3, 1.3)
    else:  # play
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawPolygon([QPointF(x - 4, y - 7), QPointF(x + 7, y), QPointF(x - 4, y + 7)])


def bar(p, rect, frac, color, track):
    p.setPen(Qt.NoPen)
    p.setBrush(track)
    p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
    if frac > 0:
        p.setBrush(color)
        w = max(rect.height(), rect.width() * min(1.0, frac))
        p.drawRoundedRect(QRectF(rect.left(), rect.top(), w, rect.height()), rect.height() / 2, rect.height() / 2)
