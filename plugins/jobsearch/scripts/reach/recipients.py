"""recipients: whom a touch or an involvement reaches, as a CLASS (insider, recruiter, decider), for the play engine.

`PATH_TYPE_CLASS` maps an involvement's `path_type` to a class and `ROLE_TO_PATH` bridges a touch's own `recipient_role` to a
`path_type` (design-connected-entities.md §18, §26.2); `touch_class` reads the involvement first and the role second, never a
guess. Moved out of `plays.py` unedited (jobsearch 0.91.0 B4 step A), so a capability module can ask the same question without
importing an entry point. `ctx` is any object carrying `involvements_by_opp` (`plays.Context` is one). Capability module of
`plays.py`. Python 3.9+, standard library only."""


# §18/§26.2 — the class an involvement's `path_type` (or, absent one, a touch's own
# `recipient_role` through this one bridge) resolves to. `RECIPIENT_ROLES` stays the touch's
# vocabulary, `PATH_TYPES` the involvement's — this is the ONE mapping between them (§26.2's
# own withdrawal of §20's "one vocabulary" sentence).
PATH_TYPE_CLASS = {"recruiter": "recruiter", "warm-referral": "insider", "internal": "insider",
                   "hiring-manager": "decider",
                   # 0.91.0 (design-build-reach.md 6.3): a recruiting, HR or talent person who is NOT the role's lead
                   # (`recruiter` already means the lead); its own class, so the side door never mistakes one for the other
                   "side-contact": "side-contact"}
ROLE_TO_PATH = {"talent-acquisition": "recruiter", "recruiter-agency": "recruiter",
               "warm-contact": "warm-referral", "peer-network": "warm-referral",
               "hiring-manager": "hiring-manager", "hiring-line": "hiring-manager"}


def _involvement_class(opp_id, person_id, ctx):
    for inv in ctx.involvements_by_opp.get(opp_id, ()):
        if inv.get("person_id") == person_id:
            c = PATH_TYPE_CLASS.get(inv.get("path_type"))
            if c:
                return c
    return None


def touch_class(touch, ctx):
    """§26.2 — the recipient's class for one touch: the involvement's `path_type` first, the
    touch's own `recipient_role` through `ROLE_TO_PATH` second. Two stored facts, in order,
    never a guess."""
    opp_id, person_id = touch.get("opp_id"), touch.get("person_id")
    c = _involvement_class(opp_id, person_id, ctx) if opp_id and person_id else None
    if c:
        return c
    pt = ROLE_TO_PATH.get(touch.get("recipient_role"))
    return PATH_TYPE_CLASS.get(pt) if pt else None


def class_known(opp_id, cls, ctx):
    for inv in ctx.involvements_by_opp.get(opp_id, ()):
        if PATH_TYPE_CLASS.get(inv.get("path_type")) == cls:
            return True
    return False
