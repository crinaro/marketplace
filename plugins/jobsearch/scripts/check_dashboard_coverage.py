#!/usr/bin/env python3
"""Does the published page ACCOUNT FOR every record — and render nothing its window excludes?

⭐ THE TWO-SIDED COVERAGE CONTRACT (dev/audit 2026-09-02, Class C)
-------------------------------------------------------------------
COVERAGE: every record in the row-backed stores is, on the generated page, exactly one of
  * RENDERED    — a row carries `data-rec="<kind>:<id>"`;
  * REFERENCED  — (dev 973) its row is a `data-ref` to its SUBJECT's one primary row in another section, whose key
                  the ledger names (`where`); that primary row and the reference are both on the page;
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

The per-section filter chips (public #48 stage 1) and their checks (DIMENSION COMPLETE, COUNT AGREES, DEFAULT,
TRIMMED BEHIND A FILTER, UNREACHABLE UNDER FILTER, ROUTER DISAGREES) are RETIRED with the chips (dashboard-redesign D2,
D-6): every list is three levels (design §4), and a row past level 2 is a counted REMAINDER like any other.

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
                  `<label for="x">` to an `id="x"`. The base case shipped
                  `#phase-outreach-approvals` with no section behind it.
  * SCRIPT      — the page carries at most ONE script, the allowlisted copy-as-prompt one
                  (OWNER REQUEST 2026-10-13), which copies text already on the page: attribute
                  values, joined by newlines (design-dashboard-redesign §6.1); it touches no network,
                  storage or navigation and builds no markup. Any other script, inline handler or
                  `javascript:` URL is a gap (`coverage_checks/script.py`).

## Today, the levels and the tick boxes (dashboard-redesign E; design §3.6, §4, §6.1, §12)

Pure page checks in the package `coverage_checks/`, each `(page, ledger, expected) -> (gaps, line)`:
`TODAY OVER CAP` (more than 5 items, an item with no link, a primary row inside Today) and `TODAY ROW
FOLDED` (a row Today references is folded) in `today_gaps.py`; `FOLD OVER CAP` (a level-2 fold holding more
than 20 rows) in `folds.py`; `TICK BOX IS A ROW` and `BUTTON WITHOUT A HEAD` in `picks.py`. Each is an
ENGINE gap (`coordinator.ENGINE_GAPS`): a regeneration cannot clear it. `LEDGER PREDATES TODAY` (a ledger
with no `today` block, the first run after an upgrade) is the one REGENERATE gap: exit 1, and nothing
else is checked against a ledger that cannot describe the page.

## Verify the artifact, not the plan (CLAUDE.md trap 6)

`generate_dashboard.py` writes a ledger beside the artifact (`views/dashboard_coverage.json`)
saying where it placed each record and what each list counted past its fold. That ledger is a
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

## The Network list, and the top that does not grow (dev #834, jobsearch 0.86.0, M4/M5)

The Network list (`<section id="phase-network">`, after Drafts) is covered like every other list: each row the
owner acts on carries `data-rec="net:<kind>:<id>"` and is EXPECTED from `funnel_report.network_rows`, the one
derivation the renderer also calls (a look-into company, a past chat nobody has marked held or no-show, a
booking with no chat recorded, an open suggestion ask, an unobserved send, a drafting proposal). A row the
page forgot is UNPLACED; a row it invents is `RENDERED, NOT A RECORD`; a SENT proposal is status, not a row,
and is counted in the "Not on this page" note (`data-net-sent-proposals`), held to the store.

And the owner's 0.84.0 C7 request is held: `TOP REGION GREW` fires when anything other than the jump bar, the
title, the `Generated` line and at most one `data-pipeline-alert` element precedes the lists. Network status
(reach-outs against budget, chats held, the access table) is in the weekly review and
`views/network_strategy.md`, the upgrade notice is the run summary's, and neither is ever added to the top.
Plants: render a network line above `section.first` (`TOP REGION GREW`); drop `net` rows from
`expected_records` (a row the page forgot passes).

## Absence reads as itself

No artifact and no ledger: nothing has been generated yet → `NOT CHECKED`, exit 0 (a new
profile is not nagged). An artifact with NO ledger: generated by a renderer that keeps
none → FAIL, regenerate. A ledger whose window does not name today's
date is still checked against its OWN generation day — staleness is check_dashboard_fresh's
dimension.

Usage:
    python3 scripts/check_dashboard_coverage.py            # exit 1 on any gap
    python3 scripts/check_dashboard_coverage.py --verbose  # list every placement

Python 3.9+. Standard library only.
"""

