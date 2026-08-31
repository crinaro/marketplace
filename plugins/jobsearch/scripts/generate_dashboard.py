#!/usr/bin/env python3
"""Generate the published state views from the operating store.

Deterministic, zero-token rendering: the model maintains data/*.jsonl (and the few
human-facing .md artifacts — drafts, cover letters, network); this script assembles the
HTML. Since dev #93 focus.md is not read at all: Your Move and This Week are
views of data/asks.jsonl, data/commitments.jsonl, opportunities.jsonl and channels.jsonl —
plus, since dev #154, the staged-message pair (drafts.md / cover_letters.md via
precondition.report) for the ready-no-ask group; the Sourcing tab (dev #148) is a view of
channels.jsonl + opportunities.jsonl sightings through channels_due.py's derivations.

⭐⭐ THE PUBLISHING MODEL — ONE ARTIFACT (2026-08-29, owner-approved 2026-08-26;
supersedes dev #233's publish set, which supersedes the 639 KB single page before it).

dev #233 split the published view into a data-dependent SET: router + state view
always, plus each phase page whose item count cleared a computed threshold. The
threshold made URL EXISTENCE a function of the DATA, and the failure was MEASURED on
a live profile, not theorised: a phase page that published once and later fell under
the line stopped republishing while its URL kept serving the old snapshot (a phase
url file with no entry in the current publish stamp), and two phases carried
generated pages with no url file at all. A stale page that looks current is worse
than an absent one. The sharding was solving a page-size problem the de-inlining had
already solved (639 KB → 224 KB measured), so the set collapses to:

  views/dashboard_artifact.html      THE one published page. The router is its top
                                     section — one bounded row per phase with two
                                     counts (needs-you headline, in-flight muted) —
                                     and each phase is an in-page anchor
                                     (#phase-<name>). Working sets are capped tables
                                     (WORKING_SET_CAP below); documents render as
                                     title + status + location, never in full —
                                     EXCEPT a body awaiting the owner's decision
                                     (a sendable message), which is the one kind of
                                     document the page exists to let them read.
  dashboard.html                     the constant TOMBSTONE STUB (unchanged; the
                                     two-copies staleness window stays closed by
                                     construction).

One Artifact call per run, always to the URL in views/dashboard_artifact_url.txt —
the oldest bookmark wins. The retired per-page URLs get a constant "moved" stub via
scripts/pending_stubs.py (recorded by migrate.m_0_34_0_dashboard_collapse, drained
by a tool-holding session — the Artifact tool is model-invoked only; no script can
publish).

The working surface for applying is NOT here and not an artifact at all — it is
views/applying.md (applying.py), regenerated in session, because working means writing
and a snapshot cannot be written to.

Usage: python3 scripts/generate_dashboard.py   (run from the profile folder root)
"""
import datetime
import html
import re
import os
from pathlib import Path

import os, sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _root import profile_root as _profile_root
import _tree
import profile as _profile
import your_move as _ym
# The one definition of the play sequence — validate_data.py owns the enum; consumers
# import it rather than restating it (a sequence typed twice disagrees with itself later).
from validate_data import PLAY_SEQUENCE as _PLAY_SEQUENCE

# ⚠️ .absolute(), NOT .resolve() — 2026-08-05. `.resolve()` FOLLOWS SYMLINKS, and the tracker
# consumes this engine as a submodule with `scripts -> engine/scripts`. Resolving made ROOT
# the ENGINE directory, which holds no data, so the dashboard regenerated with ZERO
# opportunities and silently overwrote the real one. Every sibling script uses
# os.path.abspath, which does NOT follow symlinks; this file was the lone exception.
ROOT = Path(_profile_root())
# The literal `next_action_owner` value meaning "the candidate must act" — this candidate's own
# reference token, never a hardcoded name. See profile.owner_token().
OWNER_TOKEN = _profile.owner_token()
# The profile's own currency symbol, never a hardcoded "$" — see profile.currency_symbol():
# relabelling another currency as dollars is a right number under a wrong unit.
CURRENCY = _profile.currency_symbol()


# ⭐ `next_action` IS NOT A SHORT IMPERATIVE — measured, not assumed. On the live pipeline all 35
# live roles carrying one are over 120 chars: median 419, max 1052. They are recommendation
# memos ("YOUR CALL, recommend PASS - act by ... Three independent reasons ..."). Rendering
# them in full put a wall of text in the action colour on every row and destroyed the scan the
# row layout exists for. The FIRST clause is the valuable part — it carries the verdict and the
# act-by date — so the row shows that and the rest lives under Detail.
OPP_ACTION_CLAMP = 110



# ⭐ THE DASHBOARD TITLE IS DATA — generalised 2026-08-09.
#
# It was a literal "<target titles> Search — <a real full name>", written into the <h1> and BOTH
# <title> tags. Three copies of one string, so it was already a value that could disagree with
# itself, and it named one person in a file every installation ships.
#
# ⚠️ PRESERVE, THEN TRANSFORM. The template defaults to a neutral form, and `migrate.py` writes
# the existing phrasing into the profile's own config on upgrade, so nobody's dashboard title
# silently changes under them. A migration that merely REPORTS the change would move the work
# to the owner permanently, which is not shipping.
def _dashboard_title():
    """`config.dashboard.title_template` × `user.json`'s name. Never a hard-coded name."""
    import json as _json
    name, template = "", "{name} — Job Search"
    try:
        with open(os.path.join(_profile_root(), "user.json"), encoding="utf-8") as fh:
            name = ((_json.load(fh).get("identity") or {}).get("full_name") or "").strip()
    except Exception:
        pass
    try:
        with open(os.path.join(_profile_root(), "config.json"), encoding="utf-8") as fh:
            template = ((_json.load(fh).get("dashboard") or {}).get("title_template")
                        or template)
    except Exception:
        pass
    title = template.replace("{name}", name).strip()
    # A profile with no name must not yield a title starting with a stray dash.
    return title.strip("— ").strip() or "Job Search"

def read(name: str) -> str:
    p = Path(_tree.resolve_rel(str(ROOT), name))   # canonical name; legacy root falls back
    return p.read_text(encoding="utf-8") if p.exists() else ""


def esc(s: str) -> str:
    return html.escape(s, quote=False)


def md_inline(s: str) -> str:
    """Escape, then apply **bold**, `code`, and [text](target) links.

    Link support added 2026-07-20 — focus entries routinely reference local files
    like [call_preps/call_prep_2026-08-05.md](call_preps/call_prep_2026-08-05.md)
    and those were rendering as literal markdown on the dashboard. (The original
    example, call_prep_acme.md, was promoted to kb/acme.md on 2026-08-03.)"""
    s = esc(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)

    def _link(m):
        text, target = m.group(1), m.group(2)
        if target.startswith(("http://", "https://")):
            return ('<a href="%s" target="_blank" rel="noopener noreferrer">%s</a>'
                    % (target, text))
        # Local repo file (call_prep_*.md, log.md, ...): no useful href from a
        # published artifact, so render as a filename chip rather than a dead link.
        return '<code class="fileref">%s</code>' % text
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _link, s)
    return s


# (`section_text` / `parse_table` removed 2026-08-29 with the Network tab — see the
# tombstone comment above `best_link` for the full list and the reason.)


# `is_closed_status`, `status_chip`, `first_url`, `comp_dot` and `render_table` lived here
# until 2026-08-29 and served the markdown-table Network tab alone. The one-artifact collapse
# retired that tab (D4: the network is queried, not queued — it never contributes a count),
# so they went with it rather than lingering never-called (the render_fit()/GitHub #5 trap).
# `parse_table` and `section_text` below went the same way, same date, same reason.


# `parse_your_move`, `strip_your_move` and the `## ⚡ Your Move` regex lived here until
# 2026-08-18 (dev #93). The hand-authored tail of Your Move is data now (`data/asks.jsonl`),
# so there is no prose section left to parse: `asks_from_jsonl()` below is the replacement,
# and check_action_claims.py reads the same store instead of re-parsing this file's output.


# `render_fit()` lived here until 2026-08-13 and was NEVER CALLED. It rendered exactly the
# open questions the coordinator points readers at, so its presence made the feature look
# implemented while every generated dashboard omitted them (GitHub #5, public). Its
# behaviour now lives in `_fit_detail`, which is the renderer that actually runs.


# ─────────────────────────────────────────────────────────────────────────────
# THE OPPORTUNITY ROW — one role, one place.
#
# ⭐⭐ WHY THIS REPLACED FIVE SECTIONS (2026-08-10).
#
# The Opportunities tab used to render the same roles five times: a JD-fit register, three
# application buckets (submitted / in play through a person / nothing sent), a focus-areas list
# and a sourced-pipeline table. Measured against the live pipeline: **every one of the 46 live
# roles appeared in at least two of those sections, 16 appeared in four, and not one appeared in
# exactly one.** Answering "where does this role stand" meant reading four tables and joining
# them by company name in your head.
#
# The cause was not too much content. It was that the tab was organised by ATTRIBUTE — fit,
# application state, focus, source — while the reader's unit of thought is the ROLE.
#
# ⭐ THE FIX IS STRUCTURAL, NOT COSMETIC. Bucket membership becomes a POSITION rather than a
# table you are listed in. `stage` already exists on every record, so the rail below shows where
# a role actually is; the three application buckets become a filter over one list instead of
# three copies of it. A status CHIP would not have done this — a chip shows state but not
# progression, and it would have left all four tables standing.
#
# Everything the old sections showed is still here. Each fact now appears once.
# ─────────────────────────────────────────────────────────────────────────────

STAGES = ("sourced", "contacted", "screening", "interviewing")
_STAGE_LABEL = {"sourced": "Sourced", "contacted": "Contacted",
                "screening": "Screening", "interviewing": "Interviewing"}



def best_link(o):
    """The role's posting URL — `jd_url`, else the first sighting that carried one.

    ⭐ ONE RULE, TWO SURFACES. Your Move and the Opportunities row both need this, and a second
    copy would drift. On the live pipeline the fallback is not decorative: it is the difference
    between 33 and 34 of 38 live roles having a reachable posting.
    """
    if o.get("jd_url"):
        return o["jd_url"]
    for s in (o.get("sightings") or []):
        if (s or {}).get("source_url"):
            return s["source_url"]
    return None


def opp_bucket(o):
    """The one bucket this role belongs to — the same three the old tables split across.

    Order matters and is the old precedence: an application beats a person, a person beats
    nothing. Kept identical so the filter counts match what the buckets used to report.
    """
    if o.get("applications"):
        return "applied"
    if o.get("outreach") or o.get("contacts"):
        return "person"
    return "nothing"


def stage_rail(o):
    """Four segments, one per real pipeline stage, with the CURRENT stage the only saturated one.

    ⚠️ An unrecognised stage renders every segment as pending rather than guessing a position.
    Inventing a position would put a role further along than it is, which is the one error that
    makes this rail worse than the tables it replaced.
    """
    cur = str(o.get("stage") or "").lower()
    idx = STAGES.index(cur) if cur in STAGES else -1
    segs = []
    for i, st in enumerate(STAGES):
        cls = "seg done" if (idx >= 0 and i < idx) else ("seg now" if i == idx else "seg todo")
        segs.append(f'<span class="{cls}" title="{esc(_STAGE_LABEL[st])}"></span>')
    label = _STAGE_LABEL.get(cur, "stage not set")
    return (f'<span class="rail" role="img" aria-label="Stage: {esc(label)}">'
            + "".join(segs) + f'</span><span class="rail-label">{esc(label)}</span>')


def _fit_detail(o):
    f = o.get("fit") or {}
    reqs = f.get("requirements") or []
    if not reqs and not f.get("summary"):
        return ""
    aligned = [r for r in reqs if r.get("verdict") == "aligned"]
    other = [r for r in reqs if r.get("verdict") != "aligned"]
    out = ['<div class="od-h">JD fit</div>']
    if f.get("summary"):
        out.append(f'<div class="od-p">{md_inline(str(f["summary"]))}</div>')
    if aligned:
        out.append('<div class="od-p"><strong>Evidence exists for:</strong> '
                   + esc(", ".join(str(r.get("requirement", "")) for r in aligned)) + "</div>")
    if other:
        # ⭐ The DO-NOT-CLAIM half is the half that keeps a letter honest, so it is never
        # collapsed away behind the aligned list.
        out.append('<div class="od-p od-warn"><strong>Do not claim:</strong> '
                   + esc(", ".join(str(r.get("requirement", "")) for r in other)) + "</div>")

    # ⭐⭐ THE OPEN QUESTIONS RENDER HERE — GitHub #5 (public).
    #
    # The coordinator truncates its own list and sends the reader to "the dashboard's JD fit
    # section" for the rest. That section existed and never held them: the renderer that did
    # was written and never called, so the feature looked present while every generated
    # dashboard omitted it. Grepping a real dashboard for the question text returned nothing,
    # for any role.
    #
    # A report that truncates itself must point at a surface that actually holds the
    # remainder, so they go where the pointer already says they are.
    #
    # ⚠️ DATED FIRST, AND SHOW THE DATE. `act_by` exists because the fact that made a question
    # urgent used to live as prose inside the question text, where nothing could sort it.
    # Rendering them undifferentiated here would rebuild exactly that.
    qs = [r for r in reqs
          if r.get("question_for_candidate") and r.get("question_status") == "open"]
    if qs:
        import datetime as _dt
        today = _dt.date.today().isoformat()
        qs = sorted(qs, key=lambda r: (r.get("act_by") or "9999-99-99"))
        items = []
        for r in qs:
            ab = r.get("act_by")
            text = esc(str(r["question_for_candidate"]))
            if not ab:
                items.append("<li>%s</li>" % text)
            else:
                items.append('<li><strong>%s %s</strong> &middot; %s</li>'
                             % ("&#8252;&#65039; DUE" if str(ab) <= today else "&#9203; by",
                                esc(str(ab)), text))
        out.append('<div class="od-p"><strong>&#10067; Needs you:</strong></div>'
                   '<ul class="od-p" style="margin:0 0 6px 18px">%s</ul>' % "".join(items))
    return "".join(out)


def _touch_detail(o):
    out = []
    apps = o.get("applications") or []
    if apps:
        rows = []
        for a in apps:
            when = esc(str(a.get("applied_on") or a.get("date") or "date unrecorded"))
            how = esc(str(a.get("method") or "application"))
            cl = a.get("cover_letter")
            cl = "cover letter recorded" if cl else "cover letter unrecorded"
            rows.append(f"<li>{when} — {how} · {cl}</li>")
        out.append('<div class="od-h">Applications</div><ul class="od-l">'
                   + "".join(rows) + "</ul>")
    tou = o.get("outreach") or []
    if tou:
        rows = []
        for t in tou:
            when = esc(str(t.get("sent_on") or t.get("date") or "date unrecorded"))
            who = esc(str(t.get("to") or t.get("contact_id") or "recipient unrecorded"))
            med = esc(str(t.get("medium") or ""))
            res = t.get("outcome") or "no reply yet"
            rows.append(f"<li>{when} — {who}{' · ' + med if med else ''} · {esc(str(res))}</li>")
        out.append('<div class="od-h">Outreach</div><ul class="od-l">'
                   + "".join(rows) + "</ul>")
    return "".join(out)


