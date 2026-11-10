"""Привычки: неделя кружками у каждой привычки, клик отмечает день, серия — сколько дней подряд."""
from lang import tr
from datetime import date, timedelta

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QInputDialog

from core import DesktopWidget, config, grid
from widgets import kit

DAYS = [tr("пн"), tr("вт"), tr("ср"), tr("чт"), tr("пт"), tr("сб"), tr("вс")]
COLORS = [QColor(c) for c in ("#4ade80", "#60a5fa", "#fbbf24", "#f472b6", "#a78bfa", "#22d3ee", "#fb923c", "#f87171")]
KEEP = 400  # дней истории у привычки


def streak(days, today):
    """Сколько дней подряд до сегодня (сегодня ещё не отмечено — серия не обрывается)."""
    count, day = 0, today if today.isoformat() in days else today - timedelta(days=1)
    while day.isoformat() in days:
        count += 1
        day -= timedelta(days=1)
    return count


class HabitsWidget(DesktopWidget):
    key = "habits"
    title = tr("Привычки")
    description = tr("Отмечай каждый день, считает серию")
    SHAPES = {"full": (tr("Полный"), grid(2, 1)), "tall": (tr("Высокий"), grid(2, 2))}

    def __init__(self, **kw):
        super().__init__(**kw)
        self.apply_shape()
        self.cfg.setdefault("items", [{"name": "Зарядка", "days": []}, {"name": "Чтение", "days": []},
                                      {"name": "Прогулка", "days": []}])
        self.dots = {}
        self.timer = QTimer(self, interval=10 * 60 * 1000, timeout=self.update)  # полночь — новый день
        self.timer.start()

    def click(self, pos):
        for (i, day), rect in self.dots.items():
            if rect.contains(pos):
                days = self.cfg["items"][i]["days"]
                if day in days:
                    days.remove(day)
                else:
                    days.append(day)
                    del days[:-KEEP]
                config.save()
                self.update()
                return True
        return False

    def add_actions(self, menu):
        menu.addAction(tr("Добавить привычку…"), self.add_item)
        items = self.cfg["items"]
        if items:
            rename = menu.addMenu(tr("Переименовать"))
            remove = menu.addMenu(tr("Удалить"))
            for i, item in enumerate(items):
                rename.addAction(tr(item["name"]), lambda i=i: self.rename_item(i))
                remove.addAction(tr(item["name"]), lambda i=i: self.remove_item(i))

    def add_item(self):
        name, ok = QInputDialog.getText(self, tr("Привычки"), tr("Название:"))
        if ok and name.strip():
            self.cfg["items"].append({"name": name.strip()[:40], "days": []})
            config.save()
            self.update()

    def rename_item(self, i):
        item = self.cfg["items"][i]
        name, ok = QInputDialog.getText(self, tr("Привычки"), tr("Название:"), text=tr(item["name"]))
        if ok and name.strip():
            item["name"] = name.strip()[:40]
            config.save()
            self.update()

    def remove_item(self, i):
        del self.cfg["items"][i]
        config.save()
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)  # стекло
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        r = QRectF(self.card())
        fg, dim, track = kit.ink(self)
        dark = bool(self.dark)
        today = date.today()
        items = self.cfg["items"]
        done = sum(1 for it in items if today.isoformat() in it["days"])
        all_done = bool(items) and done == len(items)
        cw = kit.chip(p, r, tr("сегодня {}/{}").format(done, len(items)), kit.GREEN if all_done else kit.ACCENT, dark)
        x, w = r.left() + 18, r.width() - 36
        kit.text(p, QRectF(x, r.top() + 14, w - cw, 22), tr("Привычки"), fg, 16, "Segoe UI Semibold")

        d = 22
        gap = 5
        strip = 7 * d + 6 * gap
        sx = r.right() - 18 - strip
        week = [today - timedelta(days=6 - i) for i in range(7)]
        for i, day in enumerate(week):
            kit.text(p, QRectF(sx + i * (d + gap) - 2, r.top() + 38, d + 4, 12), DAYS[day.weekday()], fg if i == 6 else dim, 9,
                     align=Qt.AlignCenter)
        step = 34
        room = int((r.bottom() - 10 - (r.top() + 52)) // step)
        self.dots = {}
        for i, item in enumerate(items[:room]):
            y = r.top() + 52 + i * step
            color = COLORS[i % len(COLORS)]
            kit.text(p, QRectF(x, y, sx - x - 8, 16), tr(item["name"]), fg, 13, "Segoe UI Semibold", elide=True)
            run = streak(set(item["days"]), today)
            kit.text(p, QRectF(x, y + 15, sx - x - 8, 13), tr("{} дн подряд").format(run) if run else tr("без серии"), dim, 10, elide=True)
            for j, day in enumerate(week):
                rect = QRectF(sx + j * (d + gap), y + 3, d, d)
                self.dots[(i, day.isoformat())] = rect.adjusted(-2, -3, 2, 3)
                on = day.isoformat() in item["days"]
                p.setBrush(color if on else track)
                p.setPen(QPen(fg, 1.5) if j == 6 else Qt.NoPen)
                p.drawEllipse(rect)
                if on:  # галочка
                    tick = QColor("#10131a")
                    p.setPen(QPen(tick, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                    c = rect.center()
                    p.drawPolyline([QPointF(c.x() - 5, c.y()), QPointF(c.x() - 1.5, c.y() + 3.5), QPointF(c.x() + 5, c.y() - 4)])
        if not items:
            kit.text(p, QRectF(x, r.top() + 56, w, 36), tr("Правый клик — добавить привычку"), dim)
