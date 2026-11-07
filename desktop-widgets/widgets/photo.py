"""Фоторамка: одно фото или папка-слайдшоу (смена раз в минуту). Файлы только читаются — те, что выбрал сам."""
from lang import tr
import os

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QFont, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFileDialog, QMenu

import icons
from core import DesktopWidget, RADIUS, SHADOW, config, grid, open_uri

EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif")


class PhotoWidget(DesktopWidget):
    key = "photo"
    title = tr("Фото")
    description = tr("Фото или папка-слайдшоу")

    def __init__(self, **kw):
        super().__init__(**kw)
        self.setFixedSize(*(v + 2 * SHADOW for v in grid(2, 1)))
        self.index = 0
        self.cache = (None, None)  # (путь, картинка под размер карточки)
        self.timer = QTimer(self, interval=60 * 1000, timeout=self.next_photo)
        self.timer.start()
        self.setAcceptDrops(True)

    # ---------- что показывать ----------

    def add_actions(self, menu):
        menu.addAction(tr("Выбрать фото…"), self.pick_file)
        menu.addAction(tr("Выбрать папку (слайдшоу)…"), self.pick_folder)
        if self.cfg.get("folder"):
            menu.addAction(tr("Следующее фото"), self.next_photo)

    def ask(self):
        """Что показывать — меню у курсора: фото или папка. Само всплывает, когда «Фото» включают без фото."""
        menu = QMenu()
        menu.addAction(tr("Выбрать фото…"), self.pick_file)
        menu.addAction(tr("Выбрать папку (слайдшоу)…"), self.pick_folder)
        menu.exec(QCursor.pos())

    def first_setup(self):
        if not self.photos():
            QTimer.singleShot(150, self.ask)

    # диалоги без родителя: под ярлыками окно виджета скрыто
    def pick_file(self):
        path, _ = QFileDialog.getOpenFileName(None, tr("Фото"), self.cfg.get("file", ""),
                                              tr("Картинки (*.jpg *.jpeg *.png *.webp *.bmp *.gif)"))
        if path:
            self.set_file(path)

    def pick_folder(self):
        path = QFileDialog.getExistingDirectory(None, tr("Папка с фото"), self.cfg.get("folder", ""))
        if path:
            self.set_folder(path)

    def set_file(self, path):
        self.cfg.pop("folder", None)
        self.cfg["file"] = path
        config.save()
        self.update()

    def set_folder(self, path):
        self.cfg.pop("file", None)
        self.cfg["folder"] = path
        self.index = 0
        config.save()
        self.update()

    # перетащить картинку или папку из Проводника прямо на виджет
    def dragEnterEvent(self, event):
        if self._dropped(event):
            event.acceptProposedAction()

    def dropEvent(self, event):
        path = self._dropped(event)
        if path:
            self.set_folder(path) if os.path.isdir(path) else self.set_file(path)
            event.acceptProposedAction()

    @staticmethod
    def _dropped(event):
        urls = event.mimeData().urls()
        path = urls[0].toLocalFile() if urls else ""
        return path if os.path.isdir(path) or path.lower().endswith(EXTS) else None

    def photos(self):
        folder = self.cfg.get("folder")
        if folder and os.path.isdir(folder):
            return sorted(os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(EXTS))
        file = self.cfg.get("file")
        return [file] if file and os.path.isfile(file) else []

    def click(self, pos):
        if not self.photos():  # пустая рамка — выбрать, что показывать
            self.ask()
            return True
        if self.cfg.get("folder"):  # слайдшоу — следующее фото
            self.next_photo()
            return True
        return False

    def double_click(self):
        items = self.photos()
        if items:
            open_uri(items[self.index % len(items)])  # открыть фото в просмотрщике

    def next_photo(self):
        if self.cfg.get("folder"):
            self.index += 1
            self.update()

    def current(self, w, h):
        """Текущее фото, обрезанное и уменьшенное ровно под карточку (кэш)."""
        items = self.photos()
        if not items:
            return None
        path = items[self.index % len(items)]
        if self.cache[0] != (path, w, h):
            img = QImage(path)
            if img.isNull():
                return None
            img = img.scaled(w * 2, h * 2, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            img = img.copy((img.width() - w * 2) // 2, (img.height() - h * 2) // 2, w * 2, h * 2)
            img.setDevicePixelRatio(2)
            self.cache = ((path, w, h), img)
        return self.cache[1]

    # ---------- рисование ----------

    def paintEvent(self, event):
        super().paintEvent(event)  # стекло
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        r = QRectF(self.card())
        img = self.current(int(r.width()), int(r.height()))
        dark = bool(self.dark)
        if img is None:  # фото ещё не выбрано
            pic = icons.app_icon("photo", 48)
            p.drawPixmap(QPointF(r.center().x() - 24, r.center().y() - 54), pic)
            f = QFont("Segoe UI")
            f.setPixelSize(12)
            p.setFont(f)
            p.setPen(QColor("#d8dae2") if dark else QColor("#565a6b"))
            p.drawText(r.adjusted(16, r.height() / 2 + 8, -16, -12), Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap,
                       tr("Под ярлыками: «Двигать виджеты», потом нажми сюда") if self.pinned else
                       tr("Нажми — выбрать фото или папку\nили перетащи сюда картинку"))
            return
        path = QPainterPath()
        path.addRoundedRect(r, RADIUS, RADIUS)
        p.setClipPath(path)
        p.drawImage(r, img)
        p.setClipping(False)
        # тонкая светлая кромка поверх фото — как у стекла
        p.setPen(QPen(QColor(255, 255, 255, 110), 1.2))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r.adjusted(0.6, 0.6, -0.6, -0.6), RADIUS, RADIUS)
