"""Видеокарта любой марки (AMD Radeon, Intel Arc, и NVIDIA без её утилит) — средствами самой Windows,
теми же, откуда берёт цифры Диспетчер задач:
  температура, вентилятор, имя, объём памяти — D3DKMTQueryAdapterInfo (gdi32.dll);
  загрузка и занятая память — счётчики производительности «GPU Engine» / «GPU Adapter Memory» (pdh.dll).
Ничего ставить не нужно. Чего драйвер не отдаёт (у встроенной графики часто нет температуры) — поле None."""
import ctypes
from ctypes import wintypes as wt

VENDORS = {0x1002: "amd", 0x1022: "amd", 0x10DE: "nvidia", 0x8086: "intel"}
REGISTRYINFO, SEGMENTSIZE, ADAPTERTYPE, DEVICEIDS, PERFDATA = 8, 3, 15, 31, 62
PDH_MORE_DATA, PDH_FMT_DOUBLE, PDH_FMT_NOCAP100 = 0x800007D2, 0x00000200, 0x00008000


class _Luid(ctypes.Structure):
    _fields_ = [("low", wt.DWORD), ("high", wt.LONG)]


class _AdapterInfo(ctypes.Structure):
    _fields_ = [("handle", wt.UINT), ("luid", _Luid), ("sources", wt.ULONG), ("precise", wt.BOOL)]


class _Enum(ctypes.Structure):
    _fields_ = [("count", wt.ULONG), ("adapters", ctypes.POINTER(_AdapterInfo))]


class _Query(ctypes.Structure):
    _fields_ = [("handle", wt.UINT), ("type", wt.UINT), ("data", ctypes.c_void_p), ("size", wt.UINT)]


class _Close(ctypes.Structure):
    _fields_ = [("handle", wt.UINT)]


class _Registry(ctypes.Structure):
    _fields_ = [("adapter", wt.WCHAR * 260), ("bios", wt.WCHAR * 260), ("dac", wt.WCHAR * 260),
                ("chip", wt.WCHAR * 260)]


class _Segments(ctypes.Structure):
    _fields_ = [("dedicated", ctypes.c_ulonglong), ("dedicated_system", ctypes.c_ulonglong),
                ("shared", ctypes.c_ulonglong)]


class _DeviceIds(ctypes.Structure):
    _fields_ = [("index", wt.UINT), ("vendor", wt.UINT), ("device", wt.UINT), ("subvendor", wt.UINT),
                ("subsystem", wt.UINT), ("revision", wt.UINT), ("bus", wt.UINT)]


class _Perf(ctypes.Structure):
    _fields_ = [("index", wt.ULONG), ("mem_freq", ctypes.c_ulonglong), ("mem_freq_max", ctypes.c_ulonglong),
                ("mem_freq_oc", ctypes.c_ulonglong), ("mem_bandwidth", ctypes.c_ulonglong),
                ("pcie_bandwidth", ctypes.c_ulonglong), ("fan_rpm", wt.ULONG), ("power", wt.ULONG),
                ("temperature", wt.ULONG), ("power_state", ctypes.c_ubyte)]


class _Value(ctypes.Structure):
    _fields_ = [("status", wt.DWORD), ("value", ctypes.c_double)]


class _Item(ctypes.Structure):
    _fields_ = [("name", wt.LPWSTR), ("value", _Value)]


