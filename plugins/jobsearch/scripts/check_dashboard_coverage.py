#!/usr/bin/env python3
"""Does the published page ACCOUNT FOR every record — render nothing its window excludes —
and keep its row set whole under every filter?

⭐ THE TWO-SIDED COVERAGE CONTRACT (dev/audit 2026-09-02, Class C)
-------------------------------------------------------------------
COVERAGE: every record in the row-backed stores is, on the generated page, exactly one of
  * RENDERED    — a row carries `data-rec="<kind>:<id>"`;
  * REMAINDER   — trimmed by a working-set cap into a "+K more" line whose K counts it
                  (`data-more="<set>:<K>"`), so the reader knows it exists and where;
  * TERMINAL    — it has ENDED (a terminal opportunity status, a resolved ask, a commitment
                  whose date has passed, a sent or moot staged message) and the page says so
                  by omission.
Anything in none of those is a record the page LOST — silently, which is the shape of the
defect this closes: a renderer's private "closed" set dropped every backlog row (most of
the pipeline on the profile measured) with nothing on the page or in any count to say so.

SCOPE: nothing renders that the window excludes — a terminal opportunity must not appear as
a row, and a call prep renders IN FULL only inside the PREP-OWED horizon.

⭐ MEMBERSHIP UNDER NARROWING (public #48, stage 1 — the per-section filters)
------------------------------------------------------------------------------
Filtering is CSS visibility only: the HTML row set is identical in every filter state. That
is the same contract one level down, so it is checked HERE rather than by a second script
that would grow a second meaning. For every filtered list the ledger declares:
  * DIMENSION COMPLETE — every `[data-rec]` row in the list carries every dimension the
                  ledger declares for it, with a value in the ledger's vocabulary, and that
                  vocabulary equals its ENUM SOURCE (the owning module's constant, resolved
                  here independently). Catches a row visible only under `all`, which is the
                  `backlog` shape one level down.
  * COUNT AGREES — every label carries both numbers (rendered and population); each equals
                  the rows carrying that value / the members declared with it, the per-value
                  counts sum to `all`, and the population reconciles to the ledger's placed
                  records (rendered here + this set's counted remainder). The router's
                  pipeline "in flight" number must equal the opportunity list's own label.
  * EXACTLY ONCE — ADVISORY this pass. `data-rec` occurrences are counted as a LIST (the
                  old `set(...)` collapsed duplicates silently, which is why one role could
                  render in three places and nothing said so). Today's page legitimately
                  renders a queue row AND a subject-list row for the same record; stage 2 of
                  public #48 turns queue rows into references, which is what makes this
                  satisfiable. Until then it is reported, never a gap: its red is a
                  measurement, not a wedge.
                  ⚠️ HEADS-UP FOR WHOEVER BUILDS STAGE 2 (dev/audit 2026-09-03): this count
                  is driven by `_REC_RE` alone, which matches `data-rec="..."` and nothing
                  else. If a stage-2 reference renders under a different attribute (e.g. a
                  `data-ref="..."` pointing at the subject row instead of a second
                  `data-rec`), it is invisible to `_REC_RE` and this measurement silently
                  undercounts — the exact "a missing thing reads as an empty thing" shape
                  this file exists to close, in the mechanism meant to catch it. Before
                  turning this from advisory to a gap, confirm every reference stage 2
                  renders still carries `data-rec`, or extend `_REC_RE` (and re-derive
                  `rec_list` accordingly) to see the new shape.

⭐ REACHABLE (public #54 / #58 point 3 — counted is not reachable)
--------------------------------------------------------------------
The 0.37.0 page hid three candidate-owned roles and this check said CLEAN: the working-set
cap trimmed them into the opportunity list's "+K more" remainder, COVERAGE was satisfied
(every record accounted for), and nothing asked whether a reader could GET TO one.
Under CSS-only narrowing a filtered list has ONE rendered row set, so a trimmed row is
reachable under no filter state, and a chip whose population counts it promises a row
selecting the chip cannot show. So, for every filtered list the ledger declares:
  * TRIMMED BEHIND A FILTER — the list has no remainder: no `remainders` entry in the
                  ledger, no `data-more="<set>:K"` on the page, and no record whose final
                  disposition is a remainder in that set. REMAINDER stays a legitimate
                  disposition for an UNFILTERED working set (one ordering, sorted then
                  capped, the tail named), never for a filtered one.
  * UNREACHABLE UNDER FILTER — for every chip, the rows on the page carrying its value
                  equal the members the ledger counts with it (shown == population),
                  computed from the HTML and the ledger independently, so a chip can never
                  count a record no filter state can reach.
These are independent of COUNT AGREES on purpose: a label that honestly reads "(2 shown
of 17)" passes COUNT AGREES and is exactly the page this side exists to refuse.

## Verify the artifact, not the plan (CLAUDE.md trap 6)

`generate_dashboard.py` writes a ledger beside the artifact (`views/dashboard_coverage.json`)
saying where it placed each record and what every filtered list holds. That ledger is a
CLAIM. This check reads the STORES for what exists, the LEDGER for what the renderer
believes it did, and the HTML for what is actually on the page — and fails on any
disagreement among the three. It prints `covered N of M` and refuses to be green when that
does not add up (check_engine_purity's "scanned N of M", copied on purpose).

⚠️ Deliberately SEPARATE from check_dashboard_fresh.py, which is about bytes and stamps —
whether the page is behind its sources or the published view behind the repo. Membership is
a different question with a different remedy, and one check must not grow a second meaning.

## Absence reads as itself

No artifact and no ledger: nothing has been generated yet → `NOT CHECKED`, exit 0 (a new
profile is not nagged). An artifact with NO ledger: generated by a renderer that keeps
none → FAIL, regenerate. A ledger with no `filters` block: generated by a renderer older
than the filters (0.36.0) → FAIL, regenerate. A ledger whose window does not name today's
date is still checked against its OWN generation day — staleness is check_dashboard_fresh's
dimension.

Usage:
    python3 scripts/check_dashboard_coverage.py            # exit 1 on any gap
    python3 scripts/check_dashboard_coverage.py --verbose  # list every placement

Python 3.9+. Standard library only.
"""

