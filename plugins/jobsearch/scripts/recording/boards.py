"""boards: the company-feed and job-board verbs: `ats` (a company's applicant-tracking feed, set, declined or
discovered), `warm-lookup`, and `board-sighting` (one role seen on a board: the company matched or created and the
role created or given a sighting, in one write), with the capture-time rule that a sighting carries its `source_url`.

Capability module of record.py (an entry point over `recording/`)."""

import datetime
import json
from recording.row_checks import (
    _diagnostic_lines,
    dry_run_validate,
    introduced_row_violations,
    new_problems,
    validate,
    verb_owned_refusal,
)
from recording.common import (
    _Refused,
    _profile_mod,
    _run_date,
    _run_date_value,
    _slug,
    _validator_module,
)
from recording.sourcing import _new_opportunity_plan
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


def sighting_source_url_problem(sighting, channel_type_by_id, referenced_channel_ids, receipted):
    """public #83 rule 1 — refuse a NEW sighting from a URL-bearing channel (job-board/
    aggregator — `validate_data.URL_BEARING_CHANNEL_TYPES`, imported rather than re-typed, the
    same set doctor.py's run-start advisory (#360) reads) with no source_url, AT THE MOMENT IT
    IS CAPTURED. The link is free right now and effectively unrecoverable once the posting
    comes down — making it optional guaranteed it was sometimes dropped (public #83's own
    finding). Returns None if the sighting is fine to write, else the reason to refuse.

    The SAME two exclusions the run-start advisory computes (never re-typed, only re-derived
    from data this caller already has, since the advisory works from a whole record after the
    fact and this works from one sighting before it is written):

      1. recruiter-sourced — `referenced_channel_ids` (the record's own channel_id plus every
         sighting already on it, plus this new one) resolves ANY channel of type 'recruiter'.
         There was never a public posting to link, regardless of this sighting's own channel.
      2. receipt-backed — `receipted` is True when an applications.jsonl row for this
         opportunity already carries a status in validate_data.SUBMITTED_APP_STATUS. The
         application itself is durable evidence the role existed.

    A channel type outside URL_BEARING_CHANNEL_TYPES (recruiter/referral/company-site/
    alert-email) is never in scope at all — it never carried a public URL to lose.
    """
    if sighting.get("source_url"):
        return None
    _vd = _validator_module()
    ctype = channel_type_by_id.get(sighting.get("channel_id"))
    if ctype not in _vd.URL_BEARING_CHANNEL_TYPES:
        return None
    if any(channel_type_by_id.get(cid) == "recruiter"
           for cid in referenced_channel_ids if cid):
        return None    # 1. recruiter-sourced
    if receipted:
        return None    # 2. receipt-backed
    return ("sighting from channel %r (type %r) has no source_url. public #83 rule 1: a "
            "sighting from a URL-bearing channel (job-board/aggregator) must carry its URL at "
            "the moment it is captured — the link is free now and effectively unrecoverable "
            "once the posting comes down. Pass 'source_url' in the sighting JSON, or record it "
            "through a channel that never carries one (e.g. a recruiter relationship)."
            % (sighting.get("channel_id"), ctype))


