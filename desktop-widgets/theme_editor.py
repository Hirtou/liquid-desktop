"""Редактор своей темы («Кастомная») во вкладке «Темы»: режим со свечением и без, раскладка свечения
(горизонтально / вертикально / крест), цвета заливки, рамки и акцента — градиентом из точек 0..100,
линейным или радиальным, с углом. Цвет выбирается квадратом или кругом, HEX, RGBA и пипеткой с экрана.

Всё, что меняется, через короткую паузу уходит в core.set_custom: виджеты и остров перекрашиваются сразу."""
import copy
import math

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QConicalGradient, QCursor, QGuiApplication, QImage, QIntValidator,
                           QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient,
                           QRegularExpressionValidator)
from PySide6.QtCore import QRegularExpression
from PySide6.QtWidgets import (QAbstractButton, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout,
                               QWidget)

import skins
from lang import tr


def _dark(w):
    return bool(getattr(w.window(), "dark", True))


def _checker(p, rect, radius):
    """Шахматка под прозрачным цветом."""
    p.save()
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    p.setClipPath(path)
    p.fillRect(rect, QColor(255, 255, 255))
    s = 6
    y = int(rect.top())
    row = 0
    while y < rect.bottom():
        x = int(rect.left()) + (s if row % 2 else 0)
        while x < rect.right():
            p.fillRect(QRectF(x, y, s, s), QColor(214, 214, 220))
            x += 2 * s
        y += s
        row += 1
    p.restore()


def _outline(dark):
    return QColor(255, 255, 255, 70) if dark else QColor(0, 0, 0, 50)


class ColorPicker(QWidget):
    """Выбор цвета: квадрат (насыщенность × яркость + полоса оттенка) или круг (оттенок по кругу,
    насыщенность от центра + полоса яркости). Внизу — прозрачность. changed(QColor)."""

    changed = Signal(QColor)
    S = 200

    def __init__(self):
        super().__init__(cursor=Qt.PointingHandCursor)
        self.shape = "square"
        self.h, self.s, self.v, self.a = 0.0, 1.0, 1.0, 1.0
        self.drag = None
        self.setFixedSize(self.S, self.S + 70)
        self._wheel = None

    def set_shape(self, shape):
        self.shape = shape
        self.update()

    def set_color(self, c):
        h, s, v, a = c.getHsvF()
        if h >= 0 and s > 0.001:  # у серого оттенка нет — оставляем прежний, бегунок не прыгает
            self.h = h
        self.s, self.v, self.a = s, v, a
        self.update()

    def color(self):
        return QColor.fromHsvF(self.h, self.s, self.v, self.a)

    def _area(self):
        return QRectF(1, 1, self.S - 2, self.S - 2)

    def _bar1(self):
        return QRectF(1, self.S + 14, self.S - 2, 18)

    def _bar2(self):
        return QRectF(1, self.S + 46, self.S - 2, 18)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        dark = _dark(self)
        area = self._area()
        hue = QColor.fromHsvF(self.h, 1, 1)
        if self.shape == "square":
            path = QPainterPath()
            path.addRoundedRect(area, 12, 12)
            p.fillPath(path, hue)
            g = QLinearGradient(area.topLeft(), area.topRight())
            g.setColorAt(0, QColor(255, 255, 255))
            g.setColorAt(1, QColor(255, 255, 255, 0))
            p.fillPath(path, g)
            g = QLinearGradient(area.topLeft(), area.bottomLeft())
            g.setColorAt(0, QColor(0, 0, 0, 0))
            g.setColorAt(1, QColor(0, 0, 0))
            p.fillPath(path, g)
            p.setPen(QPen(_outline(dark), 1))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
            knob = QPointF(area.left() + self.s * area.width(), area.top() + (1 - self.v) * area.height())
            # полоса оттенка
            bar = self._bar1()
            g = QLinearGradient(bar.topLeft(), bar.topRight())
            for i in range(7):
                g.setColorAt(i / 6, QColor.fromHsvF((i / 6) % 1.0, 1, 1))
            p.setPen(QPen(_outline(dark), 1))
            p.setBrush(g)
            p.drawRoundedRect(bar, 9, 9)
            bx = bar.left() + self.h * bar.width()
        else:
            c = area.center()
            R = area.width() / 2
            img = self._wheel_image(int(area.width()))
            p.drawImage(QRectF(area.left(), area.top(), area.width(), area.height()), img)
            if self.v < 1:  # яркость — затемнение всего круга
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(0, 0, 0, int((1 - self.v) * 255)))
                p.drawEllipse(c, R, R)
            p.setPen(QPen(_outline(dark), 1))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(c, R, R)
            ang = self.h * 2 * math.pi
            knob = QPointF(c.x() + math.cos(ang) * self.s * R, c.y() - math.sin(ang) * self.s * R)
            bar = self._bar1()
            g = QLinearGradient(bar.topLeft(), bar.topRight())
            g.setColorAt(0, QColor(0, 0, 0))
            g.setColorAt(1, QColor.fromHsvF(self.h, self.s, 1))
            p.setPen(QPen(_outline(dark), 1))
            p.setBrush(g)
            p.drawRoundedRect(bar, 9, 9)
            bx = bar.left() + self.v * bar.width()
        self._knob(p, knob, QColor.fromHsvF(self.h, self.s, self.v), 9)
        self._knob(p, QPointF(min(max(bx, bar.left() + 9), bar.right() - 9), bar.center().y()),
                   hue if self.shape == "square" else QColor.fromHsvF(self.h, self.s, self.v), 9)
        # прозрачность
        bar = self._bar2()
        _checker(p, bar, 9)
        g = QLinearGradient(bar.topLeft(), bar.topRight())
        solid = QColor.fromHsvF(self.h, self.s, self.v)
        clear = QColor(solid)
        clear.setAlpha(0)
        g.setColorAt(0, clear)
        g.setColorAt(1, solid)
        p.setPen(QPen(_outline(dark), 1))
        p.setBrush(g)
        p.drawRoundedRect(bar, 9, 9)
        ax = bar.left() + self.a * bar.width()
        self._knob(p, QPointF(min(max(ax, bar.left() + 9), bar.right() - 9), bar.center().y()), self.color(), 9)
        p.end()

    def _wheel_image(self, size):
        key = (size, self.devicePixelRatioF())
        if self._wheel is not None and self._wheel[0] == key:
            return self._wheel[1]
        dpr = self.devicePixelRatioF()
        n = int(size * dpr)
        img = QImage(n, n, QImage.Format_ARGB32_Premultiplied)
        img.fill(0)
        q = QPainter(img)
        q.setRenderHint(QPainter.Antialiasing)
        c = QPointF(n / 2, n / 2)
        g = QConicalGradient(c, 0)
        for i in range(13):
            g.setColorAt(i / 12, QColor.fromHsvF((i / 12) % 1.0, 1, 1))
        q.setPen(Qt.NoPen)
        q.setBrush(g)
        q.drawEllipse(c, n / 2, n / 2)
        rg = QRadialGradient(c, n / 2)
        rg.setColorAt(0, QColor(255, 255, 255))
        rg.setColorAt(1, QColor(255, 255, 255, 0))
        q.setBrush(rg)
        q.drawEllipse(c, n / 2, n / 2)
        q.end()
        self._wheel = (key, img)
        return img

    @staticmethod
    def _knob(p, at, color, r):
        p.setPen(QPen(QColor(0, 0, 0, 90), 3))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(at, r, r)
        p.setPen(QPen(QColor(255, 255, 255), 2.5))
        c = QColor(color)
        c.setAlpha(255)
        p.setBrush(c)
        p.drawEllipse(at, r - 1, r - 1)

    def mousePressEvent(self, event):
        pos = event.position()
        if self._area().contains(pos):
            self.drag = "area"
        elif self._bar1().adjusted(0, -6, 0, 6).contains(pos):
            self.drag = "bar1"
        elif self._bar2().adjusted(0, -6, 0, 6).contains(pos):
            self.drag = "bar2"
        else:
            self.drag = None
        self.mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.drag = None

    def mouseMoveEvent(self, event):
        if not self.drag:
            return
        pos = event.position()
        clamp = lambda v: max(0.0, min(1.0, v))  # noqa: E731
        if self.drag == "area":
            area = self._area()
            if self.shape == "square":
                self.s = clamp((pos.x() - area.left()) / area.width())
                self.v = clamp(1 - (pos.y() - area.top()) / area.height())
            else:
                c = area.center()
                dx, dy = pos.x() - c.x(), c.y() - pos.y()
                self.s = clamp(math.hypot(dx, dy) / (area.width() / 2))
                self.h = (math.atan2(dy, dx) / (2 * math.pi)) % 1.0
        elif self.drag == "bar1":
            bar = self._bar1()
            t = clamp((pos.x() - bar.left()) / bar.width())
            if self.shape == "square":
                self.h = min(t, 0.9999)
            else:
                self.v = t
        else:
            bar = self._bar2()
            self.a = clamp((pos.x() - bar.left()) / bar.width())
        self.update()
        self.changed.emit(self.color())


