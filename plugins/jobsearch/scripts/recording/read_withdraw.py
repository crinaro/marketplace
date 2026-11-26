"""read_withdraw: take back a read that was wrong, as a compensating attempt (jobsearch 0.94.0, dev 1063; docs/design-role-first.md 6.2, 6.3).

ONE function, three callers: `record.py read-withdraw` (`withdraw_write.cmd_read_withdraw`), the same-write contradiction of `read-failed --via render` (6.2,
`reads._jd_read_mutation`) and the 0.94.0 migration (P7, `withdraw_write.write_withdrawals`, a batch: one validation and one save over many roles). This module is the
pure part: it changes ONE row in memory and says what it did. It reads no store, takes no lock and writes nothing.

`withdraw_in_row(row, at, why, run, now_iso, rescreen)`:

  * appends `{outcome: withdrawn, evidence: {text, of}}` to the role's `jd_read`; the read is never removed (`jd_read.standing` is the read-side list that leaves
    it out, and every consumer asks it);
  * puts back `location` and `listed_pay` from that read's `evidence.replaced`, but ONLY when no later read stands and the value still carries the provenance
    (and, for the pay, the capture date) that read stamped: a later read or a hand edit owns the value now, and it is left and said so. A value the read created
    (nothing was `replaced`) goes away, so the field is NOT captured and the role is re-read;
  * calls `rescreen(row)` so `screen.inputs` follows what is stored;
  * moves a `fit` dated from the day of the read to the day of the withdrawal into `fit_prior` (a list, oldest first), so research runs again against a read that stands;
  * touches no decision, application or company, and says so when the role is decided.

`contradiction(row, attempt)` is 6.2: the read a failed render of the same page in the same run contradicts. Raises `Refused` (a sentence; nothing was changed) when the
withdrawal cannot be made. Pure. Capability module of `recording/withdraw_write.py` and `recording/reads.py`. Python 3.9+, standard library only."""

import copy
import datetime

import jd_read as _jd

WHAT = "`read-withdraw`"
DEFAULT_RUN = "read-withdraw"
DECIDED_VERDICTS = ("pursue", "parked", "pass")


class Refused(Exception):
    """A withdrawal that cannot be made. The text is the sentence the verb prints; nothing was changed."""


def _day(value):
    """The `date` of an ISO date or datetime string, or None."""
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _movable_fit(fit):
    """True when `fit` can be kept as a `fit_prior` entry the validator accepts (an ISO `analyzed_on`, a non-empty requirements list)."""
    return (isinstance(fit, dict) and _day(fit.get("analyzed_on")) is not None and isinstance(fit.get("requirements"), list)
            and bool(fit["requirements"]))


def _put_back(row, key, read, rep, later, notes):
    """`location` / `listed_pay`: restore from the read's `replaced`, or leave it and say why."""
    prov = "candidate" if read["via"] == "candidate" else "jd"
    cur = row.get(key)
    if not isinstance(cur, dict):
        notes.append("%s: nothing stored, nothing to put back" % key)
    elif later:
        notes.append("%s: left (a later read stands and owns it)" % key)
    elif cur.get("provenance") != prov or (key == "listed_pay" and cur.get("captured_on") != read["at"][:10]):
        notes.append("%s: left (it was written since that read: provenance %s)" % (key, cur.get("provenance") or "none"))
    elif key in rep:
        row[key] = copy.deepcopy(rep[key])
        notes.append("%s: restored to what the read replaced" % key)
    else:
        del row[key]
        notes.append("%s: removed (the read created it; it is NOT captured again until a read stands)" % key)


