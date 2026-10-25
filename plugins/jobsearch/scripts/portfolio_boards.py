#!/usr/bin/env python3
"""A PE/VC firm's portfolio job board: which companies and roles it produced, and whether it is covered
(dev #765; design-portfolio-boards.md, as amended by its review).

    portfolio_boards.py                     # every channel that carries `portfolio_of`
    portfolio_boards.py --board <channel>   # one board
    portfolio_boards.py --json              # the same, as data
    portfolio_boards.py --rows              # the paste-ready company + channel row templates (placeholders)
    portfolio_boards.py --today YYYY-MM-DD

⭐ WHAT A PORTFOLIO BOARD IS HERE. A firm publishes one board listing many portfolio companies' roles. Both
boards #765 names run on a platform whose terms forbid crawling, so a portfolio board is a `job-board`
channel with `access: manual-candidate` (ADR-037): the CANDIDATE opens it, and the engine never visits it,
polls it or hands it to a browser. THIS SCRIPT FETCHES NOTHING. It reads the profile's stores and the
journal and prints. It imports no network, browser or send module, and writes nothing (a source-scan test
holds it to that).

⭐ THE FIRM IS AN ORDINARY `companies` ROW, AND THE LINK IS DERIVED (ADR-022). `channels[].portfolio_of`
names the firm a board belongs to. A role's link to its firm is never stored beside the sighting that
evidences it: `backers_of` computes it from the sightings (a sighting on a `portfolio_of` channel) and from
`companies[].backed_by`, the one thing a sighting cannot say (a backing the candidate states by hand). A
stored copy would be a second record that could disagree, and `record.py unlink-sibling` (which stamps
`split_to` on a false merge's sighting) would leave it pointing at the wrong company. EVERY reader goes
through `backers_of`: this script and `warm_path.py`.

⭐ "NOT COVERED", NEVER ZERO. A manual-candidate board has no fetch to fail. Its failure is that nobody
looked. So a board is COVERED exactly when `channels_due.review_rows` says its state is `current`
(strictly before its next due date; on the due date itself it is `due`), and a board that is not covered
NEVER prints a role count: "0 roles" is printed only for a covered board that genuinely produced none. A
not-covered board lists what earlier reviews recorded under a heading that says the board is not covered
now. `retired` reads as "retired, not reviewed by design" and is not counted against the exit code;
`on-inbound` and `unscheduled` read NOT CHECKED. The automated half is reported per COMPANY, never summed
into the board's line: each portfolio company's own feed (if it has one) is read through
`journal.feed_company_state`, which never reads "covered" off a company's absence from the failure list.

Exit codes: 0 every (non-retired) board is covered, or there is no board; 4 at least one board is not
covered or not checked (the `feed_poll.py` convention); 3 the stores cannot be read or hold a malformed
portfolio field; 2 a usage error (an unknown `--board`).

Python 3.9+. Standard library only. Read-only.
"""

import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _root import profile_root as _profile_root

ROOT = _profile_root()
# The channel field that makes a channel a portfolio board. Named ONCE here so a script that WRITES the field (the
# channel catalog's opt-in, dev #769) does not retype it: the source-scan test holds every other script to never
# naming the link fields, so a second derivation of the link cannot drift.
FIRM_LINK_FIELD = "portfolio_of"
EXIT_NOT_COVERED = 4
EXIT_STORES = 3


class StoreError(Exception):
    """A store this report needs cannot be read, or holds a malformed portfolio field."""


def _is_folded(o):
    return bool(o.get("duplicate_of"))


# ---------------------------------------------------------------------------------------------------
# The one resolver: a company's backing firms.
# ---------------------------------------------------------------------------------------------------

