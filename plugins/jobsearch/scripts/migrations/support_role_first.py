"""support_role_first: what `m_0_94_0_role_first` reads, selects and writes besides its own pin (jobsearch 0.94.0, dev 1055, 1062, 1063;
docs/design-role-first.md 11, 12 MG1).

One module of `migrations/` (design-component-segmentation.md 5), read by `m_0_94_0_role_first` only. It holds the parts of the migration that are not its
sequence: the strict read of the three stores the migration depends on, the two selections (a same-run contradiction of design 6.2 among undecided roles; a pending
capture item whose degradation the card now answers, design 5.1), the byte-identical `.pre-0.94.0` copies and the run lock the writes need. Nothing here imports
another migration, and everything that touches a store is read-only except `preserve`, `append_releases`, `take_run_lock` and `release_run_lock`.

  `read_store`             one store, STRICT: every non-blank line is a JSON object, or the answer is a sentence naming the line. An absent file is "absent", never `[]`.
  `select_contradictions`  `[(opp_id, at, why)]` for `recording.withdraw_write.write_withdrawals`: every read that stands, via render, quotes no description and was
                           contradicted by a later failed render of the same page in the same run (`recording.read_withdraw.contradiction`, the ONE definition, asked of each
                           failed attempt with the attempts before it). A role the owner decided is left alone and counted. A role whose `jd_read` this engine cannot parse
                           is a store line that cannot be read: `StoreError`, and the migration is PENDING.
  `select_releases`        the ids of the pending `capture-role` items that carry a quarantine every code of which the card now answers
                           (`searching.card_evidence`, built from the profile's own config). The item stores the codes but not WHICH filter a `filter-dropped` query dropped, so
                           that code is answered only when the card states all three facts a dropped filter can have damaged (setting, place, posted date): the one
                           reading that never releases a role the evidence does not clear (OURS, stated; a later clean sighting or the owner still releases the rest).
  `preserve`               `data/<name>` to `data/<name>.pre-0.94.0`, sha1-checked. A copy already there is used only when it is PROVEN to hold, byte for byte, every row
                           about to change; otherwise it is left alone and the next free name (`.pre-0.94.0.<n>`) gets a new copy. Nothing is ever overwritten.
  `append_releases`        one append-only `_unquarantine` record per id, the shape of `deferred._append_unquarantine` (a parity test runs `deferred.replay` over it).
  `take_run_lock`          the run lock file `runlock.py` reads (`support_files._readmit_lock_path`), taken non-blocking, with who and when.

Python 3.9+, standard library only."""

import datetime
import json
import os
import shutil

import jd_read as jd
from migrations.support_files import _readmit_lock_path, _sha1_file
from recording.read_withdraw import DECIDED_VERDICTS, contradiction
from searching.card_evidence import Evidence

PRE_OPPS = "opportunities.jsonl.pre-0.94.0"
PRE_QUEUE = "pending_actions.jsonl.pre-0.94.0"
SESSION_CAP = 50                                  # design 11 step 4: withdrawals a session; the rest wait for the next one
RUN_ID = "migrate-0.94.0"                         # the `run` the withdrawal attempts carry (no whitespace: the verb's own rule)
WITHDRAW_WHY = ("a failed render of this same page in this same run contradicts this read, and it quotes no description "
                "(withdrawn by the 0.94.0 migration)")
UNQUARANTINE_BECAUSE = "card-evidence 0.94.0"
KIND_CAPTURE, KIND_UNQUARANTINE = "capture-role", "_unquarantine"
FACTS_OF_A_DROPPED_FILTER = ("setting", "place", "posted")      # `card_evidence.FILTER_NEEDS`, all of them (see the module docstring)


class StoreError(Exception):
    """A store this migration depends on cannot be read; the text names it, and the migration is PENDING with nothing written."""


