"""Cross-store link checks: location provenance, sibling links, `passed_from`, feeds, portfolio boards and channel
catalog fields.

Capability module of `validate_data.py` (S4a, moved unedited)."""

from validation.pay import PROVENANCES, _real_date, _unknown_keys
from validation.vocab import LOC_TYPES, OPP_STATUS, STAGES, TERMINAL_OPP_STATUSES


def check_location_provenance(loc, label, problems):
    """The two optional `location` keys jobsearch 0.70.0 added (dev #727 / public #159, design R3:
    keys INSIDE `location` are validated here only -- `record.py check_field` guards top-level and
    array fields).

      setting_source          `"inferred"` -- the capture script inferred `onsite` because the
                              sweep read no setting (`declared == "none stated"`) at a concrete place.
                              Absent means the setting was STATED. Only with `type: onsite`, only
                              with `declared: "none stated"`, never with `inference_overturned`.
      inference_overturned    `{was, to, on}` -- written by the overturn of an inferred setting
                              (`record.py set <id> location '<json>'`): `was` is `onsite`, `to` a
                              location type, `on` an ISO date. Absent means never overturned.
    """
    if not isinstance(loc, dict):
        return
    # dev #820 / public #175 (design section 3.1): where the location facts came from, and whether a CARD's
    # place only echoed a commute anchor's (which proves nothing about the role).
    if "provenance" in loc and loc["provenance"] not in PROVENANCES:
        problems.append("%s: location.provenance %r not in {%s}"
                        % (label, loc["provenance"], ", ".join(PROVENANCES)))
    if "anchor_echo" in loc:
        if loc["anchor_echo"] is not True:
            problems.append("%s: location.anchor_echo must be true when present -- %r"
                            % (label, loc["anchor_echo"]))
        elif loc.get("provenance") != "card":
            problems.append("%s: location.anchor_echo is legal only with provenance 'card' (a read of "
                            "the JD or by the candidate is not an echo) -- provenance is %r"
                            % (label, loc.get("provenance")))
    if loc.get("provenance") == "card" and loc.get("setting_source") == "inferred":
        problems.append("%s: a card never infers a setting: location.provenance 'card' with "
                        "setting_source 'inferred' (design section 3.1)" % label)
    if "setting_source" in loc:
        if loc["setting_source"] != "inferred":
            problems.append("%s: location.setting_source must be 'inferred' (absent means the "
                            "setting was stated) -- %r" % (label, loc["setting_source"]))
        elif loc.get("type") != "onsite":
            problems.append("%s: location.setting_source 'inferred' with type %r -- only an "
                            "inferred ONSITE exists; an overturn removes the flag"
                            % (label, loc.get("type")))
        if loc.get("declared") != "none stated":
            problems.append("%s: location.setting_source 'inferred' needs location.declared == "
                            "'none stated' (the sweep read no setting); got %r"
                            % (label, loc.get("declared")))
        if "inference_overturned" in loc:
            problems.append("%s: location.setting_source and location.inference_overturned are both "
                            "present -- an overturned inference no longer carries the flag" % label)
    if "inference_overturned" in loc:
        io = loc["inference_overturned"]
        if not isinstance(io, dict) or set(io) != {"was", "to", "on"}:
            problems.append("%s: location.inference_overturned must be exactly {was, to, on} -- %r"
                            % (label, io))
            return
        if io["was"] != "onsite":
            problems.append("%s: location.inference_overturned.was must be 'onsite' (the only "
                            "setting the script infers) -- %r" % (label, io["was"]))
        if io["to"] not in LOC_TYPES:
            problems.append("%s: location.inference_overturned.to %r not in {%s}"
                            % (label, io["to"], ", ".join(sorted(LOC_TYPES))))
        if not _real_date(io["on"]):
            problems.append("%s: location.inference_overturned.on not an ISO date -- %r"
                            % (label, io["on"]))


