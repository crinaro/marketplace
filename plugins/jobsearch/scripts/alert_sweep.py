#!/usr/bin/env python3
"""
Deterministic daily job-alert sweep — the reliable catch for board/aggregator
alert emails (Indeed, LinkedIn, Dice, CareerBuilder, Ladders).

WHY THIS EXISTS
---------------
Three consecutive daily runs (2026-07-22..24) had the `inbox-scan` agent (haiku)
report the job-alert emails "silent" when a daily Indeed alert had in fact
arrived squarely inside the window — each time the main session's own direct
`gmail_search` found it, and each time the candidate or the main session caught the miss,
not the agent. The lesson recorded in CLAUDE.md's token-discipline rule is that
a *daily, predictable* artifact like the Indeed alert is deterministic work that
belongs in a query, not a model summary. This script IS that query, promoted out
of a focus.md note (weekly-review proposal P3, approved 2026-07-27) into code so
it is never re-typed and never quietly skipped.

It does NOT judge fit — it surfaces the alert artifacts and their roles so the
run reads them itself. inbox-scan stays useful for human/recruiter mail and
meeting artifacts; this replaces it ONLY for the predictable alert digests.

Reuses mail_client.py's Keychain + IMAP plumbing (a pure library — the MCP
server lives in the gmail-multi connector plugin). Same coverage guarantee: EVERY configured
account by default, and an unreachable account is a LOUD banner, never a silent zero —
so this can never conclude "no alerts" from a one-mailbox view.

⭐ THE SENDER LIST COMES FROM data/channels.jsonl, NOT A CONSTANT (GitHub #147, dev #147)
------------------------------------------------------------------------------------------
This used to hardcode `from:indeed OR from:linkedin OR ...` as a Python constant. Retiring an
aggregator channel in the store (`relationship_status: retired`, the same field
`channels_due.py` already honors) had NO EFFECT on this sweep — the retirement decision and
the sweep's source list lived in two disconnected places, so a dead source kept surfacing
digests forever. That is the standing rule about shipping a version rather than an
instruction, pointed at configuration: **retiring a channel must stop the sweep with no
engine code edit.**

Each channel that produces alert-digest emails now carries its own `alert_sender` field (the
Gmail search fragment for THAT channel's From address, e.g. `from:indeed`) — see
`docs/schema.md`. `_channel_senders()` below collects every non-retired channel's
`alert_sender` and ORs them together. A channel with no `alert_sender` (a recruiter, a
company-site channel reviewed by direct search, ...) is simply not an alert-digest source and
is silently skipped — that is correct, not a gap.

The one piece that stayed a script constant: `SUBJECT_FALLBACK`, a generic subject match for
digests whose From address varies (rotating subdomains, ESP relays). That is a fact about how
alert digests are IDENTIFIED in general, not a fact any one channel's record could hold — no
channel "owns" it — so moving it into the store would invent a field with nothing to key it
to. Only the sender list was ever channel-specific; the subject fallback stays here.

Usage:
    python3 scripts/alert_sweep.py                 # last 1 day (the daily default)
    python3 scripts/alert_sweep.py --days 2        # widen the window
    python3 scripts/alert_sweep.py --account you@example.com     # narrow (rare)

Python 3.9+. Standard library only.
"""

import argparse
import json
import os
import sys

# scripts/ is on sys.path[0] when run as `python3 scripts/alert_sweep.py`, so sibling modules
# import cleanly. mail_client is a pure library (the MCP server lives in the gmail-multi
# connector plugin), so importing it starts nothing.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _root import profile_root as _profile_root
import journal as _journal

try:
    from mail_client import (
        Mailbox, configured_accounts, decode_header_value, CredentialError, sweep_accounts,
    )
except ImportError as exc:  # pragma: no cover - defensive
    sys.stderr.write(
        "Could not import mail_client from the scripts/ dir: %s\n"
        "Run this as `python3 scripts/alert_sweep.py` from the repo root.\n" % exc)
    sys.exit(2)

