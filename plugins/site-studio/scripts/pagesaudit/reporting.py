"""reporting.py -- what the Pages check prints: counts, the exit code, the summary line and the --json object.

EXIT CODES (OURS, following deploy.py):
  0  every item was checked and needs nothing (info and ok lines do not change this)
  3  amber: something to resolve, GitHub is still working, or something is NOT CHECKED
  1  the check could not run: no `gh` or logged out, site.json unreadable, no `publicRepo` (AM9: one
     line, "site.json has no publicRepo ..."), or `GET repos/<o>/<r>` failed
NOT CHECKED is never a pass: it is amber, and the line says why.


--json OUTPUT (AM7 asks it be stated): ONE object on stdout, always exiting as above:
  {"schema": 1, "repo": "<o>/<r>", "exit": 0|3|1,
   "summary": {"ok": n, "info": n, "resolve": n, "wait": n, "not_checked": n},
   "items": [{"key": "C12", "state": "resolve", "line": "...", "who": "..."}, ...]}
`state` is one of ok, info, resolve, wait, not_checked. When the check cannot run the object is
{"schema": 1, "repo": ..., "exit": 1, "error": "<one line>", "summary": {}, "items": []}. With `--raw`
(only with --json) the object also carries "raw": {"<path>": {"status": n, "data": ...}} holding every
response as GitHub sent it. THAT is how the owner captures the real-response fixture AM7 says is owed
(the key set below is DOCUMENTED, but only a real response proves the keys exist): run it read-only
against the owner's own live HTTPS custom-domain site, synthesize every identifier, and commit the
result as the fixture shape. A raw dump carries real logins and domains: never commit one unsynthesized.

"""

from pagesaudit.values import APPS_NOTE, EXIT_AMBER, EXIT_OK, EXIT_RED, STATES


def _n(items, state):
    return sum(1 for i in items if i.state == state)


def counts(items):
    return dict((st, _n(items, st)) for st in STATES)


def exit_code(items):
    amber = _n(items, "resolve") + _n(items, "wait") + _n(items, "not_checked")
    return EXIT_AMBER if amber else EXIT_OK


def summary_line(public_repo, items):
    return ("pages: %d to resolve, %d waiting, %d not checked on %s. %s"
            % (_n(items, "resolve"), _n(items, "wait"), _n(items, "not_checked"), public_repo, APPS_NOTE))


def as_json(public_repo, items, raw=None, error=None):
    obj = {"schema": 1, "repo": public_repo, "exit": EXIT_RED if error else exit_code(items),
           "summary": {} if error else counts(items),
           "items": [dict(i._asdict()) for i in items]}
    if error:
        obj["error"] = error
    if raw is not None:
        obj["raw"] = raw
    return obj
