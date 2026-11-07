"""Календарь на месяц: сегодня — синим кружком, выходные — красноватые."""
from lang import tr
import calendar
from datetime import date, timedelta

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter

from core import DesktopWidget, grid

MONTHS = [tr("Январь"), tr("Февраль"), tr("Март"), tr("Апрель"), tr("Май"), tr("Июнь"),
          tr("Июль"), tr("Август"), tr("Сентябрь"), tr("Октябрь"), tr("Ноябрь"), tr("Декабрь")]
DAYS = [tr("пн"), tr("вт"), tr("ср"), tr("чт"), tr("пт"), tr("сб"), tr("вс")]
FULL_DAYS = [tr("Понедельник"), tr("Вторник"), tr("Среда"), tr("Четверг"), tr("Пятница"), tr("Суббота"), tr("Воскресенье")]
BLUE = QColor("#2f6bff")
RED = QColor("#ff5a5f")


class CalendarWidget(DesktopWidget):
    key = "calendar"
    title = tr("Календарь")
    description = tr("Месяц, сегодня — синим")
    SHAPES = {"month": (tr("Месяц"), grid(2, 2)), "week": (tr("Неделя"), grid(2, 1)), "today": (tr("Сегодня"), grid(1, 1))}

    def __init__(self, **kw):
        super().__init__(**kw)
        self.apply_shape()
        self.today = date.today()
        # раз в минуту — не наступил ли новый день
        self.timer = QTimer(self, interval=60 * 1000, timeout=self.check_day)
        self.timer.start()
        self.offset = 0  # листание колесом: на сколько месяцев от текущего

    def check_day(self):
        if date.today() != self.today:
            self.today = date.today()
            self.update()

    def wheelEvent(self, event):
        """Колесо мыши — листать месяцы."""
        if self.shape() != "month":
            return
        self.offset += -1 if event.angleDelta().y() > 0 else 1
        self.update()

    def click(self, pos):
        """Клик по заголовку — вернуться к сегодняшнему месяцу."""
        if self.offset and pos.y() < self.card().top() + 40:
            self.offset = 0
            self.update()
            return True
        return False

    def shown(self):
        """Какой месяц показан: (год, месяц)."""
        m = self.today.year * 12 + self.today.month - 1 + self.offset
        return m // 12, m % 12 + 1

    def paintEvent(self, event):
        super().paintEvent(event)  # стекло
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        r = QRectF(self.card()).adjusted(18, 14, -18, -16)
        dark = bool(self.dark)
        fg = QColor("#ededf0") if dark else QColor("#151517")
        dim = QColor(fg)
        dim.setAlpha(130)
        weekend = QColor(RED)
        weekend.setAlpha(210)
        today = date.today()
        if self.shape() == "today":
            self._today(p, r, today, fg, dim, weekend)
            return
        if self.shape() == "week":
            self._week(p, r, today, fg, dim, weekend)
            return
        year, month = self.shown()

        head = QFont("Segoe UI Semibold")
        head.setPixelSize(17)
        p.setFont(head)
        p.setPen(fg)
        p.drawText(QRectF(r.left(), r.top(), r.width(), 24), Qt.AlignLeft | Qt.AlignVCenter, MONTHS[month - 1])
        p.setPen(BLUE if self.offset else dim)  # не текущий месяц — год синим (клик по заголовку вернёт)
        p.drawText(QRectF(r.left(), r.top(), r.width(), 24), Qt.AlignRight | Qt.AlignVCenter, str(year))

        cw = r.width() / 7
        top = r.top() + 34
        small = QFont("Segoe UI Semibold")
        small.setPixelSize(11)
        p.setFont(small)
        for i, d in enumerate(DAYS):
            p.setPen(weekend if i >= 5 else dim)
            p.drawText(QRectF(r.left() + i * cw, top, cw, 18), Qt.AlignCenter, d)

        weeks = calendar.Calendar().monthdayscalendar(year, month)
        this_month = (year, month) == (today.year, today.month)
        rh = (r.bottom() - top - 22) / max(len(weeks), 5)
        num = QFont("Segoe UI")
        num.setPixelSize(14)
        for row, week in enumerate(weeks):
            for col, day in enumerate(week):
                if not day:
                    continue
                cell = QRectF(r.left() + col * cw, top + 22 + row * rh, cw, rh)
                if this_month and day == today.day:
                    d = min(cw, rh) - 4
                    p.setPen(Qt.NoPen)
                    p.setBrush(BLUE)
                    p.drawEllipse(cell.center(), d / 2, d / 2)
                    bold = QFont(num)
                    bold.setBold(True)
                    p.setFont(bold)
                    p.setPen(QColor("white"))
                else:
                    p.setFont(num)
                    p.setPen(weekend if col >= 5 else fg)
                p.drawText(cell, Qt.AlignCenter, str(day))

    def _today(self, p, r, today, fg, dim, weekend):
        """Вид «Сегодня»: день недели синим, крупное число, месяц и год."""
        head = QFont("Segoe UI Semibold")
        head.setPixelSize(16)
        p.setFont(head)
        p.setPen(weekend if today.weekday() >= 5 else BLUE)
        p.drawText(QRectF(r.left(), r.top(), r.width(), 22), Qt.AlignLeft | Qt.AlignVCenter,
                   FULL_DAYS[today.weekday()])
        big = QFont("Bahnschrift SemiBold")
        big.setPixelSize(int(r.height() * 0.58))
        p.setFont(big)
        p.setPen(fg)
        p.drawText(QRectF(r.left(), r.top() + 18, r.width(), r.height() - 44), Qt.AlignLeft | Qt.AlignVCenter,
                   str(today.day))
        small = QFont("Segoe UI")
        small.setPixelSize(13)
        p.setFont(small)
        p.setPen(dim)
        p.drawText(QRectF(r.left(), r.bottom() - 22, r.width(), 22), Qt.AlignLeft | Qt.AlignVCenter,
                   f"{MONTHS[today.month - 1]} {today.year}")

    def _week(self, p, r, today, fg, dim, weekend):
        """Вид «Неделя»: месяц и эта неделя, сегодня — синим кружком."""
        head = QFont("Segoe UI Semibold")
        head.setPixelSize(15)
        p.setFont(head)
        p.setPen(fg)
        p.drawText(QRectF(r.left(), r.top(), r.width(), 22), Qt.AlignLeft | Qt.AlignVCenter, MONTHS[today.month - 1])
        p.setPen(dim)
        p.drawText(QRectF(r.left(), r.top(), r.width(), 22), Qt.AlignRight | Qt.AlignVCenter, str(today.year))
        cw = r.width() / 7
        small = QFont("Segoe UI Semibold")
        small.setPixelSize(11)
        num = QFont("Segoe UI")
        num.setPixelSize(15)
        monday = today - timedelta(days=today.weekday())
        for i in range(7):
            day = monday + timedelta(days=i)
            p.setFont(small)
            p.setPen(weekend if i >= 5 else dim)
            p.drawText(QRectF(r.left() + i * cw, r.top() + 30, cw, 16), Qt.AlignCenter, DAYS[i])
            cell = QRectF(r.left() + i * cw, r.top() + 48, cw, r.bottom() - r.top() - 48)
            if day == today:
                d = min(cw, cell.height()) - 4
                p.setPen(Qt.NoPen)
                p.setBrush(BLUE)
                p.drawEllipse(cell.center(), d / 2, d / 2)
                bold = QFont(num)
                bold.setBold(True)
                p.setFont(bold)
                p.setPen(QColor("white"))
            else:
                p.setFont(num)
                p.setPen(weekend if i >= 5 else fg)
            p.drawText(cell, Qt.AlignCenter, str(day.day))
