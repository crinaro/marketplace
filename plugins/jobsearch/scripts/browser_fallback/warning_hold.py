"""warning_hold: has LinkedIn warned since this run began? (jobsearch 0.94.0, dev 1064; docs/design-role-first.md 19.6 WN2)

Capability module of `route.py` (through `rungs.run_cli`): `route.py --next --step posting-read-linkedin --run <id>` prints `NEXT held ... REASON linkedin-warning` for a role whose run
began before the newest `linkedin-warning` row of the journal, so the run opens no further LinkedIn page.

THE RULE IS `journaling.search_state.warning_for_run`, AND THIS IS A COPY OF IT, ON PURPOSE. This package may not import `journaling`: `route.py` is imported by `validate_data.py` and
`channels_due.py`, so an import of `journaling` from here put those into one import cycle and grew the largest cycle of the plugin (G6, measured). The copy is small (the last warning
in the file; applies when it was appended after the run's `start` row; a run with no `start` row on record is treated as begun before every warning, the safe direction) and is held
equal to the original by `tests/browser_fallback/test_warning_hold.py`, which runs both over the same journals, so the two cannot drift.

It reads the journal file TOLERANTLY: a missing file is no warning (as `journal.read`), a line that is not JSON is NOT CHECKED (`ValueError`, which `run_cli` prints as `!! NO NEXT RUNG`:
a journal that cannot be read protects nothing, and a posting must not slip through it). It does not validate rows: `journal.read` does, and the writer refuses a bad one.

Python 3.9+. Standard library only."""

import json
import os

JOURNAL = os.path.join("data", "runs.jsonl")      # `journaling.journal_file.JOURNAL` under the profile root (a test holds the two equal)


def _rows(root):
    """Every row of the journal under `root`, in file order. `ValueError` on a line that is not a JSON object."""
    out = []
    try:
        with open(os.path.join(root, JOURNAL), encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    raise ValueError("%s line %d is not valid JSON: a journal that cannot be read protects nothing" % (JOURNAL, n))
                if not isinstance(rec, dict):
                    raise ValueError("%s line %d is not a row" % (JOURNAL, n))
                out.append(rec)
    except FileNotFoundError:
        pass
    return out


def warning_applies(recs, run):
    """The `linkedin-warning` row that applies to run `run` in `recs`, or None: the LAST warning in the file (by ANY run), when it was appended AFTER the run's earliest `start` row. A run whose
    start is not on record is treated as begun before every warning. Position in the file decides, never a stamp (a clock set back stamps a later row earlier). The same answer as
    `journaling.search_state.warning_for_run`."""
    last, first_start = None, None
    for i, r in enumerate(recs):
        if r.get("event") == "linkedin-warning":
            last = (i, r)
        elif r.get("event") == "start" and r.get("run_id") == run and first_start is None:
            first_start = i
    if last is None:
        return None
    return last[1] if first_start is None or last[0] > first_start else None


def held(root, run):
    """The warning that holds a LinkedIn posting of run `run` under profile root `root`, or None. `ValueError` when the journal cannot be read."""
    return warning_applies(_rows(root), run)