def _company_feed_write(args, label, edit):
    """dev #751 -- ONE locked, validated, rollback-verified write of the COMPANIES store, and the
    CHANNELS store when `edit` changed it. `edit(company, channels, opportunities)` mutates in place
    and returns `(description_lines, channels_changed)` or raises `_Refused`; nothing has been
    written when it does. Returns the exit code.

    The stores are snapshotted, written atomically, and the validator is run; a write that
    INTRODUCES a problem (a set comparison against the problems before it, `new_problems`) restores
    both stores byte for byte and says so. `--dry-run` runs `edit` on deep copies and also applies the
    two feed invariants (`validate_data.check_feed_links`) to the result, so it predicts the write
    without touching a store. Refusals happen BEFORE the lock."""
    cid = args.rid
    if not cid or args.rest:
        print("usage: %s" % label)
        return 2
    _vd = _validator_module()
    try:
        companies = load("companies")
        channels = _load_or_empty("channels")
        opps = _load_or_empty("opportunities")
    except (OSError, ValueError) as e:
        print("⛔ REFUSED — a store cannot be read (%s); nothing written." % e)
        return 1
    if find(companies, cid) is None:
        print("⛔ REFUSED — %r resolves to no companies record." % cid)
        return 1
    shadow_c, shadow_ch = json.loads(json.dumps(companies)), json.loads(json.dumps(channels))
    try:
        lines, ch_changed = edit(find(shadow_c, cid), shadow_ch, opps)
    except _Refused as e:
        print("⛔ REFUSED — %s" % e)
        return 1
    problems = _vd.check_feed_links(shadow_c, shadow_ch)
    if problems:
        print("⛔ REFUSED — the result would break the feed invariants (nothing written):")
        print("  " + "\n  ".join("- " + p for p in problems))
        return 1
    if shadow_c == companies and not ch_changed:
        for line in lines:
            print(line)
        print("%s: nothing to change." % cid)
        return 0
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
            take_lock("record.py %s %s" % (label.split()[0], cid), wait=args.wait)
        except LockError as e:
            print("  REFUSED — %s" % e)
            return 1
    try:
        # re-read INSIDE the lock, and re-run the edit on what is really there
        companies = load("companies")
        channels = _load_or_empty("channels")
        try:
            lines, ch_changed = edit(find(companies, cid), channels, opps)
        except _Refused as e:
            print("⛔ REFUSED — %s" % e)
            return 1
        snap_c, snap_ch = snapshot("companies"), snapshot("channels")
        pre_problems = validate()[3]
        save_atomic("companies", companies)
        if ch_changed:
            save_atomic("channels", channels)
        rc, out, err, post_problems = validate()
        added = new_problems(pre_problems, post_problems)
        if rc != 0 and (added is None or added):
            ok_c = restore("companies", snap_c)
            ok_ch = restore("channels", snap_ch) if (ch_changed and snap_ch is not None) else True
            print("⛔ the write left the stores invalid and was %s."
                  % ("ROLLED BACK (byte-identical)" if ok_c and ok_ch
                     else "NOT VERIFIABLY ROLLED BACK — restore companies.jsonl and channels.jsonl "
                          "from git"))
            print("  " + "\n  ".join(added if added else _diagnostic_lines(rc, out, err)))
            return 1
    finally:
        if not args.already_locked:
            release_lock()
    for line in lines:
        print(line)
    return 0


