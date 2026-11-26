"""release: when the owner's criteria let a role go from the company question (jobsearch 0.94.0, step P2; dev 1062;
docs/design-role-first.md 3.2, 3.3, 3.5, RF1 to RF5, RF10).

A role at a company that is not a stated target is held (`held-for-company`) in 0.93.0. From 0.94.0 the owner's own criteria decide, through
`reach.first_look`, for a profile that carries the 0.94.0 pin. `verdict` is the whole table of design 3.2, over three facts the caller
already has: why the company holds its roles (`admission.hold.company_hold`), whether the company is one a pursue made
(`admission.hold.pursued_company`) and, only when the pin is present, the role's `Look` (a callable, asked at most once and only when the table
needs it). Without the pin `look` is None and the answer is exactly 0.93.0's: hold with the company's reason, or nothing (RF4).

  active target (stated)                       not consulted: every role is taken on, as in 0.93.0
  active target a pursue made, no motivation   `match` as a target; otherwise held, detail `pursued`, cause the clause
  undecided or watched                         `match` RELEASED (the role waits for intake, detail `criteria`); otherwise held as before,
                                               cause the clause (`criteria` when the look could not be computed: loud, never a pass)
  passed                                       held, detail `passed`; the cause says whether it would have matched (`match`), so the count of
                                               matches the owner's refusal hid is never lost (OD-2)

`after` is the other half of RF5: a released role's earlier admissions were planned under the company hold, when no run could have read it
on purpose, so those at or before the release instant do not count, and a miss AFTER the instant is a failure as for any role.

`pin_instant` is the release instant: the earliest `profile-schema` event whose `min_engine` is at or above 0.94.0, the same answer as
`journaling.pins.earliest_pin_at` (a test pins the two equal). It is read here and not imported from there because `lifecycle` importing the
`journaling` package would grow the plugin's largest import cycle (G6, 39 to 40).

Pure: no I/O, no clock. Python 3.9+, standard library only."""

import datetime
import re

RELEASE, HOLD = "release", "hold"
PIN_EVENT = "profile-schema"
PIN_VERSION = (0, 94, 0)
_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
MATCHED = "match"                    # a held role's `cause` when its company was passed and the role meets the criteria


def verdict(why, pursued, look):
    """`(action, detail, cause)`, or None when the company does not touch the role's stage. `action` is RELEASE or HOLD; `detail` is the
    stage's detail (`criteria` for a release, else the held why); `cause` the first criterion failed, or None. `why` is
    `company_hold`'s answer, `pursued` a bool, `look` a callable returning a `first_look.Look`, or None without the 0.94.0 pin."""
    if look is None:
        return (HOLD, why, None) if why else None
    if why is None and not pursued:
        return None
    lk = look()
    if why == "passed":
        return HOLD, why, (MATCHED if lk.state == "match" else lk.clause)
    if why is None:                                        # a company a pursue made: only a role that matches is taken on
        return None if lk.state == "match" else (HOLD, "pursued", lk.clause)
    if lk.state == "match":
        return RELEASE, "criteria", None
    return HOLD, why, lk.clause


def pin_instant(recs):
    """The release instant (design 3.3): the earliest `at` among the `profile-schema` events of `recs` (the run journal's rows) whose
    `min_engine` is `X.Y.Z` at or above 0.94.0, as a naive `datetime`; None when the profile has no such pin, which turns every rule of this
    release off (RF4). A pin whose `at` is not an ISO date and time contributes no instant, and one whose `min_engine` is not `X.Y.Z` is no pin."""
    best = None
    for r in recs or ():
        if not isinstance(r, dict) or r.get("event") != PIN_EVENT:
            continue
        m = _VERSION.match(r["min_engine"]) if isinstance(r.get("min_engine"), str) else None
        try:
            at = datetime.datetime.fromisoformat(r["at"]).replace(tzinfo=None) if isinstance(r.get("at"), str) else None
        except ValueError:
            at = None
        if m and at is not None and tuple(int(g) for g in m.groups()) >= PIN_VERSION and (best is None or at < best):
            best = at
    return best


def after(adm, planned_at, instant):
    """The admissions of `adm` (run ids, oldest first) planned AFTER `instant`; one planned at or before it does not count. `planned_at` is
    `{run id: datetime}`; a run whose plan time is unknown, or cannot be compared with the instant, counts."""
    kept = []
    for rid in adm:
        planned = planned_at.get(rid)
        try:
            before = planned is not None and planned <= instant
        except TypeError:
            before = False
        if not before:
            kept.append(rid)
    return kept
