"""The Network list: the communication plan's rows, by group, in three levels (dashboard-redesign A moved it from
generate_dashboard.py; D2b gives it its groups, sub-groups, levels and tick boxes: design-dashboard-redesign §4, §6.5,
§7.5).

THE LAYOUT (`layout(rows, pd)`, pure). The groups follow `pd.plan_groups` (`your_move.PLAN_GROUPS`, the plan's order);
`Awaiting a reply` is split into four sub-groups by the row's `state` (the conversation axis) and the age of its
`last_touch`, in the page's own words (§7.5, OURS; not `brief.register_for`):

    They accepted            state `accepted`                                          level 1, fold, count
    Went quiet recently      state `silent`, last touch <= `pd.quiet_days` days old    level 1, fold, count
    Quiet for a long time    state `silent`, older (or unreadable)                     a fold and a count ONLY
    Not checked yet          state `silence-unverified`                                ONE line, nothing to act on

Every other group is one list. Each list is `caps.levels(rows, caps.NETWORK_L1, pinned=<the keys Today took from
the Network>)`: level 1 open rows (Today's rows first), level 2 one-line rows in ONE closed fold, level 3 a count with
`data-more="network-<list>:<N>"` placed in the ledger's remainder. The Today rule for `Went quiet recently` is
`rank._recent`, the same function Today's kind 11 uses, so a row Today names is always in the open level.

THE ACTIONS (§6.5, design 6.1). Each group is one `data-pick-group` element with ONE button: `work-through` for To
record, `draft-message` for the rest. A row's tick box carries `data-pick` = its own `actions[0]["rec_id"]` and
`data-line` = the loader's record line. Python writes every character of a prompt: the loader fills
`pd.network_text` from `text_needed(layout)` (`{"heads": {action: head}, "lines": {row key: record line},
"tails": {group: tail}}`); this module only places those strings. Read-only: nothing here writes."""
import collections

from dashboard import caps, rank
from dashboard.actions_ui import group_attr, group_button, pick
from dashboard.markup import _rec_attrs, _ref_attrs, _ref_link, esc, plain, theirs


NETWORK_SECTION = "phase-network"

# group -> (heading, Today's anchor on its heading, the button's action, the button's label)
GROUPS = {
    "reply-owed": ("They wrote back", "today-src-network-reply-owed", "draft-message", "Draft replies"),
    "to-record": ("To record", "today-src-network-to-record", "work-through", "Work through"),
    "applied-no-contact": ("Applied, no one contacted yet", "today-src-network-applied-no-contact", "draft-message",
                           "Draft messages"),
    "awaiting-reply": ("Awaiting a reply", None, "draft-message", "Draft messages"),
    "referral-handoff": ("Introductions", "today-src-network-referral-handoff", "draft-message", "Draft messages"),
    "relationships-due": ("Relationships due this week", "today-src-network-relationships-due", "draft-message",
                          "Draft messages"),
}
# Awaiting a reply's sub-groups, in order: (id, heading, Today's anchor, mode). mode: rows | fold | line
SUBS = (("accepted", "They accepted", "today-src-network-accepted", "rows"),
        ("quiet-recent", "Went quiet recently", "today-src-network-quiet-recent", "rows"),
        ("quiet-long", "Quiet for a long time", None, "fold"),
        ("unverified", "Not checked yet", None, "line"))

Sub = collections.namedtuple("Sub", "id heading anchor mode open folded rest")


def _who_site(row):
    return {"applied-no-contact": "role-title", "to-record": "person-name"}.get(row["group"], "person-name")


def pick_key(row):
    """The record id a row's tick box carries: its first action's `rec_id` (None when it has no action)."""
    acts = row.get("actions") or []
    return acts[0]["rec_id"] if acts else None


def sub_of(row, day, days):
    """The Awaiting-a-reply sub-group of one row (the module docstring)."""
    state = row.get("state")
    if state in ("accepted", "silence-unverified"):
        return "accepted" if state == "accepted" else "unverified"
    return "quiet-recent" if day is not None and rank._recent(row, day, days) else "quiet-long"


