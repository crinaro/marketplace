#!/usr/bin/env python3
"""Wait for content — a shipped constant per step kind, never agent prose (design-browser-fallback.md §5).

WHY THIS EXISTS (public #858)
-----------------------------
An agent that judged "the page looks loaded" read a LinkedIn shell: the navigation chrome had rendered and the
posting body had not, so the read came back with a few hundred characters of boilerplate and no quote. Whether a
page has finished is a question with a mechanical answer, so the answer is a script: `READY_JS` runs on the
browser's own executor after every `navigate` and returns a small object, and `verdict()` here reads that object
strictly. Carrying the JavaScript as prose inside five agent files would let the copies drift; so it is a MODULE
CONSTANT here and each agent that uses it carries it byte-equal between fence markers
(`test_checks.py::ReadyJsFences` asserts the equality; this file never reads an agent).

THE TEMPLATE
------------
Timer-based, never `requestAnimationFrame`: a pane that does not paint never produces a frame, so a wait that
needed one would never finish (design §P3, diverged from Playwright's animation-frame stability check). The page
is READY when `document.readyState` is `complete`, the selector (or `body` when `SEL` is null) holds at least
`MIN` characters, and that length is EQUAL across two polls `GAP` apart. A ready page therefore never returns on
the first poll: the minimum wait is one `GAP` (2.5 s).

    POLLS = 4 polls, GAP = 2500 ms   ->  about 10 s nominal
    hidden: timers align to one second (Chrome timer throttling, design §P2)  ->  up to about 12 s
    at most 4 chained timers: a chain of 5 or more runs once a minute after 5 minutes hidden (design §P2)

The allowlist is `ALLOWED_CALLS`. Nothing in the template clicks, scrolls, types or navigates.

ONE SOURCE FOR SELECTORS
------------------------
`STEP_READY` holds each step kind's `SEL` and `MIN`; `READY_JS` is rendered from it, so there is no second copy
to drift. **Every shipped kind has `SEL = None` at release** (the LinkedIn job-view selector is UNDETERMINED,
design §5): until one is pinned, `body` is read, and a page shell can pass as READY. The caller's other trigger
(no quote for `record.py read-jd`, design §3.2) is what catches that case. Pinning a selector is one edit to
`STEP_READY`, and `run_summary`'s `READY CHECK` count (a NOT-READY read on a painting page) is the signal that a
pinned selector has stopped matching.

THE VERDICT IS A SCRIPT TOO
---------------------------
    verdict(raw)  ->  "READY <chars>" | "NOT-READY" | "READY-ERROR"

STRICT. Only the exact shapes `READY_JS` returns are an answer: `{ready: true, chars: <int >= the smallest MIN>}`
is READY; `{ready: false, chars: <int >= -1>[, state: <str>]}` is NOT-READY. Everything else is READY-ERROR: a
`javascript_tool` error or timeout string, text that is not JSON, JSON that is not an object, an extra key, a
missing key, `ready` that is not a bool, `chars` that is a bool, a float or a string. A caller treats READY-ERROR
like NOT-READY; it is never read as ready, and never as a crash. The tool's own timeout against the 12 s hidden
bound is UNDETERMINED (design P-T1, round C step 7); a shorter tool timeout surfaces here as READY-ERROR.

TWO KINDS DECIDE BY CONTENT (dev 1064, jobsearch 0.94.0; design-role-first.md 19.3 N11, N12): `posting-read-linkedin` and `linkedin-results` are not a selector, they are the content
check of `browser_fallback/ready_content.py` ("About the job" with 400 or more characters in its block; 1 or more job cards, every one with text), rendered into `READY_JS` and
read by the same `verdict()` (a results answer carries `cards`, printed `READY <chars> CARDS <n>`). A page of those kinds that passes is READ whatever the paint gate says (paint is
only recorded: a LinkedIn page drew no frames and was complete), which `decide()` states in one place. A shell never passes: a missing heading, a heading with no description
under it, a card with no text and an unstable length are all NOT-READY. Any other page, and any page that fails, keeps the paint gate.

Usage:
    python3 scripts/page_ready.py --print <kind>       # READY_JS for that step kind, verbatim, for a byte-equal
                                                       # diff against the fenced copy in an agent file
    python3 scripts/page_ready.py --verdict '<json>' [--kind <kind>]   # one line: READY <chars> [CARDS <n>] | NOT-READY | READY-ERROR (--kind: the answer's shape and minimum must be that kind's)
    python3 scripts/page_ready.py --decide <kind> --ready '<json>' [--gate <word>]   # READ | ASK-GATE | GATE <word>
    python3 scripts/page_ready.py --kinds              # the step kinds, one per line

Python 3.9+. Standard library only.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from browser_fallback.ready_content import ABOUT_MIN, RESULTS_MIN, render_content

# The polling shape. POLLS x GAP_MS is the nominal bound; HIDDEN_BOUND_MS is the same chain with each timer rounded
# up to a whole second, which is what a hidden page does (Chrome timer throttling). `test_page_ready.py::poll_bound`
# pins POLLS <= 4, POLLS * GAP_MS <= 10000 and HIDDEN_BOUND_MS <= 12000.
POLLS = 4
GAP_MS = 2500
NOMINAL_BOUND_MS = POLLS * GAP_MS
HIDDEN_BOUND_MS = POLLS * (-(-GAP_MS // 1000) * 1000)

# The only identifiers READY_JS may reference. Documentation the test's own failure message can point back to;
# `test_checks.py::ReadyJsAllowlist` derives what the constant really contains, by regex, and checks it.
ALLOWED_CALLS = ("document.readyState", "document.querySelector", "document.body", "innerText",
                 "setTimeout", "Promise",
                 # 0.94.0 (dev 1064): the two content kinds of `browser_fallback/ready_content.py`, read-only
                 "document.querySelectorAll", "getAttribute", "closest", "parentElement", "children", "textContent")

# ⭐ THE SINGLE SOURCE OF SELECTORS. kind -> {"SEL": CSS selector or None (read `body`), "MIN": characters}.
# The kinds are the step kinds of design §4.1. SEL is None for every kind at release: see the module docstring.
STEP_READY = {
    "posting-read": {"SEL": None, "MIN": 200},
    "linkedin-surface": {"SEL": None, "MIN": 200},
    "board-sweep": {"SEL": None, "MIN": 200},
    "research-render": {"SEL": None, "MIN": 200},
    "profile-read": {"SEL": None, "MIN": 200},
}

# 0.94.0 (dev 1064, N11, N12): the two kinds that decide by content. `CHECK` names the content check of `browser_fallback/ready_content.py`; the numbers live there.
CONTENT_READY = {
    "posting-read-linkedin": {"CHECK": "posting-about", "MIN": ABOUT_MIN},
    "linkedin-results": {"CHECK": "results-cards", "MIN": RESULTS_MIN},
}
CONTENT_KINDS = tuple(CONTENT_READY)

# The template. `@@SEL@@`, `@@MIN@@`, `@@GAP@@` and `@@POLLS@@` are the only holes; `render()` fills them and
# nothing else. Byte-equal to design §5 once rendered with SEL = null.
READY_JS_TEMPLATE = """(async () => {
  const SEL = @@SEL@@, MIN = @@MIN@@, GAP = @@GAP@@, POLLS = @@POLLS@@;
  const len = () => { const el = SEL ? document.querySelector(SEL) : document.body;
                      return el ? (el.innerText || '').trim().length : -1; };
  let prev = -2;
  for (let i = 0; i < POLLS; i++) {
    const n = len();
    if (document.readyState === 'complete' && n >= MIN && n === prev) return {ready: true, chars: n};
    prev = n;
    await new Promise(r => setTimeout(r, GAP));
  }
  const n = len();
  return n >= MIN && n === prev && document.readyState === 'complete'
    ? {ready: true, chars: n} : {ready: false, chars: n, state: document.readyState};
})()"""


def render(sel, min_chars, gap_ms=GAP_MS, polls=POLLS):
    """The template with its four holes filled. `sel` is a CSS selector string or None; it is emitted as a JSON
    string literal, so no character of it can end the literal or open a statement. `ValueError` on a `sel` that is
    neither, and on a non-int or non-positive number: a typo must be loud, not rendered."""
    if sel is not None and not isinstance(sel, str):
        raise ValueError("SEL must be a string or None, not %r" % (sel,))
    for name, val in (("MIN", min_chars), ("GAP", gap_ms), ("POLLS", polls)):
        if isinstance(val, bool) or not isinstance(val, int) or val < 1:
            raise ValueError("%s must be a positive int, not %r" % (name, val))
    out = READY_JS_TEMPLATE
    for hole, text in (("@@SEL@@", "null" if sel is None else json.dumps(sel)),
                       ("@@MIN@@", str(min_chars)), ("@@GAP@@", str(gap_ms)), ("@@POLLS@@", str(polls))):
        out = out.replace(hole, text)
    return out


# READY_JS: kind -> the constant an agent carries. Rendered from STEP_READY, so the two cannot disagree.
READY_JS = {kind: render(spec["SEL"], spec["MIN"]) for kind, spec in STEP_READY.items()}
READY_JS.update({kind: render_content(spec["CHECK"], spec["MIN"], GAP_MS, POLLS) for kind, spec in CONTENT_READY.items()})

# What the smallest shipped MIN is: a READY claiming fewer characters than this cannot have come from READY_JS.
_MIN_FLOOR = min(spec["MIN"] for spec in STEP_READY.values())


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _kind_shape(kind):
    """`(floor, wants_cards)` of step kind `kind`: the smallest `chars` a READY answer may claim, and whether its answers carry `cards`. `ValueError` on a kind that is not a step kind."""
    if kind not in READY_JS:
        raise ValueError("unknown step kind %r; the kinds are: %s" % (kind, ", ".join(sorted(READY_JS))))
    if kind in CONTENT_READY:
        return CONTENT_READY[kind]["MIN"], CONTENT_READY[kind]["CHECK"] == "results-cards"
    return STEP_READY[kind]["MIN"], False


def verdict(raw, kind=None):
    """`READY <chars>`, `NOT-READY` or `READY-ERROR` from what `javascript_tool` returned for READY_JS.

    `raw` is the tool's result as text (or an already-parsed value). Strict, see the module docstring: anything
    that is not exactly one of the two shapes READY_JS returns is READY-ERROR, a tool error string included.

    `kind` (jobsearch 0.94.0, dev 1064, review item 9) ties the shape and the minimum to the page kind, because one kind's answer is not another's: `linkedin-results` needs a `cards`
    key (READY: 1 or more cards and `chars` of `RESULTS_MIN` or more); `posting-read-linkedin` needs `chars` of `ABOUT_MIN` (400) or more; every other kind needs its own `MIN`; a `cards`
    key on a kind that has none, or none on the kind that has it, is READY-ERROR, a NOT-READY answer too. `kind=None` is the kind-blind reading older callers use: it cannot tell a results
    answer from a posting's (a posting answer of 250 characters, or a results answer with no `cards`, reads READY), which is why every agent step passes its kind and `decide` always does.
    `ValueError` on a kind that is not a step kind."""
    floor, wants_cards = _kind_shape(kind) if kind is not None else (_MIN_FLOOR, None)
    value = raw
    if isinstance(raw, (str, bytes, bytearray)):
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            return "READY-ERROR"
    if not isinstance(value, dict):
        return "READY-ERROR"
    ready, chars = value.get("ready"), value.get("chars")
    if not isinstance(ready, bool) or not _is_int(chars):
        return "READY-ERROR"
    keys = set(value)
    cards = value.get("cards")
    if "cards" in keys and not (_is_int(cards) and cards >= 0):
        return "READY-ERROR"
    if wants_cards is not None and ("cards" in keys) != wants_cards:
        return "READY-ERROR"                                  # an answer of the wrong shape for its kind
    if ready is True:
        if keys not in ({"ready", "chars"}, {"ready", "chars", "cards"}):
            return "READY-ERROR"
        if "cards" in keys:
            return "READY-ERROR" if cards < 1 or chars < RESULTS_MIN else "READY %d CARDS %d" % (chars, cards)
        return "READY-ERROR" if chars < floor else "READY %d" % chars
    if not keys <= {"ready", "chars", "state", "cards"} or chars < -1:
        return "READY-ERROR"
    if "state" in value and not isinstance(value["state"], str):
        return "READY-ERROR"
    return "NOT-READY"


def decide(kind, raw, gate=None):
    """What a page of step kind `kind` becomes, from the wait's answer `raw` and, when it was asked, the paint gate's word (N11): `READ` when the kind decides by content and the
    content check passed (the gate is never consulted, and a `not-painting` it gave is only recorded); otherwise `ASK-GATE` (no gate word yet) or `GATE <word>` (the caller
    applies the gate's own rules). A generic kind is never `READ` here: its quote decides. `ValueError` on a kind that is not a step kind."""
    if kind not in READY_JS:
        raise ValueError("unknown step kind %r; the kinds are: %s" % (kind, ", ".join(sorted(READY_JS))))
    if kind in CONTENT_KINDS and verdict(raw, kind).startswith("READY "):
        return "READ"
    return "ASK-GATE" if gate is None else "GATE %s" % gate


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--print", dest="print_kind", metavar="KIND",
                    help="emit READY_JS for a step kind verbatim, for a byte-equal diff against a fenced copy")
    ap.add_argument("--verdict", dest="raw", metavar="JSON",
                    help="print READY <chars>, NOT-READY or READY-ERROR for one javascript_tool result")
    ap.add_argument("--kind", default=None, help="with --verdict: the step kind the result is for; ties the shape and the minimum to it (dev 1064). Without it the reading is kind-blind")
    ap.add_argument("--kinds", action="store_true", help="list the step kinds, one per line")
    ap.add_argument("--decide", metavar="KIND", help="print READ, ASK-GATE or GATE <word> for a page of KIND, from --ready and, if asked, --gate")
    ap.add_argument("--ready", default=None, help="with --decide: the wait's javascript_tool result (JSON, or the tool's own error text)")
    ap.add_argument("--gate", default=None, help="with --decide: the paint gate's word")
    args = ap.parse_args(argv)
    if args.print_kind is not None:
        if args.print_kind not in READY_JS:
            print("page_ready.py: unknown step kind %r; the kinds are: %s"
                  % (args.print_kind, ", ".join(sorted(READY_JS))), file=sys.stderr)
            return 2
        print(READY_JS[args.print_kind])
        return 0
    if args.decide is not None:
        try:
            print(decide(args.decide, args.ready if args.ready is not None else "", args.gate))
        except ValueError as e:
            print("page_ready.py: %s" % e, file=sys.stderr)
            return 2
        return 0
    if args.raw is not None:
        try:
            print(verdict(args.raw, args.kind))
        except ValueError as e:
            print("page_ready.py: %s" % e, file=sys.stderr)
            return 2
        return 0
    if args.kinds:
        print("\n".join(sorted(READY_JS)))
        return 0
    print("page_ready.py holds READY_JS, the wait-for-content script run after every navigate (one constant "
          "per step kind, selectors only from STEP_READY), and the strict verdict that reads its result. "
          "--print KIND emits it verbatim; --verdict JSON prints READY <chars>, NOT-READY or READY-ERROR.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
