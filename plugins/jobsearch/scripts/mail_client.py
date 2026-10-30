#!/usr/bin/env python3
"""
Gmail IMAP mail-reading library for jobsearch's deterministic sweeps — pure standard library.

⭐ THIS IS A LIBRARY, NOT A SERVER. It descends from the pre-extraction
`gmail_mcp_server.py`, whose MCP surface now lives in the standalone `gmail-multi`
connector plugin (marketplace ADR-004). jobsearch's manifest declares no `mcpServers`;
what its scheduled sweeps (`alert_sweep`, `watch`, `meeting_check`, `reconcile`) need is
exactly this import surface:

    Mailbox, configured_accounts, decode_header_value, body_text, CredentialError

and nothing else. The tool handlers and the JSON-RPC stdio loop the old vendored copy
carried were dead code here — 19 definitions shipped so five could be imported (public
issue #211) — and worse, they were a second MCP server for the drift gate to compare
when only a library is shared. This file is the shared surface and only that.

WHY A VENDORED LIBRARY AND NOT AN IMPORT OF THE CONNECTOR'S CODE (measured 2026-08-22)
--------------------------------------------------------------------------------------
Cross-plugin import mechanically works — the install cache is
`<config>/plugins/cache/<marketplace>/<plugin>/<version>/`, and a registry lookup
through `installed_plugins.json` resolves the sibling connector's scripts dir (probed
both layouts). But the sweeps run unattended on exactly the surfaces where the
connector's presence is BEST-EFFORT (`ensure_connectors.py` is loud-but-exit-0, and
S5/S6 have no self-install at all), the versioned layout makes the sibling path
resolvable only through the registry (scanning install state — ADR-002's rejected
convention, plus a version-picking ambiguity it didn't have then), and a sweep that
dies at import time on an unwatched scheduled surface is this repo's worst failure
shape: a missing thing reading as an empty thing. The library stays vendored; the
drift exposure is bounded because the send/tool layer — where the connector now
grows (send/reply/forward, marketplace #213) — is NOT part of this shared surface.
The contracts that must not drift (credential SERVICE name, config delegation) are
gated in `gmail-multi/scripts/test_connector.py`.

ACCOUNT RESOLUTION: THE PROFILE DECLARES A SUBSET, GMAIL-MULTI'S REGISTRY OWNS THE ACCOUNTS
-------------------------------------------------------------------------------------------
gmail-multi owns the ONE account registry (`~/.claude/gmail-multi/accounts.json`, schema 2,
override path `GMAIL_MULTI_CONFIG`; a published interface of that plugin, marketplace
ADR-004). This library is jobsearch's, and jobsearch's source of truth for WHICH of those
accounts a profile uses is the profile's `user.json` (Layer 1): a list of addresses that
REFERENCE the registry. The address is the reference. This module never WRITES the registry
(gmail-multi's `accounts.py` is the one writer) and never copies an address into it.

    registry_accounts()    strict schema-2 parser: `RegistryError` / `RegistryPending`
    declared_accounts()    (members, unregistered): the profile's addresses the registry
                           holds, and the ones it lacks
    configured_accounts()  the MEMBERS: what every sweep and brief searches (dev #469, F3)

An address the registry lacks is LOUD (one line per address, per process), never a silent
no-op and never searched: a missing thing must not read as an empty thing. Such an address
also gets no `swept` row, so the coverage ledger reads it as not covered by construction.

⭐ ONE SEAM, TWO BACKENDS (dev #161, dev #524, dev #799)
-------------------------------------------------------
`config.json` `communications.mail_connector` (config_keys.py) names where this profile's mail is
read. `Mailbox(account)` is a FACTORY over that selection:

    gmail-multi (the default)   `ImapMailbox` — Gmail IMAP, as it always was
    any claude.ai connector     `BundleMailbox` — the bundle the model fetched through the
                                connector and `mail_ingest.py ingest` validated (design
                                docs/design-mail-any-connector.md)

Both answer the same questions (`search`, `fetch_headers`, `fetch_full`, `coverage`), so the six
consumers keep their own matching. `sweep_accounts()` — the one site every deterministic sweep goes
through — writes the coverage ledger from `Mailbox.coverage()`: the IMAP window is `[now - since_days,
now]`, a bundle's is the window it actually fetched, and an uncovered span writes NO row (a row would
be a false coverage claim). A selection with NO backend still skips with ONE loud line (`skip_line`).
A sweep never skips silently and every sweep that runs prints which connector it used. An unknown
selection raises `ValueError` — refused, never coerced.

CREDENTIALS
-----------
App passwords live in the OS credential store (Keychain / PasswordVault /
secret-service via scripts/credentials.py) and are read at call time — never stored
on disk, never passed as command-line arguments, never logged. The service name
(`claudesearch-imap`) is the compatibility constant shared with the connector.

Python 3.9+. No third-party packages, by design — see CLAUDE.md.
"""

import collections
import email
import inspect
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(_os.path.realpath(__file__))))
from _root import profile_root as _profile_root
import email.header
import imaplib
import json
import os
import re
import socket
import sys
import datetime as _dt

import credentials as _cred
import journal as _journal

# Kept as an alias: the service name is shared with mailboxes.py and doctor.py.
KEYCHAIN_SERVICE = _cred.SERVICE
IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
# ⭐ dev #712 / public #146 -- NO MAILBOX CALL CAN HANG. Every IMAP socket this module opens carries
# this bound, and it covers the connect, the TLS handshake AND every later read: `imaplib` hands the
# value to `socket.create_connection`, which leaves it on the socket, so a server that accepts and
# then stalls makes the next read raise instead of waiting forever. It is read at CALL time (not
# bound as a default argument) so a test can shorten it. Without it a daily run's held probe sat on
# one silent socket until the harness killed the whole call and every result already gathered went
# with it. 30 s is far above a healthy Gmail round trip and well below the shortest kill the report
# observed (50 s).
IMAP_TIMEOUT_S = 30.0
ALL_MAIL = '"[Gmail]/All Mail"'


# Accounts this library searches. Emails only — never secrets.
#
# ⭐ THE PROFILE DECLARES A SUBSET BY REFERENCE; GMAIL-MULTI'S REGISTRY OWNS THE ACCOUNTS (dev #469).
# `user.json` (LAYER 1) lists the addresses this profile uses, read at call time. The registry
# (`registry_accounts()` below) is the machine-wide list of accounts gmail-multi can reach. What a
# profile may search is the INTERSECTION — `declared_accounts()` returns it as `members`, and
# `configured_accounts()` is `members`.
#
# Resolution order for the declared list: GMAIL_MCP_ACCOUNTS env override -> user.json -> the
# literal fallback below. The env override is gmail-multi's own override too (it replaces the
# registry there as well), so an address named by it is a member without a registry lookup. The
# fallback exists only so this module still imports if user.json is missing or malformed; it is
# NOT the configuration.
# ⭐ EMPTY BY DESIGN (2026-08-05, pre-split sanitization). This used to hard-code the
# original owner's two addresses. In a SHARED engine that is not merely a privacy leak,
# it is incoherent: silently falling back to someone else's mailbox is never the
# behaviour anyone wants. An empty list makes a missing/malformed user.json fail LOUDLY
# at the point of use, which is the correct failure.
FALLBACK_ACCOUNTS = []


