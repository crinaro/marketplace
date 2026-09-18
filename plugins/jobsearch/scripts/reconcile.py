#!/usr/bin/env python3
"""
Reconcile tracked opportunity state against the SOURCE CHANNELS — the mailbox and LinkedIn.

⚠️ THIS IS A RECONCILIATION MODE, NOT THE OPERATING PATH.
---------------------------------------------------------
The candidate, 2026-08-02: *"We have the luxury we can reconcile against the sources (mail and LinkedIn)
but that should only be used for a reconciliation mode. The process should be using the json data
and making incremental updates during the daily runs."*

**`data/*.jsonl` is the system of RECORD. The mailbox is the system of TRUTH**, consulted
periodically to catch drift. The daily run reads and writes the JSON as things happen; it does not
re-derive state from the mailbox. This script runs **weekly**, as an audit.

**Anything it finds is a PROCESS FAILURE, not a routine result.** An unrecorded reply means the
daily run that should have written it missed something — log that, don't just apply the fix. A
clean reconcile means the incremental updates are working.

WHY THIS EXISTS
---------------
The candidate, 2026-08-02:

    "Why can't the process have the ability to review opportunities, if it did, it should have
     the ability to resolve the issue. It should be the same to evaluate the current state of an
     opportunity. Look at email, look at messages in LinkedIn. Those give the system the ability
     to evaluate. I know we have a step to check the ATS but that's really only going to let us
     know if the recruiter looked at the application. Yes, that's valuable but the other channels
     are much more important and the process should be able to reconcile because the same data is
     available in mail and LinkedIn."

The candidate was correcting a claim I had made: that 22 outreach rows with `medium: unknown` were
unrecoverable because "no contemporaneous record exists." **That was wrong.** The record exists —
the actual messages are still sitting in the mailbox. I had only looked at what the repo had
written down about itself, not at the source.

That is the general failure this script fixes. Tracked state is a *transcription* of what happened
in email and LinkedIn. A transcription can be incomplete (a row never written), stale (a reply
that arrived after we last looked), or lossy (`medium: unknown`). **The source can be re-read at
any time.** The ATS portal check tells you only whether a recruiter opened an application; the
conversation itself is where the real signal is.

**⭐ LinkedIn is reconcilable from the mailbox too**, which is the non-obvious part: LinkedIn emails
a notification for messages received ("X just messaged you"), invitation acceptances ("X accepted
your invitation"), and InMail. So a deterministic Gmail sweep recovers a large share of LinkedIn
state without a browser session at all.

WHAT IT REPORTS
---------------
  * **MEDIUM EVIDENCE** — a row says `medium: unknown`, but the mailbox shows a direct email
    exchange, or a LinkedIn notification, with that person.
  * **UNRECORDED REPLY** — the row says `awaiting`/`sent`, but a message FROM that contact arrived
    after we wrote to them. This is the one that costs real opportunities.
  * **UNRECORDED ACCEPTANCE** — LinkedIn says an invitation was accepted; the row does not.
  * **NO TRACE** — nothing found. Reported explicitly rather than silently skipped, because a
    zero is only meaningful when you can see it was looked for.

It NEVER writes by default. `--apply` fills in `medium` **only** where the evidence is
unambiguous, and never touches `outcome` — a reply changes what the candidate should DO, so it is surfaced
for a human decision rather than silently absorbed.

Usage (weekly audit; NOT part of the daily run):
    python3 scripts/reconcile.py                    # report on live pursuits
    python3 scripts/reconcile.py --all              # every opportunity with outreach
    python3 scripts/reconcile.py --unknown-medium   # only rows needing a medium
    python3 scripts/reconcile.py --apply            # write the unambiguous medium fixes
    python3 scripts/reconcile.py --role <opp_id>

Python 3.9+. Standard library only.
"""

import argparse
import collections
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.parse
from email.utils import parseaddr

import os, sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _root import profile_root as _profile_root
from _atomic import write_jsonl, write_json, write_text
import validate_data as _vd
import touches as _touches
import journal as _journal

try:
    from mail_client import (
        Mailbox, configured_accounts, decode_header_value, CredentialError, body_text,
        sweep_accounts, COVERAGE_BACKFILL_MAX_DAYS, lookback_days,
    )
except ImportError as exc:  # pragma: no cover
    sys.stderr.write("Run as `python3 scripts/reconcile.py` from the repo root: %s\n" % exc)
    sys.exit(2)

ROOT = _profile_root()
DATA = os.path.join(ROOT, "data")

# LinkedIn's own notification senders. This is what makes LinkedIn state reconcilable from
# the mailbox rather than requiring a browser session.
LINKEDIN_SENDERS = ("messaging-digest-noreply@linkedin.com", "invitations-noreply@linkedin.com",
                    "inmail-hit-reply@linkedin.com", "notifications-noreply@linkedin.com",
                    "member@linkedin.com", "jobs-noreply@linkedin.com")
LINKEDIN_MESSAGE_HINTS = ("just messaged you", "sent you a message", "sent you an inmail",
                          "you have a new message")
LINKEDIN_ACCEPT_HINTS = ("accepted your invitation", "is now a connection",
                         "you are now connected")


def load(name):
    path = os.path.join(DATA, name)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


def person_terms(to_field):
    """Search terms from a `to` string like 'Marlow Quist (Some Search Firm)' — synthetic, as
    every example name in a portable file must be.

    Returns (display_name, [terms]). The parenthetical is often the firm, which is a useful
    second term, and an embedded email address is the strongest term of all.

    ⭐ Public #90 — a SINGLE-TOKEN name is never sent as a term ALONE. The query these terms
    build is `"in:anywhere (%s)" % " OR ".join(terms)` (Gmail's X-GM-RAW search, mail_client.py)
    — every term in the list is OR'd against the whole mailbox. Quoting a lone word changes
    nothing there (Gmail phrase-quoting only narrows a MULTI-word phrase to adjacency; a single
    quoted word matches exactly what the same word unquoted matches), so the fix is not
    quoting — it is that a bare first name is too weak a term to stand on its own: run against
    eight held contacts, a short common first name matched over 12,000 threads, all dated to
    the run date, and each one posted a false `store-behind-mailbox` finding (brief.py's D13).
    A one-token name is used only PAIRED with the firm, as one AND'd term (Gmail: space-
    separated quoted phrases inside one list entry are ANDed, unlike the OR every other entry
    in the list gets against each other) — never appended bare, and never OR'd loose. With
    neither an email nor a firm to pair it with, a one-token name contributes NOTHING (the
    caller's own `if not terms: continue` — reconcile.py:354/667, brief.py:266/794 — already
    treats an empty term list as "nothing to search on", the same as no name at all).
    """
    raw = (to_field or "").strip()
    email = None
    m = re.search(r"[\w.+-]+@[\w.-]+\.\w+", raw)
    if m:
        email = m.group(0)
    name = re.split(r"\(|,|;", raw)[0].strip()
    paren = re.search(r"\(([^)]+)\)", raw)
    firm = None
    if paren:
        firm = re.split(r"[,;—-]", paren.group(1))[0].strip()
        firm = re.sub(r"\b(1st|2nd|3rd)-degree connection\b", "", firm).strip()
        if not (firm and len(firm) > 3 and not firm.lower().startswith("to forward")):
            firm = None

    terms = []
    if email:
        terms.append(email)
    if name and len(name.split()) >= 2:
        terms.append('"%s"' % name)
    elif name and firm:
        # A single-token name paired with the firm as ONE combined (AND'd) term — narrow
        # enough to send; "spent" the firm here so it is never also appended below as its own
        # loose OR'd term (which would let it match without the name at all).
        terms.append('"%s" "%s"' % (name, firm))
        firm = None
    # else: a bare single-token name with no firm and no email is DROPPED — public #90.
    if firm:
        terms.append('"%s"' % firm)
    return name, terms


