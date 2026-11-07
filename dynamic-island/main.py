"""Динамический остров — отдельная программа (как док). Запуск: run.bat или pythonw main.py.

Значок в трее: включить/выключить остров, запуск с Windows, выход. Вторая копия не запускается.
Ошибки — в island.log."""
from lang import tr
import os

for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):  # numpy без лишнего пула потоков
    os.environ.setdefault(_var, "1")

import faulthandler  # noqa: E402
import sys  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import traceback  # noqa: E402
import winreg  # noqa: E402

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap  # noqa: E402
from PySide6.QtNetwork import QLocalServer, QLocalSocket  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon  # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))
SERVER = "DynamicIsland-Fluid"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "DynamicIsland"


def setup_log():
    log = open(os.path.join(ROOT, "island.log"), "a", encoding="utf-8", buffering=1)
    log.write(f"\n=== запуск {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    faulthandler.enable(log)

    def hook(kind, value, tb):
        log.write("".join(traceback.format_exception(kind, value, tb)))
    sys.excepthook = hook
    threading.excepthook = lambda a: hook(a.exc_type, a.exc_value, a.exc_traceback)
    if sys.stderr is None:
        sys.stderr = log
    return log


def make_icon():
    """Значок: чёрная капсула со светящейся кромкой."""
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QColor(255, 255, 255, 150))
    p.setBrush(QColor("#0b0b0f"))
    p.drawRoundedRect(QRectF(4, 20, 56, 24), 12, 12)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#ff9f0a"))
    p.drawEllipse(QPointF(17, 32), 5, 5)
    p.setBrush(QColor(244, 244, 247))
    p.drawRoundedRect(QRectF(27, 29, 24, 6), 3, 3)
    p.end()
    return QIcon(pm)


def autostart_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_NAME)
            return True
    except OSError:
        return False


def set_autostart(on):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
            winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, f'"{pyw}" "{os.path.join(ROOT, "main.py")}"')
        else:
            try:
                winreg.DeleteValue(k, RUN_NAME)
            except OSError:
                pass


def main():
    setup_log()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationDisplayName(tr("Динамический остров"))
    app.setFont(QFont("Segoe UI", 10))
    cmd = sys.argv[sys.argv.index("--cmd") + 1] if "--cmd" in sys.argv else ""
    if "--restart" in sys.argv:  # перезапуск (смена языка): подождать, пока прошлая копия закроется
        for _ in range(50):
            probe = QLocalSocket()
            probe.connectToServer(SERVER)
            if not probe.waitForConnected(100):
                break
            probe.abort()
            time.sleep(0.1)
    sock = QLocalSocket()
    sock.connectToServer(SERVER)
    if "--restart" not in sys.argv and sock.waitForConnected(300):  # уже запущен — передать команду и выйти
        if cmd:
            sock.write(cmd.encode())
            sock.waitForBytesWritten(300)
        return

    sys.path.insert(0, ROOT)
    from bridge import settings
    from island import Island
    island = Island()
    # всё, что создано при запуске (Qt, numpy, winrt), сборщик мусора больше не перебирает — его паузы короче,
    # анимация не спотыкается
    import gc
    gc.collect()
    gc.freeze()

    QLocalServer.removeServer(SERVER)
    server = QLocalServer(app)

    def on_command():
        s = server.nextPendingConnection()
        s.waitForReadyRead(300)
        if bytes(s.readAll()).decode(errors="ignore").strip() == "snap":  # показаться снимку экрана на 3 с
            island.on_screenshot()
    server.newConnection.connect(on_command)
    server.listen(SERVER)
    if autostart_enabled():
        set_autostart(True)  # обновить путь, если папку переносили

    tray = QSystemTrayIcon(make_icon(), app)
    tray.setToolTip(tr("Динамический остров"))
    menu = QMenu()
    menu.addAction(tr("Настройки…"), island.open_settings)
    on = QAction(tr("Остров включён"), menu, checkable=True, checked=settings.get("enabled", True))
    on.toggled.connect(island.set_enabled)
    menu.addAction(on)
    keys = island.hotkey.title() if island.hotkey_ok else tr("{} — занята, смени в config.json").format(island.hotkey.title())
    hint = QAction(tr("Спрятать / вернуть: {}").format(keys), menu, enabled=False)
    menu.addAction(hint)
    auto = QAction(tr("Запускать с Windows"), menu, checkable=True, checked=autostart_enabled())
    auto.toggled.connect(set_autostart)
    menu.addAction(auto)
    menu.addSeparator()
    menu.addAction(tr("Выход"), app.quit)
    menu.aboutToShow.connect(lambda: on.setChecked(settings.get("enabled", True)))  # могли выключить правым кликом
    tray.setContextMenu(menu)
    tray.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
