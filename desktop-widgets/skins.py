# Liquid Desktop — © 2026 Hirtou (https://github.com/Hirtou) · MIT License
"""Темы оформления: оттенок стекла, кромка, свечение и цвет акцента — для всех виджетов сразу.

Тема хранится в config["app"]["skin"]. Цвета акцента — общие объекты QColor (ACCENT, ACCENT2): виджеты берут их
при импорте (BLUE = skins.ACCENT), а смена темы перекрашивает эти же объекты на месте — поэтому всё меняется
без перезапуска, достаточно перерисовать.

«Liquid» — как было до тем: стекло считается по настройкам «Размытие» и «Замутнение», синий акцент.
Тёмные темы (Ночь, Неон, Закат, Минимал) включают тёмное стекло на любых обоях.
Файл одинаковый у виджетов и острова (остров берёт id темы из config.json виджетов)."""
import colorsys
import os

import numpy as np
from PySide6.QtGui import QColor

from lang import tr


def _load_rust():
    """Rust-модуль стекла (liquid_glass.*.pyd) с функцией glow. Лежит у виджетов; остров ищет его в соседней
    папке виджетов. Нет модуля / старый без glow / LIQUID_NO_RUST=1 — свечение считает numpy, как раньше."""
    if os.environ.get("LIQUID_NO_RUST"):
        return None
    import importlib
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    for folder in (here, os.path.join(os.path.dirname(here), "виджеты"),
                   os.path.join(os.path.dirname(here), "desktop-widgets")):
        added = False
        try:
            if folder != here and folder not in sys.path and os.path.isdir(folder):
                sys.path.append(folder)
                added = True
            mod = importlib.import_module("liquid_glass")
            if hasattr(mod, "glow"):
                return mod
            return None
        except Exception:
            if added:
                sys.path.remove(folder)
    return None


_rust = _load_rust()

# id: название, подпись, оттенок стекла, размытие, замутнение, кромка (цвет, яркость 0..1, толщина),
#     свечение вокруг карточки, акцент, второй акцент (светлее, для градиентов колец), тёмное стекло
SKINS = {
    "liquid": dict(name="Liquid", sub=tr("как сейчас"), tint=None, blur=None, haze=None, rim=None, glow=None,
                   accent="#2f6bff", accent2="#36c6ff", dark=None),
    "night": dict(name=tr("Ночь"), sub=tr("плотное, холодное"), tint=("#0b1020", 0.55), blur=6, haze=30,
                  rim=("#9ab8ff", 0.55, 1.0), glow=None, accent="#5fa8ff", accent2="#9fd0ff", dark=True),
    # неоновая трубка: тонкая яркая кромка и мягкий размытый ореол (не кольца), стекло тёмное, но не чёрное
    "neon": dict(name=tr("Неон"), sub=tr("светящаяся кромка"), tint=("#0d0820", 0.42), blur=4, haze=20,
                 rim=("grad", "#4fe8ff", "#d76bff", 0.9, 1.4), glow=("grad", "#38dcff", "#c45cff"),
                 accent="#38dcff", accent2="#c45cff", dark=True),
    "sunset": dict(name=tr("Закат"), sub=tr("тёплый градиент"), tint=("grad", "#ff7a3d", "#c2367a", 0.40),
                   blur=2, haze=-10, rim=("#ffc49a", 0.8, 1.0), glow=None, accent="#ff7f50", accent2="#ffc15c",
                   dark=True),
    "sakura": dict(name=tr("Сакура"), sub=tr("розовый оттенок"), tint=("#ff8fb8", 0.30), blur=2, haze=-20,
                   rim=("#ffd0e2", 0.8, 1.0), glow=None, accent="#ff5f9a", accent2="#ffa3c4", dark=None),
    "forest": dict(name=tr("Лес"), sub=tr("зелёное, матовое"), tint=("#2f6b3a", 0.38), blur=5, haze=10,
                   rim=("#bff5c8", 0.6, 1.0), glow=None, accent="#3fcf7f", accent2="#9df0b8", dark=None),
    "minimal": dict(name=tr("Минимал"), sub=tr("без размытия, плоское"), tint=("#1c1c20", 0.86), blur=0, haze=0,
                    rim=("#ffffff", 0.18, 1.0), glow=None, accent="#8c8c96", accent2="#c4c4cc", dark=True),
    "auto": dict(name=tr("Авто"), sub=tr("цвет из обоев"), tint=("auto", 0.40), blur=3, haze=0,
                 rim=("auto", 0.8, 1.0), glow=None, accent="auto", accent2="auto", dark=None),
    # своя тема: цвета берутся из config["app"]["custom_skin"] (см. CUSTOM_DEFAULT, set_custom)
    "custom": dict(name=tr("Кастомная"), sub=tr("свои цвета и свечение"), tint=("custom",), blur=None, haze=None,
                   rim=("custom",), glow=None, accent="custom", accent2="custom", dark=True),
}
ORDER = ["liquid", "night", "neon", "sunset", "sakura", "forest", "minimal", "auto", "custom"]

