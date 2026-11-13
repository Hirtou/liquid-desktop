"""Подключение виджета «Клод» к Claude Code: хуки в ~/.claude/settings.json.

Claude Code перед и после каждого своего действия запускает claude_hook.py — тот пишет в claude_status.json,
что сейчас делается (только состояние и имя файла/команды, без текста разговора). Виджет читает этот файл.

connect() — добавить наши хуки (чужие не трогаем; прежний файл — копией рядом), disconnect() — убрать только наши.
Удаление программы зовёт `claude_connect.py --disconnect`, чтобы Claude Code не звал файл, которого больше нет.

Connects the Claude widget to Claude Code by adding hooks to ~/.claude/settings.json (other hooks are kept)."""
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "claude_hook.py")
SETTINGS = os.path.join(os.path.expanduser("~"), ".claude", "settings.json")
# событие Claude Code -> аргумент хука
EVENTS = {"UserPromptSubmit": "prompt", "PreToolUse": "pre", "PostToolUse": "post", "Notification": "notify",
          "Stop": "stop"}
WITH_MATCHER = ("PreToolUse", "PostToolUse")  # у событий инструментов — для любого инструмента


def _python():
    """pythonw рядом с тем Python, на котором работают виджеты (у установленной версии — свой, в папке программы)."""
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return pyw if os.path.isfile(pyw) else sys.executable


def _ours(entry):
    """Наша ли запись хука: команда запускает claude_hook.py именно из этой папки
    (хуки другой копии программы — чужие: их не меняем и при удалении не трогаем)."""
    return any(HOOK.lower() in str(h.get("command", "")).lower()
               for h in entry.get("hooks", []) if isinstance(h, dict))


def _read():
    if not os.path.isfile(SETTINGS):
        return {}
    with open(SETTINGS, encoding="utf-8-sig") as f:
        data = json.load(f)  # испорченный файл — ValueError наверх: не перезаписываем чужие настройки вслепую
    if not isinstance(data, dict):
        raise ValueError("settings.json is not an object")
    return data


def _write(data):
    os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
    tmp = SETTINGS + ".liquid.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, SETTINGS)


def connected():
    try:
        hooks = _read().get("hooks") or {}
    except (OSError, ValueError):
        return False
    return all(any(_ours(e) for e in hooks.get(ev, []) if isinstance(e, dict)) for ev in EVENTS)


def connect():
    """Добавить хуки. -> путь к копии прежнего settings.json (или None, если его не было)."""
    data = _read()
    backup = None
    if os.path.isfile(SETTINGS):
        backup = SETTINGS + time.strftime(".before-liquid-%Y%m%d-%H%M%S")
        shutil.copy2(SETTINGS, backup)
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("\"hooks\" in settings.json is not an object")
    py = _python()
    for event, arg in EVENTS.items():
        entries = [e for e in hooks.get(event, []) if isinstance(e, dict) and not _ours(e)]  # старые наши — заменить
        ours = {"hooks": [{"type": "command", "command": f'"{py}" "{HOOK}" {arg}'}]}
        if event in WITH_MATCHER:
            ours = {"matcher": "*", **ours}
        hooks[event] = entries + [ours]
    _write(data)
    return backup


def disconnect():
    """Убрать только наши хуки; пустые события — тоже."""
    if not os.path.isfile(SETTINGS):
        return
    data = _read()
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return
    changed = False
    for event in list(hooks):
        entries = hooks[event]
        if not isinstance(entries, list):
            continue
        keep = [e for e in entries if not (isinstance(e, dict) and _ours(e))]
        if len(keep) != len(entries):
            changed = True
            if keep:
                hooks[event] = keep
            else:
                del hooks[event]
    if changed:
        if not hooks:
            del data["hooks"]
        _write(data)


if __name__ == "__main__":
    if "--disconnect" in sys.argv:
        try:
            disconnect()
        except Exception:
            pass  # удаление программы не должно спотыкаться о чужой испорченный файл