import argparse
import collections
import datetime
import html as _html
import importlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _root import profile_root                                      # noqa: E402
import _tree                                                        # noqa: E402
import channels_due as _cd                                          # noqa: E402
import knowledge as _kn                                             # noqa: E402
import precondition as _pre                                         # noqa: E402
import validate_data as _vd                                         # noqa: E402

LEDGER_NAME = "dashboard_coverage.json"
_REC_RE = re.compile(r'data-rec="([^"]+)"')
_FULL_REC_RE = re.compile(r'data-rec="([^"]+)" data-full="1"')
_MORE_RE = re.compile(r'data-more="([^"]+):(\d+)"')
# A filtered list's container, a row's opening tag, and a filter label.
_FLIST_RE = re.compile(r'<div class="[^"]*\bflist\b[^"]*" data-flist="([^"]+)">')
_ROW_RE = re.compile(r'<(\w+)\b([^>]*?)\sdata-rec="([^"]+)"([^>]*)>')
_DATA_ATTR_RE = re.compile(r'\sdata-([a-z][a-z0-9-]*)="([^"]*)"')
_LABEL_RE = re.compile(r'<label for="([^"]+)" data-flabel="([^"]+)">(.*?)</label>', re.S)
_DIV_RE = re.compile(r'<div\b|</div>')
# ⭐ dev/audit 2026-09-03 — the digit group is OPTIONAL on purpose: render_router_rows()
# renders an empty `<span class="ct2"></span>` when n_flight is 0 (no "N in flight" text at
# all), which is a legitimate, common state, not markup drift. The old pattern hardcoded the
# digit as required, so this same "0 in flight" case matched nothing and the ROUTER DISAGREES
# comparison below silently never ran for it — a router that claimed 0 while the opportunity
# list actually held some in-flight members would have passed CLEAN. Matching the span
# unconditionally (digit optional) closes that gap too, not just the loud-failure one.
_ROUTER_FLIGHT_RE = re.compile(r'<span class="ct2">(?:(\d+) in flight)?</span><a class="ph" '
                               r'href="#phase-pipeline"')