class GradientBar(QWidget):
    """Полоса градиента с точками: тащишь точку — меняется её место (0..100), клик по пустому месту — новая
    точка. selected(номер), changed()."""

    changed = Signal()
    selected = Signal(int)
    PAD = 10

    def __init__(self):
        super().__init__(cursor=Qt.PointingHandCursor)
        self.setFixedHeight(46)
        self.setMinimumWidth(240)
        self.stops = [["#ffffffff", 0], ["#000000ff", 100]]
        self.sel = 0
        self.drag = False

    def set_stops(self, stops, sel):
        self.stops, self.sel = stops, sel
        self.update()

    def _bar(self):
        return QRectF(self.PAD, 8, self.width() - 2 * self.PAD, 30)

    def _x(self, at):
        bar = self._bar()
        return bar.left() + at / 100 * bar.width()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = _dark(self)
        bar = self._bar()
        _checker(p, bar, 15)
        g = QLinearGradient(bar.topLeft(), bar.topRight())
        for c, at in self.stops:
            g.setColorAt(at / 100, skins.rgba(c))
        p.setPen(QPen(_outline(dark), 1))
        p.setBrush(g)
        p.drawRoundedRect(bar, 15, 15)
        for i, (c, at) in enumerate(self.stops):
            x = self._x(at)
            r = QRectF(x - 7, 3, 14, 40)
            if i == self.sel:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(255, 255, 255, 120) if dark else QColor(0, 0, 0, 50))
                p.drawRoundedRect(r.adjusted(-4, -3, 4, 3), 11, 11)
            p.setPen(QPen(QColor(30, 30, 36), 2.2))
            p.setBrush(QColor(255, 255, 255))
            p.drawRoundedRect(r, 7, 7)
            col = skins.rgba(c)
            col.setAlpha(255)
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(r.adjusted(3, 3, -3, -3), 4, 4)
        p.end()

    def mousePressEvent(self, event):
        x = event.position().x()
        near = min(range(len(self.stops)), key=lambda i: abs(self._x(self.stops[i][1]) - x))
        if abs(self._x(self.stops[near][1]) - x) > 12:  # мимо точек — ничего (новая точка — кнопкой «+»)
            return
        self.sel = near
        self.drag = True
        self.selected.emit(self.sel)
        self.update()

    def mouseMoveEvent(self, event):
        if not self.drag:
            return
        bar = self._bar()
        at = int(round(max(0.0, min(1.0, (event.position().x() - bar.left()) / bar.width())) * 100))
        if self.stops[self.sel][1] != at:
            self.stops[self.sel][1] = at
            self.update()
            self.changed.emit()

    def mouseReleaseEvent(self, event):
        if self.drag:
            self.drag = False
            self.changed.emit()  # отпустили — точки встанут по порядку

    MAX_STOPS = 6

    def add_stop(self):
        """Новая точка — посередине самого большого промежутка, цвет — какой там сейчас у градиента.
        Больше MAX_STOPS не даём: на сотню точек (спамили «+») виджеты пересчитывали тему без конца и «сходили с ума»."""
        if len(self.stops) >= self.MAX_STOPS:
            return
        st = sorted(self.stops, key=lambda s: s[1])
        edges = [0] + [s[1] for s in st] + [100]
        gaps = [(b - a, (a + b) // 2) for a, b in zip(edges, edges[1:])]
        at = max(gaps)[1]
        arr = skins.gradient_array(dict(kind="linear", angle=90, stops=self.stops), 101, 1)[at]
        c = QColor(*[int(round(v)) for v in arr])
        self.stops.append([skins.hex_rgba(c), at])
        self.sel = len(self.stops) - 1
        self.selected.emit(self.sel)
        self.changed.emit()
        self.update()


class AngleDial(QWidget):
    """Кружок угла градиента: тащишь — точка бегает по кругу. changed(угол 0..359, как в CSS)."""

    changed = Signal(int)

    def __init__(self):
        super().__init__(cursor=Qt.PointingHandCursor)
        self.setFixedSize(36, 36)
        self.angle = 90

    def set_angle(self, a):
        self.angle = a
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = _dark(self)
        c = QPointF(18, 18)
        p.setPen(QPen(QColor(skins.ACCENT), 2))
        p.setBrush(QColor(255, 255, 255, 20) if dark else QColor(255, 255, 255, 160))
        p.drawEllipse(c, 15, 15)
        a = math.radians(self.angle)
        dot = QPointF(c.x() + math.sin(a) * 10, c.y() - math.cos(a) * 10)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(skins.ACCENT))
        p.drawEllipse(dot, 3.5, 3.5)
        p.end()

    def mousePressEvent(self, event):
        self.mouseMoveEvent(event)

    def mouseMoveEvent(self, event):
        pos = event.position()
        a = int(round(math.degrees(math.atan2(pos.x() - 18, 18 - pos.y())))) % 360
        if a != self.angle:
            self.angle = a
            self.update()
            self.changed.emit(a)


class Swatch(QAbstractButton):
    """Кружок-образец цвета (точка градиента, цвет свечения). Выбранный — с обводкой акцентом."""

    def __init__(self, size=28):
        super().__init__(cursor=Qt.PointingHandCursor)
        self.setFixedSize(size, size)
        self.color = QColor(255, 255, 255)
        self.brush = None  # градиент вместо цвета (образец заливки / рамки)
        self.active = False

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        _checker(p, r, 7)
        p.setPen(QPen(_outline(_dark(self)), 1))
        p.setBrush(self.brush if self.brush is not None else self.color)
        p.drawRoundedRect(r, 7, 7)
        if self.active:
            p.setPen(QPen(QColor(skins.ACCENT), 2.2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 9, 9)
        p.end()


class Pipette(QWidget):
    """Пипетка: снимок экрана во весь монитор, клик — цвет пикселя под мышью, Esc — отмена."""

    picked = Signal(QColor)

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_DeleteOnClose)
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        self.shot = screen.grabWindow(0)
        self.img = self.shot.toImage()
        self.setGeometry(screen.geometry())
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)

    def _at(self, pos):
        k = self.img.width() / max(1, self.width())
        x = min(self.img.width() - 1, max(0, int(pos.x() * k)))
        y = min(self.img.height() - 1, max(0, int(pos.y() * k)))
        return self.img.pixelColor(x, y)

    def paintEvent(self, event):
        p = QPainter(self)
        p.drawPixmap(self.rect(), self.shot)
        pos = self.mapFromGlobal(QCursor.pos())
        c = self._at(pos)
        p.setRenderHint(QPainter.Antialiasing)
        lens = QRectF(pos.x() + 18, pos.y() + 18, 44, 44)
        p.setPen(QPen(QColor(255, 255, 255), 3))
        p.setBrush(c)
        p.drawEllipse(lens)
        p.end()

    def mouseMoveEvent(self, event):
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.picked.emit(self._at(event.position()))
        self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()


