"""Пример мода Liquid Desktop: счётчик кликов. Клик — +1, правый клик → «Сбросить».
Шаблон для авторов модов: виджет — наследник DesktopWidget, рисует поверх стекла в paintEvent,
свои настройки хранит в self.cfg (раздел «mod_<id>» в config.json) и сохраняет config.save()."""
from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter

from core import DesktopWidget, config, grid
from widgets import kit


class CounterWidget(DesktopWidget):
    # key, title и description программа подставит сама из mod.json (ключ — «mod_<id>»)
    SHAPES = {"tile": ("Плитка", grid(1, 1))}

    def __init__(self, **kw):
        super().__init__(**kw)
        self.apply_shape()
        self.cfg.setdefault("count", 0)

    def tap(self, pos):
        """Короткий клик (зажал и потянул — виджет едет, это не клик)."""
        self.cfg["count"] += 1
        config.save()
        self.update()

    def add_actions(self, menu):
        """Свои пункты в меню виджета (правый клик)."""
        menu.addAction("Сбросить", self.reset)

    def reset(self):
        self.cfg["count"] = 0
        config.save()
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)  # стекло — его рисует программа
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        r = QRectF(self.card()).adjusted(16, 14, -16, -14)
        fg, dim, _ = kit.ink(self)  # цвета текста под тему (светлое / тёмное стекло)
        kit.text(p, QRectF(r.left(), r.top(), r.width(), 20), "Счётчик", fg, 15, "Segoe UI Semibold")
        kit.text(p, QRectF(r.left(), r.top() + 30, r.width(), 50), str(self.cfg["count"]), fg, 40,
                 "Bahnschrift SemiBold")
        kit.text(p, QRectF(r.left(), r.bottom() - 16, r.width(), 16), "клик — +1", dim, 11)
