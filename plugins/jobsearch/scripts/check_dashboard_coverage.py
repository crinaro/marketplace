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
                  by omission;
  * ELSEWHERE:<home> — (jobsearch 0.71.0, dev #750, amending this contract) the page no longer
                  renders it BY DESIGN: the dashboard is cut to drafts to review, opportunities to
                  pursue and applications to finish, and everything else lives in a named home -
                  `panel` (scripts/panel.py's `elsewhere` object) or a review pane. A record
                  ledgered ELSEWHERE is only honest if its home really carries it, so this check
                  runs `panel.py --json --sections elsewhere` (and reads `presence_set.py --json`
                  for a review home) against the SAME profile and REFUSES an ELSEWHERE record whose
                  id its named home does not carry. That refusal is P3's "reachable" test: nothing a
                  reader relied on the page for is silently dropped.
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

⭐ ONE PRIMARY ROW PER RECORD (dev #496 / public #48, dev #540 / public #132 — the 2026-10
   stage-2 build; design-one-dashboard-surface.md r3 §2). EXACTLY ONCE used to be ADVISORY
   because the page legitimately rendered a queue row AND a subject-list row for one record.
   Stage 2 made every second mention a REFERENCE row — `data-ref="<key>"` plus a link to the
   primary's `id="rec-<h>"` — so the contract is enforceable, and four things are now GAPS:
  * EXACTLY ONCE — no `data-rec` key occurs twice. (`_REC_RE` counts primary rows as a LIST;
                  `_REF_RE` is its sibling for references, so a reference is never mistaken
                  for a second primary and is never invisible — the 2026-09-03 heads-up.)
  * LINKED      — every `data-ref` names a key that has a primary row on the page, and its row
                  carries a link to THAT key's id; every primary's `id` is the one derived
                  from its key (computed here independently of the renderer, on purpose); no
                  `id` occurs twice (a draft title is not unique — the key carries an
                  ordinal, your_move.entry_keys).
  * ANCHOR      — every `href="#x"` resolves to an `id="x"` on the page, and every
                  `<label for="x">` to an `id="x"` (the router's count is such a label). The
                  base case shipped `#phase-outreach-approvals` with no section behind it.
  * SCRIPT      — the page carries at most ONE script, the allowlisted copy-as-prompt one
                  (OWNER REQUEST 2026-10-13), and it touches no network, storage or navigation;
                  any other script, inline handler or `javascript:` URL is a gap.
  * DEFAULT     — exactly one radio per filter group carries `checked`, and it is the first
                  entry of the ledger's declared default order that has a DRAWN chip (a
                  population that is neither empty nor the whole list), else `All`; recomputed
                  here from the HTML rows, never from the ledger's own claim.

⭐ DEGENERACY AND CROSS-CUTS (design r3 D3/D4). A chip whose row set equals `All`'s is not
   drawn, and a dimension left with only `All` draws no bar — but the RADIO of a suppressed
   chip stays, so a router label can still activate it. So LABEL MISSING tolerates a missing
   chip only when an independent recount from the HTML rows proves its row set IS `All`'s, and
   a DRAWN degenerate chip is itself a gap (DEGENERATE CHIP DRAWN). A CROSS-CUT option (the
   ledger's `dims[dim]["cross"]`, e.g. `pursuit=your-move`) is carried in `data-<dim>-also`, not
   in `data-<dim>`: it is counted from that attribute in COUNT and REACHABLE and left out of the
   SUM, which is over the partition. ROUTER DISAGREES compares the router's pipeline in-flight
   number with the opportunity rows that do NOT carry the `your-move` cross-cut, and every
   router count that is a `<label for=…>` with the rows its radio selects.

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

## The warm-path line (dev #751, jobsearch 0.72.0)

Every role card on the page whose role has a DERIVED warm-path next action (`warm_path.derive`, which
this check calls itself, over the same stores, on the ledger's own date) must carry exactly one
`<div class="opp-warm" data-warm="<state>">` whose state is that action's state. A card without it, a
card showing a different state, and a card showing the line for a role that has no action are all gaps.
The line is not a record (it adds no `data-rec`), so it is held to the derivation here rather than to the
ledger. Plant: omit the line in `generate_dashboard.py` and this check goes red.

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
import hashlib
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
HERE = os.path.dirname(os.path.abspath(__file__))

# Where each record kind lives when its disposition is `elsewhere:panel`: the key of the home's
# `elsewhere` object that must list its id. A kind not in this table CANNOT be ledgered elsewhere.
PANEL_LISTS = {"opp": "in_flight", "ask": "asks", "commit": "week", "chan": "channels_due",
               "prep": "kb_index"}
ELSEWHERE_HOMES = ("panel", "review-resume", "review-linkedin")
_REC_RE = re.compile(r'data-rec="([^"]+)"')
# A REFERENCE row (r3 §2): the sibling of _REC_RE, so a reference is neither a second primary
# nor invisible. `_ID_RE` finds every id on the page; `_HREF_RE` every in-page link.
_REF_RE = re.compile(r'data-ref="([^"]+)"')
_ID_RE = re.compile(r'\sid="([^"]+)"')
_HREF_RE = re.compile(r'\shref="#([^"]+)"')
_LABEL_FOR_RE = re.compile(r'<label for="([^"]+)"')
_RADIO_RE = re.compile(r'<input type="radio" name="([^"]+)" id="([^"]+)" class="fctl"( checked)?>')
_ROUTER_LABEL_RE = re.compile(r'<span class="ct"><label for="([^"]+)"[^>]*>(\d+)</label></span>')
_FULL_REC_RE = re.compile(r'data-rec="([^"]+)" data-full="1"')
_MORE_RE = re.compile(r'data-more="([^"]+):(\d+)"')
# A filtered list's container, a row's opening tag, and a filter label.
_FLIST_RE = re.compile(r'<div class="[^"]*\bflist\b[^"]*" data-flist="([^"]+)">')
_ROW_RE = re.compile(r'<(\w+)\b([^>]*?)\sdata-(rec|ref)="([^"]+)"([^>]*)>')
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
    import your_move as _ymod0
    rows = _pre.report(root)
    # design r3 D5 - the key of a staged entry is unique: your_move.entry_keys (the title, or
    # `<title>#n` for the nth entry of one title in one file), the SAME function the renderer
    # calls, so two same-titled drafts are two expected records and a renderer that collapses
    # them is UNPLACED here, not silently clean.
    for fname, kind in ((drafts_rel, "draft"), (covers_rel, "cover")):
        file_rows = [r for r in rows if r.get("file") == fname]
        for r, key in zip(file_rows, _ymod0.entry_keys(kind, [r.get("title") for r in file_rows])):
            if r.get("title"):
                exp[key] = {"kind": kind, "state": r.get("state")}
    for c, state, _detail in _cd.review_rows(_jsonl(root, "channels.jsonl"), today):
        if c.get("id"):
            exp["chan:%s" % c["id"]] = {"kind": "chan", "review": state}
    # dev #539/#541 (design r3 §4-5): a RELATIONSHIP channel (recruiter / referral) is not a
    # sourcing channel - review_rows skips it - but one with a touch owed or planned is the
    # target of the follow-up view's reference, so its primary row in the Channels list must be
    # expected here (else the page would render a row for a record this check calls unknown).
    # Membership is your_move.classify_channels', the one owner of touch states.
    import your_move as _ymod1
    for c, state, _touch, _ev in _ymod1.classify_channels(
            _jsonl(root, "channels.jsonl"), _jsonl(root, "messages.jsonl"), today.isoformat(),
            _jsonl(root, "involvements.jsonl")):
        if c.get("id") and state in ("now", "scheduled"):
            exp.setdefault("chan:%s" % c["id"], {"kind": "chan", "review": None})
    # dev #686 / public #139 (E1) — the People due block. NOT "every person": only the
    # person-only people `your_move.network_people_due` says are due (the ONE membership
    # definition the renderer also uses), so a due person the page forgot is UNPLACED here.
    # A person with no cadence, a fresh one, or one a pursuit carries is not expected.
    # Not wrapped in a try: a derivation that crashes must fail the gate loudly, never
    # shrink the expected set to nothing and read as CLEAN.
    import your_move as _ymod
    for person, state, _why in _ymod.network_people_due(root, today.isoformat())["due"]:
        if person.get("id"):
            exp["person:%s" % person["id"]] = {"kind": "person", "state": state}
    return exp


def load_home(root, home, today):
    """(doc, problem): the JSON a named home publishes, from the owning script run against `root`
    (a subprocess, so a module-level root can never disagree with the profile being checked). An
    unreadable home is a PROBLEM, never an empty carry."""
    import subprocess
    if home == "panel":
        argv = [sys.executable, os.path.join(HERE, "panel.py"), "--json", "--full",
                "--sections", "elsewhere", "--today", today.isoformat()]
    elif home in ("review-resume", "review-linkedin"):
        argv = [sys.executable, os.path.join(HERE, "presence_set.py"), "--json", "--surface",
                "print" if home == "review-resume" else "public-profile"]
    else:
        return None, "unknown home %r (known: %s)" % (home, ", ".join(ELSEWHERE_HOMES))
    env = dict(os.environ, CLAUDESEARCH_ROOT=root)
    try:
        r = subprocess.run(argv, cwd=root, env=env, capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, "%s could not be run (%s)" % (os.path.basename(argv[1]), e)
    try:
        doc = json.loads(r.stdout)
    except ValueError:
        return None, "%s printed something that is not JSON (exit %d): %s" % (
            os.path.basename(argv[1]), r.returncode, (r.stdout + r.stderr).strip()[:160])
    if r.returncode != 0 or (isinstance(doc, dict) and "error" in doc):
        return None, "%s exited %d: %s" % (os.path.basename(argv[1]), r.returncode,
                                           json.dumps(doc)[:160])
    return doc, None


def home_carries(home, doc, key):
    """True when the home's JSON lists the record `key`. The id is whatever follows the first colon."""
    kind, _sep, rid = key.partition(":")
    if home == "panel":
        section = (doc.get("elsewhere") or {})
        if isinstance(section, dict) and "error" in section:
            return False
        lst = PANEL_LISTS.get(kind)
        return bool(lst) and any(str(r.get("id")) == rid for r in (section.get(lst) or []))
    return kind == "variant" and any(str(v.get("id")) == rid for v in (doc.get("variants") or []))


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


def _rows_in(region, kinds=("rec",)):
    """[(key, {data-attr: value})] for every `[data-rec]` row in a region, in order. With
    `kinds=("rec", "ref")` the reference rows too, as (key, attrs, kind) triples via
    `_rows_with_kind`."""
    return [(k, a) for k, a, kind in _rows_with_kind(region) if kind in kinds]


def _rows_with_kind(region):
    """[(key, {data-attr: value}, 'rec'|'ref')] for every primary and reference row."""
    rows = []
    for m in _ROW_RE.finditer(region):
        attrs = dict((k, _html.unescape(v))
                     for k, v in _DATA_ATTR_RE.findall(" " + m.group(2) + " " + m.group(5)))
        rows.append((_html.unescape(m.group(4)), attrs, m.group(3)))
    return rows


def rec_id(key):
    """The id a primary row for `key` must carry - the first 12 hex digits of sha1(key),
    computed HERE independently of generate_dashboard.rec_id on purpose: a renderer that
    drifted from its own checker is the defect LINKED exists to catch."""
    return "rec-" + hashlib.sha1(str(key).encode("utf-8")).hexdigest()[:12]


def _count_label(shown, pop):
    return "(%d)" % pop if shown == pop else "(%d shown of %d)" % (shown, pop)


_ID_ATTR_RE = re.compile(r'\sid="([^"]*)"')


def _tokens(attrs, dim):
    """The cross-cut tokens a row/member carries for `dim` (`data-<dim>-also`)."""
    return set((attrs.get(dim + "-also") or "").split())


def _has(vals, dim, value, cross):
    """Does a row/member (a {dim: value, dim-also: tokens} dict) carry `value` for `dim`? A
    cross-cut value is looked up in `data-<dim>-also`, every other value in `data-<dim>`."""
    if value in cross:
        return value in _tokens(vals, dim)
    return vals.get(dim) == value


def _element_span(page, m):
    """The HTML of the element whose opening tag is the regex match `m` (same-tag depth
    count), so a reference row's own link can be found inside it."""
    tag = m.group(1)
    depth, end = 1, None
    for t in re.finditer(r"<%s\b|</%s>" % (tag, tag), page[m.end():]):
        depth += 1 if t.group().startswith("<%s" % tag) and not t.group().startswith("</") else -1
        if depth == 0:
            end = m.end() + t.end()
            break
    return page[m.start():end if end is not None else len(page)]


# ⭐ SCRIPT (OWNER REQUEST 2026-10-13, "Copy as prompt"). The page was script-free by choice
# (design r3 Prior art: the page survives being saved and mailed; every filter is CSS). The
# owner chose ONE script: the draft rows' copy button. So the rule is an allowlist of exactly
# that one, keyed by its marker, never "any script": a second script, an external `src`, an
# inline `on…=` handler, a `javascript:` URL, or a network or storage API inside the allowed
# one is a gap. The script must only copy text that is already on the page.
_ALLOWED_SCRIPT_OPEN = '<script data-dashboard-script="copy-as-prompt">'
_SCRIPT_OPEN_RE = re.compile(r"<script\b[^>]*>", re.I)
_SCRIPT_BODY_RE = re.compile(r"<script\b[^>]*>(.*?)</script\s*>", re.I | re.S)
_INLINE_HANDLER_RE = re.compile(r"<[a-z][^>]*\son[a-z]+\s*=", re.I)
_SCRIPT_FORBIDDEN = ("fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket", "EventSource",
                     "import(", "localStorage", "sessionStorage", "indexedDB", "document.cookie",
                     "window.open", "location.", "postMessage", "eval(", "new Function")


def check_scripts(page):
    """(gaps, summary) — at most ONE script, the allowlisted copy-as-prompt one."""
    gaps = []
    opens = _SCRIPT_OPEN_RE.findall(page)
    others = [o for o in opens if o != _ALLOWED_SCRIPT_OPEN]
    for o in others:
        gaps.append("SCRIPT — %s is not the one script this page allows (%s); the page is "
                    "otherwise script-free" % (o[:80], _ALLOWED_SCRIPT_OPEN))
    n_allowed = len(opens) - len(others)
    if n_allowed > 1:
        gaps.append("SCRIPT — the copy-as-prompt script appears %d times; exactly one is allowed"
                    % n_allowed)
    for body in _SCRIPT_BODY_RE.findall(page):
        for tok in _SCRIPT_FORBIDDEN:
            if tok in body:
                gaps.append("SCRIPT — the page's script uses %r; it may only copy text already "
                            "on the page (no network, no storage, no navigation)" % tok)
    if _INLINE_HANDLER_RE.search(page):
        gaps.append("SCRIPT — an inline event handler attribute (on…=) is on the page")
    if re.search(r'href="\s*javascript:', page, re.I):
        gaps.append("SCRIPT — a javascript: URL is on the page")
    return gaps, "script: %d (allowed: the copy-as-prompt script, at most once)" % len(opens)


def check_links(page, exp):
    """(gaps, summary) for the page-wide contract of design r3 §2: EXACTLY ONCE, LINKED, ANCHOR
    and unique ids. All four are gaps; none depends on the ledger (verify the artifact)."""
    gaps = []
    rec_list = [_html.unescape(m) for m in _REC_RE.findall(page)]
    ref_list = [_html.unescape(m) for m in _REF_RE.findall(page)]
    for k, n in sorted(collections.Counter(rec_list).items()):
        if n > 1:
            gaps.append("EXACTLY ONCE — %s renders as %d primary rows (`data-rec`); a record has "
                        "ONE primary row and every other mention is a `data-ref` reference "
                        "(design r3 §2)" % (k, n))
    ids = [_html.unescape(i) for i in _ID_RE.findall(page)]
    id_set = set(ids)
    for i, n in sorted(collections.Counter(ids).items()):
        if n > 1:
            gaps.append("DUPLICATE ID — id=%r occurs %d times; an id must be unique in the "
                        "document, and a collision here makes a reference land on the wrong "
                        "row" % (i, n))
    for m in _HREF_RE.finditer(page):
        target = _html.unescape(m.group(1))
        if target not in id_set:
            gaps.append("ANCHOR — href=\"#%s\" resolves to no id on the page (a link to "
                        "nothing; design r3 N)" % target)
    for m in _LABEL_FOR_RE.finditer(page):
        target = _html.unescape(m.group(1))
        if target not in id_set:
            gaps.append("LABEL TARGET UNRESOLVED — <label for=%r> names no id on the page; a "
                        "label can only activate a control that exists" % target)
    primary = set(rec_list)
    n_ids = n_refs = 0
    for m in _ROW_RE.finditer(page):
        kind, key = m.group(3), _html.unescape(m.group(4))
        if kind == "rec":
            have = _ID_ATTR_RE.search(" " + m.group(2) + " " + m.group(5))
            want = rec_id(key)
            n_ids += 1
            if not have:
                gaps.append("LINKED — primary row %s carries no id; a reference cannot land on "
                            "it (expected id=%r)" % (key, want))
            elif _html.unescape(have.group(1)) != want:
                gaps.append("LINKED — primary row %s has id=%r; its key hashes to %r"
                            % (key, have.group(1), want))
        else:
            n_refs += 1
            if key not in primary:
                gaps.append("LINKED — data-ref %s names a record with no primary row on the "
                            "page (a reference to nothing)" % key)
            elif ('href="#%s"' % rec_id(key)) not in _element_span(page, m):
                gaps.append("LINKED — the reference row for %s carries no link to its primary "
                            "row (href=\"#%s\")" % (key, rec_id(key)))
    return gaps, "links: %d primary id(s) · %d reference(s) · %d in-page id(s) checked" % (
        n_ids, n_refs, len(id_set))


def check_filters(page, ledger, exp, remainders, more_on_page=None):
    """(gaps, summary_lines) for MEMBERSHIP UNDER NARROWING — DIMENSION COMPLETE and
    COUNT AGREES over every filtered list the ledger declares — and for REACHABLE:
    TRIMMED BEHIND A FILTER and UNREACHABLE UNDER FILTER (public #54), plus (design r3) the
    cross-cut, degeneracy, radio and default contracts described in the module docstring."""
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
    radios = collections.defaultdict(list)
    for rname, rid, chk in _RADIO_RE.findall(page):
        radios[_html.unescape(rname)].append((_html.unescape(rid), bool(chk)))
    need_note = False
    n_dims = n_labels = 0
    for name in sorted(set(groups) & set(regions)):
        g = groups[name]
        dims = g.get("dims") or {}
        members = g.get("members") or {}
        refs = g.get("refs") or {}
        shown_claim = list(g.get("shown") or [])
        shown_refs_claim = list(g.get("shown_refs") or [])
        vocab, cross, excl = {}, {}, {}
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
            cross[dim] = set(spec.get("cross") or [])
            if not cross[dim] <= vocab[dim]:
                gaps.append("CROSS-CUT OUTSIDE VOCABULARY — list %s dimension %s declares "
                            "cross-cut %s that is not one of its values"
                            % (name, dim, sorted(cross[dim] - vocab[dim])))
            excl[dim] = vocab[dim] - cross[dim]

        def _ledger_rows(rows, what):
            for key, vals in sorted(rows.items()):
                if key not in exp:
                    gaps.append("FILTER %s NOT A RECORD — list %s counts %s, and no such "
                                "record exists" % (what, name, key))
                for dim in dims:
                    if vals.get(dim) not in excl.get(dim, set()):
                        gaps.append("MEMBER VALUE OUTSIDE VOCABULARY — list %s %s %s has "
                                    "%s=%r" % (name, what.lower(), key, dim, vals.get(dim)))
                    bad = _tokens(vals, dim) - cross.get(dim, set())
                    if bad:
                        gaps.append("MEMBER VALUE OUTSIDE VOCABULARY — list %s %s %s carries "
                                    "cross-cut %s the dimension does not declare"
                                    % (name, what.lower(), key, sorted(bad)))
        _ledger_rows(members, "MEMBER")
        _ledger_rows(refs, "REF")
        # DIMENSION COMPLETE, page side: every row, every dimension, a vocabulary value that
        # matches what the ledger claimed for it.
        all_rows = _rows_with_kind(regions[name])
        row_keys = [k for k, _a, t in all_rows if t == "rec"]
        ref_keys = [k for k, _a, t in all_rows if t == "ref"]
        row_vals, ref_vals = {}, {}
        for key, attrs, kind in all_rows:
            ledger_rows, store = (members, row_vals) if kind == "rec" else (refs, ref_vals)
            if key not in ledger_rows:
                gaps.append("ROW NOT A MEMBER — list %s renders %s%s, which its ledger entry "
                            "does not count" % (name, key, " (a reference)" if kind == "ref" else ""))
                continue
            store[key] = {}
            for dim in dims:
                v = attrs.get(dim)
                if v is None:
                    gaps.append("DIMENSION MISSING — list %s row %s carries no data-%s, so it "
                                "is visible only under `all`" % (name, key, dim))
                elif v not in excl.get(dim, set()):
                    gaps.append("VALUE OUTSIDE VOCABULARY — list %s row %s has data-%s=%r"
                                % (name, key, dim, v))
                elif v != ledger_rows[key].get(dim):
                    gaps.append("ROW DISAGREES WITH LEDGER — list %s row %s has data-%s=%r; "
                                "the ledger says %r" % (name, key, dim, v,
                                                        ledger_rows[key].get(dim)))
                store[key][dim] = v
                if _tokens(attrs, dim) != _tokens(ledger_rows[key], dim):
                    gaps.append("ROW DISAGREES WITH LEDGER — list %s row %s has data-%s-also=%r;"
                                " the ledger says %r" % (name, key, dim,
                                                         attrs.get(dim + "-also"),
                                                         ledger_rows[key].get(dim + "-also")))
                if _tokens(attrs, dim):
                    store[key][dim + "-also"] = attrs.get(dim + "-also")
        if sorted(row_keys) != sorted(shown_claim):
            gaps.append("SHOWN DISAGREES — list %s: the ledger says %d row(s) shown, the page "
                        "carries %d" % (name, len(shown_claim), len(row_keys)))
        if sorted(ref_keys) != sorted(shown_refs_claim):
            gaps.append("SHOWN DISAGREES — list %s: the ledger says %d reference row(s) shown, "
                        "the page carries %d" % (name, len(shown_refs_claim), len(ref_keys)))
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
        # COUNT AGREES: every label, both numbers, against the rows and the members. Reference
        # rows count: a chip that advertises a reference must be able to show it.
        n_rows_all = len(row_keys) + len(ref_keys)
        n_pop_all = len(members) + len(refs)
        pop_rows = list(members.values()) + list(refs.values())
        shown_rows = list(row_vals.values()) + list(ref_vals.values())
        for dim in sorted(dims):
            cr = cross.get(dim, set())
            expect = {"all": (n_rows_all, n_pop_all)}
            for v in vocab[dim]:
                pop = sum(1 for m in pop_rows if _has(m, dim, v, cr))
                sh = sum(1 for m in shown_rows if _has(m, dim, v, cr))
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
            # DEGENERACY: a value whose HTML-recounted row set IS `All`'s selects nothing
            # `All` does not. Its chip is not drawn (its RADIO still is); drawing it is a gap.
            degenerate = {v for v, (sh, _p) in expect.items()
                          if v != "all" and n_rows_all and sh == n_rows_all}
            drawn_others = [v for v in expect if v != "all" and (name, dim, v) in labels]
            gname = "f-%s-%s" % (name, dim)
            have_radios = {rid for rid, _c in radios.get(gname, [])}
            for v in sorted(expect):
                if "%s-%s" % (gname, v) not in have_radios:
                    gaps.append("RADIO MISSING — list %s dimension %s has %d member(s) with "
                                "value %r and no radio %s-%s; a suppressed chip keeps its "
                                "radio so a router label can still activate it"
                                % (name, dim, expect[v][1], v, gname, v))
            for v, (sh, pop) in sorted(expect.items()):
                lab = labels.get((name, dim, v))
                if lab is None:
                    if v in degenerate:
                        continue            # suppressed: its rows ARE `All`'s (recounted above)
                    if v == "all" and not drawn_others and all(
                            x in degenerate for x in expect if x != "all"):
                        continue            # a dimension left with only `All` draws no bar
                    gaps.append("LABEL MISSING — list %s dimension %s has %d member(s) with "
                                "value %r and no chip for it" % (name, dim, pop, v))
                    continue
                n_labels += 1
                if v in degenerate:
                    gaps.append("DEGENERATE CHIP DRAWN — list %s chip %s=%s selects the very "
                                "rows `All` does (%d of %d); a chip that narrows nothing is "
                                "not drawn" % (name, dim, v, sh, n_rows_all))
                if v == "all" and not drawn_others:
                    gaps.append("DEGENERATE CHIP DRAWN — list %s dimension %s draws only "
                                "`All`; a dimension left with only `All` is not drawn"
                                % (name, dim))
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
            # The SUM is over the PARTITION: a cross-cut option overlaps it by definition.
            sums = [sum(x[i] for v, x in expect.items() if v != "all" and v not in cr)
                    for i in (0, 1)]
            if tuple(sums) != expect["all"]:
                gaps.append("COUNTS DO NOT SUM — list %s dimension %s: per-value counts sum to "
                            "%d shown of %d, `all` is %d of %d"
                            % (name, dim, sums[0], sums[1], expect["all"][0], expect["all"][1]))
            # DEFAULT: exactly one checked radio, and it is the declared order's first DRAWN
            # value (recomputed from the HTML rows), else `All`.
            order = list((g.get("defaults") or {}).get(dim, {}).get("order") or [])
            checked = [rid for rid, c in radios.get(gname, []) if c]
            want = next((v for v in order if v in expect and v != "all" and v not in degenerate),
                        "all")
            if len(checked) != 1:
                gaps.append("DEFAULT NOT UNIQUE — list %s dimension %s has %d checked radio(s); "
                            "exactly one must carry `checked` (a default with nothing checked "
                            "renders the unfiltered list with no chip selected)"
                            % (name, dim, len(checked)))
            elif checked[0] != "%s-%s" % (gname, want):
                gaps.append("DEFAULT WRONG — list %s dimension %s opens on %s; the declared "
                            "order %s resolves to %r on this page's rows"
                            % (name, dim, checked[0][len(gname) + 1:], order or ["all"], want))
            if order and order[0] not in expect and want != order[0]:
                need_note = True
    if need_note and 'class="sub fdefault"' not in page:
        gaps.append("DEFAULT UNANNOUNCED — a filter's first default had no members and the "
                    "page fell back, but says nowhere that it did (a default that quietly did "
                    "not apply is the defect; design r2 §5)")
    # The router's pipeline in-flight number and the opportunity rows it must equal. dev #494:
    # `state` left the opportunity bar, so the comparison is against the HTML rows that do NOT
    # carry the `your-move` cross-cut (needs-you's complement), recounted from the page.
    # ⭐ A NO-MATCH here must be LOUD, never a silent skip (dev/audit 2026-09-03) — a router
    # row can legitimately match nothing (the pipeline phase collapsed to nothing, ZERO
    # COLLAPSES), but it can also fail to match because a later feature reshaped the row's
    # markup, and those two cases must not look the same.
    m = _ROUTER_FLIGHT_RE.search(page)
    if m:
        n_router = int(m.group(1) or 0)
        opp_rows = _rows_in(regions.get("opportunities", ""))
        n_label = sum(1 for _k, a in opp_rows if "your-move" not in _tokens(a, "pursuit"))
        if n_router != n_label:
            gaps.append("ROUTER DISAGREES — the pipeline row says %d in flight; the "
                        "opportunity list's rows outside `Your move` number %d"
                        % (n_router, n_label))
    elif _ROUTER_PIPELINE_ANCHOR_RE.search(page):
        gaps.append("ROUTER ROW UNRECOGNIZED — the page links #phase-pipeline but its "
                    "in-flight markup does not match the shape this check knows "
                    "(class=\"ct2\">...</span> immediately before the link); the router's "
                    "count was NOT CHECKED against the opportunity list")
    else:
        lines.append("filters: router in-flight count NOT CHECKED — no #phase-pipeline row "
                     "on the page (the pipeline phase has collapsed to nothing)")
    # A router count that is a LABEL for a filter radio promises the population that radio
    # selects (design r3 R540): its number must equal the rows the radio shows.
    n_router_labels = 0
    for target, num in _ROUTER_LABEL_RE.findall(page):
        target = _html.unescape(target)
        hit = None
        for gname_, g_ in groups.items():
            for dim_ in (g_.get("dims") or {}):
                pre = "f-%s-%s-" % (gname_, dim_)
                if target.startswith(pre) and gname_ in regions:
                    hit = (gname_, dim_, target[len(pre):])
        if hit is None:
            continue                  # LABEL TARGET UNRESOLVED (check_links) owns a bad id
        gname_, dim_, value = hit
        cr = set(((groups[gname_].get("dims") or {}).get(dim_) or {}).get("cross") or [])
        rows_ = [dict(a) for _k, a, _t in _rows_with_kind(regions[gname_])]
        n_rows = sum(1 for a in rows_ if _has(a, dim_, value, cr))
        n_router_labels += 1
        if int(num) != n_rows:
            gaps.append("ROUTER DISAGREES — a router count of %s is a label for %s, which "
                        "selects %d row(s) of list %s" % (num, target, n_rows, gname_))
    lines.append("filters: %d list(s) · %d dimension(s) · %d label(s) checked · %d router "
                 "label(s)" % (len(set(groups) & set(regions)), n_dims, n_labels,
                               n_router_labels))
    return gaps, lines


_WARM_RE = re.compile(r'<div class="opp-warm" data-warm="([a-z-]+)"')
_OPP_CARD_RE = re.compile(r'\bclass="(?:[^"]*\s)?opp(?:\s[^"]*)?"')


def check_warm_path(page, root, today):
    """`(gaps, line)`: hold every role card to the warm-path action `warm_path.derive` computes for its
    role (see the docstring section). Recomputed HERE, independently of the renderer, on purpose."""
    import profile as _profile
    import config_keys as _ck
    import warm_path as _wp
    try:
        lookup_days = _ck.resolve_int(_profile.config(), _ck.SEARCH_WARM_LOOKUP_DAYS)
        actions = _wp.derive(root, today=today.isoformat(), lookup_days=lookup_days)
    except Exception as e:                                           # noqa: BLE001 - a gap, never a pass
        return ["WARM PATH NOT CHECKABLE — warm_path.derive failed (%s: %s); an uncheckable line is a "
                "gap, never a pass" % (type(e).__name__, e)], "warm path: NOT CHECKED"
    expected = {}
    for a in actions:
        for oid in a["opp_ids"]:
            expected[oid] = a
    gaps, cards, with_line = [], 0, 0
    for m in _ROW_RE.finditer(page):
        if m.group(3) != "rec":
            continue
        key = _html.unescape(m.group(4))
        # a ROLE CARD only (`class="opp"`): the same record also appears as a Drafts follow-up row
        # (`class="draft ..."`, key `opp:<id>`), which is a draft's row and carries no warm-path line
        if not key.startswith("opp:") or not _OPP_CARD_RE.search(m.group(2)):
            continue
        cards += 1
        oid = key[len("opp:"):]
        span = _element_span(page, m)
        lines = _WARM_RE.findall(span)
        want = expected.get(oid)
        if want is None:
            if lines:
                gaps.append("WARM PATH WITHOUT AN ACTION — %s shows a warm-path line but warm_path.py "
                            "derives none for it" % key)
            continue
        if not lines:
            gaps.append("WARM PATH MISSING — %s has a derived next action (%s, %s) but its card "
                        "carries no warm-path line" % (key, want["kind"], want["state"]))
        elif len(lines) > 1:
            gaps.append("WARM PATH TWICE — %s's card carries %d warm-path lines" % (key, len(lines)))
        elif lines[0] != want["state"]:
            gaps.append("WARM PATH WRONG STATE — %s's card says %r but warm_path.py derives %r"
                        % (key, lines[0], want["state"]))
        else:
            with_line += 1
    return gaps, "warm path: %d of %d role card(s) carry their derived next action" % (with_line, cards)


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

    # ⭐ A LIST, never a set: the count of each key is the EXACTLY ONCE measurement
    # (check_links turns it into a gap).
    rec_list = [_html.unescape(m) for m in _REC_RE.findall(page)]
    on_page = set(rec_list)
    full_on_page = set(_html.unescape(m) for m in _FULL_REC_RE.findall(page))
    more_on_page = {}
    for set_name, k in _MORE_RE.findall(page):
        more_on_page[_html.unescape(set_name)] = int(k)

    exp = expected_records(root, today)
    gaps, placements = [], []
    counts = {"rendered": 0, "remainder": 0, "terminal": 0, "elsewhere": 0}
    elsewhere_keys = []
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
        elif disp == "elsewhere":
            counts["elsewhere"] += 1
            if _is_terminal(meta, terminal, today):
                gaps.append("ELSEWHERE, BUT TERMINAL — %s has ended; it is omitted, not relocated"
                            % key)
            elsewhere_keys.append((key, where))
        else:
            gaps.append("UNKNOWN DISPOSITION — %s: %r" % (key, disp))
    # ELSEWHERE reachability: each named home must really carry the record.
    homes = {}
    for key, home in elsewhere_keys:
        if home not in homes:
            homes[home] = load_home(root, home, today)
        doc, problem = homes[home]
        if problem:
            gaps.append("ELSEWHERE HOME UNREADABLE — %s is ledgered elsewhere:%s but %s"
                        % (key, home, problem))
        elif not home_carries(home, doc, key):
            gaps.append("ELSEWHERE, NOT AT HOME — %s is ledgered elsewhere:%s but %s's own JSON does "
                        "not carry it: the page dropped it and no other surface took it"
                        % (key, home, home))
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
    l_gaps, l_line = check_links(page, exp)
    gaps.extend(l_gaps)
    s_gaps, _s_line = check_scripts(page)
    gaps.extend(s_gaps)
    w_gaps, w_line = check_warm_path(page, root, today)
    gaps.extend(w_gaps)
    n_exp = len(exp)
    n_placed = n_exp - sum(1 for g in gaps if g.startswith("UNPLACED"))
    lines = ["covered %d of %d record(s) — %d rendered · %d in counted remainders · "
             "%d terminal · %d elsewhere (generated %s, prep window %d days)"
             % (n_placed, n_exp, counts["rendered"], counts["remainder"],
                counts["terminal"], counts["elsewhere"], today.isoformat(), horizon)]
    lines.extend(f_lines)
    lines.append(l_line)
    lines.append(w_line)
    if verbose:
        lines.extend("  " + p for p in placements)
    # EXACTLY ONCE is a GAP since design r3 (check_links); nothing is advisory any more. The
    # third return value is kept so a caller unpacking three values keeps working.
    return gaps, lines, []


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
    for a in advisories:
        print("  - " + a)
    if not gaps:
        print("  CLEAN — every record is rendered, counted, or terminal; nothing renders "
              "outside its window; every record has ONE primary row and every reference and "
              "link resolves; every filtered list is whole under every filter and every chip "
              "shows every row it counts")
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
