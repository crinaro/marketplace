"""Coverage claims a gap cites (`--covered-by`): issue lookups against this plugin's trackers, the coverage cache, and
the fired-event writer.

Capability module of `journal.py` (S4a, moved unedited apart from `_public_repo` / `_private_repo` reading
`where.SCRIPTS_DIR`)."""

import datetime
import json
import os
import re
import subprocess
import sys
from _root import is_unbound, say_unbound_once
from journaling import where as _where
from journaling.journal_file import _refuse_if_unwritable, append, pin_refusal
from journaling.tables import COVERAGE_CACHE, COVERAGE_STATES, _DATE_RE


def age_days(at):
    try:
        then = datetime.datetime.fromisoformat(at)
        return (datetime.datetime.now() - then).days
    except Exception:
        return 0


def evaluate_coverage(gaps, issue_state):
    """Which covered_by citations are still doing their job? De-duplicates by citation first —
    ten gaps covered by the same filed issue need exactly one live lookup, not ten.

    `issue_state(citation) -> "OPEN" | "CLOSED" | "MISSING" | None` is the one impure call this
    function makes; everything else here is deterministic. Returns three lists of
    `(citation, [gap_id, ...])`: verified-open, stale (CLOSED or MISSING — the citation has
    outlived its cause, or never named a real issue), and unverifiable (no `gh`, no network, or —
    for a `dev`/`github`/`marketplace` citation checked from an INSTALLED copy — no private-repo
    remote to even ask; that last case is normal and not itself a failure)."""
    by_citation = {}
    for g in gaps:
        c = g.get("covered_by")
        if c:
            by_citation.setdefault(c, []).append(g.get("gap_id"))
    verified_open, stale, unverifiable = [], [], []
    for citation in sorted(by_citation):
        gap_ids = by_citation[citation]
        state = issue_state(citation)
        if state == "OPEN":
            verified_open.append((citation, gap_ids))
        elif state in ("CLOSED", "MISSING"):
            stale.append((citation, gap_ids))
        else:
            unverifiable.append((citation, gap_ids))
    return verified_open, stale, unverifiable


def _split_citation(citation):
    kind, _, num = (citation or "").partition("#")
    return kind.strip().lower(), num.strip()


def _public_repo():
    """This plugin's OWN public tracker, read from its manifest — the same derivation
    `report_issue.py`'s `tracker()` uses, so this resolves from an INSTALLED copy with no
    knowledge of the private repo at all."""
    try:
        here = _where.SCRIPTS_DIR
        with open(os.path.join(os.path.dirname(here), ".claude-plugin", "plugin.json"),
                  encoding="utf-8") as fh:
            repo = str(json.load(fh).get("repository") or "")
        m = re.search(r"github\.com[:/]([\w.\-]+/[\w.\-]+?)(?:\.git)?/?$", repo)
        return m.group(1) if m else None
    except Exception:                                     # noqa: BLE001
        return None


def _private_repo():
    """This CHECKOUT's own origin — resolvable only from a maintainer checkout. An installed
    copy is not a git repository at all, so `git remote` simply fails here, which is correct: an
    installed copy has no business knowing the private repo's name, let alone querying it."""
    try:
        here = _where.SCRIPTS_DIR
        out = subprocess.run(["git", "-C", here, "remote", "get-url", "origin"],
                             capture_output=True, text=True, timeout=10)
        m = re.search(r"github\.com[:/](.+?)(?:\.git)?$", (out.stdout or "").strip())
        return m.group(1) if m else None
    except Exception:                                     # noqa: BLE001
        return None


def issue_lookup(citation):
    """LIVE, IMPURE, NEVER CALLED IN CI. Returns `(state, title)`: state is 'OPEN', 'CLOSED',
    'MISSING' (the repo resolved but the issue did not), or None -- unverifiable from here, which
    covers "no `gh` on PATH", "no network", and "a dev/github/marketplace citation asked from an
    installed copy with no private remote" alike. `evaluate_coverage()` above is what gives that
    None a name. `title` is the issue's title when GitHub answered, else None (dev #711: the
    write-time echo prints it so a wrong citation is visible to the person typing it)."""
    kind, num = _split_citation(citation)
    if not num.isdigit():
        return None, None
    repo = _public_repo() if kind == "public" else _private_repo()
    if not repo:
        return None, None
    try:
        out = subprocess.run(["gh", "issue", "view", num, "--repo", repo, "--json",
                              "state,title"], capture_output=True, text=True, timeout=15)
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return None, None
    if out.returncode != 0:
        return ("MISSING" if "could not resolve" in (out.stderr or "").lower() else None), None
    try:
        data = json.loads(out.stdout or "{}")
    except ValueError:
        return None, None
    state = str(data.get("state") or "").upper() or None
    title = " ".join(str(data.get("title") or "").split())[:120] or None
    return state, title


def issue_state(citation):
    """The state half of `issue_lookup()`; the one impure call `evaluate_coverage()` makes."""
    return issue_lookup(citation)[0]


def coverage_cache_path(root):
    return os.path.join(root, COVERAGE_CACHE)


