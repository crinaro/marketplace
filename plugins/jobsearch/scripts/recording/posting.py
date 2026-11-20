"""posting: the `posting` verb, the ONLY writer of an opportunity's `employer_posting` (read from EMPLOYER-POSTING lines
in a file, never argv), and the value a role born from a company-feed item gets by construction.

Capability module of record.py (an entry point over `recording/`)."""

import datetime
import json
import re
from recording import profile_paths as _paths
from recording.row_checks import (
    _POSTING_FIELD,
    _diagnostic_lines,
    _posting_writer,
    dry_run_validate,
    introduced_row_violations,
    new_problems,
    validate,
    verb_owned_refusal,
)
from recording.common import _Refused
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


# ---- jobsearch 0.80.0 (dev #776 / public #166; design-employer-posting-confirmation.md sections 5-6, 15 N1/N9/N10) ------
#
# `record.py posting --from-file <file>` is the ONE writer of an opportunity's `employer_posting` field (the other is the
# capture call inside `create --from-item` for a company-feed item, `_feed_posting_value`). It reads every
# EMPLOYER-POSTING line in a FILE and never takes a line on argv: the researcher's quoted visible text holds quotes, a
# dollar sign and backticks, and a line a shell has already parsed is a line that has already been altered (N1).
#
# What it relies on from `posting_check.py` (the pure half, built beside this verb):
#   parse_line(line)                        -> (opp_id, Observation(kind, url, via, signal, evidence)); raises PostingLineError
#                                              (a ValueError) on anything outside the grammar; a `looked` line carries its word
#                                              (site-not-allowed|render-failed|inconclusive) in `signal`, mapped to a look-cache
#                                              code by `LOOKED_CODES`
#   parse(value)                            -> the stored value read strictly; raises on a malformed one; None -> unconfirmed
#   observe(reading, obs, today: ISO str)   -> the new value to store; raises ObservationRefused (T3, T7, T8)
#   employer_owned(url, company, channels)  -> (bool, basis)
#   capture_confirms(sighting, channels, opp) -> bool
#   note_look(root, opp_id, outcome, today) -> writes the look cache (a cache: losing it costs repeated looks, never a state)
POSTING_USAGE = ("posting --from-file <file of EMPLOYER-POSTING lines> [--dry-run] [--already-locked] "
                 "[--today YYYY-MM-DD (test-only)]")
POSTING_LINE_PREFIX = "EMPLOYER-POSTING "


def _posting_check():
    import posting_check as _pc
    return _pc


def _posting_errors(pc):
    """The exception types `posting_check` raises for a refusal (grammar, strict parse, a refused observation)."""
    return (ValueError, getattr(pc, "PostingFieldError", ValueError))


def _posting_today(raw):
    """The run date as a `datetime.date`: `--today` (TEST-ONLY, `YYYY-MM-DD`, a real calendar day) or today. Checked by
    shape first and calendar second, with ASCII digits only, so it does not depend on which Python runs it."""
    if raw is None:
        return datetime.date.today()
    m = re.fullmatch(r"([0-9]{4})-([0-9]{2})-([0-9]{2})", raw)
    if not m:
        raise _Refused("--today must be YYYY-MM-DD (it is test-only), got %r" % raw)
    try:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        raise _Refused("--today %r is not a calendar date" % raw)


def _posting_read_lines(path):
    """`([(line number, line), ...], ignored)` for the file at `path`: every line that begins (after spaces or tabs) with
    `EMPLOYER-POSTING `, stripped of the spaces or tabs around it and of nothing else, and the count of other non-blank
    lines. Split on a newline only (`str.splitlines` also splits on U+2028 and others, which a quoted posting text may
    hold), so a quote reaches the parser byte for byte."""
    with open(path, encoding="utf-8", newline="") as fh:
        text = fh.read()
    lines, ignored = [], 0
    for n, raw in enumerate(text.split("\n"), 1):
        line = (raw[:-1] if raw.endswith("\r") else raw).strip(" \t")
        if line.startswith(POSTING_LINE_PREFIX):
            lines.append((n, line))
        elif line:
            ignored += 1
    return lines, ignored


