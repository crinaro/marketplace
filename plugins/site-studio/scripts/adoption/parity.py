"""adoption.parity -- the parity basis and preconditions, HTML normalisation, the comparison, the difference report, the
builder run, which conversions to apply, and the parity record.

Part of the `adoption` package behind the entry point `adopt.py`. Documentation that was in `adopt.py`'s docstring about this module's code:

THE TREE IT CONVERTS (named change S2, AMENDED by dev #855, design 7.3). The PARITY BASIS: `HEAD` when
the tree is clean and `origin/main` is an ancestor of `HEAD`, otherwise `origin/main`, after a `git fetch
origin main`. It is never a requirement that the checked-out branch be `main`: the desktop app starts a
session in a worktree on a `claude/<name>` branch, and the fix-commit-run-again loop works on whatever
branch the session is on. `parity_basis()` returns ONE sha, and every step derives from it: the converted
tree, the inventory, the local builder's working-copy check, the plugin side of parity, the apply
branch's parent and the "moved since the inventory" guard. (S2 used to say "always origin/main, never
the checked-out branch"; with it, a fix the person had just committed was not what adopt measured.) When
HEAD is ahead, adopt prints the commits it will include before any work, and the apply commit lists each;
when HEAD has diverged from or fallen behind origin/main, or git cannot compare them, adopt converts
origin/main as before and says up front that parity will be UNVERIFIED. The branch is created with git
plumbing (a private index, `commit-tree`, `update-ref`), so the person's working tree, index and
HEAD are never touched. The precondition is a clean tree; untracked `.claude/worktrees/` (the
app's own session folders) and this tool's plan file do not count.

PARITY (design 6.4.5, named change M13). The local builder runs on a TEMP COPY of the repo's
WORKING COPY, which INCLUDES IGNORED FILES (and excludes `.git`, `node_modules`, `site/dist`);
the plugin's publish_build runs on a second temp repo made from the parity basis's committed files
with the adopt transform applied, so ignored files never reach it. Parity is only attempted when
the working copy's tree equals the basis's (both sides come from the same sha). The local builder runs under `node` with a scrubbed
environment (PATH reduced, HOME and TMPDIR in a scratch folder, TZ=UTC, no proxy or credentials)
and a preload that makes any network call or program launch throw: an in-process guard, not an OS
sandbox. DATES are normalised in both outputs by a stated rule (DATE_RULES): every ISO date or
datetime becomes `<date>` and a copyright year after (c) / the copyright sign / &copy; becomes
`<year>`. Differences are reported as hunks grouped by cause across files (one change repeated on 27 pages is one
line with its page count; a hunk that is only an addition inside `<head>` is its own class, listed after the body
causes; dev #879, see REPORTS THAT TELL THE WHOLE TRUTH below); an ignored file present in the
working copy is listed as the likely cause. No Node, a builder that fails, or a plugin build that
refuses: UNVERIFIED, never a pass, and the builder is kept.
"""

import io
import json
import os
import posixpath
import re
import shutil
import subprocess
import tarfile
from collections import namedtuple
from urllib.parse import urlsplit

import report_issue  # noqa: E402

from adoption.base import PARITY_RECORD_REL, PLAN_REL, PlanError, RECORD_SCHEMA, Refused, git, gitt  # noqa: F401 (PLAN_REL: read here by name)
from configschema.configkeys import ADOPT_SCRATCH
from adoption.spec import CONVERSION_CLASSES, MEASURED_ONLY_CLASSES, OPT_IN_CLASSES
from adoption.blocks import piece_pages as blocks_page
from adoption.tree import Tree
# The comparison, its stated rules and the grouped report are `parity_classes`' (design R2-13, R4 row 11): adopt
# imports them and holds no copy, so the build, the publish re-check and adopt cannot disagree on what differs.
from parity_classes import (  # noqa: E402,F401
    CAUSE_EXAMPLES, CAUSE_LINES_MAX, DATE_RULES, HUNK_CLASSES, HUNKS_PER_FILE, PARITY_IGNORED,
    _Canon, _clip, _comparable, _head_span, _inside, compare_builds, difference_groups, difference_report,
    classify_differences, file_hunks, hunk_text, normalise_dates, normalise_file, normalise_html,
)

EXAMPLE_KEYS = ("name", "siteTitle", "publicRepo")
RECORD_VERDICTS = ("EQUAL", "MARKUP-ONLY", "ACCEPTED", "DIFFERENT", "UNVERIFIED", "NOT APPLICABLE")


def example_site_json(tree):
    """The parsed examples-shaped site.json, or raises Refused naming /site-studio:setup."""
    why_setup = "; to start a new site run /site-studio:setup"
    if not tree.exists("site/site.json"):
        raise Refused("this repo has no site/site.json, so it was not built from the engine layout adopt "
                      "converts" + why_setup)
    try:
        data = json.loads(tree.text("site/site.json"))
    except ValueError:
        raise Refused("site/site.json is not valid JSON, so adopt cannot read it; fix the JSON in site/site.json first"
                      + why_setup)
    if not isinstance(data, dict):
        raise Refused("site/site.json is not an object" + why_setup)
    if "schema" in data or "engine" in data:
        raise Refused("this repo is already converted (site/site.json has schema or engine); nothing to adopt, so use "
                      "`/site-studio:coordinator` to see what to do next")
    missing = [k for k in EXAMPLE_KEYS if k not in data]
    if missing:
        raise Refused("site/site.json lacks the keys adopt expects (%s), so it was not built from the engine "
                      "layout adopt converts%s" % (", ".join(missing), why_setup))
    return data


