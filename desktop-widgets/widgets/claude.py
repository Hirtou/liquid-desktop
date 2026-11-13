"""Клод: пиксельный зверёк, показывает, чем сейчас занят Claude Code.

Состояние пишет хук Claude Code (claude_hook.py) в claude_status.json; виджет смотрит файл 4 раза в секунду.
Состояния: idle (ждёт), think (думает), read (читает/ищет), edit (правит), run (команды), web (интернет),
done (закончил), ask (ждёт ответа). Анимация — по кадрам, рисуется квадратиками.
"""
from lang import tr
import json
import os
import time
from math import ceil, cos, exp, pi, sin

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QLinearGradient, QPainter, QPen, QPixmap, QTransform

import claude_connect
from core import DesktopWidget, ROOT, SHADOW, activity, grid, open_uri

STATUS = os.path.join(ROOT, "claude_status.json")
BODY, EYE = QColor("#D97757"), QColor("#16161a")
GRAY, GREEN, YELLOW, TERM = QColor("#9aa0aa"), QColor("#4ade80"), QColor("#ffd23f"), QColor("#1d2027")
PAPER, PAPER_EDGE = QColor("#f4f5f8"), QColor("#c3c8d2")
PX = 7  # размер «пикселя» персонажа
HEART, SWEAT = QColor("#ff5a7a"), QColor("#5ab8ff")
CONFETTI = [QColor(c) for c in ("#ffd23f", "#ff5a7a", "#4ade80", "#60a5fa", "#a78bfa", "#fb923c")]
# скорость анимации по состояниям, мс на кадр
SPEED = {"idle": 320, "think": 260, "read": 300, "edit": 130, "run": 150, "web": 240, "done": 110, "ask": 220,
         "sleep": 600, "bored": 420, "greet": 170, "love": 140, "oops": 110, "party": 110,
         "sad": 420, "angry": 120, "shock": 150, "tired": 520, "yawn": 380, "cool": 300, "coffee": 340, "dance": 190,
         "dizzy": 170, "wink": 300, "stretch": 360, "worried": 200, "curious": 340,
         "laugh": 140, "blush": 260, "zen": 420, "sneeze": 180, "starstruck": 160, "thumbs": 240}
TEXT = {"idle": tr("Жду тебя"), "think": tr("Думаю…"), "done": tr("Готово!"), "ask": tr("Нужен твой ответ!"),
        "web": tr("Ищу в интернете"), "read": tr("Читаю…"), "edit": tr("Правлю…"), "run": tr("Запускаю…"),
        "sleep": tr("Сплю… разбуди задачей"), "bored": tr("Скучаю…"), "greet": tr("Привет! Берусь"),
        "love": tr("Мне приятно!"), "oops": tr("Ой, ошибка — разбираюсь"), "party": tr("Большая задача готова!"),
        "sad": tr("Опять ошибка… не выходит"), "angry": tr("Да сколько можно!"), "shock": tr("Эй, щекотно!"),
        "tired": tr("Долго работаю, устал"), "yawn": tr("Ночь на дворе…"), "cool": tr("Сколько всего сделал!"),
        "coffee": tr("Утренний кофе"), "dance": tr("Классная музыка!"), "dizzy": tr("Голова кружится…"),
        "wink": tr("Подмигиваю"), "stretch": tr("Потягиваюсь"), "worried": tr("Что-то волнуюсь…"),
        "curious": tr("Что бы такое сделать?"), "laugh": tr("Ха-ха, смешно!"), "blush": tr("Ой, смущаюсь…"),
        "zen": tr("Медитирую"), "sneeze": tr("Апчхи!"), "starstruck": tr("Вот это задача!"),
        "thumbs": tr("Быстро справился!")}
# для меню «Показать эмоцию»
EMOTIONS = ["greet", "love", "blush", "party", "starstruck", "thumbs", "cool", "laugh", "dance", "coffee", "wink",
            "stretch", "curious", "zen", "sneeze", "shock", "oops", "sad", "angry", "worried", "dizzy", "tired", "yawn",
            "bored", "sleep"]
# развлекается, пока ждёт задачу
IDLE_PLAY = ("coffee", "dance", "wink", "stretch", "curious", "laugh", "zen", "sneeze")
WORK_STATES = ("think", "read", "edit", "run", "web")
BLUSH, STAR = QColor("#ff8fab"), QColor("#ffe066")
LATE, HAT, HAT_FUR = QColor("#3a3f4b"), QColor("#e5484d"), QColor("#f4f5f8")


def new_year():
    """Новогодний колпак: с 20 декабря по 10 января."""
    t = time.localtime()
    return (t.tm_mon == 12 and t.tm_mday >= 20) or (t.tm_mon == 1 and t.tm_mday <= 10)


