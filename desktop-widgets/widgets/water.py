"""Вода за день: кольцо прогресса, «+ стакан» / «−», график за неделю. Каждый день — с нуля."""
from lang import tr
from datetime import date, timedelta

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QConicalGradient, QFont, QFontMetricsF, QPainter, QPainterPath, QPen

from core import DesktopWidget, config, grid

BLUE, CYAN = QColor("#2f8bff"), QColor("#36d1ff")
GLASS_ML = 250
DAYS = [tr("пн"), tr("вт"), tr("ср"), tr("чт"), tr("пт"), tr("сб"), tr("вс")]


class WaterWidget(DesktopWidget):
    key = "water"
    title = tr("Вода")
    description = tr("Сколько выпил за день, график недели")
    SHAPES = {"full": (tr("Полный"), grid(2, 1)), "ring": (tr("Кольцо"), grid(1, 1))}

    def __init__(self, **kw):
        super().__init__(**kw)
        self.apply_shape()
        self.cfg.setdefault("goal", 8)
        self.cfg.setdefault("days", {})
        self.buttons = {}

    def today(self):
        return self.cfg["days"].get(date.today().isoformat(), 0)

    def add(self, n):
        key = date.today().isoformat()
        self.cfg["days"][key] = max(0, min(30, self.today() + n))
        # храним только последние 2 недели
        keep = {(date.today() - timedelta(days=i)).isoformat() for i in range(14)}
        self.cfg["days"] = {k: v for k, v in self.cfg["days"].items() if k in keep}
        config.save()
        self.update()

    def click(self, pos):
        for name, rect in self.buttons.items():
            if rect.contains(pos):
                self.add(1 if name == "plus" else -1)
                return True
        return False

    def wheelEvent(self, event):
        self.add(1 if event.angleDelta().y() > 0 else -1)

    def add_actions(self, menu):
        sub = menu.addMenu(tr("Норма в день"))
        for g in (6, 8, 10, 12):
            a = sub.addAction(tr("{} стаканов ({:g} л)").format(g, g * GLASS_ML / 1000), lambda g=g: self.set_goal(g))
            a.setCheckable(True)
            a.setChecked(self.cfg["goal"] == g)

    def set_goal(self, g):
        self.cfg["goal"] = g
        config.save()
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)  # стекло
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        r = QRectF(self.card())
        dark = bool(self.dark)
        fg = QColor("#ededf0") if dark else QColor("#151517")
        dim = QColor(fg)
        dim.setAlpha(140)
        n, goal = self.today(), self.cfg["goal"]
        frac = min(1.0, n / goal)

        # слева: кольцо с каплей и счётом
        tile = QRectF(r.left() + 14, r.top() + 14, r.height() - 28, r.height() - 28)
        c = tile.center()
        R = tile.width() / 2 - 10
        track = QColor(fg)
        track.setAlpha(30)
        p.setPen(QPen(track, 12, Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(c, R, R)
        if frac > 0:
            grad = QConicalGradient(c, 90)
            grad.setColorAt(0, CYAN)
            grad.setColorAt(1, BLUE)
            p.setPen(QPen(grad, 12, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(QRectF(c.x() - R, c.y() - R, 2 * R, 2 * R), 90 * 16, int(-frac * 360 * 16))
        self._drop(p, QPointF(c.x(), c.y() - R * 0.64), R * 0.19)
        big = QFont("Bahnschrift SemiBold")
        big.setPixelSize(int(R * 0.5))
        p.setFont(big)
        p.setPen(fg)
        p.drawText(QRectF(c.x() - R, c.y() - R * 0.12, 2 * R, R * 0.55), Qt.AlignCenter, f"{n}/{goal}")
        tiny = QFont("Segoe UI")
        tiny.setPixelSize(11)
        p.setFont(tiny)
        p.setPen(dim)
        p.drawText(QRectF(c.x() - R, c.y() + R * 0.42, 2 * R, 16), Qt.AlignCenter, tr("стаканов"))
        if self.shape() == "ring":  # только кольцо: клик по нему — «+ стакан», колесо — ±
            self.buttons = {"plus": tile}
            return

        # справа: чип, главное, кнопки, неделя
        x = tile.right() + 16
        w = r.right() - 16 - x
        done = n >= goal
        chip = tr("норма есть") if done else tr("пей воду")
        cf = QFont("Segoe UI Semibold")
        cf.setPixelSize(11)
        cw = QFontMetricsF(cf).horizontalAdvance(chip) + 24
        pill = QRectF(r.right() - 16 - cw, r.top() + 15, cw, 20)
        color = QColor("#4ade80") if done else BLUE
        bg = QColor(color)
        bg.setAlpha(55 if dark else 70)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(pill, 10, 10)
        p.setBrush(color)
        p.drawEllipse(QRectF(pill.left() + 8, pill.center().y() - 3.5, 7, 7))
        p.setFont(cf)
        p.setPen(color.lighter(130) if dark else color.darker(190))
        p.drawText(pill.adjusted(19, 0, -6, 0), Qt.AlignVCenter | Qt.AlignLeft, chip)
        title = QFont("Segoe UI Semibold")
        title.setPixelSize(16)
        p.setFont(title)
        p.setPen(fg)
        p.drawText(QRectF(x, r.top() + 14, w - cw, 22), Qt.AlignLeft | Qt.AlignVCenter, tr("Вода"))
        main = QFont("Segoe UI Semibold")
        main.setPixelSize(14)
        p.setFont(main)
        ml = n * GLASS_ML
        p.drawText(QRectF(x, r.top() + 40, w, 20), Qt.AlignLeft | Qt.AlignVCenter, tr("{:g} л из {:g} л").format(ml / 1000, goal * GLASS_ML / 1000))
        p.setFont(tiny)
        p.setPen(dim)
        rest = max(0, goal - n) * GLASS_ML
        p.drawText(QRectF(x, r.top() + 60, w, 16), Qt.AlignLeft | Qt.AlignVCenter,
                   tr("на сегодня всё") if done else tr("ещё {} мл · стакан {} мл").format(rest, GLASS_ML))

        # кнопки: «−» и «+ стакан»
        self.buttons = {}
        minus = QRectF(x, r.top() + 84, 34, 30)
        plus = QRectF(minus.right() + 8, minus.top(), 96, 30)
        self.buttons = {"minus": minus, "plus": plus}
        p.setPen(QPen(QColor(255, 255, 255, 60 if dark else 170), 1))
        p.setBrush(QColor(255, 255, 255, 30 if dark else 140))
        p.drawRoundedRect(minus, 15, 15)
        p.setPen(Qt.NoPen)
        p.setBrush(BLUE)
        p.drawRoundedRect(plus, 15, 15)
        p.setPen(QPen(fg, 2.2, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(minus.center().x() - 6, minus.center().y()), QPointF(minus.center().x() + 6, minus.center().y()))
        p.setFont(cf)
        p.setPen(QColor("white"))
        p.drawText(plus, Qt.AlignCenter, tr("+ стакан"))

        # неделя: столбики (сегодня — ярче)
        # под кнопками на всю ширину правой колонки (в ячейке 2×1 сбоку от кнопок места нет)
        bars = QRectF(x, minus.bottom() + 6, w, r.bottom() - 8 - minus.bottom() - 6)
        bw = bars.width() / 7
        for i in range(7):
            d = date.today() - timedelta(days=6 - i)
            v = self.cfg["days"].get(d.isoformat(), 0)
            h = max(3, (bars.height() - 14) * min(1, v / goal))
            col = QColor(BLUE if i == 6 else fg)
            col.setAlpha(255 if i == 6 else 70)
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(QRectF(bars.left() + i * bw + bw * 0.22, bars.bottom() - 14 - h, bw * 0.56, h), 2.5, 2.5)
            p.setPen(dim)
            tf = QFont("Segoe UI")
            tf.setPixelSize(9)
            p.setFont(tf)
            p.drawText(QRectF(bars.left() + i * bw, bars.bottom() - 12, bw, 12), Qt.AlignCenter, DAYS[d.weekday()])

    @staticmethod
    def _drop(p, top, s):
        """Капля воды: вершина в top, ширина ~2s."""
        path = QPainterPath()
        path.moveTo(top)
        path.cubicTo(QPointF(top.x() + s * 1.2, top.y() + s * 1.2), QPointF(top.x() + s, top.y() + s * 2.4),
                     QPointF(top.x(), top.y() + s * 2.4))
        path.cubicTo(QPointF(top.x() - s, top.y() + s * 2.4), QPointF(top.x() - s * 1.2, top.y() + s * 1.2), top)
        p.setPen(Qt.NoPen)
        p.setBrush(CYAN)
        p.drawPath(path)