class Session(object):
    """One IMAP connection per account, reused across every query.

    The first version opened a fresh Mailbox per search — 22 rows x 2 accounts = 44 logins,
    which took longer than the harness timeout. Connection setup dominates; the searches
    themselves are fast.

    ⭐⭐ dev #334 — connections open THROUGH `mail_client.sweep_accounts()` now, not through a
    loop this class runs itself. `open_account()` below IS the `search_one(account)`
    `sweep_accounts()` calls (see `main()`): it opens (or fails to open) exactly one mailbox,
    keeps it in `self.boxes` for `search()`/`search_uids()`/`fetch_full()` to reuse across every
    contact-group query, and hands back the error `sweep_accounts()` needs to write that
    account's ONE `swept` coverage row. Before this fix `__init__` looped over `accounts`
    directly — the exact private, unrecorded "loop every account, note a failure" copy dev #321
    built the shared ledger site to retire. `account_errors` is the per-account twin of `errors`
    (which stays the full, possibly-repeated audit trail used for the terminal banner's detail):
    each account's FIRST failure — from opening OR from any later query — lands there once.
    """

    def __init__(self):
        self.boxes, self.errors, self.account_errors = {}, [], {}

    def open_account(self, acct):
        """search_one(account) for mail_client.sweep_accounts() — see the class docstring."""
        try:
            mb = Mailbox(acct)
            mb.__enter__()
            self.boxes[acct] = mb
            return None
        except CredentialError as exc:
            self._record_error(acct, "%s: %s" % (acct, exc))
            return str(exc)
        except Exception as exc:
            self._record_error(acct, "%s: %s: %s" % (acct, type(exc).__name__, exc))
            return "%s: %s" % (type(exc).__name__, exc)

    def _record_error(self, acct, msg):
        self.errors.append(msg)
        self.account_errors.setdefault(acct, msg)   # first failure per account wins

    def search(self, query, limit=25):
        rows = []
        for acct, mb in self.boxes.items():
            try:
                uids = mb.search(query)
                for uid in reversed(uids[-limit:]):
                    msg = mb.fetch_headers(uid)
                    if msg is None:
                        continue
                    rows.append({
                        "account": acct,
                        "date": decode_header_value(msg.get("Date")),
                        "from": decode_header_value(msg.get("From")),
                        "to": decode_header_value(msg.get("To")),
                        "subject": decode_header_value(msg.get("Subject")),
                    })
            except Exception as exc:
                self._record_error(acct, "%s: %s: %s" % (acct, type(exc).__name__, exc))
        return rows

    def fetch_full(self, acct, uid):
        mb = self.boxes.get(acct)
        if not mb:
            return None
        try:
            return mb.fetch_full(uid)
        except Exception as exc:
            self._record_error(acct, "%s: %s: %s" % (acct, type(exc).__name__, exc))
            return None

    def search_uids(self, query, limit=25):
        """(account, uid) pairs, so a body can be fetched and its provenance recorded."""
        out = []
        for acct, mb in self.boxes.items():
            try:
                for uid in reversed(mb.search(query)[-limit:]):
                    out.append((acct, uid))
            except Exception as exc:
                self._record_error(acct, "%s: %s: %s" % (acct, type(exc).__name__, exc))
        return out

    def close(self):
        for mb in self.boxes.values():
            try:
                mb.__exit__(None, None, None)
            except Exception:
                pass


def parse_hdr_date(s):
    if not s:
        return None
    m = re.search(r"(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})", s)
    if not m:
        return None
    months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
    try:
        return datetime.date(int(m.group(3)), months.index(m.group(2)) + 1, int(m.group(1)))
    except ValueError:
        return None


def classify(hits, name, row_date):
    """What do these messages tell us? -> (medium, replied_after, accepted, notes)"""
    medium = None
    replied_after = []
    accepted = False
    direct_email = False
    linkedin_msg = False
    last = (name or "").split()[-1].lower() if name else ""

    for h in hits:
        frm = (h["from"] or "")
        low_frm = frm.lower()
        subj = (h["subject"] or "").lower()
        # ⭐ MATCH THE ADDRESS, NOT A SUBSTRING OF THE HEADER (CodeQL, 2026-08-11).
        # `any(s in low_frm ...)` accepted any sender that merely CONTAINED a real notification
        # address — append a domain of your own to one and the substring still matches. This
        # function turns mail into pipeline state, so a spoofed sender could record an acceptance
        # that never happened. parseaddr extracts the address; the comparison is then exact.
        # (The lookalike is described, not written: an address literal here is itself a leak,
        # which the engine leak audit correctly flagged when this comment first quoted one.)
        is_linkedin = parseaddr(low_frm)[1].strip() in LINKEDIN_SENDERS
        if is_linkedin:
            if any(k in subj for k in LINKEDIN_ACCEPT_HINTS):
                accepted = True
            if any(k in subj for k in LINKEDIN_MESSAGE_HINTS) and (not last or last in subj):
                linkedin_msg = True
                d = parse_hdr_date(h["date"])
                if d and row_date and d >= row_date:
                    replied_after.append(h)
            continue
        # A direct (non-LinkedIn) message mentioning this person = an email exchange.
        if last and last in low_frm:
            direct_email = True
            d = parse_hdr_date(h["date"])
            if d and row_date and d >= row_date:
                replied_after.append(h)
        elif "@" in frm and last and last in (h["to"] or "").lower():
            direct_email = True

    if direct_email:
        medium = "email"
    elif linkedin_msg:
        medium = "linkedin"
    return medium, replied_after, accepted


def row_date(r):
    """The date an outreach row was SENT, or None if it is missing/unparseable.

    A row that cannot be dated can never become the owner of an inbound event — see
    `attribute_hits` — so it is excluded from candidacy rather than treated as "any time".
    """
    try:
        return datetime.date.fromisoformat(_vd.date_part(r.get("date")) or "")
    except (ValueError, TypeError):
        return None


def row_time(r):
    """'HH:MM' if the row's date carries a time (validate_data.TIMESTAMP_RE), else None."""
    s = str(r.get("date") or "")
    return s[11:16] if _vd.is_when(s) and len(s) > 10 else None


_HDR_TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})(?::\d{2})?\b")


def hdr_time(s):
    """'HH:MM' from a mail header date, or None. Zone-naive on purpose: same-day ordering
    against a row's own local time is only asserted when both sides carry a time, and
    the header time is what the mailbox reported — a best effort, never a claim of
    precision."""
    if not s:
        return None
    m = _HDR_TIME_RE.search(s)
    return ("%02d:%s" % (int(m.group(1)), m.group(2))) if m else None


def group_by_contact(targets):
    """Group outreach rows by the REAL PERSON they were sent to — never by opportunity.

    ⭐⭐ dev #101 / public #13 — the SIBLING of dev #65 / public #2 that the original fix did
    not cover. #65's fix grouped by `(opportunity, person)`, which correctly joins several
    touches to one recipient WITHIN a single pursuit — the case it was written for. But a
    recipient contacted about MORE THAN ONE opportunity — an agency recruiter presenting the
    candidate to several companies is the ordinary case, not an edge case — was split across
    independent groups, one per opportunity. Each group ran its OWN mail search and its OWN
    attribution pass, so nothing stopped the SAME inbound message or platform event from being
    attributed inside more than one group at once: the join was not CONSUMING what it matched,
    so a single event could satisfy several rows as long as they lived in different
    opportunities. Three hand-verified false positives in one run traced back to exactly this.

    The join key is the PERSON, full stop. Every outreach row addressed to them, from every
    opportunity, becomes ONE group with ONE mail search and ONE attribution pass (see
    `attribute_hits`), so a single inbound event has at most one owner anywhere in the store —
    not just within one opportunity.

    Terms from every row for the same person are UNION'd (never overwritten), so the search
    covers every firm name or address the candidate recorded for them, no matter which
    opportunity recorded it. The residual risk — two genuinely different people who happen to
    share the exact name string get merged — is the same text-matching risk `person_terms`
    already carried within a single opportunity; this widens its scope but does not invent it.
    """
    groups = {}
    for o, idx, r in targets:
        name, terms = person_terms(r.get("to"))
        if not terms:
            continue
        key = name.lower()
        g = groups.setdefault(key, {"name": name, "terms": [], "rows": []})
        for t in terms:
            if t not in g["terms"]:
                g["terms"].append(t)
        g["rows"].append((o, idx, r))
    return groups


def attribute_hits(rows, hits):
    """Attribute each inbound hit to the ONE outreach row it answers.

    The owner is the LATEST row sent on or before the hit's date — a message cannot answer a
    touch that had not been sent yet. That comparison (`rd <= hd`) is evaluated fresh for every
    candidate, so no row whose own date is AFTER the hit can ever become its owner, regardless
    of iteration order or of how many other rows are in play. Sorting by the PARSED date (not
    the raw string) also closes a second gap: a non-zero-padded date ("2026-1-5") used to sort
    AFTER "2026-01-10" lexically, which could crown the wrong — but still not-later-than-the-
    event — row as owner.

    `owner` is a single variable, overwritten as later-and-still-eligible candidates are seen,
    never a set: each hit lands in at most one row's bucket, so one inbound event can never
    satisfy two outreach rows once `rows` is the FULL set for that person (see
    `group_by_contact` — this is the function that must receive every row for the person, not
    a subset scoped to one opportunity, or the same non-consumption defect reappears one level
    up).
    """
    attributed, _ambiguous = attribute_hits_report(rows, hits)
    return attributed


