"""Проверка обновлений (только у установленной версии).

Установщик кладёт рядом с папками программ version.json: {"build": "20261112.1530"}.
В релизе на GitHub лежит такой же version.json — если там сборка новее, в трее появляется
«Установить обновление»: скачиваем LiquidDesktop-setup.exe во временную папку и запускаем его тихо,
он сам закрывает программы, ставит поверх (настройки не трогает) и снова запускает виджеты.
Без version.json (запуск из исходников) ничего не проверяется.
"""
import json
import os
import subprocess
import tempfile
import threading
import urllib.request

from PySide6.QtCore import QObject, QTimer, Signal

from lang import tr

REPO = "Hirtou/liquid-desktop"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
SETUP = "LiquidDesktop-setup.exe"
HERE = os.path.dirname(os.path.abspath(__file__))
LOCAL = os.path.join(os.path.dirname(HERE), "version.json")
EVERY = 6 * 3600 * 1000  # раз в 6 часов
UA = {"User-Agent": "LiquidDesktop-updater", "Accept": "application/vnd.github+json"}


def local_build():
    try:
        with open(LOCAL, encoding="utf-8-sig") as f:
            return str(json.load(f)["build"])
    except (OSError, ValueError, KeyError):
        return None


def _get(url, timeout=15):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


class Updater(QObject):
    found = Signal(str, str)      # сборка, ссылка на установщик
    progress = Signal(int)        # проценты скачивания
    failed = Signal(str)
    downloaded = Signal(str)      # путь к установщику

    def __init__(self, tray, menu, before_action, quit_app):
        super().__init__()
        self.build = local_build()
        self.tray, self.quit_app = tray, quit_app
        self.url = None
        self.busy = False
        self.action = menu.addAction(tr("Установить обновление"), self.install)
        menu.insertAction(before_action, self.action)
        self.action.setVisible(False)
        self.found.connect(self.on_found)
        self.progress.connect(lambda p: self.action.setText(tr("Скачивание обновления… {}%").format(p)))
        self.failed.connect(self.on_failed)
        self.downloaded.connect(self.run_setup)
        tray.messageClicked.connect(lambda: self.url and self.install())
        if self.build:
            QTimer.singleShot(20000, self.check)
            self.timer = QTimer(self, interval=EVERY, timeout=self.check)
            self.timer.start()

    def check(self):
        if self.busy:
            return
        threading.Thread(target=self._check, daemon=True).start()

    def _check(self):
        try:
            rel = json.loads(_get(API))
            assets = {a["name"]: a["browser_download_url"] for a in rel.get("assets", [])}
            if SETUP not in assets or "version.json" not in assets:
                return
            remote = str(json.loads(_get(assets["version.json"]))["build"])
            if remote > self.build:
                self.found.emit(remote, assets[SETUP])
        except Exception:  # нет сети, лимит GitHub — просто попробуем позже
            pass

    def on_found(self, remote, url):
        first = self.url is None
        self.url = url
        self.action.setText(tr("Установить обновление"))
        self.action.setVisible(True)
        if first:
            self.tray.showMessage(tr("Доступно обновление"),
                                  tr("Нажми, чтобы установить. Настройки и виджеты останутся."), self.tray.icon(), 8000)

    def install(self):
        if self.busy or not self.url:
            return
        self.busy = True
        self.action.setEnabled(False)
        threading.Thread(target=self._download, daemon=True).start()

    def _download(self):
        path = os.path.join(tempfile.gettempdir(), SETUP)
        try:
            req = urllib.request.Request(self.url, headers={"User-Agent": UA["User-Agent"]})
            with urllib.request.urlopen(req, timeout=30) as r, open(path + ".part", "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                got, last = 0, -1
                while chunk := r.read(1 << 18):
                    f.write(chunk)
                    got += len(chunk)
                    if total and (p := got * 100 // total) != last:
                        last = p
                        self.progress.emit(p)
            if total and got != total:
                raise OSError("incomplete")
            os.replace(path + ".part", path)
            self.downloaded.emit(path)
        except Exception as e:
            self.failed.emit(str(e))

    def on_failed(self, err):
        self.busy = False
        self.action.setEnabled(True)
        self.action.setText(tr("Установить обновление"))
        self.tray.showMessage(tr("Не удалось скачать обновление"), tr("Проверь интернет и попробуй ещё раз."),
                              self.tray.icon(), 6000)

    def run_setup(self, path):
        # установщик сам закроет остров и запустит виджеты заново; себя закрываем сразу
        subprocess.Popen([path, "/SILENT", "/SUPPRESSMSGBOXES", "/NOCANCEL", "/NORESTART"],
                         creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
        self.quit_app()
