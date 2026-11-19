"""deploying.adoptgate -- the adopt publish gate (site-fidelity 5.0.4): refuse to publish over a site whose adopt measured a
difference from the person's own builder, and re-check a MARKUP-ONLY record against the build (R2-12).
"""
import os
import parity_classes
from adoption import parity as adopt
from deploying.gitrun import DeployError, _git


def check_adopt_record(repo):
    """Refuse to publish over a site whose adopt measured a difference from the person's own builder. When
    HEAD carries `.site-studio/adopt-parity.json` and its verdict is not EQUAL, ACCEPTED or MARKUP-ONLY,
    site-studio's build differs from what that builder publishes, so the builder stays the publisher until
    `adopt.py remeasure` says otherwise. No record is 0.2.0's behaviour (a site made by setup, or adopted by
    0.2.0); an unreadable record refuses, naming the file. Returns the record when its verdict is MARKUP-ONLY, for
    `recheck_markup_only` to hold against the build once it is made (R2-12), else None."""
    shown = _git(repo, "show", "HEAD:" + adopt.PARITY_RECORD_REL, check=False, full=True)
    if shown.returncode != 0:
        return None
    try:
        rec = adopt.parse_parity_record(shown.stdout.decode("utf-8", "replace"))
    except adopt.PlanError as e:
        raise DeployError("%s (fix or delete the file, or run `adopt.py remeasure`)" % e)
    if rec["verdict"] in ("EQUAL", "ACCEPTED"):
        return None
    if rec["verdict"] == "MARKUP-ONLY":
        return rec
    raise DeployError(adopt_refusal(rec))


def recheck_markup_only(rec, out_dir):
    """R2-12. MARKUP-ONLY is a property of the CSS and scripts PRESENT, not of the class names alone, so an
    unrelated later commit can make a recorded token visible. Re-run rules 3 to 5 (`parity_classes.recheck`) for
    the record's `tokens` against the build just made, in `out_dir`, and refuse on any token a stylesheet or script
    now names, an attribute selector or `attr(` now present, or an off-origin stylesheet or script now loaded. The
    cheap record parse and the refusal of every other verdict stay in `check_adopt_record`, before the build."""
    if rec is None:
        return
    files = {}
    for dirpath, _dirs, names in os.walk(out_dir):
        for name in names:
            full = os.path.join(dirpath, name)
            with open(full, "rb") as fh:
                files[os.path.relpath(full, out_dir).replace(os.sep, "/")] = fh.read()
    tokens = rec.get("tokens")
    if not isinstance(tokens, dict):
        raise DeployError("the adopt parity record says MARKUP-ONLY but lists no tokens to hold against the build; "
                          "run `adopt.py remeasure`")
    now = parity_classes.recheck(tokens, files)
    if now:
        first = ["%s %s: %s" % (k, n, why) if n else why for k, n, why in now[:3]]
        raise DeployError("this site was adopted with parity MARKUP-ONLY, but the build now has %d reason%s a "
                          "recorded difference is visible (%s%s); the record no longer holds. Run `adopt.py "
                          "remeasure`" % (len(now), "" if len(now) == 1 else "s", "; ".join(first),
                                          "; ..." if len(now) > 3 else ""))


def adopt_refusal(rec):
    """The refusal sentence for a record whose verdict is not EQUAL or ACCEPTED. One per verdict, because each has
    a different truth and a different way out (design-site-fidelity 5.0.4 and 8.3; deployment-auditor gap 15):
    DIFFERENT was measured and listed (`remeasure --accept` after reading it); NOT APPLICABLE measured nothing
    because no builder was found (`remeasure --accept` is "site-studio's build replaces my site, unmeasured");
    UNVERIFIED could not measure and `--accept` refuses it, so the only way out is to make it measurable (install
    node) and run `remeasure` again. The gate itself is unchanged: all three refuse."""
    verdict = rec["verdict"]
    if verdict == "NOT APPLICABLE":
        return ("this site was adopted with parity NOT APPLICABLE: adopt found no builder of your own to compare "
                "site-studio's build against, so nothing was measured, and publishing with site-studio would "
                "replace what your site publishes today, unmeasured. If you accept that, run `adopt.py remeasure "
                "--accept`. If a builder of yours should be compared, put it in the repo and run `adopt.py "
                "remeasure`.")
    if verdict == "UNVERIFIED":
        return ("this site was adopted with parity UNVERIFIED: adopt could not measure (there is no node on this "
                "computer, your builder failed, or site-studio's build refused the converted tree; `adopt.py "
                "remeasure` prints which), so it is not known whether site-studio's build differs from what your "
                "builder publishes. Your builder stays your publisher. `adopt.py remeasure --accept` refuses "
                "UNVERIFIED, because nothing was measured to show you. Install node if it is missing, fix the "
                "builder if it failed, or settle what site-studio's build refuses, then run `adopt.py remeasure` "
                "again.")
    diffs = rec["differences"]
    first = ("; first: %s %s" % (diffs[0][1], diffs[0][0])) if diffs else ""
    return ("this site was adopted with parity %s: site-studio's build differs from what your own builder "
            "publishes (%d difference%s%s). Your builder stays your publisher. Run `adopt.py remeasure`, "
            "or accept the listed differences with `adopt.py remeasure --accept`."
            % (verdict, len(diffs), "" if len(diffs) == 1 else "s", first))
