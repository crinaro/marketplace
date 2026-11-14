#!/usr/bin/env python3
"""pages_check.py -- the report-only check of the public repo's GitHub Pages configuration, of the
protection on its `main`, and of who else can write to it (dev #835, design amendment 1 sections A2,
A3.4, A4.3; owner ruling items 1 and 2 and guard (c); named changes AM6 to AM11, AS4).
Python 3.9, standard library only.

    python3 pages_check.py [--repo DIR] [--json [--raw]]

It READS. It never writes, never turns anything on, never fixes anything: it tells the person, in plain
words, what still needs resolving and WHO resolves it. DNS records and the TXT domain verification stay
with the person (the ruling); the plugin checks them and names them.

EXIT CODES (OURS, following deploy.py):
  0  every item was checked and needs nothing (info and ok lines do not change this)
  3  amber: something to resolve, GitHub is still working, or something is NOT CHECKED
  1  the check could not run: no `gh` or logged out, site.json unreadable, no `publicRepo` (AM9: one
     line, "site.json has no publicRepo ..."), or `GET repos/<o>/<r>` failed
NOT CHECKED is never a pass: it is amber, and the line says why.

READ-ONLY BY CONSTRUCTION (AM10). The module starts a process in exactly ONE place, `_get`, which runs
`gh api --method GET -H "Accept: application/vnd.github+json" (--paginate | the headers flag) <path>` with
GH_PROMPT_DISABLED=1 and a 15 s timeout per call. `_refuse_writes` raises on any argv carrying `-X`,
`--method` with a value other than GET, `-f`, `-F`, `--field`, `--raw-field` or `--input` (`gh api` with
fields switches to POST on its own). tests/test_pages_check.py proves it three ways: an AST test that
this file has one subprocess call site and it is inside `_get`; every argv a fake `gh` recorded across
every fixture is a GET; and `_refuse_writes` refuses each write form. TIME: up to ~15 calls, each
bounded by 15 s, plus at most two 5 s sleeps for the DNS-health retry; the whole report is therefore
bounded by about 4 minutes in the worst case and a few seconds normally. It is interactive, and it is
NEVER run from a hook (S7: no `gh` in SessionStart).

READS, in order (each a GET): repos/{o}/{r}; .../pages; .../pages/health (only when a custom domain is
set; 202 means GitHub is still checking, retried twice 5 s apart through the `sleep` seam);
.../rules/branches/main; .../rulesets?includes_parents=false&targets=branch and .../rulesets/{id};
.../branches/main/protection (only when permissions.admin); the writers: .../collaborators, .../teams
(organisation repos), .../keys, and `user` (organisation repos, to leave the person out).

STATE PRECEDENCE (AM11; OURS). Each block below yields mutually exclusive lines; blocks are independent.
  1. Domain block, first match wins:
       cname set, domain null                  -> C11
       cname set, domain != cname              -> C10
       cname set == domain, cutover false      -> C8b  (Pages already serves it, and the next publish would
                                                  ship no CNAME file; this is NOT "planned" and NOT C8)
       cname set == domain, cutover true       -> no domain line; the checks below run
       cname null, domain null                 -> C7   (ok)
       cname null, domain set, cutover false   -> C8   (info: planned, nothing wrong yet)
       cname null, domain set, cutover true    -> C9
  2. When a cname is set (whatever block 1 said): C12 verification, then DNS health: 202 after the
     retries -> C13 only; else dns_resolves false -> C14 only (the other DNS flags mean nothing then);
     else C15 to C19 each independently. Then the certificate: exactly one of C20 / C21 / C22 / C23
     (an ABSENT certificate reads as C20 wait, never as ok; only `approved` is ok: an allowlist, S4).
  3. HTTPS: https_enforced true -> ok. False: certificate ok or no cname -> C24; certificate waiting or
     absent -> C25; certificate failed or unknown -> no HTTPS line (the certificate line dominates).
  4. Protection (C26 to C31) and writers (C32 to C35) as in their tables below.
  Pages source (C4, C5, C6) come first, in that order; C6 errored and "building" (a wait) are exclusive.

DNS / CNAME: `alt_domain` (the www alias on an apex site) is handled to one signal only: if its DNS does
not resolve, an info line says so (`C14w`). Every other alt_domain flag is NOT CHECKED; the summary says
"the www alias is checked only for DNS".

PROTECTION (AM6, AS4). `main` counts as protected when the rules in effect (from any ruleset at any
level) carry `deletion` and `non_fast_forward`, OR classic branch protection blocks force-push and
deletion (it is then reported as protecting main, C28). When rulesets are not available on the plan (a
plan-limit 403/422 on the rules read, recognised by rulesets.plan_unavailable) C26 is ONE line of kind
`info`, "not available on this plan; publish is unaffected": never a to-resolve line, because the person
cannot carry out its remedy.

WRITERS (guard c). Reported: any other collaborator with push, any team with push/maintain/admin, any
write deploy key. GitHub Apps installed with contents write are NOT CHECKED (U5), and the summary line
always says so.

--json OUTPUT (AM7 asks it be stated): ONE object on stdout, always exiting as above:
  {"schema": 1, "repo": "<o>/<r>", "exit": 0|3|1,
   "summary": {"ok": n, "info": n, "resolve": n, "wait": n, "not_checked": n},
   "items": [{"key": "C12", "state": "resolve", "line": "...", "who": "..."}, ...]}
`state` is one of ok, info, resolve, wait, not_checked. When the check cannot run the object is
{"schema": 1, "repo": ..., "exit": 1, "error": "<one line>", "summary": {}, "items": []}. With `--raw`
(only with --json) the object also carries "raw": {"<path>": {"status": n, "data": ...}} holding every
response as GitHub sent it. THAT is how the owner captures the real-response fixture AM7 says is owed
(the key set below is DOCUMENTED, but only a real response proves the keys exist): run it read-only
against the owner's own live HTTPS custom-domain site, synthesize every identifier, and commit the
result as the fixture shape. A raw dump carries real logins and domains: never commit one unsynthesized.

DOCUMENTED KEY SET (AM7). Every string key this module (and rulesets.py) reads from a GitHub response
must be in DOCUMENTED_KEYS below, which cites the REST pages (PA1, PA2, PA5, PA7). tests/test_pages_check
walks both files with `ast` and fails on a key that is not there, so a misnamed key cannot match itself
across a hand-written fixture and a hand-written reader. Keys in `_FROM_MEMORY` were not re-checked against a fetched
page and are confirmed by the first real response.
"""
import argparse
import collections
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import platform_check  # noqa: E402
import rulesets  # noqa: E402
import siteconfig  # noqa: E402

