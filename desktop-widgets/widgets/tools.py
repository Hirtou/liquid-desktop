"""Инструменты Windows одной кнопкой: терминал, командная строка, диспетчеры задач и устройств, сеть, реестр,
службы, диски, события и т.д. Плитки со своими значками; что показывать — правый клик → «Что показывать».
Запуск — через Windows (ShellExecute): программы, которым нужны права администратора (реестр, службы),
сами спросят разрешение. Отсюда ничего не выключается и не удаляется — только открывается."""
from lang import tr
import ctypes
import math
import shutil

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QToolTip

from core import DesktopWidget, config, grid

# ключ: (подпись на плитке, полное название — подсказка, цвет сверху, цвет снизу, что запустить, параметры)
TOOLS = {
    "terminal": (tr("Терминал"), tr("Терминал Windows"), "#3a4253", "#1c2029", "wt.exe", None),
    "cmd": (tr("Cmd"), tr("Командная строка"), "#2b2d33", "#0d0e11", "cmd.exe", None),
    "powershell": ("PowerShell", "Windows PowerShell", "#2f6bd9", "#123a8a", "powershell.exe", None),
    "taskmgr": (tr("Задачи"), tr("Диспетчер задач"), "#36c37a", "#14834a", "taskmgr.exe", None),
    "devmgmt": (tr("Устройства"), tr("Диспетчер устройств"), "#8b7cf6", "#5137d6", "devmgmt.msc", None),
    "network": (tr("Сеть"), tr("Параметры сети и интернета"), "#38bdf8", "#0b7fc0", "ms-settings:network-status", None),
    "adapters": (tr("Адаптеры"), tr("Сетевые подключения (адаптеры)"), "#22c3b4", "#0f8075", "ncpa.cpl", None),
    "regedit": (tr("Реестр"), tr("Редактор реестра"), "#58a6ff", "#2563c9", "regedit.exe", None),
    "services": (tr("Службы"), tr("Службы Windows"), "#9aa3b5", "#566074", "services.msc", None),
    "control": (tr("Панель"), tr("Панель управления"), "#f59e42", "#d0631a", "control.exe", None),
    "disks": (tr("Диски"), tr("Управление дисками"), "#f472b6", "#c0287e", "diskmgmt.msc", None),
    "events": (tr("События"), tr("Просмотр событий"), "#fbbf24", "#d18a0a", "eventvwr.msc", None),
    "run": (tr("Выполнить"), tr("Окно «Выполнить» (Win+R)"), "#6b7280", "#3d434f",
            "shell:::{2559a1f3-21d7-11d4-bdaf-00c04f60b9f0}", None),
    "msinfo": (tr("Сведения"), tr("Сведения о системе"), "#60a5fa", "#3567d6", "msinfo32.exe", None),
    "sound": (tr("Звук"), tr("Звук: устройства воспроизведения и записи"), "#ff7a7a", "#d23b55", "mmsys.cpl", None),
    "apps": (tr("Программы"), tr("Установленные приложения"), "#a3e635", "#5d9c12", "ms-settings:appsfeatures", None),
    "env": (tr("Переменные"), tr("Переменные среды"), "#c084fc", "#8b3fd9", "rundll32.exe",
            "sysdm.cpl,EditEnvironmentVariables"),
    "power": (tr("Питание"), tr("Электропитание"), "#facc15", "#c79a06", "powercfg.cpl", None),
    "startup": (tr("Автозапуск"), tr("Приложения в автозагрузке"), "#fb923c", "#d9531e", "ms-settings:startupapps",
                None),
}
DEFAULT = ["terminal", "cmd", "taskmgr", "devmgmt", "network", "adapters", "regedit", "services", "control",
           "disks", "events", "run"]


