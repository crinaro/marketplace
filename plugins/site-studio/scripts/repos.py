#!/usr/bin/env python3
"""repos.py -- create the dev and public repos, scaffold the starter site, make the first
publish, and protect the public repo's `main` (dev #835, design 6.2 steps 3 and 4; named change S8;
design amendment 1 sections A3 and A4.2, named changes AM1, AM4, AM6, AM9, AS4).
Python 3.9, standard library only.

    repos.py create        --owner O --name N [--dest DIR] [--person-name P] [--site-title T]
    repos.py scaffold      --dest DIR --owner O --name N [--person-name P] [--site-title T]
    repos.py first-publish [--repo DIR]
    repos.py protect       [--repo DIR] [--fix] [--classic]

`create` runs `gh repo create <O>/<N>-dev --private` and `gh repo create <O>/<N> --public`,
scaffolds the dev repo from `templates/starter/` into DIR (default `./<N>-dev`), makes ONE commit
("site-studio: starter site"), and pushes it. The starter is synthesized: no real content, one
placeholder page of each kind. `site/site.json` is written through siteconfig.py (the only writer),
never from a template, so its marker is the canonical one. The template folder names a dotfile
with a `dot-` prefix (`dot-gitignore`, `dot-claude/`) so the plugin's own repo does not act on it.
`@@NAME@@ @@SITE_TITLE@@ @@PUBLIC_REPO@@ @@OWNER@@` are replaced in every file.

`first-publish` is the ONE publish that has no privacy review, because the content is the
synthesized starter. It therefore refuses unless ALL of: the dev repo has exactly one commit and it
is the scaffold commit, the tree is clean, HEAD is on origin/main, and the public repo has NO
`main` yet (it only ever fills an empty repo; every later publish is `deploy.py` with a review).
It then builds, runs the gates, stages and verifies the commit tree exactly as `deploy.py` does (it
calls the same functions), and runs guard (b) before the push: `deploy.verify_public_target` (V1 the
dev repo is not the public repo, V2 the public repo is what it should be and this login can push, V3
the URL git will push to is the pinned one, V4 the public `main` is still absent). Only then does it
push, through `deploy.push_and_verify` and so through `deploy.push_main`, the one function that
pushes: a plain fast-forward or new-ref refspec, never a force, never a deletion. It checks the remote
head, re-reads the public repo and compares digests, and enables Pages: `POST /repos/{o}/{r}/pages`
with `build_type: legacy`, branch `main`, path `/`, then reads `builds/latest`. A gate that cannot run
(check_site.py absent) refuses: NOT CHECKED is never a pass. The target is `deploy.public_target(cfg)`
and nothing else; a null `publicRepo` refuses (exit 1) before any clone or `gh` call (AM9).

THE PUT WAS DROPPED (design amendment 1 section A2.4). The earlier design enabled Pages and then
`PUT`-ed the custom domain and HTTPS settings. That write is gone: the domain, the DNS records, the TXT
verification and Enforce HTTPS are the person's, and `pages_check.py` reads and names what is still
open. The `POST /pages` call that turns Pages on is unchanged.

NO CLI FLAG REDIRECTS A PUSH (AM1). `--remote-base` was removed from BOTH `create` and `first-publish`:
a flag that points a push somewhere else is exactly what guard (b) forbids. `first_publish(...,
public_url=None, dev_origin=None)` and `create(..., remote_base=DEFAULT_BASE)` keep a keyword for tests
only; `main()` never sets one, and test_repos.Cli asserts that no subparser accepts the flag. `create`'s
own push is of the NEW private DEV repo to the origin it set one line before: it never touches
`publicRepo`, so it is outside guard (b) and is allow-listed by name in test_deploy.NoForce.

`protect` (AM6, AS4; owner ruling (a) of 2026-11-13) puts the ruleset `rulesets.PROTECT_MAIN` on the
public repo's `main`: no force-push, no deletion, nothing else (never a pull-request or status-check
rule: publish pushes straight to `main`). It is idempotent: it reads the repo's rulesets and writes
only when the ruleset is absent (POST) or differs and `--fix` was given (PUT). Exit codes: 0 in place
or added; 3 differences found, without `--fix`; 5 rulesets are refused on this plan (a plan-limit
answer, recognised by `rulesets.plan_unavailable`; one line, which offers classic branch protection);
1 any other refusal. `--classic` applies `rulesets.CLASSIC_MAIN` (force-push and deletion blocked, no
review, no status check, no restricted pusher) through `PUT branches/main/protection`, but only when no
classic protection that falls short exists, because that PUT REPLACES the whole protection. Whether
admins are bound by either is UNDETERMINED (U7) until P-10. A null `publicRepo` refuses (AM9), and so does
a cloud session (`CLAUDE_CODE_REMOTE=true`), as `deploy.py` does.

The starter's CLAUDE.md carries the pointer line named change S8 requires (test_repos pins it
word for word), and its .gitignore carries `.claude/worktrees/` (S2).
"""
import argparse
import collections
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import build  # noqa: E402
import deploy  # noqa: E402
import rulesets  # noqa: E402
import siteconfig  # noqa: E402
import platform_check  # noqa: E402

