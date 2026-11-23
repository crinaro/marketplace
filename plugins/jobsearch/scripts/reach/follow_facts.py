"""follow_facts: the facts `reach.follow_rows.plan_people` reads, built from rows and functions its caller already holds (jobsearch
0.92.0, dev #1003; docs/design-decision-surface.md B.4, review round 2 G4).

`your_move.communication_plan` is the one caller. It passes its own functions (`conversation_axis`, `ended_because`,
`has_submitted_application`) and what it already loaded (`build_ended_context`, the Graph, the two config ints), so `your_move.py`
gains call sites only and no module here imports an entry point. `outbox_rows` reads `data/outbox.jsonl` strictly: a line that does
not read raises, and the caller names it in the plan's `failed`, never an empty outbox (an unreadable outbox is not "nothing in
hand"). The file name is spelled here because `reach` cannot import `validation` or `sending` (G6); tests/reach/test_follow_facts.py
pins it to `validation.outbox_rules.STORE_FILE`.

Python 3.9+, standard library only."""

import json
import os

from reach import keys as _keys
from reach.person_match import find_duplicates

REPLY_OWED_KEY = _keys.NETWORK_REPLY_OWED_DAYS
OUTBOX_FILE = "outbox.jsonl"
# The outbox states a message is still in hand in: queued for the candidate, staged in the mailbox, approved, or being sent. A
# `sent` row has already written its touch (sending/detect._sent_write); `discarded` and `failed` hold nothing.
OPEN_STATES = ("queued", "staged", "approved", "sending")


def outbox_rows(root):
    """Every row of `<root>/data/outbox.jsonl`, in file order; `[]` when the file is absent. A line that is not a JSON object
    raises `ValueError` naming it."""
    p = os.path.join(root, "data", OUTBOX_FILE)
    try:
        with open(p, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except FileNotFoundError:
        return []
    rows = []
    for n, line in enumerate(lines, 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError("%s line %d is not a JSON object" % (OUTBOX_FILE, n))
        rows.append(row)
    return rows


def outbox_open(rows):
    """`{person_id: row}` for the outbox rows still in hand (`OPEN_STATES`); the first such row of a person wins."""
    out = {}
    for r in rows:
        if r.get("state") in OPEN_STATES and r.get("person_id"):
            out.setdefault(r["person_id"], r)
    return out


def ended_reader(ctx, ended):
    """`ended_of(thread_id)`: `ended(opp, apps)` for a thread id that is an opportunity in `ctx` (`build_ended_context`'s
    `opps_by_id` and `apps_by_opp`), else None (a channel or person thread has no ending)."""
    opps, apps = ctx["opps_by_id"], ctx["apps_by_opp"]

    def ended_of(tid):
        return ended(opps[tid], apps.get(tid, [])) if tid in opps else None
    return ended_of


def facts(root, g, today, failed, axes, ended, applied, ctx, companies, chase, days):
    """The keyword arguments of `follow_rows.plan_people`. `axes(root, pid, today=, window=)` is `conversation_axis`, `ended` is
    `ended_because`, `applied(apps)` is `has_submitted_application`, `ctx` is `build_ended_context(root)`; `chase` and `days` are the
    chase window and `network.reply_owed_days`. An outbox that cannot be read is appended to `failed`."""
    try:
        in_hand = outbox_open(outbox_rows(root))
    except (OSError, ValueError) as e:
        failed.append("outbox: %s: %s" % (type(e).__name__, str(e)[:80]))
        in_hand = {}
    apps = ctx["apps_by_opp"]
    return {"axes_of": lambda pid: axes(root, pid, today=today, window=chase), "ended_of": ended_reader(ctx, ended),
            "applied_of": lambda oid: applied(apps.get(oid, [])), "opps": ctx["opps_by_id"], "companies": companies,
            "dup_pairs": find_duplicates(g.stores["people"]), "outbox_open": in_hand, "reply_owed_days": days, "chase": chase}
