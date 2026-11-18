"""adopt_head.py -- the one check `deploy.py --adopt` makes in place of "HEAD is on origin/main" (template-fidelity step 1.9f;
owner rulings 26 and 27, "one-process apply"). Python 3.9, standard library only. A MODULE, not a command.

WHY IT EXISTS. `adopt.py apply` publishes the converted site BEFORE it pushes anything to the dev repo's main: a killed run must
leave that main unchanged (R3N-15), so the commit it publishes from is one step ahead of `origin/main`, never on it.
`deploy.require_head_on_origin_main` refuses exactly that. Under `--adopt` this module's check runs instead:

  1. `git fetch origin main` works (the same read as the normal check);
  2. HEAD carries `.site-studio/adopt-parity.json`: `--adopt` is for the commit `adopt.py apply` made, and nothing else is
     let through by it;
  3. `origin/main` is an ancestor of HEAD, so the push that follows the publish (adopt's step 5) is a fast-forward. When it
     is not, someone pushed to main while the run was going: nothing has been published and the person runs adopt again.

It changes no other refusal: the build, the gates, the address guard, V1 to V4, the privacy review and the person's yes at the
guard are all `deploy.py --confirm`'s own. `deploy.py` is an entry point and nothing imports it, so this module takes the git
runner and the error class as arguments and imports neither.
"""

ADOPT_RECORD = ".site-studio/adopt-parity.json"


def require_head_ahead_of_origin_main(git, repo, error):
    """Returns None when the publish may go on, else raises `error(message)`. `git(repo, *args, check=, full=, timeout=)`
    is deploy's own runner."""
    fetched = git(repo, "fetch", "--quiet", "origin", "main", check=False, full=True, timeout=120)
    if fetched.returncode != 0:
        raise error("cannot check that HEAD follows origin/main (git fetch origin main failed); publishing needs the dev "
                    "repo's origin")
    if git(repo, "cat-file", "-e", "HEAD:" + ADOPT_RECORD, check=False, full=True).returncode != 0:
        raise error("--adopt is for the commit `adopt.py apply` makes, and this HEAD has no %s; publish with "
                    "/site-studio:publish" % ADOPT_RECORD)
    ancestor = git(repo, "merge-base", "--is-ancestor", "origin/main", "HEAD", check=False, full=True)
    if ancestor.returncode == 1:
        raise error("origin/main has moved since this adoption began, so the adoption is no longer a fast-forward of it; "
                    "nothing was published. Run `adopt.py apply` again")
    if ancestor.returncode != 0:
        raise error("could not compare HEAD with origin/main; run `git fetch origin` in the dev repo, then adopt again")
    return None