# Своя тема. Цвет — "#RRGGBBAA" (как в CSS). Градиент: вид (linear/radial), угол (как в CSS: 0 — снизу вверх,
# 90 — слева направо) и точки [цвет, место 0..100].
# Свечение: horizontal — слева один цвет, справа другой; vertical — сверху и снизу; cross — 4 цвета
# (сверху, справа, снизу, слева).
CUSTOM_DEFAULT = dict(
    glow=True, layout="horizontal", glow_size=50,
    glow_colors=["#c8c8d2ff", "#8a8a96ff", "#c8c8d2ff", "#8a8a96ff"],
    fill=dict(kind="linear", angle=135, stops=[["#3a3a42d0", 0], ["#24242ad0", 100]]),
    rim=dict(kind="linear", angle=180, stops=[["#e6e6eeff", 0], ["#9a9aa6ff", 100]]),
    accent=dict(kind="linear", angle=90, stops=[["#8c8c96ff", 0], ["#c4c4ccff", 100]]),
)
_custom = None  # своя тема сейчас (словарь как CUSTOM_DEFAULT)
_glow_size = 50  # «Размер свечения» встроенной темы со свечением (у каждой свой, config app.glow_sizes; 50 — как было)


def glow_size_of(app, skin_id):
    """Размер свечения встроенной темы из настроек виджетов (раздел app) -> 0..100, по умолчанию 50."""
    sizes = app.get("glow_sizes") if isinstance(app, dict) else None
    v = sizes.get(skin_id, 50) if isinstance(sizes, dict) else 50
    return max(0, min(100, v)) if isinstance(v, int) and not isinstance(v, bool) else 50


def has_glow(skin_id=None):
    """У темы есть свечение вокруг карточки? (у своей — если включено в редакторе)"""
    sid = skin_id or _current
    if sid == "custom":
        return bool((_custom or custom_spec())["glow"])
    return bool(SKINS.get(sid, {}).get("glow"))
FILL_MAX = 0.42  # заливка своей темы сильнее не бывает: под ней должно оставаться живое стекло


def custom_spec(spec=None):
    """Своя тема с подставленными недостающими полями (старый или битый конфиг не роняет программу)."""
    import copy
    out = copy.deepcopy(CUSTOM_DEFAULT)
    if isinstance(spec, dict):
        for k in out:
            if k in spec and type(spec[k]) is type(out[k]):
                out[k] = copy.deepcopy(spec[k])
    if out["layout"] not in ("horizontal", "vertical", "cross"):
        out["layout"] = "horizontal"
    out["glow_size"] = max(0, min(100, out["glow_size"]))
    while len(out["glow_colors"]) < 4:
        out["glow_colors"].append("#ffffffff")
    for key in ("fill", "rim", "accent"):
        g = out[key]
        if g.get("kind") not in ("linear", "radial"):
            g["kind"] = "linear"
        try:
            g["angle"] = int(g.get("angle", 90)) % 360
            g["stops"] = sorted(([str(c), max(0, min(100, int(at)))] for c, at in g["stops"]), key=lambda s: s[1])
        except Exception:
            g.update(copy.deepcopy(CUSTOM_DEFAULT[key]))
        if not g["stops"]:
            g["stops"] = copy.deepcopy(CUSTOM_DEFAULT[key]["stops"])
        if len(g["stops"]) > 6:  # старый конфиг с сотней точек (спамили «+») — оставить 6 через равные шаги
            st = g["stops"]
            g["stops"] = [st[round(i * (len(st) - 1) / 5)] for i in range(6)]
    return out