class PipetteButton(QAbstractButton):
    """Кнопка пипетки — значок рисуем сами."""

    def __init__(self):
        super().__init__(cursor=Qt.PointingHandCursor)
        self.setFixedSize(36, 36)
        self.setToolTip(tr("Пипетка: взять цвет с экрана"))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = _dark(self)
        p.setPen(QPen(QColor(skins.ACCENT), 1.4))
        p.setBrush(QColor(255, 255, 255, 30 if self.underMouse() else 12) if dark else QColor(255, 255, 255, 150))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 9, 9)
        p.translate(18, 18)
        p.rotate(45)
        pen = QPen(QColor("#f5f6fb" if dark else "#2a2c33"), 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(-3, -11, 6, 7), 2.5, 2.5)   # колпачок
        p.drawLine(QPointF(-5, -4), QPointF(5, -4))          # ободок
        p.drawRoundedRect(QRectF(-2, -4, 4, 11), 1.5, 1.5)   # трубочка
        p.drawLine(QPointF(0, 7), QPointF(0, 10))            # носик
        p.end()


def _field(width, text="", validator=None):
    e = QLineEdit(text)
    e.setFixedWidth(width)
    e.setAlignment(Qt.AlignCenter)
    if validator is not None:
        e.setValidator(validator)
    return e



