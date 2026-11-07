from lang import tr
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QVBoxLayout

from core import DesktopWidget, config


class NotesWidget(DesktopWidget):
    key = "notes"
    title = tr("Заметки")
    description = tr("Записка, сохраняется сама")

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
        self.fit_grid(2, min_rows=2)  # 2×2 ячейки сетки

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
