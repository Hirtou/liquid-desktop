"""Вернуть на рабочий стол все ярлыки, которые виджеты «Папка» перенесли к себе.
Запускает деинсталлятор (программу удаляют — ярлыки не должны остаться спрятанными в данных программы).
Без Qt и без окон: только config.json и перенос файлов."""
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(ROOT, "config.json")


def desktop_dir():
    import ctypes
    buf = ctypes.create_unicode_buffer(260)
    try:
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0 and buf.value:
            return buf.value
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), "Desktop")


def free(folder, name):
    stem, ext = os.path.splitext(name)
    out, n = os.path.join(folder, name), 2
    while os.path.exists(out):
        out, n = os.path.join(folder, f"{stem} ({n}){ext}"), n + 1
    return out


def main():
    try:
        with open(CONFIG, encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return 0
    changed = 0
    for section in data.values() if isinstance(data, dict) else ():
        moved = section.get("moved") if isinstance(section, dict) else None
        if not isinstance(moved, dict):
            continue
        for stored, original in list(moved.items()):
            if not (isinstance(stored, str) and isinstance(original, str)):
                continue
            try:
                if os.path.exists(stored):
                    folder = os.path.dirname(original)
                    folder = folder if os.path.isdir(folder) else desktop_dir()
                    shutil.move(stored, free(folder, os.path.basename(original)))
                moved.pop(stored)
                items = section.get("items")
                if isinstance(items, list):
                    section["items"] = [p for p in items if p != stored]
                changed += 1
            except OSError:
                pass
    if changed:
        try:
            with open(CONFIG, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
