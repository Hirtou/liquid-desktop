"""Калькулятор как на телефоне: кнопки мышью, цифры с клавиатуры. Считает точно (0,1 + 0,2 = 0,3).
Десятичный знак — по языку: «,» по-русски, «.» по-английски."""
from lang import LANG, tr
from decimal import Decimal, DivisionByZero, InvalidOperation, Overflow, getcontext

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter

from core import DesktopWidget, grid
from widgets import kit

getcontext().prec = 28
# по-английски 1,234.5 — по-русски 1 234,5 (клавиша «,» внутри — всегда «десятичный знак»)
DEC, GROUP = (".", ",") if LANG == "en" else (",", " ")
KEYS = ["C", "±", "%", "÷",
        "7", "8", "9", "×",
        "4", "5", "6", "−",
        "1", "2", "3", "+",
        "0", ",", "⌫", "="]
OPS = {"÷": lambda a, b: a / b, "×": lambda a, b: a * b, "−": lambda a, b: a - b, "+": lambda a, b: a + b}
TYPED = {Qt.Key_Plus: "+", Qt.Key_Minus: "−", Qt.Key_Asterisk: "×", Qt.Key_Slash: "÷", Qt.Key_Percent: "%",
         Qt.Key_Equal: "=", Qt.Key_Return: "=", Qt.Key_Enter: "=", Qt.Key_Backspace: "⌫", Qt.Key_Escape: "C",
         Qt.Key_Delete: "C", Qt.Key_Comma: ",", Qt.Key_Period: ","}


def show(value):
    """Decimal -> «1 234,5» (очень большие и малые — с порядком)."""
    if abs(value) >= Decimal("1e15") or (value != 0 and abs(value) < Decimal("1e-9")):
        return f"{value:.6e}".replace(".", DEC)
    rounded = round(value, 10).normalize()
    whole, _, frac = f"{rounded:f}".partition(".")
    sign = "-" if whole.startswith("-") else ""
    digits = whole.lstrip("-")
    groups = f"{int(digits or 0):,}".replace(",", GROUP)
    return sign + groups + (DEC + frac if frac else "")


class Calculator:
    """Логика отдельно от рисования: press(клавиша), screen — что на экране, history — строка сверху."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.entry = "0"       # что набирают: строка с точкой
        self.acc = None        # первое число
        self.op = None         # выбранное действие
        self.fresh = True      # следующая цифра начинает число заново
        self.error = False
        self.history = ""

    @property
    def screen(self):
        if self.error:
            return tr("Ошибка")
        if self.fresh:
            return show(Decimal(self.entry))
        whole, dot, frac = self.entry.partition(".")
        return show(Decimal(whole or "0")) + (DEC + frac if dot else "")

    def press(self, key):
        if self.error and key != "C":
            self.reset()
        if key.isdigit():
            if self.fresh or self.entry == "0":
                self.entry, self.fresh = key, False
            elif len(self.entry.replace(".", "").lstrip("-")) < 15:
                self.entry += key
        elif key == ",":
            if self.fresh:
                self.entry, self.fresh = "0.", False
            elif "." not in self.entry:
                self.entry += "."
        elif key == "C":
            self.reset()
        elif key == "⌫":
            if not self.fresh:
                self.entry = self.entry[:-1] or "0"
                if self.entry == "-":
                    self.entry = "0"
        elif key == "±":
            if self.entry not in ("0", "0."):
                self.entry = self.entry[1:] if self.entry.startswith("-") else "-" + self.entry
        elif key == "%":
            self.entry = self.compute(lambda: self.percent())
            self.fresh = True
        elif key in OPS:
            if self.op and not self.fresh:
                self.finish()
            elif self.acc is None or not self.op:
                self.acc = Decimal(self.entry)
            if not self.error:
                self.op = key
                self.fresh = True
                self.history = f"{show(self.acc)} {key}"
        elif key == "=":
            if self.op:
                self.history = f"{show(self.acc)} {self.op} {show(Decimal(self.entry))} ="
                self.finish()
                self.op = None
                self.fresh = True

    def percent(self):
        value = Decimal(self.entry)
        # 200 + 10% = 200 + 20; без действия — просто сотая часть
        return self.acc * value / 100 if self.acc is not None and self.op in ("+", "−") else value / 100

    def compute(self, fn):
        try:
            return format(fn(), "f")
        except (DivisionByZero, InvalidOperation, Overflow, ZeroDivisionError):
            self.error = True
            return "0"

    def finish(self):
        a, b, op = self.acc, Decimal(self.entry), OPS[self.op]
        self.entry = self.compute(lambda: op(a, b))
        self.acc = None if self.error else Decimal(self.entry)


class CalcWidget(DesktopWidget):
    key = "calc"
    title = tr("Калькулятор")
    description = tr("Обычный калькулятор, можно с клавиатуры")
    SHAPES = {"full": (tr("Полный"), grid(2, 2))}

    def __init__(self, **kw):
        super().__init__(**kw)
        self.apply_shape()
        self.setFocusPolicy(Qt.ClickFocus)
        self.calc = Calculator()
        self.rects = {}

    def click(self, pos):
        self.setFocus()
        for key, rect in self.rects.items():
            if rect.contains(pos):
                self.calc.press(key)
                self.update()
                return True
        return False

    def keyPressEvent(self, event):
        key = TYPED.get(event.key()) or (event.text() if event.text().isdigit() else None)
        if key:
            self.calc.press(key)
            self.update()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)  # стекло
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        r = QRectF(self.card()).adjusted(14, 12, -14, -14)
        fg, dim, track = kit.ink(self)
        dark = bool(self.dark)
        kit.text(p, QRectF(r.left() + 4, r.top(), r.width() - 8, 20), self.calc.history, dim, 13,
                 align=Qt.AlignRight | Qt.AlignVCenter, elide=True)
        value = self.calc.screen
        size = 40 if len(value) <= 13 else 30 if len(value) <= 18 else 22
        kit.text(p, QRectF(r.left() + 4, r.top() + 18, r.width() - 8, 48), value, fg, size, "Bahnschrift SemiBold",
                 Qt.AlignRight | Qt.AlignVCenter)
        top = r.top() + 72
        gap = 8
        kw = (r.width() - 3 * gap) / 4
        kh = (r.bottom() - top - 4 * gap) / 5
        self.rects = {}
        for i, key in enumerate(KEYS):
            rect = QRectF(r.left() + (i % 4) * (kw + gap), top + (i // 4) * (kh + gap), kw, kh)
            self.rects[key] = rect
            if key == "=":
                kit.button(p, rect, key, fg, dark, kit.ACCENT, 20)
            elif key in OPS:  # действия — стеклянные с синей подписью, как чип, а не оранжевые
                kit.button(p, rect, key, fg, dark, None, 20, tint=kit.ACCENT)
            elif key in ("C", "±", "%", "⌫"):
                kit.button(p, rect, key, dim, dark, None, 17)
            else:
                kit.button(p, rect, DEC if key == "," else key, fg, dark, None, 17)