def _caption(text):
    l_ = QLabel(text, objectName="dim")
    l_.setStyleSheet("font-size: 12px; font-weight: 600;")
    return l_


def _vline():
    w = QFrame()
    w.setFixedWidth(1)
    w.setStyleSheet("background: rgba(128,128,140,60);")
    return w


class Panel(QFrame):
    """Внутренняя панель редактора: чуть светлее карточки, скругление 18."""

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = _dark(self)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(255, 255, 255, 22) if dark else QColor(0, 0, 0, 18), 1))
        p.setBrush(QColor(255, 255, 255, 10) if dark else QColor(255, 255, 255, 120))
        p.drawRoundedRect(r, 18, 18)
        p.end()


class PlusButton(QAbstractButton):
    """Круглая кнопка «+» (своим рисунком, не символом шрифта)."""

    def __init__(self):
        super().__init__(cursor=Qt.PointingHandCursor)
        self.setFixedSize(30, 30)
        self.setAttribute(Qt.WA_Hover)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self.isEnabled():  # точек уже максимум
            p.setOpacity(0.35)
        c = QColor(skins.ACCENT)
        if not self.underMouse():
            c = c.darker(112)
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawEllipse(QRectF(1, 1, 28, 28))
        p.setPen(QPen(QColor(255, 255, 255) if c.lightness() < 170 else QColor(20, 20, 24), 2.2, Qt.SolidLine,
                      Qt.RoundCap))
        p.drawLine(QPointF(15, 9), QPointF(15, 21))
        p.drawLine(QPointF(9, 15), QPointF(21, 15))
        p.end()


def _spec_glow(spec):
    if not spec["glow"]:
        return None
    return spec["layout"], [skins.rgba(c) for c in spec["glow_colors"]]


def draw_mini(p, box, spec, glow_res=1.0, big=False):
    """Мини-виджет своей темы: свечение, заливка, рамка, кольцо акцента, время и кнопка."""
    from PySide6.QtGui import QFont
    r = 22 if big else 18
    path = QPainterPath()
    path.addRoundedRect(box, r, r)
    lay = _spec_glow(spec)
    if lay is not None:
        M = 18 if big else 8
        shape = QPainterPath()
        shape.addRoundedRect(QRectF(0, 0, box.width(), box.height()), r, r)
        img = skins.glow_image(shape, box.width(), box.height(), M, None, None, strength=0.8,
                               spread=7 if big else 3, res=glow_res, layout=lay)
        p.drawImage(QRectF(box.left() - M, box.top() - M, box.width() + 2 * M, box.height() + 2 * M), img)
    dark = skins.custom_dark(spec)
    p.fillPath(path, QColor(18, 19, 26, 200) if dark else QColor(40, 44, 54, 150))
    p.fillPath(path, skins.qt_gradient(spec["fill"], box, skins.FILL_MAX))
    sheen = QLinearGradient(box.topLeft(), box.bottomLeft())
    sheen.setColorAt(0, QColor(255, 255, 255, 22))
    sheen.setColorAt(0.4, QColor(255, 255, 255, 0))
    p.fillPath(path, sheen)
    p.setPen(QPen(skins.qt_gradient(spec["rim"], box), 1.8 if lay is not None else 1.2))
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)
    st = sorted(spec["accent"]["stops"], key=lambda s: s[1])
    acc, acc2 = skins.rgba(st[0][0]), skins.rgba(st[-1][0])
    k = box.height() / 102
    c = QPointF(box.left() + 50 * k, box.center().y())
    R = 30 * k
    p.setPen(QPen(QColor(255, 255, 255, 40), 7 * k, Qt.SolidLine, Qt.RoundCap))
    p.drawEllipse(c, R, R)
    ring = QConicalGradient(c, 90)
    ring.setColorAt(0, acc2)
    ring.setColorAt(1, acc)
    p.setPen(QPen(ring, 7 * k, Qt.SolidLine, Qt.RoundCap))
    p.drawArc(QRectF(c.x() - R, c.y() - R, 2 * R, 2 * R), 90 * 16, -250 * 16)
    f = QFont("Bahnschrift SemiBold")
    f.setPixelSize(int(30 * k))
    p.setFont(f)
    p.setPen(QColor(245, 246, 251))
    x0 = box.left() + 96 * k
    p.drawText(QRectF(x0, box.top() + 12 * k, 140 * k, 40 * k), Qt.AlignLeft | Qt.AlignVCenter, "07:30")
    pill = QRectF(x0 + 2 * k, box.top() + 58 * k, 92 * k, 26 * k)
    g = QLinearGradient(pill.topLeft(), pill.topRight())
    g.setColorAt(0, acc)
    g.setColorAt(1, acc2)
    p.setPen(Qt.NoPen)
    p.setBrush(g)
    p.drawRoundedRect(pill, pill.height() / 2, pill.height() / 2)
    f = QFont("Segoe UI Semibold")
    f.setPixelSize(int(12 * k))
    p.setFont(f)
    p.setPen(QColor(255, 255, 255) if acc.lightness() < 170 else QColor(20, 20, 24))
    p.drawText(pill, Qt.AlignCenter, tr("кнопка"))


