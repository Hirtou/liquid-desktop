from lang import tr
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLabel, QVBoxLayout

from core import DesktopWidget, open_uri

DAYS = [tr("понедельник"), tr("вторник"), tr("среда"), tr("четверг"), tr("пятница"), tr("суббота"), tr("воскресенье")]
MONTHS = [tr("января"), tr("февраля"), tr("марта"), tr("апреля"), tr("мая"), tr("июня"),
          tr("июля"), tr("августа"), tr("сентября"), tr("октября"), tr("ноября"), tr("декабря")]


class ClockWidget(DesktopWidget):
    key = "clock"
    title = tr("Часы")
    description = tr("Время и дата")
    # размер задаёт раскладка (подписи), поэтому вместо размеров — (шрифт времени, секунды?, дата?)
    SHAPES = {"full": (tr("С секундами"), (52, True, True)), "big": (tr("Крупные"), (78, False, True)),
              "time": (tr("Только время"), (60, False, False))}

    def __init__(self, **kw):
        super().__init__(**kw)
        self.time = QLabel()
        self.date = QLabel(objectName="dim")
        self.date.setStyleSheet("font-size: 15px;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 12, 24, 16)
        lay.setSpacing(0)
        lay.addWidget(self.time, alignment=Qt.AlignCenter)
        lay.addWidget(self.date, alignment=Qt.AlignCenter)
        self.timer = QTimer(self, interval=1000, timeout=self.tick)
        self.timer.start()
        self.apply_shape()

    def apply_shape(self):
        size, _, with_date = self.SHAPES[self.shape()][1]
        self.time.setStyleSheet(f"font-size: {size}px; font-weight: {600 if size > 60 else 300};")
        self.date.setVisible(with_date)
        self.tick()
        self.fit_grid(2)  # 2×1 ячейки сетки

    def double_click(self):
        open_uri("ms-clock:")  # приложение «Часы» Windows

    def tick(self):
        now = datetime.now()
        self.time.setText(now.strftime("%H:%M:%S" if self.SHAPES[self.shape()][1][1] else "%H:%M"))
        self.date.setText(f"{DAYS[now.weekday()]}, {now.day} {MONTHS[now.month - 1]}")
