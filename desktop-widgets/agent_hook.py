"""Хук Codex и Antigravity -> <agent>_status.json (то же, что claude_hook.py делает для Claude Code).

Помощник запускает этот скрипт на своих событиях и передаёт JSON в stdin:
    agent_hook.py codex pre        agent_hook.py antigravity stop
Пишем только состояние и короткую подробность (имя файла, начало команды) — ни текста разговора, ни содержимого файлов.
Остров читает эти файлы и показывает, чем занят помощник. Любая ошибка — молча выходим: помощнику не мешаем.

Hook for Codex and Antigravity: writes the agent's current state to <agent>_status.json for the Dynamic Island."""
import json
import os
import re
import sys
import time

try:
    from lang import tr
except Exception:  # хук не должен падать из-за перевода
    def tr(text):
        return text

HERE = os.path.dirname(os.path.abspath(__file__))
AGENTS = ("codex", "antigravity")


def status_path(agent):
    return os.path.join(HERE, f"{agent}_status.json")


def short(path):
    return os.path.basename(str(path).rstrip("\\/")) or str(path)


def clip(text, n=40):
    text = " ".join(str(text).split())
    return (text[:n] + "…") if len(text) > n else text


# ---------- что делает: инструмент -> (состояние, подробность) ----------

def describe_codex(tool, inp):
    """Codex: Bash, apply_patch, mcp__<сервер>__<инструмент>, update_plan, spawn_agent…"""
    inp = inp if isinstance(inp, dict) else {}
    if tool == "Bash":
        cmd = inp.get("command")
        if isinstance(cmd, list):
            cmd = " ".join(str(c) for c in cmd)
        return "run", clip(cmd) if cmd else tr("Запускаю команду")
    if tool in ("apply_patch", "Edit", "Write"):
        text = str(inp.get("command") or inp.get("patch") or inp.get("input") or "")
        m = re.search(r"\*\*\* (?:Update|Add|Delete) File: (.+)", text)
        return "edit", tr("Правлю ") + short(m.group(1).strip()) if m else tr("Правлю…")
    if tool in ("spawn_agent", "Agent"):
        return "think", tr("Зову помощника")
    if tool == "update_plan":
        return "think", tr("Составляю план")
    if tool.startswith("mcp__"):
        return "think", tr("Использую ") + tool.split("__")[-1]
    return "think", tr("Думаю…")


AGY_READ = {"view_file", "list_dir", "view_file_outline", "view_code_item"}
AGY_FIND = {"find_by_name", "grep_search", "codebase_search"}
AGY_EDIT = {"write_to_file", "replace_file_content", "multi_replace_file_content"}
AGY_WEB = {"search_web", "read_url_content", "read_browser_page"}
AGY_HELP = {"invoke_subagent", "define_subagent", "manage_subagents"}
AGY_ASK = {"ask_question", "ask_permission"}


def _arg(args, *names):
    """Первое строковое поле из args по имени (без учёта регистра); иначе — любое с «path»/«file» в имени."""
    low = {str(k).lower(): v for k, v in args.items()}
    for n in names:
        v = low.get(n.lower())
        if isinstance(v, str) and v:
            return v
    return ""


def describe_antigravity(tool, args):
    """Antigravity: view_file, write_to_file, run_command, search_web, ask_question…"""
    args = args if isinstance(args, dict) else {}
    if tool in AGY_READ:
        target = _arg(args, "AbsolutePath", "TargetFile", "DirectoryPath", "Path", "File")
        return "read", tr("Читаю ") + short(target) if target else tr("Читаю…")
    if tool in AGY_FIND:
        q = _arg(args, "Query", "Pattern", "SearchPattern", "Name")
        return "read", (tr("Ищу «%s»") % clip(q, 28)) if q else tr("Читаю…")
    if tool in AGY_EDIT:
        target = _arg(args, "TargetFile", "AbsolutePath", "Path", "File")
        return "edit", tr("Правлю ") + short(target) if target else tr("Правлю…")
    if tool == "run_command":
        cmd = _arg(args, "CommandLine", "Command")
        return "run", clip(cmd) if cmd else tr("Запускаю команду")
    if tool in AGY_WEB or tool.startswith("browser_"):
        return "web", tr("Ищу в интернете")
    if tool in AGY_HELP:
        return "think", tr("Зову помощника")
    if tool in AGY_ASK:
        return "ask", tr("Нужен твой ответ!")
    return "think", tr("Думаю…")


