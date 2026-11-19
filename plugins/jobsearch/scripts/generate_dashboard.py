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
                                     (#phase-<name>). Documents render as
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
# dev #820 / public #175: the role lifecycle, `lifecycle.py` (`process_report` is the one text every
# surface prints about process state). Named here by file because a bare `import` is invisible to
# `publish_manifest.py`'s reachability closure.
import lifecycle as _lifecycle
import applications as _apps
import touches as _touches
import validate_data as _vd
import applying as _applying
import precondition as _pre
import conversations as _conv_mod
import config_keys as _ck
import warm_path as _warm_path                                   # dev #751: the warm-path next action
import funnel_report as _funnel                                  # dev #834 (M4, M5): the Network list's rows
import dashboard_actions as _actions                             # dev #915: the copy-as-prompt action blocks
import types

# dashboard-redesign A: the renderers live in the pure package `dashboard/` (design §10.2); this file is the
# LOADER, and calls them by their module (step B deleted the facade that re-exported their names here).
from dashboard import drafts as drafts_ui
from dashboard import ledger as ledger_ui
from dashboard import markup as markup_ui
from dashboard import network as network_ui
from dashboard import page as page_ui
from dashboard import pagedata as pagedata_ui
from dashboard import process as process_ui
from dashboard import rank as rank_ui
from dashboard import roles as roles_ui
from dashboard import targets as targets_ui


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


def _now():  # S2 (dashboard-redesign T0): a render's ONE clock, which main(run_id, now) pins in _LC_MAIN
    return _LC_MAIN["now"] or datetime.datetime.now()   # read here only by a helper called outside a render


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
        with open(os.path.join(str(ROOT), "user.json"), encoding="utf-8") as fh:
            name = ((_json.load(fh).get("identity") or {}).get("full_name") or "").strip()
    except Exception:
        pass
    try:
        with open(os.path.join(str(ROOT), "config.json"), encoding="utf-8") as fh:
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


def best_link(o):
    """`(url, employer_owned)`: the role's posting address and whether it is the employer's own.

    (1) The `employer_posting.url` when the field reads `confirmed` (the employer's own page, checked);
    (2) else `jd_url`; (3) else the first sighting that carried a URL; `(None, False)` when none. A link
    that is not employer-owned is an aggregator copy and the row says so (dev #817 / public #173, D817).

    ⭐ ONE RULE, MANY SURFACES. The rule is `your_move.role_link`, which the status panel and Your Move
    print too, so the `your-read` card carries the SAME link on all of them. On the live pipeline the
    sighting fallback is not decorative: it is the difference between 33 and 34 of 38 live roles having a
    reachable posting.
    """
    return _ym.role_link(o)


def opp_bucket(o, involvements=()):
    """The one COVERAGE bucket this role belongs to — applying.coverage's, by import. The
    three values were this file's own until public #48 stage 1 made coverage a declared
    filter dimension, and a dimension's vocabulary must have an owner outside the renderer
    (the `_CLOSED_STATUSES` lesson at the top of this file). `involvements` — ADR-031 B1 —
    is the global `involvements.jsonl` rows; optional, so a caller with none yet still gets
    the outreach-or-nothing half of the answer rather than crashing."""
    return _applying.coverage(o, involvements)


# The actions a group button on this page can carry; `_page_values` writes each one's `head` (dashboard-redesign D2,
# design §6.5). The filter chips' dimensions (`OPP_DIMS`, `DRAFT_DIMS`, `COVER_DIMS`, `_CROSS_CUTS`) went with the
# chips (D-6).
PICK_ACTIONS = ("work-through",)


# dev #820 / public #175: ONE lifecycle snapshot per render. `main()` loads it once and every helper reads
# it; a helper called on its own (a test, a script importing this module) loads the profile's own.
_LC_MAIN = {"active": False, "data": None, "error": None, "now": None}


def _lc_data(opps=None):
    """The `lifecycle.load_data` snapshot of this profile, with `opps` as its opportunity rows when
    given (so the rows a caller already enriched are the rows staged). An unreadable store is NOT an
    empty one: the error is kept in `_LC_MAIN["error"]` for `main()` to print, and the snapshot then
    holds no journal and no open items."""
    c = _LC_MAIN
    d = c["data"] if c["active"] else None
    if d is None:
        try:
            d = _lifecycle.load_data(str(ROOT))
        except _lifecycle.LifecycleError as e:
            c["error"] = str(e)
            d = {"root": str(ROOT), "opportunities": [], "items": [], "companies": [], "journal": [],
                 "config": {}}
        if c["active"]:
            c["data"] = d
    if opps is not None and d.get("opportunities") is not opps:
        d = dict(d, opportunities=opps)
    return d


def pursuit_by_id(opps, roles=None, stages=None):
    """{opp id: your_move.pursuit_state dict} for every opportunity in `opps` that carries an
    id - the ONE map the opportunity list's `pursuit` chips, its row chips, the reading
    order and the router's `applying` count all read, so the label population and the router
    number are one query. Reads the stores through the enriched `_applications` join, never a
    nested array.

    ⭐ dev #820 / public #175: a role nobody has read is not the candidate's decision ANYWHERE on the
    page. `pursuit_state` projects it as `new` (it is an undecided role), but only the lifecycle knows
    whether it is READ, so a `new` role whose stage is not `ready` is moved to its lifecycle
    partition option by `your_move.pursuit_with_stage` (an ALLOW-list, dev #899: `your-read`,
    `process-failure`, `waiting-intake`, `in-progress`, `removed`, `gone`, `held-for-company`, `folded`,
    `ended`, `not-sent` for a decided one, `unclassifiable` for no stage): it is counted under that
    option and `New` neither lists nor counts it. `stages` is {opp id: lifecycle.Stage}, derived from `opps` when the
    caller passes none. `roles` is accepted for the old signature and unused: the stage says it all."""
    if stages is None:
        stages = _ym.stage_by_id(opps, data=_lc_data(opps))
    out = {}
    for o in opps:
        if not o.get("id"):
            continue
        p = _ym.pursuit_state(str(ROOT), o, o.get("_applications") or [])
        out[o["id"]] = _ym.pursuit_with_stage(p, stages.get(o["id"]))
    return out


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


def _play_context():
    """A fresh play-engine `Context` of this profile. `build_page` loads ONE per render and passes it down
    (dashboard-redesign A: the module cache `_PLAY_CONTEXT_CACHE` kept the first profile's graph for every
    later render in the process)."""
    import plays as _plays_mod
    return _plays_mod.Context(str(ROOT))


def _play_next_step(o, ctx=None, today=None):
    import plays as _plays_mod
    ctx = ctx or _play_context()
    today = today or _now().date().isoformat()
    plan = ctx.plans_by_id.get(o.get("plan_id"))
    play = ctx.plays_by_id.get((plan or {}).get("play_id"))
    return _plays_mod.next_step(plan, play, o, ctx, today)


def _role_titles(ctx, data):
    """{role key: title} for every role the lifecycle counts: an opportunity's title, and for a role
    that exists only as open capture items, the title its first item names."""
    out = {o.get("id"): str(o.get("title") or o.get("id")) for o in (data.get("opportunities") or [])
           if isinstance(o, dict) and o.get("id")}
    for key, items in ctx.groups.items():
        _company, title = _lifecycle.item_company_title(items[0])
        out[key] = title or key
    return out


# ─────────────────────────────────────────────────────────────────────────────
# THE LOADER (dashboard-redesign A, design §10.2). `build_page` reads the stores, calls the owners and fills
# `PageData` with VALUES; the renderers in `dashboard/` read no file, no clock and no environment and import
# no flat script. Every value below is one a renderer used to fetch at render time.
# ─────────────────────────────────────────────────────────────────────────────

def _page_values(**values):
    """This render's page-wide values (`dashboard.pagedata.PageData`): the import-time vocabularies and the
    render's clock; `values` adds or overrides fields."""
    base = dict(now=_now(), currency=CURRENCY, terminal_statuses=_TERMINAL, plan_groups=_ym.PLAN_GROUPS,
                needs_human=_pre.NEEDS_HUMAN, queued_by_contact={}, pick_rows={},
                pick_heads={a: _actions.head(a) for a in PICK_ACTIONS})
    base.update(values)
    return pagedata_ui.PageData(**base)


def _lean_values(o, role_state, stage):
    """The your_move values `role_cards._lean_html` renders for one role (dev #713, dev #820): the lean of a
    `decide` role, the reason and the remedy (engine text, so through `plain()`) of a `your-read` one, the why
    of a process one; `{}` otherwise."""
    if role_state == "decide":
        return {"decide": _ym.decide_lean(o)}
    if role_state == _ym.GROUP_YOUR_READ and stage is not None:
        return {"kind": "your-read", "reason": _ym.your_read_reason(stage),
                "remedy": markup_ui.plain(_ym.YOUR_READ_REMEDY % (o.get("id") or "<id>"))}
    if role_state in (_ym.GROUP_FAILURE, _ym.GROUP_INTAKE, _ym.GROUP_PROGRESS) and stage is not None:
        return {"kind": "process", "why": _ym.group_why(role_state, stage, o)}
    return {}


def _role_facts(live, involvements, roles, stages, play_ctx, today_iso):
    """{id(role): what its card reads from the owners}: the posting link (`best_link`), the coverage bucket
    (`opp_bucket`), the derived play step (ADR-031 B4) and the lean values."""
    out = {}
    for o in live:
        oid = o.get("id")
        out[id(o)] = {"link": best_link(o), "bucket": opp_bucket(o, involvements),
                      "play": _play_next_step(o, play_ctx, today_iso),
                      "lean": _lean_values(o, roles.get(oid), stages.get(oid))}
    return out


def _role_list(s, opps, play_ctx, set_name="opportunities"):
    """One role list, `dashboard.roles.render_opportunity_list`, with this render's maps and each live role's
    values (`_role_facts`; the involvements store is read once per list, as it always was)."""
    live = [o for o in opps if o.get("status") not in s.pd.terminal_statuses]
    facts = (_role_facts(live, load_jsonl("involvements.jsonl"), s.roles, s.stages, play_ctx,
                         s.pd.now.date().isoformat()) if live else {})
    return roles_ui.render_opportunity_list(
        opps, s.opp_comps, facts, s.ledger, s.pd, attention=s.attention, owner=s.owner, pursuit=s.pursuit,
        roles=s.roles, set_name=set_name, warm=s.warm_by_opp, posting=s.posting, stages=s.stages)


def _queued_by_contact(states):
    """{contact id: the pending deferred item that will clear its queued draft} (Query or Citation C1, plant
    10), read once and only when a draft is queued: `deferred.py`'s own queue, never re-derived. Advisory:
    an unreadable queue is no note, never an error."""
    out = {}
    if any((r or {}).get("state") in ("unverified-cold", "unverified-silent") for r in states.values()):
        try:
            import deferred as _deferred_mod
            for r in _deferred_mod.replay(_deferred_mod.load()):
                if r.get("status") != "pending":
                    continue
                m_id = re.search(r"contact:(\S+)", str(r.get("what") or ""))
                if m_id:
                    out[m_id.group(1)] = r.get("id")
        except Exception:                                    # noqa: BLE001 — advisory only
            pass
    return out


def _network_text(rows, pd):
    """`pd.network_text` (dashboard-redesign D2b; Python writes every character, design 6.2): a head per group action,
    a record line per row with a tick box, and per group the tail counting its rows the levels leave off the page,
    from `dashboard.network.text_needed` over the very layout the renderer places."""
    need = network_ui.text_needed(network_ui.layout(rows, pd))
    pd.network_text = {"heads": {a: _actions.head(a) for a in need["actions"]},
                       "lines": {k: _actions.record_line(rec, name) for k, rec, name in need["lines"]},
                       "tails": {g: _actions.tail(n) for g, n in need["more"].items()}}


def _targets_text(s):
    """Targets' loader values (dashboard-redesign D2b, design §8): `pd.targets_ask` (`dashboard.targets.ask_ids` over
    each listed company's `company_kind`, its open roles' sighting channel types and whether one links an
    employer-owned posting); `pd.targets_not_raised`; and `pd.targets_text`, the heads, one record line per listed
    company and per name-pattern exclusion, and the tail."""
    tr, pd = s.tr or {}, s.pd
    listed, excluded = tr.get("rows") or [], tr.get("excluded") or []
    chans = [c for c in load_jsonl("channels.jsonl") if c.get("id")]
    ctype = {c["id"]: c.get("type") for c in chans}
    facts = {}
    for it in listed:
        roles = [o for o in s.opp_rows if o.get("company_id") == it["id"] and o.get("status") not in _TERMINAL
                 and any(isinstance(x, dict) for x in o.get("sightings") or [])]
        facts[it["id"]] = _ym.company_kind(s.opp_comps.get(it["id"]) or {}, chans) + (
            [ctype.get(x.get("channel_id")) for o in roles for x in o["sightings"] if isinstance(x, dict)],
            any(_ym.role_link(o)[1] for o in roles))
    pd.targets_ask = targets_ui.ask_ids(listed, facts)
    pd.targets_not_raised = (_ym.classify_companies(str(ROOT), _now().date().isoformat())["look-into-waiting"]
                             if s.tr is not None else 0)
    named = [e for e in excluded if e.get("how") == "name"]
    pd.targets_text = {"heads": {a: _actions.head(a) for a in ("target-yes", "target-no", "target-later",
                                                               "company-kind-staffing", "company-kind-employer")},
                       "lines": {it["id"]: _actions.record_line("company:%s" % it["id"], it["name"])
                                 for it in listed + named},
                       "tail": _actions.tail(len(tr.get("waiting") or []))}


def build_page(root, now, run_id=None):
    """`(html, ledger)`: the ONE page for the profile at `root` at the clock `now` (None reads the wall clock
    once), and its coverage `Ledger` (`ledger.doc` is the ledger file's object, `ledger.summary` the counts
    `main` prints). The stages run in the order the old `main` placed its ledger writes, because the
    strongest placement wins and the FIRST of two equal ones names the record's `where`.

    RE-ENTRANT for this file's own state: the ledger and the play Context are this call's (they were module
    state a second in-process render inherited); `_LC_MAIN` and `ROOT` are restored on return. ⚠️ NOT per-root
    for the owners: `profile.py` and `deferred.py` (and ~25 others) bind their paths at import, so the owner
    token, currency, warm-path and re-screen config and the deferred queue are the importing process's
    profile's; tests rebase them with `tests/_dashboard_src.bound_to` (S4b removes this)."""
    global ROOT
    saved_root, ROOT = ROOT, Path(root)
    _LC_MAIN.update(active=True, data=None, error=None, now=now if now is not None else datetime.datetime.now())
    try:
        s = types.SimpleNamespace(ledger=ledger_ui.Ledger(),
                                  run_id=run_id or os.environ.get("CLAUDESEARCH_RUN_ID") or None)
        s.pd = _page_values(run_id=s.run_id)
        _load_core(s)
        _load_staged(s)
        _load_outreach(s)
        _load_network(s)
        _load_today(s)
        _load_picks(s)
        _render_covers(s)
        _render_roles(s)
        s.first_drafts = drafts_ui.render_drafts_section(
            s.drafts_active, s.drafts_active_keys, s.states, s.drafts_rel, s.trigger, s.ledger, s.pd)
        _ledger_elsewhere(s)
        _render_network(s)
        return _assemble(s), s.ledger
    finally:
        _LC_MAIN.update(active=False, data=None, error=None, now=None)
        ROOT = saved_root


def _load_core(s):
    """The staged pair's text, the asks, roles and companies, and the ONE lifecycle snapshot and report."""
    s.drafts = drafts_ui.parse_drafts(read(_tree.rel("drafts")))
    # Cover letters are a distinct artifact from outreach drafts (added 2026-07-21).
    s.covers = [c for c in drafts_ui.parse_cover_letters(read(_tree.rel("cover_letters")))]
    # ⭐⭐ focus.md IS RETIRED AS A SOURCE OF STATE — dev #93 (public #21). Every surface below reads
    # a store.
    s.all_asks = load_jsonl("asks.jsonl")
    s.opp_rows = load_jsonl("opportunities.jsonl")
    s.opp_comps = {c["id"]: c for c in load_jsonl("companies.jsonl")}
    # ── dev #820 / public #175: ONE lifecycle snapshot for the whole render. Every role's stage, the
    # Your Move groups and the process block all read it, so they cannot disagree. An unreadable
    # snapshot is said on the page (PIPELINE NOT CHECKED), never rendered as an empty pipeline. Its `now` is
    # the clock. C7 (round-2 S5): the run generating this page (`s.run_id`) is not "overlong" against itself.
    s.lc_now = _now()
    s.lc_snapshot = _lc_data(s.opp_rows)
    s.lc_ctx = _ym.lifecycle_context(s.opp_rows, s.lc_now, s.lc_snapshot)
    s.lc_report, s.lc_error = None, _LC_MAIN["error"]
    if s.lc_error is None:
        try:
            s.lc_report = _lifecycle.process_report(s.lc_snapshot, s.lc_now, generating_run=s.run_id)
        except Exception as _e:                                      # noqa: BLE001 - said, never swallowed
            s.lc_error = "%s: %s" % (type(_e).__name__, _e)
    if s.lc_error:
        print("  !! WARNING: the role lifecycle could not be read (%s) - the page says PIPELINE NOT "
              "CHECKED" % s.lc_error)


def _load_staged(s):
    """Preconditions over the staged-message pair (issues #6/#13, dev #169, public #29): each entry's state
    row by its UNIQUE key, the open, held and queued subsets, the cover letters' list (rendered here, where
    the ledger has always placed it) and the cover-letter store's cascade counts (public #95)."""
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
        _terminal = _pre.TERMINAL
    except Exception:
        _pre_rows, _states, _terminal = [], {}, frozenset()

    def _pre_state(filename, key):
        return _states.get((filename, key), {}).get("state")

    # public #29 — TERMINAL entries render in NEITHER list; the ledger says they ended.
    for _r in _pre_rows:
        if _r.get("state") in _terminal:
            s.ledger.cover(_r["_key"], "terminal",
                           "drafts" if _r.get("file") == _DRAFTS_REL else "covers")
    _draft_keys = _ym.entry_keys("draft", [d[0] for d in s.drafts])
    _cover_keys = _ym.entry_keys("cover", [c[0] for c in s.covers])
    _dpairs = [(d, k) for d, k in zip(s.drafts, _draft_keys)
               if _pre_state(_DRAFTS_REL, k) not in _terminal]
    s.drafts_active = [d for d, _k in _dpairs]
    s.drafts_active_keys = [k for _d, k in _dpairs]
    # ⭐ public #37, Query or Citation C1 — who an open entry waits on (the owner, the other side, a mailbox
    # check) is `drafts.render_message_groups`' three groups since dashboard-redesign D2 (design §5).
    # dev #169 — the covers list consults preconditions exactly as the drafts list does.
    _cpairs = [(c, k) for c, k in zip(s.covers, _cover_keys)
               if _pre_state(_COVERS_REL, k) not in _terminal]
    s.covers_active = [c for c, _k in _cpairs]
    _covers_active_keys = [k for _c, k in _cpairs]
    s.states, s.pre_rows, s.drafts_rel = _states, _pre_rows, _DRAFTS_REL
    s.pd.queued_by_contact = _queued_by_contact(_states)
    s.covers_active_keys, s.covers_rel = _covers_active_keys, _COVERS_REL
    # public #95 — the terminal-transition cascade's data-store half. Advisory only.
    try:
        _ended_ctx = _ym.build_ended_context(str(ROOT))
        _letter_rows, _cl_errs, _cl_present = _apps.load_cover_letters(str(ROOT))
        s.n_letters_moot = sum(1 for _l in _letter_rows
                               if _ym.letter_state(_l, _ended_ctx)[0] == "moot")
        s.n_letters_used = sum(1 for _l in _letter_rows
                               if _ym.letter_state(_l, _ended_ctx)[0] == "used")
    except Exception:
        s.n_letters_moot = s.n_letters_used = 0


def _load_outreach(s):
    """The trigger-derived outreach numbers and the follow-up view's membership (dev #539 / public #133),
    the ENDED records' ledger lines, the role classification and the ONE pursuit map (dev #713, #494/#540),
    and the warm-path actions (dev #751)."""
    import trigger as _trig
    try:
        _trep = _trig.report(str(ROOT), today=_now().date().isoformat())
        _n_unblocked = sum(1 for s_ in _trep["sequences"].values()
                           if s_["state"] == "unblocked")
        _n_waiting_seqs = sum(1 for s_ in _trep["sequences"].values()
                              if s_["state"] == "waiting")
        _untrig_rows = _trep["untriggered"]
    except Exception as _e:
        # ⚠️ A failed scan must NEVER read as "nothing owed" — that is the missing-reads-as-empty trap.
        print("  !! WARNING: trigger scan failed (%s) — the outreach row cannot count "
              "sequences or unlinked applications; run trigger.py --check" % _e)
        _trep, _n_unblocked, _n_waiting_seqs, _untrig_rows = None, 0, 0, []
    s.trep, s.trigger = _trep, (None if _trep is None else (_n_unblocked, _n_waiting_seqs))
    _today_iso = _now().date().isoformat()
    # Records that have ENDED say so by omission, as before.
    for _a in s.all_asks:
        if _a.get("resolved_on") and _a.get("id"):
            s.ledger.cover("ask:%s" % _a["id"], "terminal", "asks")
    s.commits = load_jsonl("commitments.jsonl")
    for _c in s.commits:
        _cd = str(_c.get("date") or "")
        _c_cancelled = str(_c.get("status") or "") == "cancelled"
        if _c.get("id") and (_c_cancelled or (_vd.is_date(_cd) and _cd < _today_iso)):
            s.ledger.cover("commit:%s" % _c["id"], "terminal", "conversations")
    for _o in s.opp_rows:
        if _o.get("status") in _TERMINAL and _o.get("id"):
            s.ledger.cover("opp:%s" % _o["id"], "terminal", "opportunities")
    s.live = [o for o in s.opp_rows if o.get("status") not in _TERMINAL]
    s.attention = _ym.attention_by_id(s.opp_rows, OWNER_TOKEN, ctx=s.lc_ctx)
    s.owner = _ym.owner_by_id(s.opp_rows, OWNER_TOKEN)
    s.roles = _ym.role_states(s.opp_rows, OWNER_TOKEN, ctx=s.lc_ctx)
    s.stages = _ym.stage_by_id(s.opp_rows, ctx=s.lc_ctx)
    s.posting = _ym.posting_labels(s.opp_rows, OWNER_TOKEN, ctx=s.lc_ctx)
    s.pursuit = pursuit_by_id(s.live, s.roles, s.stages)
    s.new_opps = [o for o in s.live if (s.pursuit.get(o.get("id")) or {}).get("state") == "new"]
    s.read_opps = [o for o in s.live if (s.pursuit.get(o.get("id")) or {}).get("state") == "your-read"]
    s.unsent_opps = [o for o in s.live if (s.pursuit.get(o.get("id")) or {}).get("state") == "not-sent"]
    # jobsearch 0.88.0 (dev #915): a role the page renders under Opportunities or Applications is referenced
    # by the Network list (`page_opp_keys`), never given a second primary row.
    s.page_opp_keys = set("opp:%s" % o.get("id") for o in s.new_opps + s.unsent_opps + s.read_opps)
    # dev #751 -- the warm-path next action per role, DERIVED by warm_path.py (no stored copy). A failed
    # derivation must NEVER read as "nobody to ask": it is said on the page and in the log.
    s.warm_by_opp, s.warm_failed = {}, None
    try:
        _cfg_lookup = _ck.resolve_int(_profile.config(), _ck.SEARCH_WARM_LOOKUP_DAYS)
        for _a in _warm_path.derive(str(ROOT), today=_today_iso, lookup_days=_cfg_lookup):
            for _oid in _a["opp_ids"]:
                s.warm_by_opp[_oid] = _a
    except Exception as _e:                                          # noqa: BLE001 - said, never swallowed
        s.warm_failed = "%s: %s" % (type(_e).__name__, _e)
        print("  !! WARNING: the warm-path derivation failed (%s) - the cards carry no warm-path line"
              % s.warm_failed)


def _render_roles(s):
    """Opportunities to pursue, Needs your read (dev #820 N9), Applications to finish and Roles to
    reconsider (dev #761: CONDITIONAL and READ-ONLY, it flags and never reopens)."""
    # ADR-031 B4: ONE play Context per render, loaded when the first role list needs it.
    play_ctx = _play_context() if (s.new_opps or s.read_opps or s.unsent_opps) else None
    s.first_opps, s.opp_counts = "", dict(roles_ui._EMPTY_OPP_COUNTS)
    if s.new_opps:
        opp_list_html, s.opp_counts = _role_list(s, s.new_opps, play_ctx)
        s.first_opps = roles_ui.render_opportunities_section(opp_list_html, s.opp_counts["all"],
                                                             s.opp_counts["open"])
    s.first_read, s.n_read = "", len(s.read_opps)
    if s.read_opps:
        read_list_html, _read_counts = _role_list(s, s.read_opps, play_ctx, set_name="needs-read")
        s.first_read = roles_ui.render_read_section(read_list_html, s.n_read, _read_counts["open"])
    todo = _role_list(s, s.unsent_opps, play_ctx, set_name="applying-finish") if s.unsent_opps else None
    covers = (s.covers_html, len(s.covers_active), s.n_covers_open) if s.covers_active else None
    s.first_apply, s.n_apply = roles_ui.render_applications_section(todo, covers, s.n_letters_used,
                                                                     s.n_letters_moot)
    _rescreen, _rescreen_failed = {"flags": [], "unreadable": []}, None
    try:
        _rescreen = _profile.comp_rescreen_flags(s.opp_rows, _profile.load())
    except Exception as _e:                                          # noqa: BLE001 - said, never swallowed
        _rescreen_failed = "%s: %s" % (type(_e).__name__, _e)
        print("  !! WARNING: the re-screen flag check failed (%s) - the page says so instead of "
              "listing roles to reconsider" % _rescreen_failed)
    s.first_flags, s.n_flags = roles_ui.render_rescreen_flags(_rescreen["flags"], _rescreen["unreadable"],
                                                              _rescreen_failed, s.opp_comps, s.ledger)


def _ledger_elsewhere(s):
    """LEDGER: everything the page no longer renders lives ELSEWHERE, with its home (jobsearch 0.71.0)."""
    for o in s.live:
        if o.get("id") and "opp:%s" % o["id"] not in s.page_opp_keys:
            s.ledger.cover("opp:%s" % o["id"], "elsewhere", "panel")
    for a in s.all_asks:
        if a.get("id") and not a.get("resolved_on"):
            s.ledger.cover("ask:%s" % a["id"], "elsewhere", "panel")
    for c in s.commits:
        if c.get("id"):
            s.ledger.cover("commit:%s" % c["id"], "elsewhere", "panel")
    for ch in load_jsonl("channels.jsonl"):
        if ch.get("id"):
            s.ledger.cover("chan:%s" % ch["id"], "elsewhere", "panel")
    _preps, _kbs = knowledge_docs()
    for _p in _preps:
        s.ledger.cover("prep:%s" % _p[1], "elsewhere", "panel")


def _load_network(s):
    """The Network list's rows (dev #834 M4/M5; the communication plan since 0.88.0, dev #914/#915) and Targets to
    review, each from `your_move`, the one owner of membership, with the owed rows trigger.py already computed (a
    failed scan is never re-run as an empty one). Computed before any section renders (dashboard-redesign D1), because
    Today reads them and every section reads what Today took from it."""
    _t = _now().date()
    _net, _net_failed = {"rows": [], "sent_proposals": 0}, None
    try:
        _net = _funnel.network_rows(str(ROOT), _t.isoformat())
    except Exception as _e:                                          # noqa: BLE001 - said, never swallowed
        _net_failed = "%s: %s" % (type(_e).__name__, _e)
        print("  !! WARNING: the network list could not be computed (%s) - the page says so instead of "
              "listing what waits on you" % _net_failed)
    _plan, _plan_failed = {"rows": [], "expired_this_week": [], "failed": None}, _net_failed
    if _net_failed is None:
        try:
            _owed_in = ({"owed": s.trep["untriggered"], "expired": s.trep["expired"]} if s.trep is not None
                        else None)
            _plan = _ym.communication_plan(str(ROOT), _t.isoformat(), net=_net, owed=_owed_in)
            _plan_failed = _plan["failed"]
        except Exception as _e:                                      # noqa: BLE001 - said, never swallowed
            _plan_failed = "%s: %s" % (type(_e).__name__, _e)
            print("  !! WARNING: the communication plan could not be computed (%s) - the page says so instead of "
                  "listing what waits on you" % _plan_failed)
    _tr, _tr_failed = None, None
    try:
        _tr = _ym.targets_review(str(ROOT), _t.isoformat())
    except Exception as _e:                                          # noqa: BLE001 - said, never swallowed
        _tr_failed = "%s: %s" % (type(_e).__name__, _e)
        print("  !! WARNING: the targets list could not be computed (%s)" % _tr_failed)
    s.net, s.plan, s.plan_failed, s.tr, s.tr_failed = _net, _plan, _plan_failed, _tr, _tr_failed


def _load_today(s):
    """Today's sources and the counts its sentence names (dashboard-redesign D1; `dashboard.rank` and
    `dashboard.today` document every field), each in its owner's order. The two counts only the sentence needs
    (companies never raised, threads not yet due a nudge) are read only when every kind is empty."""
    pd, rep = s.pd, s.lc_report
    pd.today_drafts = [{"key": k, "name": d[0], "state": (s.states.get((s.drafts_rel, k)) or {}).get("state")}
                       for d, k in zip(s.drafts_active, s.drafts_active_keys)]
    pd.today_plan = [{"key": r["key"], "name": r["who"], "site": network_ui._who_site(r), "group": r["group"],
                      "axis": r.get("state"), "last_touch": r.get("last_touch")}
                     for r in (s.plan or {}).get("rows") or []]
    pd.today_roles = [{"key": "opp:%s" % o["id"], "name": str(o.get("title") or o["id"]),
                       "pursuit": (s.pursuit.get(o["id"]) or {}).get("state"),
                       "stage": getattr(s.stages.get(o["id"]), "name", None)} for o in s.live if o.get("id")]
    by_cid = {r["key"].split(":", 2)[2]: r for r in s.net["rows"] if r["group"] == "look-into"}
    pd.today_targets = [{"key": by_cid[it["id"]]["key"], "name": it["name"]}
                        for it in ((s.tr or {}).get("rows") or []) if it["id"] in by_cid]
    pd.quiet_days = _ym._cfg_int(str(ROOT), _ck.CHASE_AFTER_DAYS) + _ym._cfg_int(str(ROOT), _ck.NO_RESPONSE_AFTER_DAYS)
    listed = {it["id"] for it in ((s.tr or {}).get("rows") or []) if it["id"] in by_cid}
    held_listed = sum(1 for o in s.live if o.get("company_id") in listed
                      and getattr(s.stages.get(o.get("id")), "name", None) == "held-for-company"
                      and getattr(s.stages.get(o.get("id")), "detail", None) == "undecided")
    counts = {"checked": rep is not None, "snoozed": len((s.tr or {}).get("snoozed") or []), "held_listed": held_listed}
    if rep is not None:
        prog = [st.since for st in s.stages.values() if st.name in _lifecycle.PROGRESS_STAGES and st.since]
        counts.update(roles=rep.totals.get("roles") or 0, ready=rep.ready, waiting=rep.waiting,
                      in_progress=rep.in_progress, held_undecided=rep.held_company["undecided"],
                      held_watching=rep.held_company["watching"], held_passed=rep.held_company["passed"],
                      in_progress_oldest_days=(s.lc_now.date() - min(prog)).days if prog else None)
    pd.today_counts = counts
    if rank_ui.is_empty(rank_ui.kinds(pd)):
        counts["not_raised"] = _ym.classify_companies(str(ROOT), s.lc_now.date().isoformat())["look-into-waiting"]
        counts["not_due"] = _not_yet_due(s)


def _not_yet_due(s):
    """How many person threads have the owner's last message and are not yet due a nudge (axis `waiting`): the plan
    lists none of them, so the empty sentence counts them here (design §3.5)."""
    chase, today = _ym._cfg_int(str(ROOT), _ck.CHASE_AFTER_DAYS), s.lc_now.date().isoformat()
    listed = {r["subject"] for r in (s.plan or {}).get("rows") or []}
    people = {p.get("id") for p in load_jsonl("people.jsonl") if p.get("id") and p.get("status") != "merged"}
    talked = {t.get("person_id") for t in load_jsonl("touches.jsonl")} | {m.get("person_id")
                                                                         for m in load_jsonl("messages.jsonl")}
    n = 0
    for pid in sorted(x for x in talked if x in people and "person:%s" % x not in listed):
        try:
            axes = _ym.conversation_axis(str(ROOT), pid, today=today, window=chase)
        except Exception as e:                                       # noqa: BLE001 - said, never a crash
            print("  !! WARNING: the conversation of %s could not be read (%s: %s) - Today's sentence leaves it "
                  "out of the threads not yet due a nudge" % (pid, type(e).__name__, e))
            continue
        n += any(a == "waiting" for a, _e in axes.values())
    return n


def _load_picks(s):
    """`pd.pick_rows` (dashboard-redesign D2; `dashboard.levels`): for every row a tick box can name, its PAGE key ->
    (its ACTION record id, `action_block.record_line(id, name)`). Python writes every line here; a renderer only places
    it. A draft, a cover letter and a role: the page key is the action id (design §6.2's table). A plan row and a
    listed company: the row's own first action's `rec_id` (a to-record chat `net:chat:<id>` is `commit:<id>`, a
    company `net:look-into:<id>` is `company:<id>`), else its page key. Computed after Today's sources (`_load_today`)
    and before any section renders."""
    rows = {}

    def put(key, rec, name):
        rows[key] = (rec, _actions.record_line(rec, name))
    for (title, _b), key in list(zip(s.drafts_active, s.drafts_active_keys)) + list(zip(s.covers_active,
                                                                                        s.covers_active_keys)):
        put(key, key, title)
    for o in s.live:
        if o.get("id"):
            put("opp:%s" % o["id"], "opp:%s" % o["id"], str(o.get("title") or o["id"]))
    listed = {t["key"]: t["name"] for t in s.pd.today_targets or []}
    for r in list((s.plan or {}).get("rows") or []) + [r for r in s.net["rows"] if r["key"] in listed]:
        acts = r.get("actions") or []
        put(r["key"], acts[0]["rec_id"] if acts else r["key"], listed.get(r["key"]) or r.get("who") or r["key"])
    s.pd.pick_rows = rows


def _render_covers(s):
    """The cover letters' three groups (design §5, `drafts.render_message_groups`), rendered once the pick rows exist;
    `s.covers_html` and `s.n_covers_open` (its level-1 rows) go under Applications."""
    s.covers_html, s.n_covers_open = "", 0
    if s.covers_active:
        s.covers_html, s.n_covers_open = drafts_ui.render_message_groups(
            "covers", "cover", s.covers_active, s.covers_active_keys, s.states, s.covers_rel, s.ledger, s.pd,
            noun="cover letter", head_tag="h4")


def _render_network(s):
    """The title, then the Network list and Targets to review, from the rows `_load_network` computed."""
    s.pd.title = _dashboard_title()
    _net, _plan, _plan_failed, _tr, _tr_failed = s.net, s.plan, s.plan_failed, s.tr, s.tr_failed
    _network_text((_plan or {}).get("rows") or [], s.pd)
    s.first_network, s.n_network = network_ui.render_network_list(_plan, _plan_failed, s.page_opp_keys, s.ledger,
                                                                  s.pd)
    _targets_text(s)
    s.first_targets, s.n_targets = targets_ui.render_targets_list(_tr, _net["rows"], s.ledger, s.pd)
    if _tr_failed:
        # a raised company the targets list could not carry is still counted (one remainder), never lost
        _lost = [_r["key"] for _r in _net["rows"] if _r["group"] == "look-into"]
        s.ledger.cover_set("targets-review", [], _lost)
        s.first_targets = targets_ui.render_targets_failed(_tr_failed, _lost)
    s.pd.net_sent_proposals, s.pd.network_rel = _net["sent_proposals"], _tree.rel("network")


def _assemble(s):
    """The process state's three pieces, then the page; the ledger file's object and the printed summary go
    on the ledger. The process block's role titles, failure texts and alert line are read from the lifecycle."""
    rep = s.lc_report
    titles = _role_titles(s.lc_ctx, s.lc_snapshot) if (rep is not None and rep.failure_roles) else {}
    failure_texts = {k: _ym.failure_text(st) for k, st in rep.failure_roles} if rep is not None else {}
    alert_line = _lifecycle.alert_line(rep) if rep is not None else None
    parts = dict(drafts=s.first_drafts, network=s.first_network, targets=s.first_targets, read=s.first_read,
                 opps=s.first_opps, apply=s.first_apply, flags=s.first_flags,
                 n_drafts=len(s.drafts_active), n_opps=s.opp_counts["all"], n_apply=s.n_apply, n_flags=s.n_flags,
                 n_read=s.n_read, n_network=s.n_network, n_targets=s.n_targets,
                 process=process_ui.render_process_block(rep, s.lc_now, s.lc_error, titles, failure_texts, alert_line),
                 conservation=process_ui.render_conservation_line(rep),
                 alert=process_ui.render_pipeline_alert(rep, s.lc_error, alert_line))
    page_html = page_ui.render(s.pd, parts, s.ledger)
    s.ledger.summary = {"drafts": len(s.drafts_active), "opportunities": s.opp_counts["all"], "read": s.n_read,
                        "apply": s.n_apply, "pipeline": rep.start_line if rep is not None else None}
    s.ledger.doc = s.ledger.document(_now().date(), _conv_mod.HORIZON_DAYS, _TERMINAL)
    return page_html


def main(run_id=None, now=None):
    """Write the ONE artifact and its coverage ledger under views/ for this profile (`ROOT`) and print the
    summary. `now` pins the render's one clock (dashboard-redesign T0); `build_page` renders (step A)."""
    page_html, ledger = build_page(ROOT, now, run_id)
    # ── The output: the ONE artifact. Nothing outside views/ is written (dev #546). ──
    (ROOT / "views").mkdir(exist_ok=True)
    (ROOT / "views" / "dashboard_artifact.html").write_text(page_html, encoding="utf-8")
    # The coverage ledger (Class C) — verified against the HTML by check_dashboard_coverage.py;
    # never trusted on its own.
    (ROOT / "views" / "dashboard_coverage.json").write_text(
        json.dumps(ledger.doc, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8")

    print("Wrote views/dashboard_artifact.html (%d bytes)"
          % len(page_html.encode("utf-8")))
    print("  publish: ONE artifact — views/dashboard_artifact.html, to the URL in "
          "views/dashboard_artifact_url.txt. If that url file is absent, check "
          "check_dashboard_fresh.py --publish-state FIRST: never-published (no stamp "
          "either) means create it on first publish; url-missing (a stamp already exists) "
          "means RECOVER the URL via the Artifact tool's list action, never mint a new one")
    sm = ledger.summary
    print("  review-now: drafts %d · opportunities %d · your read %d · applications to finish %d  "
          "(everything else is ELSEWHERE in the ledger: the panel, /jobsearch:status)"
          % (sm["drafts"], sm["opportunities"], sm["read"], sm["apply"]))
    if sm["pipeline"] is not None:
        print("  pipeline: " + sm["pipeline"])
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
    import argparse
    _ap = argparse.ArgumentParser(description="Render views/dashboard_artifact.html.")
    _ap.add_argument("--run", metavar="ID", default=None,
                     help="the id of the run generating this page; that run is left out of the "
                          "overlong-run alert (a long healthy run must not alert about itself). "
                          "CLAUDESEARCH_RUN_ID is the same, for a wrapper that regenerates the page.")
    main(run_id=_ap.parse_args().run)
