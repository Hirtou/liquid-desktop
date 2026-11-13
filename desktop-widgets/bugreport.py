"""«Сообщить об ошибке» (меню в трее): открывает в браузере новый issue на GitHub с уже заполненным текстом —
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
HERE = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(HERE)
MAX_URL = 7500          # длиннее GitHub и браузеры обрезают
LOGS = [("widgets", os.path.join(HERE, "widgets.log")),
        ("island", os.path.join(PARENT, "dynamic-island", "island.log"))]


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
    for i in range(len(lines) - 1, -1, -1):
        s = lines[i]
        if s.startswith("Traceback") or "Fatal Python error" in s or "Windows fatal exception" in s:
            start = i
            break
    if start is None:
        return ""
    block = lines[start:start + 40]
    # дальше нового «=== запуск» не берём
    for j, s in enumerate(block[1:], 1):
        if s.startswith("=== "):
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
