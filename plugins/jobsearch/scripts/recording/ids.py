"""ids: id minting: an application's `<opp_id>-aN`, a cover letter's `<opp_id>-clN`, a touch's `<person_id>-tN`,
and a message id deterministic over its own inputs.

Capability module of record.py (an entry point over `recording/`)."""


def mint_app_id(rid, existing):
    """`<opp_id>-aN`, N one past the highest suffix already minted for this opp_id (0.41.0;
    ADR-031 B2 re-pointed this at the top-level `applications` store's own `id` field — was
    `app_id` on a nested `applications[]` row, same VALUE format, "promotion changes only the
    lookup").

    ⭐ THE READER'S TARGET MUST EXIST. Every applications row gets its handle AT WRITE TIME, so
    a trigger (outreach[].trigger_ref, asks.trigger_ref) and every later reader resolve a key
    this API guarantees rather than a date somebody remembered — two applications on one day
    share a date and nothing else. Past-the-max, never count-plus-one: a row removed from the
    middle must not free its number for reuse, or an old trigger naming it would silently move
    to a different application. `existing` is every row this rid's ids could collide with —
    the caller filters to the SAME opp_id when it matters (this function itself does not,
    since the `<opp_id>-a` prefix already scopes the match)."""
    prefix = "%s-a" % rid
    n = 0
    for a in existing or []:
        aid = a.get("id") if isinstance(a, dict) else None
        if isinstance(aid, str) and aid.startswith(prefix) and aid[len(prefix):].isdigit():
            n = max(n, int(aid[len(prefix):]))
    return "%s%d" % (prefix, n + 1)


def mint_cover_letter_id(opp_id, existing):
    """`<opp_id>-clN`, N one past the highest suffix already minted for this opp_id (dev #764 /
    public #162). The same past-the-max, never count-plus-one rule as `mint_app_id`, for the same
    reason: a removed letter must not free its number for a later `cover_letter_id` reference to
    collide into. A letter is written for a role, so it is owned by the OPPORTUNITY, like an
    application. `existing` is every row whose ids could collide; the `<opp_id>-cl` prefix scopes
    the match, and a suffix that is not all digits (`<opp_id>-cl2-cl1`) is not a mint of this id."""
    prefix = "%s-cl" % opp_id
    n = 0
    for c in existing or []:
        cid = c.get("id") if isinstance(c, dict) else None
        if isinstance(cid, str) and cid.startswith(prefix) and cid[len(prefix):].isdigit():
            n = max(n, int(cid[len(prefix):]))
    return "%s%d" % (prefix, n + 1)


def mint_touch_id(person_id, existing):
    """`<person_id>-tN`, N one past the highest suffix already minted FOR THIS PERSON — ADR-031
    B3's own id scheme (design §1: 'id (= <person_id>-tN, minted by record.py)'). A touch is
    owned by the PERSON, not the opportunity — the one deliberate difference from
    `mint_app_id`'s `<opp_id>-aN`, which owns by the opportunity because an application is
    containment (design §1). `existing` is every row this person_id's ids could collide with —
    same past-the-max, never count-plus-one rule as `mint_app_id`, for the same reason: a
    removed touch must not free its number for a later trigger_ref/message_ref to collide
    into."""
    prefix = "%s-t" % person_id
    n = 0
    for t in existing or []:
        tid = t.get("id") if isinstance(t, dict) else None
        if isinstance(tid, str) and tid.startswith(prefix) and tid[len(prefix):].isdigit():
            n = max(n, int(tid[len(prefix):]))
    return "%s%d" % (prefix, n + 1)


def mint_message_id(anchor_id, person_id, date):
    """Deterministic id for a message THIS API creates (`touched`/`answered`, §15.3) — the
    SAME inputs always mint the SAME id, which is what makes the two-append write
    'idempotent by id' (§15.3 point 2): a re-run after a crash between the message append and
    the outreach append finds the message already there (by this id) and completes only the
    missing half, rather than writing a duplicate. Not a collision-proof id in general (two
    touches to the same person on the same day via different media share one id) — an
    accepted, stated trade-off, the same shape `mint_app_id`'s own docstring accepts for
    same-day applications sharing a date."""
    return "msg-record-%s-%s-%s" % (anchor_id or "none", person_id or "none", date)
