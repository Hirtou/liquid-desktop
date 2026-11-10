"""Слова песни: что сейчас играет в Spotify — текст построчно, текущая строка крупно и подсвечена.

Трек и позиция — из медиа-панели Windows (как у плеера, widgets/player.py: Media). Текст — из открытой базы LRCLIB
(lrclib.net, без ключей и входа): синхронизированный (у каждой строки время) — строки сменяются вместе с песней
и плавно прокручиваются; только обычный текст — прокручивается по ходу песни; инструментал — «без слов».
Найденное запоминается на диске (lyrics_cache.json), второй раз сеть не нужна.
"""
from lang import tr
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPen,
                           QPixmap, QTextLayout, QTextOption)

from core import DesktopWidget, RADIUS, ROOT, activity, grid
from widgets.player import Media, accent, open_player

CACHE = os.path.join(ROOT, "lyrics_cache.json")
CACHE_MAX = 300           # песен в кэше
LEAD = 0.25               # строка подсвечивается чуть раньше (так её успеваешь прочитать)
GAP = 12                  # между строками
SMALL, BIG = 15, 21       # кегль строки вдали и текущей
DOTS_H = 30               # место под «точки» в паузе без слов
FADE_TOP, FADE_BOTTOM = 26, 54  # мягкое затухание текста у краёв, px
API = "https://lrclib.net/api/"
HEADERS = {"User-Agent": "DesktopWidgets/1.0 (personal lyrics widget)"}
TIME = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]")


def parse_lrc(text):
    """«[01:02.34] строка» -> [(секунды, строка)], по времени."""
    out = []
    for line in (text or "").splitlines():
        stamps = TIME.findall(line)
        words = TIME.sub("", line).strip()
        for m, s in stamps:
            out.append((int(m) * 60 + float(s), words))
    out.sort(key=lambda x: x[0])
    return out


def _get(url):
    for attempt in range(5):  # LRCLIB иногда отвечает 503 / не отвечает — пробуем ещё
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=6) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(1.0 + attempt)
        except (urllib.error.URLError, OSError, ValueError):
            time.sleep(1.0 + attempt)
    raise OSError(tr("нет связи с LRCLIB"))


def fetch(artist, title, duration):
    """-> {"synced": [(t, строка)], "plain": [строки], "instrumental": bool} или None (не нашлось)."""
    q = {"artist_name": artist, "track_name": title}
    if duration:
        q["duration"] = int(round(duration))
    d = _get(API + "get?" + urllib.parse.urlencode(q))
    if d is None or not (d.get("syncedLyrics") or d.get("plainLyrics") or d.get("instrumental")):
        # точного совпадения нет — поиск; берём ближайшее по длительности (с синхронным текстом — лучше)
        found = _get(API + "search?" + urllib.parse.urlencode({"track_name": title, "artist_name": artist})) or []
        found = [f for f in found if f.get("syncedLyrics") or f.get("plainLyrics")]
        if duration:
            close = [f for f in found if abs((f.get("duration") or duration) - duration) < 12]
            if not close:  # другая версия песни (feat., ремикс, другой длины): синхронный текст разъедется,
                # а обычный — без времени — подойдёт и так
                close = [dict(f, syncedLyrics=None) for f in found if f.get("plainLyrics")]
            found = close
        found.sort(key=lambda f: (not f.get("syncedLyrics"), abs((f.get("duration") or 0) - (duration or 0))))
        d = found[0] if found else d
    if d is None:
        return None
    return {"synced": parse_lrc(d.get("syncedLyrics")),
            "plain": [l.strip() for l in (d.get("plainLyrics") or "").splitlines()],
            "instrumental": bool(d.get("instrumental"))}


class Cache:
    """Найденные тексты на диске: ключ «исполнитель — песня». Один на программу (виджет и его превью
    в каталоге): иначе каждая копия держит весь файл в памяти и при записи затирает найденное другой."""
    _shared = None

    @classmethod
    def shared(cls):
        if cls._shared is None:
            cls._shared = cls()
        return cls._shared

    def __init__(self):
        self.lock = threading.Lock()
        try:
            with open(CACHE, encoding="utf-8-sig") as f:
                self.data = json.load(f)
        except (OSError, ValueError):
            self.data = {}

    def get(self, key):
        with self.lock:
            v = self.data.get(key)
        if v is not None and v.get("synced"):
            v = dict(v, synced=[tuple(x) for x in v["synced"]])
        return v

    def put(self, key, value):
        with self.lock:
            self.data.pop(key, None)
            self.data[key] = value
            while len(self.data) > CACHE_MAX:  # старые — вон
                self.data.pop(next(iter(self.data)))
            try:
                with open(CACHE, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, ensure_ascii=False)
            except OSError:
                pass


