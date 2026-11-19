"""deploying.confirm -- `--confirm`: all of the dry run for the given digest, then the push, the re-read, the Pages poll and the
HANDOFF.md entry. Exit codes: 0 published, 1 red, 3 amber (pushed and verified, Pages not finished).
"""
import json
import os
from reviews.dryrun import released_refusal
import shutil
import subprocess
import sys
import time
from deploying.addressguard import print_released
from deploying.constants import EXIT_AMBER, EXIT_OK, EXIT_RED, POLL_INTERVAL, POLL_TIMEOUT
from deploying.gitrun import DeployError
from deploying.prepare import prepare, print_warnings, review_summary
from deploying.pushing import push_and_verify
from deploying.staging import stage_and_verify
from deploying.target import public_target, verify_public_target


def pages_status(owner_repo, gh="gh"):
    """(status, commit) from the latest Pages build, or None when it cannot be read."""
    exe = shutil.which(gh)
    if not exe:
        return None
    try:
        p = subprocess.run([exe, "api", "repos/%s/pages/builds/latest" % owner_repo], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=60, env=dict(os.environ, GH_PROMPT_DISABLED="1"))
        if p.returncode != 0:
            return None
        d = json.loads(p.stdout.decode("utf-8"))
        return str(d.get("status")), d.get("commit")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def poll_pages(owner_repo, sha, interval, timeout, sleep, now):
    """Returns ('published'|'errored'|'timeout', last status seen)."""
    deadline = now() + timeout
    last = None
    while True:
        st = pages_status(owner_repo)
        if st is not None:
            last = st[0]
            if st[0] == "built" and st[1] == sha:
                return "published", last
            if st[0] == "errored":
                return "errored", last
        if now() >= deadline:
            return "timeout", last
        sleep(interval)


def write_handoff(repo, cfg, sha, digest, files, pages):
    path = os.path.join(repo, "HANDOFF.md")
    old = ""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8", newline="") as fh:
            old = fh.read()
    entry = ("%s## Published %s\n\n- public repo: %s\n- public sha: %s\n- digest: %s\n- files: %d\n- Pages: %s\n"
             % ("" if not old or old.endswith("\n\n") else ("\n" if old.endswith("\n") else "\n\n"),
                time.strftime("%Y-%m-%d", time.gmtime()), cfg.publicRepo, sha, digest, files, pages))
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(entry)


def run_confirm(repo, digest, message, public_url=None, hooks=None, build_fn=None, out=None,
                interval=None, timeout=None, sleep=time.sleep, now=time.time, dev_origin=None, adopt=False):
    out = out or sys.stdout
    hooks = hooks or {}
    interval = POLL_INTERVAL if interval is None else interval
    timeout = POLL_TIMEOUT if timeout is None else timeout
    repo, cfg, work, out_dir, result, note = prepare(repo, hooks, build_fn, adopt)
    try:
        print_warnings(result, out)
        if result.digest != digest:
            raise DeployError("wrong digest: this build is %s but %s was confirmed; run --dry-run "
                              "again and confirm the digest it prints" % (result.digest[:12], digest[:12]))
        status, review = review_summary(repo, result.digest)
        if status == "none":
            raise DeployError("no privacy review covers this digest: run /site-studio:review first")
        if status == "blocked":
            raise DeployError("the privacy review for this digest is BLOCKED: resolve it and review again")
        url = public_url or public_target(cfg)[1]
        st = stage_and_verify(repo, out_dir, result, url, message, work, hooks, cfg=cfg)
        verify_public_target(repo, cfg, st, public_url, dev_origin)
        if st.pages_note:
            print(st.pages_note, file=out)
        print_released(st, out)
        refusal = released_refusal(repo, digest, st.released)
        if refusal:
            raise DeployError(refusal)
        if st.commit is None:
            print("nothing to publish: the public repo already holds this exact build", file=out)
            return EXIT_OK
        try:
            push_and_verify(st, url, digest, work, hooks, out)
        except DeployError as e:
            if "differs from what you approved" in str(e):
                write_handoff(repo, cfg, st.commit, digest, len(result.files),
                              "NOT LIVE-CHECKED: public tree differs")
            raise
        verdict, last = poll_pages(cfg.publicRepo, st.commit, interval, timeout, sleep, now)
        if verdict == "published":
            write_handoff(repo, cfg, st.commit, digest, len(result.files), "built")
            print("published: Pages built %s" % st.commit[:12], file=out)
            return EXIT_OK
        if verdict == "errored":
            write_handoff(repo, cfg, st.commit, digest, len(result.files), "errored")
            print("RED: the Pages build errored for %s" % st.commit[:12], file=out)
            return EXIT_RED
        write_handoff(repo, cfg, st.commit, digest, len(result.files), "not finished (last status %s)" % last)
        print("AMBER: pushed and verified; Pages has not finished building after %d minutes (last status: %s)"
              % (max(1, int(timeout // 60)), last or "unknown"), file=out)
        return EXIT_AMBER
    finally:
        shutil.rmtree(work, ignore_errors=True)
