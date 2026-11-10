"""Буфер обмена: последние скопированные тексты, клик — скопировать снова.
История только в памяти: на диск не пишется, после выхода из программы пропадает.
Что менеджеры паролей помечают как секретное, виджет не запоминает."""
from lang import tr
import time

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication

from core import DesktopWidget, config, grid
from widgets import kit

SECRET = 'application/x-qt-windows-mime;value="ExcludeClipboardContentFromMonitorProcessing"'  # пометка менеджеров паролей
MAX = 20


class History:
    """Одна история на все копии виджета (превью в каталоге показывает ту же)."""
    items = []     # [(текст, когда)], новые сверху
    started = False
    listeners = []

    @classmethod
    def start(cls):
        if cls.started:
            return
        cls.started = True
        QApplication.clipboard().dataChanged.connect(cls.changed)

    @classmethod
    def changed(cls):
        board = QApplication.clipboard()
        mime = board.mimeData()
        if mime is None or not mime.hasText() or mime.hasFormat(SECRET):
            return
        value = mime.text()
        if not value.strip() or len(value) > 200_000:
            return
        cls.items = [(value, time.time())] + [it for it in cls.items if it[0] != value][:MAX - 1]
        for fn in list(cls.listeners):
            try:
                fn()
            except RuntimeError:  # копию виджета уже удалили (превью каталога)
                cls.listeners.remove(fn)


def ago(sec):
    sec = int(max(0, sec))
    return tr("сейчас") if sec < 10 else tr("{} с").format(sec) if sec < 60 else tr("{} мин").format(sec // 60) \
        if sec < 3600 else tr("{} ч").format(sec // 3600)


class ClipboardWidget(DesktopWidget):
    key = "clipboard"
    title = tr("Буфер")
    description = tr("Что копировал недавно, клик — скопировать снова")
    SHAPES = {"full": (tr("Полный"), grid(2, 1)), "tall": (tr("Высокий"), grid(2, 2))}

    def __init__(self, **kw):
        super().__init__(**kw)
        self.apply_shape()
        self.cfg.setdefault("hide", False)
        self.rows = {}
        self.clear_rect = None
        self.copied = 0.0
        History.start()
        History.listeners.append(self.update)
        self.timer = QTimer(self, interval=30 * 1000, timeout=self.update)  # «2 мин» в подписях
        self.timer.start()

    def closeEvent(self, event):
        if self.update in History.listeners:
            History.listeners.remove(self.update)
        super().closeEvent(event)

    def add_actions(self, menu):
        a = menu.addAction(tr("Скрывать текст"), self.toggle_hide)
        a.setCheckable(True)
        a.setChecked(bool(self.cfg["hide"]))
        menu.addAction(tr("Очистить"), self.clear)

    def toggle_hide(self):
        self.cfg["hide"] = not self.cfg["hide"]
        config.save()
        self.update()

    def clear(self):
        History.items = []
        self.update()

    def click(self, pos):
        if self.clear_rect is not None and self.clear_rect.contains(pos):
            self.clear()
            return True
        for value, rect in self.rows.items():
            if rect.contains(pos):
                QApplication.clipboard().setText(value)
                self.copied = time.time()
                self.update()
                QTimer.singleShot(1600, self.update)
                return True
        return False

    def paintEvent(self, event):
        super().paintEvent(event)  # стекло
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        r = QRectF(self.card())
        fg, dim, track = kit.ink(self)
        dark = bool(self.dark)
        now = time.time()
        items = History.items
        if now - self.copied < 1.5:
            cw = kit.chip(p, r, tr("скопировано"), kit.GREEN, dark)
        else:
            cw = kit.chip(p, r, tr("только в памяти"), kit.GRAY, dark)
        x, w = r.left() + 18, r.width() - 36
        kit.text(p, QRectF(x, r.top() + 14, w - cw, 22), tr("Буфер"), fg, 16, "Segoe UI Semibold")
        self.rows = {}
        step = 27
        room = int((r.bottom() - 12 - (r.top() + 44)) // step)
        for i, (value, when) in enumerate(items[:room]):
            rect = QRectF(x - 6, r.top() + 44 + i * step, w + 12, step - 3)
            self.rows[value] = rect
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 16 if dark else 90))
            p.drawRoundedRect(rect, 9, 9)
            line = " ".join(value.split())
            if self.cfg["hide"]:
                line = "•" * min(14, len(line)) + "  " + tr("{} симв.").format(len(value))
            when_text = ago(now - when)
            kit.text(p, rect.adjusted(10, 0, -58, 0), line, fg, 12, elide=True)
            kit.text(p, rect.adjusted(0, 0, -10, 0), when_text, dim, 11, align=Qt.AlignRight | Qt.AlignVCenter)
        if not items:
            kit.text(p, QRectF(x, r.top() + 50, w, 44), tr("Скопируй текст — он появится здесь.\nНа диск не сохраняется."), dim, 12,
                     align=Qt.AlignLeft | Qt.AlignTop)