def _accounts_from_user_json(root=None):
    """Read mailboxes from user.json. Returns [] on any problem — never raises, because
    this module is imported by the MCP stdio loop and by alert_sweep/meeting_check.

    ⛔ THIS IS THE RAW DECLARED LIST — it knows nothing about gmail-multi's registry. It exists
    for `declared_accounts()` and for one packaging check; every other caller goes through
    `configured_accounts()` or `declared_accounts()` (dev #469, F3 — test_mail_boundary.py
    fails on a new raw caller)."""
    try:
        # ⭐ PROFILE root, not engine (2026-08-05). user.json belongs to the USER; under a plugin
        # install the engine directory has none, so this silently returned [] and the server
        # reported no mailboxes — indistinguishable from "you have no accounts configured".
        path = os.path.join(root or _profile_root(),
                            "user.json")
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return [m["address"] for m in data.get("mailboxes", []) if m.get("address")]
    except (OSError, ValueError, KeyError, TypeError):
        # ⚠️ NARROW, deliberately. A bare `except` here swallowed a NameError on 2026-08-05 and
        # reported "no mailboxes configured" — indistinguishable from a user who has none. A
        # programming error must not disguise itself as a configuration state.
        return []


# --------------------------------------------------------------------------
# ⭐ GMAIL-MULTI'S REGISTRY, READ-ONLY (dev #469) — a published interface of that plugin
# --------------------------------------------------------------------------

REGISTRY_SCHEMA = 2


class RegistryError(RuntimeError):
    """gmail-multi's registry cannot be used: the file is absent, unreadable, not a JSON object,
    or not schema 2 with a list of address strings. The message names the path and the fix."""


class RegistryPending(RuntimeError):
    """The registry is still schema 1 (no `schema` key, or `schema: 1`): gmail-multi has not
    migrated it yet. A distinct type — NOT a RegistryError — because it is a bounded window
    (the plugins update in either order), not a broken file; callers choose their own bounded
    behaviour for it and are always loud. `declared_accounts()` attaches the profile's declared
    list as `.declared`, which is what the bounded old rule scopes to."""

    declared = ()


def registry_path():
    """Where gmail-multi's registry lives: `GMAIL_MULTI_CONFIG` if set, else
    `~/.claude/gmail-multi/accounts.json`. Resolved per call (HOME can change in a test)."""
    env = os.environ.get("GMAIL_MULTI_CONFIG", "").strip()
    return env or os.path.join(os.path.expanduser("~"), ".claude", "gmail-multi", "accounts.json")


def registry_accounts(path=None):
    """The addresses in gmail-multi's registry — a STRICT parser of schema 2 (marketplace ADR-004,
    `plugins/gmail-multi/.claude-plugin/plugin.json` `metadata.provides`). READ-ONLY: this module
    never writes the registry.

    Raises `RegistryError` when the file is absent, unreadable, not a JSON object, carries a
    schema other than 1 or 2, or holds an `accounts` that is not a list of non-empty strings.
    Raises `RegistryPending` on schema 1 (no `schema` key, or `schema: 1`). Never returns a
    guess: an unreadable registry must not read as an empty one."""
    path = path or registry_path()
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        raise RegistryError("gmail-multi's registry was not found at %s. gmail-multi creates it "
                            "when you add an account: run /gmail-multi:accounts." % path)
    except (OSError, ValueError) as exc:
        raise RegistryError("gmail-multi's registry at %s cannot be read (%s: %s). Fix or remove "
                            "it, then run /gmail-multi:accounts." % (path, type(exc).__name__, exc))
    if not isinstance(data, dict):
        raise RegistryError("gmail-multi's registry at %s is not a JSON object (it is %s). Fix it, "
                            "then run /gmail-multi:accounts." % (path, type(data).__name__))
    schema = data.get("schema", 1)
    if schema == 1 and not isinstance(schema, bool):
        raise RegistryPending("gmail-multi's registry at %s is still schema 1 — gmail-multi has "
                              "not migrated it yet (it does at its next session start)." % path)
    if schema != REGISTRY_SCHEMA or isinstance(schema, bool):
        raise RegistryError("gmail-multi's registry at %s declares schema %r; this jobsearch "
                            "reads schema %d. Update the older of the two plugins."
                            % (path, schema, REGISTRY_SCHEMA))
    accounts = data.get("accounts")
    if (not isinstance(accounts, list)
            or not all(isinstance(a, str) and a.strip() for a in accounts)):
        raise RegistryError("gmail-multi's registry at %s has an `accounts` that is not a list of "
                            "addresses. Fix it, then run /gmail-multi:accounts." % path)
    return [a.strip() for a in accounts]


def _declared_raw(root=None):
    """(addresses, from_env) — the profile's declared list before any registry lookup."""
    raw = os.environ.get("GMAIL_MCP_ACCOUNTS", "").strip()
    if raw:
        return [a.strip() for a in raw.split(",") if a.strip()], True
    return _accounts_from_user_json(root) or list(FALLBACK_ACCOUNTS), False


def declared_accounts(root=None, registry=None):
    """`(members, unregistered)`: the profile's declared addresses that gmail-multi's registry
    holds, and the ones it lacks (case-insensitive match; order and spelling are the profile's).

    Under `claude-gmail` the registry is not consulted — that connector binds its own account —
    so the result is `(declared, [])`. So it is when `GMAIL_MCP_ACCOUNTS` names the list, because
    gmail-multi's own server lets that variable replace the registry too.

    Raises `RegistryError` / `RegistryPending` (see `registry_accounts`) when the registry cannot
    answer: the caller decides what that means for it, and none may treat it as "no accounts"."""
    declared, from_env = _declared_raw(root)
    if from_env:
        return declared, []
    try:
        connector = selected_connector(root)
    except ValueError:
        # An unreadable selection narrows, never widens: the registry is consulted. The sweep,
        # the Mailbox opener and the scope guard each refuse an unreadable selection on their own.
        connector = GMAIL_MULTI
    if connector != GMAIL_MULTI:
        return declared, []
    try:
        held = {a.lower() for a in registry_accounts(registry)}
    except RegistryPending as exc:
        exc.declared = list(declared)            # the old rule's list, for the bounded window
        raise
    members = [a for a in declared if a.lower() in held]
    unregistered = [a for a in declared if a.lower() not in held]
    return members, unregistered


# One loud line per distinct finding per process: a sweep calls configured_accounts() more than
# once, and a line repeated five times trains its reader to skim.
_ANNOUNCED = set()


