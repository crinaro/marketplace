#!/usr/bin/env python3
"""What has been said to this person, and when — computed at drafting time, never trusted from
prose. Query or Citation, stage C1 (public #75, #79, #80).

⭐ THE CLAIM (design-query-or-citation.md §0)
-----------------------------------------------
Generated narrative may carry a fact about the pipeline in exactly two forms: a value the
engine computed as it wrote, or a pointer to the record that holds it. Never a sentence.
CLAUDE.md's rule — a fact a run knows goes into the queryable store, never into narrative — has
four shipped write-side instances (`act_by`, `precondition.py`, `journal.py`, `knowledge.py`).
This module is the READ side of the same rule: a fact a run STATES comes out of the queryable
store at the moment it states it.

## What this closes

  #75  a draft written without reading the thread                → `--for` / `--thread`
  #79  store silence read as "no history"                         → the evidence vocabulary (§4)
  #80  elapsed days and an echoed greeting trusted from draft time → `stale-brief` (§3.8)

## Who reads `data/briefs.jsonl` (§3.6) — enforced by `check_ledger_reads.py`

`--json` is a FRESH COMPUTATION, never a ledger read. The ledger has exactly three readers:
`brief.py --check` (by the id a draft CITES — never "newest for this person"),
`validate_data.py` (shape), `make_fixture.py` (generation). The ledger row is evidence of what
the drafter SAW; the journal + stores are the source of truth, checked again at every
`precondition.report()` — that recomputation is what lets a held draft promote to sendable with
no edit to the draft itself once a probe lands (design §5.2).

Usage:
    python3 brief.py --for contact:<id> [--opp <id> | --channel <id>]
    python3 brief.py --for contact:<id> --i-checked 2026-09-09     # owner attestation (§4.4)
    python3 brief.py --thread contact:<id>                         # read-only, no ledger write
    python3 brief.py --overlap "<draft entry title>"                # advisory, no ledger write
    python3 brief.py --check                                       # every open draft's verdict
    python3 brief.py --json --for contact:<id>
    python3 brief.py --probe contact:<id>                          # mailbox probe alone
    python3 brief.py --probe --held                                # probe/queue every held draft
    python3 brief.py --rebrief [--all]                             # bulk, store-only evidence

Python 3.9+. Standard library only.
"""

import argparse
import datetime
import json
import os
import re
import secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _root import profile_root
import _tree
import _localzone
import config_keys
import credentials
import deferred as _deferred
import graph as _graph
import inbox as _inbox
import journal as _journal
import mail_client
import posture as _posture
import precondition as _pre
import your_move as _ym
# ⭐ `reconcile` is imported LAZILY, inside `name_terms()` only — never at this module's top
# level. `reconcile.py` imports `validate_data`, whose module-level `OWNERS = {...,
# _profile.owner_token(), ...}` reads `user.json` UNCONDITIONALLY and raises if it is absent.
# `precondition.py` lazily imports THIS module for every draft entry it walks — including one
# that is `unaddressed` and returns from `verdict()` before ever needing a name term — and a
# profile-less precondition.py caller (several exist in the regression suite) must not crash
# merely because brief.py's import graph happened to reach validate_data's fragile top level.

LEDGER = os.path.join("data", "briefs.jsonl")

BRIEF_ID_RE = re.compile(
    r"^brief:(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2})-([0-9a-f]{4})$")

# The three readers this ledger has (§3.6) — `check_ledger_reads.py` enforces this allowlist
# against every OTHER shipped script's source, by AST, so the set here and the set that gate
# reads cannot drift into two different truths about who may open this file.
LEDGER_READERS = frozenset({"brief.py", "validate_data.py", "make_fixture.py"})

# The evidence vocabulary (§4.1). A code path may only ever PRODUCE one of these — never a
# variant spelling — because `register_for()` below pattern-matches the token's PREFIX and a
# new spelling would silently fall through to the least-trusting branch (unverified-cold),
# which is the safe direction but still a bug worth a name.
NONE_RECORDED = "none-recorded"
CONFIRMED_EMPTY = "confirmed-empty"
NOT_CONFIGURED = "not-configured"

# `**To:**` / `**Brief:**` — the two new draft meta lines (§3.4), same line-anchored discipline
# `precondition.FIELD_RE` already uses (`re.M`, column 1, the bold closing after the label).
TO_RE = re.compile(r"^\*\*To:\*\*\s*(.+?)\s*$", re.M | re.I)
BRIEF_LINE_RE = re.compile(r"^\*\*Brief:\*\*\s*(.+?)\s*$", re.M | re.I)
CONTACT_TOKEN_RE = re.compile(r"^contact:(.+)$")

UNADDRESSED = "unaddressed"
NONE_BRIEF = "none"

# The six new draft states, in three classes (§3.5). `precondition.py` folds these into its own
# `NEEDS_HUMAN` / `WAITS_ON_SURFACE` / `OPEN_STATES` sets — declared THERE (the single owner of
# sendability), imported here only for `verdict()`'s own return values to stay in that
# vocabulary rather than inventing a fourth spelling.
NEEDS_HUMAN_STATES = frozenset({"unaddressed", "unbriefed", "brief-mismatch", "stale-brief"})
WAITS_ON_SURFACE_STATES = frozenset({"unverified-cold", "unverified-silent"})


class BriefError(ValueError):
    """Unparseable or unresolvable. Loud on purpose — the precondition.py rule applied here."""


# ── the ledger — append-only, one reader allowlist, never sorted by time (§3.6, §3.9) ─────────

def _ledger_path(root):
    return os.path.join(root, LEDGER)


