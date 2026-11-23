"""The page frame (dashboard-redesign A, moved from generate_dashboard.py): the jump bar, the stylesheet and
`render`, which assembles the sections in the page's order."""
import html

from dashboard import rank, today as today_ui
from dashboard.caps import TODAY_CAP
from dashboard.actions_ui import COPY_NOTE, PICK_SCRIPT, SHARED_FALLBACK
from dashboard.markup import esc
from dashboard.network import NETWORK_SECTION
from dashboard.roles import READ_SECTION, RESCREEN_SECTION
from dashboard.targets import TARGETS_SECTION


JUMP_TARGETS = (("Drafts", "phase-outreach-approvals"), ("Opportunities", "phase-pipeline-roles"),
                ("Applications", "phase-applying-finish"))


def render_jump_bar(n_drafts, n_opps, n_apply=None, n_flags=None, n_read=None, n_network=None, n_targets=None,
                    today=None):
    """The pinned jump bar (OWNER REQUEST 2026-10-13, three entries since jobsearch 0.71.0):
    `Drafts (N)`, `Opportunities (N)` and `Applications (N)`, each an in-page link to its list's
    heading. Pinned by CSS `position: sticky` only - no script - and offset by the viewer's top
    safe area. A count of None means the list is not on the page: the entry is then an unlinked
    muted label, never a link to nothing (ANCHOR). Each count is the list's WHOLE count (design §2); the
    heading it lands on says how many of them are open ("showing N of M").

    dashboard-redesign D1 (design §2): `Today` leads the bar. `today=True` links Today's heading; `False` (Today is
    the one sentence) is an unlinked muted label; None (no Today on the page) renders no entry."""
    out = ['<nav class="jumpbar" aria-label="Jump to the lists read most">']
    if today is not None:
        out.append(('<a class="jump" href="#%s">Today</a>' % today_ui.TODAY_ID) if today
                   else '<span class="jump off">Today</span>')
    for i, ((label, sid), n) in enumerate(zip(JUMP_TARGETS, (n_drafts, n_opps, n_apply))):
        if n is None:
            out.append('<span class="jump off">%s (0)</span>' % label)
        else:
            out.append('<a class="jump" href="#%s">%s (%d)</a>' % (sid, label, n))
        if i == 0 and n_network is not None:
            # dev #834 (M5): the Network list follows Drafts on the page and in the bar. Like "Your read" and
            # "Reconsider" it exists ONLY while the list does, so the bar stays bounded by list count and a
            # profile with nothing for the network to ask carries no `(0)` label.
            out.append('<a class="jump" href="#%s">Network (%d)</a>' % (NETWORK_SECTION, n_network))
        if i == 0 and n_targets is not None:
            out.append('<a class="jump" href="#%s">Targets (%d)</a>' % (TARGETS_SECTION, n_targets))
    if n_read is not None:
        # dev #820: "Needs your read" exists ONLY while a role waits on the candidate's own read.
        out.append('<a class="jump" href="#%s">Your read (%d)</a>' % (READ_SECTION, n_read))
    if n_flags is not None:
        # dev #761: a fourth entry exists ONLY when the conditional section does (no "(0)" label).
        out.append('<a class="jump" href="#%s">Reconsider (%d)</a>' % (RESCREEN_SECTION, n_flags))
    out.append("</nav>")
    return "".join(out)