EXIT_OK, EXIT_RED, EXIT_AMBER = 0, 1, 3
GET_TIMEOUT = 15
HEALTH_RETRIES = 2          # after the first 202
HEALTH_RETRY_SECONDS = 5

# ---------------------------------------------------------------- the documented key set (AM7)

DOC_URLS = {
    "PA1": "https://docs.github.com/en/rest/pages/pages",
    "PA2": "https://docs.github.com/en/rest/pages/pages",
    "PA5": "https://docs.github.com/en/rest/repos/rules",
    "PA7": "https://docs.github.com/en/rest/collaborators/collaborators",
    "repos": "https://docs.github.com/en/rest/repos/repos",
    "branch protection": "https://docs.github.com/en/rest/branches/branch-protection",
    "repo teams": "https://docs.github.com/en/rest/repos/repos#list-repository-teams",
    "deploy keys": "https://docs.github.com/en/rest/deploy-keys/deploy-keys",
    "users": "https://docs.github.com/en/rest/users",
}

ENDPOINT_KEYS = {
    "GET repos/{o}/{r} (repos)": ("full_name", "visibility", "archived", "owner", "login", "type",
                                  "permissions", "admin", "push"),
    "GET .../pages (PA1)": ("status", "cname", "protected_domain_state", "pending_domain_unverified_at",
                            "build_type", "source", "branch", "path", "https_enforced",
                            "https_certificate", "state", "description"),
    "GET .../pages/health (PA2; domain and alt_domain share one key set)": (
        "domain", "alt_domain", "dns_resolves", "is_proxied", "is_cloudflare_ip", "is_apex_domain",
        "is_pointed_to_github_pages_ip", "is_non_github_pages_ip_present",
        "is_cname_to_github_user_domain", "caa_error", "reason"),
    "GET .../rules/branches/{b} (PA5)": ("type", "ruleset_id", "ruleset_source", "parameters"),
    "GET .../rulesets, .../rulesets/{id} (PA5)": (
        "id", "name", "target", "enforcement", "bypass_actors", "actor_type", "actor_id", "bypass_mode",
        "conditions", "ref_name", "include", "exclude", "rules"),  # retired-terms: ok (a GitHub / gh key, not the gmail-multi registry)
    "GET .../branches/{b}/protection (branch protection)": (
        "allow_force_pushes", "allow_deletions", "enabled", "required_pull_request_reviews",
        "required_status_checks", "required_signatures", "restrictions", "lock_branch"),
    "GET .../collaborators (PA7)": ("login", "role_name"),
    "GET .../teams (repo teams)": ("slug", "permission"),
    "GET .../keys (deploy keys)": ("title", "read_only"),
    "GET user (users)": ("login",),
    "error body (GitHub's standard)": ("message",),
}
DOCUMENTED_KEYS = frozenset(k for keys in ENDPOINT_KEYS.values() for k in keys)

