"""adoption.publishchecks -- what the publish would refuse, asked of the converted tree before `apply` (dev 1068, design 1.2 and 1.3).

Part of the `adoption` package behind the entry point `adopt.py`. `offline(files, parity)` takes `wouldwrite.snapshot`'s files and asks, in
this process, what `deploy.py --dry-run` asks of a build: the plugin's build accepts the tree (each refusal a finding of family `build`), the
resume PDF has its proof, the thirteen families of the site gate (`sitechecks.checker.check_tree`: an import, never a second implementation),
a MARKUP-ONLY parity record still holds against this output, no output name is on the private list, and no two output names differ only in
case. `online` adds what only the public repo, `gh` and the network can answer, by running `deploy.py --preflight` (a subprocess: adopt does
not import an entry point), whose rows it reads as they were printed. Every finding is classified by `publishfixes` (who can fix it, and how);
`block_lines` prints them grouped, and `to_json` carries every one.

A CHECK THAT DID NOT RUN IS A ROW, never a pass (design P2). `Result.rows` holds one row per check, `ran` or `not-checked` with its reason and
how to run it; a build that refuses the tree is a finding (it blocks), and the gate families that cannot then run are a `not-checked` row, so
the list never reads shorter than the checks that ran. The offline run leaves the staging row and the public repo's rows `not-checked`
("not asked here"); `online` answers them.

THE RESUME PROOF is `resumeproof.prove` (design 2): where the existing PDF says what the resume page says, `apply` writes the real sidecar, and the
checks build over those same bytes. THE STAND-IN (`with_stand_in`, whose body is `resumeproof.stand_in`: the layer below this module, so that `problems`,
`fileacct` and `measure` ask it too) is applied here ONLY while no real sidecar exists, so the rest of the list can be computed while the proof finding
stands; the finding (family `proof`) is always printed beside it, and the placeholder is never written.

BEFORE PARITY the settings and the look are not measured, so the list is for the plugin's default look: the families a look decides
(`LOOK_FAMILIES`) are counted, never listed page by page, and nothing here changes the exit code of `check` before a `parity`.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import parity_classes  # noqa: E402
from building import running  # noqa: E402
from sitechecks.checker import check_tree  # noqa: E402

from adoption import publishfixes, resumeproof, wouldwrite
from adoption.base import PLUGIN, Refused
from adoption.parity import current_parity
from adoption.publish import run_gh
from deploying.materialize import forbidden

PREFLIGHT_TIMEOUT = 180
LOOK_FAMILIES = ("media", "performance", "head", "reachable")       # a family the look decides: counted before `parity`, never page by page
PAGES_SHOWN = 5
NOT_ASKED = ("2 checks not asked here: the staged tree against the public repo, and the public repo, its Pages settings and its published "
             "addresses (`adopt.py check --online`)")
ROW_LABELS = dict((
    ("build", "the plugin's build accepts the tree"),
    ("proof", "the resume PDF has its proof"),
    ("gates", "the thirteen gate families"),
    ("markup", "a MARKUP-ONLY record still holds"),
    ("private", "no private path in the output"),
    ("case", "no two output names that differ only in case"),
    ("staging", "the staged tree equals the build (ignore rules, line endings)"),
    ("online", "the public repo, its Pages settings and its published addresses"),
))
HOW_ONLINE = "adopt.py check --online"


class Result(object):
    """The publish checks' answer: `findings` (dicts with family, path, message and who, fix, form, row, source), `rows` (one per check),
    `causes` (the online rows `deploy.py --preflight` answered, for `blockers.preflight_occurrences`) and `scratch` (a folder the caller
    may read until `run` returns)."""

    def __init__(self):
        self.findings, self.causes, self.scratch, self.proof = [], [], None, None
        self.pending = None          # the decision `for_plan` ran past (`wouldwrite.Conversion.pending`): `check` names it as a note, so `applyrefusals` does not repeat it
        self.rows = dict((k, {"id": k, "label": v, "state": "not-checked", "reason": "not asked here", "how": HOW_ONLINE})
                                for k, v in ROW_LABELS.items())

    def ran(self, key):
        self.rows[key].update(state="ran", reason="", how="")

    def not_checked(self, key, reason, how=""):
        self.rows[key].update(state="not-checked", reason=reason, how=how)

    def add(self, family, path, message, fix=None, source=None):
        found = publishfixes.classify(family, message, fix)
        found.update(family=family, path=path, message=message, source=source)
        self.findings.append(found)

    @property
    def blocks(self):
        return bool(self.findings)

    def unasked(self):
        return [r for r in self.rows.values() if r["state"] == "not-checked"]

    def counts(self):
        """(checks that ran, checks that did not)."""
        n = sum(1 for r in self.rows.values() if r["state"] == "ran")
        return n, len(self.rows) - n


def with_stand_in(files):
    """`files` with the resume sidecar the examples never wrote given to the build, so the rest of the list can be computed while the proof
    finding stands: the one use of the placeholder here (`resumeproof.stand_in` is its body), and only where `resumeproof.with_sidecar` found no real
    proof to give. Returns a new dict."""
    return resumeproof.stand_in(files)


def _write_sources(files, tree_dir):
    """The tree the gate reads beside the build (`--repo`), which is the tree deploy's own gate is given: EVERY file of the converted tree
    (`site/`, `content/`, the address record), never a chosen few. The gate reads `site/site.json`, the address record, each page's `page.md`, each
    piece's `index.md`, a resume sidecar and (under `sitemap: "indexable"`) `site/src/<page>`, and a list of those that is shorter than the gate's own
    reads is how `check` came to refuse a deliberate noindex page that deploy accepts (dev 1068, review R1, item 1). Written whole, a path the gate
    starts reading later is already there; `test_adoption_publish_equivalence.py` holds that against deploy's own call."""
    for rel, blob in files.items():
        full = os.path.join(tree_dir, *rel.split("/"))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as fh:
            fh.write(blob)


