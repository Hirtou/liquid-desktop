"""Фоторамка: одно фото, несколько своих фото или папка-слайдшоу. Несколько — сменяются сами (интервал в меню)
с плавным переходом, короткий клик — следующее. Файлы только читаются — те, что выбрал сам."""
from lang import tr
import os
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QCursor, QFont, QImage, QPainter, QImageReader, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QFileDialog, QMenu

import icons
from core import DesktopWidget, RADIUS, SHADOW, activity, config, grid, open_uri
from widgets.gif import GifEditor, draw_add, fit_rect

EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif")
MAX_FILES = 50
EVERY = [(10, tr("10 секунд")), (30, tr("30 секунд")), (60, tr("1 минута")), (300, tr("5 минут")),
         (1800, tr("30 минут"))]
FADE = 0.45  # плавная смена фото, с
# размер по сетке (ширина × высота, ячеек) — по очереди, от маленького к большому; по умолчанию 2 × 1
SIZES = [(1, 1), (2, 1), (1, 2), (2, 2), (3, 1), (3, 2), (4, 1), (4, 2), (2, 3), (3, 3), (4, 3)]
SLIDE = 0.28  # свайп: досъезд фото после того, как отпустили, с
FLIP = [("click", tr("Кликом")), ("swipe", tr("Свайпом влево-вправо"))]


