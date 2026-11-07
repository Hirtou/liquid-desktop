"""Список дел: галочки, Enter — добавить; выполненные зачёркнуты. Всё хранится в настройках."""
from lang import tr
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout

from core import DesktopWidget, config

LIMIT = 12  # больше дел — виджет станет слишком высоким


class TodoWidget(DesktopWidget):
    key = "todo"
    title = tr("Дела")
    description = tr("Список дел с галочками")

    def __init__(self, **kw):
        super().__init__(**kw)
        self.cfg.setdefault("items", [{"text": tr("Попить воды"), "done": False},
                                      {"text": tr("Сделать зарядку"), "done": True}])
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 12, 18, 14)
        lay.setSpacing(6)
        head = QHBoxLayout()
        title = QLabel(tr("Дела"))
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        head.addWidget(title)
        head.addStretch()
        self.count = QLabel(objectName="dim")
        head.addWidget(self.count)
        lay.addLayout(head)
        self.list = QVBoxLayout()
        self.list.setSpacing(4)
        lay.addLayout(self.list)
        self.input = QLineEdit(placeholderText=tr("Новое дело — Enter"))
        self.input.returnPressed.connect(self.add_item)
        lay.addWidget(self.input)
        lay.addStretch()  # лишняя высота до целой ячейки — снизу
        self.rebuild_list()
        self.fit_grid(2)  # ширина 2 ячейки, высота — по числу дел, целыми ячейками

    def sync_preview(self):
        self.rebuild_list()

    def rebuild_list(self):
        while self.list.count():
            self.list.takeAt(0).widget().deleteLater()
        for i, item in enumerate(self.cfg["items"]):
            box = QCheckBox(item["text"])
            box.setChecked(item["done"])
            self._strike(box)
            box.toggled.connect(lambda on, i=i: self.toggle_item(i, on))
            self.list.addWidget(box)
        done = sum(it["done"] for it in self.cfg["items"])
        self.count.setText(tr("{} из {}").format(done, len(self.cfg['items'])))
        self.input.setEnabled(len(self.cfg["items"]) < LIMIT)
        self.adjustSize()

    @staticmethod
    def _strike(box):
        f = box.font()
        f.setStrikeOut(box.isChecked())
        box.setFont(f)

    def toggle_item(self, i, on):
        self.cfg["items"][i]["done"] = on
        config.save()
        self.rebuild_list()

    def add_item(self):
        text = self.input.text().strip()
        if text and len(self.cfg["items"]) < LIMIT:
            self.cfg["items"].append({"text": text, "done": False})
            config.save()
            self.input.clear()
            self.rebuild_list()

    def add_actions(self, menu):
        menu.addAction(tr("Убрать выполненные"), self.clear_done)
        menu.addAction(tr("Очистить всё"), self.clear_all)

    def clear_done(self):
        self.cfg["items"] = [it for it in self.cfg["items"] if not it["done"]]
        config.save()
        self.rebuild_list()

    def clear_all(self):
        self.cfg["items"] = []
        config.save()
        self.rebuild_list()