def check_sibling_links(r, label, ids, by_id, problems):
    """The three optional fields jobsearch 0.70.0 added for one requisition listed at several places
    (dev #728 / public #158, design-location-screen.md §5 and R3). Each is optional and ABSENT has a
    defined meaning, so only a PRESENT value is checked.

      duplicate_of          an opportunity id: this row was FOLDED into that one by hand
                            (`record.py link-sibling`). It resolves, is not itself, and the target is
                            not folded (a chain would hide the canonical row). A folded row carries
                            no decision and no application: it stands for a listing the canonical row
                            now lists.
      distinct_from         a list of opportunity ids this row was recorded as DIFFERENT from (a false
                            merge undone, or a `create --force` over a match): each resolves and none
                            is itself. The matching rule never re-merges a named pair.
      sightings[].location  a non-empty string: where that listing placed the role, verbatim.
      sightings[].split_to  an opportunity id: this listing was split away to that row (the undo of a
                            false merge); it resolves and is not this row.
    """
    oid = r.get("id")
    if "duplicate_of" in r:
        d = r["duplicate_of"]
        if not isinstance(d, str) or not d.strip():
            problems.append("%s: duplicate_of must be an opportunity id -- %r" % (label, d))
        elif d == oid:
            problems.append("%s: duplicate_of names the row itself" % label)
        elif d not in ids:
            problems.append("%s: duplicate_of %r does not resolve to an opportunity" % (label, d))
        elif by_id.get(d, {}).get("duplicate_of"):
            problems.append("%s: duplicate_of %r is itself folded into %r -- point at the canonical "
                            "row, never a chain" % (label, d, by_id[d]["duplicate_of"]))
        if r.get("verdict") not in (None, "undecided"):
            problems.append("%s: a folded row (duplicate_of) carries no decision, but its verdict is "
                            "%r -- decide the canonical row" % (label, r.get("verdict")))
    if "distinct_from" in r:
        df = r["distinct_from"]
        if not isinstance(df, list) or not all(isinstance(x, str) and x.strip() for x in df):
            problems.append("%s: distinct_from must be a list of opportunity ids -- %r" % (label, df))
        else:
            for x in df:
                if x == oid:
                    problems.append("%s: distinct_from names the row itself" % label)
                elif x not in ids:
                    problems.append("%s: distinct_from %r does not resolve to an opportunity"
                                    % (label, x))
    for i, sg in enumerate(r.get("sightings") or []):
        if not isinstance(sg, dict):
            continue
        if "location" in sg and not (isinstance(sg["location"], str) and sg["location"].strip()):
            problems.append("%s: sighting[%d].location must be a non-empty string -- %r"
                            % (label, i, sg["location"]))
        if "split_to" in sg:
            st = sg["split_to"]
            if not isinstance(st, str) or not st.strip():
                problems.append("%s: sighting[%d].split_to must be an opportunity id -- %r"
                                % (label, i, st))
            elif st == oid:
                problems.append("%s: sighting[%d].split_to names the row itself" % (label, i))
            elif st not in ids:
                problems.append("%s: sighting[%d].split_to %r does not resolve to an opportunity"
                                % (label, i, st))


def check_passed_from(r, label, problems):
    """`passed_from` (dev #722 / public #156, §5): `{status, stage}` -- where a `decide pass` found
    the role, kept so a later `decide pursue|park` can restore it. It exists ONLY on a role whose
    `status` is `passed` (a restored or never-passed row must not carry a stale way back), its
    `status` must be a NON-terminal opportunity status and its `stage` one of the stages."""
    pf = r["passed_from"]
    if r.get("status") != "passed":
        problems.append("%s: passed_from on a role whose status is %r -- it belongs only to "
                        "status 'passed' (a restore removes it)" % (label, r.get("status")))
    if not isinstance(pf, dict):
        problems.append("%s: passed_from must be an object (status, stage) -- got %s"
                        % (label, type(pf).__name__))
        return
    _unknown_keys(pf, ("status", "stage"), label + " passed_from", problems)
    if pf.get("status") not in OPP_STATUS or pf.get("status") in TERMINAL_OPP_STATUSES:
        problems.append("%s: passed_from.status %r must be a non-terminal status in {%s}"
                        % (label, pf.get("status"),
                           ", ".join(sorted(OPP_STATUS - TERMINAL_OPP_STATUSES))))
    if pf.get("stage") not in STAGES:
        problems.append("%s: passed_from.stage %r not in {%s}"
                        % (label, pf.get("stage"), ", ".join(sorted(STAGES))))


WARM_LOOKUP_RESULT = "none-found"