class Basis(namedtuple("Basis", "sha kind ahead reason branch origin")):
    """THE ONE SHA every step of adopt derives from (dev #855, design 7.3). `sha` is what is converted;
    `kind` is "origin/main" or "HEAD"; `ahead` is [(sha, subject)] of the commits HEAD holds that
    origin/main does not (oldest first; only when `kind` is "HEAD"); `reason` is None while parity can run,
    else why it will be UNVERIFIED (adopt then converts origin/main exactly as 0.1.0 did); `branch` is the
    checked-out branch's name, `origin` is origin/main's sha."""
    __slots__ = ()

    def label(self):
        return "HEAD" if self.kind == "HEAD" else "origin/main"

    def up_front(self):
        """The lines `check` and `inventory` print before anything else (none when HEAD is origin/main)."""
        if self.kind == "HEAD":
            n = len(self.ahead)
            return ["adopt converts HEAD %s on %s, %d commit%s ahead of origin/main %s; the live site is "
                    "still origin/main. The apply branch will include %s: %s"
                    % (self.sha[:7], self.branch, n, "" if n == 1 else "s", self.origin[:7],
                       "this commit" if n == 1 else "these %d commits" % n,
                       ", ".join("%s %s" % (s[:7], subj) for s, subj in self.ahead))]
        if self.reason:
            return ["parity will be UNVERIFIED: %s" % self.reason]
        return []


def parity_basis(repo, origin=None):
    """The ONE sha adopt converts and measures parity on (design 7.3; dev #855). Local `HEAD` when it is a
    fast-forward of `origin/main` (so the fix-commit-run-again loop works on a session branch AND on
    `main`), else `origin/main` with `reason` set, because parity then compares a tree nobody is
    converting. `git merge-base --is-ancestor` exits 0 for a fast-forward and 1 for "not an ancestor"; any
    OTHER status is an error and is never read as "not a fast-forward" (it is UNVERIFIED, with git's own
    message). The tree must already be known clean (`preconditions`). Raises Refused when origin/main does
    not resolve."""
    origin = origin or gitt(repo, "rev-parse", "--verify", "-q", "refs/remotes/origin/main", check=False)
    if not origin:
        raise Refused("origin/main does not resolve")
    head = gitt(repo, "rev-parse", "--verify", "-q", "HEAD^{commit}", check=False)
    branch = gitt(repo, "branch", "--show-current", check=False) or "(detached HEAD)"

    def unverified(why):
        return Basis(origin, "origin/main", (), why, branch, origin)
    if not head:
        return unverified("HEAD does not resolve to a commit, so there is no working copy to build")
    if head == origin:
        return Basis(origin, "origin/main", (), None, branch, origin)
    p = git(repo, "merge-base", "--is-ancestor", origin, head, check=False)
    if p.returncode == 0:
        log = gitt(repo, "log", "--reverse", "--format=%H%x09%s", "%s..%s" % (origin, head), check=False)
        ahead = tuple(tuple(line.split("\t", 1)) for line in log.split("\n") if "\t" in line)
        return Basis(head, "HEAD", ahead, None, branch, origin)
    if p.returncode == 1:
        if git(repo, "merge-base", "--is-ancestor", head, origin, check=False).returncode == 0:
            return unverified("HEAD %s on %s is behind origin/main %s; update this branch first"
                              % (head[:7], branch, origin[:7]))
        return unverified("HEAD %s on %s has diverged from origin/main %s; bring them together first"
                          % (head[:7], branch, origin[:7]))
    err = p.stderr.decode("utf-8", "replace").strip().split("\n")[0] or "exit status %d" % p.returncode
    return unverified("git could not compare HEAD %s with origin/main %s (%s)" % (head[:7], origin[:7], err))


def preconditions(repo):
    """Return (Basis, Tree at the basis, site.json dict). Raises Refused. Every later step derives from
    `Basis.sha`: the converted tree, the inventory, both sides of parity, the apply branch's parent and the
    "moved since the inventory" guard (design 7.3)."""
    if os.environ.get("CLAUDE_CODE_REMOTE") == "true":
        raise Refused("adopt runs on your own computer, not in a cloud session; open the repo there")
    if git(repo, "rev-parse", "--is-inside-work-tree", check=False).returncode != 0:
        raise Refused("%s is not a git checkout; run adopt from your dev repo's folder, or pass it with --repo" % repo)
    if git(repo, "remote", "get-url", "origin", check=False).returncode != 0:
        raise Refused("the repo has no 'origin' remote, so there is no origin/main to convert; add it with `git remote add "
                      "origin` and your repo's address, push main, then run adopt again")
    f = git(repo, "fetch", "--quiet", "origin", "main", check=False, timeout=60)
    if f.returncode != 0:
        raise Refused("git fetch origin main failed; adopt needs origin/main")
    basis = parity_basis(repo)
    tree = Tree(repo, basis.sha)
    data = example_site_json(tree)
    status = git(repo, "status", "--porcelain", "-z", "--untracked-files=all").decode("utf-8", "replace")
    dirty = []
    for rec in status.split("\0"):
        if not rec:
            continue
        path = rec[3:]
        if rec.startswith("??") and (path.startswith(".claude/worktrees/") or path in ADOPT_SCRATCH):     # the plan, the candidates
            continue
        dirty.append(path)
    if dirty:
        raise Refused("the repo has uncommitted changes (%d paths, first: %s); commit or discard them first"
                      % (len(dirty), dirty[0]))
    return basis, tree, data



