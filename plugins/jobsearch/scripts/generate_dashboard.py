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
  (nothing at the profile root)       ⭐ dev #546 / public #126 — this script used to
                                     also write a constant TOMBSTONE STUB to a root
                                     `dashboard.html` on every run. It no longer
                                     writes anything outside `views/`. The stub was a
                                     transitional redirect for the old habit path
                                     (dev #233); rewriting it unconditionally forever
                                     made deleting it futile, kept a retired artifact
                                     alive by the very engine that retired it, and
                                     told every NEW profile its "local copy is
                                     retired" when that profile never had one. The
                                     rulebook's own rule is that retirement is a MOVE
                                     to archive/retired-trackers/, never a note, so
                                     the stub is now retired the way everything else
                                     is: `_tree.RETIRED_TO` names it and
                                     `migrate.m_0_56_0_retire_dashboard_tombstone`
                                     moves the one a profile already has.

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
import hashlib
import html
import json
import re
import os
from pathlib import Path

import os, sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _root import profile_root as _profile_root
import _tree
import profile as _profile
import your_move as _ym
import applications as _apps
import touches as _touches
import validate_data as _vd
import applying as _applying
import knowledge as _kn
import precondition as _pre
import channels_due as _cd
import conversations as _conv_mod
import config_keys as _ck
import warm_path as _warm_path                                   # dev #751: the warm-path next action
# ⭐ THE ONE DEFINITION OF "CURRENT" — resume_variants.py owns union_hash (the canonicalized,
# line-ending/trailing-space/trailing-newline-insensitive stamp `--stamp` writes onto
# union_sha). This file used to recompute a RAW sha256 of the union's bytes, which agreed with
# the real stamp only when the claims file happened to have no trailing newline — so on an
# ordinary file (one that ends with a newline, or has trailing space, or CRLF endings) every
# active variant read STALE here even seconds after `--stamp` (public #74). Same move as
# `_TERMINAL` above: import the one answer rather than re-derive it and drift.
import resume_variants as _resume_variants
# ⭐ THE ONE TERMINAL SET — validate_data's, by import. This file used to carry its own
# `_CLOSED_STATUSES = {passed, backlog, expired}`, which dropped every backlog row as closed
# while your_move.py treated backlog+undecided as the state a sourced role STARTS in and
# this file's own sort key ranked backlog as live. Measured on a real profile: most backlog
# rows appeared NOWHERE on the page — not even in a "+K more" remainder — and the missing
# JD links were those same rows. A per-file "closed" set names what a file wants to hide; a
# shared terminal set names what has ended (dev/audit 2026-09-02, build item 1).
_TERMINAL = _vd.TERMINAL_OPP_STATUSES

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


def _collapse_words_n():
    """`config_keys.DASHBOARD_BODY_COLLAPSE_WORDS`, read the same defensive way
    `_dashboard_title()` reads `config.json` above — an unreadable file falls back to the
    registered default rather than crashing dashboard generation over a formatting knob."""
    import json as _json
    cfg = {}
    try:
        with open(os.path.join(_profile_root(), "config.json"), encoding="utf-8") as fh:
            cfg = _json.load(fh)
    except Exception:
        pass
    value, _prov = _ck.describe(cfg, _ck.DASHBOARD_BODY_COLLAPSE_WORDS)
    return value

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


# ─────────────────────────────────────────────────────────────────────────────
# ⭐ ONE PRIMARY ROW PER RECORD, AND A LINK TO IT (dev #496 / public #48, dev #540 / public
# #132, design-one-dashboard-surface.md r3 §2). A record has ONE primary row, in its kind's one
# list: it carries `data-rec="<kind>:<id>"` and `id="rec-<h>"`. Anywhere else the record is
# mentioned, the mention is a REFERENCE row: `data-ref="<kind>:<id>"` plus an `<a href=
# "#rec-<h>">` to the primary. `check_dashboard_coverage.py` refuses a second `data-rec` for
# one key (EXACTLY ONCE), a `data-ref` whose primary is not on the page (LINKED) and any
# `href="#x"` with no `id="x"` (ANCHOR). `<h>` is the first 12 hex digits of sha1(key): a draft
# title has spaces and is not unique, so it cannot be the id (design D5), and the same key
# (see `your_move.entry_keys`) is the ledger's, `data-rec`'s, the id's and every `data-ref`'s.
# ─────────────────────────────────────────────────────────────────────────────

def rec_id(key: str) -> str:
    """The HTML id of the primary row for `key` (`opp:x`, `draft:Title#2`, ...)."""
    return "rec-" + hashlib.sha1(str(key).encode("utf-8")).hexdigest()[:12]


def links_for(key: str) -> str:
    """ADR-024's LINKED side, named in r2 §4 and built here: the in-page href of a record's
    primary row. The row's `:target` reveal rule (`.flist [data-rec]:target`) makes the link
    land even when the row's own filter would hide it."""
    return "#" + rec_id(key)


def _rec_attrs(key: str) -> str:
    """` id="rec-…" data-rec="…"` - the primary row's attributes, id FIRST so the checker's
    `data-rec="…" data-full="1"` pairing is untouched."""
    return ' id="%s" data-rec="%s"' % (rec_id(key), esc(key))


def _ref_attrs(key: str) -> str:
    return ' data-ref="%s"' % esc(key)


def _ref_link(key: str, text: str = "the full row ↓") -> str:
    return '<a class="ref" href="%s">%s</a>' % (links_for(key), esc(text))


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


def opp_bucket(o, involvements=()):
    """The one COVERAGE bucket this role belongs to — applying.coverage's, by import. The
    three values were this file's own until public #48 stage 1 made coverage a declared
    filter dimension, and a dimension's vocabulary must have an owner outside the renderer
    (the `_CLOSED_STATUSES` lesson at the top of this file). `involvements` — ADR-031 B1 —
    is the global `involvements.jsonl` rows; optional, so a caller with none yet still gets
    the outreach-or-nothing half of the answer rather than crashing."""
    return _applying.coverage(o, involvements)


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
    # ADR-031 B2 — o["_applications"] is the caller's join against the top-level applications
    # store (applications.enrich_opportunities, called once in load_jsonl above), never a
    # nested array on the record.
    apps = o.get("_applications") or []
    if apps:
        rows = []
        for a in apps:
            when = esc(str(a.get("applied_on") or a.get("date") or "date unrecorded"))
            how = esc(str(a.get("method") or "application"))
            # `cover_letter_id` is the FK to the cover_letters store (was the free-text
            # `cover_letter` field before B2) — "recorded" now means "linked", not "non-empty".
            cl = "cover letter recorded" if a.get("cover_letter_id") else "cover letter unrecorded"
            rows.append(f"<li>{when} — {how} · {cl}</li>")
        out.append('<div class="od-h">Applications</div><ul class="od-l">'
                   + "".join(rows) + "</ul>")
    # ADR-031 B3 — o["_touches"], the caller's join against the top-level touches store
    # (touches.enrich_opportunities, called once in load_jsonl above), never a nested array.
    tou = o.get("_touches") or []
    if tou:
        rows = []
        for t in tou:
            when = esc(str(t.get("sent_on") or t.get("date") or "date unrecorded"))
            who = esc(str(t.get("to") or t.get("person_id") or "recipient unrecorded"))
            med = esc(str(t.get("medium") or ""))
            res = t.get("outcome") or "no reply yet"
            rows.append(f"<li>{when} — {who}{' · ' + med if med else ''} · {esc(str(res))}</li>")
        out.append('<div class="od-h">Outreach</div><ul class="od-l">'
                   + "".join(rows) + "</ul>")
    return "".join(out)


# The fixed shape of render_opportunity_list's counts dict — see dev #80 in that function's
# docstring for why this has to be a single shared constant rather than two literals.
_EMPTY_OPP_COUNTS = {"all": 0, "you": 0, "applied": 0, "person": 0, "nothing": 0}

# The opportunity list's TWO filter dimensions — every vocabulary imported from the module
# that owns it. dev #494 / public #58 and dev #540 / public #132 (design-one-dashboard-
# surface.md r3 §3.1): the bar used to offer four engine vocabularies - `state`
# (ATTENTION), `owner`, `stage` (validate_data.STAGES) and `coverage` (applying.COVERAGE) -
# and the reporter measured two of them degenerate (every one of 74 live rows `in-flight`)
# and two more as one population in two spellings (`coverage: nothing` and `stage: sourced`
# are the same rows). `pursuit` is the ONE primary dimension, in the user's words, a
# projection of workflow_state (your_move.pursuit_state); `owner` stays as the second
# (public #54: "which of these is mine" is a question the reader asks). `stage` is the
# row's RAIL (stage_rail), `ATTENTION` stays the router's number and the reading order's first
# tier, `applying.COVERAGE` stays `opp_bucket`'s: only their CHIPS went. The renderer
# declares which dimensions exist; it never declares what their values may be.
OPP_DIMS = (("pursuit", "your_move.PURSUIT_STATES", tuple(_ym.PURSUIT_STATES)),
            ("owner", "your_move.OWNER", _ym.OWNER))


def pursuit_by_id(opps, roles=None):
    """{opp id: your_move.pursuit_state dict} for every opportunity in `opps` that carries an
    id - the ONE map the opportunity list's `pursuit` chips, its row chips, the reading
    order and the router's `applying` count all read, so the label population and the router
    number are one query. Reads the stores through the enriched `_applications` join, never a
    nested array.

    ⭐ dev #713 / public #145 (owner decision 2026-10-14): a role the run is still reading is not
    the candidate's decision ANYWHERE on the page. `pursuit_state` projects it as `new` (it is an
    undecided role), but only the role classification knows it is unread, so a `new` role whose
    `roles` state (`classify_opportunities`) is `triaging` is moved to the `triaging` partition
    option here: it is counted and shown under `Triaging`, and `New` neither lists nor counts it.
    `roles` is {opp id: role state}, derived from `opps` when the caller passes none."""
    if roles is None:
        roles = {o.get("id"): st for o, st, _w in _ym.classify_opportunities(opps, OWNER_TOKEN)
                 if o.get("id")}
    out = {}
    for o in opps:
        if not o.get("id"):
            continue
        p = _ym.pursuit_state(str(ROOT), o, o.get("_applications") or [])
        if p.get("state") == "new" and roles.get(o["id"]) == "triaging":
            p = dict(p, state="triaging", cell="triaging")
        out[o["id"]] = p
    return out


def _days_since(iso, today=None):
    """Whole days from an ISO date to today, or None for anything unreadable or in the
    future - an unknown age is never invented as zero (`_age_days`' rule, as a number)."""
    try:
        d = datetime.date(*map(int, str(iso)[:10].split("-")))
        n = ((today or datetime.date.today()) - d).days
        return n if n >= 0 else None
    except Exception:                                       # noqa: BLE001
        return None


def _pursuit_chip(p):
    """The row's own pursuit chip - the SAME words as the bar's option (one table behind both:
    `_FILTER_VALUE_LABELS`), with the finer cell or cause beside it. A row the engine could
    not classify is LOUD and names the field."""
    state = p.get("state")
    label = _FILTER_VALUE_LABELS.get(("pursuit", state), state)
    if state == "unclassifiable":
        return (' <span class="chip action" title="the pursuit state could not be derived">'
                'unclassifiable — %s missing</span>' % esc(str(p.get("missing") or "a field")))
    if state == "ended" and p.get("ended_because"):
        label = "Ended — %s" % p["ended_because"]
    return ' <span class="chip pursuit" title="%s">%s</span>' % (
        esc(str(p.get("cell") or "")), esc(label))


WARM_PATH_NOTES = {
    "ready": "after you decide",
    "draft-owed": "draft owed",
    "drafted": "draft ready for you to send",
    "touched": None,           # "asked <date>"
    "lookup-owed": None,       # a link / a search to open
    "looked-none": None,       # "looked <date>, none found"
}


def _warm_html(a):
    """dev #751 (W3) -- ONE line on a role card: the warm-path next action `warm_path.py` derived for it,
    never composed here. `data-warm` carries the state so `check_dashboard_coverage.py` can hold the page
    to it (a derived action whose card lacks the line, or shows a different state, is a gap). A lookup is a
    LINK the candidate opens, only when a LinkedIn company URL is already on record; nothing here sends,
    connects or messages anyone."""
    if not a:
        return ""
    who = esc(a.get("person_name") or a.get("person_id") or "")
    kind = {"referral-ask": "referral ask to", "hm-note": "note to the hiring manager"}.get(a["kind"], "")
    st = a["state"]
    if st == "lookup-owed":
        if a.get("linkedin_url"):
            text = ('no one known: <a href="%s" target="_blank" rel="noopener">look up on LinkedIn '
                    '&#8599;</a>, then record who you found' % esc(a["linkedin_url"]))
        else:
            text = "no one known: search LinkedIn for people there, then record who you found"
    elif st == "looked-none":
        text = "looked %s, none found" % esc(a.get("on") or "?")
    elif st == "touched":
        text = "%s %s (asked %s)" % (kind, who, esc(a.get("on") or "?"))
    else:
        text = "%s %s (%s)" % (kind, who, WARM_PATH_NOTES[st])
    return '<div class="opp-warm" data-warm="%s">Warm path: %s</div>' % (esc(st), text)


def _lean_html(o, role_state):
    """The row-level triage line (dev #713 / public #145): a `decide` row shows the LEAN and the
    likely-pass signals that matched; a `triaging` row names what the system has yet to do.
    Everything comes from your_move.py (`decide_lean`, `triage_missing`) - this only renders.
    A lean is a lean: it never removes a role, and the line says `LEAN`, not a verdict."""
    if role_state == "decide":
        ln = _ym.decide_lean(o)
        if not ln:
            return ""
        sigs = "".join(
            ' <span class="lean-sig" title="a likely-pass signal matched; it never removes a '
            'role">%s</span>' % esc("%s (in %s)" % (s.get("reason") or s.get("id") or "signal",
                                                    s.get("matched_in") or "?"))
            for s in ln["signals"])
        return ('<div class="opp-lean"><strong>LEAN %s</strong> · %s%s</div>'
                % (esc(ln["lean"]), esc(ln["line"]), sigs))
    if role_state == "triaging":
        return ('<div class="opp-lean opp-triaging">Triaging &mdash; the system is reading '
                'this before it asks you. Still to do: %s</div>'
                % esc(", ".join(_ym.triage_missing(o))))
    return ""


def render_opportunity_list(opps, companies, attention=None, owner=None, involvements=None,
                            pursuit=None, roles=None, set_name="opportunities", warm=None):
    """One row per LIVE role — needs-you first, then yours, then the run's — inside a
    FILTERED LIST over OPP_DIMS, EVERY member rendered. Closed roles are not here — they
    are not opportunities.

    ⭐ public #54 — NEVER CAPPED. 0.37.0 trimmed this list to WORKING_SET_CAP rows and
    the ledger counted the rest in a "+K more" remainder, which satisfied the coverage
    contract while three candidate-owned rows appeared on no part of the page: a
    filtered list is narrowed by CSS visibility over ONE rendered row set, so a row the
    cap trims is reachable under NO filter state, and a chip counting it promises a row
    that selecting the chip cannot show (public #58 point 3). Sort-then-cap's guarantee —
    "the cap trims only the tail" — is false the moment more than one ordering is
    offered: the cap trims by one order while the chips slice by four others. The reading
    order still matters (it is what the reader meets first), so the tiers are the two
    ownership answers in precedence: ATTENTION's needs-you, then OWNER's you, then the
    rest. See ADR-024's REACHABLE side; the cap stays for UNFILTERED sets (render_ws
    without dims, the queues, the indexes), where one ordering is the only ordering.

    ⭐ public #48, stage 1 — "in flight" is a filter value here, not a section. The
    `⏳ In flight — not yours to do` list rendered every live role not in the needs-you
    queue a SECOND time (and a third, when a callout held it too); the owner called it
    noise and asked for the filter instead. `attention` is your_move.attention_by_id's
    map; the router's pipeline in-flight count reads the same map, so the label
    population and the router number are one query. `owner` is your_move.owner_by_id's
    map — derived here from OWNER_TOKEN when the caller passes none, never re-derived
    from the field by this file.

    ⭐ dev #80 — the counts dict has a FIXED shape (all/you/applied/person/nothing) because
    main() indexes every key unconditionally. The empty-live case used to return `{}` for
    it, which crashed main() with a KeyError — and the profile most likely to have zero
    live opportunities is a brand-new one, so the dashboard's first-ever render was the
    crash. `_EMPTY_OPP_COUNTS` is the one place that shape is written down, shared by both
    the empty-case return and the populated-case starting value, so they cannot drift apart.

    ⭐ dev #494 / public #58, dev #540 / public #132 (design r3 §3) - the bar is `pursuit`
    (your_move.pursuit_state, a projection of workflow_state) and `owner`; the reading order
    is whose move it is, then DAYS SINCE ANYTHING LAST HAPPENED (stalest first within a tier:
    the longer a role has sat, the sooner it needs a look). `pursuit` is
    {opp id: pursuit_state dict}, derived here when the caller passes none, never re-derived
    from the fields by this file. Each row's `data-pursuit` is its ONE partition token and
    `data-pursuit-also="your-move"` marks the cross-cut (ATTENTION's needs-you): a row can be
    both `New` and `Your move`, which one radio value could not say.

    ⭐ dev #751 -- `warm` is `{opp id: warm_path action}` (`warm_path.derive`, keyed by every role an
    action covers): each card carries ONE `Warm path:` line, rendered by `_warm_html`, and the coverage check
    recomputes the actions and holds the card to them.

    Returns (html, counts): html is the whole filtered list — controls, the `.flist` of
    rows, and the remainder line OUTSIDE it (never hidden by any filter state).
    """
    attention = attention or {}
    owner = owner if owner is not None else _ym.owner_by_id(opps, OWNER_TOKEN)
    # dev #713 / public #145 (R4): `roles` is {opp id: your_move role state}, the same
    # classify_opportunities the router and the callouts read; derived here when the caller
    # passes none, never from the status and verdict fields.
    roles = roles if roles is not None else {
        o.get("id"): st for o, st, _w in _ym.classify_opportunities(opps, OWNER_TOKEN)
        if o.get("id")}
    # ADR-031 B1 — involvements[], not opportunities.contacts[] any more (retired). Loaded
    # here, not passed by every caller, for the same reason `owner`'s default is derived here:
    # a caller with no opinion about it should not have to know it exists.
    involvements = involvements if involvements is not None else load_jsonl("involvements.jsonl")
    live = [o for o in opps if o.get("status") not in _TERMINAL]
    for o in opps:
        if o.get("status") in _TERMINAL and o.get("id"):
            _cover("opp:%s" % o["id"], "terminal", set_name)
    if not live:
        return '<div class="sub">No live opportunities.</div>', dict(_EMPTY_OPP_COUNTS)
    order = {"active-pursuit": 0, "needs-resolution": 1, "in-motion": 2, "backlog": 3}
    if pursuit is None:
        pursuit = pursuit_by_id(live, roles)

    # ADR-031 B4 (design §19) — `play_stage`/`next_action` are retired; the row's position
    # and "what's next" are now DERIVED from the play engine, every render. The shared
    # Context (`_play_context()`) is reused across every row in this list, and every other
    # function in this file that needs one.
    _play_ctx = _play_context()
    _today_iso = datetime.date.today().isoformat()

    def key(o):
        # Whose move it is, in precedence: needs the candidate today, then the candidate's
        # (dated out, or outside Your Move's membership), then the run's. The second tier is
        # the one 0.37.0 dropped (public #54): a row that is yours must never read as the
        # run's just because it is not today's.
        oid = o.get("id")
        tier = (0 if attention.get(oid) == "needs-you"
                else 1 if owner.get(oid) == "you" else 2)
        # ... then days since anything last happened, stalest first; an UNKNOWN age sorts after
        # every known one (it is never invented as zero).
        days = _days_since((pursuit.get(oid) or {}).get("last_activity_on"))
        return (tier, 0 if days is not None else 1, -(days or 0),
                order.get(o.get("status"), 9),
                -(STAGES.index(o["stage"]) if o.get("stage") in STAGES else -1),
                str(oid or ""))

    counts = dict(_EMPTY_OPP_COUNTS)
    rows, members = [], {}
    for o in sorted(live, key=key):
        comp = companies.get(o.get("company_id"), {})
        bucket = opp_bucket(o, involvements)
        waits = owner.get(o.get("id")) == "you"
        counts["all"] += 1
        counts[bucket] += 1
        if waits:
            counts["you"] += 1

        # ADR-031 B4 (design §19) — the play position, DERIVED, on the row itself.
        _ns = _play_next_step(o, _play_ctx, _today_iso)
        if _ns.kind == "stalled":
            play_html = '<span class="play-unres">play: stalled — %s</span>' % esc(_ns.why or "")
        elif _ns.kind == "step":
            play_html = esc("play: " + (_ns.step or "?"))
        elif _ns.kind not in ("no-plan", "no-play"):
            play_html = esc("play: " + _ns.kind)
        else:
            play_html = ""
        meta = " · ".join(x for x in (
            _fmt_loc(o.get("location")), _fmt_comp(o.get("comp")),
            esc(str(o.get("channel_id") or "").replace("firm:", "via ")) or "",
            play_html) if x)
        action_full = ""
        label = _play_step_label(_ns)
        if label:
            due = _ns.due
            who = "you" if waits else "the run"
            text = label
            flat = re.sub(r"[*`]+", "", text)
            if len(flat) > OPP_ACTION_CLAMP:
                teaser = flat[:OPP_ACTION_CLAMP].rsplit(" ", 1)[0].rstrip(" ,;:—-") + "…"
                action_full = text
            else:
                teaser = flat
            nxt = (f'<div class="opp-next{" opp-next-you" if waits else ""}">'
                   f'<span class="opp-arrow">→</span> {esc(teaser)} '
                   f'<span class="opp-owner">{who}{" · due " + esc(str(due)) if due else ""}</span></div>')
        elif _ns.kind == "waiting":
            nxt = ('<div class="opp-next">waiting until %s — %s</div>'
                  % (esc(str(_ns.until or "?")), esc(_ns.why or "")))
        elif _ns.kind == "goal-reached":
            nxt = '<div class="opp-next">goal reached</div>'
        elif _ns.kind == "manual":
            nxt = '<div class="opp-next">manual play — the owner decides each step</div>'
        else:
            # ⚠️ Named, not omitted. A role with no next step is a decision nobody has made,
            # and an empty space reads as "handled".
            nxt = ('<div class="opp-next opp-next-none">%s</div>'
                  % esc(_ns.why or "No next step derived"))

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

        _key = "opp:%s" % (o.get("id") or "")
        _p = pursuit.get(o.get("id")) or {"state": "unclassifiable", "missing": "pursuit"}
        dims = {"pursuit": _p["state"], "owner": owner.get(o.get("id"))}
        # The cross-cuts (your_move.PURSUIT_CROSS_CUTS): a row carries each one it is in, space-
        # separated. `your-move` is ATTENTION's needs-you and `decide` the role state of that name
        # (dev #713) - a decide row is also a your-move row. `triaging` is NOT a cross-cut: it is a
        # partition value (`pursuit_by_id`), so a triaging row is in `Triaging` and not in `New`.
        also = [cc for cc, on in (("your-move", attention.get(o.get("id")) == "needs-you"),
                                  ("decide", roles.get(o.get("id")) == "decide")) if on]
        if also:
            dims["pursuit-also"] = " ".join(also)
        if o.get("id"):
            members[_key] = dims
        rows.append((o.get("id"),
            f'<div class="opp"{_rec_attrs(_key)}{_dim_attrs(dims)}>'
            f'  <div class="opp-head">'
            f'    <div class="opp-title">{esc(str(o.get("title") or "Untitled role"))}'
            f'      <span class="opp-co">{esc(comp.get("name", o.get("company_id", "")))}</span>'
            f'      {jd}{_pursuit_chip(_p)}</div>'
            f'    <div class="opp-rail">{stage_rail(o)}</div>'
            f'  </div>'
            f'  <div class="opp-meta">{meta}</div>'
            f'  {_lean_html(o, roles.get(o.get("id")))}{nxt}{_warm_html((warm or {}).get(o.get("id")))}{body}'
            f'</div>'))
    # REACHABLE (ADR-024, public #54): every member renders; a filtered list has no remainder.
    keys = ["opp:%s" % i for i, _h in rows if i]
    _cover_set(set_name, keys, [])
    html_out = render_filtered_list(set_name, OPP_DIMS, members, keys,
                                    "".join(h for _i, h in rows), "", cls="card opp-list")
    return html_out, counts


def render_your_move(items, links=None, cap=None, more_at=None, set_name=None,
                      store="data/opportunities.jsonl", ref=False) -> str:
    """The numbered ask list (callout groups, Ready-to-send). Since the one-artifact
    collapse it takes the same cap every working set takes: items are already ordered
    soonest-first before they arrive here, so the cap trims only the tail, and the remainder is
    counted and located rather than silently absent.

    §4.3 / dev #486 (public #107 part 2): the `ym-ask` body is NON-sendable free text (a
    `why`/derived ask line, never the draft the candidate sends) so it routes through
    `_clause_cell` exactly like every other working-set body — clause, then `_collapse_over`'s
    full-under-`<details>`-or-collapsed-pointer split. `store` is this call's own source file
    for the locator; a per-item id (`item[2]`, already carried for `data-rec`) narrows it to
    that record when present.

    ⭐ `ref=True` (dev #540 / public #132, design r3 §2 - EXACTLY ONCE): the rows are REFERENCES to
    a record whose primary row lives in its kind's list (the Opportunities list, for a callout
    about a role), so each carries `data-ref="opp:<id>"` and a link to `#rec-…`, NEVER a second
    `data-rec`, and is not a coverage placement: the remainder is still counted (the page
    says "+K more" and the ledger agrees) but the shown rows claim nothing."""
    if not items:
        return '<div class="sub">Nothing is waiting on you right now.</div>'
    cap = cap if cap is not None else WORKING_SET_CAP
    shown, rest = items[:cap], items[cap:]
    if set_name:
        _cover_set(set_name,
                   [] if ref else ["opp:%s" % it[2] for it in shown if len(it) > 2 and it[2]],
                   ["opp:%s" % it[2] for it in rest if len(it) > 2 and it[2]])
    more = ""
    if rest:
        more = ('<div class="sub ws-more"%s>+%d more — every one is still counted in the '
                'heading; the full set lives in %s.</div>'
                % ((' data-more="%s:%d"' % (esc(set_name), len(rest))) if set_name else "",
                   len(rest), md_inline(more_at or "the operating store (`data/`)")))
    items = shown
    links = links or {}
    parts = []
    for n, item in enumerate(items, 1):
        t, w = item[0], item[1]
        opp_id = item[2] if len(item) > 2 else None
        link = links.get(opp_id) if opp_id else None
        jd_html = (f' <a class="ym-jd" href="{link}" target="_blank" rel="noopener">JD ↗</a>'
                   if link else '')
        key = ("opp:%s" % opp_id) if opp_id else None
        rec_attr = ((_ref_attrs(key) if ref else _rec_attrs(key)) if key else "")
        if ref and key:
            jd_html += " " + _ref_link(key, "the role ↓")
        locator = ("%s · %s" % (store, opp_id)) if opp_id else store
        parts.append(
            f'<div class="ym-item"{rec_attr}><div class="ym-num">{n}</div><div>'
            f'<div class="ym-title">{md_inline(t)}{jd_html}</div>'
            f'<div class="ym-ask">{_clause_cell(w, locator)}</div></div></div>')
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
        _cover("prep:%s" % rel, "rendered", "preps")
        out.append('<details class="kdoc"%s data-full="1"><summary><strong>%s'
                   '</strong> <code class="fileref">%s</code></summary>'
                   '<div class="kdoc-body">%s</div></details>'
                   % (_rec_attrs("prep:%s" % rel), md_inline(title), esc(rel), inner))
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


# The staged pair's filter dimensions (public #48, stage 1). Sendability is
# precondition.OPEN_STATES — the states an entry can be in while still queued; medium is
# validate_data.MEDIA, read off the entry's own `**Medium:**` line by precondition.medium_of.
# Cover letters carry sendability only (a letter is pasted into a form, not sent on a medium).
# dev #539 / public #133 (design r3 §4): the staged drafts list is the FOLLOW-UP VIEW - drafts
# are its primary rows, and every other subject owing a message is a reference row. `when` is the
# new first dimension (default `now`); `sendability` keeps its name and gains `undrafted` (a
# reference has no draft yet); `medium` is unchanged. Both new vocabularies are
# your_move.outreach_due's, never this file's.
DRAFT_DIMS = (("when", "your_move.OUTREACH_WHEN", _ym.OUTREACH_WHEN),
              ("sendability", "your_move.OUTREACH_SENDABILITY", _ym.OUTREACH_SENDABILITY),
              ("medium", "validate_data.MEDIA", tuple(sorted(_vd.MEDIA))))
COVER_DIMS = (("sendability", "precondition.OPEN_STATES", tuple(sorted(_pre.OPEN_STATES))),)

# ⭐ Query or Citation C1 (design-query-or-citation.md §3.5, D8) — six states join these three
# dicts, in their own three-way class split: `unaddressed`/`unbriefed`/`brief-mismatch`/
# `stale-brief` are NEEDS_HUMAN (chip class "action", same as `unresolved`/`unreadable`
# already render); `unverified-cold`/`unverified-silent` are WAITS_ON_SURFACE — a THIRD chip
# class, "queued", neither "waiting" (on the other side) nor "action" (on the owner): the
# draft waits on a session with a keychain. The mirror gate in TestQueryOrCitationC1 below
# asserts every state in `precondition.OPEN_STATES` is present in all three dicts, so a
# seventh state added to one and not the others fails loudly instead of rendering muted.
_SEND_ORDER = {"sendable": 0, "unreadable": 1, "unresolved": 1, "blocked": 2,
              "unaddressed": 1, "unbriefed": 1, "brief-mismatch": 1, "stale-brief": 1,
              "unverified-cold": 3, "unverified-silent": 3}
_SEND_CHIP = {"sendable": ("scheduled", "ready"), "blocked": ("waiting", "held"),
              "unresolved": ("action", "unresolved"), "unreadable": ("action", "unreadable"),
              "unaddressed": ("action", "unaddressed"), "unbriefed": ("action", "unbriefed"),
              "brief-mismatch": ("action", "brief mismatch"),
              "stale-brief": ("action", "stale brief"),
              "unverified-cold": ("queued", "queued — cold unverified"),
              "unverified-silent": ("queued", "queued — silence unverified")}
_SEND_WHERE = {
    "sendable": "full text below — expand it and read it here, never off a transcript",
    "blocked": "held — waits on the other side; moves to ready by itself once the touch "
               "outcome flips",
    "unresolved": "needs YOU — rewrite the **Blocked until:** line as contact:<id> "
                  "outcome:<...>; nobody can say what this waits on",
    "unreadable": "needs YOU — rewrite the **Blocked until:** line as contact:<id> "
                  "outcome:<...>; the strict parser refuses it",
    "unaddressed": "needs YOU — no recipient identified; add a **To:** contact:<id> line",
    "unbriefed": "needs YOU — drafted without reading the thread; run "
                "brief.py --rebrief",
    "brief-mismatch": "needs YOU — the cited brief names someone else; rebrief this entry",
    "stale-brief": "needs YOU — they wrote since this was drafted; rebrief, or redraft if "
                  "the register moved",
    "unverified-cold": "queued for a keychain-holding session — the mailbox has not been "
                       "checked on this surface",
    "unverified-silent": "queued for a keychain-holding session — a sweep must cover this "
                         "thread first",
}


# ─────────────────────────────────────────────────────────────────────────────
# ⭐ "COPY AS PROMPT" - OWNER REQUEST 2026-10-13 (design r3 "Owner request 2026-10-13: Copy as
# prompt"; the vendor pattern *Bring the result back to your session*). Each DRAFT row carries a
# button that copies a paste-ready instruction for the user's jobsearch session: the draft's ONE
# key (the D5 key every `data-rec`, ledger record and `apply_correction.py` address uses), its
# title and ordinal, its current sent text quoted, and a `Correction:` line to fill in. Pasted in
# chat, it is the coordinator's "Apply review comments" input (`--source chat`).
#
# THE PAGE'S ONE SCRIPT. It only copies text that is already on the page: no network, no
# storage, no state. `navigator.clipboard.writeText` is called inside the click handler; on a
# rejection, or with no clipboard API (a sandboxed frame), the row's own textarea is shown and
# selected with a "Press Cmd/Ctrl+C" hint. With scripts off the button is inert and the page
# still reads completely: the draft's text is on the row already. check_dashboard_coverage.py's
# SCRIPT gap allows exactly this script (by its marker) and refuses any other.
# ─────────────────────────────────────────────────────────────────────────────
COPY_SCRIPT_MARKER = 'data-dashboard-script="copy-as-prompt"'
COPY_SCRIPT = ("<script %s>\n" % COPY_SCRIPT_MARKER) + r"""(function () {
  function fallback(box, ta) {
    ta.hidden = false; ta.focus(); ta.select();
    var h = box.querySelector('.cap-hint'); if (h) { h.hidden = false; }
  }
  document.addEventListener('click', function (e) {
    var b = e.target && e.target.closest ? e.target.closest('button.cap-btn') : null;
    if (!b) { return; }
    var box = b.parentNode, ta = box.querySelector('textarea.cap-text');
    if (!ta) { return; }
    var text = ta.value;
    function done() {
      var was = b.textContent; b.textContent = 'Copied';
      setTimeout(function () { b.textContent = was; }, 1500);
    }
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, function () { fallback(box, ta); });
        return;
      }
    } catch (err) { /* fall through to the manual copy */ }
    fallback(box, ta);
  });
})();
</script>"""


def draft_ordinal(key, title):
    """The 1-based ordinal of a draft among entries of the same title, read back from its D5 key
    (`your_move.entry_keys`: `draft:<title>` for the first, `draft:<title>#<n>` for the nth) -
    the `--ordinal` `apply_correction.py` takes."""
    rest = key.split(":", 1)[1] if ":" in key else key
    if rest != title and rest.startswith(title + "#") and rest[len(title) + 1:].isdigit():
        return int(rest[len(title) + 1:])
    return 1


def copy_prompt_text(key, title, blocks, filename="outreach/drafts.md"):
    """The paste-ready instruction a draft row's "Copy as prompt" button copies. It names the
    draft's key, title and ordinal, quotes its current SENT text (the `>` blocks, the only text
    apply_correction.py edits) and ends with the line the user fills in."""
    quoted = []
    for kind, val in blocks:
        if kind != "quote":
            continue
        if quoted:
            quoted.append(">")
        paras = [p for p in val if p.strip()]
        for i, p in enumerate(paras):
            if i:
                quoted.append(">")
            quoted.extend("> " + ln for ln in p.split("\n"))
    n = draft_ordinal(key, title)
    return "\n".join(
        ["Apply a correction to one of my staged drafts (copied from the dashboard).",
         "Draft key: %s" % key,
         "Title: %s" % title,
         "Ordinal: %d (among entries titled exactly this, in %s order)" % (n, filename),
         "Use the Apply review comments step: apply_correction.py --draft %s --ordinal %d "
         "--source chat, dry run first, show me the diff." % (json.dumps(title), n),
         "Current text:"]
        + (quoted or ["> (this draft has no quoted text yet)"])
        + ["Correction: <describe the change here>"])


def render_copy_as_prompt(key, title, blocks, filename):
    """The button, its hidden textarea (the fallback the script selects) and the hint. Both the
    attribute and the textarea are escaped with quotes, so no title can close either."""
    return ('<div class="cap"><button type="button" class="cap-btn" data-cap-key="%s">'
            'Copy as prompt</button>'
            '<span class="cap-hint sub" hidden>Press Cmd/Ctrl+C to copy, then paste it in your '
            'session.</span>'
            '<textarea class="cap-text" readonly hidden rows="6">%s</textarea></div>'
            % (html.escape(key, quote=True),
               html.escape(copy_prompt_text(key, title, blocks, filename), quote=True)))


def render_message_list(set_name, kind, entries, states, filename, dims, empty_msg, keys=None,
                        whens=None, refs=None):
    """ONE list per file of the staged pair (public #48, stage 1): every OPEN entry — never
    a terminal one (public #29) — as a row carrying its precondition state chip, its meta
    line, where its full text lives, and the full body inline and collapsed — for EVERY open
    entry, not only a sendable one (dev #686 / public #139, rule 1b: a draft that is held,
    unaddressed or queued is still a message the owner has to read to act on it, and was a
    chip with no text). The body IS the decision being asked for, so it stays on the page (the
    collapse's one exception); a non-sendable entry's summary names its state so it cannot be
    mistaken for a ready one; everything else stays an index row.

    This replaces four surfaces that were the same entries under different headings:
    "Pending drafts" (index card + a second bodies card), "⏳ Waiting on someone else",
    "⏳ Cover letters held", and "⛔ Holds nobody can read". Their DISTINCTIONS survive as
    the sendability filter and as loudness on the row — an unreadable hold is still an
    `action` chip on a loud row, still counted needs-you by main() (public #37) — but an
    entry now renders in exactly one place.

    Ordered sendable → needs-you holds → blocked — the reading order. NEVER CAPPED: a
    filtered list renders every member (ADR-024 REACHABLE, public #54); the open set is
    bounded by what is actually pending, since sent and moot entries are terminal.

    ⭐ dev #496 / public #48, design r3 D5 - THE KEY IS UNIQUE. `keys` is aligned with
    `entries` and comes from `your_move.entry_keys` (the title for the first entry of that
    title, `<title>#<n>` for the nth): two same-titled entries used to share one `data-rec`,
    one ledger record and one state row, so the second was invisible to the checker or a false
    EXACTLY ONCE gap. `states` is keyed `(filename, key)`. A caller that passes no `keys`
    (a direct unit call) gets the title-only keys the old shape had.

    ⭐ dev #539 / public #133 (design r3 §4) - `whens` is {key: when} from
    `your_move.outreach_due` (a draft is `waiting` when held or queued; else `now`) and `refs`
    its reference rows: each other subject that owes a message (a relationship touch, an
    application with no follow-up, a person due) is a `data-ref` row IN THIS LIST with the same
    dimension attributes, a link to its primary row elsewhere, and `sendability: undrafted`.
    A reference carries no body (the 1b floor is about drafts) and no ledger placement."""
    if not entries and not refs:
        return '<div class="sub">%s</div>' % empty_msg
    dim_names = [d for d, _src, _v in dims]
    if keys is None:
        keys = ["%s:%s" % (kind, t) for t, _b in entries]
    pairs = list(zip(entries, keys))

    def _st(key):
        return (states.get((filename, key)) or {}).get("state") or "sendable"

    pairs.sort(key=lambda pk: _SEND_ORDER.get(_st(pk[1]), 9))
    entries = [e for e, _k in pairs]
    keys = [k for _e, k in pairs]
    _cover_set(set_name, keys, [])
    members, out = {}, []
    for (title, blocks), key in zip(entries, keys):
        row = states.get((filename, key)) or {}
        st = row.get("state") or "sendable"
        dims_here = {"sendability": st}
        if "when" in dim_names:
            dims_here["when"] = (whens or {}).get(key) or _ym.outreach_when_for_draft(st)
        if "medium" in dim_names:
            dims_here["medium"] = row.get("medium") or "unknown"
        members[key] = dims_here
    # Query or Citation C1 (plant 10) — a queued row names the deferred item that will clear
    # it, read once here rather than per row. `deferred.py`'s own queue, never re-derived.
    _queued_by_contact = {}
    if any(dims["sendability"] in ("unverified-cold", "unverified-silent")
          for dims in members.values()):
        try:
            import deferred as _deferred_mod
            for r in _deferred_mod.replay(_deferred_mod.load()):
                if r.get("status") != "pending":
                    continue
                m_id = re.search(r"contact:(\S+)", str(r.get("what") or ""))
                if m_id:
                    _queued_by_contact[m_id.group(1)] = r.get("id")
        except Exception:                                    # noqa: BLE001 — advisory only
            pass
    for (title, blocks), key in zip(entries, keys):
        dims_here = members[key]
        st = dims_here["sendability"]
        cls, label = _SEND_CHIP.get(st, ("waiting", st))
        loud = st in _pre.NEEDS_HUMAN
        meta = _draft_meta_summary(blocks)
        queued_note = ""
        if st in ("unverified-cold", "unverified-silent"):
            m_to = re.search(r"To:\s*contact:(\S+)", meta)
            act_id = _queued_by_contact.get(m_to.group(1)) if m_to else None
            if act_id:
                queued_note = " · queued: %s" % act_id
        medium_flag = ""
        if dims_here.get("medium") == "unknown":
            # Loud on the row: the line named no MEDIA value (or there is no line). The
            # filter files it under `unknown` — MEDIA's own word for this — never a guess.
            medium_flag = (' <span class="chip action" title="the **Medium:** line names no '
                           'validate_data.MEDIA value">medium: unknown</span>')
        # dev #686 / public #139, rule 1b — the body renders for every open state; only the
        # <summary> differs, naming the state the row's chip already shows. `entries` holds
        # open entries only (terminal ones are filtered before this function).
        summary = "full text" if st == "sendable" else "full text — %s, not sendable" % label
        body = ('<details class="kdoc"><summary>%s</summary>'
                '<div class="kdoc-body">%s</div></details>'
                % (esc(summary), render_draft_entries([(title, blocks)], "")))
        # OWNER REQUEST 2026-10-13 - "Copy as prompt", on a DRAFT row only (never a cover
        # letter, never a reference row).
        if kind == "draft":
            body += render_copy_as_prompt(key, title, blocks, filename)
        out.append(
            '<div class="draft%s"%s%s><div class="draft-title">%s '
            '<span class="chip %s">%s</span>%s</div>'
            '%s%s'
            '<div class="sub">%s › %s · %s%s</div></div>'
            % (" ws-loud" if loud else "", _rec_attrs(key), _dim_attrs(dims_here),
               md_inline(title), cls, label, medium_flag,
               ('<div class="draft-meta">%s</div>' % esc(meta)) if meta else "", body,
               '<code class="fileref">%s</code>' % esc(filename), esc(title[:60]),
               md_inline(_SEND_WHERE.get(st, st)), esc(queued_note)))
    ref_members, ref_rows = {}, []
    for rf in sorted(refs or [], key=lambda r: (_ym.OUTREACH_WHEN.index(r["when"]),
                                                str(r.get("due") or "9999"), r["key"])):
        d = {"sendability": "undrafted"}
        if "when" in dim_names:
            d["when"] = rf["when"]
        if "medium" in dim_names:
            d["medium"] = "unknown"
        if rf.get("primary"):
            # jobsearch 0.71.0 (dev #750): the subject's own row is no longer on this page (a channel
            # or an in-flight role lives in the jobsearch panel), so this row IS its primary row here -
            # `data-rec`, placed RENDERED in this list - and points at the panel instead of a link to
            # nothing. "Touches due" are primary Drafts-to-review rows (design section 4).
            members[rf["key"]] = d
            keys.append(rf["key"])
            _cover(rf["key"], "rendered", set_name)
            ref_rows.append(
                '<div class="draft draft-ref"%s%s><div class="draft-title">%s '
                '<span class="chip action">no draft yet</span></div>'
                '<div class="sub">%s%s · its full row is in the jobsearch panel '
                '(<code>/jobsearch:status</code>)</div></div>'
                % (_rec_attrs(rf["key"]), _dim_attrs(d), md_inline(rf["label"]), esc(rf["why"]),
                   (" · due %s" % esc(str(rf["due"]))) if rf.get("due") else ""))
            continue
        ref_members[rf["key"]] = d
        go = {"chan": "the channel ↓", "opp": "the role ↓", "person": "the person ↓"}.get(
            rf["kind"], "the full row ↓")
        ref_rows.append(
            '<div class="draft draft-ref"%s%s><div class="draft-title">%s '
            '<span class="chip action">no draft yet</span></div>'
            '<div class="sub">%s%s · %s</div></div>'
            % (_ref_attrs(rf["key"]), _dim_attrs(d), md_inline(rf["label"]), esc(rf["why"]),
               (" · due %s" % esc(str(rf["due"]))) if rf.get("due") else "",
               _ref_link(rf["key"], go)))
    return render_filtered_list(set_name, dims, members, keys, "".join(out) + "".join(ref_rows),
                                "", cls="", refs=ref_members)


def render_people_due(root, today):
    """dev #686 / public #139 (E1) — the NETWORK VIEW: people with NO opportunity who are due.

    `your_move.network_people_due` is the ONE membership definition (it wraps
    `classify_people`, the one owner of people-due, and drops anyone a pursuit already
    carries); this renders its rows and computes nothing of its own. Each due row is
    `data-rec="person:<id>"`: name, the state chip, and classify_people's own `why`. One sub
    line counts the person-only people still `fresh` within their cadence, so a relationship
    that is not due is acknowledged rather than silently absent. Returns (html, n_listed);
    empty HTML when there is nothing to say (no due person and no fresh one), so a profile
    with no cadence set sees no change to its page.

    Every listed person is placed in the coverage ledger as RENDERED (`people-due`), and
    `check_dashboard_coverage.py` expects exactly this membership, so a due person the page
    forgot is a GAP, not a silence."""
    try:
        net = _ym.network_people_due(str(root), today)
    except Exception:                                        # noqa: BLE001 — never takes the page down
        return "", 0
    due, n_fresh = net["due"], net["fresh"]
    if not due and not n_fresh:
        return "", 0
    out = []
    for person, state, why in due:
        key = "person:%s" % person.get("id")
        _cover(key, "rendered", "people-due")
        out.append('<div class="draft"%s><div class="draft-title">%s '
                   '<span class="chip %s">%s</span></div><div class="sub">%s</div></div>'
                   % (_rec_attrs(key), md_inline(person.get("name") or person.get("id") or "?"),
                      "action" if state == "due" else "waiting", esc(state), esc(why)))
    if not out:
        out.append('<div class="sub">No one is due.</div>')
    if n_fresh:
        out.append('<div class="sub">%d other relationship%s with no opportunity %s within '
                   'cadence.</div>' % (n_fresh, "" if n_fresh == 1 else "s",
                                       "is" if n_fresh == 1 else "are"))
    return ('<h2 id="phase-outreach-people">👥 People due <span class="tcount">%d</span></h2>'
            '<div class="sub" style="margin:-6px 0 10px">People you keep in touch with who are '
            'not tied to a role — from each person\'s own cadence.</div>'
            '<div class="card">%s</div>' % (len(due), "".join(out))), len(due)


def render_knowledge_index(docs, empty_msg, where, cap=None, rec_kind=None, chip=""):
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
    if rec_kind:
        _cover_set(rec_kind, ["%s:%s" % (rec_kind, r) for _t, r, _b in shown],
                   ["%s:%s" % (rec_kind, r) for _t, r, _b in rest])
    out = []
    for title, rel, body in shown:
        words = len(body.split())
        flag = "" if body.strip() else (' <span class="chip action">empty — nothing '
                                        'written yet</span>')
        rec_attr = _rec_attrs("%s:%s" % (rec_kind, rel)) if rec_kind else ""
        out.append('<div class="draft"%s><div class="draft-title">%s%s%s</div>'
                   '<div class="sub"><code class="fileref">%s</code> · %d words · %s'
                   '</div></div>'
                   % (rec_attr, md_inline(title), flag, chip, esc(rel), words, esc(where)))
    if rest:
        out.append('<div class="sub ws-more"%s>+%d more files — the count above is complete; '
                   'browse the directory in the file tree.</div>'
                   % ((' data-more="%s:%d"' % (esc(rec_kind), len(rest))) if rec_kind else "",
                      len(rest)))
    return "".join(out)


PREP_DIMS = (("window", "knowledge.PREP_WINDOWS", _kn.PREP_WINDOWS),)
WEEK_DIMS = (("prep", "conversations.PREP_STATES", _conv_mod.PREP_STATES),)
_PREP_WHERE = {
    "past": "call held — archive_preps.py moves it to archive/call-preps/",
    "later": "beyond the %d-day horizon — renders in full when the call is near",
    "undated": "⚠️ filename carries no call_prep_<date> — cannot be windowed; rename a prep "
               "call_prep_<date>.md, or move a non-prep note to the store it belongs in "
               "(archive_preps.py names each)",
}
_PREP_CHIP = {"past": ' <span class="chip">past</span>',
              "later": ' <span class="chip">later</span>',
              "undated": ' <span class="chip action">undated</span>'}


def render_prep_index(docs, horizon_days):
    """The call preps NOT rendered in full — held calls, calls beyond the horizon, and
    notes nothing can date — as ONE filtered index (public #48, stage 1) over
    knowledge.PREP_WINDOWS, instead of three index sections each with its own cap and
    its own overwrite of the `prep` remainder count. `docs` is [(title, rel, body,
    window)], already ordered; bodies stay in the file tree (the collapse). NEVER
    CAPPED — a filtered list renders every member (ADR-024 REACHABLE, public #54); the
    index is bounded because archive_preps.py moves past calls out of the working set."""
    if not docs:
        return ""
    keys = ["prep:%s" % r for _t, r, _b, _w in docs]
    _cover_set("prep", keys, [])
    members = {k: {"window": w} for k, (_t, _r, _b, w) in zip(keys, docs)}
    out = []
    for (title, rel, body, window), key in zip(docs, keys):
        words = len(body.split())
        flag = "" if body.strip() else (' <span class="chip action">empty — nothing '
                                        'written yet</span>')
        where = _PREP_WHERE[window]
        if window == "later":
            where = where % horizon_days
        out.append('<div class="draft"%s%s><div class="draft-title">%s%s%s</div>'
                   '<div class="sub"><code class="fileref">%s</code> · %d words · %s'
                   '</div></div>'
                   % (_rec_attrs(key), _dim_attrs(members[key]), md_inline(title), flag,
                      _PREP_CHIP[window], esc(rel), words, esc(where)))
    return render_filtered_list("prep", PREP_DIMS, members, keys, "".join(out), "", cls="")


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
#
# ⚠️ UNFILTERED SETS ONLY (public #54, ADR-024 REACHABLE). The volume-independence
# argument above rests on ONE ordering: sorted first, the cap trims the tail of that
# order. A FILTERED list offers several orderings at once — every chip is a slice — and
# a row the cap trims by the sort is reachable under no chip, while the chip's population
# count still promises it. So a filtered list (render_filtered_list) never takes this cap;
# its bound is the reader's own narrowing. Measured cost on the profile that reported the
# regression: ~4 KB per opportunity row, 74 rows, so the page grows by roughly the size it
# was — a cost stated, not hidden, and the row's weight (the Detail block) is stage 2's.
WORKING_SET_CAP = 20

_CLAUSE_CLAMP = 110  # same bound OPP_ACTION_CLAMP uses, for the same measured reason


def _clause(text):
    """ONE clause of prose, maximum — the single next action. `next_action` fields are
    measured to be memos (median 419 chars); a router row carries the verdict and the
    stores carry the memo. Sentence-shaped rows are the defect the owner rejected twice.

    ⭐⭐ THE COMPOSED-STRING RULE (dev/audit 2026-09-02, build item 2). A renderer clamps
    the SOURCE FIELD, then composes — it never parses a string it built itself. `_clause`
    takes a field, never a composition. The measured defect: `_role_ask` returned
    `"<comp> · <location>. <next_action>"` and the row builder then ran `_clause` over that
    composition, which cut at the FIRST ". " — the one this file had just inserted — so on
    every role row carrying context, the action itself was gone from the page (most role
    rows on the profile measured). The same shape bit the decide rows ("Decide: pursue or
    pass — …" cut at its own " — "), the channel rows ("Due <date>. <note>") and the
    applying clause ("<company> — <title>" cut to the company). Every caller now clamps
    each field it owns and joins the clamped parts; nothing downstream re-clauses."""
    flat = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", str(text or ""))
    flat = re.sub(r"[*`]+", "", flat).strip()
    for sep in (". ", "; ", " — "):
        i = flat.find(sep)
        if 0 < i < _CLAUSE_CLAMP:
            return flat[:i].rstrip(" ,;:")
    if len(flat) > _CLAUSE_CLAMP:
        return flat[:_CLAUSE_CLAMP].rsplit(" ", 1)[0].rstrip(" ,;:—-") + "…"
    return flat


def _flat(text):
    """The field as plain prose (markdown links and emphasis stripped) — what `_clause`
    clamps, exposed so a caller can tell whether the clause IS the whole field."""
    flat = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", str(text or ""))
    return re.sub(r"[*`]+", "", flat).strip()


def _collapse_over(text, n, locator):
    """design-script-first.md §4.3 (dev #486 / public #107 part 2, revising public #31/#46) —
    the ONE place a NON-SENDABLE free-text body decides between "full, collapsed under
    `<details>`" and "clause + word count + locator, no full text at all". Never called for a
    sendable body — that is the ONE exception (public #46's own ruling: the body IS the decision
    being asked for), and `render_message_list`'s own sendable path stays its separate,
    unconditional "always full" branch rather than routing through here at all. Returns the
    HTML to APPEND after the clause (`_clause_cell`'s own shape) — never the clause itself, so a
    caller that already has its own clause text keeps using it."""
    flat = _flat(text)
    words = flat.split()
    if len(words) <= n:
        if _clause(text) == flat:
            return ""
        return ('<details class="ws-full"><summary>full</summary>'
                '<div class="ws-full-body">%s</div></details>' % md_inline(text))
    # Over N: the full text is NEVER emitted — not even inside a collapsed <details> — because
    # a reader-facing "absent from the page" is the whole point (public #46's complaint was a
    # truncation with nowhere to go; the locator is the somewhere, per §4.3).
    return (' <span class="ws-collapsed">%d words · <code class="fileref">%s</code></span>'
           % (len(words), esc(locator)))


def _clause_cell(text, locator=None):
    """public #31, revised by #46, revised again by §4.3 (dev #486 / public #107 part 2): the
    row shows ONE clause of the SOURCE FIELD, and the rest of the body follows the §4.3 rule —
    full and collapsed under `<details>` when the body is at or under
    `config_keys.DASHBOARD_BODY_COLLAPSE_WORDS`, clause + word count + `locator` when over it.
    `locator` is the store's own `<code class="fileref">` pointer (e.g.
    `data/asks.jsonl · ask-20260916-03`) — REQUIRED whenever the body can plausibly exceed the
    threshold; a caller with no real locator to offer is a caller that should not be showing an
    unbounded body at all. Returns HTML."""
    clause = _clause(text)
    cell = esc(clause)
    cell += _collapse_over(text, _collapse_words_n(), locator or "")
    return cell


# ─────────────────────────────────────────────────────────────────────────────
# ⭐ THE COVERAGE LEDGER — Class C (dev/audit 2026-09-02). Every record in the four
# row-backed stores (opportunities, asks, commitments, call preps) is placed here as it
# renders: RENDERED (a row on the page carries `data-rec="<key>"`), REMAINDER (it is inside
# a "+K more" line whose K counts it, `data-more="<set>:<K>"` — a disposition only an
# UNFILTERED set may use, since public #54: counted is not reachable, and a filtered list
# renders every member), or TERMINAL (it has ended and the page says so by omission).
# Anything in none of those is a record the page lost
# silently — the exact shape of the backlog defect above. The ledger is written beside
# the artifact (views/dashboard_coverage.json) and `check_dashboard_coverage.py` verifies
# it AGAINST THE HTML, never trusting the ledger alone (verify the artifact, not the plan).
# Separate from check_dashboard_fresh.py on purpose: freshness is bytes and stamps; this is
# membership, and one check must not grow a second meaning.
# ─────────────────────────────────────────────────────────────────────────────
COVERAGE = {"records": {}, "remainders": {}}
# `elsewhere` (jobsearch 0.71.0, amending ADR-024): the record is not on this page BY DESIGN and lives
# in a named home (`where` is the home: panel, review-resume or review-linkedin). It ranks lowest, so a
# record that is rendered, counted in a remainder or terminal keeps that placement.
_DISP_RANK = {"rendered": 3, "remainder": 2, "terminal": 1, "elsewhere": 0}


def _cover(key, disposition, where):
    """Place one record. A record rendered anywhere is RENDERED even if another set
    trimmed it into a remainder — the strongest placement wins."""
    cur = COVERAGE["records"].get(key)
    if cur is None or _DISP_RANK[disposition] > _DISP_RANK[cur["disposition"]]:
        COVERAGE["records"][key] = {"disposition": disposition, "where": where}


def _cover_set(set_name, shown_keys, rest_keys):
    """One capped set: what it showed and what it trimmed into its remainder."""
    for k in shown_keys:
        if k:
            _cover(k, "rendered", set_name)
    for k in rest_keys:
        if k:
            _cover(k, "remainder", set_name)
    if rest_keys:
        COVERAGE["remainders"][set_name] = len(rest_keys)


# ─────────────────────────────────────────────────────────────────────────────
# ⭐ PER-SECTION FILTERS — public #48, stage 1 (owner-approved). Generalises the one
# mechanism on this page the owner reported liking: the opportunity list's CSS-only
# radio filter (five inputs and `#of-you:checked ~ .opp-list .opp[data-you="0"]
# {display:none}`), measured working on a phone. No JavaScript and no embedded dataset:
# a script is untestable from stdlib Python, and a data blob beside rendered HTML is the
# data twice. (The page's ONE script, "Copy as prompt" above, reads and writes no filter state.)
#
# One GROUP per filtered list: for each declared dimension, one radio set (`all` checked
# by default) and a label bar; every row in the list carries `data-rec="kind:id"` plus one
# `data-<dim>` per dimension; one deterministic CSS block per group hides the rows whose
# value is not the checked one. Dimensions AND together through the cascade — each
# checked radio hides its own non-matches, and a row hidden by any of them stays hidden.
#
# ⭐ FILTERING CHANGES CSS VISIBILITY ONLY. The HTML row set is identical in every filter
# state, so the coverage contract (ADR-024) holds under narrowing, and every label carries
# BOTH numbers — the population and what is rendered — computed here from the same store
# query. A label that counts only what it shows repeats the vanished-rows defect one level
# down.
#
# ⭐ AND A FILTERED LIST IS NEVER CAPPED (public #54, ADR-024's REACHABLE side). Stage 1
# kept the cap and let a label read "(2 shown of 17)": honest about the trim, and still a
# chip promising fifteen rows that no filter state could show — because narrowing is
# visibility over ONE rendered set, a trimmed row is reachable under no chip, and
# check_dashboard_coverage reported OK against exactly that page (counted is not
# reachable). So the two numbers are now an INVARIANT, not a disclosure: shown == population
# for every chip, verified against the HTML, and a filtered list has no remainder line.
#
# `:target` is not the filter mechanism (one target per page) — but `.flist
# [data-rec]:target {display:block !important}` reveals a link's destination even when its
# list's filter would hide it, so no cross-link (stage 2) can be a dead end.
#
# The ledger records every group — its dimensions, each dimension's ENUM SOURCE and
# vocabulary, and every member's values — and check_dashboard_coverage.py verifies
# DIMENSION COMPLETE, COUNT AGREES and (advisory until stage 2) EXACTLY ONCE against the
# HTML. Vocabularies are never this file's: every one is imported from the module that
# owns it (the `_CLOSED_STATUSES` lesson).
# ─────────────────────────────────────────────────────────────────────────────
COVERAGE["filters"] = {}
_FILTER_CSS = []
# Human labels for filter values whose enum token reads badly on a chip; anything not here
# renders as the token itself.
_FILTER_VALUE_LABELS = {
    # dev #494 / public #58, dev #540 / public #132 - the opportunity bar's one primary
    # dimension, in the user's words (NN/g: merge overlapping categories, no jargon, most
    # general first). The row's own chip reads this same table (`_pursuit_chip`).
    ("pursuit", "your-move"): "Your move — today",
    # dev #713 / public #145 (R4): the two role groups the triage gate adds. `decide` is a cross-cut
    # of the partition; `triaging` is a partition option of its own (a role is in it or in `New`).
    # (not "Decide — pursue or pass": that exact heading is the deleted dev #540 SECTION, and
    # tests assert it stays gone - a chip is not a section.)
    ("pursuit", "decide"): "Decide — pursue/pass owed",
    ("pursuit", "triaging"): "Triaging — the system is reading these",
    ("pursuit", "new"): "New — pursue or pass?",
    ("pursuit", "conversation"): "In live conversation",
    ("pursuit", "sent"): "Sent — awaiting a reply",
    ("pursuit", "not-sent"): "Not sent yet — queued to apply",
    ("pursuit", "interviews"): "In interviews",
    ("pursuit", "parked"): "Parked",
    ("pursuit", "ended"): "Ended",
    ("pursuit", "unclassifiable"): "Unclassifiable — a field is missing",
    ("owner", "you"): "Yours", ("owner", "run"): "The run's",
    ("when", "now"): "Now", ("when", "waiting"): "Waiting", ("when", "later"): "Later",
    ("sendability", "undrafted"): "No draft yet",
    ("sendability", "sendable"): "Ready to send", ("sendability", "blocked"): "Held",
    ("sendability", "unreadable"): "Unreadable hold",
    ("sendability", "unresolved"): "Unresolved hold",
    # Query or Citation C1 — the six new precondition.OPEN_STATES members.
    ("sendability", "unaddressed"): "No recipient",
    ("sendability", "unbriefed"): "Unbriefed",
    ("sendability", "brief-mismatch"): "Brief mismatch",
    ("sendability", "stale-brief"): "Stale brief",
    ("sendability", "unverified-cold"): "Queued — cold unverified",
    ("sendability", "unverified-silent"): "Queued — silence unverified",
    ("window", "past"): "Call held", ("window", "later"): "Beyond the horizon",
    ("window", "undated"): "Undated",
    ("prep", "prepped"): "Prepped", ("prep", "owed"): "Prep owed",
    ("prep", "owed-partial"): "Prep partial", ("prep", "beyond-horizon"): "Beyond the horizon",
    ("prep", "unlinked"): "No counterparty",
    ("review", "due"): "Review due", ("review", "current"): "Current",
    ("review", "on-inbound"): "On inbound", ("review", "unscheduled"): "Unscheduled",
}


# The label of a dimension's BAR, in the user's words - the sibling of _FILTER_VALUE_LABELS (the
# bar used to print the raw token, which is #58's "dimension names drawn from the data model"
# literally). A dimension with no entry still prints its token.
_FILTER_DIM_LABELS = {
    ("opportunities", "pursuit"): "Show",
    ("opportunities", "owner"): "Whose",
    ("drafts", "when"): "When",
}

# ⭐ CROSS-CUT OPTIONS (design r3 D4): a dimension's options partition its rows - each row has
# ONE value - except the options named here, which CUT ACROSS them (`your-move` is ATTENTION's
# needs-you; a role can be both `New` and `Your move`). A row carries its partition value in
# `data-<dim>` and its cross-cut memberships, space-separated, in `data-<dim>-also`; the hide
# rule for a cross-cut option tests the second, and COUNT/SUM/REACHABLE in
# check_dashboard_coverage.py count it from the same attribute (it is excluded from the SUM,
# which is over the partition).
_CROSS_CUTS = {"pursuit": tuple(_ym.PURSUIT_CROSS_CUTS)}

# ⭐ THE DECLARED DEFAULT ORDER (design r2 §5, kept by r3): for a (list, dimension), the values
# tried in order; the radio CHECKED on load is the first with a DRAWN chip (a non-zero population
# that is not the whole list), else `All`. A default whose population is zero must not emit a
# page with nothing checked and no hide rule (finding #128) - it falls through, and the page
# SAYS so (`.fdefault`). A default whose chip is suppressed because its rows ARE `All`'s needs no
# line: every row shown is in the default. The order and the value actually checked go into the
# ledger so the checker can assert both from the HTML.
FILTER_DEFAULTS = {
    ("opportunities", "pursuit"): ("your-move", "new"),
    ("drafts", "when"): ("now",),
}


def _fid(set_name, dim, value):
    return "f-%s-%s-%s" % (set_name, dim, value)


def _also(member, dim):
    """The cross-cut tokens a member carries for `dim` (`data-<dim>-also`, space-separated)."""
    return (member.get(dim + "-also") or "").split()


def _dim_attrs(dims):
    """The `data-<dim>="<value>"` attributes for one row, in a fixed order."""
    return "".join(' data-%s="%s"' % (esc(d), esc(str(v)))
                   for d, v in sorted(dims.items()) if v is not None)


def _count_label(shown, pop):
    return "(%d)" % pop if shown == pop else "(%d shown of %d)" % (shown, pop)


def render_filter_group(set_name, dims, members, shown_keys, refs=None):
    """The controls for one filtered list: `dims` is ((dim, enum_source, vocabulary), ...);
    `members` is {row key: {dim: value}} for the WHOLE population (before the cap);
    `shown_keys` the keys actually rendered — since public #54 every member, so each label
    reads "(N)"; the "(a shown of b)" form is kept only so a regression shows on the page
    as well as in the check. Records the group in the ledger and returns
    (controls_html, css). A value with zero population gets no radio and no chip.
    `refs` is {key: {dim: value}} for the REFERENCE rows of the list (design r3 §2): they carry
    the same `data-<dim>` attributes, count in every chip's population and are shown in full
    (a reference is never capped), and the ledger records them beside `members`.

    ⭐ DEGENERACY IS A RENDERER INVARIANT (dev #494 / public #58, design r3 §3.3, O2). A chip
    whose row set EQUALS `All`'s selects nothing `All` does not - on the reporter's page 74 of
    74 rows were `in-flight`, so `All (74)` and `In flight (74)` sat side by side - so it is
    NOT DRAWN, and a dimension left with only `All` draws no bar at all. This is general, not
    a constant deleted from one list: it holds on every install and every filtered list.
    ⭐ A SUPPRESSED CHIP KEEPS ITS RADIO, present and undrawn (design D3): a router label
    (`<label for="f-opportunities-pursuit-not-sent">`) resolves by id, and a label can only
    activate a radio that exists. The ledger still declares the dimension and rows still carry
    the attribute, so DIMENSION COMPLETE is unchanged.

    ⭐ THE DEFAULT is the first entry of FILTER_DEFAULTS[(set, dim)] with a drawn chip, else
    `All`; see FILTER_DEFAULTS. The page says so when the first entry had no members."""
    shown = [k for k in shown_keys if k in members]
    refs = refs or {}
    n_all = len(members) + len(refs)
    pop_vals = list(members.values()) + list(refs.values())
    shown_vals = [members[k] for k in shown] + list(refs.values())
    ctl, css, active, defaults, dims_led = [], [], [], {}, {}
    for dim, source, vocab in dims:
        name = "f-%s-%s" % (set_name, dim)
        cross = _CROSS_CUTS.get(dim, ())

        def _pop_of(value, vals=None):
            vs = pop_vals if vals is None else vals
            if value in cross:
                return sum(1 for m in vs if value in _also(m, dim))
            return sum(1 for m in vs if m.get(dim) == value)

        pops = {v: _pop_of(v) for v in vocab}
        drawn = [v for v in vocab if 0 < pops[v] < n_all]
        order = FILTER_DEFAULTS.get((set_name, dim), ())
        checked = next((v for v in order if v in drawn), "all")
        note = ""
        if order and pops.get(order[0], 0) == 0 and checked != order[0]:
            first = _FILTER_VALUE_LABELS.get((dim, order[0]), order[0])
            now = ("everything (%d)" % n_all if checked == "all" else "%s (%d)"
                   % (_FILTER_VALUE_LABELS.get((dim, checked), checked), pops[checked]))
            note = ('<div class="sub fdefault">Nothing under <strong>%s</strong> right now '
                    '— showing %s.</div>' % (esc(first), esc(now)))
        defaults[dim] = {"order": list(order), "checked": checked}
        dims_led[dim] = {"source": source, "values": list(vocab)}
        if cross:
            dims_led[dim]["cross"] = list(cross)
        dim_label = _FILTER_DIM_LABELS.get((set_name, dim), dim)
        bar = ['<span class="fdim">%s</span>' % esc(dim_label)]

        def _one(value, text, pop, sh, draw):
            fid = _fid(set_name, dim, value)
            ctl.append('<input type="radio" name="%s" id="%s" class="fctl"%s>'
                       % (esc(name), esc(fid), " checked" if value == checked else ""))
            if draw:
                bar.append('<label for="%s" data-flabel="%s:%s:%s:%d:%d">%s %s</label>'
                           % (esc(fid), esc(set_name), esc(dim), esc(value), sh, pop,
                              esc(text), _count_label(sh, pop)))
                active.append('#%s:checked ~ .fbar label[for="%s"]' % (fid, fid))
            if value != "all":
                attr = ('data-%s-also~="%s"' % (dim, value) if value in cross
                        else 'data-%s="%s"' % (dim, value))
                for tag in ("data-rec", "data-ref"):
                    css.append('  #%s:checked ~ .flist[data-flist="%s"] [%s]:not([%s])'
                               ' { display:none; }' % (fid, set_name, tag, attr))

        bar_drawn = bool(drawn)
        _one("all", "All", n_all, len(shown_vals), bar_drawn)
        for value in vocab:
            if not pops[value]:
                continue
            _one(value, _FILTER_VALUE_LABELS.get((dim, value), value), pops[value],
                 _pop_of(value, shown_vals), value in drawn)
        if bar_drawn:
            ctl.append('<div class="fbar">%s</div>' % "".join(bar))
        if note:
            ctl.append(note)
    # One highlight rule per group (a selector list), not one per chip — measured 10 KB
    # of CSS at realistic volume before this consolidation.
    if active:
        css.append('  %s { opacity:1; font-weight:600; border-color:var(--rail-now); '
                   'color:var(--rail-now); }' % ",\n  ".join(active))
    COVERAGE["filters"][set_name] = {
        "dims": dims_led,
        "members": members,
        "shown": shown,
        "defaults": defaults,
    }
    if refs:
        COVERAGE["filters"][set_name]["refs"] = refs
        COVERAGE["filters"][set_name]["shown_refs"] = sorted(refs)
    return "".join(ctl), "\n".join(css)


def render_filtered_list(set_name, dims, members, shown_keys, rows_html, more_html, cls="",
                         refs=None):
    """Controls + the `.flist` container of rows + the remainder OUTSIDE it. The three are
    siblings, in that order, because the CSS reaches the list through `~`."""
    ctl, css = render_filter_group(set_name, dims, members, shown_keys, refs=refs)
    if css:
        _FILTER_CSS.append("  /* filters: %s */\n%s" % (set_name, css))
    return ('%s<div class="%s" data-flist="%s">%s</div>%s'
            % (ctl, (cls + " flist").strip(), esc(set_name), rows_html, more_html))


def _age_days(iso, today=None):
    """'Nd' for a past ISO date, '' for anything unreadable — an unknown age must render
    as absent, never invented."""
    try:
        d = datetime.date(*map(int, str(iso).split("-")))
        n = ((today or datetime.date.today()) - d).days
        return "%dd" % n if n >= 0 else ""
    except Exception:
        return ""


def ws_row(item_html, who="", age="", due="", loud=False, rec=None, dims=None, ref=None):
    """One working-set row. `item_html` is pre-rendered (it may carry a JD link); the
    other cells are plain text, escaped at render time. `rec` is the coverage key of the
    store record this row IS ("opp:<id>", "ask:<id>", "commit:<id>"), or None for a row
    derived from something that is not a record (a channel review, a sequence). `dims`
    is {dim: value} when the row lives in a filtered list (public #48, stage 1). `ref` (design
    r3 §2) is the key of the record whose PRIMARY row lives elsewhere: the row is a REFERENCE
    (`data-ref`, a link to the primary, no ledger placement) - never a second `data-rec`."""
    return {"item": item_html, "who": who, "age": age, "due": due, "loud": loud, "rec": rec,
            "dims": dims or {}, "ref": ref}


def render_ws(rows, more_at, empty_msg, cap=None, set_name=None, dims=None):
    """One working set → a TABLE (item · who · age · due), soonest-due first (no due
    sorts last), capped at WORKING_SET_CAP with a '+K more' line naming where the
    remainder lives. Structured rows, never sentences. `set_name` places every record-
    backed row in the coverage ledger and stamps the remainder line. With `dims` — a
    ((dim, enum_source, vocabulary), ...) declaration — the table becomes a FILTERED LIST
    over the rows' own `dims` (public #48, stage 1), and then it is NEVER CAPPED: every
    member renders (ADR-024 REACHABLE, public #54) and there is no remainder."""
    if not rows:
        return '<div class="sub">%s</div>' % empty_msg
    cap = cap if cap is not None else WORKING_SET_CAP
    rows = sorted(rows, key=lambda r: (str(r.get("due") or "~"), ))
    filtered = bool(dims and set_name)
    shown, rest = (rows, []) if filtered else (rows[:cap], rows[cap:])
    if set_name:
        _cover_set(set_name, [r.get("rec") for r in shown], [r.get("rec") for r in rest])
    out = ["<table><tr><th>Item</th><th>Who</th><th>Age</th><th>Due</th></tr>"]
    for r in shown:
        attrs = (' class="ws-loud"' if r.get("loud") else "")
        item = r["item"]
        if r.get("rec"):
            attrs += _rec_attrs(r["rec"])
            if dims:
                attrs += _dim_attrs(r.get("dims") or {})
        elif r.get("ref"):
            attrs += _ref_attrs(r["ref"])
            item = item + " " + _ref_link(r["ref"])
            if dims:
                attrs += _dim_attrs(r.get("dims") or {})
        out.append('<tr%s><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
                   % (attrs, item,
                      esc(str(r.get("who") or "—")), esc(str(r.get("age") or "—")),
                      esc(str(r.get("due") or "—"))))
    out.append("</table>")
    more = ""
    if rest:
        more = ('<div class="sub ws-more"%s>+%d more — every one is still counted in the '
                'heading; the full set lives in %s.</div>'
                % ((' data-more="%s:%d"' % (esc(set_name), len(rest))) if set_name else "",
                   len(rest), md_inline(more_at)))
    if filtered:
        members = {r["rec"]: dict(r.get("dims") or {}) for r in rows if r.get("rec")}
        refs = {r["ref"]: dict(r.get("dims") or {}) for r in rows
                if r.get("ref") and not r.get("rec")}
        return render_filtered_list(set_name, dims, members,
                                    [r["rec"] for r in shown if r.get("rec")],
                                    "".join(out), more, refs=refs)
    return "".join(out) + more


def render_router_rows(phase_summaries):
    """The top of the one page: six rows, bounded by PHASE count. Each summary is
    (phase, n_needs, n_flight, clause, has_section[, extra]). Needs-you is the headline;
    in-flight is muted. ⭐ ZERO COLLAPSES: a phase with nothing at all is a muted one-liner
    with no anchor and NO section below it — four empty phases must never consume the page
    while one phase holds all the work.

    ⭐ dev #540 / public #132 (design r3 §3.2, R540) - the optional `extra` dict lets a row's
    headline COUNT be a `<label for="f-…">` for the filter radio that selects exactly that
    population in the list below (`ct_for`: the `applying` count selects `not-sent`, the
    `pipeline` count selects `your-move`), and its phase NAME anchor point at the list rather
    than at a section that no longer exists (`href`). No `:target` is involved: the label
    checks the radio, which is the only filter state there is (a fragment and a radio are two
    state sources CSS cannot reconcile - r2 finding #122). Whether the click also scrolls is
    UNDETERMINED (design probe 4); the phase-name anchor is the scroll, on the same row."""
    out = ['<div class="router">']
    for summary in phase_summaries:
        phase, n_needs, n_flight, clause, has_section = summary[:5]
        extra = summary[5] if len(summary) > 5 else {}
        label = "%s %s" % (_PHASE_ICON[phase], phase)
        href = extra.get("href") or ("#phase-%s" % phase if has_section else None)
        name = ('<a class="ph" href="%s">%s</a>' % (href, label)) if href \
            else ('<span class="ph">%s</span>' % label)
        if n_needs == 0 and n_flight == 0 and not has_section:
            out.append('<div class="rrow zero"><span class="ct">0</span>'
                       '<span class="ct2"></span>%s'
                       '<span class="nx">%s</span></div>' % (
                           ('<span class="ph">%s</span>' % label), md_inline(clause)))
            continue
        flight = ('<span class="ct2">%d in flight</span>' % n_flight) if n_flight \
            else '<span class="ct2"></span>'
        ct = ('<label for="%s" title="selects this population in the list below">%d</label>'
              % (esc(extra["ct_for"]), n_needs)) if (extra.get("ct_for") and n_needs) \
            else "%d" % n_needs
        out.append('<div class="rrow%s"><span class="ct">%s</span>%s%s'
                   '<span class="nx">%s</span></div>'
                   % (" quiet" if n_needs == 0 else "", ct, flight, name,
                      md_inline(clause)))
    out.append("</div>")
    return "".join(out)


JUMP_TARGETS = (("Drafts", "phase-outreach-approvals"), ("Opportunities", "phase-pipeline-roles"),
                ("Applications", "phase-applying-finish"))


def render_jump_bar(n_drafts, n_opps, n_apply=None):
    """The pinned jump bar (OWNER REQUEST 2026-10-13, three entries since jobsearch 0.71.0):
    `Drafts (N)`, `Opportunities (N)` and `Applications (N)`, each an in-page link to its list's
    heading. Pinned by CSS `position: sticky` only - no script - and offset by the viewer's top
    safe area. A count of None means the list is not on the page: the entry is then an unlinked
    muted label, never a link to nothing (ANCHOR). The headings it lands on sit outside every
    filtered row set, so a link lands on a visible target whatever chip is checked."""
    out = ['<nav class="jumpbar" aria-label="Jump to the lists read most">']
    for (label, sid), n in zip(JUMP_TARGETS, (n_drafts, n_opps, n_apply)):
        if n is None:
            out.append('<span class="jump off">%s (0)</span>' % label)
        else:
            out.append('<a class="jump" href="#%s">%s (%d)</a>' % (sid, label, n))
    out.append("</nav>")
    return "".join(out)


def _variant_staleness():
    """(n_active, n_stale) for the presence row: active resume variants whose union_sha
    no longer matches the claim union (presence/claims.md). Calls resume_variants.union_hash()
    on resume_variants.read_union() — the SAME 12-hex stamp `resume_variants.py --stamp`
    writes, computed the same way, so this can never disagree with the gate's own verdict."""
    variants = [v for v in load_jsonl("resume_variants.jsonl") if v.get("status") == "active"]
    union_text = _resume_variants.read_union(str(ROOT))
    cur = _resume_variants.union_hash(union_text) if union_text is not None else None
    stale = [v for v in variants if cur and v.get("union_sha") != cur]
    return len(variants), len(stale), stale


# `phase_rows`, `publish_selection` and `render_router` lived here until 2026-08-29.
# The collapse deleted them: the router is now the top section of the one page
# (render_router_rows above, fed per-phase in main()), and there is no publish
# SELECTION left to compute — the publish set is the one artifact, every run.


# ⭐ dev #546 / public #126 — DASHBOARD_TOMBSTONE lived here and was written to a root
# `dashboard.html` on every single run. It is gone, and nothing outside `views/` is written
# any more. The content it used to write is not lost: `migrate.py` carries the marker it
# needs to RECOGNISE an existing stub (`_TOMBSTONE_MARKERS`) so it can tell the engine's own
# retired stub from a file a candidate wrote themselves, and the profile's git history holds
# the bytes. Retirement is a MOVE to archive/retired-trackers/, never a note — the rule this
# stub was the standing exception to.


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
    # ADR-031 B2/B3 — every opportunities.jsonl load in this file gets o["_applications"] and
    # o["_touches"] set from their own top-level stores, from THIS one place, so every caller
    # below (there are several) never has to remember to join them separately and never
    # re-reads a nested array that no longer exists.
    if name == "opportunities.jsonl":
        _apps.enrich_opportunities(str(ROOT), out)
        _touches.enrich_opportunities(str(ROOT), out)
    return out


# ADR-031 B4 (design §19) — the play engine's Context is loaded ONCE per dashboard render and
# shared by every function in this file that needs a derived play position, rather than each
# rebuilding it (a `Context` loads the whole graph plus plans/plays/touches/applications).
_PLAY_CONTEXT_CACHE = {}


def _play_context():
    if "ctx" not in _PLAY_CONTEXT_CACHE:
        import plays as _plays_mod
        _PLAY_CONTEXT_CACHE["ctx"] = _plays_mod.Context(str(ROOT))
    return _PLAY_CONTEXT_CACHE["ctx"]


def _play_next_step(o, ctx=None, today=None):
    import plays as _plays_mod
    ctx = ctx or _play_context()
    today = today or datetime.date.today().isoformat()
    plan = ctx.plans_by_id.get(o.get("plan_id"))
    play = ctx.plays_by_id.get((plan or {}).get("play_id"))
    return _plays_mod.next_step(plan, play, o, ctx, today)


def _play_step_label(ns):
    """A short, row-scale label for one `plays.NextStep` — 'apply', 'research: find
    recruiter', 'touch (referral-ask) → insider' — or None when there is no runnable
    step to name (waiting/goal-reached/manual/stalled each render their own line)."""
    if ns.kind != "step":
        return None
    d = ns.detail or {}
    kind = d.get("kind")
    if kind == "apply":
        return "apply"
    if kind == "research":
        return "research: find %s" % d.get("find")
    if kind == "touch":
        return "touch (%s) → %s" % (d.get("touch_type"), d.get("to"))
    return ns.step


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
# `_CLOSED_STATUSES` lived here until 2026-09-02 — see the note at `_TERMINAL` (top of file).


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
        (closed if o.get("status") in _TERMINAL else live).append(row)
    return headers, live, closed, 4, 2, 5


def firms_from_channels():
    """Recruiter/referral channels -> the Network tab's firms table (cutover 2026-07-20,
    replacing network.md's firm sections). Columns mirror the old table.

    ADR-031 B1 — `channels.contacts[]` is retired; the people at a firm now join through
    `involvements.channel_id`, resolved (through any merge) against `people`. A merged-away
    alias never shows twice: `people_by_id` is only ever the survivor because
    `involvements.person_id` was written pointing at the survivor at migration time (design
    §3) — this reader does not need its own merge-resolution pass to get that right."""
    chans = [c for c in load_jsonl("channels.jsonl") if c.get("type") in ("recruiter", "referral")]
    people_by_id = {p.get("id"): p for p in load_jsonl("people.jsonl") if p.get("id")}
    involvements = load_jsonl("involvements.jsonl")
    names_by_channel = {}
    for inv in involvements:
        cid = inv.get("channel_id")
        if not cid:
            continue
        p = people_by_id.get(inv.get("person_id"))
        if p and p.get("name"):
            names_by_channel.setdefault(cid, []).append(p["name"])
    headers = ["Firm", "Contact(s)", "Relationship"]
    rows = []
    for c in sorted(chans, key=lambda c: c.get("label", "")):
        contacts = ", ".join(names_by_channel.get(c.get("id"), [])) or "—"
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

    active_rows: (label, scope, route, cadence, last_reviewed, due_html, yield_text, state,
                  channel_id)
    retired_rows: (label, scope, yield_text, channel_id). `state` is channels_due.review_rows' own
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
            retired.append((label, scope, ytxt, c.get("id")))
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
        active.append((label, scope, route, cadence, lr, due_html, ytxt, state, c.get("id")))
    return active, retired, n_due


def render_channels_list(active, retired, touch_due, relationship=()):
    """(html, n_rows) - ONE unfiltered list of the channels with something owed, plus one counted
    line for the rest (dev #541 / public #131, design r3 §5).

    Three sections over one record kind (`phase-pipeline-reviews`, `-sourcing`,
    `-sourcing-retired`) rendered a due channel twice and a quiet one never; the inventory rows
    carried no decision on a day nothing is due (a current channel is current, a retired one is
    retired). So this holds PRIMARY rows only for a channel whose review is DUE, whose cadence is
    UNSCHEDULED (a misconfiguration, loud as in the CLI) or whose touch the follow-up view refers
    to (`touch_due`: {channel id: date}, the target of that view's `data-ref`). Every other
    channel is counted in ONE line naming where it lives - the ledger places it as REMAINDER in
    set `channels` and the line carries `data-more="channels:N"`. That is legitimate for an
    UNFILTERED working set (ADR-024): the list takes no filter, so nothing is reachable-by-chip.

    `active` is `sourcing_view`'s rows `(label, scope, route, cadence, last_reviewed, due_html,
    yield_text, state, channel_id)`, `retired` its `(label, scope, yield_text, channel_id)`.
    `relationship` is the channel records (recruiter / referral) that carry a touch the
    follow-up view refers to but that `sourcing_view` never lists (a relationship channel is
    reviewed on inbound, not swept): each is a PRIMARY row too, or that reference would link
    to nothing."""
    shown, rest = [], []
    for row in active:
        cid, state = row[8], row[7]
        (shown if (state in ("due", "unscheduled") or cid in touch_due) else rest).append(row)
    for c in relationship:
        if c.get("id"):
            shown.append((c.get("label") or c["id"], c.get("scope_notes") or "",
                          c.get("type") or "—", "—", "—",
                          '<span class="chip action">touch due %s</span>'
                          % esc(str(touch_due.get(c["id"]))), "—", "touch", c["id"]))
    rest_keys = ["chan:%s" % r[8] for r in rest if r[8]] + [
        "chan:%s" % r[3] for r in retired if r[3]]
    shown_keys = ["chan:%s" % r[8] for r in shown if r[8]]
    _cover_set("channels", shown_keys, rest_keys)
    out = []
    if shown:
        out.append("<table><tr>")
        for h in ("Channel", "Route", "Cadence", "Last reviewed", "Next review", "Yield"):
            out.append("<th>%s</th>" % h)
        out.append("</tr>")
        for label, scope, route, cadence, lr, due_html, ytxt, state, cid in shown:
            name = "<strong>%s</strong>" % esc(label)
            if scope:
                name += '<div class="sub">%s</div>' % esc(scope)
            if cid in touch_due and state != "touch":
                name += (' <span class="chip action">touch due %s</span>'
                         % esc(str(touch_due[cid])))
            attrs = _rec_attrs("chan:%s" % cid) if cid else ""
            out.append("<tr%s>" % attrs + "".join(
                "<td>%s</td>" % cell
                for cell in (name, esc(route), esc(cadence), esc(lr), due_html, esc(ytxt)))
                + "</tr>")
        out.append("</table>")
    n_cur = sum(1 for r in rest)
    if rest_keys:
        out.append(
            '<div class="sub ws-more" data-more="channels:%d">%d %schannel%s: %d current, %d '
            'retired. Nothing due. They live in <code class="fileref">data/channels.jsonl</code>'
            '; ask the session &ldquo;show my channels&rdquo; for the full table.</div>'
            % (len(rest_keys), len(rest_keys), "other " if shown else "",
               "" if len(rest_keys) == 1 else "s", n_cur, len(retired)))
    return "".join(out), len(shown)


# The owning module's answer to "did a submission actually happen" (validate_data.py: "the
# applications[].status values that prove a submission actually happened"). Used to be a
# renderer-private literal here — ("submitted", "acknowledged", "interviewing", "offer") — which
# had drifted in both directions from validate_data.SUBMITTED_APP_STATUS: "interviewing" and
# "offer" are STAGES values, never legal on applications[].status, so they could never match
# anything; "rejected" and "advanced" ARE legal applications[].status values that prove a
# submission happened, and were silently missing, so an opportunity whose only application was
# rejected or advanced fell out of the "Submitted" bucket entirely — the exact shape stage 1 of
# public #48 removed everywhere else (the _TERMINAL / _CLOSED_STATUSES precedent, same pattern:
# bind the owning module's object directly, no local copy to drift).
SUBMITTED_STATES = _vd.SUBMITTED_APP_STATUS


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
        if o.get("status") in _TERMINAL:
            continue
        # ADR-031 B2 — o["_applications"], the join against the top-level applications store.
        apps = [a for a in (o.get("_applications") or []) if a.get("status") in SUBMITTED_STATES]
        if apps:
            a = sorted(apps, key=lambda x: x.get("date") or "")[-1]
            days = age(a.get("date") or "")
            # `cover_letter_attached` retired with the array; "attached" is now
            # "cover_letter_id is non-null" (design §1's own rule).
            cl_txt = "yes" if a.get("cover_letter_id") else "unrecorded"
            submitted.append([cname(o), o.get("title", ""), a.get("date") or "—",
                              f"{days}d" if days is not None else "—",
                              a.get("status", ""), cl_txt,
                              (a.get("method") or "").replace("-", " ")])
            continue
        # ADR-031 B3 — o["_touches"], never a nested array.
        contacts = len(o.get("_touches") or [])
        # `in-motion` is defined in CLAUDE.md as a recruiter/network thread — the
        # recruiter approached the candidate, so there is no touches row from their side and
        # its absence is NOT evidence that nothing is happening.
        _ns = _play_next_step(o)
        nxt = _play_step_label(_ns) or _ns.why or ""
        if contacts or o.get("status") == "in-motion" or o.get("stage") in ("screening", "interviewing", "offer"):
            who = ", ".join(x.get("to", "") for x in (o.get("_touches") or []) if x.get("to")) or "in process"
            human.append([cname(o), o.get("title", ""), o.get("stage", ""), who, nxt[:150]])
        else:
            nothing.append([cname(o), o.get("title", ""), o.get("status", ""), nxt[:180] or "— no next step derived —"])

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
    """The row's ask: context (comp · location) and ONE clause naming the play's DERIVED next
    step (ADR-031 B4, design §19 — `next_action` free text is retired), each part clamped
    BEFORE they are joined — the composed-string rule at `_clause`. The string returned here
    is display-ready; no caller may run `_clause` over it again (that is the measured defect:
    most role rows lost their action to the ". " this join inserted)."""
    ctx = [b for b in (_fmt_comp(o.get("comp")) if o.get("comp") else "",
                       _fmt_loc(o.get("location"))) if b]
    ns = _play_next_step(o)
    label = _play_step_label(ns) or ns.why or ns.kind
    action = _clause(label or "")
    if ctx and action:
        return "%s — %s" % (" · ".join(ctx), action)
    return " · ".join(ctx) or action


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
        # Clamp the field, then compose (the rule at `_clause`): the old sentence-shaped
        # ask was re-claused downstream and cut at its own " — ", losing the deadline and
        # the action on every decide row.
        bits = ["Decide: pursue or pass"]
        if d:
            bits.append("act by %s" % d)
        _ns = _play_next_step(o)
        _label = _play_step_label(_ns)
        if _label:
            bits.append(_clause(_label))
        items.append((_role_title(o, companies, "🔎"), " · ".join(bits), o.get("id"),
                      d or "9999"))
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
    for c, state, _touch, _evidence in _ym.classify_channels(
            load_jsonl("channels.jsonl"), messages, involvements=load_jsonl("involvements.jsonl")):
        if state != "now":
            continue
        nt = c.get("next_touch") or {}
        label = c.get("label") or c.get("id") or "a channel"
        when = str(nt.get("date"))
        bits = [b for b in (nt.get("time"), nt.get("note")) if b]
        # Clamp the note (a field), then compose — never the other way round.
        ask = ("Due %s — %s" % (when, _clause(" · ".join(str(b) for b in bits))) if bits
               else "Due %s" % when)
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
    for c, state, touch, evidence in _ym.classify_channels(
            load_jsonl("channels.jsonl"), messages, involvements=load_jsonl("involvements.jsonl")):
        if state != "fulfilled":
            continue
        label = c.get("label") or c.get("id") or "a channel"
        nt = c.get("next_touch") or {}
        ask = ("Plan fulfilled on %s by %s (planned for %s) — clear next_touch or author the "
              "next one." % (touch, evidence, nt.get("date")))
        fulfilled.append(("✅ %s" % label, ask, None, str(touch or "")))
    fulfilled.sort(key=lambda t: t[3])

    # ADR-031 B4 (design §19) — `play_stage 'unresolved'`'s successor: a STALLED play. The
    # ask is an imperative aimed at the owner (check_sections.py's own rule for Your Move
    # lines). Membership is `plays.next_step()`'s, never re-derived here.
    _play_ctx = _play_context()
    _today_iso = datetime.date.today().isoformat()
    stalled = []
    for o in all_opps:
        if o.get("status") in _vd.TERMINAL_OPP_STATUSES:
            continue
        ns = _play_next_step(o, _play_ctx, _today_iso)
        if ns.kind == "stalled":
            ask = "The play is stalled: %s — see `plays.py --check`." % ns.why
            stalled.append((_role_title(o, companies, "🎬"), ask, o.get("id")))

    return ([(t, a, oid) for (t, a, oid, _d) in unresolved],
            [(t, a, oid) for (t, a, oid, _d) in waiting],
            [(t, a, oid) for (t, a, oid, _d) in fulfilled],
            stalled)


def render_your_move_callouts(unresolved, waiting, fulfilled, stalled_plays, links=None):
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
            '<div class="card">%s</div>'
            % (len(unresolved), render_your_move(unresolved, links,
                                                 set_name="pipeline-unresolved", ref=True)))
    if waiting:
        parts.append(
            '<h2 style="font-size:16px;margin-top:22px">⏳ Waiting on the other side '
            '<span class="tcount">%d</span></h2>'
            '<div class="sub" style="margin:-6px 0 10px">Blocked until the named contact '
            'reaches the outcome the role is waiting on. <strong>Not yours to do</strong> — '
            'moves to the list above by itself once the record shows it.</div>'
            '<div class="card">%s</div>'
            % (len(waiting), render_your_move(waiting, links, set_name="pipeline-waiting",
                                              ref=True)))
    if fulfilled:
        parts.append(
            '<h2 style="font-size:16px;margin-top:22px">✅ Plans fulfilled, not yet cleared '
            '<span class="tcount">%d</span></h2>'
            '<div class="sub" style="margin:-6px 0 10px">A touch landed on or after the '
            'planned date. Clear <code>next_touch</code> or author the next one.</div>'
            '<div class="card">%s</div>' % (len(fulfilled), render_your_move(
                fulfilled, links, store="data/channels.jsonl")))
    if stalled_plays:
        parts.append(
            '<h2 style="font-size:16px;margin-top:22px">🎬 Stalled plays '
            '<span class="tcount">%d</span></h2>'
            '<div class="sub" style="margin:-6px 0 10px">No runnable step, and no known clock '
            'will flip one (<code>plays.py --check</code>). The play is the authority for '
            "what's next — this is what it found nothing to do about.</div>"
            '<div class="card">%s</div>'
            % (len(stalled_plays), render_your_move(stalled_plays, links,
                                                    set_name="pipeline-play", ref=True)))
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
  .sub.moved { margin: 4px 0 10px; }
  /* OWNER REQUEST 2026-10-13: "Copy as prompt" on each draft row. */
  .cap { margin: 6px 0 2px; display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  .cap-btn { font: inherit; font-size: 12px; font-weight: 600; cursor: pointer;
             color: var(--rail-now); background: var(--card-bg);
             border: 1px solid var(--card-border); border-radius: 6px; padding: 3px 10px; }
  .cap-text { width: 100%; font: 12px ui-monospace, Menlo, monospace; color: var(--fg);
              background: var(--bg); border: 1px solid var(--card-border); border-radius: 6px; }
  .sub.moved a { color: var(--rail-now); }
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
  /* Query or Citation C1 (design-query-or-citation.md sec 3.5) - WAITS_ON_SURFACE: neither
     owner nor other side, a third class beside action/waiting - queued for a session with a
     keychain. */
  .chip.queued { background: var(--chip-queued-bg); color: var(--chip-queued-fg); }
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
  .opp-triaging { opacity:.7; font-style:italic; }
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

  /* ⭐ Per-section CSS-only filters (public #48, stage 1) — the generic half; the
     per-group rules (one block per filtered list) are appended by render_filter_group. */
  .fctl { display:none; }
  .fbar { display:flex; gap:6px; flex-wrap:wrap; align-items:center; margin:2px 0 6px; }
  .fbar .fdim { font-size:11px; text-transform:uppercase; letter-spacing:.07em;
                opacity:.55; margin-right:2px; }
  .fbar label { font-size:12px; padding:4px 10px; border-radius:999px; cursor:pointer;
                border:1px solid var(--card-border); opacity:.75; }
  /* A link's destination is revealed even when its list's filter would hide it — one
     target per page, so this is never the filter, only the guarantee that no cross-link
     (stage 2) lands on a hidden row. */
  .flist [data-rec]:target { display:block !important; }
  .flist tr[data-rec]:target { display:table-row !important; }
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
  /* public #31 / #46 — clause on the row, full body collapsed on the same row */
  .ws-full { display: block; margin-top: 4px; }
  .ws-full summary { font-size: 12px; opacity: .7; cursor: pointer; }
  .ws-full-body { margin-top: 6px; font-size: 13px; line-height: 1.5; white-space: pre-wrap; }
  .prep-past { opacity: .8; }
""" + _CSS_ROUTER


REVIEW_NOW = (
    # (section id, router/jump label, icon)
    ("phase-outreach-approvals", "Drafts to review", "✉️"),
    ("phase-pipeline-roles", "Opportunities to pursue", "🎯"),
    ("phase-applying-finish", "Applications to finish", "📝"),
)

# The homes a record can live in once the page no longer renders it (design §4, amending ADR-024):
# `panel` is scripts/panel.py's `elsewhere` object; the two review homes are presence_set.py's panes.
ELSEWHERE_HOMES = ("panel", "review-resume", "review-linkedin")


def render_review_router(rows):
    """The top of the page since jobsearch 0.71.0: THREE anchors and a clause each, nothing else.
    The counts that used to ride the six-phase router moved to the band and the status pane
    (scripts/panel.py), because status is not what this page is for. A row whose list is not on the
    page is a muted label with no anchor, so the router never links to nothing (ANCHOR)."""
    out = ['<div class="router">']
    for icon, label, sid, n, clause in rows:
        if n:
            out.append('<div class="rrow"><a class="ph" href="#%s">%s %s</a>'
                       '<span class="nx">%s</span></div>' % (sid, icon, esc(label), md_inline(clause)))
        else:
            out.append('<div class="rrow zero"><span class="ph">%s %s</span>'
                       '<span class="nx">%s</span></div>' % (icon, esc(label), md_inline(clause)))
    out.append("</div>")
    return "".join(out)


def main():
    drafts = parse_drafts(read(_tree.rel("drafts")))
    # Cover letters are a distinct artifact from outreach drafts (added 2026-07-21).
    covers = [c for c in parse_cover_letters(read(_tree.rel("cover_letters")))]

    # ⭐⭐ focus.md IS RETIRED AS A SOURCE OF STATE — dev #93 (public #21). Every surface below reads
    # a store.
    _all_asks = load_jsonl("asks.jsonl")
    _opp_rows = load_jsonl("opportunities.jsonl")
    _opp_comps = {c["id"]: c for c in load_jsonl("companies.jsonl")}

    # ── Preconditions over the staged-message pair (issues #6/#13, dev #169, public #29).
    _DRAFTS_REL, _COVERS_REL = _tree.rel("drafts"), _tree.rel("cover_letters")
    try:
        import precondition as _pre
        _pre_rows = _pre.report(str(ROOT))
        # dev #496 / public #48, design r3 D5 - the state row of an entry is keyed by its UNIQUE
        # key (your_move.entry_keys), file by file in order, never by title alone.
        _states = {}
        for _f in dict.fromkeys(r.get("file", _DRAFTS_REL) for r in _pre_rows):
            _fr = [r for r in _pre_rows if r.get("file", _DRAFTS_REL) == _f]
            for _r, _k in zip(_fr, _ym.entry_keys("draft" if _f == _DRAFTS_REL else "cover",
                                                  [r["title"] for r in _fr])):
                _r["_key"] = _k
                _states[(_f, _k)] = _r
        _not_sendable = _pre.NOT_SENDABLE
        _terminal = _pre.TERMINAL
        _needs_human = _pre.NEEDS_HUMAN
        _waits_on_surface = _pre.WAITS_ON_SURFACE
    except Exception:
        _pre_rows, _states, _not_sendable, _terminal = [], {}, frozenset(), frozenset()
        _needs_human = frozenset()
        _waits_on_surface = frozenset()

    def _pre_state(filename, key):
        return _states.get((filename, key), {}).get("state")

    # public #29 — TERMINAL entries render in NEITHER list; the ledger says they ended.
    for _r in _pre_rows:
        if _r.get("state") in _terminal:
            _cover(_r["_key"], "terminal",
                   "drafts" if _r.get("file") == _DRAFTS_REL else "covers")
    _draft_keys = _ym.entry_keys("draft", [d[0] for d in drafts])
    _cover_keys = _ym.entry_keys("cover", [c[0] for c in covers])
    _dpairs = [(d, k) for d, k in zip(drafts, _draft_keys)
               if _pre_state(_DRAFTS_REL, k) not in _terminal]
    _drafts_active = [d for d, _k in _dpairs]
    _drafts_active_keys = [k for _d, k in _dpairs]
    _sendable = [d for d, k in _dpairs if _pre_state(_DRAFTS_REL, k) not in _not_sendable]
    # ⭐ public #37 — NOT_SENDABLE is two things: `blocked` waits on the other side, `unreadable`/
    # `unresolved` wait on the OWNER. ⭐ Query or Citation C1 — WAITS_ON_SURFACE is a THIRD group.
    _blocked = [d for d, k in _dpairs
                if _pre_state(_DRAFTS_REL, k) in _not_sendable
                and _pre_state(_DRAFTS_REL, k) not in _needs_human
                and _pre_state(_DRAFTS_REL, k) not in _waits_on_surface]
    _unreadable = [d for d, k in _dpairs if _pre_state(_DRAFTS_REL, k) in _needs_human]
    _queued = [d for d, k in _dpairs
               if _pre_state(_DRAFTS_REL, k) in _waits_on_surface]
    n_blocked = len(_blocked)
    n_queued = len(_queued)

    # dev #169 — the covers list consults preconditions exactly as the drafts list does.
    _cpairs = [(c, k) for c, k in zip(covers, _cover_keys)
               if _pre_state(_COVERS_REL, k) not in _terminal]
    _covers_active = [c for c, _k in _cpairs]
    _covers_active_keys = [k for _c, k in _cpairs]
    _covers_ready = [c for c, k in _cpairs if _pre_state(_COVERS_REL, k) not in _not_sendable]
    _covers_held = [c for c, k in _cpairs
                    if _pre_state(_COVERS_REL, k) in _not_sendable
                    and _pre_state(_COVERS_REL, k) not in _needs_human]
    _covers_unreadable = [c for c, k in _cpairs
                          if _pre_state(_COVERS_REL, k) in _needs_human]
    covers_html = render_message_list("covers", "cover", _covers_active, _states,
                                      _COVERS_REL, COVER_DIMS, "No cover letters pending.",
                                      keys=_covers_active_keys)
    n_covers_held = len(_covers_held)

    # public #95 — the terminal-transition cascade's data-store half. Advisory only.
    try:
        _ended_ctx = _ym.build_ended_context(str(ROOT))
        _letter_rows, _cl_errs, _cl_present = _apps.load_cover_letters(str(ROOT))
        n_letters_moot = sum(1 for _l in _letter_rows
                             if _ym.letter_state(_l, _ended_ctx)[0] == "moot")
        n_letters_used = sum(1 for _l in _letter_rows
                             if _ym.letter_state(_l, _ended_ctx)[0] == "used")
    except Exception:
        n_letters_moot = n_letters_used = 0

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
        # ⚠️ A failed scan must NEVER read as "nothing owed" — that is the missing-reads-as-empty trap.
        print("  !! WARNING: trigger scan failed (%s) — the outreach row cannot count "
              "sequences or unlinked applications; run trigger.py --check" % _e)
        _trep, _n_unblocked, _n_waiting_seqs, _untrig_rows = None, 0, 0, []
    # dev #539 / public #133 - the follow-up view's membership, from its ONE owner.
    _od = _ym.outreach_due(str(ROOT), pre_rows=_pre_rows, untriggered=_untrig_rows)
    _od_whens = {d["key"]: d["when"] for d in _od["drafts"]}

    _today_iso = datetime.date.today().isoformat()

    # ─────────────────────────────────────────────────────────────────────────
    # ⭐ THE REVIEW-NOW PAGE (jobsearch 0.71.0, dev #750 part 2; design §4, owner decision C).
    # Three sections and nothing else: current DRAFTS to review (people due promoted into it),
    # OPPORTUNITIES to pursue (a decision is owed), APPLICATIONS to finish (pursuing, not yet sent,
    # plus their cover letters). Status moved to the panel (scripts/panel.py: band + pane +
    # /jobsearch:status) and the presence artifact's reviews to /jobsearch:review-resume and
    # /jobsearch:review-linkedin. EVERY RECORD THE PAGE NO LONGER RENDERS IS LEDGERED `elsewhere`
    # WITH ITS HOME, and check_dashboard_coverage.py refuses an ELSEWHERE record whose home's JSON
    # does not carry its id - so nothing is dropped silently (P3).
    # ─────────────────────────────────────────────────────────────────────────

    # Records that have ENDED say so by omission, as before.
    for _a in _all_asks:
        if _a.get("resolved_on") and _a.get("id"):
            _cover("ask:%s" % _a["id"], "terminal", "asks")
    _commits = load_jsonl("commitments.jsonl")
    for _c in _commits:
        _cd = str(_c.get("date") or "")
        _c_cancelled = str(_c.get("status") or "") == "cancelled"
        if _c.get("id") and (_c_cancelled or (_vd.is_date(_cd) and _cd < _today_iso)):
            _cover("commit:%s" % _c["id"], "terminal", "conversations")
    for _o in _opp_rows:
        if _o.get("status") in _TERMINAL and _o.get("id"):
            _cover("opp:%s" % _o["id"], "terminal", "opportunities")

    # The role classification and the ONE pursuit map (dev #713, #494/#540).
    _live = [o for o in _opp_rows if o.get("status") not in _TERMINAL]
    _attention = _ym.attention_by_id(_opp_rows, OWNER_TOKEN)
    _owner = _ym.owner_by_id(_opp_rows, OWNER_TOKEN)
    _roles = {o.get("id"): st for o, st, _w in _ym.classify_opportunities(_opp_rows, OWNER_TOKEN)
              if o.get("id")}
    _pursuit = pursuit_by_id(_live, _roles)
    _new_opps = [o for o in _live if (_pursuit.get(o.get("id")) or {}).get("state") == "new"]
    _unsent_opps = [o for o in _live if (_pursuit.get(o.get("id")) or {}).get("state") == "not-sent"]

    # A follow-up row whose subject is NOT rendered on this page (a channel, a role in flight) is a
    # PRIMARY row of the Drafts list (render_message_list `primary`); one whose subject IS on the page
    # (a role under Opportunities / Applications) stays a reference with a link to it.
    _page_opp_keys = set("opp:%s" % o.get("id") for o in _new_opps + _unsent_opps)
    _od_refs = [dict(r, primary=(r["kind"] in ("chan", "opp") and r["key"] not in _page_opp_keys))
                for r in _od["refs"]]

    # dev #751 -- the warm-path next action per role, DERIVED by warm_path.py (no stored copy). A failed
    # derivation must NEVER read as "nobody to ask": it is said on the page and in the log.
    _warm_by_opp, _warm_failed = {}, None
    try:
        _cfg_lookup = _ck.resolve_int(_profile.config(), _ck.SEARCH_WARM_LOOKUP_DAYS)
        for _a in _warm_path.derive(str(ROOT), today=_today_iso, lookup_days=_cfg_lookup):
            for _oid in _a["opp_ids"]:
                _warm_by_opp[_oid] = _a
    except Exception as _e:                                          # noqa: BLE001 - said, never swallowed
        _warm_failed = "%s: %s" % (type(_e).__name__, _e)
        print("  !! WARNING: the warm-path derivation failed (%s) - the cards carry no warm-path line"
              % _warm_failed)

    # ── Opportunities to pursue: the roles where a decision is owed ────────
    _first_opps, opp_counts = "", dict(_EMPTY_OPP_COUNTS)
    if _new_opps:
        opp_list_html, opp_counts = render_opportunity_list(
            _new_opps, _opp_comps, attention=_attention, owner=_owner, pursuit=_pursuit,
            roles=_roles, warm=_warm_by_opp)
        _first_opps = (
            '<h2 id="phase-pipeline-roles">🎯 Opportunities to pursue '
            '<span class="tcount">%d</span></h2>'
            '<div class="sub" style="margin:-6px 0 10px">Roles where a <strong>decision is '
            'owed</strong>: pursue or pass. A role the run is still reading is not here until it '
            'has finished; a role you are pursuing is under Applications to finish; everything '
            'in flight lives in the jobsearch status pane (<code>/jobsearch:status</code>).</div>'
            % opp_counts["all"] + opp_list_html)

    # ── Applications to finish: pursuing, nothing sent, plus their cover letters ──
    _first_apply, n_apply = "", 0
    _apply_parts = []
    if _unsent_opps:
        todo_html, todo_counts = render_opportunity_list(
            _unsent_opps, _opp_comps, attention=_attention, owner=_owner, pursuit=_pursuit,
            roles=_roles, set_name="applying-finish", warm=_warm_by_opp)
        n_apply += todo_counts["all"]
        _apply_parts.append(todo_html +
                            '<div class="note"><strong>&ldquo;Not sent yet&rdquo; is the gap.'
                            '</strong> A role you are pursuing with no application out is queued '
                            'to apply.</div>')
    if _covers_active:
        # public #95 — the data-store side of the cascade, reported once, plainly.
        _cascade_note = ""
        if n_letters_moot or n_letters_used:
            _bits = []
            if n_letters_used:
                _bits.append("%d used (an application already carries it)" % n_letters_used)
            if n_letters_moot:
                _bits.append("%d moot (its pursuit has ended)" % n_letters_moot)
            _cascade_note = ('<div class="sub" style="margin:6px 0 0">data/cover_letters.'
                             'jsonl: %s — public #95</div>' % "; ".join(_bits))
        n_apply += len(_covers_ready) + len(_covers_unreadable)
        _apply_parts.append(
            '<h3 id="phase-outreach-covers">📄 Cover letters — for applications you submit '
            'yourself <span class="tcount">%d</span>%s</h3>'
            '<div class="sub" style="margin:-6px 0 10px">Every claim traces to the claim '
            'union (presence/claims.md). You paste and submit these yourself — nothing is '
            'applied on your behalf. A held letter waits on a precondition; do not submit it '
            'yet.</div>'
            '<div class="card">%s</div>%s'
            % (len(_covers_ready) + len(_covers_unreadable),
               (' <span class="ct2f">· %d held</span>' % n_covers_held) if n_covers_held else "",
               covers_html, _cascade_note))
    if _apply_parts:
        _first_apply = (
            '<h2 id="phase-applying-finish">📝 Applications to finish '
            '<span class="tcount">%d</span></h2>'
            '<div class="sub" style="margin:-6px 0 10px">Roles you are pursuing that have no '
            'application out yet, and the cover letters you will paste into them.</div>'
            % n_apply + "".join(_apply_parts))

    # ── Drafts to review: the follow-up view, with people due promoted into it ──
    _trig_note = ('<div class="note">⛔ <strong>Trigger scan failed</strong> — sequence and '
                  'follow-up counts on this page are UNKNOWN, not zero. Run '
                  '<code>trigger.py --check</code>.</div>') if _trep is None else ""
    _view = bool(_drafts_active or _od_refs)
    _people_due_html, _n_people_due = render_people_due(ROOT, _today_iso)
    _first_drafts = ""
    if _view or _people_due_html or _trig_note:
        seq_bits = []
        if _trep is not None and _n_unblocked:
            seq_bits.append("%d sequence%s unblocked — the next step is sendable"
                            % (_n_unblocked, "" if _n_unblocked == 1 else "s"))
        if _trep is not None and _n_waiting_seqs:
            seq_bits.append("%d waiting on a trigger" % _n_waiting_seqs)
        n_now = (sum(1 for d in _od["drafts"] if d["when"] == "now")
                 + sum(1 for r in _od["refs"] if r["when"] == "now"))
        _drafts_body = (render_message_list("drafts", "draft", _drafts_active, _states,
                                            _DRAFTS_REL, DRAFT_DIMS, "No pending drafts.",
                                            keys=_drafts_active_keys, whens=_od_whens,
                                            refs=_od_refs)
                        if _view else '<div class="sub">No pending drafts.</div>')
        _first_drafts = _trig_note + (
            '<h2 id="phase-outreach-approvals">✉️ Drafts to review '
            '<span class="tcount">%d</span>%s%s</h2>'
            '<div class="sub" style="margin:-6px 0 10px">Nothing is ever sent without your '
            'explicit approval. The full text of every message you have staged is right here '
            '— read it on this page, never off a transcript. A row marked <em>no draft yet</em> '
            'is someone who owes a message in the next %d days: it links to the channel, role '
            'or person it is about. Held messages wait on the other side and move to ready by '
            'themselves; a hold nobody can read waits on YOU; a queued one waits on a session '
            'with a keychain (Query or Citation C1).%s</div>'
            '<div class="card">%s</div>'
            % (n_now + _n_people_due,
               (' <span class="ct2f">· %d held</span>' % n_blocked) if n_blocked else "",
               (' <span class="ct2f">· %d queued</span>' % n_queued) if n_queued else "",
               _ck.OUTREACH_HORIZON_DAYS,
               (" " + esc("; ".join(seq_bits)) + " (trigger.py owns the derivation).")
               if seq_bits else "",
               _drafts_body)) + _people_due_html

    # ── LEDGER: everything the page no longer renders lives ELSEWHERE, with its home ──
    for o in _live:
        if o.get("id") and "opp:%s" % o["id"] not in _page_opp_keys:
            _cover("opp:%s" % o["id"], "elsewhere", "panel")
    for a in _all_asks:
        if a.get("id") and not a.get("resolved_on"):
            _cover("ask:%s" % a["id"], "elsewhere", "panel")
    for c in _commits:
        if c.get("id"):
            _cover("commit:%s" % c["id"], "elsewhere", "panel")
    for ch in load_jsonl("channels.jsonl"):
        if ch.get("id"):
            _cover("chan:%s" % ch["id"], "elsewhere", "panel")
    _preps, _kbs = knowledge_docs()
    for _p in _preps:
        _cover("prep:%s" % _p[1], "elsewhere", "panel")

    # ── Assemble the ONE page. ─────────────────────────────────────────────
    # %-d is a glibc/BSD strftime extension; on Windows it raises ValueError and kills the dashboard
    # at the last step. Build the day number by hand (same fix as parse_ics.py).
    _t = datetime.date.today()
    today = "%s %d, %d" % (_t.strftime("%B"), _t.day, _t.year)
    _title = _dashboard_title()

    n_drafts_primary = len(_drafts_active)
    router_html = render_review_router([
        ("✉️", "Drafts to review", "phase-outreach-approvals",
         1 if _first_drafts else 0,
         ("%d staged message%s to read and approve." % (n_drafts_primary,
                                                         "" if n_drafts_primary == 1 else "s"))
         if _first_drafts else "Nothing staged."),
        ("🎯", "Opportunities to pursue", "phase-pipeline-roles", 1 if _first_opps else 0,
         ("%d role%s where a decision is owed." % (opp_counts["all"],
                                                    "" if opp_counts["all"] == 1 else "s"))
         if _first_opps else "No decision is owed on a role."),
        ("📝", "Applications to finish", "phase-applying-finish", 1 if _first_apply else 0,
         ("%d item%s to finish." % (n_apply, "" if n_apply == 1 else "s"))
         if _first_apply else "Nothing queued to apply."),
    ])
    # The pinned jump bar (OWNER REQUEST 2026-10-13): one entry per list, each count the PRIMARY
    # rows that list renders (`data-rec="draft:…"` / `data-rec="opp:…"`), never a reference row;
    # a list that is not on the page is a plain, unlinked label, so the bar never links to nothing.
    _first_html = ""
    if _first_drafts or _first_opps or _first_apply:
        _first_html = ('<section class="first" id="first-lists">\n%s\n%s\n%s\n</section>'
                       % (_first_drafts, _first_opps, _first_apply))
    jump_html = render_jump_bar(n_drafts_primary if _first_drafts else None,
                                opp_counts["all"] if _first_opps else None,
                                n_apply if _first_apply else None)

    body_inner = (
        '%s\n'
        '<h1>%s</h1>\n'
        # ⭐ The generated-date line stays PROMINENT: for the dashboard-only reader it is the ONLY
        # staleness signal there is (deployment.md, the S5 read leg).
        '<div class="updated">Generated <strong>%s</strong> · the page of what needs a decision '
        'or a finish today · status lives in the jobsearch panel (<code>/jobsearch:status</code>) '
        '· generated by scripts/generate_dashboard.py</div>\n'
        '%s\n%s\n'
        '<div class="sub" style="margin-top:26px">Not on this page: status and everything in '
        'flight (the jobsearch panel and <code>/jobsearch:status</code>), the resume and '
        'public-profile reviews (<code>/jobsearch:review-resume</code>, '
        '<code>/jobsearch:review-linkedin</code>), the full network (queried in session — '
        '<code class="fileref">data/channels.jsonl</code>, <code class="fileref">%s</code>), '
        'archives, sent and closed items, and knowledge bodies.</div>'
        % (jump_html, html.escape(_title), today, router_html, _first_html,
           esc(_tree.rel("network"))))

    # ── The output: the ONE artifact. Nothing outside views/ is written (dev #546). ──
    (ROOT / "views").mkdir(exist_ok=True)
    # The page's ONE script, and only when a draft row carries its button (OWNER REQUEST 2026-10-13,
    # "Copy as prompt"); a page with no draft stays script-free.
    if 'class="cap-btn"' in body_inner:
        body_inner += "\n" + COPY_SCRIPT
    artifact_doc = ('<title>%s</title>\n<style>%s\n%s\n</style>\n%s'
                    % (html.escape(_title), CSS, "\n".join(_FILTER_CSS), body_inner))
    (ROOT / "views" / "dashboard_artifact.html").write_text(artifact_doc, encoding="utf-8")
    # The coverage ledger (Class C) — verified against the HTML by check_dashboard_coverage.py;
    # never trusted on its own.
    _ledger = {
        "generated_on": _t.isoformat(),
        "window": {"today": _t.isoformat(), "prep_horizon_days": _conv_mod.HORIZON_DAYS},
        "terminal_statuses": sorted(_TERMINAL),
        "records": COVERAGE["records"],
        "remainders": COVERAGE["remainders"],
        # public #48, stage 1 — every filtered list: its dimensions (each with the enum that owns
        # its vocabulary), every member's values, and what was shown.
        "filters": COVERAGE["filters"],
        # jobsearch 0.71.0 - the homes an `elsewhere` record may name.
        "elsewhere_homes": list(ELSEWHERE_HOMES),
    }
    (ROOT / "views" / "dashboard_coverage.json").write_text(
        json.dumps(_ledger, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8")

    print("Wrote views/dashboard_artifact.html (%d bytes)"
          % len(artifact_doc.encode("utf-8")))
    print("  publish: ONE artifact — views/dashboard_artifact.html, to the URL in "
          "views/dashboard_artifact_url.txt. If that url file is absent, check "
          "check_dashboard_fresh.py --publish-state FIRST: never-published (no stamp "
          "either) means create it on first publish; url-missing (a stamp already exists) "
          "means RECOVER the URL via the Artifact tool's list action, never mint a new one")
    print("  review-now: drafts %d · opportunities %d · applications to finish %d  "
          "(everything else is ELSEWHERE in the ledger: the panel, /jobsearch:status)"
          % (n_drafts_primary, opp_counts["all"], n_apply))
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