import argparse
from html.parser import HTMLParser
import collections
import datetime
import hashlib
import html as _html
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
from coverage_checks import held_gaps as _held                      # noqa: E402  (0.92.0, dev #1002: the held roles)
from coverage_checks.folds import check_folds                       # noqa: E402
from coverage_checks.picks import check_picks                       # noqa: E402
from coverage_checks.script import check_scripts                    # noqa: E402
from coverage_checks.today_gaps import check_today, ledger_predates_today  # noqa: E402
from dashboard.markup import THEIRS_SITES                           # noqa: E402
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
_FULL_REC_RE = re.compile(r'data-rec="([^"]+)" data-full="1"')
_MORE_RE = re.compile(r'data-more="([^"]+):(\d+)"')
# A row's opening tag, and its data attributes.
_ROW_RE = re.compile(r'<(\w+)\b([^>]*?)\sdata-(rec|ref)="([^"]+)"([^>]*)>')
_DATA_ATTR_RE = re.compile(r'\sdata-([a-z][a-z0-9-]*)="([^"]*)"')
# dev #820 / public #175 (design 2.4, N14): the process-state block and the conservation line. The page
# renders `lifecycle.process_report`'s own lines; this check recomputes the report from the stores at the
# page's own generation time and holds the page to it.
# Owner request 2026-11-12 (C7), which SUPERSEDES N14's "never collapsed" for the dashboard: the block is
# COLLAPSED at the bottom in `<details id="pipeline-details">` (told apart from the inner drill
# `<details class="pdrill" open>` by that id), the page's ONE generation time is the `data-generated` on the
# `.updated` line (read page-wide), and the top carries ONE `data-pipeline-alert` line only when
# `lifecycle.pipeline_alerts` is non-empty (or PIPELINE NOT CHECKED).
_PROCESS_SECTION_RE = re.compile(r'<section class="process" id="process-state">(.*?)</section>', re.S)
_PLINE_RE = re.compile(r'<div class="pline[^"]*">(.*?)</div>', re.S)
_PRUN_RE = re.compile(r'<div class="prun">(.*?)</div>', re.S)
_PGEN_RE = re.compile(r'data-generated="([^"]+)"')
_GEN_RUN_RE = re.compile(r'data-generating-run="([^"]*)"')
_CONS_RE = re.compile(r'<div class="conservation" data-conservation="1">(.*?)</div>', re.S)
_PDETAILS_OPEN_RE = re.compile(r'<details\b([^>]*\bid="pipeline-details"[^>]*)>')
_DETAILS_TAG_RE = re.compile(r'<details\b|</details>')
_UPDATED_RE = re.compile(r'<div class="updated"')
_FIRST_SECTION_RE = re.compile(r'<section class="first"')
_ALERT_ATTR_RE = re.compile(r'data-pipeline-alert="([^"]*)"')
_ALERT_EL_RE = re.compile(r'<div class="palert[^"]*" data-pipeline-alert="[^"]*">(.*?)</div>', re.S)
_SCRIPT_BLOCK_RE = re.compile(r'<script\b.*?</script>', re.S | re.I)
_ALERT_GLYPH = "⚠ "
_ALERT_TAIL = " — details"


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
    # jobsearch 0.88.0 (dev #914, #915): the Network section is `your_move.communication_plan`, the ONE
    # owner of its membership, so a person, role or channel it lists is EXPECTED here (a row the page forgot is
    # UNPLACED). This proves rendered == derived; that the derivation is RIGHT rests on test_communication_plan.py.
    # Not wrapped in a try: a derivation that crashes must fail the gate loudly, never shrink the expected set.
    import your_move as _ymod
    for r in _ymod.communication_plan(root, today.isoformat())["rows"]:
        exp.setdefault(r["key"], {"kind": r["key"].split(":", 1)[0], "group": r["group"]})
    # dev #834 (M4, M5): the Network list. The rows the owner acts on (look-into companies, unrecorded
    # chats, bookings with no chat, suggestion asks, unobserved sends, drafting proposals) come from
    # `funnel_report.network_rows`, the ONE derivation the renderer also calls, so a row the page forgot is
    # UNPLACED here. Not in a try, for the reason above: a derivation that crashes fails the gate loudly.
    import funnel_report as _fr
    for r in _fr.network_rows(root, today.isoformat())["rows"]:
        exp[r["key"]] = {"kind": "net", "group": r["group"]}
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


def rec_id(key):
    """The id a primary row for `key` must carry - the first 12 hex digits of sha1(key),
    computed HERE independently of generate_dashboard.rec_id on purpose: a renderer that
    drifted from its own checker is the defect LINKED exists to catch."""
    return "rec-" + hashlib.sha1(str(key).encode("utf-8")).hexdigest()[:12]


