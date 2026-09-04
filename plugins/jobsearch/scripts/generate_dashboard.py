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
# The one definition of the play sequence — validate_data.py owns the enum; consumers
# import it rather than restating it (a sequence typed twice disagrees with itself later).
from validate_data import PLAY_SEQUENCE as _PLAY_SEQUENCE
import validate_data as _vd
import applying as _applying
import knowledge as _kn
import precondition as _pre
import channels_due as _cd
import conversations as _conv_mod
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
    """The one COVERAGE bucket this role belongs to — applying.coverage's, by import. The
    three values were this file's own until public #48 stage 1 made coverage a declared
    filter dimension, and a dimension's vocabulary must have an owner outside the renderer
    (the `_CLOSED_STATUSES` lesson at the top of this file)."""
    return _applying.coverage(o)


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

# The opportunity list's four filter dimensions — every vocabulary imported from the
# module that owns it (public #48, stage 1). `state` is the router's two counts as a
# per-row value (your_move.ATTENTION); `owner` is whose move the row is
# (your_move.OWNER — public #54 restored it: ATTENTION cannot say "yours, not today");
# `stage` is the record's own funnel position (validate_data.STAGES); `coverage` is
# applying.COVERAGE. The renderer declares which dimensions exist; it never declares
# what their values may be.
OPP_DIMS = (("state", "your_move.ATTENTION", _ym.ATTENTION),
            ("owner", "your_move.OWNER", _ym.OWNER),
            ("stage", "validate_data.STAGES", tuple(sorted(_vd.STAGES))),
            ("coverage", "applying.COVERAGE", _applying.COVERAGE))


