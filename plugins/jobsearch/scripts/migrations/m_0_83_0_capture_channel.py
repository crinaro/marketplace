"""Migration 0.83.0: `m_0_83_0_capture_channel()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import json
import os
import shutil
from migrations.support_uid import _uid_text_read

VERSION = "0.83.0"


# ⭐⭐ KEYED "0.83.0" (dev #825 / public #176; design-sweep-misfires.md section 3.4) -- 0.82.1 is the newest jobsearch
# release at the branch base (`jobsearch--v0.82.1` is tagged on the public remote; plugin.json read 0.82.1 on f379166c).
# A profile that installed 0.82.1 is stamped exactly "0.82.1", and pending_for()'s strict `<` fires a migration keyed to
# "0.83.0". Re-verify at the moment 0.83.0 is cut. It touches only data/pending_actions.jsonl.
CAPTURE_CHANNEL_PRE_COPY = "pending_actions.jsonl.pre-0.83.0"


def m_0_83_0_capture_channel(profile, apply_it, _inject_fault=None):
    """0.83.0 -- every queued `capture-role` item names the channel its sighting came from (dev #825 / public #176;
    design-sweep-misfires.md section 3.4, R3).

    WHY. `record.py capture-batch` attributes a sighting to a channel. An item queued by a LinkedIn sweep before 0.83.0
    carries NO `channel_id` (the sweep's QUERY lines name none, by contract), and a `login`-access board can never be
    named by `board_hosts`, so in a profile with several boards the item was REFUSED (`capture-refused`) every run. From
    0.83.0 the producer stamps the channel at queue time; this stamps the items already waiting.

    WHAT IT DOES. For each PENDING `capture-role` item (after `deferred.replay`) with no `channel_id`, it finds the ONE
    `swept-board` catalog entry whose `sighting_hosts` domain-match the host of the item's `ref` (a value matches itself
    and every subdomain: `board_hosts.host_matches`) and appends the item's replayed state plus that entry's
    `channel_id`, as a FULL row with the same `id`. That is the same fact the producer stamps; it is not a profile lookup,
    so it does not depend on the profile holding the row (capture resolves it, `record._item_channel_why` step 1).
    Siblings, quarantine, claim and withheld fields are carried, so every earlier fold survives, and a 0.82.x engine
    folds a full row the same way (READ, `deferred.replay`; not run). No line is rewritten, and it is NOT a new fold
    kind: replay treats an unknown kind as the item's newest full row, so a fold kind would REPLACE the item after a
    rollback.

    RESIDUE. An item whose host matches no entry (or several) is COUNTED and NAMED and nothing is written for it; it
    meets capture's refusal, which names the fix. A done, closed or non-capture item is never touched.

    ⭐ PRESERVE, THEN TRANSFORM, THEN QUERY. The queue is read STRICTLY first: one line that does not parse is PENDING
    naming it, never a false "0 done". The catalog is the prerequisite: an unreadable catalog, or one with no valid
    `sighting_hosts` on any swept-board entry, is PENDING (an engine defect), never "0 done". Before the first write
    `data/pending_actions.jsonl` is copied byte for byte to `data/pending_actions.jsonl.pre-0.83.0` (never over a copy
    already there: that is the true original of an earlier partial run); a failed copy writes nothing and is PENDING.
    After the append the queue is RE-READ and replayed, and a planned item still lacking `channel_id` is PENDING.
    IDEMPOTENT: a second run plans nothing. HONEST ZERO: an absent queue, and a queue with nothing to stamp, are DONE
    with no output (residue is named).

    CONCURRENCY, STATED. `deferred.py` has no queue lock. A `_claim` appended between this read and its append is
    overridden by the full row (its `claimed_by` reverts); a claim is a 45-minute lease, so the worst case is one
    duplicated claim of one capture item.

    `_inject_fault="shortfall"` is a TEST SEAM that makes the re-read check fail. Returns `(done, message)`."""
    import board_hosts as _bh
    import channel_catalog as _cc
    import deferred as _deferred
    path = os.path.join(profile, "data", "pending_actions.jsonl")
    rows, _raws, err = _uid_text_read(profile, "pending_actions")
    if err:
        return False, ("  ⏳ 0.83.0 PENDING -- %s. Nothing was written: appending to a queue this could not fully "
                       "read would hide that line. Fix it and this runs again next session." % err)
    todo = [i for i in _deferred.replay(rows)
            if i.get("kind") == _deferred.KIND_CAPTURE and i.get("status") == "pending" and not i.get("channel_id")]
    if not todo:
        return True, ""
    try:
        catalog = _cc.load_catalog()
    except _cc.CatalogError as exc:
        return False, ("  ⏳ 0.83.0 PENDING -- the channel catalog cannot be read (%s), so %d queued capture item(s) were "
                       "not stamped and nothing was written." % (exc, len(todo)))
    entries = [e for e in catalog["entries"] if e.get("kind") == "swept-board"
               and isinstance(e.get("sighting_hosts"), list) and e["sighting_hosts"]
               and all(_bh.valid_host(h) for h in e["sighting_hosts"]) and e.get("channel_id")]
    if not entries:
        return False, ("  ⏳ 0.83.0 PENDING -- the channel catalog has no swept-board entry with valid sighting_hosts, so "
                       "%d queued capture item(s) were not stamped and nothing was written. This is an engine defect, "
                       "not a profile one; it runs again next session." % len(todo))

    # ---- plan --------------------------------------------------------------------------------------
    plan, residue = [], []
    for item in todo:
        host = _bh.host_of(item.get("ref"))
        hit = [e for e in entries if host and any(_bh.host_matches(host, h) for h in e["sighting_hosts"])]
        if len(hit) == 1:
            plan.append((item, hit[0]["channel_id"]))
        else:
            residue.append("%s (%s)" % (item.get("id"), "host %s" % host if host else "no host"))
    residue_note = (" %d queued capture item(s) match no catalog board and stay as they are, to be refused at capture "
                    "with the fix named: %s" % (len(residue), ", ".join(residue)) if residue else "")
    if not plan:
        return True, "  ⚠️ 0.83.0:" + residue_note
    if not apply_it:
        return True, ("  would stamp a channel on %d queued capture item(s)%s"
                      % (len(plan), "." + residue_note if residue else ""))

    # ---- preserve ----------------------------------------------------------------------------------
    copy_path = os.path.join(profile, "data", CAPTURE_CHANNEL_PRE_COPY)
    if not os.path.exists(copy_path):
        try:
            shutil.copy2(path, copy_path)
        except (OSError, shutil.Error) as exc:
            return False, ("  ⏳ 0.83.0 PENDING -- pending_actions.jsonl could not be preserved to %s (%s), so NOTHING "
                           "was written." % (CAPTURE_CHANNEL_PRE_COPY, exc))

    # ---- transform: append, never rewrite ----------------------------------------------------------
    try:
        with open(path, "rb") as fh:
            body = fh.read()
        lead = b"" if (not body or body.endswith(b"\n")) else b"\n"
        text = "".join(json.dumps(dict(item, channel_id=cid), ensure_ascii=False) + "\n" for item, cid in plan)
        with open(path, "ab") as fh:
            fh.write(lead + text.encode("utf-8"))
    except OSError as exc:
        return False, ("  ⏳ 0.83.0 PENDING -- the queue could not be appended to (%s); the original is also at data/%s; "
                       "offered again next session." % (exc, CAPTURE_CHANNEL_PRE_COPY))

    # ---- query: the success condition is what the disk says now ------------------------------------
    after, _r, a_err = _uid_text_read(profile, "pending_actions")
    now_by_id = {i.get("id"): i for i in _deferred.replay(after or [])}
    short = [str(item.get("id")) for item, cid in plan
             if a_err or (now_by_id.get(item.get("id")) or {}).get("channel_id") != cid]
    if _inject_fault == "shortfall":
        short = short or ["(injected)"]
    if short:
        return False, ("  ⏳ 0.83.0 PENDING -- %s still without the stamped channel after the write (the original is at "
                       "data/%s); offered again next session." % (", ".join(short), CAPTURE_CHANNEL_PRE_COPY))
    head = ("  ✅ capture channels (0.83.0) -- stamped a channel on %d queued capture item(s) (the original queue is "
            "kept at data/%s)" % (len(plan), CAPTURE_CHANNEL_PRE_COPY))
    return True, head + ("\n " + residue_note if residue else "")