def rgba(s):
    """"#RRGGBBAA" / "#RRGGBB" -> QColor (у Qt 8 знаков — это #AARRGGBB, поэтому разбираем сами)."""
    h = str(s).lstrip("#")
    try:
        if len(h) == 8:
            return QColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16))
        if len(h) == 6:
            return QColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        pass
    return QColor(255, 255, 255)


def hex_rgba(c):
    """QColor -> "#RRGGBBAA"."""
    return "#%02x%02x%02x%02x" % (c.red(), c.green(), c.blue(), c.alpha())


def _stops(g):
    return [(at / 100.0, rgba(c)) for c, at in sorted(g["stops"], key=lambda s: s[1])]


def qt_gradient(g, rect, alpha=1.0):
    """Градиент своей темы кистью Qt на прямоугольник rect (alpha — общий множитель прозрачности)."""
    import math
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QLinearGradient, QRadialGradient
    c = rect.center()
    if g["kind"] == "radial":
        q = QRadialGradient(c, max(1.0, math.hypot(rect.width(), rect.height()) / 2))
    else:
        a = math.radians(g["angle"])
        dx, dy = math.sin(a), -math.cos(a)
        half = (abs(rect.width() * dx) + abs(rect.height() * dy)) / 2
        q = QLinearGradient(QPointF(c.x() - dx * half, c.y() - dy * half), QPointF(c.x() + dx * half, c.y() + dy * half))
    for at, col in _stops(g):
        col.setAlpha(int(col.alpha() * alpha))
        q.setColorAt(at, col)
    return q


def gradient_array(g, w, h):
    """Градиент своей темы по пикселям: (h·w, 4) float32, RGBA 0..255 — для оттенка стекла."""
    import math
    xs = np.arange(w, dtype=np.float32)[None, :] + 0.5 - w / 2
    ys = np.arange(h, dtype=np.float32)[:, None] + 0.5 - h / 2
    if g["kind"] == "radial":
        t = np.sqrt(xs ** 2 + ys ** 2) / max(1.0, math.hypot(w, h) / 2)
    else:
        a = math.radians(g["angle"])
        dx, dy = math.sin(a), -math.cos(a)
        half = max(1e-3, (abs(w * dx) + abs(h * dy)) / 2)
        t = (xs * dx + ys * dy) / (2 * half) + 0.5
    t = np.clip(t, 0, 1).reshape(-1)
    st = _stops(g)
    at = np.array([s[0] for s in st], np.float32)
    out = np.empty((t.size, 4), np.float32)
    for i, ch in enumerate(("red", "green", "blue", "alpha")):
        out[:, i] = np.interp(t, at, np.array([getattr(s[1], ch)() for s in st], np.float32))
    return out


def glow_layout(force=False):
    """Раскладка свечения своей темы: (вид, [цвета]) или None — у остальных тем свечение сверху вниз.
    force — даже если сейчас включена другая тема (карточка своей темы в каталоге)."""
    c = _custom or custom_spec()
    if (_current != "custom" and not force) or not c["glow"]:
        return None
    return c["layout"], [rgba(x) for x in c["glow_colors"]]


def custom_dark(spec):
    """Своя тема тёмная, если заливка тёмная (иначе текст на светлой заливке — тёмный, как в светлых темах)."""
    st = _stops(spec["fill"])
    return sum(c.lightnessF() for _, c in st) / len(st) < 0.55

ACCENT = QColor("#2f6bff")    # общий акцент: кнопки, кольца, галочки, полоски
ACCENT2 = QColor("#36c6ff")   # светлая пара к акценту (второй конец градиента у колец)
version = 0                   # меняется при каждой смене темы — по нему виджеты сбрасывают свои кэши
_current = "liquid"
_auto = None                  # (оттенок стекла, акцент, акцент2) из обоев для темы «Авто»


def current():
    return SKINS[_current]


def current_id():
    return _current


def _hex(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], np.float32)


def _wallpaper_path():
    """Обои Windows (как glass._wallpaper_path — своя копия: этот файл общий у виджетов и острова)."""
    import ctypes
    buf = ctypes.create_unicode_buffer(520)
    ctypes.windll.user32.SystemParametersInfoW(0x73, 520, buf, 0)  # SPI_GETDESKWALLPAPER
    if buf.value and os.path.exists(buf.value):
        return buf.value
    cached = os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Themes\TranscodedWallpaper")
    return cached if os.path.exists(cached) else ""


