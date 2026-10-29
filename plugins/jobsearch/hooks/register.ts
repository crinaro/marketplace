// jobsearch mod (dev #750 part 1; design docs/design-local-surfaces-and-mods.md section 3).
//
// WHAT IT IS. A zero-token status panel for a job-search profile: a band under the prompt, a pane,
// Run daily / Run weekly buttons that start the SCHEDULED TASK as its own session, three commands
// that open panes (status, review-resume, review-linkedin), and a watcher that wakes the
// coordinator when a background run queues work. It holds no logic a script can hold: every number
// it shows comes from scripts/panel.py or scripts/presence_set.py, and every pane tree is built by
// the pure functions in panel.tsx.
//
// WHAT IT NEVER DOES (the trust obligation, enforced in CI by the repository mod-surface gate, which does not ship):
//   - write a profile file (no fs write, no store, no model call, no http, no process spawn). The ONE way a profile
//     changes through this mod is a Sources button, which runs `record.py source <on|off> <id>` and nothing else: the
//     write is that script's, under its own lock and validator (ADR-036, amended by dev #774). The mod-surface gate
//     holds the list of scripts the mod may launch, and record.py is allowed only with the `source` sub-verb;
//   - read mail or browser state; handle a tool call it did not register; approve or rewrite one;
//   - run on a refused surface differently: NO runtime refusal is built (change R2) - S3b and S4
//     are unsupported by documentation (plugins/jobsearch/docs/deployment.md, Supported surfaces).
//
// Every mods API call is written in full as the host's static analysis requires, and `$` is passed
// only to functions declared at the top level of this file.

import {
  PANES, canDrawPane, statusTree, reviewTree,
  reviseText, runTaskText, drainText,
} from './panel'

const TASKS: any = { daily: 'search-daily', weekly: 'search-strategy-weekly' }
const FAST_MS = 120000
const FULL_MS = 1800000
const WATCH_MS = 60000
const SURFACE_OF: any = { resume: 'print', linkedin: 'public-profile' }

// Module state. It is lost on a reload (/reload-plugins), which re-runs session.start; the watcher
// is then disarmed until the coordinator calls jobsearch_watch again (its startup step does).
let profileRoot: string | null = null
let snapshot: any = null
let reviews: any = {}
let reviewTabs: any = {}
let note = ''
let busy: any = { fast: false, full: false }
let armed = false
let lastSig = ''
let lastUnacked = 0
let pendingText: string | null = null

async function py($: any, script: string, args: string[], timeoutMs: number): Promise<any> {
  const cwd = await $.session.cwd()
  return $.process.run(['python3', $.plugin.root + '/scripts/' + script].concat(args), { cwd, timeoutMs })
}

function parseJson(stdout: string): any {
  try {
    return JSON.parse(stdout)
  } catch {
    return { error: 'the script printed something that is not JSON' }
  }
}

async function refresh($: any, full: boolean): Promise<void> {
  const k = full ? 'full' : 'fast'
  if (busy[k]) return
  busy[k] = true
  try {
    const r = await py($, 'panel.py', ['--json', full ? '--full' : '--fast'], full ? 60000 : 20000)
    const obj = r.exitCode === 0 ? parseJson(r.stdout) : { error: 'panel.py exited ' + r.exitCode }
    if (obj.error) {
      snapshot = Object.assign({}, snapshot || {}, { band: 'jobsearch · NOT CHECKED (' + obj.error + ')' })
    } else {
      snapshot = full ? obj : Object.assign({}, snapshot || {}, obj)
    }
    $.ui.status(snapshot.band)
    $.ui.invalidate('ui.render')
  } catch (err) {
    $.ui.status('jobsearch · NOT CHECKED (' + String(err && (err as any).message ? (err as any).message : err).slice(0, 80) + ')')
  } finally {
    busy[k] = false
  }
}

// dev #774: a Sources button. The mod runs the SAME verb the text path runs and relays its own first line; it writes
// no file, keeps nothing in $.store, and decides nothing about what "on" means.
async function toggleSource($: any, id: string, enabled: boolean): Promise<void> {
  const verb = enabled ? 'on' : 'off'
  try {
    const r = await py($, 'record.py', ['source', verb, id], 30000)
    const lines = String(r.stdout || r.stderr || '').split('\n').map((l: string) => l.trim()).filter((l: string) => l)
    const refusal = lines.find((l: string) => l.includes('REFUSED'))
    note = r.exitCode === 0
      ? 'Turned ' + verb + ' ' + id + '.'
      : (refusal || lines[lines.length - 1] || 'record.py source exited ' + r.exitCode).slice(0, 200)
    $.ui.toast(note)
  } catch (err) {
    note = 'Could not turn ' + verb + ' ' + id + ': ' + String(err && (err as any).message ? (err as any).message : err).slice(0, 100)
    $.ui.toast(note)
  }
  await refresh($, true)
}

