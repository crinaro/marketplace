"""suggestions: the suggestion verbs: `suggest` (the strategist's ask, and nothing else), `confirm` (the candidate writes
the suggested row and resolves the ask in one write of two stores) and `decline`.

Capability module of record.py (an entry point over `recording/`)."""

import json
import os
import re
from recording import profile_paths as _paths
from recording.row_checks import _diagnostic_lines, dry_run_validate, model, new_problems, validate
from recording.common import _Refused, _now, _validator_module
from recording.field_shapes import typed
from recording.network_verbs import _live_person, _network_gate, _network_row_write, _remove_new_store
from recording.proposals import PROPOSAL_USAGE, _deep
from recording.store_files import (
    LockError,
    STORES,
    _load_or_empty,
    find,
    load,
    lock_is_held,
    release_lock,
    restore,
    save_atomic,
    snapshot,
    take_lock,
)


def _suggest_allowed_keys(store):
    """The fields a suggestion for `store` may carry (closed; `validate_data` checks the same set on the stored ask)."""
    _vd = _validator_module()
    if store == "companies":
        return set(_vd.SUGGEST_COMPANY_KEYS)
    if store == "people":
        return set(_vd.SUGGEST_PERSON_KEYS)
    return {f for f in model()["stores"]["plans"]["fields"] if f != "assessments"}


def _suggested_row(store, op, tid, fields, row, today):
    """The row `fields` would leave behind, as a NEW dict (`row` is the target as it stands, None for a create). Raises `_Refused`.
    A company gains `status_on` with its status exactly as `company-status` writes it; a created plan is `active` unless the
    suggestion says otherwise. Nothing here knows the candidate's motivation: `confirm` supplies it."""
    if store == "companies":
        new = dict(row)
        new["status"], new["status_on"] = fields["status"], today
        if fields.get("motivation") is not None:
            new["motivation"] = fields["motivation"]
        return new
    if store == "people":
        new = dict(row)
        new.update(fields)
        return new
    new = {"id": tid, "status": "active"}
    new.update(fields)
    new["id"] = tid
    return new


