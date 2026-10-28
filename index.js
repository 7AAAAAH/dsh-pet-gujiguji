/**
 * Host half of dsh-pet-gujiguji.
 *
 * Mirrors the Codex desktop pet's "reacts to agent state" behaviour inside
 * DeepSeek Harness. The browser client renders a sprite-sheet pet (GujiGuji)
 * and swaps which animation row it plays based on the active agent's status.
 * This Host half does three things so the pet works without a custom build:
 *
 *   1. Serves the spritesheet bytes at /dsh-pet-gujiguji/spritesheet.webp (the
 *      client cannot import from inside the app bundle, so it fetches them).
 *   2. Tracks the dominant live agent status and broadcasts it over SSE at
 *      /dsh-pet-gujiguji/state, so every open page sees the same state.
 *   3. Persists the last status to state.json so a fresh page starts correct.
 *
 * `Agent.status` is only `idle | running`, so three signals feed the pet:
 * the status poll (running), `agent/error` (a short failed reaction) and the
 * `approval/request` waterfall (waiting). A completed `turn/end` increments a
 * one-shot completion sequence so the desktop pet can play its success hops.
 * The remaining sheet rows stay client-side because no stable Host signal
 * selects them yet.
 */

import { readFile, writeFile } from 'node:fs/promises'
import {
  closeSync,
  copyFileSync,
  existsSync,
  mkdirSync,
  openSync,
  readFileSync,
  readdirSync,
  statSync,
  unlinkSync,
  writeFileSync,
} from 'node:fs'
import { spawn } from 'node:child_process'
import { homedir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

/** Cordis function-plugin name. */
export const name = 'dsh-pet-gujiguji'

/** Host services we depend on. */
export const inject = ['webServer', 'connection', 'agents']

const SPRITE_PATH = join(dirname(fileURLToPath(import.meta.url)), 'assets', 'spritesheet.webp')
const STATE_PATH = join(dirname(fileURLToPath(import.meta.url)), 'state.json')

const STATUS_PATH = '/dsh-pet-gujiguji/state'
const SPRITE_ROUTE = '/dsh-pet-gujiguji/spritesheet.webp'
const SETTINGS_ROUTE = '/dsh-pet-gujiguji/settings'

const PLUGIN_DIR = dirname(fileURLToPath(import.meta.url))
const DESKTOP_DIR = join(PLUGIN_DIR, 'desktop')
const DESKTOP_STATE_PATH = join(DESKTOP_DIR, 'state.json')
const DESKTOP_POSITION_PATH = join(DESKTOP_DIR, 'position.json')
const DESKTOP_DEFAULT_SETTINGS_PATH = join(DESKTOP_DIR, 'default-settings.json')
const DESKTOP_SCRIPT = join(DESKTOP_DIR, 'pet-window.pyw')
const DESKTOP_SPRITE = join(PLUGIN_DIR, 'assets', 'spritesheet.png')
const DESKTOP_PROCESS_PATH = join(DESKTOP_DIR, 'pet.pid')
const DESKTOP_DSH_PID_PATH = join(DESKTOP_DIR, 'dsh.pid')
const DESKTOP_HIDDEN_PATH = join(DESKTOP_DIR, 'hidden.flag')
const USER_DATA_DIR = join(process.env.APPDATA || homedir(), 'dsh-pet-gujiguji')
const LEGACY_USER_DATA_DIRS = [
  join(process.env.APPDATA || homedir(), 'dsh-light-feather'),
  join(process.env.APPDATA || homedir(), 'dsh-mint-budgie'),
]
const USER_STATE_PATH = join(USER_DATA_DIR, 'state.json')
const USER_POSITION_PATH = join(USER_DATA_DIR, 'position.json')
const USER_SETTINGS_PATH = join(USER_DATA_DIR, 'settings.json')
const SESSION_CACHE_DIR = join(homedir(), '.dsh', 'storages', 'session_projcache', 'sessions')

/** How long the pet keeps the failure row after `agent/error`. */
const FAILED_HOLD_MS = 4000
/** Poll cadence for `Agent.status`, which only toggles idle/running. */
const POLL_MS = 500
const DEFAULT_RUNNING_ACTIVITY = '正在分析请求'

/** Whether a session event represents a normal, successfully completed turn. */
export function isCompletedTurn(event) {
  if (event?.type !== 'turn/end') return false
  const reason = event?.data?.reason ?? event?.reason
  return reason?.kind === 'completed' || reason === 'completed'
}

function callArguments(value) {
  if (typeof value === 'string') {
    try {
      return JSON.parse(value)
    } catch {
      return {}
    }
  }
  return value && typeof value === 'object' ? value : {}
}

function shortDetail(value, limit = 56) {
  if (typeof value !== 'string') return ''
  const singleLine = value.replace(/\s+/g, ' ').trim()
  if (!singleLine) return ''
  return singleLine.length <= limit ? singleLine : `${singleLine.slice(0, limit - 1)}…`
}

function toolActivity(exec) {
  const name = typeof exec?.name === 'string' ? exec.name.toLowerCase() : ''
  const args = callArguments(exec?.arguments)
  const path = shortDetail(
    args.file_path
      ?? args.filePath
      ?? args.path
      ?? args.filename
      ?? args.notebook_path,
  )
  const query = shortDetail(args.query ?? args.pattern ?? args.q)
  const command = shortDetail(args.command ?? args.cmd)
  const url = shortDetail(args.url ?? args.href)
  const withDetail = (label, detail) => detail ? `${label} · ${detail}` : label

  if (/(spawn|subagent|sub_agent|delegate|agent_task|team_task)/.test(name)) {
    return '正在协调子智能体'
  }
  if (/(web_search|search_web|browser_search)/.test(name)) {
    return withDetail('正在搜索网页', query)
  }
  if (/(browser|web_fetch|fetch_url|visit|navigate)/.test(name)) {
    return withDetail('正在访问网页', url || query)
  }
  if (/(apply_patch|write_file|edit_file|edit|replace|patch|notebook_edit)/.test(name)) {
    return withDetail('正在编辑文件', path)
  }
  if (/(read_file|read_many|read_text|read_multiple|open_file|view_image)/.test(name)) {
    return withDetail('正在读取文件', path)
  }
  if (/(grep|ripgrep|code_search|search_code|find_files|glob)/.test(name)) {
    return withDetail('正在搜索代码', query || path)
  }
  if (/(shell|bash|exec_command|execute_command|run_command|terminal|powershell|cmd)/.test(name)) {
    return withDetail('正在运行命令', command)
  }
  return '正在调用工具'
}

function agentCandidates(agentsCtx) {
  try {
    return Array.from(agentsCtx.list() ?? [])
  } catch {
    return []
  }
}

function agentId(agent) {
  const value = agent?.session?.id
    ?? agent?.sessionId
    ?? agent?.session?.sessionId
    ?? agent?.id
  return typeof value === 'string' && value.length > 0 ? value : ''
}

/** Pick "running" while any live agent is running, otherwise idle. */
function aggregateStatus(agentsCtx) {
  return agentCandidates(agentsCtx).some((agent) => agent?.status === 'running')
    ? 'running'
    : 'idle'
}

function activeAgent(agentsCtx) {
  const agents = agentCandidates(agentsCtx)
  return agents.find((agent) => agent?.status === 'running') ?? agents[0] ?? null
}

function titleFromRecord(record) {
  const title = record?.rows?.title?.val
  return typeof title === 'string' ? title.trim() : ''
}

function titleFromSessionFile(raw) {
  try {
    const parsed = JSON.parse(raw)
    const title = titleFromRecord(parsed?.record ?? parsed)
    if (title) return title
  } catch {
    // Raw session files are JSONL; inspect their first line below.
  }
  try {
    const title = titleFromRecord(JSON.parse(raw.split(/\r?\n/, 1)[0]))
    if (title) return title
  } catch {
    // No usable title in this file.
  }
  return ''
}

function isActiveTurnFile(raw) {
  try {
    const parsed = JSON.parse(raw)
    const rows = parsed?.record?.rows
    const boundary = rows?.turnBoundary?.val
    return boundary?.openTurnStartSeq !== null
      && boundary?.openTurnStartSeq !== undefined
  } catch {
    return false
  }
}

function sessionCacheFiles(cacheRoot = SESSION_CACHE_DIR) {
  return readdirSync(cacheRoot)
    .filter((entry) => entry.endsWith('.json'))
    .map((entry) => {
      const fullPath = join(cacheRoot, entry)
      return {
        id: entry.slice(0, -5),
        fullPath,
        mtime: statSync(fullPath).mtimeMs,
      }
    })
    .sort((a, b) => b.mtime - a.mtime)
}

function selectedSessionFile(files, id) {
  if (!id) return files[0] ?? null
  if (!Array.isArray(files)) return null
  return files.find((item) => item.id === id || item.id.endsWith(id)) ?? files[0] ?? null
}

/**
 * Best-effort label for the task the pet is reacting to.
 *
 * dsh stores the user-facing title in the session projection cache under
 * `record.rows.title.val`. Raw session files are a fallback when a title has
 * not reached the cache yet.
 */
export function readSessionTask(agentsCtx, cacheRoot = SESSION_CACHE_DIR) {
  const agents = agentCandidates(agentsCtx)
  const selectedAgent = activeAgent(agentsCtx)

  try {
    for (const current of [selectedAgent, ...agents]) {
      if (!current) continue
      const header = current?.session?.header ?? current?.header
      if (header === undefined) continue
      const title = header.title ?? header.name
      if (typeof title === 'string' && title.trim().length > 0) return title.trim()
    }
  } catch {
    // Overlay text is optional.
  }
  const id = agentId(selectedAgent)

  try {
    const selected = selectedSessionFile(sessionCacheFiles(cacheRoot), id)
    if (selected) {
      const title = titleFromSessionFile(readFileSync(selected.fullPath, 'utf8'))
      if (title) return title
    }
  } catch {
    // Projection cache is optional.
  }

  try {
    const sessionRoot = join(homedir(), '.dsh', 'sessions')
    const directories = readdirSync(sessionRoot, { withFileTypes: true })
      .filter((entry) => entry.isDirectory())
      .map((entry) => {
        const fullPath = join(sessionRoot, entry.name)
        return { name: entry.name, fullPath, mtime: statSync(fullPath).mtimeMs }
      })
      .sort((a, b) => b.mtime - a.mtime)
    for (const item of directories) {
      const match = item.name.match(/session-([^/\\]+)/)?.[1]
      if (id && match !== id) continue
      const files = readdirSync(item.fullPath)
        .filter((name) => name.startsWith('session.v4.json'))
      for (const file of files) {
        const title = titleFromSessionFile(readFileSync(join(item.fullPath, file), 'utf8'))
        if (title) return title
      }
    }
  } catch {
    // Raw session tree is optional too.
  }

  return ''
}

/** Whether the selected dsh session is currently executing a turn. */
function hasActiveTurn(agentsCtx, cacheRoot = SESSION_CACHE_DIR) {
  const agent = activeAgent(agentsCtx)
  const id = agentId(agent)
  try {
    const selected = selectedSessionFile(sessionCacheFiles(cacheRoot), id)
    const activeTurn = selected
      ? isActiveTurnFile(readFileSync(selected.fullPath, 'utf8'))
      : false
    return activeTurn || agent?.status === 'running'
  } catch {
    return agent?.status === 'running'
  }
}

/** Write the current status to disk so a reloaded page starts in sync. */
function persistStatus(payload) {
  try {
    mkdirSync(dirname(STATE_PATH), { recursive: true })
    const body = JSON.stringify({ ...payload, updatedAt: new Date().toISOString() })
    writeFile(STATE_PATH, body, 'utf8').catch(() => {})
  } catch {
    // Best-effort persistence; never block a route on it.
  }
}

/**
 * Desktop overlay bridge.
 *
 * The Host cannot create Electron windows (verified: `require('electron')`
 * fails there), so the overlay is a separate tkinter process. Writing a small
 * JSON file and supervising one child keeps dsh alive even if the overlay dies.
 */
function createDesktopPet(ctx) {
  let child = null
  let stopping = false
  let lastLaunchAt = 0
  let launchPending = false
  const LAUNCH_LOG = join(DESKTOP_DIR, 'launch.log')

  function resolveDesktopExecutable() {
    try {
      const versioned = readdirSync(DESKTOP_DIR, { withFileTypes: true })
        .filter((entry) => entry.isFile())
        .map((entry) => {
          const match = entry.name.match(
            /^(?:dsh-pet-gujiguji|light-feather|mint-budgie)-(\d+)\.(\d+)\.(\d+)\.exe$/i,
          )
          if (!match) return null
          return {
            path: join(DESKTOP_DIR, entry.name),
            version: match.slice(1).map(Number),
          }
        })
        .filter(Boolean)
        .sort((left, right) => {
          for (let index = 0; index < 3; index += 1) {
            if (left.version[index] !== right.version[index]) {
              return right.version[index] - left.version[index]
            }
          }
          return 0
        })
      if (versioned.length > 0) return versioned[0].path
    } catch {
      // Fall through to the legacy single executable.
    }
    for (const name of ['dsh-pet-gujiguji.exe', 'light-feather.exe', 'mint-budgie.exe']) {
      const legacy = join(DESKTOP_DIR, name)
      if (existsSync(legacy)) return legacy
    }
    return null
  }

  function seedUserFiles() {
    try {
      mkdirSync(USER_DATA_DIR, { recursive: true })
      const migrate = (name, localSource, target) => {
        if (existsSync(target)) return
        const legacySource = LEGACY_USER_DATA_DIRS
          .map((directory) => join(directory, name))
          .find((candidate) => existsSync(candidate))
        if (legacySource) copyFileSync(legacySource, target)
        else if (existsSync(localSource)) copyFileSync(localSource, target)
      }
      migrate('position.json', DESKTOP_POSITION_PATH, USER_POSITION_PATH)
      migrate(
        'settings.json',
        DESKTOP_DEFAULT_SETTINGS_PATH,
        USER_SETTINGS_PATH,
      )
    } catch {
      // The packaged defaults remain usable if the migration fails.
    }
  }

  function log(message) {
    const line = `${new Date().toISOString()} ${message}\n`
    try {
      mkdirSync(DESKTOP_DIR, { recursive: true })
      writeFileSync(LAUNCH_LOG, line, { flag: 'a' })
    } catch {
      // Logging must never break the Host.
    }
  }

  const pythonCandidates = [
    process.env.DSH_PET_PYTHON,
    'pyw.exe',
    'pythonw.exe',
    'py.exe',
    'python.exe',
  ].filter((value) => typeof value === 'string' && value.length > 0)

  function writeDesktopState(status, task, sessionId, activity, completionSeq = 0) {
    try {
      mkdirSync(USER_DATA_DIR, { recursive: true })
      if (!existsSync(USER_STATE_PATH)) {
        writeFileSync(
          USER_STATE_PATH,
          JSON.stringify({
            status: 'idle',
            task: '',
            activity: '',
            sessionId: '',
            working: false,
          }),
        )
      }
      try { writeFileSync(DESKTOP_DSH_PID_PATH, String(process.ppid)) } catch { /* optional */ }
      const payload = JSON.stringify({
        status,
        task: task ?? '',
        activity: activity ?? '',
        sessionId: sessionId ?? '',
        completionSeq,
        // Status is authoritative here. A stale session projection can keep
        // an old turn marked open after the selected agent has gone idle.
        working: status !== 'idle',
        updatedAt: new Date().toISOString(),
      })
      writeFileSync(USER_STATE_PATH, payload, 'utf8')
    } catch {
      // Overlay is optional; never fail the Host because of it.
    }
  }

  function recordedPetPid() {
    try {
      const pid = Number.parseInt(readFileSync(DESKTOP_PROCESS_PATH, 'utf8'), 10)
      return Number.isFinite(pid) && pid > 0 ? pid : 0
    } catch {
      return 0
    }
  }

  function petRunning() {
    const pid = recordedPetPid()
    if (!pid) return false
    try {
      process.kill(pid, 0)
      return true
    } catch {
      try { unlinkSync(DESKTOP_PROCESS_PATH) } catch { /* optional */ }
      return false
    }
  }

  function launch() {
    if (petRunning()) return
    log(`launch requested child=${child !== null} stopping=${stopping} pending=${launchPending}`)
    if (stopping || launchPending) return
    if (existsSync(DESKTOP_HIDDEN_PATH)) {
      log('launch skipped: hidden flag')
      return
    }
    // Retry at most every 10s: a window that cannot start must not spin the Host.
    if (Date.now() - lastLaunchAt < 10000) return
    lastLaunchAt = Date.now()
    const desktopExe = resolveDesktopExecutable()
    const hasLauncher = desktopExe !== null || existsSync(DESKTOP_SCRIPT)
    if (!hasLauncher || !existsSync(DESKTOP_SPRITE)) {
      log(`launch skipped: exe=${desktopExe !== null} script=${existsSync(DESKTOP_SCRIPT)} sprite=${existsSync(DESKTOP_SPRITE)}`)
      return
    }

    launchPending = true
    try {
      seedUserFiles()
      if (desktopExe) {
        const args = [
          '--sprite', DESKTOP_SPRITE,
          '--state', USER_STATE_PATH,
          '--position', USER_POSITION_PATH,
          '--settings', USER_SETTINGS_PATH,
          '--parent-pid', String(process.pid),
          '--anchor-pid', String(process.ppid),
        ]
        if (!existsSync(LAUNCH_LOG)) {
          try { writeFileSync(LAUNCH_LOG, '') } catch { /* optional */ }
        }
        const out = openSync(LAUNCH_LOG, 'a')
        const spawned = spawn(desktopExe, args, {
          stdio: ['ignore', out, out],
          detached: true,
          windowsHide: true,
        })
        closeSync(out)
        spawned.unref()
        log(`spawn desktop exe=${desktopExe} pid=${spawned.pid ?? 'none'}`)
        if (spawned.pid) {
          try { writeFileSync(DESKTOP_PROCESS_PATH, String(spawned.pid)) } catch { /* optional */ }
        }
        spawned.once('error', (error) => {
          log(`desktop exe error ${error.code ?? ''} ${String(error.message).split('\n')[0]}`)
          child = null
          launchPending = false
        })
        spawned.once('exit', (code, signal) => {
          log(`desktop exe exit code=${code} signal=${signal}`)
          child = null
          launchPending = false
          if (!petRunning()) {
            try { unlinkSync(DESKTOP_PROCESS_PATH) } catch { /* optional */ }
          }
        })
        child = spawned
        launchPending = false
        return
      }
      for (const executable of pythonCandidates) {
        try {
          const args = [
            DESKTOP_SCRIPT,
            '--sprite', DESKTOP_SPRITE,
            '--state', USER_STATE_PATH,
            '--position', USER_POSITION_PATH,
            '--settings', USER_SETTINGS_PATH,
            '--parent-pid', String(process.pid),
            '--anchor-pid', String(process.ppid),
          ]
          // Keep stderr attached to a file so a silent interpreter failure is
          // still diagnosable.
          if (!existsSync(LAUNCH_LOG)) {
            try { writeFileSync(LAUNCH_LOG, '') } catch { /* optional */ }
          }
          const out = openSync(LAUNCH_LOG, 'a')
          const spawned = spawn(executable, args, {
            stdio: ['ignore', out, out],
            detached: true,
            windowsHide: true,
          })
          closeSync(out)
          spawned.unref()
          log(`spawn ${executable} pid=${spawned.pid ?? 'none'}`)
          if (spawned.pid) {
            try { writeFileSync(DESKTOP_PROCESS_PATH, String(spawned.pid)) } catch { /* optional */ }
          }
          spawned.once('error', (error) => {
            log(`spawn error ${error.code ?? ''} ${String(error.message).split('\n')[0]}`)
            child = null
            launchPending = false
          })
          spawned.once('exit', (code, signal) => {
            log(`launcher exit code=${code} signal=${signal}`)
            child = null
            launchPending = false
            // A Windows launcher may hand off to another pythonw process. Keep
            // the recorded pet PID unless the pet itself is gone.
            if (!petRunning()) {
              try { unlinkSync(DESKTOP_PROCESS_PATH) } catch { /* optional */ }
            }
          })
          child = spawned
          launchPending = false
          return
        } catch (error) {
          log(`spawn threw ${String(error).split('\n')[0]}`)
          child = null
        }
      }
      log('no python candidate could be started')
    } finally {
      launchPending = false
    }
  }

  return {
    lastTask: '',
    ensure() {
      try { unlinkSync(DESKTOP_HIDDEN_PATH) } catch { /* optional */ }
      launch()
    },
    hide() {
      try { writeFileSync(DESKTOP_HIDDEN_PATH, '') } catch { /* optional */ }
      const pid = recordedPetPid()
      if (pid > 0) {
        try { process.kill(pid) } catch { /* already gone */ }
      }
      child = null
      try { unlinkSync(DESKTOP_PROCESS_PATH) } catch { /* optional */ }
    },
    update(status, task, sessionId, activity, completionSeq = 0) {
      writeDesktopState(status, task, sessionId, activity, completionSeq)
    },
    stop() {
      stopping = true
      const pid = recordedPetPid()
      if (pid > 0) {
        try { process.kill(pid) } catch { /* already gone */ }
      }
      try { unlinkSync(DESKTOP_PROCESS_PATH) } catch { /* optional */ }
      child = null
    },
  }
}

/**
 * Register routes, the status poller, and the two transient signals.
 * @param {object} ctx - the Host plugin context.
 */
export function apply(ctx) {
  let current = 'idle'
  let lastWorking = null
  let pendingApprovals = 0
  let failedUntil = 0
  let latestActivity = ''
  let lastActivity = ''
  let completionSeq = 0
  const clients = new Set()
  const desktop = createDesktopPet(ctx)
  try {
    writeFileSync(DESKTOP_DSH_PID_PATH, String(process.ppid))
  } catch {
    // The launcher can still start the pet without the anchor PID.
  }

  /** Task label shared by the SSE payload and the desktop overlay. */
  function currentTask() {
    return readSessionTask(ctx.agents)
  }

  function currentSessionId() {
    return agentId(activeAgent(ctx.agents))
  }

  function activityForStatus(status) {
    if (status === 'running') return latestActivity || DEFAULT_RUNNING_ACTIVITY
    if (status === 'waiting') return '等待你的操作'
    if (status === 'failed') return '处理失败'
    if (status === 'review') return '正在审查'
    return ''
  }

  function currentPayload(status) {
    return {
      status,
      task: currentTask(),
      activity: activityForStatus(status),
      sessionId: currentSessionId(),
      working: status !== 'idle',
    }
  }

  /** Notify every connected SSE client of the latest full state. */
  function broadcast(status, payload = currentPayload(status)) {
    const body = `data: ${JSON.stringify(payload)}\n\n`
    for (const res of clients) {
      try { res.write(body) } catch { clients.delete(res) }
    }
  }

  /** Publish status changes, and refresh desktop when working changes. */
  function setStatus(next) {
    const working = next !== 'idle'
    const activity = activityForStatus(next)
    if (next === current && working === lastWorking && activity === lastActivity) return
    current = next
    lastWorking = working
    lastActivity = activity
    const payload = currentPayload(current)
    persistStatus(payload)
    broadcast(current, payload)
    desktop.update(
      payload.status,
      payload.task,
      payload.sessionId,
      payload.activity,
      completionSeq,
    )
  }

  /**
   * Transient signals outrank the poll: an approval prompt or a fresh failure
   * must not be overwritten by `running` on the next tick.
   */
  function sample() {
    if (pendingApprovals > 0) return setStatus('waiting')
    if (Date.now() < failedUntil) return setStatus('failed')
    setStatus(aggregateStatus(ctx.agents))
  }

  // SSE stream of agent status changes.
  ctx.effect(() => ctx.webServer.register({
    kind: 'exact',
    path: STATUS_PATH,
    handler: (req, res) => {
      const rejection = ctx.connection.requestRejection(req)
      if (rejection !== undefined) { res.statusCode = rejection; res.end(); return }
      if (req.method !== 'GET') { res.statusCode = 405; res.end(); return }
      res.writeHead(200, {
        'content-type': 'text/event-stream; charset=utf-8',
        'cache-control': 'no-cache',
        connection: 'keep-alive',
      })
      res.write(`data: ${JSON.stringify(currentPayload(current))}\n\n`)
      clients.add(res)
      req.on('close', () => clients.delete(res))
    },
  }), `${name}: GET ${STATUS_PATH}`)

  // Spritesheet bytes; the client fetches the pet art from here.
  ctx.effect(() => ctx.webServer.register({
    kind: 'exact',
    path: SPRITE_ROUTE,
    handler: (req, res) => {
      const rejection = ctx.connection.requestRejection(req)
      if (rejection !== undefined) { res.statusCode = rejection; res.end(); return }
      if (!existsSync(SPRITE_PATH)) { res.statusCode = 404; res.end(); return }
      readFile(SPRITE_PATH).then((buf) => {
        res.writeHead(200, {
          'content-type': 'image/webp',
          'cache-control': 'public, max-age=3600',
          'content-length': buf.length,
        })
        res.end(buf)
      }).catch(() => { res.statusCode = 500; res.end() })
    },
  }), `${name}: GET ${SPRITE_ROUTE}`)

  // Mirror the in-app visibility toggle to the desktop overlay.
  ctx.effect(() => ctx.webServer.register({
    kind: 'exact',
    path: SETTINGS_ROUTE,
    handler: (req, res) => {
      const rejection = ctx.connection.requestRejection(req)
      if (rejection !== undefined) { res.statusCode = rejection; res.end(); return }
      if (req.method !== 'POST') { res.statusCode = 405; res.end(); return }
      let body = ''
      req.setEncoding('utf8')
      req.on('data', (chunk) => {
        if (body.length < 4096) body += chunk
      })
      req.on('end', () => {
        try {
          const payload = JSON.parse(body)
          if (payload.visible === false) desktop.hide()
          res.writeHead(204, { 'cache-control': 'no-store' })
          res.end()
        } catch {
          res.statusCode = 400
          res.end()
        }
      })
    },
  }), `${name}: POST ${SETTINGS_ROUTE}`)

  // A failed step shows the failure row briefly, then falls back to the poll.
  ctx.effect(() => ctx.on('agent/error', () => {
    failedUntil = Date.now() + FAILED_HOLD_MS
    setStatus('failed')
  }), `${name}: agent/error`)

  // Tool hooks provide the current action shown on the second bubble line.
  // They only observe execution; the actual call still runs unchanged.
  ctx.effect(() => ctx.on('tools/execute', (exec, next) => {
    latestActivity = toolActivity(exec)
    setStatus('running')
    return next()
  }, { global: true }), `${name}: tool activity`)

  // Once model output starts again, the previous tool has finished.
  ctx.effect(() => ctx.on('agent/assistant-stream', (payload) => {
    if (payload?.frame?.type === 'start') {
      latestActivity = DEFAULT_RUNNING_ACTIVITY
      setStatus('running')
    }
  }, { global: true }), `${name}: model activity`)

  // Clear the tool wording at turn boundaries so the next turn starts clean.
  ctx.effect(() => ctx.on('session/event', (_session, event) => {
    if (event?.type === 'turn/start') {
      latestActivity = DEFAULT_RUNNING_ACTIVITY
      setStatus('running')
    } else if (event?.type === 'turn/end') {
      latestActivity = ''
      sample()
      if (isCompletedTurn(event)) {
        completionSeq += 1
        const task = currentTask()
        const sessionId = currentSessionId()
        desktop.update(
          current,
          task,
          sessionId,
          activityForStatus(current),
          completionSeq,
        )
      }
    }
  }, { global: true }), `${name}: turn activity`)

  // An approval prompt means the agent is waiting on the user.
  ctx.effect(() => ctx.on('approval/request', (request, next) => {
    pendingApprovals += 1
    setStatus('waiting')
    const settle = () => {
      pendingApprovals = Math.max(0, pendingApprovals - 1)
      sample()
    }
    try {
      const outcome = next()
      if (outcome && typeof outcome.then === 'function') {
        return outcome.finally(settle)
      }
      settle()
      return outcome
    } catch (error) {
      settle()
      throw error
    }
  }), `${name}: approval/request`)

  // Poll status and refresh the state file. Effects return their disposer;
  // creating the timers inside the effect keeps them alive until unload.
  ctx.effect(() => {
    const timer = setInterval(sample, POLL_MS)
    const taskTimer = setInterval(() => {
      const task = currentTask()
      const sessionId = currentSessionId()
      const activity = activityForStatus(current)
      desktop.update(current, task, sessionId, activity, completionSeq)
      if (task !== desktop.lastTask) {
        desktop.lastTask = task
        broadcast(current, { ...currentPayload(current), task, sessionId, activity })
      }
    }, 1000)
    return () => {
      clearInterval(timer)
      clearInterval(taskTimer)
      desktop.stop()
      for (const res of clients) { try { res.end() } catch { /* noop */ } }
      clients.clear()
    }
  }, `${name}: poll + cleanup`)

  // Seed once so the overlay and a freshly registered client see a real value.
  const initial = currentPayload(current)
  desktop.update(
    initial.status,
    initial.task,
    initial.sessionId,
    initial.activity,
    completionSeq,
  )
  sample()
  desktop.ensure()
}