_ID_ATTR_RE = re.compile(r'\sid="([^"]*)"')


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


def _plain(fragment):
    return _html.unescape(re.sub(r"<[^>]+>", "", fragment))


def _outer_details_end(page, start):
    """Index just past the `</details>` that closes the `<details>` opened at `start`, counting nested
    `<details>` (the drill list is one), or None when it never closes."""
    depth = 0
    for m in _DETAILS_TAG_RE.finditer(page, start):
        depth += 1 if m.group(0).startswith("<details") else -1
        if depth == 0:
            return m.end()
    return None


def _process_position_gaps(page, sec_start):
    """The C7 position gaps: the process block is the page's collapsed bottom block. The outer
    `<details id="pipeline-details">` must exist, carry no `open`, contain the process section, follow the
    `.updated` line and every list, and precede the conservation line when there is one; with no
    conservation line (the report could not be computed) nothing but a script may follow it."""
    why = []
    dm = _PDETAILS_OPEN_RE.search(page)
    if not dm:
        return ["PROCESS BLOCK NOT COLLAPSED — the process section is not inside "
                "`<details id=\"pipeline-details\">`, so it is open on the page (owner request 2026-11-12: "
                "the block is collapsed at the bottom)"]
    if re.search(r'(?:^|\s)open(?:\s|=|$)', dm.group(1)):
        why.append("the outer `<details>` carries `open`")
    end = _outer_details_end(page, dm.start())
    if end is None:
        why.append("the outer `<details>` never closes")
    elif not dm.start() < sec_start < end:
        why.append("the process section is not inside it")
    upd = _UPDATED_RE.search(page)
    if upd and dm.start() < upd.start():
        why.append("it precedes the `Generated` line")
    last_row = max([m.start() for m in re.finditer(r'data-rec="', page)]
                   + [m.start() for m in _FIRST_SECTION_RE.finditer(page)] + [-1])
    if dm.start() < last_row:
        why.append("it sits above a list, not after the lists")
    if end is not None:
        cons = _CONS_RE.search(page)
        tail = page[end:cons.start()] if cons else page[end:]
        tail = _SCRIPT_BLOCK_RE.sub("", tail).strip()
        if cons and cons.start() < dm.start():
            why.append("the conservation line precedes it")
        elif tail:
            why.append("%s follows it" % ("something other than the conservation line" if cons
                                          else "something (the page has no conservation line, so it "
                                               "must be last)"))
    if not why:
        return []
    return ["PROCESS BLOCK NOT COLLAPSED — %s (the block is a closed `<details>` after the lists and "
            "before the conservation line, owner request 2026-11-12)" % "; ".join(why)]


def _alert_gaps(page, rep, not_checked):
    """The C7 alert gaps. With a computed `rep`: `lifecycle.pipeline_alerts(rep)` non-empty needs exactly
    one `data-pipeline-alert` whose text is `⚠ ` + `alert_line(rep)` + ` — details`, and empty needs none.
    With `not_checked` (no report could be computed and the page says so) the one alert must say
    PIPELINE NOT CHECKED. Either way one alert, between the `Generated` line and the first list."""
    import lifecycle as _lifecycle
    gaps = []
    marks = list(_ALERT_ATTR_RE.finditer(page))
    els = _ALERT_EL_RE.findall(page)
    if not_checked:
        if not marks:
            gaps.append("PIPELINE ALERT MISSING — the page says PIPELINE NOT CHECKED in its block but not at "
                        "the top, where a reader would see it")
        elif not any("PIPELINE NOT CHECKED" in _plain(e) for e in els):
            gaps.append("PIPELINE ALERT DISAGREES — the top line does not say PIPELINE NOT CHECKED")
    else:
        want = _lifecycle.alert_line(rep)
        if want is not None and not marks:
            gaps.append("PIPELINE ALERT MISSING — the pipeline is not healthy (%s) but the page's top has "
                        "no `data-pipeline-alert` line" % want)
        elif want is None and marks:
            gaps.append("PIPELINE ALERT UNEXPECTED — the pipeline is healthy and the page's top still "
                        "carries an alert (a healthy page shows nothing there)")
        elif want is not None and els:
            text = _plain(els[0])
            if text.startswith(_ALERT_GLYPH):
                text = text[len(_ALERT_GLYPH):]
            if text.endswith(_ALERT_TAIL):
                text = text[:-len(_ALERT_TAIL)]
            if text != want:
                gaps.append("PIPELINE ALERT DISAGREES — the page's alert reads %r; alert_line says %r"
                            % (text, want))
    if len(marks) > 1:
        gaps.append("PIPELINE ALERT MISPLACED — the page carries %d alert lines; exactly one, at the top"
                    % len(marks))
    elif marks:
        at = marks[0].start()
        upd, first = _UPDATED_RE.search(page), _FIRST_SECTION_RE.search(page)
        dm = _PDETAILS_OPEN_RE.search(page)
        if (upd and at < upd.start()) or (first and at > first.start()) or (dm and at > dm.start()):
            gaps.append("PIPELINE ALERT MISPLACED — the alert must sit between the `Generated` line and the "
                        "first list, above the collapsed process block")
    return gaps