def cmd_ats(args):
    """`record.py ats <company_id> --url <careers or posting URL> | --none | --clear | --discover`
    -- dev #751 (sourcing-feeds, design §3.2). The candidate's verbs over `companies[].ats`:

      --url U       parse the URL (a string parse, never a fetch) and write `ats` with `source:
                    candidate`; a URL `ats_slug.parse` returns None for is REFUSED. Links or creates
                    the company's career-page channel in the same write.
      --none        `ats: null` -- decline a feed for this company; discovery never rewrites it.
      --clear       remove the key, so discovery may run again. The channel link is left alone.
      --discover    the engine's own path (`feed_poll.py`): parse the slug off the company's
                    `career_url` and its opportunities' `jd_url` / sighting `source_url`s. Writes only
                    an UNAMBIGUOUS result and never over an existing `ats` key; two distinct boards
                    print `ATS AMBIGUOUS` and write nothing.
    One mode per call; a refusal leaves both stores byte-identical."""
    import ats_slug as _ats
    modes = [m for m, on in (("--url", args.listing_url), ("--none", args.ats_none),
                             ("--clear", args.ats_clear), ("--discover", args.ats_discover)) if on]
    label = "ats <company_id> --url <url> | --none | --clear | --discover"
    if len(modes) != 1:
        print("⛔ REFUSED — ats takes exactly one of --url, --none, --clear, --discover "
              "(got %s)." % (", ".join(modes) or "none"))
        return 2
    mode = modes[0]
    today = datetime.date.today().isoformat()
    if mode == "--url":
        triple = _ats.parse(args.listing_url)
        if triple is None:
            print("⛔ REFUSED — %r names no board this engine can poll. The forms are "
                  "jobs.lever.co/<site>, jobs.eu.lever.co/<site>, jobs.ashbyhq.com/<name>, "
                  "boards.greenhouse.io/<token> and <tenant>.wd<N>.myworkdayjobs.com/<site> "
                  "(every other ATS stays on the browser); nothing written." % args.listing_url)
            return 1

    def edit(company, channels, opps):
        if mode == "--none":
            company["ats"] = None
            return ["%s: ats declined (null) -- discovery will not rewrite it" % company["id"]], False
        if mode == "--clear":
            company.pop("ats", None)
            return ["%s: ats key removed" % company["id"]], False
        if mode == "--discover":
            if "ats" in company:
                return ["ATS SKIPPED %s: already has an `ats` key (%s)"
                        % (company["id"], "declined" if company["ats"] is None else "set")], False
            d = _ats.discover(company, opps)
            if d.ambiguous:
                return ["ATS AMBIGUOUS %s: %s" % (company["id"], " | ".join(
                    "%s:%s" % (t[0], t[1]) for t in d.ambiguous))], False
            if d.found is None:
                return ["ATS NONE %s: no board URL on its career_url or postings" % company["id"]], False
            ch_id, how = _ats.apply_discovery(company, channels, d.found, d.source, today)
            return ["ATS %s %s:%s (%s) -> channel %s [%s]"
                    % (company["id"], d.found[0], d.found[1], d.source, ch_id, how)], how != "exists"
        ch_id, how = _ats.apply_discovery(company, channels, triple, "candidate", today)
        return ["ATS %s %s:%s (candidate) -> channel %s [%s]"
                % (company["id"], triple[0], triple[1], ch_id, how)], how != "exists"

    return _company_feed_write(args, label, edit)


def cmd_warm_lookup(args):
    """`record.py warm-lookup <company_id> --none-found [--on D]` -- dev #751 (design §4.2): the ONE
    stored fact of the warm path. "I looked for a person at this company and found nobody" has no other
    home (every other state is derived from the people, touches, drafts and applications stores).
    Writes `companies[].warm_lookup = {on, result: "none-found"}`; a person who WAS found is recorded
    with the existing verbs (a people row with `company_id`, then `record.py involve`)."""
    if not args.none_found:
        print("⛔ REFUSED — warm-lookup records only that you looked and found nobody: pass "
              "--none-found. A person you DID find goes in with a people row and `record.py "
              "involve <person> --opp <opp>`.")
        return 2
    try:
        on = _run_date(args).isoformat()
    except _Refused as e:
        print("⛔ REFUSED — %s" % e)
        return 1

    def edit(company, channels, opps):
        company["warm_lookup"] = {"on": on, "result": "none-found"}
        return ["%s: warm lookup recorded -- looked on %s, found nobody" % (company["id"], on)], False

    return _company_feed_write(args, "warm-lookup <company_id> --none-found [--on D]", edit)


BOARD_SIGHTING_USAGE = ("board-sighting <channel_id> --company \"<name as the board shows it>\" "
                        "--title \"<title>\" --url <the posting's OWN URL> [--company-id <id>] "
                        "[--vertical <enum>] [--seen-on YYYY-MM-DD] [--plan <plan_id>] [--dry-run] "
                        "[--already-locked]")


