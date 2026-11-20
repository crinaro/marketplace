"""Screening, lean, JD-read, capture and likely-pass checks with their vocabularies (the JD-unavailable vocabulary and
check_jd_source stay in validate_data.py: its pattern is built by a call, work a package module may not do at import).

Capability module of `validate_data.py` (S4a, moved unedited)."""

import jd_read as _jd_read
import re
from validation.pay import PROVENANCES, _real_date, _unknown_keys


SCREEN_KEYS = ("on", "verdict", "rules", "engine", "title_keys", "setting_source", "comp_keys",
               "engagement_source", "inputs")
# dev #820 / public #175 (0.82.0, design section 3.2): which inputs a screen was computed from -- the
# capture CARD, the JD read, or the CANDIDATE's own read. Computed by `record.py screened`, never passed.
# Absent on a legacy screen, which `lifecycle` trusts only beside a `via: legacy` read.
SCREEN_INPUTS = PROVENANCES
# the stored verdict: `keep`, `provisional` (a card-input screen never keeps), `review:<rules>` or
# `remove:<rules>` with comma-separated lower-case rule names (comp, passed, geo, title, age).
SCREEN_VERDICT_RE = re.compile(r"^(keep|provisional|(review|remove):[a-z][a-z-]*(,[a-z][a-z-]*)*)$")
# dev #722 / public #156 (jobsearch 0.69.0): the title rule's tokens, a CLOSED set. 0.68.0 and earlier
# stored three; the floor and the mandate add BELOW-FLOOR and OFF-MANDATE, and an unreadable key is a
# visible UNREADABLE-TITLE-KEYS. A token outside the set is a stored screen nothing here can read.
SCREEN_TITLE_TOKENS = ("MATCHES", "NO-MATCH", "NO-CONFIGURED-TITLES", "BELOW-FLOOR", "OFF-MANDATE",
                       "UNREADABLE-TITLE-KEYS")

LEAN_KEYS = ("lean", "line", "on", "signals")
LEAN_VALUES = ("pursue", "pass", "ask")
LEAN_SIGNAL_KEYS = ("id", "reason", "matched_in")
SIGNAL_FIELDS = ("title", "jd", "company")
LEAN_LINE_CAP = 200                    # deferred.ROLES_FIELD_CAP, mirrored (that module reads a queue)


def check_screen(sc, label, problems):
    """`screen` (design §3.6, R5): `{on, verdict, rules, engine}` -- the screen's own output, written
    only by `record.py screened`. Structure only: the verdict vocabulary belongs to profile.py."""
    if not isinstance(sc, dict):
        problems.append("%s: screen must be an object (on, verdict, rules, engine) -- got %s"
                        % (label, type(sc).__name__))
        return
    _unknown_keys(sc, SCREEN_KEYS, label + " screen", problems)
    if not _real_date(sc.get("on")):
        problems.append("%s: screen.on not an ISO date -- %r" % (label, sc.get("on")))
    if not (isinstance(sc.get("verdict"), str) and sc["verdict"].strip()):
        problems.append("%s: screen.verdict must be a non-empty string" % label)
    elif not SCREEN_VERDICT_RE.match(sc["verdict"]):
        problems.append("%s: screen.verdict %r must be keep, provisional, review:<rules> or remove:<rules>"
                        % (label, sc["verdict"]))
    if "inputs" in sc and sc["inputs"] not in SCREEN_INPUTS:
        problems.append("%s: screen.inputs %r not in {%s}" % (label, sc["inputs"], ", ".join(SCREEN_INPUTS)))
    rules = sc.get("rules")
    if not isinstance(rules, dict) or not rules:
        problems.append("%s: screen.rules must be a non-empty object of rule -> result" % label)
    else:
        for k, v in rules.items():
            if not (isinstance(v, str) and v.strip()):
                problems.append("%s: screen.rules[%r] must be a non-empty string -- %r"
                                % (label, k, v))
    if not (isinstance(sc.get("engine"), str) and sc["engine"].strip()):
        problems.append("%s: screen.engine must name the engine version that screened" % label)
    if isinstance(rules, dict) and "title" in rules and isinstance(rules["title"], str) \
            and rules["title"].strip() and rules["title"] not in SCREEN_TITLE_TOKENS:
        problems.append("%s: screen.rules['title'] %r not in {%s}"
                        % (label, rules["title"], ", ".join(SCREEN_TITLE_TOKENS)))
    if "title_keys" in sc and not (isinstance(sc["title_keys"], str) and sc["title_keys"].strip()):
        problems.append("%s: screen.title_keys must be a non-empty string (the hash of the title "
                        "keys the screen was computed under) -- %r" % (label, sc["title_keys"]))
    if "setting_source" in sc and sc["setting_source"] != "inferred":
        problems.append("%s: screen.setting_source must be 'inferred' (it is present only when the "
                        "role was screened as onsite on an inference) -- %r"
                        % (label, sc["setting_source"]))
    # dev #739 / #740 (0.73.0): the sibling of title_keys, and the twin of setting_source.
    if "comp_keys" in sc and not (isinstance(sc["comp_keys"], str) and sc["comp_keys"].strip()):
        problems.append("%s: screen.comp_keys must be a non-empty string (the hash of the comp "
                        "inputs the screen was computed under) -- %r" % (label, sc["comp_keys"]))
    if "engagement_source" in sc and sc["engagement_source"] != "inferred":
        problems.append("%s: screen.engagement_source must be 'inferred' (it is present only when the "
                        "pay was routed on an engagement inferred from the title) -- %r"
                        % (label, sc["engagement_source"]))


