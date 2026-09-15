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

Usage:
    python3 scripts/pane_probe.py --print     # emit PROBE_JS verbatim, for a byte-equal diff
                                               # against the fenced copy in linkedin-runner.md

Python 3.9+. Standard library only.
"""

import argparse
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


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--print", dest="do_print", action="store_true",
                    help="emit PROBE_JS verbatim to stdout")
    args = ap.parse_args()
    if args.do_print:
        print(PROBE_JS)
        return 0
    print("pane_probe.py holds PROBE_JS, the render-stall probe run on the pane's own "
          "executor by name (linkedin-runner.md's FRAME PROBE section). --print emits it "
          "verbatim, for diffing against the fenced copy in that file.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
