#!/usr/bin/env python3
"""deploy.py -- build, verify and publish the site to the public repo (dev #835, design 7.3;
named changes S2, M5(a,c), M6, M11; amendment 1 guard (b), named changes AS2, AS5, AM2, AM3, AM8,
AM9). Python 3.9, standard library only.

    deploy.py --dry-run
    deploy.py --confirm <digest> "<commit message>"       [--repo R]

The PERSON'S YES comes between the two (design 7.4): the PreToolUse hook (publish_guard.py) asks
before `--confirm`. This script makes sure the yes approves exactly what was reviewed. It is NOT the
human act and does not pretend to be.

BOTH MODES, first, in order
  1. refuse when CLAUDE_CODE_REMOTE == "true" (the policy sentence, publish_guard.REMOTE_POLICY);
  2. refuse unless HEAD is on origin/main (named changes S2 and M11): `git fetch origin main`, then
     `git merge-base --is-ancestor HEAD origin/main`. The review-row commit that sits between a
     review and a publish is local until pushed, so a repo with an unpushed review commit refuses
     here and says to push it (a PR merge). A `claude/<name>` worktree branch is accepted when its
     HEAD is already on origin/main, never otherwise. The digest binds the BUILD, so this is not a
     reviewed-versus-published gap; it is the "public site matches a reviewed main" claim, measured.
  3. build with `build.publish_build` (design 3.5): the committed tree at HEAD, no drafts, no
     browser. A refusal there is one line.

--dry-run  runs every gate on the build, clones the public repo, replaces its tree with the output
(each file 0644), stages the EXPLICIT list of output paths plus `git rm` for vanished ones, makes a
LOCAL commit, refuses if any private path is in it, recomputes the digest from that commit's own
tree (`git ls-tree -r -z` + `git cat-file --batch`, never the working files) and refuses unless it
equals the build digest (this catches a global or repo `.gitignore` dropping a file, `core.autocrlf`
and a case collision), runs every gate again on that committed tree, and prints the changes, the
review row and `confirm: <digest>`. It writes `.site-studio/review/dryrun.json` ({digest, files,
...}): the record the hook reads, so N in the ask text comes from here and not from the model.

--confirm  repeats all of that for the digest it was given (refusing on a wrong digest or on no
covering review: `clear` or `accepted` for THIS digest), then pushes, confirms with `git ls-remote`
that the remote head IS the pushed commit, RE-READS the public repo (a fresh clone, digest again;
red "pushed, but the public tree differs from what you approved" if it differs), polls
`gh api repos/<o>/<r>/pages/builds/latest` every 10 s for up to 10 minutes, and appends what was
published to HANDOFF.md (left uncommitted: nothing here pushes the dev repo).
  exit 0  published: status built AND the build's commit is the pushed sha
  exit 1  refused, or red: errored build, or the public tree differs
  exit 3  AMBER: "pushed and verified; Pages has not finished building after 10 minutes" -- never
          reported as live

ARGUMENTS (M5(a)): argparse with allow_abbrev=False, so `--conf <digest>` is REFUSED (usage error, exit 2) rather than
accepted by the script and missed by the hook. `--confirm=<digest>` and a reordered command line are accepted, and the
hook matches them. `--dry-run` and `--confirm` are mutually exclusive. `--adopt` (with either) is `adopt.py apply`'s own:
HEAD may be one fast-forward ahead of origin/main instead of on it (adopt_head.py; 1.9f).

THE GATES are `check_site.py`, run as a subprocess: `python3 check_site.py <built tree> --repo <dev repo>`, exit 0 =
pass, anything else = a refusal carrying its first lines. If `check_site.py` is not beside this file the run is refused
with "NOT CHECKED" -- a gate that cannot run is never a pass. Tests point `deploying.gates.GATE_SCRIPT` at a fake.

NO BROWSER (M6). Nothing here launches one; test_deploy.py patches `subprocess.Popen` and `browser.find_chrome`.

The public clone URL is `https://github.com/<publicRepo>.git`; `main(..., public_url=...)` overrides
it for tests (a local bare repo). The CLI exposes no such override.

GUARD (b) -- ONE TARGET, VERIFIED BEFORE THE PUSH, NEVER FORCED (amendment 1 section A4.2)
  `public_target(cfg)` is the one place the target is computed: ("<publicRepo>",
  "https://github.com/<publicRepo>.git", "refs/heads/main"), from site.json's `publicRepo` ONLY. A
  null publicRepo refuses (a missing value must not read as the repo name "None").
  `verify_public_target(...)` runs, in order, and each failure is a refusal that pushes nothing:
    V1  not the dev repo: the dev origin's owner/name (github_url.py, the one normaliser shared with V3)
        must differ from publicRepo, compared case-insensitively. An origin that does not resolve to
        a github.com owner/name (a local path, an SSH host alias) REFUSES with a named fix.
    V2  `gh api --method GET repos/<publicRepo>`: full_name is publicRepo (a rename redirect is
        named), visibility public, not archived, `permissions.push` true. No gh, or gh failing,
        refuses. WITH SSH, V2'S PERMISSION READ IS ABOUT THE gh LOGIN AND NOT THE KEY THAT PUSHES: it
        measures the account `gh` is logged in as, which is the pushing account only when git pushes
        over the https credential helper. It is a check on the repo's state, not on the key.
    V3  in the clone, `git remote get-url --push origin` names the same github.com repo as the pinned
        URL (a rewrite to SSH of the SAME repo passes; a rewrite to another repo or an alias host
        refuses, naming the rewrite).
    V4  the remote `main` is the base the clone was made from (absent, for a first publish), and the
        base is an ancestor of the commit. Otherwise "main moved": run the dry run again; never forced.
  WHERE THEY RUN: V1-V4 run in run_dry and run_confirm right after stage_and_verify has cloned and
  committed (so a dry run shows a problem before the review); repos.first-publish calls the same
  function. V4 RUNS AGAIN, immediately before the push, inside push_and_verify (after the
  `before_push` hook seam); the first run catches a moved main early, the second closes the window
  between the first and the push. push_and_verify REFUSES a Staged that verify_public_target has not
  passed, so a caller that forgets verification is loud, not unguarded.
  `push_main(clone, sha)` is the ONLY function that pushes: `git -c push.followTags=false push
  --porcelain --no-follow-tags origin <sha>:refs/heads/main`. No `--force`, no `+` refspec, no
  --delete/--mirror/--all/--tags; the porcelain flag for refs/heads/main must be a fast-forward or a
  new ref. test_deploy.NoForce asserts that SHAPE; test_deploy.RulesetStandIn runs it.
  AFTER the push, `ls-remote --heads --tags` before and after are compared: only refs/heads/main may
  differ, and it must equal the pushed sha. This is DETECTION, not prevention (the push has
  happened), and it excludes refs/pull/*, which GitHub changes whenever anyone opens a pull request.
  Test seams (never CLI flags): `public_url=` (a local bare repo), `dev_origin=` (V1's origin string),
  and the hooks `before_push`, `after_push`, `after_ls_remote`.

THE ADDRESS GUARD (template-fidelity step 1.6, design section 8 A1; `addresses.py` is its rules and its record).
  Every path the public repo's `main` serves today is an address someone may hold. In `run_dry` and `run_confirm`,
  right after `clone_public` and BEFORE `stage` (inside `stage_and_verify`), `guard_addresses` compares the
  clone's tracked paths with the build's output paths and REFUSES while any public path is neither built nor
  released in the committed `.site-studio/addresses.json` (read from HEAD, which `require_head_on_origin_main` has
  already put on origin/main, so a drop that was never pushed is not honoured and the existing "push the commit"
  line is what the person sees: R2-8). The refusal names each path's own fix. The guard applies to every site at
  every schema once 0.4.0 publishes (owner decision 6) and changes no byte of the build.
  WHICH TREE IS SERVED (R2-5, amends decision 14). The public `main /` is the served tree only when Pages says so.
  Before the guard, `check_pages_source` reads `gh api --method GET repos/<o>/<r>/pages` ONCE, with `pages_status`'s
  60 s timeout, and classifies it with `pages_check.pages_source` (C4 a workflow, C5 another branch or folder):
  either refuses with that item's own fix. A source that cannot be READ (no gh, no login, an API error, a timeout)
  REFUSES too, naming the error and "retry": publishing already needs `gh`, so an unread source is a stop, never a
  quiet assumption. A 404 is a read: Pages is off, nothing is served yet, and the guard says so and goes on.
  `deploy.py` never calls `pages_check.check()`. Both steps are skipped for an EMPTY public repo (nothing is
  public, so nothing can be released); `repos.py first-publish` is such a call.
  THE DRY RUN names what a publish ends on purpose: `released` (path and reason, a moved piece's files included), and
  records it in `dryrun.json` v2 (review_record.write_dryrun, step 1.6r). The publish ask names those addresses
  (publish_guard) and `run_confirm` refuses a list that is not the recorded one (review_record.released_refusal).
  `deploy.py drop <path>... --reason TEXT` releases addresses (U-8 answered: a subcommand dispatched before
  argparse, as `build.py raise-schema` is, so `--dry-run` and `--confirm` and the hook's reading of them are
  untouched; the publish guard decides nothing on it because it names no `--confirm`). It writes the record and
  `site.json` at the schema the tree then needs, commits exactly those two paths, and publishes nothing.
  THE MARKUP-ONLY RE-CHECK (R2-12). `check_adopt_record` hands back a MARKUP-ONLY record, and `prepare` re-runs
  `parity_classes.recheck` for its tokens against the build it has just made (so it needs `out_dir`): any token a
  stylesheet or script now names, any attribute selector or `attr(` now present, any off-origin stylesheet or script
  now loaded refuses, naming the token, with the fix `adopt.py remeasure`.

PREFLIGHT, `deploy.py --preflight OUT [--repo DEV] [--tree TREE]` (R3N-9, R3N-13): the dry run's refusal set,
read-only, against a build someone else made (section 8 AO step 2). `OUT` is a built output folder, `TREE` the
folder whose `site/site.json` and `.site-studio/addresses.json` that build used (the scratch tree adopt converted,
NOT HEAD; default DEV), `DEV` the dev repo whose `origin` V1 reads. It pushes nothing, writes no `dryrun.json` and
does not need HEAD on origin/main. It prints ONE JSON object, `{"v": 1, "causes": [{"cause", "state", "detail"}]}`,
and exits 1 when any cause BLOCKS, else 0. The causes, each from a plugin enumeration and never the site's text:
`publish/gate/<family>` (check_site's findings), `publish/address` (the guard), `publish/pages-workflow` (C4/C5, a
person cause), `publish/serves-dev-repo` (the DEV repo itself serves Pages, a person cause) and `env/public-target`
(no publicRepo, V1, V3, a V2 refusal: blocking, never filed). `state` is `blocks` or `not-checked`; ONLY a network
or `gh` that cannot answer (gh missing or not logged in, a timeout, an unreachable public repo) reads
`not-checked` (`env/public-target`, `env/pages-source`, `env/gates`) and lets the hand-over proceed: the first
publish runs the same checks for real.

THE LIBRARY is the `deploying/` package (git, the head and gate checks, the public clone, the address guard, guard (b), the push, the
two modes, `drop` and `--preflight`; one module each). This file is the entry point only: the argument grammar, one dispatch, the
printing of a refusal and the exit code. `check_site.py` is run as a subprocess by `deploying.gates`, never imported, and
`platform_check.py` is the Windows refusal; both are named here so the package's reachable-script closure ships them.
"""
import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import platform_check  # noqa: E402
from deploying.confirm import run_confirm  # noqa: E402
from deploying.constants import EXIT_RED  # noqa: E402
from deploying.drop import run_drop  # noqa: E402
from deploying.dryrun import run_dry  # noqa: E402
from deploying.gitrun import DeployError  # noqa: E402
from deploying.preflight import run_preflight  # noqa: E402
from reviews.basics import ReviewError  # noqa: E402


