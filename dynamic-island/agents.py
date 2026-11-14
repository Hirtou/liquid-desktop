"""AI-помощники на острове: Claude Code, Codex, Antigravity — что делает тот, кто сейчас работает.

Состояние каждого пишет его хук в папку виджетов: claude_status.json (claude_hook.py), codex_status.json и
antigravity_status.json (agent_hook.py). Подключают хуки в окне настроек: раздел «Остров» -> «AI-помощники».
Остров показывает одного — самого важного: спрашивает > только что закончил (8 с) > ошибка > работает;
при равенстве — тот, кто менялся последним.

Значки свои: Claude — пиксельный персонаж (как в виджете «Клод»), Codex — окно терминала, Antigravity — орбита.

AI coding agents on the island: reads <agent>_status.json written by the hooks and picks the one to show."""
import json
import math
import os
import time

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainterPath, QPen

import claude_sprite as cl
from lang import tr

AGENTS = (("claude", "Claude"), ("codex", "Codex"), ("antigravity", "Antigravity"))
NAMES = dict(AGENTS)
WORK = ("think", "read", "edit", "run", "web", "greet")
# свой цвет у каждого (кромка значка, подпись «работает»); Codex — нейтральный: берётся цвет текста острова
COLOR = {"claude": QColor(cl.BODY), "codex": None, "antigravity": QColor("#7c9cff")}
ORBIT2 = QColor("#b58cff")
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
    """Мс на кадр анимации значка."""
    if agent == "claude":
        return cl.SPEED.get(state, 300)
    return 90 if state in WORK else 160 if state in ("ask", "oops") else 260


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


# ---------- значки ----------

def sprite(p, x0, y0, px, state, body_only=False):
    """Пиксельный Claude: левый верхний угол тела (x0, y0), px — размер «пикселя»."""
    f = int(time.monotonic() * 1000 / cl.SPEED.get(state, 300))
    p.setPen(Qt.NoPen)
    for c, r, col in cl.sprite(state, f):
        if body_only and not (0 <= c <= 11 and -1 <= r <= 6):
            continue
        p.setBrush(col)
        p.drawRect(QRectF(x0 + c * px, y0 + r * px, px + 0.3, px + 0.3))


def terminal(p, c, size, state, fg):
    """Codex — окошко терминала: «>» и мигающий курсор; работает — курсор бегает, спрашивает — «?»."""
    t = time.monotonic()
    w, h = size * 1.25, size
    box = QRectF(c.x() - w / 2, c.y() - h / 2, w, h)
    p.setPen(QPen(fg, max(1.2, size / 11)))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(box, size * 0.22, size * 0.22)
    lw = max(1.4, size / 8)
    p.setPen(QPen(color("codex", state, fg) if state in ("ask", "done", "oops") else fg, lw, Qt.SolidLine,
                  Qt.RoundCap, Qt.RoundJoin))
    k = size / 20
    x, y = box.left() + 5 * k, c.y()
    if state == "done":  # галочка
        path = QPainterPath(QPointF(x, y))
        path.lineTo(x + 3 * k, y + 3 * k)
        path.lineTo(x + 10 * k, y - 4 * k)
        p.drawPath(path)
        return
    path = QPainterPath(QPointF(x, y - 3.5 * k))  # «>»
    path.lineTo(x + 3.5 * k, y)
    path.lineTo(x, y + 3.5 * k)
    p.drawPath(path)
    if state == "ask":
        p.drawText(QRectF(x + 5 * k, y - 6 * k, 8 * k, 12 * k), Qt.AlignCenter, "?")
        return
    blink = (t * (5 if state in WORK else 1.6)) % 1 < 0.6
    if blink:
        run = (t * 2.2) % 1 * 3 * k if state in WORK else 0
        p.drawLine(QPointF(x + 6 * k + run, y + 3.5 * k), QPointF(x + 10.5 * k + run, y + 3.5 * k))


def orbit(p, c, size, state, fg):
    """Antigravity — планета с орбитой: по орбите бежит спутник (работает — быстро), в центре — цвет состояния."""
    t = time.monotonic()
    rx, ry = size * 0.62, size * 0.26
    tilt = -18
    lw = max(1.2, size / 12)
    p.save()
    p.translate(c)
    p.rotate(tilt)
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(COLOR["antigravity"], lw))
    p.drawEllipse(QPointF(0, 0), rx, ry)
    rate = 2.6 if state in WORK else 0.7
    a = t * rate * 2 * math.pi
    sat = QPointF(rx * math.cos(a), ry * math.sin(a))
    behind = math.sin(a) < 0  # спутник за планетой — рисуем до неё
    core = color("antigravity", state, fg) if state in ("ask", "done", "oops") else QColor(ORBIT2)
    if behind:
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(fg))
        p.drawEllipse(sat, lw * 1.25, lw * 1.25)
    p.setPen(Qt.NoPen)
    p.setBrush(core)
    p.drawEllipse(QPointF(0, 0), size * 0.24, size * 0.24)
    if not behind:
        p.setBrush(QColor(fg))
        p.drawEllipse(sat, lw * 1.25, lw * 1.25)
    p.restore()


def icon(p, agent, state, c, size, fg):
    """Значок помощника по центру c; size — высота (Claude рисуется пикселями под ту же высоту)."""
    if agent == "claude":
        px = size / 7
        sprite(p, c.x() - 6 * px, c.y() - 3.5 * px, px, state, body_only=True)
    elif agent == "codex":
        terminal(p, c, size * 0.82, state, fg)
    else:
        orbit(p, c, size, state, fg)