def _loud(key, line):
    if key in _ANNOUNCED:
        return
    _ANNOUNCED.add(key)
    print(line, file=sys.stderr)


def unregistered_line(address):
    return ("!! MAILBOX NOT IN GMAIL-MULTI'S REGISTRY — %s is listed in your profile but not in "
            "gmail-multi's registry, so it was NOT searched. Add it with /gmail-multi:accounts "
            "(or remove it with /jobsearch:mailboxes)." % address)


def configured_accounts():
    """⭐ THE MEMBERS: the profile's declared addresses that gmail-multi's registry holds — what
    every sweep, `brief` and `check_followups` searches (dev #469, F3: redefined here so no caller
    needs to change, and `test_mail_boundary.py` fails on a new raw caller of the declared list).

    One loud line per unregistered address (per process), on stderr. An address the registry lacks
    is never searched. Registry states that cannot answer are loud too, never an empty list that
    reads as "no mail": registry ABSENT or malformed -> `[]` and one line naming the fix; registry
    still schema 1 (`RegistryPending`, the bounded mixed-version window) -> the declared list
    unchanged (the old rule) and one line saying so.

    ⭐ RE-READ EVERY CALL — never cache at import.

    This module is imported once and then serves an MCP stdio loop for the life of the process.
    Caching the account list at import meant a single bad resolution at startup produced a
    mailbox-blind server for hours: every search returned an empty result, which is exactly what
    a genuinely empty mailbox returns. On 2026-08-05 it reported "no new mail" for a whole run
    while the per-call sweeps reached both accounts fine.

    Reading per call also means a profile fixed mid-session takes effect immediately, and an
    agency switching candidates via CLAUDESEARCH_ROOT does not need a restart. The cost is one
    small JSON read per tool call.
    """
    try:
        members, unregistered = declared_accounts()
    except RegistryPending as exc:
        _loud(("pending",), "!! gmail-multi registry not migrated yet — scoping to the profile "
              "list until it is. (%s)" % exc)
        return list(getattr(exc, "declared", []))
    except RegistryError as exc:
        _loud(("registry", str(exc)),
              "!! %s No mailbox was searched — nothing was recorded as covered." % exc)
        return []
    for address in unregistered:
        _loud(("unregistered", address.lower()), unregistered_line(address))
    return members


# --------------------------------------------------------------------------


# ⭐ THE SELECTED MAIL CONNECTOR (dev #161, dev #524)
# --------------------------------------------------------------------------

GMAIL_MULTI = "gmail-multi"


def selected_connector(root=None):
    """The mail connector this profile selected: `gmail-multi` or `claude-gmail` — read from
    `<profile root>/config.json` EVERY CALL (never cached, for the reason `configured_accounts()`
    states). An absent file or key is the default, `gmail-multi`: every profile that predates the
    key keeps today's behaviour. ⛔ A config.json that exists but cannot be read, or whose value
    is not one of the two connectors, raises `ValueError` — refused loudly, never coerced to the
    default, because a selection this module cannot read is not a selection of gmail-multi."""
    import config_keys                       # lazy: config_keys -> check_followups -> this module
    root = root or _profile_root()
    path = os.path.join(root, "config.json")
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except FileNotFoundError:
        cfg = {}
    except (OSError, ValueError) as exc:
        raise ValueError("config.json at %s could not be read (%s: %s), so the mail connector "
                         "selection (%s) cannot be determined — fix the file."
                         % (path, type(exc).__name__, exc, config_keys.MAIL_CONNECTOR))
    if not isinstance(cfg, dict):
        raise ValueError("config.json at %s is not a JSON object, so the mail connector "
                         "selection (%s) cannot be determined." % (path, config_keys.MAIL_CONNECTOR))
    return config_keys.resolve_mail_connector(cfg)


def connector_line(connector):
    """The ONE line a sweep prints so its report states which connector it used (dev #161)."""
    return "Mail connector: %s (selected in config.json communications.mail_connector)" % connector


def skip_line(connector):
    """The ONE loud line a sweep prints, instead of running, when `connector` is not gmail-multi."""
    return ("!! MAIL SWEEP SKIPPED — your mail connector is '%s', and this sweep reads mail only "
            "through gmail-multi. No mailbox was opened and nothing was recorded as covered. "
            "To run it, set communications.mail_connector to \"gmail-multi\" in config.json "
            "(/jobsearch:mailboxes shows the selection)." % connector)


# --------------------------------------------------------------------------
# ⭐⭐ THE COVERAGE LEDGER (dev #321, V0) — every multi-account sweep goes through here now
# --------------------------------------------------------------------------
#
# Before this, `alert_sweep.py`, `watch.py`, `meeting_check.py` and `reconcile.py --harvest`
# each carried its OWN copy of "loop over configured_accounts(), print `!! INCOMPLETE COVERAGE`
# on a failure" — four sites, and none of them wrote the fact down. `data/messages.jsonl` is
# only as current as the last sweep, and nothing recorded when that was, so every "nobody
# replied" rested on a mirror that could mean either "nothing arrived" or "nothing looked" —
# and `check_followups.py` measured silence against `datetime.now()` regardless. Filed as
# dev #321; the states-and-views design's §15.1 amendment is what forced the question of what
# the fact actually needs to be (an INTERVAL, not a timestamp — see journal.py's module
# docstring).
#
# `sweep_accounts()` below is that one shared site: it does what each caller's loop already did
# (iterate accounts, call a per-account search, collect an incomplete list) PLUS writes exactly
# one `swept` row per account, every call, whether or not anything was found. Adopting it in
# `alert_sweep.py`/`watch.py`/`meeting_check.py`/`reconcile.py` — replacing each script's own
# loop with a call through here — is out of this file's scope for V0 (none of those four files
# were touched); this function is the complete, independently-tested mechanism they can each
# adopt with a small, mechanical change (their own `sweep_account(account, query) -> (rows,
# error)` callbacks already match the `search_one` contract this expects).

# ⭐ dev #321 §15.1 — a FLOOR on how far a sweep reaches back to close a coverage hole, capped so
# a long-dead ledger (or the first run ever) does not demand an unbounded backfill. Decided as an
# ENGINE CONSTANT, not a config key, for the same reason the design settled on: an operator who
# wants deeper backfill runs one sweep with a wider `--days`/`--since` flag and the ledger
# records it from then on — there is no recurring decision here for a config key to hold, only a
# one-time ceiling. It is NOT yet surfaced through any `--options` discovery path (that
# infrastructure is V1's `config_keys.py` / `profile.py --options`, states-and-views design §15.7
# — it does not exist in this engine today); until it does, this module constant IS where the
# default is spelled, and any caller that uses `lookback_days()` below is expected to print the
# value it got back (as `lookback_days()`'s docstring says) so the number is visible in the run's
# own output rather than only in source.
COVERAGE_BACKFILL_MAX_DAYS = 30

