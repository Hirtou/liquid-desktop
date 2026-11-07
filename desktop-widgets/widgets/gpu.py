"""Видеокарта NVIDIA: загрузка (кольцо), температура, память, мощность, вентилятор.
Опрос раз в 2 с в фоне — напрямую из драйвера: сначала NVAPI (nvapi64.dll, +3 МБ), не вышло — nvml.dll
(она тянет библиотеку драйвера на ~22 МБ, и выгрузить её нельзя), нет и её — через nvidia-smi
(без окна консоли). Нет утилиты или видеокарты — так и пишем."""
from lang import tr
import ctypes
import os
import subprocess
import threading

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen

from core import DesktopWidget, grid, open_uri

GREEN, AMBER, RED, NVIDIA = QColor("#4ade80"), QColor("#ffb547"), QColor("#ff5a5f"), QColor("#76b900")
FIELDS = "name,utilization.gpu,temperature.gpu,memory.used,memory.total,power.draw,fan.speed"


class _Util(ctypes.Structure):
    _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]


class _Mem(ctypes.Structure):
    _fields_ = [("total", ctypes.c_ulonglong), ("free", ctypes.c_ulonglong), ("used", ctypes.c_ulonglong)]


class _Mem2(ctypes.Structure):
    """Память v2: «занято» без резерва драйвера — как в nvidia-smi."""
    _fields_ = [("version", ctypes.c_uint), ("total", ctypes.c_ulonglong), ("reserved", ctypes.c_ulonglong),
                ("free", ctypes.c_ulonglong), ("used", ctypes.c_ulonglong)]


class Nvml:
    """Библиотека драйвера NVIDIA: то же, что показывает nvidia-smi, но без запуска процесса (доли миллисекунды)."""

    def __init__(self):
        self.lib = self.dev = None
        for path in (os.path.join(os.environ.get("WINDIR", r"C:\Windows"), r"System32\nvml.dll"),
                     os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                                  r"NVIDIA Corporation\NVSMI\nvml.dll")):
            try:
                lib = ctypes.CDLL(path)
            except OSError:
                continue
            dev = ctypes.c_void_p()
            if lib.nvmlInit_v2() == 0 and lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(dev)) == 0:
                self.lib, self.dev = lib, dev
                buf = ctypes.create_string_buffer(96)
                lib.nvmlDeviceGetName(dev, buf, 96)
                self.name = buf.value.decode(errors="replace").replace("NVIDIA ", "").replace("GeForce ", "")
                return

    def read(self):
        lib, dev = self.lib, self.dev
        util, mem, temp, power, fan = _Util(), _Mem(), ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint()
        ok = lambda code: code == 0  # noqa: E731
        mem2 = _Mem2(ctypes.sizeof(_Mem2) | 2 << 24)
        if hasattr(lib, "nvmlDeviceGetMemoryInfo_v2") and ok(lib.nvmlDeviceGetMemoryInfo_v2(dev, ctypes.byref(mem2))):
            mem = mem2
        elif not ok(lib.nvmlDeviceGetMemoryInfo(dev, ctypes.byref(mem))):
            mem = _Mem()
        return {"name": self.name,
                "load": float(util.gpu) if ok(lib.nvmlDeviceGetUtilizationRates(dev, ctypes.byref(util))) else None,
                "temp": float(temp.value) if ok(lib.nvmlDeviceGetTemperature(dev, 0, ctypes.byref(temp))) else None,
                "mem": mem.used / 2 ** 20 if mem.total else None,
                "mem_total": mem.total / 2 ** 20 if mem.total else None,
                "power": power.value / 1000 if ok(lib.nvmlDeviceGetPowerUsage(dev, ctypes.byref(power))) else None,
                "fan": float(fan.value) if ok(lib.nvmlDeviceGetFanSpeed(dev, ctypes.byref(fan))) else None}