# The anchor alone, with none of the ct2/flight markup around it required. Used only to tell
# apart "the pipeline phase legitimately collapsed to nothing" (this doesn't match either —
# NOT CHECKED, the row plain doesn't exist) from "the row is there but its in-flight markup
# changed shape" (this matches, _ROUTER_FLIGHT_RE above does not — a GAP, never a silent skip).
_ROUTER_PIPELINE_ANCHOR_RE = re.compile(r'<a class="ph" href="#phase-pipeline"')
# The modules a ledger may name as a vocabulary's owner. A source outside this list is a
# gap, not an import: the check resolves enums, it does not run arbitrary code.
_ENUM_MODULES = frozenset({"validate_data", "your_move", "applying", "precondition",
                           "knowledge", "channels_due", "conversations"})


def _jsonl(root, name):
    path = os.path.join(root, "data", name)
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    except OSError:
        pass
    return rows


def expected_records(root, today=None):
    """{key: record-ish dict} for every record the contract covers. Preps carry their
    date under 'date' (None when undated). Staged messages come through precondition's
    one reader (state per entry); channels through channels_due's one classifier — the
    owning modules, never a second derivation here."""
    today = today or datetime.date.today()
    exp = {}
    for o in _jsonl(root, "opportunities.jsonl"):
        if o.get("id"):
            exp["opp:%s" % o["id"]] = {"kind": "opp", "status": o.get("status")}
    for a in _jsonl(root, "asks.jsonl"):
        if a.get("id"):
            exp["ask:%s" % a["id"]] = {"kind": "ask", "resolved": bool(a.get("resolved_on"))}
    for c in _jsonl(root, "commitments.jsonl"):
        if c.get("id"):
            exp["commit:%s" % c["id"]] = {"kind": "commit", "date": str(c.get("date") or "")}
    d = _tree.path(root, "call_preps")
    if os.path.isdir(d):
        sub = os.path.relpath(d, root)
        for name in sorted(os.listdir(d)):
            if name.endswith(".md") and name.lower() not in _kn.KB_EXEMPT:
                rel = "%s/%s" % (sub, name)
                exp["prep:%s" % rel] = {"kind": "prep", "date": _kn.prep_date(name)}
    drafts_rel, covers_rel = _tree.rel("drafts"), _tree.rel("cover_letters")
    for r in _pre.report(root):
        kind = "draft" if r.get("file") == drafts_rel else (
            "cover" if r.get("file") == covers_rel else None)
        if kind and r.get("title"):
            exp["%s:%s" % (kind, r["title"])] = {"kind": kind, "state": r.get("state")}
    for c, state, _detail in _cd.review_rows(_jsonl(root, "channels.jsonl"), today):
        if c.get("id"):
            exp["chan:%s" % c["id"]] = {"kind": "chan", "review": state}
    return exp


def _is_terminal(meta, terminal, today):
    k = meta["kind"]
    if k == "opp":
        return meta.get("status") in terminal
    if k == "ask":
        return bool(meta.get("resolved"))
    if k == "commit":
        return _vd.is_date(meta.get("date")) and meta["date"] < today.isoformat()
    if k in ("draft", "cover"):
        return meta.get("state") in _pre.TERMINAL
    return False        # preps and channels never end by omission


def _resolve_enum(source):
    """The vocabulary a ledger names, resolved from the owning module — or None."""
    mod, _sep, attr = str(source).partition(".")
    if mod not in _ENUM_MODULES or not attr:
        return None
    try:
        return set(getattr(importlib.import_module(mod), attr))
    except (ImportError, AttributeError, TypeError):
        return None


