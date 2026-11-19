"""adoption.state -- where an adopt stands, read from the committed tree, and the archive commit that completes it
(design 8 AO; "Ruled after R3N: one-process apply"; step 1.9f).

Part of the `adoption` package behind the entry point `adopt.py`.

`adopt_state(repo)` reads the state from `git ls-files` and the committed records (never from a return value and never from
the scratch plan: E is computed and archived in the SAME process, so no later process needs the plan, R3N-5 dropped), so a
killed run, a second machine and the tests all see the same answer. Two outcomes, completed or blocked, and the two that
say there is nothing to judge:

  completed   the parity record's verdict is EQUAL, MARKUP-ONLY, ACCEPTED or NOT APPLICABLE; every reports row is `resolved`
              (or there are none); and no file of the engine set E (recomputed at the record's basis, with no plan) is left
              outside `archive/`: `archive/ARCHIVE.json`'s `engine` rows list the ones that moved, and a file the person's own
              decision removed at apply is simply gone. An EMPTY E with a passing record and nothing unresolved is completed:
              there is no old publisher to hand over from.
  blocked     the verdict is DIFFERENT or UNVERIFIED, or a reports row is unresolved (a `no-landing` file or an undisposed
              one is a row), OR the old builder has not been retired yet: every engine file is at its original path. The
              last is what a branch holds when a run stopped before the archive commit (a refused publish, a Pages build that
              did not finish, a killed process). Its `retirable` flag says the tree passes and nothing blocks, so a run that
              has published may archive the engine files; there is NO "ready" state (the owner's ruling: completed or blocked).
  none        no parity record: not an adopted tree (or one made by 0.2.0).
  broken      a tree in none of the above (engine files half moved while something blocks): a defect `check` names.

`retire_engine(repo, engine, ...)` is step 5 of the flow: it moves every engine file of `engine` (the E that THIS run computed)
into `archive/` with its `ARCHIVE.json` row, in ONE commit on the current branch, unpushed. It refuses (writing nothing)
unless the state is blocked and `retirable`; when a file of E changed since `expected` (the shas taken at the start of the run);
when a file it would stage has uncommitted edits (the check covers E's paths and `archive/ARCHIVE.json` only, so a tracked
`HANDOFF.md` or the person's other edits do not stop it, R3N-3); and when the plugin's build of the tree AFTER the move does
not give the digest the publish made (R3N-10: the post-move tree must publish the same site). With a `published_digest` the
rebuild is `digest_after_move`'s, made with the same `build.publish_build` the publish used (it reads commit dates, which the
in-memory `build.accept` does not, so the two digests of one tree differ: comparing across them would refuse every run); without
one, the digest of the tree before and after the move is compared with `accept` on both sides. It never pushes: the caller does.
"""

import hashlib
import json
import os
import shutil
import tempfile

from building import digest, outcomes, running  # noqa: E402

from adoption.accounting import ARCHIVE_REL, archive_path, dump_archive, parse_archive
from adoption.base import PARITY_RECORD_REL, PlanError, Refused, git, gitt
from adoption.engine import compute_engine
from adoption.parity import parse_parity_record
from adoption.reports import rows_at
from adoption.spec import load_spec
from adoption.tree import Tree

PASSING = ("EQUAL", "MARKUP-ONLY", "ACCEPTED", "NOT APPLICABLE")
COMPLETED_LINE = ("adopt completed: your old builder is archived. From this commit, pushing no longer publishes; publish "
                  "with /site-studio:publish.")
WORKFLOW_SCOPE_LINE = "pushing this commit needs a token with the `workflow` scope (`gh auth refresh -s workflow`)"
WORKFLOW_SCOPE_UNKNOWN = ("the token's scopes could not be read (UNKNOWN); if the push is refused, run `gh auth refresh -s "
                          "workflow`")


def _record(repo, ref):
    shown = git(repo, "show", "%s:%s" % (ref, PARITY_RECORD_REL), check=False)
    if shown.returncode != 0:
        return None
    return parse_parity_record(shown.stdout.decode("utf-8", "replace"))


def _archive_rows(repo, ref):
    shown = git(repo, "show", "%s:%s" % (ref, ARCHIVE_REL), check=False)
    return parse_archive(shown.stdout.decode("utf-8", "replace")) if shown.returncode == 0 else []


def engine_at(repo, ref, spec=None):
    """E for the tree at `ref`, computed from that tree alone: no plan, so a workflow the person chose with `adopt.py file`
    reads as `listed` here. A run that needs those choices passes its own E (`retire_engine(engine=...)`)."""
    spec = spec or load_spec()
    tree = Tree(repo, ref)
    try:
        data = json.loads(tree.text("site/site.json"))
    except (KeyError, ValueError):
        data = {}
    return compute_engine(tree, data, spec, None), tree


