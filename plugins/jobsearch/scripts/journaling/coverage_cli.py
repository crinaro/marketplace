"""`journal.py --check-coverage`: the on-demand, network-needing half of coverage citations, moved out of `journal.py`'s `main` unedited
(jobsearch 0.94.0, dev 1065) so the entry point has room for the LinkedIn search flags without growing.

Is every `covered_by` citation of an open gap still open? It asks `issue_state` (the one impure call), prints one line per citation, keeps the
definite verdicts in `.jobsearch/coverage_check.json` for the routine offline `--check` (dev #711 / public #147), and returns 1 when a citation
is stale (closed or missing). Never run in CI: CI has neither `gh` nor a network.

Capability module of `journal.py`. Python 3.9+, standard library only."""

from journaling.coverage_claims import evaluate_coverage, issue_state, read_coverage_cache, write_coverage_cache
from journaling.journal_file import now_iso, read
from journaling.runs import open_gaps
from journaling.tables import COVERAGE_STATES, JournalError, _DATE_RE


def run_check_coverage(root, at):
    """Print the live lookup of every `covered_by` citation, keep the definite verdicts, and return the exit code (1 when any is stale).
    `at` is the call's ISO timestamp (its date stamps the verdicts)."""
    gaps = open_gaps(read(root))
    seen = {}

    def _recording_state(citation):
        seen[citation] = issue_state(citation)
        return seen[citation]

    verified_open, stale, unverifiable = evaluate_coverage(gaps, _recording_state)
    print("COVERAGE CHECK — live lookup against each covered_by citation\n")
    for citation, gap_ids in verified_open:
        print("  OK      %-16s covers %d gap(s), still open" % (citation, len(gap_ids)))
    for citation, gap_ids in unverifiable:
        print("  ??      %-16s NOT VERIFIED (no gh, no network, or no reachable repo)" % citation)
    if stale:
        print("\n  !! %d STALE COVERAGE — the citation is CLOSED or does not exist, so it has outlived whatever it was covering:"
              % len(stale))
        for citation, gap_ids in stale:
            print("      %-16s covers %d gap(s): %s" % (citation, len(gap_ids), ", ".join(gap_ids)))
    if not (verified_open or stale or unverifiable):
        print("  No covered gaps open. Nothing to verify.")
    # dev #711 / public #147 -- keep the answers, so the routine offline `--check` can use them. Only DEFINITE verdicts are stored; an
    # unverifiable lookup leaves that citation's previous verdict (and its date) as it was. A citation no open gap cites any more is dropped.
    old, problem = read_coverage_cache(root)
    cited = {g.get("covered_by") for g in gaps if g.get("covered_by")}
    verdicts = {c: v for c, v in old.items() if c in cited}
    day = at[:10] if _DATE_RE.match(at[:10]) else now_iso()[:10]
    for citation, state in seen.items():
        if state in COVERAGE_STATES:
            verdicts[citation] = {"state": state, "at": day}
    try:
        written = write_coverage_cache(root, verdicts, day)
        print("\n  verdicts kept for the offline --check: %s (%d citation(s))" % (written, len(verdicts)))
    except (JournalError, OSError) as e:
        print("\n  coverage cache NOT written (%s) -- the routine --check will read these citations as unverified" % e)
    return 1 if stale else 0
