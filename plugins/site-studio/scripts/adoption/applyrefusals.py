"""adoption.applyrefusals -- what `apply` would refuse before it writes anything, asked by `check` first (dev 1068, review R1, item 2).

Part of the `adoption` package behind the entry point `adopt.py`. `check` promises to name everything `apply` and the publish would refuse. The publish checks
(`publishchecks`) answer for the site; this module answers for `apply` itself: the refusals it raises that no other check makes (a covered unit of a file that
stays, an archive that already exists, a path with a tab, a branch that already exists, a hook that would name a removed file, a reports record that cannot be
read, no committer identity, and the decisions still missing) are asked here, READ-ONLY, by calling the very functions `apply.prepare` calls. `apply.stage` is
`prepare`'s steps 2 to 4 as one function, run here over a tree of its own that nothing is written back from; `check` and `apply` therefore cannot disagree
about them, and a refusal added to those steps is named by `check` with no second edit.

Two kinds, told apart because the first is the person's own to settle and the second is a fault in what they have chosen:

  decide   a decision still missing (`wouldwrite.refuse_undecided`: a file proposed for removal with no `confirm` or `--keep`, a resume paper size nobody gave);
           printed, and it changes no exit code: `check` is run at the start, when every decision is still to make
  refuse   `apply.stage`, the branch, the committer identity, the paths and the reports record; printed, and `check` exits 1, before a `parity` as after it,
           because none of them depends on how the site looks

Nothing here writes: the tree is `adoption.tree.Tree` (an in-memory overlay), the branch and identity are asked with `git show-ref` and `git var`.
`publishfixes.STOPS` has a row for every function of the path that raises, and says which of them `check` names (this module) and which cannot be known earlier.
"""

import time

from adoption import apply as adoption_apply
from adoption import resumeproof
from adoption.base import PlanError, Refused
from adoption.tree import Tree
from adoption.wouldwrite import conversion, snapshot


def _text(e):
    return str(e) or e.__class__.__name__


def collect(repo, data, plan, spec=None, date=None):
    """(decide, refuse): the lines of what a real `apply` of this plan would stop at, each the refusal's own text (which names the file and the fix). Read-only
    and never raises. `date` is `apply`'s `--date` (today by default, as `adopt.py` makes it): the day of the branch it would make."""
    decide, refuse = [], []
    date = date or time.strftime("%Y-%m-%d")
    basis = Tree(repo, plan["base"])
    try:
        conv = conversion(basis, data, plan, spec, "apply")
    except (Refused, PlanError) as e:           # the strict conversion stops at the first decision still missing; what follows is asked as `--dry-run` asks it
        decide.append(_text(e))
        try:
            conv = conversion(basis, data, plan, spec, "dry")
        except (Refused, PlanError):
            return decide, refuse               # nothing after it can be computed: the first refusal is the one the person meets
    for step in (lambda: adoption_apply.check_branch_free(repo, adoption_apply.BRANCH_PREFIX + date),
                 lambda: adoption_apply.refuse_no_identity(repo)):
        try:
            step()
        except Refused as e:
            refuse.append(_text(e))
    staged = Tree(repo, plan["base"])
    try:
        snap = snapshot(conv)
        proof = resumeproof.prove(snap.files, resumeproof.vouched_sha(conv.plan))
        adoption_apply.refuse_placeholder(proof)
        snap.files = resumeproof.with_sidecar(snap.files, proof)
        adoption_apply.stage(staged, data, conv.plan, conv, snap, proof, plan["base"], date)
        for path in sorted(staged.removed) + sorted(staged.writes):
            adoption_apply.refuse_path(path)
        adoption_apply.reports_at(staged)
    except (Refused, PlanError) as e:
        refuse.append(_text(e))
    return decide, refuse