def adopt_state(repo, spec=None, engine=None):
    """{state, retirable, why} for the tree at HEAD (see the module docstring). `why` is a list of one-line facts. `engine` is
    a run's own E (a run that holds one passes it); without it E is computed at the record's basis from the tree alone."""
    try:
        rec = _record(repo, "HEAD")
    except PlanError as e:
        return {"state": "broken", "retirable": False, "why": [str(e)]}
    if rec is None:
        return {"state": "none", "retirable": False, "why": ["no %s" % PARITY_RECORD_REL]}
    try:
        rows = rows_at(repo)
        archived = _archive_rows(repo, "HEAD")
    except (Refused, PlanError) as e:
        return {"state": "broken", "retirable": False, "why": [str(e)]}
    why = []
    unresolved = [r["id"] for r in rows if r["state"] != "resolved"]
    passes = rec["verdict"] in PASSING
    if engine is None:
        try:
            engine, _t = engine_at(repo, rec["basis"] or "HEAD", spec) if rec["basis"] else ({"files": {}}, None)
        except Refused:
            engine = {"files": {}}
    head = set(p for p in gitt(repo, "ls-files").split("\n") if p)
    moved = sorted(r["from"] for r in archived if r["disposition"] == "engine")
    present = sorted(p for p in engine["files"] if p in head)       # a file the person's own decision removed is gone, not owed
    if not passes:
        why.append("the parity verdict is %s" % rec["verdict"])
    if unresolved:
        why.append("%d reported blocker(s) are not resolved" % len(unresolved))
    if not passes or unresolved:
        if moved:
            return {"state": "broken", "retirable": False, "why": why + ["engine files have moved while something blocks"]}
        return {"state": "blocked", "retirable": False, "why": why}
    if not present:
        return {"state": "completed", "retirable": False,
                "why": (["%d engine file(s) archived" % len(moved)] if moved else
                        ["nothing to retire (E is empty) and nothing blocks"])}
    if moved:
        return {"state": "broken", "retirable": False,
                "why": ["engine files are partly moved (%d of %d left; %d archived)"
                        % (len(present), len(engine["files"]), len(moved))]}
    return {"state": "blocked", "retirable": True,
            "why": ["the old builder has not been retired: site-studio has not published and archived it in a finished run"]}


def sha_of(repo, ref, path):
    return hashlib.sha256(git(repo, "show", "%s:%s" % (ref, path))).hexdigest()


def engine_shas(repo, ref="HEAD", spec=None, engine=None):
    """{path: sha256} of E at `ref`: what a run records at its start, for `retire_engine(expected=...)`. `engine` is the run's
    own E (with the person's workflow choices); a path it lists that `ref` does not hold is left out."""
    engine = engine or engine_at(repo, ref, spec)[0]
    held = set(p for p in gitt(repo, "ls-tree", "-r", "--name-only", ref).split("\n") if p)
    return dict((p, sha_of(repo, ref, p)) for p in sorted(engine["files"]) if p in held)


def output_digest(files):
    """The design 3.5 digest of the plugin's build of an in-memory tree (`{path: bytes}` of site/ and content/), or raises
    Refused when the build refuses it. The same formula the publish uses (`digest_output_tree`)."""
    acc = running.accept(files)
    if acc.problems:
        raise Refused("the plugin's build refuses the tree after the move: %s; fix what it names, then run adopt again"
                      % acc.problems[0].message)
    out = tempfile.mkdtemp(prefix="adopt-digest-")
    try:
        _write(out, acc.output)
        return digest.digest_output_tree(out, acc.cfg.siteKind)
    finally:
        shutil.rmtree(out, ignore_errors=True)


def _write(out, files):
    for rel, data in files.items():
        full = os.path.join(out, *rel.split("/"))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as fh:
            fh.write(data)


def digest_after_move(repo, want):
    """The digest `deploy.py` would publish for the tree at `repo`'s HEAD once the files of `want` ({path: rule}) are moved into
    `archive/`: the move is made and committed in a throwaway shared clone (so `repo` is untouched when this refuses) and built
    with `build.publish_build`, the build `deploy.py` runs, which reads the commit dates the in-memory `accept` does not.
    Raises Refused when the plugin's build refuses the moved tree."""
    work = tempfile.mkdtemp(prefix="adopt-verify-")
    try:
        probe = os.path.join(work, "probe")
        git(work, "clone", "-q", "--shared", repo, probe)
        for p in sorted(want):
            dest = os.path.join(probe, *archive_path(p).split("/"))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            git(probe, "mv", "--", p, archive_path(p))
        git(probe, "-c", "user.name=adopt", "-c", "user.email=adopt-probe", "commit", "-q", "-m", "probe")
        try:
            return running.publish_build(probe, os.path.join(work, "out")).digest
        except outcomes.BuildError as e:
            raise Refused("the plugin's build refuses the tree after the move: %s; fix what it names, then run adopt again" % e)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def tracked_site_files(repo, ref="HEAD", drop=()):
    """{path: bytes} of site/ and content/ at `ref`, minus the paths in `drop`: the build's input."""
    tree = Tree(repo, ref)
    paths = [p for p in tree.paths() if p.startswith(("site/", "content/")) and p not in drop]
    tree.prefetch(paths)
    return dict((p, tree.read(p)) for p in paths)


