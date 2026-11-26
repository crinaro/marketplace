"""two_stores: a write that changes the `companies` store and the `opportunities` store as one (jobsearch 0.94.0, dev 1062;
docs/design-role-first.md 4.4, 12 RF9). The only caller today is `record.py decide <opp> pursue`, which makes the role's company a target.

`mutation.run` makes the ONE single-store write every store verb shares. A `PairMutation` is that write plus the edit of a second
store, and `mutation._write_locked` then runs the sequence `capture-batch` already runs for the same two stores:

  1. under the lock, re-read both stores and apply both edits (the pair is judged on what is really on disk, never on what the
     verb saw before it waited for the lock);
  2. snapshot BOTH stores' bytes, and the validator's problem set;
  3. save `companies` FIRST, then `opportunities` (`save_in_order`);
  4. validate the two together; a write that introduced a problem is put back in BOTH stores, byte for byte, verified
     (`restore_all`), and a save that raised is put back the same way.

WHY THAT ORDER. Two `os.replace` calls are not one: a process killed between them leaves a targeted company and a role that is still
undecided. That is SAFE (the question is asked again, and the next `decide` finds the company already targeted from this role and
changes nothing there). The other order would leave a pursued role whose company was never targeted, which cannot be told from a
pursue the owner declined, and which nothing asks again. A kill is a `BaseException` and is deliberately NOT caught here: nothing
runs between the saves, so nothing can undo the first one, and nothing should pretend to.

Capability module of record.py (an entry point over `recording/`). Python 3.9+, standard library only."""

from recording.common import Mutation
from recording.store_files import STORES, _load_or_empty, load, restore, save_atomic

COMPANIES = "companies"


class PairMutation(Mutation):
    """A `Mutation` of one existing row plus `edit(companies, opps, channels) -> (changed, line)`, which edits the `companies` rows it
    is given IN PLACE and says whether it changed any and what to tell the owner (`line`, may be empty). `opps` are the opportunity
    rows AFTER `apply`, `channels` the channel rows. `changed` and `line` hold the answer of the last `settle`."""

    def __init__(self, desc, apply, edit):
        Mutation.__init__(self, desc, apply)
        self.edit = edit
        self.changed = False
        self.line = ""


def settle(m, opps):
    """Read `companies` and `channels` as they are NOW, run `m.edit` over them and `opps`, and record the answer on `m`. Returns the
    edited `companies` rows when the edit changed any (they are saved first), else None (the write is the single store's alone)."""
    companies = load(COMPANIES)
    changed, line = m.edit(companies, opps, _load_or_empty("channels"))
    m.changed, m.line = bool(changed), line or ""
    return companies if m.changed else None


def shadow_extra(m, opps):
    """`({store: rows}, line)` for `--dry-run`: the stores `dry_run_validate` must shadow beside the verb's own, and what the owner is
    told. Nothing is written; `m.edit` works on rows read from disk and the dry run never saves them."""
    if not isinstance(m, PairMutation):
        return {}, ""
    companies = settle(m, opps)
    return ({COMPANIES: companies} if companies is not None else {}), m.line


def restore_all(before):
    """Put every `{store: bytes}` in `before` back and return True only if EVERY one is verifiably back. Each is tried even after one
    fails: a rollback that stops at the first failure leaves the others in the state the failed write made."""
    return all([restore(store, blob) for store, blob in before.items()])


def unrecoverable_line(before):
    """The sentence a rollback that did not verify ends with, naming each file to take back from git."""
    return ("restore %s from git before any further write" % " and ".join(STORES[s] for s in before))


def save_in_order(stores, before):
    """Save each `(store, rows)` of `stores` in order. Returns None when every save landed, else the lines to print after putting
    EVERY store in `before` back: a save that raised (a full disk, a permission) must not leave the first store written and the
    second not. A `BaseException` (a kill) is not caught: see the module docstring."""
    try:
        for store, rows in stores:
            save_atomic(store, rows)
    except Exception as e:                                  # noqa: BLE001 - said, and the stores are put back
        ok = restore_all(before)
        names = " and ".join(STORES[s] for s in before)
        lines = ["  ⛔ REFUSED — a store could not be written (%s: %s), so %s were put back." % (type(e).__name__, e, names)]
        if ok:
            lines.append("  ✅ Rolled back; every store is byte-identical to before. Nothing was written. Retrying is safe.")
        else:
            lines.append("  ⛔⭐ ROLLBACK FAILED — THE FILES ARE IN AN UNKNOWN STATE. DO NOT RETRY. %s." % unrecoverable_line(before).capitalize())
        return lines
    return None