# Generic digest fallback — deliberately NOT channel state (see the module docstring's #147
# section for why). Extend as new identifying patterns appear.
SUBJECT_FALLBACK = 'subject:("new jobs" OR "jobs for you" OR "job alert" OR "new job")'

# ⭐⭐ public #99 — PER-UID IDEMPOTENCY, the same ledger discipline the ATS sweep shipped in
# 0.50.0 (design-inbound-resolution.md §5, dev #376), adopted here rather than reinvented: ONE
# ledger (journal.py's `data/runs.jsonl`), not two. Before this, every run re-fetched and
# re-printed every uid the search window still covered — a uid found on three consecutive daily
# runs was triaged three times, because nothing recorded that a prior run had already surfaced
# it. `sweep_account()` below now reads `journal.triaged_uids()` BEFORE fetching any header, and
# writes `journal.record_triaged()` immediately after building each new uid's own row — never
# batched at the end — so a run killed between fetching a uid and recording its disposition
# leaves that one uid un-triaged for the next run to pick back up (see `record_triaged()`'s own
# docstring). `ALERT_SWEEP_BY` tags every row this sweep writes, the same `by` convention
# `record_swept`'s callers already use, so a second sweep kind sharing this ledger later would
# never silently cover for this one's own history.
ALERT_SWEEP_BY = "alert_sweep"

# Reset at the top of every `main()` call. `sweep_account()` records this run's own per-account
# skip count here so `main()`'s printed output can report the saving (public #99) without
# widening `sweep_account`'s own `(rows, error)` return contract — `mail_client.sweep_accounts()`
# unpacks exactly two values from whatever `search_one` returns, and a caller that already
# replaces `sweep_account` wholesale for a test (a plain two-arg stub, e.g.
# `TestSweepAccountsWiredIntoTheFourCallers`'s own) must keep working unmodified; widening the
# return arity would either break that unpacking or force every test double to grow a third
# value it has no reason to know about. A module-level side channel, reset per run, is the
# narrowest fix that touches neither.
_last_skipped = {}


def _channel_senders(root=None):
    """Every non-retired channel's `alert_sender`, from data/channels.jsonl.

    A missing or unreadable channels.jsonl yields no senders rather than raising — an empty
    profile (or one mid-scaffold) must not crash the sweep; the subject fallback alone still
    runs. A channel with `relationship_status: retired` is excluded even if `alert_sender` is
    still set on the row (the field records history; retirement is what silences it) — the
    exact behavior dev #147 asked for: retiring a channel stops the sweep with no code edit.
    """
    path = os.path.join(root or _profile_root(), "data", "channels.jsonl")
    senders = []
    try:
        fh = open(path, encoding="utf-8")
    except OSError:
        return senders
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            sender = row.get("alert_sender")
            if not sender:
                continue
            if row.get("relationship_status") == "retired":
                continue
            senders.append(sender)
    return senders


def build_query(days, root=None):
    parts = _channel_senders(root) + [SUBJECT_FALLBACK]
    return "(%s) newer_than:%dd" % (" OR ".join(parts), days)


def sweep_account(account, query):
    """Return (rows, error). rows = list of (date, from, subject).

    ⭐ public #99 — per-uid idempotent: a uid already triaged for THIS account (within
    `journal.TRIAGE_TTL_DAYS`) is skipped before `fetch_headers` is ever called for it, and
    `_last_skipped[account]` records how many were skipped so `main()` can report the saving. A
    uid processed here is marked triaged (`journal.record_triaged`) only AFTER its row is built
    — never before — so a run killed mid-loop leaves every not-yet-recorded uid to be re-triaged
    next time, not silently skipped."""
    rows = []
    skipped = 0
    try:
        root = _profile_root()
        recs = _journal.read(root)
        already = _journal.triaged_uids(recs, account, by=ALERT_SWEEP_BY)
        with Mailbox(account) as mb:
            uids = mb.search(query)
            # Newest first, cap the fetch so a busy mailbox can't run long.
            for uid in reversed(uids[-40:]):
                if str(uid) in already:
                    skipped += 1
                    continue
                msg = mb.fetch_headers(uid)
                if msg is None:
                    continue
                rows.append((
                    decode_header_value(msg.get("Date")),
                    decode_header_value(msg.get("From")),
                    decode_header_value(msg.get("Subject")),
                ))
                _journal.record_triaged(root, account, uid, "surfaced", ALERT_SWEEP_BY)
        _last_skipped[account] = skipped
        return rows, None
    except CredentialError as exc:
        _last_skipped[account] = skipped
        return [], str(exc)
    except Exception as exc:  # network/IMAP hiccup — report, never swallow
        _last_skipped[account] = skipped
        return [], "%s: %s" % (type(exc).__name__, exc)