def launch(key):
    """Открыть инструмент через Windows (как двойной клик в Проводнике)."""
    _, _, _, _, target, params = TOOLS[key]
    if key == "terminal" and not shutil.which("wt"):  # нет Терминала Windows — обычный PowerShell
        target = "powershell.exe"
    if target.endswith(".cpl"):  # апплеты панели управления: «open» на .cpl в новых Windows часто молчит
        target, params = "control.exe", target
    rc = ctypes.windll.shell32.ShellExecuteW(None, "open", target, params, None, 1)
    if rc <= 32:  # не открылось — пробуем через «Выполнить»-путь (explorer), и пишем в журнал
        try:
            import applog
            applog.warn(f"инструменты: {key} не открылся ({target} {params or ''}, код {rc})")
        except Exception:
            pass
        ctypes.windll.shell32.ShellExecuteW(None, "open", "explorer.exe",
                                            "shell:::{7007ACC7-3202-11D1-AAD2-00805FC1270E}" if key == "adapters"
                                            else target, None, 1)


class ToolsWidget(DesktopWidget):
    key = "tools"
    title = tr("Инструменты")
    description = tr("Терминал, cmd, диспетчеры задач и устройств, сеть, реестр, службы — одним кликом")
    SHAPES = {"grid": (tr("Сетка 4×3"), grid(2, 2)), "wide": (tr("Широкий: все"), grid(4, 2)),
              "row": (tr("В ряд"), grid(2, 1))}

    def __init__(self, **kw):
        super().__init__(**kw)
        self.apply_shape()
        self.buttons = {}
        self.pressed_key = None

    # ---- что показывать ----
    def items(self):
        keys = self.cfg.get("items")
        keys = [k for k in (keys if isinstance(keys, list) else DEFAULT) if k in TOOLS]
        shape = self.shape()
        if shape == "wide" and "items" not in self.cfg:
            keys = list(TOOLS)  # широкий без своего выбора — все
        return keys[:self.capacity()]

    def layout_grid(self):
        """(колонок, рядов) плиток под вид."""
        return {"grid": (4, 3), "wide": (8, 3), "row": (5, 1)}.get(self.shape(), (4, 3))

    def capacity(self):
        c, r = self.layout_grid()
        return c * r

    def add_actions(self, menu):
        sub = menu.addMenu(tr("Что показывать"))
        chosen = self.cfg.get("items") if isinstance(self.cfg.get("items"), list) else list(self.items())
        for k, (label, full, *_rest) in TOOLS.items():
            a = sub.addAction(full, lambda k=k: self.toggle_item(k))
            a.setCheckable(True)
            a.setChecked(k in chosen)
        sub.addSeparator()
        sub.addAction(tr("Как было"), self.reset_items)

    def toggle_item(self, key):
        keys = self.cfg.get("items") if isinstance(self.cfg.get("items"), list) else list(self.items())
        keys = [k for k in keys if k != key] if key in keys else keys + [key]
        self.cfg["items"] = [k for k in TOOLS if k in keys]  # порядок — как в списке инструментов
        config.save()
        self.update()

    def reset_items(self):
        self.cfg.pop("items", None)
        config.save()
        self.update()

    # ---- мышь ----
    def hit(self, pos):
        for k, rect in self.buttons.items():
            if rect.contains(pos):
                return k
        return None

    def click(self, pos):
        k = self.hit(pos)
        if k:
            self.pressed_key = k
            self.update()
            launch(k)
            QTimer.singleShot(160, self._release)
            return True
        return False

    def _release(self):
        self.pressed_key = None
        self.update()

    def event(self, ev):
        if ev.type() == ev.Type.ToolTip:  # полное название под мышью
            k = self.hit(QPointF(ev.pos()) / self.scale())
            if k:
                QToolTip.showText(ev.globalPos(), TOOLS[k][1], self)
            else:
                QToolTip.hideText()
            return True
        return super().event(ev)

    # ---- рисование ----
    def paintEvent(self, event):
        super().paintEvent(event)  # стекло
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        r = QRectF(self.card()).adjusted(14, 12, -14, -10)
        dark = bool(self.dark)
        fg = QColor("#ededf0") if dark else QColor("#151517")
        dim = QColor(fg)
        dim.setAlpha(165)
        head = QFont("Segoe UI Semibold")
        head.setPixelSize(15)
        p.setFont(head)
        p.setPen(fg)
        p.drawText(QRectF(r.left() + 2, r.top(), r.width(), 20), Qt.AlignLeft | Qt.AlignVCenter, tr("Инструменты"))
        keys = self.items()
        cols, rows = self.layout_grid()
        top = r.top() + 26
        cw, ch = r.width() / cols, (r.bottom() - top) / rows
        side = min(cw - 22, ch - 30, 46)  # плитка — как у «Быстрых кнопок»
        label = QFont("Segoe UI")
        size = 11
        label.setPixelSize(size)
        names = [TOOLS[k][0] for k in keys] or [""]
        while size > 8 and max(QFontMetricsF(label).horizontalAdvance(t) for t in names) > cw - 4:
            size -= 1
            label.setPixelSize(size)
        fm = QFontMetricsF(label)
        self.buttons = {}
        for i, k in enumerate(keys):
            row, col = divmod(i, cols)
            cx = r.left() + cw * col + cw / 2
            cy = top + ch * row + (ch - side - 16) / 2
            tile = QRectF(cx - side / 2, cy, side, side)
            self.buttons[k] = tile.adjusted(-6, -4, 6, 18)
            text, full, c1, c2 = TOOLS[k][:4]
            if k == self.pressed_key:  # нажатие — плитка чуть меньше
                tile = tile.adjusted(side * 0.06, side * 0.06, -side * 0.06, -side * 0.06)
            pix = tile_pixmap(k, tile.width(), self.devicePixelRatioF())
            pad = tile.width() * 0.12
            p.drawPixmap(QPointF(tile.left() - pad, tile.top() - pad), pix)
            p.setFont(label)
            p.setPen(dim)
            p.drawText(QRectF(cx - cw / 2 + 2, tile.bottom() + 3, cw - 4, 16), Qt.AlignCenter,
                       fm.elidedText(text, Qt.ElideRight, cw - 4))
        if not keys:
            p.setPen(dim)
            p.drawText(QRectF(r.left(), top, r.width(), r.bottom() - top), Qt.AlignCenter,
                       tr("Правый клик → «Что показывать»"))


