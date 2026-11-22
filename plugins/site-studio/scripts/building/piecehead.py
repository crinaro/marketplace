"""piecehead: a piece's dated roles under schema 6's `pieceRoles` (design-adopt-parity-2 section 4.4), the one reading
both the piece page and the roles view print.

    roles(piece)                  [(title, dates or None)] of the piece's `role`, in the order written
    current_entry(piece)          the index of the entry the piece marks current, or None when it is not `current: true`
    card_entry(piece)             the entry a roles card shows: the current one, else the first
    roles_slot(builder, piece, out)  the gated `piece.wrap` `roles` slot

Which entry is current is data, never a reading of the order: under `current: true` it is the one `currentRole` names
(a position from 1), else the first (probe P-R was answered `default`: "the first"). Without `pieceRoles` nothing here
is read: `role` is what it was in 0.5.x and `currentRole` is a free key, so no tree 0.5.x accepted changes. A malformed
entry and a `currentRole` beyond the list were refused when the content was read (`contentmodel/pagefiles.py`), so a
`ValueError` here is a fault that is still turned into a refusal naming the piece, never a traceback."""

from contentmodel import keytables, pagefiles
from contentmodel.errors import ContentError

import looks


def on(builder, piece):
    """True when the piece's OWN portfolio holds `pieceRoles`."""
    return "pieceRoles" in keytables.active_triggers(builder.model.portfolio(piece.portfolio).settings)


def roles(piece):
    """[(title, dates or None)] of the piece's `role` (a list, or one line read as one entry); [] when it has none."""
    value = piece.meta.get("role")
    if value is None:
        return []
    try:
        return pagefiles.role_entries(value)
    except ValueError as e:
        raise ContentError("%s: front matter 'role' must be a list of roles, each Title (dates): %s" % (piece.source, e),
                           path=piece.source, fix="write each role as Title (dates), or remove pieceRoles")


def current_entry(piece):
    """The index (from 0) of the entry the piece marks current: `currentRole` minus one under `current: true` (absent,
    the first); None when the piece is not `current: true`."""
    if piece.meta.get("current") is not True:
        return None
    return int(piece.meta.get("currentRole", 1)) - 1


def card_entry(piece):
    """The index of the entry a roles card shows for the piece: its current entry, else the first."""
    cur = current_entry(piece)
    return 0 if cur is None else cur


def roles_slot(builder, piece, out):
    """The gated `piece.wrap` `roles` slot: `piece-roles.wrap` holding each entry in the order written, through `item`
    (`item-current` for the current entry) and its `period` part when the entry has dates, with the link to
    `schema-6.css`. "" without the trigger of the piece's own portfolio, or for a piece with no `role`."""
    if not on(builder, piece):
        return ""
    entries = roles(piece)
    if not entries:
        return ""
    cur = current_entry(piece)
    items = []
    for i, (title, dates) in enumerate(entries):
        period = builder.r("piece-roles", "period", {"text": dates}, piece.source) if dates else ""
        items.append(builder.r("piece-roles", "item-current" if i == cur else "item",
                               {"title": title, "period": period}, piece.source))
    markup = builder.assets(out, "piece-roles") + builder.r("piece-roles", "wrap", {"items": "".join(items)},
                                                            piece.source)
    return looks.gate("piece", "wrap", "roles", keytables.active_triggers(
        builder.model.portfolio(piece.portfolio).settings), markup)
