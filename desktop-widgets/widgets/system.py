from lang import tr
import psutil
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QGridLayout, QLabel, QProgressBar, QVBoxLayout

from core import DesktopWidget, open_uri

BAR_STYLE = "QProgressBar::chunk { background: %s; border-radius: 3px; }"


def gb(n):
    return tr("{:.0f} ГБ").format(n / 1024 ** 3)


class SystemWidget(DesktopWidget):
    key = "system"
    title = tr("Система")
    description = tr("Процессор, память, место на дисках")

    def __init__(self, **kw):
        super().__init__(**kw)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 16)
        head = QLabel(tr("Система"))
        head.setStyleSheet("font-size: 16px; font-weight: 600;")
        lay.addWidget(head)
        grid = QGridLayout()
        grid.setVerticalSpacing(8)
        lay.addLayout(grid)

        self.disks = [p.mountpoint for p in psutil.disk_partitions(all=False)
                      if p.fstype and "cdrom" not in p.opts]
        self.rows = {}
        names = [tr("ЦП"), tr("Память")] + [d.rstrip("\\") for d in self.disks]
        for i, name in enumerate(names):
            label = QLabel(name)
            bar = QProgressBar(textVisible=False, maximum=100)
            bar.setFixedHeight(6)
            value = QLabel(objectName="dim")
            grid.addWidget(label, i, 0)
            grid.addWidget(bar, i, 1)
            grid.addWidget(value, i, 2)
            self.rows[name] = (bar, value)
        grid.setColumnStretch(1, 1)

        psutil.cpu_percent()  # первый вызов всегда 0 — «прогреваем»
        self.timer = QTimer(self, interval=2000, timeout=self.update_stats)
        self.timer.start()
        self.update_stats()
        lay.addStretch()
        self.fit_grid(2)  # 2 ячейки в ширину, высота — по числу дисков, целыми ячейками

    def double_click(self):
        open_uri("taskmgr.exe")  # диспетчер задач

    def set_row(self, name, percent, text):
        bar, value = self.rows[name]
        bar.setValue(int(percent))
        color = "#ff6b6b" if percent > 85 else "#ffc861" if percent > 65 else "#5ad1a0"
        bar.setStyleSheet(BAR_STYLE % color)
        value.setText(text)

    def update_stats(self):
        cpu = psutil.cpu_percent()
        self.set_row(tr("ЦП"), cpu, f"{cpu:.0f}%")
        mem = psutil.virtual_memory()
        self.set_row(tr("Память"), mem.percent, f"{mem.used / 1024 ** 3:.1f}/{gb(mem.total)}")
        for d in self.disks:
            try:
                u = psutil.disk_usage(d)
            except OSError:
                continue
            self.set_row(d.rstrip("\\"), u.percent, tr("своб. {}").format(gb(u.free)))
