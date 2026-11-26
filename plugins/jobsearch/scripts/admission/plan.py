"""plan: the company-counted admission of one drain plan, after its candidate buckets (jobsearch 0.94.0, step P0; dev 1055, 1062;
docs/design-role-first.md section 13). Moved out of `lifecycle.drain_plan`, which still builds the candidates and calls here, so the
release branch, the lane and the bound of later steps have a home that is not the over-budget file. No behaviour change.

  company_of  the id of the COMPANY a candidate role belongs to (a role with none the engine can read is a company of its own).
  admit       from the candidate buckets to the admitted companies and roles: class order and reservation, the time bound and the
              journal's 300-role ceiling, the split of a first company that does not fit, the waiting and legacy counts. It fills
              the `Plan` it is given and returns it. From 0.94.0 it is given the LANE (`admission.lane`) too: the roles that meet the
              owner's criteria, already chosen, are admitted FIRST (so they are read first), count against the same time bound and
              ceiling, and leave the companies the rest; a lane of None is 0.93.0's plan, unchanged.
  admit_roles admit a list of chosen roles into the plan: ids, class counts, solo roles and the roles that still need a fetch.

The rules are lifecycle's own (`ADMISSION_ORDER`, `INTAKE_ROLES_MAX`, `DRAIN_BUDGET_S`, `RUN_CLASS_CAUSES`, the fetch figures and
`_has_read`); the caller passes them, because a package imports no entry point (G5) and the constants stay defined once, where
`lifecycle.py`'s interface lists them. `ctx` is a `lifecycle.Ctx`, `plan` a `lifecycle.Plan`, `buckets` `{class: [(since, key, unit)]}`.

Pure: no I/O, no clock. Python 3.9+, standard library only."""

import math
import re


def company_of(unit, ctx):
    """The id of the COMPANY a candidate role belongs to, for the company-counted intake: the opportunity's `company_id`, or
    the company its open capture item(s) name through the one resolver. A role with no company id the engine can read is a
    company of its own (`role:<key>`, whitespace made `_` so the journal's id check holds)."""
    if unit.key in ctx.groups:
        cid = ctx.item_company_id(unit.rows)
    else:
        cid = ctx.opps_by_id[unit.key].get("company_id")
    return cid if isinstance(cid, str) and cid and not re.search(r"\s", cid) else "role:" + re.sub(r"\s+", "_", unit.key)


def admit_roles(ctx, plan, ents, run_causes, has_read):
    """Admit `ents` (`(class index, since, key, class, unit)`) into `plan`: their ids, the class counts, the solo roles (a retry whose cause
    is a run-class one) and the roles that still need a fetch."""
    for _ci, _since, _key, cls, u in ents:
        plan.admitted_by_class[cls] += 1
        o, i = ctx.unit_ids(u)
        plan.admitted_opps += o
        plan.admitted_items += i
        if cls == "retry" and u.stage.cause in run_causes:
            plan.solo.append(u.key)
        if cls != "returned" and not has_read(u, ctx):
            plan.for_fetch += 1


def admit(ctx, plan, buckets, intake, pct, route, prs, order, roles_max, budget_s, run_causes, fetch_s, has_read, lane=None):
    """Fill `plan` from `buckets` (the candidates of `drain_plan`, each class oldest first) and return it. `intake` is the
    company setting, `pct` the new-class percent, `route` "yes" or "no", `prs` the seconds per role; `order` is
    `ADMISSION_ORDER`, `roles_max` `INTAKE_ROLES_MAX`, `budget_s` `DRAIN_BUDGET_S`, `run_causes` `RUN_CLASS_CAUSES`, `fetch_s`
    `(FETCH_WORST_CASE_S, FETCH_CALL_S)` and `has_read(unit, ctx)` says a role already has a read. `lane` is an `admission.lane.Lane` or None."""
    lane_ents = lane.entries if lane else []
    # --- the companies the candidates belong to (dev #834, design-network-first.md 3.5) ---
    by_company = {}                                         # company id -> [(class index, since, key, class, unit)]
    for ci, cls in enumerate(order):
        for since, key, u in buckets[cls]:
            by_company.setdefault(company_of(u, ctx), []).append((ci, since, key, cls, u))
    co_class = {}                                           # company id -> (its earliest class index, oldest since in it)
    for cid, ents in by_company.items():
        ents.sort(key=lambda e: (e[1], e[2]))               # a company's own roles: oldest first
        first = min(e[0] for e in ents)
        co_class[cid] = (first, min(e[1] for e in ents if e[0] == first))
    by_cls = {cls: sorted((cid for cid, (ci, _s) in co_class.items() if ci == n),
                          key=lambda cid: (co_class[cid][1], cid))
              for n, cls in enumerate(order)}
    plan.company_setting = intake
    plan.considered_companies = len(by_company)
    plan.reserved_new = int(math.ceil(intake * pct / 100.0)) if (by_cls["legacy"] or by_cls["held"]) else 0
    chosen_cos = []

    def take(cls, limit):
        n = 0
        while by_cls[cls] and n < limit and len(chosen_cos) < intake:
            chosen_cos.append(by_cls[cls].pop(0))
            n += 1
        return n

    if plan.reserved_new:
        take("new", plan.reserved_new)
    for cls in order:
        take(cls, intake)
    # --- capacity, in ROLES: the time bound and the journal's 300-role ceiling ---
    time_cap = budget_s // prs
    limit = 0 if route == "no" else max(0, min(roles_max, time_cap) - len(lane_ents))
    intake_roles = sum(len(by_company[c]) for c in chosen_cos)
    plan.intake = max(1, min(roles_max, intake_roles + len(lane_ents)))
    plan.chosen_companies = len(chosen_cos)
    admitted_ents, admitted_cos, used = [], [], 0
    for cid in chosen_cos:
        ents = by_company[cid]
        if used + len(ents) <= limit:
            take_ents = ents
        elif not admitted_cos and limit > 0:
            take_ents = ents[:limit]                        # the first company alone does not fit: split it, oldest first
            plan.split_companies.append(cid)
        else:
            break
        admitted_cos.append(cid)
        admitted_ents += take_ents
        used += len(take_ents)
    plan.admitted_companies = admitted_cos
    plan.capped_companies = len(chosen_cos) - len(admitted_cos)
    if route == "no":
        plan.capacity, plan.capacity_reason = 0, "no-render-route"
    elif time_cap < roles_max and used + len(lane_ents) < plan.intake and intake_roles > 0:
        plan.capacity, plan.capacity_reason = used + len(lane_ents), "time-bound"
    else:
        plan.capacity = plan.intake
    # --- admit: the lane first, so it is read first ---
    admit_roles(ctx, plan, lane_ents + admitted_ents, run_causes, has_read)
    plan.fetch_calls = int(math.ceil(plan.for_fetch * fetch_s[0] / float(fetch_s[1])))
    taken = {id(e[4]) for e in admitted_ents}
    left = [e[4] for ents in by_company.values() for e in ents if id(e[4]) not in taken]
    wait = [u for u in left if u.stage.name == "waiting"] + [u for u in (lane.left if lane else ()) if u.stage.name == "waiting"]
    leg = [u for u in left if u.stage.cause == "legacy-backlog"]
    plan.waiting_count = len(wait)
    plan.waiting_oldest = min((u.stage.since for u in wait if u.stage.since), default=None)
    plan.legacy_count = len(leg)
    plan.legacy_oldest = min((u.stage.since for u in leg if u.stage.since), default=None)
    return plan
