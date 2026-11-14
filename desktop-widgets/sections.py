"""Разделы общего окна (каталог виджетов): «Остров» и «Погода». Раздел «Виджеты» — сам каталог в main.py.

Остров — отдельная программа со своим config.json (папка «остров» или «dynamic-island» рядом с виджетами).
Раздел «Остров» правит этот файл, остров замечает изменение сам (следит за файлом) и сразу применяет.
Раздел «Погода» — место и сайт погоды для виджетов «Погода», «Метеочасы» и «Солнце».
Переключатели и сегменты — те же классы, что в каталоге (их передаёт main.py: тут их импортировать нельзя)."""
import json
import os
import threading
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QAbstractButton, QFrame, QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QSlider, QVBoxLayout, QWidget)

from core import ROOT, activity, config
from lang import LANGS, tr


def island_dir():
    """Папка острова рядом с виджетами (у себя — «остров», в публичной версии — «dynamic-island»)."""
    parent = os.path.dirname(ROOT)
    for name in ("остров", "dynamic-island"):
        path = os.path.join(parent, name)
        if os.path.isfile(os.path.join(path, "island.py")):
            return path
    return None


ISLAND_SERVER = "DynamicIsland-Fluid"  # окно-сервер острова (его main.py)
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "DynamicIsland"


def island_running():
    from PySide6.QtNetwork import QLocalSocket
    probe = QLocalSocket()
    probe.connectToServer(ISLAND_SERVER)
    alive = probe.waitForConnected(150)
    probe.abort()
    return alive


