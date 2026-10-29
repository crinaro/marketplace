// jobsearch mod: the pane trees. PURE: functions of data in, element trees out.
//
// This file takes no mods API object and makes no call of its own (dev #750, design section 3.1,
// change B5): `claude plugin validate` reads only the files listed under `modules`, so a mods API
// call hidden here would be invisible to the repository mod-surface gate (a maintenance check that does not ship). That gate refuses any
// dollar sign in this file, so keep it out of strings and comments too. Every handler a button
// needs is passed IN by register.ts; every element constructor is passed in as `els`, the table
// the host hands register.ts and no more.
//
// The data it draws is the JSON of scripts/panel.py (the status pane) and of
// scripts/presence_set.py --json --surface <s> (a review pane). The mod holds no logic a script
// can hold: it renders, and the scripts decide.

export type Els = {
  Box: (p: any) => any
  Text: (p: any) => any
  Button: (p: any) => any
  Markdown: (p: any) => any
}

export const RUN_NOW_ELSEWHERE = "Run now lives in the Desktop app's Scheduled sidebar."

// Which pane id belongs to which view. register.ts opens them; ui.render dispatches on them.
export const PANES = {
  status: 'jobsearch-status',
  resume: 'jobsearch-review-resume',
  linkedin: 'jobsearch-review-linkedin',
}

// A command typed where a pane cannot be drawn must get TEXT, not a pane on some other screen.
// The signal is the command's origin: only a person's own Enter at the composer, in a session
// that has a surface attached, draws a pane. Anything else (a Remote Control bridge, the SDK, a
// plugin, a scheduled trigger) gets text. Whether a phone-typed command arrives as `bridge` is
// probe P-7, NOT RUN: until it is run that column stays UNVERIFIED (docs/surface_probes.json).
export function canDrawPane(origin: any, surfaces: any): boolean {
  const kind = origin && origin.kind
  return kind === 'composer' && Array.isArray(surfaces) && surfaces.length > 0
}

export function isFailure(v: any): boolean {
  return !v || typeof v !== 'object' || 'error' in v
}

function txt(els: Els, s: string, extra?: any): any {
  return els.Text({ children: [s], ...(extra || {}) })
}

function section(els: Els, title: string, lines: string[], empty: string): any {
  const body = lines.length ? lines : [empty]
  return els.Box({
    flexDirection: 'column',
    children: [
      txt(els, title, { bold: true }),
      els.Box({ flexDirection: 'column', paddingLeft: 2, children: body.map((l) => txt(els, l)) }),
    ],
  })
}

function notChecked(v: any): string | null {
  return v && typeof v === 'object' && 'error' in v ? 'NOT CHECKED (' + v.error + ')' : null
}

// ---- the status pane --------------------------------------------------------------------------

export function needsYouLines(snap: any): string[] {
  const ny = snap && snap.needs_you
  if (notChecked(ny)) return [notChecked(ny) as string]
  if (!Array.isArray(ny)) return ['NOT CHECKED (no data yet)']
  return ny.map((r: any) => '[' + (r.act_by || 'no date') + '] ' + r.kind + ': ' + r.title)
}

// dev #761: roles whose stored comp removal jobsearch 0.73.0 would not repeat. The pane only DRAWS
// what scripts/panel.py decided: it flags, it never reopens, and the one-step action is text the
// person runs themselves (record.py decide, then record.py screened).
export function rescreenLines(snap: any): string[] {
  const rf = snap && snap.rescreen_flags
  if (notChecked(rf)) return [notChecked(rf) as string]
  if (!rf || !Array.isArray(rf.items)) return ['NOT CHECKED (no data yet)']
  const out: string[] = []
  if (rf.count) out.push(rf.count + ' (nothing was changed; only you reopen or dismiss)')
  if (Array.isArray(rf.unreadable) && rf.unreadable.length) {
    out.push('NOT CHECKED: ' + rf.unreadable.length + ' could not be re-screened: ' + rf.unreadable.join(', '))
  }
  for (const r of rf.items.slice(0, 12)) {
    out.push(r.title + ' (' + r.id + '): was ' + r.old_verdict + ', now ' + r.new_verdict + '. ' + r.why)
    out.push('  to reopen: ' + r.action)
  }
  return out
}