async function refreshReview($: any, which: string): Promise<void> {
  try {
    const r = await py($, 'presence_set.py', ['--json', '--surface', SURFACE_OF[which]], 30000)
    reviews[which] = r.exitCode === 0 ? parseJson(r.stdout) : { error: 'presence_set.py exited ' + r.exitCode }
  } catch (err) {
    reviews[which] = { error: String(err && (err as any).message ? (err as any).message : err).slice(0, 80) }
  }
  $.ui.invalidate('ui.render')
}

// The documented retry pattern: a submit refused or dropped after the user interrupts is kept and
// repeated from turn.complete. Not awaited by callers that may run while Claude is working.
async function submitPrompt($: any, text: string): Promise<void> {
  let reason = ''
  try {
    const result = await $.prompt.submit({ text })
    reason = (result && result.drop) || ''
  } catch (error) {
    reason = String((error as any) && (error as any).message ? (error as any).message : error)
  }
  if (reason.includes('the session was stopped and nobody has sent input since') ||
      reason.includes('was removed from the queue before it ran')) {
    pendingText = text
  }
}

// Run now: the scheduled task starts as its OWN session. Either the host's tool is reachable from
// a mod (the first branch) or one short turn is asked to fire it (the second); in neither does any
// daily-run step run in the coordinator's session.
async function runTask($: any, which: string): Promise<void> {
  const taskId = TASKS[which]
  try {
    await $.mcp.call('scheduled-tasks', 'run_scheduled_task', { taskId })
    note = 'Started ' + taskId + ' as its own session.'
    $.ui.toast(note)
    $.ui.invalidate('ui.render')
    return
  } catch (err) {
    // not reachable from a mod, or refused (disabled / already running): fall through to the turn
  }
  note = 'Asked the session to start ' + taskId + '.'
  $.ui.invalidate('ui.render')
  submitPrompt($, runTaskText(taskId))
}

// Render is the one command the pane starts: /jobsearch:resume <variant>, as a command run (the host
// refuses slash text in a submitted prompt). It is the only command this mod ever runs.
async function renderVariant($: any, variantId: string): Promise<void> {
  try {
    await $.command.run({ command: 'jobsearch:resume', args: variantId })
  } catch (err) {
    $.ui.toast('Render could not start: ' + String((err as any) && (err as any).message ? (err as any).message : err).slice(0, 100))
  }
}

async function textFor($: any, which: string): Promise<string> {
  try {
    const r = which === 'status'
      ? await py($, 'panel.py', ['--text', '--full'], 60000)
      : await py($, 'presence_set.py', ['--text', '--surface', SURFACE_OF[which]], 30000)
    return r.exitCode === 0 ? r.stdout : 'jobsearch: NOT CHECKED (' + (r.stderr || 'exit ' + r.exitCode).slice(0, 200) + ')'
  } catch (err) {
    return 'jobsearch: NOT CHECKED (' + String((err as any) && (err as any).message ? (err as any).message : err).slice(0, 120) + ')'
  }
}

// One handler body for the three commands and their hyphenated twins. Returns {} after opening a
// pane (no transcript line, no model turn) and { text } wherever a pane cannot be drawn.
async function openCommand($: any, e: any, which: string): Promise<any> {
  const surfaces = await $.session.surfaces()
  if (!canDrawPane(e.origin, surfaces)) return { text: await textFor($, which) }
  if (which === 'status') {
    await refresh($, true)
  } else {
    await refreshReview($, which)
  }
  await $.ui.open({ id: PANES[which as 'status'], title: which === 'status' ? 'jobsearch status' : 'review ' + which, focus: true, closeOnEscape: true })
  return {}
}

function paneFor($: any, els: any, id: string, surface: string): any {
  if (id === PANES.status) {
    const h = {
      refresh: () => refresh($, true),
      runDaily: () => runTask($, 'daily'),
      runWeekly: () => runTask($, 'weekly'),
      toggleSource: (id: string, enabled: boolean) => toggleSource($, id, enabled),
    }
    return statusTree(els, snapshot, surface === 'desktop', note, h)
  }
  const which = id === PANES.resume ? 'resume' : 'linkedin'
  const model = reviews[which]
  const h = {
    selectTab: (tab: string) => { reviewTabs[which] = tab; $.ui.invalidate('ui.render') },
    revise: (variantId: string) => submitPrompt($, reviseText(SURFACE_OF[which], variantId)),
    render: (variantId: string) => renderVariant($, variantId),
    refresh: () => refreshReview($, which),
  }
  return reviewTree(els, model, reviewTabs[which] || 'union', h)
}

