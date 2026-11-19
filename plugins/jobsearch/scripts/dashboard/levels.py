"""The three levels' shared markup (dashboard-redesign D2; design-dashboard-redesign §4, §6.1). Pure: no I/O, no clock.

    split(rows, l1, pd, section, key)        -> (open, folded, rest)   `caps.levels`, pinned to what Today took
    row_pick(pd, key, label, level)          -> html   a row's tick box, from the loader's `pd.pick_rows`
    group_button(pd, label, n_default, more) -> html   a group's ONE `work-through` button ("" with no level-1 box)
    fold(summary, rows_html)                 -> html   level 2: one closed `<details>` per list or group
    more_line(set_name, n, what, ask)        -> html   level 3: the counted line, `data-more="<set>:<n>"`
    showing(n, m)                            -> html   a heading's "showing N of M"

THE PICK ROWS. The loader (`generate_dashboard._load_picks`) writes `pd.pick_rows` = {page key: (action record id,
`action_block.record_line(id, name)`)} for every row a section can tick, and `pd.pick_heads` = {action:
`action_block.head(action)`}. Python writes every character of a prompt and this module only places them; `tail(more)`
is the one fragment written here, because `more` (the rows past level 2) is known only once a list is split, and
`action_block.tail` is a pure function of that count. A row with no pick row is refused (KeyError), never rendered
without its box: a box that silently went missing is a row the button cannot reach.
"""
from dashboard import caps, rank
from dashboard.action_block import tail
from dashboard.actions_ui import group_button as _button, pick
from dashboard.markup import esc

ACTION = "work-through"


def split(rows, l1, pd, section, key):
    """`caps.levels(rows, l1, pinned=<the keys Today took from section>)`: level 1 holds every row Today names."""
    return caps.levels(rows, l1, caps.LEVEL2, pinned=rank.pinned_for(rank.plan(pd)[0], section), key=key)


def row_pick(pd, key, label, level):
    """The tick box of the row whose page key is `key` (`level` 1 open, 2 folded)."""
    rec, line = (pd.pick_rows or {})[key]
    return pick(rec, line, label, level=level)


def group_button(pd, label, n_default, more, action=ACTION):
    """A group's ONE button: `head(action)` from the loader, `tail(more)` here. "" when no level-1 box exists."""
    if not n_default:
        return ""
    return '<div class="pick-bar">%s</div>' % _button(label, (pd.pick_heads or {})[action], tail(more), n_default)


def fold(summary, rows_html):
    return '<details class="lvl2"><summary>%s</summary>%s</details>' % (esc(summary), rows_html) if rows_html else ""


def more_line(set_name, n, what, ask):
    """Level 3: "+ N more <what> that are not on this page", its `data-more`, and the sentence that shows them."""
    if not n:
        return ""
    return ('<div class="sub ws-more" data-more="%s:%d">+ %d more %s that %s not on this page. To see them, say to '
            'the coordinator: &ldquo;%s&rdquo;</div>' % (esc(set_name), n, n, esc(what), "is" if n == 1 else "are",
                                                         esc(ask)))


def showing(n, m):
    return ' <span class="ct2f">showing %d of %d</span>' % (n, m)
