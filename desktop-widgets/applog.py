"""Журнал программы (widgets.log / island.log): всё, что пошло не так, с временем у каждой строки.

Что попадает в журнал:
- шапка запуска: версия, Windows, Python, Qt, язык, экраны и их масштаб — чтобы по чужому журналу было ясно, где это;
- любое необработанное исключение — в главном потоке, в фоновых потоках, в asyncio и «неподнимаемые» (__del__ и т.п.);
- жёсткие вылеты (access violation) — через faulthandler;
- предупреждения и ошибки самого Qt (по умолчанию они уходят в никуда: у pythonw нет консоли);
- print() и traceback.print_exc() из любого места программы;
- ошибки, которые программа поймала и пережила: applog.error("где", ex) — одинаковые не чаще раза в 10 минут;
- как закончился прошлый запуск: если строки «выход» нет — программа упала или её убили.
Журнал больше 2 МБ откладывается в *.old.log — растёт не бесконечно.
Этот файл одинаковый у виджетов и острова."""
import atexit
import faulthandler
import os
import platform
import sys
import threading
import time
import traceback

MAX_SIZE = 2 * 1024 * 1024
REPEAT = 600        # одинаковую пойманную ошибку пишем не чаще раза в 10 минут
EXIT_MARK = "=== выход"

_raw = None          # сам файл: в него пишет faulthandler (ему нужен настоящий дескриптор)
_lock = threading.RLock()
_seen = {}           # ключ ошибки -> [когда писали, сколько раз пропустили]


def _stamp():
    t = time.time()
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t)) + f".{int(t % 1 * 1000):03d}"


class _Stream:
    """Поток для stdout/stderr: каждую новую строку начинает со времени и пометки, откуда она."""

    def __init__(self, tag):
        self.tag = tag
        self.fresh = True

    def write(self, text):
        if not text or _raw is None:
            return len(text or "")
        with _lock:
            out = []
            for part in text.splitlines(keepends=True):
                if self.fresh:
                    out.append(f"{_stamp()} {self.tag} ")
                out.append(part)
                self.fresh = part.endswith("\n")
            try:
                _raw.write("".join(out))
            except (OSError, ValueError):
                pass
        return len(text)

    def flush(self):
        try:
            _raw and _raw.flush()
        except (OSError, ValueError):
            pass

    def isatty(self):
        return False

    @property
    def encoding(self):
        return "utf-8"


def line(text, tag="     "):
    """Записать запись в журнал: время и пометка — у первой строки, остальные (traceback) — с отступом."""
    if _raw is None:
        return
    rows = str(text).rstrip("\n").split("\n")
    out = f"{_stamp()} {tag} {rows[0]}\n" + "".join(f"    {r}\n" for r in rows[1:])
    with _lock:
        try:
            _raw.write(out)
        except (OSError, ValueError):
            pass


def error(where, ex=None, once=True):
    """Ошибка, которую программа поймала и пережила: где случилась и полный traceback.
    once: такую же (то же место, тот же тип и текст) повторно — не чаще раза в 10 минут, с числом пропущенных."""
    if ex is None:
        ex = sys.exc_info()[1]
    key = (where, type(ex).__name__, str(ex)[:200])
    now = time.monotonic()
    with _lock:
        seen = _seen.get(key)
        if once and seen and now - seen[0] < REPEAT:
            seen[1] += 1
            return
        skipped = seen[1] if seen else 0
        _seen[key] = [now, 0]
    head = f"[ошибка] {where}: {type(ex).__name__}: {ex}" if ex is not None else f"[ошибка] {where}"
    if skipped:
        head += f" (ещё {skipped} раз с прошлой записи)"
    if ex is not None and ex.__traceback__ is not None:
        if _network(ex):  # сеть: traceback — одни внутренности urllib, хватит строки «откуда звали» в нашем коде
            ours = [f for f in traceback.extract_tb(ex.__traceback__) if _ROOT_HINT in f.filename]
            if ours:
                head += f"  ← {os.path.basename(ours[-1].filename)}:{ours[-1].lineno} {ours[-1].name}"
        else:
            head += "\n" + "".join(traceback.format_exception(type(ex), ex, ex.__traceback__)).rstrip()
    line(head, "ERR  ")


_ROOT_HINT = os.path.dirname(os.path.abspath(__file__))


def _network(ex):
    """Ошибка сети (нет связи, не ответил вовремя, оборвал) — а не ошибка в коде."""
    import socket
    import urllib.error
    return isinstance(ex, (urllib.error.URLError, TimeoutError, ConnectionError, socket.gaierror, socket.timeout))


def warn(text):
    """Что-то не так, но это не исключение (не нашлось, не ответило, не запустилось)."""
    line("[внимание] " + str(text), "WARN ")


def _hook(kind, value, tb, where="главный поток"):
    if issubclass(kind, KeyboardInterrupt):
        return
    line(f"[падение] необработанная ошибка ({where})\n"
         + "".join(traceback.format_exception(kind, value, tb)).rstrip(), "CRASH")


def _thread_hook(a):
    name = a.thread.name if a.thread else "?"
    _hook(a.exc_type, a.exc_value, a.exc_traceback, f"поток {name}")


def _unraisable(u):
    where = f"неподнимаемая: {u.err_msg or 'Exception ignored'} {u.object!r}"[:300]
    if u.exc_type is not None:
        _hook(u.exc_type, u.exc_value, u.exc_traceback, where)


def asyncio_handler(loop, context):
    """loop.set_exception_handler(applog.asyncio_handler) — ошибки задач asyncio, которые никто не дождался."""
    ex = context.get("exception")
    msg = context.get("message", "")
    if ex is not None:
        error("asyncio: " + msg, ex)
    else:
        warn("asyncio: " + msg)


