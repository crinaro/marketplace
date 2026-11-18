"""adoption.finish -- steps 3 to 5 of the one-process `apply`, and the two outcomes (design 8 AO; "Ruled after R3N: one-process
apply"; step 1.9f).

Part of the `adoption` package behind the entry point `adopt.py`. `do_apply` has made the conversion commit and found nothing
that blocks (steps 1 and 2: check, conversions, file accounting, parity, the publish preconditions). `run` goes on, in the same
process:

  3  publish through `deploy.py` (`adoption.publish`), in a scratch clone at the conversion commit
  4  wait for Pages to report that publish built (`deploy.py --confirm`'s own poll, or `publish.pages_built` when the public
     repo already held the build)
  5  retire the old builder in the same clone: archive E, check the tree after the move builds to the published digest
     (R3N-10), make ONE commit (`state.retire_engine`; R3N-3 scoped cleanliness), put it on the person's branch
     `site-studio/adopt-<date>`, and push it to the dev repo's main

TWO OUTCOMES, COMPLETED OR BLOCKED, and no third state. Any step that cannot complete ends the run there: the dev repo's main is
unchanged, the old builder stays the publisher, and the stop says what to do. The one stop that can come AFTER site-studio has
published is step 5's push (a token without the `workflow` scope, a protected main): the visitor sees no change (the published
site was measured equal to the old builder's), but the old publisher still runs on the next push, so the run says so, names the
one command left (`gh auth refresh -s workflow`, then the push), and ends blocked on a PERSON cause. This is stated, not
engineered around (owner: "don't over engineer this").

A KILLED RUN leaves the dev repo's main unchanged (R3N-15): nothing is pushed before step 5, the person's checkout, index and
branches are untouched until the branch is made, and the branch is made last, in one `update-ref`.
"""

import os
import re
import shutil
import tempfile

import report_issue  # noqa: E402

from adoption import publish as pub
from adoption import state
from adoption.base import Refused, git, gitt

PUSH_REFUSED_FIX = "run `gh auth refresh -s workflow`, then push: `git push origin %s:main`"


def scopes_known(gh):
    """"known" when `gh auth status` lists the token's scopes, else "unknown" (fine-grained and app tokens list none)."""
    rc, out = gh(["auth", "status"], True)
    return "known" if rc == 0 and re.search(r"Token scopes:", out) else "unknown"


def review_bullet(note):
    """The HANDOFF.md bullet about the privacy review behind a publish ("" when an agent's review covered it as usual)."""
    return "- Privacy review: %s.\n" % note if note else ""


def completion_entry(date, branch, public_repo, digest, moved, cover=None):
    """What the run appends to HANDOFF.md in its last commit. `cover` is the `review_cover` answer when no review covered the build
    and one was carried or stood in: the entry says which, never silently (owner ruling 2026-11-18)."""
    return ("\n### Adopt run (%s): completed\n\n"
            "- Published the converted site to %s (digest %s) and waited for Pages to build it.\n"
            "%s"
            "- Archived %d old-builder file(s) under `archive/` (each is a row of `archive/ARCHIVE.json`), then pushed this "
            "commit to the dev repo's main, so the old publisher no longer runs on a push.\n"
            "- If that push was refused (a token without the `workflow` scope, or a protected main), %s.\n"
            % (date, public_repo or "the public repo", (digest or "")[:12], review_bullet(cover and cover["note"]), moved,
               PUSH_REFUSED_FIX % branch))


def stop_lines(stop, branch):
    """The lines printed for a stop, and the HANDOFF.md entry text for it: (printed, entry)."""
    nxt = stop.next_action.replace("<branch>", branch)
    printed = ["adopt blocked at step %d of 5: %s." % (stop.step, stop.why),
               "  cause: %s (%s)" % (stop.cause, report_issue.cause_kind(stop.cause))]
    printed += ["  " + l for l in ([("step 3: " + stop.cover)] if stop.cover else []) + stop.lines]
    printed.append("  %s. %s." % ("The public repo has the new site and your old builder still publishes on the next push"
                                  if stop.published else
                                  "Nothing was published or pushed, and your old builder is still your publisher",
                                  "Next: " + nxt))
    entry = ("\n### Adopt run: blocked at step %d of 5\n\n- %s.\n- Cause: `%s` (%s).\n%s- %s.\n- Next: %s.\n"
             % (stop.step, stop.why, stop.cause, report_issue.cause_kind(stop.cause), review_bullet(stop.cover),
                "The public repo has the new site and the old builder still publishes on the next push" if stop.published
                else "Nothing was published or pushed; the old builder is still the publisher", nxt))
    return printed, entry