def write_kept(dest, local, plugin):
    """`parity --keep <dir>` (dev #879, P2): the two builds parity compared, as they came out of the builders (not the
    normalised forms), in `<dir>/local` and `<dir>/plugin`, so a difference can be opened and read instead of inferred.
    Returns `dest`."""
    for name, files in (("local", local), ("plugin", plugin)):
        for rel, blob in sorted(files.items()):
            target = os.path.join(dest, name, *rel.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as fh:
                fh.write(blob)
    return dest


def _walk(root):
    out = {}
    for d, _dirs, files in os.walk(root):
        for f in files:
            p = os.path.join(d, f)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, root).replace(os.sep, "/")] = fh.read()
    return out



_NET_BLOCK = r"""
const block = (what) => { throw new Error('adopt parity: ' + what + ' is blocked while the local builder runs'); };
const net = require('net'); net.Socket.prototype.connect = function () { block('the network'); };
const dns = require('dns');
for (const k of ['lookup', 'resolve', 'resolve4', 'resolve6']) { dns[k] = function () { block('the network'); }; }
const cp = require('child_process');
for (const k of ['spawn', 'spawnSync', 'exec', 'execSync', 'execFile', 'execFileSync', 'fork']) { cp[k] = function () { block('starting a program'); }; }
"""


def scrubbed_env(scratch, node_path):
    return {"PATH": os.path.dirname(node_path) + os.pathsep + "/usr/bin" + os.pathsep + "/bin",
            "HOME": scratch, "TMPDIR": scratch, "TZ": "UTC", "LC_ALL": "C", "LANG": "C",
            "NODE_OPTIONS": "", "NO_COLOR": "1"}


def _copy_working_copy(repo, dest):
    """The working copy INCLUDING ignored files; not .git, node_modules, the app's worktrees, or a
    stale site/dist."""
    skip = (".git", "node_modules", ".claude/worktrees", "site/dist", "dist", "_site")

    def ignore(d, names):
        rel = os.path.relpath(d, repo).replace(os.sep, "/")
        rel = "" if rel == "." else rel + "/"
        return [n for n in names if (rel + n) in skip or n in (".git", "node_modules")]
    shutil.copytree(repo, dest, ignore=ignore, symlinks=False)


def _archive_to(repo, ref, dest):
    data = git(repo, "archive", "--format=tar", ref)
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        for m in tf.getmembers():
            n = m.name
            if n.startswith("/") or ".." in n.split("/") or m.issym() or m.islnk():
                continue
            if m.isfile():
                target = os.path.join(dest, n)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "wb") as fh:
                    fh.write(tf.extractfile(m).read())


def builder_entry(infos):
    cands = [i for i in infos if i["capability"] == "builder" and i["kind"] == "code"
             and i["path"].lower().endswith((".js", ".mjs", ".cjs"))]
    if not cands:
        return None
    cands.sort(key=lambda i: (0 if posixpath.basename(i["path"]).lower().startswith("build") else 1, i["path"]))
    return cands[0]["path"]


BUILDER_FAILS = "builder fails"      # the `kind` of a P1 class entry whose builder EXITED NON-ZERO (dev #890), not one that differs


OUTPUT_DIRS = ("site/dist", "dist", "_site")        # where a builder writes its output; the first that exists is it (design 8 AO)


def builder_failed(why):
    """True when `why` (from `_run_builder`) says the local builder exited non-zero: it ran and failed, which is not
    a timeout, a missing output folder or a build that was never attempted."""
    return why.startswith("the local builder failed (exit")


def _run_builder(workdir, entry, node, guard, env, args=()):
    """Run the person's local builder in `workdir` under parity's scrubbed, network-blocked node, as the publisher runs it:
    `node <entry> <args>` with the workflow's literal env already merged into `env` (design 8 AO, the measured invocation).
    Returns (the output folder, "") or (None, why it did not build). Shared by P2's local build and by each P1 run."""
    try:
        p = subprocess.run([node, "-r", guard, entry] + list(args), cwd=workdir, env=env, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=120)
    except subprocess.TimeoutExpired:
        return None, "the local builder did not finish in 120 seconds"
    if p.returncode != 0:
        err = [l for l in p.stderr.decode("utf-8", "replace").strip().split("\n") if l.strip()]
        # the failure line is the one node prints as `Error: <message>` (a line of source that mentions `Error` comes
        # before it in node's output), else the first line that mentions an error, else the last line
        why = (next((l for l in err if re.match(r"^\s*(?:[A-Za-z]+\.)*[A-Za-z]*Error\b[^\n]*:", l)), None)
               or next((l for l in err if re.search(r"error", l, re.I)), err[-1] if err else ""))
        return None, "the local builder failed (exit %d: %s)" % (p.returncode, why.strip()[:120])
    for rel in OUTPUT_DIRS:
        out = os.path.join(workdir, *rel.split("/"))
        if os.path.isdir(out):
            return out, ""
    return None, "the local builder wrote no output folder (looked for %s)" % ", ".join(OUTPUT_DIRS)


