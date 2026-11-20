"""fetch_sandbox: the admission check of the posting fetch (design-browser-fallback.md 6.2; OURS).

Capability module of `posting_fetch.py`, which passes its own HOST and its two path seams in.

A sandboxed command's connection to a host its settings do not list is decided by the permission mode: a harness prompt that shows
no terms (and that nobody answers on a scheduled run), an allow, or a refusal. A script cannot read the mode, so it never lets the
proxy decide: BEFORE any GET it reads the settings files the session actually loads and sends nothing unless the host is shown to
be allowed there. Each machine runs the check every run, so a rule saved on one machine never decides for another.

UNDETERMINED (probe P-S2): server-managed and MDM-profile settings are not files a script can read, so a host they exclude passes
this check, and in manual mode the proxy may still prompt."""

import fnmatch
import json
import os
import re
import sys

PROXY_VARS = ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy")   # the list `feed_poll.py` reads for the same question


def remedy(host):
    """The line that says how to allow `host`, appended to a `sandbox-unconfirmed` answer."""
    return ("allow it: list %s in ~/.claude/settings.json sandbox.network.allowedDomains, or run from the profile folder "
            "after `posting_fetch.py --set on`" % host)


def managed_paths(managed_settings=None):
    """The managed-settings paths: `managed_settings` (a seam, a list) when given, else the OS's documented one."""
    if managed_settings is not None:
        return list(managed_settings)
    if sys.platform == "darwin":
        return ["/Library/Application Support/ClaudeCode/managed-settings.json"]
    if sys.platform.startswith("win"):
        return [r"C:\Program Files\ClaudeCode\managed-settings.json"]
    return ["/etc/claude-code/managed-settings.json"]


def user_settings_path(user_settings=None):
    return user_settings if user_settings is not None else os.path.join(os.path.expanduser("~"), ".claude", "settings.json")


def load_settings(path):
    """`(object, None)`, `(None, None)` for a file that does not exist, or `(None, why)` for one that exists and cannot be used."""
    try:
        with open(path, encoding="utf-8") as fh:
            obj = json.load(fh)
    except FileNotFoundError:
        return None, None
    except (OSError, ValueError) as e:
        return None, "%s cannot be read (%s)" % (path, e)
    if not isinstance(obj, dict):
        return None, "%s is not a JSON object" % path
    return obj, None


def _str_list(v):
    return [x.strip().lower() for x in v if isinstance(x, str)] if isinstance(v, list) else []


def _sandbox_node(obj):
    sb = obj.get("sandbox")
    return sb if isinstance(sb, dict) else {}


def _deny_matches(entry, host):
    """True when one deny entry (a `deniedDomains` item, or the domain of a `WebFetch(domain:...)` deny rule) denies `host`. FAIL CLOSED:
    an entry denies the host it names and every subdomain of it, so `linkedin.com`, `.linkedin.com` and `*.linkedin.com` all deny
    `www.linkedin.com` (and `*.x` denies `x` too); any other `*` in an entry is a glob over the host or one of its parent domains."""
    entry = entry.strip().lower().rstrip(".")
    if entry.startswith("*."):
        entry = entry[2:]
    elif entry.startswith("."):
        entry = entry[1:]
    if not entry:
        return False
    labels = host.strip().lower().rstrip(".").split(".")
    return any(fnmatch.fnmatchcase(".".join(labels[i:]), entry) for i in range(len(labels)))


def _denied(obj_net, perms, host):
    if any(_deny_matches(e, host) for e in _str_list(obj_net.get("deniedDomains"))):
        return True
    for rule in _str_list(perms.get("deny")):
        m = re.match(r"^webfetch\(domain:(.*)\)$", rule)
        if m and _deny_matches(m.group(1), host):
            return True
    return False