def cmd_suggest(args):
    """`record.py suggest --store S --action set|create --target-id ID --values '<json>' --ask "<q>"`: the strategist's proposal of ONE
    row for the candidate to confirm (design-network-first.md 8.1, 8.2). It writes an ASK (`kind: suggestion`, with `suggests`) and
    NOTHING ELSE: the suggested row is not written, and does not exist until `record.py confirm <ask_id>`. What may be suggested is
    closed: a company becomes an `active-target` (the candidate supplies the motivation at confirm), a plan is created (subject_kind
    search, company or person), a person's `cadence` is set; a PERSON row is never suggested. The would-be row is validated on a
    shadow copy first, and a suggestion that would not validate is refused. `suggests.before` records what the fields held now, so
    `confirm` can refuse a target that changed in between. The same suggestion twice is not written twice. Exit 0 written (or already
    open); 1 refused; 2 usage; 3 the profile is not ready."""
    usage = "usage: " + PROPOSAL_USAGE["suggest"]
    if args.rid or args.rest:
        print(usage)
        return 2
    store, op, tid, text = args.suggest_store, args.suggest_action, args.suggest_id, (args.ask_text or "").strip()
    if not (store and op and tid and args.values_json is not None and text):
        print(usage)
        return 2
    gate = _network_gate()               # before anything is read: a profile not ready for a 0.86.0 write reads as "not ready", never "refused"
    if gate:
        print(gate)
        return 3
    _vd = _validator_module()
    try:
        if (store, op) not in _vd.SUGGEST_OPS:
            raise _Refused("%s %s is not something to suggest: one of %s (a person row itself is never suggested: finding people is a "
                           "manual LinkedIn step)." % (store, op, ", ".join("%s %s" % (a, b) for a, b in sorted(_vd.SUGGEST_OPS))))
        try:
            fields = json.loads(args.values_json)
        except ValueError as e:
            raise _Refused("--values is not JSON (%s)." % e)
        if not (isinstance(fields, dict) and fields):
            raise _Refused("--values must be a non-empty JSON object of the fields to write.")
        bad = sorted(set(fields) - _suggest_allowed_keys(store))
        if bad:
            raise _Refused("a %s suggestion may not carry %s (allowed: %s)." % (store, ", ".join(bad),
                                                                                 ", ".join(sorted(_suggest_allowed_keys(store)))))
        if store == "companies":
            if fields.get("status") != "active-target":
                raise _Refused("a company suggestion proposes `status: active-target`; got %r." % fields.get("status"))
            if fields.get("motivation") is not None:
                mv = fields["motivation"]
                if not (isinstance(mv, int) and not isinstance(mv, bool) and _vd.MOTIVATION_MIN <= mv <= _vd.MOTIVATION_MAX):
                    raise _Refused("motivation is the candidate's own number %d-%d; leave it off and `confirm` asks for it."
                                   % (_vd.MOTIVATION_MIN, _vd.MOTIVATION_MAX))
        if store == "plans" and fields.get("subject_kind") not in _vd.SUGGEST_PLAN_SUBJECT_KINDS:
            raise _Refused("a plan suggestion's subject_kind is one of %s; got %r."
                           % ("/".join(sorted(_vd.SUGGEST_PLAN_SUBJECT_KINDS)), fields.get("subject_kind")))
        if store == "plans" and "id" in fields and fields["id"] != tid:
            raise _Refused("--values id %r is not --target-id %r." % (fields["id"], tid))
        rows = _load_or_empty(store)
        target = find(rows, tid)
        if op == "set":
            if target is None:
                raise _Refused("%r resolves to no %s record." % (tid, store))
            if store == "people":
                _live_person(rows, tid)
            if store == "companies" and target.get("status") == "active-target":
                raise _Refused("%s is already an active-target." % tid)
        elif target is not None:
            raise _Refused("%s %r already exists." % (store, tid))
        before = {k: target.get(k) for k in fields} if op == "set" else None
        today = _now().date().isoformat()
        would_be = _suggested_row(store, op, tid, fields, target, today)
        shadow_target = _deep(rows)
        if op == "create":
            shadow_target.append(would_be)
        else:
            shadow_target[[r.get("id") for r in rows].index(tid)] = would_be
    except _Refused as e:
        print("⛔ REFUSED — %s" % e)
        return 1
    suggests = {"store": store, "op": op, "id": tid, "fields": fields}
    if before is not None:
        suggests["before"] = before

    def new_ask(asks):
        for a in asks:
            s = a.get("suggests")
            if a.get("kind") == "suggestion" and not a.get("resolved_on") and isinstance(s, dict) \
                    and (s.get("store"), s.get("op"), s.get("id")) == (store, op, tid):
                if s.get("fields") == fields:
                    return None, a["id"]
                raise _Refused("%s already holds an open suggestion for %s %s with different values; confirm or decline it first."
                               % (a["id"], store, tid))
        base = "suggest-%s-%s-%s" % (today, store, re.sub(r"[^a-z0-9]+", "-", str(tid).lower()).strip("-"))
        used, aid, n = {a.get("id") for a in asks}, base, 2
        while aid in used:
            aid, n = "%s-%d" % (base, n), n + 1
        title = {"companies": "Suggested target: %s", "plans": "Suggested plan: %s", "people": "Suggested cadence: %s"}[store] % tid
        return {"id": aid, "kind": "suggestion", "title": title, "ask": text, "created": today, "suggests": suggests}, aid

    try:
        asks = _load_or_empty("asks")
        ask, aid = new_ask(asks)
        if ask is None:
            print("suggest: %s already holds this suggestion (nothing written)" % aid)
            return 0
        pre_problems = validate()[3]
        # The WOULD-BE row (and the ask that proposes it) validated together on a shadow copy: nothing real is written by this check.
        rc, out, err, problems = dry_run_validate(store, shadow_target, extra={"asks": asks + [ask]})
        if rc != 0:
            added = new_problems(pre_problems, problems)
            if added is None or added:
                print("⛔ REFUSED — the suggested row would not validate (nothing written):")
                print("  " + "\n  ".join("- " + a for a in (added if added else _diagnostic_lines(rc, out, err))))
                return 1
    except _Refused as e:
        print("⛔ REFUSED — %s" % e)
        return 1
    except (OSError, ValueError) as e:
        print("⛔ REFUSED — a store cannot be read (%s); nothing written." % e)
        return 1

    def edit(rows):
        a, _aid = new_ask(rows)
        if a is None:
            return ["suggest: %s already holds this suggestion" % _aid]
        rows.append(a)
        return ["suggest: %s -- %s %s %s awaits the candidate's `record.py confirm %s` (or `decline`); nothing else was written"
                % (a["id"], op, store, tid, a["id"])]
    return _network_row_write(args, "suggest", "asks", edit)


