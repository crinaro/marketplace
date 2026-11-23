"""staffing: a company every sighting of which came through a recruiter is a staffing firm, not a target (jobsearch 0.92.0, dev
#1004; docs/design-decision-surface.md §D.3).

`your_move.company_kind` classifies a company by what is stated, a channel of its name, or its name; a company it calls
`employer` only by `default` may still be a recruiter's front. `recruiter_only` is the signal: at least one sighting, every
sighting's channel `type` is `recruiter`, and no role links an employer-owned posting (`your_move.role_link(o)[1]`).
`kind_of` applies it to exactly the `("employer", "default")` reading and returns `("staffing", "sightings")`, so
`company_candidates` excludes the company like any staffing firm: never raised, never a Targets row. The excluded row carries
the "These are employers" tick box, so a wrong exclusion costs one tick.

Not `dashboard.targets.t1`: T1 also fires on aggregator-only sightings, and those companies keep T1's question (a job board is
not a staffing firm). An unknown channel (`None`) is not a recruiter, so a company with one is never excluded on this signal.

Takes rows and a function; imports nothing. Python 3.9+, standard library only."""

RECRUITER = "recruiter"
EXCLUDED = ("staffing", "sightings")


def recruiter_only(types, owned):
    """True when `types` (one channel type per sighting) is not empty, every one is `recruiter`, and `owned` (a role links an
    employer-owned posting) is false."""
    types = list(types)
    return bool(types) and all(t == RECRUITER for t in types) and not owned


def sighting_types(roles, channels):
    """One channel `type` per sighting of `roles` (None for a channel id that resolves to no channel or to one with no type)."""
    by_id = {c.get("id"): c.get("type") for c in channels or () if c.get("id")}
    return [by_id.get(s.get("channel_id")) for o in roles for s in (o.get("sightings") or ()) if isinstance(s, dict)]


def kind_of(kind_how, roles, channels, owned_of):
    """`(kind, how)`: `kind_how` (a `company_kind` reading) unchanged unless it is `("employer", "default")` and the company's
    open `roles` are recruiter-only, then `("staffing", "sightings")`. `owned_of(opp)` is `your_move.role_link(opp)[1]`."""
    kind_how = tuple(kind_how)
    if kind_how != ("employer", "default"):
        return kind_how
    return EXCLUDED if recruiter_only(sighting_types(roles, channels), any(owned_of(o) for o in roles)) else kind_how
