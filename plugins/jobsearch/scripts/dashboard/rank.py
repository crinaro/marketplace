"""What Today holds, and in what order (dashboard-redesign D1; design-dashboard-redesign §3.3, §3.4, §3.6).

THE ORDER IS ONE FIXED LIST OF KINDS, `KINDS` below, and nothing else. Inside a kind the order is the one its owning
function already produces (the loader passes each source in its owner's order); this module never re-sorts a kind and
never compares one kind's age with another's. Pure: no I/O, no clock read, no flat script imported.

    kinds(pd)                -> [Kind]   the table, each row's `members` filled from the PageData fields below
    today(kinds, cap=5)      -> ([Item], [(Kind, count)])   Today's items, then what the "Also below" line names
    plan(pd, cap=5)          -> today(kinds(pd), cap)
    pinned_for(items, sec)   -> (key, ...)   the keys Today took from section `sec`, for `caps.levels(pinned=...)`
    is_empty(kinds)          -> True iff every kind is empty: Today is then the sentence (§3.5)

A member is `(key, name, site)`: `key` the record's page key (`draft:<title>`, `person:<id>`, `opp:<id>`,
`net:look-into:<id>`, ...), the same key as its primary row's `data-rec`; `name` the candidate's own words naming it;
`site` the `markup.THEIRS_SITES` entry `name` is rendered under.

`today` walks the kinds in table order. A kind with 1 or 2 members yields one SINGLE item per member; a kind with more
yields ONE GROUP item naming its first member and the count, so no kind takes more than 2 of the 5. It stops at the cap;
every member left over is counted, per kind, for the "Also below" line.

A single item is a REFERENCE: `data-ref="<key>"` and a link to `#rec-<hash of key>` (`markup.links_for`), the record's
ONE primary row in its section. A group item links its kind's ANCHOR, a fixed id the section emits on that kind's
group heading. THE ANCHORS (D2 emits each one on the group heading named; until a section emits its anchor,
`today.render` links the section's own heading instead, so no link lands on nothing):

    today-src-network-reply-owed          Network › They wrote back          kind 1
    today-src-drafts-needs-you            Drafts › needs you                 kinds 2 and 10
    today-src-network-accepted            Network › They accepted            kind 3
    today-src-drafts-ready                Drafts › ready                     kind 4
    today-src-network-to-record           Network › To record                kind 5
    today-src-opportunities               Opportunities                      kind 6
    today-src-needs-read                  Needs your read                    kind 7
    today-src-applications                Applications to finish             kind 8
    today-src-targets                     Targets                            kind 9
    today-src-network-quiet-recent        Network › Went quiet recently      kind 11
    today-src-network-applied-no-contact  Network › Applied, no one contacted yet   kind 12
    today-src-network-referral-handoff    Network › Introductions            kind 13
    today-src-network-relationships-due   Network › Relationships due this week     kind 14

`pinned_for(items, section)` gives, in Today's order, the key of every single item from that section and the FIRST
member of every group item from it (the group item names that member, so its row is open too). Sections: `drafts`,
`network`, `targets`, `opps`, `read`, `apply`.

THE PAGEDATA FIELDS a kind reads (the loader, `generate_dashboard._load_today`, fills them from what exists today):

    today_drafts   [{"key", "name", "state"}]   active drafts, file order; `state` is `precondition`'s
    today_plan     [{"key", "name", "site", "group", "axis", "last_touch"}]   `communication_plan` rows, plan order;
                   `axis` the conversation axis of an `awaiting-reply` row (`accepted`, `silent`, `silence-unverified`)
    today_roles    [{"key", "name", "pursuit", "stage"}]   live roles: pursuit state and lifecycle stage name
    today_targets  [{"key", "name"}]   the companies Targets lists this week, `targets_review` order
    quiet_days     `chase_after_days + no_response_after_days`: a `silent` row whose last touch is at most this many
                   days old went quiet RECENTLY (kind 11, §7.5); older is long quiet, never on Today
    needs_human    `precondition.NEEDS_HUMAN`

Kind 1 reads `today_plan` rows of group `reply-owed`. `communication_plan` has no such group yet (probe E7, I-5): the
field is wired and EMPTY until builder D2's N4 adds the group, and then it fills with no change here."""
import collections
import datetime

from dashboard.caps import TODAY_CAP


Kind = collections.namedtuple("Kind", "num tier name words single also section where anchor members")
Item = collections.namedtuple("Item", "kind ref first count")   # ref: the member (a single item) or None (a group)


