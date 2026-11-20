"""fallback: `read-batch --fallback`, the automatic logged-out posting read of a LinkedIn role no browser could read (for
everyone from 0.90.0, dev 858), and `not-attempted`, the record that a page was never read because the Browser pane did not
paint (design-browser-fallback.md 6, 8.1).

Capability module of record.py (an entry point over `recording/`)."""

import collections
import datetime
import hashlib
import json
import re
import board_hosts as _bh
import jd_read as _jd
from recording import profile_paths as _paths
from recording.evidence_keys import PROBE_RETIRED, new_evidence, new_keys_pin_refusal
from recording.row_checks import _diagnostic_lines, _row_checks, new_problems, validate
from recording.common import _Refused, _Usage, _engine_version, _now, _profile_mod, _words
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


def _fallback_ineligible(row, run, sess, value="on"):
    """`(job_id, None)` when `row` may be fetched, else `(None, why)`. Decided from the stored attempts, never the reader's word.

    `value` is the key's tri-state (`posting_fetch.key_value`), because the per-role rules differ (design-browser-fallback.md 6.1):
    for `on` the rule is 0.85.0's (the latest browser attempt is `pane-hidden` or `render-failed`, any gate, and nothing is asked
    of the extension); for any other value (`absent`, and the `off` or `unreadable` a withheld call stores) rules 2 and 3 apply: a
    `render-failed` read counts only with a gate of `not-painting` or `probe-error`, and the attempt must carry a
    `fallback.extension` code whose "admits the fetch" cell (`jd_read.EXTENSION_CODES`) is yes. An absent code is ineligible: the
    extension rung comes first. The fetch rung's own `via fetch` attempts are never the browser's latest word."""
    import posting_fetch as _pf
    if _has_read(row):
        return None, "already read"
    try:
        in_run = [a for a in _jd.attempts(row) if a["run"] == run]
    except _jd.JdReadError as e:
        return None, "its jd_read cannot be read (%s)" % e
    latest = _jd.latest_of([a for a in in_run if not (a["via"] == "fetch" and a["outcome"] in _jd.NOT_ATTEMPTED)])
    if latest is None:
        return None, "no attempt in this run: the browser read comes first"
    if latest["via"] != "render" or latest["outcome"] not in FALLBACK_OUTCOMES:
        return None, "its latest attempt in this run is %s via %s, not %s" % (
            latest["outcome"], latest["via"], " or ".join(FALLBACK_OUTCOMES))
    if value != "on":
        ev = latest["evidence"]
        if latest["outcome"] == "render-failed" and ev.get("gate") not in FALLBACK_NOT_PAINTING_GATES:
            return None, "its read failed on a page that paints (gate %s): that is the role's own failure, not the browser's" % (
                ev.get("gate") or "not run")
        ext = (ev.get("fallback") or {}).get("extension")
        if ext is None:
            return None, "no extension code on its browser attempt: the extension rung comes before the fetch"
        if not _jd.EXTENSION_CODES.get(ext):
            return None, "its extension code %s does not admit the fetch" % ext
    job_id = next((j for j in (_pf.posting_id(u) for u in _bh.read_urls(row)) if j), None)
    if job_id is None:
        return None, "no LinkedIn job-view address"
    if sess is not None and sess.tried(row["id"]):
        return None, "already tried in this run"
    return job_id, None