def failed(resp):
    """Ответ инструмента Codex похож на ошибку? Только флаги — содержимое не сохраняем."""
    if isinstance(resp, dict):
        if resp.get("is_error") or resp.get("error") or resp.get("interrupted"):
            return True
        code = resp.get("exit_code", resp.get("returncode"))
        return isinstance(code, int) and code != 0
    return False


# ---------- событие -> новое состояние ----------

def step(agent, event, data, st, now):
    """Поменять st (словарь состояния) по событию. -> False, если событие ничего не меняет."""
    if agent == "codex":
        tool, inp = str(data.get("tool_name") or ""), data.get("tool_input")
        bad = failed(data.get("tool_response"))
        describe = describe_codex
    else:
        call = data.get("toolCall") if isinstance(data.get("toolCall"), dict) else {}
        tool, inp = str(call.get("name") or ""), call.get("args")
        bad = bool(data.get("error"))
        describe = describe_antigravity
    if event == "invoke":  # Antigravity: перед каждым запросом к модели; нулевой — начало задачи
        if data.get("invocationNum") not in (0, "0"):
            if st.get("state") in ("ask", "oops"):
                state, detail = "think", tr("Думаю…")
            else:
                return False
        else:
            event = "prompt"
    if event == "prompt":
        state, detail = "think", tr("Думаю…")
        st["started"], st["finished"], st["fails"] = now, None, 0
    elif event == "pre":
        state, detail = describe(tool, inp)
        if state != "think":
            st["history"] = ([{"s": state, "d": detail, "t": now}] + st.get("history", []))[:6]
    elif event == "post":
        if bad:
            state, detail = "oops", tr("Ой, ошибка — разбираюсь")
            st["fails"], st["failed_at"] = st.get("fails", 0) + 1, now
        else:
            state, detail = "think", tr("Думаю…")
            st["fails"] = 0
    elif event == "notify":  # Codex просит разрешения
        state, detail = "ask", tr("Нужен твой ответ!")
    elif event == "stop":
        if agent == "antigravity" and data.get("terminationReason") == "error":
            state, detail = "oops", tr("Ой, ошибка — разбираюсь")
        else:
            state, detail = "done", tr("Готово!")
        st["finished"] = now
    elif event != "invoke":
        return False
    st.update({"state": state, "detail": detail, "time": now})
    return True


class Lock:
    """Инструменты идут параллельно — хуки тоже. Без замка второй затирает первого. Ждём до 2 с, потом пишем так."""

    def __init__(self, path):
        self.path = path + ".lock"

    def __enter__(self):
        import msvcrt
        self.f = open(self.path, "a+b")
        end = time.monotonic() + 2
        while True:
            try:
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_NBLCK, 1)
                self.ok = True
                return self
            except OSError:
                if time.monotonic() > end:
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


def update(agent, event, data):
    path = status_path(agent)
    with Lock(path):
        try:
            with open(path, encoding="utf-8") as f:
                st = json.load(f)
        except Exception:
            st = {}
        if not isinstance(st, dict):
            st = {}
        if not step(agent, event, data, st, time.time()):
            return
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False)
        os.replace(tmp, path)  # атомарно: остров никогда не прочтёт половину файла


def reply(agent, event):
    """Что напечатать в ответ. Antigravity ждёт JSON с решением, Codex на Stop — JSON (пустой: «ничего не меняем»)."""
    if agent == "antigravity":
        return '{"decision": "allow"}' if event in ("pre", "stop") else "{}"
    if agent == "codex" and event == "stop":
        return "{}"
    return ""


def main():
    agent = sys.argv[1] if len(sys.argv) > 1 else ""
    event = sys.argv[2] if len(sys.argv) > 2 else ""
    if agent not in AGENTS:
        return
    try:
        try:
            raw = sys.stdin.buffer.read() if sys.stdin else b""
            data = json.loads(raw.decode("utf-8-sig") or "{}")  # -sig: вдруг пришёл BOM
        except Exception:
            data = {}
        update(agent, event, data if isinstance(data, dict) else {})
    finally:
        out = reply(agent, event)
        if out:
            try:
                os.write(1, out.encode())  # pythonw: sys.stdout бывает None, а сам канал есть
            except OSError:
                pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