# ⭐ dev #799 (design 3.1) — under a connector the backfill is 3 days, not 30: OURS, 30 days of
# model-transcribed headers is the wrong price. A longer hole stays visible as NOT COVERED.
CONNECTOR_BACKFILL_MAX_DAYS = 3


def backfill_max_days(root=None):
    """⭐ THE ONE ACCESSOR for the backfill ceiling (dev #799, design section 14 R2-M0): 30 under
    gmail-multi, `CONNECTOR_BACKFILL_MAX_DAYS` under any connector. Every consumer reads the ceiling
    HERE — `COVERAGE_BACKFILL_MAX_DAYS` is not named outside this module (a static test pins it).
    An unreadable selection answers 30: every sweep refuses an unreadable selection on its own."""
    try:
        connector = selected_connector(root)
    except ValueError:
        return COVERAGE_BACKFILL_MAX_DAYS
    return COVERAGE_BACKFILL_MAX_DAYS if connector == GMAIL_MULTI else CONNECTOR_BACKFILL_MAX_DAYS


def lookback_days(root, mailbox, floor_days, by=None):
    """dev #321 §15.1 — the LEDGER-DERIVED lookback for one mailbox's next sweep: reach back far
    enough to close any coverage hole, never less than the caller's own requested window.

    `since_days = max(floor_days, min(days since covered_through(mailbox), COVERAGE_BACKFILL_MAX_DAYS))`

    A two-day scheduler outage means the next sweep reaches back (at least) two days and the
    interval closes by construction; the very first sweep of an empty ledger reaches back the
    full `COVERAGE_BACKFILL_MAX_DAYS`, so history up to that depth becomes verifiable on day
    one. `floor_days` is a FLOOR, never a ceiling — a caller whose own window is wider than the
    computed backfill (a deliberate `--days 14` run) is never narrowed by this function.

    Callers SHOULD print the returned value (or `floor_days` when they are equal) so the window
    a sweep actually used is visible in its own output — `COVERAGE_BACKFILL_MAX_DAYS` has no
    other discovery surface yet (see the module-level note above).

    ⭐ design-inbound-resolution.md §5 amendment D3 (surface pass 2026-09-14) — `by`, optional,
    is passed straight to `journal.covered_through()`: `by=None` (every existing caller) keeps
    the old cross-sweep-kind merge; a caller naming its OWN `by` (`reconcile.py --ats` passes
    `by="reconcile-ats"`) sees only ITS OWN sweep history for this mailbox, so a mailbox the
    daily `alert_sweep` covers every day does not mask `reconcile-ats`'s own first-ever run.
    """
    recs = _journal.read(root)
    ceiling = backfill_max_days(root)
    through = _journal.covered_through(recs, mailbox, by=by)
    if through is None:
        return max(int(floor_days or 0), ceiling)
    try:
        through_dt = _dt.datetime.fromisoformat(through)
    except ValueError:
        return max(int(floor_days or 0), ceiling)
    hole_days = (_dt.datetime.now() - through_dt).days
    capped = min(max(hole_days, 0), ceiling)
    return max(int(floor_days or 0), capped)


# Error text -> a REASON CODE from journal.REASONS. Deliberately a small, named heuristic rather
# than free text: `search_one` callbacks today return a plain error STRING (CredentialError's
# message, or `"%s: %s" % (type(exc).__name__, exc)` — see alert_sweep.py's `sweep_account`), so
# this is what turns that string into something `record_swept`'s REASONS set will accept. A
# caller that already knows its own reason code can bypass this by calling
# `journal.record_swept()` directly with an explicit `reason=`.
def _classify_failure(error_text):
    low = (error_text or "").lower()
    if "credentialerror" in low or "credential" in low or "app password" in low:
        return "credential-missing"
    if "timed out" in low or "timeout" in low:
        return "timeout"
    if "rate" in low and "limit" in low:
        return "rate-limited"
    if "could not select" in low or "imap" in low:
        return "upstream-error"
    return "other"


def _clock():
    """The current time as an aware UTC datetime. ONE patch point for every bundle-side clock read
    (the sweep, `BundleMailbox`, `mail_ingest`): a test freezes it here."""
    return _dt.datetime.now(_dt.timezone.utc)


Coverage = collections.namedtuple("Coverage", ["ok_from", "through"])
Coverage.__doc__ = ("⭐ dev #799 (design 3.5) — what a mailbox VERIFIABLY covered, as naive LOCAL datetimes "
                    "(the journal's own form): `ok_from`..`through`, or `(None, None)` when nothing is "
                    "verifiable (no exhausted bundle).")


def _has_backend(connector):
    """True when `connector` has a bundle backend: a row in the connector table."""
    import mail_ingest
    try:
        mail_ingest.row_for(connector)
    except ConnectorNotSelected:
        return False
    return True


def _call_search_one(search_one, account, with_window):
    """`search_one(account) -> (rows, error)`, or with `with_window=True` — honoured only by a callback
    that DECLARES the keyword — `(rows, error, Coverage)` (design 3.5). Every existing two-argument
    callback and test double keeps working: its coverage is then read from the mailbox."""
    if with_window:
        try:
            takes = "with_window" in inspect.signature(search_one).parameters
        except (TypeError, ValueError):
            takes = False
        if takes:
            rows, error, cov = search_one(account, with_window=True)
            return rows, error, cov
    rows, error = search_one(account)
    return rows, error, None


def sweep_accounts(search_one, since_days, root=None, by="", accounts=None, now=None):
    """dev #321 (V0) — THE shared multi-account sweep site. `search_one(account) -> (rows,
    error)` performs ONE account's actual search (Gmail query construction is the caller's —
    different sweeps search different things); this function does the part every caller
    duplicated: iterate every configured account (or `accounts`, for a narrowed run), call
    `search_one`, and — the fix — write the `swept` row(s) via `journal.record_swept()`.

    ⭐ gmail-multi: exactly ONE row per account — `ok: true` with the window `[now - since_days,
    now]` when `search_one` succeeds, `ok: false` with a classified reason when it reports an error.
    A `search_one` failure is never a crash here — that IS the `ok:false` row, not an exception.

    ⭐ any connector (dev #799, design section 14 R2-M0): `ok: true` is written ONLY for the span a
    fetched, EXHAUSTED bundle covers, intersected with this consumer's own window, with additive
    `source: "connector-bundle"`. An uncovered span — no bundle, a bundle that is not exhausted, a
    bundle that stopped short of the requested window — writes NO row: a row would claim coverage
    nobody had. What is not covered is PRINTED by the consumer (`print_coverage`), from the ledger.

    Returns `(results, incomplete)`: `results` is `[(account, rows, error), ...]` in call order
    (exactly what a caller's own loop already produces, so this is a drop-in for that loop's
    body); `incomplete` is the list of accounts whose sweep failed — a caller's existing
    `!! INCOMPLETE COVERAGE` banner logic needs no other change.
    """
    root = root or _profile_root()
    # ⭐ dev #161 — ADHERE to the selected connector. A selection with NO backend does not run: one
    # loud line, no search_one call, and NO `swept` row. Every sweep that runs states its connector.
    connector = selected_connector(root)
    if connector != GMAIL_MULTI and not _has_backend(connector):
        print(skip_line(connector))
        return [], []
    print(connector_line(connector))
    now = (now or _dt.datetime.now()).replace(microsecond=0)
    frm = (now - _dt.timedelta(days=since_days)).isoformat()
    through = now.isoformat()
    accounts = accounts if accounts is not None else configured_accounts()
    results, incomplete = [], []
    for account in accounts:
        rows, error, cov = _call_search_one(search_one, account, connector != GMAIL_MULTI)
        if connector == GMAIL_MULTI:
            if error:
                incomplete.append(account)
                _journal.record_swept(root, account, None, None, by, False,
                                      reason=_classify_failure(error), at=through)
            else:
                _journal.record_swept(root, account, frm, through, by, True, at=through)
        else:
            if not error and cov is None:
                try:
                    with BundleMailbox(account, connector, root) as mb:
                        cov = mb.coverage(now - _dt.timedelta(days=since_days))
                except (BundleError, ConnectorNotSelected) as exc:
                    error = str(exc)
            if error:
                incomplete.append(account)
            elif cov is not None and cov.ok_from is not None:
                _journal.record_swept(root, account, cov.ok_from.isoformat(),
                                      cov.through.isoformat(), by, True, at=through,
                                      source=BUNDLE_SOURCE)
        results.append((account, rows, error))
    return results, incomplete


