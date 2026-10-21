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
silence): the `--overlap` shingle length, and the hex digits in a new `brief:` id.

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
# dev #539 / public #133 (design-one-dashboard-surface.md r3 §4): the follow-up view lists every
# subject owing a message within this many days. The reporter asked for "2-5 days"; 5 is the
# upper bound. DELIBERATELY not a registered key: a registered key must be seeded by a migration
# (the `m_*_states_config_keys` precedent), and this change ships with no migration. Promoting
# FIXED -> Key later is a registry line plus a seeding migration, and should wait for a report
# asking. `your_move.outreach_due` reads it; `profile.py --options` prints it under FIXED.
OUTREACH_HORIZON_DAYS = 5

# dev #729 / public #157 (jobsearch 0.70.0, design-location-screen.md §3.3): the two constants that
# turn a straight-line distance into a PROOF that a commute is impossible. OURS, deliberately
# generous, deliberately not keys (a user who could tune them would tune the proof into a guess):
#   - no road is shorter than the great circle, and no commute averages more than
#     MAX_COMMUTE_MPH door to door, so an anchor allowing `max_commute_minutes` can never reach
#     further than `minutes * MAX_COMMUTE_MPH / 60` miles;
#   - a city centroid sits within CENTROID_MARGIN_MILES of most of its own area.
# A place further than that sum from an anchor is provably outside it; one nearer but still beyond
# a real commute stays `near`, a review that prints its distance, and is never removed.
MAX_COMMUTE_MPH = 75
CENTROID_MARGIN_MILES = 15

