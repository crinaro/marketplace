"""fallback: `read-batch --fallback`, the opt-in logged-out posting read of a LinkedIn role whose browser read could not
happen, and `not-attempted`, the record that a page was never read because the Browser pane was hidden.

Capability module of record.py (an entry point over `recording/`)."""

import datetime
import hashlib
import json
import re
from recording import profile_paths as _paths
from recording.row_checks import _diagnostic_lines, _row_checks, new_problems, validate
from recording.common import _engine_version, _now, _profile_mod, _words
from recording.reads import (
    FETCH_DEADLINE_S_DEFAULT,
    NOT_ATTEMPTED_USAGE,
    _apply_failed,
    _apply_read,
    _has_read,
)
from recording.store_files import (
    LockError,
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


def _fallback_names(row, company):
    return _words(row.get("title")) | _words((company or {}).get("name")) | _words(row.get("company_id"))


def _fallback_ineligible(row, run, sess):
    """`(job_id, None)` when `row` may be fetched, else `(None, why)`. Decided from the stored attempts, never the reader's word."""
    import jd_read as _jd
    import board_hosts as _bh
    import posting_fetch as _pf
    if _has_read(row):
        return None, "already read"
    try:
        in_run = [a for a in _jd.attempts(row) if a["run"] == run]
    except _jd.JdReadError as e:
        return None, "its jd_read cannot be read (%s)" % e
    latest = _jd.latest_of(in_run)
    if latest is None:
        return None, "no attempt in this run: the browser read comes first"
    if latest["via"] != "render" or latest["outcome"] not in FALLBACK_OUTCOMES:
        return None, "its latest attempt in this run is %s via %s, not %s" % (
            latest["outcome"], latest["via"], " or ".join(FALLBACK_OUTCOMES))
    job_id = next((j for j in (_pf.posting_id(u) for u in _bh.read_urls(row)) if j), None)
    if job_id is None:
        return None, "no LinkedIn job-view address"
    if sess is not None and sess.tried(row["id"]):
        return None, "already tried in this run"
    return job_id, None


FALLBACK_OUTCOMES = ("pane-hidden", "render-failed")


def _fallback_one(sess, sdir, row, job_id, run, company):
    """What the fallback decided for one eligible role: a dict with `kind` in read | closed | body | wrong-page | refused |
    rate-limited | http | redirected | unreachable | capped | host-closed. Touches no store. A saved body is reused."""
    import posting_fetch as _pf
    import places as _places
    oid = row["id"]
    saved = _pf.saved_body(sdir, oid)
    if saved is not None:
        path, entry = saved
        sess.mark_tried(oid)
        return {"kind": "body", "reason": entry.get("reason") or "saved-body", "path": path, "sha1": entry["sha1"]}
    res = sess.get(job_id)
    if res.kind != "ok":
        if res.kind not in ("capped", "host-closed"):
            sess.mark_tried(oid)                               # a role the host answered badly is not asked again this run
        return {"kind": res.kind, "status": res.status, "detail": res.detail}
    sess.mark_tried(oid)
    try:
        parsed = _pf.parse(res.body)
    except _pf.PostingRefusal as e:
        return {"kind": "refused", "detail": e.code}
    countries = ["United States"] if _places.parse_place(parsed["place"]) else []
    d = _pf.decide(parsed, _fallback_names(row, company), countries)
    url = _pf.endpoint_url(job_id)
    sha1, chars = hashlib.sha1(res.body).hexdigest(), len(res.body)
    if d["kind"] == "wrong-page":
        return {"kind": "wrong-page"}
    if d["kind"] == "closed":
        return {"kind": "closed", "url": url, "sha1": sha1, "chars": chars}
    if d["kind"] == "read":
        return {"kind": "read", "url": url, "sha1": sha1, "chars": chars, "pay": d["pay"], "setting": d["setting"],
                "place": d["place"]}
    path, body_sha1 = _pf.save_body(sdir, oid, run, url, parsed, d["reason"])
    return {"kind": "body", "reason": d["reason"], "path": path, "sha1": body_sha1}


def cmd_read_fallback(args, run):
    """`record.py read-batch --run <id> --fallback` -- see the section comment above. Exit 0 (every non-recording answer is
    a printed line, not a fault), 1 when a store cannot be read or the write was rolled back, 2 on usage."""
    import posting_fetch as _pf
    import lifecycle as _lc
    deadline_s = FETCH_DEADLINE_S_DEFAULT if args.deadline_s is None else args.deadline_s
    if deadline_s < 0:
        print("⛔ REFUSED — --deadline-s must be 0 or more.")
        return 2
    check = bool(args.check or args.dry_run)
    on, why = _pf.key_state(_paths.ROOT)
    if not on:
        print("FALLBACK: off" + ((" (%s)" % why) if why else ""))
        return 0
    sdir = _pf.state_dir()
    if sdir is None:
        print("FALLBACK: off (no profile state directory)")
        return 0
    try:
        data = _lc.load_data(_paths.ROOT)
        planned = None
        for r in data["journal"]:
            if (r.get("event") == "drain" and r.get("phase") == "planned" and r.get("run_id") == run
                    and not r.get("on_behalf_of")):
                planned = r
    except (OSError, ValueError, _lc.LifecycleError) as e:
        print("⛔ REFUSED — a store cannot be read (%s); nothing written." % e)
        return 1
    if planned is None:
        print("⛔ REFUSED — run %r has no `drain planned` event: run `lifecycle.py --drain-plan --run %s "
              "--render-route yes|no` first; nothing written." % (run, run))
        return 1
    adm = planned.get("admitted") or {}
    adm_opps, adm_items = set(adm.get("opps") or []), set(adm.get("items") or [])
    by_id = {o.get("id"): o for o in data["opportunities"]}
    companies = {c.get("id"): c for c in data["companies"]}

    def admitted(o):
        cap = o.get("capture") if isinstance(o.get("capture"), dict) else {}
        return o.get("id") in adm_opps or cap.get("item") in adm_items

    sess = None if check else _pf.Session(sdir, run)
    asked = list(dict.fromkeys(args.ids_arg)) if args.ids_arg else None
    pool = ([by_id.get(i) or i for i in asked] if asked is not None
            else sorted((o for o in data["opportunities"] if admitted(o)),
                        key=lambda o: (_lc.first_seen(o) or datetime.date.max, str(o.get("id")))))
    import collections
    eligible, counts = [], collections.Counter()
    for o in pool:
        if isinstance(o, str):
            print("FALLBACK %s: not eligible (no such role)" % o)
            continue
        if not admitted(o):
            print("FALLBACK %s: not eligible (it was not admitted in this run)" % o["id"])
            continue
        job_id, why = _fallback_ineligible(o, run, sess)
        if why:
            print("FALLBACK %s: not eligible (%s)" % (o["id"], why))
            continue
        eligible.append((o, job_id))
    if check:
        print("read-batch --fallback --check: %d eligible role(s); nothing fetched, nothing written." % len(eligible))
        return 0
    _pf.prune(sdir, lambda oid: bool(by_id.get(oid)) and _has_read(by_id[oid]))
    clock, t0 = _pf._clock(), _pf._clock().now()
    results, more = [], False
    for o, job_id in eligible:
        if results and deadline_s - (clock.now() - t0) < _pf.ROLE_WORST_CASE_S:
            more = True                                         # always one role per call, so a small deadline still moves
            break
        out = _fallback_one(sess, sdir, o, job_id, run, companies.get(o.get("company_id")))
        out["id"] = o["id"]
        results.append(out)
        k = out["kind"]
        if k == "body":
            print("RESIDUE %s (body): %s file=%s sha1=%s" % (o["id"], out["reason"], out["path"], out["sha1"]))
            counts["body"] += 1
        elif k in ("read", "closed"):
            pass                                                # printed after the write, which can still refuse
        else:
            counts[{"rate-limited": "rate-limited", "http": "http", "refused": "refused", "wrong-page": "refused",
                    "capped": "capped"}.get(k, "host-closed")] += 1
            what = {"http": "http-%s" % out.get("status"), "refused": out.get("detail"),
                    "capped": "fetch-capped", "unreachable": "unreachable (%s)" % out.get("detail")}.get(k, k)
            print("FALLBACK %s: %s" % (o["id"], what))
    rc = 0
    writes = [r for r in results if r["kind"] in ("read", "closed")]
    if writes:
        rc = _apply_fallback_writes(args, run, data, writes, counts, _now())
    nothing = sum(counts[k] for k in ("rate-limited", "http", "refused", "capped", "host-closed"))
    print("FALLBACK DONE: read %d, closed %d, body %d, nothing recorded %d (rate-limited %d, http %d, refused %d, "
          "capped %d, host closed %d)" % (counts["read"], counts["closed"], counts["body"], nothing,
                                          counts["rate-limited"], counts["http"], counts["refused"], counts["capped"],
                                          counts["host-closed"]))
    if more:
        print("MORE")
    return rc


def _apply_fallback_writes(args, run, data, writes, counts, now):
    """The ONE locked write of the fallback: `read` and `closed` attempts, each applied only to a role that is still
    unread when the lock is held. Mirrors `cmd_read_batch`'s write (same checks, same rollback). Returns the exit code."""
    import jd_read as _jd
    import deferred as _deferred
    if args.already_locked:
        if not lock_is_held():
            print("  REFUSED — --already-locked, but NOBODY holds the run lock.")
            return 1
    else:
        try:
            take_lock("record.py read-batch --run %s --fallback" % run, wait=args.wait)
        except LockError as e:
            print("  REFUSED — %s" % e)
            return 1
    try:
        profile = _profile_mod().load()
        opps = load("opportunities")
        applications = _load_or_empty("applications")
        channels = _load_or_empty("channels")
        by_id = {o.get("id"): o for o in opps}
        before, landed = {}, []
        engine, at_iso, on = _engine_version(), now.isoformat(), now.date()
        for p in writes:
            oid = p["id"]
            row = by_id.get(oid)
            if row is None or _has_read(row):
                print("FALLBACK %s: not recorded (a read landed while the network was out)" % oid)
                continue
            pre_row = json.loads(json.dumps(row))
            before.setdefault(oid, pre_row)
            company = next((c for c in data["companies"] if c.get("id") == row.get("company_id")), None)
            try:
                if p["kind"] == "closed":
                    _apply_failed(row, run=run, url=p["url"], via="fetch", outcome="closed", at_iso=at_iso,
                                  text="the guest posting says it is no longer accepting applications (sha1 %s, %d chars)"
                                       % (p["sha1"][:12], p["chars"]))
                else:
                    lp, why = _deferred.parse_pay_slot(p["pay"])
                    if why:
                        raise KeyError(why)
                    lp = dict(lp, captured_on=on.isoformat(), provenance="jd")
                    _apply_read(row, run=run, url=p["url"], via="fetch",
                                evidence={"sha1": p["sha1"], "chars": p["chars"]}, pay=lp, setting=p["setting"],
                                place=p["place"], at_iso=at_iso, on=on, engine=engine, profile=profile,
                                company=company, all_opps=opps, applications=applications, channels=channels,
                                pay_inferred=True)
                landed.append(p)
            except KeyError as e:
                before.pop(oid, None)
                row.clear()
                row.update(pre_row)                             # a refused result leaves the row exactly as it was
                print("FALLBACK %s: not recorded: %s" % (oid, " ".join(str(e).split())[:120]))
        changed = [i for i in before if by_id[i] != before[i]]
        bad = []
        for oid in changed:
            bad += _row_checks("read-batch", before[oid], by_id[oid], jd_read_ok=True)
        if bad:
            print("⛔ REFUSED — " + "; ".join(bad) + " (nothing was written)")
            return 1
        if changed:
            snap = snapshot("opportunities")
            pre_problems = validate()[3]
            save_atomic("opportunities", opps)
            rc, out, err, post_problems = validate()
            added = new_problems(pre_problems, post_problems)
            if rc != 0 and (added is None or added):
                ok = restore("opportunities", snap)
                print("⛔ the write left the store invalid and was %s."
                      % ("ROLLED BACK (byte-identical)" if ok else
                         "NOT VERIFIABLY ROLLED BACK -- restore opportunities.jsonl from git"))
                print("  " + "\n  ".join(added if added else _diagnostic_lines(rc, out, err)))
                return 1
    finally:
        if not args.already_locked:
            release_lock()
    for p in landed:
        counts[p["kind"]] += 1
        print("FALLBACK %s: %s%s" % (p["id"], p["kind"], (" (pay %s)" % p["pay"]) if p["kind"] == "read" else ""))
    return 0


def cmd_not_attempted(args):
    """`record.py not-attempted` -- see the section comment above. Exit 0 on a write (or a dry run), 1 on a refusal (nothing
    written), 2 on usage."""
    import jd_read as _jd
    import pane_probe as _pp
    ids = [i for i in ([args.rid] + list(args.rest or [])) if i]
    if not ids:
        print("usage: " + NOT_ATTEMPTED_USAGE)
        return 2
    if any(re.search(r"\s", i) for i in ids):
        print("\u26d4 REFUSED \u2014 an opportunity id has no whitespace (got %r); nothing written." % ids)
        return 1
    if len(set(ids)) != len(ids):
        print("\u26d4 REFUSED \u2014 an id is named twice (%s): one call records one attempt per role; nothing written."
              % ", ".join(sorted(i for i in set(ids) if ids.count(i) > 1)))
        return 1
    run = (args.run_id_arg or "").strip()
    if not run or re.search(r"\s", run):
        print("\u26d4 REFUSED \u2014 --run <run id> is required (no whitespace).\nusage: " + NOT_ATTEMPTED_USAGE)
        return 2
    if args.via_medium != _jd.NOT_ATTEMPTED_VIA:
        print("\u26d4 REFUSED \u2014 --via must be %s (got %r): a not-attempted record is a browser read that could not "
              "happen.\nusage: %s" % (_jd.NOT_ATTEMPTED_VIA, args.via_medium, NOT_ATTEMPTED_USAGE))
        return 2
    reason = (args.reason_text or "").strip()
    if reason not in _jd.NOT_ATTEMPTED:
        print("\u26d4 REFUSED \u2014 --reason must be one of %s (got %r).\nusage: %s"
              % (", ".join(_jd.NOT_ATTEMPTED), reason or None, NOT_ATTEMPTED_USAGE))
        return 2
    if args.pane_line is None or not str(args.pane_line).strip():
        print("\u26d4 REFUSED \u2014 --pane \"<the tabs_context line>\" is required: the pane state is parsed from the "
              "harness's own line, never taken from the reader's word.\nusage: " + NOT_ATTEMPTED_USAGE)
        return 2
    pane = _pp.pane_state(args.pane_line)
    tab = args.tab_active
    if tab not in _jd.TAB_ACTIVE_VALUES:
        print("\u26d4 REFUSED \u2014 --tab-active yes|no is required (the reader's own word about its tab).\nusage: "
              + NOT_ATTEMPTED_USAGE)
        return 2
    if pane != "hidden" and tab != "no":
        print("\u26d4 REFUSED \u2014 the pane line reads %r and --tab-active is yes: with the pane not hidden and the tab in "
              "front the page could have rendered, so a missing posting is `read-failed` evidence about the role, never "
              "`not-attempted`. Nothing written." % pane)
        return 1
    text = (args.evidence_text or "").strip()
    if not text:
        print("\u26d4 REFUSED \u2014 --evidence is required: 1-200 characters (the status line).\nusage: "
              + NOT_ATTEMPTED_USAGE)
        return 2
    if len(text) > _jd.EVIDENCE_CAP:
        print("\u26d4 REFUSED \u2014 --evidence is %d characters; the cap is %d (shorten it -- it is never truncated for "
              "you)." % (len(text), _jd.EVIDENCE_CAP))
        return 1
    evidence = {"text": text, "pane": pane, "tab_active": tab}
    at_iso = _now().isoformat()
    check = bool(args.check or args.dry_run)
    try:
        for i in ids:                                       # the attempt itself must parse, before any lock or write
            _jd.make_attempt(at_iso, run, None, _jd.NOT_ATTEMPTED_VIA, reason, dict(evidence))
    except _jd.JdReadError as e:
        print("\u26d4 REFUSED \u2014 %s; nothing written." % e)
        return 1
    if check:
        missing = [i for i in ids if find(load("opportunities"), i) is None]
        if missing:
            print("\u26d4 REFUSED \u2014 no opportunity %s (all or none: nothing written)." % ", ".join(missing))
            return 1
        print("not-attempted --dry-run: %d role(s) would record %s (pane %s, tab_active %s); --dry-run: nothing written"
              % (len(ids), reason, pane, tab))
        return 0
    if args.already_locked:
        if not lock_is_held():
            print("  REFUSED \u2014 --already-locked, but NOBODY holds the run lock.")
            return 1
    else:
        try:
            take_lock("record.py not-attempted --run %s" % run, wait=args.wait)
        except LockError as e:
            print("  REFUSED \u2014 %s" % e)
            return 1
    try:
        opps = load("opportunities")
        by_id = {o.get("id"): o for o in opps}
        missing = [i for i in ids if i not in by_id]
        if missing:
            print("\u26d4 REFUSED \u2014 no opportunity %s (all or none: nothing written)." % ", ".join(missing))
            return 1
        before = {i: json.loads(json.dumps(by_id[i])) for i in ids}
        try:
            for i in ids:
                row = by_id[i]
                existing = _jd.attempts(row)
                attempt = _jd.make_attempt(at_iso, run, None, _jd.NOT_ATTEMPTED_VIA, reason, dict(evidence))
                row["jd_read"] = {"attempts": [dict(a) for a in existing] + [attempt]}
        except _jd.JdReadError as e:
            print("\u26d4 REFUSED \u2014 the stored jd_read cannot be extended (%s); nothing written." % e)
            return 1
        bad = []
        for i in ids:
            bad += _row_checks("not-attempted", before[i], by_id[i], jd_read_ok=True)
        if bad:
            print("\u26d4 REFUSED \u2014 " + "; ".join(bad) + " (nothing was written)")
            return 1
        snap = snapshot("opportunities")
        pre_problems = validate()[3]
        save_atomic("opportunities", opps)
        rc, out, err, post_problems = validate()
        added = new_problems(pre_problems, post_problems)
        if rc != 0 and (added is None or added):
            ok = restore("opportunities", snap)
            print("\u26d4 the write left the store invalid and was %s."
                  % ("ROLLED BACK (byte-identical)" if ok else
                     "NOT VERIFIABLY ROLLED BACK -- restore opportunities.jsonl from git"))
            print("  " + "\n  ".join(added if added else _diagnostic_lines(rc, out, err)))
            return 1
    finally:
        if not args.already_locked:
            release_lock()
    print("not-attempted: %d role(s) recorded %s via %s (pane %s, tab_active %s: the reader's own word); "
          "not a failed read, never counted toward retry-stop" % (len(ids), reason, _jd.NOT_ATTEMPTED_VIA, pane, tab))
    return 0