def attribute_hits_report(rows, hits):
    """(attributed, ambiguous) — `attribute_hits` plus the hits it REFUSED to attribute.

    ⭐ SAME-DAY PAIRS ARE AMBIGUOUS, NEVER ASSERTED (dev/audit 2026-09-02, Class B / public
    #41/#36/#34). Two rows carry only dates, so two facts the old attribution asserted are
    unprovable from dates alone: (a) which of two rows sent on the SAME day a later reply
    answers, and (b) whether a reply dated the SAME day as the row it would answer came
    after the send at all. Both used to resolve by iteration order — the last candidate
    won — which is an answer that looks measured and is not. Here either case is reported
    as `ambiguous` (hit, [candidate rows]) instead, unless BOTH sides carry a time
    (validate_data.TIMESTAMP_RE on the row; the mail header's own clock on the hit), in
    which case the order is real and is used. A human can then link the reply as data
    (messages[].answers) — a decision, recorded once — rather than the audit re-guessing
    it every week."""
    ordered = sorted(rows, key=lambda t: row_date(t[2]) or datetime.date.min)
    attributed = {}
    ambiguous = []
    for h in hits:
        hd = parse_hdr_date(h.get("date"))
        if not hd:
            continue
        ht = hdr_time(h.get("date"))
        eligible = []
        for cand in ordered:
            rd = row_date(cand[2])
            if not rd or rd > hd:
                continue
            if rd == hd:
                # Same day as the hit: eligible only when both clocks say the send came first.
                rt = row_time(cand[2])
                if rt is None or ht is None:
                    eligible.append((cand, "same-day-unordered"))
                    continue
                if rt <= ht:
                    eligible.append((cand, None))
                continue
            eligible.append((cand, None))
        if not eligible:
            continue
        latest_date = max(row_date(c[2]) for c, _why in eligible)
        latest = [(c, why) for c, why in eligible if row_date(c[2]) == latest_date]
        if any(why for _c, why in latest):
            ambiguous.append((h, [c for c, _why in latest]))
            continue
        if len(latest) > 1:
            # Two rows sent the same day, both before the hit — a tie on dates. Times on
            # BOTH rows break it; otherwise the pair is reported, not guessed.
            times = [row_time(c[2]) for c, _why in latest]
            if any(t is None for t in times):
                ambiguous.append((h, [c for c, _why in latest]))
                continue
            owner = max(latest, key=lambda cw: row_time(cw[0][2]))[0]
        else:
            owner = latest[0][0]
        attributed.setdefault(id(owner[2]), []).append(h)
    return attributed, ambiguous


# ═══════════════════════════════════════════════════════════════════════════════════════════
# design-inbound-resolution.md — ADR-029/030's deterministic ATS sweep (`--ats`/`--verify`).
# ═══════════════════════════════════════════════════════════════════════════════════════════
#
# §3.1/§3.2 — identification (sender domain) and resolution (three tiers) are two different
# questions with two different kinds of evidence; neither substitutes for the other. Everything
# in this section down to `cmd_ats`/`cmd_verify` is a PURE function — no mailbox, no store I/O
# — so the decision logic is testable directly, the same split `classify()`/
# `attribute_hits_report()` already give this file's older audit path.

Resolved = collections.namedtuple("Resolved", "app_id tier")
Tie = collections.namedtuple("Tie", "tier candidate_ids")


class _NoHit(object):
    def __repr__(self):
        return "NoHit"


NoHit = _NoHit()

TIER_NAME = {1: "req-id", 2: "url", 3: "company-single"}

_WORD_BOUND_FMT = r"(?<![A-Za-z0-9_-])%s(?![A-Za-z0-9_-])"
_URL_RE = re.compile(r"https?://[^\s<>\"'()\[\]]+")


def identify_sender_class(from_domain, configured_domains, derived_domains):
    """§3.1 — is `from_domain` candidate ATS mail? Leg 1: `configured_domains`
    (`ats.receipt_sender_domains`), matched as the domain OR A SUBDOMAIN of it. Leg 2:
    `derived_domains` (every existing `messages.jsonl` row that carries `resolves`) —
    identify-only, exact match, never a subdomain widening (a derived domain is observed
    fact, not a policy the owner stated). Returns (bool, 'configured'|'derived'|None)."""
    fd = (from_domain or "").strip().lower()
    if not fd:
        return False, None
    for d in configured_domains or ():
        d = (d or "").strip().lower()
        if d and (fd == d or fd.endswith("." + d)):
            return True, "configured"
    for d in derived_domains or ():
        d = (d or "").strip().lower()
        if d and fd == d:
            return True, "derived"
    return False, None


def derived_sender_domains(messages):
    """§3.1 leg 2 — the From domain of every `messages.jsonl` row that carries `resolves`."""
    out = set()
    for m in messages or ():
        if not m.get("resolves"):
            continue
        addr = parseaddr(m.get("from") or "")[1]
        if "@" in addr:
            out.add(addr.rsplit("@", 1)[-1].strip().lower())
    return sorted(out)


