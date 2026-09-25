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

# ── search postures (dev #323) ──────────────────────────────────────────────────────────────
# `doctor.py --fix`'s seed for a profile whose `config.json` predates `search.posture` /
# `search.postures`, or lost one by hand-edit. This is what `scripts/_config_skeleton.json`
# was meant to be — it never existed, and the read was wrapped in an `os.path.exists` guard,
# so `--fix` reported success having repaired nothing (issue #323, the project's own named
# failure shape: a missing thing read as an empty thing).
#
# Deliberately NOT in READER_KEYS/_METADATA: that registry describes the scalar ADJUSTABLE
# surface (`profile.py --options`, doctor's per-key value/provenance line) — `postures` is a
# nested tier TABLE, not one adjustable value, and folding it in would print `search.posture` /
# `search.postures` TWICE in CONFIG CURRENCY (once for the structural presence check
# `doctor.check_config_currency`'s own `need` list already runs, once more for provenance).
# `SEEDABLE_DEFAULTS` below is doctor.py's own separate, narrower registry: exactly the two
# dotted paths its additive-safe `--fix` seeds — a key doctor.py never attempts to seed
# (`compensation.tiers`, …) is simply absent from it, on purpose, not an oversight.
#
# ⚠️ Duplicated with `init_profile.py`'s `CONFIG_SKELETON["search"]` on purpose, for now.
# `init_profile.py`'s own config seeding is out of scope for this fix (tracked separately);
# it keeps its own literal until it adopts this constant instead of re-typing it — the stated
# follow-up. Two copies of the same four postures is exactly the `_ats_keys.py` two-spellings
# defect this module exists to prevent, so treat any change to one as a change owed to the
# other until that follow-up lands.
SEARCH_POSTURE = "search.posture"
SEARCH_POSTURE_DEFAULT = "economy"

SEARCH_POSTURES = "search.postures"
SEARCH_POSTURES_DEFAULT = {
    "minimal": {
        "runs_per_day": 1,
        "cron": "0 8 * * *",
        "max_agents_per_run": 0,
        "max_drafts_per_run": 0,
        "unattended": ["sweeps"],
        "_for": "The lowest tier, or a quiet week. Deterministic sweeps only: mailbox digests, "
                "calendar artifacts, silence detection, gates, dashboard. Zero model fan-out. "
                "Everything expensive is on demand.",
    },
    "economy": {
        "runs_per_day": 2,
        "cron": "0 8,15 * * *",
        "max_agents_per_run": 1,
        "max_drafts_per_run": 0,
        "unattended": ["sweeps", "linkedin"],
        "_for": "DEFAULT FOR NEW INSTALLS. Adds the LinkedIn sweep, which is where the outreach "
                "funnel lives, at one agent per run. A reply can wait ~8h.",
    },
    "standard": {
        "runs_per_day": 3,
        "cron": "0 8,12,16 * * *",
        "max_agents_per_run": 2,
        "max_drafts_per_run": 0,
        "unattended": ["sweeps", "linkedin", "research"],
        "_for": "Adds unattended research on genuinely NEW roles. Suits an active search on a "
                "mid tier.",
    },
    "full": {
        "runs_per_day": 5,
        "cron": "0 7,9,11,13,15 * * *",
        "max_agents_per_run": 5,
        "max_drafts_per_run": 5,
        "unattended": ["sweeps", "linkedin", "research", "drafting"],
        "_for": "Everything unattended, including auto-drafting replies. Assumes real token "
                "headroom; this is what the original installation runs.",
    },
}

SEEDABLE_DEFAULTS = {
    SEARCH_POSTURE: SEARCH_POSTURE_DEFAULT,
    SEARCH_POSTURES: SEARCH_POSTURES_DEFAULT,
}

# design-script-first.md §2/§12 (public #75/#76/#87/#110, decision 1/4) — LinkedIn passes are
# the largest scheduled spend (§2's own measurement: ~100k tokens per pass) and were coupled to
# a posture's `runs_per_day` with no ceiling of their own. This key decouples them: how many
# LinkedIn passes that REACH a surface a posture permits per day, independent of how many times
# the run itself fires.
#
# ⭐ Relative to a POSTURE dict (`search.postures.<name>`), never to the config.json ROOT — the
# one key in this module that is NOT a single global dotted path, because a value scoped to one
# posture cannot share a root-level key with every other posture's own value. `describe()` still
# applies unchanged: pass the posture's OWN sub-dict as `cfg` and this bare name as `key`
# (`_get_dotted` splits on "." and a name with none is just one `.get()` — the same mechanism,
# not a second one). Deliberately NOT in READER_KEYS — that registry's own callers
# (`profile.py --options`, `doctor.py`'s CONFIG CURRENCY) iterate it against the CONFIG ROOT
# (`describe(cfg, key)` with `cfg` the whole file), which would read `cfg["linkedin_runs_per_day"]`
# at the wrong location entirely; the same "deliberately NOT in READER_KEYS" reasoning
# `SEARCH_POSTURE`/`SEARCH_POSTURES` above already state for a differently-shaped reason
# (a nested TABLE, not one scalar) — this one is a scalar, but keyed per posture, so it is a
# third shape neither precedent covers, and it stays out of the shared registry rather than
# stretch it into meaning two different things depending on the caller.
LINKEDIN_RUNS_PER_DAY = "linkedin_runs_per_day"
LINKEDIN_RUNS_PER_DAY_DEFAULT = 1