def _board_sighting_plan(args, channels, companies, opps, applications, seen_on):
    """dev #765 (design-portfolio-boards.md section 4) -- decide what ONE role seen on a board needs, from
    the lists it is handed, and mutate none of them. Raises `_Refused` (nothing written) or returns

        {"company_id", "new_company": row | None, "opp_id", "new_opp": row | None,
         "sighting": {...} | None, "noop": bool, "company_how", "role_how"}

    It adds NO matching rule of its own: the company is `pipeline_index.company_candidates` (one hit is
    matched, several refuse and list the ids, none creates), and the role is `find_known_match` (an active
    match gets the sighting appended, an excluded one refuses, none creates). The board's own URLs are
    refused (`board_hosts.blocked_channel`): the engine never opens a manual-candidate site, and a role
    whose only address is the board's cannot be read."""
    import board_hosts as _bh
    import pipeline_index as _pidx
    _vd = _validator_module()
    chan = find(channels, args.rid)
    if chan is None:
        raise _Refused("%r resolves to no channels record." % args.rid)
    if chan.get("type") != "job-board":
        raise _Refused("%r is a %r channel; a board sighting is recorded against a `job-board` channel."
                       % (args.rid, chan.get("type")))
    url = (args.listing_url or "").strip()
    if _bh.host_of(url) is None:
        raise _Refused("--url must be the posting's own http(s) address (got %r)." % args.listing_url)
    blocked = _bh.blocked_channel(url, channels)
    if blocked is not None:
        raise _Refused("--url %r is on the board itself (%s, host %s): the engine never opens a "
                       "manual-candidate site, and a role whose only address is the board's cannot be "
                       "read. Give the posting's OWN outbound address instead (the employer's career "
                       "site or ATS page the board links to)."
                       % (url, blocked.get("id"), _bh.host_of(url)))
    title = (args.title_text or "").strip()
    sighting = {"channel_id": args.rid, "seen_on": seen_on, "source_url": url}
    # ---- the company ----
    new_company = None
    if args.company_id_arg:
        company = find(companies, args.company_id_arg)
        if company is None:
            raise _Refused("--company-id %r resolves to no companies record." % args.company_id_arg)
        company_id, company_how = company["id"], "matched"
    else:
        hits = _pidx.company_candidates(args.company_name, companies)
        if len(hits) > 1:
            raise _Refused("--company %r matches %d companies (%s); pass --company-id to say which."
                           % (args.company_name, len(hits), ", ".join(hits)))
        if hits:
            company_id, company_how = hits[0], "matched"
        else:
            if args.vertical_arg is None:
                raise _Refused("--company %r matches no company, so one would be created, and `vertical` is "
                               "required for it: pass --vertical <%s> (`other` would be a guess)."
                               % (args.company_name, "|".join(sorted(_vd.VERTICALS))))
            if args.vertical_arg not in _vd.VERTICALS:
                raise _Refused("--vertical %r is not one of {%s}" % (args.vertical_arg,
                                                                    ", ".join(sorted(_vd.VERTICALS))))
            company_id = _slug(args.company_name)
            if not company_id:
                raise _Refused("--company %r has no letters or digits to make an id from; pass "
                               "--company-id for an existing company." % args.company_name)
            if find(companies, company_id) is not None:
                raise _Refused("the id %r (made from --company %r) is already a company that the name did "
                               "not match; pass --company-id %s if it is the same company."
                               % (company_id, args.company_name, company_id))
            new_company = {"id": company_id, "name": args.company_name.strip(),
                           "vertical": args.vertical_arg, "status": "watching", "research_log": []}
            company_how = "created"
    # ---- the role ----
    hit = _pidx.find_known_match(opps, url=url, company_id=company_id, title=title,
                                 applications=applications)
    if hit and hit[2] == "excluded":
        raise _Refused(_pidx.describe_match(hit[0], hit[1]) + " Nothing was recorded: a role you already "
                       "passed on is not a new sighting.")
    if hit:
        row = hit[0]
        dup = any(isinstance(s, dict) and s.get("channel_id") == args.rid and s.get("seen_on") == seen_on
                  and _pidx._urls_equal(s.get("source_url"), url) for s in row.get("sightings") or [])
        return {"company_id": company_id, "new_company": new_company, "company_how": company_how,
                "opp_id": row["id"], "new_opp": None, "sighting": None if dup else sighting,
                "noop": dup and new_company is None, "role_how": "already recorded" if dup else
                "sighting appended (%s)" % hit[1]}
    plan_id, plan_err = _new_opportunity_plan(args.plan_id)
    if plan_err or not plan_id:
        raise _Refused(plan_err or "no active search plan sources role/contract, so this role has no "
                       "plan_id; add one, or pass --plan <plan_id>.")
    base = _slug("%s-%s" % (company_id, title)) or _slug(company_id) or "role"
    opp_id, n = base, 1
    taken = {o.get("id") for o in opps}
    while opp_id in taken:
        n += 1
        opp_id = "%s-%d" % (base, n)
    new_opp = {"id": opp_id, "company_id": company_id, "title": title, "status": "backlog",
               "stage": "sourced", "verdict": "undecided", "jd_url": url,
               "location": {"declared": "none stated"}, "sightings": [sighting],
               # the candidate owns the pursue/pass decision; `your_move.classify_opportunities` holds the
               # role in `triaging` (system-owned) until the daily run's triage step has read it
               "next_action_owner": _profile_mod().owner_token(),
               "plan_id": plan_id, "plan_assigned_on": datetime.date.today().isoformat()}
    return {"company_id": company_id, "new_company": new_company, "company_how": company_how,
            "opp_id": opp_id, "new_opp": new_opp, "sighting": None, "noop": False,
            "role_how": "created"}