# --------------------------------------------------------------------------
# ⭐ dev #799 (design 4.3, section 14 R2-M0) — every consumer STATES its coverage
# --------------------------------------------------------------------------

BUNDLE_SOURCE = "connector-bundle"

# What a consumer's own queries found in this process, per account — the numbers its coverage line
# prints. A side channel (reset per process), the same shape `alert_sweep._last_skipped` already uses.
_RUN_STATS = {}


def reset_run_stats():
    _RUN_STATS.clear()


def _stat(account, name, key):
    _RUN_STATS.setdefault(account.lower(), {"matched": set(), "unknown": set()})[name].add(key)


def uncovered_spans(recs, mailbox, frm, to):
    """The parts of `[frm, to]` (naive local datetimes) that NO `ok: true` `swept` row of `mailbox`
    covers — `[now - since_days, now]` minus the union of the ledger's intervals. Never computed
    from one bundle's window alone: a window that began later than the requested one is not a hole
    when the ledger already covers what came before it."""
    intervals = []
    for r in recs:
        if r.get("event") != "swept" or r.get("mailbox") != mailbox or not r.get("ok"):
            continue
        try:
            f = _dt.datetime.fromisoformat(r.get("from"))
            t = _dt.datetime.fromisoformat(r.get("through"))
        except (TypeError, ValueError):
            continue
        if f.tzinfo is not None or t.tzinfo is not None:
            continue
        intervals.append((f, t))
    merged = []
    for f, t in sorted(intervals):
        if merged and f <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], t))
        else:
            merged.append((f, t))
    spans, cursor = [], frm
    for f, t in merged:
        if t <= cursor:
            continue
        if f >= to:
            break
        if f > cursor:
            spans.append((cursor, min(f, to)))
        cursor = max(cursor, t)
        if cursor >= to:
            break
    if cursor < to:
        spans.append((cursor, to))
    return spans


def _fmt(d):
    return d.strftime("%Y-%m-%dT%H:%M")


def coverage_lines(root, account, since_days, now=None, unbounded=False, connector=None):
    """The `Mail coverage (...)` line(s) one consumer prints for one account (design 4.3). Empty under
    gmail-multi — the existing reports are unchanged. `since_days` is THIS consumer's own window, so
    the NOT COVERED span is its own, computed from the ledger. `unbounded` marks a query with no date
    bound (reconcile's harvest, brief's per-person search): the rest of the mailbox was not covered."""
    root = root or _profile_root()
    connector = connector or selected_connector(root)
    if connector == GMAIL_MULTI:
        return []
    import mail_ingest
    now_utc = _clock() if now is None else now
    now_local = now_utc.astimezone().replace(tzinfo=None, microsecond=0)
    head = "Mail coverage (%s, %s):" % (connector, account)
    try:
        b = mail_ingest.load_kept(connector, account, [account], now_utc)
    except BundleAbsent as exc:
        return ["%s %s" % (head, exc)]
    except (BundleError, ConnectorNotSelected) as exc:
        return ["%s NOT COVERED: %s" % (head, exc)]
    st = _RUN_STATS.get(account.lower())
    parts = ["window %s..%s, %s" % (b.window_from.strftime("%Y-%m-%dT%H:%MZ"),
                                    b.window_through.strftime("%Y-%m-%dT%H:%MZ"),
                                    "exhausted" if b.exhausted else "NOT exhausted")]
    if st is not None:
        unk = st["unknown"] - st["matched"]
        parts.append("matched %d, unknown %d%s" % (len(st["matched"]), len(unk),
                                                    " (body not fetched)" if unk else ""))
    notes = []
    if not b.exhausted:
        notes.append("NOT COVERED: bundle not exhausted")
    recs = _journal.read(root)
    through_local = mail_ingest.to_local_naive(b.window_through)
    for a, z in uncovered_spans(recs, account, now_local - _dt.timedelta(days=since_days), now_local):
        if a >= through_local - _dt.timedelta(seconds=1) and (z - a) <= mail_ingest.TAIL_GRACE:
            continue                                   # the minutes between the fetch and this run
        if a >= through_local - _dt.timedelta(seconds=1):
            notes.append("NOT COVERED: after %s (not fetched yet)" % _fmt(through_local))
        else:
            notes.append("NOT COVERED: %s..%s (outside the fetched window)" % (_fmt(a), _fmt(z)))
    if unbounded:
        notes.append("NOT COVERED: mail before %s (this search has no date bound and the bundle "
                     "holds only the fetched window)" % _fmt(mail_ingest.to_local_naive(b.window_from)))
    if b.stale(now_utc):
        notes.append("!! BUNDLE STALE: the window ended %s, more than %d hours ago"
                     % (_fmt(through_local), mail_ingest.CONNECTOR_BUNDLE_STALE_HOURS))
    if b.capped:
        notes.append("NOT COVERED: window too large (%d records)" % b.capped)
    return ["%s %s" % (head, "; ".join(parts + notes))]


def is_bundle_backed(root=None):
    """True when the selected connector is read from a bundle (a selection with a backend other than
    gmail-multi). An unreadable selection answers False: the IMAP path refuses it on its own."""
    try:
        connector = selected_connector(root)
    except ValueError:
        return False
    return connector != GMAIL_MULTI and _has_backend(connector)


