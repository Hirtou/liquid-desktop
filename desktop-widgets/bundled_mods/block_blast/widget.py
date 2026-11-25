"""Мод «Блокбаст» для Liquid Desktop (API 1): головоломка 8×8 — ставь фигуры, собирай линии и взрывай их."""
import math
import random
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QPixmap

import lang
from core import DesktopWidget, activity, config, grid
from widgets import kit

# свои переводы: общий lang_en.json программы мод не трогает
EN = {"Блокбаст": "Block Blast", "Головоломка: ставь фигуры и взрывай линии": "Puzzle: place pieces and blast lines",
      "Обычный": "Regular", "Закрепить": "Pin", "Открепить": "Unpin", "Новая игра": "New game", "Рекорд": "Best",
      "Комбо": "Combo", "Отлично!": "Great!", "Полная очистка!": "Board clear!", "Вы проиграли!": "Game over!",
      "Новый рекорд!": "New best!", "Новая игра сейчас начнётся…": "New game starting…"}


def tr(text):
    return EN.get(text, text) if lang.LANG == "en" else text

N = 8
OVER_SECONDS = 3.0
PALETTE = [("#ff7a95", "#e0245e"), ("#ffbf5e", "#f2742d"), ("#ffe770", "#eaa800"), ("#6af0b4", "#0f9d68"),
           ("#6fd0ff", "#1c6fe0"), ("#b39bff", "#6438e0"), ("#ff86e6", "#bd22a4")]

RAW = [
    ["X"], ["XX"], ["X", "X"], ["XXX"], ["X", "X", "X"], ["XXXX"], ["X", "X", "X", "X"], ["XXXXX"], ["X", "X", "X", "X", "X"],
    ["XX", "XX"], ["XXX", "XXX", "XXX"], ["XXX", "XXX"], ["XX", "XX", "XX"],
    ["X.", "XX"], [".X", "XX"], ["XX", "X."], ["XX", ".X"],
    ["X..", "X..", "XXX"], ["..X", "..X", "XXX"], ["XXX", "X..", "X.."], ["XXX", "..X", "..X"],
    ["X.", "X.", "XX"], [".X", ".X", "XX"], ["XX", "X.", "X."], ["XX", ".X", ".X"],
    ["XXX", ".X."], [".X.", "XXX"], ["X.", "XX", "X."], [".X", "XX", ".X"],
    [".XX", "XX."], ["XX.", ".XX"], ["X.", "XX", ".X"], [".X", "XX", "X."],
]
WEIGHT = {1: 0.5, 2: 2.0, 3: 3.0, 4: 3.0, 5: 2.0, 6: 1.5, 9: 1.0}


def parse(rows):
    return [(r, c) for r, line in enumerate(rows) for c, ch in enumerate(line) if ch == "X"]


SHAPES = [parse(r) for r in RAW]
SHAPE_W = [WEIGHT.get(len(s), 1.0) for s in SHAPES]


def size_of(cells):
    return max(r for r, _ in cells) + 1, max(c for _, c in cells) + 1


def ease_out_back(t):
    t = max(0.0, min(1.0, t)) - 1
    return 1 + 2.7 * t ** 3 + 1.7 * t ** 2


