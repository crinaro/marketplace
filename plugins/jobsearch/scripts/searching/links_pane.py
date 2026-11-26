"""links_pane: the `LINKS` and `PANE` lines of a ROLES block (jobsearch 0.94.0, dev 1064, 1065; docs/design-role-first.md 7.4, 8.1, 19.3 N13; criteria HD1, HD2, HD8).

Capability module of `deferred.parse_roles` (which hands each line it does not know to `parse`) and `deferred.add_roles` (which stores what `fold` and the PANE line give on the `roles` event).

  LINKS <matched=<m> unmatched=<k>|NO-IDS cards=<n>|NOT-LOADED|READ-ERROR|PARTIAL cards=<n> ids=<m>>
      One per results page the pass ran the link reader on (`browser_fallback/link_read.py`'s verdict, pasted, never composed). `fold` counts them as the `roles` event's `links`:
      `matched` and `unmatched` add up the ROLES of every page, the other four count PAGES. A pass that ran no link reader has no LINKS line and stores none: "no link read" is
      absent, never "a page with no links" (design 7.4).
  PANE state=<displayed|hidden|unknown|not-pane> mode=<normal|hidden>
      Once, the Browser pane's state when the pass started and the mode it ran in (the reply sweep's own line, `linkedin_sweep.PANE_LINE_STATES`). Stored as the event's `pane` and
      `mode`; a block with none stores `unreported` for both, so the hidden-pane escalation (design 8.2) can tell "not said" from "shown". A `hidden` pane runs in hidden mode: a line that
      says otherwise is a line fault, as `search_rows.check_roles_new_fields` would refuse it.

Both lines are for the `linkedin-jobsearch` surface only; on `board` each is a line fault. A line that matches neither form is not this module's (`parse` returns None).

Python 3.9+, standard library only."""

import re

SURFACE = "linkedin-jobsearch"
UNREPORTED = "unreported"
_LINKS = re.compile(r"^LINKS (?:matched=(?P<m>\d+) unmatched=(?P<k>\d+)|NO-IDS cards=(?P<n>\d+)|(?P<nl>NOT-LOADED)|(?P<re>READ-ERROR)|PARTIAL cards=(?P<c>\d+) ids=(?P<i>\d+))$")
_PANE = re.compile(r"^PANE state=(?P<state>displayed|hidden|unknown|not-pane) mode=(?P<mode>normal|hidden)$")
_WORDS = ("LINKS", "PANE")


def parse(raw, surface, pane_seen=False):
    """None when `raw` is not a LINKS or PANE line (the caller's other rules apply). Else `{"kind": "links", "counts": {...}}`, `{"kind": "pane", "state", "mode"}` or
    `{"kind": "fault", "rule"}`: a line that starts like one and breaks its form, a second PANE line (`pane_seen`), either line off the LinkedIn surface, or a hidden pane whose mode is not hidden."""
    word = raw.split(" ", 1)[0]
    if word not in _WORDS:
        return None
    if surface != SURFACE:
        return {"kind": "fault", "rule": "a %s line is for the linkedin-jobsearch surface only" % word}
    if word == "PANE":
        m = _PANE.match(raw)
        if not m:
            return {"kind": "fault", "rule": "not a PANE line: PANE state=<displayed|hidden|unknown|not-pane> mode=<normal|hidden>"}
        if pane_seen:
            return {"kind": "fault", "rule": "a second PANE line (the first one counts)"}
        return {"kind": "pane", "state": m.group("state"), "mode": m.group("mode")}
    m = _LINKS.match(raw)
    if not m:
        return {"kind": "fault", "rule": "not a LINKS line: LINKS matched=<m> unmatched=<k> | NO-IDS cards=<n> | NOT-LOADED | READ-ERROR | PARTIAL cards=<n> ids=<m>"}
    if m.group("m") is not None:
        counts = {"matched": int(m.group("m")), "unmatched": int(m.group("k"))}
    elif m.group("n") is not None:
        counts = {"no-ids": 1}
    elif m.group("nl"):
        counts = {"not-loaded": 1}
    elif m.group("re"):
        counts = {"read-error": 1}
    else:
        counts = {"partial": 1}
    return {"kind": "links", "counts": counts}


def pane_fields(pane):
    """`{"pane", "mode"}` for the `roles` event: the PANE line's own, or `unreported` for both when the block had none."""
    state, mode = pane if pane else (UNREPORTED, UNREPORTED)
    return {"pane": state, "mode": mode}


def fold(all_counts):
    """`{verdict: count}` over a block's LINKS lines (`parse`'s `counts`, in order), or None when it had none."""
    if not all_counts:
        return None
    out = {}
    for counts in all_counts:
        for k, v in counts.items():
            out[k] = out.get(k, 0) + v
    return out