def account_reachable(account, root=None):
    """Can `account`'s mail be read at all right now? gmail-multi: its stored credential. A connector:
    a kept bundle that parses. Never raises; `unreachable_reason` says why not."""
    if not is_bundle_backed(root):
        return _cred.has_credential(account)
    import mail_ingest
    try:
        return mail_ingest.kept_or_none(selected_connector(root), account, [account]) is not None
    except (BundleError, ConnectorNotSelected):
        return False


def unreachable_reason(account, root=None):
    """The short reason `account_reachable` said no."""
    return "no-bundle" if is_bundle_backed(root) else "credential-missing"


def print_coverage(root, accounts, since_days, now=None, unbounded=False, out=print):
    """Print `coverage_lines` for each account; returns True when any line reports a NOT COVERED span
    or an unknown message (so a consumer with an all-clear can withhold it). A no-op under
    gmail-multi; under a selection with no backend the sweep already printed its one loud skip line."""
    root = root or _profile_root()
    try:
        connector = selected_connector(root)
    except ValueError:
        return False
    if connector == GMAIL_MULTI or not _has_backend(connector):
        return False
    partial = False
    for account in accounts:
        for line in coverage_lines(root, account, since_days, now, unbounded, connector):
            out(line)
            partial = partial or "NOT COVERED" in line or ("unknown" in line and "unknown 0" not in line)
    return partial


# --------------------------------------------------------------------------
# Credentials — platform-aware, via scripts/credentials.py
# --------------------------------------------------------------------------

# One exception type across the plugin: callers that catch CredentialError keep working whether
# the store is Keychain, PasswordVault or secret-service.
CredentialError = _cred.CredentialError


class ConnectorNotSelected(CredentialError):
    """A mailbox open was requested while the selected mail connector is not gmail-multi (dev
    #161). A CredentialError subclass on purpose: every existing caller already turns one into a
    loud INCOMPLETE COVERAGE line, never into a silent empty result."""


class BundleError(CredentialError):
    """A connector bundle cannot be used (dev #799). A CredentialError subclass on purpose, the same
    reason `ConnectorNotSelected` is one: every consumer already turns it into a loud INCOMPLETE
    COVERAGE line, never into a silent empty result."""


class BundleAbsent(BundleError):
    """Nothing was fetched and ingested for this mailbox: `NOT COVERED: no bundle ...`."""


def get_app_password(account):
    """Read the app password for `account` from the OS credential store.

    ⭐ Delegates to scripts/credentials.py, which speaks macOS Keychain, Windows PasswordVault and
    Linux secret-service. This used to shell out to `security` directly, which made the whole
    plugin macOS-only for no reason other than where it was first written. Never logs the value.
    """
    return _cred.get_app_password(account)


# --------------------------------------------------------------------------
# IMAP
# --------------------------------------------------------------------------

# ⭐ dev #311 — RFC 6154 special-use resolution, locale-independent by construction. This
# mirrors gmail-multi's `gmail_mcp_server.py` fix of the same name -- deliberately a
# duplicate, not a shared import (see this file's own "WHY A VENDORED LIBRARY" note above).
# `[Gmail]/All Mail` is the folder's ENGLISH display name; it does not exist under that path
# on an account whose Gmail display language is not English. `select_all_mail()` used to
# treat that SELECT failure as "fall back to INBOX", which reads as a complete sweep while
# covering only the inbox -- a missing thing read as an empty thing (CLAUDE.md's standing
# trap). RFC 6154 names the folder by ATTRIBUTE (`\All`) rather than by display name; this
# file cannot open a live IMAP connection to verify Gmail advertises it on a real account
# (CLAUDE.md's constraint on this dispatch), so the design PREFERS that resolution when a
# LIST response actually offers it, falls back to the English literal only when RFC 6154
# resolution finds nothing (an ordinary English-language account is unaffected either way),
# and REFUSES -- never falls back to INBOX -- when neither resolves.
SPECIAL_USE_ALL = "\\All"

_LIST_LINE_RE = re.compile(r'^\((?P<flags>[^)]*)\)\s+"(?P<delim>[^"]*)"\s+(?P<name>.+)$')


def _parse_list_line(raw):
    """(flags: set[str], mailbox_name: str) parsed out of one IMAP LIST response line.
    Returns (None, None) for anything that does not match -- never a guess."""
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8", "replace")
        except Exception:
            return None, None
    if not isinstance(raw, str):
        return None, None
    m = _LIST_LINE_RE.match(raw.strip())
    if not m:
        return None, None
    flags = set(m.group("flags").split())
    name = m.group("name").strip()
    if len(name) >= 2 and name.startswith('"') and name.endswith('"'):
        name = name[1:-1]
    return flags, name


def resolve_special_use_folders(conn):
    """{special_use_attr: mailbox_name} for every RFC 6154 special-use folder this IMAP
    LIST response advertises (dev #311). Returns {} if LIST fails or nothing parses."""
    try:
        typ, data = conn.list()
    except (socket.timeout, TimeoutError):
        # dev #712 -- a stalled server is NOT "LIST failed, nothing advertised". Swallowing it let
        # the caller go on to SELECT on a socket that had already timed out, and on Python 3.9 the
        # second read raises an unrelated `OSError('cannot read from timed out object')`.
        raise
    except Exception:
        return {}
    if typ != "OK" or not data:
        return {}
    found = {}
    for raw in data:
        if raw is None:
            continue
        flags, name = _parse_list_line(raw)
        if not flags or not name:
            continue
        if SPECIAL_USE_ALL in flags:
            found[SPECIAL_USE_ALL] = name
    return found


class MailTimeout(TimeoutError):
    """An IMAP socket to one mailbox did not answer within `IMAP_TIMEOUT_S` (dev #712). Its text
    contains "timed out", so `_classify_failure` files it under the existing `timeout` reason, for
    every caller that formats `"%s: %s" % (type(exc).__name__, exc)` as `brief.py` does."""


_UID_RE = re.compile(r"[0-9]+")


def _decode_uids(account, raw):
    """dev #704 / public #154 (S1) -- an IMAP uid is TEXT at this boundary.

    `imaplib` hands every data item back as `bytes` (its docs: "Each data is either a bytes, or a
    tuple"), and this method used to return `data[0].split()` -- a list of bytes. Every caller then
    formatted a uid into a source tag with `%s`, which writes the REPR of the bytes: `gmail:a:b'101'`
    instead of `gmail:a:101`. The wrapped shape went into stores and ids and made the same message
    look like two. Decode once, here, and every caller holds `str`.

    RFC 9051 s2.3.1.1 defines a UID as "an unsigned non-zero 32-bit value", so strict ASCII digits
    is the whole grammar. Anything else is REFUSED loudly (a `RuntimeError`, the class `search()`
    already raises for a non-OK response) rather than passed on to be written into a store; a
    `str` item is accepted unchanged only when it is already digits."""
    out = []
    for item in (raw.split() if isinstance(raw, (bytes, bytearray, str)) else [raw]):
        try:
            text = item.decode("ascii") if isinstance(item, (bytes, bytearray)) else item
        except UnicodeDecodeError:
            text = None
        if not isinstance(text, str) or not _UID_RE.fullmatch(text):
            raise RuntimeError(
                "IMAP SEARCH for %s returned a uid that is not ASCII digits: %r -- refusing to "
                "build a source tag from it (dev #704)" % (account, item))
        out.append(text)
    return out