def _board_root(pc, url):
    """The part of `url` that names the employer's board: scheme and host, plus the first path segment on a shared
    multi-tenant host (`posting_check.PATH_TENANT_HOSTS`), where the path is what names the employer."""
    import urllib.parse as _up
    sp = _up.urlsplit(url or "")
    root = "%s://%s" % (sp.scheme, sp.netloc)
    host = (sp.hostname or "").lower()
    if host in tuple(getattr(pc, "PATH_TENANT_HOSTS", ())):
        seg = next((p for p in sp.path.split("/") if p), "")
        if seg:
            root += "/" + seg
    return root


def _posting_not_owned(pc, url, company, from_file=None):
    """The refusal for a `live` line whose URL is not the employer's own posting, with the remedy as a command the user can
    run (design section 5.1). The remedy uses the field the engine already has for "this company's own careers page",
    `companies[].career_url`, whose host `posting_check.employer_owned` compares; it replaces whatever is stored, and the
    message prints what that is. Dev #861: the refusal also prints the line to RE-RUN once the page is recorded (the file is
    re-applied whole; a line that already applied is harmless), built from `posture.LAUNCHER`, the one launcher constant."""
    import urllib.parse as _up
    import shlex
    import posture as _posture
    ats = company.get("ats") if isinstance(company.get("ats"), dict) else None
    ats_txt = ("%s:%s" % (ats.get("vendor"), ats.get("slug") or ats.get("tenant"))) if ats else "none"
    career = company.get("career_url") if isinstance(company.get("career_url"), str) else None
    host = (_up.urlsplit(career).hostname or "none") if career else "none"
    text = ("⛔ REFUSED — %s is not %s's own posting: not its ATS (%s), not its careers host (%s).\n"
            "   If this IS the employer's own board, record it as the company's careers page (this replaces the stored "
            "career_url, %s):  ~/.claude/jobsearch/run record.py set %s career_url %s --file companies"
            % (url, company.get("id"), ats_txt, host, career or "none", shlex.quote(str(company.get("id"))),
               shlex.quote(_board_root(pc, url))))
    if from_file:
        text += ("\n   Then re-run:  %s record.py posting --from-file %s"
                 % (_posture.LAUNCHER, shlex.quote(str(from_file))))
    return text


def _posting_plan(pc, lines, opps, companies, channels, today, from_file=None):
    """Apply every parsed line to `opps` IN MEMORY and return `{results, looks, changed}`. A line that cannot be applied is
    a result with `ok` False and the reason in `text`; the others still apply (each line is its own role). Nothing here
    touches disk."""
    errors = _posting_errors(pc)
    results, looks, changed = [], [], []
    for n, line in lines:
        res = {"n": n, "opp_id": None, "ok": False, "text": ""}
        results.append(res)
        try:
            oid, obs = pc.parse_line(line)
        except errors as e:
            res["text"] = "⛔ REFUSED line %d — outside the EMPLOYER-POSTING grammar (%s); never retry it edited." % (n, e)
            continue
        res["opp_id"] = oid
        row = find(opps, oid)
        if row is None:
            res["text"] = "⛔ REFUSED line %d — no opportunity with id %r." % (n, oid)
            continue
        kind = obs.kind
        if kind == "looked":
            # `posting_check.LOOKED_CODES` maps the line's word to the look-cache code (`inconclusive` -> `inconclusive-line`)
            looks.append((oid, pc.LOOKED_CODES[obs.signal]))
            res["ok"] = True
            res["text"] = "%s: looked (%s) — noted, nothing written to the role" % (oid, obs.signal)
            continue
        if kind == "live":
            company = find(companies, row.get("company_id"))
            if company is None:
                res["text"] = ("⛔ REFUSED line %d — %s names company %r, which is not in companies; nothing written."
                               % (n, oid, row.get("company_id")))
                continue
            owned, _basis = pc.employer_owned(obs.url, company, channels)
            if not owned:
                looks.append((oid, "refused-not-owned"))
                res["text"] = _posting_not_owned(pc, obs.url, company, from_file)
                continue
        try:
            # `observe` takes the run date as an ISO string (a real YYYY-MM-DD, checked by `posting_check._real_date`)
            new = pc.observe(pc.parse(row.get(_POSTING_FIELD)), obs, today.isoformat())
        except errors as e:
            res["text"] = "⛔ REFUSED line %d — %s: %s" % (n, oid, e)
            continue
        row[_POSTING_FIELD] = new
        if oid not in changed:
            changed.append(oid)
        res["ok"] = True
        res["text"] = "%s: %s → %s" % (oid, kind, (new or {}).get("state") if isinstance(new, dict) else new)
        if kind == "live" and isinstance(new, dict) and new.get("state") == "confirmed":
            res["text"] += _posting_jd_url(row, new.get("url"))
    return {"results": results, "looks": looks, "changed": changed}


