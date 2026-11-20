"""fetching: `read-batch --fetch`, the script-first JD read: one polite GET per admitted role (never to LinkedIn), the
posting's JSON-LD settling what it can and the rest listed as the render residue, written in one locked write.

Capability module of record.py (an entry point over `recording/`)."""

import datetime
import json
import re
from recording import profile_paths as _paths
from recording.row_checks import _diagnostic_lines, _row_checks, new_problems, validate
from recording.common import _engine_version, _now, _profile_mod, _words
from recording.fallback import cmd_read_fallback
from recording.reads import (
    FETCH_DEADLINE_S_DEFAULT,
    _apply_failed,
    _apply_read,
    _has_read,
    _store_screen,
)
from recording.store_files import (
    LockError,
    _load_or_empty,
    load,
    lock_is_held,
    release_lock,
    restore,
    save_atomic,
    snapshot,
    take_lock,
)


READ_BATCH_USAGE = ("read-batch --run <id> --fetch [--deadline-s N] [--check] [--already-locked]\n"
                    "       read-batch --run <id> --fallback [--ids <opp id> ...] [--deadline-s N] [--check] "
                    "[--already-locked]")

# The host the first pass never GETs (0.85.0). `board_hosts.host_matches` is the one comparison, so a sub-domain counts.
LINKEDIN_HOST = "linkedin.com"

# Seams (tests replace them; the shipped verb never does): `_FETCH(url) -> (status, headers, body)` stands in for the
# network, `_CLOCK` (an object with `now()` and `sleep(s)`) for the wall clock and the politeness sleeps.
_FETCH = None
_CLOCK = None


def _fetch_clock():
    if _CLOCK is not None:
        return _CLOCK
    import feed_poll as _fp
    return _fp.RealClock()


def _polite_get(url, last_by_host, clock):
    """`(status, headers, body)` for one GET of a job page, with the feed poller's politeness. Raises
    `feed_poll.FetchError` on a transport failure."""
    import feed_poll as _fp
    import board_hosts as _bh
    host = _bh.host_of(url)

    def one():
        if host in last_by_host:
            wait = _fp.MIN_INTERVAL_S - (clock.now() - last_by_host[host])
            if wait > 0:
                clock.sleep(wait)
        last_by_host[host] = clock.now()
        if _FETCH is not None:
            return _FETCH(url)
        r = _fp.default_fetch(_fp.Request("GET", url, {"User-Agent": _fp.USER_AGENT}, _fp.TIMEOUT_S))
        return r.status, r.headers, r.body

    status, headers, body = one()
    if status in (429, 503):
        ra = _fp.parse_retry_after((headers or {}).get("retry-after"))
        if ra is not None:
            clock.sleep(min(ra, _fp.RETRY_AFTER_CAP_S))
            status, headers, body = one()
    return status, headers, body