def retire_engine(repo, engine=None, published_digest=None, expected=None, spec=None, scopes=None, handoff=None):
    """Archive the engine set in ONE commit on the current branch. Returns {"commit", "moved": [(from, to, rule)],
    "lines": [...]}; raises Refused, writing nothing, in each case the module docstring names. `engine` is the E this run
    computed (None: E at HEAD, with no plan); `published_digest` the digest of the build site-studio published (None: the
    digest of the tree as it stands, which the post-move tree must still equal); `expected` is `engine_shas` from the start
    of the run; `scopes` is "known" (the token lists its scopes), "unknown" (it could not be read) or None (not asked);
    `handoff` is text appended to HANDOFF.md in the same commit (the run's record of what it did)."""
    st = adopt_state(repo, spec, engine)
    if not st["retirable"]:
        raise Refused("adopt is %s, so there is nothing to retire yet (%s); run `adopt.py check` to see what is left"
                      % (st["state"], "; ".join(st["why"])))
    engine = engine or engine_at(repo, "HEAD", spec)[0]
    head = set(p for p in gitt(repo, "ls-files").split("\n") if p)
    want = dict((p, r) for p, r in engine["files"].items() if p in head)
    if not want:
        raise Refused("the engine set is empty: there is no old builder to archive; run `adopt.py check` for the next step "
                      "(nothing is archived when there is no old builder)")
    if expected is not None:
        for p in sorted(want):
            if p not in expected or expected[p] != sha_of(repo, "HEAD", p):
                raise Refused("%s is not what it was when this run began, so the engine set changed under it; run adopt "
                              "again (nothing was archived)" % p)
        for p in sorted(expected):
            if p not in want and p in head:
                raise Refused("%s was part of the engine set when this run began and is not now; run adopt again" % p)
    paths = sorted(want) + [ARCHIVE_REL]
    dirty = gitt(repo, "status", "--porcelain", "--untracked-files=no", "--", *paths, check=False)
    if dirty:
        raise Refused("these files have uncommitted changes, so adopt will not archive over them: %s; commit or discard "
                      "them, then run adopt again" % ", ".join(l[3:] for l in dirty.split("\n")[:5]))
    for p in want:
        dest = archive_path(p)
        if git(repo, "cat-file", "-e", "HEAD:" + dest, check=False).returncode == 0:
            raise Refused("%s already exists, so %s cannot move onto it; rename or delete %s, then run adopt again" % (dest, p, dest))
    if published_digest:
        before, after = published_digest, digest_after_move(repo, want)
    else:
        before, after = output_digest(tracked_site_files(repo)), output_digest(tracked_site_files(repo, drop=set(want)))
    if after != before:
        raise Refused("the plugin's build of the tree after the move does not give the digest site-studio published (%s vs %s): "
                      "a file the build reads is in the engine set; nothing was archived; mark that file with `adopt.py file <path> "
                      "keep`, then run adopt again" % (after[:12], before[:12]))
    rows = list(_archive_rows(repo, "HEAD"))
    moved = []
    for p in sorted(want):
        dest = archive_path(p)
        os.makedirs(os.path.dirname(os.path.join(repo, *dest.split("/"))), exist_ok=True)
        git(repo, "mv", "--", p, dest)
        rows.append({"from": p, "disposition": "engine", "rule": want[p]})
        moved.append((p, dest, want[p]))
    with open(os.path.join(repo, *ARCHIVE_REL.split("/")), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(dump_archive(rows))
    git(repo, "add", "--", ARCHIVE_REL)
    lines = [COMPLETED_LINE]
    if any(want[p] == "workflow" for p in want):
        lines.append(WORKFLOW_SCOPE_LINE if scopes == "known" else WORKFLOW_SCOPE_UNKNOWN)
    msg = "\n".join(["adopt completed: the old builder is archived (%d file(s))" % len(moved), ""] +
                    ["  %s -> %s (%s)" % m for m in moved] + [""] + lines)
    if git(repo, "var", "GIT_COMMITTER_IDENT", check=False).returncode != 0:
        raise Refused("git has no committer identity; set user.name and user.email and run it again")
    extra = []
    if handoff:
        with open(os.path.join(repo, "HANDOFF.md"), "a", encoding="utf-8", newline="\n") as fh:
            fh.write(handoff)
        git(repo, "add", "--", "HANDOFF.md")
        extra = ["HANDOFF.md"]
    git(repo, "commit", "-q", "-m", msg, "--", ARCHIVE_REL, *(sorted(set(list(want) + [m[1] for m in moved])) + extra))
    return {"commit": gitt(repo, "rev-parse", "HEAD"), "moved": moved, "lines": lines}
