"""Связь с виджетами (папка виджетов рядом) и своё: настройки острова, громкость.

Таймер и «Фокус» — те же, что у виджетов: их состояние лежит в config.json виджетов, остров его читает.
Менять (пауза, +1 мин, сброс) — через сами виджеты, если они запущены (команда «cfg» в их окно-сервер):
иначе они перезаписали бы файл своей копией. Не запущены — правим файл сами."""
import json
import os
import time

from PySide6.QtNetwork import QLocalSocket

from lang import find_widgets_dir

ROOT = os.path.dirname(os.path.abspath(__file__))
SERVER = "DesktopWidgets-Liquid"  # окно-сервер виджетов (main.py виджетов)


class Settings:
    """Свой config.json острова."""

    def __init__(self):
        self.path = os.path.join(ROOT, "config.json")
        try:
            with open(self.path, encoding="utf-8-sig") as f:  # -sig: Блокнот мог дописать BOM
                self.data = json.load(f)
            if not isinstance(self.data, dict):
                raise ValueError("не словарь")
        except FileNotFoundError:
            self.data = {}
        except (OSError, ValueError):  # испорчен — отложить копию, а не затереть молча
            self.data = {}
            try:
                os.replace(self.path, self.path[:-5] + time.strftime(".broken-%Y%m%d-%H%M%S.json"))
            except OSError:
                pass

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.reload_if_changed()  # раздел «Остров» в окне виджетов мог только что поменять файл — не затереть
        self.data[key] = value
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)
        self.mtime = self._mtime()

    def _mtime(self):
        try:
            return os.path.getmtime(self.path)
        except OSError:
            return None

    def reload_if_changed(self):
        """Файл поменяли снаружи (раздел «Остров» в окне виджетов) — перечитать. -> поменялся ли."""
        m = self._mtime()
        if m is None or m == getattr(self, "mtime", None):
            return False
        try:
            with open(self.path, encoding="utf-8-sig") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return False  # как раз пишут — в следующий раз
        if not isinstance(data, dict):
            return False
        self.data, self.mtime = data, m
        return True


settings = Settings()


class Widgets:
    def __init__(self):
        self.dir = settings.get("widgets_dir") or find_widgets_dir()
        self.config_path = os.path.join(self.dir, "config.json")
        self.cfg, self.cfg_mtime = {}, 0
        self.alive, self.alive_checked = False, 0.0
        self.alert_path = os.path.join(self.dir, "weather_alert.json")
        self.alert_mtime, self.alert_checked = 0, 0.0

    def section(self, name):
        """Раздел настроек виджетов (перечитываем, когда файл поменялся)."""
        try:
            m = os.path.getmtime(self.config_path)
        except OSError:
            return self.cfg.setdefault(name, {})
        if m != self.cfg_mtime:
            try:
                with open(self.config_path, encoding="utf-8-sig") as f:
                    self.cfg = json.load(f)
                self.cfg_mtime = m
            except (OSError, ValueError):
                pass  # виджеты как раз пишут — прочитаем в следующий раз
        return self.cfg.setdefault(name, {})

    def running(self):
        now = time.monotonic()
        if now - self.alive_checked > 3:
            self.alive_checked = now
            sock = QLocalSocket()
            sock.connectToServer(SERVER)
            self.alive = sock.waitForConnected(80)
            if self.alive:
                sock.write(b"ping")
                sock.waitForBytesWritten(80)
                sock.disconnectFromServer()
        return self.alive

    def widget_open(self, key):
        """Виджет стоит на столе (тогда он сам пищит и переключает) — по настройкам виджетов."""
        return self.running() and bool(self.section(key).get("visible"))

    def patch(self, name, changes):
        """Поменять раздел: {ключ: значение}, None — убрать ключ."""
        sec = self.section(name)
        for k, v in changes.items():  # сразу у себя — чтобы нарисовать без ожидания
            if v is None:
                sec.pop(k, None)
            else:
                sec[k] = v
        if self.running():
            sock = QLocalSocket()
            sock.connectToServer(SERVER)
            if sock.waitForConnected(200):
                sock.write(("cfg " + json.dumps({"section": name, "set": changes}, ensure_ascii=False)).encode())
                sock.waitForBytesWritten(200)
                sock.disconnectFromServer()
                return
        try:
            with open(self.config_path, encoding="utf-8-sig") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        part = data.setdefault(name, {})
        for k, v in changes.items():
            if v is None:
                part.pop(k, None)
            else:
                part[k] = v
        tmp = self.config_path + ".island.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.config_path)
        self.cfg, self.cfg_mtime = data, os.path.getmtime(self.config_path)

    def weather_alert(self):
        """Новое предупреждение «Погоды» (через N мин дождь / дождь закончится) — один раз, иначе None.
        Файл пишет виджет «Погода» после каждого обновления; проверяем раз в 30 с."""
        now = time.monotonic()
        if now - self.alert_checked < 30:
            return None
        self.alert_checked = now
        try:
            m = os.path.getmtime(self.alert_path)
            if m == self.alert_mtime:
                return None
            with open(self.alert_path, encoding="utf-8-sig") as f:
                alert = json.load(f)
            self.alert_mtime = m
        except (OSError, ValueError):
            return None
        if not alert.get("key") or time.time() - alert.get("updated", 0) > 20 * 60:
            return None  # пусто или старое (прогноз мог уже сбыться)
        return alert