PLUGIN = os.path.dirname(HERE)
STARTER = os.path.join(PLUGIN, "templates", "starter")
SCAFFOLD_SUBJECT = "site-studio: starter site"
DEFAULT_BASE = "https://github.com"
_OWNER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


class RepoError(Exception):
    """A refusal; the message is one line."""


def gh(args, input=None, timeout=120, gh_cmd="gh"):
    exe = shutil.which(gh_cmd) if os.sep not in gh_cmd else gh_cmd
    if not exe:
        raise RepoError("gh is not installed: run /site-studio:setup first")
    try:
        p = subprocess.run([exe] + list(args), input=input, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=timeout, env=dict(os.environ, GH_PROMPT_DISABLED="1"))
    except subprocess.TimeoutExpired:
        raise RepoError("gh %s timed out after %ds" % (args[0], timeout))
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


def check_names(owner, name):
    if not _OWNER.match(owner or ""):
        raise RepoError("the owner must be a GitHub user or organization name")
    if not _NAME.match(name or "") or name.startswith(".") or name.endswith(".git"):
        raise RepoError("the site name must be letters, digits, '.', '_' or '-'")


def site_urls(owner, name):
    """(owner/name of the public repo, the address Pages will serve it at). A repo named
    <owner>.github.io is served at the root; any other repo at /<name>/ until a domain is set."""
    public = "%s/%s" % (owner, name)
    if name.lower() == ("%s.github.io" % owner).lower():
        return public, "https://%s" % name.lower()
    return public, "https://%s.github.io/%s" % (owner.lower(), name)


def _dest_name(rel):
    return "/".join("." + p[4:] if p.startswith("dot-") else p for p in rel.split("/"))


def scaffold(dest, owner, name, person_name=None, site_title=None):
    """Write the starter into `dest` (absent or empty). Returns the sorted relative paths written."""
    check_names(owner, name)
    if os.path.exists(dest) and (not os.path.isdir(dest) or os.listdir(dest)):
        raise RepoError("%s already exists and is not empty" % dest)
    person_name = (person_name or owner).strip()
    site_title = (site_title or person_name).strip()
    public, preview = site_urls(owner, name)
    subs = {"@@NAME@@": person_name, "@@SITE_TITLE@@": site_title, "@@PUBLIC_REPO@@": public,
            "@@OWNER@@": owner}
    written = []
    for d, _dirs, files in os.walk(STARTER):
        for f in files:
            src = os.path.join(d, f)
            rel = _dest_name(os.path.relpath(src, STARTER).replace(os.sep, "/"))
            with open(src, "r", encoding="utf-8", newline="") as fh:
                text = fh.read()
            for k, v in subs.items():
                text = text.replace(k, v)
            out = os.path.join(dest, *rel.split("/"))
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
            written.append(rel)
    siteconfig.write(os.path.join(dest, "site", "site.json"), {
        "schema": 1, "engine": "site-studio", "name": person_name, "siteTitle": site_title,
        "publicRepo": public, "previewUrl": preview, "domain": None, "cutover": False,
        "publicEmails": [], "privateTerms": [],
        "work": {"label": "Projects", "description": "Selected projects by %s." % person_name},
        "redirects": {}, "resume": None, "budgets": {}})
    written.append("site/site.json")
    return sorted(written)