def island_autostart(folder):
    """Остров запускается с Windows (запись Run ведёт в эту папку острова)."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            cmd = winreg.QueryValueEx(k, RUN_NAME)[0]
    except OSError:
        return False
    return os.path.normcase(os.path.join(folder, "main.py")) in os.path.normcase(cmd)


def set_island_program(folder, on):
    """«Динамический остров» вкл/выкл целиком. Выкл — закрыть, снять автозапуск, сторож виджетов его не поднимает
    (файл stopped). Вкл — автозапуск обратно и запустить. Остаются только виджеты — или всё вместе."""
    import subprocess
    import sys
    import winreg
    from PySide6.QtCore import QProcess
    from PySide6.QtNetwork import QLocalSocket
    stopped = os.path.join(folder, "stopped")
    main_py = os.path.join(folder, "main.py")
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.isfile(pyw):
        pyw = sys.executable
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, f'"{pyw}" "{main_py}"')
        elif island_autostart(folder):  # чужую запись (другая копия острова) не трогаем
            winreg.DeleteValue(k, RUN_NAME)
    try:  # подстраховка автозапуска — задача Планировщика (есть не у всех): включить/выключить вместе
        subprocess.run(["schtasks", "/Change", "/TN", RUN_NAME, "/ENABLE" if on else "/DISABLE"],
                       capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        pass
    if on:
        try:
            os.remove(stopped)
        except OSError:
            pass
        if not island_running():
            QProcess.startDetached(pyw, [main_py], folder)
        return
    open(stopped, "w").close()  # сторож виджетов не поднимет остров снова
    sock = QLocalSocket()
    sock.connectToServer(ISLAND_SERVER)
    if sock.waitForConnected(300):
        sock.write(b"quit")
        sock.waitForBytesWritten(300)
        sock.disconnectFromServer()


class IslandConfig:
    """config.json острова: читаем каждый раз заново (остров тоже пишет в него), пишем целиком и атомарно."""

    def __init__(self, folder):
        self.path = os.path.join(folder, "config.json") if folder else None

    def read(self):
        try:
            with open(self.path, encoding="utf-8-sig") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def get(self, key, default=None):
        return self.read().get(key, default)

    def set(self, key, value):
        if not self.path:
            return
        data = self.read()
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
        tmp = self.path + ".widgets.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)


def set_active(w, on):
    """Сейчас не поменять — полупрозрачно (свои переключатели рисуются сами и «серого» вида не знают)."""
    w.setEnabled(on)
    if on:
        w.setGraphicsEffect(None)
    elif not isinstance(w.graphicsEffect(), QGraphicsOpacityEffect):
        w.setGraphicsEffect(QGraphicsOpacityEffect(w, opacity=0.4))


LOOK_DEFAULT = {"acrylic": True, "blur": 6, "haze": 50, "fill": 62, "theme": "dark"}


def section_card(title, sub=None):
    """Карточка раздела: заголовок, подпись и сетка «название — переключатель»."""
    card = QFrame(objectName="card")
    lay = QVBoxLayout(card)
    lay.setContentsMargins(20, 16, 20, 18)
    lay.setSpacing(10)
    head = QLabel(title)
    head.setStyleSheet("font-size: 16px; font-weight: 600;")
    lay.addWidget(head)
    if sub:
        s = QLabel(sub, objectName="dim", wordWrap=True)
        s.setStyleSheet("font-size: 12px;")
        lay.addWidget(s)
    grid = QGridLayout()
    grid.setHorizontalSpacing(16)
    grid.setVerticalSpacing(12)
    grid.setColumnStretch(3, 1)
    lay.addLayout(grid)
    return card, grid


class IslandPage(QWidget):
    """Всё, что было в окне настроек острова: вид, стекло, что показывать."""

    def __init__(self, Switch, Segmented):
        super().__init__()
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.folder = island_dir()
        self.cfg = IslandConfig(self.folder)
        self.quiet = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        if not self.folder:
            lay.addWidget(QLabel(tr("Динамический остров не найден рядом с виджетами."), objectName="dim"))
            lay.addStretch()
            return

        # ---- вид
        card, grid = section_card(tr("Вид"), tr("Всё применяется сразу — остров подхватывает изменения сам."))
        row = 0
        self.program = Switch()
        self.program.toggled.connect(self.set_program)
        self.program_note = QLabel("", objectName="dim")
        self.program_note.setStyleSheet("font-size: 12px;")
        self.program_until = 0.0  # пока остров запускается/закрывается — переключатель не дёргаем по опросу
        row = self.add_row(grid, row, tr("Динамический остров"), self.program,
                           tr("Выкл — остров закрывается и больше не запускается с Windows: остаются только виджеты.\n"
                              "Вкл — запускается сейчас и снова с Windows."), self.program_note)
        self.enabled = Switch()
        self.enabled.toggled.connect(lambda on: self.put("enabled", bool(on)))
        row = self.add_row(grid, row, tr("Показывать остров"), self.enabled,
                           tr("Выкл — остров спрятан, программа работает (вернуть — тут, в трее острова или "
                              "горячей клавишей)."))
        self.font = QSlider(Qt.Horizontal, minimum=80, maximum=140, singleStep=5, pageStep=10)
        self.font.setFixedWidth(220)
        self.font_value = QLabel("", objectName="dim")
        self.font_value.setFixedWidth(46)
        self.font.valueChanged.connect(self.set_font)
        row = self.add_row(grid, row, tr("Размер текста"), self.font,
                           tr("Крупнее текст — капсула чуть шире, чтобы всё влезало."), self.font_value)
        self.lang = Segmented([("auto", tr("Авто"))] + list(LANGS), "auto")
        self.lang.changed.connect(lambda name: self.put("lang", None if name == "auto" else name))
        row = self.add_row(grid, row, tr("Язык"), self.lang,
                           tr("Авто — как у виджетов. Остров меняет язык перезапуском (пара секунд)."))
        lay.addWidget(card)

        # ---- стекло
        card, grid = section_card(tr("Стекло"))
        row = 0
        self.follow = Switch()
        self.follow.toggled.connect(self.set_follow)
        row = self.add_row(grid, row, tr("Как у виджетов"), self.follow,
                           tr("Брать акрил, размытие, замутнение и тему из раздела «Виджеты».\n"
                              "Выключи — и настраивай остров отдельно."))
        self.acrylic = Switch()
        self.acrylic.toggled.connect(lambda on: self.put_look("acrylic", bool(on)))
        row = self.add_row(grid, row, tr("Акрил"), self.acrylic,
                           tr("Вкл — под островом размыто то, что за ним. Выкл — простая капсула («Заливка»)."))
        self.sliders = {}
        for key, text, lo, hi, unit, tip in (
                ("blur", tr("Размытие"), 0, 10, "", tr("0 — почти чётко, 10 — сплошные мягкие пятна.")),
                ("haze", tr("Замутнение"), -50, 100, "%", tr("0 — прозрачнее, 100 — почти сплошное стекло.\n"
                                                             "В минусе — сочные, яркие цвета под стеклом.")),
                ("fill", tr("Заливка"), 20, 100, "%", tr("Плотность капсулы без акрила. 100% — сплошная."))):
            slider = QSlider(Qt.Horizontal, minimum=lo, maximum=hi)
            slider.setFixedWidth(220)
            value = QLabel("", objectName="dim")
            value.setFixedWidth(46)
            slider.valueChanged.connect(lambda v, k=key: self.put_look(k, v))
            row = self.add_row(grid, row, text, slider, tip, value)
            self.sliders[key] = (slider, value, unit)
        self.theme = Segmented([("auto", tr("Авто")), ("dark", tr("Тёмная")), ("light", tr("Светлая"))], "dark")
        self.theme.changed.connect(lambda name: self.put_look("theme", name))
        row = self.add_row(grid, row, tr("Тема"), self.theme,
                           tr("Авто — по тому, что под островом: над светлым — светлое стекло."))
        self.glass_rows = [self.acrylic, self.theme] + [s for s, _, _ in self.sliders.values()]
        lay.addWidget(card)

        self.shows = {}
        self.agents_card(lay, Switch)

        # ---- горячая клавиша
        card, grid = section_card(tr("Горячая клавиша"))
        hint = QLabel("", objectName="dim", wordWrap=True)
        hint.setStyleSheet("font-size: 12px;")
        self.hotkey_hint = hint
        grid.addWidget(hint, 0, 0, 1, 4)
        lay.addWidget(card)
        lay.addStretch()
        # остров сам тоже пишет в файл (вкл/выкл из трея) — пока раздел открыт, показываем свежее
        self.watch = QTimer(self, interval=1000, timeout=self.load)

    @staticmethod
    def add_row(grid, row, text, control, tip, extra=None):
        label = QLabel(text)
        label.setToolTip(tip)
        control.setToolTip(tip)
        grid.addWidget(label, row, 0)
        grid.addWidget(control, row, 1, Qt.AlignLeft)
        if extra is not None:
            grid.addWidget(extra, row, 2)
        return row + 1

    def agents_card(self, lay, Switch):
        """AI-помощники на острове: показывать ли и к кому подключиться (хуки в настройках каждого помощника)."""
        import agent_connect
        self.ac = agent_connect
        self.agent_rows, self.agent_err = {}, {}
        card, grid = section_card(tr("AI-помощники"), tr("Остров показывает, чем занят помощник: думает, правит файл, "
                                                          "ждёт твоего ответа. Хук передаёт только это — без текста "
                                                          "разговора и содержимого файлов."))
        row = 0
        sw = Switch()
        sw.toggled.connect(lambda on: self.put("agents", bool(on)))
        row = self.add_row(grid, row, tr("Показывать на острове"), sw,
                           tr("Выкл — помощники на острове не появляются (подключение остаётся)."))
        self.shows["agents"] = sw
        for agent in agent_connect.ORDER:
            s = Switch()
            note = QLabel("", objectName="dim")
            note.setStyleSheet("font-size: 12px;")
            s.toggled.connect(lambda on, a=agent: self.set_agent(a, on))
            row = self.add_row(grid, row, agent_connect.AGENTS[agent]["title"], s,
                               tr("Вкл — в настройки помощника добавятся хуки (прежний файл сохранится копией рядом).\n"
                                  "Выкл — наши хуки убираются, чужие остаются."), note)
            self.agent_rows[agent] = (s, note)
        lay.addWidget(card)

    def load_agents(self):
        for agent, (s, note) in self.agent_rows.items():
            have = self.ac.installed(agent)
            on = self.ac.connected(agent)
            s.set_quiet(on)
            set_active(s, have or on)
            if agent in self.agent_err:
                text = self.agent_err[agent]
            elif not have:
                text = tr("не установлен")
            elif not on:
                text = ""
            elif agent == "codex":
                text = tr("подключён — в Codex один раз подтверди хук командой /hooks")
            elif agent == "antigravity":
                text = tr("подключён — с новой задачи (не видно — перезапусти Antigravity)")
            else:
                text = tr("подключён")
            note.setText(text)

    def set_agent(self, agent, on):
        if self.quiet:
            return
        try:
            if on:
                self.ac.connect(agent)
            else:
                self.ac.disconnect(agent)
            self.agent_err.pop(agent, None)
        except (OSError, ValueError):
            self.agent_err[agent] = tr("не вышло: файл настроек помощника не читается")
        self.load_agents()

    # ---------- данные ----------

    def look(self, data):
        if data.get("follow_widgets", True):
            app = config.section("app")
            return {k: app.get(k, v) for k, v in LOOK_DEFAULT.items()}
        own = data.get("look") or {}
        return {k: own.get(k, v) for k, v in LOOK_DEFAULT.items()}

    def load(self):
        if not self.folder:
            return
        data = self.cfg.read()
        look = self.look(data)
        follow = data.get("follow_widgets", True)
        self.quiet = True
        try:
            self.enabled.set_quiet(data.get("enabled", True))
            fs = int(data.get("font_scale", 100))
            if self.font.value() != fs:
                self.font.setValue(fs)
            self.font_value.setText(f"{fs}%")
            self.lang.set_quiet(data.get("lang") or "auto")
            self.follow.set_quiet(follow)
            self.acrylic.set_quiet(bool(look["acrylic"]))
            for key, (slider, value, unit) in self.sliders.items():
                if slider.value() != int(look[key]):
                    slider.setValue(int(look[key]))
                value.setText(f"{int(look[key])}{unit}")
            self.theme.set_quiet(look["theme"])
            for key, sw in self.shows.items():
                sw.set_quiet(data.get(key, True))
        finally:
            self.quiet = False
        for w in self.glass_rows:  # «как у виджетов» — своё стекло не поменять
            set_active(w, not follow)
        set_active(self.sliders["fill"][0], not follow and not look["acrylic"])
        self.load_agents()
        self.load_program()
        keys = (data.get("hotkey") or "ctrl+alt+i").title()
        self.hotkey_hint.setText(tr("Спрятать / вернуть остров: {}. Сменить сочетание — \"hotkey\" в config.json острова.")
                                 .format(keys))

    def put(self, key, value):
        if self.quiet:
            return
        self.cfg.set(key, value)

    def load_program(self):
        """Остров работает или запустится с Windows — переключатель «Динамический остров» включён."""
        if time.monotonic() < self.program_until:
            return
        running = island_running()
        on = running or (island_autostart(self.folder) and not os.path.exists(os.path.join(self.folder, "stopped")))
        self.program.set_quiet(on)
        self.program_note.setText("" if on == running else tr("запустится с Windows") if on else "")
        set_active(self.enabled, on)

    def set_program(self, on):
        if self.quiet:
            return
        try:
            set_island_program(self.folder, bool(on))
            self.program_note.setText(tr("запускается…") if on else tr("выключен — остались только виджеты"))
        except OSError:
            self.program_note.setText(tr("не вышло: нет доступа к автозапуску"))
        self.program_until = time.monotonic() + 6  # дать острову запуститься / закрыться
        set_active(self.enabled, bool(on))

    def set_font(self, value):
        value = round(value / 5) * 5
        self.font_value.setText(f"{value}%")
        if not self.quiet and value != int(self.cfg.get("font_scale", 100)):
            self.cfg.set("font_scale", value)

    def set_follow(self, on):
        if self.quiet:
            return
        data = self.cfg.read()
        if not on and not data.get("look"):  # свои начинаются с тех, что у виджетов
            self.cfg.set("look", self.look(data))
        self.cfg.set("follow_widgets", bool(on))
        self.load()

    def put_look(self, key, value):
        if self.quiet:
            return
        data = self.cfg.read()
        if data.get("follow_widgets", True):
            return
        look = dict(data.get("look") or self.look(data))
        look[key] = value
        self.cfg.set("look", look)
        self.load()

    def showEvent(self, event):
        super().showEvent(event)
        if self.folder:
            self.load()
            self.watch.start()

    def hideEvent(self, event):
        if self.folder:
            self.watch.stop()


class PlaceButton(QAbstractButton):
    """Строка найденного места: название крупно, область и страна мелко."""

    def __init__(self, place):
        super().__init__()
        self.place = place
        self.setCursor(Qt.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 6)
        name = QLabel(place["city"])
        name.setStyleSheet("font-size: 14px; font-weight: 600;")
        region = QLabel(place.get("region", ""), objectName="dim")
        region.setStyleSheet("font-size: 12px;")
        lay.addWidget(name)
        lay.addWidget(region, 1)
        self.setMinimumHeight(36)

    def paintEvent(self, event):
        if self.underMouse():
            from PySide6.QtGui import QColor, QPainter
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(128, 128, 140, 50))
            p.drawRoundedRect(self.rect(), 12, 12)

    def enterEvent(self, event):
        self.update()

    def leaveEvent(self, event):
        self.update()


class WeatherPage(QWidget):
    """Место и сайт погоды — общие для виджетов погоды."""
    found = Signal(object)
    fetched = Signal(object)

    def __init__(self, Switch, Segmented, PillButton):
        super().__init__()
        self.setAttribute(Qt.WA_TranslucentBackground)
        from widgets import weather as W
        self.W = W
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        card, grid = section_card(tr("Место"), tr("Для виджетов «Погода», «Метеочасы» и «Солнце»."))
        self.now = QLabel("")
        self.now.setStyleSheet("font-size: 14px;")
        grid.addWidget(QLabel(tr("Сейчас")), 0, 0)
        grid.addWidget(self.now, 0, 1, 1, 3)
        self.query = QLineEdit(placeholderText=tr("Город или село"))
        self.query.setFixedWidth(280)
        self.query.returnPressed.connect(self.search)
        find = PillButton(tr("Найти"))
        find.clicked.connect(self.search)
        grid.addWidget(QLabel(tr("Сменить")), 1, 0)
        grid.addWidget(self.query, 1, 1)
        grid.addWidget(find, 1, 2, Qt.AlignLeft)
        self.status = QLabel("", objectName="dim")
        self.status.setStyleSheet("font-size: 12px;")
        grid.addWidget(self.status, 2, 1, 1, 3)
        self.results = QVBoxLayout()
        self.results.setSpacing(2)
        grid.addLayout(self.results, 3, 0, 1, 4)
        lay.addWidget(card)

        card, grid = section_card(tr("Откуда погода"), tr("Сайты с ключом (Яндекс, OpenWeatherMap) — ключ "
                                                          "вписывается в меню виджета «Погода» (правый клик)."))
        self.sources = {}
        row = 0
        for name, label in W.SOURCES.items():
            sw = Switch()
            # как переключатель «один из»: выключить выбранный нельзя — выбирают другой
            sw.toggled.connect(lambda on, n=name: self.set_source(n) if on else QTimer.singleShot(0, self.load))
            text = label + (tr(" (свой ключ)") if name in W.KEYS else "")
            grid.addWidget(QLabel(text), row, 0)
            grid.addWidget(sw, row, 1, Qt.AlignLeft)
            self.sources[name] = sw
            row += 1
        lay.addWidget(card)
        lay.addStretch()
        self.found.connect(self.show_found)
        self.fetched.connect(lambda _: self.load())

    def load(self):
        cfg = config.section("weather")
        city = cfg.get("city") or tr("не выбрано")
        try:
            with open(self.W.NOW_FILE, encoding="utf-8") as f:
                snap = json.load(f)
            if time.time() - snap.get("updated", 0) < 2 * 3600 and snap.get("city") == cfg.get("city"):
                city += f"  ·  {snap['temp']:+d}°, {snap.get('text', '')}"
        except (OSError, ValueError, KeyError, TypeError):
            pass
        self.now.setText(city)
        now = self.W.current_source(cfg)
        for name, sw in self.sources.items():
            sw.set_quiet(name == now)
            set_active(sw, name not in self.W.KEYS or self.W.valid_key(cfg.get(self.W.KEYS[name])))

    def showEvent(self, event):
        super().showEvent(event)
        self.load()

    def search(self):
        text = self.query.text().strip()
        if not text:
            return
        self.status.setText(tr("ищу…"))

        def work():
            try:
                places = self.W.find_places(text)
            except Exception as ex:  # нет сети
                places = tr("нет связи ({})").format(type(ex).__name__)
            try:
                self.found.emit(places)
            except RuntimeError:
                pass
        threading.Thread(target=work, daemon=True).start()

    def clear_results(self):
        while self.results.count():
            w = self.results.takeAt(0).widget()
            if w:
                w.deleteLater()

    def show_found(self, places):
        self.clear_results()
        if isinstance(places, str):
            self.status.setText(places)
            return
        if not places:
            self.status.setText(tr("город не найден"))
            return
        self.status.setText(tr("Выбери своё:"))
        for p in places[:6]:
            b = PlaceButton(p)
            b.clicked.connect(lambda _=False, p=p: self.choose(p))
            self.results.addWidget(b)

    def choose(self, place):
        self.W.set_place(place)
        self.clear_results()
        self.query.clear()
        self.status.setText(tr("{} — обновляю погоду…").format(place["city"]))
        self.refresh_all()
        self.load()

    def set_source(self, name):
        cfg = config.section("weather")
        if self.W.current_source(cfg) == name:
            return
        cfg["source"] = name
        config.save()
        self.status.setText(tr("обновляю погоду…"))
        self.refresh_all()
        self.load()

    def refresh_all(self):
        """Виджеты погоды на столе — обновить."""
        for w in activity.widgets():
            for name in ("refresh", "refresh_weather"):
                if w.key in ("weather", "meteoclock", "sun") and hasattr(w, name):
                    getattr(w, name)()
        QTimer.singleShot(4000, self.load)

