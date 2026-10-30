#!/usr/bin/env python3
"""Configure which mailboxes the job search reads. Backs the `/jobsearch:mailboxes` command.

Three things, deliberately separate:
  THE ACCOUNTS — which accounts exist on this machine. gmail-multi's REGISTRY owns them
               (`/gmail-multi:accounts` is its one writer); this script only READS it.
  THE LIST   — which of those this profile searches. Plain config, lives in
               `user.json.mailboxes` as a list of addresses that REFERENCE the registry. This
               script edits it, and refuses to add an address the registry lacks (dev #469).
  THE SECRETS— one app password per address. Lives in the OS credential store. ⭐ THIS SCRIPT
               NEVER TOUCHES ONE. It prints the command for you to run and then verifies that a
               credential appeared. See scripts/credentials.py for why.

⭐⭐ WHY THE LIST MATTERS AS MUCH AS THE SECRETS: a search that covers one mailbox can never prove
a message does not exist, and the failure is silent — a mailbox nobody configured returns exactly
what an empty mailbox returns. `mail_client.py` therefore searches ALL configured accounts by
default and raises a loud INCOMPLETE COVERAGE banner for any it cannot reach. Adding an address
here is what makes it searchable; storing its password is what makes it reachable. **Both, or the
account is invisible.**

    python3 scripts/mailboxes.py --status              # what is configured and what works
    python3 scripts/mailboxes.py --add you@work.com    # add an address (prints the next step)
    python3 scripts/mailboxes.py --remove old@x.com    # stop searching it

⭐ dev #799: the connector selection (`communications.mail_connector`) has five values; every per-value
fact (label, the Microsoft 365 work-or-school limit) lives in `mail_connectors.py`, the one table. Under a
claude.ai connector the addresses below are what is read THROUGH it, the credential store is not
consulted, and gmail-multi's registry is not either.
"""

import argparse
import json
import os
import platform
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _root import profile_root
import credentials as cred
import mail_connectors            # the one table of connector values and their limits (dev #799)
import mail_connectors            # the one table of connector values and their limits (dev #799)

PROVIDER_HELP = {
    "gmail.com": ("Google", "https://myaccount.google.com/apppasswords",
                  "Requires 2-Step Verification to be ON. Workspace accounts also need an admin "
                  "to leave IMAP enabled."),
    "outlook.com": ("Microsoft", "https://account.microsoft.com/security",
                    "Create an app password under Advanced security options."),
    "hotmail.com": ("Microsoft", "https://account.microsoft.com/security", ""),
    "yahoo.com": ("Yahoo", "https://login.yahoo.com/account/security", ""),
}


def _user_json_path():
    return os.path.join(profile_root(), "user.json")


def _load():
    p = _user_json_path()
    if not os.path.exists(p):
        print("No user.json at %s.\nRun the onboarding first: /jobsearch:onboarding" % p)
        raise SystemExit(1)
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def _save(data):
    p = _user_json_path()
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, p)          # atomic: a partial write would destroy the profile's identity


def _provider_note(address):
    domain = address.split("@")[-1].lower()
    for suffix, (name, url, extra) in PROVIDER_HELP.items():
        if domain == suffix or domain.endswith("." + suffix):
            return name, url, extra
    return None, None, ""


def connector_lines():
    """(lines, ok) — which mail connector jobsearch uses and how to switch it (dev #161). `ok` is
    False only when the selection in config.json is not a valid value: refused, never coerced."""
    import config_keys
    import mail_client
    key = config_keys.MAIL_CONNECTOR
    try:
        selected = mail_client.selected_connector()
    except ValueError as exc:
        return (["  Mail connector  : !! INVALID — %s" % exc,
                 "                    Until it is fixed, jobsearch will not use either connector."],
                False)
    cfg_provenance = "in your config.json"
    try:
        with open(os.path.join(profile_root(), "config.json"), encoding="utf-8") as fh:
            cfg_provenance = config_keys.describe(json.load(fh), key)[1]
    except (OSError, ValueError):
        cfg_provenance = "default — not in your file"
    lines = ["  Mail connector  : %s (%s)" % (selected, cfg_provenance),
             "                    jobsearch uses ONLY this connector; the others' mail tools are "
             "blocked."]
    row = mail_connectors.row(selected)
    if row is not None:
        # dev #799 (design §2, §14 S6): the limit and its warning are stated wherever the selection
        # is shown, never only in a doc.
        if row["limit"]:
            lines.append("                    %s %s" % (row["label"].split(" (")[0], row["limit"]))
        if row["warning"]:
            lines.append("                    ⚠️ %s" % row["warning"])
    lines.append("                    The values, and how to switch (set \"%s\" in config.json):" % key)
    for value in mail_connectors.VALUES:
        if value == selected:
            continue
        lines.append('                      "%s" — %s' % (value, mail_connectors.label(value)))
        other = mail_connectors.row(value)
        if other is not None and other["limit"]:
            lines.append("                        %s %s" % (other["label"].split(" (")[0],
                                                           other["limit"]))
    if selected != mail_client.GMAIL_MULTI:
        lines.append("                    The address list below is the list of mailboxes to read "
                     "through %s; app passwords matter for gmail-multi only." % selected)
    return lines, True