# Keys this session did NOT re-check against the fetched page (the PA1/PA2 keys were: the Pages and
# health pages were fetched 2026-11-13 and every key above for them appears there). They come from the
# amendment and the author's reading of the REST docs; the first real response confirms them (AM7).
_FROM_MEMORY = frozenset({"role_name", "ruleset_source", "lock_branch", "restrictions", "read_only"})

# ---------------------------------------------------------------- one subprocess, GET only (AM10)

WRITE_FLAGS = ("-X", "-f", "-F", "--field", "--raw-field", "--input")
_PATH_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_./~:{}%=&?,+-]*\Z")
_HTTP_RE = re.compile(r"HTTP[/ ]\S*\s+(\d{3})")
_ERR_STATUS_RE = re.compile(r"\(HTTP (\d{3})\)")

Resp = collections.namedtuple("Resp", "status data message")
Item = collections.namedtuple("Item", "key state line who")


class GhError(Exception):
    """`gh` is missing, logged out, or did not answer: one call could not be made."""


class PagesCheckError(Exception):
    """The check cannot run at all (exit 1). The message is one line."""


def build_argv(path, paginate=False):
    if not isinstance(path, str) or not _PATH_RE.match(path):
        raise ValueError("refusing an api path that is not a plain path: %r" % (path,))
    argv = ["gh", "api", "--method", "GET", "-H", "Accept: application/vnd.github+json",
            "--paginate" if paginate else "--include", path]  # retired-terms: ok (a GitHub / gh key, not the gmail-multi registry)
    _refuse_writes(argv)
    return argv


def _refuse_writes(argv):
    """Raise ValueError on any argument list that could send a write (AM10)."""
    toks = list(argv)
    for i, t in enumerate(toks):
        if not isinstance(t, str) or not t.startswith("-"):
            continue
        if t == "--method" or t.startswith("--method="):
            val = t.split("=", 1)[1] if "=" in t else (toks[i + 1] if i + 1 < len(toks) else "")
            if val.upper() != "GET":
                raise ValueError("pages_check is read-only: refusing --method %s" % val)
        elif t.startswith("-X") or t.startswith("-f") or t.startswith("-F") or t in WRITE_FLAGS \
                or t.startswith("--field") or t.startswith("--raw-field") or t.startswith("--input"):
            raise ValueError("pages_check is read-only: refusing %s" % t)


def _parse_docs(text):
    """Concatenated JSON documents (what `gh api --paginate` prints); lists are joined."""
    dec, i, out = json.JSONDecoder(), 0, []
    text = text.strip()
    while i < len(text):
        obj, j = dec.raw_decode(text, i)
        out.append(obj)
        while j < len(text) and text[j].isspace():
            j += 1
        i = j
    if not out:
        return None
    if all(isinstance(o, list) for o in out):
        return [x for o in out for x in o]
    return out[0] if len(out) == 1 else out


def _get(path, paginate=False):
    """The ONLY place this module starts a process. Returns Resp(status, data, message); raises GhError
    when `gh` is missing, logged out, times out, or says something this module cannot read."""
    argv = build_argv(path, paginate)
    env = dict(os.environ)
    env["GH_PROMPT_DISABLED"] = "1"
    try:
        p = subprocess.run(argv, env=env, timeout=GET_TIMEOUT, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)
    except FileNotFoundError:
        raise GhError("gh is not installed")
    except subprocess.TimeoutExpired:
        raise GhError("gh did not answer within %d s" % GET_TIMEOUT)
    except OSError as e:
        raise GhError("could not run gh (%s)" % e)
    out = p.stdout.decode("utf-8", "replace")
    err = p.stderr.decode("utf-8", "replace").strip()
    status, body = None, out
    if not paginate:
        m = re.match(r"HTTP/\S+\s+(\d{3})", out)
        if m:
            status = int(m.group(1))
            parts = re.split(r"\r?\n\r?\n", out, maxsplit=1)
            body = parts[1] if len(parts) > 1 else ""
    try:
        data = _parse_docs(body) if body.strip() else None
    except ValueError:
        data = None
    if status is None:
        if p.returncode == 0:
            status = 200
        else:
            m = _ERR_STATUS_RE.search(err) or _HTTP_RE.search(err)
            if m:
                status = int(m.group(1))
            elif "gh auth login" in err or "not logged" in err.lower() or "authentication" in err.lower():
                raise GhError("gh is not logged in")
            else:
                raise GhError(err.splitlines()[-1] if err else "gh exited %d" % p.returncode)
    message = data.get("message") if isinstance(data, dict) and isinstance(data.get("message"), str) else None
    if message is None and p.returncode != 0 and err:
        message = err.splitlines()[-1]
    return Resp(status, data, message)


