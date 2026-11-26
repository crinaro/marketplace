"""mutation: the ONE single-store write every store verb of record.py shares (moved out of `main`).

`preflight` and `target` run before a verb builds its change (the `--reuse` refusal, `fields`, loading the store
and finding the record); the verb's own function (in generic, decisions, persons, or `read_verb` /
`sourcing_verb` here) describes the change as a `common.Mutation` before touching anything; `run` then either
predicts the write (`--dry-run`: the same introduced-only rules and the same validator, on a copy) or makes it:
the lock (or the caller's verified hold under `--already-locked`), the store re-read inside it, the
introduced-only rules, the atomic save, the validator, the byte-identical rollback, and, under the same hold, the
asks and plans the write answers.
"""

import json
from recording.row_checks import (
    _diagnostic_lines,
    _jd_read_writer,
    _posting_writer,
    dry_run_validate,
    introduced_row_violations,
    new_problems,
    validate,
    verb_owned_refusal,
)
from recording.common import Mutation, _Refused, _Usage
from recording.decisions import _your_move_visibility_note
from recording.affiliations_verb import AFFILIATION_OPS, cmd_affiliations
from recording.employment import EMPLOYMENT_OPS, cmd_employment
from recording.fit_keys import FIT_KEY_OPS, cmd_fit_key, cmd_retopic
from recording.presence_verbs import PRESENCE_OPS, cmd_presence
from recording.document_verbs import DOCUMENT_OPS, cmd_document, order_refusal
from recording.follow_verbs import FOLLOW_OPS, cmd_follow, owned_refusal
from recording.generic import cmd_fields
from recording.persons import _reuse_people
from recording.reads import JD_READ_OPS, _jd_read_mutation, _stage_line
from recording.resolves import (
    ASK_ACTION_FOR_ARRAY,
    _applications_action_evidence,
    _load_asks,
    _resolve_plan_goal,
    _touches_action_evidence,
    linked_asks,
    resolve_linked_asks_dated,
)
from recording.sourcing import _sourcing_mutation
from recording import two_stores
from recording.store_files import (
    AUTO_MINT_LABEL,
    LockError,
    find,
    load,
    lock_is_held,
    release_lock,
    snapshot,
    take_lock,
)


def preflight(args):
    """Before the store is loaded: `--reuse` off `create --file people` is refused, `fields` is printed, and
    `create --file people --reuse` may answer with an existing person. Returns the exit code to stop with, else
    None.

    jobsearch 0.91.0: the two employment verbs (`employment`, `moved`) make their own write and answer here, the way
    `fields` does: record.py's `_dispatch` is an entry point at its line budget, so a new verb reaches its command from
    this, the store-verb path's first step (recording/employment.py). `affiliations` (user.json's one writer,
    recording/affiliations_verb.py) is reached the same way, and so are `retopic` and `fit-key` (recording/fit_keys.py)
    and jobsearch 0.92.0's `stop-following` (recording/follow_verbs.py)."""
    if args.reuse and not (args.op == "create" and args.file == "people"):
        print("⛔ REFUSED — --reuse applies only to `create <id> '<json>' --file people`.")
        return 1
    if args.op == "fields" or args.fields:
        return cmd_fields(args)
    if args.op in EMPLOYMENT_OPS:
        return cmd_employment(args)
    if args.op in AFFILIATION_OPS:
        return cmd_affiliations(args)
    if args.op in FIT_KEY_OPS:
        return cmd_retopic(args) if args.op == "retopic" else cmd_fit_key(args)
    if args.op in DOCUMENT_OPS:
        return cmd_document(args)
    if args.op in PRESENCE_OPS:
        return order_refusal(args) or cmd_presence(args)      # §3.3: one call, docx_state.blocks_md_write
    if args.op in FOLLOW_OPS:
        return cmd_follow(args)

    if args.reuse:
        _reuse_rc = _reuse_people(args)
        if _reuse_rc is not None:
            return _reuse_rc
    return None


def target(args):
    """Load the verb's store and find its record: `create` needs the id absent, every other verb present. Returns
    (rows, rec), or the exit code of a refusal it has printed."""
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
    return rows, rec


def read_verb(args, rec):
    """read-jd / read-failed on the shared write: `reads._jd_read_mutation` builds it. Returns a Mutation, or the
    exit code (2 usage, 1 refusal) of what it printed."""
    # dev #820 / public #175 -- see `_jd_read_mutation`: it validates the flags and returns (desc, apply); the lock,
    # the introduced-only rules (with the `jd_read` writer token held), the validator and the rollback are the
    # shared path every other verb takes.
    try:
        desc, apply = _jd_read_mutation(args, rec)
    except _Usage as e:
        print(str(e))
        return 2
    except _Refused as e:
        print("⛔ REFUSED — %s" % e)
        return 1
    return Mutation(desc, apply)


def sourcing_verb(args, rec):
    """screened / lean / listed-pay / posted on the shared write: `sourcing._sourcing_mutation` builds it. Returns
    a Mutation, or the exit code (2 usage, 1 refusal) of what it printed."""
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
    return Mutation(desc, apply)


def run(args, rows, rec, m):
    """Make (or, with --dry-run, predict) the write Mutation `m` describes, on the `rows` and `rec` `target` loaded.
    Returns record.py's exit code."""
    print("%s: %s" % (args.rid, m.desc))
    if args.dry_run:
        return _dry_run(args, rows, rec, m)
    refused = _take_lock(args)
    if refused is not None:
        return refused
    try:
        refused, rec = _write_locked(args, m)
        if refused is not None:
            return refused
        _resolve_declared(args, m.new_row, rec)
    finally:
        # Under --already-locked the hold belongs to the CALLING RUN — releasing it here would
        # strip the protection off the rest of the run's write phase mid-flight.
        if not args.already_locked:
            release_lock()
    _report_written(args, m, rec)
    return 0


