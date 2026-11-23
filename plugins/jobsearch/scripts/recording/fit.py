"""fit: the `fit` verb: the researcher's one JSON line per role, strictly parsed and written with `analyzed_on`
stamped by the script, before the role is ready.

Capability module of record.py (an entry point over `recording/`)."""

import datetime
import json
from recording.row_checks import (
    _diagnostic_lines,
    _row_checks,
    dry_run_validate,
    new_problems,
    validate,
)
from recording import fit_keys as _fk
from recording.common import _now
from recording.reads import _stage_line
from recording.store_files import (
    LockError,
    find,
    load,
    lock_is_held,
    release_lock,
    restore,
    save_atomic,
    snapshot,
    take_lock,
)


# ---- jobsearch 0.87.0 (dev #861 / public #194; design-stage-honesty.md section 5) --------------------------------------------
#
# `record.py fit --from-file <file>` is the ONE writer of an opportunity's `fit` from research. Before it, `Ctx.researched`
# demanded `fit.requirements[]` for a role to be `ready` and nothing wrote it: the researcher "never writes the pipeline", the
# drains routed only EMPLOYER-POSTING lines, and every researched role closed `agent-returned-nothing`. The researcher hands its
# `fit` back by FILE (one JSON object per line, never argv: the quoted evidence carries `'`, `"` and `$`), and this verb parses
# the bytes the agent wrote with a strict parser, applies each line on its own and prints one result per line.
#
#   one line = {"opp": <id>, "jd_source": <text>, "requirements": [{requirement, verdict, evidence, pitch_line,
#               question_for_candidate, question_status, act_by, landed_in, answered_on}, ...]}
#
# The script STAMPS `analyzed_on` (the local date at the moment of the write, `_now()`: the same clock and zone as the read's
# `at`, so a run that read at 00:10 never stamps a fit dated before its read); a line that carries it is refused. The rules a
# requirement must meet are the validator's own (`validate_data.py`'s fit block), reached by running the write through the
# validator on a disposable copy of the data directory: one rule set, never a copy of it here.
FIT_USAGE = "fit --from-file <file of fit lines: one JSON object per line> [--dry-run] [--already-locked]"
FIT_LINE_KEYS = ("opp", "jd_source", "requirements")
# design-presence-report.md 8.1: `topic` and `claim` are optional, checked by `recording/fit_keys.py` (the claim against the
# union at the write); a replaced fit carries neither forward, and says how many it dropped.
FIT_REQUIREMENT_KEYS = ("requirement", "verdict", "evidence", "pitch_line", "question_for_candidate", "question_status",
                        "act_by", "landed_in", "answered_on", "topic", "claim")


def _fit_read_lines(path):
    """`[(line number, line), ...]`: every non-blank line of the file at `path`, spaces and tabs stripped, split on a newline only
    (never `str.splitlines`, which also splits on U+2028 and others that quoted evidence may hold)."""
    with open(path, encoding="utf-8", newline="") as fh:
        text = fh.read()
    out = []
    for n, raw in enumerate(text.split("\n"), 1):
        line = (raw[:-1] if raw.endswith("\r") else raw).strip(" \t")
        if line:
            out.append((n, line))
    return out


def _fit_parse_line(line):
    """`(object, None)` for a well-formed fit line, else `(None, reason)`. The STRICT parser: it accepts a stated shape and
    refuses everything else (a closed key set at both levels, no model-typed `analyzed_on`, no empty requirements, and every
    `unknown` requirement stored `open` so its question is never lost)."""
    try:
        obj = json.loads(line)
    except ValueError as e:
        return None, "not JSON (%s)" % e
    if not isinstance(obj, dict):
        return None, "not one JSON object"
    extra = sorted(str(k) for k in obj if k not in FIT_LINE_KEYS)
    if extra:
        if "analyzed_on" in extra:
            return None, "analyzed_on is stamped by the script at the write, never typed on a line"
        return None, "unknown key %r (allowed: %s)" % (extra[0], ", ".join(FIT_LINE_KEYS))
    missing = [k for k in FIT_LINE_KEYS if k not in obj]
    if missing:
        return None, "missing key %r" % missing[0]
    if not (isinstance(obj["opp"], str) and obj["opp"].strip()):
        return None, "opp must be a non-empty string"
    if not (isinstance(obj["jd_source"], str) and obj["jd_source"].strip()):
        return None, "jd_source must be a non-empty string naming what was read"
    reqs = obj["requirements"]
    if not isinstance(reqs, list) or not reqs:
        return None, "requirements must be a non-empty list"
    for i, q in enumerate(reqs):
        where = "requirements[%d]" % i
        if not isinstance(q, dict):
            return None, "%s is not an object" % where
        bad = sorted(str(k) for k in q if k not in FIT_REQUIREMENT_KEYS)
        if bad:
            return None, "%s has an unknown key %r (allowed: %s)" % (where, bad[0], ", ".join(FIT_REQUIREMENT_KEYS))
        if q.get("verdict") == "unknown" and q.get("question_status") != "open":
            return None, ("%s is an `unknown` requirement whose question_status is %r, not `open`: a gap is stored open so "
                          "its question is never lost" % (where, q.get("question_status")))
    return obj, None


