"""persons: people and their involvements: `involve` (link a person to a role later), `create --file people --reuse`
(get-or-create through people.py's matcher) and `merge-person` (a pointer, never a rewrite).

Capability module of record.py (an entry point over `recording/`)."""

import json
import os
import tempfile
from recording import profile_paths as _paths
from recording.row_checks import _diagnostic_lines, validate
from recording.common import Mutation, _now, _plays_mod, _validator_module
from recording.employment import merge_employment
from recording.generic import _merge_would_cycle
from recording.store_files import (
    LockError,
    _load_or_empty,
    find,
    load,
    lock_is_held,
    release_lock,
    take_lock,
)


def _load_involvements():
    try:
        with open(os.path.join(_paths.DATA, "involvements.jsonl"), encoding="utf-8") as fh:
            return [json.loads(l) for l in fh if l.strip()]
    except OSError:
        return []


def _person_name(person_id):
    """The person's display name, for a message/outreach row's own `to` field — never the
    bare id, when a name is available. Fails open to None (the caller falls back to the id
    itself, which is always non-empty)."""
    try:
        import graph as _graph
        g = _graph.Graph(_paths.DATA)
        row = g.by_id["people"].get(person_id)
        return row.get("name") if row else None
    except Exception:                                        # noqa: BLE001 — cosmetic only
        return None


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
        inv_path = os.path.join(_paths.DATA, "involvements.jsonl")
        try:
            with open(inv_path, "rb") as fh:
                before_inv = fh.read()
        except OSError:
            before_inv = None
        fd, tmp = tempfile.mkstemp(dir=_paths.DATA, prefix=".record-involvements-", suffix=".tmp")
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
                    fd2, tmp2 = tempfile.mkstemp(dir=_paths.DATA, prefix=".rollback-involvements-",
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


def merge_person_mutation(args, rows):
    """`merge-person <duplicate-id> --into <survivor-id>` (moved out of record.py main). Returns a Mutation, or the
    exit code of a refusal it has printed."""
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
    # jobsearch 0.91.0 (design-build-reach.md 5.2): two different employers of record are a decision, never a silent win for the
    # survivor's: `--current <company_id|none>` names the one that is current, and the other moves to the survivor's `formerly`
    # (`employment.merge_employment`). The survivor is edited in the SAME locked write, through `apply_rows`.
    dup = find(rows, args.rid)
    survivor_apply, refused = merge_employment(dup or {}, survivor, args.current_company, _now().date().isoformat())
    if refused:
        print("⛔ REFUSED — %s" % refused)
        return 1
    desc = "merge-person into %s" % args.into_id
    if survivor_apply is not None:
        desc += " (the survivor keeps employer %s; the other goes to formerly)" % (
            args.current_company or survivor.get("company_id"))
    holder = [None]

    def apply(r):
        r["status"] = "merged"
        r["merged_into"] = args.into_id
        if survivor_apply is not None:
            survivor_apply(find(holder[0], args.into_id))
    return Mutation(desc, apply, apply_rows=holder)
