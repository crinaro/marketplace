#!/usr/bin/env python3
"""
THE WRITE API for the mutable data files — one code path, a lock held in milliseconds.

WHY THIS EXISTS
---------------
The candidate, 2026-08-04: *"do we have the locks on the appropriate items? … if we had processes
that are reused (atomic) that will make sense but the challenge is a process putting something on
the queue for another."*

The candidate was right, and an audit made the reason precise. The repo already runs **two** concurrency
strategies and they were mixed up:

    APPEND + REPLAY   data/inbox.jsonl · data/pending_actions.jsonl · messages.jsonl
                      Lock-free BY DESIGN. Two workers append at once and replay resolves it.
                      **These have never conflicted.** The queue hand-off the candidate worried
                      about is the part that already works.

    WHOLE-FILE REWRITE  opportunities.jsonl (167 rows) · companies.jsonl · channels.jsonl
                      Every mutation was an AD-HOC `read all → mutate → write all`, invented
                      fresh by whatever session happened to be editing. **There was no write
                      API at all.**

**That is why the lock had to be coarse.** You cannot make a file safe when any session may
rewrite it however it likes; the only defence left is a global mutex held across the whole
edit. So the lock grew to cover a verify-and-write cycle lasting minutes, and the observed cost
was four false-RED gate sweeps in a single afternoon plus a duplicated LinkedIn record.

**This collapses the window.** One code path takes the lock, reads, mutates, writes atomically,
and releases — milliseconds, not minutes. The lock stops being a convention that every session
must remember and becomes correct by construction.

## ⭐ THE WRITE IS ATOMIC, AND THAT IS NOT DECORATION

Writes go to a temp file in the same directory and are `os.replace`d into place, which is atomic
on POSIX. A partial write to `opportunities.jsonl` would corrupt **167 records** — the entire
pipeline — and the old ad-hoc pattern (`open(p,'w')` then loop) had exactly that failure mode if
a session died mid-loop. Nothing recovers that but a git checkout.

## What it does NOT solve, stated plainly

Two workers editing the **same record** still serialise. This shrinks the contention window; it
does not make concurrent edits to one row commutative. If that turns out to happen in practice,
the answer is journaling the store the way the queues are journaled — but that is a data-model
migration and should wait for evidence, not a guess.

## ⭐ CALLING THIS MID-RUN: `--already-locked` (public #17 / dev #97)

The daily run takes the run lock itself at the top of its write phase and releases after the
commit. Called inside that window, this script used to try to take the same lock AGAIN — and
since the holder was the caller's own run, it waited out the full timeout for a release that
could never come. The observed result was the exact failure this API exists to prevent:
sessions gave up and hand-edited the JSONL.

So the contract is now explicit, and it does not touch the two-strategy design above:

    OUTSIDE a lock-holding run   plain call — takes the lock, writes, releases (milliseconds).
    INSIDE the run's write phase pass `--already-locked` — the write proceeds under the RUN's
                                 hold; nothing here takes or releases. Verified, not trusted:
                                 if nobody actually holds the lock the call is REFUSED, because
                                 a caller claiming a hold that does not exist is writing
                                 unprotected by accident.

A refused take now also diagnoses the self-deadlock instead of leaving a silent wait: the
default `--wait` is seconds (holders release in seconds by design), and the refusal says when
`--already-locked` is the answer.

## ⭐ COMPLETING AN ACTION RESOLVES ITS ASK, IN THE SAME WRITE (dev #133 / public #22)

An ask in data/asks.jsonl that carries `resolves_when` ("application" | "outreach") plus
`opp_id` has declared which recorded action answers it. When this API lands that action on that
opportunity, the ask is resolved under the same lock hold — one transaction, no drift window.
Asks without the declaration are never touched (guessing closes still-needed questions);
check_action_claims.py remains the detection backstop for them.

Usage:
    python3 scripts/record.py create <opp_id> '{"company_id":"...","title":"...", ...}'
    python3 scripts/record.py create <opp_id> '{...}' --from-item <capture-role item id>
                                              # + the sweep's parsed pay, posted, setting
    python3 scripts/record.py set <opp_id> stage screening
    python3 scripts/record.py set <opp_id> next_action_owner <candidate>   # e.g. your own name, lowercased
    python3 scripts/record.py set-in <opp_id> outreach contact_id=jane-doe outcome replied
    python3 scripts/record.py append <opp_id> research_log '{"date":"2026-08-04","note":"..."}'
    python3 scripts/record.py show <opp_id>
    python3 scripts/record.py screened <opp_id>            # store the minimal screen it computes
    python3 scripts/record.py lean <opp_id> --lean pursue|pass|ask --line "<one line>" [--jd-file P]
    python3 scripts/record.py listed-pay <opp_id> --none-shown | --stated R[;R] | --estimate R[;R]
    python3 scripts/record.py posted <opp_id> --document-date D | --shown-age N | --ats-date D | --unknown
    python3 scripts/record.py board-sighting <channel_id> --company "<name>" --title "<title>" --url <posting URL>
                                              # one role seen on a job board (dev #765): the company is matched or
                                              # created, the role created or given a sighting, in ONE write
    python3 scripts/record.py channel-catalog add <entry> | --kind portfolio|curated|swept-board|alert-sender [--attach <channel_id>]
    python3 scripts/record.py channel-catalog take|keep <channel_id>
    python3 scripts/record.py source on|off <id> [--anyway]      # turn ANY job source on or off (dev #774): a board, an
    python3 scripts/record.py source list | keep-mine <id>       # alert sender, the LinkedIn job search, `company-feeds`
                                              # turn shipped catalog boards on (nothing is on by default), and settle
                                              # a board you edited that the catalog also changed (dev #769)
    ... --file companies|channels to address the other stores. --dry-run to preview.
    ... --already-locked when the calling run already holds the run lock (see above).

Python 3.9+. Standard library only.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import os, sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _root import profile_root as _profile_root, looks_like_profile as _looks_like_profile
ENGINE_SCRIPTS = os.path.dirname(os.path.realpath(__file__))

# design-inbound-resolution.md §2 amendment D4 (surface pass 2026-09-14) — the same code
# `binding.py` uses (`EXIT_NO_PROFILE = 3`). Measured: on S6 (claude.ai/Home) or any surface
# with no resolvable profile, `ROOT` falls to the CWD (`_root.py`'s own fallthrough) and every
# store load then raised a bare FileNotFoundError — a traceback, not a refusal naming the
# actual problem. record.py now asserts a profile before ANY verb touches a store.
EXIT_NO_PROFILE = 3

ROOT = _profile_root()
DATA = os.path.join(ROOT, "data")
STORES = {"opportunities": "opportunities.jsonl",
          "companies": "companies.jsonl",
          "channels": "channels.jsonl",
          # ADR-031 B2 — the two promoted top-level stores. `create auto '{"opp_id": ...}'
          # --file applications` mints the id (see the create branch below); `cover_letters`
          # takes an explicit id like any other store.
          "applications": "applications.jsonl",
          "cover_letters": "cover_letters.jsonl",
          # ADR-031 B3 — the third promoted top-level store. `create auto
          # '{"person_id": ...}' --file touches` mints the id (see the create branch below,
          # `<person_id>-tN` — design §1: a touch is owned by the PERSON, not the opportunity).
          "touches": "touches.jsonl",
          # ADR-031 B1 — the `people` store (public #93). Only `people` joins here, never
          # `involvements`: `involvements` has no `id` field of its own (design §1 — "the pair
          # (person_id, opp_id|channel_id) IS the identity"), so it does not fit this generic
          # id-keyed single-record API at all; nothing needs it to yet (`merge-person` below
          # only ever touches the `people` row itself, per ADR-031 §3's "a merge is a pointer,
          # never a rewrite" — every involvement keeps naming the absorbed id and resolves
          # through it at READ time via `graph.Graph.resolve_person`).
          "people": "people.jsonl",
          # ADR-031 B4 — the strategy stores. `plans`/`plays` both take an explicit id like
          # any other store (no auto-minting — a plan/play id is chosen, not counted).
          "plans": "plans.jsonl",
          "plays": "plays.jsonl",
          # States & Views V1b (design §15.3) — `messages` joins STORES, APPEND-ONLY: a
          # message row is immutable once written (its id is what every other row links to).
          # `set`/`set-in`/`append`/`create`/`show` on `--file messages` are refused in main()
          # before any of the generic single-store machinery runs — `answered`/`touched` and
          # (design-inbound-resolution.md §2) `received` are the only verbs that write it (see
          # MESSAGES_WRITE_VERBS below).
          "messages": "messages.jsonl",
          # design-inbound-resolution.md §2 — `asks` joins STORES (the `cover_letters`
          # precedent: an explicit id, no auto-minting). Before this an ask could only ever be
          # APPENDED by `migrate.py`; `create <id> '<json>' --file asks` / `set-in` / `append`
          # (e.g. a `note` addendum — §4.4's dedup digest) now exist, validator-run like every
          # other store.
          "asks": "asks.jsonl"}
# ⭐ dev #764 / public #162 -- THE STORES `create auto` CAN MINT AN ID FOR, and the label the
# write's report uses for the id it minted. `create auto` on any other store used to write the
# literal id "auto" (the argument was taken as the id) -- a row no later verb could tell from a
# real one, and a `cover_letter_id` pointing at it. A store absent from this table has no minting
# branch, so `create auto` on it is REFUSED before anything is written (see the create branch).
AUTO_MINT_LABEL = {"applications": "app_id", "touches": "touch id",
                   "cover_letters": "cover letter id"}
# The only ops allowed to touch `--file messages` — everything else is refused in main().
# design-inbound-resolution.md §2 — `received` joins `touched`/`answered`: the one public
# INBOUND writer (ADR-029), promoted from `reconcile.py --harvest`'s own private append.
MESSAGES_WRITE_VERBS = frozenset({"touched", "answered", "received"})
# ⭐ public #103 — THE SINGLE SOURCE for every verb this CLI has. main()'s parser is built
# from this tuple (never a second hand-typed list), and so is
# TestPublic103RecordDryRunNeverWrites.test_every_verb_dry_run_leaves_every_store_byte_identical
# in test_checks.py: a verb added here without a --dry-run mapping in that test fails LOUDLY
# instead of silently shipping a write-capable verb nobody proved honours --dry-run — which
# is exactly how `answered`/`touched` went unnoticed (they were added as their own
# early-return branches in main(), before the shared dry-run gate near the bottom of main()
# ever runs for them). `received` (design-inbound-resolution.md §2) joins the tuple for the
# identical reason — it is its own early-return branch too, and must prove --dry-run the
# same way.
OPS = ("create", "set", "set-in", "append", "show", "fields",
       "decide", "application-status", "networking-closed",
       "answered", "touched", "received", "merge-person",
       # dev #686 / public #139 (E2) — link a person to an opportunity later, as an explicit
       # act. An early-return verb like touched/answered/received: --dry-run proven in
       # test_record.py's VERB_ARGS.
       "involve",
       # jobsearch 0.67.0 (dev #713-#716 / public #142-#145) -- the four SOURCING-SCREEN verbs. Each
       # writes one top-level field of ONE opportunity through the ordinary lock / validate /
       # rollback path below (they are branches of the shared mutation chain, not early returns),
       # and each stores what a SCRIPT computed -- never a value a model typed in:
       # `screened` re-runs profile.screen_rules; `lean` runs the signal matcher; `listed-pay`
       # parses the pay-slot grammar; `posted` computes a board-relative date from a shown age.
       "screened", "lean", "listed-pay", "posted",
       # jobsearch 0.70.0 (dev #728 / public #158) -- fold a duplicate row into its canonical one,
       # and undo a false merge. Both are branches of the shared mutation chain (one locked write
       # touching two rows of ONE store), so --dry-run, the validator and the rollback all apply.
       "link-sibling", "unlink-sibling",
       # jobsearch 0.72.0 (dev #751, sourcing-feeds) -- the company-feed verbs. Early-return verbs
       # like `involve`: each writes the COMPANIES store (and `ats` also the CHANNELS store, in one
       # locked, validated, rollback-verified transaction), so --dry-run is proven in test_record.py.
       "ats", "warm-lookup",
       # jobsearch 0.75.0 (dev #765) -- record ONE role seen on a job board. An early-return verb writing
       # COMPANIES (when it creates one) and OPPORTUNITIES in one locked, validated, rollback-verified
       # transaction, so --dry-run is proven in test_record.py.
       "board-sighting",
       # jobsearch 0.76.0 (dev #769) -- turn shipped channel-catalog boards on (`add`) and settle a
       # disagreement with the catalog (`take` / `keep`). An early-return verb writing CHANNELS (and
       # COMPANIES / ASKS when they change) in one locked, validated, rollback-verified transaction, so
       # --dry-run is proven in test_record.py.
       "channel-catalog",
       # jobsearch 0.76.0 (dev #774) -- turn any job source on or off (`source on|off`), list them (`list`) and
       # resolve an adoption question (`keep-mine`). An early-return verb writing CHANNELS (and COMPANIES / ASKS /
       # config.json when they change) in one locked, validated, rollback-verified transaction, so --dry-run is
       # proven in test_record_source.py.
       "source")
SOURCING_OPS = ("screened", "lean", "listed-pay", "posted")
LOCK = os.path.join(ENGINE_SCRIPTS, "runlock.py")
# ⭐ ENGINE, not profile — the data MODEL ships with the code; the DATA belongs to the user.
MODEL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))),
                          "docs", "data_model.json")


def model():
    """⭐ THE DEFINITION THE API ENFORCES — docs/data_model.json.

    Added 2026-08-04, after the candidate asked whether the API needed definitions, whether keys
    were guarded against duplicates, and whether any of it was enforced. All three were NO:
    `record.py set <id> nxet_action_owner <candidate>` wrote silently and the validator reported
    **clean**, because only outreach[] had an unknown-key guard. Three guessed contact_ids landed
    the same day.

    Validating AFTER the write was never enough. A typo is already on disk by then, and
    validate_data cannot know that `nxet_action_owner` was meant to be `next_action_owner` — to
    it, an unguarded store simply has a new field.
    """
    with open(MODEL_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def known_fields(store, array=None):
    m = model()["stores"].get(store) or {}
    if array:
        return set((m.get("arrays", {}).get(array) or {}).get("fields") or [])
    return set(m.get("fields") or [])


def check_field(store, field, array=None):
    """Returns None if fine, else the reason to refuse. Refusing BEFORE the write is the point."""
    aliases = model()["banned_aliases"]
    if field in aliases and not field.startswith("_"):
        return ("%r is a BANNED ALIAS for %r. The same meaning under two spellings means a query "
                "written against one silently misses the other." % (field, aliases[field]))
    allowed = known_fields(store, array)
    if allowed and field not in allowed:
        near = [f for f in allowed if abs(len(f) - len(field)) <= 2
                and sum(a != b for a, b in zip(sorted(f), sorted(field))) <= 3]
        hint = ("  Did you mean: %s" % ", ".join(sorted(near)[:3])) if near else ""
        where = "%s[]" % array if array else store
        return ("%r is not a field of %s.%s\n  Known: %s" %
                (field, where, hint, ", ".join(sorted(allowed))))
    return None


def sighting_source_url_problem(sighting, channel_type_by_id, referenced_channel_ids, receipted):
    """public #83 rule 1 — refuse a NEW sighting from a URL-bearing channel (job-board/
    aggregator — `validate_data.URL_BEARING_CHANNEL_TYPES`, imported rather than re-typed, the
    same set doctor.py's run-start advisory (#360) reads) with no source_url, AT THE MOMENT IT
    IS CAPTURED. The link is free right now and effectively unrecoverable once the posting
    comes down — making it optional guaranteed it was sometimes dropped (public #83's own
    finding). Returns None if the sighting is fine to write, else the reason to refuse.

    The SAME two exclusions the run-start advisory computes (never re-typed, only re-derived
    from data this caller already has, since the advisory works from a whole record after the
    fact and this works from one sighting before it is written):

      1. recruiter-sourced — `referenced_channel_ids` (the record's own channel_id plus every
         sighting already on it, plus this new one) resolves ANY channel of type 'recruiter'.
         There was never a public posting to link, regardless of this sighting's own channel.
      2. receipt-backed — `receipted` is True when an applications.jsonl row for this
         opportunity already carries a status in validate_data.SUBMITTED_APP_STATUS. The
         application itself is durable evidence the role existed.

    A channel type outside URL_BEARING_CHANNEL_TYPES (recruiter/referral/company-site/
    alert-email) is never in scope at all — it never carried a public URL to lose.
    """
    if sighting.get("source_url"):
        return None
    _vd = _validator_module()
    ctype = channel_type_by_id.get(sighting.get("channel_id"))
    if ctype not in _vd.URL_BEARING_CHANNEL_TYPES:
        return None
    if any(channel_type_by_id.get(cid) == "recruiter"
           for cid in referenced_channel_ids if cid):
        return None    # 1. recruiter-sourced
    if receipted:
        return None    # 2. receipt-backed
    return ("sighting from channel %r (type %r) has no source_url. public #83 rule 1: a "
            "sighting from a URL-bearing channel (job-board/aggregator) must carry its URL at "
            "the moment it is captured — the link is free now and effectively unrecoverable "
            "once the posting comes down. Pass 'source_url' in the sighting JSON, or record it "
            "through a channel that never carries one (e.g. a recruiter relationship)."
            % (sighting.get("channel_id"), ctype))


class LockError(RuntimeError):
    pass


# ⭐ Seconds, not minutes. Holders release in seconds by design (runlock.py's own contract), so
# a wait longer than this only ever happens when the holder is the CALLER'S OWN RUN — which will
# never release while it waits on us. 120 was sized for the old coarse lock and turned that
# self-deadlock into a silent two-minute hang (public #17 / dev #97).
DEFAULT_WAIT = 10


def take_lock(why, wait=DEFAULT_WAIT):
    r = subprocess.run([sys.executable, LOCK, "--take", why, "--wait", str(wait)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise LockError(r.stdout.strip() or "could not take the write lock")


def lock_is_held():
    """True if ANY writer currently holds the run lock. runlock --status exits 1 when locked."""
    r = subprocess.run([sys.executable, LOCK, "--status"], capture_output=True, text=True)
    return r.returncode != 0


def lock_held_by_wrapper():
    """dev #687 / public #138 (owner decision R6, 2026-10-09) — True iff THIS process was started
    under `runlock.py --run` AND that wrapper's lock is still the one on disk: the lock record
    exists and its `holder` token equals this process's `CLAUDESEARCH_LOCK_HOLDER`. Stricter
    than `lock_is_held()` on purpose: that answers "does anybody hold the lock", which is also
    true while a FOREIGN writer holds it. A record without a `holder` (a `--take` hold) never
    matches, and neither does an env token whose lock was since released or replaced.

    Returns `(state, who)`: state is `"mine"` (the wrapper's own hold), `"foreign"` (a hold
    this process cannot prove is its own run's) or `"free"` (no lock record). `who` names the
    holder of a non-free state, for the refusal line."""
    import runlock as _runlock
    rec = _runlock.read()
    if rec is None:
        return "free", None
    token = os.environ.get(_runlock.HOLDER_ENV)
    if token and rec.get("holder") == token:
        return "mine", rec.get("who")
    return "foreign", rec.get("who")


def release_lock():
    subprocess.run([sys.executable, LOCK, "--release"], capture_output=True)


def load(store):
    p = os.path.join(DATA, STORES[store])
    with open(p, encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


def _load_or_empty(store):
    """`load(store)`, but an ABSENT store is empty rather than a crash — the same "missing
    thing is not a failure" contract every read-only check in this engine honours (a profile
    that predates a store, or one a test harness never populated because it is testing
    something else, must not blow up a check that merely wants to LOOK at it). Only for checks
    that read a store to inform a refusal; a write path that actually MUTATES a store still
    wants load()'s own crash — a missing store there is a real problem, not an empty one."""
    try:
        return load(store)
    except OSError:
        return []