def _fit_date(raw):
    try:
        return datetime.date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _fit_plan(lines, opps, today_iso, carried=None):
    """Apply every parsed line to `opps` IN MEMORY and return `{results, changed}`. A line that cannot be applied is a result
    with `ok` False and the reason in `text`; the others still apply (each line is its own role). `carried` is `{line number:
    refusal text}` for lines an earlier pass already refused (so the locked pass re-applies only what applied). Nothing here
    touches disk."""
    import jd_read as _jd
    results, changed = [], []
    known, union = _fk.stored_topics(opps), _fk.cached_keys()
    for n, line in lines:
        res = {"n": n, "opp_id": None, "ok": False, "text": "", "notes": []}
        results.append(res)
        if carried and n in carried:
            res["text"] = carried[n]
            continue
        obj, why = _fit_parse_line(line)
        if obj is not None:
            why = _fk.lines_refusal(obj["requirements"], union)
            obj = None if why else obj
        if obj is None:
            res["text"] = "⛔ REFUSED line %d — %s; nothing written for it, never retry it edited." % (n, why)
            continue
        oid = obj["opp"].strip()
        res["opp_id"] = oid
        row = find(opps, oid)
        if row is None:
            res["text"] = "⛔ REFUSED line %d — no opportunity with id %r." % (n, oid)
            continue
        try:
            reads = sorted((a for a in _jd.attempts(row) if a["outcome"] == _jd.READ), key=lambda a: a["at"])
        except _jd.JdReadError as e:
            res["text"] = "⛔ REFUSED line %d — %s: its stored jd_read cannot be read (%s)." % (n, oid, e)
            continue
        if not reads:
            res["text"] = ("⛔ REFUSED line %d — %s has no read attempt: research needs a read of the posting first "
                           "(`record.py read-jd`), so there is no fit to date against it." % (n, oid))
            continue
        read_day = _jd.parse_at(reads[-1]["at"]).date()
        have = row.get("fit")
        have_day = _fit_date(have.get("analyzed_on")) if isinstance(have, dict) else None
        if have_day is not None and have_day >= read_day:
            res["text"] = ("⛔ REFUSED line %d — %s already carries a current fit (analyzed %s, on or after its read of %s): "
                           "not overwritten, so the candidate's answered questions are never erased."
                           % (n, oid, have_day.isoformat(), read_day.isoformat()))
            continue
        res["notes"] = [x for x in [_fk.replaced_note(have)] if x] + _fk.new_topic_notes(obj["requirements"], known)
        row["fit"] = {"analyzed_on": today_iso, "jd_source": obj["jd_source"].strip(),
                      "requirements": json.loads(json.dumps(obj["requirements"]))}
        if oid not in changed:
            changed.append(oid)
        res["ok"] = True
        res["text"] = "%s: fit written (%d requirements)" % (oid, len(obj["requirements"]))
    return {"results": results, "changed": changed}


def _fit_refuse_unfit(plan, opps_before, shadow):
    """Run what the write would store through the introduced-only rules and the validator, and REFUSE per line what either
    refuses: the line is marked refused with the reasons, and its row is put back in `shadow`. The validator runs once on the
    whole shadow (a disposable copy of the data directory); only when it objects does it run again per role, to say which
    line it objects to. A refusal it cannot attribute to a line refuses every line, naming the problems. Returns the list of
    changed role ids that remain."""
    by_oid = {r["opp_id"]: r for r in plan["results"] if r["ok"]}
    bad = {}
    for oid in plan["changed"]:
        v = _row_checks("fit", find(opps_before, oid), find(shadow, oid))
        if v:
            bad[oid] = v
    keep = [o for o in plan["changed"] if o not in bad]
    if keep:
        pre_problems = validate()[3]
        rc, out, err, post = dry_run_validate("opportunities", shadow)
        added = new_problems(pre_problems, post) if rc != 0 else []
        if rc != 0 and (added is None or added):
            for oid in keep:
                single = json.loads(json.dumps(opps_before))
                single[[r.get("id") for r in single].index(oid)] = json.loads(json.dumps(find(shadow, oid)))
                rc1, out1, err1, post1 = dry_run_validate("opportunities", single)
                add1 = new_problems(pre_problems, post1) if rc1 != 0 else []
                if rc1 != 0 and (add1 is None or add1):
                    bad[oid] = add1 if add1 else _diagnostic_lines(rc1, out1, err1)
            if not bad:
                for oid in keep:
                    bad[oid] = (added if added else _diagnostic_lines(rc, out, err))
    for oid, why in bad.items():
        res = by_oid[oid]
        res["ok"] = False
        res["text"] = ("⛔ REFUSED line %d — %s: the fit would be refused by the validator (nothing written for it): %s"
                       % (res["n"], oid, "; ".join(str(w) for w in why)))
        orig = find(opps_before, oid)
        shadow[[r.get("id") for r in shadow].index(oid)] = json.loads(json.dumps(orig))
    return [o for o in plan["changed"] if o not in bad]