# In `_METADATA` (so `describe()`/`metadata()` work against a posture sub-dict) but NOT in
# READER_KEYS (see the comment above) — the one entry in this table whose `cfg` argument, at
# every real call site, is a posture dict rather than the config.json root.
_METADATA[LINKEDIN_RUNS_PER_DAY] = (
    LINKEDIN_RUNS_PER_DAY_DEFAULT, "int", (0, 20),
    "LinkedIn passes that reach a surface this posture permits per day, independent of "
    "runs_per_day (posture.py --may linkedin) — 0 disables LinkedIn passes on this posture "
    "entirely")

# ── dispatch_packet.py's per-section byte caps (design-script-first.md §3.2, #77) ──────────────
# `voice` (the candidate's `configure/strategy.md` "Message style" text, verbatim) and `claims`
# (matched `presence/claims.md` addenda) are the two sections that ride on the profile's OWN
# prose and are unbounded as first drafted — every other section is bounded by construction
# (a fixed set of short fields). One key per section that has its own named default; every
# section not named here falls back to PACKET_SECTION_CAP_OTHER. Registered here, never
# hand-duplicated in dispatch_packet.py, the same "one definition" rule every other reader key
# in this module follows.
PACKET_SECTION_CAP_VOICE = "dispatch_packet.section_cap.voice"
PACKET_SECTION_CAP_VOICE_DEFAULT = 2000
PACKET_SECTION_CAP_CLAIMS = "dispatch_packet.section_cap.claims"
PACKET_SECTION_CAP_CLAIMS_DEFAULT = 3000
PACKET_SECTION_CAP_OTHER = "dispatch_packet.section_cap.other"
PACKET_SECTION_CAP_OTHER_DEFAULT = 1500

READER_KEYS = READER_KEYS | frozenset({PACKET_SECTION_CAP_VOICE, PACKET_SECTION_CAP_CLAIMS,
                                       PACKET_SECTION_CAP_OTHER})

_METADATA[PACKET_SECTION_CAP_VOICE] = (
    PACKET_SECTION_CAP_VOICE_DEFAULT, "int", (200, 20000),
    "byte cap on the packet's `voice` section (configure/strategy.md \"Message style\", "
    "verbatim) before dispatch_packet.py prints `PACKET TRUNCATED` (§3.2, #77)")
_METADATA[PACKET_SECTION_CAP_CLAIMS] = (
    PACKET_SECTION_CAP_CLAIMS_DEFAULT, "int", (200, 20000),
    "byte cap on the packet's `claims` section (matched presence/claims.md addenda) before "
    "dispatch_packet.py prints `PACKET TRUNCATED` (§3.2, #77)")
_METADATA[PACKET_SECTION_CAP_OTHER] = (
    PACKET_SECTION_CAP_OTHER_DEFAULT, "int", (200, 20000),
    "byte cap on every other dispatch_packet.py section before `PACKET TRUNCATED` (§3.2, #77)")


def packet_section_cap(cfg, section):
    """(cap, provenance) for one packet `section` name — `voice`/`claims` get their own
    registered key, everything else falls back to PACKET_SECTION_CAP_OTHER. Never a
    hand-duplicated if/elif in dispatch_packet.py; this is the one place the mapping is
    stated."""
    key = {"voice": PACKET_SECTION_CAP_VOICE,
          "claims": PACKET_SECTION_CAP_CLAIMS}.get(section, PACKET_SECTION_CAP_OTHER)
    return describe(cfg, key)


# ── generate_dashboard.py's body collapse over N words (design-script-first.md §4.3, dev #486 /
# public #107 part 2) ── a NON-SENDABLE free-text body (an ask, a role decision's memo) over this
# many words renders as its clause + word count + store locator, never the full text; a
# SENDABLE draft body is the one exception and is never collapsed regardless of length (public
# #46's own ruling). Root-level, in READER_KEYS — unlike LINKEDIN_RUNS_PER_DAY above this is not
# scoped to a posture, so profile.py --options / doctor.py's CONFIG CURRENCY read it the
# ordinary way (`describe(cfg, key)` against the config.json root).
DASHBOARD_BODY_COLLAPSE_WORDS = "dashboard.body_collapse_words"
DASHBOARD_BODY_COLLAPSE_WORDS_DEFAULT = 120

READER_KEYS = READER_KEYS | frozenset({DASHBOARD_BODY_COLLAPSE_WORDS})

_METADATA[DASHBOARD_BODY_COLLAPSE_WORDS] = (
    DASHBOARD_BODY_COLLAPSE_WORDS_DEFAULT, "int", (20, 2000),
    "word count above which a non-sendable dashboard body (an ask, a role decision's memo) "
    "collapses to its clause + word count + store locator instead of rendering in full "
    "(design-script-first.md §4.3, #486/#107) — a sendable draft body is never collapsed")


def seed_default(dotted_key):
    """The registered default `doctor.py --fix` seeds for `dotted_key` (e.g. "search.posture")
    when a profile's `config.json` is missing it entirely. Raises `KeyError` for anything
    `SEEDABLE_DEFAULTS` does not know — the same discipline `describe()`/`metadata()` already
    apply to `READER_KEYS`: never guess over an unregistered key, and never let "cannot fix
    this" quietly become "nothing to fix".

    Returns the registry's own object. A caller that writes this into a profile's config.json
    (as `doctor.py` does) must deep-copy it first — this module's module-level default must
    never be mutated in place, or one profile's write corrupts every later caller's default in
    the same process."""
    if dotted_key not in SEEDABLE_DEFAULTS:
        raise KeyError("config_keys has no seedable default for %r — SEEDABLE_DEFAULTS: %s"
                       % (dotted_key, ", ".join(sorted(SEEDABLE_DEFAULTS))))
    return SEEDABLE_DEFAULTS[dotted_key]


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
