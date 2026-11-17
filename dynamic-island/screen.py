"""Экран через WinAPI: снимок куска экрана под островом (для стекла), «не попадать в снимки», клавиша скриншота,
что впереди (игра на весь экран). Всё, что трогает снимок, работает и в фоновом потоке."""
import applog
import ctypes
import threading
from ctypes import wintypes as wt

import numpy as np
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QImage

user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
user32.GetDC.restype = wt.HDC
user32.GetDC.argtypes = [wt.HWND]
user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.MonitorFromWindow.restype = wt.HANDLE
user32.MonitorFromWindow.argtypes = [wt.HWND, wt.DWORD]
user32.GetMonitorInfoW.argtypes = [wt.HANDLE, ctypes.c_void_p]
user32.SetWindowDisplayAffinity.argtypes = [wt.HWND, wt.DWORD]
user32.GetWindowDisplayAffinity.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetForegroundWindow.restype = wt.HWND
user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
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
    """Окно не попадает в снимки экрана — значит, можно снимать то, что под ним. -> получилось ли
    (на Windows 10 до версии 2004 такого нет; сразу после входа в систему бывает, что не с первого раза)."""
    user32.SetWindowDisplayAffinity(hwnd, 0x11)  # WDA_EXCLUDEFROMCAPTURE
    return excluded(hwnd)


def excluded(hwnd):
    """Окна точно нет в снимках экрана?"""
    mode = wt.DWORD(0)
    return bool(user32.GetWindowDisplayAffinity(hwnd, ctypes.byref(mode))) and mode.value == 0x11


def refresh_timezone():
    """Часовой пояс сменили (переезд, «летнее время») — Python сам этого не замечает до перезапуска."""
    try:
        ctypes.cdll.ucrtbase._tzset()
    except (OSError, AttributeError):
        pass


def include_in_capture(hwnd):
    user32.SetWindowDisplayAffinity(hwnd, 0)


# ---------- снимок и размытие ----------

