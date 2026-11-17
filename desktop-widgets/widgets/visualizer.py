"""Аудио-визуализатор: спектр того, что сейчас играет в Windows (любая программа — браузер, Spotify, игра).
Раскладка — как у остальных виджетов («Звук», «Вода»): слева плитка (обложка трека или значок в цветах темы),
справа заголовок с плашкой «играет / тишина», название трека и исполнитель, под ними — спектр.
Виды: столбики, волна, широкие столбики, круг. Цвета — из темы оформления (акцент → второй акцент).
Звук снимается audio_capture (WASAPI loopback) только пока виджет виден; тишина — кадры почти не рисуются."""
from lang import tr
import math
import time

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen

import skins
from core import DesktopWidget, activity, grid
from widgets import kit


def app_icon(img):
    """Похоже на значок программы, а не на обложку: обложки непрозрачные и не крошечные, у значка — прозрачные
    углы/фон. Смотрим сетку 12×12 точек: больше 8% прозрачных — значок."""
    if img.isNull():
        return True
    w, h = img.width(), img.height()
    if max(w, h) <= 64:
        return True
    if not img.hasAlphaChannel():
        return False
    clear = sum(img.pixelColor(int((x + 0.5) * w / 12), int((y + 0.5) * h / 12)).alpha() < 40  # у обложек Spotify края полупрозрачные (~180) — это не значок
                for x in range(12) for y in range(12))
    return clear > 144 * 0.08


