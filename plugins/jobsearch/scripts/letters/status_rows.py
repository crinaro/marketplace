"""The cover letters as rows of the status panel's `gates[]` (jobsearch 0.95.0; dev 1071, review item 2; design § 8.2, § 11).

The dashboard's one line says `N letters not ready; /jobsearch:status lists why.` (or `Letters not checked; /jobsearch:status says
why.`), and `/jobsearch:status` runs `panel.py --text --full`. So `--full` carries the reasons, and this module turns
`letter_out.py --check --json` into the rows. The check runs as a CHILD (`letter_out.py` is an entry point and is never
imported, G5.L2), is read-only, and is not run by `--fast`.

* `run(root, here)`    the rows: runs `<here>/letter_out.py --check --json` against the profile `root`, 40 s at most.
* `rows(rc, out, err)` the rows for an exit code and output (pure, so tested without a child). Nothing wrong is ONE ok row
                       `{name: "letters", ok: true}`. Otherwise one row per writing-rules problem (`letters: writing rules`), per
                       not-ready letter (`letters: <heading>`, `detail` its first FAIL and `(+N more)`), per open `letter-stopped`
                       ask (`letters: no letter written`, `detail` its title), or the letter guide's verdict when the exit was 1
                       and nothing else says why. A check that cannot say (`not_checked`, an exit other than 0 or 1, output that
                       is not the object, a timeout, a child that cannot start) is ONE row `{name: "letters", ok: null, error:
                       "NOT CHECKED (<why>)"}`, never no row.
* `state_text(row)`    what the text view prints after `<name>:` for a `gates[]` row: `ok`, the row's `error`, or `FAILING` and
                       its `detail`.

Standard library only. Python 3.9+.
"""

import json
import os
import subprocess
import sys

NAME = "letters"
TIMEOUT_S = 40          # the check runs its own `lifecycle.py --report` child (60 s cap); the mod waits 60 s for the whole panel


def unchecked(why):
    return [{"name": NAME, "ok": None, "error": "NOT CHECKED (%s)" % why}]


def rows(rc, out, err=""):
    try:
        rep = json.loads(out)
    except ValueError:
        rep = None
    if not isinstance(rep, dict) or rc not in (0, 1):
        return unchecked("exit %s, %s" % (rc, ((err or out or "").strip().splitlines() or ["no output"])[-1][:120]))
    if "not_checked" in rep:
        return unchecked(str(rep["not_checked"])[:160])
    if not all(isinstance(rep.get(k), list) for k in ("problems", "letters", "stops")):
        return unchecked("the check printed an object this panel cannot read")
    found = [{"name": "%s: writing rules" % NAME, "ok": False, "detail": str(p)} for p in rep["problems"]]
    for r in rep["letters"]:
        fails = [str(f) for f in (r.get("fails") or [])] if isinstance(r, dict) else []
        if fails:
            found.append({"name": "%s: %s" % (NAME, r.get("heading")), "ok": False,
                          "detail": fails[0] + (" (+%d more)" % (len(fails) - 1) if len(fails) > 1 else "")})
    for a in rep["stops"]:
        found.append({"name": "%s: no letter written" % NAME, "ok": False,
                      "detail": str((a or {}).get("title") or (a or {}).get("id") or "an open letter-stopped ask")})
    if rc == 1 and not found:       # a FAIL the object does not itemise: the letter guide's own verdict
        found.append({"name": "%s: letter guide" % NAME, "ok": False, "detail": str(rep.get("guide") or "the check failed")})
    return found or [{"name": NAME, "ok": True}]


def run(root, here):
    try:
        p = subprocess.run([sys.executable, os.path.join(here, "letter_out.py"), "--check", "--json"], capture_output=True,
                           text=True, env=dict(os.environ, CLAUDESEARCH_ROOT=root), timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return unchecked("timed out after %d s" % TIMEOUT_S)
    except OSError as e:
        return unchecked("%s: %s" % (type(e).__name__, str(e)[:120]))
    return rows(p.returncode, p.stdout, p.stderr)


def state_text(row):
    if row["ok"]:
        return "ok"
    if row["ok"] is None:
        return row.get("error") or "not checked (timed out)"
    return "FAILING" + (" - %s" % row["detail"] if row.get("detail") else "")
