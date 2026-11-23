"""ruled_out: the one predicate for "already ruled out" (a `pass` verdict or `status: passed`),
moved out of `pipeline_index.py` unchanged (design-presence-report.md §11 B0) so a capability
module can read it without importing an entry point. `pipeline_index` re-exports it."""


def is_excluded(o):
    """The one definition of 'already ruled out'. Do not re-derive this elsewhere.

    Deliberately does NOT include `status: expired` — see the module docstring: a re-sighting
    of an expired role is a repost, and treating it as 'already ruled out' would silently drop
    the second chance the candidate never declined."""
    return o.get("verdict") == "pass" or o.get("status") == "passed"