def _normalize_name_token(s):
    """Strip everything but alnum, casefolded — for comparing a company name against a
    domain, which carries none of a name's spaces or punctuation of its own."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def unidentified_finding_company(display_name, from_domain, live_apps, companies):
    """design-inbound-resolution.md §3.1 — identification uncertain (dev #376 item 1): does
    this message's DISPLAY NAME or DOMAIN — never subject or body, which is §3.2's resolution
    evidence, not §3.1's identification evidence — name a live application's company? Returns
    the first matching company id (in `live_apps`' own order, deterministic), or None. Company
    mention alone is not a finding; the caller also requires a `status_phrases` hit before
    this is asked about at all."""
    dn_low = (display_name or "").lower()
    dom_norm = _normalize_name_token(from_domain)
    seen = set()
    for app in live_apps:
        cid = app.get("_company_id")
        if not cid or cid in seen:
            continue
        seen.add(cid)
        name = (companies.get(cid) or "").strip()
        if not name:
            continue
        if name.lower() in dn_low or (dom_norm and _normalize_name_token(name) in dom_norm):
            return cid
    return None


def resolve_application(subject, body_text_, from_domain, live_apps, companies):
    """§3.2 — ADR-030's three tiers, first hit wins, a tie STOPS (never falls through to a
    weaker tier). `live_apps` is every candidate application to consider, each optionally
    carrying `_company_id` (the caller's own derived field, `applications.py`'s
    underscore-prefix convention — never written back) for tier 3's company join.
    `from_domain` is accepted for the call signature ADR-030 states but never consulted:
    identification and resolution are deliberately two different questions."""
    text = "%s\n%s" % (subject or "", body_text_ or "")

    # Tier 1 — req_id, verbatim, word-bounded. A req_id shorter than 4 characters never
    # matches at this tier (a two-digit id is a substring of everything).
    hits1 = []
    for app in live_apps:
        rid = app.get("req_id")
        if not rid or len(str(rid)) < 4:
            continue
        if re.search(_WORD_BOUND_FMT % re.escape(str(rid)), text):
            hits1.append(app["id"])
    if hits1:
        uniq = sorted(set(hits1))
        return Resolved(uniq[0], "req-id") if len(uniq) == 1 else Tie(1, uniq)

    # Tier 2 — URL: host equal, stored path a PATH-PREFIX of the found path. Never a
    # substring match on raw text.
    found = [urllib.parse.urlparse(u) for u in _URL_RE.findall(body_text_ or "")]
    hits2 = []
    for app in live_apps:
        stored = app.get("url")
        if not stored:
            continue
        su = urllib.parse.urlparse(stored)
        if not su.netloc:
            continue
        s_path = su.path.rstrip("/") or "/"
        for fu in found:
            if fu.netloc != su.netloc:
                continue
            f_path = fu.path or "/"
            if f_path == s_path or f_path.startswith(s_path.rstrip("/") + "/") or s_path == "/":
                hits2.append(app["id"])
                break
    if hits2:
        uniq = sorted(set(hits2))
        return Resolved(uniq[0], "url") if len(uniq) == 1 else Tie(2, uniq)

    # Tier 3 — company name (subject/body/display name), exactly one live application at
    # that company. A tie at this tier is any company mentioned with 2+ live applications,
    # OR more than one distinct company mentioned — a title is not a stored key.
    text_low = text.lower()
    by_company = {}
    for app in live_apps:
        cid = app.get("_company_id")
        if cid:
            by_company.setdefault(cid, []).append(app["id"])
    mentioned = [cid for cid in by_company
                if (companies.get(cid) or "").strip()
                and companies[cid].strip().lower() in text_low]
    if mentioned:
        singles = [cid for cid in mentioned if len(by_company[cid]) == 1]
        if len(singles) == 1 and len(mentioned) == 1:
            return Resolved(by_company[singles[0]][0], "company-single")
        all_ids = sorted({aid for cid in mentioned for aid in by_company[cid]})
        return Tie(3, all_ids)
    return NoHit


def classify_status_phrase(text_low, status_phrases):
    """§3.3 — exactly one status class hit -> (status, False). Zero, or two at once ->
    (None, ambiguous_bool). `status_phrases`: dict status -> [phrase, ...]."""
    hits = []
    for status, phrases in (status_phrases or {}).items():
        for p in phrases or ():
            if p and str(p).lower() in text_low:
                hits.append(status)
                break
    uniq = sorted(set(hits))
    if len(uniq) == 1:
        return uniq[0], False
    return None, bool(uniq)


_SUBJECT_PREFIX_RE = re.compile(r"^\s*(re|fwd?)\s*:\s*", re.I)


def normalize_subject(subject):
    """§4.4 — strip Re:/Fwd: prefixes, digits, and whitespace runs, for the dedup hash."""
    s = (subject or "").strip()
    while True:
        s2 = _SUBJECT_PREFIX_RE.sub("", s)
        if s2 == s:
            break
        s = s2
    s = re.sub(r"\d+", "", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def iso_week(date_iso):
    try:
        d = datetime.date.fromisoformat(str(date_iso)[:10])
    except ValueError:
        d = datetime.date.today()
    y, w, _wd = d.isocalendar()
    return "%04dW%02d" % (y, w)


def _ask_key_hash(domain, subject):
    """The (domain, normalized subject) key's own hash — independent of `kind` and of the ISO
    week, so it is stable across both. §4.4's dedup key, and (dev #376 item 2) the same key a
    `resolution: noise` disposition suppresses future asks by."""
    return hashlib.sha1(("%s|%s" % ((domain or "").lower(), normalize_subject(subject)))
                        .encode("utf-8")).hexdigest()[:10]


_ASK_ID_RE = re.compile(r"^ask-ats-[a-z]+-([0-9a-f]{10})-\d{4}W\d{2}$")


def _ask_key_hash_from_id(ask_id):
    """The `_ask_key_hash(...)` segment embedded in an `ask-ats-<kind>-<hash>-<week>` id, or
    None when `ask_id` is not that shape at all (a hand-authored or pre-ADR-030 ask row)."""
    m = _ASK_ID_RE.match(ask_id or "")
    return m.group(1) if m else None


def ask_digest_id(kind, domain, subject, date_iso):
    """§4.4 — dedup is by (sender domain, normalized subject) per ISO week, never by uid."""
    return "ask-ats-%s-%s-%s" % (kind, _ask_key_hash(domain, subject), iso_week(date_iso))


def _read_config(root):
    """`config.json`, read directly off `root` — never `profile.config()`, whose own `ROOT`/
    `CONFIG_PATH` are bound once at FIRST IMPORT. A test (or a caller) that patches THIS
    module's `ROOT` (the established convention — `TestSweepAccountsWiredIntoTheFourCallers`'s
    own `_patch()`) would otherwise still read the profile.py module saw at its own first
    import, which is exactly the kind of staleness `configured_accounts()` above already
    documents fixing for the account list. `config_keys.describe()` takes a plain dict, so it
    is unaffected either way."""
    try:
        with open(os.path.join(root, "config.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def is_first_run_for_mailbox(root, mailbox):
    """§5 — has `reconcile.py --ats` (the REAL sweep, not a plan-only run — D6) ever
    completed a sweep of this mailbox? A `by: reconcile-ats-plan` row never counts."""
    recs = _journal.read(root)
    return not any(r.get("event") == "swept" and r.get("mailbox") == mailbox
                  and r.get("by") == "reconcile-ats" and r.get("ok")
                  for r in recs)


RECORD_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "record.py")


def _ats_scratch_dir(root):
    d = os.path.join(root, ".jobsearch", "ats-tmp")
    os.makedirs(d, exist_ok=True)
    return d


def _run_record(args_list):
    r = subprocess.run([sys.executable, RECORD_PY] + args_list, capture_output=True, text=True)
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def write_ats_message(subject, body, from_addr, mail_date_iso, source, scratch_dir,
                      opp_id=None, resolves=None, resolved_by=None, already_locked=False):
    """`record.py received ...` via subprocess — the CLI face is the write API; this never
    touches messages.jsonl directly. Returns (mid, ok, output)."""
    mid = "in-%s" % hashlib.sha1(source.encode("utf-8")).hexdigest()[:12]
    # `_atomic.write_text` — never a bare truncating write of this file's own — into a scratch
    # path named from the source's own hash, so two concurrent candidates never collide.
    path = os.path.join(scratch_dir, ".ats-body-%s.txt" % mid)
    try:
        write_text(path, body or "")
        cmd = ["received", "--from", from_addr or "unknown", "--on", mail_date_iso,
              "--subject", (subject or "")[:500], "--body-file", path, "--source", source]
        if opp_id and not resolves:
            cmd += ["--opp", opp_id]
        if resolves:
            cmd += ["--resolves", resolves, "--resolved-by", resolved_by]
        if already_locked:
            cmd += ["--already-locked"]
        ok, out = _run_record(cmd)
        return mid, ok, out
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def write_ats_status(app_id, status, on_date, note, already_locked=False):
    cmd = ["application-status", app_id, status, "--on", on_date, "--note", note]
    if already_locked:
        cmd += ["--already-locked"]
    return _run_record(cmd)


def write_or_extend_ask(kind, domain, subject, date_iso, note_tag, already_locked=False,
                        opp_id=None, trigger_ref=None, asks_by_id=None, cap=None,
                        created_counter=None, company_name=None):
    """§4.4 — one ask per (domain, normalized subject, ISO week); every further uid it
    absorbs is appended to the ask's `note`, never a second row. `cap`/`created_counter`
    (a one-item mutable list, `[n]`) enforce ADR-030 decision 5: a NEW ask counts against the
    per-run cap; extending an existing one's note does not. Returns (ask_id_or_None,
    withheld_bool).

    dev #376 item 2 — before a NEW ask is created (never before extending an existing one's
    own note; the exact-id lookup above already covers a same-week re-sight), check whether
    this (domain, normalized subject) KEY was ever resolved `noise`: if so, the caller's own
    count still advances (the message is not lost), but nothing is written here, ever again,
    for that key. `company_name` is used only by the `unidentified` finding kind's own text."""
    ask_id = ask_digest_id(kind, domain, subject, date_iso)
    existing = (asks_by_id or {}).get(ask_id)
    if existing is not None:
        new_note = ("%s | %s" % (existing.get("note"), note_tag)) if existing.get("note") \
            else note_tag
        _run_record(["set", ask_id, "note", new_note, "--file", "asks"] +
                   (["--already-locked"] if already_locked else []))
        return ask_id, False
    key_hash = _ask_key_hash(domain, subject)
    if any(a.get("resolution") == "noise" and _ask_key_hash_from_id(a.get("id")) == key_hash
          for a in (asks_by_id or {}).values()):
        print("  suppressed (noise): %s|%s" % ((domain or "").lower(),
                                                normalize_subject(subject)))
        return None, False
    if cap is not None and created_counter is not None and created_counter[0] >= cap:
        return None, True
    if kind == "unresolved":
        title = "Unidentified/unresolved ATS mail"
        text = ("A message from %s (%s) could not be resolved to a live application — check "
               "whether it names one, or add the domain to receipt_sender_domains."
               % (domain, subject[:60]))
    elif kind == "unidentified":
        title = "Possible ATS domain not configured"
        text = ("A message from %s (%s) names %s, a live application's company, but %s is "
               "not a configured or derived ATS domain — add it to receipt_sender_domains if "
               "this is the ATS." % (domain, subject[:60], company_name or domain, domain))
    else:
        title = "ATS status change proposed"
        text = ("A parsed ATS status change from %s (%s) is proposed, not applied — confirm "
               "or correct it." % (domain, subject[:60]))
    fields = {
        "kind": "system", "title": title[:120], "ask": text,
        "created": date_iso[:10], "act_by": (
            datetime.date.fromisoformat(date_iso[:10]) + datetime.timedelta(days=2)
        ).isoformat(),
        "opp_id": opp_id, "channel_id": None, "resolves_when": None,
        "resolved_on": None, "resolution": None,
        "trigger_kind": "reply" if trigger_ref else None,
        "trigger_ref": trigger_ref, "note": note_tag,
    }
    ok, _out = _run_record(["create", ask_id, json.dumps(fields), "--file", "asks"] +
                           (["--already-locked"] if already_locked else []))
    if ok:
        if created_counter is not None:
            created_counter[0] += 1
        if asks_by_id is not None:
            # Update the CALLER's own dict in place — a second candidate landing later in
            # THIS SAME run (the same digest, a different uid) must see the ask this call
            # just created as already existing, or it tries `create` again on an id that is
            # now on disk and gets refused instead of extending the note.
            asks_by_id[ask_id] = dict(fields, id=ask_id)
    return (ask_id if ok else None), False