def withdraw_in_row(row, at, why, *, run, now_iso, rescreen=None, applications=()):
    """Withdraw the standing read of `row` made at `at`. Mutates `row` (a fresh copy under the lock, or the caller's own) and returns the notes, a list of lines
    saying what changed and what was left. `rescreen(row)` is called last, after the values are back, so the screen is computed from what is stored.
    Raises `Refused` before anything is changed."""
    why = (why or "").strip()
    if not why or "\n" in why or len(why) > _jd.EVIDENCE_CAP:
        raise Refused("--why is 1 to %d characters on one line: say what was wrong with the read" % _jd.EVIDENCE_CAP)
    try:
        existing = _jd.attempts(row)
    except _jd.JdReadError as e:
        raise Refused("the stored jd_read cannot be read (%s); nothing was written" % e)
    standing = [a for a in _jd.standing_of(existing) if a["outcome"] == _jd.READ]
    reads = [a for a in standing if a["at"] == at]
    if not reads:
        have = ", ".join(a["at"] for a in standing) or "none"
        raise Refused("no read made at %s stands on %s (reads that stand: %s): it never existed or is already withdrawn" % (at, row.get("id"), have))
    read = next(a for a in existing if a["outcome"] == _jd.READ and a["at"] == at)
    via = read["via"] if read["via"] != _jd.LEGACY_VIA else "render"
    try:
        att = _jd.make_attempt(now_iso, run, read["url"], via, _jd.WITHDRAWN, {"text": why, "of": at})
        new = existing + [att]
        _jd.parse({"attempts": new})                        # the cross-checks: `of` names an earlier read, the withdrawal is not before it
    except _jd.JdReadError as e:
        raise Refused("the withdrawal cannot be recorded (%s); nothing was written" % e)
    later = [a for a in _jd.standing_of(new) if a["outcome"] == _jd.READ and a["at"] >= at]
    notes = ["the read of %s via %s is withdrawn (history kept, it no longer stands): %s" % (at, read["via"], why)]
    rep = read["evidence"].get("replaced") or {}
    for key in ("location", "listed_pay"):
        _put_back(row, key, read, rep, later, notes)
    row["jd_read"] = {"attempts": [dict(a) for a in new]}
    if rescreen is not None:
        rescreen(row)
        notes.append("screen re-run on what is stored (inputs: %s)" % ((row.get("screen") or {}).get("inputs") or "none"))
    fit = row.get("fit")
    if fit is not None:
        d, lo, hi = _day(fit.get("analyzed_on")) if isinstance(fit, dict) else None, _day(at), _day(now_iso)
        if d is not None and lo <= d <= hi and _movable_fit(fit):
            row["fit_prior"] = list(row.get("fit_prior") or []) + [fit]
            del row["fit"]
            notes.append("fit of %s moved to fit_prior: research runs again against a read that stands" % d.isoformat())
        else:
            notes.append("fit: left (not dated between the read and the withdrawal)")
    if row.get("verdict") in DECIDED_VERDICTS:
        notes.append("the role is decided (verdict %s) and stays so: no decision was touched" % row["verdict"])
    mine = [a for a in applications if a.get("opp_id") == row.get("id")]
    if mine:
        notes.append("%d application(s) exist and were not touched" % len(mine))
    return notes


def contradiction(row, attempt):
    """6.2: `(read, kept)` for the failed attempt `attempt` (about to be appended to `row`), or None when it contradicts nothing. The read is the NEWEST read that
    stands, `via render`, in the same run and at the same address, when `attempt` is a host-class failure `via render`. `kept` is True when that read carries a
    `body`: a flaky render does not undo a read with its description quoted, so the write only says the two disagree and names the verb."""
    if attempt["via"] != "render" or _jd.outcome_class(attempt["outcome"]) != "host":
        return None
    try:
        reads = [a for a in _jd.standing_of(_jd.attempts(row)) if a["outcome"] == _jd.READ]
    except _jd.JdReadError:
        return None
    newest = max(reads, key=lambda a: a["at"]) if reads else None          # the later one in the list on a tie
    if newest is not None:
        newest = [a for a in reads if a["at"] == newest["at"]][-1]
    if newest is None or newest["via"] != "render" or newest["run"] != attempt["run"] or newest["url"] != attempt["url"]:
        return None
    return newest, "body" in newest["evidence"]