# ⭐ dev #834 (M5) — THE TOP REGION IS THE OWNER'S, AND IT DOES NOT GROW. Owner request 0.84.0 C7: between
# the jump bar and the lists the page shows the title, the `Generated` line and nothing else when healthy,
# or ONE pipeline alert. Network-first adds a Network LIST after Drafts; it adds no summary line above the
# lists. The region is everything before the first list (the `<section class="first">`, or, on a page with
# no lists, the "Not on this page" note or the process block); once the jump bar, the `<title>` and
# `<style>` the artifact begins with, the `<h1>`, the `.updated` line and at most one alert element are
# taken out, it must be empty.
_TOP_END_RE = re.compile(r'<section class="first"|<div class="sub" style="margin-top:26px"|<details class="pstate"')
_TOP_ALLOWED = (
    re.compile(r"<title>.*?</title>", re.S), re.compile(r"<style>.*?</style>", re.S),
    re.compile(r'<nav class="jumpbar".*?</nav>', re.S), re.compile(r"<h1>.*?</h1>", re.S),
    re.compile(r'<div class="updated"[^>]*>.*?</div>', re.S),
)


def check_top_region(page):
    """(gaps, summary): `TOP REGION GREW` when anything other than the jump bar, the title, the `Generated`
    line and one `data-pipeline-alert` element precedes the lists (dev #834, M5)."""
    end = _TOP_END_RE.search(page)
    region = page[:end.start()] if end else page
    for rx in _TOP_ALLOWED:
        region = rx.sub("", region)
    region = _ALERT_EL_RE.sub("", region, count=1)
    extra = _plain(region).strip()
    if not extra and not region.strip():
        return [], "top region: jump bar, title, Generated line, at most one alert"
    shown = (extra or region.strip())[:90]
    return (["TOP REGION GREW — %r sits between the jump bar and the lists. The owner's 0.84.0 C7 request: "
             "only the jump bar, the title, the `Generated` line and one pipeline alert are allowed there; "
             "a network summary lives in the weekly review and views/network_strategy.md, never above the "
             "lists" % shown], "top region: GREW")


def check_network_note(page, root, today):
    """(gaps, summary): the "Not on this page" note counts the proposals the owner has SENT (they are status,
    not a row), so a sent proposal is accounted for rather than lost (dev #834, M5; ADR-024 coverage)."""
    import funnel_report as _fr
    want = _fr.network_rows(root, today.isoformat())["sent_proposals"]
    m = re.search(r'data-net-sent-proposals="(\d+)"', page)
    have = int(m.group(1)) if m else 0
    if have != want:
        return (["NETWORK NOTE DISAGREES — the \"Not on this page\" note counts %d sent proposal(s); the store "
                 "has %d" % (have, want)], "network note: DISAGREES")
    return [], "network note: %d sent proposal(s) counted" % want


# ─────────────────────────────────────────────────────────────────────────────
# jobsearch 0.88.0 (dev #915, #902; design 7.2, 8): THREE NEW GATES.
#
#   NO CLI          the candidate-facing page renders no command. Only ENGINE-AUTHORED markup is scanned: every
#                   element carrying `data-theirs` (the closed `dashboard_actions.THEIRS_SITES`, set by the
#                   renderer around the candidate's own words) is removed with its subtree, as is every
#                   <script>/<style> body, and in a copy-as-prompt textarea every line that is quoted candidate
#                   text (`> `) or one of the draft block's two data lines (`Draft key:`, `Title:`). A `data-theirs`
#                   element holding a button, a textarea, a `data-rec`/`data-ref` row or a `data-action` is its own
#                   GAP (`THEIRS WRAPS ENGINE MARKUP`): the exclusion cannot become a hiding place.
#                   It reports `scanned N engine-authored chars, excluded M data-theirs spans` and cannot pass on
#                   N == 0 (NOT CHECKED, exit 2): a page it read nothing of is not a clean page.
#   SUBJECT TWICE   a subject (`data-subject`) on two primary rows across Network, Drafts and Targets. Several drafts
#                   to one person are ONE appearance (Drafts is a list of messages); two Network rows, or a subject in
#                   two sections, are a GAP. It proves rendered == derived, never derived == correct: membership
#                   rests on tests/test_communication_plan.py.
#   PURSUE COUNT    the page's Opportunities-to-pursue count equals `process_report`'s ready count minus the ready
#                   roles docs/design-stage-honesty.md 3.2 enumerates (a reply owed, ended/withdrawn). A ready role in
#                   any OTHER non-`new` cell is its own GAP. The expected side reads the RAW `pursuit_state` cell, never
#                   `pursuit_with_stage`, so a regression in that function moves only the page side.
#
# EXIT CODES: 0 clean (and 0 for "no page yet", whose last line is `NOT CHECKED`), 1 a GAP, 2 a gate that could not
# look (its last line `NOT CHECKED: <check> (<why>)`). `NOT_CHECKED` collects those reasons during `check()`.
# ─────────────────────────────────────────────────────────────────────────────
NOT_CHECKED = []
NO_CLI_PATTERNS = (re.compile(r"\brecord\.py\b"), re.compile(r"\bpython3\b"),
                   re.compile(r"~/\.claude/jobsearch/run"), re.compile(r"\b[a-z_]+\.py\s+--?[a-z]"))