def append_ledger(root, rec):
    p = _ledger_path(root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True, ensure_ascii=False) + "\n")
    return rec


def read_ledger(root):
    out = []
    try:
        with open(_ledger_path(root), encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
    except (OSError, ValueError):
        pass
    return out


def ledger_row(root, brief_id):
    """The ONE row this id names, or None. §3.6/§3.9: never 'newest for a person' — always the
    CITED id, because two runs briefing one person at once each cite their own row."""
    for r in read_ledger(root):
        if r.get("id") == brief_id:
            return r
    return None


def _engine_version():
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(os.path.dirname(here), ".claude-plugin", "plugin.json"),
                  encoding="utf-8") as fh:
            return json.load(fh).get("version") or "0.0.0"
    except Exception:                                     # noqa: BLE001
        return "0.0.0"


def new_brief_id(now=None):
    """`brief:<offset-bearing ISO ts>-<4 hex>` (§3.3, D12). The offset comes from
    `_localzone.offset_for_local` — a NAIVE local timestamp orders wrongly across a DST
    fall-back pair, which is exactly the ordering bug `computed_at` must never reproduce."""
    now = now or datetime.datetime.now()
    offset_hours = _localzone.offset_for_local(now)
    tz = datetime.timezone(datetime.timedelta(hours=offset_hours))
    ts = now.replace(microsecond=0, tzinfo=tz).isoformat()
    return "brief:%s-%s" % (ts, secrets.token_hex(2))


# ── resolving `**To:**` / `**Brief:**` ─────────────────────────────────────────────────────────

def parse_to(body):
    """The raw `**To:**` value, or None if the line is absent entirely."""
    m = TO_RE.search(body or "")
    return m.group(1).strip() if m else None


def parse_brief_line(body):
    """The raw `**Brief:**` value, or None if the line is absent entirely."""
    m = BRIEF_LINE_RE.search(body or "")
    return m.group(1).strip() if m else None


def resolve_to(root, raw):
    """(person_id, ok, why) for a `**To:**` value. `ok=False` always means the state is
    `unaddressed` — the literal `unaddressed`, an unreadable token, or one that does not
    resolve in `people.jsonl` (D3)."""
    if raw is None:
        return None, False, "no **To:** line — a recipient must be identified"
    if raw == UNADDRESSED:
        return None, False, "stamped 'unaddressed' — needs a recipient"
    m = CONTACT_TOKEN_RE.match(raw)
    if not m:
        return None, False, "unreadable **To:** value %r — expected contact:<people-id>" % raw
    pid = m.group(1)
    g = _graph.Graph(os.path.join(root, "data"))
    try:
        person = g.resolve_person(pid)
    except _graph.MergeCycleError:
        return None, False, "merged_into cycle resolving contact:%s" % pid
    if person is None:
        return None, False, "contact:%s does not resolve to any people row" % pid
    return person["id"], True, ""


# ── §4.3: what the probe searches ──────────────────────────────────────────────────────────────

def address_set(root, person_id):
    """`people.email` ∪ every from/to address on a message row carrying this `person_id`
    (resolved through merge) — §4.3."""
    g = _graph.Graph(os.path.join(root, "data"))
    person = g.by_id["people"].get(person_id)
    addrs = set()
    if person and person.get("email"):
        addrs.add(person["email"])
    email_re = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")
    for m in g.messages_for_person(person_id):
        for field in ("from", "to"):
            val = m.get(field) or ""
            addrs.update(email_re.findall(val))
    return sorted(addrs)


def name_terms(root, person_id):
    """`reconcile.person_terms()`'s own derivation — the same one harvest uses (§4.3) — over a
    'Name (Company)'-shaped string built from the person's own record. `reconcile` is imported
    HERE, lazily — see the module-level note by this file's imports."""
    g = _graph.Graph(os.path.join(root, "data"))
    person = g.by_id["people"].get(person_id) or {}
    name = person.get("name") or ""
    if not name:
        return []
    company = g.by_id["companies"].get(person.get("company_id")) or {}
    to_field = "%s (%s)" % (name, company["name"]) if company.get("name") else name
    import reconcile as _reconcile
    _display, terms = _reconcile.person_terms(to_field)
    return terms


def _has_reachable_email_target(root, person_id):
    return bool(address_set(root, person_id) or name_terms(root, person_id))


# ── §4.2: the mailbox probe — a `probe` row with a `medium`, never a `swept` row (D1) ─────────

