#!/usr/bin/env python3
"""PreToolUse guard: DENY a fetch or a browser navigation to a manual-candidate board's host.

⭐ WHY THIS EXISTS (dev #771, from jobsearch 0.75.0 / dev #765)
----------------------------------------------------------------
A `manual-candidate` channel is a site whose terms forbid automated access (ADR-037): the CANDIDATE
opens it, and the engine never visits it. Since 0.75.0 the engine refuses a board host in three
places that are all CODE paths (the triage queue, `record.py board-sighting`, the JD-read write
gate). Nothing stopped the MODEL, which holds `WebFetch` and the browser tools, from opening a board
URL directly: a policy held in three scripts and not at the tool boundary is held for the scripts
only. This guard is the tool-boundary half.

## The test, stated once

    tool_name in GUARDED_BOARD_TOOLS, and a URL it would open has a host that
    is, or is a sub-domain of, a manual-candidate board host          -> DENY (exit 2, stderr)
    any other host, no URL, a payload we cannot read                   -> ALLOW (exit 0, no output)
    the host set could not be read in full, and nothing matched        -> ALLOW (exit 0) + a shown
                                                                          `systemMessage` + one durable
                                                                          `board-guard-degraded` diag row

The URLs a call would open: `tool_input["url"]` for `WebFetch`, each `navigate` tool and
`mcp__Claude_Browser__preview_start`, and the `url`
of every `navigate` step inside `tool_input["actions"]` for a `browser_batch` (both servers). One board
URL anywhere in a batch denies the whole call; the message names the step.

## The host set: two lists, ONE reader

    the FLOOR     the shipped catalog's entries (`channel_catalog/channel_catalog.json`, read by
                  `channel_catalog.load_catalog`). Applies even to a board the candidate never adopted,
                  and to a retired entry: retiring a source does not change the site's terms.
    the PROFILE   the profile's own `data/channels.jsonl` rows, for a board the candidate added that
                  the catalog does not know.

Both lists go to `board_hosts.blocked_channel`, the same function triage, `record.py board-sighting`
and the JD-read gate call. This file restates no host matching: "is, or is a sub-domain of" is
`board_hosts.host_matches`, and a look-alike host that merely CONTAINS a board host
(`notjobs.board.example`, `jobs.board.example.invalid`) is not a match there either.

⭐ The one thing this file adds is the SCHEME. `board_hosts.host_of` reads only http(s) URLs, because
its callers hold recorded addresses. The browser's `navigate` documents "with or without protocol
(defaults to https://)", so `jobs.board.example/list` is a real call that `host_of` reads as no host at all.
A guard that took that as "allow" would be bypassed by omitting `https://`; `_with_scheme` supplies the
default the tool itself supplies, and a `\\` is read as `/` the way a browser reads it.

## When the host set cannot be read (#771-4)

    profile resolves, catalog readable, channels readable     -> the union; the normal case
    no profile resolves                                        -> the floor alone; allow is silent
                                                                  (most sessions have no profile)
    catalog unreadable                                         -> the profile's list alone
    channels store unreadable (missing, corrupt, a bad line)   -> the floor, plus every row that parsed
    a hit on whatever WAS readable                             -> DENY, always
    nothing matched AND the floor could not be read, or a
    resolved profile's channels could not be read              -> ALLOW, LOUD (the row and the message)
    a crash anywhere in the hook                               -> ALLOW, LOUD, exit 0

A deny never waits on the rest of the list. An allow that rested on a list we could not read says so.
The diag row is once per session (the shown `systemMessage` repeats), and carries a reason code, a tool
name and a session id only: the diag log may never hold a URL, a host or a channel id.

## WHAT THIS DOES NOT COVER (stated, not implied)

- **Bash `curl` / `wget` / any shell fetch.** Documented as a bypass on the platform's permissions page.
  The guard covers tool calls, not shell commands. ADR-037's line stays "held by the guard for WebFetch
  and browser navigation, not for the shell".
- **A name-only `preview_start`.** `mcp__Claude_Browser__preview_start` opens a tab at its `url` and is
  guarded like `navigate` (dev #771; an earlier draft of this file listed it here as a gap). Called with
  a `name` instead (it starts a dev server from `.claude/launch.json`), there is no URL to read and the
  call is allowed.
- **A redirect.** The host checked is the host the call names. A page that redirects onto a board is not
  followed.
- **Whether a subagent's calls reach this hook**: documented to, UNVERIFIED on this machine.
- **`allowManagedHooksOnly` / `disableAllHooks`**: the guard does not run, as for every guard here.

Protocol: PreToolUse stdin is the hook payload; exit 2 blocks and stderr is shown to the model.
`--selftest` (run from SessionStart) proves the deny and allow branches against synthetic channels, so a
syntax error or interpreter problem in this file is LOUD at session start instead of silently letting a
board through. `hooks.json`'s matcher must equal "|".join(GUARDED_BOARD_TOOLS); `check_board_guard_matcher.py`
asserts it in CI and inside the materialized shipped package.

Python 3.9+, standard library only.
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# ⭐ SINGLE SOURCE OF TRUTH for what is guarded. hooks.json's PreToolUse matcher for this script must
# equal "|".join(GUARDED_BOARD_TOOLS) exactly (check_board_guard_matcher.py). Every name here is an
# exact tool name: the matcher is a plain alternation, not a regular expression.
GUARDED_BOARD_TOOLS = (
    "WebFetch",
    "mcp__Claude_Browser__navigate",
    "mcp__claude-in-chrome__navigate",
    "mcp__Claude_Browser__preview_start",
    "mcp__Claude_Browser__browser_batch",
    "mcp__claude-in-chrome__browser_batch",
)

# What each guarded name does, decided by the name's last segment (trap 8: by what it DOES).
BATCH_TOOLS = frozenset(t for t in GUARDED_BOARD_TOOLS if t.endswith("browser_batch"))
URL_TOOLS = frozenset(t for t in GUARDED_BOARD_TOOLS if t not in BATCH_TOOLS)

DEGRADED_EVENT = "board-guard-degraded"

# Reason codes: the only form the diag log accepts (`_diag.redact` refuses prose).
CATALOG_UNREADABLE = "catalog-unreadable"
CHANNELS_UNREADABLE = "channels-unreadable"
HOOK_CRASHED = "hook-crashed"

_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")


def _with_scheme(url):
    """The URL a navigate/fetch tool will actually open: surrounding space dropped, `\\` read as `/`
    (a browser does), and `https://` supplied when no scheme is given (the browser tool's own
    default). `back`/`forward` and other non-URLs stay non-URLs: `board_hosts.host_of` then says None.
    A string that already carries a scheme (including `mailto:`) is left alone."""
    if not isinstance(url, str):
        return None
    u = url.strip().replace("\\", "/")
    if not u or u.lower() in ("back", "forward"):
        return None
    if u.startswith("//"):
        return "https:" + u
    if _SCHEME.match(u) and not re.match(r"^[A-Za-z0-9.\-]+:\d+(/|$)", u):
        return u                                          # `host:8080/x` is a host with a port, not a scheme
    return "https://" + u


def urls_of(payload):
    """[(label, url)] for every URL this call would open. A label names the step in a batch. Anything
    that is not the documented shape yields nothing: an unreadable payload is not evidence of a
    violation, and the matcher already decided this hook should run."""
    if not isinstance(payload, dict):
        return []
    name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return []
    out = []
    if name in URL_TOOLS:
        out.append((name, tool_input.get("url")))
    elif name in BATCH_TOOLS:
        actions = tool_input.get("actions")
        for i, action in enumerate(actions if isinstance(actions, list) else []):
            if not isinstance(action, dict):
                continue
            step = str(action.get("name") or "").split("__")[-1]
            inner = action.get("input")
            if step == "navigate" and isinstance(inner, dict):
                out.append(("%s step %d" % (name, i + 1), inner.get("url")))
    return [(label, _with_scheme(u)) for label, u in out if _with_scheme(u)]


def evaluate(payload, channels):
    """(verdict, info) for one call against `channels` (the floor's entries then the profile's rows).
    verdict is "deny" (info: label, url, host, channel) or "allow" (info: None). Pure: no I/O."""
    import board_hosts as bh
    for label, url in urls_of(payload):
        ch = bh.blocked_channel(url, channels)
        if ch is not None:
            return "deny", {"label": label, "url": url, "host": bh.host_of(url), "channel": ch}
    return "allow", None


def deny_message(info):
    ch = info["channel"]
    cid = ch.get("id") or ch.get("channel_id") or "a board channel"
    label = ch.get("label")
    named = "%s (%s)" % (cid, label) if label and label != cid else str(cid)
    return (
        "BLOCKED: %s would open %s, a board the engine never visits.\n\n"
        "The channel %s is manual-candidate: its terms forbid automated access (ADR-037), so the\n"
        "CANDIDATE opens it, in their own browser, and nothing here fetches or navigates to it.\n\n"
        "What to do instead:\n"
        "  * Tell the candidate which board page to open themselves, and carry on without it.\n"
        "  * For a role you already hold: use the posting's OWN address (the employer's career site\n"
        "    or its ATS page), never the board's. `record.py board-sighting` records that address.\n"
        "  * A JD you cannot read from a non-board address is recorded `unavailable: manual-board`.\n\n"
        "[guard_board_hosts: host %s, channel %s]\n"
        % (info["label"], info["host"], named, info["host"], cid))


# ---------------------------------------------------------------------------------------
# The host set
# ---------------------------------------------------------------------------------------

def floor_channels():
    """(entries, error_code). The shipped catalog's entries through the engine's own reader. An
    unreadable catalog is ([], CATALOG_UNREADABLE), never an empty list passed off as 'no boards'."""
    try:
        import channel_catalog
        doc = channel_catalog.load_catalog()
        return [e for e in doc["entries"] if isinstance(e, dict)], None
    except Exception:                                     # noqa: BLE001 - any failure is "could not read"
        return [], CATALOG_UNREADABLE


def profile_channels():
    """(rows, has_profile, error_code). `has_profile` False when nothing resolves (not an error: most
    sessions run in no profile). A resolved profile whose `data/channels.jsonl` is missing or has a
    line that does not parse is an error, and every row that DID parse is still returned."""
    try:
        import _root
        root = _root.profile_root()
        if _root.is_unbound(root) or not _root.looks_like_profile(root):
            return [], False, None
    except Exception:                                     # noqa: BLE001 - unresolvable = no profile
        return [], False, None
    rows, bad = [], False
    path = os.path.join(root, "data", "channels.jsonl")
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    bad = True
                    continue
                if isinstance(row, dict):
                    rows.append(row)
                else:
                    bad = True
    except (OSError, UnicodeDecodeError):
        return rows, True, CHANNELS_UNREADABLE
    return rows, True, (CHANNELS_UNREADABLE if bad else None)


# ---------------------------------------------------------------------------------------
# The loud half of a degraded allow
# ---------------------------------------------------------------------------------------

def _flag_path(session_id):
    sess = re.sub(r"[^A-Za-z0-9_-]", "", str(session_id or ""))[:64]
    if not sess:
        return None
    try:
        import _root
        return os.path.join(_root.state_root(), "guard_board_hosts.degraded-%s" % sess)
    except Exception:                                     # noqa: BLE001
        return None


def record_degraded(payload, reasons):
    """One `board-guard-degraded` diag row per session (the shown half is the `systemMessage` `main()`
    prints, every time). Coded scalars only. Never raises: a diagnostic must not break a hook."""
    session_id = tool = None
    try:
        if isinstance(payload, dict):
            session_id = payload.get("session_id")
            tool = payload.get("tool_name")
    except Exception:                                     # noqa: BLE001
        pass
    flag = _flag_path(session_id)
    if flag:
        try:
            if os.path.exists(flag):
                return
        except OSError:
            pass
    try:
        from _diag import log as diag
        diag(DEGRADED_EVENT, hook="guard_board_hosts", tool_name=tool, session_id=session_id,
             reason="+".join(reasons))
    except Exception:                                     # noqa: BLE001 - never block a session
        pass
    if flag:
        try:
            os.makedirs(os.path.dirname(flag), exist_ok=True)
            open(flag, "w", encoding="utf-8").close()
        except OSError:
            pass


def degraded_message(reasons, urls):
    host = ""
    try:
        import board_hosts as bh
        hosts = sorted({bh.host_of(u) for _l, u in urls if bh.host_of(u)})
        host = " to %s" % ", ".join(hosts) if hosts else ""
    except Exception:                                     # noqa: BLE001
        pass
    what = {CATALOG_UNREADABLE: "the shipped channel catalog (the board floor)",
            CHANNELS_UNREADABLE: "this profile's channels store",
            HOOK_CRASHED: "its own host check (the hook crashed)"}
    parts = " and ".join(what.get(r, r) for r in reasons)
    return ("guard_board_hosts could not read %s, so this call%s was ALLOWED UNCHECKED against "
            "manual-candidate board hosts (ADR-037). If it reached a board the candidate should "
            "open themselves, that is a miss, not a pass. Run /jobsearch:doctor." % (parts, host))


# ---------------------------------------------------------------------------------------
# selftest and main
# ---------------------------------------------------------------------------------------

def selftest():
    """Prove both branches against SYNTHETIC channels. Loud, never blocking startup."""
    failures = []
    boards = [{"id": "selftest-board", "label": "Selftest Board", "access": "manual-candidate",
               "board_hosts": ["jobs.board-selftest.example"]},
              {"id": "selftest-open", "access": "public", "board_hosts": ["open.selftest.example"]}]
    url = "https://jobs.board-selftest.example/role/1"
    for tool in sorted(URL_TOOLS):
        v, _ = evaluate({"tool_name": tool, "tool_input": {"url": url}}, boards)
        if v != "deny":
            failures.append("%s did not deny a board host" % tool)
    for tool in sorted(BATCH_TOOLS):
        v, _ = evaluate({"tool_name": tool, "tool_input": {"actions": [
            {"name": "computer", "input": {"action": "screenshot"}},
            {"name": "navigate", "input": {"url": url}}]}}, boards)
        if v != "deny":
            failures.append("%s did not deny a navigate step on a board host" % tool)
    for other in ("https://boards.greenhouse.io/acme/jobs/1", "https://notjobs.board-selftest.example/",
                  "https://jobs.board-selftest.example.invalid/", "https://open.selftest.example/x"):
        v, _ = evaluate({"tool_name": GUARDED_BOARD_TOOLS[0], "tool_input": {"url": other}}, boards)
        if v != "allow":
            failures.append("%s was denied" % other)
    v, _ = evaluate({"tool_name": GUARDED_BOARD_TOOLS[0], "tool_input": {"url": "jobs.board-selftest.example"}},
                    boards)
    if v != "deny":
        failures.append("a URL with no scheme was not denied")
    v, _ = evaluate(None, boards)
    if v != "allow":
        failures.append("an unreadable payload did not allow")
    if failures:
        print(json.dumps({"systemMessage":
                          "guard_board_hosts SELFTEST FAILED (%s) - the manual-candidate board guard "
                          "may be inert; treat WebFetch and browser navigation as unguarded this session."
                          % "; ".join(failures)}))
    return 0                                              # never block startup; the message is the point


def _run(payload):
    if not urls_of(payload):
        return 0                                          # nothing it would open: nothing to read first
    urls = urls_of(payload)
    floor, floor_err = floor_channels()
    prof, has_profile, prof_err = profile_channels()
    verdict, info = evaluate(payload, list(floor) + list(prof))
    if verdict == "deny":
        sys.stderr.write(deny_message(info))
        return 2
    reasons = [r for r in (floor_err, prof_err) if r]
    # No profile resolving is normal and silent; a floor we could not read, or a resolved profile whose
    # list we could not read, means the ALLOW rested on a list that was not whole.
    if reasons:
        record_degraded(payload, reasons)
        print(json.dumps({"systemMessage": degraded_message(reasons, urls)}))
    return 0


def main():
    if "--selftest" in sys.argv[1:]:
        return selftest()
    try:
        payload = json.load(sys.stdin)
    except Exception:                                     # noqa: BLE001
        return 0                                          # unreadable is not evidence of a violation
    try:
        return _run(payload)
    except Exception:                                     # noqa: BLE001 - never a crash that blocks a tool
        try:
            record_degraded(payload, [HOOK_CRASHED])
            print(json.dumps({"systemMessage": degraded_message([HOOK_CRASHED], [])}))
        except Exception:                                 # noqa: BLE001
            pass
        return 0


if __name__ == "__main__":
    sys.exit(main())
