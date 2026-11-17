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
}
ORDER = ["liquid", "night", "neon", "sunset", "sakura", "forest", "minimal", "auto"]

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


def apply(skin_id):
    """Включить тему: перекрасить общие цвета акцента. Виджеты после этого нужно перерисовать (см. main)."""
    global _current, version, _auto
    _current = skin_id if skin_id in SKINS else "liquid"
    s = SKINS[_current]
    if s["accent"] == "auto":
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


def glass_params(blur, haze):
    """Размытие и замутнение: у темы свои, у Liquid — из настроек."""
    s = current()
    return (blur if s["blur"] is None else s["blur"]), (haze if s["haze"] is None else s["haze"])


_grad_cache = {}


def tint_params(w, h):
    """Оттенок темы для стекла w×h: (m, add) — rgb·m >> 6 + add; (-1, None) — без оттенка.
    add — int16: 3 числа или по пикселю (h*w*3, градиент «Заката»). Его же берёт Rust-модуль стекла."""
    t = current()["tint"]
    if not t:
        return -1, None
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


def glow_image(path, w, h, margin, top, bottom, strength=0.55, spread=7, res=1.0):
    """Ореол неоновой трубки вокруг формы path (координаты 0..w, 0..h): кромка формы, размытая в мягкое свечение,
    раскрашенное сверху вниз (top -> bottom), без самой формы внутри. Картинка (w+2·margin)×(h+2·margin),
    форма — со сдвигом margin. Считается в половинном размере (быстро, ореол всё равно мягкий)."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QImage, QPainter, QPen
    k = 0.5 * res
    W, H = max(1, int((w + 2 * margin) * k)), max(1, int((h + 2 * margin) * k))
    mask = QImage(W, H, QImage.Format_Alpha8)
    mask.fill(0)
    p = QPainter(mask)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(k, k)
    p.translate(QPointF(margin, margin))
    p.setPen(QPen(Qt.white, 2.5))
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)
    p.end()
    a = np.frombuffer(mask.constBits(), np.uint8).reshape(H, mask.bytesPerLine())[:, :W].astype(np.float32) / 255
    a = _soft(a, max(1, int(spread * k)))
    a = np.clip(a / max(float(a.max()), 1e-6), 0, 1) ** 0.8 * strength
    # внутрь формы ореол не заходит: там стекло (иначе цвет ложится на текст)
    inside = QImage(W, H, QImage.Format_Alpha8)
    inside.fill(0)
    p = QPainter(inside)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(k, k)
    p.translate(QPointF(margin, margin))
    p.setPen(Qt.NoPen)
    p.setBrush(Qt.white)
    p.drawPath(path)
    p.end()
    ins = np.frombuffer(inside.constBits(), np.uint8).reshape(H, inside.bytesPerLine())[:, :W].astype(np.float32) / 255
    a *= 1 - ins
    t = np.linspace(0, 1, H, dtype=np.float32)[:, None]
    c0 = np.array([top.red(), top.green(), top.blue()], np.float32)
    c1 = np.array([bottom.red(), bottom.green(), bottom.blue()], np.float32)
    col = c0 * (1 - t[..., None]) + c1 * t[..., None]  # H×1×3
    rgba = np.empty((H, W, 4), np.uint8)
    rgba[..., :3] = np.broadcast_to(col, (H, W, 3)) * a[..., None]  # premultiplied
    rgba[..., 3] = (a * 255).astype(np.uint8)
    img = QImage(rgba.data, W, H, W * 4, QImage.Format_RGBA8888_Premultiplied).copy()
    return img


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
