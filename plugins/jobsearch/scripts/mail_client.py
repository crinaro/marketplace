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

ACCOUNT RESOLUTION IS PROFILE-COUPLED, DELIBERATELY — AND DIFFERENT FROM THE CONNECTOR'S
----------------------------------------------------------------------------------------
The connector is standalone and reads its own `~/.claude/gmail-multi/accounts.json`.
This library is jobsearch's, and jobsearch's source of truth for mailboxes is the
profile's `user.json` (Layer 1); the profile DELEGATES to the connector via the config
file's `include` list rather than the two copying from each other (ADR-004). So the
divergence in `configured_accounts()` between this file and the connector is a
contract, not drift.

CREDENTIALS
-----------
App passwords live in the OS credential store (Keychain / PasswordVault /
secret-service via scripts/credentials.py) and are read at call time — never stored
on disk, never passed as command-line arguments, never logged. The service name
(`claudesearch-imap`) is the compatibility constant shared with the connector.

Python 3.9+. No third-party packages, by design — see CLAUDE.md.
"""

import email
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(_os.path.realpath(__file__))))
from _root import profile_root as _profile_root
import email.header
import imaplib
import json
import os
import re
import sys
import datetime as _dt

import credentials as _cred
import journal as _journal

# Kept as an alias: the service name is shared with mailboxes.py and doctor.py.
KEYCHAIN_SERVICE = _cred.SERVICE
IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
ALL_MAIL = '"[Gmail]/All Mail"'


# Accounts this library searches. Emails only — never secrets.
#
# ⭐ THE SOURCE OF TRUTH IS `user.json` (LAYER 1), read at call time. This used to be a
# hardcoded list, which made the engine person-specific: a second user would have had to
# EDIT THIS SCRIPT to search their own mail. The candidate, 2026-08-02: user data is managed
# independently, and the agents/scripts leverage it rather than embedding it.
#
# Resolution order: GMAIL_MCP_ACCOUNTS env override -> user.json -> the literal fallback
# below. The fallback exists only so this module still imports if user.json is missing or
# malformed; it is NOT the configuration.
# ⭐ EMPTY BY DESIGN (2026-08-05, pre-split sanitization). This used to hard-code the
# original owner's two addresses. In a SHARED engine that is not merely a privacy leak,
# it is incoherent: silently falling back to someone else's mailbox is never the
# behaviour anyone wants. An empty list makes a missing/malformed user.json fail LOUDLY
# at the point of use, which is the correct failure.
FALLBACK_ACCOUNTS = []


def _accounts_from_user_json():
    """Read mailboxes from user.json. Returns [] on any problem — never raises, because
    this module is imported by the MCP stdio loop and by alert_sweep/meeting_check."""
    try:
        # ⭐ PROFILE root, not engine (2026-08-05). user.json belongs to the USER; under a plugin
        # install the engine directory has none, so this silently returned [] and the server
        # reported no mailboxes — indistinguishable from "you have no accounts configured".
        path = os.path.join(_profile_root(),
                            "user.json")
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return [m["address"] for m in data.get("mailboxes", []) if m.get("address")]
    except (OSError, ValueError, KeyError, TypeError):
        # ⚠️ NARROW, deliberately. A bare `except` here swallowed a NameError on 2026-08-05 and
        # reported "no mailboxes configured" — indistinguishable from a user who has none. A
        # programming error must not disguise itself as a configuration state.
        return []


def configured_accounts():
    """⭐ RE-READ EVERY CALL — never cache at import.

    This module is imported once and then serves an MCP stdio loop for the life of the process.
    Caching the account list at import meant a single bad resolution at startup produced a
    mailbox-blind server for hours: every search returned an empty result, which is exactly what
    a genuinely empty mailbox returns. On 2026-08-05 it reported "no new mail" for a whole run
    while the per-call sweeps reached both accounts fine.

    Reading per call also means a profile fixed mid-session takes effect immediately, and an
    agency switching candidates via CLAUDESEARCH_ROOT does not need a restart. The cost is one
    small JSON read per tool call.
    """
    raw = os.environ.get("GMAIL_MCP_ACCOUNTS", "").strip()
    if raw:
        return [a.strip() for a in raw.split(",") if a.strip()]
    return _accounts_from_user_json() or list(FALLBACK_ACCOUNTS)


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


def lookback_days(root, mailbox, floor_days):
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
    """
    recs = _journal.read(root)
    through = _journal.covered_through(recs, mailbox)
    if through is None:
        return max(int(floor_days or 0), COVERAGE_BACKFILL_MAX_DAYS)
    try:
        through_dt = _dt.datetime.fromisoformat(through)
    except ValueError:
        return max(int(floor_days or 0), COVERAGE_BACKFILL_MAX_DAYS)
    hole_days = (_dt.datetime.now() - through_dt).days
    capped = min(max(hole_days, 0), COVERAGE_BACKFILL_MAX_DAYS)
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


def sweep_accounts(search_one, since_days, root=None, by="", accounts=None):
    """dev #321 (V0) — THE shared multi-account sweep site. `search_one(account) -> (rows,
    error)` performs ONE account's actual search (Gmail query construction is the caller's —
    different sweeps search different things); this function does the part every caller
    duplicated: iterate every configured account (or `accounts`, for a narrowed run), call
    `search_one`, and — the fix — write exactly ONE `swept` row per account via
    `journal.record_swept()`: `ok: true` with the window `[now - since_days, now]` when
    `search_one` succeeds, `ok: false` with a classified reason when it reports an error. A
    `search_one` failure is never a crash here — that IS the `ok:false` row, not an exception.

    Returns `(results, incomplete)`: `results` is `[(account, rows, error), ...]` in call order
    (exactly what a caller's own loop already produces, so this is a drop-in for that loop's
    body); `incomplete` is the list of accounts whose sweep failed — a caller's existing
    `!! INCOMPLETE COVERAGE` banner logic needs no other change.
    """
    root = root or _profile_root()
    now = _dt.datetime.now().replace(microsecond=0)
    frm = (now - _dt.timedelta(days=since_days)).isoformat()
    through = now.isoformat()
    accounts = accounts if accounts is not None else configured_accounts()
    results, incomplete = [], []
    for account in accounts:
        rows, error = search_one(account)
        if error:
            incomplete.append(account)
            _journal.record_swept(root, account, None, None, by, False,
                                  reason=_classify_failure(error), at=through)
        else:
            _journal.record_swept(root, account, frm, through, by, True, at=through)
        results.append((account, rows, error))
    return results, incomplete


# --------------------------------------------------------------------------
# Credentials — platform-aware, via scripts/credentials.py
# --------------------------------------------------------------------------

# One exception type across the plugin: callers that catch CredentialError keep working whether
# the store is Keychain, PasswordVault or secret-service.
CredentialError = _cred.CredentialError


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


class Mailbox(object):
    def __init__(self, account):
        self.account = account
        self.conn = None
        self._special_use = None  # resolved lazily, once per connection (dev #311)

    def __enter__(self):
        pw = get_app_password(self.account)
        try:
            self.conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
            self.conn.login(self.account, pw)
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
        return data[0].split()

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

# --------------------------------------------------------------------------
# Message helpers
# --------------------------------------------------------------------------

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