def _posting_row_checks(opps_before, opps_after, changed):
    """The row-level refusals for the rows this call changed: the introduced-only rules AND `verb_owned_refusal`, with the
    writer token held (this IS the sanctioned writer; the token is what `cmd_posting`'s own test plants against)."""
    bad = []
    with _posting_writer():
        for oid in changed:
            before, after = find(opps_before, oid), find(opps_after, oid)
            bad += (introduced_row_violations("opportunities", before, after)
                    + verb_owned_refusal("posting", "opportunities", before, after))
    return bad


def _posting_jd_url(row, employer_url):
    """dev #820 / public #175 (design section 8.1, D817): a posting CONFIRMED on the employer's own address fills an EMPTY
    `jd_url` with it (the link a person is shown prefers the employer's posting). When `jd_url` is already set to
    another host nothing is changed and the disagreement is printed, once: `JD_URL DISAGREES: jd_url <host> vs employer
    posting <host>`. Returns the text to add to the result line."""
    import board_hosts as _bh
    current = row.get("jd_url")
    if not (isinstance(employer_url, str) and employer_url.strip()):
        return ""
    if not (isinstance(current, str) and current.strip()):
        row["jd_url"] = employer_url
        return "; jd_url filled from the employer posting"
    h_cur, h_emp = _bh.host_of(current), _bh.host_of(employer_url)
    if h_cur and h_emp and h_cur != h_emp:
        return "\n  JD_URL DISAGREES: jd_url %s vs employer posting %s (nothing changed)" % (h_cur, h_emp)
    return ""


def _posting_note_looks(pc, looks, today):
    for oid, outcome in looks:
        try:
            pc.note_look(_paths.ROOT, oid, outcome, today.isoformat())
        except (OSError, ValueError) as e:                       # a cache: never fails the call
            print("  ⚠️ could not note the look for %s (%s); it costs a repeated look, never a state" % (oid, e))


def _print_posting_results(plan, ignored):
    n_ok = sum(1 for r in plan["results"] if r["ok"])
    print("posting: %d EMPLOYER-POSTING line(s) read, %d applied or noted, %d refused%s"
          % (len(plan["results"]), n_ok, len(plan["results"]) - n_ok,
             ("; %d other line(s) in the file ignored" % ignored) if ignored else ""))
    for r in plan["results"]:
        print("  " + r["text"])