def _write_output(output, out_dir):
    for rel, blob in output.items():
        full = os.path.join(out_dir, *rel.split("/"))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as fh:
            fh.write(blob)


def _source_of(acc, path):
    page = (getattr(acc, "pages", None) or {}).get(path)
    return page.get("source") if isinstance(page, dict) else None


def scratch(files, work, proof=None):
    """(acc, stood, out_dir, tree_dir): the plugin's build over `files` (with the real sidecar `proof` makes, else the stand-in) and, when it accepts
    the tree, its output and the sources the gate and `deploy.py --preflight` read written under `work`. `out_dir` and `tree_dir` are None when the
    build refuses."""
    proof = resumeproof.prove(files) if proof is None else proof
    stood = with_stand_in(resumeproof.with_sidecar(files, proof))
    acc = running.accept(stood)
    if acc.problems or acc.cfg is None:
        return acc, stood, None, None
    out_dir, tree_dir = os.path.join(work, "out"), os.path.join(work, "tree")
    _write_output(acc.output, out_dir)
    _write_sources(stood, tree_dir)
    return acc, stood, out_dir, tree_dir


def offline(files, parity, work, vouched=None):
    """Every check that needs neither the network nor the public repo, over `files` ({path: bytes}, `wouldwrite.snapshot`'s). `parity` is
    the plan's record (a MARKUP-ONLY one is held against this output). `vouched` is the PDF hash `adopt.py proof --as-is` stored. `work` is a scratch
    folder the caller removes. Never raises."""
    res = Result()
    res.scratch = work
    try:
        res.proof = resumeproof.prove(files, vouched)
        acc, _stood, out_dir, tree_dir = scratch(files, work, res.proof)
    except Exception as e:      # noqa: BLE001 -- accept does not raise; this is the belt to its braces
        for key in ROW_LABELS:
            res.not_checked(key, "the plugin's build could not run (%s)" % e.__class__.__name__)
        return res
    for p in acc.problems:
        res.add("build", p.path or "site/", p.message if not p.lineno else "%s (line %d)" % (p.message, p.lineno), p.fix or None)
    res.ran("build")
    cfg = acc.cfg
    owed = res.proof.finding()
    if owed:
        res.add("proof", res.proof.pdf, owed, fix=resumeproof.FIX_PERSON)
    if res.proof.state in (resumeproof.UNBUILT, resumeproof.EMPTY):
        res.not_checked("proof", res.proof.why or "the built resume page has no words, so no PDF of it could ever be checked", "adopt.py proof")
    else:
        res.ran("proof")
    if out_dir is None:
        res.not_checked("gates", "the build refuses the tree (listed above), so the gate families did not run: they follow once it builds")
        res.not_checked("markup", "the build refuses the tree")
        res.not_checked("private", "the build refuses the tree")
        res.not_checked("case", "the build refuses the tree")
        return res
    res.out_dir, res.tree_dir = out_dir, tree_dir
    try:
        rep = check_tree(out_dir, cfg, tree_dir)
    except Exception as e:      # noqa: BLE001 -- the gate does not raise on a tree it can read; a doubt is a row, never a pass
        res.not_checked("gates", "the site gate could not run (%s)" % e.__class__.__name__)
        return res
    for f in rep.findings:
        res.add(f.family, f.path, f.message, source=_source_of(acc, f.path))
    res.ran("gates")
    if rep.not_read:
        res.not_checked("gates", "%d PDF(s) could not be read by the gate and are listed for the privacy review (%s)"
                        % (len(rep.not_read), ", ".join(f.path for f in rep.not_read[:3])), "the privacy review opens them")
    tokens = (parity or {}).get("tokens") if (parity or {}).get("verdict") == "MARKUP-ONLY" else None
    if isinstance(tokens, dict):
        for kind, name, why in parity_classes.recheck(tokens, acc.output):
            res.add("markup", "site/", "the MARKUP-ONLY record no longer holds: %s" % ("%s %s: %s" % (kind, name, why) if name else why))
    res.ran("markup")
    for rel in sorted(acc.output):
        if forbidden(rel):
            res.add("private", rel, "%s is on the private list and would be published" % rel)
    res.ran("private")
    seen = {}
    for rel in sorted(acc.output):
        other = seen.setdefault(rel.lower(), rel)
        if other != rel:
            res.add("case", rel, "%s and %s differ only in case (a Mac's disk keeps one of them)" % (other, rel))
    res.ran("case")
    return res