# The fixed shape of render_opportunity_list's counts dict — see dev #80 in that function's
# docstring for why this has to be a single shared constant rather than two literals.
_EMPTY_OPP_COUNTS = {"all": 0, "you": 0, "applied": 0, "person": 0, "nothing": 0}


def render_opportunity_list(opps, companies, cap=None):
    """One row per LIVE role, waiting-on-you first, CAPPED (the collapse's volume rule:
    rows are ordered so the cap trims the quiet tail — a role waiting on the candidate can
    never be the row that gets cut). The counts are always over the FULL set. Closed roles
    are not here — they are not opportunities.

    ⭐ dev #80 — the counts dict has a FIXED shape (all/you/applied/person/nothing) because
    main() indexes every key unconditionally to build the filter bar. The empty-live case used
    to return `{}` for it, which crashed main() with a KeyError — and the profile most likely to
    have zero live opportunities is a brand-new one, so the dashboard's first-ever render was the
    crash. `_EMPTY_OPP_COUNTS` is the one place that shape is written down, shared by both the
    empty-case return and the populated-case starting value, so they cannot drift apart.
    """
    live = [o for o in opps if o.get("status") not in _CLOSED_STATUSES]
    if not live:
        return '<div class="sub">No live opportunities.</div>', dict(_EMPTY_OPP_COUNTS)
    order = {"active-pursuit": 0, "needs-resolution": 1, "in-motion": 2, "backlog": 3}

    def key(o):
        # Anything waiting on the candidate sorts first: the tab's job is to be actionable.
        waiting = 0 if str(o.get("next_action_owner") or "").lower() not in ("me", "") else 1
        return (waiting, order.get(o.get("status"), 9),
                -(STAGES.index(o["stage"]) if o.get("stage") in STAGES else -1))

    counts = dict(_EMPTY_OPP_COUNTS)
    rows = []
    for o in sorted(live, key=key):
        comp = companies.get(o.get("company_id"), {})
        bucket = opp_bucket(o)
        owner = str(o.get("next_action_owner") or "").lower()
        waits = owner not in ("me", "")
        counts["all"] += 1
        counts[bucket] += 1
        if waits:
            counts["you"] += 1

        # The play position, on the row itself — the field's first dashboard reader (dev #95
        # follow-on: the schema gained play_stage and no surface the owner meets displayed it).
        _play = str(o.get("play_stage") or "")
        if _play == "unresolved":
            play_html = ('<span class="play-unres">play: unresolved — set the real '
                         'stage</span>')
        elif _play:
            play_html = esc("play: " + _play)
        else:
            play_html = ""
        meta = " · ".join(x for x in (
            _fmt_loc(o.get("location")), _fmt_comp(o.get("comp")),
            esc(str(o.get("channel_id") or "").replace("firm:", "via ")) or "",
            play_html) if x)
        na = o.get("next_action")
        action_full = ""
        if na:
            due = o.get("next_action_date")
            who = "you" if waits else "the run"
            text = str(na).strip()
            # Flatten markdown before clamping so the teaser never shows raw syntax.
            flat = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
            flat = re.sub(r"[*`]+", "", flat)
            if len(flat) > OPP_ACTION_CLAMP:
                teaser = flat[:OPP_ACTION_CLAMP].rsplit(" ", 1)[0].rstrip(" ,;:—-") + "…"
                action_full = text
            else:
                teaser = flat
            nxt = (f'<div class="opp-next{" opp-next-you" if waits else ""}">'
                   f'<span class="opp-arrow">→</span> {esc(teaser)} '
                   f'<span class="opp-owner">{who}{" · due " + esc(str(due)) if due else ""}</span></div>')
        else:
            # ⚠️ Named, not omitted. A role with no next action is a decision nobody has made,
            # and an empty space reads as "handled".
            nxt = '<div class="opp-next opp-next-none">No next action set</div>'

        # ⭐⭐ THE POSTING LINK IS A ROW-LEVEL AFFORDANCE, NEVER BEHIND `Detail`.
        # The reported frustration was literally "I just wanted the JD link" — and the first
        # version of this layout still cost a click to reach it. Collapsing the duplication is
        # not the same as making the most-wanted thing reachable. It sits next to the title,
        # always in the same place, so it can be hit without reading the row.
        link = best_link(o)
        if link:
            jd = (f'<a class="opp-jd" href="{esc(link)}" target="_blank" rel="noopener" '
                  f'title="Open the posting">JD ↗</a>')
        else:
            # Named, not blank — "no link recorded" is a fact about the role, and an empty
            # space here reads as "look harder".
            jd = '<span class="opp-jd opp-jd-none" title="No posting URL recorded">no link</span>'

        detail = ""
        if action_full:
            # The full recommendation, first — it is the reason the reader opened the row.
            detail += ('<div class="od-h">The call in full</div>'
                       f'<div class="od-p">{md_inline(action_full)}</div>')
        detail += _fit_detail(o) + _touch_detail(o)
        body = (f'<details class="opp-more"><summary>Detail</summary>'
                f'<div class="opp-detail">{detail}</div></details>') if detail else ""

        rows.append(
            f'<div class="opp" data-bucket="{bucket}" data-you="{"1" if waits else "0"}">'
            f'  <div class="opp-head">'
            f'    <div class="opp-title">{esc(str(o.get("title") or "Untitled role"))}'
            f'      <span class="opp-co">{esc(comp.get("name", o.get("company_id", "")))}</span>'
            f'      {jd}</div>'
            f'    <div class="opp-rail">{stage_rail(o)}</div>'
            f'  </div>'
            f'  <div class="opp-meta">{meta}</div>'
            f'  {nxt}{body}'
            f'</div>')
    cap = cap if cap is not None else WORKING_SET_CAP
    shown, rest = rows[:cap], rows[cap:]
    more = ""
    if rest:
        more = ('<div class="sub ws-more">+%d more live roles — the counts above cover '
                'every one; the full list lives in <code class="fileref">'
                'data/opportunities.jsonl</code> (pipeline_index.py renders it in '
                'session).</div>' % len(rest))
    return "".join(shown) + more, counts

def render_your_move(items, links=None, cap=None, more_at=None) -> str:
    """The numbered ask list (callout groups, Decide, Ready-to-send). Since the one-artifact
    collapse it takes the same cap every working set takes: items are already ordered
    soonest-first before they arrive here, so the cap trims only the tail, and the remainder is
    counted and located rather than silently absent."""
    if not items:
        return '<div class="sub">Nothing is waiting on you right now.</div>'
    cap = cap if cap is not None else WORKING_SET_CAP
    shown, rest = items[:cap], items[cap:]
    more = ""
    if rest:
        more = ('<div class="sub ws-more">+%d more — every one is still counted in the '
                'heading; the full set lives in %s.</div>'
                % (len(rest), md_inline(more_at or "the operating store (`data/`)")))
    items = shown
    links = links or {}
    parts = []
    for n, item in enumerate(items, 1):
        t, w = item[0], item[1]
        opp_id = item[2] if len(item) > 2 else None
        link = links.get(opp_id) if opp_id else None
        jd_html = (f' <a class="ym-jd" href="{link}" target="_blank" rel="noopener">JD ↗</a>'
                   if link else '')
        parts.append(
            f'<div class="ym-item"><div class="ym-num">{n}</div><div>'
            f'<div class="ym-title">{md_inline(t)}{jd_html}</div>'
            f'<div class="ym-ask">{md_inline(w)}</div></div></div>')
    return "".join(parts) + more


# `parse_focus` is gone with focus.md (dev #93), and `render_focus` followed on 2026-08-29
# with the one-artifact collapse: it rendered ('h', heading) / ('i', title, why) entry
# tuples, which the JSONL-backed builders now feed straight into working-set TABLES
# (render_ws below) — the owner rejected sentence-shaped rows twice, and a numbered prose
# list was that shape one level down. Removed rather than left never-called (the
# render_fit()/GitHub #5 trap).


def parse_cover_letters(md: str):
    """Entries from cover_letters.md, minus the trailing '⚠️ Questions...' section.

    Same '## ' shape as drafts.md, so parse_drafts does the splitting; this only
    filters out the housekeeping section at the bottom, which is a note to me
    rather than a letter the candidate would review.
    """
    entries = [(ttl, blocks) for ttl, blocks in parse_drafts(md)
               if "questions that would sharpen" not in ttl.lower()]
    # A letter whose body isn't blockquoted parses to an EMPTY body and publishes
    # silently as a heading with no text -- which is exactly how the PCG letter
    # reached the dashboard invisible on 2026-07-27 (the candidate caught it, not the run).
    # The body MUST be '> '-prefixed; warn loudly rather than shipping a blank.
    for ttl, blocks in entries:
        if not any(k == "quote" and any(p.strip() for p in v) for k, v in blocks):
            print("  !! WARNING: cover letter '%s' has NO quoted body -- "
                  "the letter text must be blockquoted with '> ' or it renders EMPTY."
                  % ttl[:70])
    return entries


def parse_drafts(md: str):
    """Split drafts.md on '## ' entries -> list of (title, blocks).

    ⭐⭐ REWRITTEN 2026-08-03. The candidate: *"can you fix the formatting for the html output for the
    drafts in the Your Move section? when i look at the drafts.md, they are so much easier to
    read versus the html page."*

    **What was wrong, and it was worse than cosmetic.** The old parser kept only two things: the
    lines starting with `**`, and EVERY `>` line in the entry CONCATENATED INTO ONE BLOB. For a
    single-message draft that was survivable. For a multi-recipient campaign it destroyed the
    document: the <an employer> entry has two recipients, each with a connection note AND a follow-up
    message, and all four bodies merged into one undifferentiated wall with no way to tell which
    text goes to whom or which piece is which. `### Recipient 1 of 2` and `#### A. / B.` headings
    were dropped outright, so the only signposts vanished too.

    **And free prose was silently discarded** — drafts.md's own header warns about this
    ("Free-form prose paragraphs without a `**Label:**` prefix are silently dropped... verified
    this the hard way 2026-07-10"). A parser that eats content and warns you in prose is a trap.
    This one renders everything, so the trap is gone rather than documented.

    Returns ordered, TYPED blocks so the HTML can mirror the markdown:
      ('meta', [lines])  '**Label:** value' runs
      ('h3', text)       '### ' — a recipient
      ('h4', text)       '#### ' — a piece (A. the note, B. the message)
      ('quote', [paras]) a '> ' run — THE TEXT THE CANDIDATE ACTUALLY SENDS
      ('note', [lines])  anything else, previously dropped
      ('rule', None)     '---'
    """
    entries = []
    for m in re.finditer(r"^##\s+(.+?)$(.*?)(?=^##\s|\Z)", md, re.M | re.S):
        title, body = m.group(1).strip(), m.group(2)
        blocks, buf, kind = [], [], None

        def flush():
            if not buf:
                return
            if kind == "quote":
                # A bare '>' is a paragraph break inside the message, not a blank line to drop.
                paras, cur = [], []
                for ln in buf:
                    if ln.strip():
                        cur.append(ln)
                    elif cur:
                        paras.append("\n".join(cur)); cur = []
                if cur:
                    paras.append("\n".join(cur))
                blocks.append(("quote", paras))
            else:
                blocks.append((kind, list(buf)))
            buf.clear()

        for raw in body.splitlines():
            s = raw.strip()
            if s.startswith(">"):
                if kind != "quote":
                    flush(); kind = "quote"
                buf.append(raw.lstrip()[1:].lstrip() if raw.lstrip().startswith(">") else raw)
            elif s.startswith("####"):
                flush(); kind = None; blocks.append(("h4", s.lstrip("#").strip()))
            elif s.startswith("###"):
                flush(); kind = None; blocks.append(("h3", s.lstrip("#").strip()))
            elif s in ("---", "***", "___"):
                flush(); kind = None; blocks.append(("rule", None))
            elif s.startswith("**"):
                if kind != "meta":
                    flush(); kind = "meta"
                buf.append(s)
            elif not s:
                flush(); kind = None
            else:
                if kind != "note":
                    flush(); kind = "note"
                buf.append(s)
        flush()
        entries.append((title, blocks))

    # ⭐ AN UNTITLED ENTRY IS AN INVISIBLE ENTRY — added 2026-08-05, and it had already shipped.
    # The candidate: *"I still don't see the message for <a contact>."* The draft was in drafts.md, was
    # correctly `> `-blockquoted, and its text WAS in the published HTML — so every existing guard
    # passed. But it had been written with a `**Label:**` line where every other entry uses a
    # `## ` heading, and entries are split on `## ` alone. So it never began a card: it was
    # absorbed into the TAIL of the previous, unrelated draft (MedImpact/Marjan), under that
    # draft's title. Nothing was missing; it was filed under someone else's name.
    #
    # Why the existing checks could not catch it: the no-quoted-body guard asks whether the text
    # EXISTS, and it did. This asks the different question — whether the text is FINDABLE. A
    # `---` rule followed by a `**Label:**` line is precisely the shape of an entry that forgot
    # its heading, and it does not occur in a well-formed one.
    for m in re.finditer(r"^##\s+(.+?)$(.*?)(?=^##\s|\Z)", md, re.M | re.S):
        _t, _b = m.group(1).strip(), m.group(2)
        if re.search(r"^---\s*$\s*^\*\*Label:\*\*", _b, re.M):
            print("  !! WARNING: draft '%s' contains a '---' followed by a '**Label:**' line. "
                  "That is an entry that forgot its '## ' heading, so it renders INSIDE this "
                  "one instead of as its own card -- findable only by whoever already knew it "
                  "was there. Give it a '## ' title." % _t[:70])

    # Same silent-empty guard as before: a draft body must be '> '-quoted or it renders BLANK,
    # which is indistinguishable from "not drafted yet". That shipped once and only the candidate noticed.
    for ttl, blocks in entries:
        if "questions that would sharpen" in ttl.lower():
            continue
        if not any(k == "quote" and any(p.strip() for p in v) for k, v in blocks):
            print("  !! WARNING: draft '%s' has NO quoted body -- "
                  "the message text must be blockquoted with '> ' or it renders EMPTY."
                  % ttl[:70])
    return entries


