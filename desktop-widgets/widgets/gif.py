"""Гифка на рабочем столе: своя анимация (GIF или анимированный WebP) в карточке любого размера по сетке.
Редактор (двойной клик или правый клик → «Редактор гифки…»): размер в ячейках (1×1 … 4×3), скорость и рамка обрезки,
как в редакторе фото на телефоне: тянешь за углы — меняешь размер рамки, за середину — двигаешь; что в рамке, то и на
виджете. Всё видно сразу. Файл только читается; закрытый окном виджет гифку не крутит."""
from lang import tr
import os
import sys
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QMovie, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QSlider, QVBoxLayout, QWidget)

import icons
from core import DesktopWidget, RADIUS, SHADOW, activity, config, grid

EXTS = (".gif", ".webp")
SIZES = [(1, 1), (2, 1), (1, 2), (2, 2), (3, 1), (3, 2), (4, 1), (4, 2), (2, 3), (3, 3), (4, 3)]  # ширина × высота, ячеек
MIN_PART = 0.12  # рамка обрезки не меньше 12% ширины кадра — иначе за углы уже не ухватить


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
        self.load()

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
        if self.pinned:
            self.push()
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

    def set_file(self, path):
        self.cfg["file"] = path
        self.cfg.pop("rect", None)  # у новой гифки свои размеры — рамка заново, весь кадр
        config.save()
        self.load()

    # диалоги без родителя: под ярлыками окно виджета скрыто
    def pick(self):
        path, _ = QFileDialog.getOpenFileName(None, tr("Гифка"), self.cfg.get("file", ""), tr("Гифки (*.gif *.webp)"))
        if path:
            self.set_file(path)
        return bool(path)

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

    def first_setup(self):
        if self.movie is None:
            QTimer.singleShot(150, self.pick_and_edit)

    def add_actions(self, menu):
        if self.movie is not None:
            menu.addAction(tr("Редактор гифки…"), self.edit)
        menu.addAction(tr("Выбрать гифку…"), self.pick_and_edit)

    def click(self, pos):
        if self.movie is None:  # пустая рамка — выбрать гифку
            self.pick_and_edit()
            return True
        return False

    def double_click(self):
        if self.movie is not None:
            self.edit()

    # перетащить гифку из Проводника прямо на виджет
    def dragEnterEvent(self, event):
        if self._dropped(event):
            event.acceptProposedAction()

    def dropEvent(self, event):
        path = self._dropped(event)
        if path:
            self.set_file(path)
            event.acceptProposedAction()

    @staticmethod
    def _dropped(event):
        urls = event.mimeData().urls()
        path = urls[0].toLocalFile() if urls else ""
        return path if path.lower().endswith(EXTS) and os.path.isfile(path) else None

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
            small = r.height() < 200 and r.width() < 200
            icon = icons.app_icon("gif", 48)
            p.drawPixmap(QPointF(r.center().x() - 24, r.center().y() - (24 if small else 54)), icon)
            if not small:
                f = QFont("Segoe UI")
                f.setPixelSize(12)
                p.setFont(f)
                p.setPen(QColor("#d8dae2") if self.dark else QColor("#565a6b"))
                p.drawText(r.adjusted(16, r.height() / 2 + 8, -16, -12), Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap,
                           tr("Нажми — выбрать гифку\nили перетащи её сюда"))
            return
        draw_gif(p, r, pix, self.crop(), RADIUS)


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
        self.widget.cfg["rect"] = [max(0.0, x), max(0.0, y), w, h]
        self.widget.changed()
        self.update()

    def mouseReleaseEvent(self, event):
        self.drag = None

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        w = self.widget
        pix = w.movie.currentPixmap() if w.movie is not None else None
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
        self.setWindowTitle(tr("Редактор гифки"))
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setStyleSheet(EDITOR_STYLE)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(14)
        self.view = CropView(widget)
        lay.addWidget(self.view, alignment=Qt.AlignHCenter)
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
        # скорость
        self.speed, self.speed_value = self._slider(grid_lay, row, tr("Скорость"), 25, 300, widget.speed(),
                                                    lambda v: self._put("speed", v))
        row += 1
        lay.addLayout(grid_lay)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        pick = QPushButton(tr("Выбрать гифку…"))
        pick.clicked.connect(lambda: widget.pick())
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
        self.speed.setValue(100)
        self.widget.cfg.pop("rect", None)  # рамка — снова весь кадр
        self.widget.changed()
