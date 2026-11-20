"""The `assessments` store's checks: proposal status and kind vocabularies, and the owner-prose rule.

Capability module of `validate_data.py` (S4a, moved unedited)."""

from validation.basics import enum, is_date


# ADR-031 B5 (design-b5-assessment.md §2) — `plans.assessments[]`, the weekly assessment's one
# stored row, and its `proposals[]`. The engine writes the dates, the window, the version and the
# proposals; `working`/`not_working`/`next_steps`/`note` are the owner's words only.
ASSESSMENT_PROPOSAL_STATUS = {"proposed", "accepted", "declined", "reported", "superseded"}
# The key decides the direction mechanically (design §27.2): a `parameter` proposal names a value
# the owner controls (a declared parameter of the plan's play, or a `config:<dotted>` key that
# config_keys registers); a `construct` proposal names `<signal>:<step|token>` with the signal in
# funnel_report.CONSTRUCT_SIGNALS — the shape is the engine's. There is no third kind.
ASSESSMENT_PROPOSAL_KINDS = {"parameter", "construct"}
ASSESSMENT_OWNER_PROSE = ("working", "not_working", "next_steps", "note")


def check_assessments(plan, play, model, label, problems):
    """`plans[<id>].assessments[]` — every check the row's own contract states, each a PROBLEM
    with the legal set named (the `enum()` shape, #73): entry key set and dates; proposal key
    set; `kind`/`status` enums; `key` shape BY KIND; `evidence` keys EXACTLY the kind's declared
    set (funnel_report.PROPOSAL_EVIDENCE_KEYS — an undeclared key is refused, never dropped,
    §28.2); `decided_on`/`decision` both-or-neither (the asks contract). Field lists come from
    docs/data_model.json (`model`) so this cannot drift from what record.py enforces; with the
    model unreadable the key-set half is skipped (the caller has already said the guard is OFF)
    and every other check still runs."""
    entries = plan.get("assessments")
    if entries is None:
        return
    if not isinstance(entries, list):
        problems.append("%s: assessments must be a list of entries — got %s"
                        % (label, type(entries).__name__))
        return
    import funnel_report as _fr                    # lazy: resolves the profile at import
    import config_keys as _ck
    spec = (((model or {}).get("stores") or {}).get("plans") or {}).get("arrays") or {}
    spec = spec.get("assessments") or {}
    entry_fields = set(spec.get("fields") or [])
    prop_fields = set((((spec.get("arrays") or {}).get("proposals") or {}).get("fields")) or [])
    declared = set(((play or {}).get("params") or {}).keys())
    for i, e in enumerate(entries):
        el = "%s.assessments[%d]" % (label, i)
        if not isinstance(e, dict):
            problems.append("%s: entry must be an object — got %s" % (el, type(e).__name__))
            continue
        if entry_fields:
            for k in sorted(set(e) - entry_fields):
                problems.append("%s: unknown key %r (known: %s)"
                                % (el, k, ", ".join(sorted(entry_fields))))
        for f in ("date", "as_of", "window_from"):
            v = e.get(f)
            if not is_date(v or ""):
                problems.append("%s: %s must be an ISO date — %r" % (el, f, v))
        if is_date(e.get("as_of") or "") and is_date(e.get("window_from") or "") \
                and e["window_from"] > e["as_of"]:
            problems.append("%s: window_from %s is after as_of %s — the window runs backwards"
                            % (el, e["window_from"], e["as_of"]))
        for f in ASSESSMENT_OWNER_PROSE + ("engine_version",):
            v = e.get(f)
            if v is not None and not isinstance(v, str):
                problems.append("%s: %s must be a string or null — %r" % (el, f, v))
        props = e.get("proposals")
        if not isinstance(props, list):
            problems.append("%s: proposals must be a list (empty is fine) — got %s"
                            % (el, type(props).__name__))
            continue
        seen_ids = set()
        for j, p in enumerate(props):
            pl = "%s.proposals[%d]" % (el, j)
            if not isinstance(p, dict):
                problems.append("%s: must be an object — got %s" % (pl, type(p).__name__))
                continue
            if prop_fields:
                for k in sorted(set(p) - prop_fields):
                    problems.append("%s: unknown key %r (known: %s)"
                                    % (pl, k, ", ".join(sorted(prop_fields))))
            pid = p.get("id")
            if not isinstance(pid, str) or not pid.strip():
                problems.append("%s: id must be a non-empty string (<plan>:<as_of>:<n>)" % pl)
            elif pid in seen_ids:
                problems.append("%s: duplicate proposal id %r within one entry" % (pl, pid))
            seen_ids.add(pid)
            enum(p, "kind", ASSESSMENT_PROPOSAL_KINDS, pl, problems)
            enum(p, "status", ASSESSMENT_PROPOSAL_STATUS, pl, problems)
            kind, key = p.get("kind"), p.get("key")
            if not isinstance(key, str) or not key:
                problems.append("%s: key must be a non-empty string" % pl)
            elif kind == "parameter":
                if key.startswith("config:"):
                    dotted = key[len("config:"):]
                    if dotted not in _ck.READER_KEYS:
                        problems.append("%s: key %r names a config key config_keys does not "
                                        "register (READER_KEYS: %s)"
                                        % (pl, key, ", ".join(sorted(_ck.READER_KEYS))))
                elif play is None:
                    problems.append("%s: key %r is a parameter name but the plan has no play "
                                    "that could declare it — a parameter proposal needs a "
                                    "resolving play or a config:<dotted> key" % (pl, key))
                elif key not in declared:
                    problems.append("%s: key %r is not a parameter play %r declares (declared: "
                                    "%s)" % (pl, key, play.get("id"),
                                             ", ".join(sorted(declared)) or "none"))
            elif kind == "construct":
                sig, _sep, ident = key.partition(":")
                if not _sep or not ident or sig not in _fr.CONSTRUCT_SIGNALS:
                    problems.append("%s: key %r must be <signal>:<step|token> with the signal "
                                    "in the closed catalogue {%s}"
                                    % (pl, key, ", ".join(_fr.CONSTRUCT_SIGNALS)))
            ev = p.get("evidence")
            if not isinstance(ev, dict):
                problems.append("%s: evidence must be an object" % pl)
            elif kind in _fr.PROPOSAL_EVIDENCE_KEYS:
                want = _fr.PROPOSAL_EVIDENCE_KEYS[kind]
                extra, missing = sorted(set(ev) - want), sorted(want - set(ev))
                if extra:
                    problems.append("%s: evidence key(s) %s not declared for kind %r — an "
                                    "undeclared key is refused, never dropped (declared: %s)"
                                    % (pl, ", ".join(extra), kind, ", ".join(sorted(want))))
                if missing:
                    problems.append("%s: evidence is missing declared key(s) %s for kind %r"
                                    % (pl, ", ".join(missing), kind))
            txt = p.get("text")
            if txt is not None and not isinstance(txt, str):
                problems.append("%s: text must be a string or null — %r" % (pl, txt))
            don, dec = p.get("decided_on"), p.get("decision")
            if (don is None) != (dec is None):
                problems.append("%s: decided_on and decision come together — one without the "
                                "other cannot be audited (the asks contract, copied)" % pl)
            if don is not None and not is_date(don):
                problems.append("%s: decided_on not ISO — %r" % (pl, don))
            if dec is not None and not isinstance(dec, str):
                problems.append("%s: decision must be a string or null — %r" % (pl, dec))
            rep = p.get("reported")
            if rep is not None and not isinstance(rep, str):
                problems.append("%s: reported must be a string (the issue url) or null — %r"
                                % (pl, rep))
