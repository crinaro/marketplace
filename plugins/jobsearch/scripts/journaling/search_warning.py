"""search_warning: the per-page gate of the LinkedIn search and the recorder of a warning on any LinkedIn page (jobsearch 0.94.0, dev 1065; docs/design-role-first.md 19.5, 19.6;
criteria WN1, WN2, WN3; owner review 2026-11-25).

  linkedin_sweep.py search-warning --run <id> --n <plan n> (--result '<WARN_JS json>' | --tool-error)         a results page of a search
  linkedin_sweep.py page-warning   --run <id> --kind posting|reply (--result '<json>' | --tool-error)         a posting or reply page of any run

The runner calls this ONCE for each LinkedIn page it loads, with what `WARN_JS` returned (`browser_fallback/page_warning.py`), BEFORE it takes anything from the page. The word comes from
`page_warning`'s judge, never from the agent. THE OWNER'S RULE IS DOUBT = WARNING: a tool error, a timeout, an empty answer, an unparsable answer and a verdict this module cannot read are all
`WARNING unclear`, never `NO-PAGE`.

  ORDINARY   `PAGE ORDINARY cards=<n>` (a results page; `PAGE ORDINARY` for a posting or reply page), exit 0. A results page is also counted here (below); a posting or reply page writes nothing.
  WARNING    writes the `linkedin-warning` event (`kind`, `attended`, `n`, `at_utc`, and `reason` and `page` where there are some: never page text) and, for a search, the `returned` row
             (`jobsearch: unreachable`, `reason: linkedin-warning`); prints `STOP LINKEDIN WARNING kind=<kind>[ reason=<word>]. ...` and exits 3. The scheduled search is OFF from this instant
             until `journal.py --linkedin-search-on --attended --warning <date>`. When `reason` is `no-cards`, `cards-without-text` or `no-dismiss` the line says in words that this may be a LinkedIn
             layout change or a search with no results rather than a warning; it is still a warning (never a silent off).
  NO-PAGE    only a page of the browser itself (no LinkedIn page was shown): writes only the `returned` row of a search (`unreachable`, `not-readable`), prints `STOP NO-PAGE ...` and exits 3
             (`PAGE NO-PAGE ...`, exit 0, for a posting or reply page: nothing was shown, nothing is recorded).

ANY WARNING, FROM ANY RUN, ENDS EVERY RUN IN FLIGHT AT ITS NEXT CALL (WN2). A run's own warning is not the only one: `search_state.warning_for_run` is the newest warning appended after the run's `start`
row, whoever recorded it. A call for a run that ended (a warning that applies, or a `returned` row of its search) prints the same STOP and exits 3 WHATEVER the page says, and never reopens it. A run whose
search was ended by ANOTHER run's warning gets its own `returned` row at that call, so it is not left as a crashed pass.

THE GATE (results pages, in code, `search-warning`): a page that judges ORDINARY is counted in a `linkedin-search-page` row BEFORE `PAGE ORDINARY` is printed, and is refused when

  later-pair   `n` is a pair the plan marks LATER (`do: false`): only the pairs the search-plan dispatched run                                      `PAGE REFUSED reason=later-pair`   exit 3
  reopened     `n` was already judged in this run (a resume, a retry, a reopening): a page is judged ONCE                                         `PAGE REFUSED reason=reopened`     exit 3
  pass-cap     the run already judged `MAX_SEARCHES` (20) pages, or as many as the plan has `do` pairs                                           `STOP PAGE REFUSED reason=pass-cap` exit 3

A `PAGE REFUSED` line ends only that page (take nothing from it, do not retry it); a line that begins `STOP` ends the pass. A warning or a tool error is recorded whatever the gate says: a page that
should not have been opened is still a LinkedIn page. The links caps (25 a search, 500 a pass) are `search_links`'s, counted in the same rows.

NOT ENFORCED BY ANY SCRIPT: that the runner calls this for every page it opens (it is the runner's call); the gate refuses what it is shown. Two calls racing in the same instant can both read the journal before
either appends (the journal is an append-only file with no lock here).

Python 3.9+, standard library only."""

import inspect
import re

from browser_fallback import page_warning
from journaling import search_state as ss
from journaling.journal_file import now_iso, read
from journaling.row_kinds import record_linkedin_warning, record_search_page
from journaling.search_pass import record_search_pass
from journaling.tables import JournalError

EXIT_OK, EXIT_USAGE, EXIT_STOP = 0, 2, 3
MAX_SEARCHES = 20                   # results pages (one a search) in one pass (design 19.5; the owner's limit, held in code whatever the plan says)
PAGE_KINDS = ("posting", "reply")
STOP_TAIL = ("The pass ends here: open no other LinkedIn page in this run, do not retry or reopen this page, do not wait on it, do not sign in, do not answer it. "
             "File the ROLES block for the pairs you had already read (the rest are NOT-ATTEMPTED), then return.")
