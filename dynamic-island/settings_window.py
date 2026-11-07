"""Окно настроек острова: стекло как у виджетов (акрил, размытие, замутнение, заливка, тема).

«Как у виджетов» — остров берёт эти настройки из каталога виджетов и меняется вместе с ними;
выключено — свои (начинаются с тех, что были у виджетов). Всё применяется сразу, сохраняется в config.json."""
from lang import LANGS, tr
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QLabel, QSlider,
                               QVBoxLayout, QWidget)

import island as isl_mod
from bridge import settings
from ui import Segmented, Switch, TitleButton

SLIDERS = (  # ключ, подпись, от, до, единица, подсказка — как в каталоге виджетов
    ("blur", tr("Размытие"), 0, 10, "",
     tr("Насколько размыто то, что под островом. 0 — почти чётко, 10 — сплошные мягкие пятна.")),
    ("haze", tr("Замутнение"), -50, 100, "%",
     tr("Сколько дымки поверх размытого. 0 — прозрачнее, 100 — почти сплошное стекло.\n"
     "В минусе — ещё и сочные, яркие цвета под стеклом.")),
    ("fill", tr("Заливка"), 20, 100, "%",
     tr("Плотность стекла без акрила (когда «Акрил» выключен). 100% — сплошная капсула.")),
)


def style(dark):
    fg, dim = ("#f5f6fb", "#b6bbcd") if dark else ("#1b1c22", "#565a6b")
    track = "rgba(255,255,255,40)" if dark else "rgba(0,0,0,30)"
    return f"""
QLabel {{ color: {fg}; background: transparent; font-size: 13px; }}
QLabel#dim {{ color: {dim}; font-size: 12px; }}
QLabel#title {{ font-size: 19px; font-weight: 600; }}
QLabel:disabled {{ color: {dim}; }}
QSlider {{ background: transparent; min-height: 22px; }}
QSlider::groove:horizontal {{ height: 6px; background: {track}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: #2f7bff; border-radius: 3px; }}
QSlider::sub-page:horizontal:disabled {{ background: {dim}; }}
QSlider::handle:horizontal {{ background: white; width: 18px; height: 18px; margin: -6px 0; border-radius: 9px;
                              border: 1px solid rgba(0,0,0,40); }}
"""