def _dry_run(args, rows, rec, m):
    """--dry-run: apply the change to a copy and judge it the way the real write would. Returns the exit code."""
    new_row, apply, minted = m.new_row, m.apply, m.minted
    _apply_rows, _feed_posting_written = m.apply_rows, m.feed_posting_written
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
    with _posting_writer(_feed_posting_written), _jd_read_writer(args.op in JD_READ_OPS):
        _introduced = (introduced_row_violations(
                           args.file, None if args.op == "create" else rec, _after_row)
                       + verb_owned_refusal(
                           args.op, args.file, None if args.op == "create" else rec, _after_row)
                       + owned_refusal(args.op, args.file, None if args.op == "create" else rec, _after_row))
    if _introduced:
        print("  ⛔ a REAL (non-dry-run) write of this would be REFUSED (nothing is written):")
        print("  " + "\n  ".join("- " + m for m in _introduced))
        return 1
    pre_rc, _, _, pre_problems = validate()
    _extra, _also = two_stores.shadow_extra(m, shadow_rows)       # jobsearch 0.94.0: a pursue's company, shadowed beside the role
    rc, out, err, problems = dry_run_validate(args.file, shadow_rows, extra=_extra) if _extra else dry_run_validate(args.file, shadow_rows)
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
    if _also:
        print("  · " + _also)
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


def _take_lock(args):
    """Take the run lock, or verify the caller's hold under --already-locked. Returns the exit code of a refusal it
    has printed, else None."""
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
    return None


def _write_locked(args, m):
    """Under the lock: re-read the store, apply the change, refuse an introduced violation, save atomically and
    validate (rolling back what this write broke). Returns (exit code of a refusal or None, the record as written)."""
    new_row, apply = m.new_row, m.apply
    _apply_rows, _feed_posting_written = m.apply_rows, m.feed_posting_written
    rows = load(args.file)          # re-read INSIDE the lock — the file may have moved
    rec = find(rows, args.rid)
    _row_before = None
    if args.op == "create":
        if rec is not None:
            print("  a record with id %r appeared between read and lock — aborting."
                  % args.rid)
            return 1, rec
        rows.append(new_row)
    else:
        if rec is None:
            print("  record vanished between read and lock — aborting.")
            return 1, rec
        _row_before = json.loads(json.dumps(rec))    # as it stood, for the check below
        _apply_rows[0] = rows
        try:
            apply(rec)
        except KeyError as e:
            print("  %s" % e)
            return 1, rec
    # ⭐ dev #644 item 5 / dev #427 — INTRODUCED-ONLY RULES. Refused HERE, on the row being
    # written or changed, before a byte lands: the whole-store validator only WARNS about
    # rows that already exist (validate_data.INTRODUCED_ONLY_RULES), so this is the one
    # place a new violation is stopped. Nothing is written, so there is nothing to roll back.
    with _posting_writer(_feed_posting_written), _jd_read_writer(args.op in JD_READ_OPS):
        _introduced = (introduced_row_violations(
                           args.file, _row_before, new_row if args.op == "create" else rec)
                       + verb_owned_refusal(
                           args.op, args.file, _row_before, new_row if args.op == "create" else rec)
                       + owned_refusal(args.op, args.file, _row_before, new_row if args.op == "create" else rec))
    if _introduced:
        print("  ⛔ REFUSED — this write would introduce a violation (nothing was written):")
        print("  " + "\n  ".join("- " + m for m in _introduced))
        return 1, rec
    # ⭐⭐ SNAPSHOT BEFORE THE WRITE — this is what makes the rollback below possible.
    # Raw bytes, not the parsed rows: restoring exactly what was there cannot reintroduce a
    # formatting difference, and a byte-identical restore is trivially verifiable.
    # GitHub issue #1.
    before = {args.file: snapshot(args.file)}
    # jobsearch 0.94.0 (dev 1062): a PairMutation (`decide <opp> pursue`) may change `companies` in the same transaction. It is read, edited and
    # snapshotted HERE, inside the lock, and saved FIRST (recording/two_stores.py says why that order).
    saves = [(args.file, rows)]
    if isinstance(m, two_stores.PairMutation):
        _companies = two_stores.settle(m, rows)
        if _companies is not None:
            before[two_stores.COMPANIES] = snapshot(two_stores.COMPANIES)
            saves.insert(0, (two_stores.COMPANIES, _companies))

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

    failed = two_stores.save_in_order(saves, before)
    if failed:
        print("\n".join(failed))
        return 1, rec
    refused = _keep_or_roll_back(args, before, pre_rc, pre_problems)
    return refused, rec


def _keep_or_roll_back(args, before, pre_rc, pre_problems):
    """After the save: keep a write that added no problem, roll back (byte for byte, verified) one that did. `before` is
    `{store: bytes}` for EVERY store the write saved (one, or two for a pair). Returns 1 when the validator still fails
    (printed), else None."""
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
        restored = two_stores.restore_all(before)
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
            print("  %s." % two_stores.unrecoverable_line(before).capitalize())
        return 1


def _resolve_declared(args, new_row, rec):
    """Under the same hold, after a clean write: resolve the asks and plans that declared this action answers them."""
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


def _report_written(args, m, rec):
    """What a landed write prints after the lock is released."""
    new_row, minted = m.new_row, m.minted
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
    if isinstance(m, two_stores.PairMutation) and m.line:
        print("  " + m.line)
    if args.file == "opportunities":
        _your_move_visibility_note(new_row if args.op == "create" else rec)
    if args.op in JD_READ_OPS:
        print("  " + _stage_line(args.rid))