STOP_TAIL_PAGE = ("This run opens no other LinkedIn page: do not retry or reopen this page, do not wait on it, do not sign in, do not answer it. "
                  "Hand back what you already hold from the pages you had read (every role you did not reach is held for the next run), then return.")
REFUSED_TAIL = "Take nothing from this page and do not retry it: it is not opened again in this run."
_VERDICT_RE = re.compile(r"^(ORDINARY|WARNING|NO-PAGE)(?:\s+(.*))?$")
_WORD_RE = re.compile(r"^[a-z][a-z0-9-]{0,39}$")


def parse_verdict(line):
    """`(word, kind, cards, reason)` of a judge's verdict line: word `ordinary`, `warning` or `no-page`. A line this cannot read is `("warning", "unclear", None, "unparsable-verdict")`: doubt is a warning.
    Reads `ORDINARY cards=<n>` | `ORDINARY` | `WARNING <kind>[ reason=<word>]` | `NO-PAGE`; tolerates `reason=` and any token it does not know."""
    m = _VERDICT_RE.match(str(line or "").strip())
    if not m:
        return "warning", "unclear", None, "unparsable-verdict"
    head, rest = m.group(1), (m.group(2) or "").split()
    reason = next((t[len("reason="):] for t in rest if t.startswith("reason=") and _WORD_RE.match(t[len("reason="):])), None)
    if head == "ORDINARY":
        cards = next((int(t[len("cards="):]) for t in rest if re.fullmatch(r"cards=\d+", t)), None)
        return "ordinary", None, cards, None
    if head == "NO-PAGE":
        return "no-page", None, None, None
    kind = rest[0] if rest and rest[0] in ("sign-in", "challenge", "unusual-activity", "usage-limit", "restricted", "unclear") else None
    return ("warning", kind, None, reason) if kind else ("warning", "unclear", None, reason or "unparsable-verdict")


def judge_page(raw, tool_error=False, kind="results"):
    """`(word, kind, cards, reason)` for what `WARN_JS` returned on a `kind` page (`results`, `posting` or `reply`). A tool error, a blank answer and a judge that raises are warnings (`tool-error`,
    `empty-result`, `judge-error`). The judge is `page_warning.verdict(raw, kind=kind)`; an older one that takes no `kind` is called as `verdict(raw)`."""
    if tool_error:
        return "warning", "unclear", None, "tool-error"
    if raw is None or (isinstance(raw, (str, bytes, bytearray)) and not raw.strip()):
        return "warning", "unclear", None, "empty-result"
    try:
        takes_kind = "kind" in inspect.signature(page_warning.verdict).parameters
        line = page_warning.verdict(raw, kind=kind) if takes_kind else page_warning.verdict(raw)
    except Exception:                   # noqa: BLE001 - a judge that cannot answer is a doubtful page, never a crash and never an ordinary one
        return "warning", "unclear", None, "judge-error"
    return parse_verdict(line)


def _ended(recs, run_id):
    """`(warning, returned)`: the warning that applies to this run (any run's, appended after its start) and this run's own `returned` search row, either or both."""
    warn = ss.warning_for_run(recs, run_id)
    ret = next((r for r in reversed(recs) if r.get("event") == "pass" and r.get("kind") == "linkedin" and r.get("phase") == "returned"
                and r.get("scope") == "search" and r.get("run_id") == run_id), None)
    return warn, ret


def _stop(out, headline, tail=STOP_TAIL):
    out("STOP %s. %s" % (headline, tail))
    return EXIT_STOP


def _off_headline(kind, reason):
    """`LINKEDIN WARNING kind=<kind>[ reason=<word>]. [<what a reason means>] The scheduled LinkedIn search is OFF until the owner turns it on`."""
    row = {"kind": kind, "reason": reason}
    return "LINKEDIN WARNING kind=%s%s. %sThe scheduled LinkedIn search is OFF until the owner turns it on" % (
        kind, (" reason=%s" % reason) if reason else "", (ss.reason_note(row) + " ") if ss.reason_note(row) else "")


def _ended_headline(warn, ret):
    """What an already ended run says: its warning, or how its search returned."""
    if warn:
        return _off_headline(warn.get("kind"), warn.get("reason"))
    return "SEARCH RETURNED jobsearch=%s%s" % (ret.get("jobsearch"), (" reason=%s" % ret["reason"]) if ret.get("reason") else "")


def _refuse(out, reason, sentence, ends_pass=False):
    out("%sPAGE REFUSED reason=%s. %s %s" % ("STOP " if ends_pass else "", reason, sentence, STOP_TAIL if ends_pass else REFUSED_TAIL))
    return EXIT_STOP