def check_jd_read(value, label, problems):
    """`jd_read` (dev #820 / public #175, design section 4.2): the stored record of every JD read attempt,
    parsed by `jd_read.parse` -- the ONE parser, so what a verb may write and what the validator accepts
    cannot drift. Written only by `record.py read-jd`, `read-failed` and `read-batch` and by the 0.82.0
    migration (`via: legacy`). Appends one problem naming the attempt; a record with no attempt, an
    unknown outcome, empty evidence, a `render` read with no quote and a bad `at` are each refused."""
    try:
        _jd_read.parse(value)
    except _jd_read.JdReadError as e:
        problems.append("%s: jd_read: %s" % (label, e))


# the codes a degraded sweep query can carry, mirrored from `deferred.DEGRADED_CODES` (that module reads
# the work queue and cannot be imported here); a test pins the equality.
CAPTURE_UNVERIFIED_CODES = ("filter-dropped", "param-added", "window-unapplied", "truncated",
                            "query-unparsed")
CAPTURE_KEYS = ("run", "at", "item", "unverified")


def check_capture(cap, label, problems):
    """`capture` (dev #820 / public #175): `{run, at, item, unverified?}`, stamped by `record.py
    capture-batch` on a role it creates from a capture item. `run` is the run id, `at` an ISO date and
    time, `item` the queue item id the role was made from, and `unverified` (present only when the item
    was quarantined: every query that showed the role was degraded) a non-empty list of distinct codes
    from `deferred.DEGRADED_CODES`. `lifecycle` reads `item` to find the role's admission."""
    if not isinstance(cap, dict):
        problems.append("%s: capture must be an object (run, at, item, unverified?) -- got %s"
                        % (label, type(cap).__name__))
        return
    _unknown_keys(cap, CAPTURE_KEYS, label + " capture", problems)
    for k in ("run", "item"):
        v = cap.get(k)
        if not (isinstance(v, str) and v.strip() and not re.search(r"\s", v)):
            problems.append("%s: capture.%s must be a non-empty string without whitespace -- %r"
                            % (label, k, v))
    at = cap.get("at")
    try:
        _jd_read.parse_at(at)
    except _jd_read.JdReadError:
        problems.append("%s: capture.at must be YYYY-MM-DDTHH:MM:SS -- %r" % (label, at))
    if "unverified" in cap:
        u = cap["unverified"]
        if (not isinstance(u, list) or not u or len(set(map(str, u))) != len(u)
                or any(c not in CAPTURE_UNVERIFIED_CODES for c in u)):
            problems.append("%s: capture.unverified must be a non-empty list of distinct codes from {%s} "
                            "-- %r" % (label, ", ".join(CAPTURE_UNVERIFIED_CODES), u))


