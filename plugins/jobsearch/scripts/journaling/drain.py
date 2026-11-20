"""The drain and readmit writers.

Capability module of `journal.py` (S4a, moved unedited)."""

from journaling.journal_file import append, now_iso, read
from journaling.row_shapes import _check_drain_row, _check_readmit_row
from journaling.tables import JournalError


def record_drain(root, run_id, phase, *, intake=None, capacity=None, capacity_reason=None,
                 render_route=None, attended=None, admitted=None, waiting=None, retry_stopped=None,
                 fanout=None, solo=None, fetch_calls=None, reserved_new=None, admitted_by_class=None,
                 excluded_open=None, finished=None, left=None, elapsed_s=None, per_role_s=None,
                 on_behalf_of=None, at=None, companies=None):
    """dev #820 / public #175 (design section 4.5, 17 N1, N7) -- the ONE writer of a `drain` event.

      companies (0.86.0, dev #834) an optional `planned` field: `{setting, admitted, considered, capped, split}`, the
                company figures of a plan whose intake is counted in companies (`_check_companies_block`). The same
                check the reader runs is run HERE before anything is appended; a `closed` row carrying it is refused.

      planned   `lifecycle.Plan.event_fields()`: intake, capacity (+ capacity_reason whenever it is below
                intake), render_route, attended, admitted {opps, items}, waiting {count, oldest},
                retry_stopped, fanout, solo, fetch_calls, reserved_new, admitted_by_class,
                excluded_open. One per run: a second is refused.
      closed    `admitted` (an INTEGER here: how many were admitted), `finished`, `left` {id: cause}
                with `finished + len(left) == admitted`, and for the run's own close `elapsed_s` and
                `per_role_s` (the measured rate N7's time cap reads). `on_behalf_of=<closing run>`
                marks a close written for a run that went silent; it measures nothing.

    EXACTLY ONE EFFECTIVE CLOSE PER RUN: a second own close for the run is refused, and a second
    on-behalf close is refused. The run's own close is still accepted after an on-behalf one (the
    run went silent past the window and then came back); `lifecycle.closed_event` reads the own close
    first. A close needs the run to have a plan."""
    at = at or now_iso()
    if isinstance(admitted_by_class, dict) and admitted_by_class.get("held") == 0:
        admitted_by_class = {k: v for k, v in admitted_by_class.items() if k != "held"}     # 0.85.0: held only when > 0
    rec = {"event": "drain", "phase": phase, "run_id": run_id, "at": at}
    planned = dict(intake=intake, capacity=capacity, render_route=render_route, attended=attended,
                   admitted=admitted, waiting=waiting, retry_stopped=retry_stopped, fanout=fanout,
                   solo=solo, fetch_calls=fetch_calls, reserved_new=reserved_new,
                   admitted_by_class=admitted_by_class, excluded_open=excluded_open)
    closed = dict(finished=finished, left=left, elapsed_s=elapsed_s, per_role_s=per_role_s)
    if companies is not None:
        rec["companies"] = companies
    if phase == "planned":
        rec.update({k: v for k, v in planned.items()})
        if capacity_reason is not None:
            rec["capacity_reason"] = capacity_reason
        rec.update({k: v for k, v in closed.items() if v is not None})
        if on_behalf_of is not None:
            rec["on_behalf_of"] = on_behalf_of
    else:
        rec["admitted"] = admitted
        rec.update({k: v for k, v in closed.items() if v is not None})
        rec.update({k: v for k, v in planned.items() if v is not None and k != "admitted"})
        if capacity_reason is not None:
            rec["capacity_reason"] = capacity_reason
        if on_behalf_of is not None:
            rec["on_behalf_of"] = on_behalf_of
    _check_drain_row(rec)
    existing = [r for r in read(root) if r.get("event") == "drain" and r.get("run_id") == run_id]
    if phase == "planned":
        if any(r.get("phase") == "planned" for r in existing):
            raise JournalError("run %r already has a drain plan: a run plans once" % run_id)
    else:
        if not any(r.get("phase") == "planned" for r in existing):
            raise JournalError("run %r has no drain plan, so there is nothing to close" % run_id)
        kind_of = lambda r: "behalf" if r.get("on_behalf_of") else "own"   # noqa: E731
        mine = "behalf" if on_behalf_of else "own"
        if any(r.get("phase") == "closed" and kind_of(r) == mine for r in existing):
            raise JournalError("run %r already has a %s close: exactly one close of each kind is "
                               "allowed, and the run's own close outranks one written on its behalf"
                               % (run_id, "on-behalf" if on_behalf_of else "own"))
    return append(root, rec)


def record_readmit(root, ids, by, cause, at=None):
    """dev #840 / public #181 -- the ONE writer of a `readmit` event: `{event, at, by, cause, ids}`. `cause` must
    be a role-class cause and `ids` non-empty and distinct; nothing is appended on a refusal. Returns the row."""
    rec = {"event": "readmit", "at": at or now_iso(), "by": by, "cause": cause,
           "ids": list(ids) if isinstance(ids, (list, tuple)) else ids}
    _check_readmit_row(rec)
    return append(root, rec)