REGISTRY_FIX = "add it with /gmail-multi:accounts"


def connector_in_use():
    """The selected claude.ai connector's label, or None under `gmail-multi` (and when the selection
    cannot be read: an unreadable selection narrows, so the gmail-multi path keeps its checks)."""
    import mail_client
    try:
        selected = mail_client.selected_connector()
    except ValueError:
        return None
    if selected == mail_client.GMAIL_MULTI:
        return None
    return mail_connectors.label(selected)


def registry_state():
    """`(state, held, detail)` — how gmail-multi's registry sees this machine. `state` is one of:
    "skip"    the registry is not consulted (the claude-gmail connector binds its own account);
    "env"     `GMAIL_MCP_ACCOUNTS` names the accounts (gmail-multi's own override of the registry);
    "ok"      schema 2, read — `held` is the lower-cased set of its addresses;
    "pending" still schema 1: gmail-multi has not migrated it yet;
    "absent"  absent or malformed. `detail` is the plain-words reason for the last two."""
    import mail_client
    raw = os.environ.get("GMAIL_MCP_ACCOUNTS", "").strip()
    if raw:
        return "env", {a.strip().lower() for a in raw.split(",") if a.strip()}, ""
    try:
        connector = mail_client.selected_connector()
    except ValueError:
        connector = mail_client.GMAIL_MULTI           # an unreadable selection narrows, not widens
    if connector != mail_client.GMAIL_MULTI:
        return "skip", set(), ""
    try:
        return "ok", {a.lower() for a in mail_client.registry_accounts()}, ""
    except mail_client.RegistryPending as exc:
        return "pending", set(), str(exc)
    except mail_client.RegistryError as exc:
        return "absent", set(), str(exc)


def registry_label(address, state, held):
    """(text, ok) — the line `--status` prints for one address against the registry; None when the
    registry is not consulted. An address the registry does not hold is NEVER shown as searchable."""
    if state == "skip":
        return None, True
    if state in ("ok", "env"):
        if address.lower() in held:
            return "in gmail-multi's registry", True
        return "NOT IN gmail-multi's registry — %s" % REGISTRY_FIX, False
    if state == "pending":
        return ("registry not migrated yet — gmail-multi updates it at its next session start, "
                "then this shows whether %s is in it" % address), False
    return "gmail-multi's registry is unavailable — see below", False