class Nvapi:
    """NVAPI драйвера NVIDIA — то же, что nvml, но в ~8 раз легче по памяти. Функции берутся по номерам
    через nvapi_QueryInterface (часть — недокументированные, номера те же, что в LibreHardwareMonitor).
    Отличия от nvml: мощность — в % от лимита (ватты считаем по лимиту из nvidia-smi, один раз за запуск),
    вентилятор — в оборотах (процентов NVAPI не отдаёт), память — вместе с резервом драйвера (как в диспетчере
    задач). Чего-то нет — поле None; не удалось главное (загрузка) — ok = False, и опрос идёт через nvml."""

    INIT, ENUM, NAME = 0x0150E828, 0xE5AC921F, 0xCEEE8E9F
    THERMAL, PSTATES, MEMORY = 0xE3640A56, 0x60DED2ED, 0x07F9B368
    FANS, POWER = 0x35AED5E8, 0x0EDCF624E

    def __init__(self):
        self.ok = False
        self.tdp = None  # лимит мощности, Вт
        try:
            api = ctypes.CDLL(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "System32", "nvapi64.dll"))
            qi = api.nvapi_QueryInterface
            qi.restype, qi.argtypes = ctypes.c_void_p, [ctypes.c_uint]
            self.fn = {}
            for name, num in (("init", self.INIT), ("enum", self.ENUM), ("name", self.NAME), ("thermal", self.THERMAL),
                              ("pstates", self.PSTATES), ("memory", self.MEMORY), ("fans", self.FANS),
                              ("power", self.POWER)):
                addr = qi(num)
                if addr:
                    argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p] if name == "thermal" else \
                        [ctypes.c_void_p, ctypes.c_void_p]
                    self.fn[name] = ctypes.CFUNCTYPE(ctypes.c_int, *argtypes)(addr)
            if ctypes.CFUNCTYPE(ctypes.c_int)(qi(self.INIT))() != 0:
                return
            gpus, n = (ctypes.c_void_p * 64)(), ctypes.c_uint()
            if self.fn["enum"](gpus, ctypes.byref(n)) != 0 or n.value < 1:
                return
            self.gpu = gpus[0]
            buf = ctypes.create_string_buffer(64)
            self.fn["name"](self.gpu, buf)
            self.name = buf.value.decode(errors="replace").replace("NVIDIA ", "").replace("GeForce ", "")
            self.ok = self._load() is not None
        except (OSError, KeyError, AttributeError):
            self.ok = False

    @staticmethod
    def _buf(words, version):
        """Структура NVAPI как массив слов: в первом — размер и версия."""
        buf = (ctypes.c_uint * words)()
        buf[0] = words * 4 | version << 16
        return buf

    def _load(self):
        buf = self._buf(2 + 16, 1)  # NV_GPU_DYNAMIC_PSTATES_INFO_EX: [ver, flags, (present, %) × 8]
        if self.fn["pstates"](self.gpu, buf) != 0 or not buf[2]:
            return None
        return float(buf[3])  # домен 0 — графика

    def _temp(self):
        buf = self._buf(2 + 3 * 5, 2)  # NV_GPU_THERMAL_SETTINGS_V2: [ver, count, (controller, min, max, °C, target) × 3]
        if self.fn["thermal"](self.gpu, 15, buf) != 0 or not buf[1]:
            return None
        return float(ctypes.c_int(buf[5]).value)

    def _memory(self):
        buf = self._buf(8, 3)  # NV_DISPLAY_DRIVER_MEMORY_INFO_V3, КБ: [ver, всего, …, свободно сейчас (5), …]
        if self.fn["memory"](self.gpu, buf) != 0 or not buf[1]:
            return None, None
        return (buf[1] - buf[5]) / 1024, buf[1] / 1024

    def _fan_rpm(self):
        if "fans" not in self.fn:
            return None
        buf = self._buf(2 + 8 + 32 * 13, 1)  # [ver, count, резерв × 8, (id, об/мин, min, max, уровень, резерв × 8) × 32]
        if self.fn["fans"](self.gpu, buf) != 0 or not buf[1]:
            return None
        return float(buf[11])

    def _power_pct(self):
        if "power" not in self.fn:
            return None
        buf = self._buf(2 + 4 * 4, 1)  # [ver, count, (домен, ?, тысячные %, ?) × 4]; домен 0 — вся карта
        if self.fn["power"](self.gpu, buf) != 0 or not buf[1]:
            return None
        for i in range(min(4, buf[1])):
            if buf[2 + 4 * i] == 0:
                return buf[2 + 4 * i + 2] / 1000
        return None

    def read(self):
        load = self._load()
        if load is None:
            raise OSError(tr("NVAPI не отдаёт загрузку"))
        mem, total = self._memory()
        pct = self._power_pct()
        if pct is not None and self.tdp is None:
            self.tdp = power_limit() or 0
        return {"name": self.name, "load": load, "temp": self._temp(), "mem": mem, "mem_total": total,
                "power": pct * self.tdp / 100 if pct is not None and self.tdp else None,
                "power_pct": pct, "fan": None, "fan_rpm": self._fan_rpm()}