class ThemePreview(QWidget):
    """Живое превью своей темы: меняется сразу, пока двигаешь цвет (виджеты на столе — после паузы)."""

    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.setFixedSize(330, 200)
        self._key = None

    def paintEvent(self, event):
        spec = self.editor.spec
        dpr = self.devicePixelRatioF()
        key = (repr(spec), dpr)
        if key != self._key:
            self._key = key
            pix = QPixmap(int(self.width() * dpr), int(self.height() * dpr))
            pix.setDevicePixelRatio(dpr)
            pix.fill(Qt.transparent)
            p = QPainter(pix)
            p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
            # подложка — тёмный «рабочий стол»: свечение видно и в светлом каталоге
            bg = QPainterPath()
            bg.addRoundedRect(QRectF(0, 0, self.width(), self.height()), 18, 18)
            g = QLinearGradient(0, 0, self.width(), self.height())
            g.setColorAt(0, QColor(30, 34, 52))
            g.setColorAt(1, QColor(12, 14, 22))
            p.fillPath(bg, g)
            glowc = QRadialGradient(QPointF(self.width() * 0.75, self.height() * 0.2), self.width() * 0.6)
            glowc.setColorAt(0, QColor(90, 110, 200, 40))
            glowc.setColorAt(1, QColor(90, 110, 200, 0))
            p.fillPath(bg, glowc)
            box = QRectF(32, 44, self.width() - 64, 112)
            draw_mini(p, box, spec, glow_res=2 * dpr, big=True)
            p.end()
            self._pix = pix
        p = QPainter(self)
        p.drawPixmap(0, 0, self._pix)
        p.end()


class TargetTile(QAbstractButton):
    """Плитка «что красим»: образец цвета сверху, название снизу; выбранная — в обводке акцентом."""

    def __init__(self, editor, key, name):
        super().__init__(cursor=Qt.PointingHandCursor)
        self.editor, self.key, self.name = editor, key, name
        self.active = False
        self.setFixedSize(92, 82)
        self.setAttribute(Qt.WA_Hover)

    def paintEvent(self, event):
        from PySide6.QtGui import QFont
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = _dark(self)
        spec = self.editor.spec
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(QColor(skins.ACCENT), 2) if self.active else QPen(_outline(dark), 1))
        p.setBrush(QColor(255, 255, 255, 26 if self.underMouse() else 14) if dark
                   else QColor(255, 255, 255, 190 if self.underMouse() else 140))
        p.drawRoundedRect(r, 16, 16)
        sw = QRectF(12, 12, self.width() - 24, 34)
        _checker(p, sw, 10)
        if self.key == "glow":
            cols = [skins.rgba(c) for c in spec["glow_colors"]]
            n = 4 if spec["layout"] == "cross" else 2
            if spec["layout"] == "vertical":
                g = QLinearGradient(sw.topLeft(), sw.bottomLeft())
            else:
                g = QLinearGradient(sw.topLeft(), sw.topRight())
            for i in range(n):
                g.setColorAt(i / (n - 1), cols[i])
            brush = g
        else:
            brush = skins.qt_gradient(spec[self.key], sw)
        p.setPen(QPen(_outline(dark), 1))
        p.setBrush(brush)
        p.drawRoundedRect(sw, 10, 10)
        p.setPen(QColor("#f5f6fb" if dark else "#2a2c33"))
        f = QFont("Segoe UI Semibold")
        f.setPixelSize(12)
        p.setFont(f)
        p.drawText(QRectF(0, 52, self.width(), 22), Qt.AlignCenter, self.name)
        p.end()


