#!/usr/bin/env python3
"""Flag outreach threads that have gone silent, and pursuits with no next action.

WHY THIS EXISTS (2026-07-20)
----------------------------
The weekly strategy review named this gap as proposal #4 and it had fired **zero
times**: a follow-up rule written on 2026-07-14 was never enforced by anything,
while five threads sat silent for 12-13 days. Messages get sent, replies never
come, and nothing in the system notices -- because noticing was left to a human
remembering to scan a 97-row table.

`check_stale_claims.py` catches decayed *claims*. This catches decayed *threads*:

  1. SILENT OUTREACH -- a message/connection request was sent, the status still
     says awaiting/pending/no-reply, and N+ days have passed.
  2. ACTIVE PURSUIT, NO NEXT ACTION -- a live pursuit record whose text contains no
     recognizable next step. "Pursue" without a next action is how the 2026-07-15
     "next action identified != next action executed" gap happened.

Run it at the START of every daily and weekly run, alongside check_stale_claims.py.

    python3 scripts/check_followups.py [--days N] [--quiet]

Exit code is 0 even when it finds things -- it's an advisory report, not a gate,
so it can't wedge an unattended run.

⭐⭐ dev #321 — SILENCE IS MEASURED AGAINST VERIFIED COVERAGE, NEVER THE WALL CLOCK
-----------------------------------------------------------------------------------
This used to compute every age as `(datetime.now().date() - when).days`. That is a mirror, not a
measurement: `data/messages.jsonl` (and the outreach rows this reads) are only as current as the
last sweep, and NOTHING recorded when that was — so on a profile whose sweeps had lagged, this
reported "silent 9 days" when the engine had simply not looked in 9 days, and the follow-up it
prompts could go to someone who had already replied. That is the standing "a missing thing reads
as an empty thing" trap, sitting under the one path that tells a candidate to chase someone.

`journal.covered_through()` (V0's coverage ledger, `mail_client.sweep_accounts()`'s `swept`
rows) is now the clock. `verified_as_of()` below is the conjunction over every configured
mailbox — the newest point through which EVERY one of them is verifiably covered — and it is
`None` on an empty ledger, a never-configured mailbox, or any account whose latest sweep failed.
**`None` means UNVERIFIED, not zero days and not today's date.** When it is `None`, the SILENT
OUTREACH class is withheld entirely rather than printed with a wrong number — the phantom chase
this fix exists to prevent. A fully-covered profile with genuine silence is unaffected: it still
reports the real day count, now measured to the end of verified coverage rather than to `now()`.

This is deliberately the smallest correct slice (V0 of the states-and-views design, §15.1): it
fixes the WHOLE-PROFILE version of the defect (are the configured mailboxes covered at all)
using the same reader V1's finer per-thread/per-medium version will use. It does not yet
discriminate the three unverified renderings (no sensor / stale sensor / broken sensor) — that
is V2's row-level surface; this prints one unverified banner and stops there.

Targets system Python 3.8 (/usr/bin/python3): no third-party packages, no
zoneinfo, no walrus, no X | Y annotations.
"""

import json
import os
import re
import sys
from datetime import date, datetime

import os, sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _root import profile_root as _profile_root
import _tree
import journal as _journal
import mail_client as _mail_client

ROOT = _profile_root()


def verified_as_of(root):
    """dev #321 — the newest point through which EVERY configured mailbox is verifiably swept,
    as a `date`, or `None` when that cannot be said.

    `None` covers three cases alike (V0 does not yet distinguish them on this whole-profile
    reading — see the module docstring): no mailbox configured at all, an empty ledger (nothing
    has ever recorded a `swept` row for some configured account), or an account whose most
    recent `swept` row is `ok: false` (a broken sensor — `covered_through` then returns whatever
    it had BEFORE the failure, or `None` if it never had anything, either way excluding time the
    failure covers).

    The conjunction is deliberate: a silence claim about ANY thread implicitly claims "and
    nobody replied on the other configured mailbox either" the moment more than one account
    exists, so the whole-profile answer can only be as fresh as the least-covered account.
    """
    accounts = _mail_client.configured_accounts()
    if not accounts:
        return None
    recs = _journal.read(root)
    throughs = []
    for account in accounts:
        through = _journal.covered_through(recs, account)
        if through is None:
            return None
        throughs.append(through)
    as_of = min(throughs)
    try:
        return datetime.fromisoformat(as_of).date()
    except ValueError:
        return None


def load_opps():
    """Records from data/opportunities.jsonl -- the pipeline's source of truth."""
    path = os.path.join(ROOT, "data", "opportunities.jsonl")
    if not os.path.exists(path):
        return []
    out = []
    fh = open(path, "r", errors="replace")
    try:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    finally:
        fh.close()
    return out

DEFAULT_DAYS = 7

# A thread counts as "awaiting" if the status says so ...
AWAITING = (
    "no reply", "awaiting", "pending", "no response", "not yet replied",
    "awaiting reply", "awaiting her", "awaiting his", "awaiting their",
)
# ... unless it's actually finished.
RESOLVED = (
    "closed", "passed", "dropped", "declined", "not pursued", "ruled out",
    "filled", "dead lead", "do not re-flag", "parked", "replied", "accepted",
)
SENT = ("message sent", "sent", "connection request", "inmail", "reply sent",
        "outreach sent", "request sent")

