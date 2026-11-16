"""Подключение виджета «Опен-код» к OpenCode: плагин-мост в ~/.config/opencode/plugins/liquid-desktop
(общий код — agent_connect.py).

OpenCode сам подхватывает папки из plugins/ — править его конфиг не нужно. Плагин (index.ts) пишет
opencode_status.json в папку виджетов — тот же формат, что у хука Claude Code; виджет и остров его читают.
Путь к статус-файлу вписывается в плагин при подключении (шаблон — opencode-plugin/index.ts).

Удаление программы зовёт `claude_connect.py --disconnect` — папка плагина удаляется, чтобы OpenCode
не держал файл, которого больше нет.

Connects the OpenCode widget to OpenCode by installing a plugin that writes opencode_status.json."""
import os

import agent_connect


def connected():
    return agent_connect.connected("opencode")


def connect():
    """Поставить плагин. -> None (файлы настроек OpenCode не трогаем, бэкап не нужен)."""
    return agent_connect.connect("opencode")


def disconnect():
    agent_connect.disconnect("opencode")