class VisualizerWidget(DesktopWidget):
    key = "visualizer"
    title = tr("Визуализатор")
    description = tr("Спектр музыки, которая играет на компьютере: столбики, круг или волна")
    SHAPES = {"bars": (tr("Столбики"), grid(2, 1)), "circle": (tr("Круг"), grid(2, 2)),
              "wave": (tr("Волна"), grid(4, 1)), "wide": (tr("Широкие столбики"), grid(4, 1))}

    def __init__(self, **kw):
        super().__init__(**kw)
        self.apply_shape()
        self.levels = np.zeros(64, np.float32)  # что сейчас нарисовано (сглаженно)
        self.peaks = np.zeros(64, np.float32)   # «шапки» столбиков — падают медленнее
        self.gain = 0.6                          # автоусиление: тихая музыка тоже заполняет виджет
        self.bmax = np.full(64, 0.2, np.float32)  # недавний максимум каждой полосы (выравнивание басов и верхов)
        self.last = time.monotonic()
        self.capturing = False
        self.timer = QTimer(self, interval=16, timeout=self.tick, timerType=Qt.PreciseTimer)
        self.track, self.artist, self.cover = "", "", None
        self._media_sig = None
        from widgets.player import Media
        Media.get().changed.connect(self.on_media)

    # ---- захват звука: только пока виджет на экране ----
    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, "preview", False):
            self.start_capture()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.stop_capture()

    def closeEvent(self, event):
        self.stop_capture()
        super().closeEvent(event)

    def start_capture(self):
        if self.capturing:
            return
        from audio_capture import spectrum
        spectrum.acquire()
        self.capturing = True
        self.timer.start()

    def stop_capture(self):
        if not self.capturing:
            return
        from audio_capture import spectrum
        spectrum.release()
        self.capturing = False
        self.timer.stop()

    def bands_count(self):
        return {"bars": 16, "circle": 48, "wave": 40, "wide": 44}.get(self.shape(), 16)

    def tick(self):
        if activity.covered(self):  # закрыт окном или игрой — кадры не нужны
            self.timer.setInterval(300)
            return
        from audio_capture import spectrum
        n = self.bands_count()
        now = time.monotonic()
        dt = min(0.1, now - self.last)
        self.last = now
        self.step(spectrum.bands(n), dt)
        quiet = spectrum.silent() and float(self.levels.max()) < 0.01 and float(self.peaks.max()) < 0.01
        self.timer.setInterval(250 if quiet else 16)  # тишина — почти не просыпаемся
        self.update()

    def step(self, raw, dt):
        """Новый спектр -> что рисовать. Басы у любой музыки громче — без выравнивания левая половина стояла
        в потолке, а правая не шевелилась. Поэтому каждая полоса ещё и мерится своим недавним максимумом
        (медленно забывается), плюс общее автоусиление; вверх — быстро, вниз — плавно; «шапки» падают медленно."""
        n = len(raw)
        if len(self.levels) != n:
            self.levels = np.zeros(n, np.float32)
            self.peaks = np.zeros(n, np.float32)
            self.bmax = np.full(n, 0.2, np.float32)
        self.bmax = np.maximum(raw, self.bmax * (1 - min(0.5, dt * 0.4)))
        per = raw / np.maximum(self.bmax, 0.18)
        top = float(raw.max())
        if top > 0.05:
            want = 0.9 / top
            self.gain += (min(2.2, max(0.8, want)) - self.gain) * min(1.0, dt * 1.5)
        target = np.clip(0.55 * per * 0.92 + 0.45 * raw * self.gain, 0, 1)
        up = target > self.levels
        k_up, k_down = min(1.0, dt * 28), min(1.0, dt * 7)
        self.levels += (target - self.levels) * np.where(up, k_up, k_down)
        self.peaks = np.maximum(self.levels, self.peaks - dt * 0.6)

    # ---- трек: обложка и название — из медиа-панели Windows, как у «Плеера» ----
    def on_media(self, state):
        state = state or {}
        cover = state.get("cover")
        if cover is not None and id(cover) != getattr(self, "_icon_id", None):
            self._icon_id, self._icon_is = id(cover), app_icon(cover)  # проверяем раз на картинку, не каждую секунду
        if cover is not None and self._icon_is:
            cover = None  # вместо обложки Windows отдала значок программы (браузер, Telegram) — рисуем свою плитку
        sig = (state.get("title"), state.get("artist"), id(cover))
        self.track, self.artist, self.cover = state.get("title") or "", state.get("artist") or "", cover
        if sig != self._media_sig:
            self._media_sig = sig
            self.update()

    # ---- рисование ----
    def demo(self, n):
        """Для превью в каталоге (звук не снимается): красивый неподвижный спектр."""
        x = np.linspace(0, 1, n)
        return (0.25 + 0.55 * np.exp(-((x - 0.18) / 0.16) ** 2) + 0.3 * np.exp(-((x - 0.55) / 0.2) ** 2)
                + 0.12 * np.sin(x * 31) ** 2).clip(0.05, 0.95).astype(np.float32)

    def paintEvent(self, event):
        super().paintEvent(event)  # стекло
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        r = QRectF(self.card())
        fg, dim, track = kit.ink(self)
        dark = bool(self.dark)
        n = self.bands_count()
        preview = getattr(self, "preview", False)
        levels = self.demo(n) if preview else (self.levels if len(self.levels) == n else np.zeros(n, np.float32))
        peaks = levels if preview else (self.peaks if len(self.peaks) == n else levels)
        a1, a2 = QColor(skins.ACCENT), QColor(skins.ACCENT2)
        if preview:
            playing = True
        else:
            from audio_capture import spectrum
            playing = not spectrum.silent() or float(levels.max()) > 0.02
        label, color = (tr("играет"), kit.GREEN) if playing else (tr("тишина"), kit.GRAY)
        title = self.track or (tr("Звук компьютера") if playing else tr("Ничего не играет"))
        artist = self.artist or ("" if self.track else tr("спектр того, что играет") if playing
                                 else tr("включи музыку или видео"))
        cw = kit.chip(p, r, label, color, dark)
        if self.shape() == "circle":
            kit.text(p, QRectF(r.left() + 18, r.top() + 14, r.width() - 36 - cw, 22), tr("Визуализатор"), fg, 16,
                     "Segoe UI Semibold", elide=True)
            area = QRectF(r.left() + 14, r.top() + 46, r.width() - 28, r.height() - 46 - 62)
            self.paint_circle(p, area, levels, a1, a2)
            kit.text(p, QRectF(r.left() + 18, r.bottom() - 58, r.width() - 36, 22), title, fg, 15,
                     "Segoe UI Semibold", Qt.AlignCenter, elide=True)
            kit.text(p, QRectF(r.left() + 18, r.bottom() - 36, r.width() - 36, 16), artist, dim, 11,
                     align=Qt.AlignCenter, elide=True)
            p.end()
            return
        tile = QRectF(r.left() + 14, r.top() + 14, r.height() - 28, r.height() - 28)
        self.paint_disc(p, tile, levels, a1, a2, round_=False)
        x = tile.right() + 16
        w = r.right() - 18 - x
        head = tr("Визуализатор") if self.shape() != "bars" else tr("Спектр")  # в 2×1 рядом с плашкой — короче
        kit.text(p, QRectF(x, r.top() + 14, w - cw, 22), head, fg, 16, "Segoe UI Semibold", elide=True)
        kit.text(p, QRectF(x, r.top() + 42, w, 20), title, fg, 14, "Segoe UI Semibold", elide=True)
        kit.text(p, QRectF(x, r.top() + 62, w, 16), artist, dim, 11, elide=True)
        area = QRectF(x, r.top() + 86, w, r.bottom() - 18 - (r.top() + 86))
        if self.shape() == "wave":
            self.paint_wave(p, area, levels, a1, a2, track)
        else:
            self.paint_bars(p, area, levels, peaks, a1, a2, track)
        p.end()

    def paint_disc(self, p, box, levels, a1, a2, round_):
        """Обложка трека (в плитке или круге); нет обложки — плитка в цветах темы, белые столбики пляшут в такт."""
        clip = QPainterPath()
        if round_:
            clip.addEllipse(box)
        else:
            clip.addRoundedRect(box, 22, 22)
        cover = self.cover
        if cover is not None and not cover.isNull():
            p.save()
            p.setClipPath(clip)
            side = min(cover.width(), cover.height())
            p.drawImage(box, cover, QRectF((cover.width() - side) / 2, (cover.height() - side) / 2, side, side))
            p.restore()
            return
        grad = QLinearGradient(box.topLeft(), box.bottomLeft())
        grad.setColorAt(0, a1.lighter(115))
        grad.setColorAt(1, a1.darker(150))
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        p.drawPath(clip)
        k = len(levels)
        vals = [float(levels[int(i * (k - 1) / 4)]) for i in range(5)]
        bw = box.width() * 0.085
        gap = box.width() * 0.055
        x0 = box.center().x() - (5 * bw + 4 * gap) / 2
        p.setBrush(QColor("white"))
        for i, v in enumerate(vals):
            h = box.height() * (0.15 + 0.4 * v)
            p.drawRoundedRect(QRectF(x0 + i * (bw + gap), box.center().y() - h / 2, bw, h), bw / 2, bw / 2)

    def paint_bars(self, p, r, levels, peaks, a1, a2, track):
        n = len(levels)
        gap = 3.0
        bw = max(2.0, (r.width() - gap * (n - 1)) / n)
        base = r.bottom()
        hmax = r.height()
        grad = QLinearGradient(QPointF(0, base), QPointF(0, r.top()))
        grad.setColorAt(0, a1)
        grad.setColorAt(1, a2)
        p.setPen(Qt.NoPen)
        for i, v in enumerate(levels):
            x = r.left() + i * (bw + gap)
            p.setBrush(track)  # дорожка — как у полосок «Системы» и «Звука»
            p.drawRoundedRect(QRectF(x, r.top(), bw, hmax), bw / 2, bw / 2)
            h = max(bw, float(v) * hmax)
            p.setBrush(grad)
            p.drawRoundedRect(QRectF(x, base - h, bw, h), bw / 2, bw / 2)
            pk = float(peaks[i])
            if pk > v + 0.03:  # «шапка» — тонкая полоска над столбиком
                p.setBrush(a2)
                p.drawRoundedRect(QRectF(x, base - pk * hmax, bw, 2.5), 1.2, 1.2)

    def paint_circle(self, p, r, levels, a1, a2):
        n = len(levels)
        c = r.center()
        R = min(r.width(), r.height()) / 2
        inner = R * 0.5
        energy = float(levels[: max(1, n // 6)].mean())  # низкие частоты — «удары»
        half = np.concatenate([levels, levels[::-1]])  # зеркально, низкие частоты сверху
        m = len(half)
        for i, v in enumerate(half):
            a = -math.pi / 2 + 2 * math.pi * i / m
            length = 3 + float(v) * (R - inner - 8)
            mix = abs(1 - 2 * i / m)
            col = QColor.fromRgbF(a1.redF() * mix + a2.redF() * (1 - mix), a1.greenF() * mix + a2.greenF() * (1 - mix),
                                  a1.blueF() * mix + a2.blueF() * (1 - mix))
            p.setPen(QPen(col, max(2.0, 2 * math.pi * inner / m * 0.5), Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(c.x() + math.cos(a) * (inner + 5), c.y() + math.sin(a) * (inner + 5)),
                       QPointF(c.x() + math.cos(a) * (inner + 5 + length), c.y() + math.sin(a) * (inner + 5 + length)))
        rad = inner * (1 + 0.05 * energy)  # обложка чуть «дышит» в такт басу
        disc = QRectF(c.x() - rad, c.y() - rad, 2 * rad, 2 * rad)
        self.paint_disc(p, disc, levels, a1, a2, round_=True)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 80), 1.2))
        p.drawEllipse(disc)

    def paint_wave(self, p, r, levels, a1, a2, track):
        n = len(levels)
        mid = r.center().y()
        amp = r.height() / 2
        xs = [r.left() + r.width() * i / (n - 1) for i in range(n)]
        p.setPen(QPen(track, 1))
        p.drawLine(QPointF(r.left(), mid), QPointF(r.right(), mid))

        def curve(sign, k):
            path = QPainterPath(QPointF(r.left(), mid))
            pts = [QPointF(x, mid - sign * float(v) * amp * k) for x, v in zip(xs, levels)]
            path.lineTo(pts[0])
            for a, b in zip(pts, pts[1:]):  # плавная кривая через середины отрезков
                path.quadTo(a, QPointF((a.x() + b.x()) / 2, (a.y() + b.y()) / 2))
            path.lineTo(pts[-1])
            path.lineTo(QPointF(r.right(), mid))
            return path

        for k, alpha in ((1.0, 210), (0.55, 130)):
            grad = QLinearGradient(QPointF(r.left(), 0), QPointF(r.right(), 0))
            c1, c2 = QColor(a1), QColor(a2)
            c1.setAlpha(alpha)
            c2.setAlpha(alpha)
            grad.setColorAt(0, c1)
            grad.setColorAt(1, c2)
            p.setPen(Qt.NoPen)
            p.setBrush(grad)
            p.drawPath(curve(1, k).united(curve(-1, k)))