def read_coverage_cache(root):
    """(verdicts, problem). `verdicts` is {citation: {"state", "at"}}; `problem` is None, or a
    sentence saying why the file could not be used. An ABSENT file is not a problem (nothing has
    been checked yet: every citation reads as unverified). A present-but-unreadable one is: it is
    returned as `({}, reason)` so the caller can say so out loud instead of quietly treating a
    corrupt cache as an empty one."""
    p = coverage_cache_path(root)
    try:
        with open(p, encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        return {}, None
    except (OSError, ValueError) as e:
        return {}, "%s is not readable (%s)" % (COVERAGE_CACHE, e)
    verdicts = raw.get("verdicts") if isinstance(raw, dict) else None
    if not isinstance(verdicts, dict):
        return {}, "%s has no 'verdicts' object" % COVERAGE_CACHE
    for citation, v in verdicts.items():
        if not (isinstance(v, dict) and v.get("state") in COVERAGE_STATES
                and isinstance(v.get("at"), str) and _DATE_RE.match(v["at"])):
            return {}, ("%s entry %r is not {state: OPEN|CLOSED|MISSING, at: YYYY-MM-DD}"
                        % (COVERAGE_CACHE, citation))
    return verdicts, None


def write_coverage_cache(root, verdicts, checked_at):
    """Atomically write the cache (temp file + rename). Same refusals as the journal itself:
    no unbound directory, never the tracked fixture. Returns the path written."""
    _refuse_if_unwritable(root)
    p = coverage_cache_path(root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = "%s.tmp-%d" % (p, os.getpid())
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"checked_at": checked_at, "verdicts": verdicts}, fh, indent=1, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, p)
    return p


def apply_coverage_cache(covered, verdicts):
    """PURE. Split the `covered` gaps (from `split_gaps`) by what is known about their citation:

        (still_covered, degraded, unverified)

    `degraded`: the citation was last known CLOSED or MISSING -- each is a COPY of the gap with
    `degraded_because` set, to be counted as open. `unverified` is a subset of `still_covered`:
    the citation has no verdict yet, or the gap has no stored `covered_reason` (a row from before
    dev #711). CLOSED/MISSING wins over a missing reason: a closed issue covers nothing."""
    still, degraded, unverified = [], [], []
    for g in covered:
        v = verdicts.get(g.get("covered_by"))
        if v and v["state"] in ("CLOSED", "MISSING"):
            degraded.append(dict(g, degraded_because=(
                "%s was %s as of %s" % (g.get("covered_by"), v["state"], v["at"]))))
            continue
        still.append(g)
        if not v or not g.get("covered_reason"):
            unverified.append(g)
    return still, degraded, unverified


def coverage_echo(citation, lookup=None):
    """Lines the write-time `--gap --covered-by` prints so the citation can be eyeballed: the
    cited issue's title and state, or NOT VERIFIED. `lookup` is injectable for tests."""
    state, title = (lookup or issue_lookup)(citation)
    if state is None:
        return ["  covered by %s: NOT VERIFIED (no gh, no network, or no reachable repo) -- the "
                "reason is stored, but nobody has seen that this issue exists" % citation]
    lines = ["  covered by %s: %s%s" % (citation, state, " -- %s" % title if title else "")]
    if state in ("CLOSED", "MISSING"):
        lines.append("  !! %s is %s: it covers nothing now. Check the number; "
                     "`--check-coverage` will list this gap as stale."
                     % (citation, "closed" if state == "CLOSED" else "not a real issue"))
    return lines


def _record_fired(root, at):
    """⭐⭐ public #65 — called ONLY from `hooks.json`'s SessionStart entry, before any model
    turn. This is the whole fix: a `fired` event written by the HOOK, deterministically, is
    evidence a session existed that does not depend on the run's own logic ever getting a turn
    to call `--start`. MUST NEVER block a session — every failure is swallowed and reported to
    stderr only, the same contract `ensure_connectors.py`'s SessionStart hook already keeps."""
    try:
        # ⭐ dev #618 — nothing is bound: write nothing, say so once, exit 0 (`main()` returns 0
        # on every `--fired` path). Checked BEFORE `append` so the message is this hook's own
        # sentence rather than a swallowed JournalError, and so the refusal does not depend on
        # the choke point's wording.
        if is_unbound(root):
            say_unbound_once("journal.py --fired", root)
            return
        # dev #834: a profile pinned above this engine is not written to, and the hook says why on stdout (exit 0:
        # a hook never blocks a session). Checked before stdin is read; `append` would refuse too.
        refusal = pin_refusal(root)
        if refusal:
            print("jobsearch: %s" % refusal)
            return
        session_id, cwd = "", ""
        try:
            if not sys.stdin.isatty():
                payload = json.loads(sys.stdin.read() or "{}") or {}
                session_id = str(payload.get("session_id") or "")
                cwd = str(payload.get("cwd") or "")
        except Exception:                                 # noqa: BLE001 — stdin is best-effort
            pass
        append(root, {"event": "fired", "session_id": session_id, "cwd": cwd, "at": at})
    except Exception as e:                                # noqa: BLE001 — never block a session
        print("journal.py --fired: could not record (%s) — session continues unaffected" % e,
              file=sys.stderr)
