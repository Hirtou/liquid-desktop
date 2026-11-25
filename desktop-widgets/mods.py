"""Моды: дополнения от сообщества, которые проверил автор Liquid Desktop.

Откуда: только репозиторий автора (Hirtou/liquid-desktop, папка mods/). Там лежит список mods/index.json —
название, автор, версия и у каждого файла мода его sha256. Программа качает файлы оттуда же и сверяет каждый
с суммой из списка: файл подменили или он побился — мод не ставится. Чужие адреса программа не принимает.

Куда: %LOCALAPPDATA%\\LiquidDesktop\\mods\\<id> — переустановка программы моды не трогает.
Что умеет мод (API 1): новый виджет — класс-наследник core.DesktopWidget в своём .py.
Включённые моды подхватываются при запуске; включил/выключил/поставил — виджет сразу в каталоге (без перезапуска).
Мод с ошибкой не роняет программу: не загрузился — пишем в лог и показываем на вкладке; падает при
рисовании — после нескольких ошибок прячется.

Mods: community add-ons reviewed by the Liquid Desktop author, downloaded only from the author's repository
and checked by sha256 before they are installed."""
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request

import applog
from core import ROOT, config

API = 1  # какую версию модов понимает эта программа
REPO = "https://raw.githubusercontent.com/Hirtou/liquid-desktop/main/mods"
# LIQUID_MODS_URL — только для проверки на своём компьютере (локальный сервер), в программе не настраивается
BASE = (os.environ.get("LIQUID_MODS_URL") or REPO).rstrip("/")
STORE = os.path.join(os.environ.get("LOCALAPPDATA") or ROOT, "LiquidDesktop", "mods")
# моды, которые идут вместе с программой: при первом запуске ставятся и включаются сами (см. seed_bundled)
BUNDLED = os.path.join(ROOT, "bundled_mods")
ID_RE = re.compile(r"^[a-z0-9_]{2,32}$")
PATH_RE = re.compile(r"^[A-Za-z0-9_\-]+(/[A-Za-z0-9_\-]+)*\.[A-Za-z0-9]+$")
EXTS = {".py", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".json", ".txt", ".wav", ".ttf", ".otf"}
MAX_FILE = 8 * 1024 * 1024
MAX_FILES = 60
AGENT = "LiquidDesktop-mods"

errors = {}   # id -> почему не загрузился / выключился (показываем на вкладке)
loaded = {}   # id -> класс виджета


# ---------------------------------------------------------------- список модов