class Counter:
    """Счётчик производительности Windows со многими экземплярами: read() -> {имя экземпляра: число}."""

    def __init__(self, path):
        self.pdh = ctypes.WinDLL("pdh.dll")
        self.query, self.counter = wt.HANDLE(), wt.HANDLE()
        self.pdh.PdhOpenQueryW.argtypes = [wt.LPCWSTR, ctypes.c_size_t, ctypes.POINTER(wt.HANDLE)]
        self.pdh.PdhAddEnglishCounterW.argtypes = [wt.HANDLE, wt.LPCWSTR, ctypes.c_size_t, ctypes.POINTER(wt.HANDLE)]
        self.pdh.PdhCollectQueryData.argtypes = [wt.HANDLE]
        self.pdh.PdhGetFormattedCounterArrayW.argtypes = [wt.HANDLE, wt.DWORD, ctypes.POINTER(wt.DWORD),
                                                          ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
        if self.pdh.PdhOpenQueryW(None, 0, ctypes.byref(self.query)) != 0:
            raise OSError("PdhOpenQuery")
        if self.pdh.PdhAddEnglishCounterW(self.query, path, 0, ctypes.byref(self.counter)) != 0:
            raise OSError("PdhAddEnglishCounter " + path)
        self.pdh.PdhCollectQueryData(self.query)  # первый замер: «проценты» считаются между двумя соседними

    def read(self):
        if self.pdh.PdhCollectQueryData(self.query) != 0:
            return {}
        size, count = wt.DWORD(0), wt.DWORD(0)
        fmt = PDH_FMT_DOUBLE | PDH_FMT_NOCAP100
        code = self.pdh.PdhGetFormattedCounterArrayW(self.counter, fmt, ctypes.byref(size), ctypes.byref(count), None)
        if code & 0xFFFFFFFF != PDH_MORE_DATA or not size.value:
            return {}
        buf = ctypes.create_string_buffer(size.value)
        if self.pdh.PdhGetFormattedCounterArrayW(self.counter, fmt, ctypes.byref(size), ctypes.byref(count), buf) != 0:
            return {}
        items = ctypes.cast(buf, ctypes.POINTER(_Item))
        out = {}
        for i in range(count.value):
            if items[i].value.status in (0, 1):  # готово / новое значение
                out[items[i].name] = out.get(items[i].name, 0.0) + items[i].value.value
        return out


class Generic:
    """Главная видеокарта компьютера (не программная; из нескольких — та, у которой больше своей памяти)."""

    def __init__(self):
        self.ok = False
        self.vendor = None
        try:
            self.gdi = ctypes.WinDLL("gdi32.dll")
            for fn in ("D3DKMTEnumAdapters2", "D3DKMTQueryAdapterInfo", "D3DKMTCloseAdapter"):
                getattr(self.gdi, fn).argtypes = [ctypes.c_void_p]
                getattr(self.gdi, fn).restype = ctypes.c_long
            found = self._pick()
            if found is None:
                return
            self.handle, luid, self.name, self.total, self.vendor = found
            self.luid = f"luid_0x{luid.high & 0xFFFFFFFF:08X}_0x{luid.low:08X}_"
            self.load_counter = self.mem_counter = None
            try:
                self.load_counter = Counter(r"\GPU Engine(*)\Utilization Percentage")
                self.mem_counter = Counter(r"\GPU Adapter Memory(*)\Dedicated Usage")
            except OSError:
                pass  # счётчиков нет (Windows 10 до 1709) — останутся температура и вентилятор
            self.ok = True
        except (OSError, AttributeError, ValueError):
            self.ok = False

    def _info(self, handle, kind, data):
        q = _Query(handle, kind, ctypes.cast(ctypes.byref(data), ctypes.c_void_p), ctypes.sizeof(data))
        return self.gdi.D3DKMTQueryAdapterInfo(ctypes.byref(q)) == 0

    def _pick(self):
        enum = _Enum(0, None)
        if self.gdi.D3DKMTEnumAdapters2(ctypes.byref(enum)) != 0 or not enum.count:
            return None
        arr = (_AdapterInfo * enum.count)()
        enum.adapters = ctypes.cast(arr, ctypes.POINTER(_AdapterInfo))
        if self.gdi.D3DKMTEnumAdapters2(ctypes.byref(enum)) != 0:
            return None
        best, seen = None, set()
        for a in arr[:enum.count]:
            key = (a.luid.high, a.luid.low)
            kind, seg, reg, ids = wt.UINT(0), _Segments(), _Registry(), _DeviceIds()
            good = key not in seen and self._info(a.handle, ADAPTERTYPE, kind) and not kind.value & 0b100  # не программная
            good = good and self._info(a.handle, REGISTRYINFO, reg) and bool(reg.adapter.strip())
            seen.add(key)
            if good:
                self._info(a.handle, SEGMENTSIZE, seg)
                self._info(a.handle, DEVICEIDS, ids)
                name = reg.adapter.strip()
                vendor = VENDORS.get(ids.vendor) or next((v for k, v in (("radeon", "amd"), ("amd", "amd"),
                                                                             ("nvidia", "nvidia"), ("geforce", "nvidia"),
                                                                             ("intel", "intel")) if k in name.lower()), None)
                item = (seg.dedicated, a.handle, _Luid(a.luid.low, a.luid.high), name, vendor)
                if best is None or item[0] > best[0]:
                    if best is not None:
                        self._close(best[1])
                    best = item
                    continue
            self._close(a.handle)
        if best is None:
            return None
        total, handle, luid, name, vendor = best
        for cut in ("NVIDIA ", "GeForce ", "AMD ", "(TM)", "(R)"):
            name = name.replace(cut, "")
        return handle, luid, " ".join(name.split()), total / 2 ** 20 if total else None, vendor

    def _close(self, handle):
        self.gdi.D3DKMTCloseAdapter(ctypes.byref(_Close(handle)))

    def read(self):
        perf = _Perf()
        have = self._info(self.handle, PERFDATA, perf)
        temp = perf.temperature / 10 if have and 0 < perf.temperature < 1500 else None  # в десятых долях градуса
        load = mem = None
        if self.load_counter is not None:
            engines = {}  # загрузка — как в Диспетчере задач: по каждому «движку» сумма процессов, берём самый занятый
            for inst, value in self.load_counter.read().items():
                if self.luid in inst:
                    eng = inst.split("_eng_")[-1]
                    engines[eng] = engines.get(eng, 0.0) + value
            load = min(100.0, max(engines.values())) if engines else 0.0
        if self.mem_counter is not None:
            used = [v for inst, v in self.mem_counter.read().items() if self.luid in inst]
            mem = sum(used) / 2 ** 20 if used else None
        if temp is None and load is None:
            raise OSError("no gpu data")
        return {"name": self.name, "vendor": self.vendor, "load": load, "temp": temp, "mem": mem,
                "mem_total": self.total, "power": None,
                "power_pct": perf.power / 10 if have and 0 < perf.power <= 2000 else None,
                "fan": None, "fan_rpm": float(perf.fan_rpm) if have and perf.fan_rpm else None}