widgets = Widgets()


# ---------- таймер и помидор: те же поля, что у виджетов «Таймер» и «Фокус» ----------

FOCUS_PRESETS = {"25/5": (25, 5), "50/10": (50, 10)}


def timer_cfg():
    c = widgets.section("timer")
    c.setdefault("duration", 5 * 60)
    return c


def timer_left(c, now):
    if c.get("end"):
        return max(0.0, c["end"] - now)
    return float(c.get("left", c["duration"]))


def focus_cfg():
    c = widgets.section("focus")
    c.setdefault("preset", "25/5")
    c.setdefault("mode", "work")
    return c


def focus_length(c, mode=None):
    work, rest = FOCUS_PRESETS.get(c["preset"], (25, 5))
    return (work if (mode or c["mode"]) == "work" else rest) * 60


def focus_left(c, now):
    if c.get("end"):
        return max(0.0, c["end"] - now)
    return float(c.get("left", focus_length(c)))


def focus_today(c):
    d = c.get("done", {})
    return d.get("count", 0) if d.get("day") == time.strftime("%Y-%m-%d") else 0


# ---------- громкость ----------

class Audio:
    """Общая громкость (Windows Core Audio через pycaw): прочитать, поменять, какое устройство."""

    def __init__(self):
        self.endpoint, self.name = None, ""
        self.refresh()

    def refresh(self):
        try:
            from pycaw.pycaw import AudioUtilities
            dev = AudioUtilities.GetSpeakers()
            self.endpoint = dev.EndpointVolume
            name = dev.FriendlyName or ""
            # «Динамики (fifine Headset)» -> «fifine Headset»
            self.name = name[name.find("(") + 1:name.rfind(")")] if "(" in name and name.endswith(")") else name
        except Exception:
            self.endpoint = None

    def read(self):
        """(громкость 0..1, без звука?) или None."""
        try:
            return round(self.endpoint.GetMasterVolumeLevelScalar(), 3), bool(self.endpoint.GetMute())
        except Exception:
            return None

    def set(self, v):
        """Громкость 0..1 (тянут ползунок); выше нуля — снять «без звука»."""
        try:
            v = max(0.0, min(1.0, v))
            self.endpoint.SetMasterVolumeLevelScalar(v, None)
            if v > 0 and self.endpoint.GetMute():
                self.endpoint.SetMute(0, None)
        except Exception:
            pass

    def change(self, delta):
        try:
            v = max(0.0, min(1.0, self.endpoint.GetMasterVolumeLevelScalar() + delta))
            self.endpoint.SetMasterVolumeLevelScalar(v, None)
            if v > 0 and self.endpoint.GetMute():
                self.endpoint.SetMute(0, None)
        except Exception:
            pass