def backers_of(company_id, companies, channels, opportunities):
    """The firms that back `company_id`, as a list sorted by `firm_id`:

        {"firm_id", "via": "board" | "stated", "channel_ids": [board channel ids], "stated": bool}

    * DERIVED (`via: board`): every sighting, on any opportunity whose `company_id` is `company_id`,
      that has no `split_to` (a split listing no longer evidences the row, dev #728) and whose channel
      carries `portfolio_of`. That channel's `portfolio_of` is a backer. A folded row (`duplicate_of`)
      still counts: its company is the same company.
    * STATED (`via: stated`): every id in the company's own `backed_by`.
    A firm reached both ways appears ONCE, `via: board`, with `stated: true`.

    Pure: it reads only what it is handed. `warm_path.py` and this script's report both call it, and a
    source-scan test holds every other script to not reading `portfolio_of` or `backed_by` itself."""
    by_channel = {c.get("id"): c for c in channels or [] if isinstance(c, dict)}
    derived = {}
    for o in opportunities or []:
        if o.get("company_id") != company_id:
            continue
        for sg in o.get("sightings") or []:
            if not isinstance(sg, dict) or sg.get("split_to"):
                continue
            ch = by_channel.get(sg.get("channel_id"))
            firm = ch.get("portfolio_of") if ch else None
            if isinstance(firm, str) and firm:
                derived.setdefault(firm, set()).add(ch["id"])
    stated = []
    for c in companies or []:
        if c.get("id") == company_id and isinstance(c.get("backed_by"), list):
            stated = [b for b in c["backed_by"] if isinstance(b, str) and b]
    out = []
    for firm in sorted(set(derived) | set(stated)):
        out.append({"firm_id": firm, "via": "board" if firm in derived else "stated",
                    "channel_ids": sorted(derived.get(firm, ())), "stated": firm in stated})
    return out


def boards(channels):
    """Every channel that is a portfolio board (it carries `portfolio_of`), in store order."""
    return [c for c in channels or [] if isinstance(c, dict) and "portfolio_of" in c]


# ---------------------------------------------------------------------------------------------------
# Stores
# ---------------------------------------------------------------------------------------------------

def _load_rows(root, name, required):
    path = os.path.join(root, "data", name)
    try:
        with open(path, encoding="utf-8") as fh:
            lines = [l for l in fh if l.strip()]
    except FileNotFoundError:
        if required:
            raise StoreError("%s is missing" % name)
        return []
    except OSError as e:
        raise StoreError("%s cannot be read (%s)" % (name, e))
    rows = []
    for n, line in enumerate(lines, 1):
        try:
            row = json.loads(line)
        except ValueError:
            raise StoreError("%s has a row that is not valid JSON (row %d)" % (name, n))
        if not isinstance(row, dict):
            raise StoreError("%s row %d is not an object" % (name, n))
        rows.append(row)
    return rows


def load_stores(root):
    """`(companies, channels, opportunities)`. A malformed row, or a malformed portfolio field
    (`validate_data.check_portfolio_links`), raises `StoreError`: a refusal is never an empty report."""
    companies = _load_rows(root, "companies.jsonl", False)
    channels = _load_rows(root, "channels.jsonl", False)
    opps = _load_rows(root, "opportunities.jsonl", False)
    import validate_data as _vd
    problems = _vd.check_portfolio_links(companies, channels)
    if problems:
        raise StoreError("the portfolio fields are malformed: " + "; ".join(problems))
    return companies, channels, opps


# ---------------------------------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------------------------------

def coverage(channel, today):
    """`{"state", "text"}` for one board. COVERED is `channels_due.review_rows` state `current`, imported
    and never re-derived (B6): on the due date itself the state is `due`, so the board is NOT covered.

        covered      COVERED: you reviewed it <date> (<cadence>; next due <date>)
        not-covered  NOT COVERED: never reviewed | last reviewed <date>, due <date> (<n> days over)
        retired      RETIRED: not reviewed by design
        not-checked  NOT CHECKED: <why> (on-inbound, an unrecognized cadence, or a channel the review
                     queue does not cover)"""
    import channels_due as _cd
    rows = _cd.review_rows([channel], today)
    cadence = channel.get("review_cadence")
    last = channel.get("last_reviewed")
    if not rows:
        return {"state": "not-checked", "text": "NOT CHECKED: this channel type is not in the review queue",
                "last_reviewed": last, "next_due": None}
    _c, state, detail = rows[0]
    nxt = detail.get("next_due")
    if state == "current":
        return {"state": "covered", "last_reviewed": last, "next_due": nxt,
                "text": "COVERED: you reviewed it %s (%s; next due %s)" % (last, cadence, nxt)}
    if state == "due":
        if nxt is None:
            text = "NOT COVERED: never reviewed"
        else:
            over = detail.get("days_over") or 0
            text = "NOT COVERED: last reviewed %s, due %s (%s)" % (
                last, nxt, "due today" if over == 0 else "%d day%s over" % (over, "" if over == 1 else "s"))
        return {"state": "not-covered", "text": text, "last_reviewed": last, "next_due": nxt}
    if state == "retired":
        return {"state": "retired", "text": "RETIRED: not reviewed by design", "last_reviewed": last,
                "next_due": None}
    return {"state": "not-checked", "text": "NOT CHECKED: %s" % detail.get("why"), "last_reviewed": last,
            "next_due": None}