def template_fingerprint(tree):
    """True when the repo is the SHAPE of a site made from the template site-studio replaces (design-site-
    fidelity section 5.0.1): at least two piece folders `content/<portfolio>/<slug>/` hold `work.md`, and no
    piece folder anywhere holds `index.md`. A TEMPLATE conversion is offered as mechanical only then."""
    work, index = 0, 0
    for p in tree.paths():
        parts = p.split("/")
        if len(parts) == 4 and parts[0] == "content" and not parts[1].startswith("_") and not parts[2].startswith("_"):
            if parts[3] == "work.md":
                work += 1
            elif parts[3] == "index.md":
                index += 1
    return work >= 2 and index == 0


def active_classes(notes):
    """The conversion classes a `converted_site_files` run actually used."""
    used = []
    for cls, key in (
            ("normalise", "normalised"), ("redirectKeys", "redirectKeys"), ("labels", "labels"),
            ("redirects", "redirects"), ("redirectBoiler", "redirectBoiler"), ("layout", "layout"),
            ("tokens", "tokens"), ("viewKeys", "viewKeys"), ("viewNames", "viewNames"), ("pieces", "pieces"),
            ("pieceKeys", "pieceKeys"),
            ("resumeFields", "resumeFields"), ("pageFiles", "pageFiles"), ("blocks", "blocks"),
            ("references", "references"), ("homeKeys", "homeKeys"), ("resumeHeader", "resumeHeader"),
            ("navTokens", "navTokens"), ("personName", "personName"), ("resumePdfName", "resumePdfName"),
            ("archive", "archived"), ("draft", "drafted")):
        if notes.get(key):
            used.append(cls)
    return used


def _output_paths(cls, notes):
    """The OUTPUT paths a class of conversion can change on the plugin's side, as exact paths or prefixes
    ending in `/`, or "*" for every generated page. NEVER EMPTY (design 8 FA, ruling B4): a class with no specific path
    is `["*"]`, so every class is measured (a value in site.json that no page seems to read is still measured, because
    the build may print it)."""
    if cls == "labels":
        return ["work/"]
    if cls in ("redirects", "redirectBoiler"):
        return [(r.key.strip("/") if r.key.lower().endswith((".html", ".htm")) else r.key.strip("/") + "/index.html")
                for r in notes[cls]]
    if cls == "redirectKeys":
        return [(nk if nk.lower().endswith((".html", ".htm")) else nk + "/index.html")
                for _ok, nk, _ot, _nt in notes["redirectKeys"]]
    if cls == "pieces":
        out = set()
        for _old, new in notes["pieces"]:
            parts = new.split("/")
            out.update(("%s/%s/" % (parts[1], parts[2]), "%s/index.html" % parts[1]))
        return sorted(out)
    if cls == "viewKeys":
        return ["%s/index.html" % posixpath.basename(posixpath.dirname(path)) for path, _v in notes["viewKeys"]]
    if cls == "viewNames":                         # the portfolio's index and its piece pages
        return sorted(set("%s/" % posixpath.basename(posixpath.dirname(path)) for path, _a, _b in notes["viewNames"]))
    if cls == "pieceKeys":                         # the piece page, its portfolio's index and cards, and a home that features it
        out = set(["index.html"])
        for folder, _src, _dst in notes["pieceKeys"]:
            parts = folder.split("/")
            out.update(("%s/%s/" % (parts[1], parts[2]), "%s/index.html" % parts[1]))
        return sorted(out)
    if cls == "resumeFields" or cls == "resumeHeader":
        return ["resume/index.html"]
    if cls == "blocks":
        return sorted(set(("*" if blocks_page(p) == "*" else blocks_page(p)) for p, _ln, _k in notes["blocks"]))
    if cls == "pageFiles":
        return sorted(set("index.html" if old.startswith("content/home/") else "about/index.html"
                          for old, _new in notes["pageFiles"]))
    if cls == "homeKeys":
        return ["index.html"]
    if cls == "resumePdfName":
        return ["resume/"]
    if cls == "tokens":
        out = []
        for p, _a, _b in notes["tokens"]:
            out.append("*" if p == "site/templates/layout.html" else p[len("site/src/"):])
        return sorted(set(out))
    return ["*"]                       # normalise, layout, references, navTokens, personName, archive, draft: every page


def _touches(paths, diff_path):
    return any(p == "*" or diff_path == p or (p.endswith("/") and diff_path.startswith(p)) for p in paths)