def render_opportunity_list(opps, companies, attention=None, owner=None):
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

    Returns (html, counts): html is the whole filtered list — controls, the `.flist` of
    rows, and the remainder line OUTSIDE it (never hidden by any filter state).
    """
    attention = attention or {}
    owner = owner if owner is not None else _ym.owner_by_id(opps, OWNER_TOKEN)
    live = [o for o in opps if o.get("status") not in _TERMINAL]
    for o in opps:
        if o.get("status") in _TERMINAL and o.get("id"):
            _cover("opp:%s" % o["id"], "terminal", "opportunities")
    if not live:
        return '<div class="sub">No live opportunities.</div>', dict(_EMPTY_OPP_COUNTS)
    order = {"active-pursuit": 0, "needs-resolution": 1, "in-motion": 2, "backlog": 3}

    def key(o):
        # Whose move it is, in precedence: needs the candidate today, then the candidate's
        # (dated out, or outside Your Move's membership), then the run's. The second tier is
        # the one 0.37.0 dropped (public #54): a row that is yours must never read as the
        # run's just because it is not today's.
        oid = o.get("id")
        tier = (0 if attention.get(oid) == "needs-you"
                else 1 if owner.get(oid) == "you" else 2)
        return (tier, order.get(o.get("status"), 9),
                -(STAGES.index(o["stage"]) if o.get("stage") in STAGES else -1))

    counts = dict(_EMPTY_OPP_COUNTS)
    rows, members = [], {}
    for o in sorted(live, key=key):
        comp = companies.get(o.get("company_id"), {})
        bucket = opp_bucket(o)
        waits = owner.get(o.get("id")) == "you"
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

        _key = "opp:%s" % (o.get("id") or "")
        dims = {"state": attention.get(o.get("id")), "owner": owner.get(o.get("id")),
                "coverage": bucket}
        # ⚠️ A stage outside the enum is NOT given a value: the row still renders (coverage),
        # but the dimension is missing and check_dashboard_coverage reports it — an
        # unparseable value must be loud, never guessed over.
        if o.get("stage") in _vd.STAGES:
            dims["stage"] = o["stage"]
        else:
            print("  !! WARNING: %s has stage %r, not a validate_data.STAGES value — the row "
                  "renders but carries no stage filter value (fix the record)"
                  % (_key, o.get("stage")))
        if o.get("id"):
            members[_key] = dims
        rows.append((o.get("id"),
            f'<div class="opp" data-rec="{esc(_key)}"{_dim_attrs(dims)}>'
            f'  <div class="opp-head">'
            f'    <div class="opp-title">{esc(str(o.get("title") or "Untitled role"))}'
            f'      <span class="opp-co">{esc(comp.get("name", o.get("company_id", "")))}</span>'
            f'      {jd}</div>'
            f'    <div class="opp-rail">{stage_rail(o)}</div>'
            f'  </div>'
            f'  <div class="opp-meta">{meta}</div>'
            f'  {nxt}{body}'
            f'</div>'))
    # REACHABLE (ADR-024, public #54): every member renders; a filtered list has no remainder.
    keys = ["opp:%s" % i for i, _h in rows if i]
    _cover_set("opportunities", keys, [])
    html_out = render_filtered_list("opportunities", OPP_DIMS, members, keys,
                                    "".join(h for _i, h in rows), "", cls="card opp-list")
    return html_out, counts


def render_your_move(items, links=None, cap=None, more_at=None, set_name=None) -> str:
    """The numbered ask list (callout groups, Decide, Ready-to-send). Since the one-artifact
    collapse it takes the same cap every working set takes: items are already ordered
    soonest-first before they arrive here, so the cap trims only the tail, and the remainder is
    counted and located rather than silently absent."""
    if not items:
        return '<div class="sub">Nothing is waiting on you right now.</div>'
    cap = cap if cap is not None else WORKING_SET_CAP
    shown, rest = items[:cap], items[cap:]
    if set_name:
        _cover_set(set_name,
                   ["opp:%s" % it[2] for it in shown if len(it) > 2 and it[2]],
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
        rec_attr = (' data-rec="%s"' % esc("opp:%s" % opp_id)) if opp_id else ""
        parts.append(
            f'<div class="ym-item"{rec_attr}><div class="ym-num">{n}</div><div>'
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
        _cover("prep:%s" % rel, "rendered", "preps")
        out.append('<details class="kdoc" data-rec="%s" data-full="1"><summary><strong>%s'
                   '</strong> <code class="fileref">%s</code></summary>'
                   '<div class="kdoc-body">%s</div></details>'
                   % (esc("prep:%s" % rel), md_inline(title), esc(rel), inner))
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
DRAFT_DIMS = (("sendability", "precondition.OPEN_STATES", tuple(sorted(_pre.OPEN_STATES))),
              ("medium", "validate_data.MEDIA", tuple(sorted(_vd.MEDIA))))
COVER_DIMS = (("sendability", "precondition.OPEN_STATES", tuple(sorted(_pre.OPEN_STATES))),)

_SEND_ORDER = {"sendable": 0, "unreadable": 1, "unresolved": 1, "blocked": 2}
_SEND_CHIP = {"sendable": ("scheduled", "ready"), "blocked": ("waiting", "held"),
              "unresolved": ("action", "unresolved"), "unreadable": ("action", "unreadable")}
_SEND_WHERE = {
    "sendable": "full text below — expand it and read it here, never off a transcript",
    "blocked": "held — waits on the other side; moves to ready by itself once the touch "
               "outcome flips",
    "unresolved": "needs YOU — rewrite the **Blocked until:** line as contact:<id> "
                  "outcome:<...>; nobody can say what this waits on",
    "unreadable": "needs YOU — rewrite the **Blocked until:** line as contact:<id> "
                  "outcome:<...>; the strict parser refuses it",
}


def render_message_list(set_name, kind, entries, states, filename, dims, empty_msg):
    """ONE list per file of the staged pair (public #48, stage 1): every OPEN entry — never
    a terminal one (public #29) — as a row carrying its precondition state chip, its meta
    line, where its full text lives, and, for a SENDABLE entry, the full body inline and
    collapsed. The body IS the decision being asked for, so it stays on the page (the
    collapse's one exception); everything else stays an index row.

    This replaces four surfaces that were the same entries under different headings:
    "Pending drafts" (index card + a second bodies card), "⏳ Waiting on someone else",
    "⏳ Cover letters held", and "⛔ Holds nobody can read". Their DISTINCTIONS survive as
    the sendability filter and as loudness on the row — an unreadable hold is still an
    `action` chip on a loud row, still counted needs-you by main() (public #37) — but an
    entry now renders in exactly one place.

    Ordered sendable → needs-you holds → blocked — the reading order. NEVER CAPPED: a
    filtered list renders every member (ADR-024 REACHABLE, public #54); the open set is
    bounded by what is actually pending, since sent and moot entries are terminal."""
    if not entries:
        return '<div class="sub">%s</div>' % empty_msg
    dim_names = [d for d, _src, _v in dims]

    def _st(title):
        return (states.get((filename, title)) or {}).get("state") or "sendable"

    entries = sorted(entries, key=lambda e: _SEND_ORDER.get(_st(e[0]), 9))
    keys = ["%s:%s" % (kind, t) for t, _b in entries]
    _cover_set(set_name, keys, [])
    members, out = {}, []
    for (title, blocks), key in zip(entries, keys):
        row = states.get((filename, title)) or {}
        st = row.get("state") or "sendable"
        dims_here = {"sendability": st}
        if "medium" in dim_names:
            dims_here["medium"] = row.get("medium") or "unknown"
        members[key] = dims_here
    for (title, blocks), key in zip(entries, keys):
        dims_here = members[key]
        st = dims_here["sendability"]
        cls, label = _SEND_CHIP.get(st, ("waiting", st))
        loud = st in _pre.NEEDS_HUMAN
        meta = _draft_meta_summary(blocks)
        medium_flag = ""
        if dims_here.get("medium") == "unknown":
            # Loud on the row: the line named no MEDIA value (or there is no line). The
            # filter files it under `unknown` — MEDIA's own word for this — never a guess.
            medium_flag = (' <span class="chip action" title="the **Medium:** line names no '
                           'validate_data.MEDIA value">medium: unknown</span>')
        body = ""
        if st == "sendable":
            body = ('<details class="kdoc"><summary>full text</summary>'
                    '<div class="kdoc-body">%s</div></details>'
                    % render_draft_entries([(title, blocks)], ""))
        out.append(
            '<div class="draft%s" data-rec="%s"%s><div class="draft-title">%s '
            '<span class="chip %s">%s</span>%s</div>'
            '%s%s'
            '<div class="sub">%s › %s · %s</div></div>'
            % (" ws-loud" if loud else "", esc(key), _dim_attrs(dims_here),
               md_inline(title), cls, label, medium_flag,
               ('<div class="draft-meta">%s</div>' % esc(meta)) if meta else "", body,
               '<code class="fileref">%s</code>' % esc(filename), esc(title[:60]),
               md_inline(_SEND_WHERE.get(st, st))))
    return render_filtered_list(set_name, dims, members, keys, "".join(out), "", cls="")


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
        rec_attr = (' data-rec="%s"' % esc("%s:%s" % (rec_kind, rel))) if rec_kind else ""
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
        out.append('<div class="draft" data-rec="%s"%s><div class="draft-title">%s%s%s</div>'
                   '<div class="sub"><code class="fileref">%s</code> · %d words · %s'
                   '</div></div>'
                   % (esc(key), _dim_attrs(members[key]), md_inline(title), flag,
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


def _clause_cell(text):
    """public #31, revised by #46: the row shows ONE clause of the SOURCE FIELD, and the
    full body is on the page too — collapsed, never a click away from being absent. A bare
    `<details>` alone would have hidden the #46 truncation behind a click rather than fixing
    it; a clause alone drops the memo the owner still needs on a phone. Returns HTML."""
    clause = _clause(text)
    cell = esc(clause)
    if clause != _flat(text):
        cell += ('<details class="ws-full"><summary>full</summary>'
                 '<div class="ws-full-body">%s</div></details>' % md_inline(text))
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
_DISP_RANK = {"rendered": 3, "remainder": 2, "terminal": 1}


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
# data twice.
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
    ("state", "needs-you"): "Needs you", ("state", "in-flight"): "In flight",
    ("owner", "you"): "Yours", ("owner", "run"): "The run's",
    ("coverage", "applied"): "Applied", ("coverage", "person"): "In play through a person",
    ("coverage", "nothing"): "Nothing sent",
    ("sendability", "sendable"): "Ready to send", ("sendability", "blocked"): "Held",
    ("sendability", "unreadable"): "Unreadable hold",
    ("sendability", "unresolved"): "Unresolved hold",
    ("window", "past"): "Call held", ("window", "later"): "Beyond the horizon",
    ("window", "undated"): "Undated",
    ("prep", "prepped"): "Prepped", ("prep", "owed"): "Prep owed",
    ("prep", "owed-partial"): "Prep partial", ("prep", "beyond-horizon"): "Beyond the horizon",
    ("prep", "unlinked"): "No counterparty",
    ("review", "due"): "Review due", ("review", "current"): "Current",
    ("review", "on-inbound"): "On inbound", ("review", "unscheduled"): "Unscheduled",
}


def _fid(set_name, dim, value):
    return "f-%s-%s-%s" % (set_name, dim, value)


def _dim_attrs(dims):
    """The `data-<dim>="<value>"` attributes for one row, in a fixed order."""
    return "".join(' data-%s="%s"' % (esc(d), esc(str(v)))
                   for d, v in sorted(dims.items()) if v is not None)


def _count_label(shown, pop):
    return "(%d)" % pop if shown == pop else "(%d shown of %d)" % (shown, pop)


def render_filter_group(set_name, dims, members, shown_keys):
    """The controls for one filtered list: `dims` is ((dim, enum_source, vocabulary), ...);
    `members` is {row key: {dim: value}} for the WHOLE population (before the cap);
    `shown_keys` the keys actually rendered — since public #54 every member, so each label
    reads "(N)"; the "(a shown of b)" form is kept only so a regression shows on the page
    as well as in the check. Records the group in the ledger and returns
    (controls_html, css). A value with zero population gets no chip."""
    shown = [k for k in shown_keys if k in members]
    ctl, css, active = [], [], []
    for dim, source, vocab in dims:
        name = "f-%s-%s" % (set_name, dim)
        bar = ['<span class="fdim">%s</span>' % esc(dim)]

        def _one(value, text, pop, sh):
            fid = _fid(set_name, dim, value)
            ctl.append('<input type="radio" name="%s" id="%s" class="fctl"%s>'
                       % (esc(name), esc(fid), " checked" if value == "all" else ""))
            bar.append('<label for="%s" data-flabel="%s:%s:%s:%d:%d">%s %s</label>'
                       % (esc(fid), esc(set_name), esc(dim), esc(value), sh, pop,
                          esc(text), _count_label(sh, pop)))
            active.append('#%s:checked ~ .fbar label[for="%s"]' % (fid, fid))
            if value != "all":
                css.append('  #%s:checked ~ .flist[data-flist="%s"] [data-rec]:not([data-%s="%s"])'
                           ' { display:none; }' % (fid, set_name, dim, value))

        _one("all", "All", len(members), len(shown))
        for value in vocab:
            pop = sum(1 for m in members.values() if m.get(dim) == value)
            if not pop:
                continue
            sh = sum(1 for k in shown if members[k].get(dim) == value)
            _one(value, _FILTER_VALUE_LABELS.get((dim, value), value), pop, sh)
        ctl.append('<div class="fbar">%s</div>' % "".join(bar))
    # One highlight rule per group (a selector list), not one per chip — measured 10 KB
    # of CSS at realistic volume before this consolidation.
    css.append('  %s { opacity:1; font-weight:600; border-color:var(--rail-now); '
               'color:var(--rail-now); }' % ",\n  ".join(active))
    COVERAGE["filters"][set_name] = {
        "dims": {d: {"source": src, "values": list(vocab)} for d, src, vocab in dims},
        "members": members,
        "shown": shown,
    }
    return "".join(ctl), "\n".join(css)


def render_filtered_list(set_name, dims, members, shown_keys, rows_html, more_html, cls=""):
    """Controls + the `.flist` container of rows + the remainder OUTSIDE it. The three are
    siblings, in that order, because the CSS reaches the list through `~`."""
    ctl, css = render_filter_group(set_name, dims, members, shown_keys)
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


def ws_row(item_html, who="", age="", due="", loud=False, rec=None, dims=None):
    """One working-set row. `item_html` is pre-rendered (it may carry a JD link); the
    other cells are plain text, escaped at render time. `rec` is the coverage key of the
    store record this row IS ("opp:<id>", "ask:<id>", "commit:<id>"), or None for a row
    derived from something that is not a record (a channel review, a sequence). `dims`
    is {dim: value} when the row lives in a filtered list (public #48, stage 1)."""
    return {"item": item_html, "who": who, "age": age, "due": due, "loud": loud, "rec": rec,
            "dims": dims or {}}


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
        if r.get("rec"):
            attrs += ' data-rec="%s"' % esc(r["rec"])
            if dims:
                attrs += _dim_attrs(r.get("dims") or {})
        out.append('<tr%s><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
                   % (attrs, r["item"],
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
        return render_filtered_list(set_name, dims, members,
                                    [r["rec"] for r in shown if r.get("rec")],
                                    "".join(out), more)
    return "".join(out) + more


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


# The sourcing table's one dimension — channels_due.REVIEW_STATES, the module that owns
# review state (public #48, stage 1). `retired` is in the vocabulary and always at zero
# here: retired channels are the second table.
SOURCING_DIMS = (("review", "channels_due.REVIEW_STATES", _cd.REVIEW_STATES),)


def render_sourcing_tables(active, retired):
    """(active_table_html, retired_html). Hand-rendered (not render_table) because the
    next-due cell carries chip HTML that md_inline would escape."""
    if active:
        out = ["<table><tr>"]
        for h in ("Channel", "Route", "Cadence", "Last reviewed", "Next review", "Yield"):
            out.append("<th>%s</th>" % h)
        out.append("</tr>")
        members, keys = {}, []
        for label, scope, route, cadence, lr, due_html, ytxt, state, cid in active:
            name = "<strong>%s</strong>" % esc(label)
            if scope:
                name += '<div class="sub">%s</div>' % esc(scope)
            key = ("chan:%s" % cid) if cid else None
            attrs = ""
            if key:
                keys.append(key)
                members[key] = {"review": state}
                attrs = ' data-rec="%s"%s' % (esc(key), _dim_attrs(members[key]))
            out.append("<tr%s>" % attrs + "".join(
                "<td>%s</td>" % cell
                for cell in (name, esc(route), esc(cadence), esc(lr), due_html, esc(ytxt)))
                + "</tr>")
        out.append("</table>")
        # Uncapped, as it always was: a strategy review reads every active channel.
        _cover_set("sourcing", keys, [])
        active_html = render_filtered_list("sourcing", SOURCING_DIMS, members, keys,
                                           "".join(out), "")
    else:
        active_html = '<div class="sub">No sourcing channels on file yet.</div>'

    # Retired channels stay NAMED (issue #148: silently dropping one reads as coverage,
    # and retirement is a two-effect decision — review queue AND alert sweep). Capped like
    # every list since the collapse; the records stay queryable in data/channels.jsonl.
    if retired:
        shown, rest = retired[:WORKING_SET_CAP], retired[WORKING_SET_CAP:]
        _cover_set("sourcing-retired", ["chan:%s" % c for _l, _s, _y, c in shown if c],
                   ["chan:%s" % c for _l, _s, _y, c in rest if c])
        rows = []
        for label, scope, ytxt, cid in shown:
            rows.append('<tr%s><td><strong>%s</strong>%s</td>'
                        '<td><span class="chip closed">retired</span></td><td>%s</td></tr>'
                        % ((' data-rec="%s"' % esc("chan:%s" % cid)) if cid else "",
                           esc(label),
                           '<div class="sub">%s</div>' % esc(scope) if scope else "",
                           esc(ytxt)))
        retired_html = ("<table><tr><th>Channel</th><th>Status</th><th>Lifetime yield</th>"
                        "</tr>%s</table>" % "".join(rows))
        if rest:
            retired_html += ('<div class="sub ws-more" data-more="sourcing-retired:%d">+%d '
                             'more retired — all still in '
                             '<code class="fileref">data/channels.jsonl</code>.</div>'
                             % (len(rest), len(rest)))
        retired_html += ('<div class="sub">Retiring a channel also stops the alert sweep '
                         'reading its digests — both effects follow '
                         '<code>relationship_status</code> in the record.</div>')
    else:
        retired_html = '<div class="sub">No retired channels.</div>'
    return active_html, retired_html


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
    """The row's ask: context (comp · location) and ONE clause of `next_action`, each part
    clamped BEFORE they are joined — the composed-string rule at `_clause`. The string
    returned here is display-ready; no caller may run `_clause` over it again (that is the
    measured defect: most role rows lost their action to the ". " this join inserted)."""
    ctx = [b for b in (_fmt_comp(o.get("comp")) if o.get("comp") else "",
                       _fmt_loc(o.get("location"))) if b]
    action = _clause(o.get("next_action") or "")
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
        if o.get("next_action"):
            bits.append(_clause(o["next_action"]))
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
    for c, state, _touch, _evidence in _ym.classify_channels(load_jsonl("channels.jsonl"),
                                                               messages):
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
            '<div class="card">%s</div>'
            % (len(unresolved), render_your_move(unresolved, links,
                                                 set_name="pipeline-unresolved")))
    if waiting:
        parts.append(
            '<h2 style="font-size:16px;margin-top:22px">⏳ Waiting on the other side '
            '<span class="tcount">%d</span></h2>'
            '<div class="sub" style="margin:-6px 0 10px">Blocked until the named contact '
            'reaches the outcome the role is waiting on. <strong>Not yours to do</strong> — '
            'moves to the list above by itself once the record shows it.</div>'
            '<div class="card">%s</div>'
            % (len(waiting), render_your_move(waiting, links, set_name="pipeline-waiting")))
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
            % (len(play_unresolved), render_your_move(play_unresolved, links,
                                                     set_name="pipeline-play")))
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
        _needs_human = _pre.NEEDS_HUMAN
    except Exception:
        _pre_rows, _states, _not_sendable, _terminal = [], {}, frozenset(), frozenset()
        _needs_human = frozenset()

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

    # public #29 — TERMINAL entries render in NEITHER list; the ledger says they ended.
    for _r in _pre_rows:
        if _r.get("state") in _terminal:
            _cover("%s:%s" % ("draft" if _r.get("file") == _DRAFTS_REL else "cover",
                              _r["title"]), "terminal",
                   "drafts" if _r.get("file") == _DRAFTS_REL else "covers")
    _drafts_active = [d for d in drafts if _pre_state(_DRAFTS_REL, d[0]) not in _terminal]
    _sendable = [d for d in _drafts_active if _pre_state(_DRAFTS_REL, d[0]) not in _not_sendable]
    # ⭐ public #37 — NOT_SENDABLE is two things. `blocked` waits on the other side (in
    # flight, muted); `unreadable`/`unresolved` wait on the OWNER, because nobody can say
    # what the hold is. They used to sit under "waiting on someone else" looking handled.
    # precondition.NEEDS_HUMAN owns the split; this only counts by it — since public #48
    # stage 1 the three groups are ONE list with a sendability filter, and an unreadable
    # hold is a loud row in it rather than a section of its own.
    _blocked = [d for d in _drafts_active
                if _pre_state(_DRAFTS_REL, d[0]) in _not_sendable
                and _pre_state(_DRAFTS_REL, d[0]) not in _needs_human]
    _unreadable = [d for d in _drafts_active if _pre_state(_DRAFTS_REL, d[0]) in _needs_human]
    drafts_html = render_message_list("drafts", "draft", _drafts_active, _states,
                                      _DRAFTS_REL, DRAFT_DIMS, "No pending drafts.")
    n_blocked = len(_blocked)

    # dev #169 — the covers list consults preconditions exactly as the drafts list does.
    _covers_active = [c for c in covers if _pre_state(_COVERS_REL, c[0]) not in _terminal]
    _covers_ready = [c for c in _covers_active if _pre_state(_COVERS_REL, c[0]) not in _not_sendable]
    _covers_held = [c for c in _covers_active
                    if _pre_state(_COVERS_REL, c[0]) in _not_sendable
                    and _pre_state(_COVERS_REL, c[0]) not in _needs_human]
    _covers_unreadable = [c for c in _covers_active
                          if _pre_state(_COVERS_REL, c[0]) in _needs_human]
    covers_html = render_message_list("covers", "cover", _covers_active, _states,
                                      _COVERS_REL, COVER_DIMS, "No cover letters pending.")
    n_covers_held = len(_covers_held)
    n_unreadable = len(_unreadable) + len(_covers_unreadable)

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
    # ⭐ THE PREP WINDOW (dev/audit 2026-09-02, build item 7). "Bounded by upcoming-call
    # volume" was a claim, not a bound: every file in conversations/ rendered in full,
    # and preps for calls already held — the bulk of a phone page, by bytes — were still
    # there because the archive step lived in a skill as a line the model was told to
    # follow after the call, and was not followed. The bound is now MECHANICAL: a prep
    # renders in full only for a call inside conversations.py's PREP-OWED horizon
    # [today, today + HORIZON_DAYS]; a past prep is an index row until archive_preps.py
    # (the hygiene step and the 0.36.0 migration) moves it; a prep beyond the horizon or
    # with an undated filename is an index row too, the undated one loudly.
    # The window is knowledge.prep_window's (public #48 stage 1 moved the if-chain that
    # lived here into the module that owns prep_date), and the three index sections are
    # ONE filtered index over knowledge.PREP_WINDOWS.
    _today_d = datetime.date.today()
    _preps_now, _preps_index = [], []
    for _p in _preps:
        _w = _kn.prep_window(os.path.basename(_p[1]), _today_d, _conv_mod.HORIZON_DAYS)
        if _w == "now":
            _preps_now.append(_p)
        else:
            _preps_index.append((_p[0], _p[1], _p[2], _w))
    # Undated first (loud), then held calls newest-first as knowledge_docs orders them,
    # then the far-off ones — so the cap trims the quietest tail.
    _preps_index.sort(key=lambda t: {"undated": 0, "past": 1, "later": 2}[t[3]])
    preps_full_html = render_knowledge_docs(_preps_now, "No call preps on file.")
    preps_index_html = render_prep_index(_preps_index, _conv_mod.HORIZON_DAYS)
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
                          _clause_cell(a.get("ask"))),
                       "you", _age_days(a.get("created")), a.get("act_by") or "",
                       rec=("ask:%s" % a["id"]) if a.get("id") else None)
                for a in system_asks]
    # Resolved asks have ENDED — the ledger says so, so the coverage check can tell an
    # expelled row from a lost one.
    for _a in _all_asks:
        if _a.get("resolved_on") and _a.get("id"):
            _cover("ask:%s" % _a["id"], "terminal", "asks")
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
            % (len(cfg_rows), render_ws(cfg_rows, "`data/asks.jsonl`", "",
                                        set_name="configure-asks")))
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
    _full_by_id = {o.get("id"): (o.get("next_action") or "") for o in _opp_rows}

    def _role_ws_rows(tuples):
        # `a` is DISPLAY-READY: _role_ask / the decide builder clamped each field before
        # joining. Never `_clause(a)` here — that re-parse is the measured #46 defect (the
        # composed-string rule at `_clause`). The full memo rides along, collapsed (#31).
        rows = []
        for t, a, oid in tuples:
            link = ym_links.get(oid)
            jd = (' <a class="opp-jd" href="%s" target="_blank" rel="noopener">JD ↗</a>'
                  % esc(link)) if link else ""
            full = _full_by_id.get(oid, "")
            body = ""
            if full and _clause(full) != _flat(full):
                body = ('<details class="ws-full"><summary>full</summary>'
                        '<div class="ws-full-body">%s</div></details>' % md_inline(full))
            rows.append(ws_row("<strong>%s</strong>%s — %s%s"
                               % (md_inline(t), jd, esc(a), body),
                               "you", "", _due_by_id.get(oid, ""),
                               rec=("opp:%s" % oid) if oid else None))
        return rows

    hand_role_rows = [ws_row("<strong>%s</strong> — %s"
                             % (md_inline(a.get("title") or a.get("id") or "?"),
                                _clause_cell(a.get("ask"))),
                             "you", _age_days(a.get("created")), a.get("act_by") or "",
                             rec=("ask:%s" % a["id"]) if a.get("id") else None)
                      for a in role_asks]
    now_ws = _role_ws_rows(role_decisions) + hand_role_rows
    decide_ws = _role_ws_rows(decide_rows)
    due_reviews_ws = [ws_row("<strong>%s</strong> — channel review due"
                             % esc(label), route, "", "now")
                      for (label, _scope, route, _cad, _lr, _dh, _y, st, _cid) in _src_active
                      if st == "due"]

    # ⭐ public #48, stage 1 — "in flight" is the `state` filter on the opportunity list,
    # not a section. your_move.attention_by_id is the ONE map both the list's labels and
    # this router count read, so the "N in flight" number and the "In flight (N)" chip
    # are the same query; the `⏳ In flight — not yours to do` table that rendered every
    # such role a second time is gone.
    _attention = _ym.attention_by_id(_opp_rows, OWNER_TOKEN)
    _owner = _ym.owner_by_id(_opp_rows, OWNER_TOKEN)
    n_pipe_flight = sum(1 for v in _attention.values() if v == "in-flight")

    n_pipe_needs = len(now_ws) + len(decide_ws) + len(due_reviews_ws)
    opp_alive_hint = any(o.get("status") not in _TERMINAL for o in _opp_rows)
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
                         "Nothing is waiting on you right now.", set_name="pipeline-now")))
    if decide_rows:
        pipe_parts.append(
            '<h2 id="phase-pipeline-decide">🔎 Decide — pursue or pass '
            '<span class="tcount">%d</span></h2>'
            '<div class="sub" style="margin:-6px 0 10px">Sourced roles whose verdict is '
            'still <code>undecided</code>. A decision owed to you is listed from the '
            'moment the record exists — the act-by date is a deadline, not a reveal date. '
            'Deciding moves the record and the row leaves by itself.</div>'
            '<div class="card">%s</div>'
            % (len(decide_rows), render_ws(decide_ws, "`data/opportunities.jsonl`", "",
                                           set_name="pipeline-decide")))
    if due_reviews_ws:
        pipe_parts.append(
            '<h2 id="phase-pipeline-reviews">🧭 Channel reviews due '
            '<span class="tcount">%d</span></h2>'
            '<div class="card">%s</div>'
            % (len(due_reviews_ws),
               render_ws(due_reviews_ws, "`data/channels.jsonl` (channels_due.py)", "")))
    pipe_parts.append(your_move_callouts_html)
    opp_list_html, opp_counts = render_opportunity_list(_opp_rows, _opp_comps,
                                                        attention=_attention, owner=_owner)
    if opp_counts["all"]:
        pipe_parts.append(
            '<h2 id="phase-pipeline-roles">🎯 Opportunities — where each role stands '
            '<span class="tcount">%d</span><span class="ct2f">· %d in flight</span></h2>'
            '<div class="sub" style="margin:-6px 0 10px"><strong>What lives here:</strong> '
            'every live role, once — needs-you first, then yours, then the run&rsquo;s. '
            'The bar under each title is the pipeline stage it has actually reached; the '
            'chips narrow the list by state, owner, stage and coverage (they combine), and '
            'every chip shows every row it counts.</div>'
            % (opp_counts["all"] - n_pipe_flight, n_pipe_flight)
            + stats_html + opp_list_html +
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
                               o.get("next_action_date") or "",
                               rec=("opp:%s" % o["id"]) if o.get("id") else None))
    # ⭐ public #48, stage 1 — the "⏳ Submitted — awaiting a response" table is gone: every
    # such role is the opportunity list under `coverage: applied`, with its applications
    # under Detail. The count stays the store query it always was (application_tables).
    if _apply_q:
        _q0 = _apply_q[0]
        _q0name = _opp_comps.get(_q0.get("company_id"), {}).get(
            "name", _q0.get("company_id", ""))
        # Clamp each field, then compose (the rule at `_clause`): clausing the joined
        # "<company> — <title>" cut it at its own " — " and left only the company.
        apply_clause = ("%s — %s — work the queue in session (views/applying.md)."
                        % (_clause(_q0name), _clause(_q0.get("title") or "")))
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
            % (len(apply_ws), render_ws(apply_ws, "`views/applying.md`", "",
                                        set_name="applying-queue")))
    if _submitted and apply_ws:
        apply_parts.append(
            '<div class="sub">%d application%s submitted and awaiting a response — each '
            'is in the pipeline section under <em>coverage: applied</em>.</div>'
            % (len(_submitted), "" if len(_submitted) == 1 else "s"))
    if _nothing and apply_ws:
        apply_parts.append(
            '<div class="sub">%d live role%s carried with nothing sent — the real gap; '
            'each is flagged on its row in the pipeline section.</div>'
            % (len(_nothing), "" if len(_nothing) == 1 else "s"))
    _emit("applying", len(apply_ws), len(_submitted), apply_clause,
          [("apply queue", "phase-applying-queue")] if apply_ws else [], apply_parts)

    # ── conversations ──────────────────────────────────────────────────────
    _today_iso = datetime.date.today().isoformat()
    _commits = load_jsonl("commitments.jsonl")
    # A commitment whose date has passed has ENDED for this page — placed as terminal so
    # the coverage check can tell "held" from "lost". Unplaceable dates stay loud below.
    for _c in _commits:
        _cd = str(_c.get("date") or "")
        if _c.get("id") and _vd.is_date(_cd) and _cd < _today_iso:
            _cover("commit:%s" % _c["id"], "terminal", "conversations")
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
                    "you", "", "unresolved", loud=True,
                    rec=("commit:%s" % c["id"]) if c.get("id") else None))
    else:
        for r in _conv_rows:
            if r["state"].endswith("-date"):
                # Unplaceable: the migration marker, or a date nobody can read — an
                # UNKNOWN, never a pass.
                conv_needs.append(ws_row(
                    "<strong>⚠️ %s</strong> — %s"
                    % (md_inline(r.get("title") or r.get("id") or "?"), esc(r["why"])),
                    "you", "", r.get("date") or "unresolved", loud=True,
                    rec=("commit:%s" % r["id"]) if r.get("id") else None))
            elif r["state"] in _conversations.NEEDS_YOU:
                _due = r.get("date") or ""
                if r.get("time"):
                    _due += " %s" % r["time"]
                conv_owed.append(ws_row(
                    "<strong>⛔ %s</strong> — %s"
                    % (md_inline(r.get("title") or r.get("id") or "?"), esc(r["why"])),
                    r.get("who") or "you", "", _due, loud=True,
                    rec=("commit:%s" % r["id"]) if r.get("id") else None))
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

    # The week list's one dimension (public #48, stage 1): the commitment's prep state,
    # conversations.report's own word inside the horizon and conversations.BEYOND_HORIZON
    # past it — that module owns both. When the scan failed there is no state to declare,
    # so the list renders unfiltered rather than with an invented value.
    _conv_state = {r["id"]: r["state"] for r in (_conv_rows or []) if r.get("id")}
    for c in sorted((r for r in _commits if _placed_future(r)),
                    key=lambda r: (str(r.get("date")), str(r.get("time") or ""))):
        due = str(c.get("date"))
        if c.get("time"):
            due += " %s" % c["time"]
        conv_flight.append(ws_row("<strong>%s</strong>"
                                  % md_inline(c.get("title") or c.get("id") or "?"),
                                  c.get("who") or "", "", due,
                                  rec=("commit:%s" % c["id"]) if c.get("id") else None,
                                  dims={"prep": _conv_state.get(c.get("id"),
                                                                _conv_mod.BEYOND_HORIZON)}))
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
            % (len(conv_owed), render_ws(conv_owed, "`views/conversations.md`", "",
                                         set_name="conversations-owed")))
    if conv_needs:
        conv_parts.append(
            '<h2 id="phase-conversations-unresolved">⚠️ Commitments with unresolved '
            'dates <span class="tcount">%d</span></h2>'
            '<div class="card">%s</div>'
            % (len(conv_needs), render_ws(conv_needs, "`data/commitments.jsonl`", "",
                                          set_name="conversations-unresolved")))
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
               render_ws(conv_flight, "`data/commitments.jsonl`", "",
                         set_name="conversations-week",
                         dims=None if _conv_rows is None else WEEK_DIMS)))
    if _preps_now:
        conv_parts.append(
            '<h2 id="phase-conversations-preps">📞 Call preps — in full '
            '<span class="tcount">%d</span></h2>'
            '<div class="sub" style="margin:-6px 0 10px">The one knowledge type that '
            'renders in full here (public #20: a prep must be readable the night before, '
            'anywhere) — bounded to calls inside the next %d days.</div>'
            '<div class="card">%s</div>'
            % (len(_preps_now), _conv_mod.HORIZON_DAYS, preps_full_html))
    if preps_index_html:
        conv_parts.append(
            '<h2 id="phase-conversations-preps-index">📁 Other call preps — index only '
            '<span class="tcount">%d</span></h2>'
            '<div class="sub" style="margin:-6px 0 10px">Held calls, calls beyond the '
            'horizon, and any note nothing can date. Bodies stay in the file tree.</div>'
            '<div class="card prep-past">%s</div>'
            % (len(_preps_index), preps_index_html))
    _emit("conversations", len(conv_needs) + len(conv_owed), len(conv_flight), conv_clause,
          ([("preps owed", "phase-conversations-owed")] if conv_owed else [])
          + ([("unresolved dates", "phase-conversations-unresolved")] if conv_needs else []),
          conv_parts)

    # ── outreach ───────────────────────────────────────────────────────────
    n_approvals = len(_sendable) + len(_covers_ready)
    # `a` is display-ready (the channel builder clamped the note) — never re-claused.
    touch_ws = [ws_row("<strong>%s</strong> — %s" % (md_inline(t), esc(a)),
                       "you", "", "")
                for t, a, _oid in channel_touches]
    untrig_ws = [ws_row("<strong>%s</strong> — application has no follow-up linked"
                        % esc(r.get("title") or r.get("opp_id") or "?"),
                        r.get("status") or "", _age_days(r.get("date")), "")
                 for r in _untrig_rows]
    # public #37 — an unreadable hold needs the OWNER, so it counts as needs-you.
    n_out_needs = n_approvals + _n_unblocked + len(untrig_ws) + len(touch_ws) + n_unreadable
    n_out_flight = n_blocked + n_covers_held + _n_waiting_seqs
    if _trep is None:
        out_clause = ("⛔ trigger scan failed — sequence and follow-up counts are "
                      "UNKNOWN, not zero; run trigger.py --check")
    else:
        bits = []
        if n_unreadable:
            bits.append("%d hold%s nobody can read — rewrite the Blocked until: line"
                        % (n_unreadable, "" if n_unreadable == 1 else "s"))
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
    # ⭐ public #48, stage 1 — ONE drafts list and ONE cover-letter list, each filtered by
    # sendability (and drafts by medium). "Waiting on someone else", "Cover letters held"
    # and "Holds nobody can read" were the same entries under second and third headings;
    # their counts survive (needs-you / in-flight, below and in the router), their
    # distinction is the filter, and an unreadable hold is a loud row with an `action`
    # chip (public #37's loudness, kept).
    if _drafts_active:
        out_parts.append(
            '<h2 id="phase-outreach-approvals">✉️ Drafts — awaiting your approval '
            '<span class="tcount">%d</span>%s</h2>'
            '<div class="sub" style="margin:-6px 0 10px">Nothing is ever sent without your '
            'explicit approval. The full text of every sendable message is right here — read '
            'it on this page, never off a transcript. Held messages wait on the other side '
            'and move to ready by themselves; a hold nobody can read waits on YOU.</div>'
            '<div class="card">%s</div>'
            % (len(_sendable) + len(_unreadable),
               (' <span class="ct2f">· %d held</span>' % n_blocked) if n_blocked else "",
               drafts_html))
    if _covers_active:
        out_parts.append(
            '<h2 id="phase-outreach-covers">📄 Cover letters — for applications you submit '
            'yourself <span class="tcount">%d</span>%s</h2>'
            '<div class="sub" style="margin:-6px 0 10px">Every claim traces to the claim '
            'union (presence/claims.md). You paste and submit these yourself — nothing is '
            'applied on your behalf. A held letter waits on a precondition; do not submit it '
            'yet.</div>'
            '<div class="card">%s</div>'
            % (len(_covers_ready) + len(_covers_unreadable),
               (' <span class="ct2f">· %d held</span>' % n_covers_held) if n_covers_held else "",
               covers_html))
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
    if n_unreadable:
        out_subs.append(("unreadable holds", "phase-outreach-approvals"))
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
    artifact_doc = ('<title>%s</title>\n<style>%s\n%s\n</style>\n%s'
                    % (html.escape(_title), CSS, "\n".join(_FILTER_CSS), body_inner))
    (ROOT / "views" / "dashboard_artifact.html").write_text(artifact_doc, encoding="utf-8")
    (ROOT / "dashboard.html").write_text(DASHBOARD_TOMBSTONE, encoding="utf-8")
    # The coverage ledger (Class C) — verified against the HTML by
    # check_dashboard_coverage.py; never trusted on its own.
    _ledger = {
        "generated_on": _t.isoformat(),
        "window": {"today": _t.isoformat(), "prep_horizon_days": _conv_mod.HORIZON_DAYS},
        "terminal_statuses": sorted(_TERMINAL),
        "records": COVERAGE["records"],
        "remainders": COVERAGE["remainders"],
        # public #48, stage 1 — every filtered list: its dimensions (each with the enum
        # that owns its vocabulary), every member's values, and what was shown.
        "filters": COVERAGE["filters"],
    }
    (ROOT / "views" / "dashboard_coverage.json").write_text(
        json.dumps(_ledger, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8")

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
