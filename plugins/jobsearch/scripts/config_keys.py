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

# States & Views V1 (design-states-and-views.md §3c/§15.7) — the owner's own two values:
# "make sure the is a configurable setting" (30 days, `propose`, not `auto`). Home is the
# EXISTING `ats` section (about the ATS's clock and receipts), never `applying` (a phase
# directory name that is not a config section at all — §15.7's own correction).
ATS_SILENCE_DAYS = "ats.silence_days"
ATS_SILENCE_DAYS_DEFAULT = 30
ATS_CLOSE = "ats.close"
ATS_CLOSE_DEFAULT = "propose"
ATS_CLOSE_VALUES = ("propose", "auto")

# design-linkedin-runner-resilience.md §1 (public #47/#96) — how long a taken-but-never-released
# pane lock is trusted to mean "a run is genuinely still using it" before the next `--take`
# treats it as abandoned and takes over. No pass duration exists anywhere in this repo and this
# design was read-only against the tree, so the default below is UNVERIFIED — the honest
# state, not a guess dressed as a measurement. `journal.py --pass-durations` (new, a read) prints
# every run's actual wall-clock length so the owner can set this key from real numbers rather
# than from this file's placeholder.
LINKEDIN_PANE_STALE_MINUTES = "linkedin.pane_stale_minutes"
LINKEDIN_PANE_STALE_MINUTES_DEFAULT = 90

# public #83 — the run-start "linkless sighting" advisory (doctor.py's
# `check_linkless_sightings`). A sighting is caught freshly-sighted, not linkless, below this
# many days old — the grace period a batch research pass gets before a board/aggregator
# sighting with no jd_url/source_url is named. Home is `sourcing` (about HOW a role was found),
# the same section `route_preference` already lives in — never `ats` (that section is about the
# APPLICATION's clock, a different phase).
LINKLESS_GRACE_DAYS = "sourcing.linkless_grace_days"
LINKLESS_GRACE_DAYS_DEFAULT = 3

# design-inbound-resolution.md §5.2/§5.4 (ADR-029/030 build) — the deterministic ATS sweep's
# own three owner-facing knobs. Home is the EXISTING `ats` section (about the ATS's clock and
# receipts), same reasoning ATS_SILENCE_DAYS/ATS_CLOSE already state.
#
# `ats.parsed_status` — ADR-030 decision 1: the apply/propose line follows RESOLUTION
# CONFIDENCE, not mail kind. `receipt-grade` (default) applies a tier-1/tier-2 hit (the ATS's
# own key appeared in the mail) and proposes a tier-3 hit (a name match); `propose` proposes
# everything; `all` applies everything. See design §4.2's table.
ATS_PARSED_STATUS = "ats.parsed_status"
ATS_PARSED_STATUS_DEFAULT = "receipt-grade"
ATS_PARSED_STATUS_VALUES = ("receipt-grade", "propose", "all")

# `ats.sweep_days` — the FLOOR `reconcile.py --ats` passes to `mail_client.lookback_days()`
# (design §5's own "first caller"). The ledger widens it past this floor whenever a coverage
# hole exists; this is never a ceiling.
ATS_SWEEP_DAYS = "ats.sweep_days"
ATS_SWEEP_DAYS_DEFAULT = 3

# `ats.max_asks_per_run` — ADR-030 decision 5: a reader who clears this many asks a day keeps
# up with any ATS. Applied writes (a receipt-grade resolution) are never capped — only asks
# are, because an ask is a decision queued for a human and an applied write is evidence with
# a key already resolved.
ATS_MAX_ASKS_PER_RUN = "ats.max_asks_per_run"
ATS_MAX_ASKS_PER_RUN_DEFAULT = 5
# ── geo_screen (public #89, dev #355) ──────────────────────────────────────────────────────────
# The geography keys a screening reader resolves. `init_profile.py` used to scaffold
# `geography.relocation_open_to` / `geography.radius_minutes`; every profile actually derived
# from a resume carries the shape below instead — the `_ats_keys.py` two-spellings defect, one
# config section over. Registered here ONCE so `profile.py --options` and `geo_screen.py --list`
# read the identical key set (§15.7's own gate, applied to geography); `migrate.py`'s
# `m_0_50_0_geography_keys` rewrites a profile still carrying the old names into this shape.
GEOGRAPHY_REMOTE_OK = "geography.remote_ok"
GEOGRAPHY_REMOTE_OK_DEFAULT = True

