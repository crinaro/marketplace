#!/usr/bin/env python3
"""Read a mail app-password from the OS credential store. macOS, Windows, Linux.

⭐⭐ THIS MODULE NEVER ACCEPTS, WRITES, PRINTS OR LOGS A SECRET.
It can READ one (to hand straight to an IMAP socket) and it can TELL YOU THE COMMAND that stores
one. It cannot store one for you, and there is deliberately no `--set` flag anywhere in this
plugin. The reason is not ceremony: a password passed as a CLI argument lands in shell history and
in the process table, where any other user on the machine can read it, and a password typed into a
chat window is retained in a transcript. Both are worse than the account's own login page.

So the flow is always: the tool prints a command, THE USER runs it, and the tool verifies a
credential now exists. Claude never sees the value at any point.

⚠️ USE AN APP PASSWORD, NEVER THE ACCOUNT PASSWORD. Google and Microsoft both issue per-app
passwords that can be revoked individually and cannot change the account's recovery settings. If
the mailbox has 2FA (it should), an app password is the only thing that will work over IMAP.

The store per platform, and why:
  macOS    Keychain via `security`          — present on every Mac, no install.
  Windows  PasswordVault via PowerShell     — built into Windows 10+, no module to install.
           (`cmdkey` is NOT usable: it stores a credential but cannot read the password back.)
  Linux    secret-service via `secret-tool` — the freedesktop standard; needs libsecret-tools.
"""

import os
import platform
import subprocess
import time

SERVICE = "claudesearch-imap"

# dev #1017 / public #280 -- a credential store that does not answer (a locked keychain, an
# unlock prompt nobody is there to click) made every lookup wait its full timeout, once per
# account and again when the mailbox opened, so `brief.py`'s probe ran past the caller's own kill.
# Two bounds, both per process: once the credential store has failed to answer, every later lookup refuses at
# once with the same reason (a store that is not answering is not answering for any account); and
# a caller's deadline (`set_deadline`, `brief.py --deadline-s`) caps every lookup's wait.
LOOKUP_TIMEOUT_S = 20.0
_STATE = {"deadline": None, "unresponsive": None, "failures": {}}


class CredentialError(RuntimeError):
    """Raised when a credential is missing or the store is unreachable.

    The message is always actionable — it names the exact command to run. A bare "auth failed"
    sends someone hunting through their mail provider's settings for a problem that is really an
    empty credential store.
    """

    reason = "credential-missing"


class CredentialTimeout(CredentialError):
    """The credential store did not answer in time (dev #1017). `reason` names the credential."""


def set_deadline(seconds):
    """Cap every later lookup in this process to end within `seconds` from now (None clears)."""
    _STATE["deadline"] = None if seconds is None else time.monotonic() + float(seconds)


def failure_reason(account):
    """The short reason the last lookup for `account` failed: `credential-timeout: ...` naming the
    credential when the store did not answer, else `credential-missing`."""
    return _STATE["failures"].get(account, "credential-missing")


def _timed_out(account, seconds):
    """Record and return the CredentialTimeout for `account`; its reason names the credential."""
    reason = ("credential-timeout: the %s store did not answer for %s (service %s) within %gs, "
              "a locked store or an unanswered unlock prompt" % (backend(), account, SERVICE,
                                                                 seconds))
    _STATE["failures"][account] = reason
    exc = CredentialTimeout("Credential lookup for %s refused: %s." % (account, reason))
    exc.reason = reason
    return exc


def _lookup_wait(account):
    """Seconds this lookup may wait; raises CredentialTimeout when it may not start at all."""
    if _STATE["unresponsive"] is not None:
        raise _timed_out(account, _STATE["unresponsive"])
    wait = LOOKUP_TIMEOUT_S
    if _STATE["deadline"] is not None:
        wait = min(wait, _STATE["deadline"] - time.monotonic())
    if wait <= 0:
        raise _timed_out(account, 0)
    return wait


def backend():
    """Which credential store this machine uses. Override with CLAUDESEARCH_CRED_BACKEND."""
    forced = os.environ.get("CLAUDESEARCH_CRED_BACKEND", "").strip().lower()
    if forced:
        return forced
    system = platform.system()
    if system == "Darwin":
        return "keychain"
    if system == "Windows":
        return "wincred"
    return "secretservice"


def store_command(account):
    """The command the USER runs to store a password. Returns (shell, command, note)."""
    b = backend()
    if b == "keychain":
        return (
            "bash",
            "security add-generic-password -a %s -s %s -w" % (account, SERVICE),
            "Omit any value after -w. `security` then prompts, so the password never enters "
            "your shell history.",
        )
    if b == "wincred":
        return (
            "powershell",
            "[Windows.Security.Credentials.PasswordVault,Windows.Security.Credentials,"
            "ContentType=WindowsRuntime] > $null\n"
            "$pw = Read-Host 'App password' -AsSecureString\n"
            "$plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto("
            "[Runtime.InteropServices.Marshal]::SecureStringToBSTR($pw))\n"
            "$vault = New-Object Windows.Security.Credentials.PasswordVault\n"
            "$vault.Add((New-Object Windows.Security.Credentials.PasswordCredential("
            "'%s','%s',$plain)))" % (SERVICE, account),
            "Read-Host -AsSecureString keeps the password off the screen and out of PowerShell "
            "history. Run it in PowerShell, not cmd.",
        )
    return (
        "bash",
        "secret-tool store --label='%s' service %s account %s" % (SERVICE, SERVICE, account),
        "secret-tool prompts for the value. Install with `apt install libsecret-tools` or your "
        "distribution's equivalent.",
    )


def _run(cmd, shell_kind="bash", timeout=LOOKUP_TIMEOUT_S):
    if shell_kind == "powershell":
        argv = ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd]
    else:
        argv = cmd
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def get_app_password(account):
    """Return the stored password for `account`, or raise CredentialError. Never logs it."""
    b = backend()
    wait = _lookup_wait(account)
    try:
        if b == "keychain":
            proc = _run(["security", "find-generic-password",
                         "-a", account, "-s", SERVICE, "-w"], timeout=wait)
        elif b == "wincred":
            proc = _run(
                "[Windows.Security.Credentials.PasswordVault,Windows.Security.Credentials,"
                "ContentType=WindowsRuntime] > $null; "
                "$v = New-Object Windows.Security.Credentials.PasswordVault; "
                "$c = $v.Retrieve('%s','%s'); $c.RetrievePassword(); "
                "Write-Output $c.Password" % (SERVICE, account),
                "powershell", timeout=wait)
        else:
            proc = _run(["secret-tool", "lookup", "service", SERVICE, "account", account],
                        timeout=wait)
    except FileNotFoundError:
        raise CredentialError(
            "No credential store found for this platform (%s). Expected %s.\n"
            "Run:  python3 scripts/mailboxes.py --status" % (platform.system(), b))
    except subprocess.TimeoutExpired:
        _STATE["unresponsive"] = round(wait, 1)
        raise _timed_out(account, _STATE["unresponsive"])

    if proc.returncode != 0 or not proc.stdout.strip():
        _STATE["failures"][account] = "credential-missing"
        shell_kind, cmd, note = store_command(account)
        raise CredentialError(
            "No stored credential for %r (service %r).\n\nRun this yourself, in %s:\n\n%s\n\n%s"
            % (account, SERVICE, shell_kind, cmd, note))
    _STATE["failures"].pop(account, None)
    return proc.stdout.strip()


def has_credential(account):
    """True/False without raising, and WITHOUT holding the secret any longer than the check."""
    try:
        get_app_password(account)
        return True
    except CredentialError:
        return False