DATA_LINE_PREFIXES = ("> ", "Draft key: ", "Title: ")
# attributes whose value is a record key or a link, which may carry the candidate's own title (`draft:<title>`)
_KEY_ATTRS = frozenset({"data-rec", "data-ref", "data-subject", "data-cap-key", "id", "href", "for", "name",
                        "data-more", "data-full", "data-theirs"})
# 2026-11-19 (dashboard-redesign D2, design §6.1): a tick box (`class="pick"`) and a group button (`class="pick-go"`)
# carry a record key (`data-pick`), the Python-written record line with the reader's label (`data-line`), the block's
# head and tail (`data-head`, `data-tail`) and the reader's label (`aria-label`): keys and the candidate's own words,
# never engine prose. Skipped on those two elements only; visible text and every other attribute are still scanned.
_PICK_ATTRS = {"pick": ("data-pick", "data-line", "aria-label"), "pick-go": ("data-head", "data-tail")}
_VOID_TAGS = frozenset("area base br col embed hr img input link meta param source track wbr".split())


class _Scrub(HTMLParser):
    """Collects the engine-authored text and attribute values of a page, with `data-theirs` subtrees removed."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.skip_at, self.engine = [], None, []
        self.theirs_spans, self.wraps, self.unknown_sites = 0, [], []
        self.in_textarea = False

    def _push(self, tag):
        if tag not in _VOID_TAGS:
            self.stack.append(tag)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        inside = self.skip_at is not None
        if "data-theirs" in a and any(k in a for k in ("data-rec", "data-ref", "data-action")):
            self.wraps.append("<%s data-theirs> is itself a record row or an action" % tag)
        if inside:
            if tag in ("button", "textarea") or any(k in a for k in ("data-rec", "data-ref", "data-action")):
                self.wraps.append("<%s> inside data-theirs" % tag)
            self._push(tag)
            return
        skip = _PICK_ATTRS.get(a.get("class"), ())
        for k, v in attrs:
            if k not in _KEY_ATTRS and k not in skip and v:
                self.engine.append(v)
        if "data-theirs" in a:
            if a["data-theirs"] not in THEIRS_SITES:
                self.unknown_sites.append(a["data-theirs"])
            self.theirs_spans += 1
            self._push(tag)
            if tag not in _VOID_TAGS:
                self.skip_at = len(self.stack)
            return
        self._push(tag)
        if tag == "textarea":
            self.in_textarea = True

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID_TAGS and self.stack and self.stack[-1] == tag:
            self.stack.pop()
            if self.skip_at is not None and len(self.stack) < self.skip_at:
                self.skip_at = None

    def handle_endtag(self, tag):
        if tag in _VOID_TAGS or tag not in self.stack:
            return
        while self.stack:
            if self.stack.pop() == tag:
                break
        if self.skip_at is not None and len(self.stack) < self.skip_at:
            self.skip_at = None
        if tag == "textarea":
            self.in_textarea = False

    def handle_data(self, data):
        if self.skip_at is not None or (self.stack and self.stack[-1] in ("script", "style")):
            return
        if self.in_textarea:
            data = "\n".join(ln for ln in data.split("\n") if not ln.startswith(DATA_LINE_PREFIXES))
        self.engine.append(data)


def check_no_cli(page):
    """(gaps, line): NO CLI over the engine-authored part of `page` (see the banner above)."""
    sc = _Scrub()
    try:
        sc.feed(page)
        sc.close()
    except Exception as e:                                       # noqa: BLE001 - said, never a pass
        NOT_CHECKED.append("no CLI (the page could not be parsed: %s: %s)" % (type(e).__name__, str(e)[:80]))
        return [], "no CLI: NOT CHECKED"
    gaps = []
    for site in sc.unknown_sites:
        gaps.append("THEIRS SITE UNKNOWN -- data-theirs=%r is not one of dashboard_actions.THEIRS_SITES" % site)
    for w in sc.wraps:
        gaps.append("THEIRS WRAPS ENGINE MARKUP -- %s: the exclusion may wrap the candidate's words, never a button, "
                    "a record row or an action" % w)
    text = "\n".join(sc.engine)
    n = len(text.strip())
    if n == 0:
        NOT_CHECKED.append("no CLI (0 engine-authored characters were scanned)")
        return gaps, "no CLI: NOT CHECKED (0 engine-authored chars)"
    for pat in NO_CLI_PATTERNS:
        for m in pat.finditer(text):
            ctx = text[max(0, m.start() - 30):m.end() + 40].replace("\n", " ")
            gaps.append("NO CLI -- the page shows a command: ...%s... (engine-authored text: reword it in plain "
                        "words, or wrap the candidate's own text in data-theirs)" % ctx)
            break
    return gaps, ("no CLI: scanned %d engine-authored chars, excluded %d data-theirs spans" % (n, sc.theirs_spans))


_H2_RE = re.compile(r'<h2 id="([^"]+)"')
_SUBJECT_SECTIONS = {"phase-network": "network", "phase-targets": "targets", "phase-outreach-approvals": "drafts"}


def check_subject_twice(page):
    """(gaps, line): SUBJECT TWICE. A subject on two primary rows across Network, Drafts and Targets is a GAP. Several
    Drafts rows for one subject count once: a person may have two drafts staged."""
    heads = [(m.start(), m.group(1)) for m in _H2_RE.finditer(page)]
    seen = {}
    for m in _ROW_RE.finditer(page):
        if m.group(3) != "rec":
            continue
        attrs = m.group(2) + " " + m.group(5)
        subj = dict(_DATA_ATTR_RE.findall(attrs)).get("subject")
        if not subj:
            continue
        sect = None
        for pos, hid in heads:
            if pos <= m.start():
                sect = hid
        name = _SUBJECT_SECTIONS.get(sect)
        if name:
            seen.setdefault(_html.unescape(subj), []).append(name)
    gaps = []
    for subj, where in sorted(seen.items()):
        sections = sorted(set(where))
        rows_outside_drafts = [w for w in where if w != "drafts"]
        if len(sections) > 1 or len(rows_outside_drafts) > 1:
            gaps.append("SUBJECT TWICE -- %s is a primary row %d time(s) across %s; a subject has ONE primary row "
                        "on the page" % (subj, len(where), ", ".join(sections)))
    return gaps, "subjects: %d on primary rows, %d twice" % (len(seen), len(gaps))


_PURSUE_RE = re.compile(r'id="phase-pipeline-roles">[^<]*<span class="tcount">(\d+)</span>')


def _lifecycle_facts(root, now):
    """`(data, process_report, ctx, your_move, title matcher)` at `now`: PURSUE COUNT and the held roles read it (0.92.0, §E)."""
    import lifecycle as _lifecycle
    import your_move as _ym
    data, cfg = _lifecycle.load_data(root), _ym._root_cfg(root)
    return (data, _lifecycle.process_report(data, now), _ym.lifecycle_context(data["opportunities"], now, data), _ym,
            lambda t: _ym._profile.title_matches(t, cfg))


def check_pursue_count(page, root):
    """(gaps, line): PURSUE COUNT (dev #902). See the banner above for the rule."""
    m_gen = _PGEN_RE.search(page)
    try:
        now = datetime.datetime.fromisoformat(_html.unescape(m_gen.group(1)))
    except (AttributeError, ValueError):
        NOT_CHECKED.append("pursue count (the page carries no readable generation time)")
        return [], "pursue count: NOT CHECKED"
    m = _PURSUE_RE.search(page)
    if m:
        shown = int(m.group(1))
    elif "Opportunities (0)" in page and 'id="phase-pipeline-roles"' not in page:
        shown = 0
    else:
        NOT_CHECKED.append("pursue count (no Opportunities heading and no empty-state label on the page)")
        return [], "pursue count: NOT CHECKED"
    try:
        data, rep, ctx, _ym, _matches = _lifecycle_facts(root, now)
        ready = [o for o in data["opportunities"] if ctx.stage_of_opp(o).name == "ready"]
        cells = {}
        for o in ready:
            p = _ym.pursuit_state(root, o, o.get("_applications") or [])      # RAW: never pursuit_with_stage
            cells[o.get("id")] = (p.get("state"), p.get("cell"), p.get("ended_because"))
    except Exception as e:                                       # noqa: BLE001 - said, never a pass
        NOT_CHECKED.append("pursue count (%s: %s)" % (type(e).__name__, str(e)[:100]))
        return [], "pursue count: NOT CHECKED"
    gaps, exempt = [], 0
    for oid, (state, cell, because) in sorted(cells.items()):
        if state == "new":
            continue
        if cell == "reply-owed" or (state == "ended" and because == "withdrawn"):
            exempt += 1                    # docs/design-stage-honesty.md 3.2: the enumerated cells
        else:
            gaps.append("PURSUE COUNT -- ready role %s sits in pursuit cell %r/%r, which design-stage-honesty 3.2 does "
                        "not enumerate" % (oid, state, cell))
    expected = rep.ready - exempt
    if shown != expected:
        gaps.append("PURSUE COUNT -- the page shows %d; process_report's ready count (%d) minus the 3.2 exceptions (%d)"
                    " is %d" % (shown, rep.ready, exempt, expected))
    return gaps, "pursue count: page %d, process_report ready %d less %d enumerated" % (shown, rep.ready, exempt)


def check_process_block(page, root):
    """(gaps, summary) for the process-state block (dev #820 / public #175, N14, TOT; owner request
    2026-11-12, C7). The page must carry the block, COLLAPSED at the bottom (`_process_position_gaps`),
    and its lines must be EXACTLY `lifecycle.process_report(...).block_lines` (without the conservation
    line), its open-run lines `run_lines`, and its last line the `conservation_line`, recomputed here from
    the stores at the page's own generation time (the one `data-generated`, read page-wide; two are
    `GENERATION TIME AMBIGUOUS`). The top carries the one alert line exactly when
    `lifecycle.pipeline_alerts` says the pipeline is not healthy (`_alert_gaps`), recomputed with the run
    the page names in `data-generating-run` left out, as the page did. A page that drops the block, words a
    count differently, or prints a conservation line that does not add up is a gap, never a pass; a
    lifecycle that cannot be read is said (`NOT CHECKED`), and the page must then say `PIPELINE NOT
    CHECKED` in the block and at the top."""
    m = _PROCESS_SECTION_RE.search(page)
    if not m:
        return (["PROCESS BLOCK MISSING — the page has no `process-state` section, so a role a run did "
                 "not finish, a role waiting for intake and what no pass looked at are not on it "
                 "(design 2.4: the block is never absent)"],
                "process: block MISSING")
    sec = m.group(1)
    gens = _PGEN_RE.findall(page)
    if not gens:
        return (["PROCESS BLOCK HAS NO GENERATION TIME — a stale render must read as stale (N14)"],
                "process: no generation time")
    gaps = []
    if len(gens) > 1:
        gaps.append("GENERATION TIME AMBIGUOUS — the page carries %d `data-generated` times; it has ONE, on "
                    "the `Generated` line, and the pipeline is recomputed at that instant" % len(gens))
    try:
        now = datetime.datetime.fromisoformat(_html.unescape(gens[0]))
    except ValueError:
        return (gaps + ["PROCESS BLOCK GENERATION TIME UNREADABLE — %r" % gens[0]],
                "process: generation time unreadable")
    gaps += _process_position_gaps(page, m.start())
    run_m = _GEN_RUN_RE.search(page)
    try:
        import lifecycle as _lifecycle
        rep = _lifecycle.process_report(_lifecycle.load_data(root), now,
                                        generating_run=_html.unescape(run_m.group(1)) if run_m else None)
    except Exception as e:                                      # noqa: BLE001 - said, never a pass
        if "PIPELINE NOT CHECKED" in sec:
            gaps += _alert_gaps(page, None, True)
            return gaps, "process: NOT CHECKED here (%s: %s); the page says so too" % (
                type(e).__name__, str(e)[:100])
        return (gaps + ["PROCESS BLOCK NOT VERIFIABLE — the role lifecycle cannot be read here (%s: %s) and "
                        "the page does not say PIPELINE NOT CHECKED" % (type(e).__name__, str(e)[:100])],
                "process: NOT CHECKED")
    if "PIPELINE NOT CHECKED" in sec:
        gaps.append("PROCESS BLOCK SAYS NOT CHECKED — the page claims the lifecycle could not be read, "
                    "but it reads here; regenerate")
    else:
        gaps += _alert_gaps(page, rep, False)
        page_lines = [_plain(x) for x in _PLINE_RE.findall(sec)]
        want = list(rep.block_lines[:-1])
        if page_lines != want:
            extra = [x for x in page_lines if x not in want]
            missing = [x for x in want if x not in page_lines]
            gaps.append("PROCESS BLOCK DISAGREES — the page's lines differ from process_report's "
                        "block_lines (page only: %s; report only: %s)"
                        % (extra[:2] or "none", missing[:2] or "none"))
        runs = [_plain(x) for x in _PRUN_RE.findall(sec)]
        if runs != list(rep.run_lines):
            gaps.append("OPEN RUNS DISAGREE — the page says %s; the journal says %s"
                        % (runs or "nothing", list(rep.run_lines)))
        cons = _CONS_RE.search(page)
        if not cons:
            gaps.append("CONSERVATION LINE MISSING — the page does not print `ROLES N = ...`, so a role "
                        "could leave the count unseen")
        elif _plain(cons.group(1)) != rep.conservation_line:
            gaps.append("CONSERVATION LINE DISAGREES — the page prints %r; process_report says %r"
                        % (_plain(cons.group(1)), rep.conservation_line))
    return gaps, "process: %d failure(s), %d waiting, %d ready, %d your read (conservation %s)" % (
        rep.failure, rep.waiting, rep.ready, rep.your_read, "MISMATCH" if rep.mismatch else "agrees")


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
    del NOT_CHECKED[:]
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
    predates = ledger_predates_today(ledger)
    if predates:
        return predates, [], []
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
    counts = {"rendered": 0, "remainder": 0, "terminal": 0, "elsewhere": 0, "referenced": 0}
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
        elif disp == "referenced":   # dev 973: a reference row to its subject's ONE primary row, the key `where`
            counts["referenced"] += 1
            if where not in on_page or ('data-ref="%s"' % _html.escape(str(where), False)) not in page:
                gaps.append("REFERENCED, NO PRIMARY OR NO REFERENCE ROW — %s (ledger says a reference to %s)"
                            % (key, where))
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
    l_gaps, l_line = check_links(page, exp)
    gaps.extend(l_gaps)
    s_gaps, _s_line = check_scripts(page, ledger, exp)
    gaps.extend(s_gaps)
    # dashboard-redesign E (design §3.6, §4, §6.1): the page checks of `coverage_checks/`, each pure.
    td_line = f_line = pk_line = "today, folds, picks: NOT CHECKED"
    try:
        (td_gaps, td_line), (f_gaps, f_line), (pk_gaps, pk_line) = (
            check_today(page, ledger, exp), check_folds(page, ledger, exp), check_picks(page, ledger, exp))
        gaps.extend(td_gaps + f_gaps + pk_gaps)
    except Exception as e:                                       # noqa: BLE001 - said, never a pass
        NOT_CHECKED.append("today, folds, picks (the page could not be walked: %s: %s)" % (type(e).__name__, e))
    x_lines = [l_line]               # the page checks below, in their order; each line is printed in that order
    for fn, args in ((check_warm_path, (page, root, today)), (check_process_block, (page, root)), (check_top_region, (page,)),
                     (check_network_note, (page, root, today)), (check_no_cli, (page,)), (check_subject_twice, (page,)),
                     (check_pursue_count, (page, root)),
                     (_held.run, (page, ledger, lambda now: _lifecycle_facts(root, now), NOT_CHECKED))):   # 0.92.0, dev #1002
        x_gaps, x_line = fn(*args)
        gaps.extend(x_gaps)
        x_lines.append(x_line)
    n_exp = len(exp)
    n_placed = n_exp - sum(1 for g in gaps if g.startswith("UNPLACED"))
    lines = ["covered %d of %d record(s) — %d rendered · %d referenced · %d in counted remainders · "
             "%d terminal · %d elsewhere (generated %s, prep window %d days)"
             % (n_placed, n_exp, counts["rendered"], counts["referenced"], counts["remainder"],
                counts["terminal"], counts["elsewhere"], today.isoformat(), horizon)]
    lines.extend(x_lines + [td_line, f_line, pk_line])
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
    if not gaps and NOT_CHECKED:
        for why in NOT_CHECKED:
            print("  - NOT CHECKED: %s" % why)
        print("NOT CHECKED: %s" % NOT_CHECKED[-1])
        return 2
    if not gaps:
        print("  CLEAN — every record is rendered, counted, or terminal; nothing renders "
              "outside its window; every record has ONE primary row and every reference and "
              "link resolves")
        return 0
    print("\n" + "=" * 72)
    print("%d GAP(S)" % len(gaps))
    print("=" * 72)
    for g in gaps:
        print("  - " + g)
    for why in NOT_CHECKED:
        print("  - NOT CHECKED: %s" % why)
    print("\n  Remedy: regenerate (generate_dashboard.py) and re-check; a gap that survives a "
          "regeneration is a renderer defect — report it, never hand-edit the page.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
