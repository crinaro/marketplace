"""presence_rules: a facade. The `presence_changes` store's rules moved unchanged to `presence/store_rules.py`
(design-presence-report.md §8.2; see that module for why), and every moved name stays importable from here
for `recording/presence_verbs.py` and the tests. Python 3.9+, standard library only."""

# Moved out of this file by split_module.py; every moved name stays importable from here until the tests move.
from presence.store_rules import (
    STORE_FILE,
    KINDS,
    BY,
    TARGETS,
    FIELDS_BY_TARGET,
    STATUS_VALUES,
    DECISIONS,
    APPLIED_BY,
    SKILLS_MAX,
    PUBLIC_SURFACES,
    COMMON,
    KEYS,
    REQUIRED,
    ID_RE,
    DATE_RE,
    TOPIC_RE,
    VARIANT_ID_RE,
    GAP_RES,
    PUBLIC_TAG_RE,
    PresenceStoreError,
    gap_key_refusal,
    load_file,
    id_number,
    _is_date,
    _value_problem,
    _target_problems,
    public_required,
    _proposal_problems,
    _decision_problems,
    check_rows,
    variant_rows,
    check_presence_changes,
)