def sprite(state, f, sweat=False, smooth=False):
    """Кадр f персонажа -> список (колонка, строка, цвет). Тело — колонки 2..9, строки 0..4.
    sweat — капля пота у головы (долго работает). smooth — прыжки и покачивания не клетками:
    их делает виджет плавно (motion), а тут персонаж стоит на месте."""
    cells = []
    dy = dx = 0
    if smooth:
        pass
    elif state in ("done", "party"):  # прыжок
        dy = (0, -1, -2, -3, -2, -1, 0, 0)[f % 8]
    elif state == "love":  # подпрыгивает от радости
        dy = (0, -1, -1, 0)[f % 4]
    elif state in ("oops", "angry", "worried"):  # трясётся
        dx = (0, 1, 0, -1)[f % 4]
    elif state == "dance":  # шаг в сторону и притоп
        dx, dy = (0, 1, 0, -1)[f % 4], (0, -1, 0, -1)[f % 4]
    elif state == "shock":  # подскочил
        dy = (0, -2, -1, 0, 0, 0)[f % 6]
    elif state == "dizzy":  # шатается
        dx = (0, 0, 1, 1, 0, 0, -1, -1)[f % 8]
    elif state == "stretch":  # тянется вверх
        dy = (0, -1, -1, -1, 0, 0)[f % 6]

    def put(c, r, color=BODY):
        cells.append((c + dx, r + dy, color))

    for c in range(2, 10):
        for r in range(0, 5):
            put(c, r)
    # руки (строки 2–3); у некоторых состояний двигаются
    left, right = [(0, 2), (1, 2), (0, 3), (1, 3)], [(10, 2), (11, 2), (10, 3), (11, 3)]
    if state == "edit":  # печатает: руки по очереди вверх-вниз
        up = f % 2
        left = [(0, 2 - up), (1, 2 - up), (0, 3 - up), (1, 3 - up)]
        right = [(10, 1 + up), (11, 1 + up), (10, 2 + up), (11, 2 + up)]
    elif state in ("ask", "greet"):  # машет правой рукой
        right = [(10, 2), (11, 1), (11, 0)] if f % 2 else [(10, 2), (11, 2), (11, 1)]
    elif state in ("party", "shock"):  # обе руки вверх
        left, right = [(1, 1), (0, 0), (1, 2)], [(10, 1), (11, 0), (10, 2)]
    elif state == "dance":  # руки вверх по очереди
        up, down = [(1, 2), (0, 1), (0, 0)], [(1, 2), (0, 2), (0, 3)]
        left = up if f % 4 < 2 else down
        right = [(11 - c, r) for c, r in (down if f % 4 < 2 else up)]  # зеркально левой
    elif state == "stretch":  # прямые руки над головой
        left, right = [(1, 1), (1, 0), (1, -1), (1, -2)], [(10, 1), (10, 0), (10, -1), (10, -2)]
    elif state in ("sad", "tired"):  # руки опущены
        left, right = [(1, 2), (1, 3), (0, 3), (0, 4)], [(10, 2), (10, 3), (11, 3), (11, 4)]
    elif state == "angry":  # кулаки машут
        up = f % 2
        left = [(1, 2), (0, 1 + up), (1, 1 + up)]
        right = [(10, 2), (11, 2 - up), (10, 2 - up)]
    elif state == "coffee":  # рука с кружкой то у рта, то ниже
        sip = f % 8 >= 5
        right = [(10, 2), (11, 2)] if sip else [(10, 3), (11, 3)]
    elif state == "laugh":  # держится за живот
        left, right = [(1, 3), (2, 4)], [(10, 3), (9, 4)]
    elif state == "blush":  # руки сложены перед собой, ковыряет ножкой
        left, right = [(1, 3), (2, 4), (3, 4)], [(10, 3), (9, 4), (8, 4)]
    elif state == "zen":  # руки в стороны ладонями вверх
        left, right = [(1, 3), (0, 3), (-1, 2)], [(10, 3), (11, 3), (12, 2)]
    elif state == "thumbs":  # правая рука — большой палец вверх
        right = [(10, 2), (11, 2), (12, 2), (12, 1), (12, 0)]
    elif state == "starstruck":  # руки у щёк
        left, right = [(1, 2), (1, 1)], [(10, 2), (10, 1)]
    elif state == "sneeze" and f % 8 >= 5:  # чихнул — руки вперёд
        right = [(10, 2), (11, 2), (12, 2)]
    for c, r in left + right:
        put(c, r)
    # ножки; бегом — по очереди
    legs = (2, 4, 7, 9)
    for i, c in enumerate(legs):
        if state == "zen":  # сидит, поджав ноги
            put(c, 5)
            continue
        lift = state in ("run", "edit", "idle") and (i + f) % 2 == 0 and (state != "idle" or f % 12 in (5, 6))
        if state == "blush" and c == 9 and f % 4 < 2:  # ковыряет ножкой
            lift = True
        put(c, 5)
        if not lift:
            put(c, 6)
    # глаза: моргает, смотрит вправо при чтении, вверх когда думает; у эмоций — свои глаза
    if state == "sleep":  # закрыты: чёрточки
        for c in (3, 4, 7, 8):
            put(c, 1, EYE)
    elif state in ("greet", "love", "party", "dance"):  # радостные дуги «^ ^»
        for c0 in (3, 8):
            put(c0 - 1, 1, EYE)
            put(c0, 0, EYE)
            put(c0 + 1, 1, EYE)
    elif state == "oops":  # крестики
        for c0 in (3, 8):
            for c, r in ((c0 - 1, 0), (c0 + 1, 0), (c0, 1), (c0 - 1, 2), (c0 + 1, 2)):
                put(c, r, EYE)
    elif state == "sad":  # глаза внизу, брови домиком, рот скобкой вниз
        for c, r in ((3, 2), (8, 2), (4, 1), (7, 1), (5, 3), (6, 3), (4, 4), (7, 4)):
            put(c, r, EYE)
    elif state == "angry":  # сдвинутые брови, сжатый рот
        for c, r in ((3, 0), (4, 1), (8, 0), (7, 1), (3, 2), (8, 2), (4, 4), (5, 4), (6, 4), (7, 4)):
            put(c, r, EYE)
    elif state == "shock":  # большие глаза и открытый рот
        for c0 in (3, 7):
            for c, r in ((c0, 0), (c0 + 1, 0), (c0, 1), (c0 + 1, 1)):
                put(c, r, EYE)
        for c, r in ((5, 3), (6, 3), (5, 4), (6, 4)):
            put(c, r, EYE)
    elif state in ("tired", "yawn", "stretch"):  # закрытые или прикрытые глаза
        for c in (3, 4, 7, 8):
            put(c, 1, EYE)
        if state == "tired":  # круги под глазами
            for c in (3, 4, 7, 8):
                put(c, 2, LATE)
        elif state == "yawn" and f % 6 in (2, 3, 4) or state == "stretch" and f % 6 in (1, 2, 3):  # зевок
            for c, r in ((5, 3), (6, 3), (5, 4), (6, 4)):
                put(c, r, EYE)
    elif state == "cool":  # тёмные очки с бликом и улыбка
        for c in range(2, 10):
            put(c, 1, EYE)
        for c in (3, 4, 7, 8):
            put(c, 2, EYE)
        if f % 8 < 2:
            put(3, 1, PAPER)
            put(7, 1, PAPER)
        for c in (4, 5, 6, 7):  # улыбка отдельно от очков, через строку
            put(c, 4, EYE)
    elif state == "dizzy":  # глаза-кружки
        for c0 in (3, 8):
            for c, r in ((c0 - 1, 0), (c0, 0), (c0 + 1, 0), (c0 - 1, 1), (c0 + 1, 1), (c0 - 1, 2), (c0, 2), (c0 + 1, 2)):
                put(c, r, EYE)
    elif state == "wink":  # левый глаз открыт, правый подмигивает
        put(3, 1, EYE)
        if f % 6 < 3:
            for c, r in ((7, 1), (8, 0), (9, 1)):
                put(c, r, EYE)
        else:
            put(8, 1, EYE)
        for c, r in ((5, 3), (6, 3)):
            put(c, r, EYE)
    elif state == "worried":  # брови домиком, рот волной
        for c, r in ((3, 1), (8, 1), (4, 0), (7, 0), (4, 3), (5, 4), (6, 3), (7, 4)):
            put(c, r, EYE)
    elif state == "coffee":  # пьёт — глаза закрыты от удовольствия
        if f % 8 >= 5:
            for c in (3, 4, 7, 8):
                put(c, 1, EYE)
        else:
            put(3, 1, EYE)
            put(8, 1, EYE)
    elif state == "curious":  # смотрит по сторонам
        ex = (-1, 0, 1, 0)[f // 2 % 4]
        put(4 + ex, 1, EYE)  # глаза ближе к центру: не упираются в край головы
        put(7 + ex, 1, EYE)
    elif state in ("laugh", "thumbs"):  # довольные «^ ^»; у смеха рот открыт и прыгает
        for c0 in (3, 8):
            put(c0 - 1, 1, EYE)
            put(c0, 0, EYE)
            put(c0 + 1, 1, EYE)
        if state == "laugh":
            mouth = ((5, 3), (6, 3), (5, 4), (6, 4)) if f % 2 else ((4, 3), (5, 3), (6, 3), (7, 3), (5, 4), (6, 4))
        else:
            mouth = ((4, 3), (5, 4), (6, 4), (7, 3))
        for c, r in mouth:
            put(c, r, EYE)
    elif state == "blush":  # глазки вниз, румянец
        put(3, 2, EYE)
        put(8, 2, EYE)
        for c in (2, 9):
            put(c, 3, BLUSH)
        put(5, 4, EYE)
        put(6, 4, EYE)
    elif state == "zen":  # закрытые глаза-дуги вниз, спокойная улыбка
        for c0 in (3, 8):
            put(c0 - 1, 1, EYE)
            put(c0, 2, EYE)
            put(c0 + 1, 1, EYE)
        for c in (5, 6):
            put(c, 4, EYE)
    elif state == "sneeze":  # щурится, набирает воздух — и «апчхи»
        k = f % 8
        if k < 5:
            for c in (3, 4, 7, 8):
                put(c, 1, EYE)
            if k >= 3:  # рот приоткрыт
                put(5, 3, EYE)
                put(6, 3, EYE)
        else:  # зажмурился «> <»
            for c, r in ((2, 0), (3, 1), (2, 2), (9, 0), (8, 1), (9, 2)):
                put(c, r, EYE)
            for c, r in ((5, 3), (6, 3), (5, 4), (6, 4)):
                put(c, r, EYE)
    elif state == "starstruck":  # глаза-звёзды мерцают
        for c0 in (3, 8):
            big = (f + (c0 == 8)) % 2 == 0
            star = ((c0, 0), (c0 - 1, 1), (c0, 1), (c0 + 1, 1), (c0, 2)) if big else ((c0, 1),)
            for c, r in star:
                put(c, r, STAR)
        for c, r in ((4, 3), (5, 4), (6, 4), (7, 3)):
            put(c, r, EYE)
    else:
        blink = state in ("idle", "think", "web", "bored") and f % 14 == 13  # не с первого кадра: иначе «без глаз»
        ex = 1 if state in ("read", "run") else (-1, 0, 1, 0)[f // 3 % 4] if state == "bored" else 0
        ey = 0 if state == "think" and f % 4 < 2 else 1
        if not blink:
            put(3 + ex, ey, EYE)
            put(8 + ex, ey, EYE)
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
    elif state == "sad":  # слеза катится
        t = f % 3
        put(2, 3 + t, SWEAT)
    elif state == "angry":  # пар из ушей
        for side, c in ((-1, 0), (1, 11)):
            t = f % 3
            put(c + side * t, -1 - t, GRAY)
            put(c + side * t, -2 - t, GRAY)
    elif state == "shock":  # «!» сбоку
        for r in (-4, -3, -2):
            put(12, r - dy, YELLOW)
        put(12, 0 - dy, YELLOW)
    elif state in ("tired", "yawn"):  # маленькая «z» плывёт вверх
        t = f % 4
        for c, r in ((0, 0), (1, 0), (2, 0), (1, 1), (0, 2), (1, 2), (2, 2)):
            put(12 + c, r - t - 1, GRAY)
    elif state == "coffee":  # кружка с паром
        low = 0 if f % 8 >= 5 else 1
        for c in range(12, 15):
            for r in range(1, 4):
                put(c, r + low, PAPER)
        put(15, 2 + low, PAPER)
        put(13, 2 + low, BODY)
        for i in range(2):
            if (f + i) % 2:
                put(12 + i * 2, 0 + low - i, GRAY)
                put(12 + i * 2, -1 + low - i, GRAY)
    elif state == "dance":  # ноты летят
        for i, color in ((0, YELLOW), (1, HEART)):
            t = (f + i * 2) % 4
            x0, y0 = (13, -1 - t) if i == 0 else (-2, -t)
            for c, r in ((1, 0), (1, 1), (1, 2), (0, 2), (2, 0)):
                put(x0 + c - dx, y0 + r - dy, color)
    elif state == "dizzy":  # звёздочки вокруг головы
        ring = ((1, -2), (4, -3), (7, -3), (10, -2), (7, -1), (4, -1))
        for i in (0, 2, 4):
            c, r = ring[(f + i) % 6]
            put(c - dx, r, YELLOW)
    elif state == "wink":  # искорка у подмигивающего глаза
        if f % 6 < 3:
            for c, r in ((12, -1), (11, -2), (13, -2), (12, -3)):
                put(c, r, YELLOW)
    elif state == "worried":  # капли пота с обеих сторон
        t = f % 4
        put(1, -1 + t, SWEAT)
        put(11, t, SWEAT)
    elif state == "curious":  # «?» над головой
        if f % 6 != 5:
            for c, r in ((0, 0), (1, 0), (2, 0), (2, 1), (1, 2), (1, 4)):
                put(11 + c, -5 + r, YELLOW)
    elif state == "stretch":  # искорки от потягивания
        if f % 6 in (1, 2):
            put(0, -3, YELLOW)
            put(12, -3, YELLOW)
    elif state == "laugh":  # капельки смеха разлетаются в стороны
        for i, (x0, y0, side) in enumerate(((12, -1, 1), (-1, -1, -1))):
            t = (f + i * 2) % 4
            put(x0 + side * t, y0 - t, YELLOW)
            put(x0 + side * (t + 1), y0 - t + 1, YELLOW)
    elif state == "blush":  # маленькое сердечко над головой то появляется, то нет
        if f % 4 < 2:
            for c, r in ((0, 0), (2, 0), (0, 1), (1, 1), (2, 1), (1, 2)):
                put(11 + c, -3 + r, HEART)
    elif state == "zen":  # искорки кружат вокруг
        ring = ((-1, 0), (1, -3), (6, -4), (10, -3), (12, 0), (6, -2))
        for i in (0, 2, 4):
            c, r = ring[(f + i) % 6]
            put(c, r, STAR if i else CONFETTI[4])
    elif state == "sneeze":  # брызги и «!»
        k = f % 8
        if k >= 5:
            for i, (c, r) in enumerate(((12, 2), (14, 1), (13, 4), (16, 3), (15, 0))):
                if i < (k - 4) * 2:
                    put(c, r, SWEAT)
            for r in (-4, -3, -2):
                put(12, r, YELLOW)
            put(12, 0, YELLOW)
    elif state == "starstruck":  # звёздочки вспыхивают вокруг
        for i, (c, r) in enumerate(((-2, -2), (12, -3), (14, 2), (-3, 3), (6, -4))):
            if (f + i) % 3 == 0:
                for dc, dr in ((0, -1), (-1, 0), (0, 0), (1, 0), (0, 1)):
                    put(c + dc, r + dr, STAR)
            elif (f + i) % 3 == 1:
                put(c, r, STAR)
    elif state == "thumbs":  # блик у пальца
        if f % 4 < 2:
            for c, r in ((14, -1), (13, -2), (15, -2), (14, -3)):
                put(c, r, YELLOW)
    if new_year():  # колпак
        for c in range(2, 10):
            put(c, -1, HAT_FUR)
        for r, (a, b) in enumerate(((3, 9), (4, 8), (5, 7))):
            for c in range(a, b):
                put(c, -2 - r, HAT)
        put(6, -5, HAT_FUR)
    if sweat and state not in ("oops", "sleep"):  # долго работает — капля у виска
        if f % 6 < 4:
            put(10, -1 + (f % 6) // 2, SWEAT)
    return cells


class ClaudeWidget(DesktopWidget):
    key = "claude"
    title = tr("Клод")
    description = tr("Пиксельный Claude: что он сейчас делает")

    def __init__(self, **kw):
        super().__init__(**kw)
        self.setFixedSize(*(v + 2 * SHADOW for v in grid(2, 1)))
        self.status = {"state": "idle", "detail": "", "time": 0, "counts": {}}
        self.mtime = 0
        self.frame = 0
        self.force = None  # для превью/скринов и меню «Показать эмоцию»: показать нужное состояние
        self.force_until = float("inf")
        self.poked = 0.0   # когда погладили (клик по персонажу)
        self.pokes = []    # времена последних поглаживаний: слишком часто — пугается и кружится голова
        self.tile = None   # где сцена с персонажем — для клика
        self._mood_at = 0.0
        self._music = False
        self._card_key, self._card_pix, self._pill = None, None, None  # неподвижная часть карточки (см. paintEvent)
        self._sprites = {}  # кадры персонажа картинками
        self.watch =QTimer(self, interval=250, timeout=self.read_status)
        self.watch.start()
        self.anim = QTimer(self, interval=SPEED["idle"], timeout=self.next_frame)
        self.anim.start()
        # плавное движение поверх пиксельных кадров: прыжки по дуге, дыхание, покачивания (см. motion)
        self.shown, self.shown_at = None, 0.0   # какое состояние на экране и с какого момента (для «появления»)
        self.smooth = QTimer(self, interval=33, timeout=self.smooth_tick)
        self.smooth.start()
        self.read_status()

    def read_status(self):
        try:
            m = os.path.getmtime(STATUS)
        except OSError:
            return
        if m != self.mtime:
            self.mtime = m
            try:
                with open(STATUS, encoding="utf-8-sig") as f:
                    self.status = clean_status(json.load(f))
            except (OSError, ValueError):
                return
            self.update()

    def state(self):
        """Что показывать: состояние от хука + эмоции поверх него.
        Погладили (клик) — «рад», часто — «испугался», совсем часто — «кружится голова»;
        ошибка — «ой», 3 подряд — «расстроен», 5 подряд — «злится»; только дали задачу — «привет»;
        большая задача готова — «ура», много правок — «крутой»; работает 30+ минут — «устал», глубокой ночью — «зевает»,
        ждёт — развлекается (см. idle_play), потом «скучает» и «спит»."""
        now = time.time()
        if self.force and now < self.force_until:
            return self.force
        if self.poked and now - self.poked < 2.4:
            n = sum(1 for t in self.pokes if now - t < 6)
            return "dizzy" if n >= 6 else "shock" if n >= 4 else "blush" if n >= 2 else "love"
        s = self.status
        if not s.get("time"):  # хук ещё ни разу не писал (не подключён или первый запуск) — просто ждёт
            return self.idle_play(now, time.localtime(now).tm_hour) or "idle"
        st = s.get("state", "idle")
        age = now - s.get("time", 0)
        fails = s.get("fails", 0)
        if fails >= 3 and now - s.get("failed_at", 0) < 6:
            return "angry" if fails >= 5 else "sad"
        if st == "oops":
            return "oops" if age < 4 else "think"
        if st == "think" and s.get("started") and not s.get("finished") and now - s["started"] < 2.5:
            return "greet"
        if st == "done" and age <= 6:
            took = s["finished"] - s["started"] if s.get("started") and s.get("finished") else None
            edits = s.get("task_edits", 0)
            if took is not None and took >= 180:
                return "party"
            if edits >= 30:
                return "starstruck"
            if edits >= 15:
                return "cool"
            return "thumbs" if took is not None and took < 45 else "done"
        if st == "ask":
            return st
        hour = time.localtime(now).tm_hour
        # долгая команда (сборка, тесты) — хук молчит, пока она идёт: это не «сессия закрылась»
        running = st == "run" and s.get("started") and not s.get("finished") and age < 30 * 60
        if st == "done" or st == "idle" or (age > 10 * 60 and not running):  # ждёт (или сессия закрылась)
            night = hour >= 23 or hour < 7  # ночью (23:00–7:00) засыпает сразу, без «скучаю»
            if age >= 5 * 60 or night:
                return "sleep"
            return self.idle_play(now, hour) or ("bored" if age >= 90 else "idle")
        # работает: усталость и тревога — короткими вспышками, основное — что делает сейчас
        if s.get("started") and not s.get("finished") and now - s["started"] > 30 * 60 and now % 47 < 7:
            return "tired"
        if 1 <= hour < 6 and now % 61 < 5:
            return "yawn"
        return st

    def idle_play(self, now, hour):
        """Чем занят, пока ждёт: играет музыка — танцует; иначе каждые 25 с ненадолго что-то своё (утром — кофе)."""
        self.read_mood(now)
        slot, inside = divmod(now, 25)
        if self._music and inside < 15:
            return "dance"
        if inside >= 7:
            return None
        if 7 <= hour < 11:
            plays = ("coffee", "wink", "stretch", "laugh", "curious", "sneeze")
        elif 20 <= hour < 23:  # вечером спокойнее
            plays = ("zen", "wink", "stretch", "curious", "zen", "laugh")
        else:
            plays = ("wink", "stretch", "curious", "laugh", "sneeze", "zen")
        return plays[int(slot) % len(plays)]

    def read_mood(self, now):
        """Раз в 10 с: играет ли музыка (виджет «Плеер») — тогда, пока ждёт, танцует."""
        if now - self._mood_at < 10:
            return
        self._mood_at = now
        self._music = any(getattr(w, "key", "") == "player" and isinstance(getattr(w, "state", None), dict)
                          and w.state.get("playing") for w in activity.widgets())

    def sweating(self, state):
        """Работает дольше 10 минут без перерыва — выступает пот."""
        s = self.status
        return state in ("think", "read", "edit", "run", "web") and bool(s.get("started")) \
            and not s.get("finished") and time.time() - s["started"] > 10 * 60

    def click(self, pos):
        """Клик по сцене с персонажем — погладить: подпрыгивает и сердечки."""
        if self.tile is not None and self.tile.contains(pos):
            self.poked = time.time()
            self.pokes = [t for t in self.pokes if self.poked - t < 6] + [self.poked]
            self.frame = 0
            self.update()
            return True
        return False

    def add_actions(self, menu):
        if claude_connect.connected():
            menu.addAction(tr("Отключить от Claude Code"), self.disconnect)
        else:
            menu.addAction(tr("Подключить к Claude Code"), self.connect)
        sub = menu.addMenu(tr("Показать эмоцию"))
        for name in sorted(EMOTIONS, key=lambda n: STATE_LOOK[n][1]):
            sub.addAction(STATE_LOOK[name][1].capitalize(), lambda n=name: self.show_emotion(n))

    def connect(self):
        """Прописать хуки в настройки Claude Code (~/.claude/settings.json, копия рядом) — по кнопке, не сами."""
        from PySide6.QtWidgets import QMessageBox
        try:
            backup = claude_connect.connect()
        except (OSError, ValueError) as ex:
            QMessageBox.warning(None, tr("Клод"), tr("Не получилось подключить: {}").format(ex))
            return
        text = tr("Готово. Клод будет показывать, чем занят Claude Code, — начиная со следующей задачи.")
        if backup:
            text += "\n\n" + tr("Прежние настройки Claude Code сохранены в {}").format(backup)
        QMessageBox.information(None, tr("Клод"), text)
        self._card_key = None
        self.update()

    def disconnect(self):
        try:
            claude_connect.disconnect()
        except (OSError, ValueError) as ex:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(None, tr("Клод"), tr("Не получилось отключить: {}").format(ex))
        self._card_key = None
        self.update()

    def forced(self):
        return bool(self.force) and time.time() < self.force_until

    def show_emotion(self, name, seconds=5):
        self.force, self.force_until = name, time.time() + seconds
        self.update()

    def track(self, state):
        """Сменилось состояние — анимация с первого кадра и «появление» (лёгкий пружинистый отскок)."""
        if state != self.shown:
            self.shown, self.shown_at, self.frame = state, time.monotonic(), 0

    def smooth_tick(self):
        """Плавная часть движения: перерисовать только сцену с персонажем.
        Большие движения — 30 кадров в секунду, дыхание — 15; закрыт окном или игрой — ничего."""
        if not self.isVisible() or self.tile is None or activity.covered(self):
            return
        state = self.state()
        now = time.monotonic()
        want = 33 if state in BIG_MOTION or now - self.shown_at < 0.6 else 66
        if self.smooth.interval() != want:
            self.smooth.setInterval(want)
        # картинка сдвинулась меньше чем на полпикселя (дыхание медленное) — не перерисовывать:
        # перерисовка прозрачного окна стоит дорого, а глазу разницы нет
        dx, lift, sx, sy, angle = motion(state, now, now - self.shown_at)
        k = self.scale()
        q = 2 * PX * k
        key = (state, self.frame, round(dx * q), round(lift * q), round((sx - 1) * 12 * q), round((sy - 1) * 7 * q),
               round(angle * 2))
        if key == getattr(self, "_motion_key", None):
            return
        self._motion_key = key
        t = self.tile.adjusted(-2, -2, 2, 2)
        self.update(QRectF(t.topLeft() * k, t.bottomRight() * k).toAlignedRect())

    def next_frame(self):
        self.frame += 1
        state = self.state()
        self.track(state)
        interval = SPEED.get(state, 300)
        if self.anim.interval() != interval:
            self.anim.setInterval(interval)
        if activity.covered(self):  # закрыт окном или игрой — кадр не нужен (откроют — нарисуется сам)
            return
        second = int(time.time())
        if self.tile is not None and state == getattr(self, "_shown_state", None) \
                and second == getattr(self, "_shown_second", None):
            # кадр анимации: меняются только сцена с персонажем и мигающая точка в плашке — их и перерисуем
            k = self.scale()
            r = QRectF(self.card())
            self.update(QRectF(self.tile.adjusted(-2, -2, 2, 2).topLeft() * k,
                               self.tile.adjusted(-2, -2, 2, 2).bottomRight() * k).toAlignedRect())
            self.update(QRectF(QPointF(self.tile.right(), r.top()) * k, QPointF(r.right(), r.top() + 40) * k)
                        .toAlignedRect())
        else:  # сменилось состояние или секунда (таймер «работаю 9:21») — весь виджет
            self._shown_state, self._shown_second = state, second
            self.update()

    def push_interval(self):
        return SPEED.get(self.state(), 300)

    def double_click(self):
        open_uri("claude://")  # приложение Claude

    # ---------- рисование ----------

    def paintEvent(self, event):
        super().paintEvent(event)  # стекло
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        r = QRectF(self.card())
        dark = bool(self.dark)
        state = self.state()
        color, chip = STATE_LOOK[state]
        tile = QRectF(r.left() + 14, r.top() + 14, r.height() - 28, r.height() - 28)
        self.tile = tile

        # кадр анимации меняет только персонажа, его тень и точку в плашке. Всё остальное (плитка, текст, счётчики) —
        # одной картинкой, она пересобирается раз в секунду или при смене состояния
        k, dpr = self.scale(), self.devicePixelRatioF()
        key = (self.card().size().toTuple(), dark, k, dpr, state, int(time.time()), self.mtime, self.forced())
        if key != self._card_key:
            self._card_key = key
            pix = QPixmap(ceil(r.width() * k * dpr), ceil(r.height() * k * dpr))
            pix.setDevicePixelRatio(dpr)
            pix.fill(Qt.transparent)
            cp = QPainter(pix)
            cp.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
            cp.scale(k, k)
            cp.translate(-r.topLeft())
            self._card(cp, r, tile, state, color, chip, dark)
            cp.end()
            self._card_pix = pix
        self._blit(p, r.topLeft(), self._card_pix, k)

        # тело (колонки 0..11, строки 0..6) — чуть левее центра: справа место для лупы/терминала/листка
        self.track(state)
        ox = tile.center().x() - 8 * PX - PX * (1 if state in ("run", "edit") else 0)
        oy = tile.center().y() - 3 * PX
        now = time.monotonic()
        dx, lift, sx, sy, angle = motion(state, now, now - self.shown_at)
        # тень: чем выше прыгнул, тем она меньше и прозрачнее
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, int((60 if dark else 35) * max(0.35, 1 - lift * 0.18))))
        sw = PX * max(5.0, (10 - lift * 1.2) * sx)
        p.drawEllipse(QRectF(ox + PX * 6 + dx * PX - sw / 2, oy + 7.1 * PX, sw, PX * max(0.6, 1.1 - lift * 0.1)))
        p.save()
        p.setClipRect(tile.adjusted(6, 6, -6, -6))  # всё, что держит в руках, — внутри сцены
        pix, c0, r0 = self._sprite_pix(state, k, dpr)
        # опора — середина ног: от неё растягиваемся, сплющиваемся и наклоняемся
        foot = QPointF(ox + PX * 6 + dx * PX, oy + 7 * PX - lift * PX)
        tr_ = QTransform()
        tr_.translate(foot.x(), foot.y())
        tr_.rotate(angle)
        tr_.scale(sx, sy)
        tr_.translate(-foot.x(), -foot.y())
        p.setTransform(tr_, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, abs(sx - 1) + abs(sy - 1) + abs(angle) > 0.002)
        p.drawPixmap(QRectF(ox + c0 * PX + dx * PX, oy + r0 * PX - lift * PX, pix.width() / dpr / k,
                            pix.height() / dpr / k), pix, QRectF(pix.rect()))
        p.restore()

        # «живая» точка в плашке мигает, пока работает
        dot = QColor(color)
        if state not in ("idle", "done") and self.frame % 2:
            dot.setAlpha(110)
        p.setPen(Qt.NoPen)
        p.setBrush(dot)
        p.drawEllipse(QRectF(self._pill.left() + 8, self._pill.center().y() - 3.5, 7, 7))

    @staticmethod
    def _blit(p, pos, pix, k):
        """Положить готовую картинку пиксель в пиксель: она уже нарисована с масштабом виджета."""
        p.save()
        if k != 1:
            p.scale(1 / k, 1 / k)
        p.drawPixmap(QPointF(round(pos.x() * k), round(pos.y() * k)), pix)
        p.restore()

    def _sprite_pix(self, state, k, dpr):
        """Кадр персонажа картинкой -> (картинка, первая колонка, первая строка). Кадры повторяются, а прямоугольников
        в кадре около сотни — храним последние; ключ — сами клетки: один кадр бывает у разных состояний."""
        cells = sprite(state, self.frame, self.sweating(state), smooth=True)
        key = (tuple((c, row, col.rgba()) for c, row, col in cells), k, dpr)
        found = self._sprites.get(key)
        if found is None:
            c0, c1 = min(c[0] for c in cells), max(c[0] for c in cells)
            r0, r1 = min(c[1] for c in cells), max(c[1] for c in cells)
            pix = QPixmap(ceil((c1 - c0 + 1) * PX * k * dpr), ceil((r1 - r0 + 1) * PX * k * dpr))
            pix.setDevicePixelRatio(dpr)
            pix.fill(Qt.transparent)
            cp = QPainter(pix)
            cp.scale(k, k)
            cp.setPen(Qt.NoPen)
            for c, row, col in cells:
                cp.setBrush(col)
                cp.drawRect(QRectF((c - c0) * PX, (row - r0) * PX, PX, PX))
            cp.end()
            if len(self._sprites) >= 48:  # у самых длинных анимаций кадров меньше, но на всякий случай — без роста
                self._sprites.pop(next(iter(self._sprites)))
            found = self._sprites[key] = (pix, c0, r0)
        return found

    def _card(self, p, r, tile, state, color, chip, dark):
        """Неподвижная часть карточки: сцена без персонажа и всё, что справа от неё."""
        fg = QColor("#ededf0") if dark else QColor("#151517")
        dim = QColor(fg)
        dim.setAlpha(140)
        faint = QColor(fg)
        faint.setAlpha(28)

        # ---- сцена слева: тёплая плитка ----
        grad = QLinearGradient(tile.topLeft(), tile.bottomLeft())
        top, bottom = ("#3b2a24", "#271c19") if dark else ("#fbefe6", "#f1dccd")
        grad.setColorAt(0, QColor(top))
        grad.setColorAt(1, QColor(bottom))
        p.setPen(QPen(QColor(255, 255, 255, 30 if dark else 160), 1))
        p.setBrush(grad)
        p.drawRoundedRect(tile, 22, 22)

        # ---- справа: имя, плашка состояния, действие, таймер ----
        x = tile.right() + 16
        w = r.right() - 16 - x
        name = QFont("Segoe UI Semibold")
        name.setPixelSize(16)
        p.setFont(name)
        p.setPen(fg)
        p.drawText(QRectF(x, r.top() + 14, w, 22), Qt.AlignLeft | Qt.AlignVCenter, "Claude")
        small = QFont("Segoe UI Semibold")
        small.setPixelSize(11)
        fm = QFontMetricsF(small)
        cw = fm.horizontalAdvance(chip) + 24
        pill = self._pill = QRectF(r.right() - 16 - cw, r.top() + 15, cw, 20)
        bg = QColor(color)
        bg.setAlpha(55 if dark else 70)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(pill, 10, 10)
        p.setFont(small)
        p.setPen(QColor(color).lighter(140) if dark else QColor(color).darker(210))
        p.drawText(pill.adjusted(19, 0, -6, 0), Qt.AlignVCenter | Qt.AlignLeft, chip)

        detail = self.status.get("detail") if state == self.status.get("state") else ""
        action = QFont("Segoe UI Semibold")
        action.setPixelSize(14)
        p.setFont(action)
        p.setPen(fg)
        if not self.forced() and not claude_connect.connected():  # ещё не подключён — подсказать как
            detail = tr("Не подключён")
        p.drawText(QRectF(x, r.top() + 42, w, 20), Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetricsF(action).elidedText(detail or TEXT.get(state, ""), Qt.ElideRight, w))
        tiny = QFont("Segoe UI")
        tiny.setPixelSize(11)
        p.setFont(tiny)
        p.setPen(dim)
        hint = not self.forced() and not claude_connect.connected()
        p.drawText(QRectF(x, r.top() + 62, w, 16), Qt.AlignLeft | Qt.AlignVCenter,
                   tr("правый клик → «Подключить»") if hint else self.timing(state))

        # ---- последние действия ----
        p.setPen(QPen(faint, 1))
        p.drawLine(QPointF(x, r.top() + 84), QPointF(r.right() - 16, r.top() + 84))
        now = time.time()
        lines = 3 if r.height() > 190 else 2  # в ячейке 2×1 — две последние строки, иначе налезут на счётчики
        hist = (self.status.get("history", []) if not self.forced() else SAMPLE_HISTORY)[:lines]
        for i, h in enumerate(hist):
            y = r.top() + 90 + i * 17
            p.setPen(Qt.NoPen)
            p.setBrush(STATE_LOOK.get(h["s"], STATE_LOOK["think"])[0])
            p.drawEllipse(QRectF(x, y + 5, 6, 6))
            p.setPen(dim)
            ago = ago_text(now - h["t"])
            aw = QFontMetricsF(tiny).horizontalAdvance(ago)
            p.drawText(QRectF(x + 12, y, w - 18 - aw, 16), Qt.AlignLeft | Qt.AlignVCenter,
                       QFontMetricsF(tiny).elidedText(h["d"], Qt.ElideRight, w - 18 - aw))
            p.drawText(QRectF(x, y, w, 16), Qt.AlignRight | Qt.AlignVCenter, ago)
        if not hist:
            p.setPen(dim)
            p.drawText(QRectF(x, r.top() + 90, w, 16), Qt.AlignLeft | Qt.AlignVCenter, tr("пока без дел"))

        # ---- счётчики за сегодня: крупная цифра + подпись ----
        # показ эмоции (меню, превью в каталоге, картинки) — пример, как у истории действий; иначе — настоящие за сегодня
        c = {"edit": 24, "run": 17, "read": 41} if self.forced() else self.status.get("counts", {})
        num = QFont("Bahnschrift SemiBold")
        num.setPixelSize(18)
        col_w = w / 3
        for i, (k, label) in enumerate((("edit", tr("правок")), ("run", tr("команд")), ("read", tr("чтений")))):
            cx = x + i * col_w
            p.setFont(num)
            p.setPen(fg)
            p.drawText(QRectF(cx, r.bottom() - 46, col_w, 22), Qt.AlignLeft | Qt.AlignVCenter, str(c.get(k, 0)))
            p.setFont(tiny)
            p.setPen(dim)
            p.drawText(QRectF(cx, r.bottom() - 26, col_w, 14), Qt.AlignLeft | Qt.AlignVCenter,
                       QFontMetricsF(tiny).elidedText(label, Qt.ElideRight, col_w - 4))  # не налезать на соседнюю

    def timing(self, state):
        """Сколько идёт задача / за сколько сделал / как давно ждёт."""
        s = self.status
        if self.forced():
            return {"done": tr("готово за 4 мин 12 с"), "party": tr("готово за 12 мин 40 с"), "idle": tr("жду новую задачу"),
                    "ask": tr("жду тебя 0:42"), "sleep": tr("сплю 7:30"), "bored": tr("жду тебя 2:10"),
                    "love": tr("погладили"), "greet": tr("новая задача"), "dizzy": tr("погладили"), "shock": tr("погладили"),
                    "sad": tr("ошибок подряд: {}").format(3), "angry": tr("ошибок подряд: {}").format(5),
                    "cool": tr("готово за 4 мин 12 с"), "starstruck": tr("правок за задачу: {}").format(34),
                    "thumbs": tr("готово за 28 с"), "blush": tr("погладили"),
                    **{n: tr("жду новую задачу") for n in IDLE_PLAY}}.get(state, tr("работаю 3:12"))
        now = time.time()
        if state in ("sad", "angry"):
            return tr("ошибок подряд: {}").format(s.get("fails", 0))
        if state in IDLE_PLAY:
            return tr("жду новую задачу")
        if state in ("dizzy", "shock", "blush"):
            return tr("погладили")
        if state == "starstruck":
            return tr("правок за задачу: {}").format(s.get("task_edits", 0))
        if state == "thumbs" and s.get("started") and s.get("finished"):
            return tr("готово за ") + dur_text(s["finished"] - s["started"])
        if state == "cool" and s.get("started") and s.get("finished"):
            return tr("правок за задачу: {}").format(s.get("task_edits", 0))
        if state in ("done", "party") and s.get("started") and s.get("finished"):
            return tr("готово за ") + dur_text(s["finished"] - s["started"])
        if not s.get("time") and state not in ("love", "blush", "dizzy", "shock"):
            return tr("жду новую задачу")
        if state == "ask":
            return tr("жду тебя ") + clock_text(now - s.get("time", now))
        if state == "sleep":
            return tr("сплю ") + clock_text(now - s.get("time", now))
        if state == "bored":
            return tr("жду тебя ") + clock_text(now - s.get("time", now))
        if state == "love":
            return tr("погладили")
        if state == "greet":
            return tr("новая задача")
        if state == "idle":
            return tr("жду новую задачу")
        if s.get("started") and not s.get("finished"):
            return tr("работаю ") + clock_text(now - s["started"])
        return ""


# вид состояния: цвет и подпись на плашке
STATE_LOOK = {
    "idle": (QColor("#9aa0aa"), tr("ждёт")), "think": (QColor("#a78bfa"), tr("думает")), "read": (QColor("#60a5fa"), tr("читает")),
    "edit": (QColor("#D97757"), tr("правит")), "run": (QColor("#34d399"), tr("запускает")), "web": (QColor("#22d3ee"), tr("в сети")),
    "done": (QColor("#4ade80"), tr("готово")), "ask": (QColor("#fb923c"), tr("нужен ответ")),
    "sleep": (QColor("#7c8aa5"), tr("спит")), "bored": (QColor("#9aa0aa"), tr("скучает")), "greet": (QColor("#fbbf24"), tr("привет")),
    "love": (QColor("#f472b6"), tr("рад")), "oops": (QColor("#f87171"), tr("ой")), "party": (QColor("#4ade80"), tr("ура!")),
    "sad": (QColor("#60a5fa"), tr("расстроен")), "angry": (QColor("#ef4444"), tr("злится")), "shock": (QColor("#fbbf24"), tr("испугался")),
    "tired": (QColor("#7c8aa5"), tr("устал")), "yawn": (QColor("#7c8aa5"), tr("зевает")), "cool": (QColor("#22d3ee"), tr("крутой")),
    "coffee": (QColor("#c08457"), tr("пьёт кофе")), "dance": (QColor("#e879f9"), tr("танцует")), "dizzy": (QColor("#fbbf24"), tr("кружится")),
    "wink": (QColor("#f472b6"), tr("подмигивает")), "stretch": (QColor("#34d399"), tr("потягивается")),
    "worried": (QColor("#fb923c"), tr("переживает")), "curious": (QColor("#a78bfa"), tr("любопытно")),
    "laugh": (QColor("#fbbf24"), tr("смеётся")), "blush": (QColor("#f472b6"), tr("смущается")),
    "zen": (QColor("#a78bfa"), tr("медитирует")), "sneeze": (QColor("#5ab8ff"), tr("чихает")),
    "starstruck": (QColor("#facc15"), tr("в восторге")), "thumbs": (QColor("#4ade80"), tr("класс!")),
}
SAMPLE_HISTORY = [{"s": "run", "d": tr("Гоняю стресс-тест"), "t": time.time() - 40},
                  {"s": "edit", "d": tr("Правлю weather.py"), "t": time.time() - 95},
                  {"s": "read", "d": tr("Читаю core.py"), "t": time.time() - 180}]


# состояния с крупным движением — плавная часть 30 кадров в секунду (остальные — 15)
BIG_MOTION = {"done", "party", "love", "laugh", "shock", "dance", "dizzy", "oops", "angry", "worried", "sneeze",
              "starstruck", "thumbs", "blush", "greet"}


def _bump(x):
    """0 -> 1 -> 0 на отрезке 0..1, мягко (полуволна синуса)."""
    return sin(pi * min(1.0, max(0.0, x)))


def motion(state, t, since):
    """Плавная часть движения персонажа в момент t (с): (сдвиг по x и высота прыжка — в клетках,
    растяжение по x и y, наклон в градусах). since — сколько секунд показано это состояние:
    в начале — пружинистое «появление». Пиксельные кадры (руки, глаза, частицы) — в sprite, это поверх."""
    dx = lift = angle = 0.0
    sx = sy = 1.0

    def jump(period, height, air=0.7):
        """Прыжок по параболе: взлёт — вытягивается, приземление — сплющивается."""
        nonlocal lift, sx, sy
        ph = (t % period) / period
        if ph < air:
            u = ph / air
            lift = height * 4 * u * (1 - u)
            stretch = 0.07 * (1 - abs(2 * u - 1))
            sx, sy = 1 - stretch * 0.6, 1 + stretch
        else:
            squash = _bump((ph - air) / (1 - air))
            sx, sy = 1 + 0.11 * squash, 1 - 0.13 * squash

    if state in ("done", "party"):
        jump(0.88, 3.0)
    elif state == "love":
        jump(0.56, 1.1, 0.6)
    elif state == "starstruck":
        jump(0.7, 1.4, 0.6)
        angle = 4 * sin(2 * pi * t / 1.4)
    elif state == "thumbs":
        jump(1.1, 0.8, 0.5)
    elif state == "laugh":  # трясётся от смеха
        lift = 0.35 * abs(sin(2 * pi * t / 0.3))
        sy = 1 - 0.05 * abs(sin(2 * pi * t / 0.3))
        sx = 1 + 0.04 * abs(sin(2 * pi * t / 0.3))
        angle = 3 * sin(2 * pi * t / 0.6)
    elif state == "shock":  # подскочил и медленно оседает
        lift = 2.4 * exp(-since * 3.2) * abs(cos(since * 7))
        sy = 1 + 0.08 * exp(-since * 4)
    elif state == "dance":
        ph = 2 * pi * t / 0.76
        dx = 0.9 * sin(ph)
        lift = 0.8 * abs(sin(ph))
        angle = 7 * sin(ph)
    elif state == "dizzy":
        angle = 11 * sin(2 * pi * t / 1.3)
        dx = 0.6 * sin(2 * pi * t / 1.3 + 0.8)
    elif state in ("oops", "angry", "worried"):  # дрожь
        dx = (0.6 if state == "angry" else 0.4) * sin(2 * pi * t * 9)
    elif state == "blush":  # стесняется — покачивается
        angle = 4 * sin(2 * pi * t / 1.6)
        sy = 1 + 0.02 * sin(2 * pi * t / 0.8)
    elif state == "stretch":
        u = _bump((t % 2.2) / 2.2)
        sy, sx = 1 + 0.09 * u, 1 - 0.04 * u
    elif state == "zen":  # парит над землёй
        lift = 1.3 + 0.5 * sin(2 * pi * t / 3.2)
    elif state == "sneeze":  # вдох (раздувается) — и отдача назад
        ph = (t % 1.44) / 1.44
        if ph < 0.6:
            u = ph / 0.6
            sy, sx = 1 + 0.07 * u * u, 1 + 0.03 * u * u
        else:
            k = _bump((ph - 0.6) / 0.4)
            dx, sy, sx = -0.9 * k, 1 - 0.08 * k, 1 + 0.06 * k
            angle = -6 * k
    elif state == "sleep":
        b = sin(2 * pi * t / 3.6)
        sy, sx = 1 + 0.045 * b, 1 - 0.02 * b
    elif state in ("edit", "run", "read", "web"):  # работает — дыхание чаще
        b = sin(2 * pi * t / 1.4)
        sy, sx = 1 + 0.022 * b, 1 - 0.01 * b
    else:  # ждёт, думает и прочее — спокойное дыхание
        b = sin(2 * pi * t / 2.6)
        sy, sx = 1 + 0.03 * b, 1 - 0.013 * b
    if since < 0.6:  # новое состояние — «выпрыгивает» с пружинкой
        pop = 1 - 0.14 * exp(-since * 9) * cos(since * 21)
        sx, sy = sx * pop, sy * pop
    return dx, lift, sx, sy, angle


def clean_status(data):
    """Статус от хука — проверить, прежде чем рисовать: кривой файл не должен ронять виджет на каждом кадре."""
    if not isinstance(data, dict):
        return {"state": "idle", "detail": "", "time": 0, "counts": {}}
    if data.get("state") not in STATE_LOOK:
        data["state"] = "think"
    if not isinstance(data.get("counts"), dict):
        data["counts"] = {}
    hist = data.get("history")
    data["history"] = [h for h in hist if isinstance(h, dict) and isinstance(h.get("t"), (int, float))
                       and isinstance(h.get("d"), str)] if isinstance(hist, list) else []
    for key in ("time", "started", "finished", "failed_at"):
        if data.get(key) is not None and not isinstance(data.get(key), (int, float)):
            data[key] = None if key != "time" else 0
    for key in ("fails", "task_edits"):
        if not isinstance(data.get(key, 0), int):
            data[key] = 0
    return data


def sprite_lift(state, f):
    """На сколько клеток персонаж в воздухе (для тени)."""
    if state in ("done", "party"):
        return (0, 1, 2, 3, 2, 1, 0, 0)[f % 8]
    if state == "shock":
        return (0, 2, 1, 0, 0, 0)[f % 6]
    if state == "dance":
        return (0, 1, 0, 1)[f % 4]
    if state == "stretch":
        return (0, 1, 1, 1, 0, 0)[f % 6]
    return (0, 1, 1, 0)[f % 4] if state == "love" else 0


def clock_text(sec):
    sec = int(max(0, sec))
    return f"{sec // 60}:{sec % 60:02d}" if sec < 3600 else tr("{} ч {:02d} мин").format(sec // 3600, sec % 3600 // 60)


def dur_text(sec):
    sec = int(max(0, sec))
    return tr("{} с").format(sec) if sec < 60 else tr("{} мин {} с").format(sec // 60, sec % 60) if sec < 3600 else clock_text(sec)


def ago_text(sec):
    sec = int(max(0, sec))
    return tr("сейчас") if sec < 10 else tr("{} с").format(sec) if sec < 60 else tr("{} мин").format(sec // 60) if sec < 3600 else tr("{} ч").format(sec // 3600)