def run_process(argv, runner=None, timeout=PREFLIGHT_TIMEOUT):
    """(rows printed, the closing object or None, why it stopped or None): `deploy.py --preflight` as a subprocess, its lines read as they were
    printed. A run that stops waiting keeps every row already printed; only the rest are not checked."""
    rows, final, why = [], None, None
    try:
        p = (runner or subprocess.run)(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        text, err = p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        text, err, why = e.stdout or b"", b"", "it did not finish in %d seconds" % timeout
    except OSError as e:
        return rows, None, "it did not run (%s)" % e.__class__.__name__
    for line in text.decode("utf-8", "replace").strip().split("\n"):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and isinstance(rec.get("row"), dict):
            rows.append(rec["row"])
        elif isinstance(rec, dict) and isinstance(rec.get("ran"), str):
            rows.append({"cause": "publish/" + rec["ran"], "state": "ran", "detail": ""})
        elif isinstance(rec, dict) and isinstance(rec.get("causes"), list):
            final = rec
    if final is None and why is None:
        tail = (err.decode("utf-8", "replace").strip().split("\n") or [""])[-1][:140]
        why = "it gave no answer (%s)" % tail
    return rows, final, why


def preflight_argv(out_dir, tree_dir, repo):
    """`deploy.py --preflight` over a build in `out_dir` whose sources are in `tree_dir`, for the dev repo `repo` (its `origin` is V1's)."""
    return [sys.executable, "-B", os.path.join(PLUGIN, "scripts", "deploy.py"), "--preflight", out_dir, "--repo", repo, "--tree", tree_dir]


def merged(rows, final):
    """The rows an answer holds: the closing object's causes and the checks that ran and found nothing; with no closing object (the run stopped),
    every row that was printed."""
    if final is None:
        return list(rows)
    return list(final["causes"]) + [r for r in rows if r.get("state") == "ran"]


def absorb(res, causes, notes=()):
    """Add what `deploy.py --preflight` answered (`causes`, its rows; `notes`, why it could not finish) to `res`: the public repo and its
    settings, the address guard, the staged tree. The gate rows are not taken (the offline run is the gate); a blocking row is a finding and a
    cause, a row that could not be answered is a `not-checked` row. A row never answered because the run stopped is named, never passed."""
    staging = [c for c in causes if c.get("cause") == "publish/staging"]
    others = [c for c in causes if c.get("cause") != "publish/staging" and not str(c.get("cause", "")).startswith("publish/gate/")]
    for c in staging:
        if c["state"] == "blocks":
            res.add("staging", "the public repo", c["detail"])
    staging = [c for c in staging if c["state"] != "ran"] or staging
    for c in others:
        if c["state"] == "blocks":
            res.causes.append(c)
            res.add("online", c["cause"], c["detail"])
    unsure = [c["detail"] for c in others if c["state"] == "not-checked"]
    unsure += [c["detail"] for c in causes if c.get("cause") == "env/gates" and c["state"] == "not-checked"]
    why = "; ".join(notes)
    if staging and staging[0]["state"] == "not-checked":
        res.not_checked("staging", staging[0]["detail"], HOW_ONLINE)
    elif staging:
        res.ran("staging")                       # a block, or the `ran` marker of a staged tree that holds exactly the build
    else:
        res.not_checked("staging", why or "the public repo was not cloned, so the staged tree was not read", HOW_ONLINE)
    if why or unsure:
        res.not_checked("online", "; ".join(unsure + ([why] if why else [])), HOW_ONLINE)
    else:
        res.ran("online")
    return res


def online(res, repo, runner=None):
    """Ask `deploy.py --preflight` about the output and sources `offline` left in `res.scratch` and `absorb` its rows; a build that refused the
    tree has nothing to ask about, and the rows say so."""
    if not hasattr(res, "out_dir"):
        res.not_checked("staging", "the build refuses the tree, so there is nothing to stage", HOW_ONLINE)
        res.not_checked("online", "the build refuses the tree, so there is nothing to ask the public repo about", HOW_ONLINE)
        return res
    rows, final, why = run_process(preflight_argv(res.out_dir, res.tree_dir, repo), runner)
    return absorb(res, merged(rows, final), ["deploy.py --preflight stopped: %s" % why] if why else [])


def run(repo, files, parity=None, ask_online=False, runner=None, vouched=None):
    """`offline`, then `online` when asked, over `files`; the scratch folder is removed before this returns."""
    work = tempfile.mkdtemp(prefix="adopt-publish-")
    try:
        res = offline(files, parity, work, vouched)
        if ask_online:
            online(res, repo, runner)
        else:
            res.not_checked("staging", "not asked here", HOW_ONLINE)
            res.not_checked("online", "not asked here", HOW_ONLINE)
        res.scratch = None
        return res
    finally:
        shutil.rmtree(work, ignore_errors=True)


def environment_notes(repo, gh=None):
    """[note]: what `check --online` can warn of before `apply` meets it (design 2.4), read and never changed: a `core.hooksPath` or `commit.gpgsign`
    of the person's git (running them is the act itself, so `apply` cannot know that a hook refuses its commit), and a `gh` token that lists its
    scopes without `workflow` (the push that retires the old builder moves `.github/workflows`, which GitHub refuses without it). `gh` is a
    test's fake: `gh(argv, merge) -> (returncode, text)`, as `adoption.publish.run_gh`."""
    notes = []

    def config(key):
        p = subprocess.run(["git", "-C", repo, "config", "--get", key], stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        return p.stdout.strip() if p.returncode == 0 else ""
    hooks, signing = config("core.hooksPath"), config("commit.gpgsign")
    if hooks:
        notes.append("git's core.hooksPath is set (%s): a hook of yours runs on the publish commit and can refuse it; `apply` cannot know that earlier" % hooks)
    if signing.lower() == "true":
        notes.append("commit.gpgsign is true: a signing setting of yours can make git refuse the publish commit; `apply` cannot know that earlier")
    rc, text = (gh or run_gh)(["auth", "status"], True)
    if rc == 127:
        return notes + ["gh is not on this computer's path, so its token's scopes were not read"]
    if rc == 124:
        return notes + ["gh did not answer `auth status`, so its token's scopes were not read"]
    found = re.search(r"Token scopes:(.*)", text)
    if rc != 0 or not found:
        return notes + ["gh lists no token scopes (a fine-grained or app token lists none): whether the push may touch .github/workflows is not known"]
    if "workflow" not in found.group(1):
        notes.append("gh's token lists its scopes and `workflow` is not one of them: the push that retires your old builder moves .github/workflows and "
                     "GitHub refuses it without the scope; run `gh auth refresh -s workflow` before `apply`")
    return notes


def for_plan(repo, tree, data, plan, ask_online=False, runner=None, mode="check"):
    """(Result, [notes]): the publish checks over the one converted tree of `plan` (`wouldwrite`), as `check`, `inventory` and `parity` ask
    them. A tree that cannot be converted at all is a Result whose every row is not checked, never an empty list. `notes` are what the
    conversion assumed to get this far (a decision `apply` will still ask for)."""
    try:
        conv = wouldwrite.conversion(tree, data, plan, mode=mode)
        snap = wouldwrite.snapshot(conv)
    except Refused as e:
        res = Result()
        for key in ROW_LABELS:
            res.not_checked(key, "the converted tree could not be made (%s)" % e)
        return res, []
    notes = ["the list assumes no file under site/ or content/ is removed, because a decision is still missing: %s" % conv.pending] if conv.pending else []
    res = run(repo, snap.files, current_parity(plan.get("parity")), ask_online, runner, resumeproof.vouched_sha(plan))
    res.pending = conv.pending
    if res.proof is not None and res.proof.sentence():
        notes.append(res.proof.sentence())
    return res, notes


def after_parity(repo, tree, data, plan, say, runner=None):
    """`parity`'s block: the list over the tree `plan` (with the parity just measured) converts to, printed through `say` after the verdict, and
    the JSON `parity --json` carries as `publish`. Read-only; the offline checks only."""
    res, notes = for_plan(repo, tree, data, plan, runner=runner)
    for n in notes:
        say("  note: %s" % n)
    for line in block_lines(res):
        say(line)
    return to_json(res)


def plugin_counts(res):
    """{family: how many findings are the plugin's own}: the only findings a plugin cause is recorded and offered for (design 1.3)."""
    out = {}
    for f in res.findings:
        if f["who"] == publishfixes.PLUGIN:
            out[f["family"]] = out.get(f["family"], 0) + 1
    return out


def _groups(findings):
    groups = {}
    for f in findings:
        groups.setdefault((f["who"], f["form"]), []).append(f)
    return sorted(groups.values(), key=lambda g: (-len(set(f["path"] for f in g)), publishfixes.WHO_ORDER.index(g[0]["who"]), g[0]["form"]))


def _page(f):
    return "%s (source %s)" % (f["path"], f["source"]) if f.get("source") and f["source"] != f["path"] else f["path"]


def block_lines(res, before_parity=False, show_all=False):
    """The lines every stage prints for the list (`check`, `inventory`, `parity`, `apply --dry-run` and `apply`'s step 2): one group per
    (who, form), the group with most pages first, five pages each and "and N more" (`show_all` lists every page). Before a `parity` the
    families a look decides are counted, never listed. Not-checked rows follow, each with its reason."""
    shown = [f for f in res.findings if not (before_parity and f["family"] in LOOK_FAMILIES)]
    counted = [f for f in res.findings if before_parity and f["family"] in LOOK_FAMILIES]
    lines = []
    if before_parity:
        lines.append("before parity: measured with the plugin's own markup; `adopt.py parity` gives the final list")
    if res.findings:
        lines.append("publish checks: %d finding(s) would refuse the publish (nothing is published)" % len(res.findings))
    for g in _groups(shown):
        pages = sorted(set(_page(f) for f in g))
        first = g[0]
        lines.append("  %s %d: %s%s -> %s" % (publishfixes.WHO_LABEL[first["who"]], len(g), first["form"],
                                             (" (%s, %d page(s))" % (first["family"], len(pages))) if len(pages) > 1 else "", first["fix"]))
        cut = pages if show_all else pages[:PAGES_SHOWN]
        lines.append("      %s%s" % (", ".join(cut), "" if len(cut) == len(pages) else " and %d more" % (len(pages) - len(cut))))
    if counted:
        fams = {}
        for f in counted:
            fams[f["family"]] = fams.get(f["family"], 0) + 1
        lines.append("  a look decides these, so they are counted here and not listed: %s; `adopt.py parity` settles the look"
                     % ", ".join("%s %d" % kv for kv in fams.items()))
    notchecked = res.unasked()
    for r in notchecked:
        if r["id"] in ("staging", "online") and r["reason"] == "not asked here":
            continue
        lines.append("  not checked: %s: %s%s" % (r["label"], r["reason"], (" (%s)" % r["how"]) if r["how"] else ""))
    if any(r["id"] in ("staging", "online") and r["reason"] == "not asked here" for r in notchecked):
        lines.append(NOT_ASKED)
    return lines


def to_json(res):
    """What `inventory --json` and `parity --json` carry as `publish`: every finding (never cut), every row, and the counts."""
    return {"findings": [dict(f) for f in res.findings], "rows": list(res.rows.values()), "blocks": res.blocks,
            "ran": res.counts()[0], "notChecked": res.counts()[1]}
