#!/usr/bin/env python3
"""The LinkedIn render-stall probe — a shipped constant, never agent prose.

WHY THIS EXISTS (design-linkedin-runner-resilience.md §2.2, public #96)
-------------------------------------------------------------------------
Public #96: the Browser pane stops painting — clicks land, nothing renders — and a run
degraded to "partial" without ever naming what happened. Distinguishing a genuinely stalled
render from a page that is merely busy needs a real paint-proof, run on the pane's own
executor, every time, worded identically every time. Carrying that JavaScript as prose inside
`agents/linkedin-runner.md` would let the two drift — an edit to one and not the other is
invisible until the day it matters.

So the probe is a MODULE CONSTANT here, and `linkedin-runner.md` carries it byte-equal between
two fence markers (`<!-- pane-probe:begin -->` … `<!-- pane-probe:end -->`) — the same
verbatim-fence idiom `check_verbatim_enums.py` established for agent-instructed enum values,
applied to agent-instructed CODE. `test_checks.py` asserts the equality directly; a one-character
drift in either copy is a red test, not a silent divergence.

## The verdict, in one paragraph (full detail: the design doc §2.3)

`document.visibilityState !== 'visible'` first — Chromium pauses `requestAnimationFrame` in a
hidden document, so a timer-vs-rAF probe there would read "stalled" forever; a hidden document
is `{hidden: true}`, NO VERDICT, never a stall. Otherwise: a nested `requestAnimationFrame`
resolves only when a frame is actually produced (the paint-proof), raced against a plain
`setTimeout(r, 4000)`. Painted within the window -> `{painted: true}`. Not painted, but a
trailing `setTimeout(r, 0)` still fires (`tasks_ran: true`) -> a CANDIDATE, not yet a verdict —
only TWO such candidates, at least 4s apart, both with the document visible, are a CONFIRMED
render-stall. Anything else (an error, a timeout, an unrecognised shape) is NO VERDICT — folded
into the runner's existing `browser-unavailable` ladder, never a new state.

## The call-name allowlist (§2.2)

`ALLOWED_CALLS` below is every identifier this constant may ever reference — a probe that could
grow a `querySelector(...).click()` is not a probe. `test_checks.py` asserts this BY REGEX over
the constant itself, not by trusting this list: the list documents the intent, the test is what
actually enforces it.

## The verdict is a script too (dev #826 / public #177, jobsearch 0.83.0; design-sweep-misfires.md §2)

The probe cannot tell "the pane is not painting because nobody is looking at it" from "the compositor
is broken" (#96): from inside the page the two read the same (HTML Standard, "update the rendering": a
document is dropped from the frame list when its visibility state is hidden OR its navigable has no
rendering opportunity). The distinction has to come from OUTSIDE the page, and the harness supplies it:
the last line of `mcp__Claude_Browser__tabs_context` says whether the Browser pane is displayed or
hidden. `pane_state()` reads that line and `verdict()` applies the rules, so a hidden pane is never
reported as a render-stall.

    pane_state(line)               -> "displayed" | "hidden" | "unknown"
    verdict(pane_states, results)  -> "painting" | "candidate" | "render-stalled"
                                      | "no-verdict:pane-hidden" | "no-verdict:probe-error"

`unknown` keeps the PRE-0.83 rule (the page's own `{hidden: true}` is the only no-verdict guard):
choosing `hidden` for an unreadable line would put every pass on every surface into no-click mode after
one harness rewording, silently. The price is stated, not hidden: on `unknown` a hidden pane can still be
read as stalled, which is #826 itself. `linkedin_sweep.py record` therefore prints a loud line and opens
a `pane-unreadable` gap on every `unknown` pass, so the failure is visible to the user, not only to a
transcript.

UNVERIFIED (dev #826, R2-SURF-1): the harness line says whether the owner's window is showing the
session. It does not say the pane is PAINTING. A pane that reads `displayed` while the window is
occluded, on another Space, on a sleeping display or behind a locked screen keeps the pre-0.83 outcome
(the #96 verdict fires on it).

Usage:
    python3 scripts/pane_probe.py --print     # emit PROBE_JS verbatim, for a byte-equal diff
                                               # against the fenced copy in linkedin-runner.md
    python3 scripts/pane_probe.py --verdict --pane "<tabs_context last line | not-pane>" [--pane ...] \\
        --result '<probe json>' [--result ...]
                                               # prints one line: VERDICT <a word from verdict()>

Python 3.9+. Standard library only.
"""

import argparse
import json
import re
import sys

# ⭐⭐ THE PROBE ITSELF — byte-equal to the fenced copy between `<!-- pane-probe:begin -->` and
# `<!-- pane-probe:end -->` in plugins/jobsearch/agents/linkedin-runner.md. Edit both, in the
# same commit, or `TestPaneProbeFenceMatchesShippedConstant` in test_checks.py goes red.
PROBE_JS = """(async () => {
  if (document.visibilityState !== 'visible') return {hidden: true};
  let painted = false;
  requestAnimationFrame(() => requestAnimationFrame(() => { painted = true; }));
  await new Promise(r => setTimeout(r, 4000));
  if (painted) return {painted: true};
  await new Promise(r => setTimeout(r, 0));
  return {painted: false, tasks_ran: true, ready: document.readyState};
})()"""