def layout(rows, pd):
    """`[(group, [Sub])]`: the Network list's groups in `pd.plan_groups` order, each with its lists and their three
    levels (the module docstring). Empty groups and sub-groups are left out. Pure."""
    pinned = set(rank.pinned_for(rank.plan(pd)[0], "network"))
    day = pd.now.date() if pd.now is not None else None
    days = pd.quiet_days if pd.quiet_days is not None else 0
    out = []
    for g in pd.plan_groups:
        members = [r for r in rows if r["group"] == g]
        if not members:
            continue
        heading, anchor = GROUPS[g][0], GROUPS[g][1]
        parts = ([(sid, h, a, m, [r for r in members if sub_of(r, day, days) == sid]) for sid, h, a, m in SUBS]
                 if g == "awaiting-reply" else [(g, heading, anchor, "rows", members)])
        subs = []
        for sid, h, a, mode, rs in parts:
            if not rs:
                continue
            if mode == "line":
                lv = ([], [], rs)
            else:
                lv = caps.levels(rs, caps.NETWORK_L1 if mode == "rows" else 0,
                                 pinned=pinned if mode == "rows" else (), key=lambda r: r["key"])
            subs.append(Sub(sid, h, a, mode, *lv))
        out.append((g, subs))
    return out


def text_needed(lay):
    """What the loader must write for `lay`: `{"actions": [action], "lines": [(row key, rec_id, name)],
    "more": {group: rows of its lists not on the page}}` (a `Not checked yet` line has nothing to act on)."""
    actions, lines, more = [], [], {}
    for g, subs in lay:
        if GROUPS[g][2] not in actions:
            actions.append(GROUPS[g][2])
        more[g] = sum(len(s.rest) for s in subs if s.mode != "line")
        for s in subs:
            if s.mode != "line":
                lines.extend((r["key"], pick_key(r), r["who"]) for r in s.open + s.folded if pick_key(r))
    return {"actions": actions, "lines": lines, "more": more}


def _row(r, level, page_opp_keys, text, ledger):
    """One row: level 1 a full row, level 2 one line (who, why, a tick box). A role the page already renders under
    Opportunities or Applications is a reference (`data-ref`), so a record is never two primary rows."""
    is_ref = r["key"] in page_opp_keys
    if not is_ref:
        ledger.cover(r["key"], "rendered", "network")
    line = text["lines"].get(r["key"])
    box = pick(pick_key(r), line, r["who"], level=level) if line else ""
    bits = ['<div class="net-row%s"%s data-subject="%s" data-group="%s">%s<strong>%s</strong> <span class="sub">%s</span>'
            % ("" if level == 1 else " net-line", _ref_attrs(r["key"]) if is_ref else _rec_attrs(r["key"]),
               esc(r["subject"]), esc(r["group"]), box, theirs(r["who"], _who_site(r)), esc(plain(r["why"])))]
    if level == 1:
        if r.get("last_touch"):
            bits.append('<div class="sub">last touch %s</div>' % esc(str(r["last_touch"])))
        bits.append('<div class="sub">next: %s</div>' % esc(plain(r["next_step"])))
        if is_ref:
            bits.append(_ref_link(r["key"], "the role below"))
    return "".join(bits) + "</div>"


def _head(s, cls):
    n = len(s.open) + len(s.folded) + len(s.rest)
    return '<div class="sub %s"%s><strong>%s (%d)</strong></div>' % (cls, (' id="%s"' % s.anchor) if s.anchor else "",
                                                                     esc(s.heading), n)


def _levels(s, page_opp_keys, text, ledger):
    """One list's levels: open rows, ONE closed fold of one-line rows, and the count of the rest (`data-more`, placed
    in the ledger's remainder). A `Not checked yet` list is its one counted line."""
    if s.mode == "line":
        ledger.cover_set("network-%s" % s.id, [], [r["key"] for r in s.rest])
        return ('<div class="sub ws-more" data-more="network-%s:%d">%d %s waiting for a mailbox check. Nothing for you '
                'to do.</div>' % (s.id, len(s.rest), len(s.rest), "is" if len(s.rest) == 1 else "are"))
    out = [_row(r, 1, page_opp_keys, text, ledger) for r in s.open]
    if s.folded:
        out.append('<details class="net-fold"><summary>%s</summary>%s</details>'
                   % (esc(("%d more" if s.open else "%d, folded") % len(s.folded)),
                      "".join(_row(r, 2, page_opp_keys, text, ledger) for r in s.folded)))
    if s.rest:
        ledger.cover_set("network-%s" % s.id, [], [r["key"] for r in s.rest])
        out.append('<div class="sub ws-more" data-more="network-%s:%d">+ %d more that are not on this page. To see '
                   'them, say to the coordinator: Show me every row of %s.</div>'
                   % (s.id, len(s.rest), len(s.rest), esc(s.heading)))
    return "".join(out)