_wall_cache = {}   # (путь, время изменения) -> результат: чтение и сжатие обоев ~80 мс, а зовут часто (превью)


def _from_wallpaper():
    """Средний цвет обоев -> насыщенный оттенок стекла и акцент того же тона. Живые обои не прочесть — None.
    Обои читаются один раз, пока файл не сменился."""
    path = _wallpaper_path()
    if not path:
        return None
    try:
        key = (path, os.path.getmtime(path))
    except OSError:
        return None
    if key not in _wall_cache:
        _wall_cache.clear()
        _wall_cache[key] = _read_wallpaper(path)
    return _wall_cache[key]


def _read_wallpaper(path):
    try:
        from PySide6.QtGui import QImage
        img = QImage(path)
        if img.isNull():
            return None
        img = img.scaled(64, 36).convertToFormat(QImage.Format_RGB888)
        a = np.frombuffer(img.constBits(), np.uint8).reshape(36, img.bytesPerLine())[:, :64 * 3].reshape(-1, 3)
        r, g, b = a.astype(np.float32).mean(axis=0) / 255
    except Exception:
        return None
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    tint = np.array(colorsys.hls_to_rgb(h, 0.30, min(1, s * 1.8 + 0.2)), np.float32) * 255
    acc = QColor.fromRgbF(*colorsys.hls_to_rgb(h, 0.58, 0.85))
    acc2 = QColor.fromRgbF(*colorsys.hls_to_rgb(h, 0.75, 0.9))
    return tint, acc, acc2


def apply(skin_id, custom=None, glow_size=50):
    """Включить тему: перекрасить общие цвета акцента. Виджеты после этого нужно перерисовать (см. main).
    custom — настройки своей темы (config["app"]["custom_skin"]); glow_size — размер свечения встроенной темы
    (glow_size_of: config["app"]["glow_sizes"]), у своей темы он свой, в custom."""
    global _current, version, _auto, _custom, _glow_size
    _current = skin_id if skin_id in SKINS else "liquid"
    _custom = custom_spec(custom)
    _glow_size = max(0, min(100, glow_size)) if isinstance(glow_size, int) and not isinstance(glow_size, bool) else 50
    _grad_cache.clear()
    s = SKINS[_current]
    s_custom = SKINS["custom"]
    s_custom["dark"] = True if custom_dark(_custom) else None
    s_custom["glow"] = ("grad", "#ffffff", "#ffffff") if _custom["glow"] else None
    if s["accent"] == "custom":
        st = _stops(_custom["accent"])
        acc, acc2 = st[0][1], st[-1][1]
    elif s["accent"] == "auto":
        _auto = _from_wallpaper()
        acc, acc2 = (_auto[1], _auto[2]) if _auto else (QColor("#2f6bff"), QColor("#36c6ff"))
    else:
        acc, acc2 = QColor(s["accent"]), QColor(s["accent2"])
    ACCENT.setRgb(acc.red(), acc.green(), acc.blue())
    ACCENT2.setRgb(acc2.red(), acc2.green(), acc2.blue())
    version += 1


def theme(cfg_theme):
    """Светлое/тёмное стекло с учётом темы: тёмные темы всегда тёмные, остальные — как выбрано у виджета."""
    return "dark" if current()["dark"] else cfg_theme


BLUR_DEFAULT, HAZE_DEFAULT, HAZE_MIN = 6, 50, -50  # ползунки «Размытие» / «Замутнение» по умолчанию (как в glass)


def glass_params(blur, haze):
    """Размытие и замутнение с учётом темы. У Liquid и своей темы — ровно из настроек. У остальных тем свой
    характер (Минимал плоский, Ночь плотная), но ползунки двигают и их: раньше тема подставляла свои числа,
    и «Размытие» / «Замутнение» в темах ничего не меняли. Сдвиг ползунка от значения по умолчанию
    прибавляется к числу темы."""
    s = current()
    blur = BLUR_DEFAULT if blur is None else blur
    haze = HAZE_DEFAULT if haze is None else haze
    if s["blur"] is not None:
        blur = max(0, min(10, s["blur"] + blur - BLUR_DEFAULT))
    if s["haze"] is not None:
        haze = max(HAZE_MIN, min(100, s["haze"] + haze - HAZE_DEFAULT))
    return blur, haze


_grad_cache = {}