# ---------- значки ----------
# Как у «Быстрых кнопок»: плитка сплошного цвета со скруглением, на ней белый значок, подпись снизу.
# Значки свои, нарисованы в квадрате 100×100; готовая плитка кэшируется (виджет перерисовывается часто).

_TILE_CACHE = {}


def tile_pixmap(k, side, dpr):
    key = (k, round(side, 1), round(dpr, 2))
    pix = _TILE_CACHE.get(key)
    if pix is not None:
        return pix
    pad = side * 0.12  # то же поле, что раньше (место под плитку в раскладке не меняется)
    full = side + 2 * pad
    pix = QPixmap(int(full * dpr), int(full * dpr))
    pix.setDevicePixelRatio(dpr)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
    p.translate(pad, pad)
    p.scale(side / 100, side / 100)
    c1 = QColor(TOOLS[k][2])
    flat = QColor(c1)  # яркий, как плитки «Быстрых кнопок»
    p.setPen(Qt.NoPen)
    p.setBrush(flat)
    p.drawRoundedRect(QRectF(0, 0, 100, 100), 28, 28)
    _glyph100(p, k, flat.darker(135))
    p.end()
    if len(_TILE_CACHE) > 200:
        _TILE_CACHE.clear()
    _TILE_CACHE[key] = pix
    return pix


