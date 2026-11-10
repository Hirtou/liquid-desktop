"""Плеер Spotify и YouTube Music: обложка, трек, исполнитель, прогресс, кнопки ⏮ ⏯ ⏭, у Spotify — сердечко «в любимые».

Через медиа-панель Windows (её используют кнопки громкости и экран блокировки): плеер сам отдаёт туда трек,
обложку и позицию и принимает команды. Ни входа в аккаунт, ни ключей. Показываем то, что сейчас играет (см. choose);
подходит и любой другой плеер, который пишет в медиа-панель. Сердечко — через Spotify Web API (spotify_api.py):
один раз войти в Spotify в браузере. У YouTube Music открытого API для лайков нет, сердечка у него нет.
"""
from lang import tr
import asyncio
import ctypes
import ctypes.wintypes as wt
import threading
import time
from datetime import datetime, timezone

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QLinearGradient, QPainter, QPainterPath, QPen

from PySide6.QtWidgets import QInputDialog, QMessageBox

from core import DesktopWidget, RADIUS, SHADOW, activity, config, grid, open_uri

GREEN = QColor("#1ed760")
YT_RED = QColor("#ff0033")
YT_MUSIC_URL = "https://music.youtube.com"
YT_MUSIC_APP = "cinhimbnkkaeohfgghhklpknlkffjgod"  # приложение YouTube Music, установленное из Chrome/Edge
BROWSERS = ("chrome", "msedge", "firefox", "opera", "brave", "vivaldi", "browser")
PLAYING = 4  # статус медиа-панели: 4 — играет, 5 — пауза


def window_titled(text):
    """Есть ли видимое окно с такой подписью. Вкладка браузера в медиа-панели — просто «Chrome»; что это YouTube Music,
    видно только по заголовку окна (пока вкладка активна)."""
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def each(hwnd, _):
        buf = ctypes.create_unicode_buffer(300)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, 300)
        if ctypes.windll.user32.IsWindowVisible(hwnd) and text in buf.value.lower():
            found.append(hwnd)
            return False
        return True
    ctypes.windll.user32.EnumWindows(each, 0)
    return bool(found)


_YT_SEEN = set()  # браузеры, в которых сейчас играет YouTube Music


def source_of(app_id):
    """Откуда музыка: 'spotify', 'ytmusic' или 'other' (любой другой плеер или обычное видео в браузере)."""
    low = app_id.lower()
    if "spotify" in low:
        return "spotify"
    if "youtube" in low or YT_MUSIC_APP in low:  # отдельные приложения YouTube Music
        return "ytmusic"
    if any(b in low for b in BROWSERS):
        # вкладку видно по заголовку окна, только пока она активна; ушли на другую вкладку — помним, что это
        # YouTube Music, пока в браузере не откроют обычный YouTube (тогда играть может уже он)
        if window_titled("youtube music"):
            _YT_SEEN.add(app_id)
        elif app_id in _YT_SEEN and window_titled("- youtube -"):
            _YT_SEEN.discard(app_id)
        if app_id in _YT_SEEN:
            return "ytmusic"
    return "other"


def choose(status, chosen, current):
    """Какой плеер показать. status — {id приложения: статус}, chosen — показанный сейчас, current — текущий по Windows.
    Играющий важнее стоящего на паузе; показанный не сменится, пока играет; если не играет никто — остаётся последний."""
    playing = [a for a, st in status.items() if st == PLAYING]
    if chosen in playing:
        return chosen
    if playing:
        rank = {"spotify": 0, "ytmusic": 1, "other": 2}
        return min(playing, key=lambda a: (rank[source_of(a)], a != current))
    if chosen in status:
        return chosen
    spotify = [a for a in status if "spotify" in a.lower()]
    return spotify[0] if spotify else current if current in status else next(iter(status), None)


def clean_artist(artist):
    """YouTube подписывает автоматические каналы «Исполнитель - Topic»."""
    return artist[:-len(" - Topic")] if artist and artist.endswith(" - Topic") else artist


def open_player(state):
    """Открыть тот плеер, что играет (двойной клик по виджету)."""
    open_uri(YT_MUSIC_URL if state and state.get("source") == "ytmusic" else "spotify:")