def feed_line(fs):
    """The one-line reading of `journal.feed_company_state`'s dict."""
    st = fs["state"]
    if st == "no-feed":
        return "no feed (browser-routed)"
    if st == "declined":
        return "feed declined"
    if st == "covered":
        return "own feed %s covered (poll %s)" % (fs.get("vendor"), fs.get("poll"))
    if st == "not-covered":
        if fs.get("kind") == "host":
            return "own feed %s NOT COVERED (%s; the machine or the poll's budget, not this board)" % (
                fs.get("vendor"), fs.get("code"))
        return "own feed %s NOT COVERED (%s)" % (fs.get("vendor"), fs.get("code"))
    return "own feed %s NOT CHECKED: %s" % (fs.get("vendor"), fs.get("reason"))


def _feed_states(root, companies_by_id, ids):
    """`{company_id: feed_company_state dict}`. A journal that cannot be read gives NOT CHECKED for every
    company that has a feed, never "covered" and never silence."""
    import journal as _journal
    try:
        recs = _journal.read(root)
        err = None
    except _journal.JournalError as e:
        recs, err = None, str(e)
    out = {}
    for cid in ids:
        co = companies_by_id.get(cid) or {}
        if recs is None and isinstance(co.get("ats"), dict):
            out[cid] = {"state": "not-checked", "vendor": co["ats"].get("vendor"), "code": None,
                        "kind": None, "poll": None, "reason": "the journal cannot be read (%s)" % err}
        else:
            out[cid] = _journal.feed_company_state(recs or [], co)
    return out


# ---------------------------------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------------------------------

def board_roles(channel_id, opportunities):
    """`{company_id: [opp rows]}`: every non-folded opportunity with a sighting (not `split_to`) on this
    channel. These are the board's own evidence, the same set `backers_of` derives its link from."""
    out = {}
    for o in opportunities:
        if _is_folded(o):
            continue
        if any(isinstance(sg, dict) and sg.get("channel_id") == channel_id and not sg.get("split_to")
               for sg in o.get("sightings") or []):
            out.setdefault(o.get("company_id"), []).append(o)
    return out


def build(root, today, board_id=None):
    """The report as data: `{"today", "boards": [...], "uncovered": n}`. See `render` for the text."""
    companies, channels, opps = load_stores(root)
    by_company = {c.get("id"): c for c in companies}
    chosen = boards(channels)
    if board_id is not None:
        chosen = [c for c in chosen if c.get("id") == board_id]
        if not chosen:
            raise KeyError(board_id)
    out = []
    for ch in chosen:
        cov = coverage(ch, today)
        roles = board_roles(ch["id"], opps)
        feeds = _feed_states(root, by_company, list(roles))
        firm = by_company.get(ch.get("portfolio_of")) or {}
        comp_rows = []
        for cid in sorted(roles, key=lambda c: (str((by_company.get(c) or {}).get("name") or c).casefold(),
                                                str(c))):
            co = by_company.get(cid) or {}
            comp_rows.append({
                "company_id": cid, "name": co.get("name") or cid,
                "backers": [b["firm_id"] for b in backers_of(cid, companies, channels, opps)],
                "feed": feeds[cid], "feed_line": feed_line(feeds[cid]),
                "roles": [{"id": o.get("id"), "title": o.get("title"), "status": o.get("status")}
                          for o in sorted(roles[cid], key=lambda r: str(r.get("id")))]})
        covered = cov["state"] == "covered"
        n_roles = sum(len(c["roles"]) for c in comp_rows)
        out.append({"channel_id": ch["id"], "label": ch.get("label") or ch["id"],
                    "firm_id": ch.get("portfolio_of"), "firm_name": firm.get("name") or ch.get("portfolio_of"),
                    "review_cadence": ch.get("review_cadence"), "board_hosts": ch.get("board_hosts"),
                    "coverage": cov,
                    # a board that is not covered NEVER carries a count (null), only history
                    "roles_count": n_roles if covered else None,
                    "companies_count": len(comp_rows) if covered else None,
                    "companies": comp_rows})
    uncovered = sum(1 for b in out if b["coverage"]["state"] not in ("covered", "retired"))
    return {"today": today.isoformat(), "boards": out, "uncovered": uncovered}