# ---------------------------------------------------------------- the check

APEX_A = ("185.199.108.153", "185.199.109.153", "185.199.110.153", "185.199.111.153")
CERT_WAIT = frozenset({"new", "authorization_created", "authorization_pending", "authorized", "issued",
                       "uploaded"})
CERT_OK = frozenset({"approved"})
CERT_FAILED = frozenset({"errored", "bad_authz", "authorization_revoked", "destroy_pending",
                         "dns_changed"})
RULESETS_UNAVAILABLE_LINE = "Rulesets are not available on this plan; publish is unaffected."

YOU = "you"
YOU_DNS = "you, at your DNS provider"
YOU_SETTINGS = "you: the repo's Settings, then Pages"


def _dns_records(cname, owner, apex):
    if apex:
        return ("A records for %s (and AAAA records 2606:50c0:8000::153 to 2606:50c0:8003::153 for IPv6)"
                % ", ".join(APEX_A))
    return "a CNAME record pointing to %s.github.io (without the repo name)" % owner


def _is_apex(dom, cname):
    v = dom.get("is_apex_domain")
    if isinstance(v, bool):
        return v
    return cname.count(".") == 1


def check(public_repo, cfg, get=_get, sleep=time.sleep):
    """The whole report: [Item(key, state, line, who)], state in ok / info / resolve / wait /
    not_checked. `get(path, paginate=False) -> Resp` and `sleep(seconds)` are the test seams. Raises
    PagesCheckError when the check cannot run (no repo name, gh missing or logged out, the repo read
    failed)."""
    if not public_repo or not isinstance(public_repo, str) or public_repo.count("/") != 1:
        raise PagesCheckError("site.json has no publicRepo, so there is no public repo to check. "
                              "Set publicRepo (setup step 2) and run again.")
    owner = public_repo.split("/", 1)[0]
    base = "repos/%s" % public_repo
    items = []

    def add(key, state, line, who=""):
        items.append(Item(key, state, line, who))

    def rd(path, paginate=False):
        try:
            return get(path, paginate)
        except GhError as e:
            return Resp(None, None, str(e))

    # ---- read 1: the repo
    try:
        r1 = get(base)
    except GhError as e:
        raise PagesCheckError("cannot reach GitHub with gh (%s). Run /site-studio:setup's step 1." % e)
    if r1.status != 200 or not isinstance(r1.data, dict):
        raise PagesCheckError("cannot read %s on GitHub (%s)"
                              % (public_repo, r1.message or ("HTTP %s" % r1.status)))
    repo = r1.data
    owner_obj = repo.get("owner") if isinstance(repo.get("owner"), dict) else {}
    owner_login = owner_obj.get("login") or owner
    owner_is_org = owner_obj.get("type") == "Organization"
    perms = repo.get("permissions") if isinstance(repo.get("permissions"), dict) else {}
    is_admin = bool(perms.get("admin"))
    where = "the organization's" if owner_is_org else "your profile's"

    if repo.get("visibility") != "public":
        add("C1", "resolve", "%s is not public. site-studio publishes to a public repo, and Pages on a "
            "private repo needs a paid plan." % public_repo, "you: the repo's Settings, then General")
    if repo.get("archived"):
        add("C2", "resolve", "%s is archived, so nothing can be pushed to it." % public_repo,
            "you: unarchive it in Settings")

    # ---- read 2: Pages
    pages = None
    r2 = rd(base + "/pages")
    if r2.status == 404:
        add("C3", "resolve", "GitHub Pages is off for %s. Turn it on under Settings, then Pages, then "
            "'Deploy from a branch', branch main, folder / (root). For a new site, setup's first-publish "
            "already does this." % public_repo, "you, or setup on a new site")
    elif r2.status == 200 and isinstance(r2.data, dict):
        pages = r2.data
    else:
        add("C3", "not_checked", "NOT CHECKED: the Pages settings of %s (%s)."
            % (public_repo, r2.message or "no answer"), YOU)

    if pages is not None:
        _pages_items(pages, cfg, owner_login, where, base, rd, sleep, add)

    _protection_items(public_repo, base, is_admin, rd, add)
    _writer_items(public_repo, base, owner_login, owner_is_org, rd, add)
    return items


