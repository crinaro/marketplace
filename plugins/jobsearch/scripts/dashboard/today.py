"""Today: the first list on the page (dashboard-redesign D1; design-dashboard-redesign §3).

    render(pd, sections, present) -> html     the block: heading, then at most 5 items and the "Also below" line, or
                                              the one sentence when every kind is empty
    sentence(pd)                  -> str      the sentence (§3.5)
    heading_time(now)             -> str      "18 Nov, 09:12"

THE BLOCK HOLDS REFERENCES ONLY (§3.6 rule 1). A single item is `<li data-ref="<key>">` with a link to the record's
primary row (`markup.links_for`); a group item links its kind's anchor (`rank`'s docstring lists them). Nothing in
Today carries `data-rec`, so no record gains a second primary row. `present(anchor)` says whether the page carries that
anchor yet; until a section emits its kind's anchor (builder D2), a group item links the section's own heading,
`sections[kind.section]`, so a link never lands on nothing. The heading is `Today · as of <generation time>`, from
the render's one clock (`pd.now`), because a phone reader may open the page hours after it was made (§12). Every item
carries a TICKED box (`_box`) and the block ONE `work-through` button (builder D2, design §6.1), inside
`data-pick-group="today"`.

THE SENTENCE (§3.5) shows if and only if every kind is empty, and names ONLY counts above zero, from
`pd.today_counts` (the loader's copy of `process_report`'s counts, the targets' and companies' counts, and the threads
not yet due a nudge) and `pd.today_plan`. It never uses a fault word (`FAULT_PHRASES` of
`tests/test_zero_applications_healthy.py`). `pd.today_counts` keys, each an int, absent read as 0:

    roles            process_report().totals["roles"]
    ready, waiting, in_progress           process_report()'s own counts
    in_progress_oldest_days               days since the oldest in-progress role's stage began
    held_undecided, held_watching, held_passed   process_report().held_company, by why
    held_listed      the `held-for-company` (`undecided`) roles at the companies Targets lists: the Targets item's
                     "N unread roles wait on your yes or no" (§7.4)
    not_raised       classify_companies()["look-into-waiting"]: qualifying companies never raised
    snoozed          targets_review()["snoozed"], counted
    not_due          person threads whose conversation axis is `waiting` (the last message is too recent to nudge)
`checked` is False when the pipeline could not be read: the sentence then names no pipeline count at all."""
from dashboard import levels, rank
from dashboard.actions_ui import group_attr, pick
from dashboard.caps import TODAY_CAP
from dashboard.markup import esc, key_attr, links_for, rec_id, theirs


TODAY_ID = "today"

# What follows the member's name on a single item, per kind (the label is the table's `single`).
_TAIL = {
    "reply-owed": " wrote back, and no reply is drafted.",
    "stale-brief": ": they wrote, so this draft is out of date.",
    "accepted": " accepted your connection.",
    "sendable": ". It passed every check.",
    "to-record": ". Only you know whether it happened.",
    "decide": ". A pursue or pass is owed.",
    "your-read": ". Only you can open the posting.",
    "not-sent": ". You are pursuing it and nothing is sent yet.",
    "targets": " waits on your yes or no.",
    "fix-draft": ". It needs you before it can be sent.",
    "quiet-recent": " has not replied. A nudge is due.",
    "applied-no-contact": ": you applied and nobody is contacted yet.",
    "referral-handoff": ": an introduction is not confirmed yet.",
    "relationships-due": ": a touch is due this week.",
}


def heading_time(now):
    return "%d %s, %s" % (now.day, now.strftime("%b"), now.strftime("%H:%M"))


def _n(n, one, many):
    return "%d %s" % (n, one if n == 1 else many)


def _label(item):
    k = item.kind
    if item.ref is not None:
        return k.single
    return ("%d%s" % (item.count, k.words[1:])) if k.words.startswith("N ") else k.words


def _text(item, counts):
    key, name, site = item.first
    who = theirs(name, site)
    if item.ref is not None:
        return who + esc(_TAIL[item.kind.name])
    if item.kind.name == "targets" and counts.get("held_listed"):
        held = counts["held_listed"]
        return esc("%s wait%s on your yes or no. A yes lets the next run read them."
                   % (_n(held, "unread role", "unread roles"), "s" if held == 1 else ""))
    return "%s%s" % (who, esc(", and %d more." % (item.count - 1)))


def _target(pd, key):
    """The key of the primary row an item about `key` links: `key` itself, or the row it refers to when its Network row
    is a reference (`pd.ref_of`, dev 973), so a Today item never names a key with no primary row (LINKED)."""
    return (pd.ref_of or {}).get(key, key)


def _item(item, counts, href, box="", target=None):
    ref = ' data-ref="%s"' % key_attr(target or item.ref[0]) if item.ref is not None else ' data-count="%d"' % item.count
    return ('<li class="today-item" data-kind="%s"%s>%s<a class="ref" href="%s"><strong>%s</strong> %s</a> '
            '<span class="sub">%s</span></li>' % (esc(item.kind.name), ref, box, esc(href), esc(_label(item)),
                                                  _text(item, counts), esc(item.kind.where)))


