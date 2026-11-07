"""Погода с open-meteo.com (бесплатно, без ключа): сейчас, по часам на 12 часов, на 3 дня и подробности —
ощущается, давление, ветер с порывами, осадки, УФ, восход и закат."""
from lang import LANG, tr
import json
import math
import ssl
import time
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QVBoxLayout,
                               QWidget)

import icons
from core import DesktopWidget, activity, config, open_uri

# код погоды WMO -> описание (значки рисуются сами — icons.weather_kind)
CODES = {
    0: tr("ясно"), 1: tr("почти ясно"), 2: tr("переменная облачность"), 3: tr("пасмурно"), 45: tr("туман"), 48: tr("изморозь"),
    51: tr("морось"), 53: tr("морось"), 55: tr("сильная морось"), 56: tr("ледяная морось"), 57: tr("ледяная морось"),
    61: tr("небольшой дождь"), 63: tr("дождь"), 65: tr("ливень"), 66: tr("ледяной дождь"), 67: tr("ледяной дождь"),
    71: tr("небольшой снег"), 73: tr("снег"), 75: tr("сильный снег"), 77: tr("снежная крупа"),
    80: tr("ливень"), 81: tr("ливень"), 82: tr("сильный ливень"), 85: tr("снегопад"), 86: tr("сильный снегопад"),
    95: tr("гроза"), 96: tr("гроза с градом"), 99: tr("гроза с градом"),
}
DAYS = [tr("пн"), tr("вт"), tr("ср"), tr("чт"), tr("пт"), tr("сб"), tr("вс")]
WIND = [tr("С"), tr("СВ"), tr("В"), tr("ЮВ"), tr("Ю"), tr("ЮЗ"), tr("З"), tr("СЗ")]  # откуда дует


def valid_key(key):
    """Похоже ли на ключ API: одна строка без пробелов (а не, скажем, вставленный пример кода)."""
    return bool(key) and len(key) < 100 and not any(c.isspace() for c in key)


def get_json(url, **params):
    url += "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.load(r)
    except urllib.error.URLError as ex:
        if not isinstance(ex.reason, ssl.SSLError):
            raise
    # у сервера бывает просроченный сертификат — тогда по http
    with urllib.request.urlopen(url.replace("https://", "http://", 1), timeout=10) as r:
        return json.load(r)


def _metar_now(m):
    """Сводка METAR -> (код погоды WMO для значка, описание по-русски)."""
    wx = (m.get("wxString") or "").upper()
    for key, code, text in (("TS", 95, tr("гроза")), ("SN", 73, tr("снег")), ("SG", 73, tr("снег")), ("GR", 96, tr("град")),
                            ("FZRA", 66, tr("ледяной дождь")), ("SHRA", 80, tr("ливень")), ("RA", 63, tr("дождь")),
                            ("DZ", 53, tr("морось")), ("FG", 45, tr("туман"))):
        if key in wx:
            return code, text
    haze = [t for k, t in (("BR", tr("дымка")), ("FU", tr("смог")), ("HZ", tr("мгла")), ("DU", tr("пыль"))) if k in wx]
    if haze:
        return 45, ", ".join(haze)
    cover = (m.get("cover") or "").upper()
    if cover in ("OVC", "BKN"):
        return 3, tr("облачно") if cover == "BKN" else tr("пасмурно")
    if cover == "SCT":
        return 2, tr("переменная облачность")
    if cover == "FEW":
        return 1, tr("почти ясно")
    return 0, tr("ясно")