def _fetch_one(row, company, channels, run_date, last_by_host, clock):
    """What one fetch of one role decided: `("read", {...})`, `("failed", {outcome, text, url})` or `("residue",
    reason)`. No store is touched."""
    import feed_poll as _fp
    import board_hosts as _bh
    plan = _bh.jd_read_plan(row, channels)
    if plan["url"] is None:
        if plan["blocked"]:
            b = plan["blocked"][0]
            return "failed", {"outcome": "manual-board", "url": b["url"],
                              "text": "every address is on the manual-candidate board %s (host %s): not opened"
                                      % (b["channel_id"], b["host"])}
        return "failed", {"outcome": "no-url", "url": None, "text": "the role carries no address to read"}
    url = plan["url"]
    if _bh.host_matches(_bh.host_of(url), LINKEDIN_HOST):
        # 0.85.0 (dev #840 / public #181, owner ruling "browser first"): the first pass NEVER sends a GET to a LinkedIn
        # address, the key on or off. Up to 0.84.0 it made one plain GET here, read no JSON-LD and left the role in the
        # render residue; the browser reads such a role first, and `read-batch --fallback` (below) is the only script
        # that reads LinkedIn, only for an opted-in user and only after the browser read could not happen.
        return "residue", "browser-first"
    try:
        status, headers, body = _polite_get(url, last_by_host, clock)
    except _fp.FetchError as e:
        return "residue", "fetch-error (%s)" % e.code
    if status in (404, 410):
        return "failed", {"outcome": "dead-link", "url": url, "text": "HTTP %d" % status}
    if status in (401, 403):
        return "failed", {"outcome": "login-wall", "url": url, "text": "HTTP %d" % status}
    if status != 200:
        return "residue", "http-%d" % status
    try:
        parsed = _fp.parse_jobposting(body, url, run_date)
    except _fp.PageRefusal as e:
        return "residue", "unparseable (%s)" % e.code
    if parsed["expired"]:
        return "failed", {"outcome": "closed", "url": url, "text": "the posting's validThrough is in the past"}
    posting = parsed["posting"]
    if not (_words(posting["title"]) & (_words(row.get("title")) | _words((company or {}).get("name"))
                                        | _words(row.get("company_id")))):
        return "residue", "wrong-page (the posting's title shares no word with the role)"
    if posting["pay"] == "?" or posting["setting"] == "?":
        return "residue", "insufficient (%s not derivable)" % ("pay" if posting["pay"] == "?" else "setting")
    import hashlib
    return "read", {"url": url, "pay": posting["pay"], "setting": posting["setting"],
                    "place": posting["location"], "sha1": hashlib.sha1(body).hexdigest(), "chars": len(body)}