def create(owner, name, dest=None, person_name=None, site_title=None, remote_base=DEFAULT_BASE,
           gh_cmd="gh", out=None):
    out = out or sys.stdout
    check_names(owner, name)
    dest = os.path.abspath(dest or "%s-dev" % name)
    if os.path.exists(dest) and (not os.path.isdir(dest) or os.listdir(dest)):
        raise RepoError("%s already exists and is not empty" % dest)
    dev_repo = "%s/%s-dev" % (owner, name)
    public_repo, preview = site_urls(owner, name)
    rc, _o, err = gh(["repo", "create", dev_repo, "--private"], gh_cmd=gh_cmd)
    if rc != 0:
        raise RepoError("could not create %s: %s" % (dev_repo, (err.strip().splitlines() or ["gh failed"])[-1]))
    print("created %s (private)" % dev_repo, file=out)
    rc, _o, err = gh(["repo", "create", public_repo, "--public"], gh_cmd=gh_cmd)
    if rc != 0:
        raise RepoError("%s was created, but %s was not: %s" % (dev_repo, public_repo,
                                                                 (err.strip().splitlines() or ["gh failed"])[-1]))
    print("created %s (public)" % public_repo, file=out)
    written = scaffold(dest, owner, name, person_name, site_title)
    deploy._git(dest, "init", "-q", "-b", "main")
    deploy._git(dest, "add", "--", *written)
    deploy._git(dest, "commit", "-q", "-m", SCAFFOLD_SUBJECT)
    deploy._git(dest, "remote", "add", "origin", "%s/%s.git" % (remote_base.rstrip("/"), dev_repo))
    deploy._git(dest, "push", "-q", "-u", "origin", "main")
    print("scaffolded the starter into %s (%d files), committed and pushed" % (dest, len(written)), file=out)
    print("the public site will be at %s" % preview, file=out)
    return dest