export function systemLines(snap: any): string[] {
  const out: string[] = []
  const ib = snap && snap.inbox
  out.push(notChecked(ib) || ('inbox: ' + (ib ? ib.unacked + ' pending, ' + ib.urgent + ' urgent' : 'NOT CHECKED')))
  const lk = snap && snap.lock
  if (notChecked(lk)) out.push('lock: ' + notChecked(lk))
  else if (lk && lk.held) out.push('lock: HELD by ' + (lk.by || '?') + ' since ' + lk.since)
  else out.push('lock: free')
  const rn = snap && snap.runs
  if (notChecked(rn)) out.push('runs: ' + notChecked(rn))
  else if (rn) {
    out.push('last run: ' + (rn.last_at || 'none recorded') + (rn.last_task ? ' (' + rn.last_task + ')' : ''))
    out.push('next run: ' + (rn.next_at || 'unknown') + ' (' + rn.next_task + '); weekly ' + rn.next_weekly)
  } else out.push('runs: NOT CHECKED')
  const re = snap && snap.runs_effect
  out.push('background runs did anything: ' + (notChecked(re) || (re ? re.verdict + ' - ' + re.detail : 'not computed yet')))
  const db = snap && snap.dashboard
  out.push('dashboard: ' + (notChecked(db) || (db ? db.state + ' (generated ' + (db.as_of || 'never') + ')' : 'not computed yet')))
  const gs = snap && snap.gates
  if (notChecked(gs)) out.push('gate health: ' + notChecked(gs))
  else if (Array.isArray(gs)) {
    for (const g of gs) {
      out.push('gate ' + g.name + ': ' + (g.ok === true ? 'ok' : g.ok === null ? 'not checked (timed out)' : 'FAILING'))
    }
  } else out.push('gate health: not computed yet')
  return out
}

function elsewhereLines(snap: any, key: string): string[] {
  const el = snap && snap.elsewhere
  if (notChecked(el)) return [notChecked(el) as string]
  if (!el || !Array.isArray(el[key])) return ['not computed yet']
  return el[key].slice(0, 12).map((r: any) => String(r.title || r.id || r.path))
}

export type StatusHandlers = {
  refresh: () => any
  runDaily: () => any
  runWeekly: () => any
  // dev #774: turn one job source on or off. register.ts runs `record.py source <on|off> <id>` and nothing else; this
  // file only draws the button and says which way it turns.
  toggleSource?: (id: string, enabled: boolean) => any
}

// dev #774: the Sources block. One row per job source (scripts/panel.py's `elsewhere.sources`, which is
// `sources.report`): its title, kind and state, and ONE button that turns it the other way. The pane decides nothing:
// whether a source is on comes from the script, and the write is the script's.
export function sourceRows(snap: any): any[] | null {
  const el = snap && snap.elsewhere
  if (!el || notChecked(el)) return null
  const s = el.sources
  if (!Array.isArray(s)) return null
  return s
}

export function sourcesSection(els: Els, snap: any, handlers: StatusHandlers): any {
  const el = snap && snap.elsewhere
  const rows = sourceRows(snap)
  if (el && notChecked(el.sources)) {
    return section(els, 'Sources', [notChecked(el.sources) as string], '')
  }
  if (rows === null) return section(els, 'Sources', ['not computed yet'], '')
  if (!rows.length) return section(els, 'Sources', [], 'no job source is set up yet')
  const lines = rows.slice(0, 20).map((r: any) => {
    const label = String(r.title || r.id) + '  [' + r.kind + ']  ' + (r.on ? 'on' : String(r.state))
    return els.Box({
      key: 'source-row-' + r.id,
      flexDirection: 'row',
      columnGap: 2,
      children: [
        txt(els, label),
        handlers.toggleSource
          ? els.Button({
              key: 'source-' + r.id,
              label: r.on ? 'Turn off' : 'Turn on',
              onPress: () => (handlers.toggleSource as any)(String(r.id), !r.on),
            })
          : txt(els, ' '),
      ],
    })
  })
  return els.Box({
    flexDirection: 'column',
    children: [txt(els, 'Sources', { bold: true }), els.Box({ flexDirection: 'column', paddingLeft: 2, children: lines })],
  })
}

// `canRun`: the Run buttons exist only where the Desktop app's scheduler does (surface 'desktop').
export function statusTree(els: Els, snap: any, canRun: boolean, note: string, handlers: StatusHandlers): any {
  const held = !!(snap && snap.lock && snap.lock.held)
  const runRow: any[] = []
  if (!canRun) {
    runRow.push(txt(els, RUN_NOW_ELSEWHERE))
  } else if (held) {
    // The scheduled task is refused while it is already running: say so instead of offering it.
    runRow.push(txt(els, 'run in progress'))
  } else {
    runRow.push(els.Button({ key: 'run-daily', label: 'Run daily now', onPress: handlers.runDaily }))
    runRow.push(els.Button({ key: 'run-weekly', label: 'Run weekly now', onPress: handlers.runWeekly }))
  }
  return els.Box({
    flexDirection: 'column',
    rowGap: 1,
    children: [
      txt(els, (snap && snap.band) || 'jobsearch', { bold: true }),
      section(els, 'Needs you', needsYouLines(snap), 'nothing is waiting on you'),
      section(els, 'Roles to reconsider', rescreenLines(snap), 'none: no stored comp removal would be screened differently today'),
      section(els, 'System', systemLines(snap), 'no data'),
      section(els, 'In flight', elsewhereLines(snap, 'in_flight'), 'nothing in flight'),
      section(els, 'This week', elsewhereLines(snap, 'week').concat(
        snap && snap.elsewhere && Array.isArray(snap.elsewhere.preps_owed) && snap.elsewhere.preps_owed.length
          ? ['preps owed: ' + snap.elsewhere.preps_owed.length] : []), 'no calls this week'),
      section(els, 'Channels due', elsewhereLines(snap, 'channels_due'), 'none due'),
      sourcesSection(els, snap, handlers),
      section(els, 'Open asks', elsewhereLines(snap, 'asks'), 'none open'),
      els.Box({
        flexDirection: 'row',
        columnGap: 2,
        children: [els.Button({ key: 'refresh', label: 'Refresh', onPress: handlers.refresh }), ...runRow],
      }),
      note ? txt(els, note, { dimColor: true }) : txt(els, ' '),
    ],
  })
}

