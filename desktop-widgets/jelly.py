"""Эффект «Желе» — встроенный мод (вкладка «Моды» → «Желе»): карточка виджета пружинит, как желе.

Как устроено: карточка — сетка узлов, каждый узел сдвигается сам, картинка виджета натягивается на сетку
(кусочками, у каждого своя перспектива). Три силы, у каждой своя пружина:
- бугор: курсор у края — край выпирает к нему мягким бугром (только около курсора, а не весь край);
- нажатие: карточка чуть проминается к пальцу;
- инерция: тащишь — дальняя от пальца часть отстаёт, отпустил — карточка колышется и успокаивается.
Идея и первая физика — от автора мода; core.DesktopWidget зовёт jelly_* (см. там). Картинка виджета
снимается в таймере желе (не во время перерисовки окна — так Qt не даёт), в покое виджет рисуется как обычно."""
import math
import time

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QCursor, QPainter, QPixmap, QPolygonF, QRegion, QTransform
from PySide6.QtWidgets import QApplication, QWidget

ID = "jelly"
NAME, NAME_EN = "Желе", "Jelly"
DESCRIPTION = "Виджеты пружинят, как желе: тянутся к курсору, проминаются от нажатия и колышутся, когда их тащишь"
DESCRIPTION_EN = "Widgets wobble like jelly: they reach for the cursor, squish when pressed and jiggle when dragged"
AUTHOR = "velzevul02"
AUTHOR_URL = ""

# Настройки (подобраны по кадрам, см. scratchpad jelly_lab). K — жёсткость пружины, Z — затухание (0..1:
# меньше — дольше колышется). Все расстояния — в точках виджета при размере 100 %.
P = {
    "rest": 1.2,          # курсор замер у края дольше стольких секунд — бугор мягко опадает (и не рисуем зря)
    "near": 34.0,         # с какого расстояния до края курсор начинает тянуть
    "bulge": 6.0,         # насколько край выпирает к курсору
    "bulge_width": 0.55,  # ширина бугра — доля длины края
    "bulge_depth": 0.55,  # как глубоко бугор уходит внутрь карточки — доля её размера
    "bulge_k": 230.0, "bulge_z": 0.38,
    "track_k": 520.0, "track_z": 0.95,   # бугор едет за курсором вдоль края
    "press": 0.045,       # нажатие: доля, на которую карточка сжимается к пальцу
    "press_k": 320.0, "press_z": 0.42,
    "lag": 0.6,           # инерция: доля сдвига окна, на которую дальняя часть отстаёт
    "lag_max": 22.0,      # предел отставания
    "lag_k": 180.0, "lag_z": 0.3,
    "lag_pow": 1.35,      # как быстро отставание растёт от пальца к дальнему краю
    "squash": 0.2,       # растянуло по ходу — поперёк чуть сжимается (объём сохраняется)
    "grid": 10,           # клеток сетки по стороне карточки, когда есть бугор (он узкий — нужна мелкая)
    "grid_soft": 6,       # без бугра: нажатие и инерция плавные — хватает крупной сетки (кадр дешевле)
}


def enabled():
    import core  # здесь, а не вверху: core сам импортирует этот модуль
    return bool(core.config.section("app").get("jelly", True))


def set_enabled(on):
    import core
    core.config.section("app")["jelly"] = bool(on)
    core.config.save()


def _spring(st, target, k, z, h):
    """Пружина st = [x, v] к target: жёсткость k, затухание z (доля от критического)."""
    c = 2 * z * math.sqrt(k)
    st[1] += (k * (target - st[0]) - c * st[1]) * h
    st[0] += st[1] * h


def _smooth(t):
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