def cmd_read_batch(args):
    """`record.py read-batch --run <id> --fetch` -- see the section comment above. Exit 0 (a residue and a deadline are
    not faults: the next steps take them), 1 when a store cannot be read or the write was rolled back, 2 on usage."""
    if args.rid or args.rest or bool(args.fetch) == bool(args.fallback) or (args.ids_arg and not args.fallback):
        print("usage: " + READ_BATCH_USAGE)
        return 2
    run = (args.run_id_arg or "").strip()
    if not run or re.search(r"\s", run):
        print("⛔ REFUSED — --run <run id> is required (no whitespace).\nusage: " + READ_BATCH_USAGE)
        return 2
    if args.fallback:
        return cmd_read_fallback(args, run)
    deadline_s = FETCH_DEADLINE_S_DEFAULT if args.deadline_s is None else args.deadline_s
    if deadline_s < 0:
        print("⛔ REFUSED — --deadline-s must be 0 or more.")
        return 2
    check = bool(args.check or args.dry_run)
    import journal as _journal
    import lifecycle as _lc
    clock = _fetch_clock()
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
    now = _now()
    ctx = _lc.context(data, now)
    companies = {c.get("id"): c for c in data["companies"]}
    channels = _load_or_empty("channels")
    to_fetch, to_rescreen = [], []
    for o in data["opportunities"]:
        cap = o.get("capture") if isinstance(o.get("capture"), dict) else {}
        if o.get("id") not in adm_opps and cap.get("item") not in adm_items:
            continue
        try:
            st, progress = ctx.settled_or_progress(o)
        except Exception:                                    # noqa: BLE001 -- an unclassifiable row is `unclassified`
            continue
        if st is not None:
            continue
        if progress in ("captured", "reading"):
            to_fetch.append(o)
        elif progress == "read":
            to_rescreen.append(o)
    to_fetch.sort(key=lambda o: (_lc.first_seen(o) or datetime.date.max, str(o.get("id"))))
    n_admitted = len(to_fetch) + len(to_rescreen)
    if check:
        print("read-batch --check: %d admitted role(s) -> %d to fetch, %d to re-screen; nothing fetched, nothing "
              "written." % (n_admitted, len(to_fetch), len(to_rescreen)))
        return 0
    # ---- the network, BEFORE the lock ----
    t0 = clock.now()
    last_by_host, results, residue, unreached = {}, [], [], []
    run_date = now.date().isoformat()
    for o in to_fetch:
        if clock.now() - t0 >= deadline_s:
            unreached.append(o["id"])
            residue.append((o["id"], "fetch-unreached"))
            continue
        kind, payload = _fetch_one(o, companies.get(o.get("company_id")), channels, run_date, last_by_host, clock)
        if kind == "residue":
            residue.append((o["id"], payload))
        else:
            results.append((o["id"], kind, payload))
    # ---- one locked write ----
    if args.already_locked:
        if not lock_is_held():
            print("  REFUSED — --already-locked, but NOBODY holds the run lock.")
            return 1
    else:
        try:
            take_lock("record.py read-batch --run %s" % run, wait=args.wait)
        except LockError as e:
            print("  REFUSED — %s" % e)
            return 1
    tally = {"read": 0, "gone": 0, "your-read": 0, "rescreened": 0}
    try:
        profile = _profile_mod().load()
        opps = load("opportunities")
        applications = _load_or_empty("applications")
        channels = _load_or_empty("channels")
        by_id = {o.get("id"): o for o in opps}
        before = {}
        engine, at_iso, on = _engine_version(), now.isoformat(), now.date()
        import jd_read as _jd
        for oid, kind, p in results:
            row = by_id.get(oid)
            if row is None:
                continue
            if _has_read(row):
                continue                                     # a read landed while the network was out
            pre_row = json.loads(json.dumps(row))
            before.setdefault(oid, pre_row)
            company = next((c for c in data["companies"] if c.get("id") == row.get("company_id")), None)
            try:
                if kind == "failed":
                    _apply_failed(row, run=run, url=p["url"], via="fetch", outcome=p["outcome"], text=p["text"],
                                  at_iso=at_iso)
                    tally["gone" if _jd.outcome_class(p["outcome"]) == "terminal" else "your-read"] += 1
                else:
                    import deferred as _deferred
                    lp, why = _deferred.parse_pay_slot(p["pay"])
                    if why:
                        raise KeyError(why)
                    lp = dict(lp, captured_on=on.isoformat(), provenance="jd")      # source: listing-text, as parsed
                    _apply_read(row, run=run, url=p["url"], via="fetch",
                                evidence={"sha1": p["sha1"], "chars": p["chars"]}, pay=lp, setting=p["setting"],
                                place=p["place"], at_iso=at_iso, on=on, engine=engine, profile=profile,
                                company=company, all_opps=opps, applications=applications, channels=channels,
                                pay_inferred=True)
                    tally["read"] += 1
            except KeyError as e:
                before.pop(oid, None)
                residue.append((oid, "not recorded: %s" % " ".join(str(e).split())[:120]))
                row.clear()
                row.update(pre_row)                          # a refused result leaves the row exactly as it was
        for o in to_rescreen:
            row = by_id.get(o["id"])
            if row is None:
                continue
            before.setdefault(row["id"], json.loads(json.dumps(row)))
            _store_screen(row, on, engine, profile=profile, all_opps=opps, applications=applications,
                          channels=channels)
            tally["rescreened"] += 1
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
    rc_out = 0
    try:
        _journal.record_pass(_paths.ROOT, run, "fetch", "done", unreached=sorted(unreached))
    except _journal.JournalError as e:
        print("⚠️ could not journal `pass fetch done` (%s)" % e)
        rc_out = 1
    for oid, why in residue:
        print("RESIDUE %s (render): %s" % (oid, why))
    print("read-batch: %d admitted → %d read · %d gone · %d your-read · %d re-screened · %d residue (render) · "
          "%d deadline-left" % (n_admitted, tally["read"], tally["gone"], tally["your-read"], tally["rescreened"],
                                len(residue), len(unreached)))
    print("deadline-left %d" % len(unreached))
    return rc_out