def _glyph100(p, k, acc):
    W = QColor(255, 255, 255)
    W2 = QColor(255, 255, 255, 150)
    W3 = QColor(255, 255, 255, 90)

    def fill(color):
        p.setPen(Qt.NoPen)
        p.setBrush(color)

    def stroke(color, w):
        p.setPen(QPen(color, w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)

    def rr(x, y, w, h, r, color):
        fill(color)
        p.drawRoundedRect(QRectF(x, y, w, h), r, r)

    def shadow_rr(x, y, w, h, r):
        rr(x, y + 2.5, w, h, r, QColor(0, 0, 0, 0))

    def poly(pts, color):
        fill(color)
        p.drawPolygon([QPointF(a, b) for a, b in pts])

    def text(t, rect, size, color, family="Consolas"):
        f = QFont(family)
        f.setBold(True)
        f.setPixelSize(size)
        p.setFont(f)
        p.setPen(color)
        p.drawText(QRectF(*rect), Qt.AlignCenter, t)

    if k == "terminal":  # белое окно, тёмная шапка, «>_» цветом плитки
        shadow_rr(18, 24, 64, 54, 10)
        rr(18, 24, 64, 54, 10, W)
        fill(acc)
        top = QPainterPath()
        top.addRoundedRect(QRectF(18, 24, 64, 14), 10, 10)
        top.addRect(QRectF(18, 31, 64, 7))
        p.drawPath(top.simplified())
        for i, cx in enumerate((26, 33, 40)):
            fill(QColor(255, 255, 255, 170 - i * 40))
            p.drawEllipse(QPointF(cx, 31), 2.3, 2.3)
        stroke(acc, 6)
        path = QPainterPath(QPointF(29, 48))
        path.lineTo(QPointF(39, 56))
        path.lineTo(QPointF(29, 64))
        p.drawPath(path)
        p.drawLine(QPointF(45, 66), QPointF(62, 66))
    elif k == "cmd":  # окно консоли с «C:\>» и курсором
        shadow_rr(16, 24, 68, 54, 10)
        rr(16, 24, 68, 54, 10, QColor(255, 255, 255, 38))
        stroke(QColor(255, 255, 255, 120), 2)
        p.drawRoundedRect(QRectF(16, 24, 68, 54), 10, 10)
        text("C:\\>", (16, 30, 68, 34), 21, W)
        rr(56, 60, 14, 5, 2, QColor("#36e07a"))
    elif k == "powershell":  # белая плашка-шеврон и курсор
        poly([(24, 30), (54, 50), (24, 70), (24, 60), (40, 50), (24, 40)], QColor(0, 0, 0, 0))
        p.translate(0, -2.5)
        poly([(24, 30), (54, 50), (24, 70), (24, 60), (40, 50), (24, 40)], W)
        rr(52, 64, 26, 8, 4, W)
        p.translate(0, 2.5)
    elif k == "taskmgr":  # белая карточка с графиком нагрузки
        shadow_rr(16, 22, 68, 56, 12)
        rr(16, 22, 68, 56, 12, W)
        stroke(QColor(acc.red(), acc.green(), acc.blue(), 50), 1.5)
        for gy in (38, 50, 62):
            p.drawLine(QPointF(22, gy), QPointF(78, gy))
        area = QPainterPath(QPointF(22, 66))
        pts = [(22, 58), (32, 58), (39, 40), (47, 66), (55, 48), (62, 54), (78, 54)]
        for a, b in pts:
            area.lineTo(QPointF(a, b))
        area.lineTo(QPointF(78, 70))
        area.lineTo(QPointF(22, 70))
        fill(QColor(acc.red(), acc.green(), acc.blue(), 45))
        p.drawPath(area)
        stroke(acc, 4.5)
        line = QPainterPath(QPointF(*pts[0]))
        for a, b in pts[1:]:
            line.lineTo(QPointF(a, b))
        p.drawPath(line)
    elif k == "devmgmt":  # микросхема: ножки, корпус, ядро
        fill(W2)
        for t in (36, 46, 56):
            p.drawRoundedRect(QRectF(t, 16, 8, 14), 2, 2)
            p.drawRoundedRect(QRectF(t, 70, 8, 14), 2, 2)
            p.drawRoundedRect(QRectF(16, t, 14, 8), 2, 2)
            p.drawRoundedRect(QRectF(70, t, 14, 8), 2, 2)
        shadow_rr(27, 27, 46, 46, 9)
        rr(27, 27, 46, 46, 9, W)
        rr(39, 39, 22, 22, 5, acc)
        rr(43, 43, 6, 6, 2, QColor(255, 255, 255, 120))
    elif k == "network":  # Wi-Fi: дуги разной яркости и точка
        for i, (rad, col) in enumerate(((34, W3), (23, W2), (12, W))):
            stroke(col, 8)
            p.drawArc(QRectF(50 - rad, 66 - rad, 2 * rad, 2 * rad), 45 * 16, 90 * 16)
        fill(W)
        p.drawEllipse(QPointF(50, 66), 6.5, 6.5)
    elif k == "adapters":  # два монитора, соединённые кабелем
        stroke(W2, 4)
        p.drawLine(QPointF(32, 54), QPointF(32, 66))
        p.drawLine(QPointF(68, 54), QPointF(68, 66))
        p.drawLine(QPointF(32, 66), QPointF(68, 66))
        p.drawLine(QPointF(50, 66), QPointF(50, 78))
        rr(40, 76, 20, 6, 3, W)
        for x0 in (14, 50):
            shadow_rr(x0, 24, 36, 28, 6)
            rr(x0, 24, 36, 28, 6, W)
            rr(x0 + 5, 29, 26, 18, 3, acc)
    elif k == "regedit":  # три объёмных кубика
        def cube(cx, cy, s):
            top = [(cx, cy - s), (cx + s, cy - s / 2), (cx, cy), (cx - s, cy - s / 2)]
            left = [(cx - s, cy - s / 2), (cx, cy), (cx, cy + s), (cx - s, cy + s / 2)]
            right = [(cx + s, cy - s / 2), (cx, cy), (cx, cy + s), (cx + s, cy + s / 2)]
            poly(left, QColor(255, 255, 255, 215))
            poly(right, QColor(255, 255, 255, 160))
            poly(top, W)
            stroke(QColor(acc.red(), acc.green(), acc.blue(), 90), 1.2)
            p.drawLine(QPointF(cx, cy), QPointF(cx, cy + s))
        cube(50, 36, 14)
        cube(35, 62, 14)
        cube(65, 62, 14)
    elif k == "services":  # залитая шестерёнка с отверстием
        gear = QPainterPath()
        n = 8
        pts = []
        for i in range(n * 2):
            a = math.pi * i / n
            rad = 34 if i % 2 == 0 else 26
            for da in (-0.17, 0.17):
                pts.append(QPointF(50 + math.cos(a + da) * rad, 50 + math.sin(a + da) * rad))
        gear.moveTo(pts[0])
        for q in pts[1:]:
            gear.lineTo(q)
        gear.closeSubpath()
        hole = QPainterPath()
        hole.addEllipse(QPointF(50, 50), 10, 10)
        shape = gear.subtracted(hole)
        fill(QColor(0, 0, 0, 0))
        p.drawPath(shape.translated(0, 2.5))
        fill(W)
        p.drawPath(shape)
        stroke(QColor(acc.red(), acc.green(), acc.blue(), 110), 3)
        p.drawEllipse(QPointF(50, 50), 18, 18)
    elif k == "control":  # три ползунка с ручками
        for y0, kx in ((30, 62), (50, 36), (70, 54)):
            rr(18, y0 - 3, 64, 6, 3, W3)
            rr(18, y0 - 3, kx - 18, 6, 3, W)
            fill(QColor(0, 0, 0, 0))
            p.drawEllipse(QPointF(kx, y0 + 2), 9, 9)
            fill(W)
            p.drawEllipse(QPointF(kx, y0), 9, 9)
            fill(acc)
            p.drawEllipse(QPointF(kx, y0), 3.5, 3.5)
    elif k == "disks":  # объёмный цилиндр с полосами
        body = QPainterPath()
        body.addRect(QRectF(22, 32, 56, 38))
        bottom = QPainterPath()
        bottom.addEllipse(QRectF(22, 60, 56, 20))
        cyl = body.united(bottom)
        fill(QColor(0, 0, 0, 0))
        p.drawPath(cyl.translated(0, 2.5))
        fill(QColor(255, 255, 255, 220))
        p.drawPath(cyl)
        stroke(QColor(acc.red(), acc.green(), acc.blue(), 120), 2.5)
        p.drawArc(QRectF(22, 44, 56, 20), 180 * 16, 180 * 16)
        fill(W)
        p.drawEllipse(QRectF(22, 22, 56, 20))
        fill(acc)
        p.drawEllipse(QPointF(64, 66), 3, 3)
    elif k == "events":  # документ с загнутым углом и «!»
        doc = QPainterPath(QPointF(26, 18))
        doc.lineTo(QPointF(60, 18))
        doc.lineTo(QPointF(74, 32))
        doc.lineTo(QPointF(74, 82))
        doc.lineTo(QPointF(26, 82))
        doc.closeSubpath()
        fill(QColor(0, 0, 0, 0))
        p.drawPath(doc.translated(0, 2.5))
        fill(W)
        p.drawPath(doc)
        poly([(60, 18), (74, 32), (60, 32)], QColor(255, 255, 255, 150))
        rr(46, 36, 8, 26, 4, acc)
        fill(acc)
        p.drawEllipse(QPointF(50, 71), 4.5, 4.5)
    elif k == "run":  # окно и стрелка наружу
        shadow_rr(18, 30, 50, 50, 10)
        rr(18, 30, 50, 50, 10, QColor(255, 255, 255, 60))
        stroke(W, 5)
        p.drawRoundedRect(QRectF(18, 30, 50, 50), 10, 10)
        stroke(W, 7)
        p.drawLine(QPointF(44, 56), QPointF(76, 24))
        poly([(56, 20), (82, 18), (80, 44)], W)
    elif k == "msinfo":  # белый круг с «i» цветом плитки
        fill(QColor(0, 0, 0, 0))
        p.drawEllipse(QPointF(50, 52.5), 32, 32)
        fill(W)
        p.drawEllipse(QPointF(50, 50), 32, 32)
        fill(acc)
        p.drawEllipse(QPointF(50, 35), 5, 5)
        p.drawRoundedRect(QRectF(45.5, 44, 9, 24), 4, 4)
    elif k == "sound":  # залитый динамик и волны
        spk = [(18, 40), (32, 40), (50, 24), (50, 76), (32, 60), (18, 60)]
        poly([(a, b + 2.5) for a, b in spk], QColor(0, 0, 0, 0))
        poly(spk, W)
        stroke(W, 6)
        p.drawArc(QRectF(46, 36, 20, 28), -55 * 16, 110 * 16)
        stroke(W2, 6)
        p.drawArc(QRectF(46, 24, 34, 52), -55 * 16, 110 * 16)
    elif k == "apps":  # четыре плитки, одна — цветом плитки
        for i, (x0, y0) in enumerate(((20, 20), (54, 20), (20, 54), (54, 54))):
            shadow_rr(x0, y0, 26, 26, 7)
            rr(x0, y0, 26, 26, 7, W if i != 1 else QColor(255, 255, 255, 140))
        rr(60, 26, 14, 14, 4, acc)
    elif k == "env":  # бирка с «{x}»
        shadow_rr(16, 30, 68, 40, 12)
        rr(16, 30, 68, 40, 12, W)
        text("{x}", (16, 30, 68, 40), 24, acc)
    elif k == "power":  # залитая вилка
        rr(36, 14, 7, 18, 3, W)
        rr(57, 14, 7, 18, 3, W)
        plug = QPainterPath(QPointF(28, 30))
        plug.lineTo(QPointF(72, 30))
        plug.lineTo(QPointF(72, 46))
        plug.cubicTo(QPointF(72, 60), QPointF(62, 66), QPointF(50, 66))
        plug.cubicTo(QPointF(38, 66), QPointF(28, 60), QPointF(28, 46))
        plug.closeSubpath()
        fill(QColor(0, 0, 0, 0))
        p.drawPath(plug.translated(0, 2.5))
        fill(W)
        p.drawPath(plug)
        rr(46, 64, 8, 20, 4, W)
        poly([(52, 36), (44, 50), (50, 50), (47, 60), (56, 45), (50, 45)], acc)
    elif k == "startup":  # стрелка вверх над полкой
        rr(20, 74, 60, 8, 4, W2)
        arrow = [(50, 16), (74, 42), (60, 42), (60, 66), (40, 66), (40, 42), (26, 42)]
        poly([(a, b + 2.5) for a, b in arrow], QColor(0, 0, 0, 0))
        poly(arrow, W)