class ImapMailbox(object):
    """The gmail-multi backend: Gmail IMAP (renamed from `Mailbox`, dev #799 M7 — `Mailbox` is now a
    factory below, and `isinstance(x, Mailbox)` is not a valid test)."""

    def __init__(self, account):
        self.account = account
        self.conn = None
        self._special_use = None  # resolved lazily, once per connection (dev #311)

    def __enter__(self):
        connector = selected_connector()
        if connector != GMAIL_MULTI:
            raise ConnectorNotSelected(
                "your mail connector is '%s', so this library does not open mailbox %s (it reads "
                "mail only through gmail-multi). Set communications.mail_connector to "
                "\"gmail-multi\" in config.json to use it." % (connector, self.account))
        pw = get_app_password(self.account)
        try:
            self.conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, timeout=IMAP_TIMEOUT_S)
            self.conn.login(self.account, pw)
        except (socket.timeout, TimeoutError) as exc:
            self._drop_connection()
            raise MailTimeout("IMAP for %s timed out after %ss (%s: %s)"
                              % (self.account, IMAP_TIMEOUT_S, type(exc).__name__, exc))
        except imaplib.IMAP4.error as exc:
            msg = str(exc)
            hint = ""
            if "AUTHENTICATIONFAILED" in msg.upper() or "Invalid credentials" in msg:
                hint = (" — the app password looks wrong or revoked. Regenerate at "
                        "https://myaccount.google.com/apppasswords and update the "
                        "Keychain entry. Note: a normal account password will NOT "
                        "work; it must be a 16-character app password, and 2-Step "
                        "Verification must be on.")
            raise CredentialError("IMAP login failed for %s: %s%s"
                                  % (self.account, msg, hint))
        finally:
            del pw
        return self

    def _drop_connection(self):
        """Close a half-open connection `__enter__` is about to abandon: `__exit__` never runs for
        an `__enter__` that raised, and a socket nobody closes holds its server slot."""
        conn, self.conn = self.conn, None
        if conn is not None:
            try:
                conn.shutdown()
            except Exception:
                pass

    def __exit__(self, *exc):
        if self.conn is not None:
            try:
                self.conn.logout()
            except Exception:
                pass
        return False

    def _special_use_folders(self):
        if self._special_use is None:
            self._special_use = resolve_special_use_folders(self.conn)
        return self._special_use

    def select_all_mail(self):
        # All Mail so Gmail's `in:anywhere` semantics behave as expected.
        name = self._special_use_folders().get(SPECIAL_USE_ALL)
        how = "RFC 6154 %s" % SPECIAL_USE_ALL
        if not name:
            name, how = ALL_MAIL.strip('"'), "the English literal (no %s advertised in LIST)" % SPECIAL_USE_ALL
        quoted = '"%s"' % name.replace("\\", "\\\\").replace('"', '\\"')
        typ, _ = self.conn.select(quoted, readonly=True)
        if typ != "OK":
            # ⚠️ dev #311 — REFUSE, never fall back to INBOX. A sweep that meant to read
            # every message must never silently narrow to the inbox and report a result as
            # if it were complete.
            raise RuntimeError(
                "Could not select an All Mail mailbox for %s -- tried %s: %r. Refusing "
                "rather than silently falling back to INBOX (dev #311): that would read as "
                "a complete sweep when it covered only the inbox. IMAP LIST advertised "
                "special-use folders: %s"
                % (self.account, how, name, sorted(self._special_use_folders()) or "none"))

    def search(self, query):
        """Gmail query syntax via the X-GM-RAW IMAP extension. Returns UIDs."""
        self.select_all_mail()
        quoted = '"%s"' % query.replace("\\", "\\\\").replace('"', '\\"')
        try:
            typ, data = self.conn.uid("SEARCH", "X-GM-RAW", quoted)
        except imaplib.IMAP4.error:
            # Non-ASCII queries need an explicit charset.
            typ, data = self.conn.uid(
                "SEARCH", "CHARSET", "UTF-8", "X-GM-RAW", quoted)
        if typ != "OK":
            raise RuntimeError("IMAP SEARCH failed for %s: %r" % (self.account, data))
        if not data or not data[0]:
            return []
        return _decode_uids(self.account, data[0])

    def fetch_headers(self, uid):
        typ, data = self.conn.uid(
            "FETCH", uid,
            "(BODY.PEEK[HEADER.FIELDS (FROM TO CC SUBJECT DATE MESSAGE-ID)])")
        if typ != "OK" or not data or not isinstance(data[0], tuple):
            return None
        return email.message_from_bytes(data[0][1])

    def fetch_full(self, uid):
        typ, data = self.conn.uid("FETCH", uid, "(BODY.PEEK[])")
        if typ != "OK" or not data or not isinstance(data[0], tuple):
            return None
        return email.message_from_bytes(data[0][1])

    def coverage(self, since):
        """⭐ dev #799 — what this search covered: IMAP asks Gmail itself, so it is the whole requested
        window `(since, now)` — the gmail-multi path is unchanged."""
        return Coverage(since, _dt.datetime.now().replace(microsecond=0))


# --------------------------------------------------------------------------
# ⭐ dev #799 — the bundle backend, and the factory every consumer opens a mailbox through
# --------------------------------------------------------------------------

def _address(person):
    import email.utils
    return email.utils.formataddr((person.get("name") or "", person["email"]))


def record_to_message(rec, full):
    """A stdlib message built from one normalised record — `Date`, `From`, `To`, `Cc`, `Subject`,
    `Message-ID` for headers; with `full`, the body and one part per attachment (a calendar file is
    `text/calendar`, as the consumers that look for one expect). The compat32 `Message`, exactly the
    class the IMAP backend's `message_from_bytes` hands back."""
    import email.mime.base
    import email.mime.multipart
    import email.mime.text
    import email.utils
    if full:
        msg = email.mime.multipart.MIMEMultipart("mixed") if rec.get("attachments") else None
        text = email.mime.text.MIMEText(rec.get("body_text") or "", "plain", "utf-8")
        if msg is None:
            msg = text
        else:
            msg.attach(text)
            for att in rec["attachments"]:
                name = att.get("filename") or ""
                ctype = att.get("content_type") or (
                    "text/calendar" if name.lower().endswith(".ics") else "application/octet-stream")
                main, _, sub = ctype.partition("/")
                part = email.mime.base.MIMEBase(main or "application", sub or "octet-stream")
                part.add_header("Content-Disposition", "attachment", filename=name)
                msg.attach(part)
    else:
        import email.message
        msg = email.message.Message()
    msg["From"] = _address(rec["from"])
    if rec.get("to"):
        msg["To"] = ", ".join(_address(p) for p in rec["to"])
    if rec.get("cc"):
        msg["Cc"] = ", ".join(_address(p) for p in rec["cc"])
    msg["Subject"] = rec.get("subject") or ""
    try:
        msg["Date"] = email.utils.format_datetime(_dt.datetime.fromisoformat(
            rec["date"].replace("Z", "+00:00")))
    except ValueError:
        pass
    if rec.get("message_id"):
        msg["Message-ID"] = rec["message_id"]
    return msg