def _group(g, subs, page_opp_keys, text, ledger):
    """One group: one `data-pick-group` element holding its heading, its ONE button and its lists' tick boxes."""
    heading, _anchor, action, label = GROUPS[g]
    n_default = sum(1 for s in subs if s.mode != "line" for r in s.open if text["lines"].get(r["key"]))
    act = any(text["lines"].get(r["key"]) for s in subs for r in s.open + s.folded)
    button = ('<div class="net-actions">%s</div>'
              % group_button(label, text["heads"][action], text["tails"].get(g, ""), n_default)) if act else ""
    if g == "awaiting-reply":
        # the rows that need the reader, as the section's own count: a `Not checked yet` line is counted under its own
        # sub-heading, never here, so the button's prompt plus its `Not on the page` count equals this (§3.6 rule 5, X5)
        n = sum(len(s.open) + len(s.folded) + len(s.rest) for s in subs if s.mode != "line")
        body = ('<div class="sub net-head"><strong>%s (%d)</strong></div>' % (esc(heading), n) + button
                + "".join(_head(s, "net-head net-sub") + _levels(s, page_opp_keys, text, ledger) for s in subs))
    else:
        body = _head(subs[0], "net-head") + button + _levels(subs[0], page_opp_keys, text, ledger)
    return '<div class="net-group"%s>%s</div>' % (group_attr("network-%s" % g), body)


def _expired(expired):
    return ('<div class="sub net-expired">Expired this week (no contact made): %s</div>'
            % ", ".join(theirs("%s at %s" % (e["title"], e["company"]) if e["company"] else e["title"], "role-title")
                        for e in expired))


def render_network_list(plan, failed, page_opp_keys, ledger, pd):
    """The Network list is the COMMUNICATION PLAN (dev #914, #915; design 6.1): the rows of `your_move.
    communication_plan`, the ONE owner of membership, laid out by `layout` (the module docstring). Returns
    `(html, n_rows)`, `n_rows` the rows that need the reader (a `Not checked yet` row does not); `("", None)` when
    there is nothing to say and nothing failed. Every row carries `data-subject`, which `check_dashboard_coverage`'s
    SUBJECT TWICE reads. Footer of the applied group: the applications that expired this ISO week, each once.
    dashboard-redesign: `ledger` is the render's `Ledger`; the group order (`pd.plan_groups`) and every prompt
    fragment (`pd.network_text`) are the loader's values."""
    rows = (plan or {}).get("rows") or []
    expired = (plan or {}).get("expired_this_week") or []
    if not rows and not expired and not failed:
        return "", None
    parts = []
    if failed:
        parts.append('<div class="note">&#9940; <strong>The network list could not be computed</strong> (%s): '
                     'what is waiting on you here is UNKNOWN, not zero.</div>' % esc(plain(failed)))
    text = pd.network_text or {"heads": {}, "lines": {}, "tails": {}}
    lay = layout(rows, pd)
    for g, subs in lay:
        parts.append(_group(g, subs, page_opp_keys, text, ledger))
        if g == "applied-no-contact" and expired:
            parts.append(_expired(expired))
    if expired and not any(g == "applied-no-contact" for g, _s in lay):
        parts.append(_expired(expired))
    n = sum(len(s.open) + len(s.folded) + len(s.rest) for _g, subs in lay for s in subs if s.mode != "line")
    return ('<span id="phase-outreach-people"></span>'   # D6: the retired People-due block's anchor, kept empty
            '<h2 id="%s">&#129309; Network <span class="tcount">%d</span></h2>'
            '<div class="sub" style="margin:-6px 0 10px">Tick the rows you want, or none for the open rows, then use '
            'the group\'s button and paste the text into your session. Nothing here is sent for you.</div>'
            '<div class="card">%s</div>' % (NETWORK_SECTION, n, "".join(parts))), n
