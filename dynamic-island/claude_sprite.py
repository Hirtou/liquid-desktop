"""Пиксельные помощники для острова: Claude — тот же персонаж, что в виджете «Клод» (копия из виджетов, чтобы остров
жил сам по себе), и в том же стиле — Codex (терминальчик с курсором-ртом «_») и Antigravity (планетка с кольцом, парит).
sprite(state, f, who=...) -> [(колонка, строка, цвет)]; TEXT — подписи состояний; SPEED — мс на кадр.
Реквизит (лупа, листок, терминал, антенна, «!», искры, «Z», сердечки, пот) у всех общий."""
from lang import tr
from PySide6.QtGui import QColor

BODY, EYE = QColor("#D97757"), QColor("#16161a")
GRAY, GREEN, YELLOW, TERM = QColor("#9aa0aa"), QColor("#4ade80"), QColor("#ffd23f"), QColor("#1d2027")
PAPER, PAPER_EDGE = QColor("#f4f5f8"), QColor("#c3c8d2")
PX = 7  # размер «пикселя» персонажа
HEART, SWEAT = QColor("#ff5a7a"), QColor("#5ab8ff")
# Codex: светлый корпус-терминальчик, рот — зелёный курсор «_»
CODEX = QColor("#d5dbe5")
# Antigravity: планетка (сверху светлее), золотое кольцо, огонёк снизу — парит
AGY_TOP, AGY_LOW, AGY_RING, AGY_GLOW = QColor("#9fb6ff"), QColor("#7a6cf2"), QColor("#f2c85b"), QColor("#7fe3ff")
CONFETTI = [QColor(c) for c in ("#ffd23f", "#ff5a7a", "#4ade80", "#60a5fa", "#a78bfa", "#fb923c")]
# скорость анимации по состояниям, мс на кадр
SPEED = {"idle": 320, "think": 260, "read": 300, "edit": 130, "run": 150, "web": 240, "done": 110, "ask": 220,
         "sleep": 600, "bored": 420, "greet": 170, "love": 140, "oops": 110, "party": 110}
TEXT = {"idle": tr("Жду тебя"), "think": tr("Думаю…"), "done": tr("Готово!"), "ask": tr("Нужен твой ответ!"),
        "web": tr("Ищу в интернете"), "read": tr("Читаю…"), "edit": tr("Правлю…"), "run": tr("Запускаю…"),
        "sleep": tr("Сплю… разбуди задачей"), "bored": tr("Скучаю…"), "greet": tr("Привет! Берусь"),
        "love": tr("Мне приятно!"), "oops": tr("Ой, ошибка — разбираюсь"), "party": tr("Большая задача готова!")}
EMOTIONS = ["greet", "love", "party", "oops", "bored", "sleep"]  # для меню «Показать эмоцию»