FALLBACK_OUTCOMES = ("pane-hidden", "render-failed")
FALLBACK_NOT_PAINTING_GATES = ("not-painting", "probe-error")
_FETCH_STORE_CODE = {"rate-limited": "rate-limited", "http": "http", "refused": "refused", "wrong-page": "refused",
                     "redirected": "refused", "unreachable": "unreachable"}   # a fetch result kind -> its `fallback.fetch` code


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
    value, _why = _pf.key_value(_paths.ROOT)
    go, code, remedy = _pf.auto_gate(_paths.ROOT)
    if not go:
        # `off` and `unreadable` never fetch; a host the session may not reach, or a missing notice row, sends nothing either. The
        # code is stored on every role that passed the per-role rules (below), so the summary can say why none was read.
        print(("FALLBACK: off (%s)" % remedy) if code in ("off", "unreadable") else
              ("FALLBACK: withheld (%s): %s" % (code, remedy)))
    sdir = _pf.state_dir()
    if go and sdir is None:
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
        if not go:
            return 0                                             # nothing was admitted that this call could withhold
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

    sess = None if (check or not go) else _pf.Session(sdir, run)
    asked = list(dict.fromkeys(args.ids_arg)) if args.ids_arg else None
    pool = ([by_id.get(i) or i for i in asked] if asked is not None
            else sorted((o for o in data["opportunities"] if admitted(o)),
                        key=lambda o: (_lc.first_seen(o) or datetime.date.max, str(o.get("id")))))
    say = print if go else (lambda *_a: None)                    # a withheld call names no per-role reason: only the stored code
    eligible, counts = [], collections.Counter()
    for o in pool:
        if isinstance(o, str):
            say("FALLBACK %s: not eligible (no such role)" % o)
            continue
        if not admitted(o):
            say("FALLBACK %s: not eligible (it was not admitted in this run)" % o["id"])
            continue
        job_id, why = _fallback_ineligible(o, run, sess, value)
        if why:
            say("FALLBACK %s: not eligible (%s)" % (o["id"], why))
            continue
        eligible.append((o, job_id))
    stores = []
    if not go:
        stores = [{"id": o["id"], "code": code, "url": _fallback_address(o, _pf.posting_id)} for o, _j in eligible]
        if check:
            print("read-batch --fallback --check: %d role(s) would be withheld (%s); nothing fetched, nothing written."
                  % (len(stores), code))
            return 0
        return _store_withheld(args, run, data, stores)
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
        if value == "absent" and _pf.saved_body(sdir, o["id"]) is None:
            sess.say_once("terms", "\n".join(_pf.TERMS_LINES))  # the first automatic GET of each run says what it is, once
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
            if k in _FETCH_STORE_CODE:                          # `capped` and `host-closed` stay eligible for the next call
                stores.append({"id": o["id"], "code": _FETCH_STORE_CODE[k], "url": _fallback_address(o, _pf.posting_id)})
    rc = 0
    writes = [r for r in results if r["kind"] in ("read", "closed")]
    if writes or stores:
        rc = _apply_fallback_writes(args, run, data, writes, counts, _now(), stores=_storable(stores))
    nothing = sum(counts[k] for k in ("rate-limited", "http", "refused", "capped", "host-closed"))
    print("FALLBACK DONE: read %d, closed %d, body %d, nothing recorded %d (rate-limited %d, http %d, refused %d, "
          "capped %d, host closed %d)" % (counts["read"], counts["closed"], counts["body"], nothing,
                                          counts["rate-limited"], counts["http"], counts["refused"], counts["capped"],
                                          counts["host-closed"]))
    if more:
        print("MORE")
    return rc


def _fallback_address(row, posting_id):
    """The LinkedIn job-view address `row` is fetched for (the first one `posting_id` reads a job id from), else None."""
    return next((u for u in _bh.read_urls(row) if posting_id(u)), None)


def _storable(stores):
    """`stores` when the profile may carry the `fallback` evidence key, else `[]` after saying why: a profile below the 0.90.0
    pin must not be given a key an older engine cannot read (design 8.2), and the fetch's own `read`/`closed` writes need no key."""
    if not stores:
        return []
    refusal = new_keys_pin_refusal(("fallback",))
    if refusal:
        print("FALLBACK: why-not-read codes were not stored: " + refusal)
        return []
    return stores


def _store_withheld(args, run, data, stores):
    """The write of a call that sent nothing: one `via fetch` `pane-hidden` attempt carrying `fallback.fetch` on every role that
    passed the per-role rules, so the run summary prints why none was read. Exit code of the write."""
    stores = _storable(stores)
    if not stores:
        return 0
    return _apply_fallback_writes(args, run, data, [], collections.Counter(), _now(), stores=stores)


