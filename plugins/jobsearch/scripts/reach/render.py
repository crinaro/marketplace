"""render: the reach table's text helpers, over the rows `access.table` returns (jobsearch 0.91.0, design-build-reach.md 12 B2).

The fixed-width grid, the one-line wording of a move, the by-vertical roll-up and the list of targets with no stated motivation.
Everything here reads the rows it is handed and nothing else: no store, no config, no clock. Moved out of `access.py` unchanged by
split_module.py (step B2-A), so the entry point can take the employment filter without growing.

Capability module of `access.py`. Python 3.9+, standard library only."""


PATHS = ("direct", "via-intro", "none")
NO_VERTICAL = "(none stated)"


def by_vertical(rows):
    """The market roll-up: one line per vertical, so a whole market with no path reads as one line."""
    out = {}
    for r in rows:
        v = r["vertical"] or NO_VERTICAL
        agg = out.setdefault(v, {"vertical": v, "companies": 0, "alumni": 0, "known": 0, "contacted": 0,
                                 "warm": 0, "chats_held": 0, "open_intros": 0, "posting_live": 0,
                                 "posting_newest": None, "paths": dict((p, 0) for p in PATHS)})
        agg["companies"] += 1
        for k in ("alumni", "known", "contacted", "warm", "chats_held", "open_intros"):
            agg[k] += r[k]
        agg["posting_live"] += r["posting"]["live"]
        agg["posting_newest"] = max(filter(None, [agg["posting_newest"], r["posting"]["newest"]]), default=None)
        agg["paths"][r["path"]] += 1
    return [out[k] for k in sorted(out)]


def unstated_motivation(rows):
    return [r["company_id"] for r in rows if r["motivation"] is None]


def _grid(header, body, left):
    """Fixed-width columns; the columns named in `left` are left-aligned text, the rest right-aligned."""
    widths = [max(len(str(x)) for x in col) for col in zip(header, *body)]
    lines = []
    for r in [header] + body:
        cells = [str(c).ljust(w) if i in left else str(c).rjust(w)
                 for i, (c, w) in enumerate(zip(r, widths))]
        lines.append("  ".join(cells).rstrip())
    return lines


def _fmt_move(m):
    if m["what"] == "target":
        return "new target (declared %s)" % m["on"]
    if m["what"] == "person":
        return "%s %s -> %s" % (m["person_id"], m["from"] or "not known", m["to"] or "not counted")
    if m["what"] == "standing":          # 0.91.0: an employment confirmation or departure, by its learned date
        return "%s employment %s -> %s" % (m["person_id"], m["from"] or "no link", m["to"] or "no link")
    return "%s %s -> %s" % (m["what"], m["from"], m["to"])


def standing_lines(rows):
    """The lines printed ABOVE the table (design-build-reach.md 5.5, owner O3 and O12), each only when it has people in it:

        EMPLOYMENT UNCONFIRMED: 3 people at 2 targets are counted, flagged, until you say whether they still work there: Globex
            (robin-example, sam-sample); Initech (jo-placeholder) -- `record.py employment <person_id> current|former`
        RE-CONFIRM: 1 person at 1 target still counted, last stated longer ago than the re-check window: ...

    `rows` are `access.table` rows; each carries `standing` (`reach.standing_rows.ids`)."""
    out = []
    for key, head, tail in (
            ("unconfirmed", "EMPLOYMENT UNCONFIRMED: %d %s at %d target%s %s counted, flagged, until you say whether they still "
                            "work there (never a way in): ", "`record.py employment <person_id> current|former`"),     # dev #1020
            ("reconfirm", "RE-CONFIRM: %d %s at %d target%s still counted, %s last stated longer ago than the re-check "
                          "window: ", "`record.py employment <person_id> current` (a re-confirmation is never shown as a move)")):
        hits = [(r["name"], (r.get("standing") or {}).get(key) or []) for r in rows]
        hits = [(name, ids) for name, ids in hits if ids]
        if not hits:
            continue
        n = sum(len(ids) for _name, ids in hits)
        verb = ("is" if n == 1 else "are") if key == "unconfirmed" else ("was" if n == 1 else "were")
        out.append(head % (n, "person" if n == 1 else "people", len(hits), "" if len(hits) == 1 else "s", verb)
                   + "; ".join("%s (%s)" % (name, ", ".join(ids)) for name, ids in hits) + " -- " + tail)
    return out
