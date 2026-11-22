"""mail_coverage: each mailbox's verified sweep coverage, as the reply-rate hole check reads it (jobsearch 0.91.0 B5, design-build-reach.md
8, R2 N11).

`coverage(root)` is `({mailbox: [(from_utc, through_utc)]}, problem)`: every `ok: true` `swept` row of the profile's journal, read by
`journaling.instants.coverage_intervals` (one parser of a sweep window, dev #807) and merged by `_merge_intervals`, exactly the
intervals `covered_through` answers from. No journal is no coverage, and every email ask then reads as unswept: a missing sensor is
never coverage. An unreadable journal is `problem`, and `reach.measures.rates` then prints `not checked` with it. `declared_zone()` is
the profile's zone the day boundaries are read in.

WHY THIS IS NOT IN `reach/`. `reach/` is imported by `access.py`, which sits in the plugin's largest import cycle with `journal.py`;
a `reach/` module importing `journaling` (owned by `journal.py`) would pull `reach/` and `graph.py` into that cycle, and a second
top-level importer of `journaling` would split it out as a node of its own inside it (`check_segmentation.py` G6). This package has one
importer, `build_reach.py`, which nothing imports. Capability module of `build_reach.py`. Python 3.9+, standard library only."""

from journaling import instants as _inst
from journaling.journal_file import read as _read_journal
from journaling.tables import JournalError


def coverage(root):
    """`({mailbox: merged aware intervals}, problem)` for the profile at `root` (module docstring)."""
    try:
        recs = _read_journal(root)
    except FileNotFoundError:
        return {}, None
    except (JournalError, OSError) as e:
        return {}, "journal unreadable (%s)" % e
    boxes = sorted({r.get("mailbox") for r in recs if r.get("event") == "swept" and r.get("mailbox")})
    return {mb: _inst._merge_intervals(_inst.coverage_intervals(recs, mb)) for mb in boxes}, None


def declared_zone():
    """The profile's declared zone (`geography.timezone`, then `TZ`), or None for the host's rules."""
    return _inst._declared_zone()
