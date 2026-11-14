"""Liquid Acrylic: стекло из того, что под виджетом (живой экран или обои).

Под виджетом берём картинку, размываем, у краёв «преломляем» (край как толстая
линза тянет картинку снаружи), подмешиваем молочный/тёмный оттенок.
Всё, что зависит только от размера карточки, считается один раз (кэш).
Работает в фоновом потоке: здесь нет ничего, что трогает окна Qt.
"""
from lang import tr
import ctypes
import os
import winreg
from ctypes import wintypes as wt
from functools import lru_cache

import numpy as np
import psutil
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage

PAD = 40          # запас вокруг карточки для размытия и преломления
BLUR_SCALE = 4    # размываем в уменьшенной копии — быстро и мягко
BLUR = 6          # сила размытия: больше — матовее, меньше — виднее, что под стеклом
EDGE = 18         # ширина «линзы» у края, px
REFRACT = 10      # сила преломления, px (у ColorOS — мягкое)
MILK = 0.68       # молочность светлого акрила: 0 — прозрачный, 1 — белый
FROST = 0.22      # изморозь тёмного акрила: тёмный фон чуть высветляется серым, цвета остаются


# ---------- WinAPI ----------

user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
user32.GetDC.restype = wt.HDC
user32.GetDC.argtypes = [wt.HWND]
user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.MonitorFromWindow.restype = wt.HANDLE
user32.MonitorFromWindow.argtypes = [wt.HWND, wt.DWORD]
user32.GetMonitorInfoW.argtypes = [wt.HANDLE, ctypes.c_void_p]
user32.SetWindowDisplayAffinity.argtypes = [wt.HWND, wt.DWORD]
gdi32.CreateCompatibleDC.restype = wt.HDC
gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
gdi32.CreateDIBSection.restype = wt.HBITMAP
gdi32.CreateDIBSection.argtypes = [wt.HDC, ctypes.c_void_p, wt.UINT, ctypes.c_void_p, wt.HANDLE, wt.DWORD]
gdi32.SelectObject.restype = wt.HGDIOBJ
gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
gdi32.BitBlt.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HDC,
                         ctypes.c_int, ctypes.c_int, wt.DWORD]
gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wt.HDC]


class _BMI(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
                ("biBitCount", wt.WORD), ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                ("biClrImportant", wt.DWORD)]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]


def exclude_from_capture(hwnd):
    """Окно не попадает в снимки экрана — значит, можно снимать то, что под ним."""
    return bool(user32.SetWindowDisplayAffinity(hwnd, 0x11))  # WDA_EXCLUDEFROMCAPTURE


def include_in_capture(hwnd):
    """Окно снова видно на скриншотах (и в нашем снимке экрана тоже)."""
    user32.SetWindowDisplayAffinity(hwnd, 0)  # WDA_NONE


# ---------- системный акрил Windows ----------
# Размытие того, что за окном, делает сама Windows (как у меню «Пуск»): вживую, без снимков экрана, видно и
# живые обои. Область — скруглённая карточка (SetWindowRgn), чтобы не размывалось поле под тень.

class _ACCENT(ctypes.Structure):
    _fields_ = [("state", ctypes.c_int), ("flags", ctypes.c_int), ("color", ctypes.c_uint), ("anim", ctypes.c_int)]


class _WCADATA(ctypes.Structure):
    _fields_ = [("attr", ctypes.c_int), ("data", ctypes.c_void_p), ("size", ctypes.c_size_t)]


user32.SetWindowCompositionAttribute.argtypes = [wt.HWND, ctypes.POINTER(_WCADATA)]
user32.SetWindowRgn.argtypes = [wt.HWND, wt.HRGN, wt.BOOL]
gdi32.CreateRoundRectRgn.restype = wt.HRGN


def set_backdrop(hwnd, blur, haze, dark):
    """blur (0..10): 0 — без размытия, 1..4 — лёгкое размытие Windows, 5..10 — акрил Windows;
    haze (0..100) — замутнение: сколько серой (тёмное) / молочной (светлое) дымки поверх размытого."""
    state = 2 if blur <= 0 else 3 if blur < 5 else 4  # TRANSPARENTGRADIENT / BLURBEHIND / ACRYLICBLURBEHIND
    alpha = max(1, min(255, int(2 + 2.3 * haze)))
    r, g, b = (34, 34, 38) if dark else (242, 242, 246)
    accent = _ACCENT(state, 0, (alpha << 24) | (b << 16) | (g << 8) | r, 0)
    data = _WCADATA(19, ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p), ctypes.sizeof(accent))  # WCA_ACCENT_POLICY
    user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data))


def clear_backdrop(hwnd):
    accent = _ACCENT(0, 0, 0, 0)
    data = _WCADATA(19, ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p), ctypes.sizeof(accent))
    user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data))
    user32.SetWindowRgn(hwnd, None, True)


def round_region(hwnd, x, y, w, h, radius):
    """Окно видно (и размыто) только в скруглённом прямоугольнике — физические пиксели окна."""
    rgn = gdi32.CreateRoundRectRgn(x, y, x + w + 1, y + h + 1, 2 * radius, 2 * radius)
    user32.SetWindowRgn(hwnd, rgn, True)  # регион теперь принадлежит окну — удалять не надо


