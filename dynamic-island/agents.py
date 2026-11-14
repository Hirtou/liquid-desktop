"""AI-помощники на острове: Claude Code, Codex, Antigravity — что делает тот, кто сейчас работает.

Состояние каждого пишет его хук в папку виджетов: claude_status.json (claude_hook.py), codex_status.json и
antigravity_status.json (agent_hook.py). Подключают хуки в окне настроек: раздел «Остров» -> «AI-помощники».
Остров показывает одного — самого важного: спрашивает > только что закончил (8 с) > ошибка > работает;
при равенстве — тот, кто менялся последним.

Персонажи пиксельные, в одном стиле (claude_sprite.py): Claude — как в виджете «Клод», Codex — терминальчик
с курсором-ртом «_», Antigravity — парящая планетка с кольцом. Анимации и реквизит по состояниям у всех общие.

AI coding agents on the island: reads <agent>_status.json written by the hooks and picks the one to show."""
import json
import os
import time

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor

import claude_sprite as cl
from lang import tr

AGENTS = (("claude", "Claude"), ("codex", "Codex"), ("antigravity", "Antigravity"))
NAMES = dict(AGENTS)
WORK = ("think", "read", "edit", "run", "web", "greet")
# свой цвет у каждого (кромка значка, подпись «работает»); Codex — нейтральный: берётся цвет текста острова
COLOR = {"claude": QColor(cl.BODY), "codex": QColor(cl.CODEX), "antigravity": QColor(cl.AGY_TOP)}
YELLOW, GREEN, RED = QColor("#ffd60a"), QColor("#30d158"), QColor("#ff453a")
RANK = {"ask": 0, "done": 1, "oops": 2, "greet": 3, "think": 3, "read": 3, "edit": 3, "run": 3, "web": 3}


class Agents:
    """Читает файлы состояния (только когда файл поменялся) и выбирает, кого показать."""

    def __init__(self, folder):
        self.folder = folder
        self.cache = {}  # agent -> (mtime, данные)

    def status(self, agent):
        path = os.path.join(self.folder, f"{agent}_status.json")
        old = self.cache.get(agent, (None, {}))
        try:
            m = os.path.getmtime(path)
        except OSError:
            return {}
        if m != old[0]:
            try:
                with open(path, encoding="utf-8-sig") as f:
                    data = json.load(f)
                self.cache[agent] = (m, data if isinstance(data, dict) else {})
            except (OSError, ValueError):
                return old[1]  # как раз пишут — в следующий раз
        return self.cache[agent][1]

    @staticmethod
    def state(s, now):
        """Что показать по файлу состояния: ask / done / oops / greet / think / read / edit / run / web или None."""
        st = s.get("state", "idle")
        age = now - s.get("time", 0)
        if age > 10 * 60:  # давно ничего — сессия закрылась
            return None
        if st == "ask":
            return "ask"
        if st == "done":
            return "done" if age <= 8 else None
        if st == "oops":
            return "oops" if age < 4 else "think"
        if st in WORK:
            if st == "think" and s.get("started") and not s.get("finished") and now - s["started"] < 2.5:
                return "greet"
            return st
        return None

    def pick(self, now):
        """-> (agent, состояние, данные) самого важного сейчас или (None, None, {})."""
        best = None
        for agent, _ in AGENTS:
            s = self.status(agent)
            st = self.state(s, now) if s else None
            if st is None:
                continue
            key = (RANK.get(st, 3), -s.get("time", 0))
            if best is None or key < best[0]:
                best = (key, agent, st, s)
        return (best[1], best[2], best[3]) if best else (None, None, {})


def text(state):
    return cl.TEXT.get(state, "")


def color(agent, state, fg):
    """Цвет подписи: спрашивает — жёлтый, готово — зелёный, ошибка — красный, иначе — цвет помощника."""
    if state == "ask":
        return QColor(YELLOW)
    if state == "done":
        return QColor(GREEN)
    if state == "oops":
        return QColor(RED)
    return QColor(COLOR.get(agent) or fg)


def speed(agent, state):
    """Мс на кадр анимации персонажа."""
    return cl.SPEED.get(state, 300)


def open_app(agent):
    """Клик по острову — открыть помощника (если у него есть ссылка вида agent://)."""
    import winreg
    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, agent))
    except OSError:
        return False
    try:
        os.startfile(agent + "://")
        return True
    except OSError:
        return False


# ---------- персонажи ----------

def sprite(p, x0, y0, px, state, body_only=False, who="claude"):
    """Пиксельный помощник: левый верхний угол тела (x0, y0), px — размер «пикселя».
    body_only — без реквизита вокруг (для маленькой капсулы и капли)."""
    f = int(time.monotonic() * 1000 / cl.SPEED.get(state, 300))
    p.setPen(Qt.NoPen)
    for c, r, col in cl.sprite(state, f, who=who):
        if body_only and not (0 <= c <= 11 and -1 <= r <= 6):
            continue
        p.setBrush(col)
        p.drawRect(QRectF(x0 + c * px, y0 + r * px, px + 0.3, px + 0.3))


def icon(p, agent, state, c, size, fg=None):
    """Персонаж помощника по центру c; size — высота тела в пикселях экрана."""
    px = size / 7
    sprite(p, c.x() - 6 * px, c.y() - 3.5 * px, px, state, body_only=True, who=agent or "claude")