def tint_params(w, h):
    """Оттенок темы для стекла w×h: (m, add) — rgb·m >> 6 + add; (-1, None) — без оттенка.
    add — int16: 3 числа или по пикселю (h*w*3, градиент «Заката»). Его же берёт Rust-модуль стекла."""
    t = current()["tint"]
    if not t:
        return -1, None
    if t[0] == "custom":
        g = _custom["fill"]
        key = (w, h, "custom", repr(g))
        hit = _grad_cache.get(key)
        if hit is None:
            arr = gradient_array(g, w, h)
            # непрозрачность 100% — самый сильный оттенок, но стекло всё равно просвечивает (FILL_MAX): со
            # сплошной заливкой акрил пропадал — карточки становились плоскими цветными плашками
            a = arr[:, 3:4] / 255 * FILL_MAX
            k = float(a.mean())
            hit = (k, (arr[:, :3] * a).astype(np.int16))
            if len(_grad_cache) > 64:
                _grad_cache.clear()
            _grad_cache[key] = hit
        k, add = hit
        return int(round((1 - k) * 64)), add
    if t[0] == "grad":
        k = t[3]
        key = (w, h, t[1], t[2], k)
        add = _grad_cache.get(key)
        if add is None:
            f = (np.linspace(0, 1, w, dtype=np.float32)[None, :] * 0.5 +
                 np.linspace(0, 1, h, dtype=np.float32)[:, None] * 0.5).reshape(-1, 1)
            add = ((_hex(t[1]) * (1 - f) + _hex(t[2]) * f) * k).astype(np.int16)
            if len(_grad_cache) > 64:
                _grad_cache.clear()
            _grad_cache[key] = add
    elif t[0] == "auto":
        if _auto is None:
            return -1, None
        k = t[1]
        add = (_auto[0] * k).astype(np.int16)
    else:
        k = t[1]
        add = (_hex(t[0]) * k).astype(np.int16)
    return int(round((1 - k) * 64)), add


def tint_rgb(rgb, w, h):
    """Подмешать оттенок темы в стекло: rgb — (h*w, 3) int16 до прозрачности (из glass.render). На месте."""
    m, add = tint_params(w, h)
    if m < 0:
        return
    # rgb·(1−k) + цвет·k целыми числами на месте: без временных массивов float64 (было +35% к стеклу).
    # (1−k) — в 64-х долях: 300·64 ещё влезает в int16
    np.multiply(rgb, m, out=rgb)
    np.right_shift(rgb, 6, out=rgb)
    np.add(rgb, add, out=rgb)


def _rim_spec(skin):
    """(цвет сверху, цвет снизу, яркость, толщина) кромки темы или None (кромка как была — белая)."""
    r = skin["rim"]
    if not r:
        return None
    if r[0] == "grad":
        return QColor(r[1]), QColor(r[2]), r[3], r[4]
    c = QColor(ACCENT).lighter(130) if r[0] == "auto" else QColor(r[0])
    return c, c, r[1], r[2]


