"""Часовой пояс у часов («Часы», «Аналоговые», «Метеочасы»): по умолчанию — «Авто», как в Windows
(и сразу следом, если пояс в Windows сменили — см. glass.refresh_timezone); правый клик → «Часовой пояс» —
любой город из списка или свой пояс («Europe/Moscow», «UTC+5»).
Города хранятся по-русски (как в «Мировом времени»), на экране — через tr()."""
from lang import tr
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from PySide6.QtWidgets import QInputDialog, QMessageBox

from core import config

ZONES = {
    "Алматы": "Asia/Almaty", "Астана": "Asia/Almaty", "Ташкент": "Asia/Tashkent", "Бишкек": "Asia/Bishkek",
    "Душанбе": "Asia/Dushanbe", "Москва": "Europe/Moscow", "Калининград": "Europe/Kaliningrad",
    "Самара": "Europe/Samara", "Екатеринбург": "Asia/Yekaterinburg", "Омск": "Asia/Omsk",
    "Новосибирск": "Asia/Novosibirsk", "Красноярск": "Asia/Krasnoyarsk", "Иркутск": "Asia/Irkutsk",
    "Владивосток": "Asia/Vladivostok", "Минск": "Europe/Minsk", "Киев": "Europe/Kyiv", "Тбилиси": "Asia/Tbilisi",
    "Ереван": "Asia/Yerevan", "Баку": "Asia/Baku", "Стамбул": "Europe/Istanbul", "Берлин": "Europe/Berlin",
    "Варшава": "Europe/Warsaw", "Париж": "Europe/Paris", "Рим": "Europe/Rome", "Мадрид": "Europe/Madrid",
    "Лондон": "Europe/London", "Дубай": "Asia/Dubai", "Дели": "Asia/Kolkata", "Бангкок": "Asia/Bangkok",
    "Сингапур": "Asia/Singapore", "Пекин": "Asia/Shanghai", "Сеул": "Asia/Seoul", "Токио": "Asia/Tokyo",
    "Сидней": "Australia/Sydney", "Нью-Йорк": "America/New_York", "Торонто": "America/Toronto",
    "Чикаго": "America/Chicago", "Мехико": "America/Mexico_City", "Лос-Анджелес": "America/Los_Angeles",
    "Сан-Паулу": "America/Sao_Paulo",
}


def zone_of(name):
    """Название из настроек -> пояс (tzinfo) или None («Авто» — как в Windows)."""
    if not name or name == "auto":
        return None
    if name in ZONES:
        return ZoneInfo(ZONES[name])
    if name.upper().startswith("UTC") or name.upper().startswith("GMT"):  # «UTC+5», «UTC-3:30»
        rest = name[3:].strip() or "0"
        sign = -1 if rest.startswith("-") else 1
        h, _, m = rest.lstrip("+-").partition(":")
        return timezone(sign * timedelta(hours=int(h), minutes=int(m or 0)))
    return ZoneInfo(name)


def now(cfg):
    """Время для часов: по их поясу, «Авто» — как в Windows."""
    try:
        zone = zone_of(cfg.get("tz"))
    except Exception:  # испорченная настройка или пояса нет в базе — как в Windows
        zone = None
    return datetime.now(zone) if zone is not None else datetime.now()


def label(cfg):
    name = cfg.get("tz")
    return tr("Авто") if not name or name == "auto" else tr(name)


def add_menu(menu, widget):
    """Подменю «Часовой пояс» у часов."""
    sub = menu.addMenu(tr("Часовой пояс: {}").format(label(widget.cfg)))
    current = widget.cfg.get("tz") or "auto"
    auto = sub.addAction(tr("Авто — как в Windows ({})").format(datetime.now().astimezone().strftime("UTC%z")[:-2]),
                         lambda: set_zone(widget, "auto"))
    auto.setCheckable(True)
    auto.setChecked(current == "auto")
    sub.addSeparator()
    for name in ZONES:
        a = sub.addAction(tr(name), lambda n=name: set_zone(widget, n))
        a.setCheckable(True)
        a.setChecked(current == name)
    sub.addSeparator()
    sub.addAction(tr("Другой пояс…"), lambda: ask_zone(widget))


def set_zone(widget, name):
    widget.cfg["tz"] = name
    config.save()
    widget.flat_key = None
    for attr in ("_minute", "face_key", "slow_key"):  # кэши «раз в минуту» — перерисовать сразу
        if hasattr(widget, attr):
            setattr(widget, attr, None)
    if hasattr(widget, "show_time"):  # «Часы» из подписей — обновить текст сразу
        widget.show_time()
    widget.update()


def ask_zone(widget):
    text, ok = QInputDialog.getText(None, tr("Часовой пояс"),
                                    tr("Пояс как Europe/Moscow или смещение как UTC+5:"),
                                    text="" if (widget.cfg.get("tz") or "auto") == "auto" else widget.cfg["tz"])
    if not ok or not text.strip():
        return
    try:
        zone_of(text.strip())
    except Exception:
        QMessageBox.information(None, tr("Часовой пояс"), tr("Такого пояса нет. Пример: Europe/Moscow или UTC+5."))
        return
    set_zone(widget, text.strip())