def main():
    ap = argparse.ArgumentParser(description="Daily job-alert email sweep.")
    ap.add_argument("--days", type=int, default=1,
                    help="Look-back window in days (default 1 = the daily run).")
    ap.add_argument("--account", default=None,
                    help="Restrict to ONE account (default: all configured). "
                         "Narrowing forfeits the both-mailboxes guarantee — "
                         "the output says so loudly.")
    args = ap.parse_args()

    accounts = [args.account] if args.account else configured_accounts()
    query = build_query(args.days)

    # public #99 — a fresh run must not see a prior in-process call's skip counts (relevant to
    # tests that call main() more than once in the same process; a real CLI invocation only
    # ever runs main() once, so this is a no-op there).
    _last_skipped.clear()

    print("Alert sweep — window: last %d day(s)" % args.days)
    print("Query: %s" % query)
    if args.account:
        print("!! NARROWED to a single account (%s) — NOT every configured mailbox. "
              "Do not conclude an alert is absent from this run alone." % args.account)
    print("=" * 72)

    total = 0
    total_skipped = 0
    # dev #334 — the ONE shared multi-account sweep site: iterate + write the coverage ledger,
    # instead of this loop's own private copy. `since_days=args.days` is exactly the window this
    # sweep actually searched (`build_query` bakes the same value into `newer_than:%dd`), so the
    # `swept` row never claims coverage wider than what was really queried.
    results, incomplete = sweep_accounts(
        lambda acct: sweep_account(acct, query), since_days=args.days,
        root=_profile_root(), by=ALERT_SWEEP_BY, accounts=accounts)
    for account, rows, err in results:
        print("\n[%s]" % account)
        if err:
            print("  !! INCOMPLETE COVERAGE — %s" % err)
            print("  Results for this account are MISSING, not empty. "
                  "Do not conclude a message does not exist.")
            continue
        skipped = _last_skipped.get(account, 0)
        total_skipped += skipped
        if not rows and not skipped:
            print("  (no alert emails in window)")
        else:
            if not rows:
                print("  (no new alert emails in window)")
            total += len(rows)
            for date, frm, subj in rows:
                print("  %-31s | %s" % ((date or "?")[:31], subj or "(no subject)"))
                print("  %-31s   from %s" % ("", frm or "?"))
            if skipped:
                print("  (%d already triaged, skipped)" % skipped)

    print("\n" + "=" * 72)
    if incomplete:
        print("!! %d account(s) could not be searched: %s"
              % (len(incomplete), ", ".join(incomplete)))
        print("   The count below is PARTIAL. Fix credentials before trusting a zero.")
    summary = ("%d alert email(s) found across %d searchable account(s)."
              % (total, len(accounts) - len(incomplete)))
    if total_skipped:
        summary += " (%d already triaged, skipped)" % total_skipped
    print(summary)
    print("\nNext: read each role, cross-check against data/opportunities.jsonl and "
          "its exclusion list, and hand genuinely-new roles to opportunity-researcher.")
    # Exit non-zero only when coverage was incomplete, so an unattended caller can
    # tell "clean, nothing found" from "could not check" — a zero is only trustworthy
    # when every account was reachable.
    return 3 if incomplete else 0


if __name__ == "__main__":
    sys.exit(main())
