"""Курсы валют (open.er-api.com, без ключа): сколько стоит 1 доллар, евро… в твоей валюте; стрелка — к вчера."""
from lang import tr
import threading
from datetime import date

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter

from core import DesktopWidget, config, grid, open_uri
from widgets.weather import get_json

# код -> (знак, цвет значка)
MONEY = {"USD": ("$", "#2fbf71"), "EUR": ("€", "#2f6bff"), "RUB": ("₽", "#6c5ce7"), "CNY": ("¥", "#ff5a5f"),
         "KZT": ("₸", "#16a3c9"), "GBP": ("£", "#8a6cff"), "TRY": ("₺", "#e5486b"), "UZS": (tr("сўм"), "#2c9a6b")}
BASES = ("KZT", "RUB", "USD")
WATCH = {"KZT": ["USD", "EUR", "RUB", "CNY"], "RUB": ["USD", "EUR", "CNY", "KZT"],
         "USD": ["EUR", "RUB", "KZT", "CNY"]}
ROW = 40
GREEN, RED = QColor("#2fbf71"), QColor("#ff5a5f")


class CurrencyWidget(DesktopWidget):
    key = "currency"
    title = tr("Курсы валют")
    description = tr("Доллар, евро, рубль, юань — к вчера")
    SHAPES = {"list": (tr("Список"), grid(2, 2)), "two": (tr("Две валюты"), grid(2, 1)),
              "one": (tr("Одна крупно"), grid(1, 1))}
    loaded = Signal(object)

    def __init__(self, **kw):
        super().__init__(**kw)
        self.cfg.setdefault("base", "KZT")
        self.apply_shape()
        self.error = None
        self.loaded.connect(self.on_data)
        self.timer = QTimer(self, interval=60 * 60 * 1000, timeout=self.refresh)  # раз в час
        self.timer.start()
        self.refresh()

    def refresh(self):
        threading.Thread(target=self._fetch, args=(self.cfg["base"],), daemon=True).start()

    def _fetch(self, base):
        try:
            data = get_json(f"https://open.er-api.com/v6/latest/{base}")
            if data.get("result") != "success":
                raise ValueError(data.get("error-type"))
        except Exception as ex:
            data = {"error": tr("нет связи ({})").format(type(ex).__name__)}
        try:
            self.loaded.emit((base, data))
        except RuntimeError:
            pass

    def on_data(self, result):
        base, data = result
        if "error" in data:
            self.error = data["error"]
            self.update()
            return
        self.error = None
        # курс «1 валюта = X базовой»; храним вчерашний, чтобы показать стрелку
        today = date.today().isoformat()
        hist = self.cfg.setdefault("history", {}).setdefault(base, {})
        rates = {code: 1 / data["rates"][code] for code in WATCH[base] if data["rates"].get(code)}
        if hist.get("day") != today:
            hist["prev"] = hist.get("now", rates)
            hist["day"] = today
        hist["now"] = rates
        if self.placed:
            config.save()
        self.update()

    def add_actions(self, menu):
        sub = menu.addMenu(tr("Моя валюта"))
        for b in BASES:
            a = sub.addAction(f"{MONEY[b][0]}  {b}", lambda b=b: self.set_base(b))
            a.setCheckable(True)
            a.setChecked(self.cfg["base"] == b)
        menu.addAction(tr("Обновить"), self.refresh)

    def set_base(self, base):
        self.cfg["base"] = base
        config.save()
        self.refresh()

    def double_click(self):
        open_uri("https://www.google.com/finance/markets/currencies")

    def paintEvent(self, event):
        super().paintEvent(event)  # стекло
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        r = QRectF(self.card()).adjusted(18, 12, -18, -10)
        dark = bool(self.dark)
        fg = QColor("#ededf0") if dark else QColor("#151517")
        dim = QColor(fg)
        dim.setAlpha(130)
        base = self.cfg["base"]
        head = QFont("Segoe UI Semibold")
        head.setPixelSize(15)
        p.setFont(head)
        p.setPen(fg)
        p.drawText(QRectF(r.left(), r.top(), r.width(), 22), Qt.AlignLeft | Qt.AlignVCenter,
                   tr("Курс") if self.shape() == "one" else tr("Курсы валют"))
        p.setPen(dim)
        p.drawText(QRectF(r.left(), r.top(), r.width(), 22), Qt.AlignRight | Qt.AlignVCenter, tr("в {}").format(base))

        hist = self.cfg.get("history", {}).get(base, {})
        rates, prev = hist.get("now"), hist.get("prev", {})
        if not rates:
            p.drawText(r, Qt.AlignCenter, self.error or tr("загрузка…"))
            return
        if self.shape() == "one":
            self._one(p, r, rates, prev, fg, dim)
            return
        sym_font = QFont("Segoe UI Semibold")
        sym_font.setPixelSize(15)
        code_font = QFont("Segoe UI Semibold")
        code_font.setPixelSize(14)
        val_font = QFont("Bahnschrift SemiBold")
        val_font.setPixelSize(20)
        delta_font = QFont("Segoe UI")
        delta_font.setPixelSize(11)
        codes = WATCH[base][:2 if self.shape() == "two" else 4]
        step = max(ROW, (r.height() - 32) / len(codes))  # строки — на всю высоту ячеек сетки
        for i, code in enumerate(codes):
            if code not in rates:
                continue
            top = r.top() + 32 + i * step + (step - 34) / 2
            sym, color = MONEY[code]
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(color))
            p.drawEllipse(QPointF(r.left() + 14, top + 17), 14, 14)
            p.setFont(sym_font)
            p.setPen(QColor("white"))
            p.drawText(QRectF(r.left(), top + 3, 28, 28), Qt.AlignCenter, sym)
            p.setFont(code_font)
            p.setPen(fg)
            p.drawText(QRectF(r.left() + 38, top, 80, 34), Qt.AlignLeft | Qt.AlignVCenter, code)
            value = rates[code]
            text = f"{value:,.2f}".replace(",", " ") if value < 1000 else f"{value:,.0f}".replace(",", " ")
            p.setFont(val_font)
            p.drawText(QRectF(r.left(), top, r.width() - 64, 34), Qt.AlignRight | Qt.AlignVCenter, text)
            old = prev.get(code)
            change = (value - old) / old * 100 if old else 0
            if abs(change) >= 0.05:  # стрелка — только если курс за день правда сдвинулся
                up = change >= 0
                p.setPen(Qt.NoPen)
                p.setBrush(GREEN if up else RED)
                x, y = r.right() - 54, top + 17
                tri = [QPointF(x, y + 4), QPointF(x + 8, y + 4), QPointF(x + 4, y - 3)] if up else \
                      [QPointF(x, y - 3), QPointF(x + 8, y - 3), QPointF(x + 4, y + 4)]
                p.drawPolygon(tri)
                p.setFont(delta_font)
                p.setPen(GREEN if up else RED)
                p.drawText(QRectF(x + 10, top, 46, 34), Qt.AlignLeft | Qt.AlignVCenter, f"{abs(change):.1f}%")

    def _one(self, p, r, rates, prev, fg, dim):
        """Вид «Одна крупно»: первая валюта (доллар) — значок, крупный курс и сдвиг к вчера."""
        code = next((c for c in WATCH[self.cfg["base"]] if c in rates), None)
        if not code:
            return
        sym, color = MONEY[code]
        top = r.top() + 34
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color))
        p.drawEllipse(QPointF(r.left() + 16, top + 16), 16, 16)
        f = QFont("Segoe UI Semibold")
        f.setPixelSize(17)
        p.setFont(f)
        p.setPen(QColor("white"))
        p.drawText(QRectF(r.left(), top, 32, 32), Qt.AlignCenter, sym)
        f.setPixelSize(15)
        p.setFont(f)
        p.setPen(fg)
        p.drawText(QRectF(r.left() + 42, top, r.width() - 42, 32), Qt.AlignLeft | Qt.AlignVCenter, code)
        value = rates[code]
        big = QFont("Bahnschrift SemiBold")
        big.setPixelSize(34)
        p.setFont(big)
        p.drawText(QRectF(r.left(), top + 38, r.width(), 40), Qt.AlignLeft | Qt.AlignVCenter,
                   f"{value:,.2f}".replace(",", " ") if value < 1000 else f"{value:,.0f}".replace(",", " "))
        old = prev.get(code)
        change = (value - old) / old * 100 if old else 0
        small = QFont("Segoe UI")
        small.setPixelSize(12)
        p.setFont(small)
        row = QRectF(r.left(), top + 80, r.width(), 18)
        if abs(change) >= 0.05:  # треугольник рисуем сами, как в списке
            up = change >= 0
            p.setPen(Qt.NoPen)
            p.setBrush(GREEN if up else RED)
            y = row.center().y()
            x = row.left()
            p.drawPolygon([QPointF(x, y + 4), QPointF(x + 8, y + 4), QPointF(x + 4, y - 3)] if up else
                          [QPointF(x, y - 3), QPointF(x + 8, y - 3), QPointF(x + 4, y + 4)])
            p.setPen(GREEN if up else RED)
            p.drawText(row.adjusted(12, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter, tr("{:.1f}% к вчера").format(abs(change)))
        else:
            p.setPen(dim)
            p.drawText(row, Qt.AlignLeft | Qt.AlignVCenter, tr("как вчера"))