def power_limit():
    """Лимит мощности карты, Вт (NVAPI даёт мощность в % от него) — один раз через nvidia-smi."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=power.limit", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=4, creationflags=0x08000000).stdout
        return float(out.strip().splitlines()[0])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


NVAPI = None
NVML = None


def query():
    """-> dict или {"error": "..."}."""
    global NVML, NVAPI
    if NVAPI is None:
        NVAPI = Nvapi()
    if NVAPI.ok:
        try:
            return NVAPI.read()
        except Exception:
            NVAPI.ok = False  # драйвер обновился и т.п. — дальше через nvml
    if NVML is None:
        NVML = Nvml()
    if NVML.lib is not None:
        try:
            return NVML.read()
        except Exception:
            NVML.lib = None  # драйвер обновился и т.п. — дальше по-старому
    try:
        out = subprocess.run(["nvidia-smi", f"--query-gpu={FIELDS}", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=4, creationflags=0x08000000).stdout
    except (OSError, subprocess.SubprocessError):
        return {"error": tr("нет утилиты NVIDIA")}
    line = out.strip().splitlines()[0] if out.strip() else ""
    parts = [s.strip() for s in line.split(",")]
    if len(parts) < 7:
        return {"error": tr("видеокарта не отвечает")}

    def num(s):
        try:
            return float(s)
        except ValueError:
            return None

    name = parts[0].replace("NVIDIA ", "").replace("GeForce ", "")
    return {"name": name, "load": num(parts[1]), "temp": num(parts[2]), "mem": num(parts[3]),
            "mem_total": num(parts[4]), "power": num(parts[5]), "fan": num(parts[6])}


def heat(t):
    return GREEN if t is None or t < 65 else AMBER if t < 80 else RED


class GpuWidget(DesktopWidget):
    key = "gpu"
    title = tr("Видеокарта")
    description = tr("Загрузка, температура и память GPU")
    SHAPES = {"full": (tr("Полный"), grid(2, 1)), "ring": (tr("Кольцо"), grid(1, 1))}
    loaded = Signal(object)

    def __init__(self, **kw):
        super().__init__(**kw)
        self.apply_shape()
        self.data = None
        self.fetching = False  # не busy: так у DesktopWidget зовётся «стекло считается»
        self.loaded.connect(self.on_data)
        self.timer = QTimer(self, interval=2000, timeout=self.refresh)
        self.timer.start()
        self.refresh()

    def refresh(self):
        if not self.fetching:
            self.fetching = True
            threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        data = query()
        try:
            self.loaded.emit(data)
        except RuntimeError:  # виджет уже закрыли
            pass

    def on_data(self, data):
        self.fetching = False
        self.data = data
        self.update()

    def double_click(self):
        open_uri("taskmgr.exe")

    def paintEvent(self, event):
        super().paintEvent(event)  # стекло
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        r = QRectF(self.card())
        dark = bool(self.dark)
        fg = QColor("#ededf0") if dark else QColor("#151517")
        dim = QColor(fg)
        dim.setAlpha(140)
        d = self.data or {}
        if not d or "error" in d:
            p.setPen(dim)
            p.drawText(r, Qt.AlignCenter, d.get("error", tr("загрузка…")) if d else tr("загрузка…"))
            return
        load = d["load"] or 0

        # слева: кольцо загрузки
        if self.shape() == "ring":
            tile = r.adjusted(14, 14, -14, -14)
        else:
            side = r.height() - 56
            tile = QRectF(r.left() + 14, r.center().y() - side / 2, side, side)
        c, R = tile.center(), tile.width() / 2 - 10
        track = QColor(fg)
        track.setAlpha(30)
        p.setPen(QPen(track, 12, Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(c, R, R)
        if load > 0:
            p.setPen(QPen(NVIDIA, 12, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(QRectF(c.x() - R, c.y() - R, 2 * R, 2 * R), 90 * 16, int(-load / 100 * 360 * 16))
        big = QFont("Bahnschrift SemiBold")
        big.setPixelSize(int(R * 0.55))
        p.setFont(big)
        p.setPen(fg)
        p.drawText(QRectF(c.x() - R, c.y() - R * 0.45, 2 * R, R * 0.6), Qt.AlignCenter, f"{load:.0f}%")
        tiny = QFont("Segoe UI")
        tiny.setPixelSize(11)
        p.setFont(tiny)
        p.setPen(dim)
        p.drawText(QRectF(c.x() - R, c.y() + R * 0.2, 2 * R, 16), Qt.AlignCenter,
                   "GPU" if self.shape() == "full" else f"{d['temp']:.0f}°" if d["temp"] is not None else "GPU")
        if self.shape() == "ring":
            return

        # справа: заголовок, чип температуры, полоски, счётчики
        x = tile.right() + 16
        w = r.right() - 16 - x
        t = d["temp"]
        chip, color = (tr("горячая"), RED) if t and t >= 80 else (tr("тёплая"), AMBER) if t and t >= 65 else (tr("холодная"), GREEN)
        cf = QFont("Segoe UI Semibold")
        cf.setPixelSize(11)
        cw = QFontMetricsF(cf).horizontalAdvance(chip) + 24
        pill = QRectF(r.right() - 16 - cw, r.top() + 15, cw, 20)
        bg = QColor(color)
        bg.setAlpha(55 if dark else 70)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(pill, 10, 10)
        p.setBrush(color)
        p.drawEllipse(QRectF(pill.left() + 8, pill.center().y() - 3.5, 7, 7))
        p.setFont(cf)
        p.setPen(color.lighter(130) if dark else color.darker(170))
        p.drawText(pill.adjusted(19, 0, -6, 0), Qt.AlignVCenter | Qt.AlignLeft, chip)
        title = QFont("Segoe UI Semibold")
        title.setPixelSize(16)
        p.setFont(title)
        p.setPen(fg)
        p.drawText(QRectF(x, r.top() + 14, w - cw - 6, 22), Qt.AlignLeft | Qt.AlignVCenter, tr("Видеокарта"))
        p.setFont(tiny)
        p.setPen(dim)
        p.drawText(QRectF(x, r.top() + 36, w, 16), Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetricsF(tiny).elidedText(d["name"], Qt.ElideRight, w))
        mem, total = d["mem"] or 0, d["mem_total"] or 1
        self._bar(p, x, r.top() + 58, w, tr("Температура {:.0f}°").format(t) if t is not None else tr("Температура —"),
                  (t or 0), heat(t), fg, dim)
        self._bar(p, x, r.top() + 90, w, tr("Память {:.1f}/{:.0f} ГБ").format(mem / 1024, total / 1024), mem / total * 100,
                  QColor("#60a5fa"), fg, dim)
        num = QFont("Bahnschrift SemiBold")
        num.setPixelSize(16)
        if d["power"] is not None:
            power = tr("{:.0f} Вт").format(d['power'])
        elif d.get("power_pct") is not None:  # NVAPI без лимита в ваттах — доля от лимита
            power = f"{d['power_pct']:.0f}%"
        else:
            power = "—"
        if d.get("fan_rpm") is not None:  # NVAPI: обороты (процентов он не отдаёт)
            fan = tr("{:.0f} об/мин").format(d['fan_rpm'])
        else:
            fan = f"{d['fan']:.0f}%" if d["fan"] is not None else "—"
        for i, (value, label) in enumerate(((power, tr("мощность")), (fan, tr("вентилятор")))):
            cx = x + i * w / 2
            p.setFont(num)
            p.setPen(fg)
            p.drawText(QRectF(cx, r.bottom() - 40, w / 2, 20), Qt.AlignLeft | Qt.AlignVCenter, value)
            p.setFont(tiny)
            p.setPen(dim)
            p.drawText(QRectF(cx, r.bottom() - 22, w / 2, 14), Qt.AlignLeft | Qt.AlignVCenter, label)

    @staticmethod
    def _bar(p, x, y, w, label, pct, color, fg, dim):
        f = QFont("Segoe UI")
        f.setPixelSize(12)
        p.setFont(f)
        p.setPen(fg)
        p.drawText(QRectF(x, y, w, 16), Qt.AlignLeft | Qt.AlignVCenter, label)
        track = QColor(fg)
        track.setAlpha(30)
        bar = QRectF(x, y + 19, w, 6)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(bar, 3, 3)
        p.setBrush(color)
        p.drawRoundedRect(QRectF(bar.left(), bar.top(), max(6.0, bar.width() * min(100, pct) / 100), 6), 3, 3)