DATE_RE = re.compile(r"(20\d\d)-(\d\d)-(\d\d)")

# Verbs that make a next_action actionable. Extended 2026-07-21 once this check
# was pointed at the JSONL: the original list was written against focus.md prose
# and lacked the verbs the structured records actually use ("apply", "call",
# "decide", "chase"), so three real next actions read as missing.
NEXT_ACTION_HINTS = (
    "next action", "next:", "next step", "await", "todo", "to do",
    "draft", "send", "ask ", "confirm", "follow up", "follow-up", "schedule",
    "apply", "call ", "decide", "chase", "close", "find ", "raise ", "verify",
    "reach out", "research", "approve", "watch for",
)


def read(name):
    path = _tree.resolve_rel(ROOT, name)
    if not os.path.exists(path):
        return ""
    fh = open(path, "r", errors="replace")
    try:
        return fh.read()
    finally:
        fh.close()


def latest_date(text):
    """Most recent YYYY-MM-DD appearing in the text, as a date, or None."""
    best = None
    for m in DATE_RE.finditer(text):
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
        if d.year < 2020 or d.year > 2100:
            continue
        if best is None or d > best:
            best = d
    return best


# Column names that carry the thread's state. Matching MUST be scoped to this
# column: an early version blob-matched the whole row and silently missed 3 of 5
# known-silent threads, because words like "closed" and "filled" appear
# incidentally in Notes prose ("the role is now closed" about a *different*
# req). Scanning narrative text for status keywords is how a detector
# under-reports and looks like it's working.
STATUS_COLS = ("contact status", "status", "action", "last contact")


def table_rows(md):
    """Yield (headers, cells) for pipe-table data rows, carrying each table's own
    header so callers can address columns by name instead of by position."""
    headers = []
    for line in md.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            headers = []
            continue
        if set(line) <= set("|-: "):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        low = [c.lower() for c in cells]
        if low and low[0] in ("company", "contact", "target", "name"):
            headers = low
            continue
        if len(cells) >= 3:
            yield headers, cells


def status_of(headers, cells):
    """The row's status text, by column name. Falls back to the whole row only
    when no status column exists (better to over-report than miss)."""
    for i, h in enumerate(headers):
        if h in STATUS_COLS and i < len(cells):
            return cells[i]
    return " ".join(cells)


def check_silent_jsonl(today, days):
    """Silent threads from data/opportunities.jsonl -- THE source of truth.

    Replaces the markdown scan for roles (2026-07-21). `opportunities.md` was
    retired 2026-07-20 and frozen; scanning it meant this check could only ever
    report a historical snapshot, and a row it flagged could never be re-dated
    because the file is not to be edited. Worse, roles added or updated after
    the cutover were invisible to it entirely.
    """
    import validate_data as _vd
    findings = []
    for opp in load_opps():
        # Terminal roles (validate_data's ONE set) have no thread to chase. `backlog` is
        # NOT terminal — it is skipped here as a deliberate, named choice of THIS check: a
        # shelved role's silence is not a follow-up gap. (build item 1: a surface may still
        # omit a live status, but it says so instead of calling it closed.)
        if opp.get("status") in _vd.TERMINAL_OPP_STATUSES or opp.get("status") == "backlog":
            continue
        if opp.get("stage") == "closed":
            continue
        sent = [o for o in (opp.get("outreach") or [])
                if o.get("status") == "sent" and o.get("date")]
        if not sent:
            continue
        when = latest_date(" ".join(o["date"] for o in sent))
        if when is None:
            continue
        age = (today - when).days
        if age >= days:
            who = opp.get("company_id", opp.get("id", ""))
            findings.append((age, "data/opportunities.jsonl", who,
                             (opp.get("title") or "")[:60], when))
    findings.sort(reverse=True)
    return findings


def check_silent(today, days):
    """Silent threads still tracked as markdown prose (network.md only)."""
    findings = []
    for fname in (_tree.rel("network"),):
        md = read(fname)
        for headers, cells in table_rows(md):
            status = status_of(headers, cells).lower()
            if any(k in status for k in RESOLVED):
                continue
            if not any(k in status for k in AWAITING):
                continue
            if not any(k in status for k in SENT):
                continue
            # Age from the status/date columns only. Notes prose routinely cites
            # unrelated recent dates, which would reset the age and hide the silence.
            date_src = [status_of(headers, cells)]
            for i, h in enumerate(headers):
                if h in ("found", "last checked", "date", "last contact") and i < len(cells):
                    date_src.append(cells[i])
            when = latest_date(" ".join(date_src))
            if when is None:
                continue
            age = (today - when).days
            if age >= days:
                who = cells[0]
                what = cells[1] if len(cells) > 1 else ""
                findings.append((age, fname, who, what, when))
    findings.sort(reverse=True)
    return findings


