"""block: the derived `reach` block `access.py --json` carries on every row (jobsearch 0.91.0, design-build-reach.md 6.6).

    "reach": {
      "standing":       {"current": n, "former": n, "unconfirmed": n}     at the row's date, current employees only counted
      "confirm":        [person ids]                                      the unconfirmed people, each settled by one verb
      "path":           "direct" | "via-intro" | "none"                   the row's own path
      "side_asks_open": n                                                 sent side-door asks still awaiting (never a way in, O17)
      "side_door":      null | {opp_id, step, waiting_on, ...}            an ADOPTED side-door play not finished, whatever the
                                                                          path, so a pending note is never hidden by a path that
                                                                          opened another way
      "build":          [BUILD lines, ranked]                             `[]` unless the path is `none` (`reach/build.py`)
    }

NOTHING HERE IS STORED: the block is computed from the rows on each call, at the row's `as_of`, so there is no second copy of a fact
to drift (the access table's own rule; `test_access.py` plants a stored `reach` field and shows it is never read).

Imports no entry point: `g` is a `graph.Graph`, passed in. Capability module of `access.py`. Python 3.9+, standard library only."""

from _dates import to_date
from reach import build as _build
from reach import sidedoor as _sd
from reach.standing_rows import BUCKETS


def side_door(f, company_id, as_of):
    """The first (by role id) adopted side-door play at the company that has not finished, as `sidedoor.state` says, or None."""
    for opp in f.live_roles(company_id):
        if opp.get("id") not in f.door_opps:
            continue
        st = _sd.state(opp, f.touches_by_opp.get(opp.get("id"), ()), f.invs_by_opp.get(opp.get("id"), ()), f.people, as_of)
        if st is not None:
            return st
    return None


def reach(f, row, as_of):
    """The `reach` block for one `access.table` row (its `company_id`, `path` and `standing`), on `as_of`."""
    day = to_date(as_of)
    cid = row["company_id"]
    company = f.g.by_id["companies"].get(cid) or {"id": cid, "name": row.get("name")}
    standing = row.get("standing") or {}
    return {"standing": {b: len(standing.get(b) or ()) for b in BUCKETS},
            "confirm": list(standing.get("unconfirmed") or ()),
            "path": row["path"],
            "side_asks_open": _sd.open_asks(f.touches, cid, day),
            "side_door": side_door(f, cid, day),
            "build": _build.company_lines(f, company, day) if row["path"] == "none" else []}


def attach(g, root, cfg, warm_days, rows, as_of):
    """`rows` (from `access.table(..., as_of)`), each with its derived `reach` block added. Returns the same list."""
    f = _build.Facts(g, root, cfg, warm_days)
    for r in rows:
        r["reach"] = reach(f, r, as_of)
    return rows
