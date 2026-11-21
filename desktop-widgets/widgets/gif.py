"""Гифка на рабочем столе: своя анимация (GIF или анимированный WebP) в карточке любого размера по сетке.
Редактор (правый клик → «Редактор гифки…»): размер в ячейках (1×1 … 4×3), скорость и рамка обрезки,
как в редакторе фото на телефоне: тянешь за углы — меняешь размер рамки, за середину — двигаешь; что в рамке, то и на
виджете. Всё видно сразу. Файл только читается; закрытый окном виджет гифку не крутит."""
from lang import LANG, tr
import os
import sys
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QMovie, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QSlider, QVBoxLayout, QWidget)

import icons
import skins
from core import DesktopWidget, RADIUS, SHADOW, activity, config, grid

EXTS = (".gif", ".webp")
SIZES = [(1, 1), (2, 1), (1, 2), (2, 2), (3, 1), (3, 2), (4, 1), (4, 2), (2, 3), (3, 3), (4, 3)]  # ширина × высота, ячеек
MIN_PART = 0.12  # рамка обрезки не меньше 12% ширины кадра — иначе за углы уже не ухватить
MAX_FILES = 30
EVERY = [(10, tr("10 секунд")), (30, tr("30 секунд")), (60, tr("1 минута")), (300, tr("5 минут")),
         (1800, tr("30 минут"))]
FLIP = [("click", tr("Кликом")), ("swipe", tr("Свайпом влево-вправо"))]
SLIDE = 0.22  # свайп: гифка уезжает за край и въезжает следующая, с