def save_atomic(store, rows):
    """Temp file in the SAME directory, then os.replace — atomic on POSIX.

    ⚠️ The old pattern was `open(path,'w')` followed by a write loop. A session dying mid-loop
    left a truncated file, i.e. a destroyed pipeline. `os.replace` either fully succeeds or
    leaves the original untouched; there is no partial state.
    """
    p = os.path.join(DATA, STORES[store])
    fd, tmp = tempfile.mkstemp(dir=DATA, prefix=".record-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def snapshot(store):
    """The store's exact bytes before a write, so a failed write can be undone. None if absent."""
    p = os.path.join(DATA, STORES[store])
    try:
        with open(p, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def restore(store, blob):
    """Put `blob` back, atomically. Returns True only if the bytes are verifiably back.

    ⚠️ Verified by reading the file again rather than trusting the write. A rollback that is
    merely *believed* to have happened is worse than none: the caller is told the store is clean
    and writes on top of whatever is actually there.
    """
    if blob is None:
        return False
    p = os.path.join(DATA, STORES[store])
    fd, tmp = tempfile.mkstemp(dir=DATA, prefix=".rollback-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(blob)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        return False
    try:
        with open(p, "rb") as fh:
            return fh.read() == blob
    except OSError:
        return False


def find(rows, rid):
    for r in rows:
        if r.get("id") == rid:
            return r
    return None


def _merge_would_cycle(people_rows, dup_id, survivor_id):
    """True if pointing `dup_id.merged_into = survivor_id` would close a cycle — i.e. the
    SURVIVOR's own existing merge chain already leads back to `dup_id`. Public #93: `record.py`
    had no merge verb at all, so nothing ever exercised `graph.MergeCycleError`'s refusal from
    the write side; this reuses `graph.py` itself (never a second, hand-rolled chain-walk) by
    writing the hypothetical `people` rows to a throwaway directory and asking
    `graph.Graph.resolve_person` to walk it — the one place this chain is ever resolved
    (graph.py's own docstring: 'a merge is a pointer... graph.py resolves through merged_into
    at read time'). No other store is needed for this question, so the throwaway directory
    carries `people.jsonl` alone; every other store `Graph.__init__` loads is simply absent,
    which it already treats as an empty store."""
    import graph as _graph
    shadow = [dict(r) for r in people_rows]
    for r in shadow:
        if r.get("id") == dup_id:
            r["status"] = "merged"
            r["merged_into"] = survivor_id
    tmpdir = tempfile.mkdtemp(prefix=".record-merge-check-")
    try:
        with open(os.path.join(tmpdir, "people.jsonl"), "w", encoding="utf-8") as fh:
            for r in shadow:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        g = _graph.Graph(data_dir=tmpdir)
        try:
            g.resolve_person(dup_id)
            return False
        except _graph.MergeCycleError:
            return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def mint_app_id(rid, existing):
    """`<opp_id>-aN`, N one past the highest suffix already minted for this opp_id (0.41.0;
    ADR-031 B2 re-pointed this at the top-level `applications` store's own `id` field — was
    `app_id` on a nested `applications[]` row, same VALUE format, "promotion changes only the
    lookup").

    ⭐ THE READER'S TARGET MUST EXIST. Every applications row gets its handle AT WRITE TIME, so
    a trigger (outreach[].trigger_ref, asks.trigger_ref) and every later reader resolve a key
    this API guarantees rather than a date somebody remembered — two applications on one day
    share a date and nothing else. Past-the-max, never count-plus-one: a row removed from the
    middle must not free its number for reuse, or an old trigger naming it would silently move
    to a different application. `existing` is every row this rid's ids could collide with —
    the caller filters to the SAME opp_id when it matters (this function itself does not,
    since the `<opp_id>-a` prefix already scopes the match)."""
    prefix = "%s-a" % rid
    n = 0
    for a in existing or []:
        aid = a.get("id") if isinstance(a, dict) else None
        if isinstance(aid, str) and aid.startswith(prefix) and aid[len(prefix):].isdigit():
            n = max(n, int(aid[len(prefix):]))
    return "%s%d" % (prefix, n + 1)


def mint_cover_letter_id(opp_id, existing):
    """`<opp_id>-clN`, N one past the highest suffix already minted for this opp_id (dev #764 /
    public #162). The same past-the-max, never count-plus-one rule as `mint_app_id`, for the same
    reason: a removed letter must not free its number for a later `cover_letter_id` reference to
    collide into. A letter is written for a role, so it is owned by the OPPORTUNITY, like an
    application. `existing` is every row whose ids could collide; the `<opp_id>-cl` prefix scopes
    the match, and a suffix that is not all digits (`<opp_id>-cl2-cl1`) is not a mint of this id."""
    prefix = "%s-cl" % opp_id
    n = 0
    for c in existing or []:
        cid = c.get("id") if isinstance(c, dict) else None
        if isinstance(cid, str) and cid.startswith(prefix) and cid[len(prefix):].isdigit():
            n = max(n, int(cid[len(prefix):]))
    return "%s%d" % (prefix, n + 1)


def mint_touch_id(person_id, existing):
    """`<person_id>-tN`, N one past the highest suffix already minted FOR THIS PERSON — ADR-031
    B3's own id scheme (design §1: 'id (= <person_id>-tN, minted by record.py)'). A touch is
    owned by the PERSON, not the opportunity — the one deliberate difference from
    `mint_app_id`'s `<opp_id>-aN`, which owns by the opportunity because an application is
    containment (design §1). `existing` is every row this person_id's ids could collide with —
    same past-the-max, never count-plus-one rule as `mint_app_id`, for the same reason: a
    removed touch must not free its number for a later trigger_ref/message_ref to collide
    into."""
    prefix = "%s-t" % person_id
    n = 0
    for t in existing or []:
        tid = t.get("id") if isinstance(t, dict) else None
        if isinstance(tid, str) and tid.startswith(prefix) and tid[len(prefix):].isdigit():
            n = max(n, int(tid[len(prefix):]))
    return "%s%d" % (prefix, n + 1)


def mint_message_id(anchor_id, person_id, date):
    """Deterministic id for a message THIS API creates (`touched`/`answered`, §15.3) — the
    SAME inputs always mint the SAME id, which is what makes the two-append write
    'idempotent by id' (§15.3 point 2): a re-run after a crash between the message append and
    the outreach append finds the message already there (by this id) and completes only the
    missing half, rather than writing a duplicate. Not a collision-proof id in general (two
    touches to the same person on the same day via different media share one id) — an
    accepted, stated trade-off, the same shape `mint_app_id`'s own docstring accepts for
    same-day applications sharing a date."""
    return "msg-record-%s-%s-%s" % (anchor_id or "none", person_id or "none", date)


def coerce(v):
    """A CLI gives strings; the store is typed. Guessing wrong writes "true" where True belongs."""
    if v in ("true", "True"):
        return True
    if v in ("false", "False"):
        return False
    if v in ("null", "None", ""):
        return None
    if v.lstrip("-").isdigit():
        return int(v)
    if v.startswith(("{", "[")):
        return json.loads(v)
    return v


def validate(data_dir=None):
    """Run validate_data.py and report (returncode, stdout, stderr).

    ⭐ `data_dir` points the validator at a THROWAWAY copy instead of the real store, via
    CLAUDESEARCH_DATA_DIR — the same override validate_data.py already exposes for a fresh-
    install check. This is what lets --dry-run run the exact validator a real write runs
    (dev #143 / public #23), without the real store ever being touched.

    stderr is captured too, not discarded. A validator that CRASHES (an unguarded value-shape
    assumption, for one) prints NOTHING to stdout — its own summary is only printed after every
    check finishes — so a caller reading stdout alone sees a blank result exactly when it most
    needs an answer. See _diagnostic_lines below."""
    env = os.environ.copy()
    if data_dir:
        env["CLAUDESEARCH_DATA_DIR"] = data_dir
    # dir= is explicit: the suite requires it of every mkstemp here (the store writes must
    # stay in the store's own directory); this sidecar is not a store, so the system tmp.
    fd, sidecar = tempfile.mkstemp(dir=tempfile.gettempdir(),
                                   prefix=".validate-problems-", suffix=".json")
    os.close(fd)
    try:
        env["CLAUDESEARCH_PROBLEMS_OUT"] = sidecar
        r = subprocess.run([sys.executable, os.path.join(ENGINE_SCRIPTS, "validate_data.py")],
                           capture_output=True, text=True, env=env)
        problems = _read_problems(sidecar)
    finally:
        try:
            os.unlink(sidecar)
        except OSError:
            pass
    return r.returncode, r.stdout, r.stderr, problems


def _read_problems(path):
    """The validator's own problem list, or None when it never finished (crashed before its
    summary — the sidecar is written on every finishing path, so an empty or missing one
    means exactly that). None is an honest 'unknown', never treated as clean."""
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return None
    if not text.strip():
        return None
    try:
        got = json.loads(text)
    except ValueError:
        return None
    return [str(x) for x in got] if isinstance(got, list) else None


def new_problems(pre, post):
    """The problems a write INTRODUCED — post minus pre, as sets — or None when either side is
    unknown (the validator crashed on it), which no comparison can settle.

    ⭐ THIS is the G9 fix (dev/audit 2026-09-02). The carve-out for a pre-existing failure
    used to compare EXIT CODES: with one standing problem the store returns 1 before and 1
    after any write, so a write that added a second, unrelated defect was kept under the
    first one's excuse — "already failing before" — and --dry-run refused to judge anything
    at all. One standing finding disabled the rollback for every write on every worker
    until a human dispositioned it. A set comparison sees the difference an exit code
    cannot: a write is pre-existing-only when every problem after it was already there."""
    if pre is None or post is None:
        return None
    before = set(pre)
    return [x for x in post if x not in before]


def introduced_row_violations(store, before_row, after_row):
    """The introduced-only rules (validate_data.INTRODUCED_ONLY_RULES) that a write to `store`
    NEWLY violates: `after_row` breaks them and `before_row` — the same row as it stood, or None
    for a create — did not break THAT SAME one.

    ⭐ dev #644 item 5 / dev #427. The whole-store validator only WARNS about a row that already
    exists in such a state (so a user whose history predates a rule is never locked out of their
    own store). This is the other half: a row being newly written, or changed INTO the state,
    is refused here, before anything is written. A row that was already in the state and is
    changed in some other field keeps the same message and is therefore not "introduced", so an
    unrelated edit to an old row is accepted. Messages are label-free, so they compare equal."""
    vd = _validator_module()
    gate = (_cannot_read_violations(store, before_row, after_row)
            + _manual_board_violations(store, before_row, after_row))
    after = vd.row_rule_violations(store, after_row)
    if not after:
        return gate
    before = set(vd.row_rule_violations(store, before_row)) if before_row is not None else set()
    return gate + [m for m in after if m not in before]


SURFACE_CANNOT_READ = "unavailable: surface-cannot-read"
MANUAL_BOARD = "unavailable: manual-board"


def _manual_board_violations(store, before_row, after_row):
    """dev #765 (design-portfolio-boards.md, review B1) -- a JD cannot be recorded as READ when every
    address the role carries is on a `manual-candidate` channel's `board_hosts`: those sites' terms
    forbid automated access (ADR-037), so the run must not have opened them. The role records
    `fit.jd_source = "unavailable: manual-board"` instead. Lives here for the reason
    `_cannot_read_violations` does: `introduced_row_violations` is the one choke point every write op and
    `--dry-run` passes through.

    WHEN IT FIRES: the row after the write carries a `fit.jd_source` that claims a read (a non-empty
    string not beginning `unavailable`), this write touched `fit`, and `board_hosts.jd_read_plan` finds
    NO readable address (`url` None) while at least one is on a board host. A role that also carries an
    address OFF every board host is not held: the read could have used it. A role whose `fit` this write
    leaves alone is never held, so an old row is not locked out of `decide` or any other edit. A channels
    store that cannot be read is NOT treated as one with no boards: the write is refused with
    `NOT CHECKED`."""
    if store != "opportunities" or not isinstance(after_row, dict):
        return []
    fit = after_row.get("fit")
    src = fit.get("jd_source") if isinstance(fit, dict) else None
    if not (isinstance(src, str) and src.strip()) or src.startswith("unavailable"):
        return []
    if isinstance(before_row, dict):
        keys = {k for k in set(before_row) | set(after_row) if k == "fit" or k.startswith("fit.")}
        if all(before_row.get(k) == after_row.get(k) for k in keys):
            return []                                   # this write did not touch fit
    try:
        import board_hosts as _bh
        plan = _bh.jd_read_plan(after_row, _load_or_empty("channels"))
    except (OSError, ValueError) as e:
        return ["NOT CHECKED: the channels store is unreadable (%s), so a JD read cannot be allowed" % e]
    if plan["url"] is None and plan["blocked"]:
        b = plan["blocked"][0]
        return ["fit.jd_source %r claims a read, but every address this role carries is on the manual-candidate "
                "board %r (host %s), which the engine never opens (ADR-037): record `%s` instead"
                % (src, b["channel_id"], b["host"], MANUAL_BOARD)]
    return []


def _cannot_read_violations(store, before_row, after_row):
    """dev #723 (jobsearch 0.69.0, design R5) -- `fit.jd_source = "unavailable: surface-cannot-read"`
    is refused unless a `read-jd` item for this role, pending or done, has waited MORE THAN
    `search.triage_stuck_days` days. It lives HERE because `introduced_row_violations` is the one
    row-level choke point every write op (`set`, `set-in`, `create`, `append`) and `--dry-run`
    already passes through, so no op can bypass it. 'Surface cannot read' is a claim about every
    surface, and one run on one surface cannot make it: it is the outcome of an item that waited for a
    browser-holding worker and none came (`deferred.py --settle` writes it, through this script).

    The queue is read through `deferred.py`'s own reader (`load` / `replay`, pointed at THIS store's
    data directory). A queue that cannot be read is NOT treated as an empty one: the write is refused
    with `NOT CHECKED: deferred store unreadable`, never silently allowed.

    WHEN IT FIRES: the row after the write carries the value AND this write touched its `fit`
    (a new row, a `set fit`, a `set-in` on `fit.requirements`, and an `append` to it, which writes
    the dotted key `fit.requirements` itself -- a quirk this does not fix, and that counts as
    touching fit). A write that leaves every `fit*` key alone is not this rule's business, so a role
    a 0.68.0 run marked by hand (the skill then allowed it after the bound) is never locked out of
    `decide` or any other edit; only an edit of its `fit` is held to the bound."""
    if store != "opportunities" or not isinstance(after_row, dict):
        return []
    fit = after_row.get("fit")
    if not (isinstance(fit, dict) and fit.get("jd_source") == SURFACE_CANNOT_READ):
        return []
    if isinstance(before_row, dict):
        keys = {k for k in set(before_row) | set(after_row) if k == "fit" or k.startswith("fit.")}
        if all(before_row.get(k) == after_row.get(k) for k in keys):
            return []                               # this write did not touch fit
    oid = after_row.get("id")
    try:
        import deferred as _deferred
        import your_move as _ym
        items = [r for r in _deferred.replay(
                    _deferred.load(os.path.join(DATA, "pending_actions.jsonl")))
                 if r.get("kind") == _deferred.KIND_JD_READ and r.get("ref") == oid]
        bound = _ym.triage_stuck_days()
    except (OSError, ValueError) as e:
        return ["NOT CHECKED: deferred store unreadable (%s), so fit.jd_source %r cannot be "
                "allowed" % (e, SURFACE_CANNOT_READ)]
    if any(_deferred.jd_read_waited_past_bound(i, bound) for i in items):
        return []
    return ["fit.jd_source %r needs a `read-jd` item for this role that has waited more than "
            "search.triage_stuck_days (%d) days, and %s: queue one with `deferred.py --add-jd-read "
            "%s --run <run id>`; `deferred.py --settle` records this once the bound has passed"
            % (SURFACE_CANNOT_READ, bound,
               ("the oldest has not waited that long" if items else "there is none"), oid)]


def dry_run_validate(store, rows, extra=None):
    """Validate `rows` AS IF they were the real store, on a disposable copy of the whole data
    directory — cross-references into companies/channels/messages/asks still resolve, and the
    real files are never opened for writing. Returns the same (rc, stdout, stderr) shape as
    validate().

    ⭐ THIS is the fix for dev #143 / public #23 failure #1: a dry-run create on an enum-invalid
    or wrongly-typed field used to report success, because --dry-run only ran check_field's
    unknown-key/required checks and stopped — it never ran validate_data.py, which is the ONLY
    thing that catches an enum violation or a value of the wrong shape. The identical input as
    a real write was refused and rolled back. A green dry-run that does not predict the real
    write is worse than no dry-run at all, so dry-run now runs the SAME validator, not a lesser
    one.

    ⭐ THE SHADOW IS SHAPED LIKE THE PROFILE, NOT LIKE A BAG OF JSONL (public #61, 0.37.1).
    The first version copied the `*.jsonl` files into a FLAT temp dir and pointed the
    validator at it. validate_data.py resolves AUTHORED files — a declared resume variant's
    page — off `dirname(DATA)`, the profile root; in a flat shadow that parent is the temp
    dir itself, so every declared variant's file-existence check failed and a dry run of a
    NO-OP write (a date field assigned the value it already held) printed that a real write
    would be refused, naming files that existed and were readable. One-directional: the real
    write validates against the real profile and succeeds, so the store was never corrupted —
    what broke was the ability to check anything before writing, and every message looked
    like a legitimate validation failure. Dormant from dev #143's shadow until a variant was
    declared.

    So the shadow is now `<tmp>/data/` with every NON-data sibling of the real data dir
    symlinked into `<tmp>/`: the validator's `dirname(DATA)` lands on a directory whose
    contents ARE the profile root's, and any future authored-file check resolves correctly
    with no second override for every fresh-install path to honour. The validator only reads,
    so a symlink is exactly as safe as the real file. (The repo rule against committed
    symlinks is about TRACKED files, which dangle in every clone; these live in a temp dir
    for one subprocess and are gone with it — they are never tracked.) A symlink failure
    raises rather than falling back to the flat shape: a shadow that silently regressed to
    the flat layout would reintroduce this exact bug and look like a validation failure."""
    base = os.path.dirname(os.path.abspath(DATA))       # the validator's own _files_base rule
    data_name = os.path.basename(os.path.abspath(DATA))
    with tempfile.TemporaryDirectory(prefix="record-dryrun-") as shadow:
        for name in os.listdir(base):
            if name == data_name:
                continue
            os.symlink(os.path.join(base, name), os.path.join(shadow, name))
        shadow_data = os.path.join(shadow, data_name)
        os.mkdir(shadow_data)
        for name in os.listdir(DATA):
            src = os.path.join(DATA, name)
            if name.endswith(".jsonl") and os.path.isfile(src):
                shutil.copy2(src, os.path.join(shadow_data, name))
        # `extra` ({store: rows}, dev #765): a verb that writes a SECOND store in the same transaction
        # (board-sighting writes companies and opportunities) shadows that store as well.
        for shadowed, shadow_rows in [(store, rows)] + sorted((extra or {}).items()):
            with open(os.path.join(shadow_data, STORES[shadowed]), "w", encoding="utf-8") as fh:
                for r in shadow_rows:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        return validate(data_dir=shadow_data)


def _diagnostic_lines(rc, out, err):
    """The last few informative lines from a validate_data.py run — never blank.

    dev #143 / public #23 failure #2: a refused write's banner named no field, no offending
    value, no rule — even though the validator computes exactly that detail internally for most
    problems (see enum()'s message format, which this reuses verbatim by printing the
    validator's own problem lines rather than inventing a second style of message). The banner
    went blank specifically when the validator CRASHED (docs/schema.md's comp field passed as a
    non-object used to do exactly this — see validate_data.py's comp check): stdout was empty
    because nothing had been printed yet, and the traceback landed on stderr, which record.py
    was throwing away entirely. Fall back to stderr, then to the bare fact of a silent crash, so
    there is always something to act on instead of an empty line."""
    text = (out or "").strip()
    if text:
        return text.split("\n")[-6:]
    err_text = (err or "").strip()
    if err_text:
        return (["(the validator produced no output on stdout — it crashed; last lines of "
                 "its stderr:)"] + err_text.split("\n")[-6:])
    return ["(the validator exited %d with no output on stdout or stderr)" % rc]


def _validator_module():
    """validate_data.py, imported as a MODULE rather than run as the subprocess `validate()`
    uses — so `fields` can read its enum sets DIRECTLY. docs/data_model.json's own _enums_note
    already states the intended architecture: 'ENUMS ARE NOT DUPLICATED HERE ... record.py
    imports that module' — true now for the first time (dev #143 / public #23 failure #3).
    Lazy: only the `fields` path pays for this."""
    import validate_data as _vd
    return _vd


def _plans_mod():
    """ADR-031 B4 — `plans.py`, the enum-owning module for `plans`/`plays`, imported lazily
    the same way `_validator_module()` is (only the code paths that need it pay for it)."""
    import plans as _pl
    return _pl


# field -> allowed-value SET, keyed by store then field name. Every set here is a REFERENCE to
# a validate_data.py constant, never a restated literal — the values still live in exactly one
# place. ⚠️ If a future enum() call in validate_data.py covers a new field, add it here too, or
# `fields` will silently omit it: this registry is a second place that knows WHICH field maps
# to WHICH constant (unavoidable — that linkage isn't data validate_data.py exposes any other
# way), even though it duplicates no VALUES.
def _enum_registry(_vd):
    return {
        "companies": {"vertical": _vd.VERTICALS, "status": _vd.COMPANY_STATUS},
        "channels": {"type": _vd.CHANNEL_TYPES, "review_cadence": _vd.CADENCES,
                    "access": _vd.ACCESS},
        "opportunities": {"status": _vd.OPP_STATUS, "stage": _vd.STAGES,
                          "verdict": _vd.VERDICTS, "next_action_owner": _vd.OWNERS},
        # ADR-031 B4 — `plans`/`plays` join here for the same reason `touches` did in B3: the
        # enum values live in one place (`plans.py`), never restated.
        "plans": {"subject_kind": _plans_mod().SUBJECT_KINDS, "status": _plans_mod().PLAN_STATUS,
                 "resolves_when": _plans_mod().RESOLVES_WHEN},
        "plays": {"status": _plans_mod().PLAY_STATUS},
        # ADR-031 B3 — `touches` is a top-level store now (promoted from
        # opportunities.outreach[]), so its enums move from `_array_enum_registry` below to
        # here, the same move B2 never made for applications/cover_letters (a pre-existing
        # gap this dispatch does not otherwise touch) but is worth making for the store it is
        # actually building.
        "touches": {
            "status": _vd.OUTREACH_STATUS, "outcome": _vd.OUTREACH_OUTCOME,
            "medium": _vd.MEDIA, "touch_type": _vd.TOUCH_TYPES,
            "recipient_role": _vd.RECIPIENT_ROLES, "delivery": _vd.DELIVERY,
            "address_status": _vd.ADDRESS_STATUS, "trigger_kind": _vd.TRIGGER_KINDS,
        },
    }


# (store, array-name) -> {field: allowed-value SET}. Same reference-not-restatement rule.
def _array_enum_registry(_vd):
    return {
        # ADR-031 B3 — `("opportunities", "outreach")` retired along with the array itself;
        # its enums moved to `_enum_registry`'s new `"touches"` entry above.
        ("opportunities", "contacts"): {
            "email_status": _vd.CONTACT_EMAIL_STATUS, "path_type": _vd.PATH_TYPES,
        },
        ("opportunities", "applications"): {
            "method": _vd.APPLICATION_METHODS, "status": _vd.APPLICATION_STATUS,
        },
        ("opportunities", "fit.requirements"): {
            "verdict": _vd.FIT_VERDICTS, "question_status": _vd.FIT_Q_STATUS,
        },
    }


def _object_shaped_fields(store, _vd):
    """Fields whose value is an OBJECT, not a string — the exact class of mistake the report
    cites: a comp-style field (an object with two numeric keys) rendered by `fields` as though
    it accepted free text, with nothing to tell a caller otherwise. The model file only carries
    flat field-name lists, so a caller reading just that has no way to know; state it here."""
    if store != "opportunities":
        return {}
    return {
        "comp": "object — {\"min\": number, \"max\": number}",
        "location": ("object — {\"type\": one of {%s}, \"declared\": string, "
                     "\"primary\": string}" % ", ".join(sorted(_vd.LOC_TYPES))),
        "fit": "object — {\"requirements\": [fit.requirements[] rows, below]}",
    }


# ---- dev #133 / public #22: completing an action resolves its ask, IN THE SAME WRITE --------
#
# The incident: an application was recorded on an opportunity while the ask requesting approval
# for exactly that application stayed open in data/asks.jsonl — two independent writes, one
# happened without the other, and a freshly regenerated dashboard rendered the answered question
# as still pending. check_action_claims.py DETECTS that drift after the fact; this PREVENTS it,
# but only where the linkage is declared: an ask carrying `resolves_when` ("application" or
# "outreach") plus `opp_id` states, machine-readably, which recorded action answers it. When
# record.py lands that action on that opportunity, it resolves the ask under the SAME lock hold,
# before release. An ask without `resolves_when` is deliberately untouched — guessing which ask
# an action answers is how a still-needed question gets silently closed, which is worse than the
# drift this exists to prevent.

ASKS_FILE = "asks.jsonl"
# ADR-031 B2/B3 — "applications" and (now) "outreach" both left this mapping empty: each named
# an ARRAY LEAF on the opportunities record, and neither array exists there any more (each
# promoted to its own top-level store). Both actions' ask-resolution now fire from their own
# store's write site directly (`_applications_action_evidence`/`_touches_action_evidence` and
# the two matching write-completion blocks in `main()`), never through this array-leaf mapping.
# Left EMPTY rather than removed: a future nested array with a declared `resolves_when` action
# would use exactly this shape again, and an empty dict documents the mechanism still exists
# for one, rather than a caller having to reconstruct why it disappeared.
ASK_ACTION_FOR_ARRAY = {}


def _asks_path():
    return os.path.join(DATA, ASKS_FILE)


def _load_asks():
    try:
        with open(_asks_path(), encoding="utf-8") as fh:
            return [json.loads(l) for l in fh if l.strip()]
    except OSError:
        return None          # no asks store at all — legal (pre-0.25.0 profiles)


def _applications_action_evidence(opp_id):
    """The newest dated evidence of an "application" action on `opp_id`, read from the
    TOP-LEVEL `applications` store (ADR-031 B2) — the promoted successor to a function that
    once read a nested array that no longer exists."""
    dates = []
    for ap in load("applications"):
        if ap.get("opp_id") == opp_id and ap.get("date"):
            dates.append(str(ap["date"]))
    return max(dates) if dates else None


def _touches_action_evidence(opp_id):
    """The newest dated evidence of an "outreach" action on `opp_id`, read from the TOP-LEVEL
    `touches` store (ADR-031 B3) — the promoted successor to a function that once read
    `rec.get("outreach")`, a nested array that no longer exists. Same funnel
    check_action_claims.opp_action_evidence() trusts: any touch with status == "sent" and a
    date. A drafted touch is not evidence — the ask asked for the touch, not the intention."""
    dates = []
    for t in load("touches"):
        if t.get("opp_id") == opp_id and t.get("status") == "sent" and t.get("date"):
            dates.append(str(t["date"]))
    return max(dates) if dates else None


def linked_asks(rid, action, asks):
    """The OPEN asks this write could resolve: opp_id matches, resolves_when matches."""
    return [a for a in (asks or [])
            if not a.get("resolved_on") and a.get("opp_id") == rid
            and a.get("resolves_when") == action]


def resolve_linked_asks_dated(rid, when, action):
    """Resolve every declared-linkage ask this write's action answers, GIVEN its evidence date
    directly. Returns [(id, title)]. ADR-031 B2 (2026-09-11): extracted from the old
    `resolve_linked_asks(rid, rec, array_leaf)` — deriving `when`/`action` used to be this
    function's own job when both the outreach evidence AND the application evidence lived on
    one opportunity record; `applications` now lives in its own top-level store, so the two
    call sites (the opportunities-file write path, and the applications-file write path) each
    derive their own `when` and call this shared core, rather than this function knowing about
    either store's shape.

    Runs INSIDE the caller's lock hold, after the write that produced `when` validated clean.
    Evidence must be dated on/after the ask's `created` — an action that predates the ask is
    what the ask was written about, not the answer to it (same baseline as
    check_action_claims.py).

    ⚠️ Failure honesty: the write that produced `when` has already landed and validated. If the
    asks write then fails, we roll back ONLY asks.jsonl and say so loudly — the state degrades
    to exactly what it was before this change existed (action recorded, ask open), which the
    detection backstop catches. Never let an asks problem un-land a valid action record."""
    if not action or not when:
        return []
    asks = _load_asks()
    if asks is None:
        return []
    hit = []
    for a in linked_asks(rid, action, asks):
        created = str(a.get("created") or "")
        if created and when < created:
            continue
        a["resolved_on"] = when
        a["resolution"] = "done"
        stamp = "auto-resolved with the write that recorded its %s (record.py, dev #133)" % action
        a["note"] = ("%s · %s" % (a["note"], stamp)) if a.get("note") else stamp
        hit.append((a.get("id"), a.get("title") or ""))
    if not hit:
        return []

    before = None
    try:
        with open(_asks_path(), "rb") as fh:
            before = fh.read()
    except OSError:
        pass
    fd, tmp = tempfile.mkstemp(dir=DATA, prefix=".record-asks-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for a in asks:
                fh.write(json.dumps(a, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, _asks_path())
    except Exception as e:
        if os.path.exists(tmp):
            os.unlink(tmp)
        print("  ⚠️ the action WROTE, but resolving its ask(s) failed: %s" % e)
        print("  The ask(s) remain OPEN — check_action_claims.py will flag the drift.")
        return []
    rc, out, err, _problems = validate()
    if rc != 0:
        # Only this file can be guilty: the store validated clean two steps ago.
        ok = False
        if before is not None:
            fd2, tmp2 = tempfile.mkstemp(dir=DATA, prefix=".rollback-asks-", suffix=".tmp")
            try:
                with os.fdopen(fd2, "wb") as fh:
                    fh.write(before)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp2, _asks_path())
                with open(_asks_path(), "rb") as fh:
                    ok = fh.read() == before
            except Exception:
                if os.path.exists(tmp2):
                    os.unlink(tmp2)
        print("  ⚠️ the action WROTE, but the ask resolution broke the validator and was %s."
              % ("rolled back" if ok else "NOT VERIFIABLY ROLLED BACK — restore asks.jsonl "
                 "from git"))
        print("  " + "\n  ".join(_diagnostic_lines(rc, out, err)))
        return []
    return hit


# ── States & Views V1b (design §13/§15.3) — `touched` and `answered` ───────────────────────
#
# Both span TWO files (messages.jsonl + opportunities.jsonl) with no cross-file transaction —
# §3b's own correction, generalised: "the touch lands in messages.jsonl or outreach[], the
# flag on the opportunity row, two files and two writers." So each write here is TWO
# ORDERED, IDEMPOTENT appends under ONE lock hold (message first, §15.3 point 2) rather than
# one atomic multi-file commit: a crash between them leaves a message with no completing
# outreach[] row, which validate_data.py's own orphan check (MESSAGES_TOUCHED_SOURCE) names,
# and a RE-RUN with the SAME arguments finds the message already there (mint_message_id is
# deterministic over the call's own inputs) and writes only the missing half.

def _resolve_plan_goal(opp_id, new_stage):
    """ADR-031 B4 (design §17) — [(plan_id, resolution)] for the ONE plan this write may have
    resolved: `new_stage` at screening or beyond, on a governing plan whose `resolves_when` is
    'goal-reached' and is not already resolved. The exact best-effort shape
    `resolve_linked_asks_dated` already uses — the primary write already landed and validated;
    a failure here is loud and never un-lands it."""
    if new_stage not in ("screening", "interviewing", "offer"):
        return []
    opps = load("opportunities")
    opp = find(opps, opp_id)
    if opp is None or not opp.get("plan_id"):
        return []
    plans = load("plans")
    plan = find(plans, opp["plan_id"])
    if plan is None or plan.get("resolved_on") or plan.get("resolves_when") != "goal-reached":
        return []
    today_iso = datetime.date.today().isoformat()
    plan["resolved_on"] = today_iso
    plan["resolution"] = "goal reached — %s advanced to stage %r on %s" % (opp_id, new_stage,
                                                                          today_iso)
    fd, tmp = tempfile.mkstemp(dir=DATA, prefix=".record-plans-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for p in plans:
                fh.write(json.dumps(p, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, os.path.join(DATA, STORES["plans"]))
    except Exception as e:                                        # noqa: BLE001
        if os.path.exists(tmp):
            os.unlink(tmp)
        print("  ⚠️ the write landed, but resolving its plan failed: %s" % e)
        return []
    rc, _out, _err, _problems = validate()
    if rc != 0:
        print("  ⚠️ the write landed, but resolving the plan left the store invalid — check "
              "data/plans.jsonl.")
        return []
    return [(plan.get("id"), plan.get("resolution"))]


def _load_involvements():
    try:
        with open(os.path.join(DATA, "involvements.jsonl"), encoding="utf-8") as fh:
            return [json.loads(l) for l in fh if l.strip()]
    except OSError:
        return []


def _person_name(person_id):
    """The person's display name, for a message/outreach row's own `to` field — never the
    bare id, when a name is available. Fails open to None (the caller falls back to the id
    itself, which is always non-empty)."""
    try:
        import graph as _graph
        g = _graph.Graph(DATA)
        row = g.by_id["people"].get(person_id)
        return row.get("name") if row else None
    except Exception:                                        # noqa: BLE001 — cosmetic only
        return None


def _plays_mod():
    """plays.py — the ONE place ROLE_TO_PATH/PATH_TYPE_CLASS are defined (§26.2's own bridge
    between touches' RECIPIENT_ROLES and involvements' PATH_TYPES), imported lazily the same
    way `_plans_mod()`/`_validator_module()` are — only `_propagate_touch` pays for it."""
    import plays as _pl
    return _pl


def _profile_mod():
    """profile.py, imported lazily — only `_propagate_touch`'s next_action_owner comparison
    needs `owner_token()`, the same lazy-import discipline as `_plays_mod()`."""
    import profile as _pf
    return _pf


def _upsert_involvement(opp_id, person_id, recipient_role=None, create_only=False):
    """dev #686 / public #139 (E2) — step 1 of `_propagate_touch`, factored out so `record.py
    involve` and a touch share ONE writer. Runs INSIDE the caller's lock hold.

    Creates the (person_id, opp_id) involvement if absent (`status: contacted`, `path_type`
    from `plays.ROLE_TO_PATH`), or — unless `create_only` — sets `status` to 'contacted' on an
    existing one. `create_only=True` is the explicit-link verb's mode: an existing link is
    left untouched. Verified by validate-and-roll-back, byte-identical on a new problem.

    Returns `(printable_lines, outcome)`, outcome one of `created` · `updated` · `exists`
    (create_only, link already there) · `unchanged` · `failed`."""
    lines = []
    outcome = "unchanged"

    # ---- 1. involvements: create or upsert ----------------------------------------------
    involvements = _load_involvements()
    inv = None
    for row in involvements:
        if row.get("person_id") == person_id and row.get("opp_id") == opp_id:
            inv = row
            break
    mapped_path = _plays_mod().ROLE_TO_PATH.get(recipient_role) if recipient_role else None
    created = inv is None
    inv_dirty = False
    if inv is None:
        inv = {"person_id": person_id, "opp_id": opp_id, "channel_id": None,
               "path_type": mapped_path, "role": None, "status": "contacted", "note": None}
        involvements.append(inv)
        inv_dirty = True
    else:
        if create_only:
            return lines, "exists"
        if inv.get("status") != "contacted":
            inv["status"] = "contacted"
            inv_dirty = True
        if mapped_path and inv.get("path_type") is None:
            inv["path_type"] = mapped_path
            inv_dirty = True

    if inv_dirty:
        inv_path = os.path.join(DATA, "involvements.jsonl")
        try:
            with open(inv_path, "rb") as fh:
                before_inv = fh.read()
        except OSError:
            before_inv = None
        fd, tmp = tempfile.mkstemp(dir=DATA, prefix=".record-involvements-", suffix=".tmp")
        landed = False
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                for r in involvements:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, inv_path)
            landed = True
        except Exception as e:                                        # noqa: BLE001
            if os.path.exists(tmp):
                os.unlink(tmp)
            print("  ⚠️ the write landed, but upserting the involvement failed: %s" % e)
            outcome = "failed"
        if landed:
            rc, out, err, _problems = validate()
            if rc != 0:
                ok = False
                if before_inv is not None:
                    fd2, tmp2 = tempfile.mkstemp(dir=DATA, prefix=".rollback-involvements-",
                                                 suffix=".tmp")
                    try:
                        with os.fdopen(fd2, "wb") as fh:
                            fh.write(before_inv)
                            fh.flush()
                            os.fsync(fh.fileno())
                        os.replace(tmp2, inv_path)
                        with open(inv_path, "rb") as fh:
                            ok = fh.read() == before_inv
                    except Exception:                                  # noqa: BLE001
                        if os.path.exists(tmp2):
                            os.unlink(tmp2)
                outcome = "failed"
                print("  ⚠️ the write landed, but upserting the involvement left the store "
                      "invalid and was %s."
                      % ("rolled back" if ok else "NOT VERIFIABLY ROLLED BACK — restore "
                         "involvements.jsonl from git"))
                print("  " + "\n  ".join(_diagnostic_lines(rc, out, err)))
            else:
                lines.append("  ✦ involvement %s for %s on %s"
                             % ("created" if created else "upserted", person_id, opp_id))
                outcome = "created" if created else "updated"
    return lines, outcome


# ── dev #479 / public #114 — completing an outbound touch PROPAGATES ────────────────────────
#
# The defect: `touched`/`answered` wrote only the touch/message row and stopped — the
# recipient's `involvements` row was never created or upserted (a person just written to could
# still read as not-contacted, or have no row at all), and the opportunity's
# `next_action_owner`/`next_action_date` never moved off the candidate even though the action
# they were waiting on had just been recorded. `check_followups.py` tracked the touch
# correctly; the role-decision surface reads `opportunities`/`involvements`, not the touch
# store, so completed outbound work kept rendering as an open to-do. This is proposal #1 from
# the report — the smallest of the three, and the one that closes the write path itself rather
# than adding a second, independent detector for the gap it leaves.

def _propagate_touch(opp_id, person_id, date, recipient_role=None):
    """Runs INSIDE the caller's lock hold, best-effort, AFTER the write that recorded the
    touch (or the reply message) has already landed and validated clean — the same shape
    `_resolve_plan_goal`/`resolve_linked_asks_dated` use above: a failure here is loud and
    never un-lands the primary write.

    Two independent updates, each verified by its own validate-and-roll-back:

      1. Upsert the (person_id, opp_id) involvement: create it if absent (never was there to
         upsert), or set `status` to 'contacted' on an existing one. `path_type` is filled from
         the touch's own `recipient_role` via `plays.ROLE_TO_PATH` (§26.2's existing bridge,
         "it is simply never applied when a touch is recorded" per the report) only when the
         row does not already carry one — reclassifying an existing 'cold'/'hiring-context'
         path_type is the report's SECOND, separate finding and out of this dispatch's scope.

      2. If this opportunity's `next_action_owner` names the candidate, the touch just
         recorded is the action it was waiting on: clear ownership to 'me' and clear the now-
         stale `next_action_date` alongside it, in the SAME write — never re-derive a new date,
         only retire the one that named this now-completed action.

    Returns the printable lines describing what changed (possibly empty)."""
    if not opp_id or not person_id:
        return []
    lines, _outcome = _upsert_involvement(opp_id, person_id, recipient_role)

    # ---- 2. opportunity: clear ownership off the candidate --------------------------------
    owner_token = _profile_mod().owner_token()
    opps = load("opportunities")
    opp = find(opps, opp_id)
    if opp is not None and opp.get("next_action_owner") == owner_token:
        before_opp = snapshot("opportunities")
        pre_rc, _o, _e, pre_problems = validate()
        opp["next_action_owner"] = "me"
        opp["next_action_date"] = None
        save_atomic("opportunities", opps)
        rc, out, err, problems = validate()
        if rc != 0:
            added = new_problems(pre_problems, problems)
            if not (pre_rc != 0 and added == []):
                restore("opportunities", before_opp)
                print("  ⚠️ the write landed, but clearing next_action_owner broke the "
                      "store; rolled back.")
                print("  " + "\n  ".join(_diagnostic_lines(rc, out, err)))
            else:
                lines.append("  ✦ next_action_owner cleared off %s on %s (this touch was "
                             "the action it was waiting on)" % (owner_token, opp_id))
        else:
            lines.append("  ✦ next_action_owner cleared off %s on %s (this touch was the "
                         "action it was waiting on)" % (owner_token, opp_id))
    return lines


TOUCHED_USAGE = ("usage: touched [<opp_id>] --to contact:<person-id> --medium <medium> "
                 "[--on <date>] [--role <role>] [--touch-type <type>]  "
                 "(no <opp_id> = a person-anchored touch: a relationship with no role)")


def cmd_touched(args):
    """`record.py touched [<opp_id>] --to contact:<person-id> --on <date> --medium <medium>
    [--role <role>] [--touch-type <type>]` — cell 3's own action line (design §3): a touch made
    OUTSIDE the normal draft-and-send flow (a handshake, a phone call, any medium this API does
    not draft for). Writes a row on the top-level `touches` store (ADR-031 B3 — was: appended
    to the opportunity's own `outreach[]`) and, for an EMAIL medium, the message row that
    documents it.

    ⭐ dev #686 / public #139 (rule 3) — THE `<opp_id>` IS OPTIONAL. Without one this records a
    PERSON-ANCHORED touch: `opp_id`/`channel_id` null, owned by the person alone (a legal shape
    since public #53; only this PATH was missing). Every field the validator will require is
    filled here and every up-front check runs BEFORE the lock and before any write, each
    refusal naming the field: `--to` resolves to a non-merged person, `--medium` in MEDIA,
    `--on` an ISO date, `--role` and `--touch-type` in their enums. No opportunity means no
    involvement to upsert; the output says so. `--touch-type` is valid on both forms (it is the
    only otherwise-unsettable required field). `record.py fields --file touches` lists the
    conditional requirements from the validator's own named constants.

    `--_inject-fault after-message` is a TEST-ONLY hook (never reachable except by passing the
    flag explicitly): after the message half lands, it exits before the touch half — so the
    half-written case and its repair are proven from OUTSIDE this function, by actually
    breaking it and re-running, the same discipline `migrate.py`'s own `_inject_fault` plants
    use rather than trusting the mechanism by reading the source."""
    opp_id = args.rid or None
    if args.rest:
        print(TOUCHED_USAGE)
        return 2
    if not args.to_token:
        print("⛔ REFUSED — --to contact:<person-id> is required.")
        return 1
    tm = re.match(r"^contact:(.+)$", args.to_token)
    if not tm:
        print("⛔ REFUSED — --to must be `contact:<person-id>`, got %r" % args.to_token)
        return 1
    person_id = tm.group(1)
    date = args.on_date or datetime.date.today().isoformat()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        print("⛔ REFUSED — --on must be an ISO date (YYYY-MM-DD), got %r" % date)
        return 1
    _vd = _validator_module()
    medium = args.medium
    if not medium or medium not in _vd.MEDIA:
        print("⛔ REFUSED — --medium must be one of %s" % ", ".join(sorted(_vd.MEDIA)))
        return 1
    if args.recipient_role is not None and args.recipient_role not in _vd.RECIPIENT_ROLES:
        print("⛔ REFUSED — --role must be one of %s" % ", ".join(sorted(_vd.RECIPIENT_ROLES)))
        return 1
    if args.touch_type is not None and args.touch_type not in _vd.TOUCH_TYPES:
        print("⛔ REFUSED — --touch-type must be one of %s" % ", ".join(sorted(_vd.TOUCH_TYPES)))
        return 1

    if opp_id:
        opps0 = load("opportunities")
        if find(opps0, opp_id) is None:
            print("No opportunities record with id %r." % opp_id)
            return 1
        # The join validate_data.py itself enforces on every touch naming an opp_id — checked
        # here too so a bad --to refuses BEFORE any write, not two steps later via a rollback.
        if not any(r.get("person_id") == person_id and r.get("opp_id") == opp_id
                  for r in _load_involvements()):
            print("⛔ REFUSED — person_id %r has no involvement on opportunity %r. Every touch "
                  "naming an opportunity must name a person actually involved in THIS pursuit "
                  "— add the involvement first (`record.py involve %s --opp %s`), or check "
                  "the --to id." % (person_id, opp_id, person_id, opp_id))
            return 1
    # dev #686 — the recipient must be a real, non-merged person on EITHER form. A merged id is
    # refused naming its survivor: a touch written to the absorbed row would be a touch on a
    # person nobody reads any more.
    _prow = find(_load_or_empty("people"), person_id)
    if _prow is None:
        print("⛔ REFUSED — --to names person_id %r, which resolves to no people record. A "
              "touch with no person is unfindable; create the person first "
              "(`record.py create <id> '{...}' --file people --reuse`)." % person_id)
        return 1
    if _prow.get("status") == "merged":
        print("⛔ REFUSED — --to names person_id %r, which was merged into %r. Touch the "
              "survivor: --to contact:%s" % (person_id, _prow.get("merged_into"),
                                             _prow.get("merged_into")))
        return 1

    is_email = medium.startswith("email")
    msg_id = mint_message_id(opp_id, person_id, date) if is_email else None
    to_label = _person_name(person_id) or person_id

    # ⭐ public #103 — THE FIX. `touched` used to have no --dry-run gate at all: every check
    # above (opp exists, involvement exists, medium/role valid) already ran, so this is the
    # exact point the write-shaped verbs (decide/set-in/…) stop at too. No lock is taken and
    # neither append below ever runs.
    if args.dry_run:
        preview = []
        if is_email:
            already_msg = any(m.get("id") == msg_id for m in load("messages"))
            preview.append(("message %s already recorded" % msg_id) if already_msg
                           else ("would record message %s" % msg_id))
        touches_rows = load("touches")
        already_touch = any(o.get("person_id") == person_id and o.get("opp_id") == opp_id
                            and o.get("date") == date and o.get("medium") == medium
                            and o.get("message_ref") == msg_id
                            for o in touches_rows)
        preview.append("touch already recorded" if already_touch
                       else "would record a touch on %s"
                       % (opp_id or "the person alone (no opportunity)"))
        print("touched: %s -> %s via %s on %s" % (opp_id or "(no opportunity)", person_id,
                                                  medium, date))
        print("  --dry-run: nothing written. (%s)" % "; ".join(preview))
        return 0

    if args.already_locked:
        if not lock_is_held():
            print("  REFUSED — --already-locked, but NOBODY holds the run lock.")
            print("  Take it first (runlock.py --take), or drop the flag.")
            return 1
    else:
        try:
            take_lock("record.py touched %s" % (opp_id or person_id), wait=args.wait)
        except LockError as e:
            print("  REFUSED — %s" % e)
            return 1
    try:
        if is_email:
            messages = load("messages")
            if not any(m.get("id") == msg_id for m in messages):
                # ⭐ NO validate-and-rollback dance for THIS append. §15.3 point 2 is explicit
                # that the store may be legitimately, TEMPORARILY invalid between the two
                # halves — a message with `source: 'record.py touched'` and no completing
                # touches row is EXACTLY the shape validate_data.py's own orphan check exists
                # to name, and it would fire on this half by construction, every time, even on
                # the ordinary (uninterrupted) path. Rolling back on that 'new problem' would
                # make a normal `touched` call refuse itself. The real commit point is the
                # touch write below, which DOES get the full validate-and-rollback treatment —
                # a genuine defect in the message's own shape (an unknown medium, a dangling
                # person_id) is already refused by the checks earlier in this function, before
                # the lock was even taken.
                messages.append({
                    "id": msg_id, "opp_id": opp_id, "channel_id": None,
                    "person_id": person_id, "direction": "outbound", "medium": medium,
                    "sent_on": date, "from": None, "to": to_label, "subject": None,
                    "body": "(recorded by `record.py touched` — no body captured)",
                    "source": "record.py touched", "variant": None, "answers": None,
                })
                save_atomic("messages", messages)
                print("  ✦ message %s recorded" % msg_id)
            else:
                print("  · message %s already recorded (completing the touch half)"
                     % msg_id)

            if args.inject_fault == "after-message":
                print("  ⚠️ TEST FAULT INJECTED — stopping before the touch half is "
                      "written. Re-run the SAME command to complete it.")
                return 1

        # ADR-031 B3 — the touch itself is a row on the TOP-LEVEL `touches` store now, never
        # an append to `opp["outreach"]` (which no longer exists — the retired-key guard
        # would refuse it). `mint_touch_id` mints `<person_id>-tN` the same way applications'
        # own `create auto` path mints `<opp_id>-aN`.
        touches_rows = load("touches")
        already = any(o.get("person_id") == person_id and o.get("opp_id") == opp_id
                     and o.get("date") == date and o.get("medium") == medium
                     and o.get("message_ref") == msg_id
                     for o in touches_rows)
        if already:
            print("  · touch already recorded — nothing further to do")
            return 0

        before_touches = snapshot("touches")
        pre_rc2, _, _, pre_problems2 = validate()
        new_touch_id = mint_touch_id(person_id, touches_rows)
        touches_rows.append({
            "id": new_touch_id, "person_id": person_id, "opp_id": opp_id, "channel_id": None,
            "object_person_id": None, "object_company_id": None,
            "status": "sent", "date": date, "medium": medium, "to": to_label,
            "outcome": "awaiting",
            # COMMS_CUTOVER (validate_data.py) requires touch_type/recipient_role on any row
            # dated 2026-08-02 or later — "unknown" is the enum's own explicit-unknown value,
            # never a guess at which one actually applies.
            "touch_type": args.touch_type or "unknown",
            "recipient_role": args.recipient_role or "unknown",
            "address_status": "unknown", "delivery": "unknown", "message_ref": msg_id,
        })
        save_atomic("touches", touches_rows)
        rc2, out2, err2, problems2 = validate()
        if rc2 != 0:
            added2 = new_problems(pre_problems2, problems2)
            if not (pre_rc2 != 0 and added2 == []):
                restore("touches", before_touches)
                print("  ⛔ REFUSED — the touch write broke the store; rolled back.")
                print("  " + "\n  ".join(_diagnostic_lines(rc2, out2, err2)))
                return 1
        print("  ✦ touch %s recorded on %s" % (new_touch_id, opp_id or person_id))
        # dev #479 / public #114 — propagate the just-landed touch to involvements/
        # next_action_owner/next_action_date, still inside this same lock hold.
        if not opp_id:
            print("  · no opportunity: no involvement to upsert (person-anchored touch) — "
                  "link later with `record.py involve %s --opp <opp_id>`" % person_id)
        for line in _propagate_touch(opp_id, person_id, date, recipient_role=args.recipient_role):
            print(line)
    finally:
        if not args.already_locked:
            release_lock()
    print("touched: %s -> %s via %s on %s — written atomically, validator clean"
         % (opp_id or "(no opportunity)", person_id, medium, date))
    return 0


def cmd_involve(args):
    """`record.py involve <person_id> --opp <opp_id> [--role <RECIPIENT_ROLE>]` — dev #686 /
    public #139 (E2): link a person to an opportunity LATER, as an explicit act.

    A person-anchored touch has no opportunity; when the relationship turns into a pursuit the
    link is an `involvements` row (person -> opp), written through the SAME `_upsert_involvement`
    a touch uses. Earlier person-anchored touches are NOT rewritten (back-filling `opp_id`
    would rewrite history and double-count a funnel), and the link is never inferred — only
    this verb makes it. An existing link is a no-op. After the link, `touched <opp> --to
    contact:<id>` stops refusing for want of an involvement."""
    person_id = args.rid
    if not person_id or args.rest:
        print("usage: involve <person_id> --opp <opp_id> [--role <role>]")
        return 2
    if not args.opp_id:
        print("⛔ REFUSED — involve requires --opp <opp_id>: the opportunity to link %r to."
              % person_id)
        return 1
    _vd = _validator_module()
    if args.recipient_role is not None and args.recipient_role not in _vd.RECIPIENT_ROLES:
        print("⛔ REFUSED — --role must be one of %s" % ", ".join(sorted(_vd.RECIPIENT_ROLES)))
        return 1
    prow = find(_load_or_empty("people"), person_id)
    if prow is None:
        print("⛔ REFUSED — %r resolves to no people record." % person_id)
        return 1
    if prow.get("status") == "merged":
        print("⛔ REFUSED — %r was merged into %r. Link the survivor: involve %s --opp %s"
              % (person_id, prow.get("merged_into"), prow.get("merged_into"), args.opp_id))
        return 1
    if find(load("opportunities"), args.opp_id) is None:
        print("⛔ REFUSED — --opp %r resolves to no opportunities record." % args.opp_id)
        return 1
    if any(r.get("person_id") == person_id and r.get("opp_id") == args.opp_id
           for r in _load_involvements()):
        print("involve: %s is already linked to %s — nothing to do." % (person_id, args.opp_id))
        return 0
    if args.dry_run:
        print("involve: %s -> %s" % (person_id, args.opp_id))
        print("  --dry-run: nothing written. (would link the person to the opportunity)")
        return 0
    if args.already_locked:
        if not lock_is_held():
            print("  REFUSED — --already-locked, but NOBODY holds the run lock.")
            return 1
    else:
        try:
            take_lock("record.py involve %s" % person_id, wait=args.wait)
        except LockError as e:
            print("  REFUSED — %s" % e)
            return 1
    try:
        # Re-read INSIDE the lock: the opportunity may have vanished between the check above
        # and the hold (the same re-read every write verb does).
        if find(load("opportunities"), args.opp_id) is None:
            print("  record vanished between read and lock — aborting.")
            return 1
        lines, outcome = _upsert_involvement(args.opp_id, person_id, args.recipient_role,
                                             create_only=True)
    finally:
        if not args.already_locked:
            release_lock()
    for line in lines:
        print(line)
    if outcome == "failed":
        return 1
    if outcome == "exists":
        print("involve: %s is already linked to %s — nothing to do." % (person_id, args.opp_id))
        return 0
    print("involve: %s -> %s — written atomically, validator clean; earlier touches by %s "
          "are unchanged" % (person_id, args.opp_id, person_id))
    return 0


def _company_feed_write(args, label, edit):
    """dev #751 -- ONE locked, validated, rollback-verified write of the COMPANIES store, and the
    CHANNELS store when `edit` changed it. `edit(company, channels, opportunities)` mutates in place
    and returns `(description_lines, channels_changed)` or raises `_Refused`; nothing has been
    written when it does. Returns the exit code.

    The stores are snapshotted, written atomically, and the validator is run; a write that
    INTRODUCES a problem (a set comparison against the problems before it, `new_problems`) restores
    both stores byte for byte and says so. `--dry-run` runs `edit` on deep copies and also applies the
    two feed invariants (`validate_data.check_feed_links`) to the result, so it predicts the write
    without touching a store. Refusals happen BEFORE the lock."""
    cid = args.rid
    if not cid or args.rest:
        print("usage: %s" % label)
        return 2
    _vd = _validator_module()
    try:
        companies = load("companies")
        channels = _load_or_empty("channels")
        opps = _load_or_empty("opportunities")
    except (OSError, ValueError) as e:
        print("⛔ REFUSED — a store cannot be read (%s); nothing written." % e)
        return 1
    if find(companies, cid) is None:
        print("⛔ REFUSED — %r resolves to no companies record." % cid)
        return 1
    shadow_c, shadow_ch = json.loads(json.dumps(companies)), json.loads(json.dumps(channels))
    try:
        lines, ch_changed = edit(find(shadow_c, cid), shadow_ch, opps)
    except _Refused as e:
        print("⛔ REFUSED — %s" % e)
        return 1
    problems = _vd.check_feed_links(shadow_c, shadow_ch)
    if problems:
        print("⛔ REFUSED — the result would break the feed invariants (nothing written):")
        print("  " + "\n  ".join("- " + p for p in problems))
        return 1
    if shadow_c == companies and not ch_changed:
        for line in lines:
            print(line)
        print("%s: nothing to change." % cid)
        return 0
    if args.dry_run:
        for line in lines:
            print(line)
        print("  --dry-run: nothing written.")
        return 0
    if args.already_locked:
        if not lock_is_held():
            print("  REFUSED — --already-locked, but NOBODY holds the run lock.")
            return 1
    else:
        try:
            take_lock("record.py %s %s" % (label.split()[0], cid), wait=args.wait)
        except LockError as e:
            print("  REFUSED — %s" % e)
            return 1
    try:
        # re-read INSIDE the lock, and re-run the edit on what is really there
        companies = load("companies")
        channels = _load_or_empty("channels")
        try:
            lines, ch_changed = edit(find(companies, cid), channels, opps)
        except _Refused as e:
            print("⛔ REFUSED — %s" % e)
            return 1
        snap_c, snap_ch = snapshot("companies"), snapshot("channels")
        pre_problems = validate()[3]
        save_atomic("companies", companies)
        if ch_changed:
            save_atomic("channels", channels)
        rc, out, err, post_problems = validate()
        added = new_problems(pre_problems, post_problems)
        if rc != 0 and (added is None or added):
            ok_c = restore("companies", snap_c)
            ok_ch = restore("channels", snap_ch) if (ch_changed and snap_ch is not None) else True
            print("⛔ the write left the stores invalid and was %s."
                  % ("ROLLED BACK (byte-identical)" if ok_c and ok_ch
                     else "NOT VERIFIABLY ROLLED BACK — restore companies.jsonl and channels.jsonl "
                          "from git"))
            print("  " + "\n  ".join(added if added else _diagnostic_lines(rc, out, err)))
            return 1
    finally:
        if not args.already_locked:
            release_lock()
    for line in lines:
        print(line)
    return 0


def cmd_ats(args):
    """`record.py ats <company_id> --url <careers or posting URL> | --none | --clear | --discover`
    -- dev #751 (sourcing-feeds, design §3.2). The candidate's verbs over `companies[].ats`:

      --url U       parse the URL (a string parse, never a fetch) and write `ats` with `source:
                    candidate`; a URL `ats_slug.parse` returns None for is REFUSED. Links or creates
                    the company's career-page channel in the same write.
      --none        `ats: null` -- decline a feed for this company; discovery never rewrites it.
      --clear       remove the key, so discovery may run again. The channel link is left alone.
      --discover    the engine's own path (`feed_poll.py`): parse the slug off the company's
                    `career_url` and its opportunities' `jd_url` / sighting `source_url`s. Writes only
                    an UNAMBIGUOUS result and never over an existing `ats` key; two distinct boards
                    print `ATS AMBIGUOUS` and write nothing.
    One mode per call; a refusal leaves both stores byte-identical."""
    import ats_slug as _ats
    modes = [m for m, on in (("--url", args.listing_url), ("--none", args.ats_none),
                             ("--clear", args.ats_clear), ("--discover", args.ats_discover)) if on]
    label = "ats <company_id> --url <url> | --none | --clear | --discover"
    if len(modes) != 1:
        print("⛔ REFUSED — ats takes exactly one of --url, --none, --clear, --discover "
              "(got %s)." % (", ".join(modes) or "none"))
        return 2
    mode = modes[0]
    today = datetime.date.today().isoformat()
    if mode == "--url":
        triple = _ats.parse(args.listing_url)
        if triple is None:
            print("⛔ REFUSED — %r names no board this engine can poll. The forms are "
                  "jobs.lever.co/<site>, jobs.eu.lever.co/<site>, jobs.ashbyhq.com/<name>, "
                  "boards.greenhouse.io/<token> and <tenant>.wd<N>.myworkdayjobs.com/<site> "
                  "(every other ATS stays on the browser); nothing written." % args.listing_url)
            return 1

    def edit(company, channels, opps):
        if mode == "--none":
            company["ats"] = None
            return ["%s: ats declined (null) -- discovery will not rewrite it" % company["id"]], False
        if mode == "--clear":
            company.pop("ats", None)
            return ["%s: ats key removed" % company["id"]], False
        if mode == "--discover":
            if "ats" in company:
                return ["ATS SKIPPED %s: already has an `ats` key (%s)"
                        % (company["id"], "declined" if company["ats"] is None else "set")], False
            d = _ats.discover(company, opps)
            if d.ambiguous:
                return ["ATS AMBIGUOUS %s: %s" % (company["id"], " | ".join(
                    "%s:%s" % (t[0], t[1]) for t in d.ambiguous))], False
            if d.found is None:
                return ["ATS NONE %s: no board URL on its career_url or postings" % company["id"]], False
            ch_id, how = _ats.apply_discovery(company, channels, d.found, d.source, today)
            return ["ATS %s %s:%s (%s) -> channel %s [%s]"
                    % (company["id"], d.found[0], d.found[1], d.source, ch_id, how)], how != "exists"
        ch_id, how = _ats.apply_discovery(company, channels, triple, "candidate", today)
        return ["ATS %s %s:%s (candidate) -> channel %s [%s]"
                % (company["id"], triple[0], triple[1], ch_id, how)], how != "exists"

    return _company_feed_write(args, label, edit)


def cmd_warm_lookup(args):
    """`record.py warm-lookup <company_id> --none-found [--on D]` -- dev #751 (design §4.2): the ONE
    stored fact of the warm path. "I looked for a person at this company and found nobody" has no other
    home (every other state is derived from the people, touches, drafts and applications stores).
    Writes `companies[].warm_lookup = {on, result: "none-found"}`; a person who WAS found is recorded
    with the existing verbs (a people row with `company_id`, then `record.py involve`)."""
    if not args.none_found:
        print("⛔ REFUSED — warm-lookup records only that you looked and found nobody: pass "
              "--none-found. A person you DID find goes in with a people row and `record.py "
              "involve <person> --opp <opp>`.")
        return 2
    try:
        on = _run_date(args).isoformat()
    except _Refused as e:
        print("⛔ REFUSED — %s" % e)
        return 1

    def edit(company, channels, opps):
        company["warm_lookup"] = {"on": on, "result": "none-found"}
        return ["%s: warm lookup recorded -- looked on %s, found nobody" % (company["id"], on)], False

    return _company_feed_write(args, "warm-lookup <company_id> --none-found [--on D]", edit)


BOARD_SIGHTING_USAGE = ("board-sighting <channel_id> --company \"<name as the board shows it>\" "
                        "--title \"<title>\" --url <the posting's OWN URL> [--company-id <id>] "
                        "[--vertical <enum>] [--seen-on YYYY-MM-DD] [--plan <plan_id>] [--dry-run] "
                        "[--already-locked]")


def _slug(text, limit=60):
    """A lower-case id fragment: runs of anything but a-z/0-9 become one `-`, trimmed, capped."""
    return re.sub(r"[^a-z0-9]+", "-", str(text or "").casefold()).strip("-")[:limit].strip("-")


def _board_sighting_plan(args, channels, companies, opps, applications, seen_on):
    """dev #765 (design-portfolio-boards.md section 4) -- decide what ONE role seen on a board needs, from
    the lists it is handed, and mutate none of them. Raises `_Refused` (nothing written) or returns

        {"company_id", "new_company": row | None, "opp_id", "new_opp": row | None,
         "sighting": {...} | None, "noop": bool, "company_how", "role_how"}

    It adds NO matching rule of its own: the company is `pipeline_index.company_candidates` (one hit is
    matched, several refuse and list the ids, none creates), and the role is `find_known_match` (an active
    match gets the sighting appended, an excluded one refuses, none creates). The board's own URLs are
    refused (`board_hosts.blocked_channel`): the engine never opens a manual-candidate site, and a role
    whose only address is the board's cannot be read."""
    import board_hosts as _bh
    import pipeline_index as _pidx
    _vd = _validator_module()
    chan = find(channels, args.rid)
    if chan is None:
        raise _Refused("%r resolves to no channels record." % args.rid)
    if chan.get("type") != "job-board":
        raise _Refused("%r is a %r channel; a board sighting is recorded against a `job-board` channel."
                       % (args.rid, chan.get("type")))
    url = (args.listing_url or "").strip()
    if _bh.host_of(url) is None:
        raise _Refused("--url must be the posting's own http(s) address (got %r)." % args.listing_url)
    blocked = _bh.blocked_channel(url, channels)
    if blocked is not None:
        raise _Refused("--url %r is on the board itself (%s, host %s): the engine never opens a "
                       "manual-candidate site, and a role whose only address is the board's cannot be "
                       "read. Give the posting's OWN outbound address instead (the employer's career "
                       "site or ATS page the board links to)."
                       % (url, blocked.get("id"), _bh.host_of(url)))
    title = (args.title_text or "").strip()
    sighting = {"channel_id": args.rid, "seen_on": seen_on, "source_url": url}
    # ---- the company ----
    new_company = None
    if args.company_id_arg:
        company = find(companies, args.company_id_arg)
        if company is None:
            raise _Refused("--company-id %r resolves to no companies record." % args.company_id_arg)
        company_id, company_how = company["id"], "matched"
    else:
        hits = _pidx.company_candidates(args.company_name, companies)
        if len(hits) > 1:
            raise _Refused("--company %r matches %d companies (%s); pass --company-id to say which."
                           % (args.company_name, len(hits), ", ".join(hits)))
        if hits:
            company_id, company_how = hits[0], "matched"
        else:
            if args.vertical_arg is None:
                raise _Refused("--company %r matches no company, so one would be created, and `vertical` is "
                               "required for it: pass --vertical <%s> (`other` would be a guess)."
                               % (args.company_name, "|".join(sorted(_vd.VERTICALS))))
            if args.vertical_arg not in _vd.VERTICALS:
                raise _Refused("--vertical %r is not one of {%s}" % (args.vertical_arg,
                                                                    ", ".join(sorted(_vd.VERTICALS))))
            company_id = _slug(args.company_name)
            if not company_id:
                raise _Refused("--company %r has no letters or digits to make an id from; pass "
                               "--company-id for an existing company." % args.company_name)
            if find(companies, company_id) is not None:
                raise _Refused("the id %r (made from --company %r) is already a company that the name did "
                               "not match; pass --company-id %s if it is the same company."
                               % (company_id, args.company_name, company_id))
            new_company = {"id": company_id, "name": args.company_name.strip(),
                           "vertical": args.vertical_arg, "status": "watching", "research_log": []}
            company_how = "created"
    # ---- the role ----
    hit = _pidx.find_known_match(opps, url=url, company_id=company_id, title=title,
                                 applications=applications)
    if hit and hit[2] == "excluded":
        raise _Refused(_pidx.describe_match(hit[0], hit[1]) + " Nothing was recorded: a role you already "
                       "passed on is not a new sighting.")
    if hit:
        row = hit[0]
        dup = any(isinstance(s, dict) and s.get("channel_id") == args.rid and s.get("seen_on") == seen_on
                  and _pidx._urls_equal(s.get("source_url"), url) for s in row.get("sightings") or [])
        return {"company_id": company_id, "new_company": new_company, "company_how": company_how,
                "opp_id": row["id"], "new_opp": None, "sighting": None if dup else sighting,
                "noop": dup and new_company is None, "role_how": "already recorded" if dup else
                "sighting appended (%s)" % hit[1]}
    plan_id, plan_err = _new_opportunity_plan(args.plan_id)
    if plan_err or not plan_id:
        raise _Refused(plan_err or "no active search plan sources role/contract, so this role has no "
                       "plan_id; add one, or pass --plan <plan_id>.")
    base = _slug("%s-%s" % (company_id, title)) or _slug(company_id) or "role"
    opp_id, n = base, 1
    taken = {o.get("id") for o in opps}
    while opp_id in taken:
        n += 1
        opp_id = "%s-%d" % (base, n)
    new_opp = {"id": opp_id, "company_id": company_id, "title": title, "status": "backlog",
               "stage": "sourced", "verdict": "undecided", "jd_url": url,
               "location": {"declared": "none stated"}, "sightings": [sighting],
               # the candidate owns the pursue/pass decision; `your_move.classify_opportunities` holds the
               # role in `triaging` (system-owned) until the daily run's triage step has read it
               "next_action_owner": _profile_mod().owner_token(),
               "plan_id": plan_id, "plan_assigned_on": datetime.date.today().isoformat()}
    return {"company_id": company_id, "new_company": new_company, "company_how": company_how,
            "opp_id": opp_id, "new_opp": new_opp, "sighting": None, "noop": False,
            "role_how": "created"}


def _apply_board_sighting(plan, companies, opps):
    """Apply `plan` to the lists `_board_sighting_plan` was planned against (in place)."""
    if plan["new_company"] is not None:
        companies.append(plan["new_company"])
    if plan["new_opp"] is not None:
        opps.append(plan["new_opp"])
    elif plan["sighting"] is not None:
        find(opps, plan["opp_id"]).setdefault("sightings", []).append(plan["sighting"])


def cmd_board_sighting(args):
    """`record.py board-sighting <channel_id> --company NAME --title TITLE --url POSTING_URL ...` -- dev #765
    (design-portfolio-boards.md section 4). Record ONE role the candidate saw on a job board.

    The company is matched, created or refused as ambiguous; the role either gets a sighting appended or is
    created in the 0.70.0 triaging shape (`backlog` / `sourced` / `undecided`, `jd_url` the posting's own
    address, `location.declared: none stated`, pay and posting date absent = NOT CAPTURED), so the
    daily run's triage reads it before the candidate is asked. A company created and a role created land in
    ONE locked, validated, rollback-verified write, or neither does. The firm link is not written: the
    sighting's `channel_id` is the board and the board's `portfolio_of` is the firm, derived by
    `portfolio_boards.backers_of`. This verb never fetches `--url`, and refuses one on a board host.
    A refusal leaves every store byte-identical."""
    label = "usage: " + BOARD_SIGHTING_USAGE
    if not args.rid or args.rest:
        print(label)
        return 2
    missing = [f for f, v in (("--title", args.title_text), ("--url", args.listing_url),
                              ("--company or --company-id", args.company_name or args.company_id_arg)) if not v]
    if missing:
        print("⛔ REFUSED — %s required.\n%s" % (", ".join(missing), label))
        return 2
    try:
        seen_on = _run_date_value(args.seen_on, "--seen-on")
    except _Refused as e:
        print("⛔ REFUSED — %s" % e)
        return 1
    try:
        channels, companies, opps = (_load_or_empty("channels"), load("companies"), load("opportunities"))
        applications = _load_or_empty("applications")
    except (OSError, ValueError) as e:
        print("⛔ REFUSED — a store cannot be read (%s); nothing written." % e)
        return 1
    shadow_co, shadow_op = json.loads(json.dumps(companies)), json.loads(json.dumps(opps))
    try:
        plan = _board_sighting_plan(args, channels, shadow_co, shadow_op, applications, seen_on)
    except _Refused as e:
        print("⛔ REFUSED — %s" % e)
        return 1
    summary = ("board-sighting %s: company %s (%s), role %s (%s)"
               % (args.rid, plan["company_id"], plan["company_how"], plan["opp_id"], plan["role_how"]))
    if plan["noop"]:
        print(summary)
        print("  nothing to change.")
        return 0
    _apply_board_sighting(plan, shadow_co, shadow_op)
    if args.dry_run:
        print(summary)
        row_after = find(shadow_op, plan["opp_id"])
        introduced = introduced_row_violations(
            "opportunities", None if plan["new_opp"] is not None else find(opps, plan["opp_id"]), row_after)
        if introduced:
            print("  ⛔ a REAL (non-dry-run) write of this would be REFUSED (nothing is written):")
            print("  " + "\n  ".join("- " + m for m in introduced))
            return 1
        pre_rc, _, _, pre_problems = validate()
        rc, out, err, problems = dry_run_validate("opportunities", shadow_op, extra={"companies": shadow_co})
        added = new_problems(pre_problems, problems) if rc != 0 else []
        if rc != 0 and (added is None or added):
            print("  ⛔ a REAL (non-dry-run) write of this would be REFUSED and rolled back.")
            print("  " + "\n  ".join(added if added else _diagnostic_lines(rc, out, err)))
            return 1
        print("  --dry-run: nothing written.")
        print("  ✅ dry-run validated clean against the same validator a real write runs.")
        return 0
    if args.already_locked:
        if not lock_is_held():
            print("  REFUSED — --already-locked, but NOBODY holds the run lock.")
            return 1
    else:
        try:
            take_lock("record.py board-sighting %s" % args.rid, wait=args.wait)
        except LockError as e:
            print("  REFUSED — %s" % e)
            return 1
    try:
        # re-read INSIDE the lock, and re-plan on what is really there
        channels, companies, opps = (_load_or_empty("channels"), load("companies"), load("opportunities"))
        applications = _load_or_empty("applications")
        try:
            plan = _board_sighting_plan(args, channels, companies, opps, applications, seen_on)
        except _Refused as e:
            print("⛔ REFUSED — %s" % e)
            return 1
        if plan["noop"]:
            print(summary)
            print("  nothing to change.")
            return 0
        before_row = None if plan["new_opp"] is not None else json.loads(json.dumps(find(opps, plan["opp_id"])))
        _apply_board_sighting(plan, companies, opps)
        introduced = introduced_row_violations("opportunities", before_row, find(opps, plan["opp_id"]))
        if introduced:
            print("⛔ REFUSED — " + "; ".join(introduced))
            return 1
        snap_c, snap_o = snapshot("companies"), snapshot("opportunities")
        pre_problems = validate()[3]
        if plan["new_company"] is not None:
            save_atomic("companies", companies)
        save_atomic("opportunities", opps)
        rc, out, err, post_problems = validate()
        added = new_problems(pre_problems, post_problems)
        if rc != 0 and (added is None or added):
            ok_o = restore("opportunities", snap_o)
            ok_c = restore("companies", snap_c) if plan["new_company"] is not None else True
            print("⛔ the write left the stores invalid and was %s."
                  % ("ROLLED BACK (byte-identical)" if ok_o and ok_c
                     else "NOT VERIFIABLY ROLLED BACK — restore companies.jsonl and opportunities.jsonl "
                          "from git"))
            print("  " + "\n  ".join(added if added else _diagnostic_lines(rc, out, err)))
            return 1
    finally:
        if not args.already_locked:
            release_lock()
    print(summary)
    import portfolio_boards as _pb
    firms = _pb.backers_of(plan["company_id"], companies, channels, opps)
    print("  backed by: %s" % (", ".join("%s (%s)" % (f["firm_id"], f["via"]) for f in firms)
                               if firms else "no firm is linked (this board is not a portfolio board, or "
                                             "no backing is stated)"))
    return 0


CHANNEL_CATALOG_USAGE = ("channel-catalog add <entry> | --kind portfolio|curated|swept-board|alert-sender [--attach <channel_id>] "
                         "[--firm <company_id>] [--on YYYY-MM-DD] [--dry-run] [--already-locked]\n"
                         "       channel-catalog take <channel_id> | keep <channel_id> [--on YYYY-MM-DD] "
                         "[--dry-run] [--already-locked]")


def cmd_channel_catalog(args):
    """`record.py channel-catalog add|take|keep ...` -- dev #769 (design-channel-catalog.md section 5; jobsearch
    0.76.0). Turn shipped catalog boards on, and settle a disagreement between a board you edited and the catalog.

    `add` COPIES an entry into `channels.jsonl` (plus the firm's `companies` row for a portfolio entry) and stamps
    the row (`channel_catalog.py` owns the planning; the stamp is the `plays.py --adopt` mechanism). NOTHING IS ON
    BY DEFAULT: this verb is the only way a catalog board reaches a profile. A board the user already holds (same
    channel id, or overlapping `board_hosts`) is refused with the `--attach` form, never duplicated, and a row with
    no stamp is never written (except by `--attach`, the user's own command naming it). `take` / `keep` resolve a
    conflict the SessionStart reconcile asked about, and refuse a row stamped by a NEWER catalog revision.

    The whole call is ONE locked, validated, rollback-verified write across the stores it touches (channels, and
    companies / asks when they change), or none. Exit 0 when everything requested is on, 2 when any entry was
    skipped (or the arguments are wrong), 1 when the write was refused (nothing written). A refusal leaves every
    store byte-identical."""
    label = "usage: " + CHANNEL_CATALOG_USAGE
    verb = args.rid
    if verb not in ("add", "take", "keep"):
        print(label)
        return 2
    import channel_catalog as _cc
    try:
        today = _run_date_value(args.on_date, "--on")
    except _Refused as e:
        print("⛔ REFUSED — %s" % e)
        return 1
    try:
        catalog = _cc.load_catalog()
    except _cc.CatalogError as e:
        print("⛔ REFUSED — %s; nothing written." % e)
        return 1
    entries = _cc.by_id(catalog)
    if verb == "add":
        if bool(args.rest) == bool(args.cc_kind) or len(args.rest) > 1:
            print(label)
            return 2
        if args.rest and args.rest[0] not in entries:
            print("⛔ REFUSED — %r is not a channel catalog entry (have: %s)."
                  % (args.rest[0], ", ".join(sorted(entries))))
            return 1
        ids = list(args.rest) if args.rest else [e["id"] for e in catalog["entries"] if e["kind"] == args.cc_kind]
        if args.cc_kind and (args.cc_attach or args.cc_firm):
            print("⛔ REFUSED — --attach and --firm name ONE board or ONE company; use them with a single "
                  "entry, not --kind.")
            return 1
    else:
        if len(args.rest) != 1 or args.cc_kind or args.cc_attach or args.cc_firm:
            print(label)
            return 2
    try:
        stores = {"channels": load("channels"), "companies": _load_or_empty("companies"),
                  "asks": _load_or_empty("asks")}
    except (OSError, ValueError) as e:
        print("⛔ REFUSED — a store cannot be read (%s); nothing written." % e)
        return 1

    def build(rows):
        """Mutate `rows` (a {store: list} copy) and return (changed stores, printable lines, exit code)."""
        if verb == "add":
            results = _cc.plan_add(catalog, ids, rows["channels"], rows["companies"], today,
                                   attach=args.cc_attach, firm_arg=args.cc_firm)
            lines, skipped = [], False
            for res in results:
                lines.append("  %s: %s" % (res["entry"], res["why"]))
                if res["status"] in ("write", "attach") and res["row"].get("board_url"):
                    lines.append("      open it at %s" % res["row"].get("board_url"))
                if res["status"] == "skipped":
                    skipped = True
            _cc.apply_add(results, rows["channels"], rows["companies"])
            changed = []
            if any(r["status"] in ("write", "attach") for r in results):
                changed = ["channels"] + (["companies"] if any(r["new_firm"] for r in results) else [])
            # an adoption ask (dev #774) that this `--attach` answers is resolved in the SAME write
            for r in results:
                if r["status"] == "attach":
                    for a in rows["asks"]:
                        if a.get("id") == _cc.ADOPT_ASK_PREFIX + r["channel_id"] and not a.get("resolved_on"):
                            a["resolved_on"], a["resolution"] = today, "attached"
                            if "asks" not in changed:
                                changed.append("asks")
            return changed, lines, (2 if skipped else 0)
        new_row, new_asks, summary = _cc.plan_resolve(catalog, rows["channels"], rows["asks"], args.rest[0], verb, today)
        idx = next(i for i, r in enumerate(rows["channels"]) if r.get("id") == args.rest[0])
        rows["channels"][idx] = new_row
        asks_changed = new_asks != rows["asks"]
        rows["asks"] = new_asks
        return ["channels"] + (["asks"] if asks_changed else []), ["  " + summary], 0

    shadow = json.loads(json.dumps(stores))
    try:
        changed, lines, rc = build(shadow)
    except _cc.Refused as e:
        print("⛔ REFUSED — %s" % e.args[0])
        return 1
    head = "channel-catalog %s (catalog revision %d)" % (verb, catalog["revision"])
    if not changed:
        print(head)
        print("\n".join(lines))
        print("  nothing to change.")
        return rc
    if args.dry_run:
        print(head)
        print("\n".join(lines))
        pre_problems = validate()[3]
        rc_v, out, err, problems = dry_run_validate(
            "channels", shadow["channels"], extra={k: shadow[k] for k in ("companies", "asks") if k in changed})
        added = new_problems(pre_problems, problems) if rc_v != 0 else []
        if rc_v != 0 and (added is None or added):
            print("  ⛔ a REAL (non-dry-run) write of this would be REFUSED and rolled back.")
            print("  " + "\n  ".join(added if added else _diagnostic_lines(rc_v, out, err)))
            return 1
        print("  --dry-run: nothing written.")
        print("  ✅ dry-run validated clean against the same validator a real write runs.")
        return 0
    if args.already_locked:
        if not lock_is_held():
            print("  REFUSED — --already-locked, but NOBODY holds the run lock.")
            return 1
    else:
        try:
            take_lock("record.py channel-catalog %s" % verb, wait=args.wait)
        except LockError as e:
            print("  REFUSED — %s" % e)
            return 1
    try:
        # re-read INSIDE the lock, and re-plan on what is really there
        live = {"channels": load("channels"), "companies": _load_or_empty("companies"),
                "asks": _load_or_empty("asks")}
        try:
            changed, lines, rc = build(live)
        except _cc.Refused as e:
            print("⛔ REFUSED — %s" % e.args[0])
            return 1
        if not changed:
            print(head)
            print("\n".join(lines))
            print("  nothing to change.")
            return rc
        snaps = {s: snapshot(s) for s in changed}
        pre_problems = validate()[3]
        for s in ("companies", "channels", "asks"):          # the firm row first: portfolio_of must resolve
            if s in changed:
                save_atomic(s, live[s])
        rc_v, out, err, post_problems = validate()
        added = new_problems(pre_problems, post_problems)
        if rc_v != 0 and (added is None or added):
            ok = all(restore(s, snaps[s]) for s in changed)
            print("⛔ the write left the stores invalid and was %s."
                  % ("ROLLED BACK (byte-identical)" if ok
                     else "NOT VERIFIABLY ROLLED BACK — restore %s from git"
                          % ", ".join(STORES[s] for s in changed)))
            print("  " + "\n  ".join(added if added else _diagnostic_lines(rc_v, out, err)))
            return 1
    finally:
        if not args.already_locked:
            release_lock()
    print(head)
    print("\n".join(lines))
    return rc


SOURCE_USAGE = ("source on <id> [--anyway] [--dry-run] | source off <id> [--dry-run]\n"
                "       source list | source keep-mine <id>   [--on YYYY-MM-DD] [--already-locked]")


def _config_path():
    return os.path.join(ROOT, "config.json")


def _read_config_strict():
    """config.json as a dict, or raises ValueError/OSError. An unreadable config is never an empty one."""
    with open(_config_path(), encoding="utf-8") as fh:
        cfg = json.load(fh)
    if not isinstance(cfg, dict):
        raise ValueError("config.json is not a JSON object")
    return cfg


def _remote_mode():
    try:
        return ((_read_config_strict().get("sync") or {}).get("mode")) == "remote"
    except (OSError, ValueError):
        return False


def cmd_source(args):
    """`record.py source on|off <id>`, `source list`, `source keep-mine <id>` -- dev #774 (design-source-catalog.md
    section 7.2; jobsearch 0.76.0). THE ONLY WRITER of a source's on/off state: the text path, the
    /jobsearch:sourcing command and the mod's panel button all run exactly this.

    `<id>` is a channel row (stamped or yours), a catalog entry (turn it on: the copy-and-stamp `channel-catalog add`),
    or `company-feeds`. OFF sets `relationship_status: retired` -- the one bit every reader already honours -- and
    stores what it found in the declared `prior_relationship_status` (R2) so ON puts it back exactly; `company-feeds`
    writes `sourcing.feeds.enabled`. A recruiter, referral, company-site or unknown id is REFUSED, naming the right verb.

    ONE locked, validated, rollback-verified write across the stores it touches (channels, companies, asks, and
    config.json), or none. Exit 0: done, or already in that state (a no-op). 2: refused (nothing written). 1: the write
    failed validation and was rolled back. `--dry-run` prints and writes nothing. In a `remote` profile it says that a
    machine on an engine older than 0.76.0 cannot see the switch, and that the change reaches other machines only
    after the next end-of-run commit and push (review B1)."""
    label = "usage: " + SOURCE_USAGE
    verb = args.rid
    if verb not in ("on", "off", "list", "keep-mine"):
        print(label)
        return 2
    import channel_catalog as _cc
    try:
        today = _run_date_value(args.on_date, "--on")
    except _Refused as e:
        print("⛔ REFUSED — %s" % e)
        return 2
    if verb == "list":
        if args.rest:
            print(label)
            return 2
        import sources as _sources
        try:
            sys.stdout.write(_sources.render_text(_sources.report(ROOT, datetime.date.fromisoformat(today))))
        except _sources.SourcesError as e:
            print("NOT CHECKED: %s" % e)
            return 1
        return 0
    if len(args.rest) != 1 or (verb != "on" and args.src_anyway):
        print(label)
        return 2
    ident = args.rest[0]
    catalog = None
    try:
        catalog = _cc.load_catalog()
    except _cc.CatalogError as e:
        print("  NOT CHECKED: %s -- a source you already hold can still be turned on or off; a catalog entry cannot "
              "be turned on until it is readable." % e)
    try:
        stores = {"channels": load("channels"), "companies": _load_or_empty("companies"), "asks": _load_or_empty("asks")}
        config = _read_config_strict()
    except (OSError, ValueError) as e:
        print("⛔ REFUSED — a store cannot be read (%s); nothing written." % e)
        return 2

    def build(rows, cfg):
        """(changed store names, printable lines, plan or None, noop?) -- raises `_cc.Refused`."""
        if verb == "keep-mine":
            new_asks = _cc.plan_keep_mine(rows["asks"], ident, today)
            rows["asks"] = new_asks
            return ["asks"], ["  %s: the catalog question is resolved; the row is exactly as it was" % ident], None
        plan = _cc.plan_source_toggle(catalog, rows["channels"], rows["companies"], cfg, ident, verb == "on", today,
                                      anyway=args.src_anyway)
        rows["channels"], rows["companies"] = plan["channels"], plan["companies"]
        cfg.clear()
        cfg.update(plan["config"])
        # an adoption ask this turn-on answers is resolved in the same write (`--attach` does the same)
        return list(plan["changed"]), list(plan["lines"]), plan

    shadow, shadow_cfg = json.loads(json.dumps(stores)), json.loads(json.dumps(config))
    try:
        changed, lines, plan = build(shadow, shadow_cfg)
    except _cc.Refused as e:
        print("⛔ REFUSED — %s" % e.args[0])
        return 2

    def extras(plan_, cfg_):
        out = []
        row = plan_["row"] if plan_ else None
        if verb == "on" and row is not None:
            if row.get("board_url"):
                out.append("      open it at %s" % row["board_url"])
            if row.get("query_template"):
                try:
                    import profile as _profile
                    import sources as _sources
                    out.append("      this will search: %s" % _sources.fill_query(row["query_template"], _profile.load(), cfg_))
                except Exception as exc:                              # noqa: BLE001 -- loud, not fatal
                    out.append("      this will search: NOT CHECKED (%s)" % exc)
        if _remote_mode() and not (plan_ and plan_["noop"]):
            if verb == "off":
                out.append("  NOTE (remote profile): a machine still on a jobsearch engine older than 0.76.0 cannot see this "
                           "switch and keeps running this source until it upgrades.")
            if verb in ("on", "off"):
                out.append("  NOTE (remote profile): this change reaches your other machines only after the next end-of-run "
                           "commit and push; it takes effect elsewhere after the next run.")
        return out

    head = "source %s %s" % (verb, ident)
    if plan is not None and plan["noop"]:
        print(head)
        print("\n".join(lines))
        print("  nothing to change.")
        return 0
    if args.dry_run:
        print(head)
        print("\n".join(lines + extras(plan, shadow_cfg)))
        changed_stores = [s for s in changed if s in ("channels", "companies", "asks")]
        if changed_stores:
            pre_problems = validate()[3]
            rc_v, out, err, problems = dry_run_validate(
                "channels", shadow["channels"], extra={k: shadow[k] for k in ("companies", "asks") if k in changed})
            added = new_problems(pre_problems, problems) if rc_v != 0 else []
            if rc_v != 0 and (added is None or added):
                print("  ⛔ a REAL (non-dry-run) write of this would be REFUSED and rolled back.")
                print("  " + "\n  ".join(added if added else _diagnostic_lines(rc_v, out, err)))
                return 1
        print("  --dry-run: nothing written.")
        return 0
    if args.already_locked:
        if not lock_is_held():
            print("  REFUSED — --already-locked, but NOBODY holds the run lock.")
            return 2
    else:
        try:
            take_lock("record.py source %s" % verb, wait=args.wait)
        except LockError as e:
            print("  REFUSED — %s" % e)
            return 2
    try:
        live = {"channels": load("channels"), "companies": _load_or_empty("companies"), "asks": _load_or_empty("asks")}
        try:
            live_cfg = _read_config_strict()
            changed, lines, plan = build(live, live_cfg)
        except _cc.Refused as e:
            print("⛔ REFUSED — %s" % e.args[0])
            return 2
        except (OSError, ValueError) as e:
            print("⛔ REFUSED — config.json cannot be read (%s); nothing written." % e)
            return 2
        if plan is not None and plan["noop"]:
            print(head)
            print("\n".join(lines))
            print("  nothing to change.")
            return 0
        snaps = {s: snapshot(s) for s in changed if s in STORES}
        cfg_before = None
        if "config" in changed:
            with open(_config_path(), "rb") as fh:
                cfg_before = fh.read()
        pre_problems = validate()[3]
        for s in ("companies", "channels", "asks"):          # the firm row first: portfolio_of must resolve
            if s in changed:
                save_atomic(s, live[s])
        if "config" in changed:
            import _atomic
            _atomic.write_json(_config_path(), live_cfg)
        rc_v, out, err, post_problems = validate()
        added = new_problems(pre_problems, post_problems)
        verified = True
        if "config" in changed:
            import config_keys as _ck
            try:
                now_on, _problem = _ck.feeds_enabled(_read_config_strict())
                verified = (now_on == (verb == "on"))
            except (OSError, ValueError):
                verified = False
        if (rc_v != 0 and (added is None or added)) or not verified:
            ok = all(restore(s, snaps[s]) for s in snaps)
            if cfg_before is not None:
                try:
                    with open(_config_path(), "wb") as fh:
                        fh.write(cfg_before)
                except OSError:
                    ok = False
            print("⛔ the write left the stores invalid and was %s."
                  % ("ROLLED BACK (byte-identical)" if ok else "NOT VERIFIABLY ROLLED BACK — restore from git"))
            print("  " + "\n  ".join(added if added else _diagnostic_lines(rc_v, out, err)))
            return 1
    finally:
        if not args.already_locked:
            release_lock()
    print(head)
    print("\n".join(lines + extras(plan, live_cfg)))
    return 0


def _run_date_value(value, flag):
    """An ISO date from `value` (default: today); refuses a malformed one, never coerces it."""
    if value is None:
        return datetime.date.today().isoformat()
    if not _ISO_DATE.match(value):
        raise _Refused("%s must be an ISO date (YYYY-MM-DD), got %r" % (flag, value))
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        raise _Refused("%s %r is not a calendar date" % (flag, value))
    return value


def cmd_answered(args):
    """`record.py answered <inbound-message-id | contact:<person-id>> --on <date> --via
    <medium> [--opp <opp_id>]` — cell 4's own action line (design §3/§15.3): records that the
    OWNER replied, appending the outbound message whose `answers` names the inbound it
    responds to. `target` is either a bare message id (an inbound row already in
    messages.jsonl — its own opp_id/channel_id/person_id are inherited) or `contact:<id>` — a
    touch ref, for cell 4's own 'the outreach[] row alone ... no message body in the store'
    case (a LinkedIn or pre-harvest reply with no message row to point `answers` at)."""
    target = args.rid
    if not target or args.rest:
        print("usage: answered <inbound-message-id | contact:<person-id>> --on <date> "
              "--via <medium> [--opp <opp_id>]")
        return 2
    date = args.on_date or datetime.date.today().isoformat()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        print("⛔ REFUSED — --on must be an ISO date (YYYY-MM-DD), got %r" % date)
        return 1
    _vd = _validator_module()
    medium = args.via_medium
    if not medium or medium not in _vd.MEDIA:
        print("⛔ REFUSED — --via must be one of %s" % ", ".join(sorted(_vd.MEDIA)))
        return 1
    # dev #479 / public #114 — `--role` is shared with `touched` (same flag, same
    # RECIPIENT_ROLES vocabulary) so `answered`'s own propagation below can fill an
    # involvement's path_type through plays.ROLE_TO_PATH too; validated the same way.
    if args.recipient_role is not None and args.recipient_role not in _vd.RECIPIENT_ROLES:
        print("⛔ REFUSED — --role must be one of %s" % ", ".join(sorted(_vd.RECIPIENT_ROLES)))
        return 1

    messages0 = load("messages")
    cm = re.match(r"^contact:(.+)$", target)
    if cm:
        person_id = cm.group(1)
        answers, opp_id, channel_id = None, args.opp_id, None
        if not opp_id:
            for row in _load_involvements():
                if (row.get("person_id") == person_id and row.get("channel_id")
                        and not row.get("opp_id")):
                    channel_id = row["channel_id"]
                    break
            if not channel_id:
                print("⛔ REFUSED — contact:%s names no opportunity (--opp) and resolves to "
                      "no channel-only involvement either — a message must anchor to "
                      "SOMETHING." % person_id)
                return 1
    else:
        inbound = find(messages0, target)
        if inbound is None:
            print("⛔ REFUSED — %r resolves to no message in data/messages.jsonl, and is not "
                  "`contact:<person-id>` either." % target)
            return 1
        if inbound.get("direction") != "inbound":
            print("⛔ REFUSED — %r is not an inbound message (direction=%r) — 'answered' "
                  "records a REPLY to something THEY sent." % (target, inbound.get("direction")))
            return 1
        answers = inbound.get("id")
        opp_id, channel_id, person_id = (inbound.get("opp_id"), inbound.get("channel_id"),
                                         inbound.get("person_id"))

    msg_id = mint_message_id(opp_id or channel_id, person_id, date)
    if any(m.get("id") == msg_id for m in messages0):
        print("  · message %s already recorded — nothing further to do" % msg_id)
        return 0
    to_label = _person_name(person_id) or person_id or "unknown"

    # ⭐ public #103 — THE FIX. This is the worst shape on record: `answered --dry-run` used to
    # write to `messages`, which is append-only (§15.3) — the resulting row could then never
    # be removed except by hand-editing the store, which the engine's own rules forbid. Every
    # refusal check above (target resolves, medium valid, not already recorded) has already
    # run, so this is the same point the write-shaped verbs stop at.
    if args.dry_run:
        print("answered: %s -> outbound message %s (medium=%s, on=%s)"
             % (target, msg_id, medium, date))
        print("  --dry-run: nothing written.")
        return 0

    if args.already_locked:
        if not lock_is_held():
            print("  REFUSED — --already-locked, but NOBODY holds the run lock.")
            return 1
    else:
        try:
            take_lock("record.py answered %s" % target, wait=args.wait)
        except LockError as e:
            print("  REFUSED — %s" % e)
            return 1
    try:
        messages = load("messages")
        if any(m.get("id") == msg_id for m in messages):
            print("  · message %s already recorded — nothing further to do" % msg_id)
            return 0
        before = snapshot("messages")
        pre_rc, _, _, pre_problems = validate()
        messages.append({
            "id": msg_id, "opp_id": opp_id, "channel_id": channel_id, "person_id": person_id,
            "direction": "outbound", "medium": medium, "sent_on": date,
            "from": None, "to": to_label, "subject": None,
            "body": "(recorded by `record.py answered` — no body captured)",
            "source": "record.py answered", "variant": None, "answers": answers,
        })
        save_atomic("messages", messages)
        rc, out, err, problems = validate()
        if rc != 0:
            added = new_problems(pre_problems, problems)
            if not (pre_rc != 0 and added == []):
                restore("messages", before)
                print("  ⛔ REFUSED — this reply broke the store; rolled back.")
                print("  " + "\n  ".join(_diagnostic_lines(rc, out, err)))
                return 1
        # dev #479 / public #114 — propagate this reply to involvements/next_action_owner/
        # next_action_date, still inside this same lock hold.
        for line in _propagate_touch(opp_id, person_id, date, recipient_role=args.recipient_role):
            print(line)
    finally:
        if not args.already_locked:
            release_lock()
    print("answered: %s -> outbound message %s recorded (medium=%s, on=%s) — written "
         "atomically, validator clean" % (target, msg_id, medium, date))
    return 0


# ── design-inbound-resolution.md §2 (ADR-029) — the shared inbound message writer ──────────
#
# THE ONE PUBLIC INBOUND WRITER. Before this, the only code that ever appended an inbound
# `messages` row was `reconcile.py --harvest`'s own private `existing.append(...)` +
# `write_jsonl` — no lock, no validator, no rollback. `append_message` is that write, promoted:
# `cmd_received` below is its CLI face (`record.py received ...`); `reconcile.py --harvest`
# calls this function IN-PROCESS instead of keeping a second copy of the append+validate+
# rollback dance (§2's own words: "one inbound writer path and one rollback").

def _stored_source_twin(row, stored):
    """The id of a stored message whose NORMALIZED mail-tag `source` equals `row`'s, else None
    (dev #704 / public #154, D1). `None` for a row whose source is not a mail tag."""
    _vd = _validator_module()
    src = row.get("source")
    if not _vd.is_mail_tag(src):
        return None
    key = _vd.normalize_source_tag(src)
    for m in stored:
        if m.get("id") != row.get("id") and _vd.normalize_source_tag(m.get("source")) == key:
            return m.get("id")
    return None


def append_message(row, already_locked=False, wait=DEFAULT_WAIT):
    """Append `row` (a full messages.jsonl dict, `id` already minted by the caller
    deterministically) under the lock, validator-run, rolled back byte-identical on a new
    problem — the exact `cmd_answered` shape, generalised to a caller-supplied row rather than
    one this function builds itself.

    Idempotent by id: a second call with the SAME `id` (the deterministic mint from `--source`
    means the SAME source mints the SAME id) is a no-op, not a duplicate and not a re-validate
    — this is what makes a re-swept uid safe (design §5).

    ⭐ dev #704 / public #154 (D1) — ALSO idempotent by SOURCE, for a mail tag. The ATS and
    `received` ids are a hash of the source (`in-<sha1(source)[:12]>`), so a stored row whose
    source was written wrapped (`gmail:a:b'101'`) and a fresh write of the same message with the
    clean source (`gmail:a:101`) mint DIFFERENT ids, and the id check alone admitted the
    duplicate. A row whose `source` is a mail tag is therefore also a no-op when a stored row's
    NORMALIZED source equals its own; the message names the stored id. Gated on the mail-tag
    prefix, because LinkedIn thread URLs legitimately repeat across rows (dev #686 P3).

    Returns `(returncode, message)`: 0 with the store landed (or already there) clean, 1
    refused or rolled back. Locking mirrors every other write here: `already_locked=True`
    VERIFIES `lock_is_held()` rather than trusting the caller; the plain path takes and
    releases its own short-lived hold."""
    mid = row.get("id")
    _stored = load("messages")
    if any(m.get("id") == mid for m in _stored):
        return 0, "  · message %s already recorded — nothing further to do" % mid
    _twin = _stored_source_twin(row, _stored)
    if _twin is not None:
        return 0, ("  · message %s already recorded as %s (same source) — nothing further to do"
                   % (mid, _twin))

    if already_locked:
        if not lock_is_held():
            return 1, ("  REFUSED — --already-locked, but NOBODY holds the run lock.\n"
                       "  Take it first (runlock.py --take), or drop the flag.")
    else:
        try:
            take_lock("record.py received %s" % mid, wait=wait)
        except LockError as e:
            return 1, "  REFUSED — %s" % e
    try:
        messages = load("messages")
        if any(m.get("id") == mid for m in messages):
            return 0, "  · message %s already recorded — nothing further to do" % mid
        _twin = _stored_source_twin(row, messages)
        if _twin is not None:
            return 0, ("  · message %s already recorded as %s (same source) — nothing further "
                       "to do" % (mid, _twin))
        before = snapshot("messages")
        pre_rc, _, _, pre_problems = validate()
        messages.append(row)
        save_atomic("messages", messages)
        rc, out, err, problems = validate()
        if rc != 0:
            added = new_problems(pre_problems, problems)
            if not (pre_rc != 0 and added == []):
                restore("messages", before)
                return 1, ("  ⛔ REFUSED — this message broke the store; rolled back.\n  "
                           + "\n  ".join(_diagnostic_lines(rc, out, err)))
    finally:
        if not already_locked:
            release_lock()
    return 0, ("  ✦ message %s recorded — written atomically, validator clean" % mid)


_TIMESTAMP_ARG_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?$")


def cmd_received(args):
    """`record.py received --opp <opp_id> | --channel <channel_id> | --person <person_id>
    --from <addr> [--to <addr>] --on <ISO ts> --subject <text> --body-file <path>
    --source <token> [--medium email] [--resolves <app_id> --resolved-by
    req-id|url|company-single] [--already-locked]`

    design-inbound-resolution.md §2 — the ONE public writer for an INBOUND message
    (ADR-029). `id` is minted from `--source` (`in-<sha1(source)[:12]>`), deterministic, so a
    second write of the same source is idempotent by construction (see `append_message`).
    dev #686: with `--person` alone (no --opp, no --channel) the message anchors on its person
    and the id also folds in `--on`, so two inbounds in one thread are two messages.
    `--body-file`, never `--body`: an ATS body is thousands of characters and argv is the
    wrong place."""
    if args.rest:
        print("usage: received --opp <opp_id> | --channel <channel_id> | --person <id> "
              "--from <addr> [--to <addr>] --on <ISO ts> --subject <text> "
              "--body-file <path> --source <token> [--medium email] "
              "[--resolves <app_id> --resolved-by req-id|url|company-single]")
        return 2
    if not args.source_token:
        print("⛔ REFUSED — --source is required — a body with no provenance cannot be "
              "re-verified against the mailbox.")
        return 1
    if not args.on_date or not _TIMESTAMP_ARG_RE.match(args.on_date):
        print("⛔ REFUSED — --on must be an ISO date or 'YYYY-MM-DD HH:MM[:SS]' timestamp, "
              "got %r" % args.on_date)
        return 1
    if args.opp_id and args.channel_id:
        print("⛔ REFUSED — pass --opp OR --channel, never both.")
        return 1
    if not args.opp_id and not args.channel_id and not args.resolves:
        # dev #686 / public #139 (rule 1a) — a resolving --person is the THIRD anchor: a
        # message to/from a person about no role and no channel belongs to the relationship.
        if not (args.person_id_arg and find(_load_or_empty("people"), args.person_id_arg)):
            print("⛔ REFUSED — needs an anchor: --opp <opp_id>, --channel <channel_id>, or "
                  "--person <person_id> naming an existing people record (at least one, "
                  "unless --resolves derives one). A message anchored to nothing is "
                  "unfindable.%s"
                  % ((" (--person %r resolves to no people record.)" % args.person_id_arg)
                     if args.person_id_arg else ""))
            return 1
    if not args.body_file:
        print("⛔ REFUSED — --body-file is required — an ATS body belongs in a file, never "
              "argv.")
        return 1
    try:
        with open(args.body_file, encoding="utf-8") as fh:
            body = fh.read()
    except OSError as e:
        print("⛔ REFUSED — could not read --body-file %r: %s" % (args.body_file, e))
        return 1
    # `email-reply` is the default: MEDIA is an OUTREACH taxonomy (validate_data.py's own
    # comment) and bare 'email' is legal only for direction='third-party' — an inbound ATS/
    # employer message is a reply-channel event, not a third party, so it needs a real MEDIA
    # value. Checked BEFORE the write (the touched/answered convention) rather than left to the
    # validator's rollback, so a bad --medium refuses immediately with the legal set named.
    medium = args.medium or "email-reply"
    if medium not in _validator_module().MEDIA:
        print("⛔ REFUSED — --medium must be one of %s"
              % ", ".join(sorted(_validator_module().MEDIA)))
        return 1
    if bool(args.resolves) != bool(args.resolved_by):
        print("⛔ REFUSED — --resolves and --resolved-by are required TOGETHER, or not at "
              "all (ADR-030: the tier that matched is recorded).")
        return 1

    opp_id = args.opp_id
    if args.resolves:
        app = find(load("applications"), args.resolves)
        if app is None:
            print("⛔ REFUSED — --resolves %r does not resolve to any applications row."
                  % args.resolves)
            return 1
        derived_opp = app.get("opp_id")
        if opp_id and opp_id != derived_opp:
            print("⛔ REFUSED — --opp %r conflicts with --resolves %r's own opp_id %r — a "
                  "message cannot point at one role while resolving another's application."
                  % (opp_id, args.resolves, derived_opp))
            return 1
        opp_id = derived_opp
        if args.channel_id:
            print("⛔ REFUSED — --resolves names an application (always role-anchored); "
                  "--channel is refused alongside it.")
            return 1

    # dev #686 / public #139 (P3) — a PERSON-ANCHORED inbound's id is minted from the source AND
    # the message timestamp. Two inbounds in one LinkedIn thread share one `--source` (the
    # thread URL), so a source-only mint gave both the same id and the second was silently
    # swallowed as "already recorded" — the person axis would then be dated by the older
    # message. Role- and channel-anchored inbounds keep the source-only mint, which is what
    # `reconcile.py --harvest` mints for the same mailbox uid.
    if not opp_id and not args.channel_id:
        mid_seed = "%s|%s" % (args.source_token, args.on_date)
    else:
        mid_seed = args.source_token
    mid = "in-%s" % hashlib.sha1(mid_seed.encode("utf-8")).hexdigest()[:12]
    row = {
        "id": mid, "opp_id": opp_id, "channel_id": args.channel_id,
        "person_id": args.person_id_arg, "direction": "inbound",
        "medium": medium, "sent_on": args.on_date,
        "from": args.from_addr, "to": args.to_token, "subject": args.subject, "body": body,
        "source": args.source_token, "variant": None, "answers": None,
        "resolves": args.resolves, "resolved_by": args.resolved_by,
    }

    # ⭐ public #103's own shape, closed for THIS verb too — `received` is its own
    # early-return branch in main(), reached and returned from before main()'s shared
    # dry-run gate ever runs, exactly like `touched`/`answered` were. Every refusal check
    # above has already run, so this is the same point those two verbs stop at.
    if args.dry_run:
        already = any(m.get("id") == mid for m in load("messages"))
        print("received: %s -> inbound message %s (source=%s)"
             % (opp_id or args.channel_id, mid, args.source_token))
        print("  --dry-run: nothing written. (%s)"
             % ("message already recorded" if already
                else "would record message %s" % mid))
        return 0

    rc, msg = append_message(row, already_locked=args.already_locked, wait=args.wait)
    print(msg)
    if rc == 0:
        print("received: %s -> inbound message %s recorded (source=%s)"
             % (opp_id or args.channel_id, mid, args.source_token))
    return rc


def _touch_requirement_lines(_vd):
    """dev #686 / public #139 (rule 3) — the CONDITIONAL touch requirements, as printable lines,
    read from `validate_data.py`'s own NAMED constants (never a typed copy), so a caller can
    build a valid `create --file touches` row, or run `touched`, from `fields` or `--help`
    alone. The `required:` line above only lists the unconditional four; these are the rules
    that used to surface one failed write at a time."""
    return [
        "  CONDITIONALLY REQUIRED (enforced by validate_data.py; the names below are its own "
        "constants):",
        "    status=sent                    requires: %s (non-empty), %s (ISO date)"
        % (_vd.SENT_REQUIRES_FIELD, _vd.SENT_REQUIRES_DATE_FIELD),
        "    date >= %s and status=sent  requires: %s"
        % (_vd.COMMS_CUTOVER, ", ".join(_vd.COMMS_REQUIRED_FIELDS)),
        "    medium %s*                  requires: %s"
        % (_vd.EMAIL_MEDIUM_PREFIX, _vd.EMAIL_REQUIRES_FIELD),
        "    (`record.py touched` fills every one of these; touch_type is set with "
        "--touch-type, default 'unknown')",
    ]


def _help_epilog():
    """The `--help` footer: the person-anchored `touched` form and `involve`, with the touch
    requirements named. Fails open to a shorter footer — a broken validator import must never
    make `--help` itself crash."""
    lines = [
        "touched / involve (dev #686 / public #139):",
        "  touched <opp_id> --to contact:<person-id> --medium <MEDIA> [--on D] [--role R] "
        "[--touch-type T]",
        "  touched          --to contact:<person-id> --medium <MEDIA> [--on D] [--role R] "
        "[--touch-type T]",
        "      the second form (no opp_id) records a PERSON-ANCHORED touch: a relationship with",
        "      a person who has no opportunity and no channel. --to, --medium and --on are",
        "      checked before the lock and before any write.",
        "  involve <person-id> --opp <opp_id> [--role R]",
        "      link a person to an opportunity later; earlier person-anchored touches are "
        "left as they were.",
        "  create <id> '<json>' --file people --reuse",
        "      get-or-create: an identical LinkedIn, or an identical email AND name, reuses "
        "the existing person (nothing written);",
        "      an email-only match is refused and listed as a candidate.",
        "",
        "sourcing screen (dev #713-#716 / public #142-#145) -- each stores what a script computed:",
        "  create <id> '<json>' --from-item <capture-role item id>",
        "      copies the pay, posting date and setting the sweep's ROLE line carried "
        "(listed_pay, posted, location.declared)",
        "      onto the new role; a slot the sweep did not read stays absent.",
        "  screened <opp_id> [--on D]                 re-run the minimal screen and store it",
        "  lean <opp_id> --lean pursue|pass|ask --line \"<one line>\" [--jd-file P] [--on D]",
        "  listed-pay <opp_id> --none-shown | --stated R[;R] | --estimate R[;R] [--pay-source S]",
        "      R is <min>-<max>/<yr|mo|day|hr>/<CUR> or <min>+/<unit>/<CUR>",
        "  posted <opp_id> --document-date D | --ats-date D | --board-date D | --shown-age N | "
        "--unknown",
    ]
    try:
        lines.append("")
        lines.append("touches — what a row needs:")
        lines.extend(_touch_requirement_lines(_validator_module()))
    except Exception:                                            # noqa: BLE001
        pass
    return "\n".join(lines)


def _reuse_people(args):
    """`create <id> '<json>' --file people --reuse` — dev #686 / public #139 (P1, rule 2).

    Returns an exit code when the call is FINISHED here (reused, or refused), or None to fall
    through to the ordinary create. The matching is `people.find_reusable` — the engine's ONE
    people matcher (its normalizers and ADR-031 §3's strength rule): an identical normalized
    LinkedIn, or an identical normalized email AND name. An email-only hit is REFUSED and listed
    as a candidate in `people.py --duplicates`' own shape, never reused silently. Nothing is
    written on a reuse or a refusal."""
    if len(args.rest) != 1 or not args.rid:
        print("usage: create <id> '<json object for the person>' --file people --reuse")
        return 2
    try:
        payload = json.loads(args.rest[0])
    except ValueError as e:
        print("⛔ REFUSED — the record is not valid JSON: %s" % e)
        return 1
    if not isinstance(payload, dict):
        print("⛔ REFUSED — the record must be a JSON object, got %s." % type(payload).__name__)
        return 1
    import people as _people
    probe = dict(payload)
    probe["id"] = args.rid
    found = _people.find_reusable(_load_or_empty("people"), probe)
    if found["contradictions"]:
        print("⛔ REFUSED — %s. That would be two people under one id; pick a new id (nothing "
              "written)." % "; ".join(found["contradictions"]))
        return 1
    survivors = {}
    for row, how in found["hits"]:
        survivors.setdefault(row.get("id"), []).append(how)
    if len(survivors) > 1:
        print("⛔ REFUSED — the candidate matches %d DIFFERENT people (%s); reusing one would be a "
              "guess that merges two. Decide with `people.py --duplicates` and `record.py "
              "merge-person` (nothing written)."
              % (len(survivors), "; ".join("%s on %s" % (k, "+".join(v))
                                           for k, v in sorted(survivors.items()))))
        return 1
    if survivors:
        sid, hows = next(iter(survivors.items()))
        print("person: %s reused (matched on %s)" % (sid, hows[0]))
        print("  nothing written. Next: `brief.py --address \"<draft title>\" --to contact:%s`"
              % sid)
        return 0
    email_only = [c for c in found["candidates"] if c["reason"].startswith("same email")]
    if email_only:
        print("⛔ REFUSED — an existing person shares this email but not the name; an email "
              "alone is a shared inbox or a typo, not an identity (ADR-031 §3). Nothing "
              "written. Candidate(s):")
        for c in email_only:
            print("  %s <-> %s — %s" % (c["a"], c["b"], c["reason"]))
        print("  Same person? Use that id (its name differs on file) and edit the name if it "
              "is wrong. Different person (a shared inbox)? Create WITHOUT --reuse and set "
              "not_same_as on both rows.")
        return 1
    args.reuse_notes = ["person: %s created" % args.rid]
    for c in found["candidates"]:
        args.reuse_notes.append("  ℹ️ possible duplicate (advisory, not reused): %s <-> %s — %s"
                                % (c["a"], c["b"], c["reason"]))
    return None


class _Refused(Exception):
    """A sourcing-screen verb refused its input before the lock; `main()` prints `⛔ REFUSED — `
    plus the message and exits 1. Nothing has been written when this is raised."""


class _Usage(Exception):
    """Wrong arguments for a sourcing-screen verb; `main()` prints the message and exits 2."""


_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LEAN_VALUES = ("pursue", "pass", "ask")
# `listed_pay.source` per state (design §3.1): a board's estimate can only come from the board's
# own widget; an ATS API / JSON-LD read can only be the employer's own figure.
PAY_SOURCES_STATED = ("listing-text", "ats-api", "json-ld", "candidate")
PAY_SOURCES_NONE_SHOWN = ("listing-text", "candidate")


def _engine_version():
    """The plugin version this engine ships as, read from its own plugin.json -- stamped into a
    stored `screen` so a later reader knows which rules computed it. "0.0.0" if unreadable."""
    try:
        with open(os.path.join(os.path.dirname(ENGINE_SCRIPTS), ".claude-plugin", "plugin.json"),
                  encoding="utf-8") as fh:
            return json.load(fh).get("version") or "0.0.0"
    except (OSError, ValueError):
        return "0.0.0"


def _run_date(args):
    """The date a sourcing-screen write takes: `--on` (an ISO date) or today. Refuses a malformed
    one -- a date is never coerced."""
    if args.on_date is None:
        return datetime.date.today()
    if not _ISO_DATE.match(args.on_date):
        raise _Refused("--on must be an ISO date (YYYY-MM-DD), got %r" % args.on_date)
    try:
        return datetime.date.fromisoformat(args.on_date)
    except ValueError:
        raise _Refused("--on %r is not a calendar date" % args.on_date)


def _known_match_for(rows, new_row, extra_urls=()):
    """The pipeline row a role being created duplicates, as `(row, basis, kind)`, or None
    (dev #728 / public #158): by URL first (the row's `jd_url`, its sightings, the item's own URL),
    then by company + title -- `pipeline_index.find_known_match`, the one matcher."""
    import pipeline_index as _pidx
    apps = _load_or_empty("applications")
    urls = [new_row.get("jd_url")] + [s.get("source_url") for s in (new_row.get("sightings") or [])
                                       if isinstance(s, dict)] + list(extra_urls)
    for u in urls:
        if u:
            hit = _pidx.find_known_match(rows, url=u, applications=apps)
            if hit:
                return hit
    return _pidx.find_known_match(rows, company_id=new_row.get("company_id"),
                                  title=new_row.get("title"), applications=apps)


def _append_sightings(row_id, sightings, already_locked=False, wait=None):
    """Append each sighting to `row_id` THROUGH `record.py append` (the one writer: the lock, the
    validator and the rollback all apply) -- a subprocess on this interpreter, `record.py` having no
    in-process dispatch. Returns None, or the reason one failed (the ones before it stay: each is
    its own validated write)."""
    for sg in sightings:
        cmd = [sys.executable, os.path.abspath(__file__), "append", row_id, "sightings",
               json.dumps(sg)]
        if already_locked:
            cmd.append("--already-locked")
        if wait is not None:
            cmd += ["--wait", str(wait)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            return "record.py append to %s exited %d: %s" % (
                row_id, r.returncode, " ".join((r.stdout + r.stderr).split())[-300:])
    return None


def _new_opportunity_plan(explicit_id):
    """`(plan_id | None, error | None)` for a freshly created opportunity (ADR-031 B4, design §17,
    §26.5): the one active search plan sourcing role/contract, or the `--plan` the caller named. The error
    is set only when a plan is named that cannot serve, or more than one could (the refusal names every
    candidate); with no active sourcing plan at all both are None and the required-field check refuses
    the missing `plan_id` the way it refuses any other. Shared by `create` and `board-sighting`."""
    _plans_rows, _e, _present = _plans_mod().load(ROOT)
    _cfg_for_plan = {}
    try:
        import profile as _profile_for_plan
        _cfg_for_plan = _profile_for_plan.config()
    except Exception:                                           # noqa: BLE001 — advisory only
        pass
    resolved, err = _plans_mod().resolve_sourcing_plan(_plans_rows, _cfg_for_plan,
                                                       explicit_id=explicit_id)
    if resolved:
        return resolved, None
    if explicit_id or len(_plans_mod().sourcing_candidates(_plans_rows)) > 1:
        return None, err or "no search plan could be resolved for this role (pass --plan <plan_id>)"
    return None, None


def _link_from_item(args, new_row, rows, match, item):
    """The `create --from-item` branch that finds the role ALREADY in the pipeline (dev #728 /
    public #158; design §5.3, R8): link the item's listing and its siblings onto that row instead of
    creating a second one. Returns the exit code. Prints `LINKED <item> -> <row id> (<basis>)`, or
    `NEARER LISTING of passed <id>: <place> (<state>)` and links nothing."""
    import pipeline_index as _pidx
    row, basis, kind = match
    item = item or {}
    own_loc = (new_row.get("location") or {}).get("primary") if isinstance(
        new_row.get("location"), dict) else None
    listings = [(item.get("ref") or new_row.get("jd_url"), own_loc)]
    listings += [(s.get("url"), s.get("location")) for s in (item.get("siblings") or [])]
    if kind == "excluded":
        # R8: a nearer listing of a role you PASSED on surfaces; it is not auto-closed.
        try:
            import profile as _pf
            nearer, place, state = _pf.nearer_listing(
                _pidx.listing_places(row), [loc for _u, loc in listings], _pf.load())
        except (OSError, ValueError, KeyError):
            nearer, place, state = False, None, None
        if nearer:
            print("NEARER LISTING of passed %s: %s (%s)" % (row.get("id"), place, state))
            print("  %r was NOT created or linked, and %s stays claimable: this listing is closer than "
                  "anywhere %s was listed. To decide it fresh, create it again with --force (the "
                  "pair is recorded in distinct_from)." % (args.rid, args.from_item, row.get("id")))
            return 1
    sg0 = next((s for s in (new_row.get("sightings") or []) if isinstance(s, dict)), None)
    if sg0 is None or not sg0.get("channel_id") or not sg0.get("seen_on"):
        print("⛔ REFUSED — linking %s onto %s needs the JSON's sightings[0] (channel_id, seen_on) to "
              "attribute the listing; none was given." % (args.from_item, row.get("id")))
        return 1
    have = {s.get("source_url") for s in (row.get("sightings") or []) if isinstance(s, dict)}
    have.add(row.get("jd_url"))
    todo = []
    for url, loc in listings:
        if not url or url in have or any(_pidx._urls_equal(url, h) for h in have if h):
            continue
        todo.append(dict({"channel_id": sg0["channel_id"], "seen_on": sg0["seen_on"],
                          "source_url": url}, **({"location": loc} if loc else {})))
        have.add(url)
    print("%s: link listing(s) onto %s (%s)" % (args.rid, row.get("id"), basis))
    if args.dry_run:
        print("  --dry-run: nothing written. Would append %d sighting(s) to %s and close %s as "
              "linked:%s." % (len(todo), row.get("id"), args.from_item, row.get("id")))
        return 0
    err = _append_sightings(row.get("id"), todo, already_locked=args.already_locked, wait=args.wait)
    if err:
        print("⛔ REFUSED — %s. %s stays claimable." % (err, args.from_item))
        return 1
    import deferred as _deferred_mod
    _deferred_mod.close_item(args.from_item, "linked:%s" % row.get("id"))
    print("LINKED %s -> %s (%s)" % (args.from_item, row.get("id"), basis))
    return 0


def location_replace(old, new, rid):
    """`(location, error)` -- `record.py set <id> location '<json>'` on an opportunity (dev #727 /
    public #159, design-location-screen.md §4.3 as amended by R5). `set` replaces the WHOLE
    `location` object, so this compares the stored object with the replacement:

      * the stored location is `setting_source: inferred` (the script inferred onsite at capture):
          - the replacement OMITS `setting_source` and CHANGES the type -> the setting was
            overturned: the same write adds `location.inference_overturned =
            {was: <old type>, to: <new type>, on: <today>}`;
          - it OMITS `setting_source` and keeps the type (onsite) -> the setting is now STATED: the
            flag is simply gone, nothing is recorded;
          - it KEEPS `setting_source` and changes the type -> REFUSED: the flag cannot outlive the
            inference it describes;
          - it carries no `type` -> REFUSED: an overturn names the setting it lands on.
      * a stored location that is not inferred: a replacement carrying `setting_source` is REFUSED
        (provenance is written by the capture script, never typed), and so is an
        `inference_overturned` that is not the stored one. A stored `inference_overturned` the
        replacement omits is CARRIED FORWARD: a whole-object replace must not erase the record that
        a guess was once overturned.

    No dotted `location.type` path exists (R5). Returns `(new location, None)` or `(None, why)`;
    every refusal names this exact command."""
    cmd = "`record.py set %s location '<json>'`" % (rid or "<id>")
    if not isinstance(new, dict):
        return new, None
    old = old if isinstance(old, dict) else {}
    out = dict(new)
    if old.get("setting_source") == "inferred":
        if "type" not in new:
            return None, ("the stored location.type was INFERRED (onsite); the replacement names no "
                          "type. Replace the whole object with the setting the posting states, "
                          "without setting_source: %s." % cmd)
        if "setting_source" in new:
            if new.get("type") != old.get("type"):
                return None, ("location.setting_source is 'inferred' but the type changes from %s to "
                              "%s: the flag cannot outlive the inference. Overturn it by replacing "
                              "the whole object WITHOUT setting_source: %s."
                              % (old.get("type"), new.get("type"), cmd))
            return out, None
        if new.get("type") != old.get("type"):
            out["inference_overturned"] = {"was": old.get("type"), "to": new.get("type"),
                                           "on": datetime.date.today().isoformat()}
        return out, None
    if "setting_source" in new:
        return None, ("location.setting_source is written only by the capture script when it "
                      "infers a setting (`create --from-item`); this location was not inferred, so "
                      "it is not typed by hand. Replace the object without it: %s." % cmd)
    if new.get("inference_overturned") != old.get("inference_overturned"):
        if "inference_overturned" in new:
            return None, ("location.inference_overturned is written only by the overturn of an "
                          "inferred setting, never typed: %s without it." % cmd)
    if "inference_overturned" in old and "inference_overturned" not in new:
        out["inference_overturned"] = old["inference_overturned"]
    return out, None


def copy_capture_item_facts(new_row, item_id, rid=None):
    """`(copied, error)` -- `create --from-item <deferred id>` (dev #715 / public #143, dev #716 /
    public #142; design §2). Copy what `deferred.py --add-roles` PARSED from the sweep's ROLE line,
    held on the `capture-role` item's `role` object, onto the opportunity being created:
    `role.listed_pay` -> `listed_pay`, `role.posted` -> `posted`, `role.location_declared` ->
    `location.declared`. The shapes are the ones `record.py listed-pay` / `posted` store, so the
    model never re-types a value a script already parsed, and a captured role does not screen
    NOT-CAPTURED for a pay its own sweep read.

    ⭐ jobsearch 0.70.0 (dev #727 / public #159; design-location-screen.md §4): `role.location_listed`
    (the ROLE line's `location=` text, verbatim) is copied to `location.primary`, and a posting whose
    setting the sweep read as `none stated` at a CONCRETE PLACE (`places.parse_place` reads it) is
    recorded as `location.type: onsite` with `location.setting_source: inferred`. This is the one
    place a captured row is born, so the inference is a recorded rule, not a type the model picked
    and nobody noted. It is OURS (the publisher convention reserves `TELECOMMUTE` for remote work
    and has no value for hybrid, so an unmarked posting may be hybrid; at a place proven outside every
    commute radius hybrid is as infeasible as onsite, which is why a removal on an inference is safe).
      * `none stated` + a place -> `type: onsite`, `setting_source: inferred`.
      * `none stated` + no place (or no text) -> `type` stays ABSENT; the screen asks (NEEDS-REVIEW).
      * `none stated` + a `location.type` in the JSON -> REFUSED: the sweep read no setting, so a type
        the model chose would be an unflagged guess. Omit it; or create the row, then replace the
        location with the JD's wording (`record.py set <id> location '<json>'`, which records the
        overturn).
      * `?` (not read) or a verbatim setting -> as before: the JSON states the type, nothing is
        inferred, and `unresolved` is never touched.
      * A `location.primary` in the JSON that differs from `location_listed` is refused (one value,
        stated once). An item queued before 0.70.0 has no `location_listed`; the JSON's is used.

    A slot the sweep did not read (`?`) is `None` on the item and is NOT copied: the field stays
    ABSENT (NOT CAPTURED / age unknown), never `none-shown` and never an invented date. A field the
    payload already carries must agree with the item (one fact, stated once): a different value is
    an `error`, never a silent overwrite. An item with no `role` object (queued before 0.67.0)
    copies nothing and is not an error. `new_row` is mutated in place; `copied` names the fields."""
    import deferred as _deferred
    try:
        items = {r.get("id"): r for r in _deferred.replay(_deferred.load())}
    except (OSError, ValueError) as e:
        return [], "the deferred queue cannot be read (%s)" % e
    item = items.get(item_id)
    if item is None:
        return [], ("no deferred item %r (`deferred.py --claimable` lists the pending ones)"
                    % item_id)
    if item.get("kind") != _deferred.KIND_CAPTURE:
        return [], ("deferred item %r is a %r item; --from-item takes a %r item"
                    % (item_id, item.get("kind"), _deferred.KIND_CAPTURE))
    copied = []
    # dev #751 (B7) -- a FEED item names the company-site channel it came from. It is copied into
    # sightings[0] when the JSON leaves it out, and a different channel the model supplies is
    # REFUSED: the channel is a recorded fact, so feed yield is measurable.
    feed_channel = item.get("channel_id")
    if feed_channel:
        sgs = new_row.get("sightings")
        first = sgs[0] if isinstance(sgs, list) and sgs and isinstance(sgs[0], dict) else None
        if first is not None:
            have_ch = first.get("channel_id")
            if have_ch and have_ch != feed_channel:
                return [], ("the JSON's sightings[0].channel_id is %s but deferred item %r came from "
                            "channel %s (a company feed). One value, stated once: omit "
                            "sightings[0].channel_id and the script copies it."
                            % (json.dumps(have_ch), item_id, json.dumps(feed_channel)))
            if not have_ch:
                first["channel_id"] = feed_channel
                copied.append("sightings[0].channel_id")
    role = item.get("role")
    if not isinstance(role, dict):
        return copied, None
    wanted = []
    if role.get("listed_pay") is not None:
        wanted.append(("listed_pay", role["listed_pay"]))
    if role.get("posted") is not None:
        wanted.append(("posted", role["posted"]))
    declared = role.get("location_declared")
    listed = role.get("location_listed")
    for field, value in wanted:
        if field in new_row and new_row[field] != value:
            return [], ("the JSON carries %s=%s but deferred item %r says %s. One value, stated "
                        "once." % (field, json.dumps(new_row[field]), item_id, json.dumps(value)))
        if field not in new_row:
            new_row[field] = value
            copied.append(field)
    if declared is not None:
        loc = new_row.get("location")
        if loc is not None and not isinstance(loc, dict):
            return [], "the JSON's location is not an object; cannot add location.declared"
        have = (loc or {}).get("declared")
        if have is not None and have != declared:
            return [], ("the JSON carries location.declared=%s but deferred item %r says %s. One "
                        "value, stated once." % (json.dumps(have), item_id, json.dumps(declared)))
        if have is None:
            new_row["location"] = dict(loc or {}, declared=declared)
            copied.append("location.declared")
    if listed is not None:
        loc = new_row.get("location")
        if loc is not None and not isinstance(loc, dict):
            return [], "the JSON's location is not an object; cannot add location.primary"
        have = (loc or {}).get("primary")
        if have is not None and have != listed:
            return [], ("the JSON carries location.primary=%s but deferred item %r says %s. One "
                        "value, stated once: omit location.primary and the script copies it."
                        % (json.dumps(have), item_id, json.dumps(listed)))
        if have is None:
            new_row["location"] = dict(loc or {}, primary=listed)
            copied.append("location.primary")
    if declared == _deferred.SETTING_NONE_STATED:
        import places as _places
        loc = new_row.get("location")
        loc = loc if isinstance(loc, dict) else {}
        if "type" in loc:
            return [], ("the sweep read no setting on this posting (setting=\"none stated\"), so "
                        "location.type=%s would be a guess nobody can tell from a stated setting. "
                        "Omit location.type and the script infers it from the place (recorded as "
                        "location.setting_source: inferred); or create the row without it and then "
                        "replace the location with the JD's wording: `record.py set %s location "
                        "'<the whole location object, without setting_source>'` -- that write "
                        "records the overturn."
                        % (json.dumps(loc["type"]), rid or "<id>"))
        if _places.parse_place(loc.get("primary")):
            new_row["location"] = dict(loc, type="onsite", setting_source="inferred")
            new_row["location"].setdefault("remote", False)
            copied.append("location.type (inferred onsite)")
    return copied, None


def _sourcing_mutation(args, rec):
    """`(desc, apply)` for one of `SOURCING_OPS` against the opportunity `rec` (dev #713-#716 /
    public #142-#145; design §3.1, §3.3, §3.6, §3.7). `apply(row)` sets ONE top-level field; the
    shared write path in `main()` does the lock, the introduced-only rules, the validator and the
    rollback. Raises `_Refused` / `_Usage` before anything is written.

    What each stores is COMPUTED here, from the stored row and the profile, never transcribed:

      screened     `{on, verdict, rules, engine}` from `profile.screen_rules`, evaluated INSIDE
                   `apply` against the row as re-read under the lock.
      lean         `{lean, line, on, signals}`. `line` is required, one line, at most
                   `deferred.ROLES_FIELD_CAP` characters (refused, never truncated). `signals` is
                   what `profile.match_signals` finds in the title, the company row and (when
                   `--jd-file` is given) the JD text. An unreadable `screen.likely_pass_signals`
                   list REFUSES the write: a lean stored with `signals: []` because the list could
                   not be read would claim nothing matched.
      listed-pay   `{state, [ranges], source, captured_on}` from `--none-shown`, `--stated` or
                   `--estimate`; ranges parse through `profile.parse_pay_ranges`, strictly.
      posted       `{date, source, recorded_on}`; `--shown-age N` computes `run date - N`
                   (`board-relative`), `--document-date` is the only writer of
                   `profile-document-date`.
    """
    import profile as _pf
    op = args.op
    if args.rest:
        raise _Usage("usage: %s <opp_id> %s" % (op, {
            "screened": "[--on D]",
            "lean": "--lean pursue|pass|ask --line \"<one line>\" [--jd-file PATH] [--on D]  "
                    "(--lean may be omitted on an age-flagged recruiter role: ask, and on a "
                    "role whose title is below screen.title_floor: pursue when pay clears, "
                    "otherwise ask)",
            "listed-pay": "--none-shown | --stated R[;R] | --estimate R[;R] [--pay-source S] "
                          "[--on D]",
            "posted": "--document-date D | --shown-age N | --ats-date D | --board-date D | "
                      "--unknown [--on D]"}[op]))
    on = _run_date(args)
    on_iso = on.isoformat()

    if op == "screened":
        engine = _engine_version()

        def apply(r):
            profile = _pf.load()
            result = _pf.screen_rules(r, profile, load("opportunities"),
                                      applications=_load_or_empty("applications"),
                                      channels=_load_or_empty("channels"), today=on)
            r["screen"] = {"on": on_iso, "verdict": result["verdict"],
                           "rules": dict(result["rules"]), "engine": engine,
                           "title_keys": _pf.title_keys(profile),
                           # dev #739 / #740 (0.73.0, R2): the sibling hash of the comp inputs, so
                           # a later decision or engagement edit makes this screen stale.
                           "comp_keys": _pf.comp_keys(r, profile)}
            if result.get("engagement_source"):
                # dev #740 / public #160: the pay was routed on an engagement INFERRED from the
                # title; the stored result says so, as it does for an inferred setting.
                r["screen"]["engagement_source"] = result["engagement_source"]
            if result.get("setting_source"):
                # dev #727 / public #159: the role was screened as onsite on an INFERENCE; the
                # stored result says so, so a later reader never mistakes it for a stated setting.
                r["screen"]["setting_source"] = result["setting_source"]
            # dev #722 / public #156 (R1, R2): a re-screen that finds the title BELOW the floor
            # attaches the computed lean hit to a lean the run already recorded -- the hit only,
            # never the choice (an explicit lean wins) -- and drops a title-floor hit the
            # screen no longer supports. A role with no lean yet gets it from `lean`.
            ln = r.get("lean")
            if isinstance(ln, dict):
                kept = [h for h in (ln.get("signals") or [])
                        if not (isinstance(h, dict) and h.get("id") == _pf.TITLE_FLOOR_LEAN_ID)]
                tf = _pf.title_floor_lean(r["screen"], profile)
                if tf:
                    kept.append(tf[2])
                if kept != (ln.get("signals") or []):
                    ln["signals"] = kept
        return "screened (the minimal screen, re-run and stored; on %s)" % on_iso, apply

    if op == "lean":
        lean_choice, line = args.lean_choice, args.line_text
        # ⭐ dev #716 / public #142 (design §6.2): an over-age retained-search role (or a recruiter
        # role of unknown age) defaults to `ask` with the age line's first move as its line. A
        # DEFAULT is what `--lean` omitted means -- an explicit `--lean` is the run's own reading of
        # the JD and is stored as given. Read from the STORED screen (`screened` runs first).
        # ⭐ dev #722 / public #156 (owner decision R1): a BELOW-FLOOR title never removes; the lean
        # it implies is COMPUTED from the stored screen's comp verdict (`profile.title_floor_lean`),
        # stored as a hit beside the signal hits, and is the DEFAULT when `--lean` is omitted. An
        # explicit `--lean` still wins (the 0.67.0 rule). The age flag, when both apply, defaults first.
        try:
            title_lean = _pf.title_floor_lean(rec.get("screen"), _pf.load())
        except (OSError, ValueError) as e:
            raise _Refused("the profile cannot be read, so the title floor's lean cannot be "
                           "computed: %s" % e)
        if lean_choice is None:
            first_move = _pf.age_flag_first_move(rec.get("screen"))
            if first_move:
                lean_choice = "ask"
                if line is None or not line.strip():
                    line = "FIRST MOVE: %s" % first_move
            elif title_lean:
                lean_choice = title_lean[0]
                if line is None or not line.strip():
                    line = title_lean[1]
        if lean_choice not in LEAN_VALUES:
            raise _Refused("--lean must be one of %s" % ", ".join(LEAN_VALUES))
        args.lean_choice, args.line_text = lean_choice, line
        if line is None or not line.strip():
            raise _Refused("--line is required: one line saying why (the lean without a reason "
                           "is a verdict nobody can check)")
        import deferred as _deferred
        if "\n" in line or "\r" in line:
            raise _Refused("--line must be a single line")
        if len(line) > _deferred.ROLES_FIELD_CAP:
            raise _Refused("--line is %d characters; the cap is %d (shorten it -- it is never "
                           "truncated for you)" % (len(line), _deferred.ROLES_FIELD_CAP))
        jd_text = ""
        if args.jd_file:
            try:
                with open(args.jd_file, encoding="utf-8") as fh:
                    jd_text = fh.read()
            except OSError as e:
                raise _Refused("--jd-file %r cannot be read: %s" % (args.jd_file, e))
        try:
            signals = (_pf.config().get("screen") or {}).get("likely_pass_signals")
        except (OSError, ValueError) as e:
            raise _Refused("config.json cannot be read, so likely-pass signals cannot be "
                           "matched: %s" % e)
        company = next((c for c in _load_or_empty("companies")
                        if c.get("id") == rec.get("company_id")), None)
        try:
            hits = _pf.match_signals(rec, company, jd_text, signals or [])
        except ValueError as e:
            raise _Refused(str(e))
        if title_lean:
            hits = hits + [title_lean[2]]
        lean_obj = {"lean": args.lean_choice, "line": line.strip(), "on": on_iso, "signals": hits}

        def apply(r):
            r["lean"] = lean_obj
        return ("lean %s (%d likely-pass signal(s) matched)" % (args.lean_choice, len(hits)),
                apply)

    if op == "listed-pay":
        modes = [m for m, v in (("none-shown", args.none_shown), ("stated", args.stated),
                                ("estimate", args.estimate)) if v]
        if len(modes) != 1:
            raise _Usage("listed-pay takes exactly one of --none-shown, --stated, --estimate")
        mode = modes[0]
        if mode == "none-shown":
            sources, state = PAY_SOURCES_NONE_SHOWN, "none-shown"
        elif mode == "stated":
            sources, state = PAY_SOURCES_STATED, "employer-stated"
        else:
            sources, state = ("board-widget",), "board-estimate"
        source = args.pay_source or sources[0]
        if source not in sources:
            raise _Refused("--pay-source %r is not valid for %s (allowed: %s)"
                           % (source, state, ", ".join(sources)))
        obj = {"state": state, "source": source, "captured_on": on_iso}
        if mode != "none-shown":
            try:
                obj = {"state": state, "ranges": _pf.parse_pay_ranges(
                    args.stated if mode == "stated" else args.estimate),
                    "source": source, "captured_on": on_iso}
            except ValueError as e:
                raise _Refused(str(e))

        def apply(r):
            r["listed_pay"] = obj
        return "listed-pay %s (source %s)" % (state, source), apply

    # posted
    picks = [(k, v) for k, v in (("profile-document-date", args.document_date),
                                 ("ats-posted", args.ats_date),
                                 ("board-relative", args.board_date),
                                 ("board-relative:age", args.shown_age),
                                 ("unknown", True if args.unknown else None))
             if v is not None]
    if len(picks) != 1:
        raise _Usage("posted takes exactly one of --document-date, --ats-date, --board-date, "
                     "--shown-age, --unknown")
    source, value = picks[0]
    if source == "unknown":
        obj = {"date": None, "source": "unknown", "recorded_on": on_iso}
    elif source == "board-relative:age":
        if not (isinstance(value, str) and value.isdigit() and int(value) < 3650):
            raise _Refused("--shown-age must be a whole number of days, got %r" % value)
        obj = {"date": (on - datetime.timedelta(days=int(value))).isoformat(),
               "source": "board-relative", "recorded_on": on_iso}
    else:
        try:
            datetime.date.fromisoformat(value)
        except ValueError:
            raise _Refused("the posting date must be an ISO date (YYYY-MM-DD), got %r" % value)
        obj = {"date": value, "source": source, "recorded_on": on_iso}

    def apply(r):
        r["posted"] = obj
    return "posted %s (%s)" % (obj["date"], obj["source"]), apply


def main():
    # design-inbound-resolution.md §2 amendment D4 — asserted before ANY argument parsing or
    # store touch, for every verb (not just `received`): a surface with no resolvable profile
    # (S6; a maintainer checkout with no CLAUDESEARCH_ROOT pinned) must refuse loudly rather
    # than fall to the cwd and traceback on the first missing store file.
    if not _looks_like_profile(ROOT):
        print("⛔ REFUSED — %r does not look like a job-search profile (no config.json, no "
              "data/ directory). record.py writes a PROFILE's stores; pin CLAUDESEARCH_ROOT to "
              "one, or run this from inside one." % ROOT)
        return EXIT_NO_PROFILE

    ap = argparse.ArgumentParser(description="Atomic writes to the record stores.",
                                 epilog=(_help_epilog() if any(a in ("-h", "--help") for a in sys.argv[1:]) else None),
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    # States & Views V1 (design-states-and-views.md §13/§15.3) — three new verbs, each a
    # transaction over ONE file: `decide` and `networking-closed` on opportunities,
    # `application-status` on applications. Presented as new operations (not `set`/`set-in`)
    # because each carries its own refusal logic `set` cannot express (§15.3's own reasoning).
    # States & Views V1b (design §13/§15.3) — `answered`/`touched` join the verb set: the
    # only two writers `messages` (append-only, MESSAGES_WRITE_VERBS above) ever gets.
    ap.add_argument("op", choices=OPS)
    ap.add_argument("rid", nargs="?", help="record id (e.g. an opportunity_id)")
    ap.add_argument("rest", nargs="*")
    ap.add_argument("--file", default="opportunities", choices=sorted(STORES))
    ap.add_argument("--why-kind", dest="why_kind", default=None,
                    help="decide: required when the verdict diverges from the engine's own "
                         "suggestion — one of validate_data.DECISION_REASON_KINDS.")
    ap.add_argument("--why", dest="why", default=None,
                    help="decide: the reason in the owner's own words, required alongside "
                         "--why-kind on a diverging decision.")
    ap.add_argument("--i-checked", dest="i_checked", default=None,
                    help="networking-closed: an ISO date asserting the owner looked personally — "
                         "the one way to close on UNVERIFIED silence (§15.1).")
    ap.add_argument("--on", dest="on_date", default=None,
                    help="application-status/touched/answered: the ISO date the write takes "
                         "(default: today for touched/answered; required for "
                         "application-status is optional too, same default).")
    ap.add_argument("--to", dest="to_token", default=None,
                    help="touched: `contact:<person-id>` — who the touch went to (required; "
                         "the person must exist and not be merged).")
    ap.add_argument("--medium", dest="medium", default=None,
                    help="touched: one of validate_data.MEDIA (required).")
    ap.add_argument("--touch-type", dest="touch_type", default=None,
                    help="touched: one of validate_data.TOUCH_TYPES (optional, default "
                         "'unknown'; the validator requires touch_type on a sent touch dated "
                         "on/after COMMS_CUTOVER, so the verb always fills it).")
    ap.add_argument("--reuse", action="store_true",
                    help="create --file people: get-or-create. An identical normalized "
                         "LinkedIn, or an identical email AND name, reuses the existing person "
                         "and writes nothing; an email-only match is refused and listed as a "
                         "candidate (people.py's own matcher, ADR-031 §3).")
    ap.add_argument("--via", dest="via_medium", default=None,
                    help="answered: the medium the reply went out on — one of "
                         "validate_data.MEDIA.")
    ap.add_argument("--role", dest="recipient_role", default=None,
                    help="touched/answered/involve: one of validate_data.RECIPIENT_ROLES (optional) — "
                         "feeds the involvement's path_type via plays.ROLE_TO_PATH when the "
                         "recipient's involvement does not already have one (dev #479).")
    ap.add_argument("--opp", dest="opp_id", default=None,
                    help="answered: the opportunity this reply belongs to — required when "
                         "the target is a `contact:<id>` touch ref rather than a message id "
                         "(a bare message id already carries its own opp_id/channel_id). "
                         "involve: the opportunity to link the person to (required).")
    ap.add_argument("--when", dest="when_token", default=None,
                    help="set play:<id> params.<name>: the arm's predicate token — creates or "
                         "edits that arm (design §24.1). A NEW arm requires --why.")
    ap.add_argument("--plan", dest="plan_id", default=None,
                    help="create --file opportunities: which search plan sourced this role, "
                         "when more than one active search plan sources role/contract "
                         "(design §26.5) — required only in that ambiguous case.")
    ap.add_argument("--url", dest="listing_url", default=None,
                    help="unlink-sibling: the listing's source_url on the canonical row to split "
                         "away (dev #728 / public #158).")
    ap.add_argument("--into", dest="into_id", default=None,
                    help="merge-person: the SURVIVOR person id. The record named by <rid> "
                         "(the duplicate) gets status=merged, merged_into=<--into>, in one "
                         "write. Refused if that would close a merge cycle (public #93).")
    ap.add_argument("--note", dest="note_text", default=None,
                    help="application-status: appended to the row's existing `note` (never "
                         "overwritten — an owner's hand note survives) in the SAME transaction "
                         "as status/status_on (design-inbound-resolution.md §2).")
    ap.add_argument("--channel", dest="channel_id", default=None,
                    help="received: `--channel <channel_id>` — the other half of the anchor "
                         "rule (--opp or --channel, at least one, never both).")
    ap.add_argument("--person", dest="person_id_arg", default=None,
                    help="received: the sender's people.jsonl id, when known. With neither "
                         "--opp nor --channel a resolving --person is itself the anchor (a "
                         "message to/from a person about no role and no channel).")
    ap.add_argument("--from", dest="from_addr", default=None,
                    help="received: the message's From address.")
    ap.add_argument("--subject", dest="subject", default=None,
                    help="received: the message's Subject line.")
    ap.add_argument("--body-file", dest="body_file", default=None,
                    help="received: path to a file holding the body — never argv (an ATS "
                         "body is thousands of characters); written under the profile's own "
                         "scratch, never /tmp.")
    ap.add_argument("--source", dest="source_token", default=None,
                    help="received: provenance, e.g. gmail:<account>:<uid> — the id is minted "
                         "from this deterministically, so re-sending the same source is a "
                         "no-op, never a duplicate.")
    ap.add_argument("--resolves", dest="resolves", default=None,
                    help="received: the applications.id this inbound message resolves "
                         "(ADR-029/030). Requires --resolved-by; the opp anchor is then "
                         "DERIVED from the application's own opp_id — a conflicting --opp is "
                         "refused.")
    ap.add_argument("--resolved-by", dest="resolved_by", default=None,
                    choices=("req-id", "url", "company-single"),
                    help="received: which of ADR-030's three tiers matched. Required iff "
                         "--resolves is given.")
    ap.add_argument("--source-url", dest="source_url_flag", default=None,
                    help="append <id> sightings '{...}': merges this URL into the sighting as "
                         "'source_url' — public #83 rule 1's own convenience, so a caller never "
                         "has to hand-embed it in the JSON blob. Conflicts with an already-set "
                         "'source_url' in the JSON are refused (one fact, stated once).")
    ap.add_argument("--_inject-fault", dest="inject_fault", default=None,
                    help=argparse.SUPPRESS)     # test-only — see cmd_touched's own docstring
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--wait", type=int, default=DEFAULT_WAIT,
                    help="Seconds to wait for the run lock (default %d — holders release in "
                         "seconds; a longer wait usually means you are waiting on your own "
                         "run, which never ends: see --already-locked)." % DEFAULT_WAIT)
    ap.add_argument("--already-locked", action="store_true",
                    help="The CALLING RUN already holds the run lock (it took it for its write "
                         "phase). Write under that hold; take and release nothing. Verified: "
                         "refused if nobody actually holds the lock.")
    ap.add_argument("--force", action="store_true",
                    help="Write an unknown field anyway. Almost never right — an unknown field "
                         "is invisible to every query written against the real one.")
    ap.add_argument("--req-id", dest="req_id", default=None,
                    help="create (opportunities): the ATS requisition id the sourced posting "
                         "carries. Used ONLY to match an already-passed role (dev #670); "
                         "never stored.")
    ap.add_argument("--fields", action="store_true",
                    help="Print what this store accepts, so a caller never has to guess.")
    ap.add_argument("--from-item", dest="from_item", default=None,
                    help="create (opportunities): a `capture-role` deferred item id. Copies the "
                         "pay, posting date and work setting `deferred.py --add-roles` parsed from "
                         "the sweep's ROLE line (listed_pay, posted, location.declared, "
                         "location.primary) onto the new role. A slot the sweep did not read stays "
                         "absent; a value the JSON also carries must agree with the item. When the "
                         "sweep read setting=\"none stated\" at a concrete place, the script sets "
                         "location.type onsite and location.setting_source inferred (omit "
                         "location.type; giving one is refused).")
    # jobsearch 0.67.0 sourcing-screen verbs (SOURCING_OPS) -- each flag belongs to one verb.
    ap.add_argument("--lean", dest="lean_choice", default=None,
                    help="lean: pursue | pass | ask (required, except on a role whose stored screen "
                         "carries the age flag -- over-age or unknown-age recruiter role -- where "
                         "omitting it records `ask` with the age line's first move).")
    ap.add_argument("--line", dest="line_text", default=None,
                    help="lean: the one-line reason (required, one line, capped).")
    ap.add_argument("--jd-file", dest="jd_file", default=None,
                    help="lean: a file holding the JD text the run read; the likely-pass "
                         "signals are matched against it as well as the title and company.")
    ap.add_argument("--none-shown", dest="none_shown", action="store_true",
                    help="listed-pay: the listing showed NO pay (recorded, so it is not "
                         "'never captured').")
    ap.add_argument("--stated", dest="stated", default=None,
                    help="listed-pay: the EMPLOYER's range(s), <min>-<max>/<yr|mo|day|hr>/<CUR> "
                         "or <min>+/<unit>/<CUR>, separated by ';'.")
    ap.add_argument("--estimate", dest="estimate", default=None,
                    help="listed-pay: a BOARD's own estimate (never the employer's figure; it "
                         "can never remove a role), same range grammar.")
    ap.add_argument("--pay-source", dest="pay_source", default=None,
                    help="listed-pay: where the figure was read (default listing-text).")
    ap.add_argument("--document-date", dest="document_date", default=None,
                    help="posted: the date a recruiter's spec document carries "
                         "(source profile-document-date -- this flag is its only writer).")
    ap.add_argument("--ats-date", dest="ats_date", default=None,
                    help="posted: a JSON-LD datePosted or ATS API date (source ats-posted).")
    ap.add_argument("--board-date", dest="board_date", default=None,
                    help="posted: a bare date a board shows (source board-relative).")
    ap.add_argument("--shown-age", dest="shown_age", default=None,
                    help="posted: the age a board shows, in days; the date is COMPUTED from "
                         "the run date by this script (source board-relative).")
    ap.add_argument("--unknown", dest="unknown", action="store_true",
                    help="posted: record that the age is unknown (source unknown).")
    # jobsearch 0.72.0 (dev #751) company-feed verbs.
    ap.add_argument("--none", dest="ats_none", action="store_true",
                    help="ats: DECLINE a feed for this company (`ats: null`); discovery never "
                         "rewrites it.")
    ap.add_argument("--clear", dest="ats_clear", action="store_true",
                    help="ats: remove the `ats` key so discovery may run again.")
    ap.add_argument("--discover", dest="ats_discover", action="store_true",
                    help="ats: parse the slug off the company's own career_url / jd_url / sighting "
                         "URLs (never a fetch). Writes only an unambiguous result, and never over "
                         "an existing `ats` key (a declined `null` included).")
    ap.add_argument("--none-found", dest="none_found", action="store_true",
                    help="warm-lookup: record that you looked for a person at this company and "
                         "found nobody (with --on, default today).")
    # jobsearch 0.75.0 (dev #765) board-sighting flags (`--url` and `--plan` are the existing ones).
    ap.add_argument("--company", dest="company_name", default=None,
                    help="board-sighting: the company's name as the board shows it (matched against "
                         "the companies store by pipeline_index.company_candidates).")
    ap.add_argument("--company-id", dest="company_id_arg", default=None,
                    help="board-sighting: an existing companies id, when --company is ambiguous.")
    ap.add_argument("--title", dest="title_text", default=None,
                    help="board-sighting: the role's title as the board shows it.")
    ap.add_argument("--vertical", dest="vertical_arg", default=None,
                    help="board-sighting: required only when the company is NOT yet tracked and so is "
                         "created (one of validate_data.VERTICALS).")
    ap.add_argument("--seen-on", dest="seen_on", default=None,
                    help="board-sighting: the ISO date you saw the role (default: today).")
    # jobsearch 0.76.0 (dev #769) channel-catalog flags (`--on` and `--dry-run` are the existing ones).
    ap.add_argument("--kind", dest="cc_kind", default=None,
                    choices=("portfolio", "curated", "swept-board", "alert-sender"),
                    help="channel-catalog add: turn on every non-retired entry of one kind in one write.")
    ap.add_argument("--attach", dest="cc_attach", default=None,
                    help="channel-catalog add <entry>: tie an EXISTING channel you already hold to the entry "
                         "(fills only its absent managed fields) instead of creating a second row for one board.")
    ap.add_argument("--anyway", dest="src_anyway", action="store_true",
                    help="source on <id>: turn on a source whose catalog entry the catalog retired (the row then counts "
                         "as edited).")
    ap.add_argument("--firm", dest="cc_firm", default=None,
                    help="channel-catalog add <portfolio entry>: the companies id to use as the firm when the "
                         "firm's name matches several companies you track.")
    args = ap.parse_args()

    # These three verbs each own exactly one store — --file is never the caller's to pick for
    # them (a mistaken --file would silently target the wrong record and never be diagnosed).
    if args.op in ("decide", "networking-closed") + SOURCING_OPS:
        args.file = "opportunities"
    elif args.op == "application-status":
        args.file = "applications"
    elif args.op == "touched":
        # ADR-031 B3 — `cmd_touched` writes `touches`/`messages` internally by name, never
        # through this generic `--file`-driven path (it returns before reaching it, below);
        # this assignment only keeps the messages-append-only refusal check harmless.
        args.file = "opportunities"
    elif args.op == "answered":
        args.file = "messages"
    elif args.op == "received":
        args.file = "messages"
    elif args.op == "merge-person":
        args.file = "people"
    elif args.op == "involve":
        args.file = "opportunities"      # cmd_involve names its own stores; keeps the generic checks harmless
    elif args.op in ("ats", "warm-lookup"):
        args.file = "companies"          # dev #751: cmd_ats / cmd_warm_lookup name their own stores
    elif args.op == "board-sighting":
        args.file = "opportunities"      # dev #765: cmd_board_sighting names its own stores
    elif args.op == "channel-catalog":
        args.file = "channels"           # dev #769: cmd_channel_catalog names its own stores
    elif args.op == "source":
        args.file = "channels"           # dev #774: cmd_source names its own stores

    # §15.3 point 1 — `messages` is append-only; `answered`/`touched`/`received` are its ONLY
    # writers. Refused here, before any generic single-store machinery runs, so the refusal is
    # the very first thing printed rather than a confusing failure two steps later.
    if args.file == "messages" and args.op not in MESSAGES_WRITE_VERBS:
        print("⛔ REFUSED — 'messages' is append-only (design §15.3): a message row is "
              "immutable once written. Use `record.py answered ...`, `record.py touched ...` "
              "or `record.py received ...` — never set/set-in/append/create/show --file "
              "messages.")
        return 1

    if args.op == "touched":
        return cmd_touched(args)
    if args.op == "answered":
        return cmd_answered(args)
    if args.op == "received":
        return cmd_received(args)
    if args.op == "involve":
        return cmd_involve(args)
    if args.op == "ats":
        return cmd_ats(args)
    if args.op == "warm-lookup":
        return cmd_warm_lookup(args)
    if args.op == "board-sighting":
        return cmd_board_sighting(args)
    if args.op == "channel-catalog":
        return cmd_channel_catalog(args)
    if args.op == "source":
        return cmd_source(args)

    if args.reuse and not (args.op == "create" and args.file == "people"):
        print("⛔ REFUSED — --reuse applies only to `create <id> '<json>' --file people`.")
        return 1

    if args.op == "fields" or args.fields:
        # ⭐ dev #143 / public #23 failure #3: this listing used to print field names and
        # required-ness ONLY — no enum values for constrained fields, no marker for a field
        # whose value is an object rather than a string. A caller could not construct a valid
        # record from this output alone; it took a failed write plus reading validator source.
        m = model()["stores"][args.file]
        _vd = _validator_module()
        enums = _enum_registry(_vd).get(args.file, {})
        arr_enums = _array_enum_registry(_vd)
        objects = _object_shaped_fields(args.file, _vd)
        print("%s — %s" % (args.file, ", ".join(sorted(m["fields"]))))
        print("  required: %s" % ", ".join(m.get("required") or []))
        if objects:
            print("\n  OBJECT-TYPED (not a string):")
            for f in sorted(objects):
                print("    %s: %s" % (f, objects[f]))
        if enums:
            print("\n  ENUMS (allowed values):")
            for f in sorted(enums):
                print("    %s: {%s}" % (f, ", ".join(sorted(enums[f]))))
        if args.file == "touches":
            print()
            print("\n".join(_touch_requirement_lines(_vd)))
        for a, spec in sorted((m.get("arrays") or {}).items()):
            print("\n  %s[] — %s" % (a, ", ".join(sorted(spec["fields"]))))
            print("     required: %s%s" % (", ".join(spec.get("required") or []),
                  ("  · id: %s" % spec["id_field"]) if spec.get("id_field") else ""))
            a_enums = arr_enums.get((args.file, a)) or {}
            if a_enums:
                print("     enums:")
                for f in sorted(a_enums):
                    print("       %s: {%s}" % (f, ", ".join(sorted(a_enums[f]))))
        ban = {k: v for k, v in model()["banned_aliases"].items() if not k.startswith("_")}
        print("\n  BANNED ALIASES (same meaning, two spellings): %s"
              % ", ".join("%s->%s" % (k, v) for k, v in sorted(ban.items())))
        return 0

    if args.reuse:
        _reuse_rc = _reuse_people(args)
        if _reuse_rc is not None:
            return _reuse_rc

    rows = load(args.file)
    rec = find(rows, args.rid)
    if args.op == "create":
        # A create must land on an ABSENT id — the mirror image of every other op.
        if rec is not None:
            print("⛔ REFUSED — a %s record with id %r already exists." % (args.file, args.rid))
            print("  create never overwrites. Use set/set-in/append to change an existing "
                  "record; pick a new id for a new one.")
            return 1
    elif rec is None:
        print("No %s record with id %r." % (args.file, args.rid))
        return 1

    if args.op == "show":
        print(json.dumps({k: v for k, v in rec.items()
                          if k not in ("research_log", "fit")}, indent=2)[:3000])
        return 0

    # ---- build the mutation, describing it before touching anything -------------
    new_row = None
    # dev #728: a verb that writes a SECOND row of the same store (link-sibling, unlink-sibling)
    # reaches it through this holder, so the dry-run mutates its shadow copy and the real write the
    # rows it re-read under the lock -- never the other way round.
    _apply_rows = [None]
    # 0.41.0 — app_ids this write mints (see mint_app_id). Reported after the write lands, so
    # a caller learns the handle its trigger should name without re-reading the store.
    minted = []
    if args.op == "create":
        # ⭐ THE MISSING OPERATION (public #17 / dev #97). Without it, adding a brand-new row
        # meant hand-editing the JSONL — the exact ad-hoc read-all/write-all pattern this API
        # exists to abolish, and it recurred across sessions for as long as the gap existed.
        #
        # Deliberately a NEW op rather than `set` auto-creating on an unknown id: an op that
        # creates whenever an id fails to resolve turns every typo'd id into a silent new row,
        # which is the duplicate problem wearing a different hat. Intent is stated, then checked.
        if len(args.rest) != 1:
            print("usage: create <id> '<json object for the full record>'")
            return 2
        try:
            new_row = json.loads(args.rest[0])
        except ValueError as e:
            print("⛔ REFUSED — the record is not valid JSON: %s" % e)
            return 1
        if not isinstance(new_row, dict):
            print("⛔ REFUSED — the record must be a JSON object, got %s."
                  % type(new_row).__name__)
            return 1
        # ⭐ dev #715 / public #143, dev #716 / public #142 -- the facts the sweep's ROLE line
        # carried ride the capture-role item onto the opportunity, by a script, not by a model
        # re-typing them (copy_capture_item_facts' docstring).
        _from_item_copied = []
        if args.from_item:
            if args.file != "opportunities":
                print("⛔ REFUSED — --from-item applies only to `create ... --file opportunities`.")
                return 1
            _from_item_copied, _item_err = copy_capture_item_facts(new_row, args.from_item,
                                                                    rid=args.rid)
            if _item_err:
                print("⛔ REFUSED — --from-item: %s" % _item_err)
                return 1
        # ADR-031 B2 — `applications` is now a top-level store whose own id is minted the SAME
        # way app_id always was (<opp_id>-aN), but the id is no longer known until the record
        # exists: `create auto '{"opp_id": ..., ...}' --file applications` mints it here, from
        # `opp_id` in the payload, against every existing row on that same opp_id. This
        # replaces the old nested-array minting below (0.41.0's own comment), which applied
        # only while `applications` was still `opportunities.applications[]`.
        if args.file == "applications" and args.rid in (None, "auto"):
            _opp_id = new_row.get("opp_id")
            if not _opp_id:
                print("⛔ REFUSED — create auto '{...}' --file applications requires 'opp_id' "
                      "in the JSON payload; the id is minted from it (<opp_id>-aN).")
                return 1
            args.rid = mint_app_id(_opp_id, load("applications"))
            minted = [args.rid]
        # ADR-031 B3 — `touches` is a top-level store whose own id is minted `<person_id>-tN`
        # (design §1: a touch is owned by the PERSON, unlike an application's `<opp_id>-aN`
        # containment). `create auto '{"person_id": ..., ...}' --file touches` mints it here.
        if args.file == "touches" and args.rid in (None, "auto"):
            _person_id = new_row.get("person_id")
            if not _person_id:
                print("⛔ REFUSED — create auto '{...}' --file touches requires 'person_id' "
                      "in the JSON payload; the id is minted from it (<person_id>-tN).")
                return 1
            args.rid = mint_touch_id(_person_id, load("touches"))
            minted = [args.rid]
        # dev #764 / public #162 -- `cover_letters` mints `<opp_id>-clN` from `opp_id`, the same
        # way `applications` mints `<opp_id>-aN`. Before this the id was taken literally, so
        # `create auto ... --file cover_letters` wrote a row whose id was the word "auto".
        if args.file == "cover_letters" and args.rid in (None, "auto"):
            _opp_id = new_row.get("opp_id")
            if not _opp_id:
                print("⛔ REFUSED — create auto '{...}' --file cover_letters requires 'opp_id' "
                      "in the JSON payload; the id is minted from it (<opp_id>-clN).")
                return 1
            args.rid = mint_cover_letter_id(_opp_id, load("cover_letters"))
            minted = [args.rid]
        # dev #764 / public #162 -- a store with NO minting branch cannot honour `create auto`:
        # the placeholder would be written as the row's real id. Refuse, name the store and how to
        # supply an id, and write nothing. (An omitted id is the same request.)
        if args.rid in (None, "auto") and args.file not in AUTO_MINT_LABEL:
            print("⛔ REFUSED — `create auto` is not available for the %r store: it has no id "
                  "minting, so \"auto\" would be written as the record's real id. Name the id "
                  "yourself: create <id> '<json>' --file %s. (Stores that mint: %s.)"
                  % (args.file, args.file, ", ".join(sorted(AUTO_MINT_LABEL))))
            return 1
        # ⭐ design §12 — an unshaped introduction is exactly the row that "looks handled and
        # is not": a new intro-request touch naming neither object is refused at the door.
        # `validate_data.py` treats a MIGRATED intro-request with no object as legal (a
        # migration cannot know a fact it cannot derive) — this refusal is for NEW writes only.
        if (args.file == "touches" and new_row.get("touch_type") == "intro-request"
                and not new_row.get("object_person_id") and not new_row.get("object_company_id")):
            print("⛔ REFUSED — touch_type 'intro-request' with neither object_person_id nor "
                  "object_company_id set. An introduction is always ABOUT someone or some "
                  "company (design §12) — without one this row looks like any other touch and "
                  "nothing could ever ask 'who is being worked toward <company>?'")
            return 1
        # ⭐ ADR-031 B4 (design §17, §26.5) — a freshly created opportunity is auto-assigned
        # its governing `plan_id` from the one active search plan sourcing role/contract,
        # unless the payload already names one. With more than one candidate, `--plan` is
        # required — the refusal names every candidate (§26.5).
        if args.file == "opportunities" and not new_row.get("plan_id"):
            _resolved_plan, _plan_err = _new_opportunity_plan(args.plan_id)
            if _resolved_plan:
                new_row["plan_id"] = _resolved_plan
                new_row["plan_assigned_on"] = datetime.date.today().isoformat()
            elif _plan_err:
                print("⛔ REFUSED — %s" % _plan_err)
                return 1
            # else: no active sourcing plan at all — plan_id stays unset; the required-field
            # check below refuses it the same way any other missing required field would.
        m = model()["stores"][args.file]
        idf = m.get("id_field") or "id"
        if idf in new_row and new_row[idf] != args.rid:
            print("⛔ REFUSED — the JSON carries %s=%r but the command names %r. One id, "
                  "stated once." % (idf, new_row[idf], args.rid))
            return 1
        new_row[idf] = args.rid
        # Same refuse-before-write guards every other op gets: unknown keys, aliases, required.
        for k in new_row:
            bad = check_field(args.file, k)
            if bad and not args.force:
                print("⛔ REFUSED — %s" % bad)
                return 1
            spec = (m.get("arrays") or {}).get(k)
            if spec and isinstance(new_row[k], list):
                for i, item in enumerate(new_row[k]):
                    if not isinstance(item, dict):
                        continue
                    for kk in item:
                        bad = check_field(args.file, kk, array=k)
                        if bad and not args.force:
                            print("⛔ REFUSED — %s[%d]: %s" % (k, i, bad))
                            return 1
        # ⭐ public #83 rule 1 — a freshly created opportunity's own sightings[] get the SAME
        # capture-time check the append branch gives an existing one (see
        # sighting_source_url_problem's own docstring). Never gated by --force, for the same
        # reason as there: a data-integrity rule about an unrecoverable link, not a guess.
        if args.file == "opportunities" and isinstance(new_row.get("sightings"), list):
            _channel_type_by_id = {c.get("id"): c.get("type") for c in _load_or_empty("channels")}
            _receipted = any(a.get("status") in _validator_module().SUBMITTED_APP_STATUS
                            for a in _load_or_empty("applications") if a.get("opp_id") == args.rid)
            _seen_channel_ids = set()
            for _i, _sg in enumerate(new_row["sightings"]):
                if not isinstance(_sg, dict):
                    continue    # unshaped entries are the required/array-item guards' job
                _referenced = ({new_row.get("channel_id"), _sg.get("channel_id")}
                              | _seen_channel_ids)
                _problem = sighting_source_url_problem(_sg, _channel_type_by_id, _referenced,
                                                       _receipted)
                if _problem:
                    print("⛔ REFUSED — sightings[%d]: %s" % (_i, _problem))
                    return 1
                _seen_channel_ids.add(_sg.get("channel_id"))
        missing = [f for f in (m.get("required") or []) if not new_row.get(f)]
        if missing and not args.force:
            print("⛔ REFUSED — %s requires %s" % (args.file, ", ".join(missing)))
            print("  A record missing its required fields is one no query can rely on. "
                  "(`fields` prints what this store accepts.)")
            return 1
        # ⭐ dev #728 / public #158 (jobsearch 0.70.0; design-location-screen.md §5.3) -- ONE
        # REQUISITION LISTED AT SEVERAL PLACES IS ONE DECISION. The backstop of the capture-time
        # grouping in `deferred.py --add-roles`: a role being created that the pipeline already holds
        # (an ACTIVE row too -- #136 only ever looked at passed ones) is
        #   * with --from-item: LINKED -- the item's listing and its siblings become sightings of the
        #     existing row (active or passed), the item closes as `linked:<row id>`, exit 0; but a
        #     listing of a PASSED row strictly nearer than every place that row was listed at is
        #     printed `NEARER LISTING` and is NOT linked or closed (R8): it can become a fresh
        #     decision with --force;
        #   * without it: refused with an `append <id> sightings` hint (an active row), or by #136
        #     below (a passed one), exactly as before;
        #   * with --force: created, and the pair is recorded in `distinct_from` so the matching rule
        #     never re-merges it.
        _link_match = None
        _item = None
        if args.file == "opportunities":
            import deferred as _deferred_mod
            if args.from_item:
                _item = _deferred_mod.load_capture_item(args.from_item)
            _link_match = _known_match_for(rows, new_row, [(_item or {}).get("ref")]
                                           if _item else [])
        if _link_match and args.from_item and not args.force:
            return _link_from_item(args, new_row, rows, _link_match, _item)
        if _link_match and _link_match[2] == "active" and not args.force:
            _lrow, _lbasis, _lkind = _link_match
            print("⛔ %r was NOT created: it is the SAME ROLE as the active opportunity %r (%s; "
                  "company %s, title %r, status %s) -- one requisition listed more than once is one "
                  "decision." % (args.rid, _lrow.get("id"), _lbasis, _lrow.get("company_id") or "?",
                                 _lrow.get("title") or "?", _lrow.get("status") or "?"))
            print("  Add the listing to it: `record.py append %s sightings '<json>'` (give the "
                  "sighting a `location`). If this is a genuinely different opening, create it "
                  "again with --force (the pair is recorded in distinct_from)." % _lrow.get("id"))
            return 1
        if _item:
            # A new row born from an item that carried sibling listings keeps them as sightings.
            _sg0 = next((s for s in (new_row.get("sightings") or []) if isinstance(s, dict)), None)
            if _sg0 and _item.get("siblings"):
                for _sib in _item["siblings"]:
                    if not any(s.get("source_url") == _sib.get("url")
                               for s in new_row["sightings"] if isinstance(s, dict)):
                        new_row["sightings"].append(dict(
                            {"channel_id": _sg0.get("channel_id"), "seen_on": _sg0.get("seen_on"),
                             "source_url": _sib.get("url")},
                            **({"location": _sib["location"]} if _sib.get("location") else {})))
        if _link_match and args.force:
            _dist = list(new_row.get("distinct_from") or [])
            if _link_match[0].get("id") not in _dist:
                _dist.append(_link_match[0].get("id"))
            new_row["distinct_from"] = _dist
        # ⭐ dev #670 / public #136 — a role you already PASSED on does not come back as a fresh
        # lead because the sourcing run gave it a different id. The match is pipeline_index's
        # one definition (same company_id + normalized title, or identical jd_url, or identical
        # ATS requisition id) against its one exclusion list. The answer is OUTPUT, never a new
        # stored field: nothing is written, and the line names the existing row. A different
        # opening that genuinely reuses the title takes --force; reopening the old row is
        # `set <existing-id> ...`, not a duplicate.
        if args.file == "opportunities" and not args.force:
            import pipeline_index as _pidx
            _hit = _pidx.find_excluded_match(
                rows, company_id=new_row.get("company_id"), title=new_row.get("title"),
                jd_url=new_row.get("jd_url"), req_id=args.req_id,
                applications=_load_or_empty("applications"))
            if _hit:
                print("⛔ %s" % _pidx.describe_match(*_hit))
                print("  %r was NOT created: a role you already passed on is not a new "
                      "decision. To bring the old one back, `set` its verdict/status; if this "
                      "is a genuinely different opening, create it again with --force."
                      % args.rid)
                return 1
        desc = "create record (%d field(s): %s)" % (len(new_row), ", ".join(sorted(new_row)))
        if args.from_item:
            desc += (" -- copied from %s: %s" % (args.from_item, ", ".join(_from_item_copied))
                     if _from_item_copied else
                     " -- %s carried no pay, posting date or setting to copy" % args.from_item)

        def apply(r):        # unused for create; the lock section appends new_row instead
            raise AssertionError("create does not mutate an existing record")

    elif args.op == "set" and args.file == "plays" and args.rest \
            and args.rest[0].startswith("params."):
        # ⭐ ADR-031 B4 (design §27.1) — `set <play-id> params.<name> <value> --file plays
        # [--when TOKEN] [--why TEXT]`: a bounded, reasoned parameter tweak. **The refusal
        # names the legal set** (§27.1's own resolution: "the rejection IS the option list",
        # #73 applied here) — a caller never has to re-read a pattern file to learn what it
        # could have set instead.
        if len(args.rest) != 2:
            print("usage: set <play-id> params.<name> <value> --file plays [--when TOKEN] "
                 "[--why \"...\"]")
            return 2
        field, raw_val = args.rest
        pname = field.split(".", 1)[1]
        if rec is None:
            print("No plays record with id %r." % args.rid)
            return 1
        params_now = rec.get("params") or {}
        spec = params_now.get(pname)
        if spec is None:
            print("⛔ REFUSED — %r declares no parameter %r. Known: %s"
                 % (args.rid, pname, ", ".join(sorted(params_now)) or "(none)"))
            return 1
        if isinstance(spec, (int, float)):
            print("⛔ REFUSED — parameter %r is FIXED by the pattern (no min/max declared) "
                 "and cannot be tweaked. To change it, fork the play (edit steps/params by "
                 "hand or via record.py set-in)." % pname)
            return 1
        try:
            new_val = int(raw_val)
        except (TypeError, ValueError):
            print("⛔ REFUSED — %r must be an integer number of days, got %r" % (pname, raw_val))
            return 1
        mn, mx = spec.get("min"), spec.get("max")
        arm_desc = ", ".join("%s -> %s" % (a.get("when"), a.get("days"))
                             for a in spec.get("unless") or []) or "(none)"
        if mn is not None and mx is not None and not (mn <= new_val <= mx):
            print("⛔ REFUSED — %s: %d is outside [%s, %s]. anchored to the %s touch; "
                 "default %s; arms: %s"
                 % (pname, new_val, mn, mx, spec.get("anchor"), spec.get("days"), arm_desc))
            return 1
        when_tok = args.when_token
        today_iso = datetime.date.today().isoformat()
        if when_tok:
            existing_arm = next((a for a in (spec.get("unless") or [])
                                if a.get("when") == when_tok), None)
            if existing_arm is None and not (args.why or "").strip():
                print("⛔ REFUSED — a NEW arm (--when %r) requires --why: a second value for "
                     "one concept with no stated reason is the row a later reader merges "
                     "(design §24.2)." % when_tok)
                return 1
            desc = "set play %s params.%s (--when %s) = %d" % (args.rid, pname, when_tok, new_val)

            def apply(r, _pname=pname, _when=when_tok, _val=new_val, _why=args.why,
                     _on=today_iso):
                arms = r["params"][_pname].setdefault("unless", [])
                for a in arms:
                    if a.get("when") == _when:
                        a["days"] = _val
                        a["set_on"] = _on
                        if _why:
                            a["why"] = _why
                        return
                arms.append({"when": _when, "days": _val, "why": _why, "set_on": _on})
        else:
            desc = "set play %s params.%s = %d (every arm's why: %s)" % (args.rid, pname,
                                                                        new_val, arm_desc)

            def apply(r, _pname=pname, _val=new_val, _on=today_iso):
                r["params"][_pname]["days"] = _val
                r["params"][_pname]["set_on"] = _on

    elif args.op == "set":
        if len(args.rest) != 2:
            print("usage: set <id> <field> <value>")
            return 2
        field, val = args.rest[0], coerce(args.rest[1])
        bad = check_field(args.file, field)
        if bad and not args.force:
            print("⛔ REFUSED — %s" % bad)
            print("\n  Fix the field name, or add it to docs/data_model.json if it is genuinely")
            print("  new. --force writes anyway and is almost never right: an unknown field is")
            print("  invisible to every query written against the real one.")
            return 1
        desc = "set %s = %r" % (field, val)
        if args.file == "opportunities" and field == "location" and isinstance(val, dict):
            # dev #727 / public #159 (R5): the whole-object replace of an INFERRED location records
            # the overturn, or refuses a replacement that would leave the flag lying.
            _loc_new, _loc_err = location_replace(rec.get("location"), val, args.rid)
            if _loc_err:
                print("⛔ REFUSED — %s" % _loc_err)
                return 1
            if "inference_overturned" in _loc_new and "inference_overturned" not in val:
                _was = (rec.get("location") or {}).get("inference_overturned")
                desc += (" -- records the overturn of the inferred setting (%s -> %s)"
                         % (_loc_new["inference_overturned"]["was"],
                            _loc_new["inference_overturned"]["to"]) if _was is None
                         else " -- keeps the recorded overturn of the inferred setting")

            def apply(r):
                new_loc, err = location_replace(r.get("location"), val, args.rid)
                if err:
                    raise KeyError(err)
                r[field] = new_loc
        else:
            def apply(r):
                r[field] = val

    elif args.op == "append":
        if len(args.rest) != 2:
            print("usage: append <id> <array> <json>")
            return 2
        arr, blob = args.rest[0], json.loads(args.rest[1])
        m = model()["stores"].get(args.file, {})
        if arr not in (m.get("arrays") or {}):
            print("⛔ REFUSED — %r is not an array of %s. Known: %s"
                  % (arr, args.file, ", ".join(sorted((m.get("arrays") or {})))))
            return 1
        # public #83 rule 1 — --source-url merges into a sightings[] blob so a caller never
        # has to hand-embed it in the JSON string. One fact, stated once: a JSON value that
        # DISAGREES with the flag is refused rather than silently picking one.
        if args.source_url_flag is not None and args.file == "opportunities" and arr == "sightings":
            existing_url = blob.get("source_url")
            if existing_url and existing_url != args.source_url_flag:
                print("⛔ REFUSED — the JSON carries source_url=%r but --source-url says %r. "
                      "One URL, stated once." % (existing_url, args.source_url_flag))
                return 1
            blob["source_url"] = args.source_url_flag
        # ADR-031 B2 — `applications` is no longer an array of `opportunities` (it is its own
        # top-level store, created via `create auto ... --file applications`, which mints its
        # own id — see the create branch above), so this array-append path never mints an
        # app_id any more; `arr` here can only ever be a genuinely nested array
        # (outreach/sightings/research_log/fit.requirements).
        for k in blob:
            bad = check_field(args.file, k, array=arr)
            if bad and not args.force:
                print("⛔ REFUSED — %s" % bad)
                return 1
        missing = [r for r in (m["arrays"][arr].get("required") or []) if not blob.get(r)]
        if missing and not args.force:
            print("⛔ REFUSED — %s[] requires %s" % (arr, ", ".join(missing)))
            print("  A row missing its required fields is a row no query can rely on.")
            return 1
        # ⭐ ID UNIQUENESS — the duplicate problem, caught at the door
        idf = m["arrays"][arr].get("id_field")
        if idf and blob.get(idf):
            existing = {x.get(idf) for x in (rec.get(arr) or [])}
            if blob[idf] in existing:
                print("⛔ REFUSED — %s %r already exists on this record." % (idf, blob[idf]))
                print("  Use set-in to update it. Appending a second row with the same id is how")
                print("  a join silently returns two answers.")
                return 1
        # ⭐ public #83 rule 1 — a NEW sighting from a URL-bearing channel must carry its
        # source_url at the moment it is captured (see sighting_source_url_problem's own
        # docstring). Never gated by --force: this is a data-integrity rule about a link that
        # cannot be recovered later, not a schema-shape guess --force exists to override.
        if args.file == "opportunities" and arr == "sightings":
            _channel_type_by_id = {c.get("id"): c.get("type") for c in _load_or_empty("channels")}
            _receipted = any(a.get("status") in _validator_module().SUBMITTED_APP_STATUS
                            for a in _load_or_empty("applications") if a.get("opp_id") == rec.get("id"))
            _existing_sightings = rec.get("sightings") or []
            _referenced = ({rec.get("channel_id"), blob.get("channel_id")}
                          | {sg.get("channel_id") for sg in _existing_sightings})
            _problem = sighting_source_url_problem(blob, _channel_type_by_id, _referenced,
                                                   _receipted)
            if _problem:
                print("⛔ REFUSED — %s" % _problem)
                return 1
        desc = "append to %s[]" % arr

        def apply(r):
            r.setdefault(arr, []).append(blob)

    elif args.op == "set-in":
        if len(args.rest) != 4:
            print("usage: set-in <id> <array> <key>=<match> <field> <value>")
            return 2
        arr, match, field, val = args.rest[0], args.rest[1], args.rest[2], coerce(args.rest[3])
        if "=" not in match:
            print("match must be key=value, e.g. contact_id=jane-doe")
            return 2
        mk, mv = match.split("=", 1)
        for f in (mk, field):
            bad = check_field(args.file, f, array=arr)
            if bad and not args.force:
                print("⛔ REFUSED — %s" % bad)
                return 1
        desc = "set %s = %r on %s[] where %s == %r" % (field, val, arr, mk, mv)

        def apply(r):
            # ⭐ DOTTED PATH: `fit.requirements` is an array one level down, not a top-level one.
            # Closing an answered JD-fit question is a routine write (26 were open on 2026-08-05,
            # two of them still flagged DUE for a call that had already happened), and without
            # this the only way to do it was an ad-hoc read-mutate-write — the exact pattern this
            # API exists to abolish. Resolution is by walking dicts, so it stays a strict
            # generalisation: a name with no dot behaves exactly as before.
            node = r
            for part in arr.split(".")[:-1]:
                node = node.get(part) or {}
            leaf = arr.split(".")[-1]
            hits = [x for x in (node.get(leaf) or []) if str(x.get(mk)) == mv]
            if not hits:
                raise KeyError("no %s[] entry with %s == %r" % (arr, mk, mv))
            for x in hits:
                x[field] = val

    elif args.op == "decide":
        # design-states-and-views.md §3a — writes `verdict` + `decision{}` ATOMICALLY, in the
        # SAME write: a verdict with no recorded suggestion (or a diverging one with no reason)
        # is the exact gap this verb closes.
        if len(args.rest) != 1:
            print("usage: decide <opp_id> pursue|pass|park [--why-kind K --why \"...\"]")
            return 2
        _verdict_alias = {"park": "parked"}
        new_verdict = _verdict_alias.get(args.rest[0], args.rest[0])
        if new_verdict not in ("pursue", "pass", "parked"):
            print("⛔ REFUSED — verdict must be one of pursue, pass, park (parked) — 'undecided' "
                  "is the state before a decision, never something you decide TO.")
            return 1
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import your_move as _ym
        import profile as _profile_mod
        _companies = {c.get("id"): c for c in load("companies")}
        _company = _companies.get(rec.get("company_id"))
        _cfg = _profile_mod.config()
        try:
            suggested, _missing = _ym.triage_suggestion(rec, _cfg, company=_company,
                                                        fit=rec.get("fit"))
        except Exception as e:                              # noqa: BLE001 — comp screen can
            suggested, _missing = None, "screen-error:%s" % type(e).__name__   # raise on bad data
        diverges = suggested is not None and suggested != new_verdict
        if diverges and not (args.why_kind and (args.why or "").strip()):
            print("⛔ REFUSED — the engine's own suggestion today is %r; your decision (%r) "
                  "diverges. Pass --why-kind <%s> and --why \"...\" so the override is "
                  "auditable later (design §3a)."
                  % (suggested, new_verdict, "|".join(sorted(_validator_module().DECISION_REASON_KINDS))))
            return 1
        if args.why_kind and args.why_kind not in _validator_module().DECISION_REASON_KINDS:
            print("⛔ REFUSED — --why-kind must be one of %s"
                  % ", ".join(sorted(_validator_module().DECISION_REASON_KINDS)))
            return 1
        decision_obj = {"on": datetime.date.today().isoformat(), "suggested": suggested,
                        "reason_kind": args.why_kind, "reason": args.why}
        desc = "decide verdict=%s (engine suggested %s)" % (new_verdict, suggested)

        def apply(r):
            r["verdict"] = new_verdict
            r["decision"] = decision_obj
            # ⭐ dev #722 / public #156 (jobsearch 0.69.0, §5): a decided pass on a BACKLOG role is
            # terminal in the SAME write -- `status: passed`, `stage: closed` (the validator
            # requires passed at closed), the way back kept in `passed_from` so a later
            # `decide pursue|park` restores it. Before this, `verdict: pass` left the row
            # `status: backlog`: excluded but not terminal, so the rest of the engine still saw a
            # live backlog role. A pass on any other status (a live pursuit) is unchanged and out of
            # scope; a `passed` row with no `passed_from` (passed some other way) is not guessed at.
            if new_verdict == "pass" and r.get("status") == "backlog":
                r["passed_from"] = {"status": "backlog", "stage": r.get("stage")}
                r["status"], r["stage"] = "passed", "closed"
            elif (new_verdict in ("pursue", "parked") and r.get("status") == "passed"
                    and isinstance(r.get("passed_from"), dict)):
                back = r.pop("passed_from")
                r["status"], r["stage"] = back.get("status"), back.get("stage")

    elif args.op == "application-status":
        # §3c — `status` + `status_on` in ONE transaction. `closed` presupposes a submission
        # (what was never sent is `withdrawn`, never `closed`) — refused below `submitted`.
        if len(args.rest) != 1:
            print("usage: application-status <app_id> <status> [--on <date>]")
            return 2
        new_status = args.rest[0]
        if new_status not in _validator_module().APPLICATION_STATUS:
            print("⛔ REFUSED — status must be one of %s"
                  % ", ".join(sorted(_validator_module().APPLICATION_STATUS)))
            return 1
        current = rec.get("status")
        if new_status == "closed" and current in ("not-started", "started", None):
            print("⛔ REFUSED — 'closed' presupposes a submission; this application's status "
                  "is %r. What was never sent is 'withdrawn', not 'closed' (§3c)." % current)
            return 1
        if args.on_date is not None and not re.match(r"^\d{4}-\d{2}-\d{2}$", args.on_date):
            print("⛔ REFUSED — --on must be an ISO date (YYYY-MM-DD), got %r" % args.on_date)
            return 1
        on_date = args.on_date or datetime.date.today().isoformat()
        desc = "application-status %s -> %s (status_on=%s)" % (current, new_status, on_date)
        if args.note_text:
            desc += " · note: %s" % args.note_text[:60]

        def apply(r, _note=args.note_text):
            r["status"] = new_status
            r["status_on"] = on_date
            # design-inbound-resolution.md §2 — `--note` APPENDS to the existing `note`, never
            # overwrites it: an owner's hand note (or an earlier sweep's own evidence line)
            # must survive a later status write, not be silently replaced by it.
            if _note:
                r["note"] = ("%s | %s" % (r["note"], _note)) if r.get("note") else _note

    elif args.op == "merge-person":
        # ADR-031 §3 / public #93 — "a merge is a pointer, never a rewrite": this sets
        # `status`+`merged_into` on the DUPLICATE row (args.rid) in ONE transaction —
        # `validate_data.py` refuses `merged_into` set without `status: merged`, and vice
        # versa (PEOPLE_STATUS) — and touches nothing else. Every other record's `person_id`
        # keeps naming the duplicate and resolves through it at READ time
        # (`graph.Graph.resolve_person`), never rewritten here.
        if len(args.rest) != 0:
            print("usage: merge-person <duplicate-id> --into <survivor-id>")
            return 2
        if not args.into_id:
            print("⛔ REFUSED — merge-person requires --into <survivor-id>.")
            return 1
        if args.into_id == args.rid:
            print("⛔ REFUSED — a person cannot be merged into itself.")
            return 1
        survivor = find(rows, args.into_id)
        if survivor is None:
            print("⛔ REFUSED — no people record with id %r (--into)." % args.into_id)
            return 1
        if _merge_would_cycle(rows, args.rid, args.into_id):
            print("⛔ REFUSED — merging %r into %r would close a merged_into CYCLE: %r's own "
                  "merge chain already leads back to %r."
                  % (args.rid, args.into_id, args.into_id, args.rid))
            return 1
        desc = "merge-person into %s" % args.into_id

        def apply(r):
            r["status"] = "merged"
            r["merged_into"] = args.into_id

    elif args.op == "link-sibling":
        # dev #728 / public #158 (design-location-screen.md §5.4): FOLD a pre-0.70.0 duplicate row
        # into the row that already stands for the requisition, by hand. ONE locked write: the
        # duplicate's listings become sightings of the canonical row, and the duplicate gets
        # `duplicate_of`. Nothing is deleted. No migration does this for existing rows: the matcher can
        # false-merge, and a stored row may carry notes, people or channel history only a human can
        # weigh.
        if args.file != "opportunities" or args.rest:
            print("usage: link-sibling <duplicate-id> --into <canonical-id>   (opportunities)")
            return 2
        if not args.into_id:
            print("⛔ REFUSED — link-sibling requires --into <canonical-id>.")
            return 1
        canon0 = find(rows, args.into_id)
        why = None
        if args.into_id == args.rid:
            why = "a row cannot be folded into itself"
        elif canon0 is None:
            why = "no opportunity with id %r (--into)" % args.into_id
        elif rec.get("duplicate_of"):
            why = "%r is already folded into %r" % (args.rid, rec["duplicate_of"])
        elif canon0.get("duplicate_of"):
            why = ("%r is itself folded into %r: fold into the canonical row, never a chain"
                   % (args.into_id, canon0["duplicate_of"]))
        elif rec.get("verdict") not in (None, "undecided"):
            why = ("%r carries a decision (verdict %s): a folded row stands for no decision. Decide "
                   "the canonical row, or `set` this row's verdict back to undecided first"
                   % (args.rid, rec.get("verdict")))
        elif any(a.get("opp_id") == args.rid for a in _load_or_empty("applications")):
            why = "%r has an application: it is a decision made by acting, not a duplicate" % args.rid
        elif (args.into_id in (rec.get("distinct_from") or [])
              or args.rid in (canon0.get("distinct_from") or [])):
            why = ("%r and %r were recorded as DIFFERENT (distinct_from); undo that first if they "
                   "are one requisition after all" % (args.rid, args.into_id))
        if why:
            print("⛔ REFUSED — %s." % why)
            return 1
        desc = "link-sibling into %s (folds this row; its listings become sightings of %s)" % (
            args.into_id, args.into_id)

        def apply(r):
            import pipeline_index as _pidx
            canon = find(_apply_rows[0] or rows, args.into_id)
            if canon is None:
                raise KeyError("no opportunity with id %r (--into)" % args.into_id)
            have = {s.get("source_url") for s in (canon.get("sightings") or []) if s.get("source_url")}
            primary = (r.get("location") or {}).get("primary") if isinstance(r.get("location"), dict) \
                else None
            incoming = []
            for sg in (r.get("sightings") or []):
                if isinstance(sg, dict):
                    incoming.append(dict(sg, **({"location": primary} if primary and "location" not in sg
                                                else {})))
            channel = r.get("channel_id") or next((s.get("channel_id") for s in incoming), None)
            if r.get("jd_url") and r["jd_url"] not in have and not any(
                    s.get("source_url") == r["jd_url"] for s in incoming) and channel:
                incoming.append({"channel_id": channel,
                                 "seen_on": _pidx.first_seen(r) or datetime.date.today().isoformat(),
                                 "source_url": r["jd_url"],
                                 **({"location": primary} if primary else {})})
            for sg in incoming:
                if sg.get("source_url") and sg["source_url"] in have:
                    continue
                canon.setdefault("sightings", []).append(sg)
                if sg.get("source_url"):
                    have.add(sg["source_url"])
            r["duplicate_of"] = args.into_id

    elif args.op == "unlink-sibling":
        # dev #728 / public #158 (design §5.5): UNDO a false merge. Nothing is deleted. The canonical
        # row's sighting for `--url` is stamped `split_to: <row>`; <row> (which must already exist:
        # a folded legacy row, or a row made with `create --force`) gets the canonical row in its
        # `distinct_from` and, if it was folded into this one, loses `duplicate_of`. The matching
        # rule reads both stamps, so the pair never re-merges.
        if args.file != "opportunities" or args.rest:
            print("usage: unlink-sibling <canonical-id> --url <source_url> --to <row-id>   (opportunities)")
            return 2
        if not args.listing_url or not args.to_token:
            print("⛔ REFUSED — unlink-sibling requires --url <the listing's source_url> and "
                  "--to <the row that listing belongs to>.")
            return 1
        import pipeline_index as _pidx
        target0 = find(rows, args.to_token)
        sg0 = next((s for s in (rec.get("sightings") or []) if isinstance(s, dict)
                    and _pidx._urls_equal(s.get("source_url"), args.listing_url)), None)
        why = None
        if args.to_token == args.rid:
            why = "a listing cannot be split to the row it is already on"
        elif target0 is None:
            why = ("no opportunity with id %r (--to). Create it first (`record.py create <id> '<json>' "
                   "--force`, which records distinct_from), or fold-undo a legacy row that exists"
                   % args.to_token)
        elif sg0 is None:
            why = "%r has no sighting with source_url %s" % (args.rid, args.listing_url)
        elif sg0.get("split_to"):
            why = "that sighting was already split to %r" % sg0["split_to"]
        elif target0.get("duplicate_of") not in (None, args.rid):
            why = ("%r is folded into %r, not into %r: unlink it from there"
                   % (args.to_token, target0["duplicate_of"], args.rid))
        if why:
            print("⛔ REFUSED — %s." % why)
            return 1
        desc = "unlink-sibling: split %s to %s (nothing deleted)" % (args.listing_url, args.to_token)

        def apply(r):
            import pipeline_index as _pidx2
            target = find(_apply_rows[0] or rows, args.to_token)
            if target is None:
                raise KeyError("no opportunity with id %r (--to)" % args.to_token)
            sg = next((s for s in (r.get("sightings") or []) if isinstance(s, dict)
                       and _pidx2._urls_equal(s.get("source_url"), args.listing_url)), None)
            if sg is None:
                raise KeyError("%r has no sighting with source_url %s" % (r.get("id"), args.listing_url))
            sg["split_to"] = args.to_token
            if target.get("duplicate_of") == r.get("id"):
                del target["duplicate_of"]
            df = list(target.get("distinct_from") or [])
            if r.get("id") not in df:
                df.append(r.get("id"))
            target["distinct_from"] = df

    elif args.op in SOURCING_OPS:
        # dev #713-#716 / public #142-#145 -- see `_sourcing_mutation`: it computes the value and
        # returns (desc, apply); everything after this chain (dry-run through the validator, the
        # lock, the introduced-only rules, rollback) is the shared path every other verb takes.
        try:
            desc, apply = _sourcing_mutation(args, rec)
        except _Usage as e:
            print(str(e))
            return 2
        except _Refused as e:
            print("⛔ REFUSED — %s" % e)
            return 1

    else:  # networking-closed
        # §3b/§15.1 — refuses on UNVERIFIED silence unless the owner says they looked personally.
        if len(args.rest) != 0:
            print("usage: networking-closed <opp_id> [--i-checked <date>]")
            return 2
        if args.i_checked is not None and not re.match(r"^\d{4}-\d{2}-\d{2}$", args.i_checked):
            print("⛔ REFUSED — --i-checked must be an ISO date (YYYY-MM-DD)")
            return 1
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import your_move as _ym
        today = datetime.date.today().isoformat()
        conv_axis, _newest = _ym.opportunity_conversation_axis(ROOT, args.rid, today=today)
        if conv_axis == "silence-unverified" and not args.i_checked:
            print("⛔ REFUSED — silence on this pursuit is UNVERIFIED (no mailbox coverage "
                  "confirms nobody wrote back). Pass --i-checked <date> to assert you looked "
                  "yourself (§15.1) — or 'you are the sensor' if no mailbox is configured.")
            return 1
        closed_on = args.i_checked or today
        desc = "networking-closed on %s (conversation axis at write time: %s)" % (closed_on,
                                                                                  conv_axis)

        def apply(r):
            r["networking_closed_on"] = closed_on

    print("%s: %s" % (args.rid, desc))
    if args.dry_run:
        print("  --dry-run: nothing written.")
        # ⭐ dev #143 / public #23 failure #1 — RUN THE SAME VALIDATOR A REAL WRITE RUNS, on a
        # disposable copy of the store (dry_run_validate). Before this fix, --dry-run stopped
        # after check_field's unknown-key/required checks — it never ran validate_data.py,
        # which is the only thing that catches an enum violation or a wrongly-shaped value. A
        # dry-run create on such an input reported success while the identical real write was
        # refused and rolled back: a false green, actively misleading rather than merely
        # unhelpful. Never weaken the real write to match; raise the dry-run to match it.
        shadow_rows = json.loads(json.dumps(rows))     # deep copy — `rows` itself stays untouched
        if args.op == "create":
            shadow_rows.append(new_row)
        else:
            shadow_rec = find(shadow_rows, args.rid)
            _apply_rows[0] = shadow_rows
            try:
                apply(shadow_rec)
            except KeyError as e:
                print("  %s" % e)
                return 1
        # Was the REAL store already invalid, independent of this hypothetical write? Same
        # question the real write asks — and answered the same way, by PROBLEM SET, not exit
        # code (G9): a standing problem must not stop the dry-run judging THIS change.
        #
        # dev #644 item 5 — the introduced-only rules are judged on the ROW here, exactly as the
        # real write below judges them (a dry-run must predict the write, dev #143).
        _after_row = new_row if args.op == "create" else shadow_rec
        _introduced = introduced_row_violations(
            args.file, None if args.op == "create" else rec, _after_row)
        if _introduced:
            print("  ⛔ a REAL (non-dry-run) write of this would be REFUSED (nothing is written):")
            print("  " + "\n  ".join("- " + m for m in _introduced))
            return 1
        pre_rc, _, _, pre_problems = validate()
        rc, out, err, problems = dry_run_validate(args.file, shadow_rows)
        if rc != 0:
            added = new_problems(pre_problems, problems)
            if added is None or added:
                print("  ⛔ a REAL (non-dry-run) write of this would be REFUSED and rolled back.")
                if added:
                    print("  It introduces %d problem(s) the store does not have now:" % len(added))
                    print("  " + "\n  ".join("- " + a for a in added))
                else:
                    print("  " + "\n  ".join(_diagnostic_lines(rc, out, err)))
                if pre_rc != 0:
                    print("  (%d pre-existing problem(s) stand as well; they are not this "
                          "change's.)" % len(pre_problems or []))
                return 1
            print("  ✅ THIS change adds no problem — but the store is ALREADY invalid, "
                  "independent of it:")
            print("  " + "\n  ".join("- " + a for a in (problems or [])))
            print("  A real write would LAND and exit 1 (not rolled back — the failure was "
                  "there before). Fix the pre-existing problem; the store is invalid for the "
                  "next worker.")
            return 0
        print("  ✅ dry-run validated clean against the same validator a real write runs.")
        if minted:
            _mint_label = AUTO_MINT_LABEL.get(args.file, "app_id")
            print("  · would mint %s: %s" % (_mint_label, ", ".join(minted)))
        if args.file == "opportunities" and args.op in ("append", "set-in") and args.rest:
            action = ASK_ACTION_FOR_ARRAY.get(args.rest[0].split(".")[-1])
            for a in linked_asks(args.rid, action, _load_asks()) if action else []:
                print("  would also resolve ask %r — %s (resolves_when: %s, dev #133)"
                      % (a.get("id"), (a.get("title") or "")[:60], action))
        # ADR-031 B2 — the applications-store equivalent of the preview above: a create/set
        # against `applications` may answer an ask whose `resolves_when` is "application" on
        # this application's own opp_id.
        if args.file == "applications" and args.op in ("create", "set"):
            opp_id = new_row.get("opp_id") if args.op == "create" else rec.get("opp_id")
            if opp_id:
                for a in linked_asks(opp_id, "application", _load_asks()):
                    print("  would also resolve ask %r — %s (resolves_when: application, "
                          "dev #133 / ADR-031 B2)" % (a.get("id"), (a.get("title") or "")[:60]))
        # ADR-031 B3 — the touches-store equivalent: a create/set against `touches` may answer
        # an ask whose `resolves_when` is "outreach" on the touch's own opp_id.
        if args.file == "touches" and args.op in ("create", "set"):
            opp_id = new_row.get("opp_id") if args.op == "create" else rec.get("opp_id")
            if opp_id:
                for a in linked_asks(opp_id, "outreach", _load_asks()):
                    print("  would also resolve ask %r — %s (resolves_when: outreach, "
                          "dev #133 / ADR-031 B3)" % (a.get("id"), (a.get("title") or "")[:60]))
        return 0

    # ---- the ONLY window the lock is held: read, mutate, write, verify ----------
    if args.already_locked:
        # ⭐ VERIFIED, NOT TRUSTED. A caller claiming a hold nobody has is writing unprotected
        # by accident — refuse rather than proceed bare (public #17 / dev #97).
        if not lock_is_held():
            print("  REFUSED — --already-locked, but NOBODY holds the run lock.")
            print("  Take it first (runlock.py --take), or drop the flag and let this call")
            print("  take it for the milliseconds of the write.")
            return 1
    else:
        try:
            take_lock("record.py %s %s" % (args.op, args.rid), wait=args.wait)
        except LockError as e:
            print("  REFUSED — %s" % e)
            print("  If that holder is YOUR OWN run (it took the lock for its write phase),")
            print("  waiting can never succeed — re-run with --already-locked instead.")
            print("  If it is another writer: holds are short; retry in a moment.")
            return 1
    try:
        rows = load(args.file)          # re-read INSIDE the lock — the file may have moved
        rec = find(rows, args.rid)
        _row_before = None
        if args.op == "create":
            if rec is not None:
                print("  a record with id %r appeared between read and lock — aborting."
                      % args.rid)
                return 1
            rows.append(new_row)
        else:
            if rec is None:
                print("  record vanished between read and lock — aborting.")
                return 1
            _row_before = json.loads(json.dumps(rec))    # as it stood, for the check below
            _apply_rows[0] = rows
            try:
                apply(rec)
            except KeyError as e:
                print("  %s" % e)
                return 1
        # ⭐ dev #644 item 5 / dev #427 — INTRODUCED-ONLY RULES. Refused HERE, on the row being
        # written or changed, before a byte lands: the whole-store validator only WARNS about
        # rows that already exist (validate_data.INTRODUCED_ONLY_RULES), so this is the one
        # place a new violation is stopped. Nothing is written, so there is nothing to roll back.
        _introduced = introduced_row_violations(
            args.file, _row_before, new_row if args.op == "create" else rec)
        if _introduced:
            print("  ⛔ REFUSED — this write would introduce a violation (nothing was written):")
            print("  " + "\n  ".join("- " + m for m in _introduced))
            return 1
        # ⭐⭐ SNAPSHOT BEFORE THE WRITE — this is what makes the rollback below possible.
        # Raw bytes, not the parsed rows: restoring exactly what was there cannot reintroduce a
        # formatting difference, and a byte-identical restore is trivially verifiable.
        # GitHub issue #1.
        before = snapshot(args.file)

        # ⭐ Was the store ALREADY invalid? Asked here, before touching anything, because
        # validate_data.py checks the WHOLE store — an unrelated pre-existing problem would
        # otherwise make this write look guilty and get rolled back for nothing.
        #
        # ⭐ BY PROBLEM SET, NOT EXIT CODE (G9, dev/audit 2026-09-02). "Already failing" is
        # decided per problem: the write is kept only when every problem after it was there
        # before it. A write that adds one is a new defect, whatever else was standing — and
        # it is rolled back, exactly as it would be on a clean store. The carve-out narrows;
        # nothing that lands is ever silently discarded (the outcome is always printed).
        pre_rc, _, _, pre_problems = validate()

        save_atomic(args.file, rows)
        rc, out, err, problems = validate()
        if rc != 0:
            added = new_problems(pre_problems, problems)
            if pre_rc != 0 and added == []:
                # Every problem pre-exists this write. Rolling back would discard a legitimate
                # write to "fix" something it did not cause, so keep it and say exactly that.
                print("  ⚠️ WROTE. The validator still fails — BUT IT WAS ALREADY FAILING BEFORE")
                print("  this write with the SAME problem(s), so this change is not the cause")
                print("  and was NOT rolled back:")
                print("  " + "\n  ".join("- " + a for a in (problems or [])))
                print("  Fix the pre-existing problem; the store is invalid for the next worker.")
                return 1
            if pre_rc != 0 and added is None and pre_problems is None:
                # The validator crashed before the write and crashes after it the same way:
                # nothing this write did can be blamed, and nothing can be compared. Keep it,
                # loudly — the crash is the pre-existing problem.
                print("  ⚠️ WROTE. The validator CRASHED — but it was ALREADY CRASHING BEFORE")
                print("  this write, so this change is not the cause and was NOT rolled back.")
                print("  " + "\n  ".join(_diagnostic_lines(rc, out, err)))
                print("  Fix the validator crash; the store cannot be checked for the next worker.")
                return 1

            # The store was clean and this write broke it — or it was already invalid and this
            # write ADDED a problem (or turned a finishing validator into a crashing one).
            # Either way this write is the cause of something. Put it back.
            #
            # ⭐ WHY THIS EXISTS: previously the invalid write stayed on disk and only a warning
            # was printed. The caller saw exit 1 — a failure — while the data HAD changed. **A
            # refusal that writes is worse than either honest outcome**: the caller retries and
            # duplicates the row, and the next worker inherits an invalid store. Observed
            # 2026-08-05 appending an outreach row whose message_ref did not yet resolve.
            #
            # ⭐ dev #143 / public #23 failure #2: this banner used to print `out`'s tail
            # unconditionally. When validate_data.py CRASHES instead of finishing (an unguarded
            # value-shape assumption, e.g. comp passed as a string), stdout is empty — its
            # summary only prints after every check runs — so the banner named no field, no
            # value, no rule. _diagnostic_lines falls back to stderr, then to a plain statement
            # of the crash, so this is never blank.
            restored = restore(args.file, before)
            post_rc, _, _, post_problems = validate()
            print("  ⛔ REFUSED — the write broke the store, so it was ROLLED BACK.")
            if added:
                print("  It introduced %d problem(s) the store did not have before it:" % len(added))
                print("  " + "\n  ".join("- " + a for a in added))
                if pre_rc != 0:
                    print("  (%d pre-existing problem(s) stand as well and are NOT this write's; "
                          "they are why the store still fails after the rollback.)"
                          % len(pre_problems or []))
            else:
                print("  " + "\n  ".join(_diagnostic_lines(rc, out, err)))
            # "Back to before" means back to the pre-write problem set — which, on a store that
            # was already invalid, is not "validates clean" but "the same problems as before".
            back = (post_rc == 0) if pre_rc == 0 else (post_problems is not None
                                                        and pre_problems is not None
                                                        and set(post_problems) == set(pre_problems))
            if restored and back:
                if pre_rc == 0:
                    print("  ✅ Rolled back; the store is byte-identical to before and validates.")
                else:
                    print("  ✅ Rolled back; the store is byte-identical to before, with only "
                          "its pre-existing problem(s).")
                print("  Nothing was written. Fix the input and re-run — retrying is safe.")
            else:
                # Never claim a rollback that did not happen. This is the one outcome that
                # needs a human, and saying so plainly is the whole point.
                print("  ⛔⭐ ROLLBACK FAILED — THE FILE IS IN AN UNKNOWN STATE. DO NOT RETRY.")
                print("  Restore %s from git before any further write." % STORES[args.file])
            return 1

        # ---- dev #133: the write landed clean — resolve any ask that DECLARED this action
        # answers it, under the SAME lock hold. Two facts, one transaction boundary.
        # ADR-031 B2/B3 — `ASK_ACTION_FOR_ARRAY` is permanently empty now (both actions that
        # ever populated it were promoted off nested arrays), so `_array_leaf`/`_action` here
        # can never resolve to anything and this branch is presently inert — left in place for
        # a future nested array with a declared `resolves_when` action, the same reasoning
        # `ASK_ACTION_FOR_ARRAY`'s own comment states.
        if args.file == "opportunities" and args.op in ("append", "set-in") and args.rest:
            _array_leaf = args.rest[0].split(".")[-1]
            _action = ASK_ACTION_FOR_ARRAY.get(_array_leaf)
            for aid, title in resolve_linked_asks_dated(args.rid, None, _action) if _action else ():
                print("  ✦ resolved ask %r — %s (its declared action is now recorded)"
                      % (aid, title[:60]))
        # ADR-031 B2 — the applications-store write path's own resolution: the ask's rid is the
        # APPLICATION'S opp_id (an ask names an opportunity, never an application), and the
        # evidence is this store's own `_applications_action_evidence`, never a nested array.
        if args.file == "applications" and args.op in ("create", "set"):
            _opp_id = new_row.get("opp_id") if args.op == "create" else rec.get("opp_id")
            if _opp_id:
                _when = _applications_action_evidence(_opp_id)
                for aid, title in resolve_linked_asks_dated(_opp_id, _when, "application"):
                    print("  ✦ resolved ask %r — %s (its declared action is now recorded)"
                          % (aid, title[:60]))
        # ADR-031 B3 — the touches-store write path's own resolution, the exact mirror of
        # applications' above: the ask's rid is the TOUCH'S opp_id (an ask names an
        # opportunity, never a touch), and the evidence is this store's own
        # `_touches_action_evidence`, never a nested array.
        if args.file == "touches" and args.op in ("create", "set"):
            _opp_id = new_row.get("opp_id") if args.op == "create" else rec.get("opp_id")
            if _opp_id:
                _when = _touches_action_evidence(_opp_id)
                for aid, title in resolve_linked_asks_dated(_opp_id, _when, "outreach"):
                    print("  ✦ resolved ask %r — %s (its declared action is now recorded)"
                          % (aid, title[:60]))
        # ⭐ ADR-031 B4 (design §17) — "resolution is atomic with the act": a plan whose
        # `resolves_when` is 'goal-reached' resolves the moment the stage this write just
        # landed moves to screening or beyond, under the SAME lock hold, never a later sweep
        # that may not run. Mirrors `resolve_linked_asks_dated`'s own best-effort shape: the
        # opportunity write already landed and validated; this never un-lands it.
        if args.file == "opportunities" and args.op in ("create", "set"):
            _new_stage = new_row.get("stage") if args.op == "create" else rec.get("stage")
            for pid, resolution in _resolve_plan_goal(args.rid, _new_stage):
                print("  ✦ resolved plan %r — %s (goal-reached, design §17)" % (pid, resolution))
    finally:
        # Under --already-locked the hold belongs to the CALLING RUN — releasing it here would
        # strip the protection off the rest of the run's write phase mid-flight.
        if not args.already_locked:
            release_lock()

    if args.already_locked:
        print("  written atomically · validator clean · run's lock left in place")
    else:
        print("  written atomically · validator clean · lock released")
    for _note in getattr(args, "reuse_notes", None) or []:
        print(_note)
    if minted:
        if args.file == "touches":
            print("  · touch id minted: %s — name it on the draft entry's own `**Touch:**` "
                  "line, or as trigger_ref on whatever it causes" % ", ".join(minted))
        elif args.file == "cover_letters":
            print("  · cover letter id minted: %s — name it as cover_letter_id on the "
                  "application it goes with" % ", ".join(minted))
        else:
            print("  · app_id minted: %s — name it as trigger_ref on whatever this application "
                  "causes" % ", ".join(minted))
    if args.file == "opportunities":
        _your_move_visibility_note(new_row if args.op == "create" else rec)
    return 0


def _your_move_visibility_note(rec):
    """dev #142 (public #24) — close the SILENCE at the moment the record is made. The
    reporter's row (user-owned, backlog, future date) was invisible on the decisions
    surface with no warning at creation; the membership fix handles that combination, and
    this covers the residue: any row that names the owner as next_action_owner but lands in
    NO Your Move group (a parked backlog row, `in-motion`, a closed status). Advisory only —
    it never blocks a write, and it fails open, because a broken profile must not make the
    write API refuse."""
    try:
        import your_move as _ym
        import profile as _profile
        reason = _ym.invisible_reason(rec or {}, _profile.owner_token())
    except Exception:
        return
    if reason:
        print("  ℹ️ NOT ON YOUR MOVE — this row names you as next_action_owner, but %s."
              % reason)
        print("  (dev #142: a decision recorded invisibly looks handled and is not.)")


if __name__ == "__main__":
    sys.exit(main())