def fetch_station(lat, lon):
    """Реальные измерения ближайшей метеостанции — сводки METAR аэропортов (NOAA, без ключа).
    Модель (Open-Meteo) в горах ошибается на градусы; станция — то, что на самом деле. None — рядом нет или старая."""
    try:
        reports = get_json("https://aviationweather.gov/api/data/metar", format="json", hours=3,
                           bbox=f"{lat - 0.8:.2f},{lon - 1.1:.2f},{lat + 0.8:.2f},{lon + 1.1:.2f}")
    except Exception:
        return None
    now = time.time()
    best = None
    for m in reports or []:
        if m.get("temp") is None or now - m.get("obsTime", 0) > 2.5 * 3600:
            continue
        km = math.hypot((m["lat"] - lat) * 111, (m["lon"] - lon) * 111 * math.cos(math.radians(lat)))
        if km <= 80 and (best is None or (km, -m["obsTime"]) < (best[0], -best[1]["obsTime"])):
            best = (km, m)
    if not best:
        return None
    km, m = best
    code, text = _metar_now(m)
    t, d = m["temp"], m.get("dewp")
    humidity = round(100 * math.exp(17.625 * d / (243.04 + d)) / math.exp(17.625 * t / (243.04 + t))) \
        if d is not None else None
    name = m.get("name", m["icaoId"]).split(",")[0].replace(" Intl", "")
    return {"temp": t, "code": code, "text": text, "humidity": humidity,
            "wind": (m.get("wspd") or 0) * 0.514,  # узлы -> м/с
            "visibility": m["visib"] * 1.609 if isinstance(m.get("visib"), (int, float)) else None,
            "station": tr("аэропорт ") + name.replace("Almaty", tr("Алматы")) if "Intl" in m.get("name", "") else name,
            "minutes": int((now - m["obsTime"]) // 60), "km": round(km),
            "lat": m["lat"], "lon": m["lon"], "elev": m.get("elev", 0)}


def now_values(data):
    """Погода «сейчас» в твоём месте.
    Станция в самом месте (до 5 км) — берём её как есть. Станция дальше — считаем модель для твоих координат
    и поправляем на ту ошибку, которую модель прямо сейчас делает на станции (там настоящий термометр);
    явления (дымка, облака, осадки) — со станции: на десятки км они общие. Станции нет — просто модель."""
    cur, st = data["current"], data.get("station")
    model = {"temp": cur["temperature_2m"], "code": cur["weather_code"], "text": CODES.get(cur["weather_code"], ""),
             "wind": cur["wind_speed_10m"], "humidity": cur["relative_humidity_2m"], "visibility": None,
             "is_day": cur.get("is_day", 1), "source": data.get("note", "") + tr("модель Open-Meteo")}
    if "yandex" in data:
        return {**model, "text": data["yandex"]["text"], "source": tr("Яндекс Погода")}
    if not st:
        return model
    if st["km"] <= 5:
        return {**model, "temp": st["temp"], "code": st["code"], "text": st["text"], "wind": st["wind"],
                "humidity": st["humidity"], "visibility": st["visibility"],
                "source": tr("метеостанция {}, {} мин назад").format(st['station'], st['minutes'])}
    bias = st.get("bias", 0.0)
    return {**model, "temp": cur["temperature_2m"] + bias, "code": st["code"], "text": st["text"],
            "visibility": st["visibility"],
            "source": data.get("note", "") + tr("модель, поправка {:+.0f}° по станции {} ({} км, {} мин назад)").format(bias, st['station'], st['km'], st['minutes'])}


# Яндекс: состояние -> (код WMO для нашего значка, описание)
YANDEX = {
    "clear": (0, tr("ясно")), "partly-cloudy": (2, tr("малооблачно")), "cloudy": (3, tr("облачно с прояснениями")),
    "overcast": (3, tr("пасмурно")), "drizzle": (53, tr("морось")), "light-rain": (61, tr("небольшой дождь")),
    "rain": (63, tr("дождь")), "moderate-rain": (63, tr("дождь")), "heavy-rain": (65, tr("сильный дождь")),
    "continuous-heavy-rain": (65, tr("ливень")), "showers": (81, tr("ливень")), "wet-snow": (66, tr("дождь со снегом")),
    "light-snow": (71, tr("небольшой снег")), "snow": (73, tr("снег")), "snow-showers": (75, tr("снегопад")),
    "hail": (96, tr("град")), "thunderstorm": (95, tr("гроза")), "thunderstorm-with-rain": (95, tr("дождь с грозой")),
    "thunderstorm-with-hail": (96, tr("гроза с градом")),
}


def fetch_yandex(lat, lon, key):
    """Яндекс Погода по твоему ключу (API v2). -> данные в нашем виде или исключение."""
    url = "https://api.weather.yandex.ru/v2/forecast?" + urllib.parse.urlencode(
        {"lat": lat, "lon": lon, "lang": "en_US" if LANG == "en" else "ru_RU", "limit": 4, "hours": "false"})
    req = urllib.request.Request(url, headers={"X-Yandex-Weather-Key": key, "X-Yandex-API-Key": key})
    with urllib.request.urlopen(req, timeout=10) as r:
        y = json.load(r)
    fact = y["fact"]
    code, text = YANDEX.get(fact.get("condition"), (3, fact.get("condition", "")))
    days = y.get("forecasts", [])
    daily = {"time": [], "weather_code": [], "temperature_2m_max": [], "temperature_2m_min": []}
    for f in days:
        part = f["parts"]["day"]
        daily["time"].append(f["date"])
        daily["weather_code"].append(YANDEX.get(part.get("condition"), (3, ""))[0])
        daily["temperature_2m_max"].append(part.get("temp_max", part.get("temp_avg", 0)))
        daily["temperature_2m_min"].append(f["parts"].get("night", part).get("temp_min", part.get("temp_min", 0)))
    return {"current": {"temperature_2m": fact["temp"], "weather_code": code, "wind_speed_10m": fact.get("wind_speed", 0),
                        "relative_humidity_2m": fact.get("humidity"), "is_day": int(fact.get("daytime", "d") == "d")},
            "daily": daily, "yandex": {"text": text, "feels": fact.get("feels_like")}}


def find_places(query):
    """Места с таким названием — с областью, чтобы выбрать своё (одинаковых названий бывает много)."""
    found = get_json("https://geocoding-api.open-meteo.com/v1/search", name=query, count=10,
                     language=LANG).get("results") or []
    out = []
    for f in found:
        region = ", ".join(x for x in (f.get("admin1"), f.get("admin2"), f.get("country")) if x)
        out.append({"city": f["name"], "lat": f["latitude"], "lon": f["longitude"], "region": region})
    return out


def set_place(p):
    """Запомнить место для всех погодных виджетов (Погода, Метеочасы, Солнце)."""
    w = config.section("weather")
    w.update({"city": p["city"], "lat": p["lat"], "lon": p["lon"]})
    config.save()


def fetch(place):
    """Погода для места (в фоновом потоке). place — настройки «Погоды»: точные lat/lon, если место выбрано
    из списка, иначе только city (ищем по названию). -> данные или {"error": ...}."""
    try:
        if "lat" in place:
            name, lat, lon = place.get("city", ""), place["lat"], place["lon"]
        else:
            found = find_places(place.get("city", tr("Москва")))
            if not found:
                return {"error": tr("город не найден")}
            name, lat, lon = found[0]["city"], found[0]["lat"], found[0]["lon"]
        key = config.section("weather").get("yandex_key")
        if valid_key(key):  # есть ключ Яндекса — берём всё у него
            try:
                data = fetch_yandex(lat, lon, key)
                data["name"] = name
                return data
            except Exception as ex:
                yandex_error = tr("Яндекс не ответил ({}) — ").format(getattr(ex, 'code', type(ex).__name__))
        else:
            yandex_error = ""
        data = get_json("https://api.open-meteo.com/v1/forecast", latitude=lat, longitude=lon,
                        current="temperature_2m,weather_code,wind_speed_10m,relative_humidity_2m,is_day,"
                                "apparent_temperature,pressure_msl,wind_direction_10m,wind_gusts_10m",
                        hourly="temperature_2m,weather_code,precipitation_probability,is_day",
                        daily="weather_code,temperature_2m_max,temperature_2m_min,sunrise,sunset,uv_index_max,"
                              "precipitation_probability_max",
                        wind_speed_unit="ms", timezone="auto", forecast_days=4)
        data["name"] = name
        data["note"] = yandex_error
        st = fetch_station(lat, lon)
        if st and st["km"] > 5:
            # сколько модель ошибается на станции прямо сейчас — на столько поправим и у тебя
            at = get_json("https://api.open-meteo.com/v1/forecast", latitude=st["lat"], longitude=st["lon"],
                          elevation=st["elev"], current="temperature_2m")
            st["bias"] = st["temp"] - at["current"]["temperature_2m"]
        data["station"] = st
        return data
    except Exception as ex:  # нет сети и т.п.
        return {"error": tr("нет связи ({})").format(type(ex).__name__)}


class WeatherWidget(DesktopWidget):
    key = "weather"
    title = tr("Погода")
    description = tr("Сейчас и на 3 дня (нужен интернет)")
    loaded = Signal(object)

    def __init__(self, **kw):
        super().__init__(**kw)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 12, 18, 14)
        self.city = QLabel()
        self.city.setStyleSheet("font-size: 16px; font-weight: 600;")
        lay.addWidget(self.city)
        now = QHBoxLayout()
        self.icon = QLabel()
        self.icon.setFixedSize(46, 46)
        self.temp = QLabel()
        self.temp.setStyleSheet("font-size: 36px; font-weight: 300;")
        now.addWidget(self.icon)
        now.addWidget(self.temp)
        now.addStretch()
        # справа от температуры: что за погода и солнце (раньше — отдельной строкой ниже)
        side = QVBoxLayout()
        side.setSpacing(0)
        self.info = QLabel(tr("загрузка…"), alignment=Qt.AlignRight)
        self.info.setStyleSheet("font-size: 13px; font-weight: 600;")
        self.sun = QLabel(objectName="dim", alignment=Qt.AlignRight)
        self.sun.setStyleSheet("font-size: 11px;")
        side.addStretch()
        side.addWidget(self.info)
        side.addWidget(self.sun)
        side.addStretch()
        now.addLayout(side)
        lay.addLayout(now)
        # подробности: две строки по три (подпись мелко, значение крупнее)
        self.stats = QGridLayout()
        self.stats.setContentsMargins(0, 2, 0, 0)
        self.stats.setHorizontalSpacing(10)
        self.stats.setVerticalSpacing(4)
        lay.addLayout(self.stats)
        # по часам на ближайшие 12 часов (каждые 2 часа)
        self.hours = QHBoxLayout()
        self.hours.setContentsMargins(0, 6, 0, 0)
        lay.addLayout(self.hours)
        self.days = QHBoxLayout()
        lay.addLayout(self.days)
        self.source = QLabel(objectName="dim")  # откуда «сейчас»: Яндекс, станция или модель (одна строка)
        self.source.setStyleSheet("font-size: 10px;")
        lay.addWidget(self.source)
        # лишняя высота до целых ячеек — между «сейчас» и прогнозом: прогноз и подпись прижаты к низу
        lay.insertStretch(lay.indexOf(self.source) - 1)
        self.fit_grid(2)  # 2 ячейки в ширину, высота — целыми ячейками

        if not valid_key(config.section("weather").get("yandex_key")) and config.section("weather").get("yandex_key"):
            config.section("weather").pop("yandex_key")  # вместо ключа был вставлен текст — убрать, мешает
            config.save()
        self.loaded.connect(self.show_data)
        # станции присылают сводку раз в 30 мин — смотрим каждые 15, чтобы не отставать
        self.timer = QTimer(self, interval=15 * 60 * 1000, timeout=self.refresh)
        self.timer.start()
        self.refresh()

    def double_click(self):
        city = urllib.parse.quote(self.cfg.get("city", tr("Москва")))
        open_uri(f"https://www.google.com/search?q=%D0%BF%D0%BE%D0%B3%D0%BE%D0%B4%D0%B0+{city}")  # «погода город»

    def ask_yandex(self):
        """Свой ключ Яндекс Погоды: вставляешь сам; пусто — снова станция + модель."""
        key, ok = QInputDialog.getText(
            None, tr("Яндекс Погода"),
            tr("Ключ API Яндекс Погоды (берётся в кабинете разработчика:\n"
            "yandex.ru/pogoda/b2b/console). Пусто — без Яндекса."),
            QLineEdit.Password, config.section("weather").get("yandex_key", ""))
        if not ok:
            return
        w = config.section("weather")
        if key.strip() and not valid_key(key.strip()):
            QMessageBox.information(None, tr("Яндекс Погода"), tr("Это не похоже на ключ: ключ — одна строка без пробелов.\n"
                                    "Скопируй сам ключ из кабинета, а не пример кода."))
            return
        if key.strip():
            w["yandex_key"] = key.strip()
        else:
            w.pop("yandex_key", None)
        config.save()
        self.refresh_all()

    def refresh_all(self):
        for w in activity.widgets():  # Погода, Метеочасы, Солнце — сразу по-новому
            for name in ("refresh", "refresh_weather"):
                if w.key in ("weather", "meteoclock", "sun") and hasattr(w, name):
                    getattr(w, name)()

    def add_actions(self, menu):
        menu.addAction(tr("Город или село…"), self.ask_city)
        menu.addAction(tr("Яндекс Погода (свой ключ)…"), self.ask_yandex)
        menu.addAction(tr("Обновить"), self.refresh)

    def ask_city(self):
        """Название -> список мест с областями -> выбрать своё; запоминаются точные координаты."""
        text, ok = QInputDialog.getText(None, tr("Погода"), tr("Город или село:"), text=self.cfg.get("city", tr("Москва")))
        if not ok or not text.strip():
            return
        try:
            places = find_places(text.strip())
        except Exception:
            places = []
        if not places:
            QMessageBox.information(None, tr("Погода"), tr("Не нашёл такого места. Попробуй по-другому или латиницей."))
            return
        labels = [f"{p['city']} — {p['region']}" for p in places]
        choice, ok = QInputDialog.getItem(None, tr("Погода"), tr("Какое именно?"), labels, 0, False)
        if ok:
            set_place(places[labels.index(choice)])
            self.refresh_all()

    def refresh(self):
        self.city.setText(self.cfg.get("city", tr("Москва")))
        threading.Thread(target=self._fetch_and_show, args=(dict(self.cfg),), daemon=True).start()

    def _retry(self):
        self.retry_soon = False
        self.refresh()

    def _fetch_and_show(self, place):
        data = fetch(place)
        try:
            self.loaded.emit(data)
        except RuntimeError:  # виджет уже закрыли, пока грузилось
            pass

    def show_data(self, data):
        if "error" in data:
            self.info.setText(data["error"])
            # сеть не ответила (часто сразу после запуска Windows) — не ждать 15 минут до следующего раза
            if not getattr(self, "retry_soon", False):
                self.retry_soon = True
                QTimer.singleShot(60 * 1000, self._retry)
            return
        now = now_values(data)
        self.city.setText(data["name"])
        self.icon.setPixmap(icons.pixmap(icons.weather_kind(now["code"], now["is_day"]), 52))
        self.temp.setText(f"{now['temp']:+.0f}°")
        self.info.setText(now["text"].capitalize())
        d0 = data.get("daily", {})
        sunrise, sunset = (d0.get("sunrise") or [""])[0], (d0.get("sunset") or [""])[0]
        self.sun.setText(tr("восход {} · закат {}").format(sunrise[11:16], sunset[11:16]) if sunrise and sunset else "")
        fm = self.source.fontMetrics()
        self.source.setToolTip(now["source"])  # полностью — по наведению
        self.source.setText(fm.elidedText(now["source"], Qt.ElideRight, self.card().width() - 36))
        self.show_stats(data, now)
        self.show_hours(data)

        while self.days.count():
            self.days.takeAt(0).widget().deleteLater()
        d = data["daily"]
        for i in range(1, len(d["time"])):
            day = QWidget()
            col = QVBoxLayout(day)
            col.setContentsMargins(0, 2, 0, 0)
            col.setSpacing(1)
            name = QLabel(DAYS[date.fromisoformat(d["time"][i]).weekday()], objectName="dim",
                          alignment=Qt.AlignCenter)
            pic = QLabel(alignment=Qt.AlignCenter)
            pic.setPixmap(icons.pixmap(icons.weather_kind(d["weather_code"][i]), 24))
            temps = QLabel(f"{d['temperature_2m_max'][i]:+.0f}° / {d['temperature_2m_min'][i]:+.0f}°",
                           objectName="dim", alignment=Qt.AlignCenter)
            for lbl in (name, temps):
                lbl.setStyleSheet("font-size: 12px;")
            col.addWidget(name)
            col.addWidget(pic)
            col.addWidget(temps)
            self.days.addWidget(day)
        self.adjustSize()

    @staticmethod
    def _clear(lay):
        while lay.count():
            item = lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def show_stats(self, data, now):
        """Подробности: ощущается, давление, ветер (откуда и порывы), осадки сегодня, УФ, восход и закат."""
        self._clear(self.stats)
        cur, d = data.get("current", {}), data.get("daily", {})
        bias = (data.get("station") or {}).get("bias", 0.0) if "yandex" not in data else 0.0
        feels = data.get("yandex", {}).get("feels")
        if feels is None and cur.get("apparent_temperature") is not None:
            feels = cur["apparent_temperature"] + bias
        cells = []
        if feels is not None:
            cells.append((tr("ощущается"), f"{feels:+.0f}°"))
        if cur.get("pressure_msl") is not None:
            cells.append((tr("давление"), tr("{:.0f} мм").format(cur['pressure_msl'] * 0.750062)))
        wind = tr("штиль") if now["wind"] < 0.5 else tr("{:.0f} м/с").format(now['wind'])
        if now["wind"] >= 0.5 and cur.get("wind_direction_10m") is not None:
            wind = WIND[int((cur["wind_direction_10m"] + 22.5) // 45) % 8] + " " + wind
        if cur.get("wind_gusts_10m") and cur["wind_gusts_10m"] >= now["wind"] + 2:
            wind += tr(", до {:.0f}").format(cur['wind_gusts_10m'])
        cells.append((tr("ветер"), wind))

        def today(name):
            v = d.get(name)
            return v[0] if v else None
        if today("precipitation_probability_max") is not None:
            cells.append((tr("осадки"), f"{today('precipitation_probability_max'):.0f}%"))
        if today("uv_index_max") is not None:
            uv = today("uv_index_max")
            cells.append((tr("УФ"), f"{uv:.0f} · " + (tr("низкий") if uv < 3 else tr("средний") if uv < 6 else tr("высокий"))))
        if now["visibility"] is not None and now["visibility"] < 8:
            cells.insert(0, (tr("видимость"), tr("{:.0f} км").format(now['visibility'])))
        if now["humidity"] is not None:
            cells.insert(3, (tr("влажность"), f"{now['humidity']}%"))
        for i, (label, value) in enumerate(cells[:6]):
            box = QWidget()
            col = QVBoxLayout(box)
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(0)
            top = QLabel(label, objectName="dim")
            top.setStyleSheet("font-size: 10px;")
            val = QLabel(value)
            val.setStyleSheet("font-size: 13px; font-weight: 600;")
            col.addWidget(top)
            col.addWidget(val)
            self.stats.addWidget(box, i // 3, i % 3)

    def show_hours(self, data):
        """По часам: 6 точек через 2 часа от текущего часа — время, значок, температура, вероятность осадков."""
        self._clear(self.hours)
        h = data.get("hourly")
        if not h or not h.get("time"):
            return
        now_key = datetime.now().strftime("%Y-%m-%dT%H:00")
        start = next((i for i, t in enumerate(h["time"]) if t >= now_key), 0)
        bias = (data.get("station") or {}).get("bias", 0.0)
        for k in range(6):
            i = start + 2 + 2 * k  # «сейчас» уже показано крупно — с ближайших часов
            if i >= len(h["time"]):
                break
            box = QWidget()
            col = QVBoxLayout(box)
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(1)
            t = QLabel(h["time"][i][11:16], objectName="dim", alignment=Qt.AlignCenter)
            t.setStyleSheet("font-size: 10px;")
            pic = QLabel(alignment=Qt.AlignCenter)
            day = h.get("is_day", [1] * len(h["time"]))[i]
            pic.setPixmap(icons.pixmap(icons.weather_kind(h["weather_code"][i], day), 20))
            temp = QLabel(f"{h['temperature_2m'][i] + bias:+.0f}°", alignment=Qt.AlignCenter)
            temp.setStyleSheet("font-size: 12px; font-weight: 600;")
            col.addWidget(t)
            col.addWidget(pic)
            col.addWidget(temp)
            rain = (h.get("precipitation_probability") or [None] * len(h["time"]))[i]
            if rain:  # дождь вероятен — синим под температурой
                r = QLabel(f"{rain:.0f}%", alignment=Qt.AlignCenter)
                r.setStyleSheet("font-size: 10px; color: #5ab8ff;")
                col.addWidget(r)
            self.hours.addWidget(box)
