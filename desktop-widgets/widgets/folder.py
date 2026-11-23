"""Папка: ярлыки программ, файлы и папки в стеклянной карточке — как папка на рабочем столе телефона.
Клик по значку — открыть; не влезли все — последняя клетка «+N» раскрывает папку целиком (окно поверх, как в ColorOS).
Наполнить — перетащить ярлыки / файлы / папки из Проводника на виджет или «Добавить…» в меню.
Значки — настоящие, из Windows (256 px), достаются в фоне и кэшируются на диске (icon_cache)."""
from lang import tr
import ctypes
import hashlib
import os
import queue
import shutil
import threading
from ctypes import wintypes as wt

from PySide6.QtCore import QEasingCurve, QObject, QPointF, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMenu, QWidget

import applog
import skins
from core import DesktopWidget, ROOT, SHADOW, activity, config, grid, open_uri
from widgets.gif import draw_add

# размер по сетке (ширина × высота ячеек), по умолчанию 2 × 1
SIZES = [(1, 1), (2, 1), (2, 2), (3, 1), (3, 2), (4, 1), (4, 2)]
MAX_ITEMS = 60
CELL_W, CELL_H = 76, 84      # клетка значка с подписью на карточке
ICON = 50                    # значок на карточке
VIEW_COLS, VIEW_CELL_W, VIEW_CELL_H, VIEW_ICON = 4, 104, 112, 64   # раскрытая папка
VIEW_ROWS = 4                # больше — прокрутка колесом
CACHE = os.path.join(ROOT, "icon_cache")
ICON_PX = 128                # значок в кэше (с запасом на масштаб экрана 200%)


# ---------------------------------------------------------------- перенос со стола

# куда переезжают ярлыки с рабочего стола (см. store_dir). Прежнее место — в AppData; перенесённые туда раньше
# возвращаются по записанному пути как обычно
STORE = None
OLD_STORE = os.path.join(os.environ.get("LOCALAPPDATA") or ROOT, "LiquidDesktop", "folder_items")
MOVABLE = (".lnk", ".url")


def desktop_dir():
    """Рабочий стол пользователя (и перенесённый в OneDrive / на другой диск)."""
    buf = ctypes.create_unicode_buffer(260)
    try:
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0 and buf.value:  # CSIDL_DESKTOPDIRECTORY
            return buf.value
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), "Desktop")


def store_dir():
    """Хранилище перенесённых ярлыков — скрытая папка «.liquid-desktop» рядом с рабочим столом, на ТОМ ЖЕ диске:
    ярлык переезжает простым переименованием, файл не копируется.
    Не в AppData: виджеты, запущенные изнутри приложения из Microsoft Store (например, из Claude), Windows считает
    частью того приложения — их AppData уезжает в хранилище того приложения и шифруется его ключом, и ярлык,
    вернувшийся оттуда на стол, Проводник больше не открывал (21.11.2026: Claude, Fortnite, Beyond-All-Reason)."""
    if STORE:
        return STORE
    desk = desktop_dir()
    for base in (os.path.join(os.path.dirname(os.path.abspath(desk)), ".liquid-desktop"), os.path.join(desk, ".liquid-desktop")):
        try:
            os.makedirs(base, exist_ok=True)
            ctypes.windll.kernel32.SetFileAttributesW(base, 0x2)  # скрытая
            return os.path.join(base, "folder_items")
        except OSError:
            continue
    return OLD_STORE


def _decrypt(path):
    """Файл зашифрован (см. store_dir) — снять шифрование, пока программа ещё может. True — файл обычный."""
    try:
        if not os.stat(path).st_file_attributes & 0x4000:  # FILE_ATTRIBUTE_ENCRYPTED
            return True
        ctypes.windll.advapi32.DecryptFileW(path, 0)
        return not os.stat(path).st_file_attributes & 0x4000
    except OSError:
        return False


def on_desktop(path):
    """Ярлык (.lnk / .url), который лежит прямо на рабочем столе пользователя — только такие переносим."""
    return (path.lower().endswith(MOVABLE) and os.path.isfile(path)
            and os.path.normcase(os.path.dirname(os.path.abspath(path))) == os.path.normcase(desktop_dir()))


def _free(folder, name):
    """Свободное имя в папке: «Игра.lnk», занято — «Игра (2).lnk»…"""
    stem, ext = os.path.splitext(name)
    out, n = os.path.join(folder, name), 2
    while os.path.exists(out):
        out, n = os.path.join(folder, f"{stem} ({n}){ext}"), n + 1
    return out


