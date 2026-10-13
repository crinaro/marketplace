#!/usr/bin/env python3
"""Configure which Gmail accounts the gmail-multi connector searches.

⭐⭐ ADDRESSES ONLY — NEVER SECRETS. This tool writes email addresses to
`~/.claude/gmail-multi/accounts.json` and PRINTS the command that stores an app
password in the OS credential store. It cannot accept, store, print or log a
password itself — see scripts/credentials.py for why there is no `--set` flag.

The config file is the connector's single source of truth (the server re-reads
it on every tool call). It is REGISTRY SCHEMA 2, a published interface other
plugins may read and must never write:

    { "schema": 2, "accounts": ["you@example.com"] }

⭐ THIS TOOL IS THE REGISTRY'S ONE WRITER. `write_registry()` below is the single
atomic writer (tmp file + os.replace); `migrate.py` writes through it too, so there
is no second code path that can tear the file. A consumer plugin declares which of
these accounts it uses in its OWN data, by address, and never edits this file.
(Until 0.5.0 the file could also list other files whose addresses merged in. That
was retired because it let two lists drift apart; `migrate.py` folds any such list
into `accounts` once, keeping a preserved copy.)

Usage:
    python3 accounts.py --status                 what is configured; credential presence
    python3 accounts.py --status --json          the same, machine-readable
    python3 accounts.py --add you@example.com
    python3 accounts.py --remove you@example.com

Python 3.9+. Standard library only.
"""

import argparse
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import credentials as _cred

# ⚠️ gmail_mcp_server is imported LAZILY (inside the functions that need it), never at module
# top: the server calls migrate.py, and migrate.py writes through this module's
# write_registry(). A top-level import here would be a cycle (and, with the server running as
# __main__, would load it a second time under another name).


def _server():
    import gmail_mcp_server
    return gmail_mcp_server


def _config_path():
    return os.environ.get("GMAIL_MULTI_CONFIG", "").strip() or _server().CONFIG_PATH


def write_registry(data, path=None):
    """⭐ THE ONE ATOMIC WRITER of the registry — `migrate.py` calls this too.

    A torn accounts.json would make every search fail loudly, which is better than silently,
    but better still is neither: write a temp file in the same directory, then os.replace().
    Returns the path written. Prints nothing (callers decide what to say)."""
    path = path or _config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return path


def _load():
    """The registry as a schema-2 dict (a fresh one when the file is absent). A file still on
    the old shape is migrated first (migrate.py preserves it); if that cannot complete, this
    refuses rather than write a schema-2 file over something it could not fold."""
    path = _config_path()
    if not os.path.exists(path):
        return {"schema": 2, "accounts": []}
    with open(path, encoding="utf-8") as fh:
        try:
            data = json.load(fh)
        except ValueError as exc:
            raise SystemExit("%s is not valid JSON (%s) — fix or remove it." % (path, exc))
    if not isinstance(data, dict):
        raise SystemExit("%s must hold a JSON object, got %s — fix or remove it."
                         % (path, type(data).__name__))
    if data.get("schema") != 2 or "include" in data:  # retired-terms: ok
        import migrate
        ok, msg = migrate.m_0_5_0_registry_v2(path)
        if not ok:
            raise SystemExit(msg.strip())
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    return data


def _save(data):
    # _load() guarantees `data` is already schema 2 (a fresh dict, or a migrated file).
    print("Wrote %s" % write_registry(data))


def cmd_status(as_json=False):
    srv = _server()
    path = _config_path()
    env = os.environ.get("GMAIL_MCP_ACCOUNTS", "").strip()
    error = None
    try:
        accounts = srv.configured_accounts()
    except srv.AccountsError as exc:
        accounts, error = [], str(exc)

    creds = [(acct, _cred.has_credential(acct)) for acct in accounts]
    missing = [acct for acct, ok in creds if not ok]

    if as_json:
        print(json.dumps({
            "config": path,
            "config_present": os.path.exists(path),
            "env_override": bool(env),
            "accounts": [{"address": acct, "credential": ok} for acct, ok in creds],
            "unconfigured": not accounts and error is None,
            "error": error,
        }, indent=2, sort_keys=True))
        return 1 if (error or not accounts or missing) else 0

    print("Config file: %s%s" % (path, "" if os.path.exists(path) else "  (absent)"))
    if env:
        print("GMAIL_MCP_ACCOUNTS is set and OVERRIDES the file: %s" % env)
    if error:
        print("\n%s" % error)
        return 1
    if not accounts:
        print("\n%s" % srv.UNCONFIGURED_HELP)
        return 1
    print("\nRegistered accounts (a call must name one, or pass `all` to search every one):")
    for acct, ok in creds:
        print("  [%s] %s" % ("OK     " if ok else "MISSING", acct))
    for acct in missing:
        shell, cmd, note = _cred.store_command(acct)
        print("\nStore the app password for %s yourself, in %s:\n\n  %s\n\n  %s"
              % (acct, shell, cmd, note))
    return 1 if missing else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--status", action="store_true")
    g.add_argument("--add", metavar="ADDRESS")
    g.add_argument("--remove", metavar="ADDRESS")
    ap.add_argument("--json", action="store_true", help="with --status: machine-readable output")
    args = ap.parse_args()

    if args.json and not args.status:
        ap.error("--json only goes with --status")
    if args.status:
        return cmd_status(as_json=args.json)

    data = _load()
    if args.add:
        addr = args.add.strip()
        if "@" not in addr:
            raise SystemExit("%r does not look like an email address." % addr)
        accounts = data.setdefault("accounts", [])
        if addr in accounts:
            print("%s is already configured." % addr)
            return 0
        accounts.append(addr)
        _save(data)
        shell, cmd, note = _cred.store_command(addr)
        print("\nNow store its app password yourself, in %s:\n\n  %s\n\n  %s"
              % (shell, cmd, note))
        return 0
    if args.remove:
        addr = args.remove.strip()
        accounts = data.get("accounts") or []
        if addr not in accounts:
            raise SystemExit("%s is not in `accounts` (an env override is unset in your "
                             "shell)." % addr)
        accounts.remove(addr)
        _save(data)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
