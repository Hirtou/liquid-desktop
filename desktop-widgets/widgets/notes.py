from lang import tr
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QVBoxLayout

from core import DesktopWidget, config


class NotesWidget(DesktopWidget):
    keyboard_input = True  # в рабочем столе (app.desktop_child) нужен свой фокус для поля ввода
    key = "notes"
    title = tr("Заметки")
    description = tr("Записка, сохраняется сама")
    # высота в ячейках сетки (ширина всегда 2): правый клик → «Вид»
    SHAPES = {"normal": (tr("Обычные"), 2), "long": (tr("Длинные"), 3), "xlong": (tr("Очень длинные"), 4)}

    def __init__(self, **kw):
        super().__init__(**kw)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 14)
        head = QLabel(tr("Заметки"))
        head.setStyleSheet("font-size: 16px; font-weight: 600;")
        lay.addWidget(head)
        self.edit = QPlainTextEdit(self.cfg.get("text", ""))
        self.edit.setPlaceholderText(tr("Пиши здесь…"))
        lay.addWidget(self.edit)
        # сохраняем через полсекунды после последнего нажатия
        self.save_timer = QTimer(self, singleShot=True, interval=500, timeout=self.save)
        self.edit.textChanged.connect(self.save_timer.start)
        self.apply_shape()

    def apply_shape(self):
        self.fit_grid(2, min_rows=self.SHAPES[self.shape()][1])  # 2×2, 2×3 или 2×4 ячейки сетки

    def sync_preview(self):
        text = self.cfg.get("text", "")
        if text != self.edit.toPlainText():
            self.edit.blockSignals(True)
            self.edit.setPlainText(text)
            self.edit.blockSignals(False)

    def save(self):
        self.cfg["text"] = self.edit.toPlainText()
        config.save()

    def closeEvent(self, event):
        self.save()
        super().closeEvent(event)
