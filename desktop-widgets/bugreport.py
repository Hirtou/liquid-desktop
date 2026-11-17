"""«Сообщить о баге» (кнопка в окне настроек): открывает Telegram-канал проекта. Буфер обмена не трогает.
«Сообщить об ошибке» (меню в трее): открывает в браузере новый issue на GitHub с уже заполненным текстом —
версия, Windows, язык, включённые виджеты и последняя ошибка из журналов виджетов и острова.
Ничего не отправляется само: человек видит текст, дописывает, что случилось, и сам нажимает Submit.
Из журнала перед вставкой убирается личное: имя пользователя и путь к его папке, имя компьютера, почта."""
import json
import os
import re
import sys
import urllib.parse

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

REPO = "Hirtou/liquid-desktop"
TELEGRAM = "https://t.me/Liquid_Desktop"
BOOSTY = "https://boosty.to/liquiddesktop"  # «Поддержать автора»
HERE = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(HERE)
MAX_URL = 7500          # длиннее GitHub и браузеры обрезают
STAMP = re.compile(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d")      # запись журнала начинается со времени
ERR_TAG = re.compile(r"\S+ \S+ (ERR|CRASH|QT)")              # …и это запись об ошибке (applog.py)
_ISLAND = [os.path.join(PARENT, d, "island.log") for d in ("dynamic-island", "остров")]
LOGS = [("widgets", os.path.join(HERE, "widgets.log")),
        ("island", next((p for p in _ISLAND if os.path.exists(p)), _ISLAND[0]))]


def version():
    try:
        with open(os.path.join(PARENT, "version.json"), encoding="utf-8-sig") as f:
            return "build " + str(json.load(f)["build"])
    except (OSError, ValueError, KeyError):
        return "from source"


def windows():
    try:
        v = sys.getwindowsversion()
        return f"Windows {v.major}.{v.minor}.{v.build}"
    except AttributeError:
        return sys.platform


def sanitize(text):
    """Убрать личное: папку пользователя, его имя, имя компьютера, почту."""
    home = os.path.expanduser("~")
    for value, repl in ((home, "~"), (home.replace("\\", "/"), "~")):
        if value and len(value) > 3:
            text = re.sub(re.escape(value), repl, text, flags=re.I)
    for env, repl in (("USERNAME", "<user>"), ("COMPUTERNAME", "<pc>"), ("USERDOMAIN", "<pc>")):
        value = os.environ.get(env, "")
        if len(value) >= 3:
            text = re.sub(r"(?<![A-Za-z0-9])" + re.escape(value) + r"(?![A-Za-z0-9])", repl, text, flags=re.I)
    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "<email>", text)
    return text


def last_error(path, limit):
    """Последняя ошибка из журнала: блок от последнего Traceback / Fatal / Error до конца запуска."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 65536))
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return ""
    lines = text.splitlines()
    start = None
    marks = ("[падение]", "[ошибка]", "Traceback", "Fatal Python error", "Windows fatal exception")
    for i in range(len(lines) - 1, -1, -1):
        if any(m in lines[i] for m in marks):
            start = i
            # traceback под заголовком записи — брать с заголовка: там где случилось и что за ошибка
            while start > 0 and "Traceback" in lines[start] and ("[ошибка]" in lines[start - 1]
                                                                  or "[падение]" in lines[start - 1]):
                start -= 1
            break
    if start is None:
        return ""
    block = lines[start:start + 40]
    # дальше нового «=== запуск» и следующей обычной записи журнала не берём
    for j, s in enumerate(block[1:], 1):
        if s.startswith("=== ") or (STAMP.match(s) and not ERR_TAG.match(s)):
            block = block[:j]
            break
    out = sanitize("\n".join(block).strip())
    return out[-limit:]


def visible_widgets():
    try:
        with open(os.path.join(HERE, "config.json"), encoding="utf-8-sig") as f:
            cfg = json.load(f)
        return ", ".join(k for k, v in cfg.items() if isinstance(v, dict) and v.get("visible")) or "none"
    except (OSError, ValueError):
        return "unknown"


def build_url(limit=1800):
    from lang import LANG
    head = (f"**What happened?**\n\n\n**Steps to reproduce**\n1. \n\n---\n"
            f"Liquid Desktop {version()} · {windows()} · language {LANG}\n"
            f"Widgets on screen: {visible_widgets()}\n")
    body = head
    for name, path in LOGS:
        err = last_error(path, limit)
        if err:
            body += (f"\n<details><summary>Last error ({name}.log)</summary>\n\n```\n{err}\n```\n</details>\n")
    query = urllib.parse.urlencode({"title": "Bug: ", "labels": "bug", "body": body})
    url = f"https://github.com/{REPO}/issues/new?{query}"
    if len(url) > MAX_URL and limit > 200:
        return build_url(limit // 2)     # журнал длинный — берём хвост покороче
    return url


def report():
    QDesktopServices.openUrl(QUrl(build_url()))


def chat_text(limit=1200):
    """Отчёт для чата: версия, Windows, язык, виджеты на столе и последняя ошибка (без личного)."""
    from lang import LANG, tr
    text = (tr("Что случилось:") + "\n\n\n---\n"
            f"Liquid Desktop {version()} · {windows()} · {LANG}\n"
            + tr("Виджеты на столе:") + f" {visible_widgets()}\n")
    for name, path in LOGS:
        err = last_error(path, limit)
        if err:
            text += "\n" + tr("Последняя ошибка ({}):").format(name + ".log") + f"\n{err}\n"
    return text


def support():
    """«Поддержать автора»: открыть страницу проекта на Boosty в браузере."""
    QDesktopServices.openUrl(QUrl(BOOSTY))


def report_telegram():
    """Открыть канал в Telegram. В буфер ничего не кладём — у человека там может быть своё."""
    QDesktopServices.openUrl(QUrl(TELEGRAM))