def run_email_probe(root, person_id, accounts=None):
    """The live mailbox probe for one person, across every configured account. NEVER calls
    `mail_client.sweep_accounts()` (D1: a per-person query as mailbox-wide coverage would poison
    `check_followups`'s silence assertion for every OTHER thread). Writes one `probe` row per
    REACHABLE account (a failed account writes NONE — the absent row is the honest state,
    §4.2); returns `[{"account", "state": "empty"|"hit"|"unreachable", "kind", "reason"}, ...]`
    for the caller (`--probe`'s disposition, `--for`'s brief) to read.

    Two passes per account (§4.3): the address set, then — only if the address pass is
    empty — the name-term set. An address-pass hit is `confirmed`; a name-pass-only hit is
    `candidate`, never `confirmed`, never `confirmed-empty` (§4.1).

    ⭐ C1 is the FIRST caller of `posture.py --may` in this plugin (§5.1) — a posture whose
    `unattended` list omits `sweeps` refuses before anything touches a mailbox, returning
    `not-permitted(<posture>)`. Every posture the plugin ships (the fixture's `minimal`
    included) permits `sweeps`; this exists for a user-defined posture that does not."""
    name, p, err = _posture.load()
    if not err and "sweeps" not in (p.get("unattended") or []):
        return [], "not-permitted(%s)" % name
    addresses = address_set(root, person_id)
    terms = name_terms(root, person_id)
    if not (addresses or terms):
        return [], NOT_CONFIGURED
    accounts = accounts if accounts is not None else mail_client.configured_accounts()
    if not accounts:
        return [], NOT_CONFIGURED
    out = []
    for account in accounts:
        if not credentials.has_credential(account):
            out.append({"account": account, "state": "unreachable",
                       "reason": "credential-missing"})
            continue
        try:
            with mail_client.Mailbox(account) as mb:
                addr_hits = []
                for term in addresses:
                    addr_hits.extend(mb.search(term))
                name_hits = []
                if not addr_hits:
                    for term in terms:
                        name_hits.extend(mb.search(term))
        except mail_client.CredentialError:
            out.append({"account": account, "state": "unreachable",
                       "reason": "credential-missing"})
            continue
        except Exception as e:                            # noqa: BLE001 — classified below
            out.append({"account": account, "state": "unreachable",
                       "reason": mail_client._classify_failure(
                           "%s: %s" % (type(e).__name__, e))})
            continue
        at = _journal.now_iso()
        thread = "contact:%s" % person_id
        if addr_hits:
            n = len(addr_hits)
            _journal.record_probe(root, thread, thread, "thread:%s" % at[:10],
                                  medium="email", mailbox=account, at=at)
            out.append({"account": account, "state": "hit", "kind": "confirmed", "n": n})
        elif name_hits:
            n = len(name_hits)
            _journal.record_probe(root, thread, thread, "thread:%s" % at[:10],
                                  medium="email", mailbox=account, at=at)
            out.append({"account": account, "state": "hit", "kind": "candidate", "n": n})
        else:
            _journal.record_probe(root, thread, thread, "empty",
                                  medium="email", mailbox=account, at=at)
            out.append({"account": account, "state": "empty"})
    return out, None


def record_owner_attestation(root, person_id, date_str):
    """`--i-checked <date>` (§4.4, owner decision 1) — refused when the person HAS a known
    EMAIL ADDRESS (the probe can run a precise, `confirmed`-grade search; the owner is not the
    sensor there), and refused for a future date.

    ⚠️ Deviation from the design's literal text (found building this): §4.4 says refuse when
    "an address OR NAME TERM exists" — but `reconcile.person_terms()` (§4.3's own derivation)
    returns at least the bare name for ANY non-empty `name` field, which every people.jsonl
    row has (schema-required). Read literally, that refusal condition never clears for a real
    person, which would make `--i-checked` permanently unusable — the opposite of what §4.4
    exists for. Narrowed here to an ADDRESS check only: a name-only search never yields better
    than `candidate` evidence (§4.1), so the owner's direct attestation is still the more
    reliable fact when no address is on file, even though a background name search could run
    without stopping anyone."""
    if address_set(root, person_id):
        raise BriefError(
            "--i-checked is refused for contact:%s — a known email address exists, so the "
            "probe can run a precise search. Use `brief.py --probe contact:%s` instead."
            % (person_id, person_id))
    try:
        d = datetime.date.fromisoformat(date_str)
    except ValueError:
        raise BriefError("--i-checked %r is not an ISO date (YYYY-MM-DD)" % date_str)
    if d > datetime.date.today():
        raise BriefError("--i-checked %s is in the future" % date_str)
    thread = "contact:%s" % person_id
    at = "%sT00:00:00%+03d:00" % (date_str, _localzone.offset_for_local(
        datetime.datetime.combine(d, datetime.time())))
    return _journal.record_probe(root, thread, thread, "empty", medium="email", mailbox=None,
                                 by="owner", at=at)


def evidence_from_journal(root, person_id, medium, recs=None):
    """The §4.1 evidence token for one medium, computed ONLY from what the journal already
    holds — never a live network call (that is `run_email_probe`'s job, called explicitly by
    `--for` / `--probe`). This is what `--check`, `--rebrief` and `verdict()` read, which is
    what makes the D2 promotion happen with no edit to the draft: the next read of THIS
    function sees whatever the laptop worker's probe just wrote."""
    recs = recs if recs is not None else _journal.read(root)
    thread = "contact:%s" % person_id
    rows = [r for r in recs if r.get("event") == "probe" and r.get("thread") == thread
           and r.get("medium") == medium]
    if not rows:
        if medium == "email" and (not _has_reachable_email_target(root, person_id)
                                  or not mail_client.configured_accounts()):
            return {"token": NOT_CONFIGURED, "probes": []}
        return {"token": NONE_RECORDED, "probes": []}

    owner_rows = [r for r in rows if r.get("by") == "owner"]
    if owner_rows:
        newest = max(owner_rows, key=lambda r: r.get("at") or "")
        if newest.get("result") == "empty":
            date = str(newest.get("at") or "")[:10]
            return {"token": "confirmed-empty(owner, %s)" % date, "probes": rows}

    if medium == "linkedin":
        newest = max(rows, key=lambda r: r.get("at") or "")
        result = str(newest.get("result") or "")
        if result.startswith("thread:"):
            return {"token": "confirmed 1 thread(s), latest %s" % result[len("thread:"):],
                    "probes": rows}
        return {"token": CONFIRMED_EMPTY, "probes": rows}

    # medium == "email": one row per account per probe run; fold to the NEWEST row per account.
    accounts = mail_client.configured_accounts()
    if not accounts:
        return {"token": NOT_CONFIGURED, "probes": rows}
    newest_by_account = {}
    for r in rows:
        acct = r.get("mailbox")
        if not acct:
            continue
        if acct not in newest_by_account or (r.get("at") or "") > (newest_by_account[acct].get("at") or ""):
            newest_by_account[acct] = r
    hits = [r for r in newest_by_account.values()
           if str(r.get("result") or "").startswith("thread:")]
    if hits:
        latest = max(str(r.get("result") or "")[len("thread:"):] for r in hits)
        return {"token": "confirmed %d thread(s), latest %s" % (len(hits), latest),
                "probes": rows}
    missing = [a for a in accounts if a not in newest_by_account]
    if missing:
        # Not every configured account has ever been asked — this is NOT the same fact as
        # "asked and found nothing" (CLAUDE.md's standing trap, applied to a per-account set).
        return {"token": NONE_RECORDED, "probes": rows}
    return {"token": CONFIRMED_EMPTY, "probes": rows}