def check_feed_links(companies, channels):
    """dev #751 (design §3.1) -- the join between a company and its career-page channel, and the
    three invariants that keep a feed writable. Returns a list of problems.

      * `channels[].company_id` is legal ONLY on `type: company-site`, and must resolve to a company;
      * at most ONE company-site channel per `company_id`;
      * every company whose `ats` is an OBJECT has exactly ONE linked company-site channel (a feed
        sighting's `channel_id` must resolve, and `route.py` / `channels_due.py` key on the link).

    A company with `ats: null` (declined) or no `ats` needs no channel."""
    problems = []
    by_id = {c.get("id"): c for c in companies}
    linked = {}
    for ch in channels:
        if "company_id" not in ch:
            continue
        label = "channels[%s]" % ch.get("id", "?")
        cid = ch.get("company_id")
        if ch.get("type") != "company-site":
            problems.append("%s: company_id is legal only on type 'company-site' (this one is %r)"
                            % (label, ch.get("type")))
            continue
        if not isinstance(cid, str) or cid not in by_id:
            problems.append("%s: company_id %r does not resolve to a company" % (label, cid))
            continue
        linked.setdefault(cid, []).append(ch.get("id"))
    for cid, ids in sorted(linked.items()):
        if len(ids) > 1:
            problems.append("companies[%s]: %d company-site channels link to it (%s); a company has "
                            "at most one career-page channel" % (cid, len(ids), ", ".join(map(str, ids))))
    for c in companies:
        if isinstance(c.get("ats"), dict) and len(linked.get(c.get("id"), [])) != 1:
            problems.append("companies[%s]: has an `ats` feed but %d linked company-site channel(s) "
                            "(exactly one is required: a feed's sightings are written to it)"
                            % (c.get("id", "?"), len(linked.get(c.get("id"), []))))
    return problems


PORTFOLIO_CALENDAR_CADENCES = ("daily", "weekly", "biweekly", "monthly")


def check_portfolio_links(companies, channels):
    """dev #765 (design-portfolio-boards.md section 3.4, with the review's B1) -- the three optional fields a
    portfolio board adds, and the rules that keep them readable. Returns a list of problems. Both
    `channels[].portfolio_of` and `companies[].backed_by` may be absent (every pre-0.75.0 row is valid).

      P1  `portfolio_of`  absent, or a non-empty string
      P2                  an id present in `companies`
      P3                  only on `type: job-board` AND `access: manual-candidate` (ADR-037's line as a
                          check: a `public` or `login` portfolio board would route to a browser and
                          automate a site whose terms forbid it)
      P4                  needs a calendar `review_cadence` (daily, weekly, biweekly, monthly): the board is
                          COVERED only while the candidate's review is inside its cadence, so a board with no
                          calendar could never be covered
      P5                  needs `board_hosts` (the hosts the engine must never open, see board_hosts.py)
      H1  `board_hosts`   absent, or a non-empty list of distinct bare host names
      H2                  only on a channel whose `access` is `manual-candidate`
      B1  `backed_by`     absent, or a non-empty list of non-empty strings (a bare string iterates character
                          by character, the `aliases` lesson)
      B2                  each id resolves in `companies`, none is the row's own id, no repeats

    Not checked on purpose: chains or cycles (A backed by B, B backed by A). Nothing reads `backers_of`
    transitively, so a cycle has no consequence to guard."""
    import board_hosts as _bh
    problems = []
    ids = {c.get("id") for c in companies}
    for ch in channels:
        label = "channels[%s]" % ch.get("id", "?")
        if "board_hosts" in ch:
            hosts = ch["board_hosts"]
            if not (isinstance(hosts, list) and hosts and all(_bh.valid_host(h) for h in hosts)):
                problems.append("%s: board_hosts must be a non-empty list of bare lower-case host names "
                                "(e.g. [\"jobs.example.org\"], no scheme, path or port) -- %r"
                                % (label, hosts))
            elif len(set(hosts)) != len(hosts):
                problems.append("%s: board_hosts repeats a host -- %r" % (label, hosts))
            if ch.get("access") != _bh.MANUAL_ACCESS:
                problems.append("%s: board_hosts is legal only where access is 'manual-candidate' (this one "
                                "is %r): it names the sites the engine must never open"
                                % (label, ch.get("access")))
        if "portfolio_of" not in ch:
            continue
        firm = ch["portfolio_of"]
        if not (isinstance(firm, str) and firm.strip()):
            problems.append("%s: portfolio_of must be a non-empty company id -- %r" % (label, firm))
        elif firm not in ids:
            problems.append("%s: portfolio_of %r does not resolve to a company (create the firm's company "
                            "row first)" % (label, firm))
        if ch.get("type") != "job-board" or ch.get("access") != "manual-candidate":
            problems.append("%s: portfolio_of is legal only on type 'job-board' with access 'manual-candidate' "
                            "(this one is %r / %r): a portfolio board's terms forbid automated access "
                            "(ADR-037)" % (label, ch.get("type"), ch.get("access")))
        if ch.get("review_cadence") not in PORTFOLIO_CALENDAR_CADENCES:
            problems.append("%s: a portfolio board needs a calendar review_cadence (%s), got %r: it is covered "
                            "only while your review is inside its cadence"
                            % (label, ", ".join(PORTFOLIO_CALENDAR_CADENCES), ch.get("review_cadence")))
        if "board_hosts" not in ch:
            problems.append("%s: a portfolio board needs board_hosts: the host(s) of the board, which the "
                            "engine must never open" % label)
    for c in companies:
        if "backed_by" not in c:
            continue
        label = "companies[%s]" % c.get("id", "?")
        bb = c["backed_by"]
        if not (isinstance(bb, list) and bb and all(isinstance(b, str) and b.strip() for b in bb)):
            problems.append("%s: backed_by must be a non-empty list of company ids, e.g. [\"<firm-id>\"] -- "
                            "%r (fix: record.py set %s backed_by '[\"<firm-id>\"]' --file companies)"
                            % (label, bb, c.get("id", "?")))
            continue
        for b in bb:
            if b not in ids:
                problems.append("%s: backed_by %r does not resolve to a company" % (label, b))
            elif b == c.get("id"):
                problems.append("%s: backed_by names the company itself" % label)
        if len(set(bb)) != len(bb):
            problems.append("%s: backed_by repeats an id -- %r" % (label, bb))
    return problems


