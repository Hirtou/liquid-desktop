# Моды Liquid Desktop

Моды — дополнения от сообщества во вкладке «Моды» программы. Каждый мод проверяет автор Liquid Desktop
([Hirtou](https://github.com/Hirtou)), лежит он только в этом репозитории (папка `mods/`), и программа
сверяет каждый скачанный файл по sha256. Свои репозитории и ссылки для модов программа не принимает.

## Как прислать мод

1. Сделай мод по шаблону ниже (папка `mods/_example` — рабочий пример, счётчик кликов).
2. Проверь у себя: вкладка «Моды» → «Поставить из папки…» → выбери папку мода → «Перезапустить виджеты».
3. Пришли автору: pull request с папкой `mods/<id>/` или архив в Telegram.
4. Автор проверяет код, кладёт мод в `mods/` и обновляет список — мод появляется у всех во вкладке «Моды»,
   с твоим ником как автором мода.

## Из чего состоит мод

```
mods/<id>/
  mod.json     — описание мода
  widget.py    — код (можно разложить на несколько .py)
  icon.png     — значок 128×128 (необязательно)
```

`<id>` — латиница в нижнем регистре, цифры и `_`, 2–32 символа (`block_blast`). Имена файлов — латиница.

### mod.json

```json
{
  "id": "counter",
  "name": "Счётчик",
  "name_en": "Counter",
  "description": "Клик — +1",
  "description_en": "Click to count",
  "author": "твой_ник",
  "author_url": "https://github.com/твой_ник",
  "version": "1.0.0",
  "api": 1,
  "type": "widget",
  "entry": "widget.py",
  "class": "CounterWidget",
  "tile": ["#FF9F0A", "#FF6A00"],
  "icon": "icon.png"
}
```

- `version` — поднимай при каждом изменении: у людей появится кнопка «Обновить».
- `author_url` — только `https://github.com/...` или `https://t.me/...`.
- `tile` — два цвета плитки-значка сверху вниз; `icon` — картинка поверх плитки.

### Код виджета (API 1)

Виджет — наследник `core.DesktopWidget`. Стекло, тень, перетаскивание, магнит, меню «Стекло/Размер» —
программа делает сама; мод рисует только содержимое.

```python
from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter
from core import DesktopWidget, config, grid
from widgets import kit

class CounterWidget(DesktopWidget):
    SHAPES = {"tile": ("Плитка", grid(1, 1))}    # размер по сетке: 1×1, 2×1 (grid(2, 1)), 2×2…

    def __init__(self, **kw):
        super().__init__(**kw)
        self.apply_shape()
        self.cfg.setdefault("count", 0)          # свои настройки — self.cfg, сохранить — config.save()

    def tap(self, pos):                          # короткий клик (тянуть — двигает виджет)
        self.cfg["count"] += 1
        config.save()
        self.update()

    def add_actions(self, menu):                 # свои пункты меню по правому клику
        menu.addAction("Сбросить", self.reset)

    def paintEvent(self, event):
        super().paintEvent(event)                # стекло
        p = QPainter(self)
        r = QRectF(self.card()).adjusted(16, 14, -16, -14)
        fg, dim, _ = kit.ink(self)               # цвета текста под светлое / тёмное стекло
        kit.text(p, r, str(self.cfg["count"]), fg, 40, "Bahnschrift SemiBold")
```

Чтобы не грузить процессор:
- анимацию — таймером, который сам останавливается, когда двигаться нечему (не крутить кадры впустую);
- то, что не меняется (фон поля, сетка), — один раз в `QPixmap`, в кадре только его рисовать;
- тащишь что-то внутри виджета (фигуру, ползунок) — верни `True` из `jelly_busy(self)`, тогда «Желе»
  на это время не гнёт виджет.

## Чего в моде быть не должно

Автор не примет мод, который:
- скачивает и запускает код из интернета, ставит программы, лезет в чужие файлы, пароли, токены;
- шлёт данные пользователя куда-то без явной причины, понятной из описания;
- тормозит (таймер чаще 30 раз в секунду без нужды, тяжёлая работа в главном потоке);
- ломает остальную программу (меняет чужие виджеты, `core`, `glass`).

Мод с ошибкой программа не роняет: не загрузился — видно на вкладке «Моды», падает при рисовании —
прячется. Но лучше, конечно, без ошибок.

## Для автора: как опубликовать проверенный мод

1. Положить папку мода в `mods/<id>/`.
2. `python tools/mod_index.py` — пересоберёт `mods/index.json` с sha256 всех файлов.
3. Закоммитить и запушить `mods/` — у всех во вкладке «Моды» появится мод (или «Обновить»).

---

**English, short:** mods are community add-ons reviewed by the Liquid Desktop author and served only from
this repository (`mods/`), every file checked by sha256. Make a mod like `mods/_example`, test it with
«Install from folder…» in the Mods tab, then send it to the author (pull request or Telegram).