// The watcher: armed ONLY by the coordinator calling jobsearch_watch (a scheduled run's own
// session never does, or it would wake itself on its own inbox write and drain its own queue).
async function watchTick($: any): Promise<void> {
  let st: any
  try {
    st = await $.fs.stat(profileRoot + '/data/inbox.jsonl')
  } catch (err) {
    return
  }
  const sig = st.size + ':' + st.mtimeMs
  if (sig === lastSig) return
  lastSig = sig
  const r = await py($, 'panel.py', ['--json', '--fast'], 20000)
  const obj = r.exitCode === 0 ? parseJson(r.stdout) : { error: 'panel.py exited ' + r.exitCode }
  if (obj.error || !obj.inbox || typeof obj.inbox.unacked !== 'number') return
  const n = obj.inbox.unacked
  const added = n - lastUnacked
  lastUnacked = n
  if (added > 0) await submitPrompt($, drainText(added, obj.inbox.urgent || 0))
}

async function arm($: any): Promise<string> {
  if (armed) return 'already armed'
  armed = true
  try {
    const st = await $.fs.stat(profileRoot + '/data/inbox.jsonl')
    lastSig = st.size + ':' + st.mtimeMs
  } catch (err) {
    lastSig = ''
  }
  const r = await py($, 'panel.py', ['--json', '--fast'], 20000)
  const obj = r.exitCode === 0 ? parseJson(r.stdout) : {}
  lastUnacked = obj.inbox && typeof obj.inbox.unacked === 'number' ? obj.inbox.unacked : 0
  $.clock.every(WATCH_MS, () => watchTick($))
  return 'Armed: this session will be woken when a background run queues work.'
}

export function register(on: any) {
  on('session.start', async ($: any, e: any, next: any) => {
    // Only a session whose cwd is inside a profile gets anything: no band, no timer, no command,
    // so a user-scope install costs nothing elsewhere and one profile never draws in another's session.
    try {
      const p = await py($, 'panel.py', ['--probe'], 10000)
      const probe = p.exitCode === 0 ? parseJson(p.stdout) : {}
      profileRoot = probe.profile ? probe.root : null
    } catch (err) {
      profileRoot = null
    }
    if (profileRoot) {
      for (const name of ['jobsearch-status', 'jobsearch-review-resume', 'jobsearch-review-linkedin']) {
        try {
          await $.command.register({ name, description: 'jobsearch: ' + name.slice(10).replace('-', ' ') })
        } catch (err) {
          // a taken name: the markdown command of the same purpose still works
        }
      }
      try {
        await $.tool.register({
          name: 'jobsearch_watch',
          description: 'Arm this session to be woken when a background job-search run queues work. ' +
            'Call once, from the coordinator\'s startup only; never from a scheduled run.',
          inputSchema: { type: 'object', properties: {} },
        })
      } catch (err) {
        // already registered by a reload
      }
      $.clock.every(FAST_MS, () => refresh($, false))
      $.clock.every(FULL_MS, () => refresh($, true))
      refresh($, true)
    }
    return next(e)
  })

  on('command.run', { command: ['status', 'jobsearch:status', 'jobsearch-status'] },
    async ($: any, e: any) => openCommand($, e, 'status'))
  on('command.run', { command: ['review-resume', 'jobsearch:review-resume', 'jobsearch-review-resume'] },
    async ($: any, e: any) => openCommand($, e, 'resume'))
  on('command.run', { command: ['review-linkedin', 'jobsearch:review-linkedin', 'jobsearch-review-linkedin'] },
    async ($: any, e: any) => openCommand($, e, 'linkedin'))

  // The ONE tool.call this mod handles is for the tool it registered itself.
  on('tool.call', { tool: 'mcp__jobsearch__jobsearch_watch' }, async ($: any) => {
    if (!profileRoot) return { result: 'Not armed: this session is not inside a job-search profile.' }
    return { result: await arm($) }
  })

  on('turn.complete', async ($: any, e: any, next: any) => {
    if (pendingText !== null) {
      const text = pendingText
      pendingText = null
      submitPrompt($, text)
    }
    return next(e)
  })

  on('ui.render', { component: 'Pane' }, async ($: any, e: any, next: any) => {
    if (e.requestId !== PANES.status && e.requestId !== PANES.resume && e.requestId !== PANES.linkedin) {
      return next(e)
    }
    return paneFor($, $.ui.resolve(e), e.requestId, e.surface)
  })
}