def lists_host(obj, host):
    """`(listed, denied)` for `host` in one settings object. LISTED is an exact match: `sandbox.network.allowedDomains` or a
    `WebFetch(domain:...)` allow rule names the host itself (an allow written as a wildcard or a parent domain does not list it:
    that fails closed). DENIED is not exact (dev 858, verify finding L1): `sandbox.network.deniedDomains` or a `WebFetch(domain:...)`
    deny rule denies the host when it names the host, a parent domain of it, or a wildcard that covers it (`_deny_matches`)."""
    net = _sandbox_node(obj).get("network")
    net = net if isinstance(net, dict) else {}
    perms = obj.get("permissions") if isinstance(obj.get("permissions"), dict) else {}
    rule = ("WebFetch(domain:%s)" % host).lower()
    listed = host in _str_list(net.get("allowedDomains")) or rule in _str_list(perms.get("allow"))
    return listed, _denied(net, perms, host)


def _strict_allowlist(obj):
    """True when `strictAllowlist` is set (anywhere a settings author would put it): at the top, under `sandbox`, or under
    `sandbox.network`."""
    sb = _sandbox_node(obj)
    net = sb.get("network") if isinstance(sb.get("network"), dict) else {}
    return any(bool(n.get("strictAllowlist")) for n in (obj, sb, net))


def project_dir():
    """The directory this process's session treats as its project (`CLAUDE_PROJECT_DIR`, else the working directory)."""
    return os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


def _counted_files(root, user_settings, managed_settings):
    """`[(label, path, kind)]`: the settings files this session loads that count for the profile at `root`."""
    counted = [("the user's settings", user_settings_path(user_settings), "user")]
    try:
        same = os.path.realpath(project_dir()) == os.path.realpath(root)
    except (OSError, ValueError):
        same = False
    if same:
        for name in ("settings.json", "settings.local.json"):
            counted.append(("the profile project's %s" % name, os.path.join(root, ".claude", name), "project"))
    managed = next((p for p in managed_paths(managed_settings) if os.path.exists(p)), None)
    if managed:
        counted.append(("the managed settings", managed, "managed"))
    return counted


def admitted(root, host, user_settings=None, managed_settings=None):
    """`(bool, why)`: may a GET to `host` go out from this process? Admits only when the sandbox is off (none of PROXY_VARS is set)
    or the host is listed in a file the session loads, and nothing below denies it (design 6.2):

      * the user's `~/.claude/settings.json` is always counted;
      * the profile project's `.claude/settings.json` and `.claude/settings.local.json` are counted ONLY when the process's project
        directory is the profile root (compared as real paths): a task launched from anywhere else never loaded them;
      * a counted file that exists and does not parse, or any counted file that denies the host, is a denial;
      * a user `strictAllowlist` makes the project files count as not listed;
      * a managed-settings file that sets a `sandbox` key is the only allowlist that counts (and the sandbox-off shortcut does not
        apply: that file says the sandbox is its own to configure).

    `user_settings` and `managed_settings` are the seams a test points at scratch files. Fail closed: anything not shown is
    `(False, <why>)`."""
    objs = []
    for label, path, kind in _counted_files(root, user_settings, managed_settings):
        obj, err = load_settings(path)
        if err:
            return False, "a settings file this session loads cannot be used: %s" % err
        if obj is not None:
            objs.append((label, kind, obj))
    for label, kind, obj in objs:
        if lists_host(obj, host)[1]:
            return False, "%s deny %s" % (label, host)
    managed_objs = [o for (_l, k, o) in objs if k == "managed"]
    if managed_objs and "sandbox" in managed_objs[0]:
        return (True, "listed in the managed settings") if lists_host(managed_objs[0], host)[0] else (
            False, "the managed settings set a sandbox and do not list %s" % host)
    if not any(os.environ.get(v) for v in PROXY_VARS):
        return True, "the sandbox is off (no proxy variable is set)"
    strict = any(_strict_allowlist(o) for (_l, k, o) in objs if k == "user")
    for label, kind, obj in objs:
        if kind == "project" and strict:
            continue
        if lists_host(obj, host)[0]:
            return True, "listed in %s" % label
    return False, "the command sandbox is on and no settings file this session loads lists %s" % host