def render_draft_entries(entries, empty_msg):
    """Render typed blocks so the page reads like the markdown does."""
    if not entries:
        return '<div class="sub">%s</div>' % empty_msg
    out = []
    for title, blocks in entries:
        parts = ['<div class="draft"><div class="draft-title">%s</div>' % md_inline(title)]
        for kind, val in blocks:
            if kind == "meta":
                parts.append('<div class="draft-meta">%s</div>'
                             % "".join("<div>%s</div>" % md_inline(l) for l in val))
            elif kind == "h3":
                parts.append('<div class="draft-h3">%s</div>' % md_inline(val))
            elif kind == "h4":
                parts.append('<div class="draft-h4">%s</div>' % md_inline(val))
            elif kind == "rule":
                parts.append('<hr class="draft-rule">')
            elif kind == "note":
                parts.append('<div class="draft-note">%s</div>'
                             % "<br>".join(md_inline(l) for l in val))
            elif kind == "quote":
                # THE SENDABLE TEXT. Its own card, so it is obvious what to copy.
                paras = "".join(
                    "<p>%s</p>" % "<br>".join(md_inline(x) for x in p.split("\n"))
                    for p in val if p.strip())
                parts.append('<div class="draft-quote">%s</div>' % paras)
        parts.append("</div>")
        out.append("".join(parts))
    return "".join(out)


# ─────────────────────────────────────────────────────────────────────────────
# KNOWLEDGE ARTIFACTS — GitHub #94 (public #20).
#
# Drafts and cover letters render in full, but the two DURABLE knowledge artifact types —
# kb/<company_id>.md and call_preps/call_prep_<date>.md — rendered only as code-formatted
# filename strings (md_inline's fileref chip), unreadable from the published page. The
# reported concrete failure: a call prep for an interview the next morning, readable only
# from a checkout. These render the files' CONTENT, collapsed behind their titles.
#
# ⚠️ Same standing trap as the draft parsers: a file that renders NOTHING must be loud.
# An empty body on the page is indistinguishable from "not written yet" — that shipped once
# for a cover letter and only the owner noticed. Empty or unreadable files print the same
# `!! WARNING` the draft parsers do, AND leave a visible marker on the page itself.
# ─────────────────────────────────────────────────────────────────────────────

def knowledge_docs():
    """([(title, relpath, body)] for call_preps newest-first, same for kb/ alphabetical).

    Skips knowledge.py's KB_EXEMPT names (a README is documentation about the store, not a
    knowledge artifact). Title is the file's first '# ' heading, else the filename stem —
    the stem is the company id / date key, which is exactly what a reader scans for."""
    import knowledge as _kn

    def _docs(key, newest_first):
        d = Path(_tree.path(str(ROOT), key))
        sub = os.path.relpath(str(d), str(ROOT))
        if not d.is_dir():
            return []
        out = []
        names = sorted((n for n in os.listdir(d)
                        if n.endswith(".md") and n.lower() not in _kn.KB_EXEMPT),
                       reverse=newest_first)
        for name in names:
            rel = "%s/%s" % (sub, name)
            try:
                body = (d / name).read_text(encoding="utf-8")
            except OSError as e:
                print("  !! WARNING: knowledge file '%s' is UNREADABLE (%s) -- it renders as "
                      "a heading with NO content." % (rel, e))
                body = ""
            if not body.strip():
                print("  !! WARNING: knowledge file '%s' has NO content -- it renders as a "
                      "heading with nothing under it, indistinguishable from 'not written "
                      "yet'." % rel)
            m = re.search(r"^#\s+(.+?)\s*$", body, re.M)
            title = m.group(1) if m else name[:-3]
            out.append((title, rel, body))
        return out
    return _docs("call_preps", True), _docs("kb", False)   # _tree keys, not literal dirs


def render_md_doc(md: str) -> str:
    """A small block-level markdown renderer for knowledge files: headings, bullets,
    blockquotes, rules, paragraphs — inline formatting via md_inline (which escapes).
    Deliberately modest: kb files are working notes, and a faithful readable rendering
    beats a full markdown engine this repo would then have to carry dependency-free."""
    out, para, items = [], [], []

    def flush_para():
        if para:
            out.append('<p class="kd-p">%s</p>' % "<br>".join(md_inline(l) for l in para))
            del para[:]

    def flush_list():
        if items:
            out.append('<ul class="kd-l">%s</ul>'
                       % "".join("<li>%s</li>" % md_inline(i) for i in items))
            del items[:]

    for raw in md.splitlines():
        s = raw.strip()
        hm = re.match(r"^(#{1,4})\s+(.*)$", s)
        if hm:
            flush_para(); flush_list()
            out.append('<div class="kd-h kd-h%d">%s</div>'
                       % (len(hm.group(1)), md_inline(hm.group(2))))
        elif s.startswith(("- ", "* ")):
            flush_para()
            items.append(s[2:])
        elif s.startswith(">"):
            flush_para(); flush_list()
            out.append('<div class="kd-q">%s</div>' % md_inline(s.lstrip(">").strip()))
        elif s in ("---", "***", "___"):
            flush_para(); flush_list()
            out.append('<hr class="draft-rule">')
        elif not s:
            flush_para(); flush_list()
        else:
            flush_list()
            para.append(s)
    flush_para(); flush_list()
    return "".join(out)


def render_knowledge_docs(docs, empty_msg):
    """Each file collapsed behind its title (the reporter's own suggested shape). The body
    is the rendered CONTENT — never just the filename. Since dev #233 this renders on the
    PHASE pages, never on the state view — render_knowledge_index is the state view's."""
    if not docs:
        return '<div class="sub">%s</div>' % empty_msg
    out = []
    for title, rel, body in docs:
        inner = render_md_doc(body) or ('<div class="sub">⚠️ This file is empty — nothing '
                                        'has been written here yet.</div>')
        out.append('<details class="kdoc"><summary><strong>%s</strong> '
                   '<code class="fileref">%s</code></summary>'
                   '<div class="kdoc-body">%s</div></details>'
                   % (md_inline(title), esc(rel), inner))
    return "".join(out)


# ─────────────────────────────────────────────────────────────────────────────
# INDEX RENDERERS — dev #233. The state view lists documents as title + status +
# location, NEVER in full. The full text has exactly one published home (the phase
# page named on each index row) and one authored home (the file in the tree).
# ─────────────────────────────────────────────────────────────────────────────

def _draft_meta_summary(blocks):
    """The '**Label:** value' lines of the entry's FIRST meta block, flattened to one
    ' · '-joined line — enough to recognise the message without carrying its body."""
    for kind, val in blocks:
        if kind == "meta":
            parts = [re.sub(r"\*\*(.+?):\*\*\s*", r"\1: ", l).strip() for l in val]
            return " · ".join(p for p in parts if p)[:220]
    return ""


def render_draft_index(entries, states, filename, empty_msg, where, cap=None,
                       loud=False):
    """One row per staged entry: title, precondition state chip, meta summary, and WHERE
    the full text lives. Never the body (dev #233): a state view that inlines every held
    or sent document stops being a state view. `where` names the reading surface — since
    the one-artifact collapse the phase pages are gone, so it is either the full-body
    block on this same page (sendable entries) or the authored file itself (held ones).
    Capped like every working set (the collapse's volume rule)."""
    if not entries:
        return '<div class="sub">%s</div>' % empty_msg
    cap = cap if cap is not None else WORKING_SET_CAP
    shown, rest = entries[:cap], entries[cap:]
    chip = {"sendable": ("scheduled", "ready"), "blocked": ("waiting", "held"),
            "unresolved": ("action", "unresolved"), "unreadable": ("action", "unreadable")}
    out = []
    for title, blocks in shown:
        st = (states.get((filename, title)) or {}).get("state") or "sendable"
        cls, label = chip.get(st, ("waiting", st))
        meta = _draft_meta_summary(blocks)
        out.append(
            '<div class="draft%s"><div class="draft-title">%s '
            '<span class="chip %s">%s</span></div>'
            '%s'
            '<div class="sub">full text: <code class="fileref">%s › %s</code> · %s</div></div>'
            % (" ws-loud" if loud else "", md_inline(title), cls, label,
               ('<div class="draft-meta">%s</div>' % esc(meta)) if meta else "",
               esc(filename), esc(title[:60]), esc(where)))
    if rest:
        out.append('<div class="sub ws-more">+%d more — still counted in the heading; the '
                   'full set lives in <code class="fileref">%s</code>.</div>'
                   % (len(rest), esc(filename)))
    return "".join(out)


def render_draft_bodies(entries, empty_msg, filename, cap=None):
    """⭐ The approval reading surface, ON the one page. The collapse keeps exactly one
    kind of document body published: a SENDABLE message awaiting the owner's approval —
    the body IS the decision being asked for, and the standing rule is that the candidate
    reads the full text off the published page, never the transcript. Everything else
    (held, sent, moot, knowledge not awaiting a decision) stays an index row or a count.
    Bodies are collapsed behind their titles and capped like every working set; the
    remainder is counted and named, and every capped-out body is still fully readable in
    the authored file."""
    if not entries:
        return '<div class="sub">%s</div>' % empty_msg
    cap = cap if cap is not None else WORKING_SET_CAP
    shown, rest = entries[:cap], entries[cap:]
    out = []
    for title, blocks in shown:
        inner = render_draft_entries([(title, blocks)], "")
        out.append('<details class="kdoc"><summary><strong>%s</strong></summary>'
                   '<div class="kdoc-body">%s</div></details>'
                   % (md_inline(title), inner))
    if rest:
        out.append('<div class="sub ws-more">+%d more pending — read them in '
                   '<code class="fileref">%s</code>.</div>' % (len(rest), esc(filename)))
    return "".join(out)


def render_knowledge_index(docs, empty_msg, where, cap=None):
    """One row per knowledge file: title, location, size — the content itself is NOT on
    the published page (the collapse: a knowledge body is not awaiting a decision), except
    call preps, whose full text renders in the conversations section (public #20's need —
    a prep readable the night before, anywhere — outranks the general rule and is bounded
    by upcoming-call volume). Capped: at hundreds of company files the index itself would
    be the 639 KB defect wearing rows."""
    if not docs:
        return '<div class="sub">%s</div>' % empty_msg
    cap = cap if cap is not None else WORKING_SET_CAP
    shown, rest = docs[:cap], docs[cap:]
    out = []
    for title, rel, body in shown:
        words = len(body.split())
        flag = "" if body.strip() else (' <span class="chip action">empty — nothing '
                                        'written yet</span>')
        out.append('<div class="draft"><div class="draft-title">%s%s</div>'
                   '<div class="sub"><code class="fileref">%s</code> · %d words · %s'
                   '</div></div>'
                   % (md_inline(title), flag, esc(rel), words, esc(where)))
    if rest:
        out.append('<div class="sub ws-more">+%d more files — the count above is complete; '
                   'browse the directory in the file tree.</div>' % len(rest))
    return "".join(out)


# ─────────────────────────────────────────────────────────────────────────────
# THE ROUTER — D2, merged into the ONE page by the 2026-08-29 collapse. One BOUNDED
# row per phase at the top of the page: TWO counts and one clause. Bounded by phase
# count, never by item count — this is what opens on a phone. Every number comes from
# the module that already owns it (your_move, precondition, trigger, applying,
# channels_due, the stores); nothing is re-derived here, and every count is a query,
# never model output.
#
# ⭐ TWO COUNTS PER ROW — the requirement that matters most. The headline is NEEDS-YOU:
# approvals owed, decisions owed, replies owed — the number that means "open a
# session". IN-FLIGHT (waiting on a trigger, blocked-until, scheduled) is secondary
# and muted. A single merged count buried the seven items that needed the owner under
# the thirty-four that did not, which is how the one number that must be read stopped
# meaning anything.
# ─────────────────────────────────────────────────────────────────────────────

PHASES = ("configure", "presence", "pipeline", "applying", "conversations", "outreach")
_PHASE_ICON = {"configure": "⚙️", "presence": "🪞", "pipeline": "🎯",
               "applying": "📝", "conversations": "📅", "outreach": "✉️"}

# ⭐ THE WORKING-SET CAP — a named RENDER bound, never a publish selector. ADR-019
# rejected constants tuned to the author's data ("a constant wearing a formula: right for
# the profile it was tuned on, silently wrong for any other"). This one is legitimate as a
# constant because it is volume-independent by construction: every working set is sorted
# soonest-due-first BEFORE the cap, so at any volume the cap trims only the latest-due
# tail — it can never hide the next action — and the remainder is still counted and
# located ("+K more, in <file>"), never silently absent. The value is chosen from the
# READING surface, not from any profile's distribution: ~20 table rows is a few phone
# screens, and the page as a whole stays bounded (phases × sets × cap) even at hundreds of
# items in one phase, which is the future this design is built for.
WORKING_SET_CAP = 20

_CLAUSE_CLAMP = 110  # same bound OPP_ACTION_CLAMP uses, for the same measured reason


def _clause(text):
    """ONE clause of prose, maximum — the single next action. `next_action` fields are
    measured to be memos (median 419 chars); a router row carries the verdict and the
    stores carry the memo. Sentence-shaped rows are the defect the owner rejected twice."""
    flat = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", str(text or ""))
    flat = re.sub(r"[*`]+", "", flat).strip()
    for sep in (". ", "; ", " — "):
        i = flat.find(sep)
        if 0 < i < _CLAUSE_CLAMP:
            return flat[:i].rstrip(" ,;:")
    if len(flat) > _CLAUSE_CLAMP:
        return flat[:_CLAUSE_CLAMP].rsplit(" ", 1)[0].rstrip(" ,;:—-") + "…"
    return flat


def _age_days(iso, today=None):
    """'Nd' for a past ISO date, '' for anything unreadable — an unknown age must render
    as absent, never invented."""
    try:
        d = datetime.date(*map(int, str(iso).split("-")))
        n = ((today or datetime.date.today()) - d).days
        return "%dd" % n if n >= 0 else ""
    except Exception:
        return ""


def ws_row(item_html, who="", age="", due="", loud=False):
    """One working-set row. `item_html` is pre-rendered (it may carry a JD link); the
    other cells are plain text, escaped at render time."""
    return {"item": item_html, "who": who, "age": age, "due": due, "loud": loud}


