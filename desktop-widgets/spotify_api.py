"""Spotify Web API для сердечка «в любимые» в плеере.

Медиа-панель Windows лайков не знает, поэтому — официальный API Spotify. Вход один раз и только в браузере,
на сайте Spotify (OAuth PKCE): пароль видит только Spotify, виджет получает разрешение работать с «Любимыми
треками» и видеть, что играет. Для входа нужно своё приложение Spotify (бесплатно, developer.spotify.com):
его Client ID и адрес возврата REDIRECT. Ключи (refresh token) — в config.json виджетов, раздел «spotify».

Сеть — только в фоновых потоках (здесь нет ничего, что трогает окна Qt).
"""
from lang import tr
import base64
import hashlib
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 8765
REDIRECT = f"http://127.0.0.1:{PORT}/callback"
SCOPES = "user-library-read user-library-modify user-read-currently-playing"
ACCOUNTS = "https://accounts.spotify.com"
API = "https://api.spotify.com/v1"


class SpotifyError(Exception):
    pass


class Spotify:
    def __init__(self, section, save):
        """section — словарь настроек (config.section("spotify")), save() — записать настройки на диск."""
        self.cfg, self.save = section, save
        self.lock = threading.Lock()

    def configured(self):
        return bool(self.cfg.get("client_id"))

    def logged_in(self):
        return bool(self.cfg.get("refresh_token"))

    def logout(self):
        for k in ("refresh_token", "access_token", "expires"):
            self.cfg.pop(k, None)
        self.save()

    # ---------- вход (один раз) ----------

    def login(self, timeout=180):
        """Открыть страницу входа Spotify в браузере, дождаться разрешения и получить ключи. Долго — звать в фоне."""
        verifier = secrets.token_urlsafe(64)[:96]
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(16)
        got = {}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                if q.get("state", [""])[0] == state:
                    got["code"] = q.get("code", [None])[0]
                    got["error"] = q.get("error", [None])[0]
                ok = bool(got.get("code"))
                body = (tr("<h2>Готово — можно закрыть вкладку.</h2>") if ok else
                        tr("<h2>Вход не удался — попробуй ещё раз из виджета.</h2>")).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"<meta charset='utf-8'><body style='font-family:Segoe UI;background:#121318;"
                                 b"color:#eee;text-align:center;padding-top:80px'>" + body)

            def log_message(self, *a):
                pass

        server = HTTPServer(("127.0.0.1", PORT), Handler)
        server.timeout = 1
        url = ACCOUNTS + "/authorize?" + urllib.parse.urlencode({
            "client_id": self.cfg["client_id"], "response_type": "code", "redirect_uri": REDIRECT,
            "code_challenge_method": "S256", "code_challenge": challenge, "scope": SCOPES, "state": state})
        webbrowser.open(url)
        end = time.time() + timeout
        try:
            while time.time() < end and "code" not in got and not got.get("error"):
                server.handle_request()
        finally:
            server.server_close()
        if not got.get("code"):
            raise SpotifyError(got.get("error") or tr("вход не завершён"))
        tok = self._token_request({"grant_type": "authorization_code", "code": got["code"],
                                   "redirect_uri": REDIRECT, "client_id": self.cfg["client_id"],
                                   "code_verifier": verifier})
        self._store(tok)

    def _token_request(self, data):
        req = urllib.request.Request(ACCOUNTS + "/api/token", data=urllib.parse.urlencode(data).encode(),
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            raise SpotifyError(tr("Spotify не дал ключ ({})").format(e.code))
        except (urllib.error.URLError, OSError) as e:
            raise SpotifyError(tr("нет связи со Spotify ({})").format(e))

    def _store(self, tok):
        self.cfg["access_token"] = tok["access_token"]
        self.cfg["expires"] = time.time() + int(tok.get("expires_in", 3600)) - 60
        if tok.get("refresh_token"):
            self.cfg["refresh_token"] = tok["refresh_token"]
        self.save()

    def token(self):
        with self.lock:
            if not self.logged_in():
                raise SpotifyError(tr("не выполнен вход"))
            if self.cfg.get("access_token") and time.time() < self.cfg.get("expires", 0):
                return self.cfg["access_token"]
            tok = self._token_request({"grant_type": "refresh_token", "refresh_token": self.cfg["refresh_token"],
                                       "client_id": self.cfg["client_id"]})
            self._store(tok)
            return tok["access_token"]

    # ---------- запросы ----------

    def call(self, method, path, retry=True):
        req = urllib.request.Request(API + path, method=method, headers={"Authorization": "Bearer " + self.token()})
        if method in ("PUT", "DELETE"):
            req.data = b""
            req.add_header("Content-Length", "0")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                raw = r.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            if e.code == 401 and retry:  # ключ устарел раньше срока — обновить и повторить
                self.cfg["expires"] = 0
                return self.call(method, path, retry=False)
            raise SpotifyError(tr("Spotify ответил {}").format(e.code))
        except (urllib.error.URLError, OSError) as e:
            raise SpotifyError(tr("нет связи со Spotify ({})").format(e))

    def current(self):
        """Что играет: (id, название, исполнители) или None."""
        d = self.call("GET", "/me/player/currently-playing")
        item = (d or {}).get("item")
        if not item or item.get("type") != "track":
            return None
        return item["id"], item.get("name", ""), ", ".join(a.get("name", "") for a in item.get("artists", []))

    def liked(self, track_id):
        return bool((self.call("GET", "/me/tracks/contains?ids=" + track_id) or [False])[0])

    def set_liked(self, track_id, on):
        self.call("PUT" if on else "DELETE", "/me/tracks?ids=" + track_id)
