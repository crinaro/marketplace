"""Migration 0.86.0: `m_0_86_0_proposals()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import os
from migrations.support_pins import _network_first_pin_needed

VERSION = "0.86.0"


PROPOSALS_BY = "m_0_86_0_proposals"
PROPOSALS_FILE = "proposals.jsonl"


def m_0_86_0_proposals(profile, apply_it, _inject_fault=None):
    """0.86.0 -- scaffold the `proposals` store (dev #834; design-network-first.md section 12.2; owner ruling 3: a contract engagement
    has a proposal record beside `applications`).

    WHAT IT DOES: creates an EMPTY `data/proposals.jsonl` when it is absent, and nothing else. No legacy record holds a proposal in a
    form a migration may read (a contract note is prose, and a migration that cannot know a field's type must not interpret it), so
    there is nothing to transform and nothing to preserve: an absent store is never a file the owner wrote. A profile scaffolded by
    0.86.0 (`init_profile.STORES`) is born with it, and `validate_data.check_store_introduction` names it missing at or past 0.86.0.

    PREREQUISITES, read-only, each PENDING naming its cause (never a false "0 done"): the 0.86.0 profile PIN is in the journal (this
    migration is registered after `m_0_86_0_network_first`, which writes it first; if that one is itself pending, the pin is absent and
    this waits for it, because a 0.86.0 shape must never reach a profile an older engine could still treat as its own), and `data/` is a
    writable directory.

    IDEMPOTENT: the file exists => done, nothing written (an existing store is never truncated or touched, whatever it holds).
    The success condition is a re-check that the file is there and is empty-or-JSONL-readable as created.

    `_inject_fault` is a TEST SEAM: "before-create" raises before anything is written (a crash the next run must complete from).
    Returns `(done, message)`."""
    import _atomic
    pending = "  ⏳ 0.86.0 PENDING -- %s. Nothing was written. This runs again next session."
    data = os.path.join(profile, "data")
    path = os.path.join(data, PROPOSALS_FILE)
    if os.path.exists(path):
        return True, ""
    if _network_first_pin_needed(profile):
        if not apply_it:
            return True, "  would create an empty data/%s once the profile pin is recorded (the network-first migration, just above)" \
                % PROPOSALS_FILE
        return False, pending % ("the 0.86.0 profile pin is not in data/runs.jsonl yet (the network-first migration has not completed), "
                                 "so a 0.86.0 store is not scaffolded")
    if not os.path.isdir(data):
        return False, pending % "data/ is not a directory"
    if not os.access(data, os.W_OK | os.X_OK):
        return False, pending % "data/ is not writable"
    if not apply_it:
        return True, "  would create an empty data/%s (the proposals store)" % PROPOSALS_FILE
    if _inject_fault == "before-create":
        raise RuntimeError("injected fault: before-create")
    try:
        _atomic.write_text(path, "")
    except OSError as e:
        return False, pending % ("data/%s could not be created: %s" % (PROPOSALS_FILE, e))
    if not os.path.exists(path):
        return False, pending % ("data/%s is not there after the write" % PROPOSALS_FILE)
    return True, "  ✅ proposals (0.86.0) -- created an empty data/%s" % PROPOSALS_FILE
