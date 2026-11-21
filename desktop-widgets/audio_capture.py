"""Звук, который сейчас играет в Windows (WASAPI loopback через pycaw/comtypes), -> спектр по полосам.

Ничего не записывается и никуда не отправляется: фоновый поток берёт последние ~40 мс звука из общего микшера
Windows, считает спектр (numpy FFT) и хранит только числа полос — для визуализатора. Микрофон не трогается.
Работает, только пока кто-то держит захват (Spectrum.acquire/release): виджет выключен или закрыт — поток спит."""
import applog
import ctypes
import threading
import time
from ctypes import POINTER, c_uint32, c_uint64, c_void_p
from ctypes.wintypes import DWORD

import numpy as np

AUDCLNT_STREAMFLAGS_LOOPBACK = 0x00020000
AUDCLNT_BUFFERFLAGS_SILENT = 0x2
FFT_N = 2048


def _capture_client_iface():
    from comtypes import COMMETHOD, GUID, HRESULT, IUnknown

    class IAudioCaptureClient(IUnknown):
        _iid_ = GUID("{C8ADBD64-E71E-48a0-A4DE-185C395CD317}")
        _methods_ = (
            COMMETHOD([], HRESULT, "GetBuffer", (["out"], POINTER(c_void_p), "ppData"),
                      (["out"], POINTER(c_uint32), "pNumFramesToRead"), (["out"], POINTER(DWORD), "pdwFlags"),
                      (["out"], POINTER(c_uint64), "pu64DevicePosition"),
                      (["out"], POINTER(c_uint64), "pu64QPCPosition")),
            COMMETHOD([], HRESULT, "ReleaseBuffer", (["in"], c_uint32, "NumFramesRead")),
            COMMETHOD([], HRESULT, "GetNextPacketSize", (["out"], POINTER(c_uint32), "pNumFramesInNextPacket")),
        )
    return IAudioCaptureClient


class Spectrum:
    """Один на программу: bands(n) -> n чисел 0..1 (низкие слева), level -> общая громкость 0..1."""

    def __init__(self):
        self.lock = threading.Lock()
        self.users = 0
        self.thread = None
        self.ring = np.zeros(FFT_N, np.float32)
        self.rate = 48000
        self.last_audio = 0.0
        self.err_until = 0.0

    def acquire(self):
        with self.lock:
            self.users += 1
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(target=self._run, daemon=True, name="audio-loopback")
                self.thread.start()

    def release(self):
        with self.lock:
            self.users = max(0, self.users - 1)

    def silent(self):
        return time.monotonic() - self.last_audio > 0.25

    def bands(self, n, lo=40.0, hi=11000.0):  # выше ~12 кГц в музыке почти пусто — крайние столбики стояли бы
        """Спектр последних ~43 мс по n полосам в логарифмической шкале частот, 0..1."""
        with self.lock:
            x = self.ring.copy()
            rate = self.rate
        if self.silent():
            return np.zeros(n, np.float32)
        win = np.hanning(FFT_N).astype(np.float32)
        mag = np.abs(np.fft.rfft(x * win)) / (FFT_N / 4)
        freqs = np.fft.rfftfreq(FFT_N, 1 / rate)
        edges = np.geomspace(lo, min(hi, rate / 2 - 1), n + 1)
        idx = np.searchsorted(freqs, edges)
        out = np.empty(n, np.float32)
        for i in range(n):
            a, b = idx[i], max(idx[i] + 1, idx[i + 1])
            out[i] = mag[a:b].max() if b > a else 0.0
        # в децибелы: −60 дБ -> 0, 0 дБ -> 1; высокие частоты тише — лёгкий подъём к правому краю
        db = 20 * np.log10(out + 1e-9) + np.linspace(0, 10, n)
        return np.clip((db + 60) / 60, 0, 1).astype(np.float32)

    def _run(self):
        import comtypes
        try:  # COM в этом потоке; уже включён (comtypes делает это сам) — не страшно
            comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
            mine = True
        except OSError:
            mine = False
        try:
            while True:
                with self.lock:
                    if self.users <= 0:
                        self.thread = None
                        return
                if time.monotonic() < self.err_until:
                    time.sleep(0.5)
                    continue
                try:
                    self._session()
                except Exception as ex:  # устройство отключили, сменили и т.п. — переподключиться позже
                    applog.error("визуализатор: захват звука", ex)
                    self.err_until = time.monotonic() + 3
        finally:
            if mine:
                comtypes.CoUninitialize()

    def _session(self):
        """Один сеанс захвата с устройства вывода по умолчанию; выходит при смене устройства или если не нужен."""
        from comtypes import CLSCTX_ALL
        from pycaw.api.audioclient import IAudioClient
        from pycaw.pycaw import AudioUtilities
        speakers = AudioUtilities.GetSpeakers()
        dev = getattr(speakers, "_dev", speakers)
        dev_id = dev.GetId()
        client = dev.Activate(IAudioClient._iid_, CLSCTX_ALL, None).QueryInterface(IAudioClient)
        fmt = client.GetMixFormat()
        f = fmt.contents
        channels, rate, bits = f.nChannels, f.nSamplesPerSec, f.wBitsPerSample
        client.Initialize(0, AUDCLNT_STREAMFLAGS_LOOPBACK, 2_000_000, 0, fmt, None)  # общий режим, буфер 200 мс
        ICapture = _capture_client_iface()
        cap = client.GetService(ctypes.pointer(ICapture._iid_)).QueryInterface(ICapture)
        with self.lock:
            self.rate = rate
        client.Start()
        checked = time.monotonic()
        try:
            while True:
                with self.lock:
                    if self.users <= 0:
                        return
                now = time.monotonic()
                if now - checked > 5:  # сменилось устройство вывода (наушники/колонки) — новый сеанс
                    checked = now
                    cur = AudioUtilities.GetSpeakers()
                    if getattr(cur, "_dev", cur).GetId() != dev_id:
                        return
                got = []
                while cap.GetNextPacketSize():
                    data, frames, flags, _, _ = cap.GetBuffer()
                    if frames:
                        if flags & AUDCLNT_BUFFERFLAGS_SILENT or not data:
                            got.append(np.zeros(frames, np.float32))
                        elif bits == 32:
                            buf = np.ctypeslib.as_array((ctypes.c_float * (frames * channels)).from_address(data))
                            got.append(buf.reshape(frames, channels).mean(axis=1).astype(np.float32))
                        elif bits == 16:
                            buf = np.ctypeslib.as_array((ctypes.c_int16 * (frames * channels)).from_address(data))
                            got.append(buf.reshape(frames, channels).mean(axis=1).astype(np.float32) / 32768)
                    cap.ReleaseBuffer(frames)
                if got:
                    chunk = np.concatenate(got)[-FFT_N:]
                    loud = float(np.abs(chunk).max()) > 1e-4
                    with self.lock:
                        self.ring = np.roll(self.ring, -len(chunk))
                        self.ring[-len(chunk):] = chunk
                    if loud:
                        self.last_audio = time.monotonic()
                time.sleep(0.01)
        finally:
            try:
                client.Stop()
            except Exception:
                pass
            ctypes.windll.ole32.CoTaskMemFree(fmt)


spectrum = Spectrum()