def cmd_ats(args):
    """`reconcile.py --ats [--already-locked]` — the fifth `sweep_accounts()` caller (design
    §4). Runs once, in the daily's write phase, immediately after its own lock take
    (design §6). Every write goes through `record.py`'s own lock/validate/rollback (§2);
    this function never opens a store file for writing."""
    import applications as _apps_mod
    import config_keys as _ck
    import record as _record

    # public #101's own fix, applied here too: every provenance/historical-window comparison
    # in this sweep uses the RUN's own date, never a fresh `datetime.date.today()` call at the
    # point of use — `--as-of` (validated in main() before dispatch) is the identical test
    # seam `--apply`'s MEDIUM RECOVERED note now uses, so a test can pin the clock here the
    # same way.
    run_date = args.as_of or datetime.date.today().isoformat()
    run_date_d = datetime.date.fromisoformat(run_date)

    cfg = _read_config(ROOT)
    parsed_status, _p1 = _ck.describe(cfg, _ck.ATS_PARSED_STATUS)
    sweep_floor, _p2 = _ck.describe(cfg, _ck.ATS_SWEEP_DAYS)
    max_asks, _p3 = _ck.describe(cfg, _ck.ATS_MAX_ASKS_PER_RUN)

    opps = load("opportunities.jsonl")
    opps_by_id = {o.get("id"): o for o in opps}
    companies_map = {c["id"]: c.get("name", c["id"]) for c in load("companies.jsonl")}
    all_apps, _e, _pres = _apps_mod.load(ROOT)
    app_by_id = {a["id"]: a for a in all_apps if a.get("id")}
    live_apps = _apps_mod.live(all_apps)
    for a in live_apps:
        opp = opps_by_id.get(a.get("opp_id")) or {}
        a["_company_id"] = opp.get("company_id")

    messages_all = load("messages.jsonl")
    have_sources = {m.get("source") for m in messages_all if m.get("source")}
    configured_domains = list(((cfg.get("ats") or {}).get("receipt_sender_domains")) or [])
    derived_domains = derived_sender_domains(messages_all)
    sp = (cfg.get("ats") or {}).get("status_phrases")
    status_phrases = sp if isinstance(sp, dict) else {}

    asks_all = load("asks.jsonl")
    asks_by_id = {a.get("id"): a for a in asks_all}

    # D5/D6 — `can_write` is the ACTUAL lock state, independent of whether `--already-locked`
    # was passed: unheld -> plan-only (classify, print, write a `by: reconcile-ats-plan`
    # `swept` row, exit 2, touch no other store); held (or no flag at all, in which case this
    # call takes its own short lock per write via record.py's plain path) -> real writes.
    backfill = bool(getattr(args, "backfill_asks", False))
    dry_run = bool(getattr(args, "dry_run", False))
    lock_ok = (not args.already_locked) or _record.lock_is_held()
    can_write = lock_ok and not dry_run
    by_tag = "reconcile-ats" if can_write else "reconcile-ats-plan"
    scratch = _ats_scratch_dir(ROOT)

    accounts = configured_accounts()
    plan_lines, asks_created, applied, proposed, withheld = [], [0], [0], [0], [0]
    history_counts = {"total": 0, "applied": 0, "recorded": 0, "unresolved": 0}

    # design-inbound-resolution.md §2 amendment D1 (surface pass 2026-09-14) — a message that
    # RESOLVES an application is its own idempotency mark by uid (via `source`), so a status
    # write that was refused, rolled back, or never reached because the process died between
    # the two writes would otherwise never be retried: the uid is already "seen". THE
    # COMPLETION MARK ON THE APPLY PATH IS THE STATUS WRITE ITSELF, not the message row — every
    # already-landed `resolves` message whose application's own `note` does not yet carry
    # `reconcile-ats <message id>` gets its status write RE-ATTEMPTED here, before any mailbox
    # search runs (no mail access needed: the message row already carries the evidence).
    # Idempotent under the monotone rule — a status already applied, or one whose new value
    # matches what is already there, is a no-op, never re-applied twice.
    for m in messages_all:
        resolves = m.get("resolves")
        if not resolves:
            continue
        app = app_by_id.get(resolves)
        if app is None:
            continue
        mark = "reconcile-ats %s" % m.get("id")
        if mark in (app.get("note") or ""):
            continue
        status, ambiguous = classify_status_phrase(
            ("%s\n%s" % (m.get("subject") or "", m.get("body") or "")).lower(), status_phrases)
        if status is None or ambiguous:
            continue          # a phrase-0/2 (unresolved-ask) case, not an apply — no retry
        current_status, current_status_on = app.get("status"), app.get("status_on")
        if current_status == "withdrawn" or current_status == status:
            continue
        if (current_status_on and
                _vd.date_part(m.get("sent_on")) < _vd.date_part(current_status_on)):
            continue
        if not can_write:
            plan_lines.append("  would retry status write for %s (message %s landed, status "
                             "write incomplete — D1)" % (resolves, m.get("id")))
            continue
        note = "reconcile-ats %s; was %s since %s" % (m.get("id"), current_status,
                                                       current_status_on)
        ok2, out2 = write_ats_status(resolves, status, _vd.date_part(m.get("sent_on")), note,
                                     already_locked=args.already_locked)
        if ok2:
            applied[0] += 1
            plan_lines.append("  applied (D1 retry): %s -> %s" % (resolves, status))
        else:
            plan_lines.append("  ⚠️ %s: D1 retry status write refused: %s" % (resolves, out2))

    def process_candidate(mb, account, uid, since_days, first_run):
        source = "ats:%s:%s" % (account, uid)
        if source in have_sources:
            return
        tag = "mail:%s:%s" % (account, uid)
        if any(tag in (a.get("note") or "") for a in asks_all):
            return
        hdr = mb.fetch_headers(uid)
        if hdr is None:
            return
        frm = decode_header_value(hdr.get("From")) or ""
        display_name, from_addr = parseaddr(frm)
        from_domain = from_addr.rsplit("@", 1)[-1].strip().lower() if "@" in from_addr else ""
        subject = decode_header_value(hdr.get("Subject")) or ""
        ok_class, _leg = identify_sender_class(from_domain, configured_domains, derived_domains)

        if not ok_class:
            # §3.1's identification-uncertain case (dev #376 item 1) — a domain in NEITHER
            # leg that (a) hits a status_phrases entry AND (b) names a live application's
            # company in its DISPLAY NAME or DOMAIN (never subject/body — that is §3.2's
            # resolution evidence, not §3.1's identification evidence) gets an
            # `ask-ats-unidentified-*` finding. It never resolves, never writes a status,
            # never enters messages.jsonl (design table §4.4).
            body = ""
            full = mb.fetch_full(uid)
            if full is not None:
                body = body_text(full, limit=8000) or ""
            mail_date = parse_hdr_date(decode_header_value(hdr.get("Date")))
            mail_date_iso = mail_date.isoformat() if mail_date else run_date
            status_hit, status_ambig = classify_status_phrase(
                ("%s\n%s" % (subject, body)).lower(), status_phrases)
            if status_hit is None and not status_ambig:
                return
            cid = unidentified_finding_company(display_name, from_domain, live_apps,
                                               companies_map)
            if cid is None:
                return
            company_name = companies_map.get(cid, cid)
            if not can_write:
                plan_lines.append("  would ask (unidentified sender): %s / %s (%s)"
                                 % (from_domain, subject[:60], company_name))
                return
            _aid, was_withheld = write_or_extend_ask(
                "unidentified", from_domain, subject, mail_date_iso, tag,
                already_locked=args.already_locked, opp_id=None, trigger_ref=None,
                asks_by_id=asks_by_id, cap=max_asks, created_counter=asks_created,
                company_name=company_name)
            if was_withheld:
                withheld[0] += 1
            return

        body = ""
        full = mb.fetch_full(uid)
        if full is not None:
            body = body_text(full, limit=8000) or ""
        mail_date = parse_hdr_date(decode_header_value(hdr.get("Date")))
        mail_date_iso = mail_date.isoformat() if mail_date else run_date
        historical = bool(first_run and mail_date
                          and (run_date_d - mail_date).days > sweep_floor)

        result = resolve_application(subject, body, from_domain, live_apps, companies_map)
        status, ambiguous = classify_status_phrase(("%s\n%s" % (subject, body)).lower(),
                                                    status_phrases)
        have_sources.add(source)          # never re-process this uid, whatever happens below
        if historical:
            history_counts["total"] += 1

        def _write_msg(opp_id=None, resolves=None, resolved_by=None):
            if not can_write:
                return None, False, "(plan-only)"
            return write_ats_message(subject, body, from_addr, mail_date_iso, source, scratch,
                                     opp_id=opp_id, resolves=resolves, resolved_by=resolved_by,
                                     already_locked=args.already_locked)

        def _ask(kind, opp_id=None, trigger_ref=None):
            if not can_write:
                withheld[0] += 1
                return None
            aid, was_withheld = write_or_extend_ask(
                kind, from_domain, subject, mail_date_iso, tag,
                already_locked=args.already_locked, opp_id=opp_id, trigger_ref=trigger_ref,
                asks_by_id=asks_by_id, cap=max_asks, created_counter=asks_created)
            if was_withheld:
                withheld[0] += 1
            return aid

        if isinstance(result, Resolved):
            app = app_by_id.get(result.app_id)
            opp_id = app.get("opp_id") if app else None
            tier_num = 1 if result.tier == "req-id" else (2 if result.tier == "url" else 3)
            receipt_grade = tier_num in (1, 2)
            apply_it = parsed_status == "all" or (receipt_grade and parsed_status == "receipt-grade")

            if status is None or ambiguous:
                if historical:
                    history_counts["unresolved"] += 1
                    if not backfill:
                        return
                mid, wrote_ok, _out = _write_msg(opp_id=opp_id, resolves=result.app_id,
                                                 resolved_by=result.tier)
                if can_write and not wrote_ok:
                    plan_lines.append("  ⚠️ %s: message write refused: %s" % (source, _out))
                    return
                if not can_write:
                    plan_lines.append("  would ask (unresolved status phrase): %s / %s"
                                     % (opp_id, subject[:60]))
                    return
                _ask("unresolved", opp_id=opp_id, trigger_ref=mid if wrote_ok else None)
                return

            if not apply_it:
                if historical:
                    history_counts["unresolved"] += 1
                    if not backfill:
                        return
                mid, wrote_ok, _out = _write_msg(opp_id=opp_id, resolves=result.app_id,
                                                 resolved_by=result.tier)
                if not can_write:
                    plan_lines.append("  would propose: %s -> %s (tier %s)"
                                     % (result.app_id, status, result.tier))
                    return
                if not wrote_ok:
                    plan_lines.append("  ⚠️ %s: message write refused: %s" % (source, _out))
                    return
                _ask("proposed", opp_id=opp_id, trigger_ref=mid)
                proposed[0] += 1
                return

            # apply path — monotonicity first.
            current_status = app.get("status") if app else None
            current_status_on = app.get("status_on") if app else None
            if current_status == "withdrawn":
                plan_lines.append("  · %s: withdrawn — mail ignored (owner's own statement)"
                                 % result.app_id)
                if historical:
                    history_counts["recorded"] += 1
                return
            if (current_status_on and
                    _vd.date_part(mail_date_iso) < _vd.date_part(current_status_on)):
                plan_lines.append("  · %s: mail predates status_on — refused (monotone)"
                                 % result.app_id)
                if historical:
                    history_counts["recorded"] += 1
                return
            if current_status == status:
                _write_msg(opp_id=opp_id, resolves=result.app_id, resolved_by=result.tier)
                if historical:
                    history_counts["recorded"] += 1
                return
            if not can_write:
                plan_lines.append("  would apply: %s -> %s (tier %s)"
                                 % (result.app_id, status, result.tier))
                return
            mid, wrote_ok, _out = _write_msg(opp_id=opp_id, resolves=result.app_id,
                                             resolved_by=result.tier)
            if not wrote_ok:
                plan_lines.append("  ⚠️ %s: message write refused, status NOT applied: %s"
                                 % (result.app_id, _out))
                return
            note = "reconcile-ats %s; was %s since %s" % (mid, current_status, current_status_on)
            ok2, out2 = write_ats_status(result.app_id, status, _vd.date_part(mail_date_iso),
                                         note, already_locked=args.already_locked)
            if ok2:
                applied[0] += 1
                if historical:
                    history_counts["applied"] += 1
                plan_lines.append("  applied: %s -> %s (tier %s)" % (result.app_id, status,
                                                                     result.tier))
            else:
                plan_lines.append("  ⚠️ %s: status write refused: %s" % (result.app_id, out2))
            return

        # Tie or NoHit — an anchor exists only when every candidate shares one opp_id.
        candidate_ids = result.candidate_ids if isinstance(result, Tie) else []
        candidate_opps = {app_by_id.get(cid, {}).get("opp_id") for cid in candidate_ids}
        candidate_opps.discard(None)
        anchor_opp = next(iter(candidate_opps)) if len(candidate_opps) == 1 else None
        if historical:
            history_counts["unresolved"] += 1
            if not backfill:
                return
        mid = None
        if anchor_opp and can_write:
            mid, wrote_ok, _out = _write_msg(opp_id=anchor_opp)
            if not wrote_ok:
                mid = None
        if not can_write:
            plan_lines.append("  would ask (unidentified/tie): %s" % subject[:60])
            return
        _ask("unresolved", opp_id=anchor_opp, trigger_ref=mid)

    incomplete_all = []
    for account in accounts:
        since_days = lookback_days(ROOT, account, sweep_floor, by="reconcile-ats")
        first_run = is_first_run_for_mailbox(ROOT, account)
        domains = sorted(set(configured_domains) | set(derived_domains))
        plan_lines.append("  %s: window %dd (floor %d, ledger says covered through %s)%s"
                          % (account, since_days, sweep_floor,
                             _journal.covered_through(_journal.read(ROOT), account,
                                                      by="reconcile-ats") or "never",
                             " — FIRST RUN: history counted, receipt-grade applied, nothing "
                             "asked" if first_run else ""))
        plan_lines.append("  %s: class %d configured, %d derived%s"
                          % (account, len(configured_domains), len(derived_domains),
                             " — %s add it to receipt_sender_domains to make the record "
                             "say so" % ", ".join(derived_domains) if derived_domains else ""))

        def search_one(acct, _since_days=since_days, _first_run=first_run):
            """D7 — catches EVERYTHING. A non-CredentialError exception is an ok:false row
            with reason 'other', never a traceback out of sweep_accounts()."""
            if not domains:
                return [], None
            try:
                with Mailbox(acct) as mb:
                    q = "(%s) newer_than:%dd" % (
                        " OR ".join("from:%s" % d for d in domains), _since_days)
                    uids = mb.search(q)
                    for uid in uids:
                        process_candidate(mb, acct, uid, _since_days, _first_run)
                return [], None
            except CredentialError as exc:
                return None, str(exc)
            except Exception as exc:                            # noqa: BLE001 — D7
                return None, "%s: %s" % (type(exc).__name__, exc)

        _res, incomplete = sweep_accounts(search_one, since_days=since_days, root=ROOT,
                                          by=by_tag, accounts=[account])
        incomplete_all += incomplete

    print("ATS STATUS SWEEP — reconcile.py --ats (design-inbound-resolution.md)")
    print("=" * 78)
    print("  posture: ats.parsed_status=%s · ats.max_asks_per_run=%d%s"
         % (parsed_status, max_asks, " · --backfill-asks" if backfill else ""))
    for line in plan_lines:
        print(line)
    if history_counts["total"]:
        tail = ("not asked; --backfill-asks writes them under the cap" if not backfill
               else "backfilled this run under the cap")
        print("  %d historical ATS message(s): %d applied, %d already recorded, %d "
             "unresolved (%s)"
             % (history_counts["total"], history_counts["applied"],
                history_counts["recorded"], history_counts["unresolved"], tail))
    print("  applied: %d · proposed: %d · asks created: %d · withheld this run: %d"
         % (applied[0], proposed[0], asks_created[0], withheld[0]))
    if withheld[0]:
        print("  %d candidate(s) not asked this run (cap %d) — re-seen next run"
             % (withheld[0], max_asks))
    if incomplete_all:
        print("!! INCOMPLETE COVERAGE: %s" % ", ".join(sorted(set(incomplete_all))))

    if not can_write:
        if dry_run:
            print("DRY RUN — plan only; every store is byte-identical to before this run.")
        else:
            print("WRITE PHASE SKIPPED — the run lock is not held. Plan only; every store is "
                 "byte-identical to before this run. Re-run under the daily's write phase, or "
                 "take the lock by hand, to actually apply this plan.")
        return 2
    return 1 if incomplete_all else 0