def check_channel_catalog_fields(channels):
    """dev #769 (design-channel-catalog.md section 4, jobsearch 0.76.0) -- the five optional channel fields the
    channel catalog adds, and the rules that keep them readable. Every pre-0.76.0 row is valid (all absent).

      C1  `board_url`   absent, or an `https` address with a host, no user-info and no port: the address the
                        candidate opens. Legal only where `access` is `manual-candidate` (the engine never opens
                        it), and it needs `board_hosts` covering its host, so a board the candidate is sent to
                        is a board the engine is forbidden to open
      C2  the stamp     `channel_catalog_entry` / `_sha` / `_on` / `_rev`: all four present or all four absent,
                        each well formed (`channel_catalog.stamp_problems` is the one definition)

      C3  `query_template` (dev #774) absent, or a non-empty string on a `job-board` / `aggregator` channel whose
                        placeholders are all in the closed vocabulary {titles} {geo} {seniority}
      C4  `prior_relationship_status` (dev #774, R2) absent, or exactly {"had": false} / {"had": true, "value":
                        <string|null>}: what `record.py source off` found, so `source on` can put it back. The strict
                        reader is `channel_catalog.read_prior`; the free-text `log` is never parsed for it

    Not checked on purpose: that the entry id names an entry in the CURRENT catalog. An entry the catalog no
    longer lists is a reconcile state (`orphaned`), not a data error, and this validator stays a function of the
    profile alone."""
    import board_hosts as _bh
    import channel_catalog as _cc
    from urllib.parse import urlsplit
    problems = []
    for ch in channels:
        label = "channels[%s]" % ch.get("id", "?")
        for why in _cc.stamp_problems(ch):
            problems.append("%s: %s" % (label, why))
        for why in _cc.prior_problems(ch):
            problems.append("%s: %s" % (label, why))
        if "query_template" in ch:
            qt = ch["query_template"]
            if ch.get("type") not in ("job-board", "aggregator"):
                problems.append("%s: query_template is legal only on a job-board or aggregator channel (this one is "
                                "%r)" % (label, ch.get("type")))
            elif not (isinstance(qt, str) and qt.strip()):
                problems.append("%s: query_template must be a non-empty string -- %r" % (label, qt))
            else:
                import re as _re
                bad = sorted({p for p in _re.findall(r"\{([^{}]*)\}", qt) if p not in ("titles", "geo", "seniority")})
                if bad:
                    problems.append("%s: query_template uses a placeholder outside {titles} {geo} {seniority}: %s"
                                    % (label, ", ".join(bad)))
        if "board_url" not in ch:
            continue
        url = ch["board_url"]
        host = None
        try:
            parts = urlsplit(url) if isinstance(url, str) else None
            if parts is not None and parts.scheme == "https" and parts.hostname:
                if not (parts.username or parts.password or parts.port):
                    host = parts.hostname.lower()
        except ValueError:
            host = None
        if host is None:
            problems.append("%s: board_url must be an https address with a host, no user-info and no port "
                            "-- %r" % (label, url))
            continue
        if ch.get("access") != _bh.MANUAL_ACCESS:
            problems.append("%s: board_url is legal only where access is 'manual-candidate' (this one is %r): "
                            "it is the address the candidate opens, on a site the engine must never open"
                            % (label, ch.get("access")))
        hosts = ch.get("board_hosts")
        if not (isinstance(hosts, list) and any(isinstance(h, str) and _bh.host_matches(host, h) for h in hosts)):
            problems.append("%s: board_url's host %r is not covered by board_hosts %r: the engine would be "
                            "free to open the address the candidate is sent to" % (label, host, hosts))
    return problems