# ── §3.7 register (a function of axis, age, evidence — brief.py's own composition) ────────────

def register_for(axis, elapsed_days, no_response_after_days, medium, evidence):
    """The closed register vocabulary (§3.7's table), never a second computation over
    different events — a function of the axis `your_move.conversation_axis()` already picked,
    the elapsed days at verified coverage (only meaningful for `silent`), and evidence (only
    meaningful for `nothing-sent`, and then only for the ONE medium the draft would use)."""
    if axis == "reply-owed":
        return "reply-owed"
    if axis == "accepted":
        return "accepted"
    if axis == "waiting":
        return "premature"
    if axis == "silence-unverified":
        return "unverified-silent"
    if axis == "silent":
        if elapsed_days is not None and elapsed_days >= no_response_after_days:
            return "reconnect"
        return "chase"
    if axis == "nothing-sent":
        med = "linkedin" if str(medium or "").startswith("linkedin") else "email"
        token = (evidence.get(med) or {}).get("token", NONE_RECORDED)
        return "cold" if str(token).startswith(CONFIRMED_EMPTY) else "unverified-cold"
    raise BriefError("axis %r is not in the closed vocabulary" % axis)


def _parse_date(s):
    return datetime.datetime.strptime(str(s)[:10], "%Y-%m-%d").date()


def _elapsed_for_silent(root, person_id, newest_outbound, today):
    medium = newest_outbound.get("medium") or "email"
    recs = _journal.read(root)
    thread = "contact:%s" % person_id
    verified_through = _journal.probe_covered_through(recs, thread, medium)
    sent_on = str(newest_outbound.get("date") or "")
    if verified_through and sent_on and str(verified_through) >= sent_on:
        return (_parse_date(verified_through) - _parse_date(sent_on)).days
    return None


def open_asks_for(root, person_id, opp_id=None, channel_id=None):
    """Open ask ids touching this person's pursuit/channel (§3.2). Asks join `opp_id`/
    `channel_id`, never a person directly, so scope is EITHER the caller's explicit
    `--opp`/`--channel`, or every pursuit/channel this person is involved in."""
    asks = _ym._load_jsonl(root, "asks.jsonl")
    open_rows = _ym.open_asks(asks)
    if opp_id or channel_id:
        return [a["id"] for a in open_rows
               if (opp_id and a.get("opp_id") == opp_id)
               or (channel_id and a.get("channel_id") == channel_id)]
    g = _graph.Graph(os.path.join(root, "data"))
    invs = g.involvements_for_person(person_id)
    opp_ids = {i["opp_id"] for i in invs if i.get("opp_id")}
    chan_ids = {i["channel_id"] for i in invs if i.get("channel_id")}
    return [a["id"] for a in open_rows
           if a.get("opp_id") in opp_ids or a.get("channel_id") in chan_ids]


def compute(root, person_id, opp_id=None, channel_id=None, today=None, medium=None):
    """The whole brief, as data — a fresh computation from stores + journal, never the ledger
    (§3.6). `medium` (a validate_data.MEDIA value, from the draft's own `**Medium:**` line)
    selects which medium's evidence decides a `nothing-sent` register; `--for`/`--json` with no
    draft in hand default it to `"email"` (§4's more fully specified path)."""
    today = today or datetime.date.today().isoformat()
    cfg = _config(root)
    chase_after_days, chase_prov = config_keys.describe(cfg, config_keys.CHASE_AFTER_DAYS)
    no_response_after_days, nr_prov = config_keys.describe(cfg, config_keys.NO_RESPONSE_AFTER_DAYS)

    counterpart = ("opp:%s" % opp_id) if opp_id else ("channel:%s" % channel_id) if channel_id else None
    axes = _ym.conversation_axis(root, person_id, counterpart=counterpart, today=today,
                                 window=chase_after_days)
    if opp_id or channel_id:
        tid = opp_id or channel_id
        axis, events = axes.get(tid, ("nothing-sent", []))
    elif axes:
        tid, (axis, events) = min(axes.items(),
                                  key=lambda kv: _ym.AXIS_FOLD.index(kv[1][0]))
        # The fold picked a thread id with no explicit scope — resolve whether it names an
        # opportunity or a channel so the ledger row (and the printed brief) carry it.
        g = _graph.Graph(os.path.join(root, "data"))
        if tid in g.by_id["opportunities"]:
            opp_id = tid
        elif tid in g.by_id["channels"]:
            channel_id = tid
    else:
        tid, axis, events = None, "nothing-sent", []

    inbound = [e for e in events if e["direction"] == "inbound"]
    outbound = [e for e in events if e["direction"] == "outbound"]
    latest_in = {"id": inbound[-1].get("id"), "date": inbound[-1].get("date")} if inbound else None
    latest_out = {"id": outbound[-1].get("id"), "date": outbound[-1].get("date")} if outbound else None

    elapsed = _elapsed_for_silent(root, person_id, outbound[-1], today) if (axis == "silent" and outbound) else None

    evidence = {"email": evidence_from_journal(root, person_id, "email"),
               "linkedin": evidence_from_journal(root, person_id, "linkedin")}
    register = register_for(axis, elapsed, no_response_after_days, medium or "email", evidence)

    return {
        "person_id": person_id, "opp_id": opp_id, "channel_id": channel_id, "thread": tid,
        "today": today, "axis": axis, "register": register,
        "last_word": "theirs" if inbound and (not outbound or inbound[-1]["date"] >= outbound[-1]["date"]) else "ours",
        "days_since_in": elapsed, "latest_in": latest_in, "latest_out": latest_out,
        "events": events, "evidence": evidence,
        "windows": {"chase_after_days": chase_after_days, "no_response_after_days": no_response_after_days,
                   "chase_after_days_provenance": chase_prov,
                   "no_response_after_days_provenance": nr_prov},
        "open_asks": open_asks_for(root, person_id, opp_id, channel_id),
        "engine": _engine_version(),
    }