FIXED = {
    "overlap_shingle_words": 8,     # brief.py --overlap's shared-run window, in words
    "brief_id_hex_digits": 16,      # the random suffix on a new `brief:<ts>-<hex>` id (dev #680; old rows carry 4)
    "outreach_horizon_days": OUTREACH_HORIZON_DAYS,  # the follow-up view's look-ahead, in days (dev #539)
    "max_commute_mph": MAX_COMMUTE_MPH,               # the fastest door-to-door commute the distance proof allows (dev #729)
    "centroid_margin_miles": CENTROID_MARGIN_MILES,   # how far from a city centroid its area is taken to reach (dev #729)
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

# ── mail connector selection (dev #161, dev #524) ──────────────────────────────────────────────
# Which mail connector jobsearch reads and drafts through. The owner's decision of 2026-10-02 was
# SIMPLICITY: the user selects ONE, and the plugin adheres to the selection — no per-account
# routing, no registry link, no migration. `gmail-multi` (the standalone connector plugin; the
# sweeps' IMAP library reads the same mailboxes) is the default so every profile that predates this
# key keeps today's behaviour with nothing to do; `claude-gmail` is the claude.ai-managed Gmail
# connector. `guard_mail_scope.py` DENIES the unselected connector's tools (a PreToolUse hook,
# enforced, not advised) and `mail_client.py`'s sweeps run only under `gmail-multi`.
#
# ⚠️ NOT `tooling.gmail_connector` — the profile already has that name, for an unrelated block
# (create/update/delete permissions); this key lives in `communications`, which is about mail.
# An unknown value is REFUSED (`resolve_mail_connector` raises), never coerced to the default:
# a typo that silently selected gmail-multi would read as a choice the user never made.
MAIL_CONNECTOR = "communications.mail_connector"
MAIL_CONNECTOR_DEFAULT = "gmail-multi"
MAIL_CONNECTOR_VALUES = ("gmail-multi", "claude-gmail")

READER_KEYS = READER_KEYS | frozenset({MAIL_CONNECTOR})

_METADATA[MAIL_CONNECTOR] = (
    MAIL_CONNECTOR_DEFAULT, "enum", MAIL_CONNECTOR_VALUES,
    "which mail connector jobsearch uses — gmail-multi (the standalone connector plugin, also "
    "what the sweeps read) or claude-gmail (the claude.ai Gmail connector); the other is "
    "denied at the tool layer (guard_mail_scope.py), and the deterministic sweeps run only "
    "under gmail-multi (dev #161)")


def resolve_mail_connector(cfg):
    """The selected mail connector for a loaded `config.json` dict: one of
    `MAIL_CONNECTOR_VALUES`. An absent key is `MAIL_CONNECTOR_DEFAULT` (every existing profile).
    ⛔ An unknown value — wrong spelling, wrong case, not a string — raises `ValueError` naming the
    valid values; it is never coerced to the default (dev #161)."""
    value, _provenance = describe(cfg, MAIL_CONNECTOR)
    if not isinstance(value, str) or value not in MAIL_CONNECTOR_VALUES:
        raise ValueError(
            "config.json %s is %r — not one of: %s. Set it to one of those exactly, or remove "
            "the key to get the default (%s)."
            % (MAIL_CONNECTOR, value, ", ".join(MAIL_CONNECTOR_VALUES), MAIL_CONNECTOR_DEFAULT))
    return value


# ── sourcing-screen (jobsearch 0.67.0; design-sourcing-screen.md §3.8, R1, R3) ───────────────
# dev #713/#714/#715/#716 (public #145/#144/#143/#142). Five SCALAR keys join the registry, and
# two NESTED tables are registered as named constants beside `SEARCH_POSTURES` (group finding 3:
# a nested table is deliberately kept out of READER_KEYS, which prints one adjustable value per
# key; folding a table in would print it twice in doctor.py's CONFIG CURRENCY).

# R1 (owner decision 2026-10-14) — the profile's currency is an ISO 4217 code the CANDIDATE sets
# once. NOT SEEDED, on purpose: "$" is ambiguous, so any seeded value would be a guess, and a guess
# is exactly what turns a foreign-currency listing into a wrongly REMOVED role. While it is
# absent every `listed_pay` range screens PAY-UNCOMPARABLE (profile.py), never BELOW-FLOOR; the
# migration files ONE ask (`set-compensation-currency`) so the absence is a visible question.
COMPENSATION_CURRENCY = "compensation.currency"
COMPENSATION_CURRENCY_DEFAULT = None

# §5.4 / B3 — how a HYBRID role inside the commute radius is priced when its anchor declares
# `bands`. "band" (default): by the commute, like an onsite role; "hybrid-tier": today's
# behaviour, the out-of-area hybrid floor. Consulted ONLY when bands are declared (B4).
COMPENSATION_HYBRID_INSIDE_RADIUS = "compensation.hybrid_inside_radius"
COMPENSATION_HYBRID_INSIDE_RADIUS_DEFAULT = "band"
COMPENSATION_HYBRID_INSIDE_RADIUS_VALUES = ("band", "hybrid-tier")

# §6.2/6.3 — days after which a role from a recruiter channel is flagged "ask the recruiter what
# stage the search is in". OURS: no published threshold exists (prior art: searched, found nothing);
# 35 sits inside the issue's 4-6 week window and at the early end of the 4-8 week shortlist figure
# the acceptance file records as supporting, not documented.
SEARCH_RETAINED_SEARCH_AGE_DAYS = "search.retained_search_age_days"
SEARCH_RETAINED_SEARCH_AGE_DAYS_DEFAULT = 35

# R3 — the triage gate always exits, is bounded, and is measured. Roles the daily run's triage step
# takes per run (oldest capture first), and the days after which a role still `triaging` surfaces to
# the candidate as "not yet read (waited K days)" with the lean `ask`.
SEARCH_TRIAGE_PER_RUN = "search.triage_per_run"
SEARCH_TRIAGE_PER_RUN_DEFAULT = 10
SEARCH_TRIAGE_STUCK_DAYS = "search.triage_stuck_days"
SEARCH_TRIAGE_STUCK_DAYS_DEFAULT = 3

READER_KEYS = READER_KEYS | frozenset({COMPENSATION_CURRENCY, COMPENSATION_HYBRID_INSIDE_RADIUS,
                                       SEARCH_RETAINED_SEARCH_AGE_DAYS, SEARCH_TRIAGE_PER_RUN,
                                       SEARCH_TRIAGE_STUCK_DAYS})

_METADATA[COMPENSATION_CURRENCY] = (
    COMPENSATION_CURRENCY_DEFAULT, "iso4217", ("an ISO 4217 three-letter code, e.g. USD",),
    "the currency every figure in this profile is in; a listed pay range is compared to your "
    "floors only when it is in this currency. Unset (the default) means no listed range can be "
    "compared, so each screens PAY-UNCOMPARABLE and none is ever removed (dev #715)")
_METADATA[COMPENSATION_HYBRID_INSIDE_RADIUS] = (
    COMPENSATION_HYBRID_INSIDE_RADIUS_DEFAULT, "enum", COMPENSATION_HYBRID_INSIDE_RADIUS_VALUES,
    "how a hybrid role inside a commute anchor that declares bands is priced: 'band' (by the "
    "commute, like an onsite role) or 'hybrid-tier' (the out-of-area hybrid floor, as before). "
    "Read only when an anchor declares bands (dev #714)")
_METADATA[SEARCH_RETAINED_SEARCH_AGE_DAYS] = (
    SEARCH_RETAINED_SEARCH_AGE_DAYS_DEFAULT, "int", (14, 120),
    "days after which a role from a recruiter channel is flagged: ask the recruiter what stage "
    "the search is in before research or letters (dev #716)")
_METADATA[SEARCH_TRIAGE_PER_RUN] = (
    SEARCH_TRIAGE_PER_RUN_DEFAULT, "int", (1, 50),
    "roles the daily run's triage step reads per run, oldest capture first; the rest wait and "
    "the step prints how many (dev #713)")
_METADATA[SEARCH_TRIAGE_STUCK_DAYS] = (
    SEARCH_TRIAGE_STUCK_DAYS_DEFAULT, "int", (1, 14),
    "days a role may stay 'triaging' before it surfaces to you as 'not yet read (waited K "
    "days)' with the lean 'ask' (dev #713)")

# What `migrate.m_0_67_0_sourcing_screen_config_keys` seeds where absent: (section, key, default)
# — one place, so the migration and the registry cannot name two different sets. The currency is
# NOT here (R1): it is a decision, filed as an ask, never a default.
SOURCING_SCREEN_SEEDED = (
    ("compensation", "hybrid_inside_radius", COMPENSATION_HYBRID_INSIDE_RADIUS_DEFAULT),
    ("search", "retained_search_age_days", SEARCH_RETAINED_SEARCH_AGE_DAYS_DEFAULT),
    ("search", "triage_per_run", SEARCH_TRIAGE_PER_RUN_DEFAULT),
    ("search", "triage_stuck_days", SEARCH_TRIAGE_STUCK_DAYS_DEFAULT),
)
SOURCING_SCREEN_UNSEEDED = (COMPENSATION_CURRENCY,)

# ── the location screen (dev #729 / public #157; jobsearch 0.70.0; design-location-screen.md R2) ──
# Owner decision of 2026-10-19 (OD-2, option a). A far onsite role -- one PROVEN beyond every commute
# anchor (`profile.commute_outcome`, state `outside`) -- is REMOVED (`remove:geo`, the geo verdict
# `outside-radius`) even when `geography.relocation.open` is true, unless it names an affirmative
# relocation destination or THIS key is true. `open` keeps its meaning for everything else; with
# `open` false a far role is `out`, as before. Every removal line names this key, so a user who
# wants the old behaviour has a one-key way back. A registered scalar is seeded by a migration so
# the owner's file shows it: `migrate.m_0_70_0_location_screen_config_keys`.
GEOGRAPHY_KEEP_OUTSIDE_RADIUS = "geography.relocation.keep_outside_radius"
GEOGRAPHY_KEEP_OUTSIDE_RADIUS_DEFAULT = False

READER_KEYS = READER_KEYS | frozenset({GEOGRAPHY_KEEP_OUTSIDE_RADIUS})

_METADATA[GEOGRAPHY_KEEP_OUTSIDE_RADIUS] = (
    GEOGRAPHY_KEEP_OUTSIDE_RADIUS_DEFAULT, "bool", ("True", "False"),
    "whether an onsite role PROVEN beyond every commute anchor (a straight-line distance no "
    "commute can cover) is kept when geography.relocation.open is true and it names no "
    "affirmative destination. False (the default) removes it as outside-radius; True keeps it "
    "for the relocation floor (dev #729)")

# What `migrate.m_0_70_0_location_screen_config_keys` seeds where absent: (path to the section, key,
# default) -- one place, so the migration and the registry cannot name two different sets.
LOCATION_SCREEN_SEEDED = (
    (("geography", "relocation"), "keep_outside_radius", GEOGRAPHY_KEEP_OUTSIDE_RADIUS_DEFAULT),
)

# Per-anchor nested keys (validated like `bands`, registered as named constants, NOT seeded -- their
# absence has a defined meaning: the anchor's coordinates come from the place table and its bound is
# derived from its minutes):
#   geography.commute_anchors[].radius_miles -- a number, 1 to 300: the anchor's own straight-line
#       radius. A place within it is `inside-radius`; a place beyond it is provably `outside`.
#   geography.commute_anchors[].lat / .lon -- numbers in range; they override the table lookup for
#       that anchor's coordinates (design-location-screen.md OD-1 option 4's half).
GEOGRAPHY_COMMUTE_RADIUS_MILES = "geography.commute_anchors[].radius_miles"
GEOGRAPHY_COMMUTE_LATLON = "geography.commute_anchors[].lat/.lon"
RADIUS_MILES_RANGE = (1, 300)


def validate_currency(value):
    """The normalised (upper-case) ISO 4217 code for `value`, or `ValueError`. Strict: three ASCII
    letters and nothing else — a symbol ("$"), a word ("dollars") or a lower-case typo is refused,
    never coerced to a guess. (Membership in the ISO list is NOT checked: no stdlib list exists and
    a hand-copied one drifts; the shape is what a comparison needs, since two codes are compared
    for equality only.)"""
    if (not isinstance(value, str) or len(value) != 3
            or not all("A" <= c <= "Z" or "a" <= c <= "z" for c in value)):
        raise ValueError("%s is %r -- not an ISO 4217 three-letter code (e.g. USD). A symbol such "
                         "as '$' is ambiguous, so it is never accepted." % (COMPENSATION_CURRENCY, value))
    return value.upper()


def resolve_currency(cfg):
    """The profile's currency code for a loaded `config.json` dict, or None while the key is
    absent (R1: unseeded). A present-but-malformed value raises `ValueError` -- never read as
    absent, never coerced (the `resolve_mail_connector` discipline)."""
    value, _provenance = describe(cfg, COMPENSATION_CURRENCY)
    if value is None:
        return None
    return validate_currency(value)


def resolve_int(cfg, key):
    """The integer value of a registered `kind == "int"` key: the configured value when it is a
    real int within the key's bounds, the registered default when the key is absent. A value
    present but not an int (a bool is not one), or outside the bounds, raises `ValueError` naming
    the key and the legal range -- a sourcing-screen reader treats that as a loud `review`, never
    as the default, because a typo that silently fell back would read as a choice the candidate
    never made."""
    value, _provenance = describe(cfg, key)
    default, kind, bounds, _why = metadata(key)
    if kind != "int":
        raise KeyError("%r is not an int key" % key)
    lo, hi = bounds
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise ValueError("config.json %s is %r -- not an integer in %d-%d. Set one, or remove the "
                         "key to get the default (%d)." % (key, value, lo, hi, default))
    return value


# Nested tables, registered as NAMED CONSTANTS (group finding 3), each with a validator that
# returns a list of plain-words problems ([] = valid). A reader that cannot trust a table treats
# it as LOUD (NEEDS-COMMUTE-CHECK / no signals reported), never as an empty table.
#
# `geography.commute_anchors[].bands` -- #714 B1: `[{max_minutes:int, floor:int}]`, ascending, the
# last `max_minutes <=` the anchor's own `max_commute_minutes`. Absent (or `[]`) = the anchor
# declares no bands = today's floors, line for line (B4).
# `geography.commute_anchors[].includes[]` -- each entry a string (today) or `{place, minutes}`
# (the minutes from the candidate's home to that place, used when a role names the place but
# carries no `location.commute_minutes` of its own, §5.4 step 2).
GEOGRAPHY_COMMUTE_BANDS = "geography.commute_anchors[].bands"
GEOGRAPHY_COMMUTE_INCLUDES = "geography.commute_anchors[].includes[]"

# `screen.likely_pass_signals` -- #713 T2: `[{id, phrase, fields:[title|jd|company], reason}]`.
# A match is a LEAN, shown on the Decide card with its reason, and NEVER removes a role.
SCREEN_LIKELY_PASS_SIGNALS = "screen.likely_pass_signals"
SCREEN_SIGNAL_FIELDS = ("title", "jd", "company")

# `screen.title_floor` -- dev #722 / public #156 (jobsearch 0.69.0, part b): ONE level token from the
# closed engine ladder below, or absent/null. A title the ladder reads as BELOW the floor is a LEAN
# (owner decision R1, 2026-10-16: a below-floor title NEVER removes, because a larger company gives
# a lower title for the same scope, so pay is the real test); the lean depends on the comp verdict
# (`profile.title_floor_lean`). ABSENT MEANS THE SCREEN IS BYTE-IDENTICAL TO 0.68.0: the key is NOT
# seeded by any migration, because absent has a defined meaning (like `likely_pass_signals`), and it
# is not in READER_KEYS, which prints one adjustable scalar with a default.
# The "mandate" (out-of-scope FUNCTION phrases) is NOT a key: it is `screen.likely_pass_signals`
# with `fields:["title"]` (R1: a pass lean, so a second key with the same shape would be the
# parallel mechanism contract rule 20 forbids).
SCREEN_TITLE_FLOOR = "screen.title_floor"

# The ladder: OURS, closed, generic English job-title words (no personal data), lowest rank first.
# `(level, (phrase, ...))`: a title's level is the HIGHEST rank any phrase matched, phrases matched
# whole-phrase and case-insensitively, LONGEST FIRST on non-overlapping spans (so "vice president"
# is consumed before "president" and "general manager" before "manager"). A title no phrase reads
# has NO level, and no level is never below the floor: no evidence is not evidence.
# It is a heuristic and says so: "Associate Director" reads director, "Account Manager" reads
# manager, "Staff Accountant" reads lead. That over-breadth is why a match only ever leans.
SENIORITY_LADDER = (
    ("intern", ("intern", "internship", "co-op")),
    ("entry", ("junior", "jr", "entry level", "entry-level", "graduate", "trainee", "apprentice")),
    ("associate", ("associate", "assistant", "coordinator")),
    ("senior", ("senior", "sr")),
    ("lead", ("lead", "principal", "staff")),
    ("manager", ("manager",)),
    ("director", ("director", "head of")),
    ("vp", ("vice president", "vp", "svp", "evp")),
    ("executive", ("chief", "president", "general manager", "ceo", "cto", "cfo", "coo", "cmo",
                   "cio")),
)
SENIORITY_LEVELS = tuple(level for level, _phrases in SENIORITY_LADDER)


def validate_title_floor(value):
    """Problems with `screen.title_floor` ([] when valid or absent/null): a string that is exactly
    one of `SENIORITY_LEVELS`. Strict -- "Senior", " senior", a list, a number and an unknown level
    are all refused with the levels named, never coerced to a guess."""
    if value is None:
        return []
    if not isinstance(value, str) or value not in SENIORITY_LEVELS:
        return ["%s is %r -- not one of %s" % (SCREEN_TITLE_FLOOR, value,
                                               ", ".join(SENIORITY_LEVELS))]
    return []


def _is_pos_int(v):
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


def validate_commute_bands(anchor):
    """Problems with one anchor's `bands` ([] when valid or undeclared)."""
    bands = anchor.get("bands") if isinstance(anchor, dict) else None
    if bands is None or bands == []:
        return []
    if not isinstance(bands, list):
        return ["bands must be a list of {max_minutes, floor}, got %s" % type(bands).__name__]
    problems, prev = [], 0
    for i, b in enumerate(bands):
        if not isinstance(b, dict) or set(b) != {"max_minutes", "floor"}:
            problems.append("bands[%d] must be exactly {max_minutes, floor}" % i)
            continue
        if not _is_pos_int(b["max_minutes"]) or not _is_pos_int(b["floor"]):
            problems.append("bands[%d]: max_minutes and floor must be positive integers" % i)
            continue
        if b["max_minutes"] <= prev:
            problems.append("bands[%d]: max_minutes %d is not above the previous band's %d "
                            "(bands run in ascending order)" % (i, b["max_minutes"], prev))
        prev = max(prev, b["max_minutes"])
    ceiling = anchor.get("max_commute_minutes")
    if not problems and _is_pos_int(ceiling) and prev > ceiling:
        problems.append("the last band reaches %d minutes, beyond the anchor's own "
                        "max_commute_minutes %d" % (prev, ceiling))
    return problems


def commute_bands(anchor):
    """`([(max_minutes, floor), ...], problems)` for one anchor: the bands in ascending order when
    valid; `([], [])` when it declares none; `([], problems)` when it declares some it cannot
    read (the caller must treat that as loud, not as 'no bands')."""
    problems = validate_commute_bands(anchor)
    if problems:
        return [], problems
    bands = anchor.get("bands") if isinstance(anchor, dict) else None
    return [(b["max_minutes"], b["floor"]) for b in (bands or [])], []


def validate_commute_includes(anchor):
    """Problems with one anchor's `includes[]` ([] when valid or undeclared): each entry a
    non-empty string, or `{place, minutes}` with a non-empty place and positive integer minutes."""
    inc = anchor.get("includes") if isinstance(anchor, dict) else None
    if inc is None:
        return []
    if not isinstance(inc, list):
        return ["includes must be a list, got %s" % type(inc).__name__]
    problems = []
    for i, e in enumerate(inc):
        if isinstance(e, str):
            if not e.strip():
                problems.append("includes[%d] is an empty string" % i)
        elif isinstance(e, dict):
            if (set(e) != {"place", "minutes"} or not isinstance(e["place"], str)
                    or not e["place"].strip() or not _is_pos_int(e["minutes"])):
                problems.append("includes[%d] must be a string or {place, minutes} with a "
                                "positive integer minutes" % i)
        else:
            problems.append("includes[%d] must be a string or {place, minutes}" % i)
    return problems


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v


def validate_anchor_geo(anchor):
    """Problems with one anchor's `radius_miles` / `lat` / `lon` ([] when valid or undeclared). An
    unreadable value is LOUD (the screen holds, `hold="config"`), never read as absent: a typo in a
    radius that silently fell back to the derived bound would be a choice the candidate never made."""
    if not isinstance(anchor, dict):
        return []
    problems = []
    if anchor.get("radius_miles") is not None:
        r, (lo, hi) = anchor["radius_miles"], RADIUS_MILES_RANGE
        if not _is_number(r) or not lo <= r <= hi:
            problems.append("radius_miles must be a number from %d to %d, got %r" % (lo, hi, r))
    lat, lon = anchor.get("lat"), anchor.get("lon")
    if (lat is None) != (lon is None):
        problems.append("lat and lon must be given together")
    elif lat is not None:
        if not _is_number(lat) or not -90 <= lat <= 90:
            problems.append("lat must be a number from -90 to 90, got %r" % (lat,))
        if not _is_number(lon) or not -180 <= lon <= 180:
            problems.append("lon must be a number from -180 to 180, got %r" % (lon,))
    return problems


def outer_bound_miles(anchor):
    """`(miles, how)` for one anchor: the straight-line distance beyond which a place is PROVABLY
    outside it, or `(None, why)` when the anchor contributes no bound (design §3.3).

    `radius_miles` when the anchor configures it; otherwise `max_minutes * MAX_COMMUTE_MPH / 60 +
    CENTROID_MARGIN_MILES`, where `max_minutes` is the anchor's `max_commute_minutes` or, when that
    is absent, its last band's `max_minutes`. A 45-minute anchor gives 71.25 miles. An anchor with
    neither a radius, minutes nor bands has NO bound; the caller must not call a place outside it."""
    if not isinstance(anchor, dict):
        return None, "not an anchor object"
    if anchor.get("radius_miles") is not None and not validate_anchor_geo(
            {"radius_miles": anchor["radius_miles"]}):
        return float(anchor["radius_miles"]), "radius_miles"
    minutes = anchor.get("max_commute_minutes")
    if not _is_number(minutes) or minutes <= 0:
        bands, problems = commute_bands(anchor)
        minutes = bands[-1][0] if bands and not problems else None
    if minutes is None:
        return None, "it declares no radius_miles, max_commute_minutes or bands"
    return minutes * MAX_COMMUTE_MPH / 60.0 + CENTROID_MARGIN_MILES, "max_commute_minutes"


def validate_likely_pass_signals(signals):
    """Problems with `screen.likely_pass_signals` ([] when valid, absent or empty): each signal
    `{id, phrase, fields, reason}` with a unique non-empty id, a non-empty phrase (a PHRASE, never a
    regular expression: OURS, design 7.2), at least one field of title/jd/company, and a reason --
    a signal without a reason is refused, since the reason is what the Decide card shows."""
    if signals is None or signals == []:
        return []
    if not isinstance(signals, list):
        return ["%s must be a list" % SCREEN_LIKELY_PASS_SIGNALS]
    problems, seen = [], set()
    for i, s in enumerate(signals):
        if not isinstance(s, dict) or set(s) != {"id", "phrase", "fields", "reason"}:
            problems.append("signal[%d] must be exactly {id, phrase, fields, reason}" % i)
            continue
        sid = s["id"]
        if not isinstance(sid, str) or not sid.strip():
            problems.append("signal[%d]: id must be a non-empty string" % i)
        elif sid in seen:
            problems.append("signal[%d]: duplicate id %r" % (i, sid))
        else:
            seen.add(sid)
        if not isinstance(s["phrase"], str) or not s["phrase"].strip():
            problems.append("signal[%d]: phrase must be a non-empty string" % i)
        f = s["fields"]
        if (not isinstance(f, list) or not f
                or any(x not in SCREEN_SIGNAL_FIELDS for x in f)):
            problems.append("signal[%d]: fields must be a non-empty list drawn from %s"
                            % (i, "/".join(SCREEN_SIGNAL_FIELDS)))
        if not isinstance(s["reason"], str) or not s["reason"].strip():
            problems.append("signal[%d]: a signal without a reason is refused (the reason is "
                            "what the Decide card shows)" % i)
    return problems


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
