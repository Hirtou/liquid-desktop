"""Собрать mods/index.json для вкладки «Моды»: для каждой папки mods/<id>/ с mod.json — запись
и sha256 каждого файла. Запускать после того, как проверил мод и положил его папку в mods/:

    python tools/mod_index.py            (в репозитории liquid-desktop)

Программа скачает только файлы из этого списка и только если их sha256 совпадёт — значит, в список попадает
ровно то, что ты проверил. Поменял файл мода — запусти снова (и подними "version" в mod.json, чтобы у людей
появилась кнопка «Обновить»). Папки, которые начинаются с «_» или «.», пропускаются (шаблоны, черновики).

Builds mods/index.json (entries + sha256 of every file) for the Mods tab."""
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MODS = os.path.join(os.path.dirname(HERE), "mods") if os.path.basename(HERE) == "tools" else os.path.join(HERE, "mods")
EXTS = {".py", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".json", ".txt", ".wav", ".ttf", ".otf"}
KEEP = ("id", "name", "name_en", "description", "description_en", "author", "author_url", "version", "api",
        "type", "entry", "class", "tile", "icon")


def build(root=MODS):
    out, problems = [], []
    for mid in sorted(os.listdir(root)):
        folder = os.path.join(root, mid)
        if mid.startswith(("_", ".")) or not os.path.isdir(folder):
            continue
        try:
            with open(os.path.join(folder, "mod.json"), encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, ValueError) as err:
            problems.append(f"{mid}: нет или битый mod.json ({err})")
            continue
        if meta.get("id") != mid:
            problems.append(f"{mid}: id в mod.json ({meta.get('id')!r}) не совпадает с именем папки")
            continue
        files = {}
        for base, dirs, names in os.walk(folder):
            dirs[:] = sorted(d for d in dirs if not d.startswith((".", "__")))
            for n in sorted(names):
                rel = os.path.relpath(os.path.join(base, n), folder).replace("\\", "/")
                if rel == "mod.json" or os.path.splitext(n)[1].lower() not in EXTS:
                    continue
                if not re.fullmatch(r"[A-Za-z0-9_\-]+(/[A-Za-z0-9_\-]+)*\.[A-Za-z0-9]+", rel):
                    problems.append(f"{mid}: имя файла {rel!r} — только латиница, цифры, _ и -")
                    continue
                with open(os.path.join(base, n), "rb") as fh:
                    files[rel] = hashlib.sha256(fh.read()).hexdigest()
        if meta.get("entry") not in files:
            problems.append(f"{mid}: главного файла {meta.get('entry')!r} нет в папке")
            continue
        out.append({**{k: meta[k] for k in KEEP if k in meta}, "files": files})
    return out, problems


def main():
    if not os.path.isdir(MODS):
        print("нет папки", MODS)
        return 1
    mods, problems = build()
    for p in problems:
        print("пропущен:", p)
    with open(os.path.join(MODS, "index.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump({"mods": mods}, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"index.json: модов {len(mods)}" + "".join(f"\n  {m['id']} {m['version']} — {m['author']}" for m in mods))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