def _mix(a, b):
    return QColor((a.red() + b.red()) // 2, (a.green() + b.green()) // 2, (a.blue() + b.blue()) // 2)


def rim_pen(rect, dark):
    """Кромка карточки / острова: (градиент сверху вниз, толщина). Одна функция для виджетов и острова."""
    from PySide6.QtGui import QLinearGradient
    if _current == "custom":
        return qt_gradient(_custom["rim"], rect, 0.75 if dark else 1.0), (1.4 if _custom["glow"] else 1.1)
    spec = _rim_spec(current())
    top, bottom, strength, width = spec if spec else (QColor(255, 255, 255), QColor(255, 255, 255), 1.0, 1.0)
    a = (0.55 if dark else 1.0) * (1.6 if spec else 1.0) * strength
    g = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    for at, base in ((0, 150), (0.5, 90 if spec else 45), (1, 130)):
        c = QColor(top) if at < 0.5 else QColor(bottom) if at > 0.5 else _mix(top, bottom)
        c.setAlpha(min(255, int(base * a)))
        g.setColorAt(at, c)
    return g, width


def glow_colors(skin=None):
    """Свечение вокруг карточки: (цвет сверху, цвет снизу) или None."""
    g = (skin or current())["glow"]
    if not g:
        return None
    if isinstance(g, tuple):
        return QColor(g[1]), QColor(g[2])
    return QColor(g), QColor(g)


def _soft(a, r):
    """Мягкое размытие маски (float32 H×W): три box-размытия по строкам и столбцам ≈ гаусс."""
    for _ in range(3):
        for axis in (0, 1):
            n = a.shape[axis]
            pad = [(0, 0), (0, 0)]
            pad[axis] = (r + 1, r)
            c = np.cumsum(np.pad(a, pad), axis=axis)
            hi = [slice(None)] * 2
            lo = [slice(None)] * 2
            hi[axis], lo[axis] = slice(2 * r + 1, 2 * r + 1 + n), slice(0, n)
            a = (c[tuple(hi)] - c[tuple(lo)]) / (2 * r + 1)
    return a


def glow_scale(spec=None):
    """«Размер свечения» (0..100, по умолчанию 50 — как было) -> (множитель ширины, множитель яркости).
    spec — своя тема из редактора (превью); без него — текущая тема: своя — её размер, встроенная — _glow_size."""
    if spec is None:
        if _current == "custom" and _custom is not None:
            spec = _custom
        else:
            spec = {"glow_size": _glow_size}
    s = max(0, min(100, spec.get("glow_size", 50) if isinstance(spec.get("glow_size", 50), int) else 50)) / 100
    # ширина ×0.4…×1.6: больше — ореол упирается в поле тени вокруг карточки (18 px) и обрезается краем окна
    return 0.4 + 1.2 * s, 0.6 + 0.8 * s


def glow_image(path, w, h, margin, top, bottom, strength=0.55, spread=7, res=1.0, layout=None, scale=None):
    """Ореол неоновой трубки вокруг формы path (координаты 0..w, 0..h): кромка формы, размытая в мягкое свечение,
    раскрашенное сверху вниз (top -> bottom), без самой формы внутри. Картинка (w+2·margin)×(h+2·margin),
    форма — со сдвигом margin. Считается в половинном размере (быстро, ореол всё равно мягкий)."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QImage, QPainter, QPen
    import math
    k = 0.5 * res
    sk, tk = scale or glow_scale()
    spread, strength = spread * sk, min(1.0, strength * tk)
    # размер картинки — целые пиксели, а масштаб — ровно под них (kx, ky): при масштабе экрана 125% округление
    # растягивало ореол при выводе, и он получался «не по размеру и кривой» (Диар)
    W, H = max(1, math.ceil((w + 2 * margin) * k)), max(1, math.ceil((h + 2 * margin) * k))
    kx, ky = W / (w + 2 * margin), H / (h + 2 * margin)
    mask = QImage(W, H, QImage.Format_Alpha8)
    mask.fill(0)
    p = QPainter(mask)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(kx, ky)
    p.translate(QPointF(margin, margin))
    p.setPen(QPen(Qt.white, 2.5))
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)
    p.end()
    if _rust is not None:
        img = _glow_rust(path, mask, W, H, kx, ky, margin, top, bottom, strength, spread, k, layout)
        if img is not None:
            return img
    a = np.frombuffer(mask.constBits(), np.uint8).reshape(H, mask.bytesPerLine())[:, :W].astype(np.float32) / 255
    a = _soft(a, max(1, int(spread * k)))
    a = np.clip(a / max(float(a.max()), 1e-6), 0, 1) ** 0.8 * strength
    if margin > 0:  # к краю картинки (поле тени вокруг карточки) ореол сходит на нет: иначе широкий упирался
        # в край окна и обрезался ровной линией
        fw = max(1.0, margin * min(kx, ky) * 0.55)
        ex = np.minimum(np.arange(W, dtype=np.float32), np.arange(W, dtype=np.float32)[::-1]) + 0.5
        ey = np.minimum(np.arange(H, dtype=np.float32), np.arange(H, dtype=np.float32)[::-1]) + 0.5
        f = np.clip(np.minimum(ey[:, None], ex[None, :]) / fw, 0, 1)
        a *= f * f * (3 - 2 * f)
    # внутрь формы ореол не заходит: там стекло (иначе цвет ложится на текст)
    inside = QImage(W, H, QImage.Format_Alpha8)
    inside.fill(0)
    p = QPainter(inside)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(kx, ky)
    p.translate(QPointF(margin, margin))
    p.setPen(Qt.NoPen)
    p.setBrush(Qt.white)
    p.drawPath(path)
    p.end()
    ins = np.frombuffer(inside.constBits(), np.uint8).reshape(H, inside.bytesPerLine())[:, :W].astype(np.float32) / 255
    a *= 1 - ins
    lay = layout or glow_layout()
    if lay is None:
        t = np.linspace(0, 1, H, dtype=np.float32)[:, None]
        c0 = np.array([top.red(), top.green(), top.blue()], np.float32)
        c1 = np.array([bottom.red(), bottom.green(), bottom.blue()], np.float32)
        col = np.broadcast_to(c0 * (1 - t[..., None]) + c1 * t[..., None], (H, W, 3))  # H×1×3
    else:
        # раскладка — по самой форме, а не по картинке: у острова картинка во всё окно, а капсула — вверху,
        # и «сверху/снизу», «крест» считались от середины окна (капсула вся была «верхнего» цвета)
        br = path.boundingRect()
        box = ((br.left() + margin) * kx, (br.top() + margin) * ky, br.width() * kx, br.height() * ky)
        col, ca = _glow_paint(lay, W, H, box)
        a = a * ca
    out = np.empty((H, W, 4), np.uint8)
    out[..., :3] = col * a[..., None]  # premultiplied
    out[..., 3] = (a * 255).astype(np.uint8)
    img = QImage(out.data, W, H, W * 4, QImage.Format_RGBA8888_Premultiplied).copy()
    return img


def _inside_mask(path, W, H, kx, ky, margin):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QImage, QPainter
    inside = QImage(W, H, QImage.Format_Alpha8)
    inside.fill(0)
    p = QPainter(inside)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(kx, ky)
    p.translate(QPointF(margin, margin))
    p.setPen(Qt.NoPen)
    p.setBrush(Qt.white)
    p.drawPath(path)
    p.end()
    return inside


def _glow_rust(path, mask, W, H, kx, ky, margin, top, bottom, strength, spread, k, layout):
    """То же, что numpy-ветка glow_image (числа совпадают до единицы яркости), но размытие, затухание и раскраска —
    в Rust, без GIL. Ошибка — None: досчитает numpy."""
    global _rust
    from PySide6.QtGui import QImage
    try:
        inside = _inside_mask(path, W, H, kx, ky, margin)
        m = np.frombuffer(mask.constBits(), np.uint8).reshape(H, mask.bytesPerLine())[:, :W]
        ins = np.frombuffer(inside.constBits(), np.uint8).reshape(H, inside.bytesPerLine())[:, :W]
        fw = max(1.0, margin * min(kx, ky) * 0.55) if margin > 0 else 0.0
        lay = layout or glow_layout()
        if lay is None:
            cols = np.array([[top.red(), top.green(), top.blue(), 1.0],
                             [bottom.red(), bottom.green(), bottom.blue(), 1.0]], np.float32)
            kind, box = 0, (0.0, 0.0, 1.0, 1.0)
        else:
            kind = {"horizontal": 1, "vertical": 2}.get(lay[0], 3)
            cols = np.array([[c.red(), c.green(), c.blue(), c.alpha() / 255] for c in lay[1]], np.float32)
            br = path.boundingRect()
            box = ((br.left() + margin) * kx, (br.top() + margin) * ky, max(br.width() * kx, 1.0),
                   max(br.height() * ky, 1.0))
        out = _rust.glow(np.ascontiguousarray(m), np.ascontiguousarray(ins), max(1, int(spread * k)), float(strength),
                         float(fw), kind, cols, *(float(v) for v in box))
        return QImage(out.data, W, H, W * 4, QImage.Format_RGBA8888_Premultiplied).copy()
    except Exception as err:
        _rust = None  # один раз сломалось — дальше numpy, без повторных ошибок на каждом кадре
        try:
            import applog
            applog.error("skins.glow (Rust)", err)
        except Exception:
            pass
        return None


def _smooth(x):
    """Пополам, но со стыком помягче: середина 30..70% — плавный переход."""
    x = np.clip((x - 0.3) / 0.4, 0, 1)
    return x * x * (3 - 2 * x)


def _glow_paint(lay, W, H, box=None):
    """Цвет свечения своей темы по пикселям: (H×W×3 RGB, H×W прозрачность 0..1).
    box — где форма на картинке (x, y, ш, в): стороны «слева/справа/сверху/снизу» — её, а не всей картинки."""
    kind, cols = lay
    arr = np.array([[c.red(), c.green(), c.blue(), c.alpha() / 255] for c in cols], np.float32)
    bx, by, bw, bh = box if box else (0, 0, W, H)
    bw, bh = max(bw, 1.0), max(bh, 1.0)
    fx = (np.arange(W, dtype=np.float32) + 0.5 - bx) / bw  # 0..1 поперёк формы (за краями — меньше 0 / больше 1)
    fy = (np.arange(H, dtype=np.float32) + 0.5 - by) / bh
    if kind in ("horizontal", "vertical"):
        if kind == "horizontal":  # слева первый цвет, справа второй
            t = _smooth(fx)[None, :, None]
        else:                     # сверху первый, снизу второй
            t = _smooth(fy)[:, None, None]
        c = arr[0] * (1 - t) + arr[1] * t
        c = np.broadcast_to(c, (H, W, 4))
    else:  # крест: сверху, справа, снизу, слева — по углу от центра формы
        ys = (fy * 2 - 1)[:, None]
        xs = (fx * 2 - 1)[None, :]
        ang = np.arctan2(ys, xs)  # 0 — справа, π/2 — снизу
        wts = []
        for base in (-np.pi / 2, 0.0, np.pi / 2, np.pi):  # сверху, справа, снизу, слева
            wts.append(np.maximum(0, np.cos(ang - base)) ** 3)
        wsum = sum(wts) + 1e-6
        c = sum(wt[..., None] * arr[i] for i, wt in enumerate(wts)) / wsum[..., None]
    return c[..., :3], c[..., 3]


def glow_pen(rect, top, bottom, alpha, width=2.0):
    """Перо одного кольца свечения: градиент сверху вниз с прозрачностью alpha (0..255)."""
    from PySide6.QtGui import QLinearGradient, QPen
    g = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    for at, c in ((0, top), (1, bottom)):
        c = QColor(c)
        c.setAlpha(int(alpha))
        g.setColorAt(at, c)
    return QPen(g, width)


def tint_brush(rect):
    """Оттенок темы кистью Qt (для острова и превью): (кисть, сила 0..1) или None."""
    from PySide6.QtGui import QLinearGradient
    t = current()["tint"]
    if not t:
        return None
    if t[0] == "custom":
        return qt_gradient(_custom["fill"], rect, FILL_MAX), 1.0
    if t[0] == "grad":
        g = QLinearGradient(rect.topLeft(), rect.bottomRight())
        g.setColorAt(0, QColor(t[1]))
        g.setColorAt(1, QColor(t[2]))
        return g, t[3]
    if t[0] == "auto":
        if _auto is None:
            return None
        return QColor(*[int(v) for v in _auto[0]]), t[1]
    return QColor(t[0]), t[1]


def preview(skin_id):
    """Для карточки темы в каталоге: (цвет или пара цветов стекла, сила, кромка, свечение, акцент, акцент2, тёмная)."""
    s = SKINS[skin_id]
    t = s["tint"]
    if skin_id == "custom":  # свою тему карточка рисует сама (градиенты, раскладка свечения) — здесь лишь цвета
        c = _custom or custom_spec()
        acc = _stops(c["accent"])
        rim = _stops(c["rim"])
        return None, 0.0, (rim[0][1], rim[-1][1]), None, acc[0][1], acc[-1][1], custom_dark(c)
    if t is None:
        tint, k = None, 0.0
    elif t[0] == "grad":
        tint, k = (QColor(t[1]), QColor(t[2])), t[3]
    elif t[0] == "auto":
        auto = _auto if _current == "auto" else _from_wallpaper()
        tint, k = (QColor(*[int(v) for v in auto[0]]) if auto else None), t[1]
        if auto:
            rim = QColor(auto[1]).lighter(130)
            return tint, k, (rim, rim), None, auto[1], auto[2], False
    else:
        tint, k = QColor(t[0]), t[1]
    r = s["rim"]
    if not r or r[0] == "auto":
        rim = (QColor(255, 255, 255), QColor(255, 255, 255))
    elif r[0] == "grad":
        rim = (QColor(r[1]), QColor(r[2]))
    else:
        rim = (QColor(r[0]), QColor(r[0]))
    acc = QColor(s["accent"]) if s["accent"] != "auto" else QColor("#2f6bff")
    acc2 = QColor(s["accent2"]) if s["accent2"] != "auto" else QColor("#36c6ff")
    return tint, k, rim, glow_colors(s), acc, acc2, bool(s["dark"])
