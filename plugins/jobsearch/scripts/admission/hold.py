"""hold: whether a role is held for its company, as functions over the company map (jobsearch 0.94.0, step P0; dev 1055, 1062;
docs/design-role-first.md section 13). Moved out of `lifecycle.Ctx`, which delegates here, so the release branch, the pin instant and
`held_cause` of later steps have a home that is not the over-budget file. No behaviour change.

A role at a company the candidate has not targeted is HELD (`held-for-company`, `lifecycle.HELD_STAGES`; dev #834). The three
questions, each a function of what the caller already loaded:

  company_hold      why a role at this company is held, or None: `passed`, `watching` (a decision is on the row) or `undecided`.
  item_company_id   the company id a role's open capture item(s) name, through the one resolver every other reader uses.
  held_for_company  a stage turned into `held-for-company` when it is one the rule demotes.

and, from 0.94.0 (dev 1062; design 3.2, 4.4), three more: `pursued_company` (an active target a pursue made, with no motivation of the owner's
own), `stated_target` (an active target the owner chose) and `released` (a waiting role the first look let go of the company question).

Pure: no I/O, no clock. It imports no entry point (G5): the two lookups a caller owns (`item_company_title`, `resolve_company`) are
passed in. Python 3.9+, standard library only."""

HELD = "held-for-company"
RELEASED = "criteria"                                   # the `detail` of a waiting role the first look released (design 3.2)


def company_hold(companies_by_id, company_id):
    """Why a role at this company is held, or None when it is not: `passed`, `watching` (the candidate decided to watch
    it, so `status_on` is on the row) or `undecided` (`watching` with no `status_on`). An `active-target` company holds
    nothing. A company id that resolves to no row, or a status outside the three, holds nothing either: the engine cannot
    say the role is at a NON-target company, so its stage is left exactly as it was (and a company a capture makes is
    always written `watching`, so a real role never lacks the row)."""
    c = companies_by_id.get(company_id) if company_id else None
    if c is None:
        return None
    status = c.get("status")
    if status == "passed":
        return "passed"
    if status == "watching":
        return "watching" if c.get("status_on") else "undecided"
    return None


def item_company_id(items, companies_by_id, company_title, resolve_company):
    """The company id the open capture item(s) of one role name, through the one resolver every other reader uses
    (`resolve_company`, `pipeline_index.resolve_company`), or None when the name resolves to no single company.
    `company_title(item)` is `lifecycle.item_company_title`: `(company, title)` read off the item, or `(None, None)`."""
    for it in items:
        name, _title = company_title(it)
        if name:
            cid = resolve_company(name, list(companies_by_id.values()))
            if cid:
                return cid
    return None


def pursued_company(companies_by_id, company_id):
    """True when the company is an `active-target` that only a PURSUE made (`target_from` is on the row) and the owner has stated no
    motivation (design 4.4). Such a company's roles are read only when they match the owner's criteria; `company-status <id> active-target`
    with a motivation deletes `target_from`, which ends it. A company that resolves to no row is not."""
    c = companies_by_id.get(company_id) if company_id else None
    return (isinstance(c, dict) and c.get("status") == "active-target" and isinstance(c.get("target_from"), dict)
            and not c.get("motivation"))


def stated_target(companies_by_id, company_id):
    """True when the company is an `active-target` the owner chose: not one a pursue made without a motivation (`pursued_company`)."""
    c = companies_by_id.get(company_id) if company_id else None
    return isinstance(c, dict) and c.get("status") == "active-target" and not pursued_company(companies_by_id, company_id)


def released(st):
    """`st` with `detail` `criteria` when it is a waiting role with no other reason to wait (a plain wait or a re-admission), else `st`."""
    if st.name == "waiting" and st.detail in ("", "readmitted"):
        return st._replace(detail=RELEASED)
    return st


def held_for_company(st, why, since, cause=None):
    """`st` turned into `held-for-company` when it is a stage the rule demotes and `why` says the company is not a target;
    else `st` unchanged. `cause` (0.94.0) is the first criterion the role fails, kept on the stage (a first look's clause). Only a role NO read has reached is demoted: `waiting` or one of the failure states a never-read
    role sits in (`uncaptured`, `unread`, `read-failed`). A role already read, screened, decided or researched keeps its
    stage (work done is never demoted), and so does `unclassified`, `your-read`, `gone`, `removed` and `ended`. `st` is a
    `lifecycle.Stage`; the result is another one (a named-tuple replace keeps its type and its key)."""
    if why is None:
        return st
    if st.name == "waiting" or (st.failure and st.name in ("uncaptured", "unread", "read-failed")):
        return st._replace(name=HELD, failure=False, since=since, cause=cause, detail=why)
    return st
