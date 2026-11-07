"""Отсчёт до события: сколько дней осталось. По умолчанию — Новый год; своё событие — правый клик."""
from lang import tr
import math
import random
from datetime import date, datetime

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QInputDialog, QMessageBox

from core import DesktopWidget, config, grid

MONTHS = [tr("января"), tr("февраля"), tr("марта"), tr("апреля"), tr("мая"), tr("июня"),
          tr("июля"), tr("августа"), tr("сентября"), tr("октября"), tr("ноября"), tr("декабря")]
DAYS = [tr("пн"), tr("вт"), tr("ср"), tr("чт"), tr("пт"), tr("сб"), tr("вс")]
CORAL, CORAL2 = QColor("#ff8a5c"), QColor("#e5486b")
# Новый год: ёлочно-зелёная плитка со снегом, золото — в чипе и полоске
PINE, PINE2, GOLD = QColor("#22a06b"), QColor("#0b5a55"), QColor("#ffcf5a")


def plural(n, one, few, many):
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


class CountdownWidget(DesktopWidget):
    key = "countdown"
    title = tr("Отсчёт")
    description = tr("Сколько дней до события")
    SHAPES = {"full": (tr("Полный"), grid(2, 1)), "tile": (tr("Плитка"), grid(1, 1))}

    def __init__(self, **kw):
        super().__init__(**kw)
        self.apply_shape()
        self.timer = QTimer(self, interval=60 * 1000, timeout=self.update)  # раз в минуту — часы в счётчике
        self.timer.start()

    def event_info(self):
        """(название, дата события, дата начала отсчёта). Новый год переходит на следующий сам."""
        today = date.today()
        if self.cfg.get("date"):
            target = date.fromisoformat(self.cfg["date"])
            start = date.fromisoformat(self.cfg.get("start", today.isoformat()))
            return self.cfg.get("name", tr("Событие")), target, start
        return tr("Новый год"), date(today.year + 1, 1, 1), date(today.year, 1, 1)

    def add_actions(self, menu):
        menu.addAction(tr("Своё событие…"), self.ask_event)
        if self.cfg.get("date"):
            menu.addAction(tr("Вернуть Новый год"), self.reset_event)

    def ask_event(self):
        name, ok = QInputDialog.getText(None, tr("Отсчёт"), tr("Что ждём?"), text=self.cfg.get("name", tr("День рождения")))
        if not ok or not name.strip():
            return
        text, ok = QInputDialog.getText(None, tr("Отсчёт"), tr("Когда? (ДД.ММ.ГГГГ)"), text=self.cfg.get("date_text", ""))
        if not ok:
            return
        try:
            when = datetime.strptime(text.strip(), "%d.%m.%Y").date()
        except ValueError:
            QMessageBox.information(None, tr("Отсчёт"), tr("Дата в виде 25.12.2026"))
            return
        self.cfg.update({"name": name.strip(), "date": when.isoformat(), "date_text": text.strip(),
                         "start": date.today().isoformat()})
        config.save()
        self.update()

    def reset_event(self):
        for k in ("name", "date", "date_text", "start"):
            self.cfg.pop(k, None)
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
        name, target, start = self.event_info()
        new_year = not self.cfg.get("date")
        c1, c2, accent = (PINE, PINE2, GOLD) if new_year else (CORAL, CORAL2, CORAL)
        now = datetime.now()
        left = (target - now.date()).days
        hours = max(0, int((datetime.combine(target, datetime.min.time()) - now).total_seconds() // 3600))

        # плитка слева: крупное число дней
        tile = QRectF(r.left() + 14, r.top() + 14, r.height() - 28, r.height() - 28)
        g = QLinearGradient(tile.topLeft(), tile.bottomRight())
        g.setColorAt(0, c1)
        g.setColorAt(1, c2)
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(tile, 22, 22)
        if new_year:
            self._snow(p, tile)
        big = QFont("Bahnschrift SemiBold")
        big.setPixelSize(int(tile.height() * (0.44 if left < 1000 else 0.32)))
        p.setFont(big)
        p.setPen(QColor("white"))
        p.drawText(tile.adjusted(0, -12, 0, -12), Qt.AlignCenter, str(abs(left)))
        small = QFont("Segoe UI Semibold")
        small.setPixelSize(13)
        p.setFont(small)
        label = plural(left, tr("день"), tr("дня"), tr("дней")) if left > 0 else tr("сегодня!") if left == 0 else \
            plural(left, tr("день"), tr("дня"), tr("дней")) + tr(" назад")
        p.drawText(QRectF(tile.left(), tile.bottom() - 40, tile.width(), 20), Qt.AlignCenter, label)
        if self.shape() == "tile":  # только плитка: название события — сверху на ней
            head = QFont("Segoe UI Semibold")
            head.setPixelSize(12)
            p.setFont(head)
            p.drawText(QRectF(tile.left() + 12, tile.top() + 10, tile.width() - 24, 18), Qt.AlignCenter,
                       QFontMetricsF(head).elidedText(name, Qt.ElideRight, tile.width() - 24))
            return

        # справа: чип, название, дата, прогресс, счётчики
        x = tile.right() + 16
        w = r.right() - 16 - x
        chip = tr("сегодня!") if left == 0 else tr("прошло") if left < 0 else tr("осталось")
        cf = QFont("Segoe UI Semibold")
        cf.setPixelSize(11)
        cw = QFontMetricsF(cf).horizontalAdvance(chip) + 24
        pill = QRectF(r.right() - 16 - cw, r.top() + 15, cw, 20)
        bg = QColor(accent)
        bg.setAlpha(55 if dark else 70)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(pill, 10, 10)
        p.setBrush(accent)
        p.drawEllipse(QRectF(pill.left() + 8, pill.center().y() - 3.5, 7, 7))
        p.setFont(cf)
        p.setPen(accent.lighter(130) if dark else accent.darker(170))
        p.drawText(pill.adjusted(19, 0, -6, 0), Qt.AlignVCenter | Qt.AlignLeft, chip)

        title = QFont("Segoe UI Semibold")
        title.setPixelSize(16)
        p.setFont(title)
        p.setPen(fg)
        p.drawText(QRectF(x, r.top() + 14, w - cw - 8, 22), Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetricsF(title).elidedText(name, Qt.ElideRight, w - cw - 8))
        tiny = QFont("Segoe UI")
        tiny.setPixelSize(12)
        p.setFont(tiny)
        p.setPen(dim)
        p.drawText(QRectF(x, r.top() + 38, w, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   f"{target.day} {MONTHS[target.month - 1]} {target.year}, {DAYS[target.weekday()]}")

        total = max(1, (target - start).days)
        frac = min(1, max(0, (now.date() - start).days / total))
        bar = QRectF(x, r.top() + 68, w, 6)
        track = QColor(fg)
        track.setAlpha(35)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(bar, 3, 3)
        fill = QLinearGradient(bar.topLeft(), bar.topRight())
        fill.setColorAt(0, c1)
        fill.setColorAt(1, accent if new_year else c2)
        p.setBrush(fill)
        p.drawRoundedRect(QRectF(bar.left(), bar.top(), max(6, bar.width() * frac), bar.height()), 3, 3)
        p.setPen(dim)
        p.drawText(QRectF(x, bar.bottom() + 4, w, 16), Qt.AlignLeft | Qt.AlignVCenter, tr("пройдено {:.0f}%").format(frac * 100))

        num = QFont("Bahnschrift SemiBold")
        num.setPixelSize(18)
        for i, (value, label) in enumerate(((max(left, 0) // 7, plural(left // 7, tr("неделя"), tr("недели"), tr("недель"))),
                                            (hours, plural(hours, tr("час"), tr("часа"), tr("часов"))))):
            cx = x + i * w / 2
            p.setFont(num)
            p.setPen(fg)
            p.drawText(QRectF(cx, r.bottom() - 46, w / 2, 22), Qt.AlignLeft | Qt.AlignVCenter, f"{value:,}".replace(",", " "))
            p.setFont(tiny)
            p.setPen(dim)
            p.drawText(QRectF(cx, r.bottom() - 26, w / 2, 14), Qt.AlignLeft | Qt.AlignVCenter, label)

    @staticmethod
    def _snow(p, tile):
        """Снег на плитке: снежинки-точки, несколько звёздочек и сугроб внизу. Узор всегда один и тот же."""
        rnd = random.Random(7)
        p.save()
        clip = QPainterPath()
        clip.addRoundedRect(tile, 22, 22)
        p.setClipPath(clip)
        p.setPen(Qt.NoPen)
        for _ in range(34):
            flake = QColor(255, 255, 255, rnd.randint(90, 220))
            p.setBrush(flake)
            s = rnd.uniform(0.9, 2.6)
            p.drawEllipse(QPointF(tile.left() + rnd.random() * tile.width(), tile.top() + rnd.random() * tile.height() * 0.9), s, s)
        for _ in range(5):  # звёздочки из шести лучей
            c = QPointF(tile.left() + rnd.uniform(0.1, 0.9) * tile.width(), tile.top() + rnd.uniform(0.08, 0.7) * tile.height())
            s = rnd.uniform(4, 7)
            p.setPen(QPen(QColor(255, 255, 255, 200), 1.3, Qt.SolidLine, Qt.RoundCap))
            for k in range(3):
                a = math.pi / 3 * k
                d = QPointF(math.cos(a) * s, math.sin(a) * s)
                p.drawLine(c - d, c + d)
        # сугроб: мягкая волна по низу
        drift = QPainterPath(QPointF(tile.left(), tile.bottom()))
        y = tile.bottom() - tile.height() * 0.06
        drift.lineTo(tile.left(), y)
        steps = 4
        for i in range(steps):
            x0 = tile.left() + tile.width() * i / steps
            x1 = tile.left() + tile.width() * (i + 1) / steps
            up = tile.height() * (0.04 if i % 2 else 0.025)
            drift.cubicTo(QPointF(x0 + (x1 - x0) * 0.3, y - up), QPointF(x0 + (x1 - x0) * 0.7, y - up), QPointF(x1, y))
        drift.lineTo(tile.right(), tile.bottom())
        drift.closeSubpath()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 235))
        p.drawPath(drift)
        p.restore()
