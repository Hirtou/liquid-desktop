"""Хук Claude Code -> виджет «Клод».

Claude Code запускает этот скрипт перед/после каждого своего действия и передаёт JSON в stdin.
Пишем в claude_status.json: что сейчас делает (состояние, подробность) и счётчики за день.
Только эти поля — ни текста разговора, ни содержимого файлов. Любая ошибка — молча выходим (Claude не мешаем).
"""
from lang import tr
import json
import os
import sys
import time
from datetime import date

STATUS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "claude_status.json")
READ = {"Read", "Grep", "Glob", "NotebookRead", "LS"}
EDIT = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
RUN = {"Bash", "PowerShell", "BashOutput", "KillShell", "TaskStop", "Monitor"}
WEB = {"WebFetch", "WebSearch"}


def short(path):
    return os.path.basename(str(path).rstrip("\\/")) or str(path)


def describe(tool, inp):
    """Инструмент -> (состояние, подробность по-русски)."""
    if tool in READ:
        target = inp.get("file_path") or inp.get("path") or inp.get("pattern") or ""
        return "read", (tr("Читаю ") + short(target)) if tool == "Read" else (tr("Ищу «%s»") % str(target)[:28])
    if tool in EDIT:
        return "edit", tr("Правлю ") + short(inp.get("file_path") or inp.get("notebook_path") or "")
    if tool in RUN:
        text = inp.get("description") or inp.get("command") or ""
        return "run", (text[:40] + "…") if len(text) > 40 else (text or tr("Запускаю команду"))
    if tool in WEB:
        return "web", tr("Ищу в интернете")
    if tool in ("Agent", "Task"):
        return "think", tr("Зову помощника")
    if tool == "AskUserQuestion":
        return "ask", tr("Спрашиваю тебя")
    return "think", tr("Думаю…")


def failed(resp):
    """Ответ инструмента похож на ошибку? Только флаги и начало строки — содержимое не сохраняем."""
    if isinstance(resp, dict):
        if resp.get("is_error") or resp.get("error") or resp.get("interrupted"):
            return True
        code = resp.get("exit_code", resp.get("returncode"))
        return isinstance(code, int) and code != 0
    if isinstance(resp, str):
        return resp.lstrip().lower().startswith(("error", tr("ошибка")))
    return False




class Lock:
    """Claude Code запускает инструменты параллельно — хуки идут одновременно. Без замка два хука читают один
    и тот же файл, и второй затирает счётчики и историю первого. Замок — файл рядом (msvcrt, ждём до 2 с)."""

    def __enter__(self):
        import msvcrt
        self.f = open(STATUS + ".lock", "a+b")
        end = time.monotonic() + 2
        while True:
            try:
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_NBLCK, 1)
                self.ok = True
                return self
            except OSError:
                if time.monotonic() > end:  # не дождались — пишем без замка, Claude не держим
                    self.ok = False
                    return self
                time.sleep(0.02)

    def __exit__(self, *exc):
        import msvcrt
        try:
            if self.ok:
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            self.f.close()


def idle_notice(data):
    """Напоминание «Claude ждёт ввода» (через минуту простоя) — не вопрос: задача уже готова."""
    kind = str(data.get("notification_type") or "")
    message = str(data.get("message") or "").lower()
    return kind == "idle_prompt" or "waiting for your input" in message


def main():
    event = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8-sig") or "{}")  # -sig: вдруг пришёл BOM
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    if event == "notify" and idle_notice(data):
        return
    with Lock():
        update(event, data)


def update(event, data):
    try:
        with open(STATUS, encoding="utf-8") as f:
            st = json.load(f)
    except Exception:
        st = {}
    if not isinstance(st, dict):
        st = {}
    today = date.today().isoformat()
    counts = st.get("counts") if isinstance(st.get("counts"), dict) else {}
    if counts.get("date") != today:
        counts = {"date": today, "edit": 0, "run": 0, "read": 0, "web": 0}

    now = time.time()
    if event == "pre":
        state, detail = describe(data.get("tool_name", ""), data.get("tool_input") or {})
        if state in counts:
            counts[state] += 1
        if state == "edit":  # много правок за задачу — виджет в конце «крутой»
            st["task_edits"] = st.get("task_edits", 0) + 1
        if state != "think":  # последние действия — для списка в виджете
            st["history"] = ([{"s": state, "d": detail, "t": now}] + st.get("history", []))[:6]
    elif event == "post":
        # инструмент вернул ошибку — у виджета эмоция «ой» (смотрим только признаки ошибки, не текст)
        if failed(data.get("tool_response")):
            state, detail = "oops", tr("Ой, ошибка — разбираюсь")
            st["fails"], st["failed_at"] = st.get("fails", 0) + 1, now  # подряд: расстроен, потом злится
        else:
            state, detail = "think", tr("Думаю…")
            st["fails"] = 0
    elif event == "prompt":  # новая задача — засекаем время
        state, detail = "think", tr("Думаю…")
        st["started"], st["finished"] = now, None
        st["task_edits"], st["fails"] = 0, 0
    elif event == "stop":
        state, detail = "done", tr("Готово!")
        st["finished"] = now
    elif event == "notify":
        state, detail = "ask", tr("Нужен твой ответ!")
    else:
        return
    st.update({"state": state, "detail": detail, "time": now, "counts": counts})
    tmp = STATUS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)
    os.replace(tmp, STATUS)  # атомарно: виджет никогда не прочтёт половину файла


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