def ease_out(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


_pix = {}
_fonts = {}
_dpr = [1.0]  # чёткость экрана, на котором рисуем сейчас (клетки — сразу в нужном размере, без пересчёта)


def label(p, rect, value, color, size=12, family="Segoe UI", align=Qt.AlignLeft | Qt.AlignVCenter):
    """Как kit.text, но шрифт не создаётся заново на каждую надпись в каждом кадре."""
    f = _fonts.get((size, family))
    if f is None:
        f = _fonts[(size, family)] = kit.font(size, family)
    p.setFont(f)
    p.setPen(color)
    p.drawText(rect, align, value)


def cell_pix(col, px):
    key = (col, int(px), _dpr[0])
    pm = _pix.get(key)
    if pm is None:
        if len(_pix) > 200:  # меняли размер виджета — старые размеры не копить
            _pix.clear()
        s = max(8, round(int(px) * _dpr[0]))
        pm = QPixmap(s, s)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHints(QPainter.Antialiasing)
        top, bot = PALETTE[col]
        box = QRectF(2, 2, s - 4, s - 4)
        g = QLinearGradient(box.topLeft(), box.bottomLeft())
        g.setColorAt(0, QColor(top))
        g.setColorAt(1, QColor(bot))
        rad = s * 0.24
        p.setPen(QPen(QColor(255, 255, 255, 80), 2))
        p.setBrush(g)
        p.drawRoundedRect(box, rad, rad)
        p.setPen(Qt.NoPen)
        shine = QLinearGradient(box.topLeft(), QPointF(box.left(), box.center().y()))
        shine.setColorAt(0, QColor(255, 255, 255, 120))
        shine.setColorAt(1, QColor(255, 255, 255, 0))
        p.setBrush(shine)
        p.drawRoundedRect(QRectF(box.left() + s * 0.08, box.top() + s * 0.06, box.width() - s * 0.16, box.height() * 0.46),
                          rad * 0.7, rad * 0.7)
        p.end()
        _pix[key] = pm
    return pm


class BlockBlastWidget(DesktopWidget):
    key = "blockblast"
    title = tr("Блокбаст")
    description = tr("Головоломка: ставь фигуры и взрывай линии")
    SHAPES = {"tall": (tr("Обычный"), grid(2, 3))}

    def __init__(self, **kw):
        super().__init__(**kw)
        self.apply_shape()
        self.grid = [[-1] * N for _ in range(N)]
        self.pieces = [None, None, None]
        self.spawn = [0.0, 0.0, 0.0]
        self.score = 0
        self.shown = 0.0
        self.combo = 0
        self.over = False
        self.over_t0 = 0.0
        self.pop = {}
        self.fading = []
        self.parts = []
        self.floats = []
        self.shake_t0 = -9.0
        self.shake_amp = 0.0
        self.flash_t0 = -9.0
        self.flash_col = None
        self.drag = None
        self.ret = None
        self.anim = QTimer(self, interval=16, timeout=self.tick)
        self.anim.setTimerType(Qt.PreciseTimer)
        self._tick_at = time.monotonic()
        self._bg_key, self._bg = None, None
        self.load()

    def jelly_busy(self):
        """Пока тащат фигуру или она едет обратно — «Желе» не гнёт виджет: иначе каждый кадр — снимок
        всего виджета, и фигура дёргается."""
        return self.drag is not None or self.ret is not None


    def load(self):
        st = self.cfg.get("bb")
        try:
            g = st["g"]
            self.grid = [[int(g[r * N + c]) for c in range(N)] for r in range(N)]
            self.pieces = [None if p is None else (int(p[0]), int(p[1])) for p in st["p"]]
            assert len(self.pieces) == 3 and all(p is None or (0 <= p[0] < len(SHAPES) and 0 <= p[1] < len(PALETTE)) for p in self.pieces)
            self.score, self.combo = int(st["s"]), int(st.get("c", 0))
        except Exception:
            self.new_game(save=False)
            return
        self.shown = float(self.score)
        if all(p is None for p in self.pieces):
            self.deal()
        self.check_over(immediate=True)

    def save(self):
        self.cfg["bb"] = {"g": [v for row in self.grid for v in row], "p": [None if p is None else list(p) for p in self.pieces],
                          "s": self.score, "c": self.combo}
        config.save()

    def new_game(self, save=True):
        self.grid = [[-1] * N for _ in range(N)]
        self.score = 0
        self.shown = 0.0
        self.combo = 0
        self.over = False
        self.pop, self.fading, self.parts, self.floats = {}, [], [], []
        self.drag = self.ret = None
        self.deal()
        if save:
            self.save()
        self.go()

    def add_actions(self, menu):
        menu.addAction(tr("Открепить") if self.pinned_on() else tr("Закрепить"), self.toggle_pin)
        menu.addAction(tr("Новая игра"), self.new_game)

    def best(self):
        return int(self.cfg.get("best", 0))


    def fits(self, cells, r0, c0):
        g = self.grid
        for dr, dc in cells:
            r, c = r0 + dr, c0 + dc
            if not (0 <= r < N and 0 <= c < N) or g[r][c] >= 0:
                return False
        return True

    def fits_anywhere(self, cells):
        h, w = size_of(cells)
        return any(self.fits(cells, r, c) for r in range(N - h + 1) for c in range(N - w + 1))

    def deal(self):
        now = time.monotonic()
        for _ in range(40):
            idx = random.choices(range(len(SHAPES)), SHAPE_W, k=3)
            if any(self.fits_anywhere(SHAPES[i]) for i in idx):
                break
        cols = random.sample(range(len(PALETTE)), 3)
        self.pieces = [(idx[i], cols[i]) for i in range(3)]
        self.spawn = [now + i * 0.09 for i in range(3)]

    def check_over(self, immediate=False):
        left = [p for p in self.pieces if p]
        if left and not any(self.fits_anywhere(SHAPES[p[0]]) for p in left) and not self.over:
            self.over = True
            self.over_t0 = time.monotonic() + (0.0 if immediate else 0.7)
            best = self.best()
            if self.score > best:
                self.cfg["best"] = self.score
                config.save()
            # табличка проигрыша выезжает за 0.5 с и дальше стоит — кадры не нужны, новую игру начнёт таймер
            QTimer.singleShot(max(0, int((self.over_t0 + OVER_SECONDS - time.monotonic()) * 1000)) + 30, self.over_done)
            self.go()

    def over_done(self):
        if self.over and time.monotonic() >= self.over_t0 + OVER_SECONDS:
            self.new_game()

    def lines_if(self, cells, r0, c0):
        occ = {(r, c) for r in range(N) for c in range(N) if self.grid[r][c] >= 0}
        occ |= {(r0 + dr, c0 + dc) for dr, dc in cells}
        rows = [r for r in range(N) if all((r, c) in occ for c in range(N))]
        cols = [c for c in range(N) if all((r, c) in occ for r in range(N))]
        return rows, cols

    def put(self, i, r0, c0):
        shape, col = self.pieces[i]
        cells = SHAPES[shape]
        now = time.monotonic()
        for dr, dc in cells:
            self.grid[r0 + dr][c0 + dc] = col
            self.pop[(r0 + dr, c0 + dc)] = now
        self.pieces[i] = None
        rows = [r for r in range(N) if all(self.grid[r][c] >= 0 for c in range(N))]
        cols = [c for c in range(N) if all(self.grid[r][c] >= 0 for r in range(N))]
        lines = len(rows) + len(cols)
        gain = len(cells)
        board = self.board_rect()
        cell = board.width() / N
        if lines:
            clear = {(r, c) for r in rows for c in range(N)} | {(r, c) for c in cols for r in range(N)}
            cr = r0 + (max(d[0] for d in cells) + 1) / 2
            cc = c0 + (max(d[1] for d in cells) + 1) / 2
            for r, c in clear:
                v = self.grid[r][c]
                delay = math.hypot(r + 0.5 - cr, c + 0.5 - cc) * 0.035
                self.fading.append((r, c, v, now + delay))
                self.grid[r][c] = -1
                self.pop.pop((r, c), None)
                cx, cy = board.left() + (c + 0.5) * cell, board.top() + (r + 0.5) * cell
                for _ in range(4):
                    a = random.uniform(0, math.tau)
                    sp = random.uniform(90, 300)
                    self.parts.append([cx, cy, math.cos(a) * sp, math.sin(a) * sp - 60, now + delay,
                                       random.uniform(0.5, 0.95), v, random.uniform(3.0, 6.5), random.uniform(-6, 6)])
            self.combo += 1
            mult = 1.0 + 0.5 * (self.combo - 1)
            gain += int(10 * lines * lines * mult)
            self.shake_t0, self.shake_amp = now, min(9.0, 3.0 + 2.0 * lines)
            self.flash_t0, self.flash_col = now, PALETTE[col][0]
            mid = QPointF(board.center().x(), board.top() + board.height() * 0.4)
            self.floats.append([f"+{gain}", mid.x(), mid.y(), now, 30 if lines < 3 else 38, PALETTE[col][0]])
            if self.combo > 1:
                self.floats.append([tr("Комбо") + f" ×{self.combo}", mid.x(), mid.y() - 38, now + 0.08, 22, "#ffd86b"])
            if lines >= 3:
                self.floats.append([tr("Отлично!"), mid.x(), mid.y() + 40, now + 0.12, 22, "#ffffff"])
            if all(self.grid[r][c] < 0 for r in range(N) for c in range(N)):
                gain += 120
                self.floats.append([tr("Полная очистка!") + " +120", mid.x(), mid.y() + 74, now + 0.25, 20, "#6af0b4"])
        else:
            self.combo = 0
        self.score += gain
        if self.score > self.best():
            self.cfg["best"] = self.score
        if all(p is None for p in self.pieces):
            self.deal()
        self.check_over()
        self.save()
        self.go()


    def board_rect(self):
        r = QRectF(self.card())
        cell = (r.width() - 32) / N
        return QRectF(r.left() + 16, r.top() + 68, cell * N, cell * N)

    def slot_rect(self, i):
        r = QRectF(self.card())
        b = self.board_rect()
        top = b.bottom() + 12
        h = r.bottom() - 12 - top
        w = b.width() / 3
        return QRectF(b.left() + i * w, top, w, h)

    def tray_cell(self):
        return min(23.0, (self.slot_rect(0).width() + 6) / 5)

    def piece_rect(self, i, cell, scale=1.0):
        h, w = size_of(SHAPES[self.pieces[i][0]])
        s = self.slot_rect(i)
        pw, ph = w * cell * scale, h * cell * scale
        return QRectF(s.center().x() - pw / 2, s.center().y() - ph / 2, pw, ph)


    def pinned_on(self):
        return bool(self.cfg.get("locked", False))

    def toggle_pin(self):
        self.cfg["locked"] = not self.pinned_on()
        config.save()
        self.update()

    def pin_rect(self):
        r = QRectF(self.card())
        return QRectF(r.right() - 46, r.top() + 16, 30, 30)

    def click(self, pos):
        now = time.monotonic()
        if self.pin_rect().adjusted(-4, -4, 4, 4).contains(pos):
            self.toggle_pin()
            return True
        if self.over and now > self.over_t0 + 0.4:
            self.new_game()
            return True
        if self.over:
            return True
        for i, p in enumerate(self.pieces):
            if p and now >= self.spawn[i] + 0.2 and self.slot_rect(i).adjusted(-2, -6, 2, 6).contains(pos):
                self.drag = {"i": i, "pos": QPointF(pos), "t0": now}
                self.go()
                return True
        return self.pinned_on()

    def mouseMoveEvent(self, event):
        if self.drag is not None:
            self.drag["pos"] = QPointF(event.position() / self.scale())
            self.update()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.drag is None or event.button() != Qt.LeftButton:
            super().mouseReleaseEvent(event)
            return
        d, self.drag = self.drag, None
        target = self.target(d)
        if target is not None:
            self.put(d["i"], *target)
        else:
            x, y, s = self.drag_geom(d)
            self.ret = {"i": d["i"], "from": (x, y, s), "t0": time.monotonic()}
            self.go()
        self.update()

    def drag_geom(self, d):
        shape = SHAPES[self.pieces[d["i"]][0]]
        h, w = size_of(shape)
        cell = self.board_rect().width() / N
        tc = self.tray_cell()
        k = tc / cell + (1 - tc / cell) * ease_out(min(1.0, (time.monotonic() - d["t0"]) / 0.14))
        pos = d["pos"]
        return pos.x() - w * cell * k / 2, pos.y() - h * cell * k - 16 * k, k

    def target(self, d):
        shape = SHAPES[self.pieces[d["i"]][0]]
        b = self.board_rect()
        cell = b.width() / N
        x, y, k = self.drag_geom(d)
        cc, cr = (x - b.left()) / cell, (y - b.top()) / cell
        best, bd = None, 1.25
        for r in range(math.floor(cr) - 1, math.floor(cr) + 3):
            for c in range(math.floor(cc) - 1, math.floor(cc) + 3):
                dist = (r - cr) ** 2 + (c - cc) ** 2
                if dist < bd and self.fits(shape, r, c):
                    best, bd = (r, c), dist
        return best


    def go(self):
        if not self.anim.isActive():
            self._tick_at = time.monotonic()
            self.anim.start()
        self.update()

    def animating(self, now):
        if self.drag is not None or self.ret is not None or self.fading or self.parts or self.floats:
            return True
        if abs(self.score - self.shown) > 0.5:
            return True
        if now - self.shake_t0 < 0.5 or now - self.flash_t0 < 0.5:
            return True
        if self.over and now < self.over_t0 + 0.6:
            return True
        if any(now < s + 0.45 for s in self.spawn):
            return True
        return any(now - t < 0.3 for t in self.pop.values())

    def tick(self):
        now = time.monotonic()
        dt = min(max(now - self._tick_at, 0.001), 0.05)
        self._tick_at = now
        self.shown += (self.score - self.shown) * 0.22
        if abs(self.score - self.shown) < 0.6:
            self.shown = float(self.score)
        self.fading = [f for f in self.fading if now - f[3] < 0.5]
        alive = []
        for pt in self.parts:
            if now < pt[4]:
                alive.append(pt)
                continue
            if now - pt[4] < pt[5]:
                pt[0] += pt[2] * dt
                pt[1] += pt[3] * dt
                pt[3] += 760 * dt
                pt[2] *= 0.985
                alive.append(pt)
        self.parts = alive
        if self.over and now > self.over_t0 + OVER_SECONDS:
            self.new_game()
            return
        self.floats = [f for f in self.floats if now - f[3] < 1.1]
        self.pop = {k: t for k, t in self.pop.items() if now - t < 0.3}
        if self.ret is not None and now - self.ret["t0"] > 0.2:
            self.ret = None
        if not self.animating(now):
            self.anim.stop()
        if not activity.paused(self):
            self.update()


    def draw_piece(self, p, shape, col, x, y, cell, alpha=1.0, pop_scale=1.0):
        p.setOpacity(alpha)
        for dr, dc in shape:
            cx, cy = x + dc * cell + cell / 2, y + dr * cell + cell / 2
            half = cell / 2 * pop_scale
            p.drawPixmap(QRectF(cx - half, cy - half, half * 2, half * 2), cell_pix(col, max(8, round(cell))), QRectF(cell_pix(col, max(8, round(cell))).rect()))
        p.setOpacity(1.0)

    def board_bg(self, b, cell, fg, track):
        """Подложка поля и 64 пустые клетки — одна готовая картинка (раньше — 65 скруглений в каждом кадре)."""
        dpr = self.devicePixelRatioF()
        key = (round(b.width(), 2), fg.rgba(), track.rgba(), dpr)
        if key != self._bg_key:
            pm = QPixmap(max(1, round((b.width() + 10) * dpr)), max(1, round((b.height() + 10) * dpr)))
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.transparent)
            q = QPainter(pm)
            q.setRenderHints(QPainter.Antialiasing)
            q.setPen(Qt.NoPen)
            q.setBrush(QColor(fg.red(), fg.green(), fg.blue(), 16))
            q.drawRoundedRect(QRectF(0, 0, b.width() + 10, b.height() + 10), 16, 16)
            q.setBrush(track)
            for rr in range(N):
                for cc in range(N):
                    q.drawRoundedRect(QRectF(5 + cc * cell + 2, 5 + rr * cell + 2, cell - 4, cell - 4), cell * 0.2, cell * 0.2)
            q.end()
            self._bg_key, self._bg = key, pm
        return self._bg

    def paintEvent(self, event):
        super().paintEvent(event)
        now = time.monotonic()
        _dpr[0] = self.devicePixelRatioF()
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        r = QRectF(self.card())
        fg, dim, track = kit.ink(self)
        b = self.board_rect()
        cell = b.width() / N


        label(p, QRectF(r.left() + 18, r.top() + 12, 150, 14), tr("Блокбаст").upper(), dim, 11, "Segoe UI Semibold")
        label(p, QRectF(r.left() + 18, r.top() + 24, 190, 38), f"{round(self.shown)}", fg, 32, "Bahnschrift SemiBold")
        best = max(self.best(), self.score)
        label(p, QRectF(r.right() - 206, r.top() + 12, 150, 14), tr("Рекорд").upper(), dim, 11, "Segoe UI Semibold", Qt.AlignRight | Qt.AlignVCenter)
        label(p, QRectF(r.right() - 206, r.top() + 28, 150, 28), f"{best}", QColor("#ffc93c"), 22, "Bahnschrift SemiBold", Qt.AlignRight | Qt.AlignVCenter)


        pr = self.pin_rect()
        on = self.pinned_on()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#ffc93c") if on else track)
        p.drawEllipse(pr)
        ink_c = QColor("#3a2a00") if on else dim
        p.save()
        p.translate(pr.center())
        p.rotate(35 if not on else 0)
        p.setPen(QPen(ink_c, 2.2, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(0, 1), QPointF(0, 9))
        p.setPen(Qt.NoPen)
        p.setBrush(ink_c)
        p.drawRoundedRect(QRectF(-5, -9, 10, 6), 2, 2)
        p.drawRoundedRect(QRectF(-3, -4, 6, 6), 1.5, 1.5)
        p.drawRoundedRect(QRectF(-6.5, 1.2, 13, 2.4), 1.2, 1.2)
        p.restore()


        sh = 0.0
        if now - self.shake_t0 < 0.45:
            k = 1 - (now - self.shake_t0) / 0.45
            sh = math.sin((now - self.shake_t0) * 70) * self.shake_amp * k * k
        p.save()
        p.translate(sh, -sh * 0.4)
        p.setPen(Qt.NoPen)
        p.drawPixmap(QPointF(b.left() - 5, b.top() - 5), self.board_bg(b, cell, fg, track))


        ghost, hot = None, set()
        if self.drag is not None:
            t = self.target(self.drag)
            if t is not None:
                shape, col = self.pieces[self.drag["i"]]
                rows, cols = self.lines_if(SHAPES[shape], *t)
                hot = {(rr, c) for rr in rows for c in range(N)} | {(rr, c) for c in cols for rr in range(N)}
                ghost = (shape, col, t)
        over_k = 0.0
        if self.over and now > self.over_t0:
            over_k = min(1.0, (now - self.over_t0) / 0.5)
        for rr in range(N):
            for cc in range(N):
                v = self.grid[rr][cc]
                if v < 0:
                    continue
                s = 1.0
                if (rr, cc) in self.pop:
                    s = 0.78 + 0.22 * ease_out_back((now - self.pop[(rr, cc)]) / 0.28) + 0.0
                if (rr, cc) in hot:
                    s = 1.0 + 0.04 * math.sin(now * 14)
                half = cell / 2 * s
                cx, cy = b.left() + (cc + 0.5) * cell, b.top() + (rr + 0.5) * cell
                pm = cell_pix(v, round(cell))
                p.setOpacity(1.0 - 0.55 * over_k)
                p.drawPixmap(QRectF(cx - half, cy - half, half * 2, half * 2), pm, QRectF(pm.rect()))
                if (rr, cc) in hot:
                    p.setOpacity(0.35 + 0.15 * math.sin(now * 14))
                    p.setBrush(QColor(255, 255, 255))
                    p.drawRoundedRect(QRectF(cx - half + 2, cy - half + 2, half * 2 - 4, half * 2 - 4), cell * 0.2, cell * 0.2)
                p.setOpacity(1.0)
        if ghost is not None:
            shape, col, (gr, gc) = ghost
            for dr, dc in SHAPES[shape]:
                cx, cy = b.left() + (gc + dc + 0.5) * cell, b.top() + (gr + dr + 0.5) * cell
                pm = cell_pix(col, round(cell))
                p.setOpacity(0.5)
                p.drawPixmap(QRectF(cx - cell / 2, cy - cell / 2, cell, cell), pm, QRectF(pm.rect()))
            p.setOpacity(1.0)


        for rr, cc, v, t0 in self.fading:
            a = (now - t0) / 0.4
            if a < 0 or a >= 1:
                if a < 0:
                    cx, cy = b.left() + (cc + 0.5) * cell, b.top() + (rr + 0.5) * cell
                    pm = cell_pix(v, round(cell))
                    p.drawPixmap(QRectF(cx - cell / 2, cy - cell / 2, cell, cell), pm, QRectF(pm.rect()))
                continue
            cx, cy = b.left() + (cc + 0.5) * cell, b.top() + (rr + 0.5) * cell
            s = (1.0 + 0.25 * math.sin(min(1.0, a * 2.2) * math.pi)) * (1 - ease_out(a) ** 1.4 * 0.98)
            p.save()
            p.translate(cx, cy)
            p.rotate(a * 120)
            half = cell / 2 * s
            pm = cell_pix(v, round(cell))
            p.setOpacity(max(0.0, 1.0 - a * 0.7))
            p.drawPixmap(QRectF(-half, -half, half * 2, half * 2), pm, QRectF(pm.rect()))
            p.setOpacity(max(0.0, 0.9 - a * 1.6))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255))
            p.drawRoundedRect(QRectF(-half + 2, -half + 2, half * 2 - 4, half * 2 - 4), cell * 0.2, cell * 0.2)
            p.restore()
        p.restore()


        p.setPen(Qt.NoPen)
        for x, y, vx, vy, t0, life, v, size, spin in self.parts:
            a = (now - t0) / life
            if a < 0 or a >= 1:
                continue
            col = QColor(PALETTE[v][0])
            col.setAlphaF(max(0.0, 1.0 - a * a))
            p.save()
            p.translate(x + sh, y)
            p.rotate(a * spin * 60)
            p.setBrush(col)
            sz = size * (1.0 - 0.5 * a)
            p.drawRoundedRect(QRectF(-sz, -sz, sz * 2, sz * 2), sz * 0.4, sz * 0.4)
            p.restore()


        if self.flash_col and now - self.flash_t0 < 0.4:
            c = QColor(self.flash_col)
            c.setAlphaF(0.22 * (1 - (now - self.flash_t0) / 0.4))
            p.setBrush(c)
            p.drawRoundedRect(b.adjusted(-5, -5, 5, 5), 16, 16)


        tc = self.tray_cell()
        for i, pc in enumerate(self.pieces):
            if not pc:
                continue
            if self.drag is not None and self.drag["i"] == i:
                continue
            shape, col = SHAPES[pc[0]], pc[1]
            k = ease_out_back((now - self.spawn[i]) / 0.4) if now < self.spawn[i] + 0.4 else 1.0
            if now < self.spawn[i]:
                continue
            if self.ret is not None and self.ret["i"] == i:
                a = ease_out((now - self.ret["t0"]) / 0.2)
                fx, fy, fk = self.ret["from"]
                pr = self.piece_rect(i, tc)
                x = fx + (pr.left() - fx) * a
                y = fy + (pr.top() - fy) * a
                cb = self.board_rect().width() / N * fk
                self.draw_piece(p, shape, col, x, y, cb + (tc - cb) * a)
                continue
            pr = self.piece_rect(i, tc, max(0.01, k))
            self.draw_piece(p, shape, col, pr.left(), pr.top() + (1 - min(k, 1.0)) * 40, tc * max(0.01, k), min(1.0, k * 1.4))


        if self.drag is not None:
            shape, col = SHAPES[self.pieces[self.drag["i"]][0]], self.pieces[self.drag["i"]][1]
            x, y, k = self.drag_geom(self.drag)
            cell0 = b.width() / N
            p.setPen(Qt.NoPen)
            h, w = size_of(shape)
            self.draw_piece(p, shape, col, x, y, cell0 * k)


        for text, x, y, t0, size, color in self.floats:
            a = (now - t0) / 1.0
            if a < 0 or a >= 1:
                continue
            f = ease_out(a)
            c = QColor(color)
            c.setAlphaF(min(1.0, (1 - a) * 2.2))
            pop = 1.0 + 0.35 * math.sin(min(1.0, a * 3) * math.pi) if a < 0.33 else 1.0
            p.save()
            p.translate(x + sh, y - 46 * f)
            p.scale(pop, pop)
            label(p, QRectF(-150, -22, 300, 44), text, QColor(0, 0, 0, int(90 * c.alphaF())), size, "Bahnschrift SemiBold", Qt.AlignCenter)
            p.translate(0, -1.5)
            label(p, QRectF(-150, -22, 300, 44), text, c, size, "Bahnschrift SemiBold", Qt.AlignCenter)
            p.restore()


        if over_k > 0:
            p.setPen(Qt.NoPen)
            panel = QRectF(b.center().x() - 110, b.center().y() - 64, 220, 128)
            p.setOpacity(over_k)
            p.setBrush(QColor(15, 16, 22, 240))
            p.drawRoundedRect(panel, 22, 22)
            white, grey = QColor("#ffffff"), QColor(255, 255, 255, 150)
            label(p, QRectF(panel.left(), panel.top() + 12, panel.width(), 24), tr("Вы проиграли!"), white, 18, "Segoe UI Semibold", Qt.AlignCenter)
            label(p, QRectF(panel.left(), panel.top() + 38, panel.width(), 40), f"{self.score}", QColor("#ffc93c"), 34, "Bahnschrift SemiBold", Qt.AlignCenter)
            new = self.score >= self.best() and self.score > 0
            label(p, QRectF(panel.left(), panel.top() + 80, panel.width(), 16), tr("Новый рекорд!") if new else tr("Рекорд") + f": {self.best()}", grey, 12, align=Qt.AlignCenter)
            label(p, QRectF(panel.left(), panel.top() + 100, panel.width(), 18), tr("Новая игра сейчас начнётся…"), white, 12, "Segoe UI Semibold", Qt.AlignCenter)
            p.setOpacity(1.0)