def status():
    data = _load()
    boxes = data.get("mailboxes", []) or []
    b = cred.backend()
    store_name = {"keychain": "macOS Keychain",
                  "wincred": "Windows Credential Manager (PasswordVault)",
                  "secretservice": "Linux secret-service (libsecret)"}.get(b, b)

    print("MAILBOXES — %s" % _user_json_path())
    print("=" * 74)
    print("  Platform        : %s" % platform.system())
    print("  Credential store: %s" % store_name)
    print("  Service name    : %s" % cred.SERVICE)
    connector_text, connector_ok = connector_lines()
    for line in connector_text:
        print(line)
    print()

    if not boxes:
        print("  No mailboxes configured. The search is mailbox-blind: every query will come")
        print("  back empty, which looks exactly like a quiet inbox.")
        if connector_in_use():
            print("\n  List the address to read through your connector:")
        else:
            print("\n  Register the account with gmail-multi first (/gmail-multi:accounts), then:")
        print("  Add one:  python3 scripts/mailboxes.py --add you@example.com")
        return 1

    reg_state, reg_held, reg_detail = registry_state()
    via = connector_in_use()        # a claude.ai connector's label, or None under gmail-multi
    problems = 0
    registry_problems = 0
    for m in boxes:
        addr = m.get("address", "")
        if via:
            # dev #799: a claude.ai connector holds its own sign-in, so no app password or registry
            # entry is involved. Printing "NO CREDENTIAL" here would be a false alarm.
            print("  [OK ] %-38s read through %s" % (addr, via))
            continue
        ok = cred.has_credential(addr)
        problems += 0 if ok else 1
        print("  [%s] %-38s %s" % ("OK " if ok else "!! ", addr,
                                   "credential present" if ok else "NO CREDENTIAL — not searchable"))
        reg_text, reg_ok = registry_label(addr, reg_state, reg_held)
        if reg_text is not None:
            registry_problems += 0 if reg_ok else 1
            print("       %s" % reg_text)
        if not ok:
            shell_kind, cmd, note = cred.store_command(addr)
            name, url, extra = _provider_note(addr)
            print()
            if name:
                print("       1. Create an app password at %s (%s)." % (url, name))
                if extra:
                    print("          %s" % extra)
            else:
                print("       1. Create an app password in your mail provider's security settings.")
            print("       2. Store it yourself, in %s:" % shell_kind)
            for line in cmd.splitlines():
                print("            %s" % line)
            print("          %s" % note)
            print()

    print()
    if reg_detail:
        print("  gmail-multi registry: %s" % reg_detail)
        print()
    if registry_problems:
        print("  %d of %d mailbox(es) are not confirmed in gmail-multi's registry, so they are NOT "
              "searched." % (registry_problems, len(boxes)))
        print("  The accounts live in gmail-multi's registry, which /gmail-multi:accounts writes; "
              "this profile only references them.")
        print()
    if problems:
        print("  %d of %d mailbox(es) cannot be searched." % (problems, len(boxes)))
        print("  ⚠️ Until fixed, a search of those accounts returns empty — indistinguishable")
        print("     from no mail. Never read that as 'nothing arrived'.")
    elif via:
        print("  %d mailbox(es) listed to read through %s. Whether the connector can reach each one "
              "is shown by the daily run's preflight, not here." % (len(boxes), via))
    elif not registry_problems:
        print("  All %d mailbox(es) configured and reachable." % len(boxes))
    return 1 if (problems or registry_problems or not connector_ok) else 0


def add(address):
    data = _load()
    boxes = data.setdefault("mailboxes", [])
    if any(m.get("address", "").lower() == address.lower() for m in boxes):
        print("%s is already configured." % address)
        return status()
    # dev #469 — the address is a REFERENCE into gmail-multi's registry, so an address the registry
    # lacks is refused HERE, loudly, and nothing is written. (The registry has one writer,
    # gmail-multi's accounts.py; this script never writes it.)
    state, held, detail = registry_state()
    if state in ("ok", "env") and address.lower() not in held:
        print("NOT IN gmail-multi's registry — %s is not one of the accounts gmail-multi knows, so "
              "adding it here would reference nothing and it would never be searched." % address)
        print("Nothing was written. First register it with gmail-multi:  /gmail-multi:accounts "
              "(add %s), then run this again." % address)
        return 1
    if state in ("pending", "absent"):
        print("Cannot confirm %s against gmail-multi's registry: %s" % (address, detail))
        print("Nothing was written. Fix that first (/gmail-multi:accounts), then run this again.")
        return 1
    boxes.append({"address": address,
                  "kind": "consumer" if "@gmail." in address else "workspace"})
    _save(data)
    print("Added %s to user.json.\n" % address)
    via = connector_in_use()
    if via:
        print("It is listed to be read through %s, which holds its own sign-in. No app password "
              "is involved." % via)
    else:
        print("⭐ It is NOT searchable yet — it still needs an app password in your credential "
              "store.")
    print()
    return status()


def remove(address):
    data = _load()
    boxes = data.get("mailboxes", []) or []
    kept = [m for m in boxes if m.get("address", "").lower() != address.lower()]
    if len(kept) == len(boxes):
        print("%s is not configured; nothing to remove." % address)
        return 1
    data["mailboxes"] = kept
    _save(data)
    print("Removed %s from user.json. It will no longer be searched." % address)
    print()
    print("⚠️ Its stored password was NOT deleted — this tool never touches the credential store.")
    shell_kind, _, _ = cred.store_command(address)
    if cred.backend() == "keychain":
        print("   To delete it yourself:  security delete-generic-password -a %s -s %s"
              % (address, cred.SERVICE))
    elif cred.backend() == "wincred":
        print("   To delete it yourself:  Windows Credential Manager > Web Credentials > %s"
              % cred.SERVICE)
    else:
        print("   To delete it yourself:  secret-tool clear service %s account %s"
              % (cred.SERVICE, address))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--status", action="store_true", help="what is configured and what works")
    ap.add_argument("--add", metavar="ADDRESS", help="add a mailbox to search")
    ap.add_argument("--remove", metavar="ADDRESS", help="stop searching a mailbox")
    a = ap.parse_args()
    if a.add:
        return add(a.add)
    if a.remove:
        return remove(a.remove)
    return status()


if __name__ == "__main__":
    sys.exit(main())