# ── The stylesheet. Tokens define the complete light palette on bare :root, redefine
# under prefers-color-scheme:dark (guarded against an explicit light choice), and again
# under [data-theme] so the viewer's toggle wins in both directions. Hoisted out of
# main() with the 2026-08-29 collapse so the one page's CSS has one home.
_CSS_ROUTER = """
  /* ── The page frame (the router and phase sections it held went with 0.71.0 and C7; their rules were pruned by
     dashboard-redesign D2, design §10.1) ── */
  /* OWNER REQUEST 2026-10-13: the pinned jump bar. Sticky, never a script; below the viewer's
     top safe area; every in-page target lands clear of it. */
  .jumpbar { position: sticky; top: env(safe-area-inset-top, 0px); z-index: 10;
             display: flex; gap: 8px; flex-wrap: wrap; background: var(--bg);
             margin: -20px -20px 12px; padding: 8px 20px;
             border-bottom: 1px solid var(--card-border); }
  .jumpbar .jump { font-weight: 700; font-size: 13px; text-decoration: none;
                   color: var(--rail-now); background: var(--card-bg);
                   border: 1px solid var(--card-border); border-radius: 999px;
                   padding: 4px 12px; }
  .jumpbar .jump.off { color: var(--muted); font-weight: 600; }
  h2[id], section[id], [data-rec] {
    scroll-margin-top: calc(env(safe-area-inset-top, 0px) + 56px); }
  tr.ws-loud td, div.ws-loud .draft-title { color: var(--chip-action-fg); }
  .ws-more { margin-top: 6px; }
"""


