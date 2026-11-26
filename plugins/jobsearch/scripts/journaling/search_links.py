"""search_links: `search_page.py links --run <id> --n <n>`, the owner's link limits held in code (jobsearch 0.94.0, dev 1064, 1065; docs/design-role-first.md 7.4, 19.5; OD-10, OD-11;
owner review 2026-11-25).

  search_page.py links --run <id> --n <plan n> --match <roles file> --result '<LINKS_JS json>' [--tool-error]

The ids of a results page are printed ONLY for a page this run's gate judged ORDINARY (`search-warning` counted it), at most `MAX_LINKS_SEARCH` (25) for the search and at most `MAX_LINKS_PASS` (500) for the
pass, and each page's links are taken ONCE. What was printed is counted in a `linkedin-search-page` row (`step: links`, `count`) BEFORE it is printed, so the caps hold across a crash and a resume. The lines:

  LINKS ...            the verdict (`link_read.read_verdict`), counting only the ids printed; then `ID <k> <id> <url>` / `NOURL <k>` per role; then, when ids were cut, `LIMIT links kept=<k> of <m>: ...`   exit 0
  LINKS REFUSED reason=<word>. <why>   then `NOURL <k>` for every role: no id is taken                                                                                                              exit 3
      page-not-judged  the page of plan entry `n` was never judged ordinary in this run (the gate is `search-warning`; a page not shown to it gives no ids)
      already-read     this page's links were taken once already (a page is read once, never again after a resume)
      pass-cap         the pass has taken its 500
  STOP ...             the run ended (a warning of any run after it began, or its own `returned` row): the same STOP `search-warning` prints; no id is taken                                        exit 3
  search-links: ...    a call that names no search of this run, or no plan entry of it (nothing recorded)                                                                                          exit 2

NOT ENFORCED BY ANY SCRIPT: that the runner runs `LINKS_JS` only through this call (it is the runner's own call to the page; this script refuses what it is handed, so ids it does not print are ids the
roles file cannot carry).

Capability module of `search_page.py` through `journal.py`. Python 3.9+, standard library only."""

from browser_fallback import link_read
from journaling import search_state as ss
from journaling import search_warning as sw
from journaling.journal_file import now_iso, read
from journaling.row_kinds import record_search_page

EXIT_OK, EXIT_USAGE, EXIT_STOP = 0, 2, 3


def _rows(recs, run_id, step, n=None):
    return [r for r in recs if isinstance(r, dict) and r.get("event") == "linkedin-search-page" and r.get("run_id") == run_id and r.get("step") == step
            and (n is None or r.get("n") == n)]


def _refused(out, reason, sentence, roles_text):
    out("LINKS REFUSED reason=%s. %s No id is taken: every role stays `ROLE nourl`." % (reason, sentence))
    for k in range(len(link_read.roles_of(roles_text))):
        out("NOURL %d" % (k + 1))
    return EXIT_STOP


def run(root, run_id, n, roles_text, raw, tool_error=False, now=None, out=print):
    """Gate and print the links of the results page of plan entry `n`. Returns 0, 3 (stop or refused) or 2 (a call that names no search of this run)."""
    recs = read(root)
    disp = ss.dispatched_search(recs, run_id)
    if disp is None:
        out("search-links: run %s has no search-plan dispatch: run `linkedin_sweep.py search-plan` first (nothing recorded)" % run_id)
        return EXIT_USAGE
    if n not in {e["n"] for e in disp["plan"]}:
        out("search-links: --n %r is not a query of this run's plan (1..%d) (nothing recorded)" % (n, len(disp["plan"])))
        return EXIT_USAGE
    warn, ret = sw._ended(recs, run_id)
    if warn or ret:
        return sw._stop(out, sw._ended_headline(warn, ret))
    if not _rows(recs, run_id, "page", n):
        return _refused(out, "page-not-judged", "The results page of n=%d was not judged ordinary in this run (`search-warning` counts the pages it passes)." % n, roles_text)
    if _rows(recs, run_id, "links", n):
        return _refused(out, "already-read", "The links of n=%d were already taken in this run: a page is read once." % n, roles_text)
    room = link_read.MAX_LINKS_PASS - sum(r["count"] for r in _rows(recs, run_id, "links"))
    if room <= 0:
        return _refused(out, "pass-cap", "This pass has already taken its %d links." % link_read.MAX_LINKS_PASS, roles_text)
    lines = link_read.match_lines(raw, roles_text, tool_error, limit=min(link_read.MAX_LINKS_SEARCH, room))
    record_search_page(root, run_id, n, "links", sum(1 for line in lines if line.startswith("ID ")), at=now or now_iso())
    for line in lines:
        out(line)
    return EXIT_OK