def check_lean(ln, label, problems):
    """`lean` (design §3.7): `{lean, line, on, signals?}`. The line is required, non-empty, ONE
    line and capped; each signal carries the `reason` it matched for -- a signal without one is a
    flag nobody can read."""
    if not isinstance(ln, dict):
        problems.append("%s: lean must be an object (lean, line, on, signals) -- got %s"
                        % (label, type(ln).__name__))
        return
    _unknown_keys(ln, LEAN_KEYS, label + " lean", problems)
    if ln.get("lean") not in LEAN_VALUES:
        problems.append("%s: lean.lean %r not in {%s}" % (label, ln.get("lean"),
                                                           ", ".join(LEAN_VALUES)))
    line = ln.get("line")
    if not (isinstance(line, str) and line.strip()):
        problems.append("%s: lean.line must be a non-empty string -- the one line that says why"
                        % label)
    elif "\n" in line or "\r" in line:
        problems.append("%s: lean.line must be ONE line (no line breaks)" % label)
    elif len(line) > LEAN_LINE_CAP:
        problems.append("%s: lean.line is %d characters; the cap is %d"
                        % (label, len(line), LEAN_LINE_CAP))
    if not _real_date(ln.get("on")):
        problems.append("%s: lean.on not an ISO date -- %r" % (label, ln.get("on")))
    sigs = ln.get("signals")
    if sigs is None:
        return
    if not isinstance(sigs, list):
        problems.append("%s: lean.signals must be a list" % label)
        return
    for i, sg in enumerate(sigs):
        sl = "%s lean.signals[%d]" % (label, i)
        if not isinstance(sg, dict):
            problems.append("%s: must be an object (id, reason, matched_in)" % sl)
            continue
        _unknown_keys(sg, LEAN_SIGNAL_KEYS, sl, problems)
        if not (isinstance(sg.get("id"), str) and sg["id"].strip()):
            problems.append("%s: id must be a non-empty string" % sl)
        if not (isinstance(sg.get("reason"), str) and sg["reason"].strip()):
            problems.append("%s: a signal without a reason -- a lean the candidate cannot read "
                            "is a flag, not a lean" % sl)
        if sg.get("matched_in") not in SIGNAL_FIELDS:
            problems.append("%s: matched_in %r not in {%s}" % (sl, sg.get("matched_in"),
                                                                ", ".join(SIGNAL_FIELDS)))


def check_likely_pass_signals(signals, problems):
    """`screen.likely_pass_signals` of `config.json` (design §3.8, §9): `[{id, phrase, fields,
    reason}]`. A signal without a `reason` is refused (a lean the candidate cannot read), as is a
    duplicate id, an empty phrase and a field outside title / jd / company. Returns the count."""
    if signals is None:
        return 0
    if not isinstance(signals, list):
        problems.append("config screen.likely_pass_signals must be a list of {id, phrase, fields, "
                        "reason}")
        return 0
    seen = set()
    for i, sg in enumerate(signals):
        sl = "config screen.likely_pass_signals[%d]" % i
        if not isinstance(sg, dict):
            problems.append("%s: must be an object {id, phrase, fields, reason}" % sl)
            continue
        _unknown_keys(sg, ("id", "phrase", "fields", "reason"), sl, problems)
        sid = sg.get("id")
        if not (isinstance(sid, str) and sid.strip()):
            problems.append("%s: id must be a non-empty string" % sl)
        elif sid in seen:
            problems.append("%s: duplicate id %r" % (sl, sid))
        seen.add(sid)
        if not (isinstance(sg.get("phrase"), str) and sg["phrase"].strip()):
            problems.append("%s: phrase must be a non-empty string" % sl)
        if not (isinstance(sg.get("reason"), str) and sg["reason"].strip()):
            problems.append("%s: a signal without a reason -- the lean it produces would be "
                            "unreadable" % sl)
        flds = sg.get("fields")
        if not isinstance(flds, list) or not flds or any(f not in SIGNAL_FIELDS for f in flds):
            problems.append("%s: fields must be a non-empty list drawn from {%s}"
                            % (sl, ", ".join(SIGNAL_FIELDS)))
    return len(signals)