def grab_small(x, y, w, h, sw, sh):
    """Кусок экрана (физ. пиксели) -> уменьшенный до sw×sh RGB-массив (сглаженно, силами Qt)."""
    sdc = user32.GetDC(None)
    mdc = gdi32.CreateCompatibleDC(sdc)
    bmi = _BMI(ctypes.sizeof(_BMI), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    bits = ctypes.c_void_p()
    bmp = gdi32.CreateDIBSection(mdc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
    old = gdi32.SelectObject(mdc, bmp)
    try:
        gdi32.BitBlt(mdc, 0, 0, w, h, sdc, x, y, 0x00CC0020)  # SRCCOPY
        buf = np.ctypeslib.as_array(ctypes.cast(bits, ctypes.POINTER(ctypes.c_uint8)), (h, w * 4))
        img = QImage(buf.data, w, h, w * 4, QImage.Format_RGB32)  # память снимка жива, пока Qt её читает
        img = img.scaled(sw, sh, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).convertToFormat(QImage.Format_RGB888)
        out = np.frombuffer(img.constBits(), np.uint8, img.sizeInBytes())
        return out.reshape(sh, img.bytesPerLine())[:, :sw * 3].reshape(sh, sw, 3).copy()
    finally:
        gdi32.SelectObject(mdc, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mdc)
        user32.ReleaseDC(None, sdc)


def _box(a, r, axis):
    pad = [(0, 0)] * a.ndim
    pad[axis] = (r + 1, r)
    c = np.cumsum(np.pad(a, pad, mode="edge"), axis=axis)
    n = a.shape[axis]
    hi = [slice(None)] * a.ndim
    lo = [slice(None)] * a.ndim
    hi[axis], lo[axis] = slice(2 * r + 1, 2 * r + 1 + n), slice(0, n)
    return (c[tuple(hi)] - c[tuple(lo)]) / (2 * r + 1)


def blur(a, r):
    for _ in range(3):  # три box-размытия ≈ гаусс
        a = _box(_box(a, r, 0), r, 1)
    return a


TO_LIGHT, TO_DARK = 0.40, 0.34  # авто-тема: фон светлее — светлая, темнее — тёмная (между — как была)


def frosted(x, y, w, h, radius=2, haze=50, theme="dark", prev_dark=True):
    """Что под окном острова -> (готовое стекло, яркость фона 0..1). Фоновый поток.
    Маленькая картинка (её растягивает painter); radius — размытие в уменьшенной копии.
    Цвет считается ровно как у стекла виджетов (их glass.render): та же насыщенность, то же притемнение
    и та же дымка по «замутнению» — чтобы остров с настройкой «как у виджетов» и выглядел как виджеты.
    Раньше дымку клал сам остров, своей формулой (не меньше 45% тёмного), и был заметно темнее виджетов."""
    small = grab_small(x, y, w, h, max(8, w // 6), max(4, h // 6)).astype(np.float32) / 255
    if radius > 0:
        small = blur(small, radius)
    lum = float((small[..., 0] * 0.3 + small[..., 1] * 0.59 + small[..., 2] * 0.11).mean())
    dark = theme == "dark" if theme in ("dark", "light") else lum < (TO_LIGHT if prev_dark else TO_DARK)
    gray = small.mean(axis=2, keepdims=True)
    vivid = 0.0 if haze >= 0 else min(1.0, haze / -50)  # замутнение в минусе — цвета сочнее
    t = max(0, min(100, haze)) / 100
    if dark:
        k = 0.95 * t ** 0.9
        small = (gray + (small - gray) * (0.5 + 0.6 * vivid)) * (0.8 + 0.15 * vivid)
        small = small * (1 - k) + np.array([0.12, 0.12, 0.14], np.float32) * k
    else:
        k = 0.97 * t ** 0.5
        small = gray + (small - gray) * (1.15 + 0.35 * vivid)
        small = small * (1 - k) + np.array([0.93, 0.93, 0.95], np.float32) * k
    out = np.ascontiguousarray((np.clip(small, 0, 1) * 255).astype(np.uint8))
    return QImage(out.data, out.shape[1], out.shape[0], out.shape[1] * 3, QImage.Format_RGB888).copy(), lum


# ---------- что впереди ----------

def window_rect(hwnd):
    """Окно и его монитор в физических пикселях: (l, t, r, b), (l, t, r, b)."""
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    mi = _MONITORINFO(ctypes.sizeof(_MONITORINFO))
    user32.GetMonitorInfoW(user32.MonitorFromWindow(hwnd, 2), ctypes.byref(mi))
    m = mi.rcMonitor
    return (r.left, r.top, r.right, r.bottom), (m.left, m.top, m.right, m.bottom)


SHELL = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}


def fullscreen_monitor():
    """Монитор (физ. пиксели), который целиком занимает окно впереди (игра, видео), или None."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    if buf.value in SHELL:
        return None
    win, monitor = window_rect(hwnd)
    return monitor if win == monitor else None


def caps_lock():
    return bool(user32.GetKeyState(0x14) & 1)


# ---------- клавиша скриншота ----------

WH_KEYBOARD_LL, WM_KEYDOWN, WM_SYSKEYDOWN = 13, 0x0100, 0x0104
VK_SNAPSHOT, VK_S, VK_SHIFT, VK_LWIN, VK_RWIN = 0x2C, 0x53, 0x10, 0x5B, 0x5C
_HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wt.WPARAM, wt.LPARAM)
user32.SetWindowsHookExW.restype = wt.HHOOK
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, _HOOKPROC, wt.HINSTANCE, wt.DWORD]
user32.CallNextHookEx.restype = ctypes.c_ssize_t
user32.CallNextHookEx.argtypes = [wt.HHOOK, ctypes.c_int, wt.WPARAM, wt.LPARAM]


user32.GetMessageW.argtypes = [ctypes.c_void_p, wt.HWND, wt.UINT, wt.UINT]


class _KBD(ctypes.Structure):
    _fields_ = [("vkCode", wt.DWORD), ("scanCode", wt.DWORD), ("flags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _KeyRelay(QObject):
    fired = Signal(object)


def watch_screenshot_keys(callback):
    """PrtSc (с любыми Alt/Win) и Win+Shift+S -> callback до того, как Windows снимет экран.
    Смотрим только эти клавиши, ничего не записываем и не глотаем."""
    def down(vk):
        return user32.GetAsyncKeyState(vk) & 0x8000

    # Перехват живёт в своём потоке со своей очередью сообщений. Windows ждёт его ответа на КАЖДОЕ нажатие
    # любой клавиши в любой программе: пока он был в главном потоке (рисование, стекло, запуск виджетов),
    # занятый главный поток задерживал ввод текста во всей системе. Теперь обычная клавиша — одно сравнение
    # и сразу ответ; главный поток ждём (не дольше 0.3 с) только на самих клавишах скриншота.
    relay = _KeyRelay()

    def run(done):
        try:
            callback()
        except Exception as _err:
            applog.error("screen.watch_screenshot_keys.run", _err)
        finally:
            done.set()
    relay.fired.connect(run)  # из потока перехвата — в главный (сигнал сам встаёт в очередь)

    def proc(code, wparam, lparam):
        if code == 0 and wparam in (WM_KEYDOWN, WM_SYSKEYDOWN):
            vk = ctypes.cast(lparam, ctypes.POINTER(_KBD))[0].vkCode
            if vk == VK_SNAPSHOT or (vk == VK_S and down(VK_SHIFT) and (down(VK_LWIN) or down(VK_RWIN))):
                try:
                    done = threading.Event()
                    relay.fired.emit(done)
                    done.wait(0.3)  # окна должны успеть показаться снимку до того, как Windows снимет экран
                except Exception as _err:
                    applog.error("screen.watch_screenshot_keys.proc", _err)
        return user32.CallNextHookEx(None, code, wparam, lparam)

    def loop():
        hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, watch_screenshot_keys.proc, None, 0)
        thread = ctypes.windll.kernel32.GetCurrentThreadId()

        def stop():  # при выходе снять перехват: иначе нажатие клавиши могло прийти в уже закрывающийся Python
            user32.UnhookWindowsHookEx(wt.HHOOK(hook))
            user32.PostThreadMessageW(thread, 0x0012, 0, 0)  # WM_QUIT — цикл ниже закончится
        import atexit
        atexit.register(stop)
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            pass

    watch_screenshot_keys.proc = _HOOKPROC(proc)  # держим ссылки, иначе сборщик мусора убьёт callback
    watch_screenshot_keys.relay = relay
    threading.Thread(target=loop, daemon=True, name="screenshot-keys").start()
    return True


# ---------- горячая клавиша ----------

WM_HOTKEY = 0x0312
MODS = {"alt": 0x1, "ctrl": 0x2, "shift": 0x4, "win": 0x8}
MOD_NOREPEAT = 0x4000
user32.RegisterHotKey.argtypes = [wt.HWND, ctypes.c_int, wt.UINT, wt.UINT]
user32.UnregisterHotKey.argtypes = [wt.HWND, ctypes.c_int]


def parse_hotkey(text):
    """«ctrl+alt+i» -> (модификаторы, код клавиши) или None. Клавиша — буква, цифра или F1..F24."""
    mods, vk = MOD_NOREPEAT, None
    for part in text.lower().replace(" ", "").split("+"):
        if part in MODS:
            mods |= MODS[part]
        elif len(part) == 1 and part.isalnum():
            vk = ord(part.upper())
        elif part.startswith("f") and part[1:].isdigit() and 1 <= int(part[1:]) <= 24:
            vk = 0x70 + int(part[1:]) - 1
        else:
            return None
    return (mods, vk) if vk is not None else None


def register_hotkey(hwnd, ident, text):
    """Глобальная горячая клавиша на окно: Windows шлёт ему WM_HOTKEY. False — разбор не удался или занята."""
    parsed = parse_hotkey(text)
    if parsed is None:
        return False
    user32.UnregisterHotKey(hwnd, ident)
    return bool(user32.RegisterHotKey(hwnd, ident, *parsed))


def is_hotkey(message, ident):
    """Сообщение Windows (из nativeEvent) — наша горячая клавиша?"""
    msg = wt.MSG.from_address(int(message))
    return msg.message == WM_HOTKEY and msg.wParam == ident


# ---------- события окон: открылось, закрылось, сдвинулось, стало активным ----------

WINEVENT_OUTOFCONTEXT, WINEVENT_SKIPOWNPROCESS = 0x0000, 0x0002
EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_MOVESIZEEND = 0x0003, 0x000B
EVENT_SYSTEM_MINIMIZESTART, EVENT_SYSTEM_MINIMIZEEND = 0x0016, 0x0017
EVENT_OBJECT_SHOW, EVENT_OBJECT_HIDE, EVENT_OBJECT_LOCATIONCHANGE = 0x8002, 0x8003, 0x800B
EVENT_OBJECT_CLOAKED, EVENT_OBJECT_UNCLOAKED = 0x8017, 0x8018
OBJID_WINDOW, GA_ROOT = 0, 2
_WINEVENTPROC = ctypes.WINFUNCTYPE(None, wt.HANDLE, wt.DWORD, wt.HWND, wt.LONG, wt.LONG, wt.DWORD, wt.DWORD)
user32.SetWinEventHook.restype = wt.HANDLE
user32.SetWinEventHook.argtypes = [wt.DWORD, wt.DWORD, wt.HMODULE, _WINEVENTPROC, wt.DWORD, wt.DWORD, wt.DWORD]
user32.GetAncestor.restype = wt.HWND
user32.GetAncestor.argtypes = [wt.HWND, wt.UINT]
user32.IsWindowVisible.argtypes = [wt.HWND]


def watch_windows(callback):
    """Окна верхнего уровня: открылось/закрылось, свернулось/развернулось, сдвинули, стало активным ->
    callback(hwnd, rect или None, активное ли окно сменилось). Только окна целиком (не курсор, не каретка,
    не части окон), свои окна не считаем. Зовётся в главном потоке (через очередь сообщений Qt)."""
    places = {}  # окно -> где было: «сдвинулось» без настоящего сдвига (виджеты шлют ~70 раз/с) не считаем

    def proc(hook, event, hwnd, id_object, id_child, thread, ms):
        if not hwnd or id_object != OBJID_WINDOW or id_child != 0:
            return
        if user32.GetAncestor(hwnd, GA_ROOT) != hwnd:
            return
        r = wt.RECT()
        rect = (r.left, r.top, r.right, r.bottom) if user32.GetWindowRect(hwnd, ctypes.byref(r)) else None
        if event == EVENT_OBJECT_LOCATIONCHANGE:
            if places.get(hwnd) == rect:
                return
            if len(places) > 500:
                places.clear()
        places[hwnd] = rect
        try:
            callback(hwnd, rect, event == EVENT_SYSTEM_FOREGROUND)
        except RuntimeError as _err:  # остров уже закрывается, а Windows ещё шлёт события окон — молча
            if "already deleted" not in str(_err):
                applog.error("screen.watch_windows.proc", _err)
        except Exception as _err:
            applog.error("screen.watch_windows.proc", _err)

    watch_windows.proc = _WINEVENTPROC(proc)  # держим ссылку, иначе сборщик мусора убьёт callback
    flags = WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS
    return [user32.SetWinEventHook(lo, hi, None, watch_windows.proc, 0, 0, flags)
            for lo, hi in ((EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND),
                           (EVENT_SYSTEM_MOVESIZEEND, EVENT_SYSTEM_MOVESIZEEND),
                           (EVENT_SYSTEM_MINIMIZESTART, EVENT_SYSTEM_MINIMIZEEND),
                           (EVENT_OBJECT_SHOW, EVENT_OBJECT_HIDE),
                           (EVENT_OBJECT_LOCATIONCHANGE, EVENT_OBJECT_LOCATIONCHANGE),
                           (EVENT_OBJECT_CLOAKED, EVENT_OBJECT_UNCLOAKED))]


user32.UnhookWinEvent.argtypes = [wt.HANDLE]


def unwatch_windows(hooks):
    for h in hooks or []:
        if h:
            user32.UnhookWinEvent(h)