# The only identifiers PROBE_JS may ever reference — see the module docstring and
# test_checks.py's `TestPaneProbeCallNameAllowlist`. Never imported by the test as the source of
# truth (the test re-derives what the constant actually contains, by regex); this is
# documentation the test's own failure message can point back to.
ALLOWED_CALLS = ("document.visibilityState", "document.readyState",
                 "requestAnimationFrame", "setTimeout", "Promise")

# The harness's own wording, observed 2026-11-11 (TESTED by the controller; the literals are pinned, with who
# called and in what view state, in tests/pane_state_lines.json). Anything that does not match is `unknown`,
# never a guess: a reworded line must be loud, not silently read as one of the two.
_PANE_LINE_RE = re.compile(r"^The Browser pane is currently (displayed|hidden)\.$")

# The pane states a caller may hand to `verdict`. `not-pane` is the runner's word for "this pass runs on the
# Chrome extension", which has no pane line to read.
PANE_STATES = ("displayed", "hidden", "unknown", "not-pane")


def pane_state(line):
    """`"displayed"`, `"hidden"` or `"unknown"` from a `mcp__Claude_Browser__tabs_context` result.

    Takes the LAST non-empty line, strips trailing whitespace (a stray `\\r` included) and matches the
    harness wording exactly. A body with no state line, the not-open wording (never observed, so never
    quoted) and any reworded text are `unknown`. `None` and non-strings are `unknown` too."""
    if not isinstance(line, str):
        return "unknown"
    lines = [ln.rstrip() for ln in line.splitlines() if ln.strip()]
    if not lines:
        return "unknown"
    m = _PANE_LINE_RE.match(lines[-1])
    return m.group(1) if m else "unknown"


def _pane_arg(arg):
    """The CLI's `--pane` value as a state: the literal `not-pane` stays itself (the Chrome-extension
    executor), anything else is a `tabs_context` result read by `pane_state`."""
    return "not-pane" if isinstance(arg, str) and arg.strip() == "not-pane" else pane_state(arg)


def _shape(result):
    """`"hidden"`, `"painted"`, `"candidate"` or `None` (not a shape PROBE_JS returns). Exact: an extra
    or a missing key is not the probe's answer."""
    if not isinstance(result, dict):
        return None
    if result == {"hidden": True}:
        return "hidden"
    if result == {"painted": True}:
        return "painted"
    keys = set(result)
    if (result.get("painted") is False and result.get("tasks_ran") is True
            and {"painted", "tasks_ran"} <= keys <= {"painted", "tasks_ran", "ready"}):
        return "candidate"
    return None


def verdict(pane_states, results):
    """The frame probe's verdict, from the harness's pane states and the probe's results. In order:

      1. any pane state is `hidden`                     -> `no-verdict:pane-hidden`   (dev #826, P1)
      2. any result is `{hidden: true}`                 -> `no-verdict:pane-hidden`   (either executor)
      3. no result, or one that is not a PROBE_JS shape -> `no-verdict:probe-error`
      4. any `{painted: true}`                          -> `painting`
      5. one candidate -> `candidate`; two or more      -> `render-stalled`

    Rule 5 is the #96 verdict, and a `displayed` pane gets it unchanged (P5); `not-pane` and `unknown` get
    the pre-0.83 verdict. The 4-second spacing between candidates stays prose: this function cannot see
    time. `ValueError` on a state outside `PANE_STATES`: a typo must be loud, not read as a state."""
    states = list(pane_states or [])
    for st in states:
        if st not in PANE_STATES:
            raise ValueError("pane state %r is not one of %r" % (st, PANE_STATES))
    if "hidden" in states:
        return "no-verdict:pane-hidden"
    shapes = [_shape(r) for r in (results or [])]
    if "hidden" in shapes:
        return "no-verdict:pane-hidden"
    if not shapes or None in shapes:
        return "no-verdict:probe-error"
    if "painted" in shapes:
        return "painting"
    return "candidate" if len(shapes) == 1 else "render-stalled"


def _parse_result(raw):
    """A `--result` value as JSON. An unreadable one becomes a value `_shape` refuses, so the verdict is
    `no-verdict:probe-error`: never a crash, never a guess."""
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--print", dest="do_print", action="store_true",
                    help="emit PROBE_JS verbatim to stdout")
    ap.add_argument("--verdict", dest="do_verdict", action="store_true",
                    help="print the probe's verdict from --pane and --result (dev #826)")
    ap.add_argument("--pane", action="append", default=[],
                    help="with --verdict: the last line of a tabs_context result, or the literal not-pane "
                         "when the pass runs on the Chrome extension; repeat it per read")
    ap.add_argument("--result", action="append", default=[],
                    help="with --verdict: one probe result as JSON, e.g. '{\"painted\": true}'; repeat it "
                         "per probe")
    args = ap.parse_args()
    if args.do_print:
        print(PROBE_JS)
        return 0
    if args.do_verdict:
        print("VERDICT %s" % verdict([_pane_arg(p) for p in args.pane],
                                     [_parse_result(r) for r in args.result]))
        return 0
    print("pane_probe.py holds PROBE_JS, the render-stall probe run on the pane's own "
          "executor by name (linkedin-runner.md's FRAME PROBE section), and the verdict that decides "
          "what its result means. --print emits it verbatim, for diffing against the fenced copy in "
          "that file; --verdict --pane <tabs_context last line> --result <json> prints the verdict.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
