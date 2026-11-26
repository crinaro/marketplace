"""jobsearch_line: the LinkedIn job search's off switch and the `JOBSEARCH` line of the worklist (jobsearch 0.94.0, step P0; dev 1055,
1064, 1065; docs/design-role-first.md section 13). Moved out of `linkedin_sweep.py`, which keeps both names and the old signatures
as thin wrappers. No behaviour change when moved; changed since in 0.94.0 (below).

  job_search_is_off   True when the `linkedin-jobsearch` channel row is `relationship_status: retired` (dev #774).
  jobsearch_line      `JOBSEARCH off source=linkedin-jobsearch` (turned off), `... reason=own-dispatch` (a pinned profile) or `... reason=migration-pending` (an unpinned one: no unattended
                      LinkedIn job search runs while the 0.94.0 migration is pending). The `JOBSEARCH window=...` line is printed by no profile any more.

ONE EDIT, stated: `jobsearch_line` takes the `journal` module as its second argument. `journal.py` is an entry point and a package
imports none (G5); moved with its own `import journal` it also grew the plugin's largest import cycle from 39 to 40 (G6, measured
2026-11-25 with `scripts/check_segmentation.py`). The body is otherwise the moved text: the one function-level `import json` it
carried is now this module's own.

Python 3.9+, standard library only."""

import json
import os

JOBSEARCH_CHANNEL = "linkedin-jobsearch"       # the channel id every LinkedIn job-search sighting is written with
OWN_DISPATCH_LINE = "JOBSEARCH off source=%s reason=own-dispatch" % JOBSEARCH_CHANNEL      # a pinned profile's reply worklist; the prefix an older runner obeys is unchanged
MIGRATION_PENDING_LINE = "JOBSEARCH off source=%s reason=migration-pending" % JOBSEARCH_CHANNEL      # an UNPINNED profile's reply worklist: the 0.93.0 reply-pass search has no warning stop


def job_search_is_off(root):
    """dev #774 (design-source-catalog.md section 4.1): True when the user turned the LinkedIn job search off, i.e. the
    `linkedin-jobsearch` channel row is `relationship_status: retired` -- the same off bit `alert_sweep.py`,
    `channels_due.py` and `portfolio_boards.py` already honour for every other channel, written by
    `record.py source off linkedin-jobs`. A MISSING row, or one that is not retired, is NOT off (an install older than
    0.76.0 never had to hold the row, and its search ran). A channels store that cannot be read is not read as off
    either: `validate_data.py` reports the unreadable store at run start; an off switch nobody can read must not
    silently turn a search off."""
    path = os.path.join(root, "data", "channels.jsonl")
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and row.get("id") == JOBSEARCH_CHANNEL:
                    return row.get("relationship_status") == "retired"
    except OSError:
        return False
    return False


def jobsearch_line(root, journal, now=None):
    """dev #489 / public #102 + #692 (R5) -- the `JOBSEARCH` line of the worklist: which LinkedIn job-search window THIS pass runs, printed by a
    script so the runner never hard-codes one. `window=wide f_TPR=r604800 titles=all` (LinkedIn's weekly bucket) unless every pair this pass would run
    was reached within the last 24 hours, then `window=daily f_TPR=r86400 titles=configured` (dev 1055, 0.94.0: the one window rule is
    `query_plan.window`; the weekly "wide re-scan is due" state and its `wide-due-since` suffix retired, because a scheduled run could never satisfy
    them). Only LinkedIn's own UI buckets exist (R5): there is no computed window. The geographies are computed here from config (`remote`, plus
    `local` when `geography.commute_anchors` is non-empty), never self-reported by the runner. On a profile with no stored pairs (no 0.94.0 pin) no pair
    has been reached, so the weekly bucket applies. `journal` is the `journal` module (`jobsearch_geos`, `now_iso`, `read`), passed in because a package
    imports no entry point.

    0.94.0 (dev 1065, owner review 2026-11-25): a PINNED profile prints `OWN_DISPATCH_LINE` (the search is its own dispatch), an UNPINNED one `MIGRATION_PENDING_LINE`: the window line above is
    no longer printed by any profile, because the 0.93.0 reply-pass search has no warning stop and no unattended LinkedIn job search may run while the migration is pending. `now` is kept for the
    callers' signature."""
    if job_search_is_off(root):
        return "JOBSEARCH off source=%s" % JOBSEARCH_CHANNEL
    if journal.pin_missing_line(root, "the reply pass's search") is None:
        return OWN_DISPATCH_LINE        # 0.94.0 (dev 1065, design 8.1, 19.5): the search is its own dispatch (`search-plan`); the reply pass reads replies only
    return MIGRATION_PENDING_LINE       # 0.94.0 (dev 1065, owner review 2026-11-25): while the migration is pending NO unattended LinkedIn job search runs; the reply pass has no warning stop of its own to run one under
