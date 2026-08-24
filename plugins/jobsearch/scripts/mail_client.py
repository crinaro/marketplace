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

import credentials as _cred

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

class Mailbox(object):
    def __init__(self, account):
        self.account = account
        self.conn = None

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

    def select_all_mail(self):
        # All Mail so Gmail's `in:anywhere` semantics behave as expected.
        typ, _ = self.conn.select(ALL_MAIL, readonly=True)
        if typ != "OK":
            typ, _ = self.conn.select("INBOX", readonly=True)
            if typ != "OK":
                raise RuntimeError("Could not select a mailbox for %s" % self.account)

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