class LyricsWidget(DesktopWidget):
    key = "lyrics"
    title = tr("Слова песни")
    description = tr("Текст того, что играет сейчас")
    SHAPES = {"tall": (tr("Высокий"), grid(2, 2)), "wide": (tr("Широкий"), grid(2, 1))}
    loaded = Signal(object, object)  # (ключ песни, текст или None/"error")

    def __init__(self, **kw):
        super().__init__(**kw)
        self.apply_shape()
        self.cache = Cache.shared()
        self.state = None
        self.song = None        # (исполнитель, песня)
        self.lyrics = None      # {"synced", "plain", "instrumental"}
        self.status = "idle"    # idle / loading / ok / none / error
        self.index = -1         # текущая строка
        self.offset = 0.0       # плавная прокрутка: где сейчас «якорь» (px от начала текста)
        self.offset_to = 0.0
        self.layout_key, self.slots = None, []  # раскладка строк: [(верх, высота)] для текущей ширины
        self.cover_key, self.cover_img, self.color = None, None, None
        self.loaded.connect(self.on_loaded)
        Media.get().changed.connect(self.on_state)
        self.anim = QTimer(self, interval=16, timeout=self.step, timerType=Qt.PreciseTimer)
        self.next_line = QTimer(self, singleShot=True, timeout=self.sync)  # ровно к смене строки
        self.last = time.monotonic()

    # ---------- данные ----------

    def on_state(self, state):
        self.state = state
        if state and "key" in state:
            if state["key"] != self.cover_key or state.get("cover") is not self.cover_img:  # обложка браузера приходит позже
                self.cover_key, self.cover_img = state["key"], state.get("cover")
                self.color = accent(self.cover_img) if self.cover_img is not None else None
                self.update()
            title, artist = state["key"]
            song = (artist or "", title or "")
            if song != self.song:
                self.song, self.lyrics, self.index = song, None, -1
                self.offset = self.offset_to = 0.0
                self.layout_key = None
                self.load(song, state.get("duration"))
        self.sync()

    def load(self, song, duration):
        key = f"{song[0]} — {song[1]}".lower()
        cached = self.cache.get(key)
        if cached is not None:
            self.on_loaded(song, cached)
            return
        self.status = "loading"
        self.update()

        def work():
            try:
                found = fetch(song[0], song[1], duration)
            except OSError:
                found = "error"
            if found not in (None, "error"):
                self.cache.put(key, found)
            elif found is None:
                self.cache.put(key, {"synced": [], "plain": [], "instrumental": False, "none": True})
            try:
                self.loaded.emit(song, found)
            except RuntimeError:  # виджет закрыли
                pass
        threading.Thread(target=work, daemon=True).start()

    def on_loaded(self, song, found):
        if song != self.song:
            return  # пока искали, песня сменилась
        if found == "error":  # база не ответила (бывает 503) — через 15 с ещё раз, если песня та же
            self.status = "error"
            QTimer.singleShot(15000, lambda s=song: self.load(s, (self.state or {}).get("duration"))
                              if s == self.song and self.status == "error" else None)
        elif not found or found.get("none") or not (found["synced"] or found["plain"] or found["instrumental"]):
            self.status = "none"
        else:
            self.lyrics, self.status = found, "ok"
        self.index = -1
        self.layout_key = None
        self.sync()
        self.update()

    def position(self):
        s = self.state
        if not s or "position" not in s:
            return 0.0
        return s["position"] + (time.monotonic() - s["read"] if s["playing"] else 0)

    def lines(self):
        if not self.lyrics:
            return []
        if self.lyrics["synced"]:
            return [t for _, t in self.lyrics["synced"]]
        return [l for l in self.lyrics["plain"]]

    def sync(self):
        """Какая строка сейчас; следующая смена — по таймеру ровно к её времени (без опроса каждые 16 мс)."""
        self.next_line.stop()
        if self.status != "ok" or not self.lyrics or not self.state:
            return
        pos = self.position() + LEAD
        synced = self.lyrics["synced"]
        if synced:
            idx = max(-1, sum(1 for t, _ in synced if t <= pos) - 1)
            if self.state.get("playing") and idx + 1 < len(synced):
                self.next_line.start(max(30, int((synced[idx + 1][0] - pos) * 1000) + 10))
        else:  # обычный текст: прокрутка по ходу песни
            n, dur = len(self.lyrics["plain"]), self.state.get("duration") or 0
            idx = min(n - 1, int(pos / dur * n)) if dur and n else 0
            if self.state.get("playing") and dur and n:
                self.next_line.start(max(200, int(dur / n * 1000)))
        if idx != self.index:
            jump = abs(idx - self.index) > 3  # перемотали — без долгой прокрутки
            self.index = idx
            self.offset_to = self.anchor_of(idx)
            if jump:
                self.offset = self.offset_to
        self.kick()  # прокрутка, заливка строки и «точки» — кадрами, пока играет

    # ---------- раскладка ----------

    def body_rect(self):
        r = QRectF(self.card())
        return QRectF(r.left() + 20, r.top() + 58, r.width() - 40, r.bottom() - r.top() - 58 - 10)

    def line_layout(self):
        """Где какая строка (по высоте), если каждая — крупным кеглем с переносом: [(верх, высота)]."""
        width = self.body_rect().width()
        key = (self.song, len(self.lines()), int(width))
        if key != self.layout_key:
            self.layout_key = key
            font = QFont("Segoe UI Semibold")
            font.setPixelSize(BIG)
            fm = QFontMetricsF(font)
            y, self.slots = DOTS_H + GAP, []  # сверху — место под «точки» до первой строки
            for text in self.lines():
                h = DOTS_H if not text.strip() or text.strip() == "♪" else \
                    fm.boundingRect(QRectF(0, 0, width, 1e5), Qt.TextWordWrap, text).height()
                self.slots.append((y, h))
                y += h + GAP
        return self.slots

    def anchor_of(self, idx):
        """Середина строки idx (до первой строки — «точки»)."""
        slots = self.line_layout()
        if idx < 0 or idx >= len(slots):
            return DOTS_H / 2
        top, h = slots[idx]
        return top + h / 2

    def karaoke(self):
        """Доля спетого в текущей строке 0..1 (только у синхронного текста), иначе None."""
        if not self.lyrics or not self.lyrics["synced"] or self.index < 0:
            return None
        synced = self.lyrics["synced"]
        t0 = synced[self.index][0]
        t1 = synced[self.index + 1][0] if self.index + 1 < len(synced) else t0 + 4
        return max(0.0, min(1.0, (self.position() + LEAD - t0) / max(0.3, t1 - t0)))

    # ---------- анимация ----------

    def kick(self):
        if not self.anim.isActive() and self.isVisible():
            self.last = time.monotonic()
            self.anim.start()

    def step(self):
        now = time.monotonic()
        dt = min(0.05, now - self.last)
        self.last = now
        d = self.offset_to - self.offset
        scrolling = abs(d) > 0.3
        self.offset = self.offset + d * (1 - pow(2.718, -dt * 9)) if scrolling else self.offset_to
        playing = bool(self.state and self.state.get("playing")) and self.status == "ok"
        hidden = activity.covered(self)
        if hidden:  # закрыт окном или игрой: кадры не нужны — прокрутку сразу до места, проверка 4 раза в с
            self.offset, scrolling = self.offset_to, False
        # прокрутка — 60 кадров; поётся строка или пауза с точками — 30; иначе стоим
        rate = 250 if hidden and playing else 16 if scrolling else 33 if playing else 0
        if rate:
            if self.anim.interval() != rate:
                self.anim.setInterval(rate)
        else:
            self.anim.stop()
        if hidden:
            return  # откроют — Activity сам перерисует виджет целиком
        # шапка (обложка, название) от кадра к кадру не меняется — перерисовываем только строки
        k = self.scale()
        body = self.body_rect().adjusted(-2, -2, 2, 2)
        self.update(QRectF(body.topLeft() * k, body.bottomRight() * k).toAlignedRect())

    def double_click(self):
        open_player(self.state)

    # ---------- рисование ----------

    def paintEvent(self, event):
        super().paintEvent(event)  # стекло
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        r = QRectF(self.card())
        dark = bool(self.dark)
        fg = QColor("#ededf0") if dark else QColor("#151517")
        dim = QColor(fg)
        dim.setAlpha(130)
        clip = QPainterPath()
        clip.addRoundedRect(r, RADIUS, RADIUS)
        p.setClipPath(clip)
        if self.color is not None:  # мягкая подсветка цветом обложки сверху, как у плеера
            glow = QLinearGradient(r.topLeft(), r.bottomLeft())
            c1, c2 = QColor(self.color), QColor(self.color)
            c1.setAlpha(110 if dark else 80)
            c2.setAlpha(0)
            glow.setColorAt(0, c1)
            glow.setColorAt(0.75, c2)
            p.fillRect(r, glow)

        s = self.state
        self._header(p, r, s, fg, dim)
        body = self.body_rect()
        msg = None
        if not s or "key" not in s:
            msg = tr("Сейчас ничего не играет")
        elif self.status == "loading":
            msg = tr("Ищу слова…")
        elif self.status == "error":
            msg = tr("Нет связи с базой текстов")
        elif self.status == "none":
            msg = tr("Слов к этой песне не нашлось")
        elif self.lyrics and self.lyrics["instrumental"] and not self.lines():
            msg = tr("Без слов")
        if msg:
            f = QFont("Segoe UI Semibold")
            f.setPixelSize(15)
            p.setFont(f)
            p.setPen(dim)
            p.drawText(body, Qt.AlignCenter, msg)
            return

        # текст рисуем в отдельную картинку и гасим её края градиентом — строки мягко тают вверху и внизу
        dpr = self.devicePixelRatioF() * self.scale()
        pix = QPixmap(int(body.width() * dpr) + 2, int(body.height() * dpr) + 2)
        pix.setDevicePixelRatio(dpr)
        pix.fill(Qt.transparent)
        q = QPainter(pix)
        q.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self._lines(q, body.width(), body.height(), fg)
        q.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        mask = QLinearGradient(0, 0, 0, body.height())
        h = max(1.0, body.height())
        mask.setColorAt(0, QColor(0, 0, 0, 0))
        mask.setColorAt(FADE_TOP / h, QColor(0, 0, 0, 255))
        mask.setColorAt(1 - FADE_BOTTOM / h, QColor(0, 0, 0, 255))
        mask.setColorAt(1, QColor(0, 0, 0, 0))
        q.fillRect(QRectF(0, 0, body.width() + 2, body.height() + 2), mask)
        q.end()
        p.drawPixmap(body.topLeft(), pix)

    def _header(self, p, r, s, fg, dim):
        """Шапка: обложка, песня, исполнитель."""
        if not s or "key" not in s:
            return
        cover = QRectF(r.left() + 18, r.top() + 14, 32, 32)
        img = s.get("cover")
        path = QPainterPath()
        path.addRoundedRect(cover, 8, 8)
        if img is not None:
            p.save()
            p.setClipPath(path, Qt.IntersectClip)
            crop = min(img.width(), img.height())
            p.drawImage(cover, img, QRectF((img.width() - crop) / 2, (img.height() - crop) / 2, crop, crop))
            p.restore()
        else:
            p.fillPath(path, QColor(128, 128, 140, 70))
        x = cover.right() + 10
        w = r.right() - 18 - x
        t = QFont("Segoe UI Semibold")
        t.setPixelSize(13)
        a = QFont("Segoe UI")
        a.setPixelSize(11)
        title, artist = s["key"]
        p.setFont(t)
        p.setPen(fg)
        p.drawText(QRectF(x, cover.top() - 1, w, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetricsF(t).elidedText(title or "—", Qt.ElideRight, w))
        p.setFont(a)
        p.setPen(dim)
        p.drawText(QRectF(x, cover.top() + 16, w, 16), Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetricsF(a).elidedText(artist or "", Qt.ElideRight, w))

    def _lines(self, q, width, height, fg):
        """Строки: текущая — крупно и заливается по мере пения; соседи меньше и бледнее, растут, подъезжая."""
        lines = self.lines()
        slots = self.line_layout()
        anchor = height * 0.36
        shift = anchor - self.offset  # +shift: из координат текста в координаты картинки
        if self.index < 0 or (0 <= self.index < len(lines) and lines[self.index].strip() in ("", "♪")):
            y = (DOTS_H / 2 if self.index < 0 else self.anchor_of(self.index)) + shift
            self._dots(q, QPointF(14, y), fg)
        fill = self.karaoke()
        for i, text in enumerate(lines):
            top, h = slots[i]
            y = top + shift
            if y + h < -10 or y > height + 10:
                continue
            if not text.strip() or text.strip() == "♪":
                continue  # пауза: на её месте точки (если она сейчас)
            near = max(0.0, 1 - abs((top + h / 2) - self.offset) / 70)  # 1 — строка у якоря
            font = QFont("Segoe UI Semibold")
            font.setPixelSize(int(round(SMALL + (BIG - SMALL) * near)))
            past, current = i < self.index, i == self.index
            dimc = QColor(fg)
            dimc.setAlpha(80 if past else 125)
            if current and fill is not None:  # заливка: спетое — ярко, мягкий переход, впереди — бледно
                self._karaoke(q, text, font, QRectF(0, y, width, h), fill, fg, dimc)
                continue
            col = QColor(fg) if current else dimc
            q.setFont(font)
            q.setPen(col)
            q.drawText(QRectF(0, y, width, h), Qt.AlignLeft | Qt.AlignVCenter | Qt.TextWordWrap, text)

    @staticmethod
    def _karaoke(q, text, font, rect, fill, bright, dim):
        """Текст с переносом (QTextLayout), каждая строчка — градиентом: до точки пения ярко, дальше бледно."""
        lay = QTextLayout(text, font)
        opt = QTextOption()
        opt.setWrapMode(QTextOption.WordWrap)
        lay.setTextOption(opt)
        lay.beginLayout()
        rows, y = [], 0.0
        while True:
            line = lay.createLine()
            if not line.isValid():
                break
            line.setLineWidth(rect.width())
            line.setPosition(QPointF(0, y))
            rows.append(line)
            y += line.height()
        lay.endLayout()
        top = rect.top() + (rect.height() - y) / 2
        total = sum(l.naturalTextWidth() for l in rows) or 1
        left = fill * total  # сколько «пройдено» по всей строке, px
        for line in rows:
            w = line.naturalTextWidth()
            edge = max(0.0, min(w, left))  # точка пения в этой строчке
            left -= w
            g = QLinearGradient(rect.left(), 0, rect.left() + max(w, 1), 0)
            soft = 14 / max(w, 1)  # мягкая кромка ~14 px
            k = edge / max(w, 1)
            g.setColorAt(0, bright)
            g.setColorAt(max(0.0, k - soft), bright)
            g.setColorAt(min(1.0, k + soft), dim)
            g.setColorAt(1, dim)
            if k >= 1:
                g = QLinearGradient(0, 0, 1, 0)
                g.setColorAt(0, bright)
                g.setColorAt(1, bright)
            elif k <= 0:
                g = QLinearGradient(0, 0, 1, 0)
                g.setColorAt(0, dim)
                g.setColorAt(1, dim)
            q.setPen(QPen(QBrush(g), 0))
            line.draw(q, QPointF(rect.left(), top))

    def _dots(self, q, c, fg):
        """Пауза без слов: три точки по очереди мягко «дышат»."""
        t = time.monotonic()
        playing = bool(self.state and self.state.get("playing"))
        q.setPen(Qt.NoPen)
        for k in range(3):
            phase = (t * 2.2 - k * 0.45) % 3.0 if playing else 1.0
            pulse = max(0.0, 1 - abs(phase - 1.0))  # 0..1..0
            col = QColor(fg)
            col.setAlpha(int(90 + 165 * pulse))
            q.setBrush(col)
            rr = 4.5 + 1.8 * pulse
            q.drawEllipse(QPointF(c.x() + k * 18, c.y()), rr, rr)