CSS = """
  :root {
    color-scheme: light dark;
    --bg: #f7f7f5; --fg: #1a1a1a; --muted: #777; --muted2: #666; --th: #888;
    --card-bg: #fff; --card-border: #e4e2dd; --divider: #f0efeb;
    --focus-num-bg: #1a1a1a; --focus-num-fg: #fff;
    --chip-waiting-bg: #fef3cd; --chip-waiting-fg: #8a6d00;
    --chip-action-bg: #fde2e2; --chip-action-fg: #a12626;
    --rail-done: #9aa3ad; --rail-todo: #dcdcd8; --rail-now: #2f5fd0;
    --chip-scheduled-bg: #d9f2e3; --chip-scheduled-fg: #1c7c46;
    --chip-queued-bg: #e6e6fa; --chip-queued-fg: #4b3f8f;
    --chip-closed-bg: #ececec; --chip-closed-fg: #666;
    --pill-bg: #f0efeb; --pill-fg: #1a1a1a; --pill-done-fg: #999;
    --note-bg: #eef4fb; --note-border: #d5e4f5; --note-fg: #2c5580;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #17181a; --fg: #ececeb; --muted: #9a9a97; --muted2: #a8a8a5; --th: #8e8e8b;
      --card-bg: #201f1f; --card-border: #34322f; --divider: #2b2a28;
      --focus-num-bg: #ececeb; --focus-num-fg: #17181a;
      --chip-waiting-bg: #3d3210; --chip-waiting-fg: #f0c750;
      --chip-action-bg: #3d1e1e; --chip-action-fg: #f0908f;
      --rail-done: #5a626b; --rail-todo: #33322f; --rail-now: #7aa2f7;
      --chip-scheduled-bg: #123526; --chip-scheduled-fg: #6fdba4;
      --chip-queued-bg: #2b2650; --chip-queued-fg: #c3b8f7;
      --chip-closed-bg: #2e2d2b; --chip-closed-fg: #9a9a97;
      --pill-bg: #2b2a28; --pill-fg: #ececeb; --pill-done-fg: #767674;
      --note-bg: #172433; --note-border: #253a52; --note-fg: #8fbaea;
    }
  }
  :root[data-theme="dark"] {
    --bg: #17181a; --fg: #ececeb; --muted: #9a9a97; --muted2: #a8a8a5; --th: #8e8e8b;
    --card-bg: #201f1f; --card-border: #34322f; --divider: #2b2a28;
    --focus-num-bg: #ececeb; --focus-num-fg: #17181a;
    --chip-waiting-bg: #3d3210; --chip-waiting-fg: #f0c750;
    --chip-action-bg: #3d1e1e; --chip-action-fg: #f0908f;
    --chip-scheduled-bg: #123526; --chip-scheduled-fg: #6fdba4;
      --chip-queued-bg: #2b2650; --chip-queued-fg: #c3b8f7;
    --chip-closed-bg: #2e2d2b; --chip-closed-fg: #9a9a97;
    --pill-bg: #2b2a28; --pill-fg: #ececeb; --pill-done-fg: #767674;
    --note-bg: #172433; --note-border: #253a52; --note-fg: #8fbaea;
  }
  :root[data-theme="light"] {
    --bg: #f7f7f5; --fg: #1a1a1a; --muted: #777; --muted2: #666; --th: #888;
    --card-bg: #fff; --card-border: #e4e2dd; --divider: #f0efeb;
    --focus-num-bg: #1a1a1a; --focus-num-fg: #fff;
    --chip-waiting-bg: #fef3cd; --chip-waiting-fg: #8a6d00;
    --chip-action-bg: #fde2e2; --chip-action-fg: #a12626;
    --chip-scheduled-bg: #d9f2e3; --chip-scheduled-fg: #1c7c46;
    --chip-queued-bg: #e6e6fa; --chip-queued-fg: #4b3f8f;
    --chip-closed-bg: #ececec; --chip-closed-fg: #666;
    --pill-bg: #f0efeb; --pill-fg: #1a1a1a; --pill-done-fg: #999;
    --note-bg: #eef4fb; --note-border: #d5e4f5; --note-fg: #2c5580;
  }
  * { box-sizing: border-box; margin: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: var(--bg); color: var(--fg); padding: 20px; font-size: 14px; }
  h1 { font-size: 20px; margin-bottom: 2px; }
  .updated { color: var(--muted); font-size: 12px; margin-bottom: 18px; }
  h2 { font-size: 15px; margin: 22px 0 10px; }
  .card { background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 10px; padding: 14px 16px; margin-bottom: 10px; overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { text-align: left; color: var(--th); font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: .04em; padding: 6px 10px 6px 0; border-bottom: 1px solid var(--card-border); }
  td { padding: 8px 10px 8px 0; border-bottom: 1px solid var(--divider); vertical-align: top; }
  tr:last-child td { border-bottom: none; }
  .chip { display: inline-block; padding: 2px 9px; border-radius: 20px; font-size: 11.5px; font-weight: 600; }
  .chip.waiting { background: var(--chip-waiting-bg); color: var(--chip-waiting-fg); }
  .chip.action { background: var(--chip-action-bg); color: var(--chip-action-fg); }
  .chip.scheduled { background: var(--chip-scheduled-bg); color: var(--chip-scheduled-fg); }
  /* Query or Citation C1 (design-query-or-citation.md sec 3.5) - WAITS_ON_SURFACE: neither
     owner nor other side, a third class beside action/waiting - queued for a session with a
     keychain. */
  .chip.queued { background: var(--chip-queued-bg); color: var(--chip-queued-fg); }
  .sub { color: var(--muted2); font-size: 12px; }
  .note { background: var(--note-bg); border: 1px solid var(--note-border); border-radius: 8px; padding: 10px 14px; font-size: 12.5px; color: var(--note-fg); margin-top: 16px; }
  .draft { padding: 10px 0; border-bottom: 1px solid var(--divider); }
  .draft:last-child { border-bottom: none; }
  .draft-title { font-weight: 600; }
  .draft-meta { color: var(--muted2); font-size: 12px; margin: 2px 0 8px; }
  /* ⭐ Draft structure — added 2026-08-03. The candidate: the markdown was far easier to read than the
     page. The old renderer merged every quoted line in an entry into one blob, so a two-recipient
     campaign became an undifferentiated wall. These give each level the separation the markdown
     already had, and make the SENDABLE TEXT visually distinct from the commentary about it. */
  .draft-h3 { font-weight: 650; font-size: 14px; margin: 16px 0 4px;
              padding-top: 12px; border-top: 2px solid var(--divider); }
  .draft-h4 { font-weight: 600; font-size: 12px; margin: 12px 0 4px;
              color: var(--muted2); text-transform: none; letter-spacing: .01em; }
  .draft-note { font-size: 12px; line-height: 1.55; color: var(--muted2); margin: 6px 0; }
  .draft-rule { border: 0; border-top: 1px dashed var(--divider); margin: 14px 0; }
  /* The message itself: its own card, so it is obvious what to copy and send. */
  .draft-quote { font-size: 13.5px; line-height: 1.62; background: var(--divider);
                 border-left: 3px solid var(--accent, #6b8afd); border-radius: 6px;
                 padding: 10px 14px; margin: 4px 0 10px; }
  .draft-quote p { margin: 0 0 .7em; }
  .draft-quote p:last-child { margin-bottom: 0; }
  .draft-meta > div { margin: 1px 0; }
  code.fileref { font-size: 12px; opacity: .85; }


  /* ── Opportunity rows ──────────────────────────────────────────────────────
     One role, one place. The rail is the only new structural device, and the
     ONLY saturated colour on the row is the stage it is actually at, plus the
     existing action colour when it is waiting on the candidate. Everything else
     stays quiet so those two reads survive a fast scan. */
  .opp { border-top: 1px solid var(--card-border); padding: 12px 2px 10px; }
  .opp:first-child { border-top: 0; }
  .opp-head { display:flex; align-items:baseline; gap:14px; justify-content:space-between;
  @media (max-width: 620px) {
    /* On a phone the rail must not be stranded a full row width from its title. */
    .opp-head { gap:4px; }
    .opp-rail { width:100%; margin-top:2px; }
    .rail .seg { flex:1; max-width:48px; }
  }
              flex-wrap:wrap; }
  .opp-title { font-weight:650; font-size:15px; letter-spacing:-0.01em; }
  .opp-co { font-weight:450; opacity:.72; margin-left:8px; }
  /* The posting link is the single most-requested thing on this tab, so it is always in the
     same place and reachable without opening anything. Quiet until hovered or focused. */
  .opp-jd { margin-left:10px; font-size:11.5px; font-weight:600; letter-spacing:.02em;
            text-decoration:none; color:var(--rail-now); opacity:.85;
            border:1px solid var(--card-border); border-radius:5px; padding:1px 6px;
            white-space:nowrap; }
  .opp-jd:hover, .opp-jd:focus-visible { opacity:1; border-color:var(--rail-now); }
  .opp-jd-none { color:inherit; opacity:.4; font-weight:450; border-style:dashed; }
  .opp-meta { font-size:12.5px; opacity:.66; margin-top:2px; }
  .opp-next { font-size:13px; margin-top:7px; }
  .opp-warm { font-size:12.5px; margin-top:5px; opacity:.85; }
  .opp-warm a { text-decoration:underline; }
  .opp-arrow { opacity:.5; margin-right:4px; }
  .opp-owner { font-size:11.5px; opacity:.6; margin-left:6px; white-space:nowrap;
               display:inline-block; }
  /* ⭐ SPEND THE COLOUR IN ONE PLACE. Waiting-on-you rows sort first, so colouring the whole
     sentence turned the top of the list into a block of red and the signal stopped being a
     signal. The marker and the owner carry it; the text stays readable. */
  .opp-next-you .opp-arrow { color: var(--chip-action-fg); opacity:1; }
  .opp-next-you { font-weight:520; }
  .opp-next-you .opp-owner { color: var(--chip-action-fg); opacity:1; font-weight:600;
                             background: var(--chip-action-bg); border-radius:4px;
                             padding:1px 5px; }
  .opp-next-none { opacity:.55; font-style:italic; }
  /* dev #713: the triage lean (decide rows) and the "system is reading this" line (triaging). */
  .opp-lean { font-size:13px; margin-top:6px; }
  .opp-process { opacity:.8; font-style:italic; }
  .opp-read { color: var(--chip-action-fg); }
  .opp-copy { font-size:11.5px; opacity:.7; margin-left:4px; }
  /* dev #820: the process-state block. Owner request 2026-11-12 (C7): it now sits at the bottom, collapsed
     (`details.pstate`), and the page's top carries ONE `.palert` line only when the pipeline is not
     healthy, or when it could not be checked. */
  .palert { font-size:13px; font-weight:700; margin: 0 0 14px; padding:8px 12px; border-radius:10px;
            border:1px solid var(--card-border); background: var(--card-bg);
            color: var(--chip-action-fg); }
  .palert a { color: inherit; }
  details.pstate { margin: 26px 0 0; }
  details.pstate > summary { cursor:pointer; font-size:12.5px; opacity:.85; padding:4px 0; }
  .process { background: var(--card-bg); border: 1px solid var(--card-border); border-radius:10px;
             padding:8px 14px; margin: 4px 0 12px; }
  .process .pline { font-size:13px; padding:2px 0; white-space:pre-wrap; }
  .process .pline.pfail { font-weight:700; color: var(--chip-action-fg); }
  .process .pside { display:flex; gap:16px; flex-wrap:wrap; }
  .process .pside .pline { flex:1 1 280px; }
  .process .prun, .process .pdrill { font-size:12.5px; opacity:.85; }
  .process .pdrill li { margin: 2px 0; }
  .conservation { font-size:12px; margin-top:18px; opacity:.8; }
  /* dev #776: the employer-posting line; flagged = not confirmed live on the employer's own posting. */
  .opp-posting { font-size:13px; margin-top:6px; opacity:.8; }
  .opp-posting-flag { opacity:1; color: var(--chip-waiting-fg); background: var(--chip-waiting-bg);
                      border-radius:4px; padding:2px 6px; display:inline-block; }
  .lean-sig { font-size:11.5px; margin-left:6px; border:1px solid var(--card-border);
              border-radius:4px; padding:1px 5px; white-space:nowrap; }
  .opp-more > summary { cursor:pointer; font-size:12px; opacity:.6; margin-top:6px;
                        list-style:none; }
  .opp-more > summary::-webkit-details-marker { display:none; }
  .opp-more > summary::before { content:"▸ "; }
  .opp-more[open] > summary::before { content:"▾ "; }
  .opp-detail { margin:8px 0 2px 14px; padding-left:12px;
                border-left:2px solid var(--card-border); }
  .od-h { font-size:11px; text-transform:uppercase; letter-spacing:.07em; opacity:.55;
          margin:8px 0 3px; }
  .od-p { font-size:13px; margin:3px 0; }
  .od-warn { color: var(--chip-action-fg); }
  .od-l { font-size:13px; margin:3px 0 3px 16px; padding:0; }

  /* The rail: four segments, one per real pipeline stage. */
  .rail { display:inline-flex; gap:3px; vertical-align:middle; }
  .rail .seg { width:26px; height:5px; border-radius:2px; background:var(--rail-todo); }
  .rail .seg.done { background:var(--rail-done); }
  .rail .seg.now  { background:var(--rail-now); }
  .rail-label { font-size:11px; opacity:.6; margin-left:8px; vertical-align:middle; }

  /* dashboard-redesign D2 (design §4, §6.1): the three levels and the tick-box actions. Level 2 is one closed fold
     per list or group; a group's ONE button sits above its rows; the read-only note shows on a narrow screen only
     (design §12's ship rule). */
  details.lvl2 { margin: 8px 0 2px; }
  details.lvl2 > summary { cursor: pointer; font-size: 12.5px; color: var(--muted2); padding: 4px 0; }
  .draft-line, .role-line { padding: 5px 0; border-bottom: 1px solid var(--divider); font-size: 13px; }
  .dgroup { font-size: 13px; margin: 10px 0 2px; }
  .pick-bar { margin: 0 0 8px; }
  .pick { margin-right: 6px; vertical-align: middle; }
  .pick-go { font: inherit; font-size: 12.5px; font-weight: 600; cursor: pointer; color: var(--rail-now);
             background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 6px; padding: 4px 12px; }
  .pick-shared { margin: 14px 0; }
  .pick-text { width: 100%; font: 12px ui-monospace, Menlo, monospace; color: var(--fg);
               background: var(--bg); border: 1px solid var(--card-border); border-radius: 6px; }
  /* Builder D2b's .net-* groups, their folds and one-line rows, and the staffing question. */
  .net-group { margin: 12px 0 4px; }
  details.net-fold { margin: 6px 0 2px; }
  details.net-fold > summary { cursor: pointer; font-size: 12.5px; color: var(--muted2); padding: 4px 0; }
  .net-line { padding: 5px 0; border-bottom: 1px solid var(--divider); font-size: 13px; }
  .net-staffing { font-size: 12.5px; color: var(--muted2); margin: 4px 0; }
  .pick-ro { display: none; }
  @media (max-width: 620px) { .pick-ro { display: block; margin-top: 4px; } }
  @media (prefers-reduced-motion: reduce) { .opp-more { transition:none; } }

  /* dev #95 follow-on: the migration marker must read as a defect on the row, not a value. */
  .play-unres { color: var(--chip-action-fg); font-weight: 600; }

  /* ── A closed text fold (GitHub #94's knowledge style): a draft's or a cover letter's text since D2. ── */
  .kdoc { border-bottom: 1px solid var(--divider); padding: 8px 0; }
  .kdoc:last-child { border-bottom: none; }
  .kdoc > summary { cursor: pointer; list-style: none; }
  .kdoc > summary::-webkit-details-marker { display: none; }
  .kdoc > summary::before { content: "▸ "; opacity: .6; }
  .kdoc[open] > summary::before { content: "▾ "; }
  .kdoc-body { margin: 8px 0 4px 14px; padding-left: 12px;
               border-left: 2px solid var(--card-border); }
  /* dev #761 -- a flagged role: a stored comp removal 0.73.0 would not repeat. */
  .rsflag { border-bottom: 1px solid var(--divider); padding: 8px 0; }
  .rsflag:last-child { border-bottom: none; }
  .rsflag .rs-title { font-weight: 600; }
  .rsflag .rs-line { font-size: 13px; margin: 3px 0; }
  .rsflag .rs-act { font-size: 12.5px; margin: 3px 0; color: var(--muted2); }
""" + _CSS_ROUTER