def _apply_fallback_writes(args, run, data, writes, counts, now, stores=()):
    """The ONE locked write of the fallback: `read` and `closed` attempts, each applied only to a role that is still
    unread when the lock is held, and (0.90.0, design 8.1) one `via fetch` `pane-hidden` attempt carrying `fallback.fetch` for
    each of `stores` ({id, code, url}: a role the fetch could not read, or that a withheld call never sent). A role whose latest
    attempt in this run is already that attempt with that code gets no second one. Mirrors `cmd_read_batch`'s write (same checks,
    same rollback). Returns the exit code."""
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
        noted = _note_not_read(stores, by_id, before, landed, run, at_iso)
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
    if noted:
        by_code = collections.Counter(s["code"] for s in noted)
        print("FALLBACK STORED: why-not-read noted on %d role(s) (%s); each is one `via fetch` pane-hidden attempt, never an "
              "outcome about the role" % (len(noted), ", ".join("%s %d" % (c, n) for c, n in sorted(by_code.items()))))
    return 0


def _note_not_read(stores, by_id, before, landed, run, at_iso):
    """Append, in memory, the `via fetch` `pane-hidden` attempt carrying `fallback.fetch` for each of `stores` still unread; the roles
    touched are added to `before` (their pre-write copy). Returns the stores noted. The caller's one locked write saves them."""
    noted = []
    for s in stores:
        oid = s["id"]
        row = by_id.get(oid)
        if row is None or _has_read(row) or any(w["id"] == oid and w["kind"] == "closed" for w in landed):
            continue
        try:
            existing = [dict(a) for a in _jd.attempts(row)]
            mine = _jd.latest_of([a for a in existing if a["run"] == run])
            if (mine is not None and mine["via"] == "fetch" and mine["outcome"] in _jd.NOT_ATTEMPTED
                    and (mine["evidence"].get("fallback") or {}).get("fetch") == s["code"]):
                continue                                    # the same answer is already stored for this role in this run
            attempt = _jd.make_attempt(at_iso, run, s.get("url"), "fetch", "pane-hidden",
                                       {"text": "no posting fetch read this role: %s" % s["code"], "fallback": {"fetch": s["code"]}})
        except _jd.JdReadError as e:
            print("FALLBACK %s: why-not-read code not stored (%s)" % (oid, " ".join(str(e).split())[:120]))
            continue
        before.setdefault(oid, json.loads(json.dumps(row)))
        row["jd_read"] = {"attempts": existing + [attempt]}
        noted.append(s)
    return noted


def cmd_not_attempted(args):
    """`record.py not-attempted` -- see the section comment above. Exit 0 on a write (or a dry run), 1 on a refusal (nothing
    written), 2 on usage."""
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
    if args.via_medium != _jd.NOT_ATTEMPTED_VERB_VIA:
        print("\u26d4 REFUSED \u2014 --via must be %s (got %r): a not-attempted record is a browser read that could not "
              "happen.\nusage: %s" % (_jd.NOT_ATTEMPTED_VERB_VIA, args.via_medium, NOT_ATTEMPTED_USAGE))
        return 2
    if args.probe_json is not None:
        print("\u26d4 REFUSED \u2014 %s\nusage: %s" % (PROBE_RETIRED, NOT_ATTEMPTED_USAGE))
        return 2
    try:
        new_keys = new_evidence(args, "not-attempted", args.via_medium, NOT_ATTEMPTED_USAGE)
    except _Usage as e:
        print("\u26d4 REFUSED \u2014 %s" % e)
        return 2
    except _Refused as e:
        print("\u26d4 REFUSED \u2014 %s" % e)
        return 1
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
    not_painting = new_keys.get("gate") in ("not-painting", "probe-error")
    if pane != "hidden" and tab != "no" and not not_painting:
        print("\u26d4 REFUSED \u2014 the pane line reads %r, --tab-active is yes and no --gate says the page did not paint: "
              "with the pane not hidden, the tab in front and a page that paints the page could have rendered, so a missing "
              "posting is `read-failed` evidence about the role, never `not-attempted`. Nothing written." % pane)
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
    evidence.update(new_keys)
    at_iso = _now().isoformat()
    check = bool(args.check or args.dry_run)
    try:
        for i in ids:                                       # the attempt itself must parse, before any lock or write
            _jd.make_attempt(at_iso, run, None, _jd.NOT_ATTEMPTED_VERB_VIA, reason, dict(evidence))
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
                attempt = _jd.make_attempt(at_iso, run, None, _jd.NOT_ATTEMPTED_VERB_VIA, reason, dict(evidence))
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
          "not a failed read, never counted toward retry-stop" % (len(ids), reason, _jd.NOT_ATTEMPTED_VERB_VIA, pane, tab))
    return 0