def draw_add(p, r, dark, title, hint):
    """Пустой виджет (фото / гифка ещё не выбраны): по центру — круглый «+» цвета акцента и «Добавить …»,
    ниже серым — подсказка. Нажатие по виджету открывает выбор файлов."""
    small = min(r.width(), r.height()) < 200
    rad = 20 if small else 24
    c = QPointF(r.center().x(), r.center().y() - (16 if small else 24))
    accent = QColor(skins.ACCENT)
    glow = QColor(accent)
    glow.setAlpha(45)
    p.setPen(Qt.NoPen)
    p.setBrush(glow)
    p.drawEllipse(c, rad + 7, rad + 7)
    p.setBrush(accent)
    p.drawEllipse(c, rad, rad)
    k = rad * 0.38
    p.setPen(QPen(QColor("white"), 2.6, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(c + QPointF(-k, 0), c + QPointF(k, 0))
    p.drawLine(c + QPointF(0, -k), c + QPointF(0, k))
    f = QFont("Segoe UI")
    f.setPixelSize(14)
    f.setWeight(QFont.DemiBold)
    p.setFont(f)
    p.setPen(QColor("#f5f6fb") if dark else QColor("#1b1c22"))
    top = c.y() + rad + 10
    p.drawText(QRectF(r.left() + 8, top, r.width() - 16, 20), Qt.AlignCenter, title)
    if hint and r.bottom() - (top + 22) >= 16:
        f.setPixelSize(11)
        f.setWeight(QFont.Normal)
        p.setFont(f)
        p.setPen(QColor("#b6bbcd") if dark else QColor("#565a6b"))
        p.drawText(QRectF(r.left() + 14, top + 22, r.width() - 28, r.bottom() - top - 26),
                   Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap, hint)


def fit_rect(W, H, aspect, cx=0.5, cy=0.5, part=1.0):
    """Рамка обрезки нужных пропорций (aspect = ширина / высота карточки) внутри кадра W×H, в долях кадра
    (x, y, w, h): самая большая, какая влезает, умноженная на part, с центром как можно ближе к (cx, cy)."""
    w = min(W, H * aspect) * max(MIN_PART, min(1.0, part))
    h = w / aspect
    fw, fh = w / W, h / H
    x = max(0.0, min(1 - fw, cx - fw / 2))
    y = max(0.0, min(1 - fh, cy - fh / 2))
    return [x, y, fw, fh]


def draw_gif(p, rect, pix, crop, radius):
    """Кадр в прямоугольник: берём кусок кадра из рамки обрезки (crop — x, y, ширина, высота в долях кадра),
    вписываем с заполнением (рамка тех же пропорций, что карточка, так что обычно ничего не теряется),
    скругляем углы, сверху тонкая светлая кромка."""
    w, h = pix.width(), pix.height()
    fx, fy, fw, fh = crop
    src = QRectF(w * fx, h * fy, max(1.0, w * fw), max(1.0, h * fh))
    want, have = rect.width() / max(1.0, rect.height()), src.width() / src.height()
    if have > want:
        nw = src.height() * want
        src = QRectF(src.center().x() - nw / 2, src.top(), nw, src.height())
    else:
        nh = src.width() / want
        src = QRectF(src.left(), src.center().y() - nh / 2, src.width(), nh)
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    p.save()
    p.setClipPath(path)
    p.drawPixmap(rect, pix, src)
    p.restore()
    p.setPen(QPen(QColor(255, 255, 255, 110), 1.2))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(rect.adjusted(0.6, 0.6, -0.6, -0.6), radius, radius)


class GifWidget(DesktopWidget):
    key = "gif"
    title = tr("Гифка")
    description = tr("Своя гифка: размер, скорость, обрезка")

    def __init__(self, **kw):
        super().__init__(**kw)
        self.movie = None
        self.path = None
        self.editor = None
        self.apply_size()
        self.setAcceptDrops(True)
        self.save_timer = QTimer(self, singleShot=True, interval=300, timeout=config.save)
        self.watch = QTimer(self, interval=500, timeout=self.sync)  # закрыт окном или игрой — гифку не крутим
        self.watch.start()
        self.turn = QTimer(self, timeout=self.auto_next)  # несколько гифок — сменяются сами
        self.slide = 0.0  # свайп: сдвиг гифки, px
        self.slide_anim = None  # (откуда, куда, начало, шаг по списку в конце)
        self.slide_timer = QTimer(self, interval=16, timeout=self.slide_tick)
        self.apply_every()
        self.load()

    @staticmethod
    def summary(cfg):
        """Сколько гифок — для карточки в каталоге."""
        files = cfg.get("files")
        if not isinstance(files, list) or not files:
            files = [cfg["file"]] if isinstance(cfg.get("file"), str) else []
        n = len(files)
        if not n:
            return tr("Гифки не выбраны")
        if LANG == "en":
            return f"{n} GIF" + ("" if n == 1 else "s")
        if n % 10 == 1 and n % 100 != 11:
            word = "гифка"
        elif 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
            word = "гифки"
        else:
            word = "гифок"
        return f"{n} {word}"

    # ---------- настройки ----------

    def cells(self):
        c, r = self.cfg.get("cols", 2), self.cfg.get("rows", 2)
        return (c, r) if (c, r) in SIZES else (2, 2)

    def aspect(self):
        w, h = grid(*self.cells())
        return w / h

    def frame_size(self):
        pix = self.movie.currentPixmap() if self.movie is not None else None
        return (pix.width(), pix.height()) if pix is not None and not pix.isNull() else (0, 0)

    def crop(self):
        """Рамка обрезки в долях кадра (x, y, ширина, высота). Не задана или испорчена — весь кадр по центру."""
        raw = self.cfg.get("rect")
        ok = isinstance(raw, list) and len(raw) == 4 and all(isinstance(v, (int, float)) for v in raw)
        if ok and raw[2] > 0.01 and raw[3] > 0.01 and raw[0] >= 0 and raw[1] >= 0 \
                and raw[0] + raw[2] <= 1.001 and raw[1] + raw[3] <= 1.001:
            return [float(v) for v in raw]
        W, H = self.frame_size()
        return fit_rect(W, H, self.aspect()) if W and H else [0.0, 0.0, 1.0, 1.0]

    def refit(self):
        """Размер карточки поменяли — рамку под новые пропорции: там же и примерно того же охвата."""
        W, H = self.frame_size()
        if not (W and H):
            self.cfg.pop("rect", None)
            return
        x, y, w, h = self.crop()
        self.cfg["rect"] = fit_rect(W, H, self.aspect(), x + w / 2, y + h / 2, max(w, h))

    def speed(self):
        return max(25, min(300, int(self.cfg.get("speed", 100))))

    def apply_size(self):
        w, h = grid(*self.cells())
        self.setFixedSize(w + 2 * SHADOW, h + 2 * SHADOW)

    # ---------- для редактора (общий с «Фото»: CropView и GifEditor спрашивают это) ----------
    EDITOR_TITLE = tr("Редактор гифки")
    EDITOR_PICK = tr("Выбрать гифку…")

    def editor_pixmap(self):
        return self.movie.currentPixmap() if self.movie is not None else None

    def set_crop(self, rect):
        self.cfg["rect"] = rect
        self.changed()

    def reset_crop(self):
        self.cfg.pop("rect", None)  # рамка — снова весь кадр
        self.changed()

    def editor_items(self):
        """(номер текущей, сколько всего) — для «‹ 2 из 3 ›» в редакторе."""
        files = [f for f in self.files() if os.path.isfile(f)]
        cur = self.cfg.get("file")
        return (files.index(cur) if cur in files else 0), len(files)

    def editor_step(self, step):
        self.next_gif(step)

    def changed(self):
        """Настройку поменяли (в редакторе — ползунком, много раз подряд): показать сразу, сохранить чуть погодя."""
        if self.movie:
            self.movie.setSpeed(self.speed())
        self.save_timer.start()
        self.update()

    def set_cells(self, cols, rows):
        self.cfg["cols"], self.cfg["rows"] = cols, rows
        self.refit()
        self.apply_size()
        self.flat_key = None
        self.last_src = None
        if self.pinned:
            self.push()
        self.keep_on_screen()
        if self.editor is not None:  # поменяли из меню при открытом редакторе — и там тоже
            self.editor.size.blockSignals(True)
            self.editor.size.setCurrentIndex(SIZES.index((cols, rows)))
            self.editor.size.blockSignals(False)
        self.changed()

    # ---------- гифка ----------

    def load(self):
        path = self.cfg.get("file")
        if self.movie is not None:
            self.movie.stop()
            self.movie.deleteLater()
            self.movie = None
        self.path = path
        if path and os.path.isfile(path):
            movie = QMovie(path)
            movie.setParent(self)
            if movie.isValid():
                movie.setSpeed(self.speed())
                movie.frameChanged.connect(self.on_frame)
                movie.finished.connect(movie.start)  # гифка с конечным числом повторов — крутим по кругу
                self.movie = movie
                movie.start()
            else:
                movie.deleteLater()
        self.update()

    def on_frame(self, _=0):
        self.last_frame = time.monotonic()
        if self.isVisible():
            self.update()

    def sync(self):
        if self.cfg.get("file") != self.path:  # файл поменяли в другом месте (превью в каталоге, редактор)
            self.load()
        movie = self.movie
        if movie is None:
            return
        now = time.monotonic()
        # редактор открыт — гифка идёт, даже если его окно закрыло виджет
        if self.editor is None and activity.covered(self):
            movie.setPaused(True)
            self.last_frame = now
            return
        # Должна идти. Сторож: встала (после паузы не продолжилась, сбой чтения кадра) — запускаем заново
        # и пишем в журнал, из какого состояния: «иногда гифка не воспроизводится».
        state = movie.state()
        if state == QMovie.Paused:
            movie.setPaused(False)
            self.last_frame = now
        elif state == QMovie.NotRunning or (movie.frameCount() != 1 and now - getattr(self, "last_frame", now) > 2.0):
            print(time.strftime("%Y-%m-%d %H:%M:%S"), f"гифка стояла (состояние {state}, кадр {movie.currentFrameNumber()}"
                  f" из {movie.frameCount()}, ошибка {movie.lastErrorString()!r}) — запущена заново",
                  file=sys.stderr, flush=True)
            movie.stop()
            movie.start()
            self.last_frame = now

    # ---------- несколько гифок ----------
    # Текущая — как раньше: cfg["file"] и её рамка cfg["rect"] (редактор работает с ними). Весь список —
    # cfg["files"], рамки остальных — cfg["rects"][путь]: при смене текущая рамка уходит туда, следующая — оттуда.

    def files(self):
        files = self.cfg.get("files")
        if isinstance(files, list) and files:
            return [f for f in files if isinstance(f, str)]
        return [self.cfg["file"]] if isinstance(self.cfg.get("file"), str) else []

    def every(self):
        v = self.cfg.get("every", 30)
        return v if v in [s for s, _ in EVERY] else 30

    def apply_every(self):
        self.turn.setInterval(self.every() * 1000)
        self.turn.start()

    def set_every(self, seconds):
        self.cfg["every"] = seconds
        config.save()
        self.apply_every()

    def show_file(self, path):
        """Сделать текущей гифку из списка: рамку прошлой запомнить, рамку этой вернуть."""
        cur = self.cfg.get("file")
        rects = self.cfg.get("rects") if isinstance(self.cfg.get("rects"), dict) else {}
        if cur and isinstance(self.cfg.get("rect"), list):
            rects[cur] = self.cfg["rect"]
        self.cfg["file"] = path
        if isinstance(rects.get(path), list):
            self.cfg["rect"] = rects[path]
        else:
            self.cfg.pop("rect", None)  # у новой гифки свои размеры — рамка заново, весь кадр
        self.cfg["rects"] = {k: v for k, v in rects.items() if k in self.files() or k == path}
        self.save_timer.start()
        self.load()

    def auto_next(self):
        if self.editor is None and not activity.covered(self):
            self.next_gif()

    def next_gif(self, step=1):
        files = [f for f in self.files() if os.path.isfile(f)]
        if len(files) < 2:
            return
        cur = self.cfg.get("file")
        i = files.index(cur) if cur in files else -1
        self.show_file(files[(i + step) % len(files)])
        self.turn.start()  # отсчёт заново

    def set_files(self, paths, show=None):
        paths = list(dict.fromkeys(paths))[:MAX_FILES]
        self.cfg["files"] = paths
        if paths:
            self.show_file(paths[0] if show is None else paths[show])
        config.save()

    def set_file(self, path):  # одна гифка (как раньше)
        self.set_files([path])

    def remove_current(self):
        files = self.files()
        cur = self.cfg.get("file")
        if len(files) < 2 or cur not in files:
            return
        i = files.index(cur)
        files.remove(cur)
        self.cfg.pop("rect", None)
        self.cfg["file"] = None  # рамку убранной не запоминать
        self.set_files(files, show=i % len(files))

    # диалоги без родителя: под ярлыками окно виджета скрыто
    def _ask(self):
        paths, _ = QFileDialog.getOpenFileNames(None, tr("Гифки (можно несколько)"), self.cfg.get("file") or "",
                                                tr("Гифки (*.gif *.webp)"))
        return paths

    def pick(self):
        paths = self._ask()
        if paths:
            self.set_files(paths)
        return bool(paths)

    def add_more(self):
        paths = self._ask()
        if paths:
            have = self.files()
            self.set_files(have + [p for p in paths if p not in have], show=len(have) if len(have) < MAX_FILES else None)

    def pick_and_edit(self):
        if self.pick() and self.movie is not None:
            self.edit()

    def edit(self):
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
        config.save()

    def add_actions(self, menu):
        sub = menu.addMenu(tr("Размер по сетке"))  # то же, что в редакторе, — без него
        for c, r in SIZES:
            a = sub.addAction(f"{c} × {r}", lambda c=c, r=r: self.set_cells(c, r))
            a.setCheckable(True)
            a.setChecked((c, r) == self.cells())
        if self.movie is not None:
            menu.addAction(tr("Редактор гифки…"), self.edit)
        menu.addAction(tr("Выбрать гифки…"), self.pick_and_edit)
        if self.files():
            menu.addAction(tr("Добавить гифки…"), self.add_more)
        if len(self.files()) > 1:
            menu.addAction(tr("Следующая гифка"), self.next_gif)
            menu.addAction(tr("Убрать эту гифку"), self.remove_current)
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
            menu.addAction(tr("Ещё одна гифка"), lambda: activity.copies.add_copy(self.copy_of or self.key, self))

    def click(self, pos):
        return False  # тащить можно всегда (и пустой); короткое нажатие — tap

    def tap(self, pos):
        if self.movie is None:  # пустой виджет — кнопка «Добавить гифку»
            QTimer.singleShot(0, self.pick)
            return
        if len(self.files()) > 1 and self.flip() == "click":  # короткое нажатие — следующая
            self.next_gif()

    # ---------- свайп ----------

    def flip(self):
        return "swipe" if self.cfg.get("flip") == "swipe" else "click"

    def set_flip(self, name):
        self.cfg["flip"] = name
        config.save()

    def swiping(self):
        return self.flip() == "swipe" and len(self.files()) > 1

    def swipe_move(self, dx):
        self.slide_timer.stop()
        self.slide_anim = None
        self.slide = float(dx) / self.scale()
        self.update()

    def swipe_end(self, dx):
        """Дотянули — гифка уезжает в сторону свайпа, с другой стороны въезжает следующая (влево) или прошлая."""
        w = self.card().width()
        dx = float(dx) / self.scale()
        if abs(dx) > min(60.0, w * 0.18):
            step = 1 if dx < 0 else -1
            self.slide_anim = (dx, -step * (w + 12), time.monotonic(), step)
        else:
            self.slide_anim = (dx, 0.0, time.monotonic(), 0)
        self.slide_timer.start()

    def slide_tick(self):
        if self.slide_anim is None:
            self.slide_timer.stop()
            return
        a, b, start, step = self.slide_anim
        t = min(1.0, (time.monotonic() - start) / SLIDE)
        self.slide = a + (b - a) * (1 - (1 - t) ** 3)
        if t >= 1.0:
            self.slide_timer.stop()
            if step:  # уехала — следующая въезжает с другого края
                self.next_gif(step)
                w = self.card().width() + 12
                self.slide_anim = (step * w, 0.0, time.monotonic(), 0)
                self.slide = step * w
                self.slide_timer.start()
            else:
                self.slide_anim = None
                self.slide = 0.0
        self.update()

    # перетащить гифку из Проводника прямо на виджет
    def dragEnterEvent(self, event):
        if self._dropped(event):
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = self._dropped(event)
        if paths:
            have = self.files()
            if event.modifiers() & Qt.ControlModifier and have:  # с Ctrl — добавить к тем, что есть
                self.set_files(have + [p for p in paths if p not in have], show=min(len(have), MAX_FILES - 1))
            else:
                self.set_files(paths)
            event.acceptProposedAction()

    @staticmethod
    def _dropped(event):
        paths = [u.toLocalFile() for u in event.mimeData().urls()]
        paths = [p for p in paths if p.lower().endswith(EXTS) and os.path.isfile(p)]
        return paths or None

    def closeEvent(self, event):
        if self.editor is not None:
            self.editor.close()
        super().closeEvent(event)

    # ---------- рисование ----------

    def paintEvent(self, event):
        super().paintEvent(event)  # стекло
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        r = QRectF(self.card())
        pix = self.movie.currentPixmap() if self.movie is not None else None
        if pix is None or pix.isNull():
            draw_add(p, r, bool(self.dark), tr("Добавить гифку"),
                     tr("Под ярлыками: сначала «Двигать виджеты»") if self.pinned else tr("или перетащи сюда"))
            return
        if self.slide:  # свайп — гифка едет за мышью, за краем карточки не видна
            clip = QPainterPath()
            clip.addRoundedRect(r, RADIUS, RADIUS)
            p.save()
            p.setClipPath(clip)
            draw_gif(p, r.translated(self.slide, 0), pix, self.crop(), RADIUS)
            p.restore()
        else:
            draw_gif(p, r, pix, self.crop(), RADIUS)
        files = self.files()
        n = len(files)
        if 1 < n <= 12:  # точки — сколько гифок и какая сейчас
            cur = files.index(self.cfg.get("file")) if self.cfg.get("file") in files else -1
            d, gap = 6.0, 6.0
            x = r.center().x() - (n * d + (n - 1) * gap) / 2
            p.setPen(QPen(QColor(0, 0, 0, 70), 1.0))  # тонкая тень — точки видно и на светлой гифке
            for i in range(n):
                p.setBrush(QColor(255, 255, 255, 235 if i == cur else 110))
                p.drawEllipse(QRectF(x + i * (d + gap), r.bottom() - 14, d, d))


class CropView(QWidget):
    """Рамка обрезки, как в редакторе фото на телефоне: весь кадр гифки, поверх — рамка с уголками.
    Тянешь за угол — рамка растёт или сжимается (пропорции — как у карточки выбранного размера), за середину —
    едет по кадру. Вокруг рамки кадр притемнён: что в рамке, то и на виджете."""

    GRAB = 22  # с какого расстояния до угла хватаем его, px

    def __init__(self, widget):
        super().__init__()
        self.widget = widget
        self.setFixedSize(460, 300)
        self.setMouseTracking(True)
        self.drag = None  # ("move", смещение) или ("corner", неподвижный угол в долях кадра)
        self.timer = QTimer(self, interval=40, timeout=self.update)
        self.timer.start()

    def image_rect(self):
        """Где на окошке лежит весь кадр (вписан целиком, с полями)."""
        W, H = self.widget.frame_size()
        if not (W and H):
            return QRectF()
        k = min((self.width() - 24) / W, (self.height() - 24) / H)
        return QRectF((self.width() - W * k) / 2, (self.height() - H * k) / 2, W * k, H * k)

    def crop_rect(self):
        img = self.image_rect()
        x, y, w, h = self.widget.crop()
        return QRectF(img.left() + x * img.width(), img.top() + y * img.height(), w * img.width(), h * img.height())

    def corner_at(self, pos):
        r = self.crop_rect()
        corners = {"tl": r.topLeft(), "tr": r.topRight(), "bl": r.bottomLeft(), "br": r.bottomRight()}
        name = min(corners, key=lambda n: (corners[n] - pos).manhattanLength())
        return name if (corners[name] - pos).manhattanLength() <= self.GRAB else None

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton or self.image_rect().isEmpty():
            return
        pos, r, img = event.position(), self.crop_rect(), self.image_rect()
        corner = self.corner_at(pos)
        if corner:  # тянем угол — противоположный стоит на месте
            fixed = {"tl": r.bottomRight(), "tr": r.bottomLeft(), "bl": r.topRight(), "br": r.topLeft()}[corner]
            self.drag = ("corner", ((fixed.x() - img.left()) / img.width(), (fixed.y() - img.top()) / img.height()))
        elif r.contains(pos):
            self.drag = ("move", pos - r.topLeft())

    def mouseMoveEvent(self, event):
        pos, img = event.position(), self.image_rect()
        if img.isEmpty():
            return
        if self.drag is None:
            corner = self.corner_at(pos)
            self.setCursor(Qt.SizeFDiagCursor if corner in ("tl", "br") else Qt.SizeBDiagCursor if corner
                           else Qt.SizeAllCursor if self.crop_rect().contains(pos) else Qt.ArrowCursor)
            return
        W, H = self.widget.frame_size()
        aspect = self.widget.aspect()
        mx = max(0.0, min(1.0, (pos.x() - img.left()) / img.width()))
        my = max(0.0, min(1.0, (pos.y() - img.top()) / img.height()))
        if self.drag[0] == "move":
            x, y, w, h = self.widget.crop()
            off = self.drag[1]
            x = max(0.0, min(1 - w, (pos.x() - off.x() - img.left()) / img.width()))
            y = max(0.0, min(1 - h, (pos.y() - off.y() - img.top()) / img.height()))
        else:
            ax, ay = self.drag[1]
            right, down = mx >= ax, my >= ay
            # в пикселях кадра: ширина — по курсору (что дальше ушло — то и ведёт), но не за край кадра
            room_x = ((1 - ax) if right else ax) * W
            room_y = ((1 - ay) if down else ay) * H
            wpx = max(abs(mx - ax) * W, abs(my - ay) * H * aspect, MIN_PART * W)
            wpx = max(1.0, min(wpx, room_x, room_y * aspect))
            w, h = wpx / W, wpx / aspect / H
            x, y = (ax if right else ax - w), (ay if down else ay - h)
        self.widget.set_crop([max(0.0, x), max(0.0, y), w, h])
        self.update()

    def mouseReleaseEvent(self, event):
        self.drag = None

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        w = self.widget
        pix = w.editor_pixmap()
        img = self.image_rect()
        if pix is None or pix.isNull() or img.isEmpty():
            return
        p.drawPixmap(img, pix, QRectF(pix.rect()))
        r = self.crop_rect()
        shade = QPainterPath()
        shade.addRect(img)
        hole = QPainterPath()
        hole.addRect(r)
        p.fillPath(shade.subtracted(hole), QColor(0, 0, 0, 150))  # вне рамки — притемнено
        p.setPen(QPen(QColor(255, 255, 255, 70), 1))               # сетка третей
        for i in (1, 2):
            p.drawLine(QPointF(r.left() + r.width() * i / 3, r.top()), QPointF(r.left() + r.width() * i / 3, r.bottom()))
            p.drawLine(QPointF(r.left(), r.top() + r.height() * i / 3), QPointF(r.right(), r.top() + r.height() * i / 3))
        p.setPen(QPen(QColor(255, 255, 255, 230), 1.2))
        p.setBrush(Qt.NoBrush)
        p.drawRect(r)
        p.setPen(QPen(QColor("white"), 4, Qt.SolidLine, Qt.FlatCap, Qt.MiterJoin))  # уголки — за них тянуть
        n = min(20.0, r.width() / 3, r.height() / 3)
        for cx, cy, sx, sy in ((r.left(), r.top(), 1, 1), (r.right(), r.top(), -1, 1),
                               (r.left(), r.bottom(), 1, -1), (r.right(), r.bottom(), -1, -1)):
            p.drawPolyline([QPointF(cx + sx * n, cy), QPointF(cx, cy), QPointF(cx, cy + sy * n)])


EDITOR_STYLE = """
QDialog { background: #17181d; }
QLabel { color: #e8e9ee; font-size: 13px; }
QLabel#dim { color: #9a9dab; font-size: 12px; }
QLabel#head { font-size: 15px; font-weight: 600; }
QPushButton { background: #2a2c35; color: #e8e9ee; border: none; border-radius: 10px; padding: 8px 16px; font-size: 13px; }
QPushButton:hover { background: #353846; }
QPushButton#main { background: #2f6bff; color: white; }
QPushButton#main:hover { background: #4a7fff; }
QPushButton#nav { padding: 4px 14px; font-size: 18px; border-radius: 14px; }
QComboBox { background: #2a2c35; color: #e8e9ee; border: none; border-radius: 10px; padding: 6px 12px; font-size: 13px; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView { background: #23252d; color: #e8e9ee; selection-background-color: #2f6bff; border: none; }
QSlider::groove:horizontal { height: 4px; background: #33363f; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #2f6bff; border-radius: 2px; }
QSlider::handle:horizontal { width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; background: #f2f3f7; }
"""


class GifEditor(QDialog):
    """Редактор гифки: рамка обрезки с уголками, размер по сетке, скорость. Всё применяется сразу — «Готово» закрывает."""

    def __init__(self, widget):
        super().__init__(None)
        self.widget = widget
        self.setWindowTitle(widget.EDITOR_TITLE)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setStyleSheet(EDITOR_STYLE)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(14)
        self.view = CropView(widget)
        lay.addWidget(self.view, alignment=Qt.AlignHCenter)
        # несколько фото / гифок — листать прямо в редакторе: у каждой своя рамка
        nav = QHBoxLayout()
        nav.setSpacing(10)
        self.prev_btn = QPushButton("‹", objectName="nav")
        self.next_btn = QPushButton("›", objectName="nav")
        self.where = QLabel("", objectName="dim")
        self.where.setAlignment(Qt.AlignCenter)
        self.where.setMinimumWidth(90)
        self.prev_btn.clicked.connect(lambda: self.step(-1))
        self.next_btn.clicked.connect(lambda: self.step(1))
        nav.addStretch()
        nav.addWidget(self.prev_btn)
        nav.addWidget(self.where)
        nav.addWidget(self.next_btn)
        nav.addStretch()
        lay.addLayout(nav)
        hint = QLabel(tr("Тяни за углы рамки или двигай её — что в рамке, то и на виджете"), objectName="dim")
        hint.setAlignment(Qt.AlignHCenter)
        lay.addWidget(hint)

        grid_lay = QGridLayout()
        grid_lay.setHorizontalSpacing(12)
        grid_lay.setVerticalSpacing(10)
        grid_lay.setColumnStretch(1, 1)
        row = 0
        # размер
        grid_lay.addWidget(QLabel(tr("Размер")), row, 0)
        self.size = QComboBox()
        for c, r in SIZES:
            self.size.addItem(f"{c} × {r}", (c, r))
        self.size.setCurrentIndex(SIZES.index(widget.cells()))
        self.size.currentIndexChanged.connect(lambda i: widget.set_cells(*SIZES[i]))
        grid_lay.addWidget(self.size, row, 1, 1, 2, Qt.AlignLeft)
        row += 1
        # скорость — только у гифок
        self.speed = None
        if hasattr(widget, "speed"):
            self.speed, self.speed_value = self._slider(grid_lay, row, tr("Скорость"), 25, 300, widget.speed(),
                                                        lambda v: self._put("speed", v))
            row += 1
        lay.addLayout(grid_lay)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        pick = QPushButton(widget.EDITOR_PICK)
        pick.clicked.connect(lambda: (widget.pick(), self.update_nav()))
        reset = QPushButton(tr("Сбросить"))
        reset.clicked.connect(self.reset)
        done = QPushButton(tr("Готово"), objectName="main")
        done.clicked.connect(self.accept)
        done.setDefault(True)
        buttons.addWidget(pick)
        buttons.addWidget(reset)
        buttons.addStretch()
        buttons.addWidget(done)
        lay.addLayout(buttons)
        self.update_nav()

    def update_nav(self):
        i, n = self.widget.editor_items()
        for w in (self.prev_btn, self.next_btn, self.where):
            w.setVisible(n > 1)
        self.where.setText(tr("{} из {}").format(i + 1, n))

    def step(self, d):
        self.widget.editor_step(d)
        self.update_nav()
        self.view.update()

    @staticmethod
    def _slider(lay, row, text, low, high, value, on_change):
        lay.addWidget(QLabel(text), row, 0)
        slider = QSlider(Qt.Horizontal)
        slider.setRange(low, high)
        slider.setValue(value)
        slider.setMinimumWidth(260)
        shown = QLabel(f"{value}%", objectName="dim")
        shown.setFixedWidth(44)
        slider.valueChanged.connect(lambda v: (shown.setText(f"{v}%"), on_change(v)))
        lay.addWidget(slider, row, 1)
        lay.addWidget(shown, row, 2)
        return slider, shown

    def _put(self, key, value):
        self.widget.cfg[key] = value
        self.widget.changed()

    def reset(self):
        if self.speed is not None:
            self.speed.setValue(100)
        self.widget.reset_crop()