def check_entry(e):
    """Запись о моде из списка (или mod.json) -> чистая запись; не годится — ValueError с причиной."""
    if not isinstance(e, dict):
        raise ValueError("не запись")
    mid = e.get("id")
    if not isinstance(mid, str) or not ID_RE.match(mid):
        raise ValueError(f"плохой id: {mid!r}")
    out = {"id": mid}
    for k in ("name", "author", "version"):
        v = e.get(k)
        if not isinstance(v, str) or not v.strip() or len(v) > 80:
            raise ValueError(f"{mid}: нет поля {k}")
        out[k] = v.strip()
    for k in ("name_en", "description", "description_en", "author_url", "class", "entry"):
        v = e.get(k, "")
        out[k] = v.strip()[:400] if isinstance(v, str) else ""
    if out["author_url"] and not out["author_url"].startswith(("https://github.com/", "https://t.me/")):
        out["author_url"] = ""  # ссылки — только на GitHub или Telegram автора
    api = e.get("api", 1)
    if not isinstance(api, int) or api < 1:
        raise ValueError(f"{mid}: плохая версия API")
    out["api"] = api
    if e.get("type", "widget") != "widget":
        raise ValueError(f"{mid}: тип {e.get('type')!r} эта версия не знает")
    out["type"] = "widget"
    if not out["class"].isidentifier():
        raise ValueError(f"{mid}: нет класса виджета")
    files = e.get("files")
    if not isinstance(files, dict) or not files or len(files) > MAX_FILES:
        raise ValueError(f"{mid}: нет списка файлов")
    clean = {}
    for path, digest in files.items():
        if (not isinstance(path, str) or not PATH_RE.match(path) or ".." in path
                or os.path.splitext(path)[1].lower() not in EXTS or path.lower() == "mod.json"):
            raise ValueError(f"{mid}: недопустимый файл {path!r}")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(f"{mid}: нет sha256 у {path}")
        clean[path] = digest
    out["files"] = clean
    if not out["entry"].endswith(".py") or out["entry"] not in clean:
        raise ValueError(f"{mid}: нет главного файла")
    tile = e.get("tile")
    out["tile"] = ([str(c) for c in tile[:2]] if isinstance(tile, list) and len(tile) >= 2
                   and all(isinstance(c, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", c) for c in tile[:2]) else [])
    icon = e.get("icon", "")
    out["icon"] = icon if isinstance(icon, str) and icon in clean and icon.lower().endswith(".png") else ""
    return out


def _get(url, limit=MAX_FILE):
    req = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise ValueError("файл слишком большой")
    return data


def fetch_index():
    """Список модов из репозитория автора -> [запись, ...]. Сеть — вызывать из фонового потока.
    Битые записи пропускаем (пишем в лог), остальные показываем."""
    try:
        raw = json.loads(_get(f"{BASE}/index.json", 1024 * 1024).decode("utf-8"))
    except urllib.error.HTTPError as err:
        if err.code == 404:  # список ещё не выложен — модов просто нет
            return []
        raise
    mods = raw.get("mods") if isinstance(raw, dict) else None
    if not isinstance(mods, list):
        raise ValueError("в index.json нет списка mods")
    out = []
    for e in mods:
        try:
            out.append(check_entry(e))
        except ValueError as err:
            applog.line(f"моды: запись пропущена — {err}")
    return out


# ---------------------------------------------------------------- что стоит

def installed():
    """Поставленные моды: {id: запись из mod.json (+ source: catalog / local)}."""
    out = {}
    if not os.path.isdir(STORE):
        return out
    for mid in sorted(os.listdir(STORE)):
        path = os.path.join(STORE, mid, "mod.json")
        if not ID_RE.match(mid) or not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
            e = check_entry(raw)
            if e["id"] != mid:
                continue
            e["source"] = raw.get("source") if raw.get("source") in ("catalog", "local", "bundled") else "catalog"
            out[mid] = e
        except (OSError, ValueError) as err:
            errors[mid] = str(err)
    return out


def _state():
    s = config.section("mods")
    if not isinstance(s.get("enabled"), list):
        s["enabled"] = []
    return s


def is_enabled(mid):
    return mid in _state()["enabled"]


def set_enabled(mid, on):
    s = _state()
    s["enabled"] = [m for m in s["enabled"] if m != mid] + ([mid] if on else [])
    config.save()


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _put(mid, files, entry, source):
    """Файлы мода ({путь: байты}) -> во временную папку, потом подменой на место старой версии."""
    os.makedirs(STORE, exist_ok=True)
    tmp = os.path.join(STORE, f".new_{mid}_{int(time.time() * 1000)}")
    try:
        for path, data in files.items():
            dst = os.path.join(tmp, *path.split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as f:
                f.write(data)
        with open(os.path.join(tmp, "mod.json"), "w", encoding="utf-8") as f:
            json.dump({**entry, "source": source}, f, ensure_ascii=False, indent=2)
        final = os.path.join(STORE, mid)
        old = None
        if os.path.exists(final):
            old = os.path.join(STORE, f".old_{mid}_{int(time.time() * 1000)}")
            os.replace(final, old)
        os.replace(tmp, final)
        if old:
            shutil.rmtree(old, ignore_errors=True)
    finally:
        if os.path.exists(tmp):
            shutil.rmtree(tmp, ignore_errors=True)


def install(entry):
    """Поставить / обновить мод из списка автора. Каждый файл сверяем с sha256 из списка. Сеть — в фоне.
    -> None или текст ошибки (мод при ошибке не ставится и прежняя версия остаётся)."""
    try:
        e = check_entry(entry)
        if e["api"] > API:
            return "мод для более новой версии программы — обнови Liquid Desktop"
        files = {}
        for path, digest in e["files"].items():
            data = _get(f"{BASE}/{e['id']}/{path}")
            if _sha(data) != digest:
                return f"файл {path} не совпал с проверенным — мод не поставлен"
            files[path] = data
        _put(e["id"], files, e, "catalog")
        errors.pop(e["id"], None)
        applog.line(f"моды: поставлен {e['id']} {e['version']}")
        return None
    except Exception as err:
        applog.error("mods.install", err)
        return str(err) or type(err).__name__


def install_local(folder, source="local"):
    """Мод из папки на диске (проверка присланного кода до публикации). В папке — mod.json; список файлов
    и суммы считаем сами. -> (id, None) или (None, текст ошибки)."""
    try:
        with open(os.path.join(folder, "mod.json"), encoding="utf-8") as f:
            raw = json.load(f)
        files, sums = {}, {}
        for base, dirs, names in os.walk(folder):
            dirs[:] = [d for d in dirs if not d.startswith((".", "__"))]
            for n in names:
                full = os.path.join(base, n)
                rel = os.path.relpath(full, folder).replace("\\", "/")
                if rel == "mod.json" or os.path.splitext(n)[1].lower() not in EXTS:
                    continue
                with open(full, "rb") as fh:
                    data = fh.read(MAX_FILE + 1)
                if len(data) > MAX_FILE:
                    return None, f"{rel}: файл больше 8 МБ"
                files[rel], sums[rel] = data, _sha(data)
        e = check_entry({**raw, "files": sums})
        if e["api"] > API:
            return None, "мод для более новой версии программы"
        _put(e["id"], files, e, source)
        errors.pop(e["id"], None)
        applog.line(f"моды: поставлен {'вместе с программой' if source == 'bundled' else 'из папки'} {e['id']} {e['version']}")
        return e["id"], None
    except Exception as err:
        applog.error("mods.install_local", err)
        return None, str(err) or type(err).__name__


def remove(mid):
    if not ID_RE.match(mid):
        return
    set_enabled(mid, False)
    shutil.rmtree(os.path.join(STORE, mid), ignore_errors=True)
    errors.pop(mid, None)
    applog.line(f"моды: удалён {mid}")


def newer(a, b):
    """Версия a новее b? «1.2.10» > «1.2.9»; непонятное — сравниваем как строки."""
    def parts(v):
        return [int(x) if x.isdigit() else x for x in re.split(r"[.\-]", v)]
    try:
        return parts(a) > parts(b)
    except TypeError:
        return a != b


# ---------------------------------------------------------------- загрузка при запуске

def _guard(cls, mid):
    """Мод падает при рисовании — не сыпать ошибками бесконечно: после 5 ошибок виджет прячется."""
    orig = cls.paintEvent
    fails = [0]

    def paintEvent(self, event):
        try:
            orig(self, event)
        except Exception as err:
            fails[0] += 1
            applog.error(f"mods.{mid}.paint", err)
            if fails[0] >= 5:
                errors[mid] = f"падает при рисовании: {err}"
                from PySide6.QtCore import QTimer
                QTimer.singleShot(0, self.hide)
    cls.paintEvent = paintEvent


def seed_bundled():
    """Моды из bundled_mods/ (идут в установщике): в первый раз — поставить и включить; вышла новая версия
    такого мода вместе с программой — обновить. Выключил или удалил сам — больше не трогаем (список seeded)."""
    if not os.path.isdir(BUNDLED):
        return
    s = _state()
    seeded = s.get("seeded") if isinstance(s.get("seeded"), list) else []
    have = installed()
    changed = False
    for mid in sorted(os.listdir(BUNDLED)):
        folder = os.path.join(BUNDLED, mid)
        if not ID_RE.match(mid) or not os.path.isfile(os.path.join(folder, "mod.json")):
            continue
        try:
            with open(os.path.join(folder, "mod.json"), encoding="utf-8") as f:
                version = str(json.load(f).get("version", ""))
        except (OSError, ValueError) as err:
            applog.error(f"mods.bundled {mid}", err)
            continue
        inst = have.get(mid)
        first = mid not in seeded
        if first and inst is None or (inst is not None and inst["source"] == "bundled" and newer(version, inst["version"])):
            got, err = install_local(folder, "bundled")
            if err:
                continue
        if first:
            seeded.append(mid)
            if mid not in s["enabled"]:
                s["enabled"].append(mid)
            changed = True
    if changed:
        s["seeded"] = seeded
        config.save()


def load_one(mid, e=None):
    """Один включённый мод -> класс виджета (или None, причина — в errors). Можно звать и на ходу:
    поставили / включили мод — его виджет сразу в каталоге, без перезапуска (каталог: Catalog.mod_changed)."""
    from core import DesktopWidget
    import icons
    import lang
    if e is None:
        e = installed().get(mid)
    if e is None:
        return None
    try:
        if e["api"] > API:
            raise ValueError("мод для более новой версии программы")
        folder = os.path.join(STORE, mid)
        name = f"liquid_mod_{mid}"
        spec = importlib.util.spec_from_file_location(name, os.path.join(folder, *e["entry"].split("/")))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        if folder not in sys.path:
            sys.path.append(folder)  # мод может разложить код на несколько своих файлов
        spec.loader.exec_module(module)
        cls = getattr(module, e["class"], None)
        if not (isinstance(cls, type) and issubclass(cls, DesktopWidget)):
            raise ValueError(f"в {e['entry']} нет виджета {e['class']}")
        en = lang.LANG == "en"
        cls.key = f"mod_{mid}"
        cls.title = (e["name_en"] if en and e["name_en"] else e["name"])
        desc = (e["description_en"] if en and e["description_en"] else e["description"])
        cls.description = (desc + " · " if desc else "") + ("mod by " if en else "мод от ") + e["author"]
        cls.mod_info = e
        if e["tile"]:
            icons.TILES[cls.key] = tuple(e["tile"])
        if e["icon"]:
            icons.MOD_ICONS[cls.key] = os.path.join(folder, *e["icon"].split("/"))
        icons.MOD_LETTERS[cls.key] = cls.title[:1].upper()
        _guard(cls, mid)
        loaded[mid] = cls
        errors.pop(mid, None)
        applog.line(f"моды: загружен {mid} {e['version']} ({e['author']})")
        return cls
    except Exception as err:
        loaded.pop(mid, None)
        errors[mid] = str(err) or type(err).__name__
        applog.error(f"mods.load {mid}", err)
        return None


def load_widgets():
    """Включённые моды -> классы виджетов для каталога. Ключ виджета — «mod_<id>» (свой раздел настроек)."""
    try:
        seed_bundled()
    except Exception as err:
        applog.error("mods.seed_bundled", err)
    have = installed()
    out = []
    for mid in list(_state()["enabled"]):
        if mid in have:
            cls = load_one(mid, have[mid])
            if cls is not None:
                out.append(cls)
    return out
