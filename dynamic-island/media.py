"""Музыка через медиа-панель Windows (как виджет «Плеер»): трек, обложка, позиция, команды.
Копия из виджетов, чтобы остров жил сам по себе. Показываем то, что играет: Spotify, YouTube Music или любой другой плеер."""
import asyncio
import ctypes
import ctypes.wintypes as wt
import threading
import time
from datetime import datetime, timezone

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainterPath, QPen

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
            await asyncio.sleep(1.0)

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


def glyph(p, name, c, color, playing):
    """Значки ⏮ ⏯ ⏭ — рисуем сами."""
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


def toggle_glyph(p, name, c, color, one):
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
