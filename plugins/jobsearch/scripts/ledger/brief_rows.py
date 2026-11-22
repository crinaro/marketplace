"""ledger/brief_rows.py -- the brief ledger's row reader (`data/briefs.jsonl`, design-query-or-citation.md 3.6), moved out of
the entry point `brief.py` by `split_module.py` (jobsearch 0.91.0 B4b) so a capability module can resolve the row a draft cites
without importing an entry point (G5.L2). This module is one of `brief.LEDGER_READERS`, the allowlist `check_ledger_reads.py`
enforces; `brief.py` keeps the writer (`append_ledger`) and the strict reader.

Python 3.9+, standard library only."""

import json
import os


LEDGER = os.path.join("data", "briefs.jsonl")


def _ledger_path(root):
    return os.path.join(root, LEDGER)


def read_ledger(root):
    out = []
    try:
        with open(_ledger_path(root), encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
    except (OSError, ValueError):
        pass
    return out


def ledger_row(root, brief_id):
    """The ONE row this id names, or None. §3.6/§3.9: never 'newest for a person' — always the
    CITED id, because two runs briefing one person at once each cite their own row."""
    for r in read_ledger(root):
        if r.get("id") == brief_id:
            return r
    return None


def build_step(root, brief_id, out=print):
    """R2 N10: the BUILD step the ledger row `brief_id` names -- what `sending/detect.apply` takes as `ledger_lookup` and copies
    onto the sent touch by `detect.BUILD_FIELDS`. B4 NESTS the step on the row as `build`: a dict of fields, None (an ordinary
    reach-out), or `{"not_checked": why}`; a row written before 0.91.0 has no `build` key. So this returns `row["build"]`, never
    the row (whose top level carries no BUILD field). `not_checked`, and a cited id no ledger row has, copy nothing and say so
    on `out`, loudly: a touch with no `build_kind` must never read as an ordinary reach-out without a line saying why."""
    row = ledger_row(root, brief_id)
    if row is None:
        out("!! BUILD STEP NOT CHECKED for %s: no brief ledger row has that id; the touch records no build_kind" % brief_id)
        return None
    step = row.get("build")
    if isinstance(step, dict) and "not_checked" in step:
        out("!! BUILD STEP NOT CHECKED for %s: %s; the touch records no build_kind" % (brief_id, step["not_checked"]))
        return None
    return step if isinstance(step, dict) else None