def take(path, key):
    """Ярлык со стола — в папку виджета (перемещение, не удаление). Новый путь или None (оставить ссылку)."""
    try:
        folder = os.path.join(store_dir(), key)
        os.makedirs(folder, exist_ok=True)
        dst = _free(folder, os.path.basename(path))
        shutil.move(path, dst)
        if not _decrypt(dst):  # ярлык зашифровался по дороге — вернуть на стол как был и оставить ссылкой
            shutil.move(dst, path)
            applog.line(f"папка: {os.path.basename(path)} зашифровался при переносе — оставлен на столе")
            return None
        applog.line(f"папка: ярлык со стола в папку {os.path.basename(path)}")
        return dst
    except Exception as err:
        applog.error("folder.take", err)
        return None


def give_back(stored, original):
    """Вернуть ярлык на рабочий стол (на прежнее имя, занято — с номером). True — вернули (или файла уже нет)."""
    if not os.path.exists(stored):
        return True
    try:
        folder = os.path.dirname(original) if os.path.isdir(os.path.dirname(original)) else desktop_dir()
        _decrypt(stored)
        dst = _free(folder, os.path.basename(original))
        shutil.move(stored, dst)
        if not _decrypt(dst):
            applog.line(f"папка: {os.path.basename(original)} на столе зашифрован — Проводник может его не открыть")
        applog.line(f"папка: ярлык обратно на стол {os.path.basename(original)}")
        return True
    except Exception as err:
        applog.error("folder.give_back", err)
        return False


# ---------------------------------------------------------------- значки Windows

class _SHFILEINFOW(ctypes.Structure):
    _fields_ = [("hIcon", wt.HANDLE), ("iIcon", ctypes.c_int), ("dwAttributes", wt.DWORD),
                ("szDisplayName", wt.WCHAR * 260), ("szTypeName", wt.WCHAR * 80)]


class _GUID(ctypes.Structure):
    _fields_ = [("a", wt.DWORD), ("b", wt.WORD), ("c", wt.WORD), ("d", ctypes.c_ubyte * 8)]


_IID_IImageList = _GUID(0x46EB5926, 0x582E, 0x4017,
                        (ctypes.c_ubyte * 8)(0x9F, 0xDF, 0xE8, 0x99, 0x8D, 0xAA, 0x09, 0x50))
_GETICON = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_int, wt.UINT, ctypes.POINTER(wt.HICON))
_RELEASE = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)