def cmd_verify(args):
    """`reconcile.py --ats --verify [--days 30]` — design §7's ingestion half of the
    invariant: a READ, independent of the ledger, that catches a record.py write that never
    happened for mail the mailbox actually has. D2 — a mailbox this cannot even OPEN prints
    UNVERIFIED (the SILENCE UNVERIFIED banner's own shape), never 'no traffic', and the run
    exits non-zero."""
    cfg = _read_config(ROOT)
    configured_domains = list(((cfg.get("ats") or {}).get("receipt_sender_domains")) or [])
    messages_all = load("messages.jsonl")
    derived_domains = derived_sender_domains(messages_all)
    domains = sorted(set(configured_domains) | set(derived_domains))
    asks_all = load("asks.jsonl")
    have_sources = {m.get("source") for m in messages_all if m.get("source")}
    days = args.days or COVERAGE_BACKFILL_MAX_DAYS

    problem = False
    accounts = configured_accounts()
    for account in accounts:
        try:
            with Mailbox(account) as mb:
                per_domain = {}
                for d in domains:
                    uids = mb.search("from:%s newer_than:%dd" % (d, days))
                    n_recorded = n_asked = n_unrecorded = n_historical = 0
                    first_run = is_first_run_for_mailbox(ROOT, account)
                    for uid in uids:
                        source = "ats:%s:%s" % (account, uid)
                        tag = "mail:%s:%s" % (account, uid)
                        if source in have_sources:
                            n_recorded += 1
                        elif any(tag in (a.get("note") or "") for a in asks_all):
                            n_asked += 1
                        elif first_run:
                            n_historical += 1
                        else:
                            n_unrecorded += 1
                            problem = True
                    per_domain[d] = (len(uids), n_recorded, n_asked, n_historical,
                                     n_unrecorded)
                print("--VERIFY %s (window %dd)" % (account, days))
                for d in domains:
                    n, rec, asked, hist, unrec = per_domain.get(d, (0, 0, 0, 0, 0))
                    if n == 0:
                        print("  %s: no traffic" % d)
                        continue
                    leg = "derived, not configured" if d in derived_domains and d not in \
                        configured_domains else "configured"
                    print("  %s (%s): %d received · %d rows · %d asked · %d historical · "
                         "%d UNRECORDED" % (d, leg, n, rec, asked, hist, unrec))
                    if unrec:
                        print("  ⛔ %d UNRECORDED — inside the sweep's own window; this is a "
                             "PROCESS FAILURE" % unrec)
        except CredentialError as exc:
            print("--VERIFY %s: UNVERIFIED (credential-missing: %s)" % (account, exc))
            problem = True
        except Exception as exc:                                # noqa: BLE001
            print("--VERIFY %s: UNVERIFIED (%s: %s)" % (account, type(exc).__name__, exc))
            problem = True
    if not accounts:
        print("--VERIFY: no mailbox configured — UNVERIFIED")
        problem = True
    return 1 if problem else 0