def _opt_in_reason(cls, notes, diffs, paths):
    """Why an OPT_IN class is `you decide` by its nature, naming what it drops or adds, and the page parity says
    differs when it has measured one (design-site-fidelity sections 5.5, 5.6)."""
    if cls == "redirectBoiler":
        what = "; ".join("%s drops %s" % (r.path, ", ".join(r.boiler)) for r in notes["redirectBoiler"])
        base = ("converting it would drop head elements from a page a visitor loads (%s), so it stays as written; "
                "`adopt.py convert redirectBoiler` converts it" % what)
    elif cls == "viewKeys":
        what = "; ".join("%s: view %s" % (posixpath.dirname(path), v) for path, v in notes["viewKeys"])
        base = ("it changes that portfolio's index from the layout your builder renders to the plugin's grid (%s), so a "
                "visitor sees a different page; `adopt.py convert viewKeys` makes it, and until then the plugin's build "
                "refuses the key and the site stays on your builder" % what)
    else:
        what = ", ".join(k for k, _v in notes["resumeFields"])
        base = ("it adds visible text in the plugin's markup (fields: %s), so it cannot equal your builder's page; "
                "`adopt.py convert resumeFields` makes it" % what)
        if notes.get("resumeFieldsLeft"):
            base += "; no default for %s" % ", ".join("%s (%s)" % t for t in notes["resumeFieldsLeft"])
    hit = [d for d in diffs if _touches(paths, d)]
    return base + (("; parity shows %s differs" % hit[0]) if hit else "")


TAKEOVER = "applies once parity is EQUAL or ACCEPTED (site-studio takes over publishing)"

# A stored parity names the site-studio that measured it (design-adopt-parity-2 section 7.5, `plan.parity.plugin`), and one another
# version measured is read as none (`stale_parity`): `check`, `inventory` and `apply` say `waits on parity`, and nothing it says is
# repeated. The WRITE is `stamp_plugin`, called where `parity` stores its entry (`measure.cmd_parity`), and the plan schema that
# holds it is 3 (`adoption/plan.py`): both landed at step 9b, which turned this on. A parity that names NONE (every plan 0.5.0 wrote)
# is read as stale while this is True; a parity that names ANOTHER version is stale either way. `plan.load_plan` drops a stale one
# for `apply`, which reads `plan["parity"]` directly.
PARITY_NAMES_PLUGIN = True


def plugin_version():
    """The version of this site-studio, as a stored parity names it (`report_issue.plugin_version`, from plugin.json)."""
    return report_issue.plugin_version()


def stamp_plugin(entry):
    """`entry` (the plan's parity entry, a dict) with `plugin` set to this site-studio's version; returned."""
    entry["plugin"] = plugin_version()
    return entry


def stale_parity(parity):
    """The `waits on parity` line for a stored parity this site-studio did not measure, or None (section 7.5): "measured by
    site-studio <x>; this is <y>: run `adopt.py parity`". A parity that names another version is stale; one that names none
    is stale once `PARITY_NAMES_PLUGIN` holds. No parity at all is None: that is "not run", said by the caller."""
    if not parity:
        return None
    got = parity.get("plugin")
    if got is None and not PARITY_NAMES_PLUGIN:
        return None
    mine = plugin_version()
    if got == mine:
        return None
    return "measured by %s; this is %s: run `adopt.py parity`" % (
        ("site-studio %s" % got) if got else "an earlier site-studio (the stored parity names no version)", mine)


def current_parity(parity):
    """`parity`, or None when it is stale (`stale_parity`): what a reader may repeat."""
    return None if stale_parity(parity) else parity


def takeover_class(cls):
    """True for a TEMPLATE rename the kept builder may be unable to read (`resumeHeader`, `pieces`, `pageFiles`, `pieceKeys`, ...):
    the template's own builder reads the template's names, so a failure it shows on the renamed tree is the point of the
    rename, not a blocker. It is held while that builder publishes and made once site-studio takes over (P1R). An OPT_IN
    class is never one: choosing it is the person's say, and `broken_chosen` refuses it while parity is not EQUAL or ACCEPTED."""
    return cls not in OPT_IN_CLASSES and any(c == cls and label == "TEMPLATE" for c, label, _w in CONVERSION_CLASSES)


def measured_alone(fail, paths, diffs):
    """What P2 says about a takeover class (design-adopt-parity-2 section 7.5): the kept builder cannot read the tree it
    makes, so P1 cannot measure it, and it is measured against the plugin's build only, on the output paths it can change
    (`_output_paths`; `*` is every page). "the pages it touches are EQUAL", or "differ on <n>, first <page>", from the stored
    P2 differences. The class stays held until takeover; this line says what it is held with."""
    hit = sorted(set(d for d in diffs if _touches(paths, d)))
    head = "measured against the plugin's build only (your builder cannot read what it makes: %s)" % fail
    return "%s: %s" % (head, ("the pages it touches differ on %d, first %s" % (len(hit), hit[0])) if hit
                       else "the pages it touches are EQUAL")


def _builder_failure(p1, cls):
    """The failure line of the kept builder when P1 ran `cls` alone and the builder EXITED NON-ZERO (dev #890), else ''."""
    ds = ((p1 or {}).get("classes") or {}).get(cls) or []
    return ds[0][1] if ds and ds[0][0] == BUILDER_FAILS else ""