def sprite(state, f, sweat=False, who="claude"):
    """Кадр f персонажа -> список (колонка, строка, цвет). Тело — колонки 2..9, строки 0..4.
    sweat — капля пота у головы (долго работает). who — claude / codex / antigravity."""
    cells = []
    dy = dx = 0
    if state in ("done", "party"):  # прыжок
        dy = (0, -1, -2, -3, -2, -1, 0, 0)[f % 8]
    elif state == "love":  # подпрыгивает от радости
        dy = (0, -1, -1, 0)[f % 4]
    elif state == "oops":  # трясётся
        dx = (0, 1, 0, -1)[f % 4]
    elif who == "antigravity" and state != "sleep":  # антигравитация: всё время мягко парит
        dy = (0, 0, -1, -1)[f // 2 % 4]

    def put(c, r, color=BODY):
        cells.append((c + dx, r + dy, color))

    if who == "codex":
        _codex(put, state, f)
    elif who == "antigravity":
        _antigravity(put, state, f)
    else:
        _claude(put, state, f)
    _props(put, state, f, dy, sweat)
    return cells


def _claude(put, state, f):
    for c in range(2, 10):
        for r in range(0, 5):
            put(c, r)
    _arms(put, state, f, BODY)
    # ножки; бегом — по очереди
    for i, c in enumerate((2, 4, 7, 9)):
        lift = state in ("run", "edit", "idle") and (i + f) % 2 == 0 and (state != "idle" or f % 12 in (5, 6))
        put(c, 5)
        if not lift:
            put(c, 6)
    _eyes(put, state, f, (3, 8))


def _codex(put, state, f):
    """Терминальчик: светлый корпус, обычные глаза, рот — зелёный курсор «_» терминала (мигает), две ножки."""
    for c in range(2, 10):
        for r in range(0, 5):
            put(c, r, CODEX)
    _arms(put, state, f, CODEX)
    for i, c in enumerate((3, 8)):
        lift = state in ("run", "edit") and (i + f) % 2 == 0
        put(c, 5, CODEX)
        if not lift:
            put(c, 6, CODEX)
    _eyes(put, state, f, (3, 8))
    if state not in ("sleep", "oops"):
        fast = state in ("think", "edit", "run", "web")
        if (f % 2 if fast else f % 6 < 4) or state in ("ask", "greet", "love", "party", "done"):
            put(5, 3, GREEN)
            put(6, 3, GREEN)


def _antigravity(put, state, f):
    """Планетка с кольцом: тело-шар (сверху светлее), кольцо поперёк, огонёк снизу вместо ножек."""
    for c in range(2, 10):
        for r in range(0, 5):
            if (c, r) in ((2, 0), (9, 0), (2, 4), (9, 4)):
                continue  # скруглённые углы
            put(c, r, AGY_TOP if r < 2 else AGY_LOW)
    for c in list(range(0, 12)):  # кольцо: по бокам и спереди
        put(c, 3, AGY_RING)
    if state != "sleep":  # огонёк снизу мерцает
        put(6, 5, AGY_GLOW)
        if f % 2:
            put(5, 5, AGY_GLOW)
            put(6, 6, AGY_GLOW)
    _eyes(put, state, f, (4, 7))


def _arms(put, state, f, color):
    """Руки (строки 2–3); печатает — по очереди вверх-вниз, машет правой, обе вверх на празднике."""
    left, right = [(0, 2), (1, 2), (0, 3), (1, 3)], [(10, 2), (11, 2), (10, 3), (11, 3)]
    if state == "edit":
        up = f % 2
        left = [(0, 2 - up), (1, 2 - up), (0, 3 - up), (1, 3 - up)]
        right = [(10, 1 + up), (11, 1 + up), (10, 2 + up), (11, 2 + up)]
    elif state in ("ask", "greet"):
        right = [(10, 2), (11, 1), (11, 0)] if f % 2 else [(10, 2), (11, 2), (11, 1)]
    elif state == "party":
        left, right = [(1, 1), (0, 0), (1, 2)], [(10, 1), (11, 0), (10, 2)]
    for c, r in left + right:
        put(c, r, color)


def _eyes(put, state, f, cols):
    """Глаза: моргает, смотрит вправо при чтении, вверх когда думает; у эмоций — свои."""
    a, b = cols
    if state == "sleep":
        for c in (a, a + 1, b - 1, b):
            put(c, 1, EYE)
    elif state in ("greet", "love", "party"):
        for c0 in (a, b):
            put(c0 - 1, 1, EYE)
            put(c0, 0, EYE)
            put(c0 + 1, 1, EYE)
    elif state == "oops":
        for c0 in (a, b):
            for c, r in ((c0 - 1, 0), (c0 + 1, 0), (c0, 1), (c0 - 1, 2), (c0 + 1, 2)):
                put(c, r, EYE)
    else:
        blink = state in ("idle", "think", "web", "bored") and f % 14 == 0
        ex = 1 if state in ("read", "run") else (-1, 0, 1, 0)[f // 3 % 4] if state == "bored" else 0
        ey = 0 if state == "think" and f % 4 < 2 else 1
        if not blink:
            put(a + ex, ey, EYE)
            put(b + ex, ey, EYE)


def _props(put, state, f, dy, sweat):
    """Что вокруг персонажа — у всех помощников одинаковое."""
    # что вокруг
    if state == "think":  # бегущие точки над головой
        for i in range(f % 4):
            put(10 + i * 2, -2 - i, GRAY)
    elif state == "read":  # лупа в руке
        for c, r in ((13, -1), (14, -1), (15, 0), (15, 1), (14, 2), (13, 2), (12, 1), (12, 0)):
            put(c, r + (f % 2), GRAY)
        put(12, 2 + (f % 2) + 1, GRAY)
    elif state == "run":  # мини-терминал: «>» и мигающий курсор «_»
        for c in range(13, 20):
            for r in range(-2, 4):
                put(c, r, TERM)
        for c, r in ((14, -1), (15, 0), (14, 1)):
            put(c, r, GREEN)
        if f % 2:
            put(17, 1, GREEN)
            put(18, 1, GREEN)
    elif state == "web":  # антенна с сигналом
        for c, r in ((8, -1), (8, -2), (9, -3), (10, -3)):
            put(c, r, GRAY)
        if f % 2:
            put(12, -4, GRAY)
            put(12, -2, GRAY)
    elif state == "edit":  # листок, на котором по очереди появляются строки кода
        for c in range(13, 19):
            for r in range(-2, 4):
                put(c, r, PAPER_EDGE if c in (13, 18) or r in (-2, 3) else PAPER)  # рамка — видно и на светлом
        for i in range(f % 5):
            for c in range(14, 14 + (4 if i % 2 == 0 else 3)):
                put(c, -1 + i, GRAY)
    elif state == "done":  # искры
        if f % 4 < 2:
            for c, r in ((0, -2), (11, -3), (13, 0)):
                put(c, r - dy, YELLOW)
    elif state == "ask":  # «!» над головой
        if f % 4 != 3:
            for r in (-7, -6, -5):
                put(5, r - dy, YELLOW)
            put(5, -3 - dy, YELLOW)
    elif state == "sleep":  # «Z» поднимается и появляется снова (одна — две в сцену не влезают)
        for i in range(1):
            t = f % 4
            x0, y0 = 12 + t // 2, 1 - t  # не выше края сцены
            z = [(c, 0) for c in range(5)] + [(3, 1), (2, 2), (1, 3)] + [(c, 4) for c in range(5)]  # «Z» 5×5
            for c, r in z:
                put(x0 + c, y0 + r - 2, GRAY)
    elif state == "bored":  # «…» загораются по одной
        for i in range((f // 2) % 4):
            put(11 + i * 2, -2, GRAY)
    elif state == "greet":  # искорка у машущей руки
        if f % 2:
            for c, r in ((13, -1), (12, -2), (14, -2), (13, -3)):
                put(c, r, YELLOW)
    elif state == "love":  # сердечки поднимаются
        for i in range(2):
            t = (f + i * 2) % 4
            x0, y0 = 11 + i * 4, -1 - t  # выше не поднимаются — иначе уходят за край сцены
            for c, r in ((0, 0), (2, 0), (0, 1), (1, 1), (2, 1), (1, 2)):
                put(x0 + c, y0 + r - dy, HEART)
    elif state == "oops":  # капля пота стекает
        t = f % 4
        put(11, -1 + t, SWEAT)
        put(11, t, SWEAT)
    elif state == "party":  # конфетти сыплется
        for i in range(12):
            c = (i * 7 + 3) % 22 - 5
            r = (f * 2 + i * 5) % 14 - 8
            put(c, r - dy, CONFETTI[i % len(CONFETTI)])
    if sweat and state not in ("oops", "sleep"):  # долго работает — капля у виска
        if f % 6 < 4:
            put(10, -1 + (f % 6) // 2, SWEAT)