# False, not True: the same caution `effective_setting()` already applies to an unrecognized
# commute location (never default to "relocation") — a profile that has never SET this is read
# as closed to relocation outside its named commute anchors and affirmative destinations, never
# open by silent default.
GEOGRAPHY_RELOCATION_OPEN = "geography.relocation.open"
GEOGRAPHY_RELOCATION_OPEN_DEFAULT = False

GEOGRAPHY_AFFIRMATIVE_DESTINATIONS = "geography.relocation.affirmative_destinations"
GEOGRAPHY_AFFIRMATIVE_DESTINATIONS_DEFAULT = ()

GEOGRAPHY_COMMUTE_ANCHORS = "geography.commute_anchors"
GEOGRAPHY_COMMUTE_ANCHORS_DEFAULT = ()

# What a reader resolves — and therefore exactly what a scaffold seeding fresh defaults would
# need to seed (the `_ats_keys.READER_KEYS` / `resume_variants.SUBMITTED` mirror precedent).
# `describe()` below reports the default when a profile has not set one, same as the register
# line at brief.py §3.2 prints "default — not in your file". ONE registry — `profile.py
# --options` and `doctor.py`'s CONFIG CURRENCY both iterate `READER_KEYS` (via `describe()`)
# rather than each naming its own list, so the two cannot enumerate two different sets
# (design §15.7's own gate: "profile.py --options and doctor.py reading different key lists").
READER_KEYS = frozenset({CHASE_AFTER_DAYS, NO_RESPONSE_AFTER_DAYS, ATS_SILENCE_DAYS, ATS_CLOSE,
                         LINKLESS_GRACE_DAYS, ATS_PARSED_STATUS, ATS_SWEEP_DAYS,
                         ATS_MAX_ASKS_PER_RUN, LINKEDIN_PANE_STALE_MINUTES, GEOGRAPHY_REMOTE_OK,
                         GEOGRAPHY_RELOCATION_OPEN, GEOGRAPHY_AFFIRMATIVE_DESTINATIONS,
                         GEOGRAPHY_COMMUTE_ANCHORS})