def _pages_items(pages, cfg, owner, where, base, rd, sleep, add):
    domain = getattr(cfg, "domain", None)
    cutover = bool(getattr(cfg, "cutover", False))
    preview = getattr(cfg, "previewUrl", None) or "its github.io address"
    cname = pages.get("cname") or None
    build_type = pages.get("build_type")
    src = pages.get("source") if isinstance(pages.get("source"), dict) else {}

    # -- source and build
    if build_type == "workflow":
        add("C4", "resolve", "Pages builds from a GitHub Actions workflow, so the files publish pushes are "
            "not what is served. Set the source to 'Deploy from a branch'.", YOU_SETTINGS)
    elif src.get("branch") != "main" or src.get("path") != "/":
        got = "%s%s" % (src.get("branch") or "no branch", src.get("path") or "")
        add("C5", "resolve", "Pages serves %s, but publish pushes to main at the root. Set the source to "
            "main, / (root)." % got, YOU_SETTINGS)
    status = pages.get("status")
    if status == "errored":
        add("C6", "resolve", "The last Pages build failed. Open the repo's Actions tab, run 'pages build "
            "and deployment', and read the error.", YOU)
    elif status == "building":
        add("C6w", "wait", "GitHub is still building the Pages site. Run this check again in a minute.",
            "GitHub (wait)")

    # -- the domain block: first match wins (see the docstring)
    same = bool(cname and domain and cname.lower() == domain.lower())
    if cname and not domain:
        add("C11", "resolve", "Pages has the custom domain %s, but site.json does not name it, so the next "
            "publish carries no CNAME file. Set domain in site.json, or remove the domain in Settings, "
            "then Pages." % cname, YOU)
    elif cname and not same:
        add("C10", "resolve", "Pages serves %s, but site.json says %s. Decide which one is right: change "
            "it in Settings, then Pages, or edit domain in site.json and publish." % (cname, domain), YOU)
    elif cname and same and not cutover:
        add("C8b", "resolve", "Pages already serves %s, but site.json has cutover false, so the next "
            "publish carries no CNAME file and Pages would stop serving the domain. Set cutover to true "
            "(setup step 5), or remove the domain in Settings, then Pages." % cname, YOU)
    elif not cname and not domain:
        add("C7", "ok", "No custom domain. The site is at %s." % preview, "")
    elif not cname and not cutover:
        add("C8", "info", "%s is planned and not switched over yet. Run setup step 5 when the DNS is ready."
            % domain, YOU)
    elif not cname:
        add("C9", "resolve", "The site's CNAME file names %s, but Pages has no custom domain set. In the "
            "repo's Settings, then Pages, then Custom domain, enter %s and save (saving writes a commit "
            "to main; the next publish replaces it with the build's own CNAME file). Whether the pushed "
            "CNAME file alone sets it is not yet known (U2)." % (domain, domain), YOU)

    cert_state_kind = None
    if cname:
        # -- verification
        pstate = pages.get("protected_domain_state")
        if pstate != "verified":
            since = pages.get("pending_domain_unverified_at")
            add("C12", "resolve", "%s is not verified for %s (GitHub says: %s%s). Add a DNS TXT record "
                "named _github-pages-challenge-%s on the domain you verify, with the value GitHub shows "
                "under %s Settings, then Pages, then Add a domain (it shows the exact name and value). "
                "Then press Verify there, not in the repo's settings. This stops anyone else publishing "
                "on the domain." % (cname, owner, pstate or "no state",
                                    ", unverified since %s" % since if since else "", owner, where),
                "you, at your DNS provider and in your account's Settings")
        # -- DNS health
        _health_items(cname, owner, base, rd, sleep, add)
        # -- certificate
        cert = pages.get("https_certificate") if isinstance(pages.get("https_certificate"), dict) else None
        cstate = cert.get("state") if cert else None
        if cstate in CERT_OK:
            cert_state_kind = "ok"
            add("C21", "ok", "Certificate ready.", "")
        elif cstate in CERT_WAIT or cert is None or cstate is None:
            cert_state_kind = "wait"
            add("C20", "wait", "GitHub is getting a certificate for %s (%s). This can take up to 24 hours."
                % (cname, cstate or "no state reported yet"), "GitHub (wait)")
        elif cstate in CERT_FAILED:
            cert_state_kind = "failed"
            add("C22", "resolve", "The certificate for %s failed (%s: %s). Fix the DNS lines above, then "
                "remove the custom domain in Settings, then Pages, and add it again."
                % (cname, cstate, cert.get("description") or "no description"), YOU)
        else:
            cert_state_kind = "unknown"
            add("C23", "resolve", "GitHub reports a certificate state this check does not know (%s). Look "
                "in Settings, then Pages." % cstate, YOU)

    # -- HTTPS
    if pages.get("https_enforced"):
        add("C24", "ok", "HTTPS is enforced.", "")
    elif not cname or cert_state_kind == "ok":
        add("C24", "resolve", "HTTPS is not enforced. Turn on 'Enforce HTTPS' in the repo's Settings, "
            "then Pages.", YOU)
    elif cert_state_kind == "wait":
        add("C25", "wait", "'Enforce HTTPS' becomes available when the certificate is ready.",
            "GitHub (wait)")


