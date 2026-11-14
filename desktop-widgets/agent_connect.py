"""Подключение AI-помощников к острову и виджету «Клод»: свои хуки в настройках каждого помощника.

    Claude Code  — ~/.claude/settings.json      -> claude_hook.py  (пишет claude_status.json)
    Codex        — ~/.codex/hooks.json           -> agent_hook.py codex …
    Antigravity  — ~/.gemini/config/hooks.json   -> agent_hook.py antigravity …

Хук пишет только состояние («правит файл X», «ждёт ответа»), без текста разговора. Чужие хуки не трогаем,
прежний файл настроек сохраняем копией рядом. disconnect() убирает только наши записи.
Удаление программы зовёт `claude_connect.py --disconnect` — он отключает всех помощников.

Connects AI coding agents (Claude Code, Codex, Antigravity) to the Dynamic Island via their hook settings."""
import ctypes
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
CLAUDE_HOOK = os.path.join(HERE, "claude_hook.py")
AGENT_HOOK = os.path.join(HERE, "agent_hook.py")
NAME = "liquid-desktop"  # имя нашего набора хуков у Antigravity

AGENTS = {
    "claude": {"title": "Claude Code", "home": os.path.join(HOME, ".claude"),
               "settings": os.path.join(HOME, ".claude", "settings.json"),
               # событие помощника -> аргумент хука
               "events": {"UserPromptSubmit": "prompt", "PreToolUse": "pre", "PostToolUse": "post",
                          "Notification": "notify", "Stop": "stop"},
               "matcher": ("PreToolUse", "PostToolUse")},
    "codex": {"title": "Codex", "home": os.path.join(HOME, ".codex"),
              "settings": os.path.join(HOME, ".codex", "hooks.json"),
              "events": {"UserPromptSubmit": "prompt", "PreToolUse": "pre", "PostToolUse": "post",
                         "PermissionRequest": "notify", "Stop": "stop"},
              "matcher": ()},  # без matcher — для любого инструмента (у Codex matcher — регулярка, «*» не годится)
    "antigravity": {"title": "Antigravity", "home": os.path.join(HOME, ".gemini"),
                    "settings": os.path.join(HOME, ".gemini", "config", "hooks.json"),
                    "events": {"PreInvocation": "invoke", "PreToolUse": "pre", "PostToolUse": "post",
                               "Stop": "stop"},
                    "matcher": ("PreToolUse", "PostToolUse")},
}
ORDER = ("claude", "codex", "antigravity")


def _python():
    """pythonw рядом с тем Python, на котором работают виджеты (у установленной версии — свой, в папке программы)."""
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return pyw if os.path.isfile(pyw) else sys.executable


def _bare(path):
    """Путь без кавычек и пробелов, с прямыми слешами: такую команду одинаково поймут cmd, PowerShell и bash
    (каким шеллом помощник запустит хук — заранее не знаем). С пробелами — короткое имя 8.3."""
    if " " in path:
        buf = ctypes.create_unicode_buffer(1024)
        if ctypes.windll.kernel32.GetShortPathNameW(path, buf, 1024) and " " not in buf.value:
            path = buf.value
        else:
            return '"' + path + '"'
    return path.replace("\\", "/")


def command(agent, arg):
    if agent == "claude":  # как и раньше: Claude Code зовёт хуки через свой шелл, кавычки ему подходят
        return f'"{_python()}" "{CLAUDE_HOOK}" {arg}'
    return f"{_bare(_python())} {_bare(AGENT_HOOK)} {agent} {arg}"


def _norm(text):
    return str(text).replace("\\", "/").lower()


def _ours_cmd(cmd):
    """Команда запускает наш хук именно из этой папки (хуки другой копии программы — чужие)."""
    c = _norm(cmd)
    if _norm(CLAUDE_HOOK) in c or _norm(AGENT_HOOK) in c:
        return True
    for path in (CLAUDE_HOOK, AGENT_HOOK):  # записано коротким именем 8.3
        buf = ctypes.create_unicode_buffer(1024)
        if ctypes.windll.kernel32.GetShortPathNameW(path, buf, 1024) and _norm(buf.value) in c:
            return True
    return False