def _suggestion_ask(asks, ask_id):
    """The open `kind: suggestion` ask `ask_id`, or `_Refused` naming what it is instead."""
    ask = find(asks, ask_id)
    if ask is None:
        raise _Refused("%r resolves to no asks record." % ask_id)
    if ask.get("kind") != "suggestion":
        raise _Refused("%s is a %r ask, not a suggestion: confirm and decline answer suggestions only." % (ask_id, ask.get("kind")))
    if ask.get("resolved_on"):
        raise _Refused("%s was already resolved (%s on %s)." % (ask_id, ask.get("resolution"), ask.get("resolved_on")))
    if not isinstance(ask.get("suggests"), dict):
        raise _Refused("%s carries no `suggests`: there is nothing to confirm." % ask_id)
    return ask


def _confirm_edit(asks, target_rows, ask_id, overrides, today):
    """Apply the suggestion `ask_id` names to `target_rows` and resolve its ask in `asks`, both IN PLACE; returns the lines to print.
    Raises `_Refused` before either is touched in a way that matters (the caller holds shadow copies). The target is RE-READ by the
    caller and compared with `suggests.before`: a field that changed since the suggestion refuses, naming each difference."""
    _vd = _validator_module()
    ask = _suggestion_ask(asks, ask_id)
    s = ask["suggests"]
    store, op, tid, fields = s.get("store"), s.get("op"), s.get("id"), dict(s.get("fields") or {})
    if (store, op) not in _vd.SUGGEST_OPS:
        raise _Refused("%s suggests %r %r, which is not a suggestable write." % (ask_id, store, op))
    allowed = _suggest_allowed_keys(store) - ({"id"} if store == "plans" else {"status"} if store == "companies" else set())
    bad = sorted(set(overrides) - allowed)
    if bad:
        raise _Refused("--set %s: a %s suggestion lets the candidate set %s." % (", ".join(bad), store, ", ".join(sorted(allowed))))
    merged = dict(fields)
    merged.update(overrides)
    row = find(target_rows, tid)
    if op == "set":
        if row is None:
            raise _Refused("%s %r no longer exists: `record.py decline %s`." % (store, tid, ask_id))
        changed = {k: (v, row.get(k)) for k, v in (s.get("before") or {}).items() if row.get(k) != v}
        if changed:
            raise _Refused("%s %r changed since it was suggested (%s): `record.py decline %s` and ask again."
                           % (store, tid, "; ".join("%s was %r, is now %r" % (k, a, b) for k, (a, b) in sorted(changed.items())), ask_id))
    elif row is not None:
        raise _Refused("%s %r already exists (it was created after the suggestion): `record.py decline %s`." % (store, tid, ask_id))
    if store == "companies":
        mv = merged.get("motivation")
        if not (isinstance(mv, int) and not isinstance(mv, bool) and _vd.MOTIVATION_MIN <= mv <= _vd.MOTIVATION_MAX):
            raise _Refused("targeting %s needs `--set motivation=<%d-%d>`: how much the candidate wants to work there is their own "
                           "statement, never the strategist's." % (tid, _vd.MOTIVATION_MIN, _vd.MOTIVATION_MAX))
        row["status"], row["status_on"], row["motivation"] = merged["status"], today, mv
        line = "confirm: %s is an active-target (motivation %d, status_on %s)" % (tid, mv, today)
    elif store == "people":
        row["cadence"] = merged["cadence"]
        line = "confirm: %s cadence set to %r" % (tid, merged["cadence"])
    else:
        new = _suggested_row(store, op, tid, merged, None, today)
        target_rows.append(new)
        line = "confirm: plan %s created (%s %s, %s)" % (tid, new.get("subject_kind"), new.get("subject_id"), new.get("status"))
    ask["resolved_on"], ask["resolution"] = today, "confirmed"
    return [line, "confirm: %s resolved confirmed" % ask_id]