class SettingsWindow(QWidget):
    def __init__(self, island):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle(tr("Остров — настройки"))
        self.island = island
        self.dark = True
        self.drag = None
        self.quiet = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 20, 22)
        lay.setSpacing(14)
        head = QHBoxLayout()
        title = QLabel(tr("Динамический остров"), objectName="title")
        head.addWidget(title)
        head.addStretch()
        close = TitleButton("close")
        close.setToolTip(tr("Закрыть"))
        close.clicked.connect(self.hide)
        head.addWidget(close, alignment=Qt.AlignTop)
        lay.addLayout(head)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(12)
        row = 0
        # размер текста — свой у острова всегда (у виджетов такой настройки нет)
        font_label = QLabel(tr("Размер текста"))
        font_label.setToolTip(tr("Крупнее текст — капсула чуть шире, чтобы всё влезало."))
        self.font_slider = QSlider(Qt.Horizontal, minimum=80, maximum=140, singleStep=5, pageStep=10)
        self.font_slider.setFixedWidth(200)
        self.font_value = QLabel("", objectName="dim")
        self.font_value.setFixedWidth(42)
        self.font_slider.valueChanged.connect(self.set_font)
        grid.addWidget(font_label, row, 0)
        grid.addWidget(self.font_slider, row, 1)
        grid.addWidget(self.font_value, row, 2)
        row += 1
        follow_label = QLabel(tr("Как у виджетов"))
        follow_label.setToolTip(tr("Брать стекло и тему из каталога виджетов и меняться вместе с ними.\n"
                                "Выключи — и настраивай остров отдельно."))
        self.follow = Switch()
        self.follow.toggled.connect(self.set_follow)
        grid.addWidget(follow_label, row, 0)
        grid.addWidget(self.follow, row, 1, 1, 2, Qt.AlignLeft)
        row += 1
        self.follow_hint = QLabel("", objectName="dim")
        grid.addWidget(self.follow_hint, row, 0, 1, 3)
        row += 1

        self.acrylic_label = QLabel(tr("Акрил"))
        self.acrylic_label.setToolTip(tr("Вкл — настоящий акрил: под островом размыто то, что за ним.\n"
                                      "Выкл — простая капсула (плотность — «Заливка»), экран не снимается — дешевле."))
        self.acrylic = Switch()
        self.acrylic.toggled.connect(lambda on: self.changed("acrylic", on))
        grid.addWidget(self.acrylic_label, row, 0)
        grid.addWidget(self.acrylic, row, 1, 1, 2, Qt.AlignLeft)
        row += 1

        self.sliders = {}
        for key, text, lo, hi, unit, tip in SLIDERS:
            label = QLabel(text)
            label.setToolTip(tip)
            slider = QSlider(Qt.Horizontal, minimum=lo, maximum=hi)
            slider.setFixedWidth(200)
            slider.setToolTip(tip)
            value = QLabel("", objectName="dim")
            value.setFixedWidth(42)
            slider.valueChanged.connect(lambda v, k=key: self.changed(k, v))
            grid.addWidget(label, row, 0)
            grid.addWidget(slider, row, 1)
            grid.addWidget(value, row, 2)
            self.sliders[key] = (label, slider, value, unit)
            row += 1

        self.theme_label = QLabel(tr("Тема"))
        self.theme_label.setToolTip(tr("Авто — по тому, что под островом: над светлым — светлое стекло и тёмный текст."))
        self.theme = Segmented([("auto", tr("Авто")), ("dark", tr("Тёмная")), ("light", tr("Светлая"))], "dark")
        self.theme.changed.connect(lambda name: self.changed("theme", name))
        grid.addWidget(self.theme_label, row, 0)
        grid.addWidget(self.theme, row, 1, 1, 2, Qt.AlignLeft)
        row += 1
        lang_label = QLabel(tr("Язык"))
        lang_tip = tr("Авто — как у виджетов. Язык меняется перезапуском острова (пара секунд).")
        lang_label.setToolTip(lang_tip)
        self.lang = Segmented([("auto", tr("Авто"))] + list(LANGS), settings.get("lang") or "auto")
        self.lang.setToolTip(lang_tip)
        self.lang.changed.connect(self.set_lang)
        grid.addWidget(lang_label, row, 0)
        grid.addWidget(self.lang, row, 1, 1, 2, Qt.AlignLeft)
        row += 1
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)

        keys = island.hotkey.title() if island.hotkey_ok else tr("{} (занята)").format(island.hotkey.title())
        hint = QLabel(tr("Спрятать / вернуть остров: {}. Сменить сочетание — \"hotkey\" в config.json острова.").format(keys),
                      objectName="dim", wordWrap=True)
        lay.addWidget(hint)
        self.follow_hint.setWordWrap(True)
        self.setFixedWidth(470)

        # «Как у виджетов» — пока окно открыто, видно, что меняют в каталоге
        self.watch = QTimer(self, interval=700, timeout=self.load)

    # ---------- данные ----------

    def load(self):
        """Показать текущие настройки (свои или виджетов) — без сигналов."""
        follow = settings.get("follow_widgets", True)
        look = self.island.wanted_look()
        self.quiet = True
        fs = int(settings.get("font_scale", 100))
        if self.font_slider.value() != fs:
            self.font_slider.setValue(fs)
        self.font_value.setText(f"{fs}%")
        if self.follow.isChecked() != follow:
            self.follow.set_quiet(follow)
        if self.acrylic.isChecked() != bool(look["acrylic"]):
            self.acrylic.set_quiet(bool(look["acrylic"]))
        for key, (label, slider, value, unit) in self.sliders.items():
            if slider.value() != int(look[key]):
                slider.setValue(int(look[key]))
            value.setText(f"{int(look[key])}{unit}")
        self.theme.set_quiet(look["theme"])
        self.quiet = False
        self.follow_hint.setText(tr("Стекло и тема — из каталога виджетов; поменяешь там — поменяется и тут.")
                                 if follow else tr("Свои настройки острова."))
        fill_on = not follow and not look["acrylic"]  # заливка — только без акрила
        rest = [x for key, row in self.sliders.items() if key != "fill" for x in row[:3]]
        for w in [self.acrylic_label, self.acrylic, self.theme_label, self.theme] + rest:
            self.set_active(w, not follow)
        for x in self.sliders["fill"][:3]:
            self.set_active(x, fill_on)
        self.set_dark(isl_mod.DARK)

    @staticmethod
    def set_active(w, on):
        """Заблокировано — полупрозрачное: видно, что сейчас эту настройку не поменять."""
        w.setEnabled(on)
        if on:
            w.setGraphicsEffect(None)
        elif not isinstance(w.graphicsEffect(), QGraphicsOpacityEffect):
            w.setGraphicsEffect(QGraphicsOpacityEffect(w, opacity=0.4))

    def set_lang(self, name):
        settings.set("lang", None if name == "auto" else name)
        if self.island.wanted_lang() != isl_mod.lang.LANG:
            self.island.restart()

    def set_font(self, value):
        if self.quiet:
            return
        value = round(value / 5) * 5  # шаг 5%: меньше лишних пересборок, пока тянут
        self.font_value.setText(f"{value}%")
        if value != int(settings.get("font_scale", 100)):
            settings.set("font_scale", value)
            self.island.refresh_look()

    def set_follow(self, on):
        if self.quiet:
            return
        if not on and not settings.get("look"):  # свои начинаются с тех, что у виджетов
            settings.set("look", self.island.wanted_look())
        settings.set("follow_widgets", on)
        self.island.refresh_look(force=True)
        self.load()

    def changed(self, key, value):
        if self.quiet or settings.get("follow_widgets", True):
            return
        look = dict(settings.get("look", {})) or self.island.wanted_look()
        look[key] = value
        settings.set("look", look)
        self.island.refresh_look(force=True)
        self.load()

    # ---------- окно ----------

    def set_dark(self, dark):
        if dark != self.dark or not self.styleSheet():
            self.dark = dark
            self.setStyleSheet(style(dark))
            self.update()

    def open(self):
        self.load()
        self.adjustSize()
        if not self.isVisible():
            g = QApplication.primaryScreen().availableGeometry()
            self.move(g.x() + (g.width() - self.width()) // 2, g.y() + 200)
        self.show()
        self.raise_()
        self.activateWindow()
        self.watch.start()

    def hideEvent(self, event):
        self.watch.stop()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(QColor(255, 255, 255, 50 if self.dark else 170), 1))
        p.setBrush(QColor(22, 22, 28, 244) if self.dark else QColor(246, 246, 250, 246))
        p.drawRoundedRect(r, 24, 24)

    # таскать за пустое место
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event):
        if self.drag is not None:
            self.move(event.globalPosition().toPoint() - self.drag)

    def mouseReleaseEvent(self, event):
        self.drag = None

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.hide()