def _page_rows(recs, run_id, step):
    return [r for r in recs if isinstance(r, dict) and r.get("event") == "linkedin-search-page" and r.get("run_id") == run_id and r.get("step") == step]


def gate_refusal(recs, disp, run_id, n):
    """`(reason, sentence, ends_pass)` for the first gate rule an ORDINARY results page of plan entry `n` breaks, else None (see the module docstring)."""
    entry = next(e for e in disp["plan"] if e["n"] == n)
    if not entry.get("do"):
        return "later-pair", "n=%d is a pair this search leaves for a later search, so its page is not opened in this pass." % n, False
    judged = {r["n"] for r in _page_rows(recs, run_id, "page")}
    if n in judged:
        return "reopened", "n=%d was already judged in this run: a results page is judged once, never reopened, retried or read again after a resume." % n, False
    limit = min(MAX_SEARCHES, sum(1 for e in disp["plan"] if e.get("do")))
    if len(judged) >= limit:
        return "pass-cap", "this pass has already judged %d results pages (at most %d, and no more than the plan's pairs)." % (len(judged), MAX_SEARCHES), True
    return None


def run(root, run_id, n, raw, tool_error=False, now=None, out=print):
    """Judge one results page and record what it ends. Returns 0 (ordinary, counted), 3 (stop or refused) or 2 (a call that names no search of this run)."""
    recs = read(root)
    disp = ss.dispatched_search(recs, run_id)
    if disp is None:
        out("search-warning: run %s has no search-plan dispatch: run `linkedin_sweep.py search-plan` first (nothing recorded)" % run_id)
        return EXIT_USAGE
    if n not in {e["n"] for e in disp["plan"]}:
        out("search-warning: --n %r is not a query of this run's plan (1..%d) (nothing recorded)" % (n, len(disp["plan"])))
        return EXIT_USAGE
    now = now or now_iso()
    warn, ret = _ended(recs, run_id)
    if warn or ret:
        if warn and not ret:        # ANOTHER run's warning ended this search: close it, so it is not left as a crashed pass
            record_search_pass(root, run_id, "linkedin", "returned", jobsearch="unreachable", reason="linkedin-warning", at=now)
        return _stop(out, _ended_headline(warn, ret))
    word, kind, cards, reason = judge_page(raw, tool_error, "results")
    if word == "ordinary":
        refusal = gate_refusal(recs, disp, run_id, n)
        if refusal:
            return _refuse(out, *refusal)
        record_search_page(root, run_id, n, "page", cards or 0, at=now)
        out("PAGE ORDINARY cards=%d" % (cards or 0))
        return EXIT_OK
    if word == "warning":
        record_linkedin_warning(root, run_id, kind, bool(disp.get("attended")), n, at=now, reason=reason)
        record_search_pass(root, run_id, "linkedin", "returned", jobsearch="unreachable", reason="linkedin-warning", at=now)
        return _stop(out, _off_headline(kind, reason))
    record_search_pass(root, run_id, "linkedin", "returned", jobsearch="unreachable", reason="not-readable", at=now)
    return _stop(out, "NO-PAGE reason=not-readable (no LinkedIn page was shown)")


def run_page(root, run_id, kind, raw, tool_error=False, now=None, out=print):
    """Judge one posting or reply page (`kind`) of run `run_id` (the owner's condition covers any LinkedIn page, 19.6). A warning is recorded exactly as a search's is (the scheduled search goes off, every
    opener refuses in this run) and ends the run's LinkedIn work; a page after a warning is not let through. Returns 0 (ordinary, or no page was shown) or 3 (stop). Nothing is written for an ordinary page."""
    if kind not in PAGE_KINDS:
        out("page-warning: --kind %r is not one of %s (nothing recorded)" % (kind, ", ".join(PAGE_KINDS)))
        return EXIT_USAGE
    warn = ss.warning_for_run(read(root), run_id)
    if warn:
        return _stop(out, _ended_headline(warn, None), STOP_TAIL_PAGE)
    word, wkind, _cards, reason = judge_page(raw, tool_error, kind)
    if word == "ordinary":
        out("PAGE ORDINARY")
        return EXIT_OK
    if word == "no-page":
        out("PAGE NO-PAGE: no LinkedIn page was shown (nothing recorded)")
        return EXIT_OK
    try:
        record_linkedin_warning(root, run_id, wkind, False, 1, at=now or now_iso(), reason=reason, page=kind)
    except JournalError:                # an unpinned profile cannot store the event: the page still ends this run's LinkedIn work, and the line says nothing was recorded
        return _stop(out, "%s (NOT RECORDED: this profile is not pinned to jobsearch 0.94.0 yet, so nothing could be written)" % _off_headline(wkind, reason), STOP_TAIL_PAGE)
    return _stop(out, _off_headline(wkind, reason), STOP_TAIL_PAGE)