# {key: (default, kind, bounds_or_values, why)} — the metadata `profile.py --options` and
# `doctor.py` render alongside the value/provenance `describe()` returns. `kind` is "int" or
# "enum"; `bounds` is (lo, hi) for "int", a tuple of legal values for "enum".
_METADATA = {
    CHASE_AFTER_DAYS: (CHASE_AFTER_DAYS_DEFAULT, "int", (1, 60),
                       "days of silence before an outreach thread reads 'silent' "
                       "(your_move.conversation_axis / workflow_state)"),
    NO_RESPONSE_AFTER_DAYS: (NO_RESPONSE_AFTER_DAYS_DEFAULT, "int", (1, 90),
                             "verified silence below this many days is a 'chase' register "
                             "line, at or past it a 'reconnect' (brief.py)"),
    ATS_SILENCE_DAYS: (ATS_SILENCE_DAYS_DEFAULT, "int", (7, 180),
                       "days of ATS silence, measured to verified mailbox coverage — never "
                       "to today — before a close is PROPOSED (check_followups.py)"),
    ATS_CLOSE: (ATS_CLOSE_DEFAULT, "enum", ATS_CLOSE_VALUES,
               "whether the run only PROPOSES a close ('propose') or writes it itself "
               "('auto') — a window is a guess about the employer's clock; the owner's confirmation "
               "is what turns it into a fact"),
    LINKLESS_GRACE_DAYS: (LINKLESS_GRACE_DAYS_DEFAULT, "int", (0, 30),
                          "days a board/aggregator sighting with no jd_url/source_url is given "
                          "before doctor.py's run-start advisory names it (public #83)"),
    ATS_PARSED_STATUS: (ATS_PARSED_STATUS_DEFAULT, "enum", ATS_PARSED_STATUS_VALUES,
                       "whether a parsed ATS status is APPLIED or only PROPOSED, by resolution "
                       "confidence — receipt-grade (tier 1/2 apply, tier 3 proposes), propose "
                       "(everything proposed), or all (everything applied) — "
                       "reconcile.py --ats"),
    ATS_SWEEP_DAYS: (ATS_SWEEP_DAYS_DEFAULT, "int", (1, 30),
                     "the FLOOR reconcile.py --ats passes to mail_client.lookback_days() — "
                     "the ledger widens past this floor on a coverage hole, never narrows"),
    ATS_MAX_ASKS_PER_RUN: (ATS_MAX_ASKS_PER_RUN_DEFAULT, "int", (1, 50),
                          "asks reconcile.py --ats will write in one run before withholding "
                          "the remainder (counted, re-seen next run) — applied writes are "
                          "never capped, only asks are (ADR-030 decision 5)"),
    GEOGRAPHY_REMOTE_OK: (GEOGRAPHY_REMOTE_OK_DEFAULT, "bool", ("True", "False"),
                          "whether a fully-remote posting screens as REMOTE at all "
                          "(geo_screen.py) — False is an explicit config no, never silence"),
    GEOGRAPHY_RELOCATION_OPEN: (GEOGRAPHY_RELOCATION_OPEN_DEFAULT, "bool", ("True", "False"),
                                "whether a metro that is neither a commute anchor nor an "
                                "affirmative destination still screens RELOCATION-OK "
                                "(geo_screen.py) — False means OUT"),
    GEOGRAPHY_AFFIRMATIVE_DESTINATIONS: (GEOGRAPHY_AFFIRMATIVE_DESTINATIONS_DEFAULT, "list",
                                         ("free-form list of metro names",),
                                         "metros that screen AFFIRMATIVE regardless of "
                                         "relocation.open (geo_screen.py) — public #89's own "
                                         "list, the one the daily run dismissed a whole digest "
                                         "for never consulting"),
    GEOGRAPHY_COMMUTE_ANCHORS: (GEOGRAPHY_COMMUTE_ANCHORS_DEFAULT, "list",
                                ("free-form list of anchor objects",),
                                "each anchor's own max_commute_minutes is what geo_screen.py "
                                "and profile.py's within_commute() both screen a location "
                                "against"),
    LINKEDIN_PANE_STALE_MINUTES: (LINKEDIN_PANE_STALE_MINUTES_DEFAULT, "int", (20, 360),
                                  "minutes a taken pane lock is trusted before the next --take "
                                  "treats it as abandoned (runlock.py --resource pane) — "
                                  "UNVERIFIED: no pass duration exists in this repo; measure "
                                  "with journal.py --pass-durations before trusting the default"),
}

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
    if key not in _METADATA:
        raise KeyError("config_keys does not know %r — READER_KEYS: %s"
                       % (key, ", ".join(sorted(READER_KEYS))))
    default = _METADATA[key][0]
    v = _get_dotted(cfg, key)
    if v is None:
        return default, "default — not in your file"
    return v, "in your config.json"


def metadata(key):
    """(default, kind, bounds_or_values, why) for a registered `key` — what `--options`
    prints beside the value/provenance `describe()` returns. Raises `KeyError` the same way
    `describe()` does for an unknown key."""
    if key not in _METADATA:
        raise KeyError("config_keys does not know %r — READER_KEYS: %s"
                       % (key, ", ".join(sorted(READER_KEYS))))
    return _METADATA[key]