def _box(pd, item, present):
    """`(html, missing)`: an item's tick box, TICKED (design §6.1, builder D2), and how many of the members it stands for
    are NOT on the page. A single item's box is its record's; a group item's stands for the rows of its kind that are on
    the page (`present(rec_id(key))`), their record lines joined; the rest of the kind (past a section's level 2) is
    `missing`, which the button's `tail(more)` counts, so the prompt's lines plus its "Not on the page" count equal the
    counts the items show (§3.6 rule 5, criterion X5). The lines are the loader's (`pd.pick_rows`); ("", 0) when the
    loader gave none (a hand-built PageData), or no member row is on the page."""
    if pd.pick_rows is None:
        return "", 0
    members = [item.ref] if item.ref is not None else list(item.kind.members)
    picks = [pd.pick_rows[m[0]] for m in members if present(rec_id(_target(pd, m[0])))]
    if not picks:
        return "", 0
    return (pick(picks[0][0], "\n".join(line for _rec, line in picks), item.first[1], level=1, checked=True),
            len(members) - len(picks))


def render(pd, sections, present):
    """The Today block (the module docstring). `sections` {section: its heading id}; `present(id)` -> bool."""
    items, also = rank.plan(pd, TODAY_CAP)
    head = '<h2 id="%s">Today · as of %s</h2>' % (TODAY_ID, esc(heading_time(pd.now)))
    if not items:
        return ('<section class="today" data-today="sentence">%s<div class="sub today-sentence">%s</div></section>'
                % (head, esc(sentence(pd))))
    counts = pd.today_counts or {}
    lis, n_boxes, missing = [], 0, 0
    for it in items:
        if it.ref is not None:
            href = links_for(_target(pd, it.ref[0]))
        else:
            href = "#" + (it.kind.anchor if present(it.kind.anchor) else sections.get(it.kind.section, it.kind.anchor))
        box, n_missing = _box(pd, it, present)
        n_boxes += bool(box)
        missing += n_missing
        lis.append(_item(it, counts, href, box, it.ref and _target(pd, it.ref[0])))
    more = ('<div class="sub today-also">Also below: %s</div>'
            % esc(" · ".join(_n(n, *k.also) for k, n in also))) if also else ""
    button = levels.group_button(pd, "Work through", n_boxes, missing) if n_boxes else ""
    return ('<section class="today" data-today="items">%s<div%s>%s<ul class="today-list">%s</ul></div>%s</section>'
            % (head, group_attr("today"), button, "".join(lis), more))


def sentence(pd):
    """The one sentence of an empty Today (§3.5): only counts above zero, never a fault word."""
    c = dict(pd.today_counts or {})
    g = c.get
    out = ["Nothing needs a decision from you right now." if g("roles") else "Nothing needs you right now."]
    if g("checked", True):
        if g("held_undecided"):
            out.append("%s at companies not yet put to you."
                       % _n(g("held_undecided"), "unread role is", "unread roles are"))
        if g("not_raised"):
            out.append("%s will be raised by later runs." % _n(g("not_raised"), "company", "companies"))
        if g("snoozed"):
            out.append("%s snoozed until next week." % _n(g("snoozed"), "company is", "companies are"))
        if g("held_watching"):
            out.append("%s at companies you are watching." % _n(g("held_watching"), "role waits", "roles wait"))
        if g("held_passed"):
            out.append("%s at companies you passed on." % _n(g("held_passed"), "role is", "roles are"))
        if g("waiting"):
            out.append("%s waiting to be read." % _n(g("waiting"), "role is", "roles are"))
        if g("in_progress"):
            age = g("in_progress_oldest_days")
            when = "" if age is None else "; the oldest started %s" % ("today" if not age else
                                                                       _n(age, "day", "days") + " ago")
            out.append("%s being read%s." % (_n(g("in_progress"), "role is", "roles are"), when))
        if g("ready"):
            out.append("%s ready and already decided." % _n(g("ready"), "role is", "roles are"))
    plan = pd.today_plan or []
    unverified = sum(1 for r in plan if r.get("group") == "awaiting-reply" and r.get("axis") == "silence-unverified")
    quiet = sum(1 for r in plan if r.get("group") == "awaiting-reply" and r.get("axis") == "silent")
    if g("not_due"):
        out.append("%s your last message and it is not yet time to nudge."
                   % _n(g("not_due"), "person has", "people have"))
    if unverified:
        out.append("%s waiting for a mailbox check." % _n(unverified, "person is", "people are"))
    if quiet:                       # every `silent` row here is long quiet: a recent one would be kind 11, not empty
        out.append("%s been quiet for a long time." % _n(quiet, "person has", "people have"))
    return " ".join(out)