def watch(future, where):
    """asyncio.run_coroutine_threadsafe(...) теряет ошибку, если результат никто не ждёт: так — запишется."""
    def done(f):
        if not f.cancelled() and f.exception() is not None:
            error(where, f.exception())
    future.add_done_callback(done)
    return future


def _qt_handler(mode, ctx, msg):
    from PySide6.QtCore import QtMsgType
    if mode == QtMsgType.QtDebugMsg or mode == QtMsgType.QtInfoMsg:
        return
    # шумные и безвредные сообщения Windows-платформы Qt
    for junk in ("QWindowsWindow::setGeometry", "SetProcessDpiAwarenessContext", "QFont::setPointSize"):
        if junk in msg:
            return
    kind = {QtMsgType.QtWarningMsg: "предупреждение Qt", QtMsgType.QtCriticalMsg: "ошибка Qt",
            QtMsgType.QtFatalMsg: "фатальная ошибка Qt"}.get(mode, "Qt")
    where = f" ({ctx.file}:{ctx.line})" if ctx and ctx.file else ""
    line(f"[{kind}] {msg}{where}", "QT   ")


def _rotate(path):
    try:
        if os.path.getsize(path) > MAX_SIZE:
            old = path[:-4] + ".old.log"
            if os.path.exists(old):
                os.remove(old)
            os.replace(path, old)
    except OSError:
        pass


def _last_run_ended(path):
    """Как закончился прошлый запуск: True — нормально, False — без строки «выход», None — журнала не было."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 65536))
            tail = f.read().decode("utf-8", "replace")
    except OSError:
        return None
    start = tail.rfind("=== запуск")
    if start < 0:
        return None
    return EXIT_MARK in tail[start:]


def _qt_info():
    try:
        import PySide6
        from PySide6.QtCore import qVersion
        return f"PySide6 {PySide6.__version__} (Qt {qVersion()})"
    except Exception:
        return "PySide6 ?"


def _windows():
    try:
        v = sys.getwindowsversion()
        name = "11" if v.build >= 22000 else "10" if v.major == 10 else f"{v.major}.{v.minor}"
        return f"Windows {name} ({v.major}.{v.minor}.{v.build})"
    except AttributeError:
        return platform.platform()


def _version(root):
    import json
    for path in (os.path.join(os.path.dirname(root), "version.json"), os.path.join(root, "version.json")):
        try:
            with open(path, encoding="utf-8-sig") as f:
                return "сборка " + str(json.load(f)["build"])
        except (OSError, ValueError, KeyError):
            pass
    return "из исходников"


def screens():
    """Экраны: разрешение, масштаб, частота — пишем после создания QApplication и при смене экранов."""
    try:
        from PySide6.QtGui import QGuiApplication
        out = []
        for i, s in enumerate(QGuiApplication.screens()):
            g = s.geometry()
            out.append(f"#{i} {g.width()}x{g.height()} @{g.x()},{g.y()} масштаб {s.devicePixelRatio():g}"
                       f" {s.refreshRate():.0f} Гц" + (" (главный)" if s == QGuiApplication.primaryScreen() else ""))
        return "; ".join(out) or "нет"
    except Exception as ex:
        return f"не узнать ({type(ex).__name__})"


def log_screens(app):
    """Записать экраны сейчас и при каждом подключении/отключении монитора."""
    line("экраны: " + screens())

    def changed(*_):
        line("экраны изменились: " + screens())
    try:
        app.screenAdded.connect(changed)
        app.screenRemoved.connect(changed)
        app.primaryScreenChanged.connect(changed)
    except Exception:
        pass


def setup(path, name, extra=""):
    """Открыть журнал и перехватить всё. Вызывать как можно раньше; extra — строка в шапку (язык и т.п.)."""
    global _raw
    _rotate(path)
    ended = _last_run_ended(path)
    _raw = open(path, "a", encoding="utf-8", buffering=1, errors="replace")
    root = os.path.dirname(os.path.abspath(path))
    _raw.write(f"\n=== запуск {name} {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    if ended is False:
        line("[внимание] прошлый запуск закончился без «выхода»: программа упала, зависла и её сняли, "
             "или выключили компьютер", "WARN ")
    line(f"{name} {_version(root)} · {_windows()} · Python {platform.python_version()} "
         f"{'64' if sys.maxsize > 2**32 else '32'}-бит · {_qt_info()}" + (f" · {extra}" if extra else ""))
    if getattr(sys, "frozen", False) or "--tray" in sys.argv:
        line("аргументы: " + " ".join(sys.argv[1:]))

    faulthandler.enable(_raw, all_threads=True)  # жёсткие вылеты — с traceback всех потоков
    sys.excepthook = _hook
    threading.excepthook = _thread_hook
    sys.unraisablehook = _unraisable
    sys.stderr = _Stream("ERR  ")   # traceback.print_exc() и print(..., file=sys.stderr)
    sys.stdout = _Stream("     ")   # обычный print(): у pythonw stdout нет, без этого всё терялось
    try:
        from PySide6.QtCore import qInstallMessageHandler
        qInstallMessageHandler(_qt_handler)
    except Exception:
        pass
    start = time.monotonic()

    def bye():
        mins = (time.monotonic() - start) / 60
        try:
            _raw.write(f"{_stamp()}       {EXIT_MARK} (проработала {mins:.0f} мин) ===\n")
            _raw.flush()
        except (OSError, ValueError):
            pass
    atexit.register(bye)
    return _raw
