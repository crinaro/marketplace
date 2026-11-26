"""pursue_target: whether pursuing a role makes its company a target, and what a later pass says about it (jobsearch 0.94.0, dev 1062, RF9, OD-9 yes;
docs/design-role-first.md 4.4). Pure functions over the rows `decisions.decide_mutation` hands a `two_stores.PairMutation`; nothing here reads or writes a
store. They edit the `companies` rows they are given IN PLACE and return `(changed, line)`, so the same function serves the dry run (on a copy), the write
(on the rows re-read under the lock) and the tests.

The pursued company is `active-target` with `status_on` and `target_from: {opp, on}` and NO `motivation`: how much the owner wants to work there is their own
statement and is never defaulted, so absent stays absent. `company-status` (the owner's whole-company yes) deletes `target_from`; so does a stated motivation.

Capability module of record.py (an entry point over `recording/`). Python 3.9+, standard library only."""

from journaling.pins import ROLE_FIRST_MIGRATION, ROLE_FIRST_PIN
from reach import staffing as _staff
from recording import role_first

KIND_WORDS = {"staffing": "a staffing firm", "aggregator": "a job board"}


def _not_targeted(why):
    return False, "company not targeted: %s" % why


def _live_roles(opps, cid, opp_id, ym):
    """The company's roles the way `your_move.company_candidates` reads them (non-terminal, not folded, carrying a sighting), plus the pursued
    role itself whatever its status: a staffing firm is told by its roles' sightings, and the one pursued must be among them."""
    return [o for o in opps if o.get("company_id") == cid and (
        o.get("id") == opp_id or (o.get("status") in ym._lc.NON_TERMINAL_STATUSES and not ym._pidx.is_folded(o)
                                  and any(isinstance(s, dict) for s in (o.get("sightings") or []))))]


def pursue_target(companies, opps, channels, opp_id, today, ym, no_target):
    """`(changed, line)`: make the company of `opp_id` (a row of `opps`, as it stands after the pursue) a target by editing `companies` IN PLACE
    when it may be, else leave it untouched and say why (design 4.4). It may be when ALL of these hold: `--no-target` was not given; the profile
    carries the 0.94.0 pin (without it a pursue behaves as 0.93.0 did and targets nothing); the company is `watching` (the stored status of an
    undecided or a watched one); it states no `motivation` (a stated one is the owner's own word and `target_from` never sits beside it, so
    targeting it is theirs to say); and it is neither a staffing firm nor a job board (`ym.company_kind`, `reach.staffing`: the employer is not
    known). A company already a target is left as it is, so a repeat of a pursue that was killed between its two saves changes nothing here.
    What is written: `status` `active-target`, `status_on`, `target_from` `{opp, on}`, and nothing else, `motivation` above all."""
    if no_target:
        return _not_targeted("--no-target was given")
    if role_first.pin_refusal("a company target from a pursue"):
        return _not_targeted("this profile is not pinned to jobsearch %s (%s is pending), so a pursue targets nothing yet" % (ROLE_FIRST_PIN, ROLE_FIRST_MIGRATION))
    opp = next((o for o in opps if o.get("id") == opp_id), {})
    cid = opp.get("company_id")
    company = next((c for c in companies if cid and c.get("id") == cid), None)
    if company is None:
        return _not_targeted("this role names no company record")
    status = company.get("status")
    if status == "passed":
        return _not_targeted("you passed on this company (`record.py company-status %s active-target` targets it)" % cid)
    if status == "active-target":
        tf = company.get("target_from")
        return False, "company %s is already a target%s" % (cid, " (from this role)" if isinstance(tf, dict) and tf.get("opp") == opp_id else "")
    if status != "watching":
        return _not_targeted("its status is %r, not watching" % status)
    if company.get("motivation") is not None:
        return _not_targeted("you stated a motivation for it earlier; `record.py company-status %s active-target` targets it, in your words" % cid)
    kind, _how = _staff.kind_of(ym.company_kind(company, channels), _live_roles(opps, cid, opp_id, ym), channels, lambda o: ym.role_link(o)[1])
    if kind in KIND_WORDS:
        return _not_targeted("%s: the employer is not known (`record.py company-kind %s employer` if it is one)" % (KIND_WORDS[kind], cid))
    company["status"], company["status_on"], company["target_from"] = "active-target", today, {"opp": opp_id, "on": today}
    return True, ("company %s is now an active target, from this role: its other roles are read only when they match your criteria "
                  "(`record.py company-status %s watching` takes it back)" % (cid, cid))


def pass_note(companies, opps, opp_id):
    """`(False, line)`: what a pass on a role says when the role's company was targeted BY pursuing this very role (`target_from`): it stays a
    target, and the line names how to change that. `(False, "")` otherwise. Never an edit: a later pass does not untarget a company."""
    opp = next((o for o in opps if o.get("id") == opp_id), {})
    company = next((c for c in companies if opp.get("company_id") and c.get("id") == opp["company_id"]), None) or {}
    tf = company.get("target_from")
    if company.get("status") == "active-target" and isinstance(tf, dict) and tf.get("opp") == opp_id:
        return False, ("company %s was targeted when you pursued this role and stays a target; `record.py company-status %s watching` "
                       "(or `passed`) changes that" % (company["id"], company["id"]))
    return False, ""