def cmd_confirm(args):
    """`record.py confirm <ask_id> [--set field=value ...]`: the candidate's yes to a suggestion (design-network-first.md 8.2). It writes
    the suggested row (a company's `status`, `status_on` and the candidate's `motivation`; a plan; a person's `cadence`) and resolves
    the ask (`resolution: confirmed`) in ONE locked write of two stores, validated and rolled back TOGETHER: when either save fails, or
    the validator finds a problem the stores did not have, both are put back byte for byte. `--set` is the candidate's own value for any
    field they may edit (a company's `motivation`, which a target REQUIRES; a person's `cadence`; any field of a plan but its id). A
    target that changed since it was suggested refuses, naming the difference. Exit 0 written; 1 refused or rolled back; 2 usage; 3 the
    profile is not ready."""
    usage = "usage: " + PROPOSAL_USAGE["confirm"]
    if not args.rid or args.rest:
        print(usage)
        return 2
    overrides = {}
    for pair in (args.set_pairs or []):
        k, eq, v = pair.partition("=")
        if not (k.strip() and eq):
            print("⛔ REFUSED — --set %r is not field=value.\n%s" % (pair, usage))
            return 1
        if k.strip() in overrides:
            print("⛔ REFUSED — --set %s is given twice." % k.strip())
            return 1
        overrides[k.strip()] = v
    gate = _network_gate()
    if gate:
        print(gate)
        return 3
    try:
        ask = _suggestion_ask(_load_or_empty("asks"), args.rid)
    except _Refused as e:
        print("⛔ REFUSED — %s" % e)
        return 1
    except (OSError, ValueError) as e:
        print("⛔ REFUSED — a store cannot be read (%s); nothing written." % e)
        return 1
    store = (ask.get("suggests") or {}).get("store")
    if store not in ("companies", "plans", "people"):
        print("⛔ REFUSED — %s suggests store %r, which is not a suggestable store." % (args.rid, store))
        return 1
    try:
        overrides = {k: typed(store, k, v) for k, v in overrides.items()}
    except _Refused as e:
        print("⛔ REFUSED — --set: %s" % e)
        return 1
    today = _now().date().isoformat()

    def build(stores):
        return _confirm_edit(stores["asks"], stores[store], args.rid, overrides, today)
    return _two_store_write(args, "confirm", store, "asks", build)


def _restore_or_remove(store, blob):
    """Put `store` back as it was: its bytes when it existed, nothing at all when the write created it. True when verifiably back."""
    return restore(store, blob) if blob is not None else _remove_new_store(store)