# The page's ONE copy note (jobsearch 0.92.0, owner decision 1, review round 2 H6): what a tick and a button do, said once
# instead of under every heading (it replaces the Network heading's own sentence). `actions_ui.COPY_NOTE` is its last sentence.
PAGE_NOTE = '<div class="sub copy-note">Buttons copy text. %s</div>' % COPY_NOTE


def render(pd, parts, ledger):
    """The ONE page (cut from `main`, dashboard-redesign A). Page order: jump bar, title, `Generated`, the
    ONE alert line (nothing when healthy), Today (`dashboard.today`, dashboard-redesign D1, always the first list),
    the copy note (`PAGE_NOTE`, once, when a button is on the page; jobsearch 0.92.0, owner decision 1), the lists
    (Targets, then Roles waiting on a company decision, `dashboard.held`), the "Not on this page" note, the collapsed process
    block, the conservation line (last). `parts` holds the rendered sections (`drafts`, `network`,
    `targets`, `held`, `read`, `opps`, `apply`, `flags`, `alert`, `process`, `conservation`) and the jump bar's
    counts (`n_drafts`, `n_opps`, `n_apply`, `n_flags`, `n_read`, `n_network`, `n_targets`); `pd` the
    title, the clock, the run and the note's values; `ledger` is the render's: the page writes only Today's block to it
    (`Ledger.place_today`, dashboard-redesign E; the filter chips' block retired, D-6). Each list's count in the jump bar is its WHOLE count (design §2)."""
    _first_drafts, _first_network, _first_targets = parts["drafts"], parts["network"], parts["targets"]
    _first_read, _first_opps, _first_apply, _first_flags = parts["read"], parts["opps"], parts["apply"], parts["flags"]
    # The pinned jump bar (OWNER REQUEST 2026-10-13): one entry per list, each count the PRIMARY
    # rows that list renders (`data-rec="draft:…"` / `data-rec="opp:…"`), never a reference row;
    # a list that is not on the page is a plain, unlinked label, so the bar never links to nothing.
    # dashboard-redesign D1 (design §2, §3.6 rule 3): Today is the FIRST list, always on the page (items or its one
    # sentence), so the first-lists section always exists and nothing but the frame and one alert precedes it.
    _lists = "\n".join(x for x in (_first_drafts, _first_network, _first_targets, parts.get("held"), _first_read,
                                   _first_opps, _first_apply, _first_flags) if x)
    _today = today_ui.render(pd, {"drafts": JUMP_TARGETS[0][1], "network": NETWORK_SECTION,
                                  "targets": TARGETS_SECTION, "opps": JUMP_TARGETS[1][1], "read": READ_SECTION,
                                  "apply": JUMP_TARGETS[2][1]}, lambda anchor: (' id="%s"' % anchor) in _lists)
    ledger.place_today(TODAY_CAP, [{"kind": it.kind.name, "ref": it.ref[0]} if it.ref is not None else
                                   {"kind": it.kind.name, "count": it.count} for it in rank.plan(pd, TODAY_CAP)[0]])
    _note = PAGE_NOTE if 'class="pick-go"' in _today + _lists else ""
    _first_html = '<section class="first" id="first-lists">\n%s\n</section>' % "\n".join(
        x for x in [_today, _note, _lists] if x)
    jump_html = render_jump_bar(parts["n_drafts"] if _first_drafts else None,
                                parts["n_opps"] if _first_opps else None,
                                parts["n_apply"] if _first_apply else None,
                                parts["n_flags"] if _first_flags else None,
                                parts["n_read"] if _first_read else None,
                                parts["n_network"] if _first_network else None,
                                parts["n_targets"] if _first_targets else None,
                                today='data-today="items"' in _today)
    # The page's ONE generation time (owner request 2026-11-12, C7): the date and the minute and the
    # machine-readable `data-generated` all come from the ONE clock read `pd.now`, so the line a reader
    # sees and the instant the gate recomputes the pipeline at cannot disagree. `data-generating-run` is
    # present only when a run was named, so the gate recomputes the alert with the same run excluded.
    _lc_now = pd.now
    _gen_attrs = 'data-generated="%s"' % esc(_lc_now.replace(microsecond=0).isoformat())
    if pd.run_id:
        _gen_attrs += ' data-generating-run="%s"' % esc(pd.run_id)
    _gen_text = "%s %d, %d, %s" % (_lc_now.strftime("%B"), _lc_now.day, _lc_now.year,
                                   _lc_now.strftime("%H:%M"))
    body_inner = "\n".join(x for x in (
        jump_html,
        '<h1>%s</h1>' % html.escape(pd.title),
        # ⭐ The generated-date line stays PROMINENT: for the dashboard-only reader it is the ONLY
        # staleness signal there is (deployment.md, the S5 read leg).
        '<div class="updated" %s>Generated <strong>%s</strong> · the page of what needs a decision '
        'or a finish today · generated by scripts/generate_dashboard.py</div>' % (_gen_attrs, esc(_gen_text)),
        parts["alert"],
        _first_html,
        # The page's ONE shared text area and ONE script (dashboard-redesign D2, design §6.1), right after the lists
        # whose buttons they serve and only when a group button is on the page: the process block and the
        # conservation line stay last, and a page with no button stays script-free.
        (SHARED_FALLBACK + "\n" + PICK_SCRIPT) if 'class="pick-go"' in _first_html else "",
        '<div class="sub" style="margin-top:26px"%s>Not on this page: status and everything in '
        'flight (<code>/jobsearch:status</code>), the resume and public-profile reviews '
        '(<code>/jobsearch:review-resume</code>, <code>/jobsearch:review-linkedin</code>), the full network '
        '(<code class="fileref">data/channels.jsonl</code>, <code class="fileref">%s</code>), '
        'its numbers, the access table and your sent proposals%s '
        '(<code>views/network_strategy.md</code>, the weekly review), '
        'archives, sent and closed items, and knowledge bodies.</div>'
        % ((' data-net-sent-proposals="%d"' % pd.net_sent_proposals) if pd.net_sent_proposals else "",
           esc(pd.network_rel),
           (" (%d sent)" % pd.net_sent_proposals) if pd.net_sent_proposals else ""),
        parts["process"],
        parts["conservation"]) if x)
    return '<title>%s</title>\n<style>%s\n</style>\n%s' % (html.escape(pd.title), CSS, body_inner)