def _health_items(cname, owner, base, rd, sleep, add):
    r = None
    for attempt in range(HEALTH_RETRIES + 1):
        r = rd(base + "/pages/health")
        if r.status != 202:
            break
        if attempt < HEALTH_RETRIES:
            sleep(HEALTH_RETRY_SECONDS)
    if r.status == 202:
        add("C13", "wait", "GitHub is still checking the DNS for %s. Run this check again in a minute."
            % cname, "GitHub (wait)")
        return
    if r.status != 200 or not isinstance(r.data, dict):
        why = "needs admin access" if r.status in (403, 404) else (r.message or "no answer")
        add("C13n", "not_checked", "NOT CHECKED: the DNS health of %s (%s)." % (cname, why), YOU)
        return
    dom = r.data.get("domain")
    if not isinstance(dom, dict):
        add("C13n", "not_checked", "NOT CHECKED: GitHub's DNS health answer for %s was empty." % cname, YOU)
        return
    apex = _is_apex(dom, cname)
    resolves = dom.get("dns_resolves")
    if resolves is False:
        reason = dom.get("reason")
        add("C14", "resolve", "%s does not resolve yet%s. Add these DNS records at your DNS provider: %s."
            % (cname, " (GitHub says: %s)" % reason if isinstance(reason, str) and reason else "",
               _dns_records(cname, owner, apex)), YOU_DNS)
    elif resolves is True:
        if apex and dom.get("is_pointed_to_github_pages_ip") is False:
            add("C15", "resolve", "The apex %s must have A records for %s (and AAAA 2606:50c0:8000::153 to "
                "2606:50c0:8003::153 for IPv6)." % (cname, ", ".join(APEX_A)), YOU_DNS)
        if dom.get("is_non_github_pages_ip_present") is True:
            add("C16", "resolve", "%s also points at an address that is not GitHub's. Remove that extra "
                "record, or GitHub cannot issue the certificate." % cname, YOU_DNS)
        if (not apex and dom.get("is_cname_to_github_user_domain") is False
                and dom.get("is_pointed_to_github_pages_ip") is not True):
            add("C17", "resolve", "%s must be a CNAME record pointing to %s.github.io (without the repo "
                "name)." % (cname, owner), YOU_DNS)
        if dom.get("is_proxied") is True or dom.get("is_cloudflare_ip") is True:
            add("C18", "resolve", "%s is behind a proxy or CDN, which stops GitHub issuing the "
                "certificate. Turn the proxy off for this record." % cname, YOU_DNS)
        if dom.get("caa_error"):
            add("C19", "resolve", "A CAA record on %s blocks the certificate (%s). Allow letsencrypt.org, "
                "or remove the CAA record." % (cname, dom.get("caa_error")), YOU_DNS)
    else:
        add("C13n", "not_checked", "NOT CHECKED: GitHub's DNS health answer for %s did not say whether it "
            "resolves." % cname, YOU)
    alt = r.data.get("alt_domain")
    if isinstance(alt, dict) and alt.get("dns_resolves") is False:
        add("C14w", "info", "The www alias of %s does not resolve, so www visitors will not reach the "
            "site. Add a CNAME record for www pointing to %s.github.io, or ignore this if you do not use "
            "www." % (cname, owner), YOU_DNS)