def _flist_regions(page):
    """{set name: html inside its `.flist` container}. Depth-counted over <div> tags so a
    row's own nested markup never ends the region early."""
    out = {}
    for m in _FLIST_RE.finditer(page):
        depth, pos, end = 1, m.end(), None
        for t in _DIV_RE.finditer(page, m.end()):
            depth += 1 if t.group() == "<div" else -1
            if depth == 0:
                end = t.start()
                break
        out[_html.unescape(m.group(1))] = page[pos:end] if end is not None else page[pos:]
    return out


def _rows_in(region):
    """[(key, {data-attr: value})] for every `[data-rec]` row in a region, in order."""
    rows = []
    for m in _ROW_RE.finditer(region):
        attrs = dict((k, _html.unescape(v))
                     for k, v in _DATA_ATTR_RE.findall(" " + m.group(2) + " " + m.group(4)))
        rows.append((_html.unescape(m.group(3)), attrs))
    return rows


def _count_label(shown, pop):
    return "(%d)" % pop if shown == pop else "(%d shown of %d)" % (shown, pop)


def check_filters(page, ledger, exp, remainders, more_on_page=None):
    """(gaps, summary_lines) for MEMBERSHIP UNDER NARROWING — DIMENSION COMPLETE and
    COUNT AGREES over every filtered list the ledger declares — and for REACHABLE:
    TRIMMED BEHIND A FILTER and UNREACHABLE UNDER FILTER (public #54)."""
    more_on_page = more_on_page or {}
    gaps, lines = [], []
    groups = ledger.get("filters")
    if groups is None:
        return ["LEDGER PREDATES FILTERS — views/%s has no `filters` block, so the page was "
                "generated by a renderer older than the per-section filters; regenerate with "
                "the current generate_dashboard.py" % LEDGER_NAME], []
    regions = _flist_regions(page)
    for name in sorted(set(regions) - set(groups)):
        gaps.append("FILTERED LIST NOT IN LEDGER — the page carries a `.flist` %r the ledger "
                    "declares nothing about" % name)
    for name in sorted(set(groups) - set(regions)):
        gaps.append("FILTERED LIST NOT ON PAGE — the ledger declares list %r and the page "
                    "has no `.flist` for it" % name)
    labels = {}
    for fid, spec, text in _LABEL_RE.findall(page):
        try:
            set_name, dim, value, sh, pop = spec.split(":")
            labels[(set_name, dim, value)] = (int(sh), int(pop), re.sub(r"<[^>]+>", "", text).strip())
        except ValueError:
            gaps.append("LABEL UNREADABLE — data-flabel=%r on label %r" % (spec, fid))
    n_dims = n_labels = 0
    for name in sorted(set(groups) & set(regions)):
        g = groups[name]
        dims = g.get("dims") or {}
        members = g.get("members") or {}
        shown_claim = list(g.get("shown") or [])
        vocab = {}
        # DIMENSION COMPLETE, ledger side: the vocabulary IS the enum source's.
        for dim, spec in sorted(dims.items()):
            n_dims += 1
            declared = list(spec.get("values") or [])
            resolved = _resolve_enum(spec.get("source"))
            if resolved is None:
                gaps.append("VOCABULARY SOURCE UNRESOLVED — list %s dimension %s names %r, "
                            "which is not a constant in an owning module"
                            % (name, dim, spec.get("source")))
            elif set(declared) != resolved or len(set(declared)) != len(declared):
                gaps.append("VOCABULARY DRIFT — list %s dimension %s declares %s but %s is %s"
                            % (name, dim, sorted(declared), spec.get("source"),
                               sorted(resolved)))
            vocab[dim] = set(declared)
        for key, vals in sorted(members.items()):
            if key not in exp:
                gaps.append("FILTER MEMBER NOT A RECORD — list %s counts %s, and no such "
                            "record exists" % (name, key))
            for dim in dims:
                if vals.get(dim) not in vocab.get(dim, set()):
                    gaps.append("MEMBER VALUE OUTSIDE VOCABULARY — list %s member %s has %s=%r"
                                % (name, key, dim, vals.get(dim)))
        # DIMENSION COMPLETE, page side: every row, every dimension, a vocabulary value that
        # matches what the ledger claimed for it.
        rows = _rows_in(regions[name])
        row_keys = [k for k, _a in rows]
        row_vals = {}
        for key, attrs in rows:
            if key not in members:
                gaps.append("ROW NOT A MEMBER — list %s renders %s, which its ledger entry "
                            "does not count" % (name, key))
                continue
            row_vals[key] = {}
            for dim in dims:
                v = attrs.get(dim)
                if v is None:
                    gaps.append("DIMENSION MISSING — list %s row %s carries no data-%s, so it "
                                "is visible only under `all`" % (name, key, dim))
                elif v not in vocab.get(dim, set()):
                    gaps.append("VALUE OUTSIDE VOCABULARY — list %s row %s has data-%s=%r"
                                % (name, key, dim, v))
                elif v != members[key].get(dim):
                    gaps.append("ROW DISAGREES WITH LEDGER — list %s row %s has data-%s=%r; "
                                "the ledger says %r" % (name, key, dim, v,
                                                        members[key].get(dim)))
                row_vals[key][dim] = v
        if sorted(row_keys) != sorted(shown_claim):
            gaps.append("SHOWN DISAGREES — list %s: the ledger says %d row(s) shown, the page "
                        "carries %d" % (name, len(shown_claim), len(row_keys)))
        k_rem = int(remainders.get(name) or 0)
        if len(members) != len(row_keys) + k_rem:
            gaps.append("POPULATION DOES NOT RECONCILE — list %s counts %d member(s) but the "
                        "page carries %d row(s) and the remainder trims %d"
                        % (name, len(members), len(row_keys), k_rem))
        # REACHABLE, ledger and page side: a filtered list never trims. Either signal alone
        # is a gap — the ledger's remainder count and the page's "+K more" line are two
        # claims, and a regression may carry one without the other.
        k_page = more_on_page.get(name)
        if k_rem or k_page:
            gaps.append("TRIMMED BEHIND A FILTER — list %s trims %s record(s) into a "
                        "remainder (ledger +%s, page +%s); a member of a filtered list is "
                        "reachable only if rendered, so a filtered list has no remainder "
                        "(ADR-024 REACHABLE, public #54)"
                        % (name, k_rem or k_page, k_rem, "none" if k_page is None else k_page))
        # COUNT AGREES: every label, both numbers, against the rows and the members.
        for dim in sorted(dims):
            expect = {"all": (len(row_keys), len(members))}
            for v in vocab[dim]:
                pop = sum(1 for m in members.values() if m.get(dim) == v)
                sh = sum(1 for k in row_keys if row_vals.get(k, {}).get(dim) == v)
                if pop:
                    expect[v] = (sh, pop)
            # REACHABLE, chip side: shown == population for every chip, from the HTML rows
            # and the ledger members independently — never from the label, which may
            # honestly say "(2 shown of 17)" and still describe an unreachable fifteen.
            for v, (sh, pop) in sorted(expect.items()):
                if sh != pop:
                    gaps.append("UNREACHABLE UNDER FILTER — list %s chip %s=%s counts %d "
                                "member(s) and the page renders %d of them; a member with no "
                                "row is reachable under no filter state (public #58 point 3)"
                                % (name, dim, v, pop, sh))
            for v, (sh, pop) in sorted(expect.items()):
                lab = labels.get((name, dim, v))
                if lab is None:
                    gaps.append("LABEL MISSING — list %s dimension %s has %d member(s) with "
                                "value %r and no chip for it" % (name, dim, pop, v))
                    continue
                n_labels += 1
                l_sh, l_pop, text = lab
                if (l_sh, l_pop) != (sh, pop):
                    gaps.append("COUNT DISAGREES — list %s chip %s=%s says %d shown of %d; the "
                                "page carries %d row(s) and the ledger %d member(s) with it"
                                % (name, dim, v, l_sh, l_pop, sh, pop))
                if not text.endswith(_count_label(l_sh, l_pop)):
                    gaps.append("LABEL TEXT DISAGREES — list %s chip %s=%s reads %r but its "
                                "counts are %d shown of %d" % (name, dim, v, text, l_sh, l_pop))
            for v in sorted(vocab[dim]):
                if v not in expect and (name, dim, v) in labels:
                    gaps.append("LABEL WITHOUT MEMBERS — list %s has a chip for %s=%s and no "
                                "member carries it" % (name, dim, v))
            sums = [sum(x[i] for v, x in expect.items() if v != "all") for i in (0, 1)]
            if tuple(sums) != expect["all"]:
                gaps.append("COUNTS DO NOT SUM — list %s dimension %s: per-value counts sum to "
                            "%d shown of %d, `all` is %d of %d"
                            % (name, dim, sums[0], sums[1], expect["all"][0], expect["all"][1]))
    # The router's pipeline in-flight number and the opportunity list's own label are one
    # query in the renderer; the page must show them agreeing. ⭐ A NO-MATCH here must be
    # LOUD, never a silent skip (dev/audit 2026-09-03) — a router row can legitimately match
    # nothing (the pipeline phase collapsed to nothing, ZERO COLLAPSES), but it can also fail
    # to match because a later feature reshaped the row's markup, and those two cases must not
    # look the same: the first is nothing to check, the second is a check that just went dark.
    m = _ROUTER_FLIGHT_RE.search(page)
    if m:
        n_router = int(m.group(1) or 0)
        opp = groups.get("opportunities") or {}
        n_label = sum(1 for v in (opp.get("members") or {}).values()
                      if v.get("state") == "in-flight")
        if n_router != n_label:
            gaps.append("ROUTER DISAGREES — the pipeline row says %d in flight; the "
                        "opportunity list counts %d" % (n_router, n_label))
    elif _ROUTER_PIPELINE_ANCHOR_RE.search(page):
        gaps.append("ROUTER ROW UNRECOGNIZED — the page links #phase-pipeline but its "
                    "in-flight markup does not match the shape this check knows "
                    "(class=\"ct2\">...</span> immediately before the link); the router's "
                    "count was NOT CHECKED against the opportunity list")
    else:
        lines.append("filters: router in-flight count NOT CHECKED — no #phase-pipeline row "
                     "on the page (the pipeline phase has collapsed to nothing)")
    lines.append("filters: %d list(s) · %d dimension(s) · %d label(s) checked"
                 % (len(set(groups) & set(regions)), n_dims, n_labels))
    return gaps, lines


