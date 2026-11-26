"""Does a role have a pitch? The one predicate, defined once (dev #1071, jobsearch 0.95.0; design-cover-letters.md § 8.1).

A role **has a pitch** when its `fit` is an object whose `requirements` is a list holding at least one item
with verdict `aligned` or `partial` and a non-empty `pitch_line`: exactly when `fit_report.py --pitch` has at
least one pitch line to print. A letter for a role without one is a stop, not a draft:

* `state(opp)` returns one of
    "ok"        a pitch exists.
    "no-fit"    there is no fit analysis to read: `opp` is None, `opp["fit"]` is not an object, or its
                `requirements` is not a list. (A `fit` of `{}` is this, not a pitch-less fit.)
    "no-pitch"  the fit was analysed and nothing in it is aligned or partial with a pitch line: a letter
                here is more likely for a wrong role than one to write, and the person decides.
* `pitch_lines(fit)` returns the `(verdict, requirement, pitch_line, evidence)` items `fit_report.py --pitch`
  prints, in order. It is empty exactly when `state` is not `"ok"` for an analysed fit.

`fit_report.py` (an entry point) and the `letters/` package (which may not import an entry point) both call
this module, so the two cannot disagree about when a role has a pitch.

A core module: standard library only, no profile read. Python 3.9+.
"""

PITCH_VERDICTS = ("aligned", "partial")


def pitch_lines(fit):
    """[(verdict, requirement, pitch_line, evidence)] for each requirement worth pitching, in order."""
    reqs = fit.get("requirements") if isinstance(fit, dict) else None
    if not isinstance(reqs, list):
        return []
    return [(q["verdict"], q.get("requirement"), q["pitch_line"], q.get("evidence"))
            for q in reqs if isinstance(q, dict) and q.get("verdict") in PITCH_VERDICTS and q.get("pitch_line")]


def state(opp):
    """"ok" | "no-fit" | "no-pitch" for an opportunity row (or None)."""
    fit = opp.get("fit") if isinstance(opp, dict) else None
    if not isinstance(fit, dict) or not isinstance(fit.get("requirements"), list):
        return "no-fit"
    return "ok" if pitch_lines(fit) else "no-pitch"