def decide_conversions(notes, parity, fingerprint=False, chosen=()):
    """Every conversion `notes` records, each with its label and its status under design-site-fidelity section
    5.0.3: `apply fixes this` only when parity MEASURES no visitor-facing difference; `you decide`, with the
    reason, when it measures one or cannot measure; `waits on parity` when it has not run yet. A conversion
    that touches no output path (a value in site.json, a folder the build never reads) has nothing for
    parity to measure and is mechanical. Returns [{class, label, what, status, reason}].

    A stored parity another site-studio measured (`stale_parity`, design-adopt-parity-2 section 7.5) is read as none: every
    row `waits on parity`, its reason the stale line, and nothing that parity says is repeated."""
    out = []
    stale = stale_parity(parity)
    parity = None if stale else parity
    p2 = (parity or {}).get("verdict")
    p1 = (parity or {}).get("p1") or {}
    diffs = [d[1] for d in (parity or {}).get("differences", [])]
    for cls, label, what in CONVERSION_CLASSES:
        if cls not in active_classes(notes):
            continue
        paths = _output_paths(cls, notes)
        row = {"class": cls, "label": label, "what": what, "status": "apply fixes this", "reason": "", "failure": ""}
        fail = _builder_failure(p1, cls)
        if cls in OPT_IN_CLASSES:
            row.update(status="you chose" if cls in chosen else "you decide",
                       reason=_opt_in_reason(cls, notes, diffs, paths))
            if fail and cls in chosen and p2 not in ("EQUAL", "MARKUP-ONLY", "ACCEPTED"):   # dev #890, B1 (P1R: not once site-studio publishes)
                row.update(status="you decide", failure=fail,
                           reason="your own builder FAILS on the tree this conversion makes (%s), so choosing it would "
                                  "break the builder that stays your publisher: apply refuses it while parity is not "
                                  "EQUAL or ACCEPTED, and `adopt.py convert %s --keep` leaves the page as written; %s"
                                  % (fail, cls, row["reason"]))
        elif label == "TEMPLATE" and not fingerprint:
            row.update(status="you decide", reason="the repo does not carry the template's fingerprint, so this "
                       "reading of it is a guess")
        elif p2 == "NOT APPLICABLE" and cls not in MEASURED_ONLY_CLASSES:
            pass
        elif parity is None:
            row.update(status="waits on parity", reason=stale or "run `adopt.py parity`: it measures whether this "
                       "changes a page, and whether it changes what your own builder publishes")
        elif p2 in ("UNVERIFIED", "NOT APPLICABLE"):        # NOT APPLICABLE here: a MEASURED_ONLY class, held without a P2
            row.update(status="you decide", reason="parity could not measure this (%s)" % parity.get("reason", ""))
        elif p2 in ("EQUAL", "MARKUP-ONLY", "ACCEPTED"):
            pass
        else:                                               # DIFFERENT: the builder is kept
            # a class that touches every page (`*`) is attributed by ITS OWN P1 run, never by "some page differs": it cannot
            # be blamed for a difference some other class or an unconverted construct made
            hit = [] if paths == ["*"] else [d for d in diffs if _touches(paths, d)]
            reasons = []
            if fail and takeover_class(cls):      # P1R: a rename the kept builder cannot read is made at takeover, not a blocker
                reasons.append("%s; %s" % (TAKEOVER, measured_alone(fail, paths, diffs)))
                hit = []                          # the P2-only line names the pages it touches
            elif fail:                # dev #890, B1: not a difference, a failure, named with the builder's own line
                row["failure"] = fail
                reasons.append("your own builder FAILS on the tree this conversion makes (%s)" % fail)
            elif p1.get("verdict") in ("DIFFERENT", "FAILS") and p1.get("classes", {}).get(cls):
                first = p1["classes"][cls][0]
                reasons.append("it would change what your own builder publishes (%s %s)" % (first[0], first[1]))
            if hit:
                reasons.append("parity found a difference on %s, which this conversion touches" % hit[0])
            if (not reasons and p1.get("verdict") == "FAILS"
                    and not any(ds and ds[0][0] == BUILDER_FAILS for ds in (p1.get("classes") or {}).values())):
                reasons.append("your own builder FAILS on the converted tree (%s), though no one conversion alone makes "
                               "it fail" % p1.get("reason"))
            if not reasons and p1.get("verdict") in (None, "UNVERIFIED"):
                reasons.append("parity could not measure whether this changes what your own builder publishes (%s)"
                               % (p1.get("reason") or "P1 was not run"))
            if reasons:
                row.update(status="you decide", reason="; ".join(reasons))
        out.append(row)
    return out


def conversion_lines(rows):
    """The `check` / `inventory` lines for `decide_conversions`' rows."""
    L = []
    for r in rows:
        L.append("  - %s [%s] %s: %s%s" % (r["status"], r["label"], r["class"], r["what"],
                                          (" (%s)" % r["reason"]) if r["reason"] else ""))
    return L


# Said once per run when the verdict is MARKUP-ONLY (design 5.3): what the static check cannot see.
MARKUP_LIMITS = ("the check is static: a script that reads class names or data attributes without naming them, a token "
                 "built from parts, and anything loaded from another origin are not seen, and rendered pixels are not "
                 "compared; whitespace a browser collapses is judged by the same static read of the markup, stylesheets "
                 "and scripts, and the publish re-check cannot repeat it for whitespace")


_SITEMAP_LINE = re.compile(r"^Sitemap:\s*(\S+)/sitemap\.xml\s*$", re.M)