def check(root, verbose=False):
    """(gaps, summary_lines, advisories). Empty gaps means the contract holds; advisories
    are measurements that do not fail the check (EXACTLY ONCE, until stage 2)."""
    html_path = _tree.path(root, "dashboard_artifact")
    ledger_path = os.path.join(root, "views", LEDGER_NAME)
    have_html, have_ledger = os.path.isfile(html_path), os.path.isfile(ledger_path)
    if not have_html and not have_ledger:
        return None, ["NOT CHECKED — no generated dashboard yet (views/dashboard_artifact.html "
                      "absent); run generate_dashboard.py first"], []
    if have_html and not have_ledger:
        return ["ARTIFACT WITHOUT A LEDGER — views/%s is missing, so the page was generated "
                "by a renderer that keeps no coverage record; regenerate with the current "
                "generate_dashboard.py" % LEDGER_NAME], [], []
    try:
        with open(ledger_path, encoding="utf-8") as fh:
            ledger = json.load(fh)
        records = ledger["records"]
        remainders = ledger.get("remainders") or {}
        window = ledger.get("window") or {}
        today = datetime.date.fromisoformat(window["today"])
        horizon = int(window["prep_horizon_days"])
        terminal = set(ledger.get("terminal_statuses") or [])
    except (OSError, ValueError, KeyError, TypeError) as e:
        return ["LEDGER UNREADABLE — views/%s: %s (an unreadable ledger is a gap, never a "
                "pass)" % (LEDGER_NAME, e)], [], []
    if terminal != set(_vd.TERMINAL_OPP_STATUSES):
        return ["LEDGER VOCABULARY DRIFT — the ledger's terminal set %s is not validate_data's "
                "%s; the page was generated by a renderer with a different vocabulary"
                % (sorted(terminal), sorted(_vd.TERMINAL_OPP_STATUSES))], [], []
    try:
        with open(html_path, encoding="utf-8") as fh:
            page = fh.read()
    except OSError as e:
        return ["ARTIFACT UNREADABLE — %s" % e], [], []

    # ⭐ A LIST, never a set: the count of each key is the EXACTLY ONCE measurement.
    rec_list = [_html.unescape(m) for m in _REC_RE.findall(page)]
    on_page = set(rec_list)
    full_on_page = set(_html.unescape(m) for m in _FULL_REC_RE.findall(page))
    more_on_page = {}
    for set_name, k in _MORE_RE.findall(page):
        more_on_page[_html.unescape(set_name)] = int(k)

    exp = expected_records(root, today)
    gaps, placements = [], []
    counts = {"rendered": 0, "remainder": 0, "terminal": 0}
    remainder_members = {}
    for key, meta in sorted(exp.items()):
        entry = records.get(key)
        if not entry:
            gaps.append("UNPLACED — %s is in the store but the page neither rendered it, "
                        "counted it in a remainder, nor marked it terminal" % key)
            continue
        disp, where = entry.get("disposition"), entry.get("where")
        placements.append("%-10s %-24s %s" % (disp, where, key))
        if disp == "rendered":
            counts["rendered"] += 1
            if key not in on_page:
                gaps.append("CLAIMED RENDERED, NOT ON PAGE — %s (ledger says %s)" % (key, where))
        elif disp == "remainder":
            counts["remainder"] += 1
            remainder_members.setdefault(where, []).append(key)
        elif disp == "terminal":
            counts["terminal"] += 1
            if not _is_terminal(meta, terminal, today):
                gaps.append("CLAIMED TERMINAL, NOT TERMINAL — %s (%s) has not ended, so "
                            "omitting it hides a live record" % (key, json.dumps(meta)))
        else:
            gaps.append("UNKNOWN DISPOSITION — %s: %r" % (key, disp))
    # A set's K counts everything it trimmed; a record trimmed here but rendered in another
    # set is RENDERED (the strongest placement wins), so K may exceed the records whose final
    # placement is this remainder — never the reverse. The page's K must equal the ledger's.
    for set_name, members in sorted(remainder_members.items()):
        k_ledger = remainders.get(set_name)
        if k_ledger is None or k_ledger < len(members):
            gaps.append("REMAINDER MISCOUNT — set %s: ledger says +%s more but %d record(s) "
                        "rest on that count" % (set_name, k_ledger, len(members)))
        # REACHABLE, record side: a record whose FINAL placement is a filtered list's
        # remainder is on no part of the page and reachable under no chip.
        if set_name in (ledger.get("filters") or {}):
            for key in members:
                gaps.append("TRIMMED BEHIND A FILTER — %s rests in list %s's remainder and "
                            "renders nowhere; a filtered list has no remainder (ADR-024 "
                            "REACHABLE, public #54)" % (key, set_name))
    # Every "+K more" the ledger recorded must be on the page with the same K, and vice
    # versa — whichever side disagrees, the reader is being told a wrong count.
    for set_name in sorted(set(remainders) | set(more_on_page)):
        k_ledger, k_page = remainders.get(set_name), more_on_page.get(set_name)
        if k_page is None:
            gaps.append("REMAINDER NOT ON PAGE — set %s trims %s record(s) but the page has "
                        "no '+K more' line for it" % (set_name, k_ledger))
        elif k_page != k_ledger:
            gaps.append("REMAINDER MISCOUNT ON PAGE — set %s shows +%d more but the ledger "
                        "trimmed %s" % (set_name, k_page, k_ledger))
    # SCOPE — nothing the window excludes.
    limit = today + datetime.timedelta(days=horizon)
    for key in sorted(on_page):
        meta = exp.get(key)
        if meta is None:
            gaps.append("RENDERED, NOT A RECORD — %s is on the page but no such record exists "
                        "(stale render, or a row derived from nothing)" % key)
            continue
        if meta["kind"] == "opp" and meta.get("status") in terminal:
            gaps.append("TERMINAL ROLE RENDERED — %s (status %r) is on the page"
                        % (key, meta.get("status")))
        if meta["kind"] in ("draft", "cover") and meta.get("state") in _pre.TERMINAL:
            gaps.append("TERMINAL MESSAGE RENDERED — %s (state %r) is on the page"
                        % (key, meta.get("state")))
        if meta["kind"] == "prep" and key in full_on_page:
            d = meta.get("date")
            if d is None or d < today or d > limit:
                gaps.append("PREP IN FULL OUTSIDE THE WINDOW — %s (call date %s) renders in "
                            "full; the window is %s..%s" % (key, d, today, limit))
    # MEMBERSHIP UNDER NARROWING — the filtered lists.
    f_gaps, f_lines = check_filters(page, ledger, exp, remainders, more_on_page)
    gaps.extend(f_gaps)
    n_exp = len(exp)
    n_placed = n_exp - sum(1 for g in gaps if g.startswith("UNPLACED"))
    lines = ["covered %d of %d record(s) — %d rendered · %d in counted remainders · "
             "%d terminal (generated %s, prep window %d days)"
             % (n_placed, n_exp, counts["rendered"], counts["remainder"],
                counts["terminal"], today.isoformat(), horizon)]
    lines.extend(f_lines)
    if verbose:
        lines.extend("  " + p for p in placements)
    # EXACTLY ONCE — advisory until stage 2 (see the module docstring).
    dupes = sorted((k, n) for k, n in collections.Counter(rec_list).items() if n > 1)
    advisories = []
    if dupes:
        advisories.append("EXACTLY ONCE (advisory) — %d record(s) render in more than one "
                          "place: %s" % (len(dupes), ", ".join("%s ×%d" % kn for kn in dupes)))
    return gaps, lines, advisories


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    root = profile_root()
    gaps, lines, advisories = check(root, verbose=args.verbose)
    print("Dashboard coverage — stores vs ledger vs views/dashboard_artifact.html")
    for l in lines:
        print("  " + l)
    if gaps is None:
        return 0
    if advisories:
        print("\n  ADVISORY — measured, not enforced. Stage 2 of public #48 turns queue rows "
              "into references to the subject row; until it lands a record legitimately "
              "renders in its queue row AND its subject list, so this cannot be a gap yet "
              "without wedging every page. It is printed so the number is watched, not "
              "assumed.")
        for a in advisories:
            print("  - " + a)
    if not gaps:
        print("  CLEAN — every record is rendered, counted, or terminal; nothing renders "
              "outside its window; every filtered list is whole under every filter and "
              "every chip shows every row it counts")
        return 0
    print("\n" + "=" * 72)
    print("%d GAP(S)" % len(gaps))
    print("=" * 72)
    for g in gaps:
        print("  - " + g)
    print("\n  Remedy: regenerate (generate_dashboard.py) and re-check; a gap that survives a "
          "regeneration is a renderer defect — report it, never hand-edit the page.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
