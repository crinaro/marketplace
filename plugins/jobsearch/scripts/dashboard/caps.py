"""The page's caps and its three levels (dashboard-redesign D1; design-dashboard-redesign §4, decision D-4).

The caps are CONSTANTS here, never config keys (D-4, approved). `network.targets_per_week` stays the one cap the reader
sets, because it already exists; the Targets list reads it from `targets_review`, not from this module.

    DRAFTS_L1      5    Drafts, ready and needs-you, open rows
    NETWORK_L1     3    each Network group and sub-group, open rows
    NEEDS_READ_L1  3    Needs your read
    OPPS_L1        5    Opportunities, open cards
    APPS_L1        5    Applications to finish
    RECONSIDER_L1  3    Roles to reconsider
    LEVEL2        20    one-line rows inside ONE closed fold, per list or group, every fold (the Drafts waiting fold too)
    TODAY_CAP      5    Today's items (§3.2, D-1)

THE CONTRACT every section builds its list with (D2 relies on it; §3.6 rule 2, §4):

    levels(rows, l1, l2=LEVEL2, pinned=(), key=lambda r: r) -> (open, folded, rest)

- `rows` is the section's list in its OWNER's order (`precondition`, `communication_plan`, `targets_review`, ...).
  `levels` never re-sorts it: every output list keeps that order.
- level 1, `open`: the rows whose `key(row)` is in `pinned` (the keys Today took from this section,
  `rank.pinned_for`), in owner order, THEN the head of the owner's order, until `open` holds `l1` rows. The cap
  STRETCHES to hold every pinned row: six pinned rows with `l1=5` give six open rows, never five. A pinned key with
  no row in `rows` is ignored (it adds nothing and stretches nothing).
- level 2, `folded`: the next `l2` rows of what is left, in owner order.
- level 3, `rest`: everything after that, in owner order. The caller counts it ("+ N more that are not on this
  page", `data-more="<list>:<N>"`) and places it in the ledger's remainder (`Ledger.cover_set`).
- Every row is in exactly one of the three; `open + folded + rest` is a permutation of `rows`.
Pure: no I/O, no clock, no import beyond the standard library."""

DRAFTS_L1 = 5
NETWORK_L1 = 3
NEEDS_READ_L1 = 3
OPPS_L1 = 5
APPS_L1 = 5
RECONSIDER_L1 = 3
LEVEL2 = 20
TODAY_CAP = 5


def _identity(row):
    return row


def levels(rows, l1, l2=LEVEL2, pinned=(), key=_identity):
    """`(open, folded, rest)`: the three levels of one list (the module docstring is the contract)."""
    rows = list(rows)
    pinned = set(pinned)
    first = [r for r in rows if key(r) in pinned]               # owner order, because `rows` is
    others = [r for r in rows if key(r) not in pinned]
    room = max(int(l1) - len(first), 0)                          # the cap stretches: never below the pinned rows
    left = others[room:]
    return first + others[:room], left[:int(l2)], left[int(l2):]
