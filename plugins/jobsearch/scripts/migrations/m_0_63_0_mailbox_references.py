"""Migration 0.63.0: `m_0_63_0_mailbox_references()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import json
import os
import shutil
from migrations.support_jsonl import _read_asks_tolerant

VERSION = "0.63.0"


# ⭐⭐ KEYED "0.63.0" — 0.62.0 is the newest PUBLISHED jobsearch release (ADR-009; `jobsearch--v0.62.0`
# is the newest tag on origin as of 2026-10-12 and plugin.json at the branch base read 0.62.0). A
# profile that installed 0.62.0 is stamped exactly "0.62.0", and pending_for()'s strict `<` would
# never fire a migration keyed to it. Re-verify when 0.63.0 is actually cut (dev #469).
MAILBOX_ASK_PREFIX = "mailbox-unregistered:"
MAILBOX_PRE_COPY = "user.json.pre-0.63.0"


def _gmail_multi_registry_path(home=None):
    """Where gmail-multi's registry lives — the same rule `mail_client.registry_path()` states
    (`GMAIL_MULTI_CONFIG`, else `~/.claude/gmail-multi/accounts.json`), with `home` as the test /
    caller override `m_0_29_0` always had."""
    env = os.environ.get("GMAIL_MULTI_CONFIG", "").strip()
    return env or os.path.join(home or os.path.expanduser("~"), ".claude", "gmail-multi",
                               "accounts.json")


def _profile_selects_a_connector(profile):
    """True only when `config.json` names a known claude.ai connector in
    `communications.mail_connector` (any accepted value other than "gmail-multi"; dev #799). A
    connector binds its own account, so the registry is not consulted. Anything unreadable or
    unrecognised is NOT a connector: the registry is consulted, which narrows, never widens."""
    import config_keys as _ck
    try:
        with open(os.path.join(profile, "config.json"), encoding="utf-8") as fh:
            cfg = json.load(fh)
        value = (cfg.get("communications") or {}).get("mail_connector")
    except (OSError, ValueError, AttributeError):
        return False
    return value in _ck.MAIL_CONNECTOR_VALUES and value != "gmail-multi"


def _mailbox_reference_state(profile, home=None):
    """The 0.63.0 SUCCESS CONDITION, queried from disk (never assumed from what was just written):
    `(registry, detail, unregistered, declared, keychain_left)`.

    `registry` is one of
      "ok"           a claude.ai connector is selected, or no address is declared, or the registry reads
                     schema 2 and holds every declared address;
      "absent"       the registry file is not there (gmail-multi installs itself at session start);
      "pending"      the registry is still schema 1 — gmail-multi has not migrated it;
      "malformed"    the registry exists but cannot be read as schema 2 (`detail` says why);
      "unregistered" the registry is fine but lacks `unregistered` (declared addresses);
      "unreadable"   user.json itself cannot be read (`detail` says why).
    `declared` is the profile's own address list; `keychain_left` is True while any mailbox still
    carries `keychain_service`. The migration is done only when `registry == "ok"` and not
    `keychain_left`."""
    user_path = os.path.join(profile, "user.json")
    try:
        with open(user_path, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("top level is %s, not an object" % type(data).__name__)
    except (OSError, ValueError) as e:
        return "unreadable", "%s: %s" % (type(e).__name__, e), [], [], False
    boxes = [b for b in (data.get("mailboxes") or []) if isinstance(b, dict)]
    declared = [b["address"].strip() for b in boxes
                if isinstance(b.get("address"), str) and b["address"].strip()]
    keychain_left = any("keychain_service" in b for b in boxes)
    if _profile_selects_a_connector(profile) or not declared:
        return "ok", "", [], declared, keychain_left
    import mail_client
    path = _gmail_multi_registry_path(home)
    if not os.path.exists(path):
        return "absent", path, [], declared, keychain_left
    try:
        held = {a.lower() for a in mail_client.registry_accounts(path)}
    except mail_client.RegistryPending as e:
        return "pending", str(e), [], declared, keychain_left
    except mail_client.RegistryError as e:
        return "malformed", str(e), [], declared, keychain_left
    unregistered = [a for a in declared if a.lower() not in held]
    if unregistered:
        return "unregistered", "", unregistered, declared, keychain_left
    return "ok", "", [], declared, keychain_left


def _mailbox_ask_row(address, today):
    """F5 — one `asks.jsonl` row, kind=system, a STABLE id so a re-run replaces it by id (the
    `check_engine_purity` ask's shape). It asks the user for a DECISION, never for mechanical work."""
    return {"id": MAILBOX_ASK_PREFIX + address.lower(), "kind": "system",
            "title": "%s is not in gmail-multi's registry" % address,
            "ask": ("This profile lists %s as a mailbox, but gmail-multi does not know that "
                    "account, so it is NOT searched (the job search would read it as no mail). "
                    "Decide: keep it and register it with /gmail-multi:accounts, or drop it from "
                    "this profile with /jobsearch:mailboxes. The next session start re-checks and "
                    "closes this ask on its own once either is done." % address),
            "created": today, "act_by": None, "opp_id": None, "channel_id": None,
            "resolves_when": None, "resolved_on": None, "resolution": None,
            "trigger_kind": None, "trigger_ref": None, "note": None}


def _reconcile_mailbox_asks(profile, unregistered, declared, may_close, apply_it, today):
    """The resolver for the `mailbox-unregistered:<addr>` rows (F5) — THIS migration, on every re-run
    until it stamps. Adds a row for each address in `unregistered` (an already-present row is kept
    as it is, so `created` does not reset and a row the user resolved is not reopened) and, when
    `may_close` (the registry was read, so the answer is KNOWN), closes an OPEN row whose address is
    now registered (`registered`) or no longer declared (`removed`).
    Returns `(error, closed)`: `error` is a plain-words reason the file could not be handled."""
    path = os.path.join(profile, "data", "asks.jsonl")
    rows, err = _read_asks_tolerant(path)
    if err:
        return err, 0
    want = {MAILBOX_ASK_PREFIX + a.lower(): a for a in unregistered}
    still_declared = {a.lower() for a in declared}
    present = {r.get("id") for r in rows}
    out, closed, added = [], 0, 0
    for r in rows:
        rid = str(r.get("id") or "")
        if (may_close and rid.startswith(MAILBOX_ASK_PREFIX) and not r.get("resolved_on")
                and rid not in want):
            addr = rid[len(MAILBOX_ASK_PREFIX):]
            r = dict(r, resolved_on=today,
                     resolution=("registered" if addr in still_declared else "removed"))
            closed += 1
        out.append(r)
    for rid, addr in sorted(want.items()):
        if rid not in present:
            out.append(_mailbox_ask_row(addr, today))
            added += 1
    if (closed or added) and apply_it:
        import _atomic
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _atomic.write_jsonl(path, out)
    return None, closed


def m_0_63_0_mailbox_references(profile, apply_it, home=None):
    """0.63.0 — the profile's mailboxes become REFERENCES into gmail-multi's registry (dev #469 /
    public #524; design-mail-boundary.md § 3.3, § 7.2).

    gmail-multi owns the ONE account registry (`~/.claude/gmail-multi/accounts.json`, schema 2).
    `user.json` `mailboxes` stays a list of `{"address", "kind"?, "note"?}`, and the address IS the
    reference — so `keychain_service`, a second copy of credential identity that nothing reads, is
    dropped. This migration never WRITES the registry (gmail-multi's `accounts.py` is its one
    writer).

    ⭐ PRESERVE, THEN TRANSFORM, THEN QUERY. Before the first write, `user.json` is copied
    byte-for-byte to `user.json.pre-0.63.0` (unless that copy exists). Then `keychain_service` is
    dropped from each mailbox and nothing else changes. Then the success condition is RE-READ from
    disk (`_mailbox_reference_state`), and what it finds decides the return:

      * registry ABSENT        -> ⏳ pending (gmail-multi installs itself at session start; ADR-005)
      * registry schema 1      -> ⏳ pending (gmail-multi has not migrated its registry yet)
      * registry malformed     -> ⏳ pending, naming why
      * some address lacks one -> ⏳ pending, and one `asks.jsonl` row per such address (F5)
      * everything holds       -> done; any open `mailbox-unregistered:*` row is closed

    ⛔ Pending is NEVER a false "0 done": it returns False, so `main()` does not stamp and the
    migration is offered again next session — which is also what closes the ask rows once the user
    has registered the account or dropped it. The transform is idempotent, so a re-run costs nothing.
    Under the `claude-gmail` connector the registry is not consulted at all.
    """
    import datetime as _dt
    user_path = os.path.join(profile, "user.json")
    if not os.path.exists(user_path):
        return True, ""
    registry, detail, unregistered, declared, keychain_left = _mailbox_reference_state(profile, home)
    if registry == "unreadable":
        return False, ("  ⚠️ %s exists but cannot be read (%s). Left untouched — fix it, and this "
                       "migration runs again next session." % (user_path, detail))
    lines = []
    if keychain_left and not apply_it:
        lines.append("  would drop keychain_service from user.json mailboxes (the original is kept "
                     "at %s)" % MAILBOX_PRE_COPY)
    elif keychain_left:
        with open(user_path, encoding="utf-8") as fh:
            data = json.load(fh)
        holding = [b for b in (data.get("mailboxes") or [])
                   if isinstance(b, dict) and "keychain_service" in b]
        copy_path = os.path.join(profile, MAILBOX_PRE_COPY)
        if not os.path.exists(copy_path):
            try:
                shutil.copy2(user_path, copy_path)
            except (OSError, shutil.Error) as e:
                return False, ("  ⚠️ user.json could not be preserved to %s (%s), so keychain_service "
                               "was NOT dropped — nothing was changed." % (MAILBOX_PRE_COPY, e))
        for b in holding:
            del b["keychain_service"]
        import _atomic
        _atomic.write_json(user_path, data)
        lines.append("  dropped keychain_service from %d mailbox(es) in user.json (nothing else "
                     "changed; the original is kept at %s)" % (len(holding), MAILBOX_PRE_COPY))
        # QUERY: the success condition is what the disk says now, not what was just written.
        registry, detail, unregistered, declared, keychain_left = \
            _mailbox_reference_state(profile, home)
        if keychain_left:
            return False, "\n".join(lines + ["  ⚠️ keychain_service is still present after the "
                                             "write — not stamped; offered again next session."])

    today = _dt.date.today().isoformat()
    ask_err, closed = _reconcile_mailbox_asks(
        profile, unregistered, declared, registry in ("ok", "unregistered"), apply_it, today)
    if ask_err:
        lines.append("  ⚠️ data/asks.jsonl cannot be read (%s), so the unregistered-mailbox ask was "
                     "left alone." % ask_err)
    if closed:
        lines.append("  closed %d unregistered-mailbox ask(s): the address is registered, or gone "
                     "from this profile" % closed)

    if registry == "absent":
        lines.append("  ⏳ 0.63.0 PENDING — gmail-multi's registry not found at %s (gmail-multi "
                     "installs itself at session start; ADR-005). The mailboxes cannot be checked "
                     "against it yet." % detail)
    elif registry == "pending":
        lines.append("  ⏳ 0.63.0 PENDING — gmail-multi has not migrated its registry yet (%s)"
                     % detail)
    elif registry == "malformed":
        lines.append("  ⏳ 0.63.0 PENDING — gmail-multi's registry cannot be used: %s" % detail)
    elif registry == "unregistered":
        lines.append("  ⏳ 0.63.0 PENDING — not in gmail-multi's registry: %s. Each has an ask: "
                     "register it with /gmail-multi:accounts, or drop it with /jobsearch:mailboxes."
                     % ", ".join(unregistered))
    return registry == "ok", "\n".join(lines)