def render(report):
    """The report as text lines."""
    lines = []
    if not report["boards"]:
        return ["PORTFOLIO BOARDS: none. No channel carries `portfolio_of`, so there is nothing to cover "
                "(add a board: `portfolio_boards.py --rows` prints the row templates)."]
    for b in report["boards"]:
        cov = b["coverage"]
        lines.append("%s (%s): portfolio board of %s (%s)" % (b["label"], b["channel_id"], b["firm_name"],
                                                               b["firm_id"]))
        lines.append("  coverage: %s" % cov["text"])
        if cov["state"] == "covered":
            lines.append("  roles recorded from this board: %d at %d compan%s"
                         % (b["roles_count"], b["companies_count"], "y" if b["companies_count"] == 1 else "ies"))
        else:
            lines.append("  roles recorded from earlier reviews (board NOT COVERED now)%s"
                         % (":" if b["companies"] else ": none recorded"))
        for c in b["companies"]:
            lines.append("    %s (%s): %s" % (c["name"], c["company_id"], c["feed_line"]))
            for r in c["roles"]:
                lines.append("      %s  %s  %s" % (r["id"], r["title"], r["status"]))
    total = len(report["boards"])
    cov_n = sum(1 for b in report["boards"] if b["coverage"]["state"] == "covered")
    lines.append("PORTFOLIO BOARDS %d: %d covered · %d NOT COVERED or NOT CHECKED%s"
                 % (total, cov_n, report["uncovered"],
                    " · %d retired" % (total - cov_n - report["uncovered"])
                    if total - cov_n - report["uncovered"] else ""))
    return lines


# ---------------------------------------------------------------------------------------------------
# The paste-ready rows (placeholders only: no real firm is named in a shipped file)
# ---------------------------------------------------------------------------------------------------

PLACEHOLDER_FIRM_ID = "<firm-id>"
PLACEHOLDER_FIRM_NAME = "<Firm Name>"
PLACEHOLDER_HOST = "<the board's host>"
PLACEHOLDER_ALERT = "from:<the From address of one alert email from this board>"
PLACEHOLDER_URL = "<the board's URL>"


def paste_ready_rows(firm_id=PLACEHOLDER_FIRM_ID, firm_name=PLACEHOLDER_FIRM_NAME,
                     host=PLACEHOLDER_HOST, board_url=PLACEHOLDER_URL, alert_sender=PLACEHOLDER_ALERT):
    """The two rows a candidate adds for one firm's portfolio board: the firm's company row, then the
    board's channel row (company FIRST: `check_portfolio_links` P2 refuses a `portfolio_of` that does
    not resolve yet). The defaults are the placeholders the published doc shows; a test substitutes
    invented values and creates the rows through `record.py create`. Drop `alert_sender` when the
    board sends no alert email."""
    company = {"id": firm_id, "name": firm_name, "vertical": "other", "status": "watching",
               "size_ownership": "investment firm", "research_log": []}
    channel = {"id": "portfolio:%s" % firm_id, "label": "%s portfolio jobs" % firm_name,
               "type": "job-board", "access": "manual-candidate", "review_cadence": "weekly",
               "last_reviewed": None, "portfolio_of": firm_id, "board_hosts": [host],
               "alert_sender": alert_sender,
               "scope_notes": "you open it at %s; the engine never visits (its terms forbid "
                              "automated access)" % board_url}
    return [company, channel]


def main(argv=None):
    ap = argparse.ArgumentParser(description="What each portfolio job board produced, and whether it is covered.")
    ap.add_argument("--board", metavar="CHANNEL_ID")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--today", metavar="YYYY-MM-DD")
    ap.add_argument("--rows", action="store_true",
                    help="print the paste-ready company and channel row templates (placeholders)")
    args = ap.parse_args(argv)
    if args.rows:
        for row in paste_ready_rows():
            print(json.dumps(row))
        return 0
    try:
        today = datetime.date.fromisoformat(args.today) if args.today else datetime.date.today()
    except ValueError:
        print("--today must be an ISO date, got %r" % args.today, file=sys.stderr)
        return 2
    try:
        report = build(ROOT, today, board_id=args.board)
    except StoreError as e:
        print("NOT CHECKED: portfolio boards were not read: %s" % e)
        return EXIT_STORES
    except KeyError:
        try:
            known = ", ".join(c.get("id") for c in boards(load_stores(ROOT)[1])) or "none"
        except StoreError:
            known = "unknown"
        print("no portfolio board %r (boards: %s)" % (args.board, known), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=1))
    else:
        print("\n".join(render(report)))
    return EXIT_NOT_COVERED if report["uncovered"] else 0


if __name__ == "__main__":
    sys.exit(main())