def drop_main(argv):
    ap = argparse.ArgumentParser(prog="deploy.py drop", allow_abbrev=False,
                                 description="Release published addresses on purpose; publishes nothing.")
    ap.add_argument("paths", nargs="+", metavar="PATH", help="an output path the live site serves today")
    ap.add_argument("--reason", required=True, help="one line: why the address is released")
    ap.add_argument("--repo", default=".", help="the dev repo (default: the current folder)")
    args = ap.parse_args(argv)
    try:
        return run_drop(args.repo, args.paths, args.reason)
    except DeployError as e:
        print("drop refused: %s" % e)
        return EXIT_RED


def main(argv=None, public_url=None, hooks=None, build_fn=None, interval=None, timeout=None,
         sleep=time.sleep, now=time.time, dev_origin=None):
    rc = platform_check.windows_refusal_rc("deploy.py")
    if rc is not None:
        return rc
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] == "drop":          # a subcommand, dispatched as `build.py raise-schema` is (U-8)
        return drop_main(argv[1:])
    ap = argparse.ArgumentParser(prog="deploy.py", allow_abbrev=False,
                                 description="Verify and publish the site. `deploy.py drop PATH...` releases a "
                                             "published address on purpose and publishes nothing.")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="build, stage and verify; push nothing")
    mode.add_argument("--confirm", metavar="DIGEST", help="publish the build with this digest")
    mode.add_argument("--preflight", metavar="OUT", help="the dry run's refusals against a build in OUT; read-only")
    ap.add_argument("--repo", default=".", help="the dev repo (default: the current folder)")
    ap.add_argument("--tree", default=None, help="with --preflight: the folder holding the site/site.json and "
                                                 ".site-studio/addresses.json the build used (default: --repo)")
    ap.add_argument("--adopt", action="store_true", help="adopt.py apply only: HEAD may be one fast-forward ahead of origin/main")
    ap.add_argument("message", nargs="?", help="the public commit message (with --confirm)")
    args = ap.parse_args(argv)
    if args.adopt and args.preflight is not None:
        ap.error("--adopt is for --dry-run and --confirm")
    if args.tree is not None and args.preflight is None:
        ap.error("--tree is only for --preflight")
    if args.preflight is not None and args.message:
        ap.error("--preflight takes no message")
    if args.confirm is not None and not (args.message or "").strip():
        ap.error("--confirm needs the commit message as the last argument")
    if args.dry_run and args.message:
        ap.error("--dry-run takes no message")
    try:
        if args.preflight is not None:
            return run_preflight(args.preflight, args.repo, args.tree, public_url, dev_origin)
        if args.dry_run:
            return run_dry(args.repo, public_url, hooks, build_fn, dev_origin=dev_origin, adopt=args.adopt)
        return run_confirm(args.repo, args.confirm, args.message.strip(), public_url, hooks, build_fn, interval=interval,
                           timeout=timeout, sleep=sleep, now=now, dev_origin=dev_origin, adopt=args.adopt)
    except (DeployError, ReviewError) as e:
        print("deploy refused: %s" % e)
        return EXIT_RED


if __name__ == "__main__":
    sys.exit(main())
