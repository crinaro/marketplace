"""Migration 0.48.0: `m_0_48_0_probe_single_token_ack()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import json
import os
from migrations.support_jsonl import _read_jsonl

VERSION = "0.48.0"


def m_0_48_0_probe_single_token_ack(profile, apply_it):
    """0.48.0 — public #90, the repair half. `reconcile.person_terms()` used to append a
    single-token name as a BARE, unquoted OR'd search term (fixed at the source above — see
    `person_terms`'s own docstring); against a short common first name this searched the
    WHOLE mailbox and posted a `store-behind-mailbox` finding (`brief.post_store_behind_
    mailbox`, D13) for every one of the eight held contacts whose name happened to be one
    token, all false.

    Every `store-behind-mailbox` row is deterministically keyed
    `store-behind-mailbox:<person_id>:<date>` (brief.py). This finds every currently-PENDING
    one, resolves `<person_id>` (through `merged_into`) to its CURRENT name, and — for exactly
    the shape the bug could produce, a one-token name — appends an `_ack` record the same way
    `inbox.py --ack` does (APPEND ONLY; `inbox.jsonl` is a log, never rewritten — see
    `inbox.append`'s own docstring for why a rewrite here would race a concurrent watcher).
    A pending row whose person has a multi-token name is NOT this bug's shape and is left
    exactly as it is, for a human. Re-run safe: only PENDING rows are considered (the replay
    fold `inbox.replay` already treats an acked row as handled), so a second run acks nothing
    new once the first pass has caught up.
    """
    inbox_path = os.path.join(profile, "data", "inbox.jsonl")
    people_path = os.path.join(profile, "data", "people.jsonl")
    if not os.path.exists(inbox_path):
        return True, ""
    import inbox as _inbox
    import graph as _graph
    try:
        raw = _read_jsonl(inbox_path)
    except Exception as e:                                          # noqa: BLE001
        return False, "  ⚠️ inbox.jsonl could not be read — nothing acked: %s" % e
    rows = _inbox.replay(raw)
    pending_sbm = [r for r in rows
                  if r.get("kind") == "store-behind-mailbox" and r.get("status") == "pending"]
    if not pending_sbm:
        return True, ""
    try:
        g = _graph.Graph(os.path.join(profile, "data")) if os.path.exists(people_path) else None
    except Exception:                                               # noqa: BLE001
        g = None
    if g is None:
        # No people store to resolve a name against yet — nothing to ack, and nothing pending
        # forever either: this simply has nothing to say until 0.44.0 lands.
        return True, ""

    to_ack = []
    for r in pending_sbm:
        rid = r.get("id") or ""
        parts = rid.split(":")
        person_id = parts[1] if len(parts) >= 3 and parts[0] == "store-behind-mailbox" else None
        if not person_id:
            continue
        person = g.by_id["people"].get(person_id)
        name = (person or {}).get("name") or ""
        if name and len(name.split()) == 1:
            to_ack.append(rid)

    if not to_ack:
        return True, ""
    if not apply_it:
        # ⭐ COUNTS ONLY, NEVER IDS — this is `--check` output, the exact surface a release
        # preflight captures verbatim into the release record (design-first-real-run-
        # 2026-09-13.md §1 (c): "migrate.py --check output must print counts and never ids —
        # today #94's print carries <app_id>s: that line is the leak shape"). The finding id
        # embeds a person_id; the apply-mode message below still names them, because that
        # output lands only in the owner's own session, same as every other migration's
        # apply-mode summary in this file.
        return True, ("  would ack %d pending store-behind-mailbox finding(s) (0.48.0) — "
                      "single-token name, public #90's own shape" % len(to_ack))

    import datetime
    now_iso = datetime.datetime.now().isoformat(timespec="seconds")
    acks = [{"id": rid, "kind": "_ack", "acked_at": now_iso,
            "note": "auto-acked by 0.48.0 migration — single-token name term sent unquoted/"
                    "bare searched the whole mailbox (public #90); false positive"}
           for rid in to_ack]
    # ⭐ `inbox.append()` is NOT used here — its `INBOX` path is a MODULE-LEVEL constant
    # resolved from `_root.profile_root()` at IMPORT time, i.e. THIS PROCESS's own ambient
    # profile, never the `profile` argument a migration is asked to act on (the exact
    # dev #278/#259 shape CLAUDE.md trap 10 names: a helper that resolves its own root instead
    # of taking one). Append the same shape `inbox.append()` writes (one JSON object per line,
    # APPEND ONLY — `inbox.py`'s own docstring on why a rewrite here would race a concurrent
    # watcher), directly at the target profile's own path.
    with open(inbox_path, "a", encoding="utf-8") as fh:
        for r in acks:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return True, ("  ✅ store-behind-mailbox ack (0.48.0) — %d false finding(s) acked "
                 "(single-token name, public #90): %s"
                 % (len(to_ack), ", ".join(to_ack[:10])))