class BundleMailbox(object):
    """⭐ dev #799 (design section 4.1) — one account's mail read from the kept bundle, behind the
    same four calls the IMAP backend answers. `search(query)` evaluates the consumer's own Gmail
    query over the records with `mail_query` (three-valued): a TRUE record is returned, a FALSE one is
    not, an UNKNOWN one (a body or attachment list that was never fetched) is counted and NEVER
    returned as a miss — the consumer's coverage line prints it. A uid is a stable digit string
    derived from the dedupe key, so it survives a new bundle and fits the `<tag>:<account>:<digits>`
    source-tag grammar."""

    def __init__(self, account, connector=None, root=None, now=None):
        self.account, self.connector, self._root, self._now = account, connector, root, now
        self.bundle = None

    def __enter__(self):
        import mail_ingest
        connector = self.connector or selected_connector(self._root)
        if connector == GMAIL_MULTI:
            raise ConnectorNotSelected(
                "your mail connector is gmail-multi, which has no bundle (mailbox %s)" % self.account)
        mail_ingest.row_for(connector)               # ConnectorNotSelected when no backend
        self.connector = connector
        self.bundle = mail_ingest.load_kept(connector, self.account, [self.account], self._now or _clock())
        return self

    def __exit__(self, *exc):
        return False

    def _clock(self):
        return self._now or _clock()

    def search(self, query):
        import mail_query
        now = self._clock()
        _RUN_STATS.setdefault(self.account.lower(), {"matched": set(), "unknown": set()})
        uids = []
        for rec in self.bundle.records:
            key = _bundle_key(self.bundle, rec)
            v = mail_query.evaluate(query, rec, now)
            if v is True:
                uids.append(_uid_of(self.bundle, key))
                _stat(self.account, "matched", key)
            elif v is None:
                _stat(self.account, "unknown", key)
        return uids

    def _record(self, uid):
        key = self.bundle.by_uid.get(str(uid))
        return self.bundle.by_key.get(key) if key else None

    def fetch_headers(self, uid):
        rec = self._record(uid)
        return None if rec is None else record_to_message(rec, False)

    def fetch_full(self, uid):
        rec = self._record(uid)
        return None if rec is None else record_to_message(rec, True)

    def coverage(self, since):
        """The span a fetched, exhausted bundle verifiably covers, intersected with the requested
        `since`: `Coverage(None, None)` when the bundle is not exhausted or stops before `since`."""
        import mail_ingest
        b = self.bundle
        if not b.exhausted:
            return Coverage(None, None)
        frm = max(mail_ingest.to_local_naive(b.window_from), since) if since else \
            mail_ingest.to_local_naive(b.window_from)
        through = mail_ingest.to_local_naive(b.window_through)
        if frm >= through:
            return Coverage(None, None)
        return Coverage(frm, through)


def _bundle_key(bundle, rec):
    import mail_ingest
    return mail_ingest.record_key(rec, bundle.connector)


def _uid_of(bundle, key):
    import mail_ingest
    return mail_ingest.uid_for(key)


def Mailbox(account):
    """⭐ dev #799 (design section 14 M7) — the ONE opener, a FACTORY: `ImapMailbox` under gmail-multi,
    `BundleMailbox` under any other selection. Every consumer opens a mailbox here. An unreadable
    selection returns the IMAP backend, whose `__enter__` refuses it loudly (as it always did)."""
    try:
        connector = selected_connector()
    except ValueError:
        return ImapMailbox(account)
    if connector == GMAIL_MULTI:
        return ImapMailbox(account)
    return BundleMailbox(account, connector)


# --------------------------------------------------------------------------
# Message helpers
# --------------------------------------------------------------------------

def header_date(msg):
    """The message's own `Date:` header as an aware UTC datetime, or None when the header is
    absent or unreadable (dev #671 / public #135). RFC 5322 section 3.6.1: `Date:` is the time
    the author finished the message -- a property of the message, never of when someone looked
    at it. `parsedate_to_datetime` yields a NAIVE value for a `-0000` zone and an aware one for
    any other offset (and raises TypeError on 3.9, ValueError on 3.10+, for garbage), so every
    value is normalised to UTC here and newest-of-several is always like compared with like.
    None is returned, never a guess: the caller decides how loud to be."""
    import email.utils
    # Reading the header is inside the try too: under the modern email policy, Python 3.9 parses a
    # `Date:` header on access and raises TypeError for garbage before parsedate_to_datetime is
    # ever reached (CI caught this on PR #676; 3.10+ is lenient).
    try:
        raw = msg.get("Date") if msg is not None else None
        if not raw:
            return None
        d = email.utils.parsedate_to_datetime(str(raw))
    except (TypeError, ValueError, IndexError, AttributeError):
        return None
    if d is None:
        return None
    if d.tzinfo is None:
        return d.replace(tzinfo=_dt.timezone.utc)
    return d.astimezone(_dt.timezone.utc)


def decode_header_value(raw):
    if not raw:
        return ""
    parts = []
    for chunk, enc in email.header.decode_header(raw):
        if isinstance(chunk, bytes):
            try:
                parts.append(chunk.decode(enc or "utf-8", "replace"))
            except (LookupError, UnicodeDecodeError):
                parts.append(chunk.decode("utf-8", "replace"))
        else:
            parts.append(chunk)
    return "".join(parts).strip()


def body_text(msg, limit=20000):
    """Prefer text/plain; fall back to de-tagged HTML."""
    plain, html = [], []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        disp = str(part.get("Content-Disposition") or "")
        if "attachment" in disp.lower():
            continue
        ctype = part.get_content_type()
        try:
            payload = part.get_payload(decode=True)
        except Exception:
            continue
        if payload is None:
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            text = payload.decode(charset, "replace")
        except (LookupError, UnicodeDecodeError):
            text = payload.decode("utf-8", "replace")
        if ctype == "text/plain":
            plain.append(text)
        elif ctype == "text/html":
            html.append(text)
    out = "\n".join(plain).strip()
    if not out and html:
        stripped = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", "\n".join(html))
        stripped = re.sub(r"(?s)<[^>]+>", " ", stripped)
        stripped = re.sub(r"&nbsp;?", " ", stripped)
        out = re.sub(r"[ \t\r\f\v]+", " ", stripped)
        out = re.sub(r"\n\s*\n\s*\n+", "\n\n", out).strip()
    if len(out) > limit:
        out = out[:limit] + "\n...[truncated]"
    return out