# THE TABLE (design §3.3). Its row order IS Today's order. `words` is the item's label (`N` is the kind's count, for a
# group item), `single` the label of a single item, `also` what the "Also below" line calls the members left over,
# as (one, many); `members` is empty here and filled by `kinds`.
KINDS = (
    Kind(1, 1, "reply-owed", "They wrote back", "They wrote back",
       ("person wrote back with no reply drafted", "people wrote back with no reply drafted"),
       "network", "Network › They wrote back", "today-src-network-reply-owed", ()),
    Kind(2, 1, "stale-brief", "They wrote back", "They wrote back",
       ("draft out of date because they wrote", "drafts out of date because they wrote"),
       "drafts", "Drafts › needs you", "today-src-drafts-needs-you", ()),
    Kind(3, 1, "accepted", "They accepted", "They accepted",
       ("person accepted your connection", "people accepted your connection"),
       "network", "Network › They accepted", "today-src-network-accepted", ()),
    Kind(4, 1, "sendable", "Ready to send", "Ready to send", ("draft ready to send", "drafts ready to send"),
       "drafts", "Drafts › ready", "today-src-drafts-ready", ()),
    Kind(5, 1, "to-record", "Did it happen?", "Did it happen?",
       ("thing only you can record", "things only you can record"),
       "network", "Network › To record", "today-src-network-to-record", ()),
    Kind(6, 2, "decide", "Decide", "Decide", ("role to decide", "roles to decide"),
       "opps", "Opportunities", "today-src-opportunities", ()),
    Kind(7, 2, "your-read", "Needs your read", "Needs your read",
       ("posting only you can open", "postings only you can open"),
       "read", "Needs your read", "today-src-needs-read", ()),
    Kind(8, 2, "not-sent", "Finish", "Finish", ("application to finish", "applications to finish"),
       "apply", "Applications to finish", "today-src-applications", ()),
    Kind(9, 2, "targets", "N companies", "A company to answer", ("company to answer", "companies to answer"),
       "targets", "Targets", "today-src-targets", ()),
    Kind(10, 2, "fix-draft", "Fix a draft", "Fix a draft", ("draft to fix", "drafts to fix"),
       "drafts", "Drafts › needs you", "today-src-drafts-needs-you", ()),
    Kind(11, 3, "quiet-recent", "N went quiet", "Went quiet", ("went quiet recently", "went quiet recently"),
       "network", "Network › Went quiet recently", "today-src-network-quiet-recent", ()),
    Kind(12, 3, "applied-no-contact", "N with no contact", "No contact yet",
       ("application with nobody contacted", "applications with nobody contacted"),
       "network", "Network › Applied, no one contacted yet", "today-src-network-applied-no-contact", ()),
    Kind(13, 3, "referral-handoff", "Ask about an intro", "Ask about an intro",
       ("introduction not confirmed", "introductions not confirmed"),
       "network", "Network › Introductions", "today-src-network-referral-handoff", ()),
    Kind(14, 3, "relationships-due", "N to touch base with", "Touch base",
       ("relationship due this week", "relationships due this week"),
       "network", "Network › Relationships due this week", "today-src-network-relationships-due", ()),
)


def _recent(row, day, days):
    try:
        return (day - datetime.date.fromisoformat(str(row.get("last_touch"))[:10])).days <= days
    except ValueError:
        return False                                            # no readable last touch: never "recent"


def _sources(pd):
    """{kind name: [member]} from the PageData fields (the module docstring), each in its owner's order."""
    drafts, plan = pd.today_drafts or [], pd.today_plan or []
    roles, needs_human = pd.today_roles or [], set(pd.needs_human or ())
    day = pd.now.date() if pd.now is not None else None
    days = pd.quiet_days if pd.quiet_days is not None else 0

    def d(test):
        return [(r["key"], r["name"], "message-snippet") for r in drafts if test(r.get("state"))]

    def p(group, test=lambda r: True):
        return [(r["key"], r["name"], r.get("site") or "person-name") for r in plan
                if r.get("group") == group and test(r)]

    def o(state, stage=None):
        return [(r["key"], r["name"], "role-title") for r in roles
                if r.get("pursuit") == state and (stage is None or r.get("stage") == stage)]

    return {
        "reply-owed": p("reply-owed"),
        "stale-brief": d(lambda s: s == "stale-brief"),
        "accepted": p("awaiting-reply", lambda r: r.get("axis") == "accepted"),
        "sendable": d(lambda s: s == "sendable"),
        "to-record": p("to-record"),
        "decide": o("new", "ready"),
        "your-read": o("your-read"),
        "not-sent": o("not-sent"),
        "targets": [(r["key"], r["name"], "company-name") for r in pd.today_targets or []],
        "fix-draft": d(lambda s: s in needs_human and s != "stale-brief"),
        "quiet-recent": p("awaiting-reply", lambda r: r.get("axis") == "silent" and day is not None
                          and _recent(r, day, days)),
        "applied-no-contact": p("applied-no-contact"),
        "referral-handoff": p("referral-handoff"),
        "relationships-due": p("relationships-due"),
    }


def kinds(pd):
    """[Kind]: `KINDS` in table order, each with its `members` from `pd`."""
    src = _sources(pd)
    return [k._replace(members=tuple(src[k.name])) for k in KINDS]


def is_empty(ks):
    return not any(k.members for k in ks)


def today(ks, cap=TODAY_CAP):
    """`(items, also)`: at most `cap` items in table order; `also` [(kind, count)] counts every member left out."""
    items, also = [], []
    for k in ks:
        if not k.members:
            continue
        if len(k.members) > 2:
            if len(items) < cap:
                items.append(Item(k, None, k.members[0], len(k.members)))
            else:
                also.append((k, len(k.members)))
            continue
        left = 0
        for m in k.members:
            if len(items) < cap:
                items.append(Item(k, m, m, 1))
            else:
                left += 1
        if left:
            also.append((k, left))
    return items, also


def plan(pd, cap=TODAY_CAP):
    return today(kinds(pd), cap)


def pinned_for(items, section):
    """The keys Today took from `section`, in Today's order (a group item contributes its first member)."""
    return tuple(it.first[0] for it in items if it.kind.section == section)