def render_ws(rows, more_at, empty_msg, cap=None):
    """One working set → a TABLE (item · who · age · due), soonest-due first (no due
    sorts last), capped at WORKING_SET_CAP with a '+K more' line naming where the
    remainder lives. Structured rows, never sentences."""
    if not rows:
        return '<div class="sub">%s</div>' % empty_msg
    cap = cap if cap is not None else WORKING_SET_CAP
    rows = sorted(rows, key=lambda r: (str(r.get("due") or "~"), ))
    shown, rest = rows[:cap], rows[cap:]
    out = ["<table><tr><th>Item</th><th>Who</th><th>Age</th><th>Due</th></tr>"]
    for r in shown:
        out.append('<tr%s><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
                   % (' class="ws-loud"' if r.get("loud") else "", r["item"],
                      esc(str(r.get("who") or "—")), esc(str(r.get("age") or "—")),
                      esc(str(r.get("due") or "—"))))
    out.append("</table>")
    if rest:
        out.append('<div class="sub ws-more">+%d more — every one is still counted in the '
                   'heading; the full set lives in %s.</div>'
                   % (len(rest), md_inline(more_at)))
    return "".join(out)


def render_router_rows(phase_summaries):
    """The top of the one page: six rows, bounded by PHASE count. Each summary is
    (phase, n_needs, n_flight, clause, has_section). Needs-you is the headline; in-flight
    is muted. ⭐ ZERO COLLAPSES: a phase with nothing at all is a muted one-liner with no
    anchor and NO section below it — four empty phases must never consume the page while
    one phase holds all the work."""
    out = ['<div class="router">']
    for phase, n_needs, n_flight, clause, has_section in phase_summaries:
        label = "%s %s" % (_PHASE_ICON[phase], phase)
        name = ('<a class="ph" href="#phase-%s">%s</a>' % (phase, label)) if has_section \
            else ('<span class="ph">%s</span>' % label)
        if n_needs == 0 and n_flight == 0 and not has_section:
            out.append('<div class="rrow zero"><span class="ct">0</span>'
                       '<span class="ct2"></span>%s'
                       '<span class="nx">%s</span></div>' % (name, md_inline(clause)))
            continue
        flight = ('<span class="ct2">%d in flight</span>' % n_flight) if n_flight \
            else '<span class="ct2"></span>'
        out.append('<div class="rrow%s"><span class="ct">%d</span>%s%s'
                   '<span class="nx">%s</span></div>'
                   % (" quiet" if n_needs == 0 else "", n_needs, flight, name,
                      md_inline(clause)))
    out.append("</div>")
    return "".join(out)


def _variant_staleness():
    """(n_active, n_stale) for the presence row: active resume variants whose union_sha
    no longer matches the claim union (presence/claims.md). Same 12-hex stamp resume_variants.py --stamp writes."""
    import hashlib as _h
    variants = [v for v in load_jsonl("resume_variants.jsonl") if v.get("status") == "active"]
    try:
        cur = _h.sha256(Path(_tree.path(str(ROOT), "claims")).read_bytes()).hexdigest()[:12]
    except OSError:
        cur = None
    stale = [v for v in variants if cur and v.get("union_sha") != cur]
    return len(variants), len(stale), stale


# `phase_rows`, `publish_selection` and `render_router` lived here until 2026-08-29.
# The collapse deleted them: the router is now the top section of the one page
# (render_router_rows above, fed per-phase in main()), and there is no publish
# SELECTION left to compute — the publish set is the one artifact, every run.


