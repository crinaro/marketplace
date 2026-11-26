"""q_verdict: each ROLE line's `q=` judged against the block's QUERY lines (jobsearch 0.94.0, step P0; dev 1055, 1064, 1065;
docs/design-role-first.md section 13). Moved out of `deferred.parse_roles`, which calls here once every line of the ROLES block has
been read. No behaviour change.

`vet_roles(roles, qord, ordinals, lines, fault, evidence=None)` takes the parsed ROLE entries, `qord` (how many QUERY lines the block has),
`ordinals` (`{ordinal: parsed query}`, an unparsed QUERY line has none), the block's text lines and `fault(line number, text,
rule)` (the parser's own recorder of a LINE fault). It returns the ROLE entries that stay, each with `quarantine_codes` set. With
`evidence` (a `card_evidence.Evidence`, given on a profile pinned at 0.94.0, dev 1055) the hold is `evidence.verdict`: a degradation holds a
role only where its own card does not answer it. Without it, 0.93.0's rule: held when every query that showed it is degraded.

Pure but for `fault`. It imports no entry point (G5). Python 3.9+, standard library only."""


def vet_roles(roles, qord, ordinals, lines, fault, evidence=None):
    """The ROLE entries that survive the `q=` check, in order. A `ROLE nourl` entry passes as it is. A ROLE whose `q=` names an
    ordinal out of range, or an UNREACHABLE query (it showed no roles), is a line fault and is dropped. One naming a QUERY line
    that did not parse is allowed and counts as DEGRADED (`query-unparsed`), so a broken line can never make its roles look
    clean. A role is QUARANTINED when EVERY query that showed it is degraded: `quarantine_codes` is the sorted union of those
    queries' codes then, else None."""
    # dev #722 / public #156 -- each ROLE url line's q= is judged against the block's QUERY lines
    # now that all of them have been seen: an ordinal out of range or naming an UNREACHABLE query
    # (it showed no roles) is a line fault for that ROLE; one naming a QUERY line that did not
    # parse is allowed and counts as DEGRADED (`query-unparsed`), so a broken line can never make
    # its roles look clean. A role is QUARANTINED when EVERY query that showed it is degraded.
    vetted = []
    for r in roles:
        if r["url"] is None:
            vetted.append(r)
            continue
        bad = None
        for k in r["q"]:
            if k > qord:
                bad = "q=%d is out of range: the block has %d QUERY line(s)" % (k, qord)
            elif k in ordinals and ordinals[k]["status"] == "unreachable":
                bad = "q=%d names an unreachable QUERY, which showed no roles" % k
            if bad:
                break
        if bad:
            fault(r["line"], lines[r["line"] - 1], bad)
            continue
        if evidence is not None:                                    # 0.94.0: the card answers what it can (card_evidence.py)
            r["quarantine_codes"] = evidence.verdict(r, ordinals)
            vetted.append(r)
            continue
        codes, all_degraded = set(), True
        for k in r["q"]:
            q = ordinals.get(k)
            if q is None:
                codes.add("query-unparsed")
            elif q["degraded"]:
                codes.update(q["degraded"])
            else:
                all_degraded = False
        r["quarantine_codes"] = sorted(codes) if all_degraded else None
        vetted.append(r)
    return vetted