def _two_store_write(args, verb, store_a, store_b, build):
    """ONE locked, validated, rollback-verified write of TWO stores. `build(stores)` mutates `{store_a: rows, store_b: rows}` in place and
    returns the lines to print, or raises `_Refused` (nothing has been written when it does). The sequence is `_network_row_write`'s:
    a shadow, `--dry-run` runs the real validator over both shadows and stops, the lock, a re-read INSIDE it, the build again on what
    is really there, a snapshot of both, the two atomic saves, the validator, and a byte-identical rollback of BOTH when either save
    raised or the write introduced a problem the stores did not have. `--_inject-fault between-stores` raises after the first save and
    before the second (a test seam: the half-written state must never survive it). Returns the exit code."""
    gate = _network_gate()
    if gate:
        print(gate)
        return 3
    try:
        stores = {store_a: _load_or_empty(store_a), store_b: _load_or_empty(store_b)}
        shadow = _deep(stores)
        lines = build(shadow)
    except _Refused as e:
        print("⛔ REFUSED — %s" % e)
        return 1
    except (OSError, ValueError) as e:
        print("⛔ REFUSED — a store cannot be read (%s); nothing written." % e)
        return 1
    pre_rc, _, _, pre_problems = validate()
    rc, out, err, problems = dry_run_validate(store_a, shadow[store_a], extra={store_b: shadow[store_b]})
    if rc != 0:
        added = new_problems(pre_problems, problems)
        if added is None or added:
            print("⛔ REFUSED — a real write of this would be refused and rolled back (nothing is written):")
            print("  " + "\n  ".join("- " + a for a in (added if added else _diagnostic_lines(rc, out, err))))
            return 1
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
            take_lock("record.py %s %s" % (verb, args.rid), wait=args.wait)
        except LockError as e:
            print("  REFUSED — %s" % e)
            return 1
    try:
        try:
            stores = {s: (load(s) if os.path.exists(os.path.join(_paths.DATA, STORES[s])) else []) for s in (store_a, store_b)}
            lines = build(stores)               # re-read INSIDE the lock, and build on what is really there
        except _Refused as e:
            print("⛔ REFUSED — %s" % e)
            return 1
        snaps = {store_a: snapshot(store_a), store_b: snapshot(store_b)}
        pre_problems = validate()[3]
        try:
            save_atomic(store_a, stores[store_a])
            if args.inject_fault == "between-stores":
                raise RuntimeError("injected fault: between-stores")
            save_atomic(store_b, stores[store_b])
        except Exception as e:                  # noqa: BLE001 -- ANY failure between the two saves must not leave one of them behind
            ok = all([_restore_or_remove(store_a, snaps[store_a]), _restore_or_remove(store_b, snaps[store_b])])
            print("⛔ the write of %s and %s failed (%s) and was %s." % (store_a, store_b, e, "ROLLED BACK (both stores byte-identical)"
                  if ok else "NOT VERIFIABLY ROLLED BACK -- restore %s and %s from git" % (STORES[store_a], STORES[store_b])))
            return 1
        rc, out, err, post_problems = validate()
        added = new_problems(pre_problems, post_problems)
        if rc != 0 and (added is None or added):
            ok = all([_restore_or_remove(store_a, snaps[store_a]), _restore_or_remove(store_b, snaps[store_b])])
            print("⛔ the write left the stores invalid and was %s."
                  % ("ROLLED BACK (both stores byte-identical)" if ok else
                     "NOT VERIFIABLY ROLLED BACK -- restore %s and %s from git" % (STORES[store_a], STORES[store_b])))
            print("  " + "\n  ".join(added if added else _diagnostic_lines(rc, out, err)))
            return 1
    finally:
        if not args.already_locked:
            release_lock()
    for line in lines:
        print(line)
    return 0


def cmd_decline(args):
    """`record.py decline <ask_id> [--why "<text>"]`: the candidate's no to a suggestion (design-network-first.md 8.2). It resolves the ask
    `declined` (`resolved_on` today; `--why` is kept in the ask's `note`) and writes nothing else: the suggested row was never written.
    Exit 0 written; 1 refused; 2 usage; 3 the profile is not ready."""
    usage = "usage: " + PROPOSAL_USAGE["decline"]
    if not args.rid or args.rest:
        print(usage)
        return 2
    today = _now().date().isoformat()
    why = (args.why or "").strip()

    def edit(rows):
        ask = _suggestion_ask(rows, args.rid)
        ask["resolved_on"], ask["resolution"] = today, "declined"
        if why:
            ask["note"] = ((ask.get("note") + " | ") if ask.get("note") else "") + "declined: " + why
        return ["decline: %s resolved declined; nothing else was written" % args.rid]
    return _network_row_write(args, "decline", "asks", edit)