class Backdrop:
    """Подложка с акрилом Windows под карточкой виджета. Окна Qt прозрачные («слоистые»), а такие Windows
    размывает целиком, вместе с полем под тень и без скругления. Поэтому размывает отдельное простое окно ровно
    по карточке (скруглённое SetWindowRgn), а виджет лежит прямо над ним и рисует только содержимое."""

    _wc = None

    def __init__(self):
        if Backdrop._wc is None:
            Backdrop._proc = _WNDPROC(lambda h, m, w, l: user32.DefWindowProcW(h, m, w, l))
            Backdrop._wc = _WNDCLASS(0, Backdrop._proc, 0, 0, _kernel32.GetModuleHandleW(None), None, None, None,
                                     None, "LiquidWidgetBackdrop")
            user32.RegisterClassW(ctypes.byref(Backdrop._wc))
        # всплывающее, не активируется, не в Alt+Tab и не на панели задач
        self.hwnd = user32.CreateWindowExW(0x08000000 | 0x80, "LiquidWidgetBackdrop", "", 0x80000000,
                                           0, 0, 1, 1, None, None, _kernel32.GetModuleHandleW(None), None)
        self.geom = None
        self.look = None

    def follow(self, above, x, y, w, h, radius):
        """Встать под окно above (сразу под ним в стопке) в прямоугольник (x, y, w, h) — физические пиксели."""
        if not self.hwnd:
            return
        if self.geom != (w, h, radius):
            self.geom = (w, h, radius)
            round_region(self.hwnd, 0, 0, w, h, radius)
        # SWP_NOACTIVATE | SWP_SHOWWINDOW; вставка «после above» = сразу под ним
        user32.SetWindowPos(self.hwnd, above, x, y, w, h, 0x0010 | 0x0040)

    def style(self, blur, haze, dark):
        if self.hwnd and self.look != (blur, haze, dark):
            self.look = (blur, haze, dark)
            set_backdrop(self.hwnd, blur, haze, dark)

    def hide(self):
        if self.hwnd:
            user32.ShowWindow(self.hwnd, 0)

    def destroy(self):
        if self.hwnd and user32.IsWindow(self.hwnd):
            user32.DestroyWindow(self.hwnd)
        self.hwnd = None


# ---------- клавиши скриншота ----------

WH_KEYBOARD_LL, WM_KEYDOWN, WM_SYSKEYDOWN = 13, 0x0100, 0x0104
VK_SNAPSHOT, VK_S, VK_SHIFT, VK_LWIN, VK_RWIN = 0x2C, 0x53, 0x10, 0x5B, 0x5C
_HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wt.WPARAM, wt.LPARAM)
user32.SetWindowsHookExW.restype = wt.HHOOK
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, _HOOKPROC, wt.HINSTANCE, wt.DWORD]
user32.CallNextHookEx.restype = ctypes.c_ssize_t
user32.CallNextHookEx.argtypes = [wt.HHOOK, ctypes.c_int, wt.WPARAM, wt.LPARAM]
user32.GetAsyncKeyState.restype = ctypes.c_short


