"""jd_source: the `fit.jd_source` check (R3) and its closed `unavailable: <reason>` vocabulary,
moved out of `validate_data.py` unchanged (design-presence-report.md §11 B0, "Files that may not
grow"). `validate_data` re-exports every moved name."""

import re


# R3: a JD read that was TRIED and failed satisfies the read. It is recorded in `fit.jd_source` as
# `unavailable: <reason>` -- a CLOSED prefix, so a hand-typed "unavailable" or an invented reason is
# refused instead of passing as a read. A null `jd_source` still means not tried.
JD_UNAVAILABLE_PREFIX = "unavailable"
# dev #765: `manual-board` -- the only address the role carries is on a `manual-candidate` channel's
# `board_hosts`, a site whose terms forbid automated access, so the read was REFUSED rather than tried.
JD_UNAVAILABLE_REASONS = ("login-wall", "dead-link", "no-url", "surface-cannot-read", "manual-board")
JD_UNAVAILABLE_RE = re.compile(r"^unavailable: (login-wall|dead-link|no-url|surface-cannot-read|manual-board)$")   # == the tuple above, pinned by its test (G3: no join at import)


def check_jd_source(jd_source, label, problems):
    """`fit.jd_source` (R3): free text naming what was read, EXCEPT that anything beginning
    `unavailable` is a read that was tried and failed and must be exactly `unavailable: <reason>`
    with the reason in the closed set. A null is 'not tried' and is legal."""
    if jd_source is None:
        return
    if not isinstance(jd_source, str):
        problems.append("%s: fit.jd_source must be a string or null -- %r" % (label, jd_source))
        return
    if jd_source.lower().startswith(JD_UNAVAILABLE_PREFIX) and not JD_UNAVAILABLE_RE.match(jd_source):
        problems.append("%s: fit.jd_source %r must be exactly 'unavailable: <reason>' with the "
                        "reason one of {%s}" % (label, jd_source, ", ".join(JD_UNAVAILABLE_REASONS)))
