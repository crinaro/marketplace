"""asks: whether one ask concerns one person (dev #475, public #118).

An ask joins a pursuit or a channel, never a person, so it counts against a contact only when that contact is the SOLE living
person its scope resolves to (`_ask_concerns_person`). `g` is a `graph.Graph`, passed in: this module imports no entry point.
Moved out of `brief.py` unedited (jobsearch 0.91.0 B4 step A); `brief.is_stale` calls it. Capability module of `brief.py`.
Python 3.9+, standard library only."""


def _ask_concerns_person(g, ask, person_id):
    """dev #475 (public #118) — an ask joins `opp_id`/`channel_id`, never a person directly
    (asks.jsonl's own field list has no `person_id`), so on a pursuit or channel that has MORE
    THAN ONE person involved — a hiring manager and a recruiter on the same opportunity, say —
    the ask cannot be attributed to either one specifically. `is_stale()` used to flag staleness
    for ANY contact sharing that opp/channel the moment the ask resolved, even when it was
    really the OTHER party's ask that closed. That is the too-broad predicate this narrows:
    an ask counts against a contact only when that contact is the SOLE person its own scope
    resolves to. An ambiguous, shared scope is a false-positive risk, not evidence this
    particular contact's brief moved — so it is excluded rather than guessed at."""
    opp_id, channel_id = ask.get("opp_id"), ask.get("channel_id")
    if not opp_id and not channel_id:
        return False
    invs = g.involvements_for_opportunity(opp_id) if opp_id else g.involvements_for_channel(channel_id)
    people = set()
    for inv in invs:
        p = g.resolve_person(inv.get("person_id"))
        if p is not None:
            people.add(p["id"])
    return people == {person_id}