class Media(QObject):
    """Один фоновый поток на все плееры: раз в секунду читает медиа-панель Windows, шлёт состояние в окна."""

    changed = Signal(object)
    _instance = None

    @classmethod
    def get(cls):
        if cls._instance is None:
            cls._instance = Media()
        return cls._instance

    def __init__(self):
        super().__init__()
        self.loop = asyncio.new_event_loop()
        self.cover_key, self.cover, self.cover_tries = None, None, 0
        self.chosen = None  # id приложения, которое показываем
        self.source_key, self.source = None, "other"
        self.reported, self.forced = {}, {}  # forced: имя -> (что включили, что Windows показывала тогда)
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        asyncio.run_coroutine_threadsafe(self._poll(), self.loop)

    async def _session(self):
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Manager
        if not hasattr(self, "manager"):
            self.manager = await Manager.request_async()
        sessions = {}
        for s in self.manager.get_sessions():
            sessions.setdefault(s.source_app_user_model_id, s)
        current = self.manager.get_current_session()
        status = {app: int(s.get_playback_info().playback_status) for app, s in sessions.items()}
        self.chosen = choose(status, self.chosen, current.source_app_user_model_id if current else None)
        return sessions.get(self.chosen)

    async def _poll(self):
        while True:
            try:
                state = await self._read()
            except Exception as ex:
                state = {"error": type(ex).__name__}
            try:
                self.changed.emit(state)
            except RuntimeError:
                return
            # в игре на весь экран виджетов не видно: обращаться к плееру реже (ответ идёт через другой процесс)
            await asyncio.sleep(3.0 if activity.mode == "fullscreen" else 1.0)

    async def _read(self):
        s = await self._session()
        if s is None:
            return None
        props = await s.try_get_media_properties_async()
        t, pb = s.get_timeline_properties(), s.get_playback_info()
        playing = int(pb.playback_status) == PLAYING
        pos = t.position.total_seconds()
        duration = t.end_time.total_seconds()
        if playing and t.last_updated_time:  # плеер обновляет позицию не каждую секунду — досчитываем сами
            passed = (datetime.now(timezone.utc) - t.last_updated_time).total_seconds()
            if 0 <= passed <= duration:  # браузер может не сообщать время обновления: тогда разница бессмысленна
                pos += passed
        artist = clean_artist(props.artist)
        key = (props.title, artist)
        if key != self.cover_key:
            self.cover_key, self.cover, self.cover_tries = key, None, 0
        # обложку читаем при смене трека; браузер отдаёт её не сразу и иногда с ошибкой — ещё пара попыток, без неё трек важнее
        if self.cover is None and props.thumbnail is not None and self.cover_tries < 3:
            self.cover_tries += 1
            try:
                self.cover = await self._cover(props.thumbnail)
            except Exception:
                self.cover = None
        app = s.source_app_user_model_id.split("!")[-1].replace(".exe", "")
        if key != self.source_key or self.source != "ytmusic":  # вкладку могли переключить: песня остаётся той же
            self.source_key, self.source = key, source_of(s.source_app_user_model_id)
        c = pb.controls
        # Spotify выполняет 🔀 и 🔁, но не сообщает о них — держим то, что включили из виджета,
        # пока Windows не покажет другое значение
        self.reported = {"shuffle": bool(pb.is_shuffle_active), "repeat": int(pb.auto_repeat_mode or 0)}
        mine = {}
        for name, (value, base) in list(self.forced.items()):
            if self.reported[name] == base:
                mine[name] = value
            else:
                del self.forced[name]
        return {"title": props.title, "artist": artist, "app": app, "source": self.source, "playing": playing,
                "position": max(0.0, pos), "duration": duration, "read": time.monotonic(),
                "cover": self.cover, "key": key,
                **self.reported, **mine,  # repeat: 0 нет, 1 трек, 2 всё
                "can_shuffle": c.is_shuffle_enabled, "can_repeat": c.is_repeat_enabled,
                "can_seek": c.is_playback_position_enabled}

    @staticmethod
    async def _cover(thumb):
        if thumb is None:
            return None
        from winrt.windows.storage.streams import Buffer, InputStreamOptions
        stream = await thumb.open_read_async()
        buf = Buffer(stream.size)
        await stream.read_async(buf, stream.size, InputStreamOptions.READ_AHEAD)
        img = QImage.fromData(bytes(memoryview(buf))[:buf.length])
        return None if img.isNull() else img

    def command(self, name, value=None):
        """play / next / prev / shuffle / repeat / seek — из окна; выполняется в фоновом потоке."""
        async def run():
            s = await self._session()
            if not s:
                return
            if name in ("shuffle", "repeat"):
                self.forced[name] = (value, self.reported.get(name))
            if name == "shuffle":
                await s.try_change_shuffle_active_async(bool(value))
            elif name == "repeat":
                from winrt.windows.media import MediaPlaybackAutoRepeatMode
                await s.try_change_auto_repeat_mode_async(MediaPlaybackAutoRepeatMode(value))
            elif name == "seek":  # value — секунды; Windows ждёт тики по 100 нс
                await s.try_change_playback_position_async(int(value * 10_000_000))
            else:
                await {"play": s.try_toggle_play_pause_async, "next": s.try_skip_next_async,
                       "prev": s.try_skip_previous_async}[name]()
        asyncio.run_coroutine_threadsafe(run(), self.loop)


