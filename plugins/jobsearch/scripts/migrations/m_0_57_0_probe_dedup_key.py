"""Migration 0.57.0: `m_0_57_0_probe_dedup_key()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import json
import os
from migrations.support_jsonl import _read_jsonl

VERSION = "0.57.0"


def m_0_57_0_probe_dedup_key(profile, apply_it):
    """0.57.0 — dev #485/public #108 ask 3, the repair half. `brief.post_store_behind_mailbox`
    used to key its finding `store-behind-mailbox:<person_id>:<date>` — a NEW id every day —
    so the same unresolved contact was re-posted as a fresh PENDING finding on every later run
    day even after the owner had explicitly acked one of the dated ids. The code fix (same
    version) drops the date: the id is now `store-behind-mailbox:<person_id>` alone, and dedup
    checks every existing id regardless of status, not `pending` only.

    PRESERVE, THEN TRANSFORM. A profile that already acked one of the OLD dated ids for a
    contact has a true fact on disk — "the owner looked at this and it was nothing new" — and
    that fact is keyed to an id the new code will never compute again. Left alone, the very
    next probe for that contact computes the new dateless id, finds it absent from
    `inbox.replay()`'s state (nothing ever wrote it), and posts it PENDING — re-queuing every
    one of them once, the exact symptom the key change exists to stop (brief-485's own
    warning). So: for every person_id with AT LEAST ONE acked (`status == "handled"`) old-style
    dated finding anywhere in the log — not merely the newest one, since the reposting bug
    itself means a later, unacked, freshly-reposted dated row can sit alongside an earlier
    acked one for the same person — write the new dateless id's finding AND its `_ack` record,
    both APPEND ONLY, the same shape `m_0_48_0_probe_single_token_ack` already establishes for
    this exact file. A bare `_ack` row for an id `inbox.replay()` has never seen does NOTHING
    (`replay()`'s own fold requires the id already IN STATE before an `_ack` can flip its
    status — see `inbox.replay`'s docstring) — the finding row must be written first, or this
    migration would silently preserve nothing.

    Idempotent: skips any person_id whose dateless id is already present (any status) in the
    replayed state, so a second run writes nothing new.

    ⭐ PENDING ON ITS OWN READ, never a false '0 done' (CLAUDE.md's own migration rule) —
    unlike `m_0_46_0_brief_line`'s prerequisite (another migration not yet landed), this
    migration's own dependency is simply being able to READ `inbox.jsonl`: an unreadable log
    means "acked or not" cannot be answered, so refusing (returning PENDING) rather than
    reporting a false "nothing to migrate" is the only honest outcome — the same shape
    `m_0_48_0_probe_single_token_ack` already uses for the identical read."""
    inbox_path = os.path.join(profile, "data", "inbox.jsonl")
    if not os.path.exists(inbox_path):
        return True, ""
    import inbox as _inbox
    try:
        raw = _read_jsonl(inbox_path)
    except Exception as e:                                          # noqa: BLE001
        return False, ("  ⏳ 0.57.0 PENDING — inbox.jsonl could not be read, so it is not "
                       "known whether any store-behind-mailbox ack needs to carry forward: "
                       "%s" % e)

    state = _inbox.replay(raw)
    have_ids = {r.get("id") for r in state}

    # Every OLD-style dated id (3+ colon-parts, `store-behind-mailbox:<person_id>:<date>`),
    # grouped by person_id — ANY acked row for that person is enough (see docstring: the
    # reposting bug itself can leave an acked row and a later unacked repost side by side).
    acked_person_ids = set()
    for r in state:
        rid = r.get("id") or ""
        parts = rid.split(":")
        if len(parts) < 3 or parts[0] != "store-behind-mailbox":
            continue
        if r.get("status") == "handled":
            acked_person_ids.add(parts[1])

    to_migrate = sorted(pid for pid in acked_person_ids
                        if ("store-behind-mailbox:%s" % pid) not in have_ids)
    if not to_migrate:
        return True, ""
    if not apply_it:
        # COUNTS ONLY, NEVER IDS in --check output (design-first-real-run-2026-09-13.md §1(c),
        # the same rule m_0_48_0_probe_single_token_ack's own check-mode branch follows).
        return True, ("  would carry forward %d already-acked store-behind-mailbox finding(s) "
                      "to the dateless key (0.57.0) — dev #485/public #108 ask 3"
                      % len(to_migrate))

    import datetime
    now_iso = datetime.datetime.now().isoformat(timespec="seconds")
    rows = []
    for pid in to_migrate:
        new_id = "store-behind-mailbox:%s" % pid
        rows.append({
            "id": new_id, "kind": "store-behind-mailbox", "status": "pending",
            "summary": "store behind mailbox: contact:%s (carried forward, already acked)" % pid,
            "detail": "0.57.0 migration — an old dated id for this contact was already acked; "
                      "this dateless id preserves that fact so the key change does not "
                      "re-queue it (dev #485/public #108 ask 3).",
            "urgency": "normal", "found_at": now_iso,
        })
        rows.append({"id": new_id, "kind": "_ack", "acked_at": now_iso,
                    "note": "auto-acked by 0.57.0 migration — carried forward from an already-"
                            "acked dated id (dev #485/public #108 ask 3); preserve, then "
                            "transform"})
    # `inbox.append()` is NOT used here — its `INBOX` path is resolved from `_root.
    # profile_root()` at IMPORT time (THIS process's own ambient profile), never the
    # `profile` argument a migration is asked to act on (dev #278/#259, CLAUDE.md trap 10).
    # Append directly at the target profile's own path instead — the same append-only shape.
    with open(inbox_path, "a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return True, ("  ✅ store-behind-mailbox dedup key (0.57.0) — %d ack(s) carried forward to "
                 "the dateless key (dev #485/public #108 ask 3): %s"
                 % (len(to_migrate), ", ".join(to_migrate[:10])))
