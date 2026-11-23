"""piecehead: a piece's dated roles under schema 6's `pieceRoles` (design-adopt-parity-2 section 4.4), the one reading
both the piece page and the roles view print.

    roles(piece)                  [(title, dates or None)] of the piece's `role`, in the order written
    current_entries(piece, look)  the indices of the entries the piece marks current (in the order picked), () when it is
                                  not `current: true`
    current_entry(piece, look)    the first of them, or None
    card_entry(piece, look)       the entry a roles card shows: the current one, else the first
    roles_slot(builder, piece, out)  the gated `piece.wrap` `roles` slot

Which entry is current is data, never a reading of the order: under `current: true` it is the one `currentRole` names
(a position from 1), else the first (probe P-R was answered `default`: "the first"). Without `pieceRoles` nothing here
is read: `role` is what it was in 0.5.x and `currentRole` is a free key, so no tree 0.5.x accepted changes. A malformed
entry and a `currentRole` beyond the list were refused when the content was read (`contentmodel/pagefiles.py`), so a
`ValueError` here is a fault that is still turned into a refusal naming the piece, never a traceback.

0.7.0 (design-adopt-ownership-line section 6.2): which entries are current is read through the effective look's
`reads` `piece-roles.item-current` (`building/readsources.py`), still only under `current: true` (0.6.0's gate). With no
entry the chain is 0.6.0's, `currentRole` then the first. `look` defaults to None, which reads that chain: the roles
view's card (`views._dated_rows`) calls `card_entry` without one, so it does not read an entry yet."""

from contentmodel import keytables, pagefiles
from contentmodel.errors import ContentError

import looks

from building import readsources


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


def current_entries(piece, look=None):
    """The indices (from 0, in the order picked) of the entries the piece marks current under `current: true`: those
    the look's `reads` `piece-roles.item-current` picks, else `currentRole` minus one (absent, the first); () when the
    piece is not `current: true`. A position the entry reads outside the list is refused, naming the piece."""
    if piece.meta.get("current") is not True:
        return ()
    return readsources.choice(look, "piece-roles.item-current", piece.meta.get, lambda: len(roles(piece)), piece.source)


def current_entry(piece, look=None):
    """The index (from 0) of the first entry the piece marks current (`current_entries`); None when it is not
    `current: true`."""
    cur = current_entries(piece, look)
    return cur[0] if cur else None


def card_entry(piece, look=None):
    """The index of the entry a roles card shows for the piece: its current entry, else the first."""
    cur = current_entry(piece, look)
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
    cur = current_entries(piece, builder.look)
    items = []
    for i, (title, dates) in enumerate(entries):
        period = builder.r("piece-roles", "period", {"text": dates}, piece.source) if dates else ""
        items.append(builder.r("piece-roles", "item-current" if i in cur else "item",
                               {"title": title, "period": period}, piece.source))
    markup = builder.assets(out, "piece-roles") + builder.r("piece-roles", "wrap", {"items": "".join(items)},
                                                            piece.source)
    return looks.gate("piece", "wrap", "roles", keytables.active_triggers(
        builder.model.portfolio(piece.portfolio).settings), markup)
