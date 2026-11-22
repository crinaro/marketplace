"""generic: the generic store verbs on the shared write: `create`, `set` (and a play's bounded `params.` tweak), `set-in`,
`append`, `show`, `fields`, `link-sibling` / `unlink-sibling` (fold one requisition's duplicate rows, or undo a
fold), and `merge-person`'s cycle check. Each builds a `common.Mutation`; `mutation.run` makes the write.

Capability module of record.py (an entry point over `recording/`)."""

import datetime
import json
import os
import shutil
import tempfile
from recording.boards import sighting_source_url_problem
from recording.capture import _from_item_resolved_channel, copy_capture_item_facts
from recording.row_checks import (
    _POSTING_FIELD,
    _array_enum_registry,
    _enum_registry,
    _object_shaped_fields,
    check_field,
    model,
)
from recording.common import Mutation, _Refused, _now, _validator_module
from recording.employment import stamp_people_create
from recording.ids import mint_app_id, mint_cover_letter_id, mint_touch_id
from recording.parser import _touch_requirement_lines
from recording.posting import _feed_posting_value, _posting_today
from recording.sourcing import _known_match_for, _link_from_item, _new_opportunity_plan, location_replace
from recording.store_files import AUTO_MINT_LABEL, _load_or_empty, find, load


def _merge_would_cycle(people_rows, dup_id, survivor_id):
    """True if pointing `dup_id.merged_into = survivor_id` would close a cycle — i.e. the
    SURVIVOR's own existing merge chain already leads back to `dup_id`. Public #93: `record.py`
    had no merge verb at all, so nothing ever exercised `graph.MergeCycleError`'s refusal from
    the write side; this reuses `graph.py` itself (never a second, hand-rolled chain-walk) by
    writing the hypothetical `people` rows to a throwaway directory and asking
    `graph.Graph.resolve_person` to walk it — the one place this chain is ever resolved
    (graph.py's own docstring: 'a merge is a pointer... graph.py resolves through merged_into
    at read time'). No other store is needed for this question, so the throwaway directory
    carries `people.jsonl` alone; every other store `Graph.__init__` loads is simply absent,
    which it already treats as an empty store."""
    import graph as _graph
    shadow = [dict(r) for r in people_rows]
    for r in shadow:
        if r.get("id") == dup_id:
            r["status"] = "merged"
            r["merged_into"] = survivor_id
    tmpdir = tempfile.mkdtemp(prefix=".record-merge-check-")
    try:
        with open(os.path.join(tmpdir, "people.jsonl"), "w", encoding="utf-8") as fh:
            for r in shadow:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        g = _graph.Graph(data_dir=tmpdir)
        try:
            g.resolve_person(dup_id)
            return False
        except _graph.MergeCycleError:
            return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def coerce(v):
    """A CLI gives strings; the store is typed. Guessing wrong writes "true" where True belongs."""
    if v in ("true", "True"):
        return True
    if v in ("false", "False"):
        return False
    if v in ("null", "None", ""):
        return None
    if v.lstrip("-").isdigit():
        return int(v)
    if v.startswith(("{", "[")):
        return json.loads(v)
    return v


