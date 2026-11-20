"""catalog: the `channel-catalog` verb: turn shipped catalog boards on (`add`, by entry or `--kind`), and settle a
board the candidate edited that the catalog also changed (`take` / `keep`).

Capability module of record.py (an entry point over `recording/`)."""

import json
from recording.row_checks import _diagnostic_lines, dry_run_validate, new_problems, validate
from recording.common import _Refused, _run_date_value
from recording.store_files import (
    LockError,
    STORES,
    _load_or_empty,
    load,
    lock_is_held,
    release_lock,
    restore,
    save_atomic,
    snapshot,
    take_lock,
)


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