def read_store(profile, name):
    """`(rows, None)` for `data/<name>`, every non-blank line a JSON object; `(None, None)` when the file is absent; `(None, sentence)` when it cannot be read or a line
    does not parse (named by number). Absent is NOT empty: the caller says which of the two it accepts."""
    path = os.path.join(profile, "data", name)
    if not os.path.exists(path):
        return None, None
    try:
        with open(path, "rb") as fh:
            text = fh.read().decode("utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return None, "data/%s cannot be read (%s)" % (name, e)
    rows = []
    for n, line in enumerate(text.split("\n"), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as e:
            return None, "data/%s line %d does not parse: %s" % (name, n, e)
        if not isinstance(row, dict):
            return None, "data/%s line %d is not an object" % (name, n)
        rows.append(row)
    return rows, None


def select_contradictions(rows):
    """`(specs, decided)`: `specs` is `[(opp_id, at, why)]` in store order, `decided` the number of contradicted reads left alone because the role has a verdict.
    Raises `StoreError` naming a role whose `jd_read` this engine refuses to parse."""
    specs, decided = [], 0
    for row in rows:
        if not row.get("jd_read"):
            continue
        try:
            atts = jd.attempts(row)
        except jd.JdReadError as e:
            raise StoreError("data/opportunities.jsonl: the jd_read of %s cannot be read (%s)" % (row.get("id"), e))
        standing = {a["at"] for a in jd.standing_of(atts) if a["outcome"] == jd.READ}
        found = []
        for i, att in enumerate(atts):
            hit = contradiction({"jd_read": {"attempts": atts[:i]}}, att)
            if hit is None:
                continue
            read, kept = hit
            if not kept and read["at"] in standing and read["at"] not in found:
                found.append(read["at"])
        if not found:
            continue
        if row.get("verdict") in DECIDED_VERDICTS:
            decided += len(found)
            continue
        specs.extend((row.get("id"), at, WITHDRAW_WHY) for at in found)
    return specs, decided


def fold_queue(rows):
    """The queue as its own `replay` folds it, for the one thing this migration asks: `{id: item}` of the items that are still pending, each with its `quarantine`
    as the newest records leave it. (`deferred.replay` is an entry point: this is its fold of `_done` and `_unquarantine` over the newest record per id, and
    `tests/test_migrate_0_94_0_role_first.py::TestQueueFoldParity` runs both over the same rows.)"""
    state = {}
    for r in rows:
        rid, kind = r.get("id"), r.get("kind")
        if not rid:
            continue
        if kind == "_done" and rid in state:
            state[rid] = dict(state[rid], status="done")
        elif kind == KIND_UNQUARANTINE and rid in state:
            state[rid] = dict(state[rid], quarantine=None)
        elif kind not in ("_done", "_claim", "_release", "_withheld", KIND_UNQUARANTINE, "_sibling"):
            state[rid] = r
    return {k: v for k, v in state.items() if v.get("status") == "pending"}


def card_role(item):
    """What `searching.card_evidence.Evidence` reads off a ROLE line, rebuilt from what the item stored of its card (`deferred.role_payload`)."""
    role = item.get("role") if isinstance(item.get("role"), dict) else {}
    return {"setting": role.get("location_declared") or "?", "location": role.get("location_listed") or "?",
            "posted_parsed": ("stated", role["posted"]) if role.get("posted") else ("unknown", None)}


def answered(evidence, item, codes):
    """True when the card of `item` answers EVERY code in `codes` (`truncated` and `param-added` never held a shown role; `filter-dropped` needs all three facts;
    `window-unapplied` needs the posted date; `query-unparsed` and any code not named here are never answered)."""
    role = card_role(item)
    for code in codes:
        if code in ("truncated", "param-added"):
            continue
        if code == "filter-dropped" and evidence.answers(role, FACTS_OF_A_DROPPED_FILTER):
            continue
        if code == "window-unapplied" and evidence.answers(role, ("posted",)):
            continue
        return False
    return True


def select_releases(queue_rows, evidence):
    """The ids, in queue order, of the pending `capture-role` items whose quarantine the card now answers."""
    out = []
    for rid, item in fold_queue(queue_rows).items():
        q = item.get("quarantine")
        if item.get("kind") != KIND_CAPTURE or not isinstance(q, dict):
            continue
        codes = q.get("because")
        if isinstance(codes, list) and codes and all(isinstance(c, str) for c in codes) and answered(evidence, item, codes):
            out.append(rid)
    return out


def evidence_for(profile):
    """`searching.card_evidence.Evidence` over the profile's `config.json`; a config that cannot be read answers nothing about a place (every place is an echo)."""
    try:
        with open(os.path.join(profile, "config.json"), encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        cfg = None
    return Evidence.from_config(cfg)


COPY_TRIES = 99                                   # `.pre-0.94.0`, then `.pre-0.94.0.1` ... `.99`: more than this many distinct copies of one store is a profile to look at


def _lines(path):
    """The non-blank lines of the file at `path`, as bytes exactly as stored (no stripping), or None when it cannot be read."""
    try:
        with open(path, "rb") as fh:
            return [l for l in fh.read().split(b"\n") if l.strip()]
    except OSError:
        return None


def rows_to_change(profile, name, ids):
    """The stored lines of `data/<name>` whose row id is in `ids`, as bytes exactly as they are now (a queue item's id has several lines: every one is returned)."""
    out = []
    for line in _lines(os.path.join(profile, "data", name)) or []:
        try:
            row = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            continue
        if isinstance(row, dict) and row.get("id") in ids:
            out.append(line)
    return out


def _holds(path, required):
    """True when the file at `path` carries every line in `required` byte for byte. A file that is not a plain file, cannot be read or has none of them never holds."""
    have = _lines(path) if os.path.isfile(path) else None
    return bool(required) and have is not None and set(required) <= set(have)


def _write_copy(src, dst, name, copy_name):
    """`(copy_name, None)` once `dst` is a sha1-checked copy of `src` made now, or `(None, sentence)`. `dst` is created exclusively, so nothing is ever overwritten, and a
    copy that failed its check is removed (it must not pass for the original later)."""
    try:
        with open(src, "rb") as rd, open(dst, "xb") as wr:
            wr.write(rd.read())
        shutil.copystat(src, dst)
        if _sha1_file(src) != _sha1_file(dst):
            raise OSError("the copy does not match the original")
    except (OSError, shutil.Error) as e:
        try:
            os.remove(dst)
        except OSError:
            pass
        return None, "data/%s could not be preserved to data/%s (%s)" % (name, copy_name, e)
    return copy_name, None


def preserve(profile, name, copy_name, ids):
    """`(copy, None)`: `data/<copy>` holds the original of every row of `data/<name>` whose id is in `ids` (the rows the next steps will change), byte for byte as it is
    now; `copy` is the file's name, `copy_name` or `copy_name.<n>`. Or `(None, sentence)` when no such copy could be had.

    A copy that is already there is trusted for nothing but what it is PROVEN to hold: it is read, and used only when it carries every one of those lines exactly. One that
    does not (an earlier partial run's from a store that has moved on, a copy carried over with a copied profile, an unrelated file under that name) is left exactly as
    it is, and the next name in `copy_name`, `copy_name.1`, `copy_name.2` ... is tried: the first that holds them is used, the first that is free gets a new whole-store copy
    (created exclusively, sha1-checked). A session with nothing left to change never reaches here, so it writes no copy."""
    src = os.path.join(profile, "data", name)
    required = rows_to_change(profile, name, ids)
    for n in range(COPY_TRIES + 1):
        cand = copy_name if n == 0 else "%s.%d" % (copy_name, n)
        dst = os.path.join(profile, "data", cand)
        if not os.path.lexists(dst):
            return _write_copy(src, dst, name, cand)
        if _holds(dst, required):
            return cand, None
    return None, "data/%s has %d copies named data/%s.<n> already and none holds the rows about to change" % (name, COPY_TRIES + 1, copy_name)


def append_releases(profile, ids, now=None):
    """Append one `_unquarantine` record per id to `data/pending_actions.jsonl` (append-only, a record per line, a missing final newline put back first)."""
    path = os.path.join(profile, "data", "pending_actions.jsonl")
    at = (now or datetime.datetime.now()).isoformat(timespec="seconds")
    lines = "".join(json.dumps({"id": rid, "kind": KIND_UNQUARANTINE, "because": UNQUARANTINE_BECAUSE, "at": at}, ensure_ascii=False) + "\n" for rid in ids)
    glue = b""
    if os.path.exists(path) and os.path.getsize(path):
        with open(path, "rb") as rd:
            rd.seek(-1, os.SEEK_END)
            glue = b"" if rd.read(1) == b"\n" else b"\n"
    with open(path, "ab") as fh:
        fh.write(glue + lines.encode("utf-8"))


class LockBusy(Exception):
    """The run lock is held: a run may be writing a store this migration would rewrite."""


def take_run_lock(profile, who="migrate 0.94.0"):
    """Take the run lock the way `runlock.py` records it, non-blocking. Returns `(lock_path, made_dir)`; raises `LockBusy` when it is held and `OSError` when it could
    not be taken. Release with `release_run_lock`."""
    lock_path = _readmit_lock_path(profile)
    made_dir = False
    try:
        lock_dir = os.path.dirname(lock_path)
        if not os.path.isdir(lock_dir):
            os.makedirs(lock_dir)
            made_dir = True
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise LockBusy(lock_path)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"who": who, "pid": os.getpid(), "taken_at": datetime.datetime.now().isoformat(timespec="seconds")}, fh)
    return lock_path, made_dir


def release_run_lock(lock_path, made_dir):
    """Remove the lock file this took, and the directory only when this made it (never a real `.git`)."""
    try:
        os.remove(lock_path)
    except OSError:
        pass
    if made_dir:
        try:
            os.rmdir(os.path.dirname(lock_path))
        except OSError:
            pass


def lock_is_held(profile):
    """True when the run lock file for this profile exists (`runlock.py`'s own rule for the path)."""
    return os.path.exists(_readmit_lock_path(profile))