def cmd_show(rec, as_json):
    """Print the whole stored record. Indented JSON by default; `--json` prints ONE compact line (a script reads it).
    Before 0.82.0 `show` dropped `research_log` and `fit` and cut the rest at 3000 characters, so a role looked
    smaller than it was and a reader could not tell what had been left out (SH1). Nothing is left out now."""
    if as_json:
        print(json.dumps(rec, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(rec, ensure_ascii=False, indent=2))
    return 0


def cmd_fields(args):
    """`fields <store>` (or `--fields` on any verb): print what `args.file` accepts, so a caller never has to guess
    (moved out of record.py main)."""
    # ⭐ dev #143 / public #23 failure #3: this listing used to print field names and
    # required-ness ONLY — no enum values for constrained fields, no marker for a field
    # whose value is an object rather than a string. A caller could not construct a valid
    # record from this output alone; it took a failed write plus reading validator source.
    m = model()["stores"][args.file]
    _vd = _validator_module()
    enums = _enum_registry(_vd).get(args.file, {})
    arr_enums = _array_enum_registry(_vd)
    objects = _object_shaped_fields(args.file, _vd)
    print("%s — %s" % (args.file, ", ".join(sorted(m["fields"]))))
    print("  required: %s" % ", ".join(m.get("required") or []))
    if objects:
        print("\n  OBJECT-TYPED (not a string):")
        for f in sorted(objects):
            print("    %s: %s" % (f, objects[f]))
    if enums:
        print("\n  ENUMS (allowed values):")
        for f in sorted(enums):
            print("    %s: {%s}" % (f, ", ".join(sorted(enums[f]))))
    if args.file == "touches":
        print()
        print("\n".join(_touch_requirement_lines(_vd)))
    for a, spec in sorted((m.get("arrays") or {}).items()):
        print("\n  %s[] — %s" % (a, ", ".join(sorted(spec["fields"]))))
        print("     required: %s%s" % (", ".join(spec.get("required") or []),
              ("  · id: %s" % spec["id_field"]) if spec.get("id_field") else ""))
        a_enums = arr_enums.get((args.file, a)) or {}
        if a_enums:
            print("     enums:")
            for f in sorted(a_enums):
                print("       %s: {%s}" % (f, ", ".join(sorted(a_enums[f]))))
    ban = {k: v for k, v in model()["banned_aliases"].items() if not k.startswith("_")}
    print("\n  BANNED ALIASES (same meaning, two spellings): %s"
          % ", ".join("%s->%s" % (k, v) for k, v in sorted(ban.items())))
    return 0


def create_mutation(args, rows, _deferred_mod, _pidx):
    """`create <id> '<json>'` (moved out of record.py main): the new row, built and checked before anything is
    written. `_deferred_mod` and `_pidx` are record.py's `deferred` and `pipeline_index` modules, given for
    `--file opportunities` (None otherwise): a package module never imports an entry point. Returns a Mutation,
    or the exit code of a refusal it has printed."""
    # ⭐ THE MISSING OPERATION (public #17 / dev #97). Without it, adding a brand-new row
    # meant hand-editing the JSONL — the exact ad-hoc read-all/write-all pattern this API
    # exists to abolish, and it recurred across sessions for as long as the gap existed.
    #
    # Deliberately a NEW op rather than `set` auto-creating on an unknown id: an op that
    # creates whenever an id fails to resolve turns every typo'd id into a silent new row,
    # which is the duplicate problem wearing a different hat. Intent is stated, then checked.
    payload = _create_payload(args)
    if isinstance(payload, int):
        return payload
    new_row, _from_item_copied = payload
    minted = _create_mint(args, new_row)
    if isinstance(minted, int):
        return minted
    refused = _create_checks(args, new_row)
    if refused is not None:
        return refused
    # ⭐ dev #728 / public #158 (jobsearch 0.70.0; design-location-screen.md §5.3) -- ONE
    # REQUISITION LISTED AT SEVERAL PLACES IS ONE DECISION. The backstop of the capture-time
    # grouping in `deferred.py --add-roles`: a role being created that the pipeline already holds
    # (an ACTIVE row too -- #136 only ever looked at passed ones) is
    #   * with --from-item: LINKED -- the item's listing and its siblings become sightings of the
    #     existing row (active or passed), the item closes as `linked:<row id>`, exit 0; but a
    #     listing of a PASSED row strictly nearer than every place that row was listed at is
    #     printed `NEARER LISTING` and is NOT linked or closed (R8): it can become a fresh
    #     decision with --force;
    #   * without it: refused with an `append <id> sightings` hint (an active row), or by #136
    #     below (a passed one), exactly as before;
    #   * with --force: created, and the pair is recorded in `distinct_from` so the matching rule
    #     never re-merges it.
    _link_match = None
    _item = None
    if args.file == "opportunities":
        if args.from_item:
            _item = _deferred_mod.load_capture_item(args.from_item)
        _link_match = _known_match_for(rows, new_row, [(_item or {}).get("ref")]
                                       if _item else [])
    refused = _create_known_role(args, rows, new_row, _link_match, _item)
    if refused is not None:
        return refused
    refused, _feed_posting_written = _create_feed_posting(args, new_row, _item)
    if refused is not None:
        return refused
    if _link_match and args.force:
        _dist = list(new_row.get("distinct_from") or [])
        if _link_match[0].get("id") not in _dist:
            _dist.append(_link_match[0].get("id"))
        new_row["distinct_from"] = _dist
    refused = _create_passed_match(args, rows, new_row, _pidx)
    if refused is not None:
        return refused
    desc = "create record (%d field(s): %s)" % (len(new_row), ", ".join(sorted(new_row)))
    if args.from_item:
        desc += (" -- copied from %s: %s" % (args.from_item, ", ".join(_from_item_copied))
                 if _from_item_copied else
                 " -- %s carried no pay, posting date or setting to copy" % args.from_item)

    def apply(r):        # unused for create; the lock section appends new_row instead
        raise AssertionError("create does not mutate an existing record")
    return Mutation(desc, apply, new_row=new_row, minted=minted, feed_posting_written=_feed_posting_written)


def _create_payload(args):
    """create: the JSON row and the facts `--from-item` copies onto it. Returns (new_row, the copied slot names),
    or the exit code of a refusal it has printed."""
    if len(args.rest) != 1:
        print("usage: create <id> '<json object for the full record>'")
        return 2
    try:
        new_row = json.loads(args.rest[0])
    except ValueError as e:
        print("⛔ REFUSED — the record is not valid JSON: %s" % e)
        return 1
    if not isinstance(new_row, dict):
        print("⛔ REFUSED — the record must be a JSON object, got %s."
              % type(new_row).__name__)
        return 1
    # ⭐ dev #715 / public #143, dev #716 / public #142 -- the facts the sweep's ROLE line
    # carried ride the capture-role item onto the opportunity, by a script, not by a model
    # re-typing them (copy_capture_item_facts' docstring).
    _from_item_copied = []
    if args.from_item:
        if args.file != "opportunities":
            print("⛔ REFUSED — --from-item applies only to `create ... --file opportunities`.")
            return 1
        # dev #825 / public #176 -- an item stamped with a channel THIS profile does not hold (a pre-0.76.0 install has
        # no `linkedin-jobsearch` row) would copy an id that does not resolve into sightings[0] and fail later as a
        # validator rollback that names no fix. Resolve it the way `capture-batch` does (`_item_channel_why`), and
        # refuse BEFORE anything is written with the same named fix.
        _item_for_copy, _chan_err = _from_item_resolved_channel(args.from_item)
        if _chan_err:
            print("⛔ REFUSED — --from-item: %s" % _chan_err)
            return 1
        _from_item_copied, _item_err = copy_capture_item_facts(new_row, args.from_item,
                                                                rid=args.rid, item=_item_for_copy)
        if _item_err:
            print("⛔ REFUSED — --from-item: %s" % _item_err)
            return 1
    return new_row, _from_item_copied


def _create_mint(args, new_row):
    """create auto: the id a minting store mints (applications, touches, cover_letters). Returns the minted ids
    (empty when none), or the exit code of a refusal it has printed."""
    minted = []
    # ADR-031 B2 — `applications` is now a top-level store whose own id is minted the SAME
    # way app_id always was (<opp_id>-aN), but the id is no longer known until the record
    # exists: `create auto '{"opp_id": ..., ...}' --file applications` mints it here, from
    # `opp_id` in the payload, against every existing row on that same opp_id. This
    # replaces the old nested-array minting below (0.41.0's own comment), which applied
    # only while `applications` was still `opportunities.applications[]`.
    if args.file == "applications" and args.rid in (None, "auto"):
        _opp_id = new_row.get("opp_id")
        if not _opp_id:
            print("⛔ REFUSED — create auto '{...}' --file applications requires 'opp_id' "
                  "in the JSON payload; the id is minted from it (<opp_id>-aN).")
            return 1
        args.rid = mint_app_id(_opp_id, load("applications"))
        minted = [args.rid]
    # ADR-031 B3 — `touches` is a top-level store whose own id is minted `<person_id>-tN`
    # (design §1: a touch is owned by the PERSON, unlike an application's `<opp_id>-aN`
    # containment). `create auto '{"person_id": ..., ...}' --file touches` mints it here.
    if args.file == "touches" and args.rid in (None, "auto"):
        _person_id = new_row.get("person_id")
        if not _person_id:
            print("⛔ REFUSED — create auto '{...}' --file touches requires 'person_id' "
                  "in the JSON payload; the id is minted from it (<person_id>-tN).")
            return 1
        args.rid = mint_touch_id(_person_id, load("touches"))
        minted = [args.rid]
    # dev #764 / public #162 -- `cover_letters` mints `<opp_id>-clN` from `opp_id`, the same
    # way `applications` mints `<opp_id>-aN`. Before this the id was taken literally, so
    # `create auto ... --file cover_letters` wrote a row whose id was the word "auto".
    if args.file == "cover_letters" and args.rid in (None, "auto"):
        _opp_id = new_row.get("opp_id")
        if not _opp_id:
            print("⛔ REFUSED — create auto '{...}' --file cover_letters requires 'opp_id' "
                  "in the JSON payload; the id is minted from it (<opp_id>-clN).")
            return 1
        args.rid = mint_cover_letter_id(_opp_id, load("cover_letters"))
        minted = [args.rid]
    # dev #764 / public #162 -- a store with NO minting branch cannot honour `create auto`:
    # the placeholder would be written as the row's real id. Refuse, name the store and how to
    # supply an id, and write nothing. (An omitted id is the same request.)
    if args.rid in (None, "auto") and args.file not in AUTO_MINT_LABEL:
        print("⛔ REFUSED — `create auto` is not available for the %r store: it has no id "
              "minting, so \"auto\" would be written as the record's real id. Name the id "
              "yourself: create <id> '<json>' --file %s. (Stores that mint: %s.)"
              % (args.file, args.file, ", ".join(sorted(AUTO_MINT_LABEL))))
        return 1
    return minted


def _create_checks(args, new_row):
    """create: the refuse-before-write guards (intro-request shape, the governing plan, one id, known fields,
    sightings' source_url, required fields). Returns the exit code of a refusal it has printed, else None."""
    # ⭐ design §12 — an unshaped introduction is exactly the row that "looks handled and
    # is not": a new intro-request touch naming neither object is refused at the door.
    # `validate_data.py` treats a MIGRATED intro-request with no object as legal (a
    # migration cannot know a fact it cannot derive) — this refusal is for NEW writes only.
    if (args.file == "touches" and new_row.get("touch_type") == "intro-request"
            and not new_row.get("object_person_id") and not new_row.get("object_company_id")):
        print("⛔ REFUSED — touch_type 'intro-request' with neither object_person_id nor "
              "object_company_id set. An introduction is always ABOUT someone or some "
              "company (design §12) — without one this row looks like any other touch and "
              "nothing could ever ask 'who is being worked toward <company>?'")
        return 1
    # ⭐ ADR-031 B4 (design §17, §26.5) — a freshly created opportunity is auto-assigned
    # its governing `plan_id` from the one active search plan sourcing role/contract,
    # unless the payload already names one. With more than one candidate, `--plan` is
    # required — the refusal names every candidate (§26.5).
    if args.file == "opportunities" and not new_row.get("plan_id"):
        _resolved_plan, _plan_err = _new_opportunity_plan(args.plan_id)
        if _resolved_plan:
            new_row["plan_id"] = _resolved_plan
            new_row["plan_assigned_on"] = datetime.date.today().isoformat()
        elif _plan_err:
            print("⛔ REFUSED — %s" % _plan_err)
            return 1
        # else: no active sourcing plan at all — plan_id stays unset; the required-field
        # check below refuses it the same way any other missing required field would.
    m = model()["stores"][args.file]
    idf = m.get("id_field") or "id"
    if idf in new_row and new_row[idf] != args.rid:
        print("⛔ REFUSED — the JSON carries %s=%r but the command names %r. One id, "
              "stated once." % (idf, new_row[idf], args.rid))
        return 1
    new_row[idf] = args.rid
    if args.file == "people":           # jobsearch 0.91.0: `created` and the first standing are stamped, never typed
        _stamp_refused = stamp_people_create(new_row, _now().date().isoformat())
        if _stamp_refused:
            print("⛔ REFUSED — %s" % _stamp_refused)
            return 1
    # Same refuse-before-write guards every other op gets: unknown keys, aliases, required.
    for k in new_row:
        bad = check_field(args.file, k)
        if bad and not args.force:
            print("⛔ REFUSED — %s" % bad)
            return 1
        spec = (m.get("arrays") or {}).get(k)
        if spec and isinstance(new_row[k], list):
            for i, item in enumerate(new_row[k]):
                if not isinstance(item, dict):
                    continue
                for kk in item:
                    bad = check_field(args.file, kk, array=k)
                    if bad and not args.force:
                        print("⛔ REFUSED — %s[%d]: %s" % (k, i, bad))
                        return 1
    # ⭐ public #83 rule 1 — a freshly created opportunity's own sightings[] get the SAME
    # capture-time check the append branch gives an existing one (see
    # sighting_source_url_problem's own docstring). Never gated by --force, for the same
    # reason as there: a data-integrity rule about an unrecoverable link, not a guess.
    if args.file == "opportunities" and isinstance(new_row.get("sightings"), list):
        _channel_type_by_id = {c.get("id"): c.get("type") for c in _load_or_empty("channels")}
        _receipted = any(a.get("status") in _validator_module().SUBMITTED_APP_STATUS
                        for a in _load_or_empty("applications") if a.get("opp_id") == args.rid)
        _seen_channel_ids = set()
        for _i, _sg in enumerate(new_row["sightings"]):
            if not isinstance(_sg, dict):
                continue    # unshaped entries are the required/array-item guards' job
            _referenced = ({new_row.get("channel_id"), _sg.get("channel_id")}
                          | _seen_channel_ids)
            _problem = sighting_source_url_problem(_sg, _channel_type_by_id, _referenced,
                                                   _receipted)
            if _problem:
                print("⛔ REFUSED — sightings[%d]: %s" % (_i, _problem))
                return 1
            _seen_channel_ids.add(_sg.get("channel_id"))
    missing = [f for f in (m.get("required") or []) if not new_row.get(f)]
    if missing and not args.force:
        print("⛔ REFUSED — %s requires %s" % (args.file, ", ".join(missing)))
        print("  A record missing its required fields is one no query can rely on. "
              "(`fields` prints what this store accepts.)")
        return 1


def _create_known_role(args, rows, new_row, _link_match, _item):
    """create --file opportunities: a role the pipeline already holds is linked (`--from-item`) or refused; an item's
    sibling listings become sightings of the new row. Returns an exit code to stop with, else None."""
    if _link_match and args.from_item and not args.force:
        return _link_from_item(args, new_row, rows, _link_match, _item)
    if _link_match and _link_match[2] == "active" and not args.force:
        _lrow, _lbasis, _lkind = _link_match
        print("⛔ %r was NOT created: it is the SAME ROLE as the active opportunity %r (%s; "
              "company %s, title %r, status %s) -- one requisition listed more than once is one "
              "decision." % (args.rid, _lrow.get("id"), _lbasis, _lrow.get("company_id") or "?",
                             _lrow.get("title") or "?", _lrow.get("status") or "?"))
        print("  Add the listing to it: `record.py append %s sightings '<json>'` (give the "
              "sighting a `location`). If this is a genuinely different opening, create it "
              "again with --force (the pair is recorded in distinct_from)." % _lrow.get("id"))
        return 1
    if _item:
        # A new row born from an item that carried sibling listings keeps them as sightings.
        _sg0 = next((s for s in (new_row.get("sightings") or []) if isinstance(s, dict)), None)
        if _sg0 and _item.get("siblings"):
            for _sib in _item["siblings"]:
                if not any(s.get("source_url") == _sib.get("url")
                           for s in new_row["sightings"] if isinstance(s, dict)):
                    new_row["sightings"].append(dict(
                        {"channel_id": _sg0.get("channel_id"), "seen_on": _sg0.get("seen_on"),
                         "source_url": _sib.get("url")},
                        **({"location": _sib["location"]} if _sib.get("location") else {})))


def _create_feed_posting(args, new_row, _item):
    """create --from-item of a company-FEED item: the script writes `employer_posting` itself. Returns
    (exit code of a printed refusal or None, whether it wrote the field)."""
    _feed_posting_written = False
    # ⭐ dev #776 / public #166 (design section 6.3) -- a role born from a company-FEED item is confirmed on the
    # employer's own posting by CONSTRUCTION (the feed is the employer's own board): the script writes
    # `employer_posting` itself, through the same `observe` every other writer uses, and holds the writer token only
    # for the checks below. A typed `employer_posting` is refused here, token or no token: the value is the script's.
    if _item and str(_item.get("source") or "").startswith("feed:"):
        try:
            _feed_value, _feed_err = _feed_posting_value(_item, new_row, _posting_today(args.today_arg))
        except _Refused as e:
            print("⛔ REFUSED — %s" % e)
            return 1, False
        if _feed_err:
            print("⛔ REFUSED — --from-item: %s" % _feed_err)
            return 1, False
        if _feed_value is not None:
            new_row[_POSTING_FIELD] = _feed_value
            _feed_posting_written = True
    return None, _feed_posting_written


def _create_passed_match(args, rows, new_row, _pidx):
    """create --file opportunities without --force: a role already passed on is not created again (`_pidx` is
    record.py's `pipeline_index`). Returns the exit code of a refusal it has printed, else None."""
    # ⭐ dev #670 / public #136 — a role you already PASSED on does not come back as a fresh
    # lead because the sourcing run gave it a different id. The match is pipeline_index's
    # one definition (same company_id + normalized title, or identical jd_url, or identical
    # ATS requisition id) against its one exclusion list. The answer is OUTPUT, never a new
    # stored field: nothing is written, and the line names the existing row. A different
    # opening that genuinely reuses the title takes --force; reopening the old row is
    # `set <existing-id> ...`, not a duplicate.
    if args.file == "opportunities" and not args.force:
        _hit = _pidx.find_excluded_match(
            rows, company_id=new_row.get("company_id"), title=new_row.get("title"),
            jd_url=new_row.get("jd_url"), req_id=args.req_id,
            applications=_load_or_empty("applications"))
        if _hit:
            print("⛔ %s" % _pidx.describe_match(*_hit))
            print("  %r was NOT created: a role you already passed on is not a new "
                  "decision. To bring the old one back, `set` its verdict/status; if this "
                  "is a genuinely different opening, create it again with --force."
                  % args.rid)
            return 1


def play_params_mutation(args, rec):
    """`set <play-id> params.<name> <value> --file plays [--when T] [--why W]` (moved out of record.py main).
    Returns a Mutation, or the exit code of a refusal it has printed."""
    # ⭐ ADR-031 B4 (design §27.1) — `set <play-id> params.<name> <value> --file plays
    # [--when TOKEN] [--why TEXT]`: a bounded, reasoned parameter tweak. **The refusal
    # names the legal set** (§27.1's own resolution: "the rejection IS the option list",
    # #73 applied here) — a caller never has to re-read a pattern file to learn what it
    # could have set instead.
    if len(args.rest) != 2:
        print("usage: set <play-id> params.<name> <value> --file plays [--when TOKEN] "
             "[--why \"...\"]")
        return 2
    field, raw_val = args.rest
    pname = field.split(".", 1)[1]
    if rec is None:
        print("No plays record with id %r." % args.rid)
        return 1
    params_now = rec.get("params") or {}
    spec = params_now.get(pname)
    if spec is None:
        print("⛔ REFUSED — %r declares no parameter %r. Known: %s"
             % (args.rid, pname, ", ".join(sorted(params_now)) or "(none)"))
        return 1
    if isinstance(spec, (int, float)):
        print("⛔ REFUSED — parameter %r is FIXED by the pattern (no min/max declared) "
             "and cannot be tweaked. To change it, fork the play (edit steps/params by "
             "hand or via record.py set-in)." % pname)
        return 1
    try:
        new_val = int(raw_val)
    except (TypeError, ValueError):
        print("⛔ REFUSED — %r must be an integer number of days, got %r" % (pname, raw_val))
        return 1
    mn, mx = spec.get("min"), spec.get("max")
    arm_desc = ", ".join("%s -> %s" % (a.get("when"), a.get("days"))
                         for a in spec.get("unless") or []) or "(none)"
    if mn is not None and mx is not None and not (mn <= new_val <= mx):
        print("⛔ REFUSED — %s: %d is outside [%s, %s]. anchored to the %s touch; "
             "default %s; arms: %s"
             % (pname, new_val, mn, mx, spec.get("anchor"), spec.get("days"), arm_desc))
        return 1
    when_tok = args.when_token
    today_iso = datetime.date.today().isoformat()
    if when_tok:
        existing_arm = next((a for a in (spec.get("unless") or [])
                            if a.get("when") == when_tok), None)
        if existing_arm is None and not (args.why or "").strip():
            print("⛔ REFUSED — a NEW arm (--when %r) requires --why: a second value for "
                 "one concept with no stated reason is the row a later reader merges "
                 "(design §24.2)." % when_tok)
            return 1
        desc = "set play %s params.%s (--when %s) = %d" % (args.rid, pname, when_tok, new_val)

        def apply(r, _pname=pname, _when=when_tok, _val=new_val, _why=args.why,
                 _on=today_iso):
            arms = r["params"][_pname].setdefault("unless", [])
            for a in arms:
                if a.get("when") == _when:
                    a["days"] = _val
                    a["set_on"] = _on
                    if _why:
                        a["why"] = _why
                    return
            arms.append({"when": _when, "days": _val, "why": _why, "set_on": _on})
    else:
        desc = "set play %s params.%s = %d (every arm's why: %s)" % (args.rid, pname,
                                                                    new_val, arm_desc)

        def apply(r, _pname=pname, _val=new_val, _on=today_iso):
            r["params"][_pname]["days"] = _val
            r["params"][_pname]["set_on"] = _on
    return Mutation(desc, apply)


def set_mutation(args, rec):
    """`set <id> <field> <value>` (moved out of record.py main). Returns a Mutation, or a printed refusal's code."""
    if len(args.rest) != 2:
        print("usage: set <id> <field> <value>")
        return 2
    field, val = args.rest[0], coerce(args.rest[1])
    bad = check_field(args.file, field)
    if bad and not args.force:
        print("⛔ REFUSED — %s" % bad)
        print("\n  Fix the field name, or add it to docs/data_model.json if it is genuinely")
        print("  new. --force writes anyway and is almost never right: an unknown field is")
        print("  invisible to every query written against the real one.")
        return 1
    desc = "set %s = %r" % (field, val)
    if args.file == "opportunities" and field == "location" and isinstance(val, dict):
        # dev #727 / public #159 (R5): the whole-object replace of an INFERRED location records
        # the overturn, or refuses a replacement that would leave the flag lying.
        _loc_new, _loc_err = location_replace(rec.get("location"), val, args.rid)
        if _loc_err:
            print("⛔ REFUSED — %s" % _loc_err)
            return 1
        if "inference_overturned" in _loc_new and "inference_overturned" not in val:
            _was = (rec.get("location") or {}).get("inference_overturned")
            desc += (" -- records the overturn of the inferred setting (%s -> %s)"
                     % (_loc_new["inference_overturned"]["was"],
                        _loc_new["inference_overturned"]["to"]) if _was is None
                     else " -- keeps the recorded overturn of the inferred setting")

        def apply(r):
            new_loc, err = location_replace(r.get("location"), val, args.rid)
            if err:
                raise KeyError(err)
            r[field] = new_loc
    else:
        def apply(r):
            r[field] = val
    return Mutation(desc, apply)


def append_mutation(args, rec):
    """`append <id> <array> <json>` (moved out of record.py main). Returns a Mutation, or a printed refusal's code."""
    if len(args.rest) != 2:
        print("usage: append <id> <array> <json>")
        return 2
    arr, blob = args.rest[0], json.loads(args.rest[1])
    m = model()["stores"].get(args.file, {})
    if arr not in (m.get("arrays") or {}):
        print("⛔ REFUSED — %r is not an array of %s. Known: %s"
              % (arr, args.file, ", ".join(sorted((m.get("arrays") or {})))))
        return 1
    # public #83 rule 1 — --source-url merges into a sightings[] blob so a caller never
    # has to hand-embed it in the JSON string. One fact, stated once: a JSON value that
    # DISAGREES with the flag is refused rather than silently picking one.
    if args.source_url_flag is not None and args.file == "opportunities" and arr == "sightings":
        existing_url = blob.get("source_url")
        if existing_url and existing_url != args.source_url_flag:
            print("⛔ REFUSED — the JSON carries source_url=%r but --source-url says %r. "
                  "One URL, stated once." % (existing_url, args.source_url_flag))
            return 1
        blob["source_url"] = args.source_url_flag
    # ADR-031 B2 — `applications` is no longer an array of `opportunities` (it is its own
    # top-level store, created via `create auto ... --file applications`, which mints its
    # own id — see the create branch above), so this array-append path never mints an
    # app_id any more; `arr` here can only ever be a genuinely nested array
    # (outreach/sightings/research_log/fit.requirements).
    for k in blob:
        bad = check_field(args.file, k, array=arr)
        if bad and not args.force:
            print("⛔ REFUSED — %s" % bad)
            return 1
    missing = [r for r in (m["arrays"][arr].get("required") or []) if not blob.get(r)]
    if missing and not args.force:
        print("⛔ REFUSED — %s[] requires %s" % (arr, ", ".join(missing)))
        print("  A row missing its required fields is a row no query can rely on.")
        return 1
    # ⭐ ID UNIQUENESS — the duplicate problem, caught at the door
    idf = m["arrays"][arr].get("id_field")
    if idf and blob.get(idf):
        existing = {x.get(idf) for x in (rec.get(arr) or [])}
        if blob[idf] in existing:
            print("⛔ REFUSED — %s %r already exists on this record." % (idf, blob[idf]))
            print("  Use set-in to update it. Appending a second row with the same id is how")
            print("  a join silently returns two answers.")
            return 1
    # ⭐ public #83 rule 1 — a NEW sighting from a URL-bearing channel must carry its
    # source_url at the moment it is captured (see sighting_source_url_problem's own
    # docstring). Never gated by --force: this is a data-integrity rule about a link that
    # cannot be recovered later, not a schema-shape guess --force exists to override.
    if args.file == "opportunities" and arr == "sightings":
        _channel_type_by_id = {c.get("id"): c.get("type") for c in _load_or_empty("channels")}
        _receipted = any(a.get("status") in _validator_module().SUBMITTED_APP_STATUS
                        for a in _load_or_empty("applications") if a.get("opp_id") == rec.get("id"))
        _existing_sightings = rec.get("sightings") or []
        _referenced = ({rec.get("channel_id"), blob.get("channel_id")}
                      | {sg.get("channel_id") for sg in _existing_sightings})
        _problem = sighting_source_url_problem(blob, _channel_type_by_id, _referenced,
                                               _receipted)
        if _problem:
            print("⛔ REFUSED — %s" % _problem)
            return 1
    desc = "append to %s[]" % arr

    def apply(r):
        r.setdefault(arr, []).append(blob)
    return Mutation(desc, apply)


def set_in_mutation(args):
    """`set-in <id> <array> <key>=<match> <field> <value>` (moved out of record.py main). Returns a Mutation, or a
    printed refusal's code."""
    if len(args.rest) != 4:
        print("usage: set-in <id> <array> <key>=<match> <field> <value>")
        return 2
    arr, match, field, val = args.rest[0], args.rest[1], args.rest[2], coerce(args.rest[3])
    if "=" not in match:
        print("match must be key=value, e.g. contact_id=jane-doe")
        return 2
    mk, mv = match.split("=", 1)
    for f in (mk, field):
        bad = check_field(args.file, f, array=arr)
        if bad and not args.force:
            print("⛔ REFUSED — %s" % bad)
            return 1
    desc = "set %s = %r on %s[] where %s == %r" % (field, val, arr, mk, mv)

    def apply(r):
        # ⭐ DOTTED PATH: `fit.requirements` is an array one level down, not a top-level one.
        # Closing an answered JD-fit question is a routine write (26 were open on 2026-08-05,
        # two of them still flagged DUE for a call that had already happened), and without
        # this the only way to do it was an ad-hoc read-mutate-write — the exact pattern this
        # API exists to abolish. Resolution is by walking dicts, so it stays a strict
        # generalisation: a name with no dot behaves exactly as before.
        node = r
        for part in arr.split(".")[:-1]:
            node = node.get(part) or {}
        leaf = arr.split(".")[-1]
        hits = [x for x in (node.get(leaf) or []) if str(x.get(mk)) == mv]
        if not hits:
            raise KeyError("no %s[] entry with %s == %r" % (arr, mk, mv))
        for x in hits:
            x[field] = val
    return Mutation(desc, apply)


def link_sibling_mutation(args, rows, rec, _pidx):
    """`link-sibling <duplicate-id> --into <canonical-id>` (moved out of record.py main). `_pidx` is record.py's
    `pipeline_index`. The Mutation's `apply_rows` holder is what `apply` reads the canonical row from."""
    _apply_rows = [None]
    # dev #728 / public #158 (design-location-screen.md §5.4): FOLD a pre-0.70.0 duplicate row
    # into the row that already stands for the requisition, by hand. ONE locked write: the
    # duplicate's listings become sightings of the canonical row, and the duplicate gets
    # `duplicate_of`. Nothing is deleted. No migration does this for existing rows: the matcher can
    # false-merge, and a stored row may carry notes, people or channel history only a human can
    # weigh.
    if args.file != "opportunities" or args.rest:
        print("usage: link-sibling <duplicate-id> --into <canonical-id>   (opportunities)")
        return 2
    if not args.into_id:
        print("⛔ REFUSED — link-sibling requires --into <canonical-id>.")
        return 1
    canon0 = find(rows, args.into_id)
    why = None
    if args.into_id == args.rid:
        why = "a row cannot be folded into itself"
    elif canon0 is None:
        why = "no opportunity with id %r (--into)" % args.into_id
    elif rec.get("duplicate_of"):
        why = "%r is already folded into %r" % (args.rid, rec["duplicate_of"])
    elif canon0.get("duplicate_of"):
        why = ("%r is itself folded into %r: fold into the canonical row, never a chain"
               % (args.into_id, canon0["duplicate_of"]))
    elif rec.get("verdict") not in (None, "undecided"):
        why = ("%r carries a decision (verdict %s): a folded row stands for no decision. Decide "
               "the canonical row, or `set` this row's verdict back to undecided first"
               % (args.rid, rec.get("verdict")))
    elif any(a.get("opp_id") == args.rid for a in _load_or_empty("applications")):
        why = "%r has an application: it is a decision made by acting, not a duplicate" % args.rid
    elif (args.into_id in (rec.get("distinct_from") or [])
          or args.rid in (canon0.get("distinct_from") or [])):
        why = ("%r and %r were recorded as DIFFERENT (distinct_from); undo that first if they "
               "are one requisition after all" % (args.rid, args.into_id))
    if why:
        print("⛔ REFUSED — %s." % why)
        return 1
    desc = "link-sibling into %s (folds this row; its listings become sightings of %s)" % (
        args.into_id, args.into_id)

    def apply(r):
        canon = find(_apply_rows[0] or rows, args.into_id)
        if canon is None:
            raise KeyError("no opportunity with id %r (--into)" % args.into_id)
        have = {s.get("source_url") for s in (canon.get("sightings") or []) if s.get("source_url")}
        primary = (r.get("location") or {}).get("primary") if isinstance(r.get("location"), dict) \
            else None
        incoming = []
        for sg in (r.get("sightings") or []):
            if isinstance(sg, dict):
                incoming.append(dict(sg, **({"location": primary} if primary and "location" not in sg
                                            else {})))
        channel = r.get("channel_id") or next((s.get("channel_id") for s in incoming), None)
        if r.get("jd_url") and r["jd_url"] not in have and not any(
                s.get("source_url") == r["jd_url"] for s in incoming) and channel:
            incoming.append({"channel_id": channel,
                             "seen_on": _pidx.first_seen(r) or datetime.date.today().isoformat(),
                             "source_url": r["jd_url"],
                             **({"location": primary} if primary else {})})
        for sg in incoming:
            if sg.get("source_url") and sg["source_url"] in have:
                continue
            canon.setdefault("sightings", []).append(sg)
            if sg.get("source_url"):
                have.add(sg["source_url"])
        r["duplicate_of"] = args.into_id
    return Mutation(desc, apply, apply_rows=_apply_rows)


def unlink_sibling_mutation(args, rows, rec, _pidx):
    """`unlink-sibling <canonical-id> --url <source_url> --to <row-id>` (moved out of record.py main). `_pidx` is
    record.py's `pipeline_index`. The Mutation's `apply_rows` holder is what `apply` reads the target row from."""
    _apply_rows = [None]
    # dev #728 / public #158 (design §5.5): UNDO a false merge. Nothing is deleted. The canonical
    # row's sighting for `--url` is stamped `split_to: <row>`; <row> (which must already exist:
    # a folded legacy row, or a row made with `create --force`) gets the canonical row in its
    # `distinct_from` and, if it was folded into this one, loses `duplicate_of`. The matching
    # rule reads both stamps, so the pair never re-merges.
    if args.file != "opportunities" or args.rest:
        print("usage: unlink-sibling <canonical-id> --url <source_url> --to <row-id>   (opportunities)")
        return 2
    if not args.listing_url or not args.to_token:
        print("⛔ REFUSED — unlink-sibling requires --url <the listing's source_url> and "
              "--to <the row that listing belongs to>.")
        return 1
    target0 = find(rows, args.to_token)
    sg0 = next((s for s in (rec.get("sightings") or []) if isinstance(s, dict)
                and _pidx._urls_equal(s.get("source_url"), args.listing_url)), None)
    why = None
    if args.to_token == args.rid:
        why = "a listing cannot be split to the row it is already on"
    elif target0 is None:
        why = ("no opportunity with id %r (--to). Create it first (`record.py create <id> '<json>' "
               "--force`, which records distinct_from), or fold-undo a legacy row that exists"
               % args.to_token)
    elif sg0 is None:
        why = "%r has no sighting with source_url %s" % (args.rid, args.listing_url)
    elif sg0.get("split_to"):
        why = "that sighting was already split to %r" % sg0["split_to"]
    elif target0.get("duplicate_of") not in (None, args.rid):
        why = ("%r is folded into %r, not into %r: unlink it from there"
               % (args.to_token, target0["duplicate_of"], args.rid))
    if why:
        print("⛔ REFUSED — %s." % why)
        return 1
    desc = "unlink-sibling: split %s to %s (nothing deleted)" % (args.listing_url, args.to_token)

    def apply(r):
        target = find(_apply_rows[0] or rows, args.to_token)
        if target is None:
            raise KeyError("no opportunity with id %r (--to)" % args.to_token)
        sg = next((s for s in (r.get("sightings") or []) if isinstance(s, dict)
                   and _pidx._urls_equal(s.get("source_url"), args.listing_url)), None)
        if sg is None:
            raise KeyError("%r has no sighting with source_url %s" % (r.get("id"), args.listing_url))
        sg["split_to"] = args.to_token
        if target.get("duplicate_of") == r.get("id"):
            del target["duplicate_of"]
        df = list(target.get("distinct_from") or [])
        if r.get("id") not in df:
            df.append(r.get("id"))
        target["distinct_from"] = df
    return Mutation(desc, apply, apply_rows=_apply_rows)