def run(repo, p, commit, date, hooks=None):
    """Steps 3 to 5 for the prepared apply `p` (`apply.prepare`) whose conversion commit is `commit` (on no branch yet).
    Returns {"completed": bool, "lines": [...], "tip": the sha the branch must point at, or None (the caller makes a stop
    commit), "stop": the Stop or None}. Never raises for a stop."""
    hooks = hooks or {}
    gh = hooks.get("gh") or pub.run_gh
    branch = p["branch"]
    work = tempfile.mkdtemp(prefix="adopt-run-")
    try:
        try:
            got = pub.publish(repo, commit, work, deploy=hooks.get("deploy"), gh=gh, cover=hooks.get("cover"),
                              dev_slug=hooks["dev_slug"] if "dev_slug" in hooks else pub.dev_slug_of(repo))
        except pub.Stop as stop:
            return {"completed": False, "lines": stop_lines(stop, branch)[0], "tip": None, "stop": stop}
        clone, lines = got["clone"], list(got["lines"])
        engine = p["engine"]
        expected = state.engine_shas(repo, commit, engine=engine)
        public_repo = p["public_repo"]
        entry = completion_entry(p["date"], branch, public_repo, got["digest"], len(expected), got.get("cover"))
        try:
            if expected:
                retired = state.retire_engine(clone, engine, published_digest=got["digest"], expected=expected,
                                              scopes=scopes_known(gh), handoff=entry)
                lines += ["step 5: archived %d old-builder file(s) in one commit" % len(retired["moved"])] + retired["lines"]
            else:
                _record_run(clone, entry)
                lines += ["step 5: there was no old builder to archive; the run is recorded in HANDOFF.md"]
        except Refused as e:
            stop = pub.Stop(5, "site-studio published, but the old builder could not be archived: %s" % e,
                            "fix that, delete the branch (`git branch -D <branch>`) and run `adopt.py apply` again; it finds "
                            "the public repo already holding this build", published=True,
                            cause=report_issue.cause_id("apply", "archive-refused"))
            return {"completed": False, "lines": stop_lines(stop, branch)[0], "tip": None, "stop": stop}
        tip = gitt(clone, "rev-parse", "HEAD")
        git(repo, "fetch", "-q", "--no-tags", clone, "HEAD:refs/heads/" + branch)
        pushed = git(clone, "push", "-q", "origin", "HEAD:refs/heads/main", check=False, timeout=300)
        if pushed.returncode != 0:
            why = (pushed.stderr.decode("utf-8", "replace").strip().split("\n") or [""])[-1][:160]
            stop = pub.Stop(5, "site-studio published and archived your old builder on branch %s, but the push to main was "
                               "refused (%s)" % (branch, why or "no reason given"),
                            PUSH_REFUSED_FIX % branch, lines, published=True,
                            cause=report_issue.cause_id("apply", "push-refused"))
            printed, _entry = stop_lines(stop, branch)
            return {"completed": False, "lines": printed, "tip": tip, "stop": stop}
        git(repo, "fetch", "-q", "origin", "main", check=False, timeout=120)
        lines += ["step 5: pushed %s to the dev repo's main" % tip[:7]]
        headline = ("adopt completed: published %s to %s, archived the old builder, and pushed it to main (branch %s, commit "
                    "%s). Your checkout is untouched: update it with `git pull --ff-only` when you are ready.%s"
                    % ((got["digest"] or "")[:12], public_repo or "the public repo", branch, tip[:7],
                       " NO AGENT REVIEWED THIS BUILD: a parity-EQUAL stand-in covered it (step 3 says what it checked)."
                       if (got.get("cover") or {}).get("kind") == "standin" else ""))
        return {"completed": True, "lines": [headline] + lines, "tip": tip, "stop": None}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _record_run(clone, entry):
    """No old builder to archive: one small commit in the clone that records the run in HANDOFF.md."""
    with open(os.path.join(clone, "HANDOFF.md"), "a", encoding="utf-8", newline="\n") as fh:
        fh.write(entry)
    if git(clone, "var", "GIT_COMMITTER_IDENT", check=False).returncode != 0:
        raise Refused("git has no committer identity; set user.name and user.email and run it again")
    git(clone, "add", "--", "HANDOFF.md")
    git(clone, "commit", "-q", "-m", "adopt completed: site-studio published the converted site (no old builder to archive)",
        "--", "HANDOFF.md")