def first_publish(repo, public_url=None, gh_cmd="gh", hooks=None, interval=None, timeout=None,
                  sleep=time.sleep, now=time.time, out=None, dev_origin=None):
    """The starter, once, into an empty public repo (module docstring). `public_url` and `dev_origin`
    are test-only seams (never CLI flags): the URL replaces `deploy.public_target(cfg)[1]`, and
    `dev_origin` is the string V1 reads in place of the dev repo's `git remote get-url origin`. The PUT
    that once set the custom domain after enabling Pages is DROPPED (design amendment 1 section A2.4);
    only the `POST /pages` that turns Pages on remains."""
    out = out or sys.stdout
    interval = deploy.POLL_INTERVAL if interval is None else interval
    timeout = deploy.POLL_TIMEOUT if timeout is None else timeout
    repo = deploy._toplevel(repo)
    count = deploy._git(repo, "rev-list", "--count", "HEAD").strip()
    subject = deploy._git(repo, "log", "-1", "--format=%s", "HEAD").strip()
    if count != "1" or subject != SCAFFOLD_SUBJECT:
        raise RepoError("first-publish only publishes the untouched starter (one commit, \"%s\"); "
                        "every later publish goes through /site-studio:publish and a review" % SCAFFOLD_SUBJECT)
    if deploy._git(repo, "status", "--porcelain").strip():
        raise RepoError("the dev repo has uncommitted changes; first-publish publishes the starter as committed")
    cfg = siteconfig.load(os.path.join(repo, "site", "site.json"))
    # The one place the target is computed. A null publicRepo raises here, before any clone or gh call.
    _public, pinned, _ref = deploy.public_target(cfg)
    url = public_url or pinned
    heads = deploy._git(repo, "ls-remote", "--heads", url, "main").strip()
    if heads:
        raise RepoError("%s already has a main branch; first-publish only fills an empty public repo"
                        % cfg.publicRepo)
    repo, cfg, work, out_dir, result, _note = deploy.prepare(repo)
    try:
        st = deploy.stage_and_verify(repo, out_dir, result, url, "First publish: starter site", work)
        if st.commit is None:
            raise RepoError("nothing to publish")
        deploy.verify_public_target(repo, cfg, st, public_url, dev_origin, gh_cmd)      # guard (b): V1-V4
        deploy.push_and_verify(st, url, result.digest, work, hooks or {}, out)           # -> push_main
    finally:
        shutil.rmtree(work, ignore_errors=True)
    body = json.dumps({"build_type": "legacy", "source": {"branch": "main", "path": "/"}}).encode("utf-8")
    rc, _o, err = gh(["api", "--method", "POST", "repos/%s/pages" % cfg.publicRepo, "--input", "-"],
                     input=body, gh_cmd=gh_cmd)
    if rc != 0 and "409" not in err and "already" not in err.lower():
        raise RepoError("pushed, but Pages could not be enabled: %s"
                        % (err.strip().splitlines() or ["gh failed"])[-1])
    verdict, last = deploy.poll_pages(cfg.publicRepo, st.commit, interval, timeout, sleep, now)
    if verdict == "published":
        print("published: Pages built %s; the site is at %s" % (st.commit[:12], cfg.site_url()), file=out)
        return deploy.EXIT_OK
    if verdict == "errored":
        print("RED: the Pages build errored", file=out)
        return deploy.EXIT_RED
    print("AMBER: pushed and verified; Pages has not finished building after %d minutes (last status: %s)"
          % (max(1, int(timeout // 60)), last or "unknown"), file=out)
    return deploy.EXIT_AMBER


# ---------------------------------------------------------------- protect (AM6, AS4)

PROTECT_OK, PROTECT_RED, PROTECT_DIFFERS, PROTECT_NO_PLAN = 0, 1, 3, 5
Resp = collections.namedtuple("Resp", "status data message")
_STATUS_LINE = re.compile(r"\AHTTP/\S+\s+(\d{3})")
_HTTP_IN_ERR = re.compile(r"\(HTTP (\d{3})\)")
_NOT_PROTECTED = re.compile(r"not protected", re.I)
_BOTH = frozenset({"force-push", "deletion"})

# The classic-branch-protection fallback lives in rulesets.py (design amendment 1 section A3.1), the one
# canonical copy; test_rulesets.Classic pins its literal and test_repos.Protect pins what is sent.
CLASSIC_MAIN = rulesets.CLASSIC_MAIN


def _api(method, path, body=None, gh_cmd="gh"):
    """One `gh api` call; returns Resp(status, data, message). gh's flag that prints response headers puts
    the HTTP status line on stdout, so a plan-limit 422 and a permissions 403 can be told apart (as
    pages_check does)."""
    argv = ["api", "--method", method, "-H", "Accept: application/vnd.github+json", "--include"]  # retired-terms: ok (a gh flag, not the gmail-multi registry)
    data_in = None
    if body is not None:
        argv += ["--input", "-"]
        data_in = json.dumps(body).encode("utf-8")
    argv.append(path)
    rc, out, err = gh(argv, input=data_in, gh_cmd=gh_cmd)
    status, text = None, out
    m = _STATUS_LINE.match(out.lstrip())
    if m:
        status = int(m.group(1))
        parts = re.split(r"\r?\n\r?\n", out.lstrip(), maxsplit=1)
        text = parts[1] if len(parts) > 1 else ""
    elif rc == 0:
        status = 200
    else:
        m = _HTTP_IN_ERR.search(err)
        if m:
            status = int(m.group(1))
        elif "gh auth login" in err or "not logged" in err.lower():
            raise RepoError("gh is not logged in: run /site-studio:setup first")
        else:
            raise RepoError("gh failed: %s" % ((err.strip().splitlines() or ["no answer"])[-1]))
    try:
        data = json.loads(text) if text.strip() else None
    except ValueError:
        data = None
    message = data.get("message") if isinstance(data, dict) and isinstance(data.get("message"), str) else None
    if message is None and rc != 0 and err.strip():
        message = err.strip().splitlines()[-1]
    return Resp(status, data, message)


def _one_line(text):
    return " ".join(str(text or "").split())


def _plan_line(public_repo, message, classic_offered, out):
    """The ONE line printed when this plan refuses the protection (exit 5)."""
    said = _one_line(message) or "no message"
    if classic_offered:
        print("rulesets are not available for %s on this plan (GitHub says: %s). Classic branch protection "
              "can block force-push and deletion of main instead, and nothing else: `repos.py protect "
              "--classic` applies it. Without it, protection is not available on this plan; publish is "
              "unaffected." % (public_repo, said), file=out)
    else:
        print("main on %s: not available on this plan; publish is unaffected (GitHub says: %s)"
              % (public_repo, said), file=out)
    return PROTECT_NO_PLAN


def _refusal(r, what, public_repo, admin_line, out, classic_offered):
    """A refused read or write: plan limit (5), permissions (the admin line), or anything else (1)."""
    if rulesets.plan_unavailable(r.status, r.message):
        return _plan_line(public_repo, r.message, classic_offered, out)
    if r.status in (403, 404):
        print("could not %s: only an admin of %s can do this (GitHub says: %s). %s"
              % (what, public_repo, _one_line(r.message) or "HTTP %s" % r.status, admin_line), file=out)
        return PROTECT_RED
    print("could not %s: GitHub refused (HTTP %s: %s)" % (what, r.status, _one_line(r.message) or "no message"),
          file=out)
    return PROTECT_RED


ADMIN_RULESET = ("Add it yourself in Settings, then Rules, then Rulesets: target main, restrict deletions, "
                 "block force pushes, no bypass.")
ADMIN_CLASSIC = "Add it yourself in Settings, then Branches: do not allow force pushes or deletions."


def protect(repo, fix=False, classic=False, gh_cmd="gh", out=None):
    """Put the ruleset (or, with `classic`, classic branch protection) on the public repo's `main`.
    Returns the exit code: 0 in place or added, 3 differences and no --fix, 5 not on this plan, 1 refused."""
    out = out or sys.stdout
    if fix and classic:
        raise RepoError("--fix repairs the ruleset; --classic never replaces protection that exists. "
                        "Use one or the other")
    deploy.refuse_if_remote()
    repo = deploy._toplevel(repo)
    cfg = siteconfig.load(os.path.join(repo, "site", "site.json"))
    public_repo = deploy.public_target(cfg)[0]      # a null publicRepo refuses here (AM9)
    base = "repos/%s" % public_repo

    def api(method, path, body=None):
        return _api(method, path, body, gh_cmd)

    if classic:
        return _protect_classic(public_repo, base, api, out)
    r = api("GET", base + "/rulesets?includes_parents=false&targets=branch")
    if r.status != 200:
        return _refusal(r, "read the rulesets", public_repo, ADMIN_RULESET, out, True)
    listing = r.data if isinstance(r.data, list) else []
    named = [x for x in listing if isinstance(x, dict) and x.get("name") == rulesets.RULESET_NAME]
    if len(named) >= 2:
        print("refused: %d rulesets on %s are named \"%s\" (ids %s). Keep one and remove the others in "
              "Settings, then Rules." % (len(named), public_repo, rulesets.RULESET_NAME,
                                         ", ".join(str(x.get("id")) for x in named)), file=out)
        return PROTECT_RED
    if not named:
        w = api("POST", base + "/rulesets", rulesets.canonical_payload())
        if w.status not in (200, 201):
            return _refusal(w, "add the ruleset", public_repo, ADMIN_RULESET, out, True)
        print("added the ruleset that protects main on %s" % public_repo, file=out)
        return PROTECT_OK
    rid = named[0].get("id")
    if not isinstance(rid, int) or isinstance(rid, bool):
        print("refused: the ruleset on %s has no readable id" % public_repo, file=out)
        return PROTECT_RED
    d = api("GET", "%s/rulesets/%d" % (base, rid))
    if d.status != 200:
        return _refusal(d, "read the ruleset", public_repo, ADMIN_RULESET, out, True)
    diffs = rulesets.differences(d.data)
    if not diffs:
        print("already in place: the ruleset that protects main on %s is as it should be" % public_repo, file=out)
        return PROTECT_OK
    for line in diffs:
        print("the site-studio ruleset on %s differs: %s" % (public_repo, line), file=out)
    if not fix:
        print("run repos.py protect --fix to restore it", file=out)
        return PROTECT_DIFFERS
    w = api("PUT", "%s/rulesets/%d" % (base, rid), rulesets.canonical_payload())
    if w.status not in (200, 201):
        return _refusal(w, "restore the ruleset", public_repo, ADMIN_RULESET, out, True)
    print("restored the ruleset that protects main on %s" % public_repo, file=out)
    return PROTECT_OK


def _classic_summary(protection):
    blocked = rulesets.classic_blocks(protection)
    parts = ["force-push %s" % ("blocked" if "force-push" in blocked else "allowed"),
             "deletion %s" % ("blocked" if "deletion" in blocked else "allowed")]
    needs = rulesets.classic_refusing(protection)
    if needs:
        parts.append("requires " + ", ".join(needs))
    return "; ".join(parts)


def _protect_classic(public_repo, base, api, out):
    """`--classic` (the fallback for a plan without rulesets). A PUT to branches/main/protection REPLACES
    the whole protection, so it is sent only when none exists (or the existing one already says what
    this would say, which needs no write)."""
    path = base + "/branches/main/protection"
    r = api("GET", path)
    if r.status == 200 and isinstance(r.data, dict):
        if rulesets.classic_blocks(r.data) >= _BOTH and not rulesets.classic_refusing(r.data):
            print("already in place: classic branch protection on main of %s already blocks force-push and "
                  "deletion" % public_repo, file=out)
            return PROTECT_OK
        print("refused: main of %s already has classic branch protection (%s), and replacing it would "
              "discard it. Change it yourself in Settings, then Branches." % (public_repo, _classic_summary(r.data)),
              file=out)
        return PROTECT_RED
    if not (r.status == 404 and _NOT_PROTECTED.search(r.message or "")):
        return _refusal(r, "read the protection of main", public_repo, ADMIN_CLASSIC, out, False)
    w = api("PUT", path, copy.deepcopy(CLASSIC_MAIN))
    if w.status not in (200, 201):
        return _refusal(w, "protect main", public_repo, ADMIN_CLASSIC, out, False)
    print("protected main on %s with classic branch protection: no force-push, no deletion" % public_repo,
          file=out)
    return PROTECT_OK


def build_parser():
    """The CLI. No option here names a URL, a remote or a target: nothing on the command line can
    redirect a push (AM1); test_repos.Cli pins the exact option set of every subcommand."""
    ap = argparse.ArgumentParser(prog="repos.py", allow_abbrev=False)
    sub = ap.add_subparsers(dest="cmd")
    sub.required = True
    for n in ("create", "scaffold"):
        p = sub.add_parser(n, allow_abbrev=False)
        p.add_argument("--owner", required=True)
        p.add_argument("--name", required=True)
        p.add_argument("--dest")
        p.add_argument("--person-name")
        p.add_argument("--site-title")
    f = sub.add_parser("first-publish", allow_abbrev=False)
    f.add_argument("--repo", default=".")
    q = sub.add_parser("protect", allow_abbrev=False)
    q.add_argument("--repo", default=".")
    q.add_argument("--fix", action="store_true")
    q.add_argument("--classic", action="store_true")
    return ap


def main(argv=None, **kw):
    rc = platform_check.windows_refusal_rc("repos.py")
    if rc is not None:
        return rc
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "create":
            create(args.owner, args.name, args.dest, args.person_name, args.site_title)
        elif args.cmd == "scaffold":
            dest = os.path.abspath(args.dest or "%s-dev" % args.name)
            files = scaffold(dest, args.owner, args.name, args.person_name, args.site_title)
            print("scaffolded %d files into %s" % (len(files), dest))
        elif args.cmd == "protect":
            return protect(args.repo, args.fix, args.classic, **kw)
        else:
            return first_publish(args.repo, **kw)
        return 0
    except (RepoError, deploy.DeployError, siteconfig.SiteConfigError, build.BuildError) as e:
        print("repos refused: %s" % e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