def _protection_items(repo, base, is_admin, rd, add):
    rules, plan = None, False
    names = {}
    r4 = rd(base + "/rules/branches/main", True)
    if r4.status == 200 and isinstance(r4.data, (list, type(None))):
        rules = r4.data or []
    elif rulesets.plan_unavailable(r4.status, r4.message):
        plan, rules = True, []
    else:
        add("C31", "not_checked", "NOT CHECKED: the rules in effect on main (%s)."
            % (r4.message or "needs access"), YOU)

    r5 = rd(base + "/rulesets?includes_parents=false&targets=branch")
    listing, detail = None, None
    if r5.status == 200 and isinstance(r5.data, list):
        listing = [x for x in r5.data if isinstance(x, dict)]
        names = dict((x.get("id"), x.get("name")) for x in listing)
    elif rulesets.plan_unavailable(r5.status, r5.message):
        plan = True
    else:
        add("C31", "not_checked", "NOT CHECKED: the rulesets of %s (%s)." % (repo, r5.message or "needs access"), YOU)
    named = [x for x in (listing or []) if x.get("name") == rulesets.RULESET_NAME]
    if len(named) == 1:
        d = rd(base + "/rulesets/%s" % named[0].get("id"))
        if d.status == 200 and isinstance(d.data, dict):
            detail = d.data
        else:
            add("C31", "not_checked", "NOT CHECKED: the site-studio ruleset's settings (%s)."
                % (d.message or "needs access"), YOU)

    classic = None
    if is_admin:
        r6 = rd(base + "/branches/main/protection")
        if r6.status == 200 and isinstance(r6.data, dict):
            classic = r6.data
        elif r6.status == 404:
            classic = None
        elif not rulesets.plan_unavailable(r6.status, r6.message):
            add("C31", "not_checked", "NOT CHECKED: classic branch protection (%s)."
                % (r6.message or "needs access"), YOU)
    else:
        add("C31", "not_checked", "NOT CHECKED: classic branch protection (needs admin access).", YOU)

    if rules is not None:
        gaps = rulesets.protection_gaps(rules, classic)
        if gaps and plan and not rulesets.classic_blocks(classic):
            add("C26", "info", RULESETS_UNAVAILABLE_LINE, "")
        elif gaps:
            add("C26", "resolve", "main on %s is not protected against %s. Run setup's protect step "
                "(repos.py protect, which asks you first), or add a ruleset in Settings, then Rules."
                % (repo, " or ".join(gaps)), "site-studio, with your yes; or you")
        else:
            srcs = ["%s (%s)" % (n, s) if s else n for n, s in rulesets.sources(rules, names)]
            if rulesets.classic_blocks(classic) >= {"force-push", "deletion"} and not srcs:
                srcs = ["classic branch protection"]
            add("C28", "ok", "main is protected by %s." % ", ".join(srcs or ["rules in effect"]), "")
        for t, n in rulesets.refusing_rules(rules, names):
            add("C29", "resolve", "A rule on main can refuse publish's push: %s (%s). Publish pushes "
                "straight to main, so remove that rule in Settings, then Rules, or publishing will fail."
                % (t, n), YOU)
    if classic is not None:
        bad = rulesets.classic_refusing(classic)
        if bad:
            add("C30", "resolve", "Classic branch protection on main requires %s, which refuses publish's "
                "push. Remove it in Settings, then Branches." % ", ".join(bad), YOU)
    if len(named) > 1:
        add("C27", "resolve", "There are %d rulesets named '%s' (ids %s). Keep one and remove the others in "
            "Settings, then Rules." % (len(named), rulesets.RULESET_NAME,
                                       ", ".join(str(x.get("id")) for x in named)), YOU)
    elif detail is not None:
        diffs = rulesets.differences(detail)
        if diffs:
            add("C27", "resolve", "The site-studio ruleset on %s has been changed: %s. Run repos.py protect "
                "--fix to restore it (it asks you first)." % (repo, "; ".join(diffs)),
                "site-studio, with your yes")


