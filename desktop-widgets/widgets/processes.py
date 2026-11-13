"""Процессы: кто больше всех занимает память. Одинаковые имена складываются (Chrome — один, а не сорок)."""
from lang import tr
import threading

import ctypes
import psutil
from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter

from core import DesktopWidget, activity, grid, open_uri
from widgets import kit

COLORS = [QColor(c) for c in ("#60a5fa", "#a78bfa", "#f472b6", "#fbbf24", "#34d399", "#22d3ee")]


def _all_memory():
    """[(имя, рабочий набор байт)] всех процессов одним вызовом NtQuerySystemInformation — ~3 мс.
    psutil.process_iter(memory_info) открывает каждый процесс, к закрытым идёт обходом — ~370 мс на 240 процессов,
    и всё это время держит GIL: окна программы подвисали, хоть чтение и в своём потоке."""
    size = 1 << 20
    while True:
        buf = ctypes.create_string_buffer(size)
        need = ctypes.c_ulong()
        st = ctypes.windll.ntdll.NtQuerySystemInformation(5, buf, size, ctypes.byref(need)) & 0xFFFFFFFF
        if st == 0:
            break
        if st != 0xC0000004 or size > 64 << 20:  # не «мал буфер» — не выйдет
            raise OSError(st)
        size = max(size * 2, need.value + 65536)
    raw, off, out = buf.raw, 0, []
    while True:  # SYSTEM_PROCESS_INFORMATION, x64: имя — UNICODE_STRING на 0x38, WorkingSetSize на 0x90
        nxt = int.from_bytes(raw[off:off + 4], "little")
        ln = int.from_bytes(raw[off + 0x38:off + 0x3A], "little")
        ptr = int.from_bytes(raw[off + 0x40:off + 0x48], "little")
        if ptr and ln:
            out.append((ctypes.wstring_at(ptr, ln // 2), int.from_bytes(raw[off + 0x90:off + 0x98], "little")))
        if not nxt:
            return out
        off += nxt


def _all_memory_psutil():
    out = []
    for proc in psutil.process_iter(["name", "memory_info"]):
        info = proc.info
        if info.get("name") and info.get("memory_info"):
            out.append((info["name"], info["memory_info"].rss))
    return out


def top_memory(count):
    """[(имя, байт)] по убыванию и занятая доля памяти в процентах."""
    try:
        procs = _all_memory() if ctypes.sizeof(ctypes.c_void_p) == 8 else _all_memory_psutil()
    except OSError:
        procs = _all_memory_psutil()
    used = {}
    for name, rss in procs:
        if name in ("System Idle Process", "System", "Registry", "Memory Compression"):
            continue
        name = name[:-4] if name.lower().endswith(".exe") else name
        used[name] = used.get(name, 0) + rss
    return sorted(used.items(), key=lambda kv: kv[1], reverse=True)[:count], psutil.virtual_memory().percent


def size(n):
    return tr("{:.1f} ГБ").format(n / 1024 ** 3) if n >= 1024 ** 3 else tr("{:.0f} МБ").format(n / 1024 ** 2)


class ProcessesWidget(DesktopWidget):
    key = "processes"
    title = tr("Процессы")
    description = tr("Кто занимает больше всего памяти")
    SHAPES = {"full": (tr("Полный"), grid(2, 1)), "tall": (tr("Высокий"), grid(2, 2))}
    loaded = Signal(list, float)

    def __init__(self, **kw):
        super().__init__(**kw)
        self.apply_shape()
        self.rows, self.percent = [], 0.0
        self.busy_read = False
        self.loaded.connect(self.show_rows)
        self.timer = QTimer(self, interval=5000, timeout=self.refresh)
        self.timer.start()
        self.refresh(force=True)

    def double_click(self):
        open_uri("taskmgr.exe")

    def refresh(self, force=False):
        if self.busy_read or (not force and activity.covered(self)):
            return
        self.busy_read = True
        threading.Thread(target=self._read, daemon=True).start()  # обход процессов — десятки мс, не в главном потоке

    def _read(self):
        rows, percent = top_memory(12)
        try:
            self.loaded.emit(rows, percent)
        except RuntimeError:  # виджет уже закрыли
            pass

    def show_rows(self, rows, percent):
        self.busy_read = False
        self.rows, self.percent = rows, percent
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)  # стекло
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        r = QRectF(self.card())
        fg, dim, track = kit.ink(self)
        dark = bool(self.dark)
        color = kit.RED if self.percent > 85 else kit.AMBER if self.percent > 65 else kit.GREEN
        cw = kit.chip(p, r, tr("память {:.0f}%").format(self.percent), color, dark)
        x, w = r.left() + 18, r.width() - 36
        kit.text(p, QRectF(x, r.top() + 14, w - cw, 22), tr("Процессы"), fg, 16, "Segoe UI Semibold")
        step = 24 if self.shape() == "full" else 30
        room = int((r.bottom() - 12 - (r.top() + 44)) // step)
        rows = self.rows[:room]
        total = rows[0][1] if rows else 1
        for i, (name, rss) in enumerate(rows):
            y = r.top() + 44 + i * step
            kit.text(p, QRectF(x, y, w * 0.62, 15), name, fg, 12, elide=True)
            kit.text(p, QRectF(x, y, w, 15), size(rss), dim, 11, align=Qt.AlignRight | Qt.AlignVCenter)
            kit.bar(p, QRectF(x, y + 16, w, 6), rss / total, COLORS[i % len(COLORS)], track)
        if not rows:
            kit.text(p, QRectF(x, r.top() + 44, w, 18), tr("Считаю…"), dim)