def _shell_icon(path, kind):
    """Значок из системного списка: kind 4 — 256 px (SHIL_JUMBO), 2 — 48 px (SHIL_EXTRALARGE). Фоновый поток."""
    shell32, user32 = ctypes.windll.shell32, ctypes.windll.user32
    shell32.SHGetFileInfoW.argtypes = [wt.LPCWSTR, wt.DWORD, ctypes.POINTER(_SHFILEINFOW), wt.UINT, wt.UINT]
    shell32.SHGetFileInfoW.restype = ctypes.c_size_t
    shell32.SHGetImageList.argtypes = [ctypes.c_int, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)]
    shell32.SHGetImageList.restype = ctypes.c_long
    user32.DestroyIcon.argtypes = [wt.HICON]
    sfi = _SHFILEINFOW()
    if not shell32.SHGetFileInfoW(path, 0, ctypes.byref(sfi), ctypes.sizeof(sfi), 0x4000):  # SHGFI_SYSICONINDEX
        return None
    il = ctypes.c_void_p()
    if shell32.SHGetImageList(kind, ctypes.byref(_IID_IImageList), ctypes.byref(il)) != 0 or not il:
        return None
    vtbl = ctypes.cast(ctypes.cast(il, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
    h = wt.HICON()
    try:
        if _GETICON(vtbl[10])(il, sfi.iIcon, 1, ctypes.byref(h)) != 0 or not h:  # IImageList::GetIcon, ILD_TRANSPARENT
            return None
        img = QImage.fromHICON(int(h.value))
    finally:
        if h:
            user32.DestroyIcon(h)
        _RELEASE(vtbl[2])(il)  # SHGetImageList выдаёт список со счётчиком ссылок — вернуть
    return None if img.isNull() else img


def _filled(img):
    """Сколько точек по большей стороне занято значком (у старых программ в 256 — значок 32 px в углу)."""
    img = img.convertToFormat(QImage.Format_ARGB32)
    w, h = img.width(), img.height()
    import numpy as np
    a = np.frombuffer(img.constBits(), np.uint8).reshape(h, img.bytesPerLine())[:, :w * 4].reshape(h, w, 4)[..., 3]
    ys, xs = np.nonzero(a > 8)
    return max(xs.max() - xs.min() + 1, ys.max() - ys.min() + 1) if len(xs) else 0


def _cache_name(path):
    try:
        st = os.stat(path)
        stamp = f"{st.st_mtime_ns}:{st.st_size}"
    except OSError:
        stamp = "-"
    return os.path.join(CACHE, hashlib.sha1(f"{path.lower()}|{stamp}".encode("utf-8")).hexdigest()[:20] + ".png")


class IconLoader(QObject):
    """Значки по пути: из памяти, из кэша на диске или (в фоне) из Windows. Готово — сигнал loaded(путь)."""
    loaded = Signal(str)

    def __init__(self):
        super().__init__()
        self.images = {}      # путь -> QImage (или None — значка нет)
        self.waiting = set()
        self.jobs = queue.Queue()
        self.thread = None

    def get(self, path):
        if path in self.images:
            return self.images[path]
        if path not in self.waiting:
            name = _cache_name(path)
            if os.path.isfile(name):
                img = QImage(name)
                if not img.isNull():
                    self.images[path] = img
                    return img
            self.waiting.add(path)
            self.jobs.put(path)
            if self.thread is None:  # один поток на всю программу: ждёт работу, не засыпая насовсем
                self.thread = threading.Thread(target=self._work, daemon=True, name="folder-icons")
                self.thread.start()
        return None

    def _work(self):
        ctypes.windll.ole32.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED: оболочке Windows так спокойнее
        while True:
            path = self.jobs.get()
            img = None
            try:
                big = _shell_icon(path, 4)
                img = big if big is not None and _filled(big) >= 100 else (_shell_icon(path, 2) or big)
                if img is not None:
                    img = img.scaled(ICON_PX, ICON_PX, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    os.makedirs(CACHE, exist_ok=True)
                    img.save(_cache_name(path))
            except Exception as err:
                applog.error("folder.icon", err)
            self.images[path] = img
            self.waiting.discard(path)
            try:
                self.loaded.emit(path)
            except RuntimeError:
                return


_loader = None


def loader():
    global _loader
    if _loader is None:
        _loader = IconLoader()
    return _loader


def item_name(path):
    base = os.path.basename(path.rstrip("\\/")) or path
    stem, ext = os.path.splitext(base)
    return stem if ext.lower() in (".lnk", ".url", ".exe", ".appref-ms") and stem else base


def draw_icon(p, rect, path, dark, press=1.0):
    """Значок по центру rect (квадрат); пока не готов — мягкая плитка-заглушка."""
    img = loader().get(path)
    r = QRectF(rect)
    if press != 1.0:
        c = r.center()
        r = QRectF(c.x() - r.width() * press / 2, c.y() - r.height() * press / 2, r.width() * press, r.height() * press)
    if img is None:
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 40) if dark else QColor(0, 0, 0, 30))
        p.drawRoundedRect(r.adjusted(4, 4, -4, -4), r.width() * 0.22, r.width() * 0.22)
        return
    p.drawImage(r, img)


def draw_label(p, rect, text, dark, size=11):
    f = QFont("Segoe UI")
    f.setPixelSize(size)
    p.setFont(f)
    fm = QFontMetricsF(f)
    p.setPen(QColor(240, 241, 246) if dark else QColor(28, 29, 34))
    p.drawText(rect, Qt.AlignHCenter | Qt.AlignTop, fm.elidedText(text, Qt.ElideRight, rect.width()))


def draw_stack(p, rect, paths, dark, more):
    """Клетка «ещё»: четыре маленьких значка следующих и «+N» — нажатие раскрывает папку."""
    r = QRectF(rect)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 255, 255, 34) if dark else QColor(0, 0, 0, 22))
    p.drawRoundedRect(r, r.width() * 0.24, r.width() * 0.24)
    s = (r.width() - 12) / 2
    for i, path in enumerate(paths[:4]):
        cell = QRectF(r.left() + 4 + (i % 2) * (s + 4), r.top() + 4 + (i // 2) * (s + 4), s, s)
        draw_icon(p, cell, path, dark)
    if more > 0:
        f = QFont("Segoe UI Semibold")
        f.setPixelSize(11)
        p.setFont(f)
        badge = QRectF(r.right() - 26, r.bottom() - 16, 30, 18)
        p.setBrush(skins.ACCENT)
        p.drawRoundedRect(badge, 9, 9)
        p.setPen(QColor("white"))
        p.drawText(badge, Qt.AlignCenter, f"+{more}")


def item_menu(parent, widget, path):
    """Правый клик по значку: открыть, показать в Проводнике, убрать из папки (перенесённый со стола — вернуть)."""
    menu = QMenu(parent)
    menu.addAction(tr("Открыть"), lambda: widget.launch(path))
    if os.path.exists(path) and path not in widget.moved():
        menu.addAction(tr("Показать в Проводнике"), lambda: _reveal(path))
    menu.addSeparator()
    menu.addAction(tr("Вернуть на рабочий стол") if path in widget.moved() else tr("Убрать из папки"),
                   lambda: widget.remove_item(path))
    menu.exec(QCursor.pos())


def _reveal(path):
    try:
        ctypes.windll.shell32.ShellExecuteW(None, "open", "explorer.exe", f'/select,"{os.path.normpath(path)}"', None, 1)
    except Exception as err:
        applog.error("folder.reveal", err)


# ---------------------------------------------------------------- виджет

class FolderWidget(DesktopWidget):
    key = "folder"
    title = tr("Папка")
    description = tr("Ярлыки программ, файлы и папки — как папка на телефоне")

    def __init__(self, **kw):
        super().__init__(**kw)
        self.apply_size()
        self.cells_hit = []        # [(прямоугольник, путь или "more")] — что где нарисовано
        self.pressed = None
        self.view = None
        self.setAcceptDrops(True)
        loader().loaded.connect(self._icon_ready)

    # ---------- размер по сетке ----------

    def cells(self):
        c, r = self.cfg.get("cols", 2), self.cfg.get("rows", 1)
        return (c, r) if (c, r) in SIZES else (2, 1)

    def apply_size(self):
        self.setFixedSize(*(v + 2 * SHADOW for v in grid(*self.cells())))

    def set_cells(self, cols, rows):
        self.cfg["cols"], self.cfg["rows"] = cols, rows
        config.save()
        self.apply_size()
        self.flat_key = None
        self.last_src = None
        self.keep_on_screen()
        self.update()

    # ---------- что внутри ----------

    def items(self):
        raw = self.cfg.get("items")
        return [p for p in raw if isinstance(p, str)] if isinstance(raw, list) else []

    def set_items(self, paths):
        self.cfg["items"] = list(dict.fromkeys(paths))[:MAX_ITEMS]
        config.save()
        if activity.copies:
            try:
                activity.copies.refresh_counts()  # подпись карточки в каталоге: «5 в папке»
            except Exception:
                pass
        self.update()
        if self.view is not None:
            self.view.relayout()

    def moved(self):
        """Перенесённые со стола: {путь в папке: где лежал на столе}."""
        raw = self.cfg.get("moved")
        return {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, str)} if isinstance(raw, dict) else {}

    def takes_desktop(self):
        return self.cfg.get("take_desktop", True) is not False

    def set_takes_desktop(self, on):
        self.cfg["take_desktop"] = bool(on)
        config.save()

    def add_paths(self, paths):
        have = self.items()
        moved = self.moved()
        new = []
        for p in paths:
            p = os.path.normpath(p)
            if p in have or p in new or len(have) + len(new) >= MAX_ITEMS:
                continue
            if self.takes_desktop() and on_desktop(p):  # ярлык со стола — уезжает в папку, со стола пропадает
                dst = take(p, self.key)
                if dst is not None:
                    moved[dst] = p
                    p = dst
            new.append(p)
        self.cfg["moved"] = moved
        self.set_items(have + new)

    def remove_item(self, path):
        moved = self.moved()
        if path in moved:
            if not give_back(path, moved[path]):
                return  # не вернулся на стол (занят диском и т.п.) — из папки не убираем, чтобы не потерять
            moved.pop(path)
            self.cfg["moved"] = moved
        self.set_items([p for p in self.items() if p != path])

    def release_all(self):
        """Все перенесённые ярлыки — обратно на рабочий стол (папку удаляют или «Вернуть всё на стол»)."""
        for path in list(self.moved()):
            self.remove_item(path)

    @staticmethod
    def release_cfg(cfg):
        """То же по настройкам — для копии, которую удаляют (её окна может уже не быть)."""
        raw = cfg.get("moved")
        if not isinstance(raw, dict):
            return
        for stored, original in list(raw.items()):
            if isinstance(stored, str) and isinstance(original, str) and give_back(stored, original):
                raw.pop(stored, None)

    def move_item(self, path, index):
        """Порядок: значок path — на место index (перетащили в раскрытой папке)."""
        items = [p for p in self.items() if p != path]
        items.insert(max(0, min(index, len(items))), path)
        self.set_items(items)

    def folder_title(self):
        t = self.cfg.get("title")
        return t if isinstance(t, str) and t.strip() else self.title

    @staticmethod
    def summary(cfg):
        raw = cfg.get("items")
        n = len([p for p in raw if isinstance(p, str)]) if isinstance(raw, list) else 0
        return tr("{} в папке").format(n) if n else tr("Пусто — перетащи сюда ярлыки")

    def labels(self):
        return self.cfg.get("labels", True) is not False

    def _icon_ready(self, path):
        if path in self.items():
            self.update()

    # ---------- действия ----------

    def launch(self, path):
        applog.line(f"папка: открыть {os.path.basename(path)}")
        open_uri(path)

    def _start_dir(self):
        have = self.items()
        if have:
            return os.path.dirname(have[-1])
        return os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs")

    def pick_files(self):
        paths, _ = QFileDialog.getOpenFileNames(None, tr("Что положить в папку (можно несколько)"), self._start_dir(),
                                                tr("Программы и ярлыки (*.lnk *.exe *.url);;Все файлы (*)"))
        if paths:
            self.add_paths(paths)

    def pick_folder(self):
        path = QFileDialog.getExistingDirectory(None, tr("Папка, которую положить внутрь"), self._start_dir())
        if path:
            self.add_paths([path])

    def rename(self):
        text, ok = QInputDialog.getText(None, tr("Название папки"), tr("Название:"), text=self.folder_title())
        if ok:
            self.cfg["title"] = text.strip()[:40]
            config.save()
            self.update()
            if self.view is not None:
                self.view.update()

    def set_labels(self, on):
        self.cfg["labels"] = bool(on)
        config.save()
        self.update()

    def open_view(self):
        if self.view is not None:
            self.view.close()
            return
        self.view = FolderView(self)
        self.view.destroyed.connect(lambda *_: setattr(self, "view", None))
        self.view.show_near()

    def add_actions(self, menu):
        sub = menu.addMenu(tr("Размер по сетке"))
        for c, r in SIZES:
            a = sub.addAction(f"{c} × {r}", lambda c=c, r=r: self.set_cells(c, r))
            a.setCheckable(True)
            a.setChecked((c, r) == self.cells())
        menu.addAction(tr("Добавить программы и файлы…"), self.pick_files)
        menu.addAction(tr("Положить внутрь папку с диска…"), self.pick_folder)
        if self.items():
            menu.addAction(tr("Открыть папку целиком"), self.open_view)
        menu.addAction(tr("Название…"), self.rename)
        a = menu.addAction(tr("Подписи под значками"), lambda: self.set_labels(not self.labels()))
        a.setCheckable(True)
        a.setChecked(self.labels())
        a = menu.addAction(tr("Ярлыки со стола — переносить в папку"),
                           lambda: self.set_takes_desktop(not self.takes_desktop()))
        a.setCheckable(True)
        a.setChecked(self.takes_desktop())
        if self.moved():
            menu.addAction(tr("Вернуть всё на рабочий стол"), self.release_all)
        if activity.copies:
            menu.addAction(tr("Ещё одна папка"), lambda: activity.copies.add_copy(self.copy_of or self.key, self))

    def contextMenuEvent(self, event):
        hit = self.hit(QPointF(event.pos()) / self.scale())
        if hit not in (None, "more"):
            item_menu(self, self, hit)
            return
        super().contextMenuEvent(event)

    # ---------- мышь ----------

    def hit(self, pos):
        for rect, what in self.cells_hit:
            if rect.contains(pos):
                return what
        return None

    def click(self, pos):
        return False  # тащить можно за любое место; короткое нажатие — tap

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton:
            self.pressed = self.hit(event.position() / self.scale())
            self.update()

    def mouseMoveEvent(self, event):
        if self.pressed is not None and getattr(self, "_press", None):
            if (event.globalPosition().toPoint() - self._press[0]).manhattanLength() >= 5:
                self.pressed = None  # потянули — это перетаскивание, не нажатие
                self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if self.pressed is not None:
            self.pressed = None
            self.update()

    def tap(self, pos):
        if not self.items():
            QTimer.singleShot(0, self.pick_files)
            return
        if self.cells() == (1, 1):  # маленькая папка — значки мелкие, нажатие раскрывает её
            self.open_view()
            return
        what = self.hit(pos)
        if what == "more":
            self.open_view()
        elif what:
            self.launch(what)

    # перетащить ярлыки / файлы / папки из Проводника.
    # Действие — «ссылка» (или «копия»), НИКОГДА не «перемещение»: Проводник на ответ «переместили» сам удаляет
    # исходный файл (так он делает перенос в чужую программу), и файл пропал бы с диска. Ярлыки со стола
    # переносим сами (take), остальное остаётся где лежит.
    @staticmethod
    def _drop_action(event):
        if not [u for u in event.mimeData().urls() if u.isLocalFile()]:
            event.ignore()
            return False
        event.setDropAction(Qt.LinkAction if event.possibleActions() & Qt.LinkAction else Qt.CopyAction)
        event.accept()
        return True

    def dragEnterEvent(self, event):
        self._drop_action(event)

    def dragMoveEvent(self, event):
        self._drop_action(event)

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if self._drop_action(event):
            QTimer.singleShot(0, lambda: self.add_paths(paths))  # после ответа Проводнику: он ждёт, пока мы вернём

    def closeEvent(self, event):
        if self.view is not None:
            self.view.close()
        super().closeEvent(event)

    # ---------- рисование ----------

    def paintEvent(self, event):
        super().paintEvent(event)  # стекло
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        r = QRectF(self.card())
        dark = bool(self.dark)
        items = self.items()
        self.cells_hit = []
        if not items:
            draw_add(p, r, dark, tr("Добавить программы"), tr("или перетащи сюда ярлыки"))
            return
        small = self.cells() == (1, 1)
        # заголовок
        f = QFont("Segoe UI Semibold")
        f.setPixelSize(13 if small else 14)
        p.setFont(f)
        p.setPen(QColor(240, 241, 246) if dark else QColor(28, 29, 34))
        head = QRectF(r.left() + 16, r.top() + 10, r.width() - 32, 20)
        p.drawText(head, Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetricsF(f).elidedText(self.folder_title(), Qt.ElideRight, head.width()))
        if small:  # 2 × 2 мелких значка, как маленькая папка на телефоне
            area = QRectF(r.left() + 18, head.bottom() + 8, r.width() - 36, r.bottom() - head.bottom() - 22)
            s = min(area.width(), area.height())
            box = QRectF(area.center().x() - s / 2, area.top(), s, s)
            step = s / 2
            for i, path in enumerate(items[:4]):
                cell = QRectF(box.left() + (i % 2) * step + 5, box.top() + (i // 2) * step + 5, step - 10, step - 10)
                draw_icon(p, cell, path, dark)
            self.cells_hit = [(QRectF(r), "more")]
            return
        labels = self.labels()
        cell_h = CELL_H if labels else CELL_W - 10
        area = QRectF(r.left() + 10, head.bottom() + 6, r.width() - 20, r.bottom() - head.bottom() - 12)
        cols = max(1, int(area.width() // CELL_W))
        rows = max(1, int(area.height() // cell_h))
        cap = cols * rows
        cw = area.width() / cols
        top = area.top() + (area.height() - rows * cell_h) * 0.3  # свободное место — больше снизу: сетка ближе к названию
        show = items if len(items) <= cap else items[:cap - 1]
        for i in range(min(len(items), cap)):
            col, row = i % cols, i // cols
            cell = QRectF(area.left() + col * cw, top + row * cell_h, cw, cell_h)
            ic = QRectF(cell.center().x() - ICON / 2, cell.top() + 6, ICON, ICON)
            if i < len(show):
                path = show[i]
                draw_icon(p, ic, path, dark, 0.88 if self.pressed == path else 1.0)
                if labels:
                    draw_label(p, QRectF(cell.left() + 3, ic.bottom() + 5, cell.width() - 6, 16), item_name(path), dark)
                self.cells_hit.append((cell, path))
            else:  # не влезли — «ещё» с маленькими значками и «+N»
                rest = items[cap - 1:]
                draw_stack(p, ic, rest, dark, len(rest))
                if labels:
                    draw_label(p, QRectF(cell.left() + 3, ic.bottom() + 5, cell.width() - 6, 16), tr("Ещё"), dark)
                self.cells_hit.append((cell, "more"))


# ---------------------------------------------------------------- раскрытая папка

class FolderView(QWidget):
    """Папка целиком — окно поверх стола: название и все значки сеткой (как раскрытая папка в ColorOS).
    Клик мимо, Esc или запуск программы — закрывается.
    Окно НЕ становится активным (не Qt.Popup): активное окно сменилось — все виджеты переставляли себя
    «поверх всех / под окна» и переснимали стекло по три раза, и при открытии папки мигало всё. Поэтому
    клики мимо и Esc ловим сами (опрос мыши и клавиши), а в снимки стекла соседей окно не попадает."""

    def __init__(self, folder):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.watch = QTimer(self, interval=30, timeout=self._watch)
        self._armed = False  # кнопки мыши отпустили после открытия — дальше нажатие мимо закрывает
        self.folder = folder
        self.offset = 0.0
        self.hits = []
        self.pressed = None
        self.drag_item = None     # значок, который тащат (порядок)
        self.drag_pos = None
        self.drag_to = 0
        self.press_at = None
        self.t = 0.0
        self.anim = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=220)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.anim.valueChanged.connect(self._step)
        loader().loaded.connect(self._icon_ready)
        self.relayout()

    def _icon_ready(self, _path):
        self.update()

    def _step(self, v):
        self.t = float(v)
        self.update()

    def relayout(self):
        n = max(1, len(self.folder.items()))
        cols = min(VIEW_COLS, n)
        rows = min(VIEW_ROWS, (n + VIEW_COLS - 1) // VIEW_COLS)
        self.cols = max(cols, 3)
        self.resize(int(self.cols * VIEW_CELL_W + 48), int(rows * VIEW_CELL_H + 86))
        self.update()

    def show_near(self):
        f = self.folder
        c = f.mapToGlobal(f.card().center() * f.scale())
        screen = QApplication.screenAt(c) or QApplication.primaryScreen()
        g = screen.availableGeometry()
        x = max(g.left() + 12, min(c.x() - self.width() // 2, g.right() - 12 - self.width()))
        y = max(g.top() + 12, min(c.y() - self.height() // 2, g.bottom() - 12 - self.height()))
        self.open_at(x, y)

    def open_at(self, x, y):
        self.move(x, y)
        self.show()
        hwnd = int(self.winId())
        try:
            u32 = ctypes.windll.user32
            u32.SetWindowLongW(hwnd, -20, u32.GetWindowLongW(hwnd, -20) | 0x08000000)  # WS_EX_NOACTIVATE
            import glass
            glass.exclude_from_capture(hwnd)  # соседние виджеты не снимают папку себе в стекло
        except Exception as err:
            applog.error("folder.view", err)
        self.anim.start()
        self.watch.start()

    def _watch(self):
        """Окно не активное — клик мимо и Esc сами до него не дойдут: смотрим кнопки мыши и Esc."""
        u32 = ctypes.windll.user32
        down = any(u32.GetAsyncKeyState(vk) & 0x8000 for vk in (0x01, 0x02, 0x04))
        if not down:
            self._armed = True
        elif self._armed and self.drag_item is None and QApplication.activePopupWidget() is None \
                and not self.geometry().contains(QCursor.pos()):
            self.close()
            return
        if u32.GetAsyncKeyState(0x1B) & 0x8000:  # Esc
            self.close()

    def area(self):
        box = QRectF(self.rect()).adjusted(4, 4, -4, -4)
        return QRectF(box.left() + 20, box.top() + 60, box.width() - 40, box.height() - 72)

    def content_height(self):
        n = len(self.folder.items())
        return ((n + self.cols - 1) // self.cols) * VIEW_CELL_H

    def wheelEvent(self, event):
        visible = self.height() - 86
        top = max(0.0, self.content_height() - visible)
        self.offset = max(0.0, min(top, self.offset - event.angleDelta().y() / 2))
        self.update()

    def hit(self, pos):
        for rect, path in self.hits:
            if rect.contains(pos):
                return path
        return None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.pressed = self.hit(event.position())
            self.press_at = event.position()
            self.update()

    def index_at(self, pos):
        """Куда встанет перетаскиваемый значок: номер клетки под мышью."""
        area = self.area()
        cw = area.width() / self.cols
        col = max(0, min(self.cols - 1, int((pos.x() - area.left()) // cw)))
        row = max(0, int((pos.y() - area.top() + self.offset) // VIEW_CELL_H))
        return min(len(self.folder.items()) - 1, row * self.cols + col)

    def mouseMoveEvent(self, event):
        if not event.buttons() & Qt.LeftButton or self.pressed is None or self.press_at is None:
            return
        pos = event.position()
        if self.drag_item is None and (pos - self.press_at).manhattanLength() >= 8:
            self.drag_item = self.pressed  # потянули значок — меняем порядок
        if self.drag_item is not None:
            self.drag_pos = pos
            self.drag_to = self.index_at(pos)
            area = self.area()  # у края — прокрутка
            top = max(0.0, self.content_height() - area.height())
            if pos.y() > area.bottom() - 16:
                self.offset = min(top, self.offset + 8)
            elif pos.y() < area.top() + 16:
                self.offset = max(0.0, self.offset - 8)
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        if self.drag_item is not None:
            path, to = self.drag_item, self.drag_to
            self.drag_item = self.drag_pos = self.pressed = None
            self.folder.move_item(path, to)
            self.update()
            return
        if self.pressed is not None:
            path, self.pressed = self.pressed, None
            if self.hit(event.position()) == path:
                folder = self.folder
                self.close()  # сначала закрыть: запуск программы может увести фокус, а окно — уже удалиться
                folder.launch(path)
                return
            self.update()

    def contextMenuEvent(self, event):
        path = self.hit(QPointF(event.pos()))
        if path:
            item_menu(self, self.folder, path)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        dark = bool(self.folder.dark) if self.folder.dark is not None else True
        k = 0.9 + 0.1 * self.t
        p.setOpacity(self.t)
        p.translate(self.width() / 2, self.height() / 2)
        p.scale(k, k)
        p.translate(-self.width() / 2, -self.height() / 2)
        box = QRectF(self.rect()).adjusted(4, 4, -4, -4)
        path = QPainterPath()
        path.addRoundedRect(box, 30, 30)
        p.fillPath(path, QColor(22, 24, 32, 236) if dark else QColor(246, 247, 251, 240))
        rim, width = skins.rim_pen(box, dark)
        p.setPen(QPen(rim, width))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), 30, 30)
        f = QFont("Segoe UI Semibold")
        f.setPixelSize(20)
        p.setFont(f)
        p.setPen(QColor(244, 245, 250) if dark else QColor(24, 25, 30))
        p.drawText(QRectF(box.left() + 24, box.top() + 14, box.width() - 48, 34), Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetricsF(f).elidedText(self.folder.folder_title(), Qt.ElideRight, box.width() - 48))
        area = self.area()
        p.save()
        p.setClipRect(area)
        self.hits = []
        cw = area.width() / self.cols
        order = self.folder.items()
        if self.drag_item is not None and self.drag_item in order:  # тащат: остальные расступаются
            order = [x for x in order if x != self.drag_item]
            order.insert(self.drag_to, self.drag_item)
        for i, item in enumerate(order):
            cell = QRectF(area.left() + (i % self.cols) * cw, area.top() + (i // self.cols) * VIEW_CELL_H - self.offset,
                          cw, VIEW_CELL_H)
            if cell.bottom() < area.top() or cell.top() + 8 >= area.bottom():  # снизу виден край без значка — не клетка
                continue
            ic = QRectF(cell.center().x() - VIEW_ICON / 2, cell.top() + 8, VIEW_ICON, VIEW_ICON)
            if item == self.drag_item:  # пустое место, куда встанет
                p.setPen(QPen(QColor(255, 255, 255, 70) if dark else QColor(0, 0, 0, 50), 1.5, Qt.DashLine))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(ic.adjusted(2, 2, -2, -2), 16, 16)
                continue
            draw_icon(p, ic, item, dark, 0.88 if self.pressed == item and self.drag_item is None else 1.0)
            draw_label(p, QRectF(cell.left() + 4, ic.bottom() + 7, cell.width() - 8, 18), item_name(item), dark, 12)
            self.hits.append((cell.intersected(area), item))
        p.restore()
        if self.drag_item is not None and self.drag_pos is not None:  # значок едет за мышью, чуть крупнее
            s = VIEW_ICON * 1.12
            draw_icon(p, QRectF(self.drag_pos.x() - s / 2, self.drag_pos.y() - s / 2, s, s), self.drag_item, dark)