def check_pursuits_without_next_action():
    """Active pursuits with no next action, read from the JSONL.

    This function used to parse focus.md's `## Active Pursuit` section. That
    section was RETIRED 2026-07-20 (role state is now generated from the JSONL),
    so the regex stopped matching, the function returned [] on every run, and
    the check reported a clean bill of health it could not possibly have earned.
    Found 2026-07-21 with five pursuits actually missing a next action.
    """
    out = []
    for opp in load_opps():
        if opp.get("status") != "active-pursuit":
            continue
        na = (opp.get("next_action") or "").strip()
        if not na:
            out.append("%s - %s" % (opp.get("company_id", ""),
                                    (opp.get("title") or "")[:55]))
            continue
        if not any(h in na.lower() for h in NEXT_ACTION_HINTS):
            out.append("%s - %s (next_action is not a recognizable action)"
                       % (opp.get("company_id", ""), (opp.get("title") or "")[:45]))
    return out


def main():
    days = DEFAULT_DAYS
    quiet = "--quiet" in sys.argv
    for i, a in enumerate(sys.argv):
        if a == "--days" and i + 1 < len(sys.argv):
            try:
                days = int(sys.argv[i + 1])
            except ValueError:
                pass

    run_today = datetime.now().date()
    as_of = verified_as_of(ROOT)
    unverified = as_of is None
    if unverified:
        silent = []
    else:
        silent = check_silent_jsonl(as_of, days) + check_silent(as_of, days)
        silent.sort(reverse=True)
    stalled = check_pursuits_without_next_action()

    print("Follow-up check - %s (silence threshold: %d days)" % (run_today.isoformat(), days))
    if unverified:
        print("")
        print("!! SILENCE UNVERIFIED (dev #321) -- no confirmed mailbox coverage, or a "
              "configured account's last sweep failed.")
        print("   SILENT OUTREACH is withheld below: a day count computed against the wall")
        print("   clock instead of a verified sweep could send a chase to someone who already")
        print("   replied. Run an alert/watch sweep, then re-run this check.")
    else:
        print("(silence verified through %s)" % as_of.isoformat())

    if silent:
        print("")
        print("=" * 72)
        print("SILENT OUTREACH - sent, still awaiting, no movement")
        print("=" * 72)
        print("Decide one of three for each: chase it, close it, or re-date the")
        print("row if something DID happen and nobody wrote it down.")
        print("")
        for age, fname, who, what, when in silent:
            print("  %3d days  %-16s %s" % (age, fname, who))
            if what:
                print("            %s" % what[:88])
            print("            last dated %s" % when.isoformat())
    elif unverified:
        pass  # the banner above already said why nothing is listed here
    elif not quiet:
        print("\n  No silent outreach past %d days." % days)

    if stalled:
        print("")
        print("=" * 72)
        print("ACTIVE PURSUIT WITH NO RECOGNIZABLE NEXT ACTION")
        print("=" * 72)
        print('"Pursue" without a next action is how a plan quietly becomes a')
        print("wait-and-see. Give each one a concrete next step or demote it.")
        print("")
        for t in stalled:
            print("  - %s" % t)
    elif not quiet:
        print("  Every active pursuit names a next action.")

    # ---- Bounce check: silence, or did it never arrive? ------------------------
    # Added 2026-08-02. The 2026-07-31 campaign used PATTERN-INFERRED addresses
    # (first.last@company.com at ~91% confidence). A bounce that reads as a non-reply
    # silently poisons every reply rate, and funnel_report has to exclude these rows
    # entirely until someone checks. This asks the question in the slot where
    # "is it silent?" is already being asked.
    suspects = []
    for o in load_opps():
        for x in (o.get("outreach") or []):
            if (x.get("status") == "sent"
                    and x.get("outcome") == "awaiting"
                    and (x.get("medium") or "").startswith("email")
                    and x.get("address_status") == "pattern-inferred"
                    and x.get("delivery") == "unknown"):
                suspects.append((o, x))
    if suspects:
        print("")
        print("=" * 72)
        print("CHECK FOR A BOUNCE - %d unverified address(es), silence is not evidence yet" % len(suspects))
        print("=" * 72)
        print("  These went to a GUESSED address. Until delivery is known, they cannot")
        print("  distinguish 'ignored' from 'never arrived', so funnel_report excludes them")
        print("  from every rate. Run this query, then set delivery=delivered|bounced:")
        print("")
        domains = sorted({(x.get("to") or "").split("@")[-1].strip(" )") for _o, x in suspects
                          if "@" in (x.get("to") or "")})
        print('    in:anywhere (from:mailer-daemon OR from:postmaster OR')
        print('      subject:("Address not found" OR "Delivery Status Notification" OR')
        print('              "Undeliverable" OR "could not be delivered")) newer_than:30d')
        print("")
        for o, x in suspects:
            print("  - %-34s %s  (%s)" % ((x.get("to") or "")[:34], x.get("date"), o["id"][:34]))
        if domains:
            print("\n  recipient domains seen: %s" % ", ".join(d for d in domains if d))

    if not silent and not stalled and not unverified:
        print("\nNothing to chase.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