def served_at(plugin):
    """(site path, site host) the plugin's build says it is served at, from its own `robots.txt` (`_Builder.build_sitemap`
    writes `Sitemap: <cfg.site_url()>/sitemap.xml` on every publish build): the path is `SiteConfig.site_path()`'s form, None
    for the root; the host lower-case. (None, None) when the build wrote no such line (design-adopt-parity-2 section 7.1, rule
    U: a root-absolute `/<site path>/...` address on the old site is the same address as the plugin's relative one)."""
    raw = (plugin or {}).get("robots.txt")
    m = _SITEMAP_LINE.search(raw.decode("utf-8", "replace")) if isinstance(raw, bytes) else None
    if not m:
        return None, None
    parts = urlsplit(m.group(1))
    return (parts.path.strip("/") or None), ((parts.hostname or "").lower() or None)


def classify_p2(local, plugin, site_path=None, site_host=None, limit=CAUSE_LINES_MAX):
    """P2 over two `{path: bytes}` builds, with the invisible-markup class (design 5, R4 row 11: `parity_classes`' one
    classifier). Returns {verdict EQUAL | MARKUP-ONLY | DIFFERENT; differences (the files with a VISIBLE difference, in
    `compare_builds`' words); markup ([[path, detail]], one per invisible hunk, sorted); tokens ({"class", "data", "id"}:
    every invisible token, sorted); external (each off-origin stylesheet or script: while one exists nothing is
    invisible); files (every file that differs); report (the printed lines); reason}. Both builds are read once.

    Rule U reads each build under its own path (design-adopt-parity-2 section 7.1): `site_path` and `site_host` are the
    plugin's, from `served_at(plugin)` when neither is given (step 7 left them out here, so a `/<site path>/...` address on
    the old site was not yet the same address in a real run; dev 977)."""
    if site_path is None and site_host is None:
        site_path, site_host = served_at(plugin)
    res = classify_differences(local, plugin, site_path=site_path, site_host=site_host)
    visible_paths = set(d.path for d in res["visible"])
    diffs = [t for t in res["files"] if t[1] in visible_paths]
    markup = sorted([d.path, "line %d: %s" % (d.line, hunk_text(list(d.local), list(d.plugin)))] for d in res["markup"])
    if res["verdict"] == "EQUAL":
        reason = "the two builds are equal after the stated exclusions and normalisation"
    elif res["verdict"] == "DIFFERENT":
        reason = "%d difference(s)" % len(diffs)
    else:
        reason = ("every difference is markup a visitor cannot see (%d hunk(s) on %d page(s)); %s"
                  % (len(markup), len(set(m[0] for m in markup)), MARKUP_LIMITS))
    kinds = {}
    for d in res["visible"]:
        kinds[d.kind] = kinds.get(d.kind, 0) + 1
    return {"verdict": res["verdict"], "differences": diffs, "markup": markup, "tokens": res["tokens"], "kinds": kinds,
            "external": [list(x) for x in res["external"]], "files": res["files"],
            "report": difference_report(local, plugin, res["files"], site_path=site_path, site_host=site_host, limit=limit),
            "reason": reason}


def record_text(verdict, basis_sha, differences, markup=(), tokens=None, look=None, effective=None):
    """The text of `.site-studio/adopt-parity.json` for one verdict. It carries no date, so a commit stays reproducible.
    Record schema 2 only for MARKUP-ONLY (it adds `markup` and `tokens`); every other verdict is written at schema 1,
    the lowest that holds it (design 3.5), so an older install reads the record it always could. Record schema 3
    (design-adopt-ownership-line 2.8) only when `look` holds a measured row of the person's look entries: it adds `look` (each
    row's value) and `effective` (`lookperson.effective_hash`, round 2 M6), and keeps `markup` and `tokens` for MARKUP-ONLY."""
    body = {"schema": RECORD_SCHEMA, "verdict": verdict, "basis": basis_sha,
            "differences": [list(d) for d in differences]}
    if verdict == "MARKUP-ONLY":
        body["schema"] = 2
        body["markup"] = [list(m) for m in markup]
        body["tokens"] = dict((k, sorted((tokens or {}).get(k, []))) for k in ("class", "data", "id"))
    if look:
        body.update(schema=3, look=dict((n, dict(v)) for n, v in sorted(look.items())), effective=effective)
    return json.dumps(body, indent=2, sort_keys=True) + "\n"


_LOOK_ROW = re.compile(r"^(?:look|reads)\.[A-Za-z][A-Za-z0-9._-]*$")
_LOOK_VALUE = ("derived", "file", "pages", "sha256", "status", "yours")


def _record_look(d):
    """Record schema 3's `look` and `effective`, strict (design-adopt-ownership-line 2.8): every row named `look.<id>` or
    `reads.<target>`, its value exactly the plan row's (`plan._person_row`), its numbers whole or null; `effective` 64 hex."""
    whole = lambda v, none=True: (v is None and none) or (isinstance(v, int) and not isinstance(v, bool) and v >= 0)  # noqa: E731
    rows = d["look"]
    if not isinstance(rows, dict) or not rows or not all(
            isinstance(n, str) and _LOOK_ROW.match(n) and isinstance(v, dict) and sorted(v) == list(_LOOK_VALUE)
            and v["file"] in ("site/looks/local.json", "site/looks/derived.json")
            and isinstance(v["sha256"], str) and re.match(r"^[0-9a-f]{64}$", v["sha256"])
            and whole(v["pages"], False) and whole(v["yours"]) and whole(v["derived"])
            and v["status"] in ("mapped", "ambiguous", "unmapped", "none") for n, v in rows.items()):
        raise PlanError("%s: look maps look.<id> or reads.<target> to exactly file, sha256, pages, yours, derived (whole numbers "
                        "or null) and status; restore the committed copy, or run `adopt.py remeasure`" % PARITY_RECORD_REL)
    if not (isinstance(d["effective"], str) and re.match(r"^[0-9a-f]{64}$", d["effective"])):
        raise PlanError("%s: effective must be a 64-hex hash" % PARITY_RECORD_REL)


