"""Луна: фаза сейчас (рисуем освещённую часть), название фазы, освещённость и сколько дней до полнолуния.
Считается без интернета: от известного новолуния и длины лунного месяца."""
from lang import tr
import math
from datetime import datetime, timezone

import numpy as np
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QImage, QPainter

from core import DesktopWidget, grid

NEW_MOON = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)  # известное новолуние
SYNODIC = 29.530588853  # лунный месяц, дней
PHASES = [(1.0, tr("Новолуние")), (6.4, tr("Растущий серп")), (8.4, tr("Первая четверть")), (13.8, tr("Растущая луна")),
          (15.8, tr("Полнолуние")), (21.1, tr("Убывающая луна")), (23.1, tr("Последняя четверть")), (28.5, tr("Убывающий серп")),
          (30.0, tr("Новолуние"))]


def moon_age(now=None):
    """Возраст луны в днях от новолуния (0..29.5)."""
    now = now or datetime.now(timezone.utc)
    return ((now - NEW_MOON).total_seconds() / 86400) % SYNODIC


def phase_name(age):
    return next(name for limit, name in PHASES if age < limit)


def moon_image(age, size, dark):
    """Картинка луны size×size: освещённая часть по фазе, мягкое затемнение к краю (объём)."""
    theta = 2 * math.pi * age / SYNODIC  # 0 — новолуние, π — полнолуние
    k = math.cos(theta)
    y, x = np.mgrid[0:size, 0:size].astype(np.float32)
    x = (x + 0.5) / size * 2 - 1
    y = (y + 0.5) / size * 2 - 1
    d2 = x * x + y * y
    inside = d2 <= 1
    s = np.sqrt(np.clip(1 - y * y, 0, 1))
    lit = (x >= k * s) if theta < math.pi else (x <= -k * s)  # растущая — свет справа, убывающая — слева
    shade = np.clip(1.05 - d2 * 0.35, 0, 1)  # к краю чуть темнее — шар
    base_lit = np.array([242, 238, 226], np.float32)
    base_dark = np.array([58, 60, 70] if dark else [150, 152, 160], np.float32)
    rgb = np.where(lit[..., None], base_lit, base_dark) * shade[..., None]
    alpha = np.clip((1 - np.sqrt(d2)) * size / 2 + 0.5, 0, 1) * 255  # сглаженный край
    rgba = np.zeros((size, size, 4), np.uint8)
    rgba[..., :3] = np.clip(rgb, 0, 255)
    rgba[..., 3] = np.where(inside | (alpha > 0), alpha, 0)
    img = QImage(rgba.data, size, size, size * 4, QImage.Format_RGBA8888)
    return img.copy()


class MoonWidget(DesktopWidget):
    key = "moon"
    title = tr("Луна")
    description = tr("Фаза луны и сколько до полнолуния")
    SHAPES = {"tile": (tr("Плитка"), grid(1, 1))}

    def __init__(self, **kw):
        super().__init__(**kw)
        self.apply_shape()
        self.cache = (None, None)  # (ключ, картинка)
        self.timer = QTimer(self, interval=10 * 60 * 1000, timeout=self.update)  # фаза меняется медленно
        self.timer.start()

    def paintEvent(self, event):
        super().paintEvent(event)  # стекло
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        r = QRectF(self.card()).adjusted(16, 14, -16, -14)
        dark = bool(self.dark)
        fg = QColor("#ededf0") if dark else QColor("#151517")
        dim = QColor(fg)
        dim.setAlpha(140)
        age = moon_age()
        size = 72
        key = (round(age, 2), dark)
        if self.cache[0] != key:
            self.cache = (key, moon_image(age, size * 2, dark))
        p.drawImage(QRectF(r.right() - size, r.top(), size, size), self.cache[1])

        head = QFont("Segoe UI Semibold")
        head.setPixelSize(15)
        p.setFont(head)
        p.setPen(fg)
        p.drawText(QRectF(r.left(), r.top(), r.width(), 20), Qt.AlignLeft | Qt.AlignVCenter, tr("Луна"))
        light = (1 - math.cos(2 * math.pi * age / SYNODIC)) / 2
        big = QFont("Bahnschrift SemiBold")
        big.setPixelSize(26)
        p.setFont(big)
        p.drawText(QRectF(r.left(), r.top() + 26, r.width() - size, 32), Qt.AlignLeft | Qt.AlignVCenter,
                   f"{light * 100:.0f}%")
        small = QFont("Segoe UI")
        small.setPixelSize(11)
        p.setFont(small)
        p.setPen(dim)
        p.drawText(QRectF(r.left(), r.top() + 56, r.width(), 14), Qt.AlignLeft | Qt.AlignVCenter, tr("освещена"))
        name = QFont("Segoe UI Semibold")
        name.setPixelSize(13)
        p.setFont(name)
        p.setPen(fg)
        p.drawText(QRectF(r.left(), r.bottom() - 38, r.width(), 18), Qt.AlignLeft | Qt.AlignVCenter, phase_name(age))
        to_full = (SYNODIC / 2 - age) % SYNODIC
        to_new = SYNODIC - age
        p.setFont(small)
        p.setPen(dim)
        text = tr("до полнолуния {:.0f} дн").format(to_full) if age < SYNODIC / 2 else tr("до новолуния {:.0f} дн").format(to_new)
        if to_full < 0.5 or age > SYNODIC - 0.5 or age < 0.5:
            text = tr("сегодня")
        p.drawText(QRectF(r.left(), r.bottom() - 18, r.width(), 16), Qt.AlignLeft | Qt.AlignVCenter, text)