def mmss(sec):
    sec = max(0, int(sec))
    return f"{sec // 60}:{sec % 60:02d}"


def accent(img):
    """Главный цвет обложки — для мягкой подсветки карточки, как у плееров на телефоне."""
    small = img.scaled(8, 8, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    r = g = b = n = 0
    for y in range(8):
        for x in range(8):
            c = small.pixelColor(x, y)
            w = max(c.saturation(), 30)  # яркие пиксели важнее серых
            r, g, b, n = r + c.red() * w, g + c.green() * w, b + c.blue() * w, n + w
    return QColor(int(r / n), int(g / n), int(b / n))


class PlayerWidget(DesktopWidget):
    key = "player"
    title = tr("Плеер")
    description = tr("Spotify и YouTube Music: обложка, трек, кнопки")
    liked_ready = Signal(object, object, object)  # (песня, id трека, в любимых?) — из фонового потока
    login_done = Signal(object)                   # None — вошли, иначе текст ошибки
    save_cfg = Signal()                           # записать настройки — в главном потоке

    def __init__(self, **kw):
        super().__init__(**kw)
        self.setFixedSize(*(v + 2 * SHADOW for v in grid(2, 1)))
        self.state = None
        self.cover_key = None
        self.cover = None
        self.source = None
        self.color = None
        self.buttons = {}
        Media.get().changed.connect(self.on_state)
        self.tick = QTimer(self, interval=1000, timeout=self.on_tick)  # бегунок прогресса
        self.tick.start()
        self.shown = None  # что нарисовано — на паузе и без музыки перерисовывать нечего
        self.like = {"key": None, "id": None, "liked": None}  # сердечко: для какой песни, id в Spotify, в любимых?
        self.api = None
        self.liked_ready.connect(self.on_liked)
        self.login_done.connect(self.on_login)
        self.save_cfg.connect(config.save)

    def on_tick(self):
        if self.state and self.state.get("playing") and not activity.paused(self):
            self.update()

    def on_state(self, state):
        self.state = state
        if state and "key" in state:
            new_song = state["key"] != self.cover_key
            if new_song or state["cover"] is not self.cover:  # обложка у браузера приходит позже трека
                img = state["cover"]
                self.cover = img
                self.color = accent(img) if img is not None else None
                self.update()
            if new_song or state.get("source") != self.source:
                self.cover_key, self.source = state["key"], state.get("source")
                self.like = {"key": state["key"], "id": None, "liked": None}
                if self.source == "spotify":  # лайки есть только у Spotify
                    self.check_like()
                self.update()
        # опрос приходит раз в секунду; играет — бегунок и так перерисует on_tick
        sig = None if not state else tuple(state.get(k) for k in ("key", "playing", "shuffle", "repeat", "error",
                                                                   "can_shuffle", "can_repeat", "can_seek")) \
            + (int(state.get("position", 0)), int(state.get("duration", 0)))
        if sig != self.shown and not (state and state.get("playing") and sig[:-2] == (self.shown or ())[:-2]):
            self.update()
        self.shown = sig

    # ---------- мышь ----------

    def click(self, pos):
        for name, rect in self.buttons.items():
            if rect.contains(pos):
                if name == "open":
                    open_uri("spotify:")
                elif name == "open_yt":
                    open_uri(YT_MUSIC_URL)
                elif name == "like":
                    self.toggle_like()
                elif name == "seek":  # клик по полоске — перемотка туда
                    sec = (pos.x() - rect.left()) / rect.width() * self.state["duration"]
                    Media.get().command("seek", sec)
                    self.state = {**self.state, "position": sec, "read": time.monotonic()}
                    self.update()
                elif name in ("shuffle", "repeat"):  # сразу показать новое состояние, не ждать опроса
                    value = (not self.state["shuffle"]) if name == "shuffle" else {0: 2, 2: 1, 1: 0}[self.state["repeat"]]
                    Media.get().command(name, value)
                    self.state = {**self.state, name: value}
                    self.update()
                else:
                    Media.get().command(name)
                    if name == "play" and self.state:  # сразу перерисовать кнопку, не ждать опроса
                        self.state = {**self.state, "playing": not self.state["playing"],
                                      "position": self.position(), "read": time.monotonic()}
                        self.update()
                return True
        return False

    def double_click(self):
        open_player(self.state)

    # ---------- любимые (Spotify Web API) ----------

    def spotify(self):
        if self.api is None:
            from spotify_api import Spotify
            self.api = Spotify(config.section("spotify"), self.save_cfg.emit)
        return self.api

    def check_like(self):
        """В любимых ли то, что играет (в фоне: что играет — у Spotify, потом — есть ли в «Любимых»)."""
        api = self.spotify()
        key = self.like["key"]
        if not api.logged_in() or key is None:
            return

        def work():
            try:
                cur = api.current()
                title = (key[0] or "").casefold()
                if cur and (cur[1].casefold() == title or cur[1].casefold().startswith(title[:12])):
                    self.liked_ready.emit(key, cur[0], api.liked(cur[0]))
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()

    def on_liked(self, key, track_id, liked):
        if key == self.like["key"]:
            self.like.update(id=track_id, liked=liked)
            self.update()

    def toggle_like(self):
        api = self.spotify()
        if not api.configured():
            self.setup_spotify()
            return
        if not api.logged_in():
            self.start_login()
            return
        if self.like["id"] is None:  # ещё не узнали id трека — спросить (сердечко станет точным) и нажать ещё раз
            self.check_like()
            return
        on = not self.like["liked"]
        self.like["liked"] = on  # сразу показать, не ждать ответа
        self.update()
        key, track_id = self.like["key"], self.like["id"]

        def work():
            try:
                api.set_liked(track_id, on)
            except Exception:
                self.liked_ready.emit(key, track_id, not on)  # не вышло — вернуть как было
        threading.Thread(target=work, daemon=True).start()

    def setup_spotify(self):
        """Один раз: Client ID своего приложения Spotify (бесплатно), потом — вход в браузере."""
        from spotify_api import REDIRECT
        text, ok = QInputDialog.getText(
            None, tr("Spotify — любимые треки"),
            tr("Чтобы ставить лайки, нужен вход в Spotify (один раз, в браузере).\n\n"
            "1. Открой developer.spotify.com/dashboard и войди своим аккаунтом Spotify.\n"
            "2. Create app: имя любое, Redirect URI:  ") + REDIRECT + tr(",  API: Web API.\n"
            "3. Скопируй Client ID приложения и вставь сюда:"),
            text=config.section("spotify").get("client_id", ""))
        if ok and text.strip():
            config.section("spotify")["client_id"] = text.strip()
            config.save()
            self.start_login()

    def start_login(self):
        api = self.spotify()

        def work():
            try:
                api.login()
                self.login_done.emit(None)
            except Exception as e:
                self.login_done.emit(str(e))
        threading.Thread(target=work, daemon=True).start()

    def on_login(self, error):
        if error:
            QMessageBox.warning(None, "Spotify", tr("Войти не получилось: {}").format(error))
            return
        self.check_like()

    def logout(self):
        self.spotify().logout()
        self.like.update(id=None, liked=None)
        self.update()

    def add_actions(self, menu):
        if self.spotify().logged_in():
            menu.addAction(tr("Spotify: выйти (сердечко)"), self.logout)
        else:
            menu.addAction(tr("Spotify: войти (для сердечка)"), self.toggle_like)

    def position(self):
        s = self.state
        pos = s["position"] + (time.monotonic() - s["read"] if s["playing"] else 0)
        return min(pos, s["duration"]) if s["duration"] else pos

    # ---------- рисование ----------

    def paintEvent(self, event):
        super().paintEvent(event)  # стекло
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        r = QRectF(self.card())
        dark = bool(self.dark)
        fg = QColor("#ededf0") if dark else QColor("#151517")
        dim = QColor(fg)
        dim.setAlpha(140)
        s = self.state
        self.buttons = {}

        if not s or "key" not in s:  # ничего не играет
            f = QFont("Segoe UI Semibold")
            f.setPixelSize(15)
            p.setFont(f)
            p.setPen(fg)
            p.drawText(r.adjusted(0, 0, 0, -40), Qt.AlignCenter, tr("Сейчас ничего не играет"))
            f.setPixelSize(13)
            p.setFont(f)
            for name, text, x0, w0, bg, ink in (("open", "Spotify", r.center().x() - 138, 112, GREEN, QColor("#0b2615")),
                                                ("open_yt", "YouTube Music", r.center().x() - 18, 156, YT_RED, QColor("white"))):
                btn = QRectF(x0, r.bottom() - 52, w0, 32)
                self.buttons[name] = btn
                p.setPen(Qt.NoPen)
                p.setBrush(bg)
                p.drawRoundedRect(btn, 16, 16)
                p.setPen(ink)
                p.drawText(btn, Qt.AlignCenter, text)
            return

        # мягкая подсветка цветом обложки
        if self.color is not None:
            clip = QPainterPath()
            clip.addRoundedRect(r, RADIUS, RADIUS)
            p.setClipPath(clip)
            glow = QLinearGradient(r.topLeft(), r.topRight())
            c1, c2 = QColor(self.color), QColor(self.color)
            c1.setAlpha(110 if dark else 80)
            c2.setAlpha(0)
            glow.setColorAt(0, c1)
            glow.setColorAt(0.75, c2)
            p.fillRect(r, glow)
            p.setClipping(False)

        # обложка
        side = r.height() - 32
        cover = QRectF(r.left() + 16, r.top() + 16, side, side)
        path = QPainterPath()
        path.addRoundedRect(cover, 14, 14)
        if self.cover is not None:
            p.save()
            p.setClipPath(path)
            img = self.cover
            crop = min(img.width(), img.height())
            p.drawImage(cover, img, QRectF((img.width() - crop) / 2, (img.height() - crop) / 2, crop, crop))
            p.restore()
            p.setPen(QPen(QColor(255, 255, 255, 60), 1))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(128, 128, 140, 70))
            p.drawPath(path)

        # текст: трек, исполнитель, откуда
        x = cover.right() + 16
        w = r.right() - 16 - x
        title = QFont("Segoe UI Semibold")
        title.setPixelSize(15)
        small = QFont("Segoe UI")
        small.setPixelSize(12)
        # сердечко «в любимые» справа от названия — только у Spotify
        title_w = w
        if s.get("source") == "spotify":
            heart = QRectF(x + w - 24, r.top() + 13, 24, 24)
            self.buttons["like"] = heart
            draw_heart(p, heart.center(), self.like["liked"], fg, dim)
            title_w = w - 30
        p.setFont(title)
        p.setPen(fg)
        p.drawText(QRectF(x, r.top() + 14, title_w, 22), Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetricsF(title).elidedText(s["title"] or "—", Qt.ElideRight, title_w))
        p.setFont(small)
        p.setPen(dim)
        p.drawText(QRectF(x, r.top() + 36, w, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetricsF(small).elidedText(s["artist"] or "", Qt.ElideRight, w))

        # прогресс
        pos, dur = self.position(), s["duration"]
        bar = QRectF(x, r.top() + 66, w, 4)
        track = QColor(fg)
        track.setAlpha(45)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(bar, 2, 2)
        if dur and s.get("can_seek"):
            self.buttons["seek"] = bar.adjusted(-4, -8, 4, 8)  # по тонкой полоске легко промахнуться
        if dur:
            done = QRectF(bar.left(), bar.top(), bar.width() * min(1, pos / dur), bar.height())
            p.setBrush(fg)
            p.drawRoundedRect(done, 2, 2)
            p.drawEllipse(QPointF(done.right(), bar.center().y()), 5, 5)
        tiny = QFont("Segoe UI")
        tiny.setPixelSize(10)
        p.setFont(tiny)
        p.setPen(dim)
        p.drawText(QRectF(x, bar.bottom() + 4, 60, 14), Qt.AlignLeft | Qt.AlignVCenter, mmss(pos))
        p.drawText(QRectF(bar.right() - 60, bar.bottom() + 4, 60, 14), Qt.AlignRight | Qt.AlignVCenter, mmss(dur))

        # кнопки 🔀 ⏮ ⏯ ⏭ 🔁 — рисуем сами
        cy = r.bottom() - 26
        cx = x + w / 2
        for name, dx, rad in (("shuffle", -70, 11), ("prev", -38, 14), ("play", 0, 19), ("next", 38, 14),
                              ("repeat", 70, 11)):
            if name in ("shuffle", "repeat") and not s.get("can_" + name):
                continue
            rect = QRectF(cx + dx - rad, cy - rad, 2 * rad, 2 * rad)
            self.buttons[name] = rect
            if name == "play":
                p.setPen(Qt.NoPen)
                p.setBrush(fg)
                p.drawEllipse(rect)
                self._glyph(p, name, rect.center(), QColor("#151517") if dark else QColor("white"), s["playing"])
            elif name in ("shuffle", "repeat"):
                on = s["shuffle"] if name == "shuffle" else s["repeat"]
                self._toggle(p, name, rect.center(), GREEN if on else dim, s["repeat"] == 1)
                if on:  # точка под включённой кнопкой, как в Spotify
                    p.setPen(Qt.NoPen)
                    p.setBrush(GREEN)
                    p.drawEllipse(QPointF(rect.center().x(), rect.bottom() + 2), 1.6, 1.6)
            else:
                self._glyph(p, name, rect.center(), fg, s["playing"])

    @staticmethod
    def _toggle(p, name, c, color, one):
        """🔀 — две скрещённые стрелки, 🔁 — петля со стрелкой (с «1» — повтор трека)."""
        pen = QPen(color, 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        x, y = c.x(), c.y()
        if name == "shuffle":
            for y0, y1 in ((-4, 4), (4, -4)):
                path = QPainterPath(QPointF(x - 7, y + y0))
                path.cubicTo(QPointF(x - 1, y + y0), QPointF(x + 1, y + y1), QPointF(x + 6, y + y1))
                p.drawPath(path)
                p.drawPolyline([QPointF(x + 3.5, y + y1 - 2.5), QPointF(x + 6.5, y + y1), QPointF(x + 3.5, y + y1 + 2.5)])
            return
        path = QPainterPath()
        path.addRoundedRect(QRectF(x - 7, y - 5, 14, 10), 3.5, 3.5)
        p.drawPath(path)
        p.drawPolyline([QPointF(x + 0.5, y - 7.5), QPointF(x + 3, y - 5), QPointF(x + 0.5, y - 2.5)])
        if one:
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            p.drawEllipse(QPointF(x, y + 0.5), 3.6, 3.6)
            f = QFont("Segoe UI Semibold")
            f.setPixelSize(7)
            p.setFont(f)
            p.setPen(QColor("#0b2615"))
            p.drawText(QRectF(x - 4, y - 3.5, 8, 8), Qt.AlignCenter, "1")

    @staticmethod
    def _glyph(p, name, c, color, playing):
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        if name == "play" and playing:  # пауза
            p.drawRoundedRect(QRectF(c.x() - 6, c.y() - 7, 4.5, 14), 1.5, 1.5)
            p.drawRoundedRect(QRectF(c.x() + 1.5, c.y() - 7, 4.5, 14), 1.5, 1.5)
        elif name == "play":
            p.drawPolygon([QPointF(c.x() - 4, c.y() - 8), QPointF(c.x() + 8, c.y()), QPointF(c.x() - 4, c.y() + 8)])
        else:  # ⏮ / ⏭: треугольник и палочка
            d = 1 if name == "next" else -1
            p.drawPolygon([QPointF(c.x() - 6 * d, c.y() - 7), QPointF(c.x() + 4 * d, c.y()),
                           QPointF(c.x() - 6 * d, c.y() + 7)])
            p.drawRoundedRect(QRectF(c.x() + 4 * d - (0 if d > 0 else 3), c.y() - 7, 3, 14), 1, 1)


def draw_heart(p, c, liked, fg, dim):
    """Сердечко: в любимых — залито зелёным; нет — контур; неизвестно (не вошли) — бледный контур."""
    path = QPainterPath(QPointF(c.x(), c.y() + 7))
    path.cubicTo(QPointF(c.x() - 11, c.y() - 1), QPointF(c.x() - 7, c.y() - 10), QPointF(c.x(), c.y() - 4.5))
    path.cubicTo(QPointF(c.x() + 7, c.y() - 10), QPointF(c.x() + 11, c.y() - 1), QPointF(c.x(), c.y() + 7))
    if liked:
        p.setPen(Qt.NoPen)
        p.setBrush(GREEN)
    else:
        p.setPen(QPen(fg if liked is not None else dim, 1.7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
    p.drawPath(path)
