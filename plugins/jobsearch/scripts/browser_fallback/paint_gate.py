"""paint_gate: the paint gate's rules and the one reader of a probe's answer (jobsearch 0.90.0, dev 858; 0.94.0, dev 1064, design-role-first.md 19 N3, N4).

Capability module of `pane_probe.py`, which keeps `PROBE_JS`, the pane line, `verdict()` and the CLI, and re-exports every name here (the tests, the agents and `route.py` read them there).
It was moved out of the entry point whole, with `_shape` unchanged byte for byte (its source is pinned by hash in `tests/test_browser_fallback_agents.py`), because the entry point is over
its line budget and may not grow: the 0.94.0 size rules (`set-size`, a first hidden answer that is `probe-again`) are what made this module necessary.

`paint_gate(results)` reads the results of `PROBE_JS` (oldest first) and answers one word: `paints`, `not-painting`, `probe-again`, `probe-error` or, from 0.94.0, `set-size`. The pane
line is never an input. Results with no size (an older fenced probe) are judged exactly as before 0.94.0.

Pure. Python 3.9+, standard library only."""

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


# The words `paint_gate` returns, and the `verdict()` word each one is the gate's reading of. Declared once so
# the CLI, the agents' recorded `gate:` values (jd_read.GATE_WORDS) and the agreement test name the same set.
GATE_WORDS = ("paints", "not-painting", "probe-again", "probe-error", "set-size")
GATE_OF_VERDICT = {                      # for results with no size (an older fenced probe): see `paint_gate`
    "no-verdict:pane-hidden": "not-painting",
    "no-verdict:probe-error": "probe-error",
    "painting": "paints",
    "candidate": "probe-again",
    "render-stalled": "not-painting",
}
# The words that are REQUESTS, never stored (`jd_read.GATE_WORDS` is `GATE_WORDS` less these): probe again, or set the size and probe again.
REQUEST_WORDS = ("probe-again", "set-size")
# 0.94.0 (dev 1064, design-role-first.md 19 N2, N3): the size a browsing agent gives its own tab, and the size under which a page cannot fill.
TARGET_W, TARGET_H = 1280, 3200
MIN_W, MIN_H = 600, 800


def _int(v):
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def _size(result):
    """`(w, h)` when `result` carries BOTH as non-negative ints (the sized probe), else None (an older fenced probe, or no size at all)."""
    if isinstance(result, dict) and _int(result.get("w")) and _int(result.get("h")):
        return result["w"], result["h"]
    return None


def _unsized(result):
    """`result` without its `w` and `h`, so `_shape` and `verdict()` (both unchanged) read a result of the sized probe. A result whose size is not both
    ints is returned as it came, so `_shape` refuses it."""
    if _size(result) is None:
        return result
    return {k: v for k, v in result.items() if k not in ("w", "h")}


def paint_gate(results):
    """The paint gate's word for a step's `PROBE_JS` results, oldest first (dev #858, design §3.1; 0.94.0, dev 1064, design-role-first.md 19 N3).

    Results with NO size (an older fenced probe) are judged exactly as before 0.94.0, by `_gate_unsized`. When any result carries a size, in order:

      0. the LAST result is sized and either side is 0, or under 600 x 800   -> `set-size`  (set the tab to 1280 x 3200, then probe again: the page could not fill)
      1. the last result is `{hidden: true}`                                  -> `probe-again` the first time, `not-painting` when an earlier result was hidden too
                                                                                 (the second answer, at least 4 s after the first: the next call may have woken the tab)
      2. no result, or one that is not a PROBE_JS shape                       -> `probe-error`
      3. any `{painted: true}`                                                -> `paints`  (a later paint clears the latch: route.py)
      4. exactly one candidate                                                -> `probe-again`
      5. two or more candidates                                               -> `not-painting`

    The latch of `route.py` is set only by `not-painting`, so a first hidden answer never sets it. The pane line is not an input.

    The words below describe the unsized rules, which are unchanged:

    The paint gate's word for a step's `PROBE_JS` results (dev #858, design §3.1). First match wins, in the
    order of `verdict()`'s rules 2-5, and the pane line is not an input:

      1. any result is `{hidden: true}`                 -> `not-painting`
      2. no result, or one that is not a PROBE_JS shape -> `probe-error`
      3. any `{painted: true}`                          -> `paints`
      4. exactly one candidate                          -> `probe-again`   (probe again, at least 4 s later)
      5. two or more candidates                         -> `not-painting`

    Rule 1 is a VISIBILITY signal: `PROBE_JS` returns `{hidden: true}` before any frame is requested when
    `document.visibilityState` is not `visible`, so it says "this document is not shown", not "this document
    does not paint" (see the module docstring). `probe-error` falls back like `not-painting`: a fallback is
    cheap and visible, a silent read of a page that never rendered is not. The spacing between candidates
    stays prose, as in `verdict()`. A result is judged by the same `_shape` as `verdict()`, never a second
    parser."""
    results = list(results or [])
    if not any(_size(r) for r in results):
        return _gate_unsized(results)
    shapes = [_shape(_unsized(r)) for r in results]
    last = _size(results[-1])
    if last is not None and (last[0] == 0 or last[1] == 0 or last[0] < MIN_W or last[1] < MIN_H):
        return "set-size"
    if shapes[-1] == "hidden":
        return "not-painting" if "hidden" in shapes[:-1] else "probe-again"
    if None in shapes:
        return "probe-error"
    if "painted" in shapes:
        return "paints"
    return "probe-again" if shapes.count("candidate") == 1 else "not-painting"


def _gate_unsized(results):
    """The gate before 0.94.0, for results with no size: the numbered rules of `paint_gate`'s docstring, first match wins."""
    shapes = [_shape(r) for r in results]
    if "hidden" in shapes:
        return "not-painting"
    if not shapes or None in shapes:
        return "probe-error"
    if "painted" in shapes:
        return "paints"
    return "probe-again" if len(shapes) == 1 else "not-painting"