def _writer_items(repo, base, owner_login, owner_is_org, rd, add):
    refused = []
    me = None
    if owner_is_org:
        u = rd("user")
        if u.status == 200 and isinstance(u.data, dict) and u.data.get("login"):
            me = u.data["login"]
        else:
            refused.append("which account is you")
    person = me if owner_is_org else owner_login
    seen = set()
    if not (owner_is_org and me is None):
        c = rd(base + "/collaborators?affiliation=all&per_page=100", True)
        if c.status == 200 and isinstance(c.data, list):
            for x in c.data:
                if not isinstance(x, dict) or not x.get("login"):
                    continue
                p = x.get("permissions") if isinstance(x.get("permissions"), dict) else {}
                if p.get("push") is True and x["login"].lower() != person.lower() and x["login"] not in seen:
                    seen.add(x["login"])
                    add("C32", "resolve", "%s can also push to %s (%s). If you did not mean that, remove "
                        "them in Settings, then Collaborators and teams."
                        % (x["login"], repo, x.get("role_name") or "write"), YOU)
        else:
            refused.append("collaborators")
    if owner_is_org:
        t = rd(base + "/teams", True)
        if t.status == 200 and isinstance(t.data, list):
            for x in t.data:
                if isinstance(x, dict) and x.get("permission") in ("push", "maintain", "admin"):
                    add("C33", "resolve", "The team %s can push to %s (%s). If you did not mean that, remove "
                        "it in Settings, then Collaborators and teams." % (x.get("slug"), repo, x["permission"]), YOU)
        else:
            refused.append("teams")
    k = rd(base + "/keys", True)
    if k.status == 200 and isinstance(k.data, list):
        for x in k.data:
            if isinstance(x, dict) and x.get("read_only") is False:
                add("C34", "resolve", "The deploy key '%s' can push to %s. If you did not mean that, remove "
                    "it in Settings, then Deploy keys." % (x.get("title") or "untitled", repo), YOU)
    else:
        refused.append("deploy keys")
    if refused:
        add("C35", "not_checked", "NOT CHECKED: who else can push (needs write access; could not read: %s)."
            % ", ".join(refused), YOU)


# ---------------------------------------------------------------- reporting

STATES = ("ok", "info", "resolve", "wait", "not_checked")
LABEL = {"info": "info", "resolve": "to resolve", "wait": "waiting", "not_checked": "not checked"}
APPS_NOTE = ("Apps installed on the account are not checked, and the www alias is checked only for DNS.")


def _n(items, state):
    return sum(1 for i in items if i.state == state)


def counts(items):
    return dict((st, _n(items, st)) for st in STATES)


def exit_code(items):
    amber = _n(items, "resolve") + _n(items, "wait") + _n(items, "not_checked")
    return EXIT_AMBER if amber else EXIT_OK


def summary_line(public_repo, items):
    return ("pages: %d to resolve, %d waiting, %d not checked on %s. %s"
            % (_n(items, "resolve"), _n(items, "wait"), _n(items, "not_checked"), public_repo, APPS_NOTE))


def as_json(public_repo, items, raw=None, error=None):
    obj = {"schema": 1, "repo": public_repo, "exit": EXIT_RED if error else exit_code(items),
           "summary": {} if error else counts(items),
           "items": [dict(i._asdict()) for i in items]}
    if error:
        obj["error"] = error
    if raw is not None:
        obj["raw"] = raw
    return obj


def main(argv=None):
    rc = platform_check.windows_refusal_rc("pages_check.py")
    if rc is not None:
        return rc
    ap = argparse.ArgumentParser(prog="pages_check.py", allow_abbrev=False,
                                 description="Report the public repo's Pages configuration (read-only; dev #835).")
    ap.add_argument("--repo", default=".", help="the dev repo (default: the current folder)")
    ap.add_argument("--json", action="store_true", help="print one JSON object instead of lines")
    ap.add_argument("--raw", action="store_true", help="with --json: include every raw GitHub response")
    args = ap.parse_args(argv)
    if args.raw and not args.json:
        ap.error("--raw needs --json")
    public_repo = None
    raw = {} if args.raw else None

    def fail(msg):
        if args.json:
            print(json.dumps(as_json(public_repo, [], error=msg), indent=2))
        else:
            print(msg)
        return EXIT_RED

    try:
        cfg = siteconfig.load(os.path.join(args.repo, "site", "site.json"))
    except siteconfig.SiteConfigError as e:
        return fail("NOT CHECKED: %s" % e)
    public_repo = cfg.publicRepo

    def recording_get(path, paginate=False):
        r = _get(path, paginate)
        if raw is not None:
            raw[path] = {"status": r.status, "data": r.data}
        return r

    try:
        items = check(public_repo, cfg, get=recording_get)
    except PagesCheckError as e:
        return fail(str(e) if str(e).startswith("site.json") else "NOT CHECKED: %s" % e)
    if args.json:
        print(json.dumps(as_json(public_repo, items, raw), indent=2))
    else:
        for it in items:
            if it.state == "ok":
                continue
            print("[%s] %s%s" % (LABEL[it.state], it.line, " (Who: %s)" % it.who if it.who else ""))
        print(summary_line(public_repo, items))
    return exit_code(items)


if __name__ == "__main__":
    sys.exit(main())