def _print_fit_results(plan):
    n_ok = sum(1 for r in plan["results"] if r["ok"])
    print("fit: %d line(s) read, %d written, %d refused" % (len(plan["results"]), n_ok, len(plan["results"]) - n_ok))
    for r in plan["results"]:
        print("  " + r["text"])
        for note in r.get("notes") or ():
            print("    " + note)


def cmd_fit(args):
    """`record.py fit --from-file <file>` -- dev #861 / public #194 (design-stage-honesty.md section 5). Record the `fit`
    the opportunity-researcher handed back by file: one JSON object per line, parsed strictly, each line its own role.

    A line the strict parser or the validator refuses is refused loudly, by line number, and writes nothing; the others still
    land in ONE locked, validated, rollback-verified write of the opportunities store, or none does. A role whose fit is
    already current (analyzed on or after its latest read) is refused rather than overwritten; a stale fit is replaced.
    `analyzed_on` is stamped here. Each applied line prints the lifecycle stage the role is now in. Exit 0 when every line
    applied, 1 when any was refused (the applied ones still landed) or the write was rolled back, 2 on usage."""
    if args.rid or args.rest or not args.from_file:
        print("usage: " + FIT_USAGE)
        return 2
    try:
        lines = _fit_read_lines(args.from_file)
    except (OSError, UnicodeDecodeError) as e:
        print("⛔ REFUSED — %s cannot be read (%s); nothing written." % (args.from_file, e))
        return 1
    if not lines:
        print("⛔ REFUSED — NOT CHECKED: %s holds no fit line. A researched role owes one line, never silence." % args.from_file)
        return 1
    try:
        opps = load("opportunities")
    except (OSError, ValueError) as e:
        print("⛔ REFUSED — the opportunities store cannot be read (%s); nothing written." % e)
        return 1
    today_iso = _now().date().isoformat()
    shadow = json.loads(json.dumps(opps))
    plan = _fit_plan(lines, shadow, today_iso)
    _fit_refuse_unfit(plan, opps, shadow)
    carried = {r["n"]: r["text"] for r in plan["results"] if not r["ok"]}
    if args.dry_run:
        _print_fit_results(plan)
        print("  --dry-run: nothing written.")
        return 1 if carried else 0
    if any(r["ok"] for r in plan["results"]):
        if args.already_locked:
            if not lock_is_held():
                print("  REFUSED — --already-locked, but NOBODY holds the run lock.")
                return 1
        else:
            try:
                take_lock("record.py fit", wait=args.wait)
            except LockError as e:
                print("  REFUSED — %s" % e)
                return 1
        try:
            # re-read INSIDE the lock, and re-apply on what is really there
            opps = load("opportunities")
            before_rows = json.loads(json.dumps(opps))
            plan = _fit_plan(lines, opps, today_iso, carried=carried)
            if plan["changed"]:
                introduced = []
                for oid in plan["changed"]:
                    introduced += _row_checks("fit", find(before_rows, oid), find(opps, oid))
                if introduced:
                    print("⛔ REFUSED — " + "; ".join(introduced))
                    return 1
                snap = snapshot("opportunities")
                pre_problems = validate()[3]
                save_atomic("opportunities", opps)
                rc, out, err, post_problems = validate()
                added = new_problems(pre_problems, post_problems)
                if rc != 0 and (added is None or added):
                    ok = restore("opportunities", snap)
                    print("⛔ the write left the store invalid and was %s."
                          % ("ROLLED BACK (byte-identical)" if ok else
                             "NOT VERIFIABLY ROLLED BACK — restore opportunities.jsonl from git"))
                    print("  " + "\n  ".join(added if added else _diagnostic_lines(rc, out, err)))
                    return 1
        finally:
            if not args.already_locked:
                release_lock()
    for r in plan["results"]:
        if r["ok"]:
            r["text"] += " → %s" % _stage_line(r["opp_id"])
    _print_fit_results(plan)
    return 1 if any(not r["ok"] for r in plan["results"]) else 0