def main():
    ap = argparse.ArgumentParser(description="Reconcile tracked state against mail + LinkedIn.")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--unknown-medium", action="store_true")
    ap.add_argument("--role", metavar="OPP_ID")
    ap.add_argument("--apply", action="store_true",
                    help="Write unambiguous medium fixes. Never touches outcome.")
    ap.add_argument("--limit", type=int, default=0, help="Max rows to check (0 = no cap).")
    ap.add_argument("--harvest", action="store_true",
                    help="Write the ACTUAL messages (both directions) into data/messages.jsonl.")
    ap.add_argument("--ats", action="store_true",
                    help="design-inbound-resolution.md — the deterministic ATS status sweep "
                         "(ADR-029/030). Run in the daily's write phase, immediately after its "
                         "own lock take; every write is under record.py's own lock/validate/"
                         "rollback.")
    ap.add_argument("--already-locked", action="store_true",
                    help="--ats: the calling run already holds the run lock. Verified, not "
                         "trusted — unheld, --ats degrades to plan-only (exit 2) rather than "
                         "hard-refusing (design §6).")
    ap.add_argument("--verify", action="store_true",
                    help="--ats --verify: read-only ingestion check (design §7) — queries "
                         "each mailbox for the sender class over the window independent of "
                         "the ledger; an UNRECORDED uid inside the sweep's own window is a "
                         "process failure, exit 1. A mailbox this cannot open prints "
                         "UNVERIFIED and exits non-zero (D2).")
    ap.add_argument("--days", type=int, default=0,
                    help="--ats --verify: window in days (default: "
                         "COVERAGE_BACKFILL_MAX_DAYS).")
    # ⭐ public #101 — the test seam. `--apply`'s provenance note used to carry a LITERAL date
    # string (the date this feature was first written), so a row recovered weeks later carried
    # a false provenance date forever — nothing about the write depended on when the RUN
    # actually happened. `--as-of` lets a test assert the stamp tracks a controlled clock
    # rather than reading real wall time in the harness; every real invocation leaves it unset
    # and gets today, exactly as before this fix in every way except correctness.
    ap.add_argument("--as-of", dest="as_of", default=None,
                    help="ISO date (YYYY-MM-DD) this run's own provenance stamps use — "
                         "default: today. Test seam; a real run never needs this.")
    ap.add_argument("--backfill-asks", action="store_true",
                    help="--ats: write the historical unresolved/proposed candidates the "
                         "first-run history branch (design §5, decision 5) normally only "
                         "counts, under the per-run cap. A hand flag — never invoked from a "
                         "skill.")
    ap.add_argument("--dry-run", action="store_true",
                    help="--ats --backfill-asks: print the plan without writing anything; "
                         "every store stays byte-identical to before the run.")
    args = ap.parse_args()
    if args.as_of and not re.match(r"^\d{4}-\d{2}-\d{2}$", args.as_of):
        print("⛔ REFUSED — --as-of must be an ISO date (YYYY-MM-DD), got %r" % args.as_of)
        return 1
    run_date = args.as_of or datetime.date.today().isoformat()

    if args.ats:
        return cmd_verify(args) if args.verify else cmd_ats(args)

    opps = load("opportunities.jsonl")
    companies = {c["id"]: c.get("name", c["id"]) for c in load("companies.jsonl")}
    accounts = configured_accounts()
    opps_by_id = {o.get("id"): o for o in opps}

    # ADR-031 B3 — `touches` is the top-level store now, joined by `opp_id`; never a nested
    # array on the opportunity record. `idx` is retired in favor of the touch's own `id` — the
    # write-back below addresses a row by id, never by position in an array that no longer
    # exists (see the `--apply` block).
    targets = []
    for r in _touches.load(ROOT)[0]:
        oid = r.get("opp_id")
        o = opps_by_id.get(oid) or {}
        if args.role and oid != args.role:
            continue
        if not args.role and not args.all and not args.unknown_medium:
            if o.get("status") not in ("active-pursuit", "needs-resolution", "in-motion"):
                continue
        if args.unknown_medium and r.get("medium") != "unknown":
            continue
        targets.append((o, r.get("id"), r))
    if args.limit:
        targets = targets[:args.limit]

    print("RECONCILE — tracked state vs the source channels (mail + LinkedIn notifications)")
    print("=" * 78)
    print("Checking %d outreach row(s) across %s" % (len(targets), ", ".join(accounts)))
    print("Tracked state is a TRANSCRIPTION of what happened in email and LinkedIn. The source")
    print("can be re-read; the transcription can be incomplete, stale, or lossy.\n")

    findings = {"medium": [], "reply": [], "accepted": [], "none": [], "ambiguous": []}
    sess = Session()

    # dev #334 — open every account's connection through the shared coverage-ledger site
    # instead of Session's own former constructor loop. `since_days`: reconcile's own query
    # (`in:anywhere (...)`, below) carries NO time restriction — it is unbounded, unlike
    # alert_sweep/meeting_check/watch's `newer_than:%dd` windows. There is no true "window this
    # sweep searched" to report, so recording `COVERAGE_BACKFILL_MAX_DAYS` is a deliberately
    # CONSERVATIVE understatement (the real search covers strictly more than this claims) rather
    # than a guess at "forever" — the ledger's own rule is that a window WIDER than what was
    # searched is a lie; a window narrower than an actually-unbounded search is merely modest,
    # never dishonest.
    def search_one(account):
        return [], sess.open_account(account)

    _sweep_results, incomplete = sweep_accounts(
        search_one, since_days=COVERAGE_BACKFILL_MAX_DAYS, root=ROOT, by="reconcile",
        accounts=accounts)

    n_done = 0

    # ⭐⭐ THE JOIN KEY IS THE PERSON, ACROSS EVERY OPPORTUNITY THAT NAMES THEM — dev #101 /
    # public #13, the sibling of dev #65 / public #2. See `group_by_contact` and
    # `attribute_hits` for the mechanism and why the earlier, opportunity-scoped grouping let
    # the same event satisfy more than one row as long as the rows lived in different
    # opportunities.
    groups = group_by_contact(targets)

    for g in groups.values():
        name, terms = g["name"], g["terms"]
        q = "in:anywhere (%s)" % " OR ".join(terms)
        hits = sess.search(q)
        sys.stderr.write("  ... %d/%d %s\r" % (n_done + 1, len(groups), name[:28]))
        sys.stderr.flush()
        n_done += 1

        rows = sorted(g["rows"], key=lambda t: row_date(t[2]) or datetime.date.min)
        attributed, ambiguous = attribute_hits_report(rows, hits)
        for h, cands in ambiguous:
            findings["ambiguous"].append((name, h, [
                "%s — sent %s" % (companies.get(o.get("company_id"), o.get("company_id")),
                                  r.get("date")) for o, _i, r in cands]))

        for o, idx, r in rows:
            rd = row_date(r)
            mine = attributed.get(id(r), [])
            # Medium is a property of how this PERSON is reached, so it is inferred from every
            # message. Reply and acceptance are properties of THIS ROW, so they see only what
            # was attributed to it.
            medium, _all_replied, _all_accepted = classify(hits, name, rd)
            _m, replied, accepted = classify(mine, name, rd)

            # ⚠️ An invitation ACCEPTANCE answers a connection request, not an email or an
            # InMail. Reported against a row of another medium it is noise by construction —
            # the second half of what made this audit unreadable.
            if accepted and r.get("medium") not in (None, "unknown",
                                                    "linkedin-connection-note"):
                accepted = False

            label = "%s — %s" % (companies.get(o.get("company_id"), o.get("company_id")), name)
            if not hits:
                findings["none"].append((o, idx, r, label))
                continue
            if r.get("medium") == "unknown" and medium:
                findings["medium"].append((o, idx, r, label, medium, len(hits)))
            # `responded_on` set means a human already read this inbound and dispositioned
            # it. Without this test the audit re-reports it EVERY week and never stops. The
            # case that forced it (2026-08-02): an OOO auto-reply is real inbound mail, so it
            # must be recorded — but it is NOT a substantive answer, so `outcome` correctly
            # stays `awaiting` and the thread keeps aging. Keying only on `outcome` made that
            # legitimate state permanently indistinguishable from a missed reply.
            if replied and r.get("outcome") in ("awaiting", None) \
                    and not r.get("responded_on"):
                findings["reply"].append((o, idx, r, label, replied))
            if accepted and r.get("outcome") == "awaiting" and not r.get("responded_on"):
                findings["accepted"].append((o, idx, r, label))

    if findings["reply"]:
        print("-" * 78)
        print("⚠️  UNRECORDED REPLY — the row says awaiting, but they answered")
        print("-" * 78)
        print("  This is the finding that costs real opportunities. NOT auto-applied: a reply")
        print("  changes what the candidate should DO, so it needs a human read, not a silent field flip.\n")
        for o, idx, r, label, replied in findings["reply"]:
            print("  • %s  (sent %s)" % (label, r.get("date")))
            for h in replied[:3]:
                print("      %s | %s" % ((h["date"] or "?")[:31], (h["subject"] or "")[:64]))
            print()

    if findings["ambiguous"]:
        print("-" * 78)
        print("❓ AMBIGUOUS — an inbound event on the SAME DAY as the row(s) it might answer")
        print("-" * 78)
        print("  Dates alone cannot order these, so nothing is asserted (the old audit picked the")
        print("  last candidate, which looked measured and was not). Decide once and record it as")
        print("  data: messages[].answers on the reply, and responded_on on the row. A time on the")
        print("  row's own date ('YYYY-MM-DD HH:MM') lets the next audit order it mechanically.\n")
        for name, h, cands in findings["ambiguous"]:
            print("  • %s  %s | %s" % (name[:40], (h.get("date") or "?")[:31],
                                      (h.get("subject") or "")[:48]))
            for c in cands:
                print("      candidate: %s" % c)
        print()

    if findings["accepted"]:
        print("-" * 78)
        print("⚠️  UNRECORDED ACCEPTANCE — LinkedIn says they accepted; the row still says awaiting")
        print("-" * 78)
        for o, idx, r, label in findings["accepted"]:
            print("  • %s  (sent %s) -> consider outcome: accepted" % (label, r.get("date")))
        print()

    if findings["medium"]:
        print("-" * 78)
        print("MEDIUM EVIDENCE — rows recorded as 'unknown' that the mailbox can resolve")
        print("-" * 78)
        for o, idx, r, label, medium, n in findings["medium"]:
            print("  • %-52s unknown -> %-9s (%d msg)" % (label[:52], medium, n))
        print()

    if findings["none"]:
        print("-" * 78)
        print("NO TRACE — searched and found nothing (reported, not silently skipped)")
        print("-" * 78)
        for o, idx, r, label in findings["none"]:
            print("  • %-52s %s" % (label[:52], r.get("date")))
        print("  ⚠️ THIS TOOL SEARCHES EMAIL ONLY. Outreach migrated to LinkedIn CONNECTION")
        print("     REQUESTS (the candidate, 2026-08-03), which leave NO mail trace, so a request reads")
        print("     as NO TRACE here forever. Verify those on the Sent Invitations page:")
        print("       https://www.linkedin.com/mynetwork/invitation-manager/sent/")
        print("     Read this section as 'unverifiable here', NEVER as 'did not happen'.")
        print("  A zero is only meaningful when you can see it was looked for. Likely causes:")
        print("  a LinkedIn touch with notifications off, or a name the mailbox spells differently.\n")

    if args.apply and findings["medium"]:
        # ADR-031 B3 — the write lands on `data/touches.jsonl`, addressed by the touch's OWN
        # `id`, never by position in `opportunities[].outreach[]` (which no longer exists).
        by_id = {}
        for o, tid, r, label, medium, n in findings["medium"]:
            by_id[tid] = medium
        path = os.path.join(DATA, "touches.jsonl")
        with open(path, encoding="utf-8") as fh:
            lines = [json.loads(l) for l in fh if l.strip()]
        changed = 0
        for row in lines:
            medium = by_id.get(row.get("id"))
            if medium is None:
                continue
            # Only the coarse family is provable from a header. linkedin-message vs
            # connection-note vs InMail is NOT distinguishable this way, so don't pretend.
            row["medium"] = "email-reply" if medium == "email" and \
                (row.get("touch_type") in ("reply", "chase")) else (
                    "email-cold" if medium == "email" else "linkedin-message")
            if row["medium"].startswith("email") and not row.get("address_status"):
                row["address_status"] = "unknown"
            row["note"] = ((row.get("note") + " | ") if row.get("note") else "") + \
                ("MEDIUM RECOVERED %s by scripts/reconcile.py from the mailbox. "
                 "The header proves the FAMILY (email vs LinkedIn); it cannot distinguish "
                 "connection-note vs InMail vs free message, so the finer value is not "
                 "asserted." % run_date)
            changed += 1
        write_jsonl(path, lines)
        print("APPLIED: medium filled on %d row(s). Run validate_data.py." % changed)
    elif findings["medium"]:
        print("  (re-run with --apply to write these; outcome changes are never auto-applied)\n")

    # ---- --harvest: store the ACTUAL conversation, both directions -------------
    #
    # design-inbound-resolution.md §2 (ADR-029) — every row lands through
    # `record.append_message()`, in-process, never a second hand-rolled append+write_jsonl.
    # Before this fix the whole batch was ONE unlocked, unvalidated write at the end of the
    # loop; now each message is its own short-held-lock, validator-run, rollback-on-a-new-
    # problem transaction — the same guarantee `cmd_touched`/`cmd_answered` give their own
    # writes. `have` is still read once up front (an id-membership check, never a second
    # source of truth) so a uid already recorded is skipped before the write is even attempted.
    if args.harvest:
        import record as _record
        have = {m.get("source") for m in load("messages.jsonl")}
        added, refused = 0, 0
        print("\n" + "-" * 78)
        print("HARVEST — writing the actual messages into data/messages.jsonl")
        print("-" * 78)
        print("  Both directions. Until now the store held ZERO bodies and inbound replies")
        print("  existed only as an `outcome` flag, so 'all communications' was not modelled.\n")
        for o, idx, r in targets:
            name, terms = person_terms(r.get("to"))
            if not terms:
                continue
            for acct, uid in sess.search_uids("in:anywhere (%s)" % " OR ".join(terms), limit=12):
                src = "gmail:%s:%s" % (acct, uid)
                if src in have:
                    continue
                msg = sess.fetch_full(acct, uid)
                if msg is None:
                    continue
                frm = decode_header_value(msg.get("From")) or ""
                subj = decode_header_value(msg.get("Subject")) or ""
                # Skip LinkedIn/system notifications — they are SIGNALS about a conversation,
                # not the conversation. classify() already uses them for state.
                if any(sdr in frm.lower() for sdr in LINKEDIN_SENDERS) or "noreply" in frm.lower():
                    continue
                last = (name or "").split()[-1].lower() if name else ""
                if last and last not in frm.lower() and last not in (
                        decode_header_value(msg.get("To")) or "").lower():
                    continue
                try:
                    body = body_text(msg, limit=8000) or ""
                except Exception:
                    body = ""
                if not body.strip():
                    continue
                d = parse_hdr_date(decode_header_value(msg.get("Date")))
                inbound = last in frm.lower() if last else False
                row = {
                    "id": "%s-%s-%s" % ((o.get("id") or "x")[:28],
                                        (r.get("person_id") or "x"), uid),
                    "opp_id": o.get("id"), "channel_id": None,
                    "person_id": r.get("person_id"),
                    "direction": "inbound" if inbound else "outbound",
                    "medium": r.get("medium") if not inbound else "email-reply",
                    "sent_on": d.isoformat() if d else None,
                    "from": frm, "to": decode_header_value(msg.get("To")),
                    "subject": subj, "body": body[:8000],
                    "source": src, "variant": None, "answers": None,
                    "resolves": None, "resolved_by": None,
                }
                rc, out = _record.append_message(row, already_locked=False)
                have.add(src)          # never re-attempt this uid, refused or not
                if rc == 0:
                    added += 1
                else:
                    refused += 1
                    print("  ⚠️ %s: %s" % (src, out.strip()))
        existing = load("messages.jsonl")
        ins = sum(1 for m in existing if m.get("direction") == "inbound")
        outs = sum(1 for m in existing if m.get("direction") == "outbound")
        print("  harvested %d new message(s)%s. Store now: %d inbound / %d outbound."
              % (added, (" (%d refused)" % refused) if refused else "", ins, outs))
        print("  Every row carries `source` (gmail:<account>:<uid>) so it can be re-verified.")

    sess.close()

    # dev #334 — `incomplete` is the shared ledger site's own list, from the `search_one` call
    # made when connections were opened above — not a second, independently-collected one.
    if incomplete:
        print("!! INCOMPLETE COVERAGE: %s"
              % "; ".join(sess.account_errors.get(a, a) for a in sorted(set(incomplete))))
        print("   Results are PARTIAL. Do not conclude a message does not exist.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