class CustomThemeEditor(QFrame):
    """Карточка «Кастомная тема» под сеткой тем."""

    TARGETS = ("fill", "rim", "accent", "glow")

    def __init__(self, Segmented, PillButton, apply):
        super().__init__(objectName="card")
        self.apply = apply  # core.set_custom
        self.spec = skins.custom_spec(None)
        self.target = "fill"
        self.sel = 0        # выбранная точка градиента
        self.glow_i = 0     # выбранный цвет свечения
        self.commit_timer = QTimer(self, singleShot=True, interval=350, timeout=self._commit)
        self._busy = False  # раскладываем значения по полям — их сигналы не считаются правкой

        box = QVBoxLayout(self)
        box.setContentsMargins(20, 16, 20, 20)
        box.setSpacing(14)
        head_row = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        head = QLabel(tr("Кастомная тема"))
        head.setStyleSheet("font-size: 16px; font-weight: 600;")
        titles.addWidget(head)
        sub = QLabel(tr("Свои цвета рамки, заливки и акцента — одним цветом или переходом. Свечение вокруг "
                        "виджетов можно выключить или раскрасить: слева и справа, сверху и снизу или крестом."),
                     objectName="dim", wordWrap=True)
        sub.setStyleSheet("font-size: 12px;")
        titles.addWidget(sub)
        head_row.addLayout(titles, 1)
        reset = PillButton(tr("Сбросить"))
        reset.setToolTip(tr("Вернуть серую тему по умолчанию"))
        reset.clicked.connect(self.reset)
        head_row.addWidget(reset, 0, Qt.AlignTop)
        box.addLayout(head_row)

        # верх: живое превью слева, режим, свечение и «что красим» справа
        top = QHBoxLayout()
        top.setSpacing(24)
        self.preview = ThemePreview(self)
        top.addWidget(self.preview, 0, Qt.AlignTop)
        side = QVBoxLayout()
        side.setSpacing(8)
        side.addWidget(_caption(tr("Режим")))
        self.mode = Segmented([("glow", tr("Со свечением")), ("flat", tr("Без свечения"))], "glow")
        self.mode.changed.connect(self._mode)
        side.addWidget(self.mode, 0, Qt.AlignLeft)
        side.addSpacing(4)
        self.layout_lbl = _caption(tr("Свечение"))
        side.addWidget(self.layout_lbl)
        self.layout_seg = Segmented([("horizontal", tr("Горизонтально")), ("vertical", tr("Вертикально")),
                                     ("cross", tr("Крест"))], "horizontal")
        self.layout_seg.changed.connect(self._layout)
        side.addWidget(self.layout_seg, 0, Qt.AlignLeft)
        side.addSpacing(4)
        side.addWidget(_caption(tr("Что красим")))
        tiles = QHBoxLayout()
        tiles.setSpacing(10)
        self.tiles = {}
        for key, name in (("fill", tr("Заливка")), ("rim", tr("Рамка")), ("accent", tr("Акцент")),
                          ("glow", tr("Свечение"))):
            t = TargetTile(self, key, name)
            t.clicked.connect(lambda _=False, k=key: self._target(k))
            tiles.addWidget(t)
            self.tiles[key] = t
        tiles.addStretch()
        side.addLayout(tiles)
        side.addStretch()
        top.addLayout(side, 1)
        box.addLayout(top)

        # панель цвета: всё про выбранный элемент
        panel = Panel()
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(18, 16, 18, 18)
        pl.setSpacing(14)

        # цвета свечения: 2 (слева/справа, сверху/снизу) или 4 (крест)
        self.glow_row = QWidget()
        gl = QHBoxLayout(self.glow_row)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setSpacing(14)
        self.glow_swatches, self.glow_labels = [], []
        for i in range(4):
            cell = QVBoxLayout()
            cell.setSpacing(4)
            sw = Swatch(44)
            sw.clicked.connect(lambda _=False, i=i: self._pick_glow(i))
            lbl = QLabel("", objectName="dim")
            lbl.setStyleSheet("font-size: 11px;")
            lbl.setAlignment(Qt.AlignCenter)
            cell.addWidget(sw, 0, Qt.AlignHCenter)
            cell.addWidget(lbl)
            gl.addLayout(cell)
            self.glow_swatches.append(sw)
            self.glow_labels.append(lbl)
        gl.addStretch()
        pl.addWidget(self.glow_row)

        # градиент: полоса с точками
        self.grad_row = QWidget()
        gr = QVBoxLayout(self.grad_row)
        gr.setContentsMargins(0, 0, 0, 0)
        gr.setSpacing(2)
        self.bar = GradientBar()
        self.bar.selected.connect(self._select_stop)
        self.bar.changed.connect(self._bar_changed)
        gr.addWidget(self.bar)
        ends = QHBoxLayout()
        ends.setContentsMargins(6, 0, 6, 0)
        lo, hi = QLabel("0", objectName="dim"), QLabel("100", objectName="dim")
        for l_ in (lo, hi):
            l_.setStyleSheet("font-size: 11px;")
        ends.addWidget(lo)
        ends.addStretch()
        hint = QLabel(tr("точки можно тащить, новая — кнопкой «+»"), objectName="dim")
        hint.setStyleSheet("font-size: 11px;")
        ends.addWidget(hint)
        ends.addStretch()
        ends.addWidget(hi)
        gr.addLayout(ends)
        pl.addWidget(self.grad_row)

        cols = QHBoxLayout()
        cols.setSpacing(26)
        # 1) выбор цвета
        left = QVBoxLayout()
        left.setSpacing(10)
        self.shape = Segmented([("square", tr("Квадрат")), ("circle", tr("Круг"))], "square")
        self.picker = ColorPicker()
        self.shape.changed.connect(self.picker.set_shape)
        self.picker.changed.connect(self._picked)
        left.addWidget(self.shape, 0, Qt.AlignLeft)
        left.addWidget(self.picker)
        left.addStretch()
        cols.addLayout(left)
        cols.addWidget(_vline())
        # 2) HEX, пипетка, RGBA и крупный образец
        mid = QVBoxLayout()
        mid.setSpacing(8)
        mid.addWidget(_caption("HEX"))
        hexrow = QHBoxLayout()
        hexrow.setSpacing(8)
        self.hex = _field(124, validator=QRegularExpressionValidator(QRegularExpression("#?[0-9a-fA-F]{0,8}")))
        self.hex.editingFinished.connect(self._hex_edited)
        hexrow.addWidget(self.hex)
        pip = PipetteButton()
        pip.clicked.connect(self._pipette)
        hexrow.addWidget(pip)
        hexrow.addStretch()
        mid.addLayout(hexrow)
        mid.addSpacing(4)
        rgba = QGridLayout()
        rgba.setHorizontalSpacing(6)
        rgba.setVerticalSpacing(4)
        self.chan = []
        for i, name in enumerate(("R", "G", "B", "A")):
            l_ = _caption(name)
            l_.setAlignment(Qt.AlignCenter)
            rgba.addWidget(l_, 0, i)
            e = _field(50, validator=QIntValidator(0, 255 if i < 3 else 100))
            e.editingFinished.connect(self._chan_edited)
            rgba.addWidget(e, 1, i)
            self.chan.append(e)
        mid.addLayout(rgba)
        mid.addSpacing(8)
        self.big_swatch = Swatch(28)
        self.big_swatch.setFixedSize(218, 56)
        self.big_swatch.setEnabled(False)
        mid.addWidget(self.big_swatch)
        mid.addStretch()
        mid_w = QWidget()
        mid_w.setLayout(mid)
        mid_w.setFixedWidth(230)
        cols.addWidget(mid_w)
        self.right_line = _vline()
        cols.addWidget(self.right_line)
        # 3) вид градиента, угол, точки
        self.right = QWidget()
        right = QVBoxLayout(self.right)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(8)
        right.addWidget(_caption(tr("Переход")))
        kind_row = QHBoxLayout()
        kind_row.setSpacing(8)
        self.kind = Segmented([("linear", tr("Линейный")), ("radial", tr("Радиальный"))], "linear")
        self.kind.changed.connect(self._kind)
        kind_row.addWidget(self.kind)
        self.dial = AngleDial()
        self.dial.changed.connect(self._angle)
        kind_row.addWidget(self.dial)
        self.angle = _field(50, validator=QIntValidator(0, 359))
        self.angle.editingFinished.connect(self._angle_edited)
        kind_row.addWidget(self.angle)
        kind_row.addStretch()
        right.addLayout(kind_row)
        right.addSpacing(6)
        pts = QHBoxLayout()
        pts.setSpacing(10)
        pts.addWidget(_caption(tr("Точки")))
        self.plus = plus = PlusButton()
        plus.setToolTip(tr("Добавить точку"))
        plus.clicked.connect(self.bar.add_stop)
        pts.addWidget(plus)
        pts.addStretch()
        right.addLayout(pts)
        self.rows_box = QVBoxLayout()
        self.rows_box.setSpacing(6)
        right.addLayout(self.rows_box)
        right.addStretch()
        cols.addWidget(self.right, 1)
        self.tail = QWidget()  # свечение: правого столбца нет — пустое место справа, а не растянутые поля
        cols.addWidget(self.tail, 1)
        pl.addLayout(cols)
        box.addWidget(panel)

    # ── данные ──────────────────────────────────────────────────────────────────────────────
    def load(self, spec):
        self.spec = skins.custom_spec(spec)
        self.sel = min(self.sel, len(self._grad()["stops"]) - 1) if self.target != "glow" else self.sel
        self._sync()

    def _grad(self):
        return self.spec[self.target] if self.target != "glow" else None

    def _color(self):
        if self.target == "glow":
            return skins.rgba(self.spec["glow_colors"][self.glow_i])
        return skins.rgba(self._grad()["stops"][self.sel][0])

    def _set_color(self, c):
        h = skins.hex_rgba(c)
        if self.target == "glow":
            self.spec["glow_colors"][self.glow_i] = h
        else:
            self._grad()["stops"][self.sel][0] = h
        self._changed()

    def _changed(self):
        self.commit_timer.start()
        self._sync(keep_picker=True)

    def _commit(self):
        self.apply(copy.deepcopy(self.spec))

    def reset(self):
        self.spec = skins.custom_spec(None)
        self.sel, self.glow_i = 0, 0
        self._commit()
        self._sync()

    # ── раскладка значений по полям ────────────────────────────────────────────────────────────
    def _sync(self, keep_picker=False):
        self._busy = True
        glow = self.spec["glow"]
        self.mode.set_quiet("glow" if glow else "flat")
        self.layout_seg.set_quiet(self.spec["layout"])
        self.layout_lbl.setVisible(glow)
        self.layout_seg.setVisible(glow)
        if not glow and self.target == "glow":
            self.target = "fill"
        for k, t in self.tiles.items():
            t.active = k == self.target
            t.setVisible(k != "glow" or glow)
            t.update()
        self.preview.update()
        is_glow = self.target == "glow"
        self.glow_row.setVisible(is_glow)
        self.grad_row.setVisible(not is_glow)
        self.right.setVisible(not is_glow)
        self.right_line.setVisible(not is_glow)
        n = 4 if self.spec["layout"] == "cross" else 2
        names = {"horizontal": (tr("Слева"), tr("Справа")), "vertical": (tr("Сверху"), tr("Снизу")),
                 "cross": (tr("Сверху"), tr("Справа"), tr("Снизу"), tr("Слева"))}[self.spec["layout"]]
        self.glow_i = min(self.glow_i, n - 1)
        for i, (sw, lbl) in enumerate(zip(self.glow_swatches, self.glow_labels)):
            sw.setVisible(i < n)
            lbl.setVisible(i < n)
            if i < n:
                sw.color = skins.rgba(self.spec["glow_colors"][i])
                sw.active = i == self.glow_i
                lbl.setText(names[i])
                sw.update()
        if not is_glow:
            g = self._grad()
            self.sel = min(self.sel, len(g["stops"]) - 1)
            if not self.bar.drag:  # точку перетащили за соседнюю — порядок по месту, выбранная остаётся выбранной
                cur = g["stops"][self.sel]
                g["stops"].sort(key=lambda s: s[1])
                self.sel = next(i for i, s in enumerate(g["stops"]) if s is cur)
            self.bar.set_stops(g["stops"], self.sel)
            self.kind.set_quiet(g["kind"])
            self.dial.set_angle(g["angle"])
            # у радиального перехода угла нет: крутилку прячем, а не выключаем — выключенная выглядела как
            # обычная и «переставала крутиться» (Диар)
            self.dial.setVisible(g["kind"] == "linear")
            self.angle.setVisible(g["kind"] == "linear")
            if not self.angle.hasFocus():
                self.angle.setText(str(g["angle"]))
            self._rows(g)
            self.plus.setEnabled(len(g["stops"]) < GradientBar.MAX_STOPS)
        c = self._color()
        if not keep_picker:
            self.picker.set_color(c)
        self.big_swatch.color = c
        self.big_swatch.update()
        if not self.hex.hasFocus():
            self.hex.setText(skins.hex_rgba(c).upper())
        for e, v in zip(self.chan, (c.red(), c.green(), c.blue(), round(c.alphaF() * 100))):
            if not e.hasFocus():
                e.setText(str(v))
        self._busy = False

    def _rows(self, g):
        """Список точек: образец, HEX, место, ×. Пересобирается, только когда меняется число точек."""
        rows = getattr(self, "_row_widgets", [])
        if len(rows) != len(g["stops"]):
            for w in rows:
                w.setParent(None)
                w.deleteLater()
            rows = []
            for i in range(len(g["stops"])):
                w = QFrame()
                lay = QHBoxLayout(w)
                lay.setContentsMargins(4, 2, 4, 2)
                lay.setSpacing(6)
                sw = Swatch(30)
                sw.clicked.connect(lambda _=False, i=i: self._select_stop(i))
                hx = _field(104, validator=QRegularExpressionValidator(QRegularExpression("#?[0-9a-fA-F]{0,8}")))
                hx.editingFinished.connect(lambda i=i: self._row_hex(i))
                at = _field(50, validator=QIntValidator(0, 100))
                at.editingFinished.connect(lambda i=i: self._row_at(i))
                rm = QLabel("✕")
                rm.setCursor(Qt.PointingHandCursor)
                rm.setToolTip(tr("Убрать точку"))
                rm.mousePressEvent = lambda e, i=i: self._remove(i)
                for x in (sw, hx, at, rm):
                    lay.addWidget(x)
                lay.addStretch()
                w.parts = (sw, hx, at, rm)
                self.rows_box.addWidget(w)
                rows.append(w)
            self._row_widgets = rows
        for i, (w, (c, at)) in enumerate(zip(rows, g["stops"])):
            sw, hx, ate, rm = w.parts
            sw.color = skins.rgba(c)
            sw.active = i == self.sel
            sw.update()
            if not hx.hasFocus():
                hx.setText(c.upper())
            if not ate.hasFocus():
                ate.setText(str(at))
            rm.setVisible(len(g["stops"]) > 2)

    # ── обработчики ──────────────────────────────────────────────────────────────────────────
    def _mode(self, m):
        self.spec["glow"] = m == "glow"
        self._changed()
        self._sync()

    def _layout(self, lay):
        self.spec["layout"] = lay
        self._changed()
        self._sync()

    def _target(self, t):
        self.target = t
        self.sel = 0
        self._sync()

    def _pick_glow(self, i):
        self.glow_i = i
        self._sync()

    def _select_stop(self, i):
        self.sel = i
        self._sync()

    def _bar_changed(self):
        self._changed()
        self.picker.set_color(self._color())

    def _picked(self, c):
        if not self._busy:
            self._set_color(c)

    def _hex_edited(self):
        if self._busy:
            return
        h = self.hex.text().lstrip("#")
        if len(h) in (6, 8):
            self._set_color(skins.rgba("#" + h + ("" if len(h) == 8 else "ff")))
            self.picker.set_color(self._color())

    def _chan_edited(self):
        if self._busy:
            return
        try:
            r, g, b, a = (int(e.text() or 0) for e in self.chan)
        except ValueError:
            return
        self._set_color(QColor(min(r, 255), min(g, 255), min(b, 255), int(min(a, 100) * 2.55 + 0.5)))
        self.picker.set_color(self._color())

    def _pipette(self):
        win = self.window()
        # каталог не должен попасть в снимок. Не hide(): спрятанный каталог отпускает все превью виджетов
        # и потом строит их заново — прозрачным он просто пропадает с экрана на время пипетки
        self._opacity = win.windowOpacity()
        win.setWindowOpacity(0.0)
        QTimer.singleShot(220, lambda: self._pipette_go(win))

    def _pipette_go(self, win):
        self._pip = Pipette()

        def done(c):
            c.setAlpha(self._color().alpha())
            self._set_color(c)
            self.picker.set_color(self._color())
        self._pip.picked.connect(done)
        self._pip.destroyed.connect(lambda: (win.setWindowOpacity(self._opacity), win.raise_(),
                                             win.activateWindow()))
        self._pip.showFullScreen()
        self._pip.activateWindow()

    def _kind(self, k):
        self._grad()["kind"] = k
        self._changed()
        self._sync()

    def _angle(self, a):
        self._grad()["angle"] = a
        self._changed()

    def _angle_edited(self):
        if self._busy:
            return
        try:
            self._grad()["angle"] = int(self.angle.text()) % 360
        except ValueError:
            return
        self._changed()

    def _row_hex(self, i):
        if self._busy:
            return
        w = self._row_widgets[i]
        h = w.parts[1].text().lstrip("#")
        if len(h) in (6, 8):
            self.sel = i
            self._set_color(skins.rgba("#" + h + ("" if len(h) == 8 else "ff")))
            self.picker.set_color(self._color())

    def _row_at(self, i):
        if self._busy:
            return
        try:
            v = max(0, min(100, int(self._row_widgets[i].parts[2].text())))
        except ValueError:
            return
        g = self._grad()
        g["stops"][i][1] = v
        c = g["stops"][i]
        g["stops"].sort(key=lambda s: s[1])
        self.sel = g["stops"].index(c)
        self._changed()
        self._sync()

    def _remove(self, i):
        g = self._grad()
        if len(g["stops"]) <= 2:
            return
        del g["stops"][i]
        self.sel = max(0, min(self.sel, len(g["stops"]) - 1))
        self._changed()
        self._sync()