class JellyMixin:

    def jelly_init(self):
        self._jb = {s: [0.0, 0.0] for s in "rlbt"}     # бугор у каждой стороны: [высота, скорость]
        self._jt = {s: [0.0, 0.0] for s in "rlbt"}     # где бугор вдоль стороны: [место, скорость]
        self._jpress = [0.0, 0.0]
        self._jlag = [[0.0, 0.0], [0.0, 0.0]]          # отставание по x и y: [сдвиг, скорость]
        self._jelly_xf = None    # не None — карточка изогнута (core рисует через jelly_paint)
        self._jelly_mesh = None  # узлы сетки: (xs, ys, сдвиги)
        self._jelly_at = time.monotonic()
        self._jelly_painting = False
        self._jelly_pix = None    # картинка виджета для кадров с изгибом
        self._jelly_snap_at = 0.0
        self._jelly_last_pos = None
        self._grab = None
        self._jelly_cur, self._jelly_cur_at = None, 0.0  # где курсор был и когда последний раз двигался
        self._jelly_timer = QTimer(self, interval=16, timeout=self._jelly_tick)
        self._jelly_timer.setTimerType(Qt.PreciseTimer)

    def jelly_ok(self):
        """Этому виджету можно пружинить? Не превью в каталоге и не «под ярлыками»."""
        return not getattr(self, "preview", False) and not getattr(self, "pinned", None)

    def _jelly_kids(self):
        """Дочерние окна (надписи, поля ввода у виджетов из готовых подписей Qt)."""
        return [c for c in self.findChildren(QWidget, options=Qt.FindDirectChildrenOnly) if not c.isWindow()]

    def _jelly_hold_kids(self, hold):
        """Пока карточка изогнута, дочерние окна сами не рисуются (иначе ровная копия поверх изогнутой —
        двоилось бы): они уже в снимке и гнутся вместе с ним."""
        for c in self._jelly_kids():
            if c.updatesEnabled() == hold:
                c.setUpdatesEnabled(not hold)

    def jelly_busy(self):
        """Виджет сам что-то тащит внутри себя (фигуру в игре и т. п.) — пока не гнуть. Виджеты и моды
        переопределяют; по умолчанию — нет."""
        return False

    def jelly_on(self):
        return enabled() and self.jelly_ok() and not self.jelly_busy()

    def jelly_kick(self):
        """Что-то произошло (курсор вошёл, нажали, окно поехало) — запустить расчёт."""
        if not hasattr(self, "_jelly_timer"):
            return
        if not self._jelly_timer.isActive() and (self.jelly_on() or self._jelly_xf is not None):
            self._jelly_at = time.monotonic()
            self._jelly_timer.start()

    def jelly_press(self, local):
        self._grab = QPointF(local) * self.scale()
        self.jelly_kick()

    def jelly_release(self):
        self._jelly_last_pos = None
        self.jelly_kick()  # _grab оставляем: колышется вокруг места, где держали

    def jelly_moved(self, pos):
        """Окно сдвинулось, пока его тащат: содержимое по инерции остаётся на месте и пружиной догоняет палец."""
        if self._drag is None or not self.jelly_on():
            self._jelly_last_pos = None
            return
        if self._jelly_last_pos is not None:
            d = pos - self._jelly_last_pos
            lim = P["lag_max"] * self.scale()
            for st, dd in ((self._jlag[0], d.x()), (self._jlag[1], d.y())):
                st[0] -= dd * P["lag"]
                st[0] = lim * math.tanh(st[0] / lim)  # мягкий предел — не рвётся при резком рывке
        self._jelly_last_pos = QPoint(pos)
        self.jelly_kick()

    # ---------- картинка

    def jelly_snapshot(self):
        """Картинка виджета для кадров с изгибом. Снимается в таймере желе, а не во время перерисовки окна:
        render() того же окна внутри его перерисовки ломает рисование («Painter not active»)."""
        dpr = self.devicePixelRatioF()
        pix = QPixmap(max(1, int(self.width() * dpr)), max(1, int(self.height() * dpr)))
        pix.setDevicePixelRatio(dpr)
        pix.fill(Qt.transparent)
        held = [c for c in self._jelly_kids() if not c.updatesEnabled()]
        for c in held:  # в снимок дочерние окна попадают, только если им можно рисоваться
            c.setUpdatesEnabled(True)
        self._jelly_painting = True
        try:
            self.render(pix, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
        finally:
            self._jelly_painting = False
            for c in held:
                c.setUpdatesEnabled(False)
        self._jelly_pix = pix
        self._jelly_snap_at = time.monotonic()

    def jelly_paint(self, painter=None):
        """Перерисовка окна, пока карточка пружинит: картинку — кусочками на изогнутую сетку. -> True, если нарисовали."""
        if self._jelly_xf is None or self._jelly_painting or self._jelly_pix is None or self._jelly_mesh is None:
            return False
        p = painter or QPainter(self)
        if not p.isActive():
            return False
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        # кусочки лежат чуть внахлёст (иначе между ними щели); на полупрозрачном (стекло, поля ввода) нахлёст
        # смешивался бы дважды — светлые линии сетки. «Замена» вместо смешивания: нахлёст — тот же цвет
        mode = p.compositionMode()
        p.setCompositionMode(QPainter.CompositionMode_Source)
        pix, dpr = self._jelly_pix, self._jelly_pix.devicePixelRatio()
        xs, ys, disp = self._jelly_mesh
        W, H = self.width(), self.height()
        for j in range(len(ys) - 1):
            for i in range(len(xs) - 1):
                x0, x1, y0, y1 = xs[i], xs[i + 1], ys[j], ys[j + 1]
                if x1 - x0 < 0.5 or y1 - y0 < 0.5:
                    continue
                src = QRectF(x0, y0, x1 - x0, y1 - y0)
                d00, d10, d01, d11 = disp[j][i], disp[j][i + 1], disp[j + 1][i], disp[j + 1][i + 1]
                if max(abs(d00[0] - d[0]) + abs(d00[1] - d[1]) for d in (d10, d01, d11)) < 0.04:
                    # клетка не изогнута, только сдвинута — простое копирование (в разы дешевле перспективы)
                    pad = src.adjusted(-0.5 if x0 > 0 else 0, -0.5 if y0 > 0 else 0,
                                       0.5 if x1 < W else 0, 0.5 if y1 < H else 0)
                    p.resetTransform()
                    p.drawPixmap(pad.translated(d00[0], d00[1]), pix,
                                 QRectF(pad.x() * dpr, pad.y() * dpr, pad.width() * dpr, pad.height() * dpr))
                    continue
                quad = QPolygonF([QPointF(x0 + disp[j][i][0], y0 + disp[j][i][1]),
                                  QPointF(x1 + disp[j][i + 1][0], y0 + disp[j][i + 1][1]),
                                  QPointF(x1 + disp[j + 1][i + 1][0], y1 + disp[j + 1][i + 1][1]),
                                  QPointF(x0 + disp[j + 1][i][0], y1 + disp[j + 1][i][1])])
                t = QTransform()
                if not QTransform.quadToQuad(QPolygonF(src), quad, t):
                    continue
                # кусочки чуть внахлёст (полточки) — между ними не просвечивают швы
                pad = src.adjusted(-0.5 if x0 > 0 else 0, -0.5 if y0 > 0 else 0,
                                   0.5 if x1 < W else 0, 0.5 if y1 < H else 0)
                p.setTransform(t)
                p.drawPixmap(pad, pix, QRectF(pad.x() * dpr, pad.y() * dpr, pad.width() * dpr, pad.height() * dpr))
        p.resetTransform()
        p.setCompositionMode(mode)
        if painter is None:
            p.end()
        return True

    # ---------- расчёт

    def jelly_step(self, dt, pos):
        """Один шаг физики на dt секунд; pos — курсор в точках окна. -> сдвинут ли хоть один узел."""
        k = self.scale()
        c = QRectF(self.card())
        c = QRectF(c.x() * k, c.y() * k, c.width() * k, c.height() * k)
        if self.jelly_busy():  # внутри тащат — изгиб убрать сразу, без угасания (каждый его кадр — снимок виджета)
            for b in self._jb.values():
                b[:] = [0.0, 0.0]
            self._jpress[:] = [0.0, 0.0]
            for st in self._jlag:
                st[:] = [0.0, 0.0]
            self._jelly_mesh = None
            return False
        on = self.jelly_on() and self.isVisible()
        now = time.monotonic()
        cur = (round(pos.x()), round(pos.y()))
        if cur != self._jelly_cur:
            self._jelly_cur, self._jelly_cur_at = cur, now
        # «держат» — только пока левая кнопка и правда зажата: отпускание могла забрать кнопка внутри окна,
        # и _drag остался бы навсегда — карточка так и стояла бы промятой
        held = bool(QApplication.mouseButtons() & Qt.LeftButton)
        live = on and (self._drag is None or not held) and now - self._jelly_cur_at < P["rest"]
        near = P["near"] * k
        cx, cy = c.center().x(), c.center().y()
        # курсор у края: (сторона, расстояние до края снаружи (+) / внутри (-), где вдоль края)
        sides = {"r": (pos.x() - c.right(), pos.y(), c.top(), c.bottom()),
                 "l": (c.left() - pos.x(), pos.y(), c.top(), c.bottom()),
                 "b": (pos.y() - c.bottom(), pos.x(), c.left(), c.right()),
                 "t": (c.top() - pos.y(), pos.x(), c.left(), c.right())}
        targets = {}
        for s, (d, along, a0, a1) in sides.items():
            w = 0.0
            if live and a0 - near < along < a1 + near:
                w = _smooth(1 - abs(d) / near) if abs(d) < near else 0.0
                w *= _smooth(1 - max(0.0, a0 - along, along - a1) / near)  # за углом — слабее
            targets[s] = (P["bulge"] * k * w, min(max(along, a0), a1))
        press_target = P["press"] if on and self._drag is not None and held else 0.0
        steps = max(1, math.ceil(dt / 0.004))
        h = dt / steps
        for _ in range(steps):
            for s, (amp, along) in targets.items():
                _spring(self._jb[s], amp, P["bulge_k"], P["bulge_z"], h)
                if amp > 0:  # бугор едет за курсором; пока его нет — стоит, где был (чтобы не съезжал при угасании)
                    _spring(self._jt[s], along, P["track_k"], P["track_z"], h)
            _spring(self._jpress, press_target, P["press_k"], P["press_z"], h)
            for st in self._jlag:
                _spring(st, 0.0, P["lag_k"], P["lag_z"], h)
        for s, (amp, along) in targets.items():  # бугор появился впервые — сразу под курсором
            if amp > 0 and abs(self._jb[s][0]) < 0.05 and abs(self._jb[s][1]) < 1:
                self._jt[s] = [along, 0.0]
        # тихо — всё в ноль, изгиба нет
        quiet = all(abs(b[0]) < 0.03 and abs(b[1]) < 0.5 for b in self._jb.values()) and \
            abs(self._jpress[0]) < 0.0005 and abs(self._jpress[1]) < 0.01 and \
            all(abs(st[0]) < 0.05 and abs(st[1]) < 0.8 for st in self._jlag) and \
            all(t[0] == 0 for t in targets.values()) and press_target == 0
        if quiet:
            for b in self._jb.values():
                b[:] = [0.0, 0.0]
            self._jpress[:] = [0.0, 0.0]
            for st in self._jlag:
                st[:] = [0.0, 0.0]
            if self._drag is None:
                self._grab = None
            self._jelly_mesh = None
            return False
        self._jelly_mesh = self.jelly_mesh(c)
        return True

    def jelly_mesh(self, c):
        """Узлы сетки (по всему окну: поле тени — крайние клетки) и сдвиг каждого узла."""
        bulges = [(s, self._jb[s][0], self._jt[s][0]) for s in "rlbt" if abs(self._jb[s][0]) > 0.01]
        n = int(P["grid"] if bulges else P["grid_soft"])
        W, H = self.width(), self.height()
        xs = [0.0] + [c.left() + c.width() * i / n for i in range(n + 1)] + [float(W)]
        ys = [0.0] + [c.top() + c.height() * i / n for i in range(n + 1)] + [float(H)]
        cx, cy, hw, hh = c.center().x(), c.center().y(), c.width() / 2, c.height() / 2
        g = self._grab if self._grab is not None else QPointF(cx, cy)
        lx, ly = self._jlag[0][0], self._jlag[1][0]
        lag_len = math.hypot(lx, ly)
        far = max(math.hypot(px - g.x(), py - g.y()) for px in (c.left(), c.right()) for py in (c.top(), c.bottom()))
        pr = self._jpress[0]
        bw, bd = P["bulge_width"], P["bulge_depth"]
        disp = []
        for y in ys:
            row = []
            vy = min(max(y, c.top()), c.bottom())  # узлы в поле тени двигаются вместе с краем карточки
            for x in xs:
                vx = min(max(x, c.left()), c.right())
                dx = dy = 0.0
                for s, amp, at in bulges:
                    if s in "rl":
                        t = (vy - at) / (bw * c.height())
                        inside = (c.right() - vx) if s == "r" else (vx - c.left())
                        depth = _smooth(1 - inside / (bd * c.width()))
                        dx += (amp if s == "r" else -amp) * math.exp(-t * t * 1.6) * depth
                    else:
                        t = (vx - at) / (bw * c.width())
                        inside = (c.bottom() - vy) if s == "b" else (vy - c.top())
                        depth = _smooth(1 - inside / (bd * c.height()))
                        dy += (amp if s == "b" else -amp) * math.exp(-t * t * 1.6) * depth
                if pr:  # нажатие: к пальцу
                    dx += (g.x() - vx) * pr
                    dy += (g.y() - vy) * pr
                if lag_len > 0.01:  # инерция: чем дальше от пальца, тем сильнее отстаёт
                    w = (math.hypot(vx - g.x(), vy - g.y()) / far) ** P["lag_pow"] if far else 0.0
                    dx += lx * w
                    dy += ly * w
                    # объём: вытянуло вдоль отставания — поперёк к оси через палец чуть сжимается
                    ux, uy = lx / lag_len, ly / lag_len
                    rx, ry = vx - g.x(), vy - g.y()
                    across = -rx * uy + ry * ux
                    sq = P["squash"] * lag_len / max(hw, hh) * w
                    dx -= -uy * across * sq
                    dy -= ux * across * sq
                row.append((dx, dy))
            disp.append(row)
        return xs, ys, disp

    def _jelly_tick(self):
        now = time.monotonic()
        dt = min(max(now - self._jelly_at, 0.001), 1 / 20)
        self._jelly_at = now
        pos = QPointF(self.mapFromGlobal(QCursor.pos()))
        was = self._jelly_xf is not None
        prev = self._jelly_mesh
        moving = self.jelly_step(dt, pos)
        # замерло (курсор стоит у края, бугор дотянулся): сетка почти не меняется — кадр не нужен,
        # только картинку виджета обновить раз в 0.1 с (стрелки, цифры) и таймер — реже
        still = moving and was and prev is not None and self._jelly_mesh is not None and             len(prev[0]) == len(self._jelly_mesh[0]) and self._drag is None and             max(abs(a[0] - b[0]) + abs(a[1] - b[1]) for ra, rb in zip(prev[2], self._jelly_mesh[2])
                for a, b in zip(ra, rb)) < 0.03
        if still:
            self._jelly_mesh = prev
            if self._jelly_timer.interval() != 50:
                self._jelly_timer.setInterval(50)
            if now - self._jelly_snap_at > 0.1:
                self._jelly_xf = None
                self.jelly_snapshot()
                self._jelly_xf = True
                self.update()
            return
        if self._jelly_timer.interval() != 16:
            self._jelly_timer.setInterval(16)
        if moving and (self._jelly_pix is None or not was or now - self._jelly_snap_at > 0.04):
            self._jelly_xf = None  # снимок — обычный виджет, без изгиба
            self.jelly_snapshot()
        self._jelly_xf = True if moving else None
        if moving and not was:
            self._jelly_hold_kids(True)
        if not moving:
            self._jelly_pix = None
            if was:
                self._jelly_hold_kids(False)
        if moving or was:
            self.update()
        if not moving:
            if not self.rect().contains(pos.toPoint()) and self._drag is None:
                self._jelly_timer.stop()
            elif self._jelly_timer.interval() != 60:
                self._jelly_timer.setInterval(60)  # курсор над виджетом, но не у края — следить реже