def _apply_board_sighting(plan, companies, opps):
    """Apply `plan` to the lists `_board_sighting_plan` was planned against (in place)."""
    if plan["new_company"] is not None:
        companies.append(plan["new_company"])
    if plan["new_opp"] is not None:
        opps.append(plan["new_opp"])
    elif plan["sighting"] is not None:
        find(opps, plan["opp_id"]).setdefault("sightings", []).append(plan["sighting"])


def cmd_board_sighting(args):
    """`record.py board-sighting <channel_id> --company NAME --title TITLE --url POSTING_URL ...` -- dev #765
    (design-portfolio-boards.md section 4). Record ONE role the candidate saw on a job board.

    The company is matched, created or refused as ambiguous; the role either gets a sighting appended or is
    created in the 0.70.0 triaging shape (`backlog` / `sourced` / `undecided`, `jd_url` the posting's own
    address, `location.declared: none stated`, pay and posting date absent = NOT CAPTURED), so the
    daily run's triage reads it before the candidate is asked. A company created and a role created land in
    ONE locked, validated, rollback-verified write, or neither does. The firm link is not written: the
    sighting's `channel_id` is the board and the board's `portfolio_of` is the firm, derived by
    `portfolio_boards.backers_of`. This verb never fetches `--url`, and refuses one on a board host.
    A refusal leaves every store byte-identical."""
    label = "usage: " + BOARD_SIGHTING_USAGE
    if not args.rid or args.rest:
        print(label)
        return 2
    missing = [f for f, v in (("--title", args.title_text), ("--url", args.listing_url),
                              ("--company or --company-id", args.company_name or args.company_id_arg)) if not v]
    if missing:
        print("⛔ REFUSED — %s required.\n%s" % (", ".join(missing), label))
        return 2
    try:
        seen_on = _run_date_value(args.seen_on, "--seen-on")
    except _Refused as e:
        print("⛔ REFUSED — %s" % e)
        return 1
    try:
        channels, companies, opps = (_load_or_empty("channels"), load("companies"), load("opportunities"))
        applications = _load_or_empty("applications")
    except (OSError, ValueError) as e:
        print("⛔ REFUSED — a store cannot be read (%s); nothing written." % e)
        return 1
    shadow_co, shadow_op = json.loads(json.dumps(companies)), json.loads(json.dumps(opps))
    try:
        plan = _board_sighting_plan(args, channels, shadow_co, shadow_op, applications, seen_on)
    except _Refused as e:
        print("⛔ REFUSED — %s" % e)
        return 1
    summary = ("board-sighting %s: company %s (%s), role %s (%s)"
               % (args.rid, plan["company_id"], plan["company_how"], plan["opp_id"], plan["role_how"]))
    if plan["noop"]:
        print(summary)
        print("  nothing to change.")
        return 0
    _apply_board_sighting(plan, shadow_co, shadow_op)
    if args.dry_run:
        print(summary)
        row_after = find(shadow_op, plan["opp_id"])
        _bs_before = None if plan["new_opp"] is not None else find(opps, plan["opp_id"])
        introduced = (introduced_row_violations("opportunities", _bs_before, row_after)
                      + verb_owned_refusal("board-sighting", "opportunities", _bs_before, row_after))
        if introduced:
            print("  ⛔ a REAL (non-dry-run) write of this would be REFUSED (nothing is written):")
            print("  " + "\n  ".join("- " + m for m in introduced))
            return 1
        pre_rc, _, _, pre_problems = validate()
        rc, out, err, problems = dry_run_validate("opportunities", shadow_op, extra={"companies": shadow_co})
        added = new_problems(pre_problems, problems) if rc != 0 else []
        if rc != 0 and (added is None or added):
            print("  ⛔ a REAL (non-dry-run) write of this would be REFUSED and rolled back.")
            print("  " + "\n  ".join(added if added else _diagnostic_lines(rc, out, err)))
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
            take_lock("record.py board-sighting %s" % args.rid, wait=args.wait)
        except LockError as e:
            print("  REFUSED — %s" % e)
            return 1
    try:
        # re-read INSIDE the lock, and re-plan on what is really there
        channels, companies, opps = (_load_or_empty("channels"), load("companies"), load("opportunities"))
        applications = _load_or_empty("applications")
        try:
            plan = _board_sighting_plan(args, channels, companies, opps, applications, seen_on)
        except _Refused as e:
            print("⛔ REFUSED — %s" % e)
            return 1
        if plan["noop"]:
            print(summary)
            print("  nothing to change.")
            return 0
        before_row = None if plan["new_opp"] is not None else json.loads(json.dumps(find(opps, plan["opp_id"])))
        _apply_board_sighting(plan, companies, opps)
        introduced = (introduced_row_violations("opportunities", before_row, find(opps, plan["opp_id"]))
                      + verb_owned_refusal("board-sighting", "opportunities", before_row, find(opps, plan["opp_id"])))
        if introduced:
            print("⛔ REFUSED — " + "; ".join(introduced))
            return 1
        snap_c, snap_o = snapshot("companies"), snapshot("opportunities")
        pre_problems = validate()[3]
        if plan["new_company"] is not None:
            save_atomic("companies", companies)
        save_atomic("opportunities", opps)
        rc, out, err, post_problems = validate()
        added = new_problems(pre_problems, post_problems)
        if rc != 0 and (added is None or added):
            ok_o = restore("opportunities", snap_o)
            ok_c = restore("companies", snap_c) if plan["new_company"] is not None else True
            print("⛔ the write left the stores invalid and was %s."
                  % ("ROLLED BACK (byte-identical)" if ok_o and ok_c
                     else "NOT VERIFIABLY ROLLED BACK — restore companies.jsonl and opportunities.jsonl "
                          "from git"))
            print("  " + "\n  ".join(added if added else _diagnostic_lines(rc, out, err)))
            return 1
    finally:
        if not args.already_locked:
            release_lock()
    print(summary)
    import portfolio_boards as _pb
    firms = _pb.backers_of(plan["company_id"], companies, channels, opps)
    print("  backed by: %s" % (", ".join("%s (%s)" % (f["firm_id"], f["via"]) for f in firms)
                               if firms else "no firm is linked (this board is not a portfolio board, or "
                                             "no backing is stated)"))
    return 0
