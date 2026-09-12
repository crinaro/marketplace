"""The `config.json` key names this engine actually reads, spelled ONCE — a leaf like
`_ats_keys.py`, applied beyond ATS.

WHY THIS EXISTS (Query or Citation C1, D5)
-------------------------------------------
The first pass of the brief reader named `chase_days`, `reconnect_days` and
`brief_max_age_hours` — none of which exists anywhere in a real profile, while every profile
already carries `communications.chase_after_days` / `communications.no_response_after_days`,
read by nothing until C1. Three defaults, two spellings, no registry: exactly the
`_ats_keys.py` defect (RECEIPT_SENDER_DOMAINS vs `sender_domains`), one layer up. This module
is the fix, generalised past ATS: a config key a reader resolves is declared here ONCE, with
its default, so "what does this engine actually read from config.json" has one answer instead
of as many as there are readers.

C1 registers exactly the two keys it reads (`your_move.conversation_axis()`'s window and the
reconnect threshold, both consumed by `brief.py`'s register computation — see
design-query-or-citation.md §6). States & Views V1 (not built) adds `ats.*` and its own keys to
`READER_KEYS`, and builds `profile.py --options` / `doctor.py`'s reader over this registry — this
module ships the registry now so V1 extends it rather than inventing a second one.

This module is a LEAF: no imports beyond `check_followups.DEFAULT_DAYS` (the one existing
definition of the 7-day default — reusing it, rather than re-typing "7", is what keeps the two
from drifting the way the ATS keys once did), no I/O of its own.

FIXED — engine constants C1 hardcodes rather than reading from config (declared here so a
reader asking "is this configurable?" gets a documented "no, and here is why" instead of
silence): the `--overlap` shingle length, and the four hex digits in a `brief:` id.

Python 3.9+. Standard library only.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_followups as _cf

# `config.json.communications.chase_after_days` — the axis's `silent` threshold (your_move.py's
# `conversation_axis`): below this many days since the last outbound touch with no verified
# reply, the axis is `waiting` ("premature" to chase); at or past it, `silent` (verified) or
# `silence-unverified` applies. Every profile already carries this key (pre-dating C1); the
# default below is what a profile that has NOT set it gets, imported from the one other reader
# that already needed a "how long before I chase" number rather than re-declaring "7".
CHASE_AFTER_DAYS = "communications.chase_after_days"
CHASE_AFTER_DAYS_DEFAULT = _cf.DEFAULT_DAYS

# `config.json.communications.no_response_after_days` — the register's `chase` -> `reconnect`
# threshold (brief.py): verified silence below this many days is a `chase`, at or past it a
# `reconnect`. Declared once, here — not re-typed at each call site.
NO_RESPONSE_AFTER_DAYS = "communications.no_response_after_days"
NO_RESPONSE_AFTER_DAYS_DEFAULT = 14

# What a reader resolves — and therefore exactly what a scaffold seeding fresh defaults would
# need to seed (the `_ats_keys.READER_KEYS` / `resume_variants.SUBMITTED` mirror precedent).
# Both keys already exist on every profile pre-dating C1 (they were declared, unread, before
# this registry existed) — nothing seeds them; `describe()` below reports the default when a
# profile has not set one, same as the register line at brief.py §3.2 prints "default — not in
# your file".
READER_KEYS = frozenset({CHASE_AFTER_DAYS, NO_RESPONSE_AFTER_DAYS})

# Engine constants C1 hardcodes rather than reading from config — never resolved by describe(),
# printed here so "is this configurable?" has a documented answer.
FIXED = {
    "overlap_shingle_words": 8,     # brief.py --overlap's shared-run window, in words
    "brief_id_hex_digits": 4,       # the random suffix on a `brief:<ts>-<hex>` id
}


def _get_dotted(cfg, dotted):
    node = cfg or {}
    for part in dotted.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def describe(cfg, key):
    """(value, provenance) for a registered `key` against a loaded `config.json` dict —
    `provenance` is one of the exact two phrases brief.py's register line prints, so every
    caller renders identically: `"in your config.json"` or `"default — not in your file"`.
    Raises `KeyError` for a key this registry does not know — never guessed over."""
    if key == CHASE_AFTER_DAYS:
        default = CHASE_AFTER_DAYS_DEFAULT
    elif key == NO_RESPONSE_AFTER_DAYS:
        default = NO_RESPONSE_AFTER_DAYS_DEFAULT
    else:
        raise KeyError("config_keys does not know %r — READER_KEYS: %s"
                       % (key, ", ".join(sorted(READER_KEYS))))
    v = _get_dotted(cfg, key)
    if v is None:
        return default, "default — not in your file"
    return v, "in your config.json"
