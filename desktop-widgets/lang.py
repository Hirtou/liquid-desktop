"""Язык интерфейса: русский (как написано в коде) или английский (lang_en.json рядом).

Выбирается в каталоге («Язык»), хранится в config.json -> app.lang. Читается один раз при запуске:
подписи, собранные при запуске (меню, названия виджетов), тоже переводятся — поэтому смена языка = перезапуск.
tr("Текст") -> перевод или сам текст, если перевода нет. Шаблоны с подстановкой: tr("сброс {} · {}").format(a, b).
"""
import json
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
LANGS = (("ru", "Русский"), ("en", "English"))


def system_lang():
    """Язык по умолчанию (в настройках ещё не выбран) — как у Windows: русский для России и соседей, иначе английский."""
    try:
        import ctypes
        primary = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF
    except Exception:
        return "ru"
    # ru, uk, be, kk, ky, uz, tg
    return "ru" if primary in (0x19, 0x22, 0x23, 0x3F, 0x40, 0x43, 0x28) else "en"


def _read_lang():
    try:
        with open(os.path.join(ROOT, "config.json"), encoding="utf-8-sig") as f:
            return json.load(f).get("app", {}).get("lang") or system_lang()
    except (OSError, ValueError):
        return system_lang()


LANG = _read_lang()
EN = {}
if LANG == "en":
    try:
        with open(os.path.join(ROOT, "lang_en.json"), encoding="utf-8-sig") as f:
            EN = json.load(f)
    except (OSError, ValueError):
        EN = {}


def tr(text):
    return EN.get(text, text) if EN else text