def _ours(entry):
    """Запись события: {"matcher", "hooks": [...]} (Claude, Codex, инструменты Antigravity) или сам обработчик
    {"type", "command"} (прочие события Antigravity)."""
    if not isinstance(entry, dict):
        return False
    if "command" in entry:
        return _ours_cmd(entry.get("command", ""))
    return any(_ours_cmd(h.get("command", "")) for h in entry.get("hooks", []) if isinstance(h, dict))


def installed(agent):
    """Помощник стоит на этом компьютере (есть его папка настроек)."""
    return os.path.isdir(AGENTS[agent]["home"])


def _read(path):
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8-sig") as f:
        data = json.load(f)  # испорченный файл — ValueError наверх: не перезаписываем чужие настройки вслепую
    if not isinstance(data, dict):
        raise ValueError(os.path.basename(path) + " is not an object")
    return data


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".liquid.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _events(agent, data):
    """Словарь «событие -> список записей», где лежат наши хуки (создаётся при необходимости)."""
    if agent == "antigravity":  # верхний уровень — имена наборов хуков
        block = data.setdefault(NAME, {})
    else:
        block = data.setdefault("hooks", {})
    if not isinstance(block, dict):
        raise ValueError("hooks block is not an object")
    return block


def connected(agent):
    a = AGENTS[agent]
    try:
        data = _read(a["settings"])
    except (OSError, ValueError):
        return False
    block = data.get(NAME if agent == "antigravity" else "hooks") or {}
    if not isinstance(block, dict):
        return False
    return all(any(_ours(e) for e in block.get(ev, []) if isinstance(block.get(ev), list)) for ev in a["events"])


def connect(agent):
    """Добавить наши хуки. -> путь к копии прежнего файла настроек (или None, если его не было)."""
    a = AGENTS[agent]
    path = a["settings"]
    data = _read(path)
    backup = None
    if os.path.isfile(path):
        backup = path + time.strftime(".before-liquid-%Y%m%d-%H%M%S")
        shutil.copy2(path, backup)
    block = _events(agent, data)
    for event, arg in a["events"].items():
        old = block.get(event) if isinstance(block.get(event), list) else []
        entries = [e for e in old if not _ours(e)]  # старые наши — заменить
        handler = {"type": "command", "command": command(agent, arg)}
        if agent == "antigravity" and event not in a["matcher"]:
            ours = handler  # у Antigravity события без инструмента — сразу список обработчиков
        else:
            ours = {"hooks": [handler]}
            if event in a["matcher"]:
                ours = {"matcher": "*", **ours}
        block[event] = entries + [ours]
    if agent == "antigravity":
        block["enabled"] = True
    _write(path, data)
    return backup


def disconnect(agent):
    """Убрать только наши хуки; опустевшие события и блоки — тоже."""
    a = AGENTS[agent]
    path = a["settings"]
    if not os.path.isfile(path):
        return
    data = _read(path)
    key = NAME if agent == "antigravity" else "hooks"
    block = data.get(key)
    if not isinstance(block, dict):
        return
    changed = False
    for event in list(block):
        entries = block[event]
        if not isinstance(entries, list):
            continue
        keep = [e for e in entries if not _ours(e)]
        if len(keep) != len(entries):
            changed = True
            if keep:
                block[event] = keep
            else:
                del block[event]
    if changed:
        if not any(isinstance(v, list) for v in block.values()):
            del data[key]
        _write(path, data)


def disconnect_all():
    for agent in ORDER:
        try:
            disconnect(agent)
        except Exception:
            pass  # удаление программы не должно спотыкаться о чужой испорченный файл


if __name__ == "__main__":
    if "--disconnect" in sys.argv:
        disconnect_all()
