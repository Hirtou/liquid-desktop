// Мост OpenCode -> Liquid Desktop: виджет «Опен-код» и остров показывают, чем занят OpenCode.
// Пишет opencode_status.json: что сейчас делается (состояние, подробность) и счётчики за день.
// Только эти поля — ни текста разговора, ни содержимого файлов. Путь подставляет Liquid Desktop
// при подключении вместо @STATUS_PATH@. Любая ошибка — молча выходим (OpenCode не мешаем).
import { Plugin } from "@opencode/plugin"
import { mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs"
import { dirname } from "node:path"

const STATUS = "@STATUS_PATH@"  // opencode_status.json в папке виджетов Liquid Desktop

// имена инструментов у OpenCode (приводим к нижнему регистру, на всякий случай — и от старых версий)
const READ = new Set(["read", "grep", "glob", "list", "ls", "view"])
const EDIT = new Set(["edit", "write", "patch", "multiedit", "notebookedit"])
const RUN = new Set(["shell", "bash", "execute", "powershell", "bashoutput", "killshell", "taskstop", "monitor"])
const WEB = new Set(["webfetch", "websearch"])
const HELP = new Set(["subagent", "task", "agent"])  // зовём помощника
const ASK = new Set(["question", "askuserquestion"])

type Any = Record<string, any>

function short(path: any): string {
  const s = String(path ?? "")
  const base = s.replace(/[\\/]+$/, "").split(/[\\/]/).pop()
  return base || s
}

function describe(toolRaw: any, inputRaw: any): [string, string] {
  // инструмент -> (состояние, подробность по-русски)
  const tool = String(toolRaw ?? "").toLowerCase()
  const input: Any = inputRaw && typeof inputRaw === "object" ? inputRaw : {}
  if (READ.has(tool)) {
    const target = input.file_path || input.path || input.pattern || ""
    return ["read", tool === "read" ? "Читаю " + short(target) : "Ищу «" + String(target).slice(0, 28) + "»"]
  }
  }
  if (EDIT.has(tool)) return ["edit", "Правлю " + short(input.file_path || input.path || input.notebook_path || "")]
  if (RUN.has(tool)) {
    const text = String(input.description || input.command || input.code || "")
    return ["run", text.length > 40 ? text.slice(0, 40) + "…" : (text || "Запускаю команду")]
  }
  if (WEB.has(tool)) return ["web", "Ищу в интернете"]
  if (HELP.has(tool)) return ["think", "Зову помощника"]
  if (ASK.has(tool)) return ["ask", "Спрашиваю тебя"]
  return ["think", "Думаю…"]
}

function isFail(event: Any): boolean {
  // инструмент вернул ошибку? только флаги и начало строки — содержимое не сохраняем
  if (event.status === "error" || event.error) return true
  const r = event.result ?? event.output
  if (typeof r === "string") return /^\s*(error|ошибка)/i.test(r)
  if (r && typeof r === "object") {
    if (r.is_error || r.error || r.interrupted) return true
    const code = r.exit_code ?? r.returncode
    if (typeof code === "number" && code !== 0) return true
    for (const item of Array.isArray(r.content) ? r.content : []) {
      const text = typeof item === "string" ? item : item?.text
      if (typeof text === "string" && /^\s*(error|ошибка)/i.test(text)) return true
    }
  }
  return false
}

function load(): Any {
  try {
    const st = JSON.parse(readFileSync(STATUS, "utf8"))
    return st && typeof st === "object" && !Array.isArray(st) ? st : {}
  } catch {
    return {}
  }
}

function save(st: Any): void {
  try {
    mkdirSync(dirname(STATUS), { recursive: true })
    const tmp = STATUS + ".tmp"
    writeFileSync(tmp, JSON.stringify(st))
    try {
      renameSync(tmp, STATUS)  // атомарно: виджет никогда не прочтёт половину файла
    } catch {
      writeFileSync(STATUS, JSON.stringify(st))  // rename не вышел (файл читают) — пишем как есть
    }
  } catch {}
}

function update(event: string, data: Any): void {
  const st = load()
  const today = new Date().toISOString().slice(0, 10)
  let counts: Any = st.counts && typeof st.counts === "object" ? st.counts : {}
  if (counts.date !== today) counts = { date: today, edit: 0, run: 0, read: 0, web: 0 }

  const now = Date.now() / 1000
  let state: string, detail: string
  if (event === "pre") {
    const [s, d] = describe(data.tool, data.input)
    state = s
    detail = d
    if (state in counts) counts[state] += 1
    if (state === "edit") st.task_edits = (st.task_edits ?? 0) + 1  // много правок за задачу — виджет в конце «крутой»
    if (state !== "think")  // последние действия — для списка в виджете
      st.history = ([{ s: state, d: detail, t: now }, ...(Array.isArray(st.history) ? st.history : [])]).slice(0, 6)
  } else if (event === "post") {
    if (isFail(data)) {
      state = "oops"
      detail = "Ой, ошибка — разбираюсь"
      st.fails = (st.fails ?? 0) + 1  // подряд: расстроен, потом злится
      st.failed_at = now
    } else {
      state = "think"
      detail = "Думаю…"
      st.fails = 0
    }
  } else if (event === "prompt") {  // новая задача — засекаем время
    state = "think"
    detail = "Думаю…"
    st.started = now
    st.finished = null
    st.task_edits = 0
    st.fails = 0
  } else if (event === "stop") {
    state = "done"
    detail = "Готово!"
    st.finished = now
  } else if (event === "notify" || event === "ask") {
    state = "ask"
    detail = "Нужен твой ответ!"
  } else if (event === "step_failed") {
    state = "oops"
    detail = "Ой, ошибка — разбираюсь"
    st.fails = (st.fails ?? 0) + 1
    st.failed_at = now
  } else {
    return
  }
  save({ ...st, state, detail, time: now, counts })
}

export default Plugin.define({
  id: "liquid-desktop",
  async setup(ctx) {
    console.log(`[liquid-desktop] мост активен: ${STATUS}`)
    // пользователь дал задачу — старт
    await ctx.session.hook("prompt", () => update("prompt", {}))
    // инструменты: что сейчас делается и чем закончилось
    await ctx.tool.hook("execute.before", (event) => update("pre", { tool: event.tool, input: event.input }))
    await ctx.tool.hook("execute.after", (event) =>
      update("post", { status: event.status, result: event.result, error: event.error }))
    // OpenCode ждёт разрешения (событие «allow» не трогаем — дальше инструмент сам скажет о себе)
    await ctx.permission.hook("evaluate", (event) => {
      if (event.effect === "ask") update("ask", {})
    })
    // сессия закончилась / шаг упал (в OpenCode 2.2.x окончание задачи — session.execution.*, session.idle нет)
    const controller = new AbortController()
    void (async () => {
      try {
        for await (const ev of ctx.event.subscribe({
          types: ["session.execution.succeeded", "session.execution.failed", "session.execution.interrupted",
                  "session.step.failed", "session.idle"],
          signal: controller.signal,
        })) {
          if (ev.type === "session.execution.succeeded" || ev.type === "session.execution.interrupted"
              || ev.type === "session.idle") update("stop", {})
          else update("step_failed", {})  // session.execution.failed / session.step.failed
        }
      } catch {}
    })()
    return () => controller.abort()
  },
})
