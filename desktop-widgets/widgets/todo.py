"""Список дел: галочки, Enter — добавить; выполненные зачёркнуты. Всё хранится в настройках."""
from lang import tr
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from core import DesktopWidget, config

LIMIT = 12  # больше дел — виджет станет слишком высоким


class Item(QWidget):
    """Одно дело: галочка и текст, который переносится на следующие строки (у галочки Qt текст в одну строку —
    длинное дело уходило за край виджета, и дочитать его было нельзя). Клик по тексту — тоже ставит галочку."""

    def __init__(self, text, done, on_toggle):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self.box = QCheckBox()
        self.box.setChecked(done)
        row.addWidget(self.box, alignment=Qt.AlignTop)
        self.label = QLabel(text, wordWrap=True)
        self.label.setStyleSheet("font-size: 14px;")
        self.label.setTextInteractionFlags(Qt.NoTextInteraction)
        f = self.label.font()
        f.setStrikeOut(done)
        self.label.setFont(f)
        if done:
            self.label.setObjectName("dim")
        row.addWidget(self.label, 1)
        self.box.toggled.connect(on_toggle)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.label.geometry().contains(event.position().toPoint()):
            self.box.toggle()


class TodoWidget(DesktopWidget):
    keyboard_input = True  # в рабочем столе (app.desktop_child) нужен свой фокус для поля ввода
    key = "todo"
    title = tr("Дела")
    description = tr("Список дел с галочками")
    # ширина в ячейках сетки (высота — по делам): правый клик → «Вид»
    SHAPES = {"normal": (tr("Обычный"), 2), "wide": (tr("Широкий"), 3), "xwide": (tr("Очень широкий"), 4)}

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
        self.apply_shape()

    def apply_shape(self):
        self.fit_grid(self.SHAPES[self.shape()][1])  # ширина 2–4 ячейки, высота — по делам, целыми ячейками

    def sync_preview(self):
        self.rebuild_list()

    def rebuild_list(self):
        while self.list.count():
            self.list.takeAt(0).widget().deleteLater()
        for i, item in enumerate(self.cfg["items"]):
            self.list.addWidget(Item(item["text"], item["done"], lambda on, i=i: self.toggle_item(i, on)))
        done = sum(it["done"] for it in self.cfg["items"])
        self.count.setText(tr("{} из {}").format(done, len(self.cfg['items'])))
        self.input.setEnabled(len(self.cfg["items"]) < LIMIT)
        self.adjustSize()

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
