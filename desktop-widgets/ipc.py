"""Связь виджетов и острова — без зависаний.

Раньше проверка «жив ли сосед» и отправка команд шли через QLocalSocket с waitForConnected / waitForBytesWritten
прямо в главном потоке. В Windows у Qt это ожидание может не закончиться никогда, если программа на том конце
закрылась или зависла в этот самый миг (20.11.2026: остров так и повис на waitForBytesWritten, пока виджеты
перезапускались). А вместе с главным потоком вставал и перехват клавиш для PrtSc — Windows ждёт его на каждом
нажатии в любой программе, и ввод тормозил во всей системе.

Теперь:
- alive(имя) — есть ли канал соседа: WaitNamedPipe на 1 мс, без подключения (сосед ничего не замечает);
- send(имя, данные) — запись в канал в отдельном потоке: главный поток не ждёт никогда.
Обе программы читают команду целиком, когда отправитель отключился, — простая запись в канал им подходит.
"""
import ctypes
import threading
import time

_k = ctypes.WinDLL("kernel32", use_last_error=True)
_k.WaitNamedPipeW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
_k.WaitNamedPipeW.restype = ctypes.c_int

ERROR_FILE_NOT_FOUND = 2
ERROR_PIPE_BUSY = 231


def pipe(name):
    return "\\\\.\\pipe\\" + name  # так QLocalServer называет свой канал в Windows


def alive(name):
    """Запущен ли сосед (его канал есть). Занят другим подключением — тоже жив."""
    if _k.WaitNamedPipeW(pipe(name), 1):
        return True
    return ctypes.get_last_error() != ERROR_FILE_NOT_FOUND


def send(name, data):
    """Отправить команду соседу в фоне. Его нет или не ответил за ~1 с — команда просто теряется."""
    if isinstance(data, str):
        data = data.encode()

    def work():
        for _ in range(20):
            try:
                with open(pipe(name), "wb", buffering=0) as f:
                    f.write(data)
                return
            except OSError as err:
                if getattr(err, "winerror", None) == ERROR_PIPE_BUSY:
                    time.sleep(0.05)  # сосед как раз принимает другое подключение
                    continue
                return
    threading.Thread(target=work, daemon=True, name="ipc-send").start()
