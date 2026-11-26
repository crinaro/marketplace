"""The 0.94.0 verbs and flags' shared wiring: the pin's refusal, and the one dispatch point `record.py` reaches `read-withdraw` through (jobsearch 0.94.0, dev 1062, 1063;
docs/design-role-first.md 3.5, 4.4, 6.1, 6.3, 13).

P1 shipped `read-withdraw` and `read-jd --body` as STUBS that refused. P3 builds them, and nothing here is a stub any more:

  read-withdraw <opp> --at <the read's at> --why "..."   `recording/withdraw_write.py` (the write) over `recording/read_withdraw.py` (the transform)
  read-jd ... --body "<60-200 characters of the description>"   `recording/reads.py` checks it with `recording/body_evidence.py`, where the role and the company are known

(`decide <opp> pursue --no-target`, P5, is built in `recording/decisions.py`.) `flag_refusal` is kept because `record.py`'s `main` still calls it before it dispatches; it refuses
nothing now and returns None, and the call can be dropped from `main` in a later cleanup (the owner of `record.py` decides).

`pin_refusal` is the ONE "no 0.94.0 pin" refusal a recording-side writer uses (RF4, design 3.5). `journaling.pins` owns the sentence; this module only supplies the profile
(`profile_paths.ROOT`).

Capability module of record.py (an entry point over `recording/`)."""

from journaling.pins import pin_missing_line
from recording import profile_paths as _paths
from recording.withdraw_write import cmd_read_withdraw  # noqa: F401  -- `record.py` reaches the verb here; the module is the verb's own


def pin_refusal(what):
    """`None` when the profile carries the 0.94.0 pin, else the line a writer of `what` refuses with (nothing written)."""
    return pin_missing_line(_paths.ROOT, what)


def flag_refusal(args):
    """None: no flag is a stub any more (P3 built `--body`, P5 built `--no-target`). Kept for `record.py`'s call; see the module docstring."""
    return None