def _config(root):
    try:
        with open(os.path.join(root, "config.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


# ── §4.6: store-behind-mailbox — a finding, not prose (D13) ────────────────────────────────────

def post_store_behind_mailbox(root, person_id, probe_results):
    """A deterministic finding, keyed so a re-probe never queues it twice (`inbox.replay()`
    keys on id). `probe_results` is `run_email_probe`'s own return: any `hit` means the mailbox
    holds something the store may not — this posts unconditionally on a hit (the harvest
    decides whether the store was actually behind; the finding is the queryable fact that a
    look is owed, which is all C1 promises, §4.6)."""
    hits = [r for r in probe_results if r.get("state") == "hit"]
    if not hits:
        return None
    total = sum(r.get("n", 0) for r in hits)
    latest = datetime.date.today().isoformat()
    fid = "store-behind-mailbox:%s:%s" % (person_id, latest)
    existing = {r.get("id") for r in _inbox.replay(_inbox.load()) if r.get("status") == "pending"}
    if fid in existing:
        return fid
    accounts = ", ".join(sorted({r["account"] for r in hits}))
    by = "; ".join("%s (%s)" % (r["account"], r.get("kind", "confirmed")) for r in hits)
    _inbox.append([{
        "id": fid, "kind": "store-behind-mailbox", "status": "pending",
        "summary": "store behind mailbox: contact:%s — %d thread(s), latest %s"
                   % (person_id, total, latest),
        "detail": "accounts: %s; by: %s; reconcile.py --harvest is owed" % (accounts, by),
        "urgency": "normal", "found_at": _journal.now_iso(),
    }])
    return fid


# ── §3.5/§5.2: draft states and the deferred-work bridge ───────────────────────────────────────

def _probe_result_class(result):
    r = str(result or "")
    if r == "empty":
        return "empty"
    if r.startswith("thread:"):
        return "thread"
    return "other"


def is_stale(root, row, today=None):
    """§3.8, D10 — staleness by DATA MOVEMENT ONLY, never clock age. `True` when the AXIS,
    `latest_in`/`latest_out` ids, or an open ask's resolution has moved since the cited row
    was computed, OR an ACCOUNT ALREADY PROBED at citation time now shows a probe of a
    DIFFERENT result class (empty ↔ thread:) for that same account.

    ⚠️ Register is NOT compared directly, and a probe landing where NONE existed before is
    NOT staleness — both deliberately (design §3.8's own words: 'a brief stales because the
    world MOVED, not because a day passed', and §5.2/D2: 'the verdict is recomputed... with
    no edit to the draft'). Register is a pure function of axis + age + evidence class; axis
    is checked directly, and a FRESH probe (nothing recorded -> something recorded) is new
    information, not a contradiction of what was cited — that is exactly the D2 promotion,
    and it must reach `verdict()`'s own register recomputation, never `stale-brief`. Only a
    probe that CONTRADICTS an already-cited result for the same account is staleness."""
    now = compute(root, row["person_id"], row.get("opp_id"), row.get("channel_id"), today=today)
    if now["axis"] != row.get("axis"):
        return True
    if (now["latest_in"] or {}).get("id") != (row.get("latest_in") or {}).get("id"):
        return True
    if (now["latest_out"] or {}).get("id") != (row.get("latest_out") or {}).get("id"):
        return True
    asks = _ym._load_jsonl(root, "asks.jsonl")
    by_id = {a["id"]: a for a in asks}
    for aid in row.get("open_asks") or []:
        a = by_id.get(aid)
        if a and a.get("resolved_on"):
            return True
    for medium in ("email", "linkedin"):
        old_probes = (row.get("evidence") or {}).get(medium, {}).get("probes") or []
        if not old_probes:
            continue          # nothing verified before — a fresh probe is new info, not a
                              # contradiction (this IS the D2 promotion path)
        new_probes = now["evidence"].get(medium, {}).get("probes") or []
        old_by_key = {(p.get("mailbox"), p.get("by")): p.get("result") for p in old_probes}
        new_by_key = {(p.get("mailbox"), p.get("by")): p.get("result") for p in new_probes}
        for key, old_result in old_by_key.items():
            new_result = new_by_key.get(key)
            if (new_result is not None
                    and _probe_result_class(new_result) != _probe_result_class(old_result)):
                return True
    return False


def verdict(root, title, body):
    """The brief-side draft state, or `None` when the brief has nothing to say (the entry
    falls through to `precondition.py`'s own `**Blocked until:**` logic). Six states, three
    classes (§3.5) — `precondition.py` imports this the way `trigger.py` imports the
    precondition verdict; `precondition.py` stays the single owner of sendability."""
    to_raw = parse_to(body)
    pid, ok, why = resolve_to(root, to_raw)
    if not ok:
        return "unaddressed", why
    brief_raw = parse_brief_line(body)
    if brief_raw is None or brief_raw == NONE_BRIEF:
        return "unbriefed", "drafted without reading the thread — brief.py --rebrief"
    if not BRIEF_ID_RE.match(brief_raw):
        return "unbriefed", "cited brief %r is not a recognised id" % brief_raw
    row = ledger_row(root, brief_raw)
    if row is None:
        return "unbriefed", "cited brief %r is absent from the ledger" % brief_raw
    if row.get("person_id") != pid:
        return "brief-mismatch", "cites a brief for someone else"
    if is_stale(root, row):
        return "stale-brief", "they wrote since this was drafted — rebrief; if the register moved, redraft"
    # The register hold (WAITS_ON_SURFACE) is about a COLD or CHASE draft going out unverified
    # — it does not apply to an entry ALREADY gated on its own `**Blocked until:**` join, which
    # is a different, already-communicated sequence's outcome, not a fresh send. An entry with
    # no structured hold field at all is exactly the case the register exists to protect.
    if _pre.FIELD_RE.search(body):
        return None
    medium = _pre.medium_of(body)
    now = compute(root, pid, row.get("opp_id"), row.get("channel_id"), medium=medium)
    if now["register"] == "unverified-cold":
        return "unverified-cold", "cold register unverified — mailbox not checked on this surface"
    if now["register"] == "unverified-silent":
        return "unverified-silent", "silence unverified — a sweep must cover this thread first"
    return None


# ── §5.2: the deferred queue's own `what` and disposition ──────────────────────────────────────

def probe_disposition(probe_results):
    """(exit_code, message) for `--probe`'s own per-account rule (D2): every account
    `confirmed-empty`/`confirmed` -> 0, `--done`; any `unreachable`/`not-permitted`/
    `not-configured` -> 2, `--release`."""
    if not probe_results:
        return 2, "not-configured — no address, name term, or mailbox to search"
    bad = [r for r in probe_results if r.get("state") == "unreachable"]
    if bad:
        reasons = ", ".join("%s: %s" % (r["account"], r["reason"]) for r in bad)
        return 2, "%d account(s) unreachable (%s) — deferred.py --release" % (len(bad), reasons)
    return 0, "every account confirmed — deferred.py --done"


def queue_probe_if_needed(root, person_id):
    """`--probe --held`'s per-person queue write, on a surface without a keychain (§5.2, D2):
    the `what` is the LITERAL command, deduplicated against any already-pending row with the
    same `what` — a second hold for the same person never queues a second item."""
    what = "brief.py --probe contact:%s" % person_id
    rows = _deferred.replay(_deferred.load())
    if any(r.get("what") == what and r.get("status") == "pending" for r in rows):
        return None
    return _deferred.queue_item(what, why="cold register unverified — mailbox not checked here",
                                requires=("keychain",))


# ── printing (§3.2) ─────────────────────────────────────────────────────────────────────────

def _fmt_windows(w):
    return ("windows: chase %s (%s) · reconnect %s (%s)"
           % (w["chase_after_days"], w["chase_after_days_provenance"],
              w["no_response_after_days"], w["no_response_after_days_provenance"]))


def print_brief(brief_id, b):
    print("BRIEF  %-45s computed %s" % (brief_id, b["today"]))
    print("person    contact:%-25s opp: %-20s channel: %s"
         % (b["person_id"], b.get("opp_id") or "—", b.get("channel_id") or "—"))
    print()
    print("axis      %-12s thread %s" % (b["axis"].upper(), b.get("thread") or "—"))
    print("register  %-12s last word: %s" % (b["register"].upper(), b["last_word"]))
    print("          %s" % _fmt_windows(b["windows"]))
    print()
    for medium in ("email", "linkedin"):
        ev = b["evidence"].get(medium, {})
        print("evidence  %-9s %s" % (medium, ev.get("token", NONE_RECORDED)))
    print()
    if b["latest_in"]:
        print("latest inbound   %s (%s)" % (b["latest_in"].get("date"), b["latest_in"].get("id") or "no message row"))
    if b["latest_out"]:
        print("latest outbound  %s (%s)" % (b["latest_out"].get("date"), b["latest_out"].get("id") or "no message row"))
    if b["open_asks"]:
        print("open asks        %s" % ", ".join(b["open_asks"]))
    print()


# ── mainline commands ───────────────────────────────────────────────────────────────────────

def cmd_for(root, person_token, opp_id, channel_id, i_checked, as_json, stamp=True):
    pid, ok, why = resolve_to(root, person_token)
    if not ok:
        raise BriefError(why)
    if i_checked:
        record_owner_attestation(root, pid, i_checked)
    else:
        results, refusal = run_email_probe(root, pid)
        if refusal is None:
            post_store_behind_mailbox(root, pid, results)
    b = compute(root, pid, opp_id, channel_id)
    if as_json:
        print(json.dumps(b, indent=1))
        return 0
    brief_id = new_brief_id()
    row = dict(b)
    row["id"] = brief_id
    row["computed_at"] = brief_id.split("brief:", 1)[1].rsplit("-", 1)[0]
    del row["events"]
    append_ledger(root, row)
    print_brief(brief_id, b)
    print(brief_id)
    return 0


def cmd_json_for(root, person_token, opp_id, channel_id):
    pid, ok, why = resolve_to(root, person_token)
    if not ok:
        raise BriefError(why)
    b = compute(root, pid, opp_id, channel_id)
    print(json.dumps(b, indent=1))
    return 0


def cmd_thread(root, person_token):
    pid, ok, why = resolve_to(root, person_token)
    if not ok:
        raise BriefError(why)
    axes = _ym.conversation_axis(root, pid)
    if not axes:
        print("No thread found for contact:%s." % pid)
        return 0
    for tid, (axis, events) in axes.items():
        print("THREAD %s  (axis: %s)" % (tid, axis))
        for e in events:
            print("  %-10s %-8s %s" % (e.get("date"), e["direction"], e.get("id") or e.get("source")))
        print()
    return 0


def cmd_probe(root, person_token):
    pid, ok, why = resolve_to(root, person_token)
    if not ok:
        raise BriefError(why)
    results, refusal = run_email_probe(root, pid)
    if refusal:
        print("PROBE  contact:%s — %s" % (pid, refusal))
        return 2
    post_store_behind_mailbox(root, pid, results)
    ev = evidence_from_journal(root, pid, "email")
    code, msg = probe_disposition(results)
    print("PROBE  contact:%s — %s" % (pid, ev["token"]))
    print("       %s" % msg)
    return code


def cmd_probe_held(root):
    """§3.1/§5.2, daily-run §2c — probe (or queue) every draft currently `unverified-cold`.
    Re-derives holds through `verdict()`, the same function `precondition.py` uses, over every
    OPEN entry — never a private re-implementation of the states."""
    held_people = set()
    for filename in _pre.FILES:
        path = _tree.resolve_rel(root, filename)
        try:
            with open(path, encoding="utf-8") as fh:
                md = fh.read()
        except OSError:
            continue
        for m in _pre.ENTRY_RE.finditer(md):
            body = m.group(2)
            v = verdict(root, m.group(1).strip(), body)
            if v and v[0] in WAITS_ON_SURFACE_STATES and v[0] == "unverified-cold":
                to_raw = parse_to(body)
                pid, ok, _why = resolve_to(root, to_raw)
                if ok:
                    held_people.add(pid)
    if not held_people:
        print("No held drafts to probe.")
        return 0
    probed, queued = 0, 0
    for pid in sorted(held_people):
        addresses = address_set(root, pid)
        terms = name_terms(root, pid)
        if not (addresses or terms):
            continue
        accounts = mail_client.configured_accounts()
        reachable = accounts and all(credentials.has_credential(a) for a in accounts)
        if reachable:
            results, refusal = run_email_probe(root, pid)
            if refusal is None:
                post_store_behind_mailbox(root, pid, results)
                probed += 1
        else:
            if queue_probe_if_needed(root, pid):
                queued += 1
    print("Probed %d held draft(s) directly, queued %d for a keychain-holding session."
         % (probed, queued))
    return 0


# Register classes a re-run may quietly REPLACE a citation for — a probe landing after a
# hold (D2's promotion) is an IMPROVEMENT, never a "the world moved, look again" surprise.
_UNVERIFIED_REGISTERS = frozenset({"unverified-cold", "unverified-silent"})


def rebrief(root, probe=False, only_all=False):
    """§3.1/§7 — bulk, STORE-ONLY BY DEFAULT (`probe=False`; migration always calls it this
    way, since it runs on any surface, attended or not — §7 step 3).

    `only_all=False` (the default, and what the migration's bulk pass uses): rebriefs ONLY
    entries whose `**Brief:**` line is missing or the literal `none` — an already-current
    citation is left untouched, which is what makes a migration re-run genuinely idempotent
    (§7's own claim) rather than minting a fresh id for every open entry on every run.
    `only_all=True` (the CLI's `--all`): also revisits ALREADY-briefed entries, rewriting the
    line when the register is unchanged or has moved OUT of an unverified hold (a probe just
    landed — D2), and leaving it loud as `stale-brief` when the register moved to something
    else (§3.8 — a human should see that, not have it silently swept under a new citation).

    Returns `{"rebriefed": N, "path": <drafts.md path or None>}` — a pure-ish function
    (writes the ledger and, when it has something to insert, the drafts file) that both the
    CLI (`cmd_rebrief`) and `migrate.py`'s `m_0_46_0_brief_line` call, so there is exactly one
    bulk-rebrief implementation."""
    path = _tree.resolve_rel(root, _pre.FILES[0])
    try:
        with open(path, encoding="utf-8") as fh:
            md = fh.read()
    except OSError:
        return {"rebriefed": 0, "path": None}
    inserts = []
    rebriefed = 0
    for m in _pre.ENTRY_RE.finditer(md):
        body = m.group(2)
        to_raw = parse_to(body)
        pid, ok, _why = resolve_to(root, to_raw)
        if not ok:
            continue
        old_brief_raw = parse_brief_line(body)
        old_row = (ledger_row(root, old_brief_raw)
                  if old_brief_raw and old_brief_raw != NONE_BRIEF else None)
        if old_row is not None and not only_all:
            continue          # already briefed, and this pass only catches up the unbriefed
        b = compute(root, pid, medium=_pre.medium_of(body))
        if old_row is not None:
            old_reg, new_reg = old_row.get("register"), b["register"]
            improved = old_reg in _UNVERIFIED_REGISTERS and new_reg not in _UNVERIFIED_REGISTERS
            if new_reg != old_reg and not improved:
                continue      # register MOVED to something else — leave stale-brief loud
        brief_id = new_brief_id()
        row = dict(b)
        row["id"] = brief_id
        row["computed_at"] = brief_id.split("brief:", 1)[1].rsplit("-", 1)[0]
        del row["events"]
        append_ledger(root, row)
        rebriefed += 1
        bm = BRIEF_LINE_RE.search(body)
        if bm:
            start, end = m.start(2) + bm.start(), m.start(2) + bm.end()
            inserts.append((start, end, "**Brief:** %s" % brief_id))
        else:
            inserts.append((m.end(2), m.end(2), "\n**Brief:** %s" % brief_id))
    if inserts:
        new_md = md
        for start, end, text in sorted(inserts, key=lambda t: t[0], reverse=True):
            new_md = new_md[:start] + text + new_md[end:]
        import _atomic
        _atomic.write_text(path, new_md)
    return {"rebriefed": rebriefed, "path": path}


def cmd_rebrief(root, only_all):
    result = rebrief(root, probe=False, only_all=only_all)
    print("%d draft(s) rebriefed." % result["rebriefed"])
    return 0


def _shingles(text, n):
    words = re.findall(r"[a-z0-9']+", str(text or "").lower())
    return [tuple(words[i:i + n]) for i in range(len(words) - n + 1)]


def cmd_overlap(root, title):
    """§3.1 — advisory only, no ledger write. Compares the draft's body against every other
    outbound body to the SAME person (signature stripped, best-effort) for the longest shared
    8-word run (`config_keys.FIXED["overlap_shingle_words"]`), and names its source."""
    n = config_keys.FIXED["overlap_shingle_words"]
    body = None
    to_raw = None
    for filename in _pre.FILES:
        path = _tree.resolve_rel(root, filename)
        try:
            with open(path, encoding="utf-8") as fh:
                md = fh.read()
        except OSError:
            continue
        for m in _pre.ENTRY_RE.finditer(md):
            if m.group(1).strip() == title:
                body = m.group(2)
                to_raw = parse_to(body)
                break
        if body is not None:
            break
    if body is None:
        raise BriefError("no draft entry titled %r" % title)
    pid, ok, why = resolve_to(root, to_raw)
    if not ok:
        raise BriefError("cannot compare — %s" % why)
    try:
        import profile as _profile
        sig = _profile.email_signature()
    except Exception:                                     # noqa: BLE001 — advisory only
        sig = ""
    draft_body = body.replace(sig, "") if sig else body
    draft_shingles = set(_shingles(draft_body, n))
    axes = _ym.conversation_axis(root, pid)
    best = (0, None, None)
    for tid, (_axis, events) in axes.items():
        for e in events:
            if e["direction"] != "outbound":
                continue
            src_body = e.get("body") or ""
            shared = draft_shingles & set(_shingles(src_body, n))
            if len(shared) > best[0]:
                best = (len(shared), next(iter(shared)), e.get("id") or ("%s@%s" % (tid, e.get("date"))))
    if best[0] == 0:
        print("No shared %d-word run found against this person's prior outbound messages." % n)
        return 0
    print("Longest shared run (%d words): %s" % (n, " ".join(best[1])))
    print("Source: %s" % best[2])
    print("A repeated fact is sometimes a deliberate reminder — advisory only.")
    return 0


def cmd_check(root):
    """§3.1 — every open draft's brief verdict, recomputed from stores + journal NOW
    (`precondition.report()`, the single owner of sendability — never a second walk here).
    Exit 1 on any `NEEDS_HUMAN` state; a `WAITS_ON_SURFACE` row is counted, never a red close
    (§3.5: 'a WAITS_ON_SURFACE draft is not a red close, or every application-session close on
    S4/S5 is red forever')."""
    rows = _pre.report(root)
    counts = {}
    exit_code = 0
    for r in rows:
        if r.get("file") != _pre.FILES[0]:
            continue
        counts[r["state"]] = counts.get(r["state"], 0) + 1
        if r["state"] in NEEDS_HUMAN_STATES:
            print("⛔ %s [%s]: %s" % (r["title"][:60], r["state"], r["why"]), file=sys.stderr)
            exit_code = 1
    print("BRIEF CHECK — %s" % ", ".join("%s: %d" % (k, v) for k, v in sorted(counts.items())))
    return exit_code


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--for", dest="for_", metavar="contact:<id>")
    ap.add_argument("--opp", metavar="ID")
    ap.add_argument("--channel", metavar="ID")
    ap.add_argument("--i-checked", dest="i_checked", metavar="DATE")
    ap.add_argument("--thread", metavar="contact:<id>")
    ap.add_argument("--overlap", metavar="TITLE")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--probe", metavar="contact:<id>")
    ap.add_argument("--held", action="store_true")
    ap.add_argument("--rebrief", action="store_true")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    root = profile_root()
    try:
        if args.probe and args.held:
            return cmd_probe_held(root)
        if args.probe:
            return cmd_probe(root, args.probe)
        if args.rebrief:
            return cmd_rebrief(root, args.all)
        if args.check:
            return cmd_check(root)
        if args.thread:
            return cmd_thread(root, args.thread)
        if args.overlap:
            return cmd_overlap(root, args.overlap)
        if args.for_:
            if args.json:
                return cmd_json_for(root, args.for_, args.opp, args.channel)
            return cmd_for(root, args.for_, args.opp, args.channel, args.i_checked, args.json)
        ap.error("one of --for / --thread / --overlap / --check / --probe / --rebrief is required")
    except BriefError as e:
        print("⛔ %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