def parity_record_text(parity, builder_found, basis_sha, look=None, effective=None):
    """The text `apply` commits as `.site-studio/adopt-parity.json` (design-site-fidelity section 5.0.4):
    the verdict, the basis it was measured on, and the differences. It carries no date, so the commit stays
    reproducible. `parity` is the plan's parity entry (None: parity was never run). `look` and `effective` are the plan's
    measured rows of the person's look entries and the effective look's hash (`lookperson.record_look`): record schema 3."""
    if parity is None:
        return record_text("UNVERIFIED" if builder_found else "NOT APPLICABLE", basis_sha, [])
    return record_text(parity["verdict"], basis_sha, parity.get("differences", []), parity.get("markup", ()),
                       parity.get("tokens"), look, effective)


def parse_parity_record(text):
    """The strict reader of `.site-studio/adopt-parity.json`, record schemas 1 and 2. An unknown key, verdict or shape
    raises `PlanError` (CLAUDE.md: a fact a run knows goes into a store with a parser that refuses what it cannot
    read). Schema 2 adds `markup` and `tokens` and is the only schema that may hold the verdict MARKUP-ONLY. Returns
    the dict."""
    try:
        d = json.loads(text)
    except ValueError as e:
        raise PlanError("%s is not valid JSON: %s; restore the committed copy from an earlier commit (`git log -- %s` "
                        "lists them)" % (PARITY_RECORD_REL, e, PARITY_RECORD_REL))
    base_keys = {"schema", "verdict", "basis", "differences"}
    three = {"look", "effective"}
    if not isinstance(d, dict) or set(d) not in (base_keys, base_keys | {"markup", "tokens"}, base_keys | three,
                                                 base_keys | three | {"markup", "tokens"}):
        raise PlanError("%s must hold exactly schema, verdict, basis and differences (record schema 2 adds markup and "
                        "tokens; record schema 3 adds look and effective)" % PARITY_RECORD_REL)
    if isinstance(d["schema"], bool) or d["schema"] not in (1, 2, 3):
        raise PlanError("%s: schema %r is not understood (this adopt reads 1 to 3); update site-studio, because a newer "
                        "one wrote it" % (PARITY_RECORD_REL, d["schema"]))
    if (d["schema"] == 3) != ("look" in d):
        raise PlanError("%s: record schema %d %s look and effective" % (PARITY_RECORD_REL, d["schema"],
                                                                       "must hold" if d["schema"] == 3 else "cannot hold"))
    if d["schema"] < 3 and (d["schema"] == 2) != ("markup" in d):
        raise PlanError("%s: record schema %d %s markup and tokens" % (PARITY_RECORD_REL, d["schema"],
                                                                      "must hold" if d["schema"] == 2 else "cannot hold"))
    if d["schema"] == 3 and (d["verdict"] == "MARKUP-ONLY") != ("markup" in d):
        raise PlanError("%s: a record schema 3 holds markup and tokens exactly when its verdict is MARKUP-ONLY" % PARITY_RECORD_REL)
    if d["verdict"] not in RECORD_VERDICTS:
        raise PlanError("%s: verdict %r is not one of %s" % (PARITY_RECORD_REL, d["verdict"], ", ".join(RECORD_VERDICTS)))
    if d["schema"] == 3:
        _record_look(d)
    if d["verdict"] == "MARKUP-ONLY" and d["schema"] not in (2, 3):
        raise PlanError("%s: the verdict MARKUP-ONLY needs record schema 2 (it lists the tokens the publish re-check "
                        "holds against the build)" % PARITY_RECORD_REL)
    if not isinstance(d["basis"], str) or (d["basis"] and not re.match(r"^[0-9a-f]{40}$", d["basis"])):
        raise PlanError("%s: basis must be a 40-hex commit" % PARITY_RECORD_REL)
    if not isinstance(d["differences"], list) or not all(
            isinstance(x, list) and len(x) == 3 and all(isinstance(y, str) for y in x) for x in d["differences"]):
        raise PlanError("%s: differences must be a list of [kind, path, detail]" % PARITY_RECORD_REL)
    if "markup" in d:
        if not isinstance(d["markup"], list) or not all(
                isinstance(x, list) and len(x) == 2 and all(isinstance(y, str) for y in x) for x in d["markup"]):
            raise PlanError("%s: markup must be a list of [path, detail]" % PARITY_RECORD_REL)
        t = d["tokens"]
        if (not isinstance(t, dict) or set(t) != {"class", "data", "id"}
                or not all(isinstance(v, list) and all(isinstance(y, str) for y in v) for v in t.values())):
            raise PlanError("%s: tokens must hold exactly class, data and id, each a list of text" % PARITY_RECORD_REL)
    return d
