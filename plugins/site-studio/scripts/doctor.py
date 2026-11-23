#!/usr/bin/env python3
"""doctor.py -- the machine check (dev #835, design 6.1, named changes S7 and S10). Python 3.9,
standard library only. Prints one plain report, installs nothing, and exits 0 ALWAYS.

    doctor.py [--hook] [--repo R]

WHAT IT CHECKS: python3 3.9 or newer; git with a name and an email; `gh` installed; the repo's
`site/site.json` carries the CANONICAL marker line (named change S10: siteconfig.py is the only
writer of one canonical form, and a hand-edited file whose marker the SessionStart grep might not
recognise is reported here as "re-save site.json", never silently ignored; a `site.json` with NO marker
at all is not a file to re-save but a site site-studio does not manage yet, and is told to type
/site-studio:adopt, dev #855); Chrome found (design
5.2). In the FULL report only (setup, `doctor.py` with no flag) it also checks that `gh` is logged
in and that the public repo is reachable with this login, that `main` is current, and one summary line
of the Pages check (below).

THE PAGES LINE (dev #835, amendment 1 AM10; full report ONLY). "pages: <n> to resolve, <m> waiting
(run pages_check.py)" comes from `pages_check.check`, which makes up to ~15 `gh` reads. It is
INTERACTIVE and NEVER RUNS FROM THE HOOK: `pages_check` is imported lazily inside `pages_line`, and
`hook_line` never reaches it (test_doctor proves it in a SUBPROCESS: `pages_check` is not in
`sys.modules` after `hook_line`). TIME BOUND: PAGES_BUDGET_S = 30 s for the whole line. Every read is
handed `min(15, seconds left)` as its timeout (through pages_check's GET_TIMEOUT, which `_get` reads
at call time) and a read started after the budget is spent is refused as "time budget spent", so
that item reads NOT CHECKED, never ok; the line is bounded at the budget plus about one second of
process start-up. pages_check.check has no `budget_s` seam of its own yet (the amendment's A2.1
names one), so doctor wraps `get` and `sleep` instead.

WINDOWS (design 5.2): `os.name == "nt"` is checked first and the report is one sentence, nothing else.

AS A SESSIONSTART HOOK (`--hook`, named change S7). Scheduled runs (S2) have nobody to answer a
call that waits on a human, and docs/surfaces.md records that an unattended `gh` call from a
SessionStart hook stalls there. So `--hook` (a) runs ONLY local checks: it does NOT call `gh`
(installed-or-not is a PATH lookup; the login and reachability checks are lazy, in setup and
publish), and it makes no network call; (b) bounds every subprocess (3 s each); (c) prints exactly
ONE line, whatever happens; (d) exits 0. The S2 start-up path is UNVERIFIED alongside probe P-9.

CHROME. The lookup is browser.lookup_chrome, called and never copied (gate-keeper D11): a
CHROME_PATH that points nowhere is a refusal that names it here exactly as it is in capture. It does
not launch Chrome.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

WINDOWS_SENTENCE = "site-studio 0.1.0 runs on macOS and Linux; Windows is not supported yet."
# A site/site.json with no engine marker at all (dev #855, design 7.4): not a file to re-save, a site to adopt.
UNMANAGED_SENTENCE = ("site/site.json was not made by site-studio: this is a site site-studio does not manage "
                      "yet. Type /site-studio:adopt to convert it.")
SUB_TIMEOUT = 3          # seconds, every local subprocess
GH_TIMEOUT = 15          # seconds, the lazy gh calls of the full report only
PAGES_BUDGET_S = 30      # seconds, the WHOLE pages line of the full report (AM10)


def _run(args, cwd=None, timeout=None):
    """(returncode, stdout) or (None, reason) on a timeout or a missing program. Never raises."""
    timeout = timeout or SUB_TIMEOUT
    try:
        p = subprocess.run(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True, timeout=timeout,
                           env=dict(os.environ, GIT_TERMINAL_PROMPT="0", GH_PROMPT_DISABLED="1"))
        return p.returncode, p.stdout.strip()
    except subprocess.TimeoutExpired:
        return None, "timed out after %ds" % timeout
    except OSError as e:
        return None, str(e.strerror or e)


def chrome_lookup(env=None):
    """(path, why) from browser.lookup_chrome, the ONE Chrome lookup (gate-keeper D11, dev #835).

    This used to repeat the lookup and fall through to another Chrome when CHROME_PATH pointed at
    nothing, where browser.py refuses that by name (2026-11-12 decision: an explicit setting that
    points nowhere must not be silently replaced). The two disagreed, so the machine check could
    say "ready" while capture refused. It now asks browser.py, so a bad CHROME_PATH reads the same
    here and there. Never raises: a lookup that cannot load is reported as the reason."""
    try:
        import browser
        return browser.lookup_chrome(env)
    except Exception as e:
        return None, "the Chrome lookup could not run (%s: %s)" % (type(e).__name__, e)


def find_chrome(env=None):
    return chrome_lookup(env)[0]


def local_checks(repo):
    """[(label, ok, detail)] for the checks that need no network and no gh."""
    out = []
    v = sys.version_info
    out.append(("python3", v >= (3, 9), "%d.%d.%d%s" % (v[0], v[1], v[2], "" if v >= (3, 9) else
                                                       " (3.9 or newer is needed)")))
    if shutil.which("git") is None:
        out.append(("git", False, "not installed"))
    else:
        name = _run(["git", "config", "user.name"], cwd=repo)
        email = _run(["git", "config", "user.email"], cwd=repo)
        missing = [k for k, r in (("name", name), ("email", email)) if r[0] != 0 or not r[1]]
        if any(r[0] is None for r in (name, email)):
            out.append(("git", False, "did not answer (%s)" % (name[1] if name[0] is None else email[1])))
        elif missing:
            out.append(("git", False, "no %s set (git config --global user.%s ...)" % (
                " or ".join(missing), missing[0])))
        else:
            out.append(("git", True, "name and email set"))
    out.append(("gh", shutil.which("gh") is not None, "installed" if shutil.which("gh") else "not installed"))
    out.append(_marker_check(repo))
    chrome, why = chrome_lookup()
    out.append(("chrome", chrome is not None, chrome or "%s (needed to import media and for the "
                                                       "visual checks; build and publish still work)" % why))
    return out


def _marker_check(repo):
    path = os.path.join(repo, "site", "site.json")
    if not os.path.isfile(path):
        return ("site.json", False, "not found at %s" % path)
    try:
        from configschema import canonical
        with open(path, "r", encoding="utf-8", newline="") as fh:
            state, reason = canonical.marker_state(fh.read())
    except (OSError, ImportError, UnicodeDecodeError) as e:
        return ("site.json", False, "cannot be read (%s)" % e)
    if state == canonical.MARKER_OK:
        return ("site.json", True, "canonical marker")
    if state == canonical.MARKER_ABSENT:
        # a re-save cannot help a file site-studio never made: it is a site to adopt (dev #855)
        return ("site.json", False, UNMANAGED_SENTENCE)
    return ("site.json", False, "%s; re-save site.json" % reason)


def adopt_line(repo):
    """"site-studio <v> may resolve N adopt blockers: run adopt again", or None (template-fidelity step 1.9f; R3N-12 as the owner's
    rulings changed it). N counts the recorded blockers in `.site-studio/adopt-reports.json` this install MAY clear: an unresolved
    row raised in an OLDER version than the install, or an `upgrade` row whose fix this install has reached
    (`report_issue.may_resolve`). It reads the record only, runs no `gh`, and imports neither `adopt` nor `build` (R3N-16). A
    missing, unreadable or unrecognised record, or a count of zero, is no line: a doctor line never raises."""
    try:
        path = os.path.join(repo, ".site-studio", "adopt-reports.json")
        if not os.path.isfile(path):
            return None
        import report_issue
        with open(path, "r", encoding="utf-8") as fh:
            rows = report_issue.parse_reports(fh.read())
        installed = report_issue.plugin_version()
        n = report_issue.may_resolve(rows, installed)
        return "site-studio %s may resolve %d adopt blockers: run adopt again" % (installed, n) if n else None
    except Exception:
        return None


def hook_line(repo):
    """The ONE line the SessionStart hook prints. Never raises."""
    try:
        if os.name == "nt":
            return WINDOWS_SENTENCE
        found = [(l, d) for l, ok, d in local_checks(repo) if not ok]
        adopt = adopt_line(repo)
        if not found:
            return "site-studio: this computer is ready" + ("; " + adopt if adopt else "")
        text = "; ".join("%s: %s" % (l, d) for l, d in found)
        rest = [1 for _l, d in found if d != UNMANAGED_SENTENCE]
        if not rest:                  # only the unmanaged site.json: it already says what to type
            return "site-studio: needs attention - %s" % text
        if len(rest) < len(found):
            line = "site-studio: needs attention - %s Type /site-studio:setup to fix the rest." % (
                text if text.endswith(".") else text + ".")
        else:
            line = "site-studio: needs attention - %s. Type /site-studio:setup to fix it." % text
        return line + (" " + adopt if adopt else "")
    except Exception as e:
        return "site-studio: the machine check could not finish (%s: %s)" % (type(e).__name__, e)


_LOOK_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*\.json$")     # `lookgrammar.layering.LOOK_FILE_RE`'s file names


def look_lines(repo):
    """P6 (design-adopt-ownership-line section 3): each look file under `site/looks/` that `site.json` names in neither `look` nor
    `lookLocal`, which no build reads, in the words `lookgrammar.layering.unread_notes` prints (a test pins the two equal). Read
    from disk with no look code imported, as the rest of the report is. Never raises: [] when site.json does not read."""
    try:
        with open(os.path.join(repo, "site", "site.json"), encoding="utf-8") as fh:
            cfg = json.load(fh)
        names = sorted("site/looks/" + f for f in os.listdir(os.path.join(repo, "site", "looks")) if _LOOK_NAME.match(f))
    except (OSError, ValueError):
        return []
    named = set((cfg.get("look"), cfg.get("lookLocal"))) if isinstance(cfg, dict) else set()
    return [('%s is not used: site/site.json has no "lookLocal"' if p == "site/looks/local.json" else
             '%s is not used: site/site.json names it in neither "look" nor "lookLocal"') % p for p in names if p not in named]


def full_report(repo):
    """The multi-line report of setup. gh is asked here, lazily; it is never asked by the hook."""
    if os.name == "nt":
        return WINDOWS_SENTENCE
    lines = []
    for label, ok, detail in local_checks(repo):
        lines.append("%-10s %s  %s" % (label, "ok     " if ok else "MISSING", detail))
    gh_ok = False
    if shutil.which("gh"):
        rc, out = _run(["gh", "auth", "status"], timeout=GH_TIMEOUT)
        gh_ok = rc == 0
        lines.append("%-10s %s  %s" % ("gh login", "ok     " if rc == 0 else "MISSING",
                                       "logged in" if rc == 0 else "not logged in (gh auth login)" if rc
                                       else "could not be checked (%s)" % out))
        slug = _public_repo(repo)
        if slug and rc == 0:
            rc2, out2 = _run(["gh", "api", "repos/%s" % slug, "--jq", ".full_name"], timeout=GH_TIMEOUT)
            lines.append("%-10s %s  %s" % ("public repo", "ok     " if rc2 == 0 else "MISSING",
                                           out2 if rc2 == 0 else "%s is not reachable with this login" % slug))
        else:
            lines.append("%-10s %s  %s" % ("public repo", "NOT CHECKED", "needs gh logged in and a publicRepo in site.json"))
    else:
        lines.append("%-10s %s  %s" % ("gh login", "NOT CHECKED", "gh is not installed"))
    lines.append(pages_line(repo, logged_in=gh_ok))
    lines += ["%-10s %s  %s" % ("look", "NOTE   ", line) for line in look_lines(repo)]
    try:
        import sync_main
        line = sync_main.run(repo)
        lines.append("%-10s %s  %s" % ("main", "ok     " if line is None else "NOTE   ",
                                       "current" if line is None else line))
    except Exception as e:
        lines.append("%-10s %s  %s" % ("main", "NOT CHECKED", "%s: %s" % (type(e).__name__, e)))
    return "\n".join(lines)


def pages_line(repo, logged_in=True, budget_s=None, now=time.monotonic):
    """The ONE Pages line of the full report (never of the hook). Never raises.

    "pages: <n> to resolve, <m> waiting[, <k> not checked] (run pages_check.py)", or
    "pages: NOT CHECKED (<why>)". NOT CHECKED is never shown as a clean count (design rule: a
    missing thing must not read as an empty thing). The whole call is bounded by `budget_s`
    (default PAGES_BUDGET_S); see the module docstring for how."""
    budget_s = PAGES_BUDGET_S if budget_s is None else budget_s
    slug = _public_repo(repo)
    if not logged_in or not slug:
        return "pages: NOT CHECKED (needs gh logged in and a publicRepo in site.json)"
    try:
        from pagesaudit import ghget, reporting, runcheck, values
        from configschema import model
        cfg = model.load(os.path.join(repo, "site", "site.json"))
        deadline = now() + budget_s

        def get(path, paginate=False):
            left = deadline - now()
            if left <= 0:
                raise values.GhError("time budget spent")
            saved = ghget.GET_TIMEOUT
            ghget.GET_TIMEOUT = max(1, min(saved, left))
            try:
                return ghget._get(path, paginate)
            finally:
                ghget.GET_TIMEOUT = saved

        def sleep(seconds):
            time.sleep(max(0, min(seconds, deadline - now())))

        items = runcheck.check(slug, cfg, get=get, sleep=sleep)
        n = reporting.counts(items)
        extra = ", %d not checked" % n["not_checked"] if n["not_checked"] else ""
        return "pages: %d to resolve, %d waiting%s (run pages_check.py)" % (n["resolve"], n["wait"], extra)
    except Exception as e:  # PagesCheckError, a bad site.json, anything: one line, never a traceback
        return "pages: NOT CHECKED (%s)" % (str(e).splitlines()[0] if str(e) else type(e).__name__)


def _public_repo(repo):
    try:
        from configschema import model
        return model.load(os.path.join(repo, "site", "site.json")).publicRepo
    except Exception:
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(prog="doctor.py", allow_abbrev=False)
    ap.add_argument("--hook", action="store_true", help="SessionStart mode: local checks, one line")
    ap.add_argument("--repo", help="the dev repo (default CLAUDE_PROJECT_DIR, else here)")
    args = ap.parse_args(argv)
    repo = args.repo or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    print(hook_line(repo) if args.hook else full_report(repo))
    return 0


if __name__ == "__main__":
    sys.exit(main())
