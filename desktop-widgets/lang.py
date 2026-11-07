"""Язык интерфейса: русский (как написано в коде) или английский (lang_en.json рядом).

Выбирается в каталоге («Язык»), хранится в config.json -> app.lang. Читается один раз при запуске:
подписи, собранные при запуске (меню, названия виджетов), тоже переводятся — поэтому смена языка = перезапуск.
tr("Текст") -> перевод или сам текст, если перевода нет. Шаблоны с подстановкой: tr("сброс {} · {}").format(a, b).
"""
import json
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
LANGS = (("ru", "Русский"), ("en", "English"))


def _read_lang():
    try:
        with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as f:
            return json.load(f).get("app", {}).get("lang", "ru")
    except (OSError, ValueError):
        return "ru"


LANG = _read_lang()
EN = {}
if LANG == "en":
    try:
        with open(os.path.join(ROOT, "lang_en.json"), encoding="utf-8") as f:
            EN = json.load(f)
    except (OSError, ValueError):
        EN = {}


def tr(text):
    return EN.get(text, text) if EN else text