// ---- a review pane ----------------------------------------------------------------------------

export type ReviewHandlers = {
  selectTab: (tab: string) => any
  revise: (variantId: string) => any
  render: (variantId: string) => any
  refresh: () => any
}

export function reviewTabs(model: any): { key: string; label: string }[] {
  const tabs = [{ key: 'union', label: (model.union && model.union.title) || 'The claim union' }]
  for (const v of model.variants || []) tabs.push({ key: 'v:' + v.id, label: v.title || v.id })
  tabs.push({ key: 'open', label: 'Open items' })
  tabs.push({ key: 'rules', label: 'Rules' })
  return tabs
}

function stripLine(v: any): string {
  const s = v.strip || {}
  if (s.cap == null) return (s.note || 'no character cap is recorded for this surface')
  return 'limit ' + s.cap + ' · used ' + s.count + (s.as_of ? ' · as of ' + s.as_of : '')
}

export function reviewTree(els: Els, model: any, tab: string, handlers: ReviewHandlers): any {
  if (isFailure(model)) {
    return txt(els, 'NOT CHECKED (' + (model && model.error ? model.error : 'no data yet') + ')')
  }
  const tabs = reviewTabs(model)
  const active = tabs.some((t) => t.key === tab) ? tab : 'union'
  const tabRow = els.Box({
    flexDirection: 'row',
    columnGap: 2,
    children: tabs.map((t) =>
      els.Button({
        key: 'tab-' + t.key,
        label: t.label,
        plain: true,
        dimColor: t.key !== active,
        onPress: () => handlers.selectTab(t.key),
      }),
    ),
  })
  let body: any[] = []
  let actions: any[] = []
  if (active === 'union') {
    body = (model.union.paragraphs || []).map((p: string, i: number) => els.Markdown({ key: 'u' + i, text: p }))
  } else if (active === 'open') {
    const items: any[] = model.open_items || []
    body = items.length
      ? items.map((it: any) => txt(els, '[' + it.category + '] ' + it.text))
      : [txt(els, 'no open items')]
  } else if (active === 'rules') {
    body = [els.Markdown({ key: 'rules', text: (model.rules && model.rules.markdown) || 'no rules file' })]
  } else {
    const id = active.slice(2)
    const v = (model.variants || []).find((x: any) => x.id === id)
    if (!v) {
      body = [txt(els, 'variant ' + id + ' is not declared')]
    } else {
      // Caps and counts sit in a strip OUTSIDE the preview (ADR-028 rules 1 and 6).
      body = [txt(els, stripLine(v), { dimColor: true })].concat(
        v.state === 'active'
          ? (v.paragraphs || []).map((p: string, i: number) => els.Markdown({ key: 'p' + i, text: p }))
          : [txt(els, 'no preview: ' + (v.note || v.state))],
      )
      actions.push(els.Button({ key: 'revise', label: 'Revise with Claude', onPress: () => handlers.revise(id) }))
      if (model.surface === 'print') {
        actions.push(els.Button({ key: 'render', label: 'Render', onPress: () => handlers.render(id) }))
      }
    }
  }
  return els.Box({
    flexDirection: 'column',
    rowGap: 1,
    children: [
      tabRow,
      els.Box({ flexDirection: 'column', children: body }),
      els.Box({
        flexDirection: 'row',
        columnGap: 2,
        children: [els.Button({ key: 'refresh', label: 'Refresh', onPress: handlers.refresh }), ...actions],
      }),
    ],
  })
}

// The submitted texts are built here, from data, so a test can read them without a session.
export function reviseText(surface: string, variantId: string): string {
  return 'Revise the "' + variantId + '" variant of the ' + surface + ' layer with profile-optimizer. ' +
    'Work through the open items for it, edit the source file under the write lock, and regenerate nothing by hand.'
}

// (The Render button runs /jobsearch:resume <variant> as a COMMAND RUN from register.ts: the host
// refuses slash text in a submitted prompt.)

export function runTaskText(taskId: string): string {
  return 'Start the scheduled task "' + taskId + '" with run_scheduled_task and report only whether it started. ' +
    'Do not run any daily-run step in this session.'
}

export function drainText(n: number, urgent: number): string {
  return 'A background run queued ' + n + ' new item(s) (' + urgent + ' urgent). Drain the queue.'
}
