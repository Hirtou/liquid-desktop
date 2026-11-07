"""Элементы окна настроек — те же, что в каталоге виджетов (копия, чтобы остров жил сам по себе):
тумблер ColorOS, круглая кнопка окна, кнопка-капсула, переключатель вариантов. Тема — по self.window().dark."""
from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QCursor, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QWidget

ACCENT = QColor("#2f7bff")


def _mix(a, b, t):
    return QColor(*(int(x + (y - x) * t) for x, y in zip(a.getRgb(), b.getRgb())))


class Switch(QAbstractButton):
    """Тумблер в духе ColorOS: бегунок едет с лёгким перелётом и пружинит назад,
    в пути вытягивается каплей, цвет перетекает; при нажатии бегунок растягивается."""

    def __init__(self):
        super().__init__(checkable=True, cursor=Qt.PointingHandCursor)
        self.setFixedSize(52, 30)
        self.pos_ = 0.0     # 0 — выкл, 1 — вкл (может чуть перелететь)
        self.color_ = 0.0   # 0..1 — цвет дорожки
        self.press = 0.0    # 0..1 — бегунок нажат
        curve = QEasingCurve(QEasingCurve.OutBack)
        curve.setOvershoot(2.2)
        self.anim = QVariantAnimation(self, duration=420, easingCurve=curve)
        self.anim.valueChanged.connect(lambda v: self._set("pos_", v))
        self.fade = QVariantAnimation(self, duration=260, easingCurve=QEasingCurve.InOutSine)
        self.fade.valueChanged.connect(lambda v: self._set("color_", v))
        self.squash = QVariantAnimation(self, duration=140, easingCurve=QEasingCurve.OutCubic)
        self.squash.valueChanged.connect(lambda v: self._set("press", v))
        self.toggled.connect(self._animate)
        self.pressed.connect(lambda: self._run(self.squash, self.press, 1.0))
        self.released.connect(lambda: self._run(self.squash, self.press, 0.0))

    def _set(self, name, v):
        setattr(self, name, v)
        self.update()

    @staticmethod
    def _run(anim, start, end):
        anim.stop()
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.start()

    def _animate(self, on):
        self._run(self.anim, self.pos_, 1.0 if on else 0.0)
        self._run(self.fade, self.color_, 1.0 if on else 0.0)

    def set_quiet(self, on):
        """Переключить без анимации (при запуске)."""
        self.blockSignals(True)
        self.setChecked(on)
        self.blockSignals(False)
        self.pos_ = self.color_ = 1.0 if on else 0.0
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = bool(self.window().dark)
        off = QColor(255, 255, 255, 46) if dark else QColor(0, 0, 0, 40)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(Qt.NoPen)
        p.setBrush(_mix(off, ACCENT, self.color_))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        # капля: в середине пути и при нажатии бегунок шире
        t = self.pos_
        d = r.height() - 6
        stretch = max(0.0, 4 * t * (1 - t)) * 9 + self.press * 6
        w = d + stretch
        lo, hi = r.left() + 3, r.right() - 3 - w
        x = lo + (hi - lo) * t
        x = min(max(x, lo - 2), hi + 2)  # перелёт — чуть-чуть за край, как пружина
        knob = QRectF(x, r.top() + 3, w, d)
        p.setBrush(QColor(0, 0, 0, 45))  # тень бегунка
        p.drawRoundedRect(knob.translated(0, 1.2), d / 2, d / 2)
        p.setBrush(QColor("white"))
        p.drawRoundedRect(knob, d / 2, d / 2)


class TitleButton(QAbstractButton):
    """Круглая стеклянная кнопка окна: ✕ (закрыть) или – (свернуть)."""

    def __init__(self, kind="close"):
        super().__init__(cursor=Qt.PointingHandCursor)
        self.kind = kind
        self.setFixedSize(32, 32)
        self.setAttribute(Qt.WA_Hover)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = bool(self.window().dark)
        hover = self.underMouse()
        p.setPen(QPen(QColor(255, 255, 255, 60 if dark else 170), 1))
        p.setBrush(QColor(255, 255, 255, (45 if hover else 25) if dark else (190 if hover else 130)))
        p.drawEllipse(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))
        p.setPen(QPen(QColor("#f5f6fb" if dark else "#2a2c33"), 1.6, Qt.SolidLine, Qt.RoundCap))
        c, s = QPointF(16, 16), 4.5
        if self.kind == "min":
            p.drawLine(c + QPointF(-s, 0), c + QPointF(s, 0))
        else:
            p.drawLine(c + QPointF(-s, -s), c + QPointF(s, s))
            p.drawLine(c + QPointF(-s, s), c + QPointF(s, -s))


class PillButton(QAbstractButton):
    """Стеклянная кнопка-капсула с текстом."""

    def __init__(self, text):
        super().__init__(cursor=Qt.PointingHandCursor)
        self.setText(text)
        self.setAttribute(Qt.WA_Hover)
        self.setFixedHeight(32)
        self.setMinimumWidth(QFontMetricsF(self.font()).horizontalAdvance(text) + 36)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = bool(self.window().dark)
        hover = self.underMouse()
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(255, 255, 255, 60 if dark else 170), 1))
        p.setBrush(QColor(255, 255, 255, (45 if hover else 25) if dark else (190 if hover else 130)))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        p.setPen(QColor("#f5f6fb" if dark else "#2a2c33"))
        p.drawText(r, Qt.AlignCenter, self.text())


class Segmented(QWidget):
    """Капсула с вариантами (как переключатель в iOS/ColorOS): выбранный — синим. changed(имя варианта)."""

    changed = Signal(str)

    def __init__(self, options, current):
        super().__init__(cursor=Qt.PointingHandCursor)
        self.options = options  # [(имя, подпись)]
        self.current = current
        self.setAttribute(Qt.WA_Hover)
        self.setMouseTracking(True)
        fm = QFontMetricsF(self.font())
        self.cell = max(fm.horizontalAdvance(t) for _, t in options) + 26
        self.setFixedSize(int(self.cell * len(options)) + 4, 32)

    def set_quiet(self, name):
        self.current = name
        self.update()

    def mouseReleaseEvent(self, event):
        i = int((event.position().x() - 2) // self.cell)
        if 0 <= i < len(self.options) and self.options[i][0] != self.current:
            self.current = self.options[i][0]
            self.update()
            self.changed.emit(self.current)

    def mouseMoveEvent(self, event):
        self.update()

    def leaveEvent(self, event):
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = bool(self.window().dark)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(255, 255, 255, 60 if dark else 170), 1))
        p.setBrush(QColor(255, 255, 255, 25 if dark else 130))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        mouse = self.mapFromGlobal(QCursor.pos()) if self.underMouse() else None
        for i, (name, text) in enumerate(self.options):
            cell = QRectF(2 + i * self.cell, 2, self.cell, r.height() - 4)
            if name == self.current:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor("#2f6bff"))
                p.drawRoundedRect(cell, cell.height() / 2, cell.height() / 2)
                p.setPen(QColor("white"))
            else:
                if mouse is not None and cell.contains(QPointF(mouse)):
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(255, 255, 255, 30 if dark else 120))
                    p.drawRoundedRect(cell, cell.height() / 2, cell.height() / 2)
                p.setPen(QColor("#f5f6fb" if dark else "#2a2c33"))
            p.drawText(cell, Qt.AlignCenter, text)
