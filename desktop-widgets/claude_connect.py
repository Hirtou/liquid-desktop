"""Подключение виджета «Клод» к Claude Code: хуки в ~/.claude/settings.json (общий код — agent_connect.py).

Claude Code перед и после каждого своего действия запускает claude_hook.py — тот пишет в claude_status.json,
что сейчас делается (только состояние и имя файла/команды, без текста разговора). Виджет и остров читают этот файл.

Удаление программы зовёт `claude_connect.py --disconnect` — отключаются все помощники (Claude Code, Codex,
Antigravity), чтобы они не звали файл, которого больше нет.

Connects the Claude widget to Claude Code by adding hooks to ~/.claude/settings.json (other hooks are kept)."""
import sys

import agent_connect

SETTINGS = agent_connect.AGENTS["claude"]["settings"]


def connected():
    return agent_connect.connected("claude")


def connect():
    """Добавить хуки. -> путь к копии прежнего settings.json (или None, если его не было)."""
    return agent_connect.connect("claude")


def disconnect():
    agent_connect.disconnect("claude")


if __name__ == "__main__":
    if "--disconnect" in sys.argv:
        agent_connect.disconnect_all()
