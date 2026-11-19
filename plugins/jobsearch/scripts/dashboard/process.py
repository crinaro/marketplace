"""The process state (dashboard-redesign A, moved from generate_dashboard.py): the top alert line, the
collapsed process block and the conservation line."""
import datetime

from dashboard.markup import esc


PROCESS_DRILL_CAP = 30


def render_process_block(rep, now, error=None, titles=None, failure_texts=None, alert_line=None):
    """The process-state block, at the BOTTOM of the page and COLLAPSED (owner request 2026-11-12, design
    r3 section 2.7, criterion C7). This SUPERSEDES dev #820 / public #175 design 2.4 N14 "never collapsed"
    for the dashboard. What N14 held that still holds: the block is never absent, its lines are
    `process_report`'s own, every open run (or `no run open`) is on the page, and PIPELINE NOT CHECKED is
    loud (and is now loud at the top too, `render_pipeline_alert`).

    It is `process_report().block_lines` verbatim: the process failure with its oldest age and causes,
    waiting for intake and the legacy backlog side by side with the reservation, `UNCLASSIFIED`/`ROLES
    MISMATCH` when they are true, and `Did not look`. Then a drill list of the oldest failed roles with
    each one's cause (that list keeps its own `open`, so it shows open once the reader opens the outer
    block). The conservation line (the report's last line) is NOT here; `render_conservation_line` prints
    it after this block, last on the page. The page's ONE generation time is on the `Generated` line at the
    top, not here.

    The outer `<details>` is told apart from the inner drill `<details>` by `id="pipeline-details"`, which
    the top alert links to. Its `<summary>` reads `Pipeline state: healthy · N ready · N held · N waiting`
    (`summary_text`; the alert text in place of `healthy`), or `PIPELINE NOT CHECKED`.

    A report that could not be computed is `PIPELINE NOT CHECKED`, loudly, never an empty block.

    dashboard-redesign A: `titles` ({role key: title}), `failure_texts` ({role key: your_move.failure_text})
    and `alert_line` (lifecycle.alert_line) are the loader's values; this module imports no flat script."""
    def wrap(summary, section):
        return ('<details class="pstate" id="pipeline-details"><summary>Pipeline state: %s</summary>%s'
                '</details>' % (esc(summary), section))

    if rep is None:
        return wrap("PIPELINE NOT CHECKED",
                    '<section class="process" id="process-state">'
                    '<div class="pline pfail">PIPELINE NOT CHECKED &mdash; %s. Nothing on this page is an '
                    'empty queue.</div></section>' % esc(error or "the lifecycle could not be read"))
    body = list(rep.block_lines[:-1])           # the last line is the conservation line
    rows = []
    i = 0
    while i < len(body):
        line = body[i]
        nxt = body[i + 1] if i + 1 < len(body) else ""
        if line.startswith("Waiting for intake") and nxt.startswith("Legacy backlog"):
            rows.append('<div class="pside"><div class="pline">%s</div><div class="pline">%s</div></div>'
                        % (esc(line), esc(nxt)))
            i += 2
            continue
        cls = "pline pfail" if line.startswith("Process failure") else "pline"
        rows.append('<div class="%s">%s</div>' % (cls, esc(line)))
        i += 1
    runs = "".join('<div class="prun">%s</div>' % esc(l) for l in rep.run_lines)
    drill = ""
    if rep.failure_roles:
        ordered = sorted(rep.failure_roles, key=lambda kv: (kv[1].since or datetime.date.max, kv[0]))
        shown = ordered[:PROCESS_DRILL_CAP]
        lis = []
        for key, st in shown:
            age = ""
            if st.since is not None:
                age = ", %dd" % (now.date() - st.since).days
            lis.append('<li data-process-role="%s"><strong>%s</strong> &middot; %s%s</li>'
                       % (esc(key), esc(titles.get(key, key)), esc(failure_texts[key]), esc(age)))
        more = ""
        if len(ordered) > len(shown):
            more = ('<li>+%d more, oldest first above. Every live role is also listed in the status '
                    'pane (<code>/jobsearch:status</code>).</li>' % (len(ordered) - len(shown)))
        drill = ('<details class="pdrill" open><summary>The oldest %d of %d failed roles, with their '
                 'cause</summary><ul>%s%s</ul></details>'
                 % (len(shown), len(ordered), "".join(lis), more))
    return wrap(summary_text(rep, alert_line),
                '<section class="process" id="process-state">%s%s%s</section>'
                % ("".join(rows), runs, drill))


def summary_text(rep, alert_line=None):
    """The folded block's summary after `Pipeline state: ` (dashboard-redesign D1, design §7.4, criterion Y5):
    `healthy · N ready · N held · N waiting`, or the alert text in place of `healthy`. "Healthy" keeps its meaning (no
    alert); the three counts are `process_report`'s own (`ready`, `held_for_company`, `waiting`), so a page whose
    every new role is held for an unanswered company says so even while closed (dev #949)."""
    return "%s · %d ready · %d held · %d waiting" % (alert_line or "healthy", rep.ready, rep.held_for_company,
                                                      rep.waiting)


def render_conservation_line(rep):
    """The conservation line, LAST on the page (TOT): every role is in exactly one term. Its text is
    `process_report().conservation_line` and nothing else."""
    if rep is None:
        return ""
    return '<div class="conservation" data-conservation="1">%s</div>' % esc(rep.conservation_line)


def render_pipeline_alert(rep, error=None, alert_line=None):
    """The ONE line between the `Generated` line and the first list, and only when something is wrong
    (owner request 2026-11-12, design r3 section 2.7, criterion C7). A healthy pipeline renders NOTHING
    here. `lifecycle.alert_line(rep)` is the text, with no glyph; the `⚠ ` is added once, here, and the
    gate compares exactly the text between it and ` — details`. The link goes to the collapsed process
    block's `<summary>` (`#pipeline-details`), which stays visible while the block is closed, so the link
    never depends on a fragment opening a closed `<details>` (UNDETERMINED in the HTML spec).

    A report that could not be computed is `PIPELINE NOT CHECKED`, always loud, and is its own line
    because there is no report to read an alert from. `alert_line` is `lifecycle.alert_line(rep)`, computed by
    the loader (dashboard-redesign A)."""
    if rep is None:
        return ('<div class="palert pfail" data-pipeline-alert="not-checked">⚠ PIPELINE NOT CHECKED '
                '— %s. Nothing on this page is an empty queue. — <a href="#pipeline-details">details</a>'
                '</div>' % esc(error or "the lifecycle could not be read"))
    line = alert_line
    if line is None:
        return ""
    return ('<div class="palert" data-pipeline-alert="1">⚠ %s — <a href="#pipeline-details">details</a>'
            '</div>' % esc(line))