class _KBD(ctypes.Structure):
    _fields_ = [("vkCode", wt.DWORD), ("scanCode", wt.DWORD), ("flags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


def watch_screenshot_keys(callback):
    """Ловит PrtSc (с любыми Alt/Win) и Win+Shift+S и сразу зовёт callback — до того, как
    Windows снимет экран. Смотрим только эти клавиши, ничего не записываем и не глотаем.
    Работает в главном потоке (там крутится очередь сообщений Qt)."""
    def down(vk):
        return user32.GetAsyncKeyState(vk) & 0x8000

    def proc(code, wparam, lparam):
        if code == 0 and wparam in (WM_KEYDOWN, WM_SYSKEYDOWN):
            vk = ctypes.cast(lparam, ctypes.POINTER(_KBD))[0].vkCode
            if vk == VK_SNAPSHOT or (vk == VK_S and down(VK_SHIFT) and (down(VK_LWIN) or down(VK_RWIN))):
                try:
                    callback()
                except Exception:
                    pass
        return user32.CallNextHookEx(None, code, wparam, lparam)

    watch_screenshot_keys.proc = _HOOKPROC(proc)  # держим ссылку, иначе сборщик мусора убьёт callback
    return user32.SetWindowsHookExW(WH_KEYBOARD_LL, watch_screenshot_keys.proc, None, 0)


def window_rect(hwnd):
    """Окно и его монитор в физических пикселях: (l, t, r, b), (l, t, r, b)."""
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    mi = _MONITORINFO(ctypes.sizeof(_MONITORINFO))
    user32.GetMonitorInfoW(user32.MonitorFromWindow(hwnd, 2), ctypes.byref(mi))
    m = mi.rcMonitor
    return (r.left, r.top, r.right, r.bottom), (m.left, m.top, m.right, m.bottom)


_dwm = ctypes.WinDLL("dwmapi")


def cover_rect(hwnd):
    """Где окно видно на самом деле (физ. пиксели) или None, если свёрнуто. GetWindowRect включает
    невидимую рамку для растягивания (~8 px с каждой стороны) — по ней окно у края монитора «заходило»
    на соседний и замораживало стекло виджетов, которых не касалось."""
    if not hwnd or user32.IsIconic(hwnd) or not user32.IsWindowVisible(hwnd):
        return None
    r = wt.RECT()
    if _dwm.DwmGetWindowAttribute(wt.HWND(hwnd), 9, ctypes.byref(r), ctypes.sizeof(r)) != 0:  # EXTENDED_FRAME_BOUNDS
        user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def hides(cover, win, margin):
    """Окно cover закрывает карточку виджета win целиком (margin — прозрачное поле тени вокруг карточки)."""
    return cover is not None and cover[0] <= win[0] + margin and cover[1] <= win[1] + margin \
        and win[2] - margin <= cover[2] and win[3] - margin <= cover[3]


user32.GetForegroundWindow.restype = wt.HWND
user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]

DESKTOP_CLASSES = {"Progman", "WorkerW"}
SHELL_CLASSES = {"Shell_TrayWnd", "Shell_SecondaryTrayWnd", "NotifyIconOverflowWindow",
                 "TopLevelWindowForOverflowXamlIsland", "XamlExplorerHostIslandWindow"}


def foreground():
    """Чем занят пользователь: 'desktop', 'window', 'fullscreen' или None (панель задач — не считается)."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return "desktop"
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    if buf.value in DESKTOP_CLASSES:
        return "desktop"
    if buf.value in SHELL_CLASSES:
        return None
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value == os.getpid():  # наш виджет или меню — как стол; окно каталога — обычное окно
        buf2 = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf2, 256)
        return "window" if buf2.value == tr("Виджеты") else "desktop"
    win, monitor = window_rect(hwnd)
    return "fullscreen" if win == monitor else "window"


def _grab_parts(x, y, w, h, parts):
    """Один BitBlt куска экрана (x, y, w, h — физ. пиксели); parts — [((x0, y0, x1, y1), fn), ...]:
    каждому куску внутри снимка — своя обработка fn(BGRA-вид (h, w, 4)), пока память снимка жива.
    fn=None — кусок как RGB-массив (h, w, 3)."""
    sdc = user32.GetDC(None)
    mdc = gdi32.CreateCompatibleDC(sdc)
    bmi = _BMI(ctypes.sizeof(_BMI), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    bits = ctypes.c_void_p()
    bmp = gdi32.CreateDIBSection(mdc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
    old = gdi32.SelectObject(mdc, bmp)
    try:
        gdi32.BitBlt(mdc, 0, 0, w, h, sdc, x, y, 0x00CC0020)  # SRCCOPY
        buf = np.ctypeslib.as_array(ctypes.cast(bits, ctypes.POINTER(ctypes.c_uint8)), (h, w, 4))
        out = []
        for (x0, y0, x1, y1), fn in parts:
            view = buf[y0 - y:y1 - y, x0 - x:x1 - x]
            out.append(fn(view) if fn else view[..., 2::-1].copy())  # копия: память снимка ниже освобождаем
        return out
    finally:
        gdi32.SelectObject(mdc, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mdc)
        user32.ReleaseDC(None, sdc)


def _grab(x, y, w, h):
    """Кусок экрана (физ. пиксели) -> массив (h, w, 3) RGB."""
    return _grab_parts(x, y, w, h, [((x, y, x + w, y + h), None)])[0]


def _shrink(bgra, w, h):
    """BGRA-кусок снимка -> RGB (h, w, 3) уменьшенный силами Qt (сглаженно), без перевода в RGB целиком:
    в памяти Windows BGRA — это QImage.Format_RGB32 как есть."""
    a = np.ascontiguousarray(bgra)
    img = QImage(a.data, a.shape[1], a.shape[0], a.shape[1] * 4, QImage.Format_RGB32)
    img = img.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).convertToFormat(QImage.Format_RGB888)
    out = np.frombuffer(img.constBits(), np.uint8, img.sizeInBytes())
    return out.reshape(h, img.bytesPerLine())[:, :w * 3].reshape(h, w, 3).copy()


def small_size(W, H):
    """Размер уменьшенной копии, в которой стекло размывается и красится (W, H — кусок с запасом PAD)."""
    return W // BLUR_SCALE, H // BLUR_SCALE


# Цена BitBlt с экрана (замер, 1080p, Windows 11): ~5 мс на сам вызов (DWM отдаёт кадр) + ~6.5 мс
# на каждый миллион пикселей. Отсюда выбор: один общий снимок или по снимку на карточку.
BLT_CALL_MS = 5.0
BLT_MPX_MS = 6.5


def capture_rect(win, inset, w, h, dpr):
    """Где на экране (физ. пиксели) лежит то, что под карточкой, с запасом PAD."""
    W, H = w + 2 * PAD, h + 2 * PAD
    return (win[0] + round((inset - PAD) * dpr), win[1] + round((inset - PAD) * dpr),
            round(W * dpr), round(H * dpr), W, H)


def capture_many(monitor, rects):
    """Несколько кусков экрана одного монитора -> для каждого уменьшенная копия (см. small_size), из неё
    render и считает стекло: полный размер стеклу не нужен (размывает в 4 раза меньшей), а на переводе
    и хранении полного снимка уходило больше, чем на всё стекло. Одним общим снимком или каждый своим —
    что дешевле по цене BitBlt (сам вызов дорогой, но и лишние пиксели между карточками не бесплатны)."""
    clipped = []
    for x, y, pw, ph, W, H in rects:
        c = (max(x, monitor[0]), max(y, monitor[1]), min(x + pw, monitor[2]), min(y + ph, monitor[3]))
        clipped.append(c if c[0] < c[2] and c[1] < c[3] else None)
    jobs = []
    for (x, y, pw, ph, W, H), c in zip(rects, clipped):
        if c is None:
            continue
        pads = ((c[1] - y, y + ph - c[3]), (c[0] - x, x + pw - c[2]), (0, 0))

        def fn(view, pads=pads, size=small_size(W, H)):
            if any(a or b for a, b in pads):  # край карточки за экраном — дорисовать краевыми пикселями
                view = np.pad(view, pads, mode="edge")
            return _shrink(view, *size)
        jobs.append((c, fn))
    if not jobs:
        return [None] * len(rects)
    live = [c for c, _ in jobs]
    ux0, uy0 = min(c[0] for c in live), min(c[1] for c in live)
    ux1, uy1 = max(c[2] for c in live), max(c[3] for c in live)
    cost = lambda area: BLT_CALL_MS + BLT_MPX_MS * area / 1e6
    if cost((ux1 - ux0) * (uy1 - uy0)) <= sum(cost((c[2] - c[0]) * (c[3] - c[1])) for c in live):
        shots = iter(_grab_parts(ux0, uy0, ux1 - ux0, uy1 - uy0, jobs))
    else:
        shots = iter(_grab_parts(c[0], c[1], c[2] - c[0], c[3] - c[1], [(c, fn)])[0] for c, fn in jobs)
    return [None if c is None else next(shots) for c in clipped]


def capture(win, monitor, inset, w, h, dpr):
    """Что под одной карточкой, с запасом PAD; размер в логических пикселях."""
    return capture_many(monitor, [capture_rect(win, inset, w, h, dpr)])[0]


# ---------- обои ----------

def _wallpaper_path():
    buf = ctypes.create_unicode_buffer(520)
    user32.SystemParametersInfoW(0x73, 520, buf, 0)  # SPI_GETDESKWALLPAPER
    path = buf.value
    if path and os.path.exists(path):
        return path
    cached = os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Themes\TranscodedWallpaper")
    return cached if os.path.exists(cached) else ""


def _reg(key, name, default):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return default


def to_array(img):
    img = img.convertToFormat(QImage.Format_RGBA8888)
    arr = np.frombuffer(img.constBits(), np.uint8, img.sizeInBytes())
    return arr.reshape(img.height(), img.bytesPerLine() // 4, 4)[:, :img.width(), :3].copy()


def to_image(rgba):
    """RGBA-массив -> QImage сразу в «родном» формате Qt (premultiplied): иначе Qt переводит картинку
    при каждой перерисовке (у часов с плавной стрелкой — 30 раз в секунду)."""
    rgba = np.ascontiguousarray(rgba)
    h, w = rgba.shape[:2]
    return QImage(rgba.data, w, h, w * 4, QImage.Format_RGBA8888).convertToFormat(QImage.Format_ARGB32_Premultiplied)


class Wallpaper:
    """Обои, разложенные по экрану так же, как у Windows (заполнение/вписать/растянуть)."""

    def __init__(self):
        self.key = None
        self.screens = {}

    def changed(self):
        path = _wallpaper_path()
        mtime = os.path.getmtime(path) if path else 0
        key = (path, mtime, _reg(r"Control Panel\Desktop", "WallpaperStyle", "10"))
        if key != self.key:
            self.key = key
            self.screens = {}
            return True
        return False

    def for_screen(self, w, h):
        if self.key is None:
            self.changed()
        if (w, h) not in self.screens:
            self.screens[(w, h)] = self._build(w, h)
        return self.screens[(w, h)]

    def _build(self, w, h):
        path, _, style = self.key
        img = QImage(path) if path else QImage()
        if img.isNull():
            r, g, b = (int(v) for v in _reg(r"Control Panel\Colors", "Background", "0 90 160").split())
            return np.full((h, w, 3), (r, g, b), np.uint8)
        style = str(style)
        if style == "2":  # растянуть
            img = img.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        elif style == "6":  # вписать
            img = img.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        else:  # заполнить (и всё остальное)
            img = img.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        arr = to_array(img)
        out = np.zeros((h, w, 3), np.uint8)
        ih, iw = arr.shape[:2]
        sy, sx = max(0, (ih - h) // 2), max(0, (iw - w) // 2)
        dy, dx = max(0, (h - ih) // 2), max(0, (w - iw) // 2)
        ch, cw = min(h, ih), min(w, iw)
        out[dy:dy + ch, dx:dx + cw] = arr[sy:sy + ch, sx:sx + cw]
        return out


wallpaper = Wallpaper()


def from_wallpaper(screen_geo, card):
    """Кусок обоев под карточкой с запасом PAD (логические пиксели, QRect)."""
    arr = wallpaper.for_screen(screen_geo.width(), screen_geo.height())
    return _crop(arr, card.x() - screen_geo.x() - PAD, card.y() - screen_geo.y() - PAD,
                 card.width() + 2 * PAD, card.height() + 2 * PAD)


def _crop(arr, x, y, w, h):
    H, W = arr.shape[:2]
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, W), min(y + h, H)
    if x0 >= x1 or y0 >= y1:
        return np.full((h, w, 3), arr.mean(axis=(0, 1)), np.uint8)
    part = arr[y0:y1, x0:x1]
    return np.pad(part, ((y0 - y, y + h - y1), (x0 - x, x + w - x1), (0, 0)), mode="edge")


# ---------- математика ----------

def _box(a, r, axis):
    n = a.shape[axis]
    # края — копии крайнего ряда (как np.pad mode="edge"), но без np.pad: на маленьких картинках он медленный
    first = np.take(a, [0], axis=axis)
    last = np.take(a, [n - 1], axis=axis)
    c = np.cumsum(np.concatenate([np.repeat(first, r + 1, axis=axis), a, np.repeat(last, r, axis=axis)],
                                 axis=axis), axis=axis)
    # срезы, а не np.take по списку индексов: то же самое без лишних копий (размытие стало в ~2 раза быстрее)
    hi = [slice(None)] * a.ndim
    lo = [slice(None)] * a.ndim
    hi[axis], lo[axis] = slice(2 * r + 1, 2 * r + 1 + n), slice(0, n)
    return (c[tuple(hi)] - c[tuple(lo)]) / (2 * r + 1)


def blur(a, r):
    for _ in range(3):  # три box-размытия ≈ гаусс
        a = _box(_box(a, r, 0), r, 1)
    return a


def rounded_sdf(w, h, radius, ox=0.0, oy=0.0):
    """Расстояние до края скруглённого прямоугольника: <0 внутри, >0 снаружи."""
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    px = np.abs(x + 0.5 - ox - w / 2) - (w / 2 - radius)
    py = np.abs(y + 0.5 - oy - h / 2) - (h / 2 - radius)
    outside = np.hypot(np.maximum(px, 0), np.maximum(py, 0))
    return outside + np.minimum(np.maximum(px, py), 0) - radius


@lru_cache(maxsize=16)
def _geometry(w, h, radius):
    """Всё, что зависит только от размера: полоса у края, откуда её пиксели берут цвет
    (с преломлением), маска скругления."""
    sdf = rounded_sdf(w, h, radius)
    gy, gx = np.gradient(sdf)
    norm = np.hypot(gx, gy) + 1e-6
    nx, ny = gx / norm, gy / norm
    t = np.clip(1 + sdf / EDGE, 0, 1) ** 2
    band = np.flatnonzero((t > 0) & (sdf < 1))  # линза у края; середину копируем как есть
    Wb = (w + 2 * PAD) // BLUR_SCALE * BLUR_SCALE  # размер увеличенной копии
    Hb = (h + 2 * PAD) // BLUR_SCALE * BLUR_SCALE
    y, x = np.divmod(band, w)
    tb, nxb, nyb = t.ravel()[band], nx.ravel()[band], ny.ravel()[band]
    taps = []
    # у каждого цвета своя сила преломления — лёгкая радуга по краю
    for k in (1.12, 1.0, 0.88):
        sx = np.clip(np.rint(x + PAD + nxb * tb * REFRACT * k), 0, Wb - 1).astype(np.int32)
        sy = np.clip(np.rint(y + PAD + nyb * tb * REFRACT * k), 0, Hb - 1).astype(np.int32)
        taps.append(sy * Wb + sx)
    alpha = (np.clip(0.5 - sdf, 0, 1) * 255).astype(np.uint8)
    light = {dark: _lighting(sdf, nx, ny, h, dark).ravel() for dark in (False, True)}
    return band, taps, light, alpha, Wb, Hb


def _lighting(sdf, nx, ny, h, dark):
    """Свет в толще акрила (прибавка к яркости, 0..255), как у ColorOS 17:
    светлый — сверху чуть темнее, книзу светлеет, самый яркий край снизу (свет собирается
    в кромке); тёмный — светлее сверху; по краю мягкая светлая кромка."""
    yn = (np.arange(h, dtype=np.float32)[:, None] + 0.5) / h
    rim = np.clip(1 + sdf / 7, 0, 1) ** 1.5           # узкая кромка ~7 px
    inner = np.clip(1 + sdf / 22, 0, 1) - rim          # полоса под кромкой
    down, up = np.maximum(ny, 0), np.maximum(-ny, 0)  # край смотрит вниз / вверх
    if dark:
        # как в шторке ColorOS: блик в верхней трети, тонкая светлая кромка (ярче сверху и снизу)
        # и мягкий отсвет под ней
        v = 12 * np.clip(1 - yn / 0.35, 0, 1) ** 2
        line = np.clip(1 + sdf / 2.5, 0, 1)
        edge = line * 30 * (0.45 + 0.55 * up + 0.5 * down) + np.clip(1 + sdf / 10, 0, 1) ** 2 * 9
        shade = 0
    else:
        v = 24 * np.clip((yn - 0.45) / 0.55, 0, 1) ** 2
        glow = np.clip(1 + sdf / 16, 0, 1) ** 2 * 46 * down        # низ кромки светится
        dim = np.clip(1 + sdf / 12, 0, 1) * 12 * (1 - down)         # верх и бока — видна толщина, чуть серее
        edge, shade = glow - dim, -inner * 6 * np.maximum(nx, 0)
    return np.rint(v + edge + shade).astype(np.int16)


def _resize(arr, w, h):
    """RGB-массив -> другой размер силами Qt (сглаженно). arr жив, пока Qt читает его память."""
    arr = np.ascontiguousarray(arr)
    img = QImage(arr.data, arr.shape[1], arr.shape[0], arr.shape[1] * 3, QImage.Format_RGB888)
    img = img.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).convertToFormat(QImage.Format_RGB888)
    out = np.frombuffer(img.constBits(), np.uint8, img.sizeInBytes())
    return out.reshape(h, img.bytesPerLine())[:, :w * 3].reshape(h, w, 3).copy()


# ---------- стекло ----------

HAZE_MIN = -50  # замутнение ниже нуля: дымки уже нет — убираем и приглушение цветов


def juice(haze):
    """Замутнение в минусе -> насколько сочнее цвета под стеклом: 0 (при 0 и выше) .. 1 (при HAZE_MIN)."""
    if haze is None or haze >= 0:
        return 0.0
    return min(1.0, haze / HAZE_MIN)


def haze_amount(haze, dark):
    """Замутнение (настройка 0..100, 50 — как было) -> доля серой (тёмное) или молочной (светлое) подмеси."""
    if haze is None:
        return FROST if dark else MILK
    t = max(0, min(100, haze)) / 100
    # 50 — как стекло в шторке ColorOS (тёмное: ~0.4 тёмной дымки, светлое: ~0.7 молочной), 100 — почти сплошная
    return 0.95 * t ** 0.9 if dark else 0.97 * t ** 0.5


TO_LIGHT, TO_DARK = 0.40, 0.34  # яркость фона: светлее — светлая тема, темнее — тёмная (между — как была)


def theme_for(lum, prev=None):
    """Тёмная ли тема над фоном яркости lum. Светлое (розовое закатное небо ~0.4) — уже светлая тема.
    Между порогами тема не меняется — иначе над пограничным местом живые обои дёргали бы её туда-сюда.
    prev — прошлая тема или функция prev(lum), которая её выбирает."""
    if callable(prev):
        prev = prev(lum)
    if prev is True:
        return lum < TO_LIGHT
    if prev is False:
        return lum < TO_DARK
    return lum < (TO_LIGHT + TO_DARK) / 2


def render(src, w, h, radius, theme="auto", fill=None, blur_r=None, haze=None, prev=None):
    """Картинка стекла размером с карточку + признак тёмной темы. fill (%) — плотность, как у изморози;
    не задана — стекло сплошное. blur_r — сила размытия (0..10, по умолчанию BLUR), haze — замутнение (0..100).

    Цвет считаем в маленькой (размытой) копии — она в 16 раз меньше; увеличиваем силами Qt;
    преломление — только в полосе у края."""
    band, taps, light, alpha, Wb, Hb = _geometry(w, h, radius)
    Ws, Hs = Wb // BLUR_SCALE, Hb // BLUR_SCALE
    # из capture_many снимок приходит уже уменьшенным (small_size); из обоев и превью — полным
    small = src if src.shape[:2] == (Hs, Ws) else _resize(src, Ws, Hs)
    small = blur(small.astype(np.float32) / 255, BLUR if blur_r is None else max(0, min(10, int(blur_r))))

    lum = float((small[..., 0] * 0.3 + small[..., 1] * 0.59 + small[..., 2] * 0.11).mean())
    dark = theme_for(lum, prev) if theme == "auto" else theme == "dark"
    # насыщенность как у акрила + молочный (светлый) или дымчатый (тёмный) оттенок;
    # цвета под стеклом остаются мягкими цветными пятнами
    gray = small.mean(axis=2, keepdims=True)
    k = haze_amount(haze, dark)
    vivid = juice(haze)
    if dark:
        # тёмный акрил: цвета под ним приглушены и притемнены (рыжее за стеклом — тёплый тёмно-серый, не рыжий);
        # замутнение в минусе — приглушения меньше: сочные цвета под тёмным стеклом
        small = (gray + (small - gray) * (0.5 + 0.6 * vivid)) * (0.8 + 0.15 * vivid)
        small = small * (1 - k) + np.array([0.12, 0.12, 0.14], np.float32) * k
    else:
        small = gray + (small - gray) * (1.15 + 0.35 * vivid)
        small = small * (1 - k) + np.array([0.93, 0.93, 0.95], np.float32) * k
    small = np.clip(small * 255, 0, 255).astype(np.uint8)
    big = _resize(small, Wb, Hb)

    # свет в толще акрила + преломление у края
    lit = light[dark]
    rgb = big[PAD:PAD + h, PAD:PAD + w].reshape(-1, 3).astype(np.int16)
    bigf = big.reshape(-1, 3)
    for ch, idx in enumerate(taps):
        rgb[band, ch] = bigf[idx, ch]
    rgb += lit[:, None]
    rgba = np.empty((h, w, 4), np.uint8)
    rgba[..., :3] = np.clip(rgb, 0, 255).reshape(h, w, 3)
    rgba[..., 3] = alpha if fill is None else (alpha.astype(np.float32) * fill / 100).astype(np.uint8)
    return to_image(rgba), dark


def render_flat(w, h, radius, dark, fill=None):
    """Стекло для виджета под ярлыками. Что за ним (живые обои, Wallpaper Engine) не снять — размыть нечего.
    Поэтому полупрозрачная изморозь: настоящие обои просвечивают сквозь неё цветом; свет и кромка — как у живого."""
    band, taps, light, alpha, Wb, Hb = _geometry(w, h, radius)
    rgb = np.empty((h * w, 3), np.int16)
    rgb[:] = (58, 58, 64) if dark else (232, 232, 236)
    rgb += light[dark][:, None]
    rgba = np.empty((h, w, 4), np.uint8)
    rgba[..., :3] = np.clip(rgb, 0, 255).reshape(h, w, 3)
    # заливка (настройка, %): 100 — сплошная матовая плитка; не задана — своя для темы
    k = fill / 100 if fill is not None else (0.62 if dark else 0.72)
    rgba[..., 3] = (alpha.astype(np.float32) * k).astype(np.uint8)
    return to_image(rgba)


def luminance(src):
    """Средняя яркость RGB-снимка (0..1); большой (обои) — через 4 пикселя."""
    if src.shape[1] >= 200:
        src = src[::4, ::4]
    m = src.reshape(-1, 3).mean(axis=0)
    return float(m[0] * 0.3 + m[1] * 0.59 + m[2] * 0.11) / 255


def wallpaper_is_dark(screen_geo, card):
    """Обычные обои — смотрим их яркость под виджетом; живые (не снять) — считаем тёмными."""
    if not _wallpaper_path():
        return True
    src = from_wallpaper(screen_geo, card).astype(np.float32) / 255
    return theme_for(float((src[..., 0] * 0.3 + src[..., 1] * 0.59 + src[..., 2] * 0.11).mean()))


# ---------- окно под ярлыками рабочего стола ----------

_WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.CreateWindowExW.restype = wt.HWND
user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
user32.FindWindowW.restype = wt.HWND
user32.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
user32.FindWindowExW.restype = wt.HWND
user32.FindWindowExW.argtypes = [wt.HWND, wt.HWND, wt.LPCWSTR, wt.LPCWSTR]
user32.GetParent.restype = wt.HWND
user32.GetParent.argtypes = [wt.HWND]
user32.IsWindow.argtypes = [wt.HWND]
user32.DestroyWindow.argtypes = [wt.HWND]
user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT]
user32.UpdateLayeredWindow.argtypes = [wt.HWND, wt.HDC, ctypes.c_void_p, ctypes.c_void_p, wt.HDC,
                                       ctypes.c_void_p, wt.DWORD, ctypes.c_void_p, wt.DWORD]
user32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM), wt.LPARAM]
_kernel32 = ctypes.windll.kernel32
_kernel32.GetModuleHandleW.restype = wt.HMODULE


class _WNDCLASS(ctypes.Structure):
    _fields_ = [("style", wt.UINT), ("proc", _WNDPROC), ("cls", ctypes.c_int), ("wnd", ctypes.c_int),
                ("inst", wt.HINSTANCE), ("icon", wt.HICON), ("cursor", wt.HANDLE), ("bg", wt.HBRUSH),
                ("menu", wt.LPCWSTR), ("name", wt.LPCWSTR)]


class WINDOWPOS(ctypes.Structure):
    _fields_ = [("hwnd", wt.HWND), ("hwndInsertAfter", wt.HWND), ("x", ctypes.c_int), ("y", ctypes.c_int),
                ("cx", ctypes.c_int), ("cy", ctypes.c_int), ("flags", wt.UINT)]


class _BLEND(ctypes.Structure):
    _fields_ = [("op", ctypes.c_byte), ("flags", ctypes.c_byte), ("alpha", ctypes.c_ubyte), ("fmt", ctypes.c_byte)]


_desktop = {"hwnd": None}
user32.GetWindow.restype = wt.HWND
user32.GetWindow.argtypes = [wt.HWND, wt.UINT]


def desktop_window():
    """Окно рабочего стола верхнего уровня — то, в котором ярлыки (Progman или WorkerW)."""
    h = _desktop["hwnd"]
    if h and user32.IsWindow(h):
        return h
    defview = icons_layer()
    h = None
    while defview:
        parent = user32.GetParent(defview)
        if not parent:
            h = defview
            break
        defview = parent
    _desktop["hwnd"] = h or user32.FindWindowW("Progman", None)
    return _desktop["hwnd"]


def above_desktop(own):
    """Куда вставить окно own, чтобы оно было прямо над рабочим столом (для SetWindowPos/WINDOWPOS):
    окно, которое сейчас над рабочим столом (мы встанем под ним); -1 — own и так прямо над ним;
    HWND_BOTTOM (1) — рабочий стол не нашёлся."""
    desk = desktop_window()
    if not desk:
        return 1
    prev = user32.GetWindow(desk, 3)  # GW_HWNDPREV — кто над рабочим столом
    if not prev:
        return 0  # рабочий стол сверху всех (так не бывает) — тогда HWND_TOP
    if int(prev) == own:
        return -1
    return int(prev)


def live_wallpaper_running():
    """Запущены живые обои (Wallpaper Engine)? Они рисуют видео поверх всего в слое обоев —
    под ярлыками тогда ничего не видно."""
    for p in psutil.process_iter(["name"]):
        if (p.info["name"] or "").lower() in ("wallpaper32.exe", "wallpaper64.exe"):
            return True
    return False


def icons_layer():
    """Слой ярлыков (SHELLDLL_DefView). В Windows 11 24H2+ он внутри Progman; в старых — внутри
    одного из окон верхнего уровня. Наше окно кладём в того же родителя, сразу под ним."""
    progman = user32.FindWindowW("Progman", None)
    defview = user32.FindWindowExW(progman, None, "SHELLDLL_DefView", None) if progman else None
    if defview:
        return defview
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def each(hwnd, _):
        d = user32.FindWindowExW(hwnd, None, "SHELLDLL_DefView", None)
        if d:
            found.append(d)
            return False
        return True
    user32.EnumWindows(each, 0)
    return found[0] if found else None


class Pin:
    """Окно под ярлыками рабочего стола: как обои — окна и папки всегда выше, Win+D не прячет,
    мышь до него не доходит. Окна Qt туда не встают (не рисуются), поэтому своё простое окно WinAPI,
    в которое кладём готовую картинку виджета (UpdateLayeredWindow, с прозрачностью).
    С живыми обоями (Wallpaper Engine) не работает — проверено 2026-11-02 тремя способами: рядом с ярлыками
    и внутри окна обоев видео закрывает окно; внутри слоя ярлыков прозрачное окно рисуется поверх значков.
    Поэтому при живых обоях виджеты не вшиваем (см. DesktopWidget.place)."""

    _wc = None

    def __init__(self):
        if Pin._wc is None:
            Pin._proc = _WNDPROC(lambda h, m, w, l: user32.DefWindowProcW(h, m, w, l))
            Pin._wc = _WNDCLASS(0, Pin._proc, 0, 0, _kernel32.GetModuleHandleW(None), None, None, None, None,
                                "LiquidWidgetPin")
            user32.RegisterClassW(ctypes.byref(Pin._wc))
        self.hwnd = None
        self.size = None
        self.mdc = self.bmp = self.bits = None
        self.last = None

    def ensure(self):
        """Окно на месте? Если Проводник перезапускался — создать заново."""
        if self.hwnd and user32.IsWindow(self.hwnd):
            return True
        defview = icons_layer()
        if not defview:
            return False
        # слоистое, не активируется, мышь пропускает, не в Alt+Tab; дочернее и видимое
        self.hwnd = user32.CreateWindowExW(0x00080000 | 0x08000000 | 0x20 | 0x80, "LiquidWidgetPin", "",
                                           0x40000000 | 0x10000000, 0, 0, 1, 1, user32.GetParent(defview),
                                           None, _kernel32.GetModuleHandleW(None), None)
        if not self.hwnd:
            return False
        user32.SetWindowPos(self.hwnd, defview, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)  # сразу под ярлыками
        self.last = None
        return True

    def show(self, img, x, y):
        """Картинка виджета (QImage) в точке экрана (x, y) — физические пиксели."""
        if not self.ensure():
            return
        img = img.convertToFormat(QImage.Format_ARGB32_Premultiplied)
        w, h = img.width(), img.height()
        arr = np.frombuffer(img.constBits(), np.uint8, img.sizeInBytes())
        key = (x, y, w, h)
        if self.last is not None and self.last[0] == key and np.array_equal(self.last[1], arr):
            return  # ничего не поменялось
        self.last = (key, arr.copy())
        if self.size != (w, h):
            self._free_bitmap()
            sdc = user32.GetDC(None)
            self.mdc = gdi32.CreateCompatibleDC(sdc)
            user32.ReleaseDC(None, sdc)
            bmi = _BMI(ctypes.sizeof(_BMI), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
            self.bits = ctypes.c_void_p()
            self.bmp = gdi32.CreateDIBSection(self.mdc, ctypes.byref(bmi), 0, ctypes.byref(self.bits), None, 0)
            gdi32.SelectObject(self.mdc, self.bmp)
            self.size = (w, h)
        ctypes.memmove(self.bits, arr.ctypes.data, w * h * 4)
        parent = wt.RECT()
        user32.GetWindowRect(user32.GetParent(self.hwnd), ctypes.byref(parent))
        pos, size, src = wt.POINT(x - parent.left, y - parent.top), wt.SIZE(w, h), wt.POINT(0, 0)
        sdc = user32.GetDC(None)
        user32.UpdateLayeredWindow(self.hwnd, sdc, ctypes.byref(pos), ctypes.byref(size), self.mdc,
                                   ctypes.byref(src), 0, ctypes.byref(_BLEND(0, 0, 255, 1)), 2)  # ULW_ALPHA
        user32.ReleaseDC(None, sdc)

    def _free_bitmap(self):
        if self.bmp:
            gdi32.DeleteDC(self.mdc)  # сначала DC (в нём выбрана картинка), потом саму картинку
            gdi32.DeleteObject(self.bmp)
        self.mdc = self.bmp = self.bits = None
        self.size = None

    def destroy(self):
        if self.hwnd and user32.IsWindow(self.hwnd):
            user32.DestroyWindow(self.hwnd)
        self.hwnd = None
        self._free_bitmap()


def render_shadow(w, h, radius, margin, dark):
    """Мягкая тень под карточкой (картинка размером с окно)."""
    W, H = w + 2 * margin, h + 2 * margin
    sdf = rounded_sdf(W, H, radius, oy=6) + margin + 2
    a = blur(np.clip(0.5 - sdf, 0, 1)[..., None], 5)[..., 0]
    rgba = np.zeros((H, W, 4), np.uint8)
    rgba[..., 3] = (a * (0.22 if dark else 0.16) * 255).astype(np.uint8)
    return to_image(rgba)


THEMES = {
    False: dict(fg="#1b1c22", dim="#565a6b", field="rgba(255,255,255,110)", track="rgba(0,0,0,30)",
                card="rgba(255,255,255,95)", cardhover="rgba(255,255,255,140)",
                cardline="rgba(255,255,255,170)", bubble="rgba(255,255,255,150)",
                glow=QColor(255, 255, 255, 80)),
    True: dict(fg="#f5f6fb", dim="#b6bbcd", field="rgba(255,255,255,24)", track="rgba(255,255,255,45)",
               card="rgba(255,255,255,20)", cardhover="rgba(255,255,255,34)",
               cardline="rgba(255,255,255,38)", bubble="rgba(255,255,255,30)",
               glow=QColor(255, 255, 255, 30)),
}
