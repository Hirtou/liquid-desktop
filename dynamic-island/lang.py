"""Язык острова: русский (как написано в коде) или английский (lang_en.json рядом).

Свой выбор — в настройках острова («Язык»), хранится в config.json острова -> "lang"; не выбран — как у виджетов
(их config.json -> app.lang). Читается один раз при запуске, поэтому смена языка = перезапуск острова.
tr("Текст") -> перевод или сам текст. Шаблоны: tr("Фокус · {}").format(режим).
"""
import json
import os

ROOT = os.path.dirname(os.path.abspath(__file__))


def find_widgets_dir():
    """Папка виджетов рядом с островом: «виджеты» или desktop-widgets (как в репозитории)."""
    parent = os.path.dirname(ROOT)
    for name in ("виджеты", "desktop-widgets", "widgets"):
        if os.path.isfile(os.path.join(parent, name, "main.py")):
            return os.path.join(parent, name)
    return os.path.join(parent, "desktop-widgets")


LANGS = (("ru", "Русский"), ("en", "English"))


def _load(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _read_lang():
    own = _load(os.path.join(ROOT, "config.json"))
    if own.get("lang"):
        return own["lang"]
    widgets_dir = own.get("widgets_dir") or find_widgets_dir()
    return _load(os.path.join(widgets_dir, "config.json")).get("app", {}).get("lang", "ru")


LANG = _read_lang()
EN = _load(os.path.join(ROOT, "lang_en.json")) if LANG == "en" else {}


def tr(text):
    return EN.get(text, text) if EN else text
