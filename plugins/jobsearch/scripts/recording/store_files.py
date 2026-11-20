"""stores: the record stores and their mechanics: the `STORES` table, the run lock (take, verify, release), load and
find, the atomic save, and the byte-identical snapshot and restore a rollback uses.

Capability module of record.py (an entry point over `recording/`)."""

import json
import os
import subprocess
import sys
import tempfile
from recording import profile_paths as _paths
from recording.profile_paths import ENGINE_SCRIPTS


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
          "asks": "asks.jsonl",
          # dev #834 (jobsearch 0.86.0, design-network-first.md 5.2) -- `commitments` joins STORES so a legacy meeting can be
          # classified (`set <id> kind interview --file commitments`) and the chat verbs' dry-run validates it. The chat fields are
          # written by `chat`, `attended` and `intro-offered`; `attendance` without `attendance_on` is refused by the validator.
          "commitments": "commitments.jsonl",
          # dev #834 (jobsearch 0.86.0, design-network-first.md 6) -- `proposals` joins STORES so the generic `set` / `set-in` write
          # `conceptual_agreement` and `doc_ref` and the proposal verbs' dry-run validates it. `proposal` mints the id
          # (`<opp_id>-pN`); `proposal-status` is the one writer of `status`, `status_on` and `date` of an existing row.
          "proposals": "proposals.jsonl"}
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


LOCK = os.path.join(ENGINE_SCRIPTS, "runlock.py")


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
    p = os.path.join(_paths.DATA, STORES[store])
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
    p = os.path.join(_paths.DATA, STORES[store])
    fd, tmp = tempfile.mkstemp(dir=_paths.DATA, prefix=".record-", suffix=".tmp")
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
    p = os.path.join(_paths.DATA, STORES[store])
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
    p = os.path.join(_paths.DATA, STORES[store])
    fd, tmp = tempfile.mkstemp(dir=_paths.DATA, prefix=".rollback-", suffix=".tmp")
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