def cmd_posting(args):
    """`record.py posting --from-file <file>` -- dev #776 / public #166 (design section 6.1, 15 N1/N9/N10). Record what
    research or the scheduled re-check saw on the employer's OWN posting, from the EMPLOYER-POSTING lines in a file.

    The date is the run date (`--today` is a test-only seam), never typed on a line. Each line is parsed strictly
    (`posting_check.parse_line`), a `live` line must name the employer's own posting (`employer_owned`) or is refused
    with a remedy and a look noted, and the new value is `posting_check.observe`'s. Every line that applies lands in
    ONE locked, validated, rollback-verified write of the opportunities store, or none does; a refused line does not stop
    the others. `looked` lines and ownership refusals write only the look cache. Exit 0 when every line applied or was
    noted, 1 when any was refused (the applied ones still landed) or the write was rolled back, 2 on usage."""
    if args.rid or args.rest or not args.from_file:
        print("usage: " + POSTING_USAGE)
        return 2
    try:
        today = _posting_today(args.today_arg)
        lines, ignored = _posting_read_lines(args.from_file)
    except _Refused as e:
        print("⛔ REFUSED — %s" % e)
        return 1
    except (OSError, UnicodeDecodeError) as e:
        print("⛔ REFUSED — %s cannot be read (%s); nothing written." % (args.from_file, e))
        return 1
    if not lines:
        print("⛔ REFUSED — NOT CHECKED: %s holds no EMPLOYER-POSTING line (%d other non-blank line(s) ignored). A role "
              "the research could not place owes a `not-found` line, never silence." % (args.from_file, ignored))
        return 1
    pc = _posting_check()
    try:
        channels, companies, opps = (_load_or_empty("channels"), load("companies"), load("opportunities"))
    except (OSError, ValueError) as e:
        print("⛔ REFUSED — a store cannot be read (%s); nothing written." % e)
        return 1
    shadow = json.loads(json.dumps(opps))
    plan = _posting_plan(pc, lines, shadow, companies, channels, today, args.from_file)
    refused = any(not r["ok"] for r in plan["results"])
    if args.dry_run:
        _print_posting_results(plan, ignored)
        if plan["changed"]:
            introduced = _posting_row_checks(opps, shadow, plan["changed"])
            if introduced:
                print("  ⛔ a REAL (non-dry-run) write of this would be REFUSED (nothing is written):")
                print("  " + "\n  ".join("- " + m for m in introduced))
                return 1
            pre_rc, _, _, pre_problems = validate()
            rc, out, err, problems = dry_run_validate("opportunities", shadow)
            added = new_problems(pre_problems, problems) if rc != 0 else []
            if rc != 0 and (added is None or added):
                print("  ⛔ a REAL (non-dry-run) write of this would be REFUSED and rolled back.")
                print("  " + "\n  ".join(added if added else _diagnostic_lines(rc, out, err)))
                return 1
            print("  ✅ dry-run validated clean against the same validator a real write runs.")
        print("  --dry-run: nothing written.")
        return 1 if refused else 0
    if plan["changed"]:
        if args.already_locked:
            if not lock_is_held():
                print("  REFUSED — --already-locked, but NOBODY holds the run lock.")
                return 1
        else:
            try:
                take_lock("record.py posting", wait=args.wait)
            except LockError as e:
                print("  REFUSED — %s" % e)
                return 1
        try:
            # re-read INSIDE the lock, and re-apply on what is really there
            channels, companies, opps = (_load_or_empty("channels"), load("companies"), load("opportunities"))
            before_rows = json.loads(json.dumps(opps))
            plan = _posting_plan(pc, lines, opps, companies, channels, today, args.from_file)
            refused = any(not r["ok"] for r in plan["results"])
            if plan["changed"]:
                introduced = _posting_row_checks(before_rows, opps, plan["changed"])
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
    _print_posting_results(plan, ignored)
    _posting_note_looks(pc, plan["looks"], today)
    return 1 if refused else 0


def _feed_posting_value(item, new_row, today, channels=None):
    """`(value, error)` for `create --from-item` of a company-FEED item (design section 6.3): the `employer_posting` value
    the script writes itself, `live <canonical job url> via feed`, through the same `observe` every writer uses, when
    `capture_confirms` holds for the sighting (a company-site channel linked to this role's company). `(None, None)` when
    it does not hold or the item has no URL: nothing is written for that role. A typed `employer_posting` is an error."""
    if _POSTING_FIELD in new_row:
        return None, ("%s is written only by the script (`record.py posting`, or this capture of a feed item); remove it "
                      "from the JSON" % _POSTING_FIELD)
    pc = _posting_check()
    sgs = new_row.get("sightings")
    sighting = next((s for s in (sgs if isinstance(sgs, list) else []) if isinstance(s, dict)), None)
    url = item.get("ref")
    if channels is None:
        channels = _load_or_empty("channels")
    if sighting is None or not url or not pc.capture_confirms(sighting, channels, new_row):
        return None, None
    try:
        value = pc.observe(pc.parse(None), pc.live(url, "feed"), today.isoformat())
    except _posting_errors(pc) as e:
        return None, "the feed observation was refused (%s)" % e
    return value, None