class PhotoWidget(DesktopWidget):
    key = "photo"
    title = tr("Фото")
    description = tr("Одно или несколько фото, папка-слайдшоу")

    def __init__(self, **kw):
        super().__init__(**kw)
        self.apply_size()
        self.index = 0
        self.cache = {}  # (путь, w, h) -> картинка под размер карточки (текущая и прошлая — для перехода)
        self.fade_from, self.fade_start = None, 0.0
        self.timer = QTimer(self, timeout=self.auto_next)
        self.fade_timer = QTimer(self, interval=16, timeout=self.update)
        self.slide = 0.0  # свайп: насколько сдвинуто фото, px (минус — влево, к следующему)
        self.slide_anim = None  # (откуда, куда, начало, шаг по фото после) — досъезд после свайпа
        self.slide_timer = QTimer(self, interval=16, timeout=self.slide_tick)
        self.editor = None
        self.full = (None, None)        # (путь, фото целиком) — последнее загруженное
        self.full_pix = (None, None)    # (путь, уменьшенное — для окошка редактора)
        self.save_timer = QTimer(self, singleShot=True, interval=300, timeout=config.save)
        self.apply_every()
        self.setAcceptDrops(True)

    # ---------- размер по сетке ----------

    def cells(self):
        c, r = self.cfg.get("cols", 2), self.cfg.get("rows", 1)
        return (c, r) if (c, r) in SIZES else (2, 1)

    def apply_size(self):
        self.setFixedSize(*(v + 2 * SHADOW for v in grid(*self.cells())))

    def set_cells(self, cols, rows):
        self.cfg["cols"], self.cfg["rows"] = cols, rows
        self.refit()
        config.save()
        self.apply_size()
        self.cache.clear()  # фото обрезаются ровно под карточку — под новый размер заново
        self.fade_from = None
        self.flat_key = None
        self.last_src = None
        if self.pinned:
            self.push()
        self.keep_on_screen()
        if self.editor is not None:  # поменяли из меню при открытом редакторе — и там тоже
            self.editor.size.blockSignals(True)
            self.editor.size.setCurrentIndex(SIZES.index((cols, rows)))
            self.editor.size.blockSignals(False)
            self.editor.view.update()
        self.update()

    # ---------- обрезка: у каждого фото своя рамка, cfg["rects"][путь] = [x, y, ширина, высота] в долях ----------

    def aspect(self):
        w, h = grid(*self.cells())
        return w / h

    def path_now(self):
        items = self.photos()
        return items[self.index % len(items)] if items else None

    FULL_MAX = 2560  # фото больше — читаем сразу уменьшенным: 3840×3840 — это 56 МБ в памяти и долгая распаковка

    def full_image(self, path):
        """Фото целиком (не больше FULL_MAX по длинной стороне) — для обрезки и редактора. Держим только пока нужно:
        уменьшенная под карточку копия готова и редактор закрыт — отпускаем (см. current)."""
        if self.full[0] != path:
            reader = QImageReader(path)
            size = reader.size()
            if size.isValid() and max(size.width(), size.height()) > self.FULL_MAX:
                k = self.FULL_MAX / max(size.width(), size.height())
                reader.setScaledSize(QSize(max(1, round(size.width() * k)), max(1, round(size.height() * k))))
            img = reader.read()
            self.full = (path, None if img.isNull() else img)
        return self.full[1]

    def crop_for(self, path, W, H):
        rects = self.cfg.get("rects") if isinstance(self.cfg.get("rects"), dict) else {}
        raw = rects.get(path)
        ok = isinstance(raw, list) and len(raw) == 4 and all(isinstance(v, (int, float)) for v in raw)
        if ok and raw[2] > 0.01 and raw[3] > 0.01 and raw[0] >= 0 and raw[1] >= 0 \
                and raw[0] + raw[2] <= 1.001 and raw[1] + raw[3] <= 1.001:
            return [float(v) for v in raw]
        return fit_rect(W, H, self.aspect())  # не задана — как раньше: всё фото по центру

    # для редактора (тот же, что у гифок)
    EDITOR_TITLE = tr("Редактор фото")
    EDITOR_PICK = tr("Выбрать фото…")

    def frame_size(self):
        path = self.path_now()
        img = self.full_image(path) if path else None
        return (img.width(), img.height()) if img is not None else (0, 0)

    def crop(self):
        W, H = self.frame_size()
        return self.crop_for(self.path_now(), W, H) if W and H else [0.0, 0.0, 1.0, 1.0]

    def editor_pixmap(self):
        path = self.path_now()
        if not path:
            return None
        if self.full_pix[0] != path:
            img = self.full_image(path)
            pix = None
            if img is not None:
                pix = QPixmap.fromImage(img.scaled(1200, 1200, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                                        if max(img.width(), img.height()) > 1200 else img)
            self.full_pix = (path, pix)
        return self.full_pix[1]

    def set_crop(self, rect):
        path = self.path_now()
        if not path:
            return
        rects = self.cfg.get("rects") if isinstance(self.cfg.get("rects"), dict) else {}
        rects[path] = rect
        self.cfg["rects"] = rects
        self.save_timer.start()
        self.photo_changed()

    def reset_crop(self):
        rects = self.cfg.get("rects")
        if isinstance(rects, dict):
            rects.pop(self.path_now(), None)
        config.save()
        self.photo_changed()

    def photo_changed(self):
        self.cache.clear()
        self.fade_from = None
        if self.pinned:
            self.push()
        self.update()

    def changed(self):  # редактор зовёт после своих настроек
        self.photo_changed()

    def editor_items(self):
        items = self.photos()
        return (self.index % len(items) if items else 0), len(items)

    def editor_step(self, step):
        items = self.photos()
        if len(items) > 1:
            self.index = (self.index + step) % len(items)
            self.timer.start()
            self.photo_changed()

    def pick(self):
        self.pick_files()
        return bool(self.photos())

    def edit(self):
        if not self.photos():
            self.ask()
            return
        if self.editor is None:
            self.editor = GifEditor(self)
            self.editor.finished.connect(self._editor_closed)
            self.editor.show()
        self.editor.raise_()
        self.editor.activateWindow()

    def _editor_closed(self, *_):
        if self.editor is not None:
            self.editor.deleteLater()
            self.editor = None
        self.full = self.full_pix = (None, None)  # фото целиком нужно было только редактору
        config.save()

    def closeEvent(self, event):
        if self.editor is not None:
            self.editor.close()
        super().closeEvent(event)

    def refit(self):
        """Размер карточки поменяли — рамки фото под новые пропорции: там же и примерно того же охвата."""
        rects = self.cfg.get("rects")
        if not isinstance(rects, dict):
            return
        for path in list(rects):
            size = QImageReader(path).size()
            if not size.isValid() or not size.width() or not size.height():
                rects.pop(path)
                continue
            x, y, w, h = self.crop_for(path, size.width(), size.height())
            rects[path] = fit_rect(size.width(), size.height(), self.aspect(), x + w / 2, y + h / 2, max(w, h))

    def add_sizes(self, menu):
        sub = menu.addMenu(tr("Размер по сетке"))
        for c, r in SIZES:
            a = sub.addAction(f"{c} × {r}", lambda c=c, r=r: self.set_cells(c, r))
            a.setCheckable(True)
            a.setChecked((c, r) == self.cells())

    # ---------- что показывать ----------

    @staticmethod
    def summary(cfg):
        """Что в рамке — для карточки в каталоге: «3 фото», «Папка «Обои» · 25 фото»."""
        folder = cfg.get("folder")
        if isinstance(folder, str) and folder:
            try:
                n = sum(1 for f in os.listdir(folder) if f.lower().endswith(EXTS))
            except OSError:
                n = 0
            return tr("Папка «{}» · {} фото").format(os.path.basename(folder.rstrip("\\/")) or folder, n)
        files = cfg.get("files")
        if not isinstance(files, list):
            files = [cfg["file"]] if isinstance(cfg.get("file"), str) else []
        return tr("{} фото").format(len(files)) if files else tr("Фото не выбраны")

    def every(self):
        v = self.cfg.get("every", 60)
        return v if v in [s for s, _ in EVERY] else 60

    def apply_every(self):
        self.timer.setInterval(self.every() * 1000)
        self.timer.start()

    def set_every(self, seconds):
        self.cfg["every"] = seconds
        config.save()
        self.apply_every()

    def flip(self):
        return "swipe" if self.cfg.get("flip") == "swipe" else "click"

    def set_flip(self, name):
        self.cfg["flip"] = name
        config.save()

    def add_actions(self, menu):
        self.add_sizes(menu)
        if self.photos():
            menu.addAction(tr("Редактор фото…"), self.edit)
            menu.addAction(tr("Открыть фото"), self.open_photo)
        menu.addAction(tr("Выбрать фото…"), self.pick_files)
        if self.cfg.get("files") or self.cfg.get("file"):
            menu.addAction(tr("Добавить фото…"), self.add_files)
        menu.addAction(tr("Выбрать папку (слайдшоу)…"), self.pick_folder)
        if len(self.photos()) > 1:
            menu.addAction(tr("Следующее фото"), self.next_photo)
            if not self.cfg.get("folder"):
                menu.addAction(tr("Убрать это фото"), self.remove_current)
            sub = menu.addMenu(tr("Менять каждые"))
            for seconds, text in EVERY:
                a = sub.addAction(text, lambda s=seconds: self.set_every(s))
                a.setCheckable(True)
                a.setChecked(seconds == self.every())
            sub = menu.addMenu(tr("Листать"))
            for name, text in FLIP:
                a = sub.addAction(text, lambda n=name: self.set_flip(n))
                a.setCheckable(True)
                a.setChecked(name == self.flip())
        if activity.copies:
            menu.addAction(tr("Ещё одна фоторамка"), lambda: activity.copies.add_copy(self.copy_of or self.key, self))

    def ask(self):
        """Что показывать — меню у курсора: фото или папка. Само всплывает, когда «Фото» включают без фото."""
        menu = QMenu()
        menu.addAction(tr("Выбрать фото…"), self.pick_files)
        menu.addAction(tr("Выбрать папку (слайдшоу)…"), self.pick_folder)
        menu.exec(QCursor.pos())

    # диалоги без родителя: под ярлыками окно виджета скрыто
    def _ask_files(self):
        start = (self.own_files() or [""])[-1]
        paths, _ = QFileDialog.getOpenFileNames(None, tr("Фото (можно несколько)"), start,
                                                tr("Картинки (*.jpg *.jpeg *.png *.webp *.bmp *.gif)"))
        return paths

    def pick_files(self):
        paths = self._ask_files()
        if paths:
            self.set_files(paths)

    def add_files(self):
        paths = self._ask_files()
        if paths:
            have = self.own_files()
            self.set_files(have + [p for p in paths if p not in have], show=len(have))

    def pick_folder(self):
        path = QFileDialog.getExistingDirectory(None, tr("Папка с фото"), self.cfg.get("folder", ""))
        if path:
            self.set_folder(path)

    def own_files(self):
        """Свои выбранные фото (не папка). Старые настройки — одно «file»."""
        files = self.cfg.get("files")
        if isinstance(files, list):
            return [f for f in files if isinstance(f, str)]
        return [self.cfg["file"]] if isinstance(self.cfg.get("file"), str) else []

    def set_files(self, paths, show=0):
        paths = list(dict.fromkeys(paths))[:MAX_FILES]
        self.cfg.pop("folder", None)
        self.cfg.pop("file", None)
        self.cfg["files"] = paths
        config.save()
        self.go(show)

    def set_file(self, path):  # одно фото (перетащили одну картинку)
        self.set_files([path])

    def set_folder(self, path):
        self.cfg.pop("file", None)
        self.cfg.pop("files", None)
        self.cfg["folder"] = path
        config.save()
        self.go(0)

    def remove_current(self):
        files = self.own_files()
        items = self.photos()
        if len(items) < 2 or self.cfg.get("folder"):
            return
        gone = items[self.index % len(items)]
        files = [f for f in files if f != gone]
        self.set_files(files, show=self.index % max(1, len(files)))

    # перетащить картинки или папку из Проводника прямо на виджет
    def dragEnterEvent(self, event):
        if self._dropped(event):
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = self._dropped(event)
        if paths:
            if len(paths) == 1 and os.path.isdir(paths[0]):
                self.set_folder(paths[0])
            else:
                files = [p for p in paths if os.path.isfile(p)]
                # с Ctrl — добавить к тем, что уже есть
                if event.modifiers() & Qt.ControlModifier and self.own_files() and not self.cfg.get("folder"):
                    have = self.own_files()
                    self.set_files(have + [p for p in files if p not in have], show=len(have))
                else:
                    self.set_files(files)
            event.acceptProposedAction()

    @staticmethod
    def _dropped(event):
        paths = [u.toLocalFile() for u in event.mimeData().urls()]
        if len(paths) == 1 and os.path.isdir(paths[0]):
            return paths
        paths = [p for p in paths if p.lower().endswith(EXTS)]
        return paths or None

    def photos(self):
        folder = self.cfg.get("folder")
        if folder and os.path.isdir(folder):
            return sorted(os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(EXTS))
        return [f for f in self.own_files() if os.path.isfile(f)]

    def click(self, pos):
        return False  # тащить можно всегда (и пустой); короткое нажатие — tap

    def tap(self, pos):
        if not self.photos():  # пустой виджет — кнопка «Добавить фото» (папка — в меню)
            QTimer.singleShot(0, self.pick_files)
            return
        if len(self.photos()) > 1 and self.flip() == "click":
            self.next_photo()

    # ---------- свайп ----------

    def swiping(self):
        return self.flip() == "swipe" and len(self.photos()) > 1

    def swipe_move(self, dx):
        self.slide_timer.stop()
        self.slide_anim = None
        self.fade_from = None
        self.slide = float(dx) / self.scale()
        self.update()

    def swipe_end(self, dx):
        w = self.card().width()
        dx = float(dx) / self.scale()
        if abs(dx) > min(60.0, w * 0.18):  # дотянули — листаем: влево — следующее, вправо — прошлое
            step = 1 if dx < 0 else -1
            self.slide_anim = (dx, -step * w, time.monotonic(), step)
        else:  # мало — фото возвращается на место
            self.slide_anim = (dx, 0.0, time.monotonic(), 0)
        self.slide_timer.start()

    def slide_tick(self):
        if self.slide_anim is None:
            self.slide_timer.stop()
            return
        a, b, start, step = self.slide_anim
        t = min(1.0, (time.monotonic() - start) / SLIDE)
        k = 1 - (1 - t) ** 3  # быстро, с мягкой остановкой
        self.slide = a + (b - a) * k
        if t >= 1.0:
            self.slide_anim = None
            self.slide_timer.stop()
            self.slide = 0.0
            if step:
                self.index += step
                self.timer.start()  # листнули рукой — отсчёт заново
                if self.pinned:
                    self.push()
        self.update()

    def open_photo(self):
        items = self.photos()
        if items:
            open_uri(items[self.index % len(items)])

    def auto_next(self):
        if self.editor is None and not activity.covered(self):  # в редакторе фото не листаем  # закрыт окном или игрой — смотреть некому
            self.next_photo()

    def next_photo(self):
        if len(self.photos()) > 1:
            self.go(self.index + 1)
            self.timer.start()  # отсчёт заново: только что листнули рукой

    def go(self, index):
        """Показать фото номер index — с плавным переходом от того, что было."""
        r = self.card()
        old = self.current(r.width(), r.height())
        self.index = index
        new = self.current(r.width(), r.height())
        if old is not None and new is not None and old is not new and self.isVisible():
            self.fade_from, self.fade_start = old, time.monotonic()
            self.fade_timer.start()
        if self.pinned:
            self.push()
        self.update()

    def current(self, w, h, index=None):
        """Текущее фото (или номер index), обрезанное и уменьшенное ровно под карточку
        (кэш на три фото: текущее, прошлое и соседнее — при свайпе)."""
        items = self.photos()
        if not items:
            return None
        path = items[(self.index if index is None else index) % len(items)]
        rects = self.cfg.get("rects") if isinstance(self.cfg.get("rects"), dict) else {}
        key = (path, w, h, str(rects.get(path)))
        if key not in self.cache:
            full = self.full_image(path)
            if full is None:
                return None
            x, y, fw, fh = self.crop_for(path, full.width(), full.height())
            src = QRectF(full.width() * x, full.height() * y, max(1.0, full.width() * fw), max(1.0, full.height() * fh))
            want, have = w / max(1, h), src.width() / src.height()
            if have > want:  # рамка чуть шире карточки — подрезать по бокам (и наоборот)
                nw = src.height() * want
                src = QRectF(src.center().x() - nw / 2, src.top(), nw, src.height())
            else:
                nh = src.width() / want
                src = QRectF(src.left(), src.center().y() - nh / 2, src.width(), nh)
            img = full.copy(src.toRect()).scaled(w * 2, h * 2, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            img.setDevicePixelRatio(2)
            while len(self.cache) >= 3:
                self.cache.pop(next(iter(self.cache)))
            self.cache[key] = img
            if self.editor is None:
                self.full = (None, None)  # большое фото больше не нужно — в памяти только картинка под карточку
        return self.cache[key]

    # ---------- рисование ----------

    def paintEvent(self, event):
        super().paintEvent(event)  # стекло
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        r = QRectF(self.card())
        img = self.current(int(r.width()), int(r.height()))
        dark = bool(self.dark)
        if img is None:  # фото ещё не выбрано — кнопка «Добавить фото» прямо на виджете
            draw_add(p, r, dark, tr("Добавить фото"),
                     tr("Под ярлыками: сначала «Двигать виджеты»") if self.pinned else tr("или перетащи сюда"))
            return
        path = QPainterPath()
        path.addRoundedRect(r, RADIUS, RADIUS)
        p.setClipPath(path)
        t = (time.monotonic() - self.fade_start) / FADE if self.fade_from is not None else 1.0
        if self.slide:  # свайп: фото едет за мышью, рядом въезжает соседнее
            side = 1 if self.slide < 0 else -1
            other = self.current(int(r.width()), int(r.height()), self.index + side)
            p.drawImage(r.translated(self.slide, 0), img)
            if other is not None:
                p.drawImage(r.translated(self.slide + side * (r.width() + 12), 0), other)
        elif t < 1.0:
            k = t * t * (3 - 2 * t)  # мягкий старт и конец
            p.drawImage(r, self.fade_from)
            p.setOpacity(k)
            p.drawImage(r, img)
            p.setOpacity(1.0)
        else:
            if self.fade_from is not None:
                self.fade_from = None
                self.fade_timer.stop()
            p.drawImage(r, img)
        p.setClipping(False)
        # точки — сколько фото и какое сейчас (если их несколько)
        n = len(self.photos())
        if 1 < n <= 12:
            d, gap = 6.0, 6.0
            x = r.center().x() - (n * d + (n - 1) * gap) / 2
            y = r.bottom() - 14
            p.setPen(QPen(QColor(0, 0, 0, 70), 1.0))  # тонкая тень — точки видно и на светлом фото
            for i in range(n):
                on = i == self.index % n
                p.setBrush(QColor(255, 255, 255, 235 if on else 110))
                p.drawEllipse(QRectF(x + i * (d + gap), y, d, d))
        # тонкая светлая кромка поверх фото — как у стекла
        p.setPen(QPen(QColor(255, 255, 255, 110), 1.2))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r.adjusted(0.6, 0.6, -0.6, -0.6), RADIUS, RADIUS)