# The tombstone written where dashboard.html used to be — CONSTANT, carrying no state,
# so the local-copy staleness window (public #22 / dev #233) is closed by construction.
DASHBOARD_TOMBSTONE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><title>Dashboard has moved</title></head>
<body style="font-family:sans-serif;max-width:34em;margin:3em auto;line-height:1.5">
<h1>This local copy is retired</h1>
<p>The dashboard is the <strong>published artifact</strong> now — one rendering, no
local twin to go stale (dev #233). Its URL is in <code>views/dashboard_artifact_url.txt</code>.
The generated pages live in <code>views/</code> (public #28); regenerate with
<code>generate_dashboard.py</code>.</p>
</body></html>
"""


def load_jsonl(name):
    import json as _json
    path = ROOT / "data" / name
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(_json.loads(line))
    return out


def _fmt_comp(c):
    if not c:
        return "Not disclosed"
    def k(v): return ("%s%dK" % (CURRENCY, round(v/1000))) if v else "?"
    lo, hi = c.get("min"), c.get("max")
    rng = k(lo) if lo == hi else "%s–%s" % (k(lo), k(hi))
    return "%s %s" % (rng, c.get("basis", ""))


def _fmt_loc(loc):
    if not isinstance(loc, dict):
        return ""
    t = loc.get("type", "")
    p = loc.get("primary", "")
    return ("%s — %s" % (t, p)) if p and t not in p.lower() else (p or t)


# Disposition -> the Contact-Status-style label the renderer chips on, and the live/closed split.
# `expired` (issue #6) is terminal like `passed` but is LABELLED apart from it — the whole point
# of the state is that "the posting vanished" and "I declined" stop looking like one thing.
_STATUS_LABEL = {
    "active-pursuit": "Active pursuit", "needs-resolution": "Needs resolution",
    "in-motion": "In motion", "backlog": "Parked", "passed": "Passed / closed",
    "expired": "Expired",
}
_CLOSED_STATUSES = {"passed", "backlog", "expired"}


def opps_from_jsonl():
    """Build the sourced-pipeline table from data/*.jsonl (the 2026-07-20 cutover).
    Returns (headers, live_rows, closed_rows, status_col, comp_col, jd_col) mirroring
    what the old markdown-parse path produced, so render_table is unchanged."""
    companies = {c["id"]: c for c in load_jsonl("companies.jsonl")}
    opps = load_jsonl("opportunities.jsonl")
    headers = ["Company", "Title", "Comp", "Location", "Status", "JD"]
    live, closed = [], []
    # active first, then by company; closed bucket sorted by company
    order = {"active-pursuit": 0, "needs-resolution": 1, "in-motion": 2, "backlog": 3,
             "passed": 4, "expired": 5}
    for o in sorted(opps, key=lambda o: (order.get(o.get("status"), 9), o.get("company_id", ""))):
        comp = companies.get(o.get("company_id"), {})
        row = [
            comp.get("name", o.get("company_id", "")),
            o.get("title", ""),
            _fmt_comp(o.get("comp")),
            _fmt_loc(o.get("location")),
            _STATUS_LABEL.get(o.get("status"), o.get("status", "")),
            o.get("jd_url") or "",
        ]
        (closed if o.get("status") in _CLOSED_STATUSES else live).append(row)
    return headers, live, closed, 4, 2, 5


def firms_from_channels():
    """Recruiter/referral channels -> the Network tab's firms table (cutover 2026-07-20,
    replacing network.md's firm sections). Columns mirror the old table."""
    chans = [c for c in load_jsonl("channels.jsonl") if c.get("type") in ("recruiter", "referral")]
    headers = ["Firm", "Contact(s)", "Relationship"]
    rows = []
    for c in sorted(chans, key=lambda c: c.get("label", "")):
        contacts = ", ".join(ct.get("name", "") for ct in c.get("contacts", [])) or "—"
        rows.append([c.get("label", ""), contacts, c.get("relationship_status") or ""])
    return headers, rows


# ─────────────────────────────────────────────────────────────────────────────
# SOURCING STRATEGY — dev #148 (GitHub issue #148).
#
# The dashboard read channels.jsonl for the Network firms table and the Your Move touch
# queue, but never the fields a STRATEGY REVIEW runs on: relationship_status (active vs
# retired), review_cadence / last_reviewed / next-due, access (the route), and yield. That
# one view was reachable only by running channels_due.py / funnel_report.py by hand —
# a field-level gap invisible to any file-level scan, because this file already named the
# store. Classification and yield are channels_due.py's ONE definition (review_rows /
# channel_yield); this only renders what they say — the your_move.py single-owner rule.
# ─────────────────────────────────────────────────────────────────────────────

def sourcing_view(today=None):
    """(active_rows, retired_rows, n_due) for the Sourcing tab.

    active_rows: (label, scope, route, cadence, last_reviewed, due_html, yield_text, state)
    retired_rows: (label, scope, yield_text). `state` is channels_due.review_rows' own
    word (due / current / on-inbound / unscheduled) — carried so the pipeline working set
    can list due reviews without re-deriving membership (the single-owner rule)."""
    import channels_due as _cd
    chans = load_jsonl("channels.jsonl")
    yields = _cd.channel_yield(load_jsonl("opportunities.jsonl"))
    today = today or datetime.date.today()
    active, retired, n_due = [], [], 0

    def _yield_text(cid):
        y = yields.get(cid)
        if not y:
            return "—"
        return "%d sighting%s · %d pursued" % (y["sightings"],
                                               "" if y["sightings"] == 1 else "s",
                                               y["pursued"])

    for c, state, detail in _cd.review_rows(chans, today):
        label = c.get("label") or c.get("id") or "?"
        scope = c.get("scope_notes") or ""
        ytxt = _yield_text(c.get("id"))
        if state == "retired":
            retired.append((label, scope, ytxt))
            continue
        route = " · ".join(b for b in (c.get("type"), c.get("access")) if b) or "—"
        cadence = c.get("review_cadence") or "—"
        lr = c.get("last_reviewed") or "never"
        if state == "due":
            n_due += 1
            due_html = ('<span class="chip action">due now</span> '
                        '<span class="sub">%s</span>' % esc(detail["why"]))
        elif state == "current":
            due_html = '<span class="chip scheduled">%s</span>' % esc(detail["next_due"])
        elif state == "on-inbound":
            due_html = '<span class="chip waiting">on inbound</span>'
        else:  # unscheduled — a misconfiguration, loud on the page as in the CLI
            due_html = ('<span class="chip action">⚠️ unscheduled</span> '
                        '<span class="sub">%s</span>' % esc(detail["why"]))
        active.append((label, scope, route, cadence, lr, due_html, ytxt, state))
    return active, retired, n_due


def render_sourcing_tables(active, retired):
    """(active_table_html, retired_html). Hand-rendered (not render_table) because the
    next-due cell carries chip HTML that md_inline would escape."""
    if active:
        out = ["<table><tr>"]
        for h in ("Channel", "Route", "Cadence", "Last reviewed", "Next review", "Yield"):
            out.append("<th>%s</th>" % h)
        out.append("</tr>")
        for label, scope, route, cadence, lr, due_html, ytxt, _state in active:
            name = "<strong>%s</strong>" % esc(label)
            if scope:
                name += '<div class="sub">%s</div>' % esc(scope)
            out.append("<tr>" + "".join(
                "<td>%s</td>" % cell
                for cell in (name, esc(route), esc(cadence), esc(lr), due_html, esc(ytxt)))
                + "</tr>")
        out.append("</table>")
        active_html = "".join(out)
    else:
        active_html = '<div class="sub">No sourcing channels on file yet.</div>'

    # Retired channels stay NAMED (issue #148: silently dropping one reads as coverage,
    # and retirement is a two-effect decision — review queue AND alert sweep). Capped like
    # every list since the collapse; the records stay queryable in data/channels.jsonl.
    if retired:
        shown, rest = retired[:WORKING_SET_CAP], retired[WORKING_SET_CAP:]
        rows = []
        for label, scope, ytxt in shown:
            rows.append('<tr><td><strong>%s</strong>%s</td>'
                        '<td><span class="chip closed">retired</span></td><td>%s</td></tr>'
                        % (esc(label),
                           '<div class="sub">%s</div>' % esc(scope) if scope else "",
                           esc(ytxt)))
        retired_html = ("<table><tr><th>Channel</th><th>Status</th><th>Lifetime yield</th>"
                        "</tr>%s</table>" % "".join(rows))
        if rest:
            retired_html += ('<div class="sub ws-more">+%d more retired — all still in '
                             '<code class="fileref">data/channels.jsonl</code>.</div>'
                             % len(rest))
        retired_html += ('<div class="sub">Retiring a channel also stops the alert sweep '
                         'reading its digests — both effects follow '
                         '<code>relationship_status</code> in the record.</div>')
    else:
        retired_html = '<div class="sub">No retired channels.</div>'
    return active_html, retired_html


SUBMITTED_STATES = ("submitted", "acknowledged", "interviewing", "offer")


def application_tables(today=None):
    """Answer 'what have I applied to, and what haven't I?' — added 2026-07-22 at the candidate's ask.

    Splits into THREE buckets, because "no application" is not one thing:
      1. Submitted        — an application actually went in.
      2. Human path       — in play through a recruiter or a live conversation, where
                            applying would be redundant or wrong (<an employer> via Ashford Search,
                            <an employer> mid-process). NOT a gap.
      3. Nothing sent     — being carried as a pursuit with no application AND no
                            outreach. THIS is the real gap and the only bucket that
                            should ever feel uncomfortable.
    """
    import datetime as _dt
    today = today or _dt.date.today()
    opps = load_jsonl("opportunities.jsonl")
    companies = {c["id"]: c for c in load_jsonl("companies.jsonl")}

    def cname(o):
        return companies.get(o.get("company_id"), {}).get("name") or o.get("company_id", "")

    def age(d):
        try:
            return (today - _dt.date(*map(int, d.split("-")))).days
        except Exception:
            return None

    submitted, human, nothing = [], [], []
    for o in opps:
        # Terminal roles have no application gap to report — an expired posting can no longer
        # be applied to, so listing it under "nothing sent" would nag about the impossible.
        if o.get("status") in ("passed", "expired"):
            continue
        apps = [a for a in (o.get("applications") or []) if a.get("status") in SUBMITTED_STATES]
        if apps:
            a = sorted(apps, key=lambda x: x.get("date") or "")[-1]
            days = age(a.get("date") or "")
            cl = a.get("cover_letter_attached")
            cl_txt = "yes" if cl is True else ("no" if cl is False else "unrecorded")
            submitted.append([cname(o), o.get("title", ""), a.get("date") or "—",
                              f"{days}d" if days is not None else "—",
                              a.get("status", ""), cl_txt,
                              (a.get("method") or "").replace("-", " ")])
            continue
        contacts = len(o.get("outreach") or [])
        # `in-motion` is defined in CLAUDE.md as a recruiter/network thread — the
        # recruiter approached the candidate, so there is no outreach[] row from their side and
        # its absence is NOT evidence that nothing is happening.
        if contacts or o.get("status") == "in-motion" or o.get("stage") in ("screening", "interviewing", "offer"):
            who = ", ".join(x.get("to", "") for x in (o.get("outreach") or []) if x.get("to")) or "in process"
            nxt = (o.get("next_action") or "").strip()
            human.append([cname(o), o.get("title", ""), o.get("stage", ""), who, nxt[:150]])
        else:
            nxt = (o.get("next_action") or "").strip()
            nothing.append([cname(o), o.get("title", ""), o.get("status", ""), nxt[:180] or "— no next action recorded —"])

    submitted.sort(key=lambda r: r[2], reverse=True)
    return submitted, human, nothing


# `opp_focus_from_jsonl()` lived here until 2026-08-18 and was NEVER CALLED — the 2026-08-10
# one-list cutover (`render_opportunity_list`) replaced the focus-group view it rendered, and
# the function survived looking load-bearing, the same defect that kept `render_fit()` alive
# (GitHub #5). Removed with the focus.md cutover (dev #93).


# `asks_from_jsonl` lived here until 2026-08-29: main() now reads your_move.open_asks
# directly, because the working-set tables need act_by and created as their own cells
# rather than folded into an ask sentence. Membership is still your_move.open_asks's.


# `this_week_from_jsonl` lived here until 2026-08-29: the This Week card is a working-set
# TABLE now, built in main() straight from data/commitments.jsonl with the same
# membership (dated today or later, soonest first, plus the loud `unresolved` marker
# rows — an unreadable date is an unknown, never a pass).


def _role_title(o, companies, mark="🎯"):
    comp = companies.get(o.get("company_id"), {})
    return "%s %s — %s" % (mark, comp.get("name", o.get("company_id", "")), o.get("title", ""))


def _role_ask(o):
    ctx = [b for b in (_fmt_comp(o.get("comp")) if o.get("comp") else "",
                       _fmt_loc(o.get("location"))) if b]
    return ((" · ".join(ctx) + ". ") if ctx else "") + (o.get("next_action") or "")


def your_move_roles_from_jsonl():
    """Role decisions on Your Move are a FILTERED VIEW of data/opportunities.jsonl —
    not hand-copied prose (added 2026-07-29, per the candidate: 'the your move page should be a
    targeted view of the data on opportunities'). Any opportunity flagged with this
    candidate's own next_action_owner token (see profile.owner_token()) while still live
    surfaces here automatically, with its
    comp / location / lean / JD link sourced straight from the record. To move a role on
    or off Your Move, change its next_action_owner in the JSONL — never a hand-typed list.

    ⭐ GitHub #79 — ownership alone is no longer the filter. `your_move.py` is the single
    owner of role-group membership (unresolved / waiting / scheduled / now); this renders
    ONLY the `now` group — a future-dated or blocked role does not belong in the primary
    "needs you" queue. `your_move_callouts()` surfaces the other three states.

    Returns (title, ask, opp_id) tuples matching render_your_move's shape (opp_id lets it
    resolve the JD link from the same links map the tagged manual asks use)."""
    companies = {c["id"]: c for c in load_jsonl("companies.jsonl")}
    classified = _ym.classify_opportunities(load_jsonl("opportunities.jsonl"), OWNER_TOKEN)
    items = []
    for o, state, _why in classified:
        if state != "now":
            continue
        items.append((_role_title(o, companies), _role_ask(o), o.get("id"),
                      o.get("next_action_date") or "9999"))
    # Soonest act-by first, so the most time-sensitive decision leads.
    items.sort(key=lambda t: t[3])
    return [(t, a, oid) for (t, a, oid, _d) in items]


def your_move_decides_from_jsonl():
    """dev #142 (public #24) — the DECIDE group: a user-owned role in a sourced/backlog
    state (`status: backlog`, `verdict: undecided`) whose pursue/pass decision is still
    owed. Rendered REGARDLESS of `next_action_date`, because the date answers "when is the
    action scheduled" while this surface asks "is a decision owed" — before this group
    existed, the intuitive way to record a newly sourced role (backlog status, user as
    owner, future act-by date) produced a row visible on NO Your Move group, silently.

    ⭐ This does not reopen issue #79's over-inclusion: membership is keyed on the VERDICT,
    not on relaxing the date cutoff. A decided defer (`verdict: parked`) stays off, a
    future-dated LIVE role is still `scheduled`, and a `blocked_until` still routes an
    undecided row to waiting/unresolved. Membership is your_move.py's alone; this renders
    ONLY the `decide` group, as its own labelled section so the reader can tell what kind
    of item it is from the surface — #79's core complaint.

    Returns render_your_move's (title, ask, opp_id) tuples, soonest act-by first."""
    companies = {c["id"]: c for c in load_jsonl("companies.jsonl")}
    classified = _ym.classify_opportunities(load_jsonl("opportunities.jsonl"), OWNER_TOKEN)
    items = []
    for o, state, _why in classified:
        if state != "decide":
            continue
        d = o.get("next_action_date")
        ask = "Decide: pursue or pass — the verdict is still undecided."
        if d:
            ask += " Act by %s." % d
        if o.get("next_action"):
            ask += " %s" % o["next_action"]
        items.append((_role_title(o, companies, "🔎"), ask, o.get("id"), d or "9999"))
    items.sort(key=lambda t: t[3])
    return [(t, a, oid) for (t, a, oid, _d) in items]


def your_move_channels_from_jsonl():
    """Relationship follow-ups on Your Move are a FILTERED VIEW of data/channels.jsonl —
    GitHub #44.

    ⭐⭐ THE SAME CUTOVER THAT ALREADY FIXED ROLES. Role decisions were hand-maintained prose
    in focus.md until 2026-07-20, went stale, and were cut over to a filtered view of the
    opportunities data. The other half of this surface — cross-cutting asks, of which
    channel and relationship follow-ups are the clearest example — was left typed by hand,
    so it kept the defect the cutover removed: an item asserting an action is still pending
    after the operating store already records it done, expelled only when a human notices.

    ⭐ NO NEW FIELD, AND NO MIGRATION. `channels.jsonl` already carries `next_touch`
    {date, time, note} — a relationship call not tied to a role — and a `next_touch` IS by
    definition an action the candidate takes. Adding a parallel `next_action_owner` here
    would be inventing a second way to say what the record already says, which is the very
    duplication this issue is about.

    ⭐ GitHub #79 — a truthy `next_touch.date` is no longer enough by itself. `your_move.py`
    is the single owner of channel-group membership (now / scheduled / fulfilled), derived
    from actual outbound messages and log[] entries rather than a hand-authored field; this
    renders ONLY the `now` group. A future-dated plan does not belong here yet (it is
    `scheduled`), and a plan a later touch already satisfied does not belong here either (it
    is `fulfilled`) — the item leaves this list the moment the derived data says so, not when
    somebody remembers to clear `next_touch` by hand. `your_move_callouts()` surfaces the
    other two states. Returns render_your_move's (title, ask, opp_id) shape; opp_id is None
    because a relationship follow-up has no job posting to link to.
    """
    messages = load_jsonl("messages.jsonl")
    items = []
    for c, state, _touch, _evidence in _ym.classify_channels(load_jsonl("channels.jsonl"),
                                                               messages):
        if state != "now":
            continue
        nt = c.get("next_touch") or {}
        label = c.get("label") or c.get("id") or "a channel"
        when = str(nt.get("date"))
        bits = [b for b in (nt.get("time"), nt.get("note")) if b]
        ask = "Due %s. %s" % (when, " · ".join(str(b) for b in bits)) if bits \
            else "Due %s." % when
        rel = c.get("relationship_status")
        if rel:
            ask += " (%s)" % rel
        items.append(("🤝 %s" % label, ask, None, when))
    items.sort(key=lambda t: t[3])
    return [(t, a, oid) for (t, a, oid, _d) in items]


def your_move_callouts():
    """GitHub #79 — the states that must NEVER render inside the primary "needs you"
    queue, but must not vanish silently either: an unresolved/unreadable `blocked_until`, a
    role still waiting on the other side, a channel plan a touch already fulfilled but
    nobody has cleared — and (dev #95 follow-on) a `play_stage` still carrying the
    migration marker `unresolved`. Each is its own loud callout — see
    render_your_move_callouts().

    Returns (unresolved, waiting, fulfilled, play_unresolved), each a list of
    render_your_move's (title, ask, opp_id) tuples.
    """
    companies = {c["id"]: c for c in load_jsonl("companies.jsonl")}
    all_opps = load_jsonl("opportunities.jsonl")
    unresolved, waiting = [], []
    for o, state, why in _ym.classify_opportunities(all_opps, OWNER_TOKEN):
        if state == "unresolved":
            unresolved.append((_role_title(o, companies, "🚧"), why, o.get("id"),
                               o.get("next_action_date") or "9999"))
        elif state == "waiting":
            waiting.append((_role_title(o, companies, "⏳"), why, o.get("id"),
                            o.get("next_action_date") or "9999"))
    unresolved.sort(key=lambda t: t[3])
    waiting.sort(key=lambda t: t[3])

    messages = load_jsonl("messages.jsonl")
    fulfilled = []
    for c, state, touch, evidence in _ym.classify_channels(load_jsonl("channels.jsonl"),
                                                            messages):
        if state != "fulfilled":
            continue
        label = c.get("label") or c.get("id") or "a channel"
        nt = c.get("next_touch") or {}
        ask = ("Plan fulfilled on %s by %s (planned for %s) — clear next_touch or author the "
              "next one." % (touch, evidence, nt.get("date")))
        fulfilled.append(("✅ %s" % label, ask, None, str(touch or "")))
    fulfilled.sort(key=lambda t: t[3])

    # dev #95 follow-on — membership is your_move.py's, never re-derived here. The ask is an
    # imperative aimed at the owner (check_sections.py's own rule for Your Move lines).
    play = []
    for o in _ym.unresolved_play_stages(all_opps):
        ask = ("The play position is the migration marker, not a real value — replace it: "
               "`record.py set %s play_stage <stage>` (sequence: %s)."
               % (o.get("id") or "?", " → ".join(_PLAY_SEQUENCE)))
        play.append((_role_title(o, companies, "🎬"), ask, o.get("id")))

    return ([(t, a, oid) for (t, a, oid, _d) in unresolved],
            [(t, a, oid) for (t, a, oid, _d) in waiting],
            [(t, a, oid) for (t, a, oid, _d) in fulfilled],
            play)


def render_your_move_callouts(unresolved, waiting, fulfilled, play_unresolved, links=None):
    """Loud, non-"needs you" callouts for Your Move — GitHub #79. None of these three groups
    render inside render_your_move's primary list; they exist so an unresolved precondition,
    a still-pending one, or an uncleared fulfilled plan is visible rather than silently
    dropped, without padding the one list that must stay unskippable."""
    parts = []
    if unresolved:
        parts.append(
            '<h2 style="font-size:16px;margin-top:22px">🚧 Unresolved — blocked_until needs a '
            'real join <span class="tcount">%d</span></h2>'
            '<div class="sub" style="margin:-6px 0 10px">An unreadable or unstructured '
            '<code>blocked_until</code>. Never "needs you" until it is replaced with '
            '<code>contact:&lt;id&gt; outcome:&lt;...&gt;</code>.</div>'
            '<div class="card">%s</div>' % (len(unresolved), render_your_move(unresolved, links)))
    if waiting:
        parts.append(
            '<h2 style="font-size:16px;margin-top:22px">⏳ Waiting on the other side '
            '<span class="tcount">%d</span></h2>'
            '<div class="sub" style="margin:-6px 0 10px">Blocked until the named contact '
            'reaches the outcome the role is waiting on. <strong>Not yours to do</strong> — '
            'moves to the list above by itself once the record shows it.</div>'
            '<div class="card">%s</div>' % (len(waiting), render_your_move(waiting, links)))
    if fulfilled:
        parts.append(
            '<h2 style="font-size:16px;margin-top:22px">✅ Plans fulfilled, not yet cleared '
            '<span class="tcount">%d</span></h2>'
            '<div class="sub" style="margin:-6px 0 10px">A touch landed on or after the '
            'planned date. Clear <code>next_touch</code> or author the next one.</div>'
            '<div class="card">%s</div>' % (len(fulfilled), render_your_move(fulfilled, links)))
    if play_unresolved:
        parts.append(
            '<h2 style="font-size:16px;margin-top:22px">🎬 Play position unresolved — set the '
            'real stage <span class="tcount">%d</span></h2>'
            '<div class="sub" style="margin:-6px 0 10px">The migration found a numbered play '
            'marker in prose but could not name the stage, so it wrote the literal '
            '<code>unresolved</code>. The prose survives on the role; only a human can name '
            'the position.</div>'
            '<div class="card">%s</div>'
            % (len(play_unresolved), render_your_move(play_unresolved, links)))
    return "".join(parts)


# ── The stylesheet. Tokens define the complete light palette on bare :root, redefine
# under prefers-color-scheme:dark (guarded against an explicit light choice), and again
# under [data-theme] so the viewer's toggle wins in both directions. Hoisted out of
# main() with the 2026-08-29 collapse so the one page's CSS has one home.
_CSS_ROUTER = """
  /* ── The merged router + phase sections (the one-artifact collapse, 2026-08-29) ── */
  .router { background: var(--card-bg); border: 1px solid var(--card-border);
            border-radius: 10px; padding: 4px 14px; margin: 4px 0 10px; }
  .rrow { display: flex; gap: 12px; align-items: baseline; padding: 10px 2px;
          border-bottom: 1px solid var(--divider); flex-wrap: wrap; }
  .rrow:last-child { border-bottom: none; }
  .rrow .ct { font-weight: 700; font-size: 16px; color: var(--chip-action-fg);
              min-width: 1.6em; text-align: right; }
  .rrow.quiet .ct, .rrow.zero .ct { color: var(--muted); font-weight: 600; }
  .rrow .ct2 { color: var(--muted); font-size: 11.5px; min-width: 6.5em; }
  .rrow .ph { font-weight: 700; min-width: 9.5em; text-decoration: none;
              color: var(--fg); }
  .rrow a.ph:hover { color: var(--rail-now); }
  .rrow .nx { color: var(--muted2); font-size: 12.5px; }
  .rrow.zero { opacity: .55; }
  section.phase { scroll-margin-top: 12px; }
  .phase-h { font-size: 17px; margin: 30px 0 2px; padding-top: 14px;
             border-top: 2px solid var(--card-border); }
  .phase-h .ct2f { font-weight: 500; font-size: 12px; color: var(--muted); margin-left: 6px; }
  .subcounts { color: var(--muted2); font-size: 12px; margin: 2px 0 10px; }
  .subcounts a { color: var(--rail-now); text-decoration: none; }
  tr.ws-loud td, div.ws-loud .draft-title { color: var(--chip-action-fg); }
  .ws-more { margin-top: 6px; }
  .inflight { opacity: .82; }
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
    --chip-closed-bg: #ececec; --chip-closed-fg: #666;
    --pill-bg: #f0efeb; --pill-fg: #1a1a1a; --pill-done-fg: #999;
    --note-bg: #eef4fb; --note-border: #d5e4f5; --note-fg: #2c5580;
  }
  * { box-sizing: border-box; margin: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: var(--bg); color: var(--fg); padding: 20px; font-size: 14px; }
  h1 { font-size: 20px; margin-bottom: 2px; }
  .updated { color: var(--muted); font-size: 12px; margin-bottom: 18px; }
  h2 { font-size: 15px; margin: 22px 0 10px; }
  .mega-header { font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted2); background: var(--divider); border-radius: 8px; padding: 8px 14px; margin: 28px 0 4px; }
  .mega-header:first-of-type { margin-top: 8px; }
  .card { background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 10px; padding: 14px 16px; margin-bottom: 10px; overflow-x: auto; }
  /* Your-move panel — the priority-decision surface, deliberately loud */
  .ym-card { background: var(--card-bg); border: 2px solid #d97706; border-radius: 12px;
             padding: 14px 16px; margin: 18px 0 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.07); }
  .ym-head { font-size: 13px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.05em;
             margin-bottom: 10px; }
  .ym-item { display: flex; gap: 12px; align-items: flex-start; padding: 9px 0;
             border-bottom: 1px solid var(--divider); }
  .ym-item:last-child { border-bottom: none; }
  .ym-num { background: #d97706; color: #fff; border-radius: 50%; width: 22px; height: 22px;
            min-width: 22px; display: flex; align-items: center; justify-content: center;
            font-size: 12px; font-weight: 700; margin-top: 1px; }
  .ym-title { font-weight: 700; }
  .ym-jd { font-weight: 600; font-size: 11px; color: #b45309; text-decoration: none;
           background: #fef3c7; border: 1px solid #fcd34d; border-radius: 4px;
           padding: 1px 6px; margin-left: 6px; white-space: nowrap; vertical-align: middle; }
  .ym-jd:hover { background: #fde68a; }
  .ym-ask { color: var(--muted2); font-size: 12.5px; margin-top: 2px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { text-align: left; color: var(--th); font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: .04em; padding: 6px 10px 6px 0; border-bottom: 1px solid var(--card-border); }
  td { padding: 8px 10px 8px 0; border-bottom: 1px solid var(--divider); vertical-align: top; }
  tr:last-child td { border-bottom: none; }
  .chip { display: inline-block; padding: 2px 9px; border-radius: 20px; font-size: 11.5px; font-weight: 600; }
  .chip.waiting { background: var(--chip-waiting-bg); color: var(--chip-waiting-fg); }
  .chip.action { background: var(--chip-action-bg); color: var(--chip-action-fg); }
  .chip.scheduled { background: var(--chip-scheduled-bg); color: var(--chip-scheduled-fg); }
  .chip.closed { background: var(--chip-closed-bg); color: var(--chip-closed-fg); }
  .sub { color: var(--muted2); font-size: 12px; }
  .pill-row { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
  .pill { background: var(--pill-bg); color: var(--pill-fg); border-radius: 6px; padding: 3px 8px; font-size: 12px; }
  .pill.done { text-decoration: line-through; color: var(--pill-done-fg); }
  .note { background: var(--note-bg); border: 1px solid var(--note-border); border-radius: 8px; padding: 10px 14px; font-size: 12.5px; color: var(--note-fg); margin-top: 16px; }
  .stats-row { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
  .stat { background: var(--divider); border-radius: 8px; padding: 6px 12px; font-size: 12.5px; }
  .stat strong { font-size: 15px; }
  .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; vertical-align: middle; }
  .dot-clear { background: #1c7c46; }
  .dot-below { background: #a12626; }
  .dot-unknown { background: #999; }
  details.closed-group { margin-top: 10px; }
  details.closed-group summary { cursor: pointer; color: var(--muted2); font-size: 12.5px; padding: 6px 0; }
  details.closed-group summary:hover { color: var(--fg); }
  .draft { padding: 10px 0; border-bottom: 1px solid var(--divider); }
  .draft:last-child { border-bottom: none; }
  .draft-title { font-weight: 600; }
  .draft-meta { color: var(--muted2); font-size: 12px; margin: 2px 0 8px; }
  .draft-body { font-size: 13px; line-height: 1.5; background: var(--divider); border-radius: 8px; padding: 10px 12px; }
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

  /* CSS-only filters, matching the tab pattern already used on this page. */
  .oppfilter { display:none; }
  .oppbar { display:flex; gap:6px; flex-wrap:wrap; margin:2px 0 8px; }
  .oppbar label { font-size:12px; padding:4px 10px; border-radius:999px; cursor:pointer;
                  border:1px solid var(--card-border); opacity:.75; }
  #of-all:checked ~ .oppbar label[for="of-all"],
  #of-you:checked ~ .oppbar label[for="of-you"],
  #of-app:checked ~ .oppbar label[for="of-app"],
  #of-per:checked ~ .oppbar label[for="of-per"],
  #of-non:checked ~ .oppbar label[for="of-non"] {
      opacity:1; font-weight:600; border-color:var(--rail-now); color:var(--rail-now); }
  #of-you:checked ~ .opp-list .opp[data-you="0"],
  #of-app:checked ~ .opp-list .opp[data-bucket="person"],
  #of-app:checked ~ .opp-list .opp[data-bucket="nothing"],
  #of-per:checked ~ .opp-list .opp[data-bucket="applied"],
  #of-per:checked ~ .opp-list .opp[data-bucket="nothing"],
  #of-non:checked ~ .opp-list .opp[data-bucket="applied"],
  #of-non:checked ~ .opp-list .opp[data-bucket="person"] { display:none; }
  @media (prefers-reduced-motion: reduce) { .opp-more { transition:none; } }

  /* dev #95 follow-on: the migration marker must read as a defect on the row, not a value. */
  .play-unres { color: var(--chip-action-fg); font-weight: 600; }

  /* ── Knowledge artifacts (GitHub #94) — kb/ and call_preps/ rendered as content. ── */
  .kdoc { border-bottom: 1px solid var(--divider); padding: 8px 0; }
  .kdoc:last-child { border-bottom: none; }
  .kdoc > summary { cursor: pointer; list-style: none; }
  .kdoc > summary::-webkit-details-marker { display: none; }
  .kdoc > summary::before { content: "▸ "; opacity: .6; }
  .kdoc[open] > summary::before { content: "▾ "; }
  .kdoc-body { margin: 8px 0 4px 14px; padding-left: 12px;
               border-left: 2px solid var(--card-border); }
  .kd-h { font-weight: 700; margin: 10px 0 4px; }
  .kd-h1 { font-size: 15px; }
  .kd-h2 { font-size: 14px; }
  .kd-h3, .kd-h4 { font-size: 13px; color: var(--muted2); }
  .kd-p { font-size: 13px; line-height: 1.55; margin: 4px 0; }
  .kd-l { font-size: 13px; margin: 4px 0 4px 18px; padding: 0; }
  .kd-q { border-left: 3px solid var(--card-border); background: var(--divider);
          border-radius: 4px; padding: 4px 10px; margin: 4px 0; font-size: 13px; }
""" + _CSS_ROUTER


def main():
    # `net = read(...network...)` left with the Network tab (2026-08-29): the network is
    # queried, not queued (D4) — it never contributed a count, and its firm/alumni tables
    # were the page's only remaining markdown-table parse. Its location is named in the
    # page footer; the data stays fully queryable in session.
    drafts = parse_drafts(read(_tree.rel("drafts")))
    # Cover letters are a distinct artifact from outreach drafts (added 2026-07-21,
    # per the candidate: the "why is this job a great fit" message was missing entirely).
    covers = [c for c in parse_cover_letters(read(_tree.rel("cover_letters")))]

    # ⭐⭐ focus.md IS RETIRED AS A SOURCE OF STATE — dev #93 (public #21). Every surface
    # below reads a store; the hand tail lives in data/asks.jsonl, commitments in
    # data/commitments.jsonl. (See the dev #93 narrative in this file's history.)
    _all_asks = load_jsonl("asks.jsonl")
    role_asks = _ym.open_asks(_all_asks, kind="role")
    system_asks = _ym.open_asks(_all_asks, kind="system")

    # SOURCED PIPELINE — data/*.jsonl (cutover 2026-07-20); the stats strip's numbers.
    _sh2, live_rows, closed_rows, _status_idx2, comp_idx2, _jd_idx = opps_from_jsonl()

    def clears_comp(comp_text):
        c = comp_text.lower()
        return any(k in c for k in ("clears", "clear the", "comfortably clear", "exceeds"))

    clearing_count = sum(1 for r in live_rows
                          if comp_idx2 is not None and comp_idx2 < len(r)
                          and clears_comp(r[comp_idx2]))
    stats_html = (
        '<div class="stats-row">'
        f'<div class="stat"><strong>{len(live_rows)}</strong> active</div>'
        f'<div class="stat"><strong>{clearing_count}</strong> clear comp floor</div>'
        f'<div class="stat"><strong>{len(closed_rows)}</strong> passed / closed</div>'
        f'<div class="stat"><strong>{len(live_rows) + len(closed_rows)}</strong> total sourced</div>'
        '</div>'
    )

    _opp_rows = load_jsonl("opportunities.jsonl")
    _opp_comps = {c["id"]: c for c in load_jsonl("companies.jsonl")}
    ym_links = {o["id"]: best_link(o) for o in _opp_rows if o.get("id")}
    _due_by_id = {o.get("id"): (o.get("next_action_date") or "") for o in _opp_rows}

    # Membership is your_move.py's alone (#79); this file only renders what it says.
    role_decisions = your_move_roles_from_jsonl()
    channel_touches = your_move_channels_from_jsonl()
    decide_rows = your_move_decides_from_jsonl()
    _unresolved_rows, _waiting_rows, _fulfilled_rows, _play_rows = your_move_callouts()
    your_move_callouts_html = render_your_move_callouts(_unresolved_rows, _waiting_rows,
                                                         _fulfilled_rows, _play_rows,
                                                         ym_links)

    # ── Preconditions over the staged-message pair (issues #6/#13, dev #169, public #29).
    # Same grouping rules as ever: NOT_SENDABLE and TERMINAL are precondition.py's to own.
    _DRAFTS_REL, _COVERS_REL = _tree.rel("drafts"), _tree.rel("cover_letters")
    try:
        import precondition as _pre
        _pre_rows = _pre.report(str(ROOT))
        _states = {(r.get("file", _DRAFTS_REL), r["title"]): r for r in _pre_rows}
        _not_sendable = _pre.NOT_SENDABLE
        _terminal = _pre.TERMINAL
    except Exception:
        _pre_rows, _states, _not_sendable, _terminal = [], {}, frozenset(), frozenset()

    # dev #154 — a READY staged message no open ask covers gets a DERIVED queue line.
    try:
        _ready_rows = _ym.ready_staged_without_ask(str(ROOT), pre_rows=_pre_rows)
    except Exception:
        _ready_rows = []
    _ready_items = [("✉️ %s" % r["title"],
                     "Approve and send — staged in %s and cleared to go; no open ask "
                     "points at it. The full text is in the Pending drafts block on this "
                     "page." % r["file"], None)
                    for r in _ready_rows]
    your_move_ready_html = ""
    if _ready_items:
        your_move_ready_html = (
            '<h2 id="phase-outreach-ready">✉️ Ready to send — staged, no ask '
            'on file <span class="tcount">%d</span></h2>'
            '<div class="sub" style="margin:-6px 0 10px">Fully written, every send-'
            'precondition met, and no open ask points at it — derived straight from the '
            'staged files, so a ready reply can never sit invisible again. Sending it (and '
            'logging the send), or recording the ask that owns it, removes the line by '
            'itself.</div>'
            '<div class="card">%s</div>'
            % (len(_ready_items), render_your_move(_ready_items)))

    def _pre_state(filename, title):
        return _states.get((filename, title), {}).get("state")

    # public #29 — TERMINAL entries land in NEITHER list.
    _drafts_active = [d for d in drafts if _pre_state(_DRAFTS_REL, d[0]) not in _terminal]
    _sendable = [d for d in _drafts_active if _pre_state(_DRAFTS_REL, d[0]) not in _not_sendable]
    _blocked = [d for d in _drafts_active if _pre_state(_DRAFTS_REL, d[0]) in _not_sendable]
    drafts_html = render_draft_index(_sendable, _states, _DRAFTS_REL,
                                     "No pending drafts.", "full body just below")
    blocked_html = render_draft_index(_blocked, _states, _DRAFTS_REL, "",
                                      "held — body stays in the file until unblocked")
    drafts_bodies_html = render_draft_bodies(_sendable, "No pending drafts.", _DRAFTS_REL)
    n_blocked = len(_blocked)

    # dev #169 — the covers panel consults preconditions exactly as the drafts panel does.
    _covers_active = [c for c in covers if _pre_state(_COVERS_REL, c[0]) not in _terminal]
    _covers_ready = [c for c in _covers_active if _pre_state(_COVERS_REL, c[0]) not in _not_sendable]
    _covers_held = [c for c in _covers_active if _pre_state(_COVERS_REL, c[0]) in _not_sendable]
    covers_html = render_draft_index(_covers_ready, _states, _COVERS_REL,
                                     "No cover letters pending.", "full body just below")
    covers_held_html = render_draft_index(_covers_held, _states, _COVERS_REL, "",
                                          "held — do not submit yet")
    covers_bodies_html = render_draft_bodies(_covers_ready, "No cover letters pending.",
                                             _COVERS_REL)
    n_covers_held = len(_covers_held)

    # dev #148 — sourcing strategy, via channels_due.py's one definition
    # (review_rows / channel_yield — the single-owner rule).
    _src_active, _src_retired, n_sourcing_due = sourcing_view()
    sourcing_active_html, sourcing_retired_html = render_sourcing_tables(_src_active,
                                                                          _src_retired)

    # public #20 (amended by the collapse): call preps render IN FULL on this page —
    # bounded by upcoming-call volume, and the one knowledge type someone reads on a
    # phone the night before. Company kb stays an INDEX (its bodies are not awaiting a
    # decision; inlining them is the measured 328 KB of the old 639 KB page).
    _preps, _kbs = knowledge_docs()
    preps_full_html = render_knowledge_docs(_preps, "No call preps on file.")
    kbs_html = render_knowledge_index(
        _kbs, "No company knowledge files yet.",
        "read in the file tree — knowledge bodies are not published (the collapse)")

    # ── Trigger-derived outreach numbers — every one from its owning module. ──
    import trigger as _trig
    try:
        _trep = _trig.report(str(ROOT))
        _n_unblocked = sum(1 for s in _trep["sequences"].values()
                           if s["state"] == "unblocked")
        _n_waiting_seqs = sum(1 for s in _trep["sequences"].values()
                              if s["state"] == "waiting")
        _untrig_rows = _trep["untriggered"]
    except Exception as _e:
        # ⚠️ A failed scan must NEVER read as "nothing owed" — that is the missing-reads-
        # as-empty trap. Zero counts with a loud line on the page and in the console.
        print("  !! WARNING: trigger scan failed (%s) — the outreach row cannot count "
              "sequences or unlinked applications; run trigger.py --check" % _e)
        _trep, _n_unblocked, _n_waiting_seqs, _untrig_rows = None, 0, 0, []
    import applying as _applying
    _apply_q = _applying.queue(_opp_rows)
    _submitted, _human, _nothing = application_tables()

    # ─────────────────────────────────────────────────────────────────────────
    # THE PHASE SECTIONS — each built as (needs rows, in-flight rows, extra panels),
    # every count a query. A phase at zero gets a muted router row and NO section.
    # ─────────────────────────────────────────────────────────────────────────
    _summaries = []           # (phase, n_needs, n_flight, clause, has_section)
    _sections = []

    def _emit(phase, n_needs, n_flight, clause, sub_bits, parts):
        inner = "\n  ".join(p for p in parts if p)
        has = bool(inner.strip())
        _summaries.append((phase, n_needs, n_flight, clause, has))
        if not has:
            return
        subs = " · ".join('<a href="#%s">%s</a>' % (sid, esc(lbl))
                          for lbl, sid in sub_bits if lbl)
        flight_note = (' <span class="ct2f">· %d in flight</span>' % n_flight) if n_flight else ""
        _sections.append(
            '<section class="phase" id="phase-%s">\n'
            '<h2 class="phase-h">%s %s <span class="tcount">%d</span>%s</h2>\n'
            '%s\n  %s\n</section>'
            % (phase, _PHASE_ICON[phase], phase, n_needs, flight_note,
               ('<div class="subcounts">needs you: %s</div>' % subs) if subs else "",
               inner))

    # ── configure ──────────────────────────────────────────────────────────
    cfg_rows = [ws_row("<strong>%s</strong> — %s"
                       % (md_inline(a.get("title") or a.get("id") or "?"),
                          esc(_clause(a.get("ask")))),
                       "you", _age_days(a.get("created")), a.get("act_by") or "")
                for a in system_asks]
    cfg_clause = (_clause(system_asks[0].get("title")) if system_asks
                  else "Nothing needs a settings decision.")
    cfg_parts = []
    if cfg_rows:
        cfg_parts.append(
            '<h2 id="phase-configure-asks">⚙️ System &amp; tooling — needs you '
            '<span class="tcount">%d</span></h2>'
            '<div class="sub" style="margin:-6px 0 10px">Decisions about the tracker, '
            'scripts, credentials, or tooling that only you can make. Each stays until it '
            'is done.</div>'
            '<div class="card">%s</div>'
            % (len(cfg_rows), render_ws(cfg_rows, "`data/asks.jsonl`", "")))
    _emit("configure", len(cfg_rows), 0, cfg_clause,
          [("settings decisions", "phase-configure-asks")] if cfg_rows else [], cfg_parts)

    # ── presence ───────────────────────────────────────────────────────────
    n_var, n_stale, _stale_variants = _variant_staleness()
    if n_var == 0:
        pres_clause, pres_rows = "No resume variants declared yet.", []
    elif n_stale:
        pres_clause = ("Reconcile %s against presence/claims.md — the claim union moved."
                       % ", ".join(v.get("id", "?") for v in _stale_variants[:3]))
        pres_rows = [ws_row("<strong>%s</strong> — reconcile against presence/claims.md"
                            % esc(v.get("id") or "?"), "you")
                     for v in _stale_variants]
    else:
        pres_clause = "%d variant%s reconciled — steady." % (n_var,
                                                             "" if n_var == 1 else "s")
        pres_rows = []
    pres_parts = []
    if pres_rows:
        pres_parts.append(
            '<h2 id="phase-presence-stale">🪞 Variants out of step with the claim union '
            '<span class="tcount">%d</span></h2>'
            '<div class="card">%s</div>'
            % (len(pres_rows),
               render_ws(pres_rows, "`data/resume_variants.jsonl`", "")))
    _emit("presence", len(pres_rows), 0, pres_clause,
          [("stale variants", "phase-presence-stale")] if pres_rows else [], pres_parts)

    # ── pipeline ───────────────────────────────────────────────────────────
    def _role_ws_rows(tuples):
        rows = []
        for t, a, oid in tuples:
            link = ym_links.get(oid)
            jd = (' <a class="opp-jd" href="%s" target="_blank" rel="noopener">JD ↗</a>'
                  % esc(link)) if link else ""
            rows.append(ws_row("<strong>%s</strong>%s — %s"
                               % (md_inline(t), jd, esc(_clause(a))),
                               "you", "", _due_by_id.get(oid, "")))
        return rows

    hand_role_rows = [ws_row("<strong>%s</strong> — %s"
                             % (md_inline(a.get("title") or a.get("id") or "?"),
                                esc(_clause(a.get("ask")))),
                             "you", _age_days(a.get("created")), a.get("act_by") or "")
                      for a in role_asks]
    now_ws = _role_ws_rows(role_decisions) + hand_role_rows
    decide_ws = _role_ws_rows(decide_rows)
    due_reviews_ws = [ws_row("<strong>%s</strong> — channel review due"
                             % esc(label), route, "", "now")
                      for (label, _scope, route, _cad, _lr, _dh, _y, st) in _src_active
                      if st == "due"]

    _needs_ids = ({oid for _t, _a, oid in role_decisions if oid}
                  | {oid for _t, _a, oid in decide_rows if oid})
    _callout_ids = ({oid for _t, _a, oid in _unresolved_rows if oid}
                    | {oid for _t, _a, oid in _waiting_rows if oid})
    _cls_map = {}
    for o, st, _w in _ym.classify_opportunities(_opp_rows, OWNER_TOKEN):
        if o.get("id"):
            _cls_map[o["id"]] = st
    pipe_flight_ws = []
    n_pipe_flight = 0
    for o in _opp_rows:
        if o.get("status") in _CLOSED_STATUSES or o.get("id") in _needs_ids:
            continue
        n_pipe_flight += 1
        if o.get("id") in _callout_ids:
            continue      # rendered richer in its callout below; still counted
        comp = _opp_comps.get(o.get("company_id"), {})
        st = _cls_map.get(o.get("id")) or ("stage: %s" % (o.get("stage") or "not set"))
        pipe_flight_ws.append(ws_row(
            "<strong>%s — %s</strong>"
            % (esc(comp.get("name", o.get("company_id", ""))), esc(o.get("title") or "")),
            st, "", o.get("next_action_date") or ""))

    n_pipe_needs = len(now_ws) + len(decide_ws) + len(due_reviews_ws)
    opp_alive_hint = any(o.get("status") not in _CLOSED_STATUSES for o in _opp_rows)
    _pipe_first = role_decisions + decide_rows
    pipe_clause = (_clause(_pipe_first[0][0]) if _pipe_first
                   else ("A sourcing-channel review is due." if due_reviews_ws
                         else "No decision is owed on a role."))
    pipe_parts = []
    if now_ws or decide_rows or n_pipe_flight or opp_alive_hint:
        pipe_parts.append(
            '<h2 id="phase-pipeline-now">⚡ Decisions &amp; actions waiting on you '
            '<span class="tcount">%d</span></h2>'
            '<div class="ym-card"><div class="ym-head">Nothing here moves without you</div>'
            '<div class="ws">%s</div></div>'
            % (len(now_ws),
               render_ws(now_ws, "`data/opportunities.jsonl` and `data/asks.jsonl`",
                         "Nothing is waiting on you right now.")))
    if decide_rows:
        pipe_parts.append(
            '<h2 id="phase-pipeline-decide">🔎 Decide — pursue or pass '
            '<span class="tcount">%d</span></h2>'
            '<div class="sub" style="margin:-6px 0 10px">Sourced roles whose verdict is '
            'still <code>undecided</code>. A decision owed to you is listed from the '
            'moment the record exists — the act-by date is a deadline, not a reveal date. '
            'Deciding moves the record and the row leaves by itself.</div>'
            '<div class="card">%s</div>'
            % (len(decide_rows), render_ws(decide_ws, "`data/opportunities.jsonl`", "")))
    if due_reviews_ws:
        pipe_parts.append(
            '<h2 id="phase-pipeline-reviews">🧭 Channel reviews due '
            '<span class="tcount">%d</span></h2>'
            '<div class="card">%s</div>'
            % (len(due_reviews_ws),
               render_ws(due_reviews_ws, "`data/channels.jsonl` (channels_due.py)", "")))
    pipe_parts.append(your_move_callouts_html)
    if pipe_flight_ws:
        pipe_parts.append(
            '<div class="inflight"><h2 id="phase-pipeline-flight">⏳ In flight — not '
            'yours to do <span class="tcount">%d</span></h2>'
            '<div class="card">%s</div></div>'
            % (n_pipe_flight,
               render_ws(pipe_flight_ws, "`data/opportunities.jsonl`", "")))
    opp_list_html, opp_counts = render_opportunity_list(_opp_rows, _opp_comps)
    if opp_counts["all"]:
        pipe_parts.append(
            '<h2 id="phase-pipeline-roles">🎯 Opportunities — where each role stands</h2>'
            '<div class="sub" style="margin:-6px 0 10px"><strong>What lives here:</strong> '
            'every live role, once — waiting-on-you first. The bar under each title is the '
            'pipeline stage it has actually reached.</div>'
            + stats_html +
            f'<input type="radio" name="oppf" id="of-all" class="oppfilter" checked>'
            f'<input type="radio" name="oppf" id="of-you" class="oppfilter">'
            f'<input type="radio" name="oppf" id="of-app" class="oppfilter">'
            f'<input type="radio" name="oppf" id="of-per" class="oppfilter">'
            f'<input type="radio" name="oppf" id="of-non" class="oppfilter">'
            '<div class="oppbar">'
            f'<label for="of-all">All ({opp_counts["all"]})</label>'
            f'<label for="of-you">Waiting on you ({opp_counts["you"]})</label>'
            f'<label for="of-app">Applied ({opp_counts["applied"]})</label>'
            f'<label for="of-per">In play through a person ({opp_counts["person"]})</label>'
            f'<label for="of-non">Nothing sent ({opp_counts["nothing"]})</label>'
            '</div>'
            f'<div class="card opp-list">{opp_list_html}</div>'
            '<div class="note"><strong>Only &ldquo;nothing sent&rdquo; is a gap.</strong> '
            'Applied and in-play-through-a-person are both covered; a role carried with '
            'nothing sent is the hole.</div>')
    if _src_active or _src_retired:
        pipe_parts.append(
            '<h2 id="phase-pipeline-sourcing">🧭 Sourcing — Active channels '
            '<span class="tcount">%d due</span></h2>'
            '<div class="card">%s</div>'
            '<h2 id="phase-pipeline-sourcing-retired">Retired channels '
            '<span class="tcount">%d</span></h2>'
            '<div class="card">%s</div>'
            % (n_sourcing_due, sourcing_active_html,
               len(_src_retired), sourcing_retired_html))
    if _kbs:
        pipe_parts.append(
            '<h2 id="phase-pipeline-kb">🏢 Company knowledge base '
            '<span class="tcount">%d</span></h2>'
            '<div class="card">%s</div>' % (len(_kbs), kbs_html))
    pipe_subs = [("role decisions", "phase-pipeline-now")]
    if decide_rows:
        pipe_subs.append(("pursue/pass", "phase-pipeline-decide"))
    if due_reviews_ws:
        pipe_subs.append(("channel reviews", "phase-pipeline-reviews"))
    _emit("pipeline", n_pipe_needs, n_pipe_flight, pipe_clause, pipe_subs, pipe_parts)

    # ── applying ───────────────────────────────────────────────────────────
    apply_ws = []
    for o in _apply_q:
        comp = _opp_comps.get(o.get("company_id"), {})
        apply_ws.append(ws_row("<strong>%s — %s</strong>"
                               % (esc(comp.get("name", o.get("company_id", ""))),
                                  esc(o.get("title") or "")), "you", "",
                               o.get("next_action_date") or ""))
    submitted_ws = [ws_row("<strong>%s — %s</strong>" % (esc(r[0]), esc(r[1])),
                           r[4], r[3], "")
                    for r in _submitted]
    if _apply_q:
        _q0 = _apply_q[0]
        _q0name = _opp_comps.get(_q0.get("company_id"), {}).get(
            "name", _q0.get("company_id", ""))
        apply_clause = ("%s — work the queue in session (views/applying.md)."
                        % _clause("%s — %s" % (_q0name, _q0.get("title") or "")))
    else:
        apply_clause = "Nothing queued to apply."
    apply_parts = []
    if apply_ws:
        apply_parts.append(
            '<h2 id="phase-applying-queue">📝 Queued to apply '
            '<span class="tcount">%d</span></h2>'
            '<div class="sub" style="margin:-6px 0 10px">Working happens in session — '
            '<code class="fileref">views/applying.md</code> is the worksheet; this is the '
            'queue.</div>'
            '<div class="card">%s</div>'
            % (len(apply_ws), render_ws(apply_ws, "`views/applying.md`", "")))
    if submitted_ws:
        apply_parts.append(
            '<div class="inflight"><h2 id="phase-applying-inflight">⏳ Submitted — '
            'awaiting a response <span class="tcount">%d</span></h2>'
            '<div class="card">%s</div></div>'
            % (len(submitted_ws),
               render_ws(submitted_ws, "`data/opportunities.jsonl`", "")))
    if _nothing and (apply_ws or submitted_ws):
        apply_parts.append(
            '<div class="sub">%d live role%s carried with nothing sent — the real gap; '
            'each is flagged on its row in the pipeline section.</div>'
            % (len(_nothing), "" if len(_nothing) == 1 else "s"))
    _emit("applying", len(apply_ws), len(submitted_ws), apply_clause,
          [("apply queue", "phase-applying-queue")] if apply_ws else [], apply_parts)

    # ── conversations ──────────────────────────────────────────────────────
    _today_iso = datetime.date.today().isoformat()
    _commits = load_jsonl("commitments.jsonl")
    # Commitment states — unplaceable dates AND preps owed — come from conversations.py's
    # one resolver (which itself resolves prep existence through knowledge.prep_hits, the
    # dev #153 single predicate). A second derivation here would disagree with it later,
    # the same reason the applying row imports applying.queue.
    import conversations as _conversations
    conv_needs = []
    conv_owed = []
    try:
        _conv_rows = _conversations.report(str(ROOT))
    except Exception as _e:
        # ⚠️ A failed scan must NEVER read as "no prep owed" — that is the missing-reads-
        # as-empty trap. Zero counts with a loud line on the console, and the
        # unresolved-date marker still derives from the store directly below.
        print("  !! WARNING: conversations scan failed (%s) — the conversations row "
              "cannot count preps owed; run conversations.py" % _e)
        _conv_rows = None
    if _conv_rows is None:
        for c in _commits:
            if str(c.get("date")) == "unresolved":
                # The migration marker: an unreadable date is an UNKNOWN, never a pass.
                conv_needs.append(ws_row(
                    "<strong>⚠️ %s</strong> — date is the migration marker "
                    "<code>unresolved</code>: verify the real date (invite "
                    "<code>.ics</code>, never recall) and set it on the record"
                    % md_inline(c.get("title") or c.get("id") or "?"),
                    "you", "", "unresolved", loud=True))
    else:
        for r in _conv_rows:
            if r["state"].endswith("-date"):
                # Unplaceable: the migration marker, or a date nobody can read — an
                # UNKNOWN, never a pass.
                conv_needs.append(ws_row(
                    "<strong>⚠️ %s</strong> — %s"
                    % (md_inline(r.get("title") or r.get("id") or "?"), esc(r["why"])),
                    "you", "", r.get("date") or "unresolved", loud=True))
            elif r["state"] in _conversations.NEEDS_YOU:
                _due = r.get("date") or ""
                if r.get("time"):
                    _due += " %s" % r["time"]
                conv_owed.append(ws_row(
                    "<strong>⛔ %s</strong> — %s"
                    % (md_inline(r.get("title") or r.get("id") or "?"), esc(r["why"])),
                    r.get("who") or "you", "", _due, loud=True))
    conv_flight = []

    def _placed_future(r):
        # An unplaceable date is an UNKNOWN, never a pass — and never an in-flight row
        # either. The old lexical compare let a non-ISO date string that happened to sort
        # above today ("next Tuesday" >= "2026-…") render as an ordinary scheduled
        # commitment while the needs-you list was simultaneously calling it unreadable.
        try:
            return datetime.date.fromisoformat(str(r.get("date"))) >= \
                datetime.date.fromisoformat(_today_iso)
        except ValueError:
            return False

    for c in sorted((r for r in _commits if _placed_future(r)),
                    key=lambda r: (str(r.get("date")), str(r.get("time") or ""))):
        due = str(c.get("date"))
        if c.get("time"):
            due += " %s" % c["time"]
        conv_flight.append(ws_row("<strong>%s</strong>"
                                  % md_inline(c.get("title") or c.get("id") or "?"),
                                  c.get("who") or "", "", due))
    if _conv_rows is None:
        # ⚠️ Mirrors the trigger-scan-failure idiom below (out_clause / the "Trigger scan
        # failed" note) — the same defect, the same fix. A failed scan must never present
        # as "Nothing scheduled" or a quiet zero; the clause itself must say UNKNOWN.
        conv_clause = ("⛔ conversations scan failed — prep-owed counts are UNKNOWN, not "
                       "zero; run conversations.py")
    else:
        conv_clause = ("%s — %s" % (_clause(re.sub(r"<[^>]+>", "",
                                                   conv_flight[0]["item"])),
                                    conv_flight[0]["due"])
                       if conv_flight else "Nothing scheduled.")
        if conv_owed:
            conv_clause = ("%d prep%s owed (call-prep) · %s"
                           % (len(conv_owed), "" if len(conv_owed) == 1 else "s", conv_clause))
    conv_parts = []
    if _conv_rows is None:
        # dev/audit 2026-08-29, item 2 — the S5 phone reader never sees stdout, so the
        # WARNING printed above (conversations scan failed) must ALSO land on the page,
        # in this section, or a scan failure renders as an ordinary (not-visibly-broken)
        # page with a possibly-wrong quiet-zero preps-owed count. This banner must appear
        # regardless of whether conv_owed happens to be empty — it is the thing that
        # distinguishes "scan failed, cannot know" from "zero owed".
        conv_parts.append(
            '<div class="note">⛔ <strong>Conversations scan failed</strong> — prep-owed '
            'counts on this page are UNKNOWN, not zero (conversations.report() raised). '
            'Run <code>conversations.py</code> to see the full traceback, fix it, and '
            'regenerate before trusting a zero here.</div>')
    if conv_owed:
        conv_parts.append(
            '<h2 id="phase-conversations-owed">⛔ Preps owed — before the call '
            '<span class="tcount">%d</span></h2>'
            '<div class="sub" style="margin:-6px 0 10px">Writing happens in session — the '
            '<code>call-prep</code> skill drains every row here; a row stands until '
            '<code>conversations.py</code> reports the note complete (a partial, '
            'records-only note never satisfies the predicate).</div>'
            '<div class="card">%s</div>'
            % (len(conv_owed), render_ws(conv_owed, "`views/conversations.md`", "")))
    if conv_needs:
        conv_parts.append(
            '<h2 id="phase-conversations-unresolved">⚠️ Commitments with unresolved '
            'dates <span class="tcount">%d</span></h2>'
            '<div class="card">%s</div>'
            % (len(conv_needs), render_ws(conv_needs, "`data/commitments.jsonl`", "")))
    if conv_flight:
        conv_parts.append(
            '<h2 id="phase-conversations-week">📅 This week — calls &amp; deadlines '
            '<span class="tcount">%d</span></h2>'
            '<div class="card">%s</div>'
            '<div class="note"><strong>Meeting times are verified from the invite&rsquo;s '
            '<code>.ics</code>, not from recall.</strong> A calendar receipt only proves '
            'what was booked when it was sent — confirm anything that may have been '
            'rescheduled (<code>parse_ics.py</code>).</div>'
            % (len(conv_flight),
               render_ws(conv_flight, "`data/commitments.jsonl`", "")))
    if _preps:
        conv_parts.append(
            '<h2 id="phase-conversations-preps">📞 Call preps — in full '
            '<span class="tcount">%d</span></h2>'
            '<div class="sub" style="margin:-6px 0 10px">The one knowledge type that '
            'renders in full here (public #20: a prep must be readable the night before, '
            'anywhere) — bounded by upcoming-call volume.</div>'
            '<div class="card">%s</div>' % (len(_preps), preps_full_html))
    _emit("conversations", len(conv_needs) + len(conv_owed), len(conv_flight), conv_clause,
          ([("preps owed", "phase-conversations-owed")] if conv_owed else [])
          + ([("unresolved dates", "phase-conversations-unresolved")] if conv_needs else []),
          conv_parts)

    # ── outreach ───────────────────────────────────────────────────────────
    n_approvals = len(_sendable) + len(_covers_ready)
    touch_ws = [ws_row("<strong>%s</strong> — %s" % (md_inline(t), esc(_clause(a))),
                       "you", "", "")
                for t, a, _oid in channel_touches]
    untrig_ws = [ws_row("<strong>%s</strong> — application has no follow-up linked"
                        % esc(r.get("title") or r.get("opp_id") or "?"),
                        r.get("status") or "", _age_days(r.get("date")), "")
                 for r in _untrig_rows]
    n_out_needs = n_approvals + _n_unblocked + len(untrig_ws) + len(touch_ws)
    n_out_flight = n_blocked + n_covers_held + _n_waiting_seqs
    if _trep is None:
        out_clause = ("⛔ trigger scan failed — sequence and follow-up counts are "
                      "UNKNOWN, not zero; run trigger.py --check")
    else:
        bits = []
        if n_approvals:
            bits.append("%d message%s await%s approval"
                        % (n_approvals, "" if n_approvals == 1 else "s",
                           "s" if n_approvals == 1 else ""))
        if _n_unblocked:
            bits.append("%d sequence%s unblocked"
                        % (_n_unblocked, "" if _n_unblocked == 1 else "s"))
        if untrig_ws:
            bits.append("%d application%s with no follow-up linked"
                        % (len(untrig_ws), "" if len(untrig_ws) == 1 else "s"))
        if touch_ws:
            bits.append("%d relationship follow-up%s due"
                        % (len(touch_ws), "" if len(touch_ws) == 1 else "s"))
        out_clause = (bits[0] + "." if bits else "Nothing staged or owed.")
    out_parts = [your_move_ready_html]
    if _sendable:
        out_parts.append(
            '<h2 id="phase-outreach-approvals">✉️ Pending drafts — awaiting your approval '
            '<span class="tcount">%d</span></h2>'
            '<div class="sub" style="margin:-6px 0 10px">Nothing is ever sent without your '
            'explicit approval. The full text of every sendable message is right here — read '
            'it on this page, never off a transcript.</div>'
            '<div class="card">%s</div>'
            '<div class="card">%s</div>'
            % (len(_sendable), drafts_html, drafts_bodies_html))
    if n_blocked:
        out_parts.append(
            '<div class="inflight"><h2 id="phase-outreach-blocked">⏳ Waiting on someone '
            'else <span class="tcount">%d</span></h2>'
            '<div class="sub" style="margin:-6px 0 10px">Written and ready, but blocked '
            'until the other person acts. <strong>Not yours to do</strong> — each moves up '
            'by itself once the precondition is met.</div>'
            '<div class="card">%s</div></div>' % (n_blocked, blocked_html))
    if _covers_ready:
        out_parts.append(
            '<h2 id="phase-outreach-covers">📄 Cover letters — for applications you submit '
            'yourself <span class="tcount">%d</span></h2>'
            '<div class="sub" style="margin:-6px 0 10px">Every claim traces to the claim '
            'union (presence/claims.md). You paste and submit these yourself — nothing is '
            'applied on your behalf.</div>'
            '<div class="card">%s</div>'
            '<div class="card">%s</div>'
            % (len(_covers_ready), covers_html, covers_bodies_html))
    if n_covers_held:
        out_parts.append(
            '<div class="inflight"><h2 id="phase-outreach-covers-held">⏳ Cover letters '
            'held — do not submit yet <span class="tcount">%d</span></h2>'
            '<div class="card">%s</div></div>' % (n_covers_held, covers_held_html))
    if touch_ws:
        out_parts.append(
            '<h2 id="phase-outreach-touches">🤝 Relationship follow-ups due '
            '<span class="tcount">%d</span></h2>'
            '<div class="card">%s</div>'
            % (len(touch_ws), render_ws(touch_ws, "`data/channels.jsonl`", "")))
    if _trep is None:
        out_parts.append(
            '<div class="note">⛔ <strong>Trigger scan failed</strong> — sequence and '
            'follow-up counts on this page are UNKNOWN, not zero. Run '
            '<code>trigger.py --check</code>.</div>')
    elif _n_unblocked or untrig_ws or _n_waiting_seqs:
        seq_bits = []
        if _n_unblocked:
            seq_bits.append("%d unblocked — the next step is sendable" % _n_unblocked)
        if _n_waiting_seqs:
            seq_bits.append("%d waiting on a trigger" % _n_waiting_seqs)
        out_parts.append(
            '<h2 id="phase-outreach-seq">⏱ Follow-up sequences'
            + ((' <span class="tcount">%d</span>' % (_n_unblocked + _n_waiting_seqs))
               if (_n_unblocked or _n_waiting_seqs) else "")
            + '</h2>'
            + (('<div class="sub" style="margin:-6px 0 10px">%s (trigger.py owns the '
                'derivation).</div>' % esc("; ".join(seq_bits))) if seq_bits else "")
            + (('<div class="card">%s</div>'
                % render_ws(untrig_ws, "`trigger.py --check`", "")) if untrig_ws else ""))
    out_subs = [("approvals", "phase-outreach-approvals")]
    if touch_ws:
        out_subs.append(("follow-ups", "phase-outreach-touches"))
    if _n_unblocked or untrig_ws:
        out_subs.append(("sequences", "phase-outreach-seq"))
    _emit("outreach", n_out_needs, n_out_flight, out_clause, out_subs, out_parts)

    # ── Assemble the ONE page. ─────────────────────────────────────────────
    # %-d is a glibc/BSD strftime extension; on Windows it raises ValueError and kills the
    # dashboard at the last step. Build the day number by hand (same fix as parse_ics.py).
    _t = datetime.date.today()
    today = "%s %d, %d" % (_t.strftime("%B"), _t.day, _t.year)
    _title = _dashboard_title()

    n_needs_total = sum(s[1] for s in _summaries)
    router_html = render_router_rows(_summaries)

    body_inner = (
        '<h1>%s</h1>\n'
        # ⭐ The generated-date line stays PROMINENT: for the dashboard-only reader it is
        # the ONLY staleness signal there is (deployment.md, the S5 read leg).
        '<div class="updated">Generated <strong>%s</strong> · %d item%s need%s you · '
        'the phase name in each row jumps to its section · generated by '
        'scripts/generate_dashboard.py</div>\n'
        '%s\n%s\n'
        '<div class="sub" style="margin-top:26px">Not on this page: the network '
        '(queried in session — <code class="fileref">data/channels.jsonl</code>, '
        '<code class="fileref">%s</code>), archives, sent and closed items, and knowledge '
        'bodies — counts above, files in the tree.</div>'
        % (html.escape(_title), today, n_needs_total,
           "" if n_needs_total == 1 else "s", "s" if n_needs_total == 1 else "",
           router_html, "\n".join(_sections), esc(_tree.rel("network"))))

    # ── The outputs: the ONE artifact and the constant tombstone. ──────────
    (ROOT / "views").mkdir(exist_ok=True)
    artifact_doc = ('<title>%s</title>\n<style>%s</style>\n%s'
                    % (html.escape(_title), CSS, body_inner))
    (ROOT / "views" / "dashboard_artifact.html").write_text(artifact_doc, encoding="utf-8")
    (ROOT / "dashboard.html").write_text(DASHBOARD_TOMBSTONE, encoding="utf-8")

    print("Wrote views/dashboard_artifact.html (%d bytes) and the dashboard.html "
          "tombstone (%d bytes)"
          % (len(artifact_doc.encode("utf-8")), len(DASHBOARD_TOMBSTONE)))
    print("  publish: ONE artifact — views/dashboard_artifact.html, to the URL in "
          "views/dashboard_artifact_url.txt (the router and phase pages are RETIRED — "
          "2026-08-29 collapse). If that url file is absent, check "
          "check_dashboard_fresh.py --publish-state FIRST: never-published (no stamp "
          "either) means create it on first publish; url-missing (a stamp already exists) "
          "means RECOVER the URL via the Artifact tool's list action, never mint a new one")
    print("  " + " · ".join("%s %d/%d" % (p, n, f)
                             for p, n, f, _c, _h in _summaries)
          + "  (needs-you/in-flight per phase)")
    try:
        import pending_stubs as _stubs
        _pend = [r for r in _stubs.load_rows(str(ROOT))
                 if r.get("state") in ("pending", "failed", "unresolved")]
        if _pend:
            print("  ⚠️ %d retired page URL(s) still await their moved-stub publish — "
                  "run scripts/pending_stubs.py" % len(_pend))
    except Exception:
        pass


if __name__ == "__main__":
    main()
