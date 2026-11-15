#!/usr/bin/env python3
"""adopt.py -- convert a dev repo that carries its own copy of this plugin's tools (dev #835,
design 6.4; named changes S2, S8, S9, S10 (round 1), M9, M13). Python 3.9, standard library only.

    adopt.py [--repo R] check
    adopt.py [--repo R] inventory [--json]
    adopt.py [--repo R] confirm PATH [--keep] [--as CAPABILITY]
    adopt.py [--repo R] unit PATH UNIT_ID {person-data|keep|rule} [--kind context|voice|rule] [--name SLUG]
    adopt.py [--repo R] fact PATH --kind context|voice|rule --text TEXT [--name SLUG]
    adopt.py [--repo R] reviewed PATH
    adopt.py [--repo R] paper {Letter|A4}
    adopt.py [--repo R] folder NAME {source|portfolio}
    adopt.py [--repo R] kind {portfolio|hub|custom}
    adopt.py [--repo R] parity [--accept]
    adopt.py [--repo R] apply [--date YYYY-MM-DD] [--dry-run]

WHAT IT IS FOR. The person's dev repo may hold local copies of what the plugin now does (agents,
commands, scripts, a builder). A project agent with the same name outranks a plugin agent, and a
similar one under another name competes for routing, so the copies must go -- but the person's own
content, decisions and facts must not. `inventory` classifies each local file by WHAT IT DOES
(`spec/capabilities.json`: signals, weights, thresholds), `apply` makes ONE commit on a NEW branch
of the person's dev repo, and nothing is merged or pushed.

NOTHING HERE TOUCHES THE PUBLIC REPO, THE DEPLOY PATH OR THE PERSON'S CHECKOUT. There is no
code path that pushes, runs `gh`, or imports the deploy script. The only value read from
`site.json` about the public repo is the file's own text, carried through unchanged.

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

EVERY PROBLEM AT ONCE (dev #855, design-site-adoption section 7.1). `check` and `inventory` build the
site.json adopt WOULD write and run `siteconfig.problems()` over it and `content.layout_problems()` over
the tree, then print EVERY problem with its fix, each marked `apply fixes this` (mechanical) or `you
decide`. The converted site.json is written with the lowest schema its tree needs (a `[key, label]`
pair converted into `work.labels`, or a `{{resumeLink}}` anchor rewritten into a page section, makes it
schema 2, and the inventory says so).

APPLY NORMALISES THE MECHANICAL PROBLEMS AND LISTS EACH (dev #855, design 7.2). A clone-URL `publicRepo`
becomes `owner/name` (through `github_url.slug`), a `previewUrl` loses its trailing slash, a `content/<f>/`
with no `page.md` is renamed `content/_<f>/` (kept as source material, not built; `adopt.py folder <f>
portfolio` adds a `page.md` instead), and `[key, label]` pairs become the `work.labels` map. Every one is a
line of the commit. For each replaced value, a literal search of the files the person KEEPS (not the retired
copies) names `file:line` under "your own script may depend on the old form". Anything that is not
mechanical (an unknown key, a non-https previewUrl) is never rewritten: it stays `you decide`.

A STANDING RULE OF THE PERSON'S OWN (dev #851, design-site-adoption section 10, criterion O1). A residual unit of
a file adopt removes can be marked `rule`: "a standing rule of mine, keep it for every agent". Apply appends each
one, verbatim and with its source path, to the site repo's `CLAUDE.md` under `## Standing rules carried by
adopt`, after the engine sections are replaced (that heading is not one of them), and lists each in the commit.
Subagents load the project's CLAUDE.md, and tests/probes/PB-RESULT.md measured that `.claude/rules/` reaches a
plugin agent too, so the person may move the rules there. A `rule` unit on a file that stays is refused: a rule
travels only out of a file adopt removes.

THE INPUT DOMAIN (named change S9(b)). Adopt converts a repo built from the examples' engine
layout: `site/site.json` carrying `name`, `siteTitle` and `publicRepo`. Anything else (a Jekyll or
Eleventy repo, no `site/site.json`, a `site.json` without those keys) is refused naming
`/site-studio:setup`; a repo that already has `schema` and `engine` is refused as already
converted.

THE PAPER SIZE (named change S9(a)). `resume.paper` is read from the MediaBox of the repo's existing
resume PDF (612x792 is Letter, 595x842 is A4, a few points of tolerance, either orientation). No
PDF, or a PDF whose boxes cannot be read as plain text (an object-stream file), means adopt
REPORTS that it needs the answer, and `apply` refuses until `adopt.py paper Letter|A4` is run.
Letter is never assumed.

THE CLASSIFIER (design 6.4.2). Per file: a SCORE per capability (summed weight of its signals found
/ its total signal weight) and a RESIDUAL (units no signal of the matched capability explains /
all units). Units: a paragraph or list item for Markdown, a top-level function or statement for
code, a top-level key for package.json. Blank lines, comments, headings and front matter are not
units. Classes: DUPLICATE, PARTIAL, AMBIGUOUS, CUSTOM, MIXED, DATA (the thresholds live in the
spec). The file name is one signal, never sufficient and never required (tested for every
capability). NAMESAKES (dev #851, design 7.6): an agent file named like one of the plugin's agents gets a
SHADOW warning WHATEVER ITS CLASS, because a project agent outranks a plugin agent of the same name when it
is called by its bare name (and adopt can see only this repo's `.claude/agents/`, never the person's
`~/.claude/agents/`). If it also scores at or above the match threshold against that agent's capability it
is a SELF-MATCH: DUPLICATE or PARTIAL, never AMBIGUOUS. If it does not, it keeps the class it earned and
carries `namesake` [capability, score]; the name alone never makes a match.

THE PLAN (`.site-studio/adopt-plan.json`, a strict parser) holds only the person's decisions: per
file, remove or keep; which residual units are person data or kept behaviour; whether the facts
were reviewed; the paper size; the parity result. `apply` re-classifies from the tree, so a plan
cannot assert a class. Order inside `apply`: DATA FILES FIRST, CONFIG SECOND, REMOVALS LAST, and
it refuses (changing nothing) while any file proposed for removal has no decision, any removal's
facts are unreviewed, any residual unit is undispositioned or marked keep, a builder's parity is
not EQUAL or ACCEPTED, or a hook would be left naming a file that is not in the new tree.

HOOKS (design 6.4.3, round 1 S10). A hook command naming a removed file: removed when the plugin's
own hook does the same job (doctor, sync_main), rewritten to the plugin's script keeping its
arguments when the capability has a counterpart script, and otherwise the file is KEPT. Every
change is listed. UNDETERMINED: whether `${CLAUDE_PLUGIN_ROOT}` is defined for a hook in a
project's settings file; the rewrite is listed for the person to read, and the backstop below
guards the rest. The backstop refuses to finish when any remaining hook names a repo path absent
from the new tree.

PARITY (design 6.4.5, named change M13). The local builder runs on a TEMP COPY of the repo's
WORKING COPY, which INCLUDES IGNORED FILES (and excludes `.git`, `node_modules`, `site/dist`);
the plugin's publish_build runs on a second temp repo made from the parity basis's committed files
with the adopt transform applied, so ignored files never reach it. Parity is only attempted when
the working copy's tree equals the basis's (both sides come from the same sha). The local builder runs under `node` with a scrubbed
environment (PATH reduced, HOME and TMPDIR in a scratch folder, TZ=UTC, no proxy or credentials)
and a preload that makes any network call or program launch throw: an in-process guard, not an OS
sandbox. DATES are normalised in both outputs by a stated rule (DATE_RULES): every ISO date or
datetime becomes `<date>` and a copyright year after (c) / the copyright sign / &copy; becomes
`<year>`. Differences are listed as path and first differing line; an ignored file present in the
working copy is listed as the likely cause. No Node, a builder that fails, or a plugin build that
refuses: UNVERIFIED, never a pass, and the builder is kept.

PARITY_IGNORED lists what the plugin adds and the examples never wrote. It follows the design's
list plus ONE addition: the `decoding` attribute on `<img>`, because build.py writes
`decoding="async"` on every image and the design's list names only srcset, sizes, width, height
and loading (a finding; without it no repo with an image could pass).
"""
import argparse
import difflib
import hashlib
import html
import html.parser
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import io
from collections import namedtuple
from urllib.parse import urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import github_url  # noqa: E402
import siteconfig  # noqa: E402
import content as site_content  # noqa: E402
import platform_check  # noqa: E402

PLUGIN = os.path.dirname(HERE)
SPEC_PATH = os.path.join(PLUGIN, "spec", "capabilities.json")
AGENTS_DIR = os.path.join(PLUGIN, "agents")
STARTER_SETTINGS = os.path.join(PLUGIN, "templates", "starter", "dot-claude", "settings.json")

# Named change S8: pinned word for word in tests/test_adopt.py and the starter's test_repos.
POINTER_LINE = ("If /site-studio commands are unknown, this session does not have the plugin (cloud "
                "sessions do not install repo-declared plugins); open the repo on your own computer.")
PLAN_REL = ".site-studio/adopt-plan.json"
BRANCH_PREFIX = "site-studio/adopt-"
# Named change S2: the app keeps session worktrees inside the repo.
GITIGNORE_LINES = (".claude/worktrees/", "site/dist/", ".site-studio/review/")
EXAMPLE_KEYS = ("name", "siteTitle", "publicRepo")
RESERVED_FOLDERS = ("media", "resume", "references", "about", "home")
PLAN_SCHEMA = 1
FACT_KINDS = ("context", "voice", "rule")
UNIT_DISPOSITIONS = ("person-data", "keep", "rule")       # `rule` is NOT the `rule` fact kind: it goes to CLAUDE.md
RULES_HEADING = "## Standing rules carried by adopt"
# What the person may decide for a content/ folder that has no page.md (design 7.2): the default,
# `source`, renames it to content/_<name> (kept as source material, not built); `portfolio` adds a page.md.
FOLDER_CHOICES = ("source", "portfolio")
# Text files adopt searches for a value it replaced (design 7.2); anything else is left unread.
_TEXT_EXTS = (".sh", ".bash", ".zsh", ".py", ".js", ".mjs", ".cjs", ".ts", ".rb", ".json", ".md", ".yml",
              ".yaml", ".toml", ".html", ".htm", ".txt", ".cfg", ".ini", ".mk", ".csv")
_TEXT_MAX = 512 * 1024

PARITY_IGNORED = {
    "files": ("sitemap.xml", "robots.txt"),
    "head": ("link[rel=canonical]", "meta[property^=og:]", "meta[name^=twitter:]"),
    "img_attrs": ("srcset", "sizes", "width", "height", "loading", "decoding"),
}

# The stated date rule (named change M13). Applied to both builds' text output.
DATE_RULES = (
    (re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?\b"), "<date>"),
    (re.compile(r"((?:&copy;|&#169;|&#xa9;|©|\(c\))\s*)(?:19|20)\d{2}(?:\s*[-–—]\s*(?:19|20)\d{2})?", re.I),
     r"\1<year>"),
)

_REDIRECTING = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
                "GIT_OBJECT_DIRECTORY", "GIT_NAMESPACE")
CODE_EXTS = (".js", ".mjs", ".cjs", ".py", ".sh", ".bash", ".zsh", ".json")


class Refused(Exception):
    """A refusal; the message is one line. Nothing was changed."""


class NeedsAnswer(Refused):
    """The person must answer a question before adopt can go on."""


class PlanError(ValueError):
    """The plan file cannot be read."""


# ---------------------------------------------------------------- git

def _env(extra=None):
    env = dict((k, v) for k, v in os.environ.items() if k not in _REDIRECTING)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "never"
    env["LC_ALL"] = "C"
    if extra:
        env.update(extra)
    return env


def git(repo, *args, **kw):
    """Run git in `repo`; return stdout bytes. `input` bytes, `env` extra vars, `check` (default True)."""
    check = kw.pop("check", True)
    p = subprocess.run(["git", "-C", repo] + list(args), input=kw.pop("input", None),
                       env=_env(kw.pop("env", None)), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       timeout=kw.pop("timeout", 120))
    if check and p.returncode != 0:
        raise Refused("git %s failed: %s" % (args[0], p.stderr.decode("utf-8", "replace").strip().split("\n")[0]))
    if not check:
        return p
    return p.stdout


def gitt(repo, *args, **kw):
    """Like git(), returning stripped text; with check=False a failure reads as an empty string."""
    out = git(repo, *args, **kw)
    if not isinstance(out, bytes):
        out = out.stdout if out.returncode == 0 else b""
    return out.decode("utf-8", "replace").strip()


# ---------------------------------------------------------------- the spec

class Spec(object):
    def __init__(self, data):
        self.data = data
        th = data["thresholds"]
        self.match = th["match"]
        self.gap = th["ambiguousGap"]
        self.residual_max = th["residualMax"]
        self.caps = data["capabilities"]
        self._rx = {}

    def rx(self, pattern):
        r = self._rx.get(pattern)
        if r is None:
            r = self._rx[pattern] = re.compile(pattern, re.I | re.M)
        return r


def load_spec(path=None):
    with open(path or SPEC_PATH, "r", encoding="utf-8") as fh:
        return Spec(json.load(fh))


def _sig_found(spec, sig, text, base):
    target = base if sig.get("name") else text
    for p in sig["any"]:
        if spec.rx(p).search(target):
            return True
    return False


def _applicable(cap, kind, base):
    if kind not in cap["kinds"]:
        return False
    files = cap.get("files")
    if files and not any(re.search(f, base, re.I) for f in files):
        return False
    return True


def score_capability(spec, cap, text, base):
    total = sum(s["weight"] for s in cap["signals"])
    got = 0
    found = []
    for s in cap["signals"]:
        if _sig_found(spec, s, text, base):
            got += s["weight"]
            found.append(s["id"])
    return (got / float(total) if total else 0.0), found


# ---------------------------------------------------------------- units

_FM = re.compile(r"\A---\r?\n.*?\r?\n---\r?\n", re.S)
_LIST = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_HEAD = re.compile(r"^\s{0,3}#{1,6}\s")


def md_units(text):
    """Paragraphs and list items of a Markdown file; headings, comments, front matter, blanks excluded."""
    text = _FM.sub("", text.replace("\r\n", "\n"), count=1)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    units, cur, fence = [], [], False

    def flush():
        if cur:
            units.append("\n".join(cur).strip())
            del cur[:]
    for line in text.split("\n"):
        if line.strip().startswith("```"):
            if not fence:
                flush()
                fence = True
                cur.append(line)
            else:
                cur.append(line)
                fence = False
                flush()
            continue
        if fence:
            cur.append(line)
            continue
        if not line.strip():
            flush()
        elif _HEAD.match(line):
            flush()
        elif _LIST.match(line):
            flush()
            cur.append(line)
        else:
            cur.append(line)
    flush()
    return [u for u in units if u]


_CLOSERS = re.compile(r"^(?:[})\]]|fi\b|done\b|esac\b|else\b|elif\b|then\b|catch\b|finally\b|except\b|\.)")


def _code_line(line, ext):
    """The line with string contents and line comments blanked, for bracket counting."""
    out, i, n, q = [], 0, len(line), None
    while i < n:
        c = line[i]
        if q:
            if c == "\\":
                i += 2
                continue
            if c == q:
                q = None
            i += 1
            continue
        if c in "\"'`":
            q = c
        elif c == "#" and ext in (".py", ".sh", ".bash", ".zsh"):
            break
        elif c == "/" and line[i:i + 2] == "//" and ext in (".js", ".mjs", ".cjs"):
            break
        else:
            out.append(c)
        i += 1
    return "".join(out)


def code_units(text, ext):
    """Top-level functions and statements; comments and blank lines are not units."""
    if ext == ".json":
        return _json_units(text)
    py = ext == ".py"
    sh = ext in (".sh", ".bash", ".zsh")
    units, cur, depth = [], [], 0
    in_block = False
    in_triple = None
    in_tpl = False
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw
        stripped = line.strip()
        if in_block:
            if "*/" in line:
                in_block = False
            continue
        if in_triple:
            cur.append(raw)
            if in_triple in line:
                in_triple = None
            continue
        if in_tpl:
            cur.append(raw)
            if line.count("`") % 2 == 1:
                in_tpl = False
            continue
        if not stripped:
            continue
        if stripped.startswith("/*") and not py and not sh:
            if "*/" not in stripped:
                in_block = True
            continue
        if stripped.startswith("#") and (py or sh):
            continue
        if stripped.startswith("//") and not py and not sh:
            continue
        indent = len(line) - len(line.lstrip())
        starts_new = (indent == 0 and depth <= 0 and not _CLOSERS.match(stripped)
                      and not (py and re.match(r"(else|elif|except|finally)\b", stripped)))
        if starts_new:
            if cur:
                units.append("\n".join(cur))
            cur = [raw]
            depth = 0
        else:
            cur.append(raw)
        code = _code_line(line, ext)
        depth += sum(code.count(c) for c in "({[") - sum(code.count(c) for c in ")}]")
        if sh:
            if re.match(r"^\s*(if|for|while|case|until)\b", code) or re.search(r"\b(do|then)\s*$", code):
                pass
        for t in ('"""', "'''"):
            if py and line.count(t) % 2 == 1:
                in_triple = t
        if not py and line.count("`") % 2 == 1:
            in_tpl = True
    if cur:
        units.append("\n".join(cur))
    return [u.strip("\n") for u in units if u.strip()]


def _json_units(text):
    units, cur = [], []
    for line in text.replace("\r\n", "\n").split("\n"):
        if re.match(r'^ {2}"', line) or re.match(r"^\t\"", line):
            if cur:
                units.append("\n".join(cur))
            cur = [line]
        elif cur:
            cur.append(line)
    if cur:
        units.append("\n".join(cur))
    return [u for u in units if u.strip()]


# Plumbing (dev #835 phase 4c): a line that only imports a module, declares strict mode, or lists the
# names a module exports carries no behaviour and no person data, so it is not a unit. Without this a
# clean copy of a plugin tool scored PARTIAL on its import lines alone (see the first run in
# tests/fixtures/adopt/AS-FOUND.md and EXPECTED.md's stated refinement).
_PLUMBING = tuple(re.compile(p, re.S) for p in (
    r"^import\s+[\w.]+(?:\s+as\s+\w+)?(?:\s*,\s*[\w.]+(?:\s+as\s+\w+)?)*$",
    r"^from\s+[\w.]+\s+import\s+[\w\s,()*]+$",
    r"^(?:const|let|var)\s+[\w{},\s$:]+=\s*require\(\s*['\"][^'\"]+['\"]\s*\)\s*;?$",
    r"^import\s+(?:[\w{},\s*$]+\s+from\s+)?['\"][^'\"]+['\"]\s*;?$",
    r"^['\"]use strict['\"];?$",
    r"^set\s+-[A-Za-z]+(?:\s+\S+)*$",
    r"^module\.exports\s*=\s*\{[\w\s,:]*\}\s*;?$",
    r"^export\s*\{[\w\s,]*\}\s*;?$",
    r"^__all__\s*=\s*[\[(][^\])]*[\])]$",
))
_DOCSTRING = re.compile(r"^(?:\"{3}|'{3}).*(?:\"{3}|'{3})$", re.S)


def is_plumbing(unit):
    one = " ".join(unit.split())
    return any(r.match(one) for r in _PLUMBING)


def units_of(kind, path, text):
    if kind == "code":
        ext = posixpath.splitext(path)[1].lower()
        units = code_units(text, ext)
        if ext == ".py" and units and _DOCSTRING.match(units[0].strip()):
            units = units[1:]
        return [u for u in units if not is_plumbing(u)]
    return md_units(text)


# A driver statement (dev #835 phase 4c): a top-level statement that does nothing but call a function
# the same file defines is explained when that function's own unit is. A call to an unexplained
# function stays residual, so an extra renderer still counts.
_DEFS = (
    re.compile(r"^\s*(?:async\s+)?def\s+(\w+)"),
    re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s*\*?\s*(\w+)"),
    re.compile(r"^\s*(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>"),
    re.compile(r"^\s*(?:function\s+)?(\w+)\s*\(\)\s*\{"),
)


def defined_name(unit):
    first = unit.lstrip("\n").split("\n", 1)[0]
    for r in _DEFS:
        m = r.match(first)
        if m:
            return m.group(1)
    return None


def driver_explained(units, explained):
    """The indexes of unexplained units that only call explained functions defined in this file."""
    names = {}
    for i, u in enumerate(units):
        n = defined_name(u)
        if n:
            names[n] = i
    out = set()
    for i, u in enumerate(units):
        if explained[i] or defined_name(u):
            continue
        called = [n for n in names
                  if re.search(r"\b%s\s*\(|[(,]\s*%s\s*[,)]" % (re.escape(n), re.escape(n)), u)]
        if called and all(explained[names[n]] for n in called):
            out.add(i)
    return out


# ---------------------------------------------------------------- the tree (origin/main's blobs)

class Tree(object):
    """A commit's files, read with plumbing, plus the pending changes adopt will commit."""

    def __init__(self, repo, ref):
        self.repo = repo
        self.ref = ref
        out = git(repo, "ls-tree", "-r", "-z", "--full-tree", ref)
        self.entries = {}
        for rec in out.split(b"\0"):
            if not rec:
                continue
            meta, _, raw = rec.partition(b"\t")
            mode, typ, sha = meta.decode("ascii").split()
            path = raw.decode("utf-8", "surrogateescape")
            if typ == "blob":
                self.entries[path] = (mode, sha)
        self.writes = {}
        self.removed = set()
        self._cache = {}

    def paths(self):
        cur = set(self.entries) | set(self.writes)
        return sorted(cur - self.removed)

    def exists(self, path):
        return path in self.writes or (path in self.entries and path not in self.removed)

    def mode(self, path):
        if path in self.entries:
            return self.entries[path][0]
        return "100644"

    def read(self, path):
        if path in self.writes:
            return self.writes[path]
        if path in self.removed or path not in self.entries:
            raise KeyError(path)
        mode, sha = self.entries[path]
        if mode == "120000":
            return b""
        data = self._cache.get(sha)
        if data is None:
            data = self._cache[sha] = git(self.repo, "cat-file", "blob", sha)
        return data

    def text(self, path):
        return self.read(path).decode("utf-8", "replace")

    def write(self, path, data):
        if isinstance(data, str):
            data = data.encode("utf-8")
        self.writes[path] = data
        self.removed.discard(path)

    def remove(self, path):
        self.writes.pop(path, None)
        if path in self.entries:
            self.removed.add(path)


class TreeFiles(object):
    """The tree's `site/` and `content/` files, with adopt's pending page rewrites laid over them, as
    the read-only {repo path: bytes} mapping that `siteconfig.required_schema` and
    `content.layout_problems` take (they read no file themselves). Built lazily: nothing is read from
    git until a caller asks for a path's bytes."""

    def __init__(self, tree, overlay=None, removed=()):
        self.tree = tree
        self.overlay = dict((p, b) for p, b in (overlay or {}).items() if self._ours(p))
        self.removed = set(removed)
        self._keys = None

    @staticmethod
    def _ours(path):
        return path.startswith(("site/", "content/"))

    def _paths(self):
        if self._keys is None:
            self._keys = sorted((set(p for p in self.tree.paths() if self._ours(p)) | set(self.overlay))
                                - self.removed)
        return self._keys

    def __iter__(self):
        return iter(self._paths())

    def __len__(self):
        return len(self._paths())

    def __contains__(self, path):
        if path in self.removed:
            return False
        return path in self.overlay or (self._ours(path) and self.tree.exists(path))

    def __getitem__(self, path):
        if path in self.removed:
            raise KeyError(path)
        if path in self.overlay:
            return self.overlay[path]
        if self._ours(path):
            return self.tree.read(path)
        raise KeyError(path)

    def get(self, path, default=None):
        try:
            return self[path]
        except KeyError:
            return default


# ---------------------------------------------------------------- classification

def file_kind(path):
    parts = path.split("/")
    base = parts[-1]
    if "node_modules" in parts or base in (".DS_Store", "package-lock.json"):
        return None
    if path == "CLAUDE.md" or path == ".claude/settings.json":
        return "mixed"
    if parts[:2] == [".claude", "agents"] and len(parts) == 3 and base.endswith(".md"):
        return "agent"
    if parts[:2] == [".claude", "commands"] and len(parts) >= 3 and base.endswith(".md"):
        return "command"
    if parts[:2] == [".claude", "skills"] and len(parts) == 4 and base == "SKILL.md":
        return "skill"
    if parts[0] in ("scripts", "tools") and len(parts) >= 2:
        if posixpath.splitext(base)[1].lower() in CODE_EXTS:
            if base.lower().endswith(".json") and base != "package.json":
                return None
            return "code"
        return None
    if parts[0] == "site" and len(parts) == 2 and posixpath.splitext(base)[1].lower() in (".js", ".mjs", ".cjs"):
        return "code"
    return None


def classify_text(spec, path, kind, text, as_cap=None, shadows=None):
    """Classify one file. `shadows` is the set of this plugin's agent names (`shadow_names()` when None).

    NAMESAKES (dev #851, design 7.6). An agent file whose STEM equals a plugin agent's name is a
    SELF-MATCH when its score against that agent's capability (the capability id IS the agent's name:
    `test_adopt.RosterCapabilities` asserts it for every agent) is at or above `spec.match`. A self-match
    skips the AMBIGUOUS gap rule and is classified against that capability, DUPLICATE or PARTIAL by the
    residual rule, never AMBIGUOUS: the name is the one signal the platform acts on, but it is NEVER
    sufficient (the capability's name weight stays below `match`, `SpecShape`). A same-named file that is
    NOT a self-match keeps whatever class it earned and gains `namesake`: [capability id, score], however
    low the score; `candidates` keeps its one meaning (the capabilities at or above `match`)."""
    base = posixpath.basename(path)
    units = units_of(kind, path, text)
    scored = []
    for cid, cap in spec.caps.items():
        if as_cap is not None and cid != as_cap:
            continue
        if not _applicable(cap, kind, base):
            continue
        s, found = score_capability(spec, cap, text, base)
        scored.append((s, cid, found))
    scored.sort(key=lambda t: (-t[0], t[1]))
    info = {"path": path, "kind": kind, "units": len(units), "capability": None, "score": 0.0,
            "residual": 0.0, "residual_units": [], "signals": [], "class": "CUSTOM", "candidates": [],
            "needs_parity": False, "best": [(c, round(s, 2)) for s, c, _f in scored[:3]], "namesake": None}
    matches = [t for t in scored if t[0] >= spec.match - 1e-9]
    same = None
    if kind == "agent" and as_cap is None:
        stem = posixpath.splitext(base)[0]
        if stem in (shadows if shadows is not None else shadow_names()) and stem in spec.caps:
            same = stem
    self_hit = next((t for t in matches if t[1] == same), None) if same else None
    if same and self_hit is None:
        info["namesake"] = [same, round(next((s for s, c, _f in scored if c == same), 0.0), 2)]
    if not matches:
        return info
    top = self_hit or matches[0]
    if self_hit is None and as_cap is None and len(matches) > 1 and top[0] - matches[1][0] <= spec.gap + 1e-9:
        info["class"] = "AMBIGUOUS"
        info["candidates"] = [(c, round(s, 2)) for s, c, _f in matches]
        info["capability"] = top[1]
        info["score"] = top[0]
        return info
    cid = top[1]
    cap = spec.caps[cid]
    explainers = [s for s in cap["signals"] if not s.get("name")]
    explained = [any(_sig_found(spec, s, u, base) for s in explainers) for u in units]
    if kind == "code":
        for i in driver_explained(units, explained):
            explained[i] = True
    resid = [{"id": "u%d" % (i + 1), "text": u} for i, u in enumerate(units) if not explained[i]]
    ratio = (len(resid) / float(len(units))) if units else 0.0
    info.update(capability=cid, score=top[0], signals=top[2], residual=ratio, residual_units=resid,
                needs_parity=bool(cap.get("needsParity")))
    info["class"] = "DUPLICATE" if ratio <= spec.residual_max + 1e-9 else "PARTIAL"
    return info


def shadow_names(agents_dir=None):
    """The names of this plugin's own agents: a repo agent with one of these names outranks the plugin's.

    Read from the shipped `agents/` directory, not from `plugins/site-studio/spec/roster.json` (dev #835, gate-keeper G3):
    the roster is a maintenance file that is withheld from the package, so the old read returned an
    empty set on every install and the shadow warning silently never fired. An agents directory that
    is missing or holds no agent is a broken install and refuses loudly instead of reading as "no
    shadows"."""
    d = agents_dir or AGENTS_DIR
    try:
        names = {posixpath.splitext(n)[0] for n in os.listdir(d) if n.endswith(".md")}
    except OSError as e:
        raise RuntimeError("adopt cannot read the plugin's agents directory (%s): %s" % (d, e))
    if not names:
        raise RuntimeError("adopt found no agent in the plugin's agents directory (%s)" % d)
    return names


# The version the scoped-name claim below was measured on (probe P-A, tests/probes/PA-RESULT.md).
SCOPED_DISPATCH_MEASURED = "Claude Code 2.1.325"


def shadow_note(name):
    """The warning for a kept local agent named like one of this plugin's (design 7.6, dev #851). A project
    agent outranks a plugin agent of the same name, whatever the project agent does, so this is said for
    EVERY same-named agent that is kept. It states its own limit: adopt reads this repo's .claude/agents/
    only. The last sentence is the probe-P-A verdict (scoped-wins): the plugin's own review and ideas steps
    dispatch the agents by their scoped names, which reached the plugin's agent past a same-named project
    agent when measured; `test_routing.PluginAgentPrecedence` checks this text against that verdict."""
    return ("%s would replace site-studio's %s wherever it is called by its bare name, on this machine and on "
            "any machine this repo is cloned to. Rename it (suggested: %s-local) or remove it. This check "
            "covers this repo's .claude/agents/ only; a same-named agent in your own ~/.claude/agents/ on any "
            "computer also replaces it. site-studio's own review and ideas steps call it as site-studio:%s, "
            "which is not replaced (measured on %s)." % (name, name, name, name, SCOPED_DISPATCH_MEASURED))


def namesake_text(info):
    """How the inventory describes a same-named file next to its class, or None for any other file."""
    if info.get("namesake"):
        cid, score = info["namesake"]
        return "is named like site-studio's %s (score %s, below the match threshold)" % (cid, _fmt_pct(score))
    if info.get("shadows") and info.get("capability") == info["shadows"]:
        return "does the same job as site-studio's %s (score %s)" % (info["shadows"], _fmt_pct(info["score"]))
    return None


def shadow_suffix(info):
    """What the commit's Kept list adds after a kept file's reason when it shares a plugin agent's name."""
    if not info.get("shadows"):
        return ""
    return " (SHADOWS the plugin's %s agent: rename it to %s-local, or remove it)" % (info["shadows"], info["shadows"])


def inventory(tree, spec=None):
    """Classify every file adopt looks at. Returns a list of info dicts, sorted by path."""
    spec = spec or load_spec()
    shadows = shadow_names()
    out = []
    for path in tree.paths():
        kind = file_kind(path)
        if kind is None:
            continue
        if kind == "mixed":
            out.append({"path": path, "kind": kind, "class": "MIXED", "capability": None, "score": 0.0,
                        "residual": 0.0, "residual_units": [], "signals": [], "units": 0, "candidates": [],
                        "needs_parity": False, "best": [], "namesake": None, "shadows": None})
            continue
        info = classify_text(spec, path, kind, tree.text(path), shadows=shadows)
        info["shadows"] = None
        if kind == "agent":
            stem = posixpath.splitext(posixpath.basename(path))[0]
            if stem in shadows:
                info["shadows"] = stem                    # whatever its class: precedence ignores class (7.6)
        out.append(info)
    return out


def counterpart_of(spec, cid):
    return spec.data["descriptions"].get(cid, {}).get("counterpart", cid) if cid else "none"


# ---------------------------------------------------------------- preconditions

def example_site_json(tree):
    """The parsed examples-shaped site.json, or raises Refused naming /site-studio:setup."""
    why_setup = "; to start a new site run /site-studio:setup"
    if not tree.exists("site/site.json"):
        raise Refused("this repo has no site/site.json, so it was not built from the engine layout adopt "
                      "converts" + why_setup)
    try:
        data = json.loads(tree.text("site/site.json"))
    except ValueError:
        raise Refused("site/site.json is not valid JSON, so adopt cannot read it" + why_setup)
    if not isinstance(data, dict):
        raise Refused("site/site.json is not an object" + why_setup)
    if "schema" in data or "engine" in data:
        raise Refused("this repo is already converted (site/site.json has schema or engine); nothing to adopt")
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
        raise Refused("%s is not a git checkout" % repo)
    if git(repo, "remote", "get-url", "origin", check=False).returncode != 0:
        raise Refused("the repo has no 'origin' remote, so there is no origin/main to convert")
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
        if rec.startswith("??") and (path.startswith(".claude/worktrees/") or path == PLAN_REL):
            continue
        dirty.append(path)
    if dirty:
        raise Refused("the repo has uncommitted changes (%d paths, first: %s); commit or discard them first"
                      % (len(dirty), dirty[0]))
    return basis, tree, data


# ---------------------------------------------------------------- resume and paper size

_BOX = re.compile(rb"/MediaBox\s*\[\s*(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s*\]")


def _paper_of(w, h):
    a, b = sorted((w, h))
    if abs(a - 612) <= 5 and abs(b - 792) <= 5:
        return "Letter"
    if abs(a - 595.3) <= 5 and abs(b - 841.9) <= 5:
        return "A4"
    return None


def paper_from_pdf(data):
    """'Letter' or 'A4' from the PDF's plain-text MediaBox entries, else None (never a guess)."""
    sizes = set()
    for m in _BOX.finditer(data):
        x1, y1, x2, y2 = [float(v) for v in m.groups()]
        sizes.add(_paper_of(abs(x2 - x1), abs(y2 - y1)))
    if len(sizes) == 1 and None not in sizes:
        return sizes.pop()
    return None


def detect_resume(tree):
    md = pdf = None
    for cand in ("content/resume/resume.md", "content/resume.md"):
        if tree.exists(cand):
            md = cand
            break
    if md:
        pdf_c = posixpath.splitext(md)[0] + ".pdf"
        if tree.exists(pdf_c):
            pdf = pdf_c
    paper = None
    if pdf:
        paper = paper_from_pdf(tree.read(pdf))
    return {"md": md, "pdf": pdf, "paper": paper,
            "source": ("the MediaBox of %s" % pdf) if paper else None,
            "needsAnswer": bool(md) and paper is None}


# ---------------------------------------------------------------- tokens

_TOKEN = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
_KNOWN_TOKENS = ("siteUrl", "siteTitle", "name", "year", "root", "nav")
_LAYOUT_TOKENS = ("title", "pageTitle", "description", "content")
_OLD_TOKEN = re.compile(r"^([A-Za-z][A-Za-z0-9]*?)Link(?::([A-Za-z0-9_.-]+))?$")


def portfolio_folders(tree):
    names = set()
    for p in tree.paths():
        parts = p.split("/")
        if parts[0] == "content" and len(parts) >= 3:
            f = parts[1]
            if f in RESERVED_FOLDERS or f.startswith("_"):
                continue
            if f == "work" or (len(parts) == 3 and parts[2] == "page.md"):
                names.add(f)
    return sorted(names)


# `<a href="{{resumeLink}}">TEXT</a>`: the anchor whose href is exactly the old resume token (section 6.1)
_RESUME_ANCHOR = re.compile(r"<a\b([^>]*?)\bhref=([\"'])\{\{\s*resumeLink\s*\}\}\2([^>]*)>((?:(?!<a\b).)*?)</a>",
                            re.S | re.I)


def section_for_resume(inner):
    """The page section adopt writes around a resume anchor, for the inventory to show."""
    return "{{#page:resume}}%s{{/page}}" % inner


def rewrite_tokens(text, folders, layout=False):
    """(new text, [(old, new)], [unknown tokens]). Old site-specific `{{<folder>Link}}` forms become
    `{{link:<folder>}}`; an anchor whose href is exactly `{{resumeLink}}` becomes a `{{#page:resume}}`
    section (a link that is there when the resume is built and gone when it is not); anything else the
    plugin's build would refuse is listed, never guessed."""
    norm = dict((re.sub(r"[-_]", "", f).lower(), f) for f in folders)
    changes, unknown = [], []

    def anchor(m):
        old = m.group(0)
        new = section_for_resume('<a%shref=%s{{link:resume}}%s%s>%s</a>' % (
            m.group(1), m.group(2), m.group(2), m.group(3), m.group(4)))
        changes.append((old, new))
        return new
    text = _RESUME_ANCHOR.sub(anchor, text)

    def sub(m):
        tok = m.group(1).strip()
        if tok in _KNOWN_TOKENS or tok.startswith("link:") or (layout and tok in _LAYOUT_TOKENS):
            return m.group(0)
        if tok.startswith("#page:") or tok == "/page":      # a section marker, ours or the person's
            return m.group(0)
        om = _OLD_TOKEN.match(tok)
        if om:
            f = norm.get(om.group(1).lower())
            if f:
                new = "{{link:%s%s}}" % (f, "/" + om.group(2) if om.group(2) else "")
                changes.append((m.group(0), new))
                return new
        unknown.append(m.group(0))
        return m.group(0)
    return _TOKEN.sub(sub, text), changes, unknown


def token_files(tree):
    return [p for p in tree.paths() if (p.startswith("site/src/") and p.lower().endswith((".html", ".htm")))
            or p == "site/templates/layout.html"]


# ---------------------------------------------------------------- meta-refresh pages (design 7.5)

STUB_MAX_WORDS = 12     # the words a redirect page may carry in its paragraph and link ("This page has moved: continue")
_STUB_QUOTES = "\"'"


class _Stub(html.parser.HTMLParser):
    """What a page is made of, for the one question: is it NOTHING BUT a redirect? It records the
    refresh, the canonical link, the anchors, the scripts, and everything else it finds (`foreign`: a tag the
    list does not allow; `stray`: text outside a paragraph, a link, the title and a script)."""

    ALLOWED = ("html", "head", "body", "meta", "title", "link", "a", "p", "script")

    def __init__(self):
        html.parser.HTMLParser.__init__(self, convert_charrefs=True)
        self.refresh, self.canon, self.anchors, self.scripts = [], [], [], []
        self.title = ""
        self.foreign, self.stray, self.words, self.texts, self.bare_p = [], [], 0, [], []
        self._mode = None
        self._p = None
        self._in_a = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        a = dict((k.lower(), v or "") for k, v in attrs)
        if tag == "meta":
            if a.get("http-equiv", "").strip().lower() == "refresh":
                self.refresh.append(a.get("content", ""))
            elif not ("charset" in a or a.get("name", "").strip().lower() in ("viewport", "robots")):
                self.foreign.append("a <meta> that is not charset, viewport, robots or the refresh")
        elif tag == "link":
            if a.get("rel", "").strip().lower() == "canonical":
                self.canon.append(a.get("href", ""))
            else:
                self.foreign.append("a <link rel=%s>" % (a.get("rel", "") or "?"))
        elif tag == "a":
            self.anchors.append(a.get("href", ""))
            self._in_a += 1
            if self._p is not None:
                self._p["anchor"] = True
        elif tag == "p":
            self._p = {"text": [], "anchor": False}
        elif tag == "title":
            self._mode = "title"
        elif tag == "script":
            if "src" in a:
                self.foreign.append("a <script src>")
            self._mode = "script"
            self.scripts.append("")
        elif tag not in self.ALLOWED:
            self.foreign.append("a <%s>" % tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "a" and self._in_a:
            self._in_a -= 1
        elif tag == "p" and self._p is not None:
            p, self._p = self._p, None
            text = " ".join(" ".join(p["text"]).split())
            if text and not p["anchor"]:
                self.bare_p.append(text)
        elif tag in ("title", "script"):
            self._mode = None

    def handle_data(self, data):
        if self._mode == "title":
            self.title += data
        elif self._mode == "script":
            self.scripts[-1] += data
        elif self._p is not None or self._in_a:
            if self._p is not None:
                self._p["text"].append(data)
            self.words += len(data.split())
            self.texts.append(data)
        elif data.strip():
            self.stray.append(" ".join(data.split()))


_SCRIPT_GO = re.compile(r"""^\s*(?:window\.|self\.|top\.)?(?:location(?:\.href)?\s*=\s*|location\.(?:replace|assign)\s*\(\s*)"""
                        r"""(["'])(.*?)\1\s*\)?\s*;?\s*$""", re.S)


def page_key(rel):
    """The `redirects` key (and `{{#page:X}}` / link key) of a `site/src` page, the way the build serves it
    (`build._page_dir`): `old/index.html` is `old`, `old.html` is `old.html`, the root index is ''."""
    if rel in ("index.html", "index.htm"):
        return ""
    for tail in ("/index.html", "/index.htm"):
        if rel.endswith(tail):
            return rel[:-len(tail)]
    return rel


def _refresh_parts(content):
    """(delay seconds as a float or None, target string or None) from a refresh `content` value."""
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*(?:[;,]\s*(.*?))?\s*$", content or "", re.S)
    if not m:
        return None, None
    target = m.group(2)
    if target is not None:
        target = re.sub(r"^url\s*=\s*", "", target.strip(), flags=re.I).strip()
        if len(target) > 1 and target[0] in _STUB_QUOTES and target[-1] == target[0]:
            target = target[1:-1].strip()
    return float(m.group(1)), (target or None)


def resolve_redirect_target(page_rel, raw):
    """(value, None) or (None, reason). `value` is what a `redirects` entry holds for a refresh target as
    written on the page at `site/src/<page_rel>`: an `http(s)://` address as it stands, or the page key of
    a site-relative address resolved the way a browser would (against the page's own folder)."""
    t = (raw or "").strip()
    if re.match(r"^https?://", t):
        return t, None
    if not t:
        return None, "it names no address to go to"
    if t.startswith("//") or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", t):
        return None, "its target %s is neither a page on this site nor an http(s):// address" % t
    if "#" in t or "?" in t:
        return None, "its target %s carries a query or a fragment, which a redirects entry cannot" % t
    path = t.lstrip("/") if t.startswith("/") else posixpath.join(posixpath.dirname(page_rel), t)
    path = posixpath.normpath(path)
    if path == ".." or path.startswith("../"):
        return None, "its target %s points outside the site" % t
    if posixpath.basename(path) in ("index.html", "index.htm"):
        path = posixpath.dirname(path)
    if path in ("", "."):
        return None, ("its target is the home page, which a site.json redirects entry cannot name "
                      "(leave the page, or point it at a page)")
    return path, None


def _same_target(main, other):
    """True when `other` (a canonical link, an anchor, a script's address, already resolved) is `main`."""
    if other == main or other.rstrip("/") == main.rstrip("/"):
        return True
    web_m, web_o = main.startswith(("http://", "https://")), other.startswith(("http://", "https://"))
    if web_m != web_o:      # an absolute address that ends in the site-relative key (a base path ahead of it)
        url, key = (main, other) if web_m else (other, main)
        path = urlsplit(url).path
        if posixpath.basename(path) in ("index.html", "index.htm"):
            path = posixpath.dirname(path)
        path = path.strip("/")
        return path == key or path.endswith("/" + key)
    return False


def built_page_keys(tree, skip=()):
    """The page keys a `redirects` target may name in the converted tree: every `site/src` HTML page that
    stays, the portfolio folders and their pieces, about and resume. A target the plugin's build would not
    find is not in this set (an honest approximation: a page left out here is left as a hand page, never
    converted wrongly)."""
    keys = set()
    for p in tree.paths():
        if p.startswith("site/src/") and p.lower().endswith((".html", ".htm")) and p not in skip:
            keys.add(page_key(p[len("site/src/"):]))
    folders = portfolio_folders(tree)
    keys.update(folders)
    for p in tree.paths():
        parts = p.split("/")
        if len(parts) == 4 and parts[0] == "content" and parts[1] in folders and parts[3] == "index.md":
            keys.add("%s/%s" % (parts[1], parts[2]))
    if detect_resume(tree)["md"]:
        keys.add("resume")
    if tree.exists("content/about.md"):
        keys.add("about")
    return keys


RedirectPage = namedtuple("RedirectPage", "path key target dropped")


def _stub_verdict(rel, text):
    """None when the page is not a meta-refresh page at all; else ('left', reason) or ('ok', target value,
    the page text a conversion drops), before the checks that need the rest of the tree."""
    s = _Stub()
    try:
        s.feed(text)
        s.close()
    except Exception:       # a page the parser cannot read is content, never a redirect
        return None
    if not s.refresh:
        return None
    parts = [_refresh_parts(c) for c in s.refresh]
    if any(d is None or t is None for d, t in parts):
        return ("left", "its refresh names no address to go to, or is not read as `0; url=...`")
    if len(set(parts)) > 1:
        return ("left", "it holds more than one refresh")
    delay, raw = parts[0]
    if delay != 0:
        return ("left", "its refresh waits %g second(s), not 0, so the page is content a visitor reads" % delay)
    extra = (s.foreign[:1] or (["text outside its link: \"%s\"" % s.stray[0][:40]] if s.stray else [])
             or (["a paragraph of its own: \"%s\"" % s.bare_p[0][:40]] if s.bare_p else [])
             or (["more than %d words of text" % STUB_MAX_WORDS] if s.words > STUB_MAX_WORDS else []))
    if extra:
        return ("left", "it carries more than the redirect (%s)" % extra[0])
    value, why = resolve_redirect_target(rel, raw)
    if why:
        return ("left", why)
    for what, urls in (("its canonical link", s.canon), ("its link", s.anchors)):
        for u in urls:
            v, w = resolve_redirect_target(rel, u)
            if w or not _same_target(value, v):
                return ("left", "%s goes to %s, not to %s" % (what, u, raw))
    for code in s.scripts:
        m = _SCRIPT_GO.match(code)
        v = resolve_redirect_target(rel, m.group(2))[0] if m else None
        if v is None or not _same_target(value, v):
            return ("left", "its script does more than send the visitor to %s" % raw)
    title = " ".join(s.title.split())
    dropped = " ".join(x for x in ["" if title.lower() == "redirecting" else title, " ".join("".join(s.texts).split())] if x)
    return ("ok", value, dropped[:80])


def redirect_pages(tree, existing=None):
    """(convert, left) for every `site/src` page that carries a meta refresh (design 7.5). `convert` is a list
    of RedirectPage (path, redirects key, redirects value, the page text adopt drops); `left` is [(path, reason)]
    for a refresh page that stays a hand page. A page converts only when NOTHING else is on it, its key and
    target are ones `siteconfig` accepts, its target is a page the build will have (or an http(s) address) and
    `existing` (the site.json `redirects`) does not already send that key elsewhere."""
    existing = existing if isinstance(existing, dict) else {}
    cand, left = [], []
    for p in tree.paths():
        if not (p.startswith("site/src/") and p.lower().endswith((".html", ".htm"))):
            continue
        rel = p[len("site/src/"):]
        v = _stub_verdict(rel, tree.text(p))
        if v is None:
            continue
        if v[0] == "left":
            left.append((p, v[1]))
        elif posixpath.basename(rel) == "404.html":
            left.append((p, "it is the 404 page"))
        elif page_key(rel) == "":
            left.append((p, "it is the home page"))
        else:
            cand.append((p, page_key(rel), v[1], v[2]))
    moving = set(c[0] for c in cand)
    keys = built_page_keys(tree, skip=moving)
    convert = []
    for p, key, value, dropped in sorted(cand):
        try:
            siteconfig._redirect_entry(key, value)
        except siteconfig.SiteConfigError as e:
            left.append((p, str(e).replace("site.json: ", "", 1)))
            continue
        if not value.startswith(("http://", "https://")) and value not in keys:
            chained = any(c[1] == value for c in cand)
            left.append((p, "its target is another redirect page that adopt also converts" if chained else
                         "the build has no page '%s' to point it at" % value))
            continue
        if key in existing and existing[key] != value:
            left.append((p, "site.json already sends '%s' to '%s'" % (key, existing[key])))
            continue
        convert.append(RedirectPage(p, key, value, dropped))
    return convert, sorted(left)


def redirect_problems(convert):
    """One mechanical `siteconfig.Problem` per page adopt will turn into a redirects entry, so `check` and
    `inventory` list it beside the others, marked `apply fixes this`."""
    out = []
    for r in convert:
        out.append(siteconfig.make_problem(
            "%s is a meta-refresh page: it belongs in site.json redirects as '%s'" % (r.path, r.key),
            path=r.path, found="a hand-made meta-refresh page", expected="a site.json redirects entry",
            fix="move it into site.json redirects ('%s' -> '%s'); the build writes the page" % (r.key, r.target),
            mechanical=True))
    return out


# ---------------------------------------------------------------- features and the inferred kind (design 7.7)

Feature = namedtuple("Feature", "key signal sentence answer")

# ONE table: what the person's site does -> what that is called -> what the plugin does about it. A signal
# the inventory finds that has no row here prints the fallback line, so the table is what the inventory says.
FEATURES = (
    Feature("token:resumeLink", "{{resumeLink}}",
            "a resume link that disappears when there is no resume",
            "a page section, {{#page:resume}}...{{/page}}: adopt rewrites an anchor whose whole href is the "
            "token, and lists any other placement for you to wrap by hand"),
    Feature("featured-flag", "featured: true in a piece's front matter",
            "the home page shows pieces marked featured: true",
            "set \"featuredFrom\": \"flags\" in site/site.json (schema 2); adopt does not set it for you, "
            "because it changes which pieces the home page shows"),
    Feature("hand-home", "site/src/index.html with no content/home.md",
            "a hand-made home page",
            "kept as written: a site/src/index.html with no content/home.md is the home page (schema 2)"),
    Feature("meta-refresh", "a meta-refresh page under site/src",
            "an old address that forwards to a new one",
            "a site.json redirects entry: adopt converts the simple ones and lists the rest"),
    Feature("labels", "a [key, label] pair in work.meta, cardMeta or groups",
            "custom field names on piece pages",
            "the work.labels map (schema 2): adopt converts each pair and lists it"),
)

_TOKEN_NAME = {"resumeLink": "token:resumeLink"}
_FEATURED_FLAG = re.compile(r"^featured:\s*(?:true|yes)\s*(?:#.*)?$", re.I | re.M)


def detect_signals(tree, data, redirect_found=None):
    """[(key, where)] for every feature signal the person's tree carries (design 7.7). `key` is a FEATURES key,
    or `token:<the refused token>` for a local token the plugin's build would refuse; each appears once, with
    the first place it was seen."""
    seen, out = set(), []

    def add(key, where):
        if key not in seen:
            seen.add(key)
            out.append((key, where))
    folders = portfolio_folders(tree)
    for p in token_files(tree):
        text = tree.text(p)
        for m in _TOKEN.finditer(text):
            if m.group(1).strip() in _TOKEN_NAME:
                add(_TOKEN_NAME[m.group(1).strip()], p)
        for tok in rewrite_tokens(text, folders, layout=(p == "site/templates/layout.html"))[2]:
            add("token:" + re.sub(r"\s", "", tok), p)
    for p in tree.paths():
        if p.startswith("content/") and p.lower().endswith(".md") and not posixpath.basename(p).startswith("_"):
            m = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n", tree.text(p), re.S)
            if m and _FEATURED_FLAG.search(m.group(1)):
                add("featured-flag", p)
                break
    if tree.exists("site/src/index.html") and not tree.exists("content/home.md"):
        add("hand-home", "site/src/index.html")
    convert, left = redirect_found if redirect_found is not None else redirect_pages(tree, (data or {}).get("redirects"))
    if convert or left:
        add("meta-refresh", (convert[0].path if convert else left[0][0]))
    work = (data or {}).get("work")
    if isinstance(work, dict) and label_conversions(work)[1]:
        add("labels", "site/site.json")
    return out


def feature_lines(signals):
    """The inventory's feature list, one line per signal: the feature's sentence and the plugin's answer from
    FEATURES, or the fallback for a signal with no row."""
    table = dict((f.key, f) for f in FEATURES)
    out = []
    for key, where in signals:
        f = table.get(key)
        if f:
            out.append("  - %s (%s): %s" % (f.sentence, where, f.answer))
        elif key.startswith("token:"):
            out.append("  - a local token %s (%s); site-studio has no equivalent" % (key[len("token:"):], where))
        else:
            out.append("  - a local signal %s (%s); site-studio has no equivalent" % (key, where))
    return out


def infer_kind(tree):
    """(kind, why): the site kind adopt PROPOSES for the person to confirm (design 7.7). `portfolio` when
    `content/` has portfolio folders, a resume source or a `home.md` (only the portfolio build reads it), else
    `hub` when the links on `site/src/index.html` are mostly outbound, else `custom`."""
    folders = portfolio_folders(tree)
    resume = detect_resume(tree)["md"]
    if folders or resume or tree.exists("content/home.md"):
        what = ("portfolio folder%s %s" % ("s" if len(folders) > 1 else "", ", ".join(folders)) if folders else
                "a resume source (%s)" % resume if resume else "content/home.md")
        return "portfolio", "content/ holds %s" % what
    idx = "site/src/index.html"
    if tree.exists(idx):
        hrefs = [h.strip() for h in re.findall(r"""<a\b[^>]*?\bhref\s*=\s*["']([^"']*)["']""", tree.text(idx), re.I)]
        hrefs = [h for h in hrefs if h and not h.startswith(("#", "mailto:", "tel:", "{{"))]
        out = [h for h in hrefs if re.match(r"^(?:https?:)?//", h)]
        if hrefs and len(out) * 2 > len(hrefs):
            return "hub", "%d of the %d links on %s go to other sites" % (len(out), len(hrefs), idx)
        return "custom", "%s has %s" % (idx, "%d of %d links to other sites" % (len(out), len(hrefs)) if hrefs
                                         else "no links to read")
    return "custom", "there is no content/ portfolio and no site/src/index.html to read"


# ---------------------------------------------------------------- the plan (decisions only)

def empty_plan(base):
    return {"schema": PLAN_SCHEMA, "base": base, "files": {}, "facts": [], "paper": None, "parity": None,
            "folders": {}, "siteKind": None}


def parse_plan(text):
    try:
        d = json.loads(text)
    except ValueError as e:
        raise PlanError("adopt plan is not valid JSON: %s" % e)
    if not isinstance(d, dict):
        raise PlanError("adopt plan: the top level must be an object")
    allowed = ("schema", "base", "files", "facts", "paper", "parity", "folders", "siteKind")
    for k in d:
        if k not in allowed:
            raise PlanError("adopt plan: unknown key '%s'" % k)
    for k in allowed:
        if k not in d and k not in ("folders", "siteKind"):
            raise PlanError("adopt plan: '%s' is missing" % k)
    d.setdefault("folders", {})
    d.setdefault("siteKind", None)
    if d["siteKind"] not in (None,) + siteconfig.SITE_KINDS:
        raise PlanError("adopt plan: 'siteKind' must be null or one of %s" % ", ".join(siteconfig.SITE_KINDS))
    if not isinstance(d["folders"], dict):
        raise PlanError("adopt plan: 'folders' must be an object")
    for name, choice in d["folders"].items():
        if not re.match(r"^[^/\s]+$", name) or choice not in FOLDER_CHOICES:
            raise PlanError("adopt plan: folders[%r] must name one folder under content/ and be %s"
                            % (name, " or ".join("'%s'" % c for c in FOLDER_CHOICES)))
    if d["schema"] != PLAN_SCHEMA:
        raise PlanError("adopt plan: schema %r is not understood (this adopt reads %d)" % (d["schema"], PLAN_SCHEMA))
    if not isinstance(d["base"], str) or not re.match(r"^[0-9a-f]{40}$", d["base"]):
        raise PlanError("adopt plan: 'base' must be a 40-hex commit")
    if not isinstance(d["files"], dict):
        raise PlanError("adopt plan: 'files' must be an object")
    for path, f in d["files"].items():
        if not isinstance(f, dict):
            raise PlanError("adopt plan: files[%r] must be an object" % path)
        for k in f:
            if k not in ("removal", "as", "reviewed", "units"):
                raise PlanError("adopt plan: unknown key files[%r].%s" % (path, k))
        if f.get("removal") not in (None, "confirm", "keep"):
            raise PlanError("adopt plan: files[%r].removal must be null, 'confirm' or 'keep'" % path)
        if not isinstance(f.get("reviewed", False), bool):
            raise PlanError("adopt plan: files[%r].reviewed must be true or false" % path)
        if not isinstance(f.get("units", {}), dict):
            raise PlanError("adopt plan: files[%r].units must be an object" % path)
        for uid, u in f.get("units", {}).items():
            if not isinstance(u, dict) or u.get("disposition") not in UNIT_DISPOSITIONS:
                raise PlanError("adopt plan: files[%r].units[%r].disposition must be 'person-data', 'keep' or 'rule'"
                                % (path, uid))
            if u["disposition"] == "person-data" and u.get("kind") not in FACT_KINDS:
                raise PlanError("adopt plan: files[%r].units[%r].kind must be one of %s"
                                % (path, uid, ", ".join(FACT_KINDS)))
    if not isinstance(d["facts"], list):
        raise PlanError("adopt plan: 'facts' must be a list")
    for fa in d["facts"]:
        if (not isinstance(fa, dict) or fa.get("kind") not in FACT_KINDS or not isinstance(fa.get("text"), str)
                or not fa["text"].strip() or not isinstance(fa.get("source"), str)):
            raise PlanError("adopt plan: every fact needs a source, a kind (%s) and text" % ", ".join(FACT_KINDS))
    if d["paper"] not in (None, "Letter", "A4"):
        raise PlanError("adopt plan: 'paper' must be null, \"Letter\" or \"A4\"")
    if d["parity"] is not None:
        if not isinstance(d["parity"], dict) or d["parity"].get("verdict") not in (
                "EQUAL", "DIFFERENT", "UNVERIFIED", "ACCEPTED", "NOT APPLICABLE"):
            raise PlanError("adopt plan: 'parity.verdict' is not a known verdict")
    return d


def plan_path(repo):
    return os.path.join(repo, PLAN_REL)


def load_plan(repo):
    try:
        with open(plan_path(repo), "r", encoding="utf-8") as fh:
            return parse_plan(fh.read())
    except OSError:
        return None


def save_plan(repo, plan):
    parse_plan(json.dumps(plan))
    p = plan_path(repo)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(plan, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, p)


def _plan_for(repo, base):
    plan = load_plan(repo)
    if plan is None:
        return empty_plan(base)
    if plan["base"] != base:
        return empty_plan(base)
    return plan


# ---------------------------------------------------------------- parity helpers

class _Canon(html.parser.HTMLParser):
    VOID = ("area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param",
            "source", "track", "wbr")

    def __init__(self, ignored):
        html.parser.HTMLParser.__init__(self, convert_charrefs=True)
        self.out = []
        self.ignored = ignored

    def _skip(self, tag, attrs):
        d = dict((k, (v or "")) for k, v in attrs)
        if tag == "link" and "canonical" in d.get("rel", "").lower().split():
            return "link[rel=canonical]" in self.ignored["head"]
        if tag == "meta":
            if d.get("property", "").lower().startswith("og:"):
                return "meta[property^=og:]" in self.ignored["head"]
            if d.get("name", "").lower().startswith("twitter:"):
                return "meta[name^=twitter:]" in self.ignored["head"]
        return False

    def handle_starttag(self, tag, attrs):
        if self._skip(tag, attrs):
            return
        if tag == "img":
            attrs = [(k, v) for k, v in attrs if k not in self.ignored["img_attrs"]]
        parts = []
        for k, v in sorted(attrs, key=lambda kv: kv[0]):
            parts.append(k if v is None else '%s="%s"' % (k, v))
        self.out.append("<%s%s>" % (tag, (" " + " ".join(parts)) if parts else ""))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag not in self.VOID:
            self.out.append("</%s>" % tag)

    def handle_data(self, data):
        data = data.replace("\r\n", "\n")
        if not data.strip():
            if self.out and not self.out[-1] == " ":
                self.out.append(" ")
        else:
            self.out.append(data)

    def handle_decl(self, decl):
        self.out.append("<!%s>" % decl.lower())

    def handle_comment(self, data):
        pass


def normalise_html(text, ignored=None):
    """The comparison form of an HTML page (design 6.4.5): comments removed, whitespace between tags
    one space, attributes sorted within each tag, character references decoded, and the parts the
    plugin adds that the examples never wrote (PARITY_IGNORED) dropped. One token per line."""
    p = _Canon(ignored or PARITY_IGNORED)
    p.feed(text.replace("\r\n", "\n"))
    p.close()
    merged = []
    for t in p.out:
        if t == " " and merged and merged[-1] == " ":
            continue
        merged.append(t)
    while merged and merged[0] == " ":
        merged.pop(0)
    while merged and merged[-1] == " ":
        merged.pop()
    return "\n".join(t if t != " " else "<ws>" for t in merged)


def normalise_dates(text):
    for rx, repl in DATE_RULES:
        text = rx.sub(repl, text)
    return text


def normalise_file(rel, data):
    """A comparable form of one output file: normalised text, or the raw bytes for binary files."""
    low = rel.lower()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return data
    if low.endswith((".html", ".htm")):
        text = normalise_html(text)
    else:
        text = text.replace("\r\n", "\n")
    return normalise_dates(text).encode("utf-8")


def _walk(root):
    out = {}
    for d, _dirs, files in os.walk(root):
        for f in files:
            p = os.path.join(d, f)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, root).replace(os.sep, "/")] = fh.read()
    return out


def compare_builds(local, plugin, ignored=None):
    """Compare two {path: bytes} outputs after the stated exclusions and normalisation. Returns the
    list of differences: (kind, path, detail); empty means EQUAL."""
    ignored = ignored or PARITY_IGNORED
    skip = set(ignored["files"])
    a = dict((p, d) for p, d in local.items() if p not in skip)
    b = dict((p, d) for p, d in plugin.items() if p not in skip)
    diffs = []
    for p in sorted(set(a) - set(b)):
        diffs.append(("only in the local build", p, ""))
    for p in sorted(set(b) - set(a)):
        diffs.append(("only in the plugin build", p, ""))
    for p in sorted(set(a) & set(b)):
        if p.lower().endswith((".html", ".htm")):
            na = normalise_dates(normalise_html(a[p].decode("utf-8", "replace"), ignored)).encode("utf-8")
            nb = normalise_dates(normalise_html(b[p].decode("utf-8", "replace"), ignored)).encode("utf-8")
        else:
            na, nb = normalise_file(p, a[p]), normalise_file(p, b[p])
        if na != nb:
            la = na.decode("utf-8", "replace").split("\n")
            lb = nb.decode("utf-8", "replace").split("\n")
            first = ""
            for i in range(max(len(la), len(lb))):
                x = la[i] if i < len(la) else "(end)"
                y = lb[i] if i < len(lb) else "(end)"
                if x != y:
                    first = "line %d: local %r vs plugin %r" % (i + 1, x[:70], y[:70])
                    break
            diffs.append(("differs", p, first or "binary content differs"))
    return diffs


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
    skip = (".git", "node_modules", ".claude/worktrees", "site/dist")

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


def _converted_dict(tree, data, paper, kind=None):
    """The dict adopt would hand `siteconfig.parse_data`: the person's own site.json keys, plus the
    schema, the engine marker and `resume`, and the site kind the person CONFIRMED (design 7.7: `hub` or
    `custom` is written, `portfolio` is the default and is not, and nothing confirmed writes nothing). Its
    labels, if any, are still in the form they were written in. Returns (dict, detect_resume result)."""
    resume = detect_resume(tree)
    d = dict(data)
    d["schema"] = siteconfig.SCHEMA_MAX
    d["engine"] = siteconfig.ENGINE_MARKER
    if kind in ("hub", "custom"):
        d["siteKind"] = kind
    if resume["md"]:
        d["resume"] = {"path": resume["md"], "pdf": resume["pdf"], "paper": paper or resume["paper"] or "Letter"}
    else:
        d["resume"] = None
    return d, resume


def label_conversions(work):
    """Normalise a local site.json `work` object (design-site-adoption section 5): a `[key, label]`
    pair, or a `{"key": ..., "label": ...}` object, in `meta`, `cardMeta` or `groups` becomes the plain
    key, and its label goes into the sibling `labels` map. Returns (new work, [(where, found, key,
    label)]), one row per conversion, for the inventory and the commit to list. Anything that is not
    one of those two shapes is left alone for the parser to refuse."""
    if not isinstance(work, dict):
        return work, []
    out, conv = dict(work), []
    labels = {"meta": {}, "groups": {}}
    existing = work.get("labels")
    if isinstance(existing, dict):
        for part in siteconfig.LABEL_PARTS:
            if isinstance(existing.get(part), dict):
                labels[part].update(existing[part])
    for k in ("meta", "cardMeta", "groups"):
        v = work.get(k)
        if not isinstance(v, list):
            continue
        plain = []
        for i, item in enumerate(v):
            pl = None if isinstance(item, str) else siteconfig.pair_label(item)
            if pl is None:
                plain.append(item)
                continue
            key, label = pl
            labels["groups" if k == "groups" else "meta"].setdefault(key, label)
            conv.append(("work.%s[%d]" % (k, i), json.dumps(item), key, label))
            plain.append(key)
        out[k] = plain
    if conv:
        out["labels"] = dict((part, m) for part, m in labels.items() if m)
    return out, conv


def normalise_values(d):
    """The mechanical fixes to two site.json values (design 7.2), made IN PLACE on the dict adopt is about
    to parse: a `publicRepo` that is a GitHub clone URL becomes `owner/name` (through `github_url.slug`,
    the one normaliser, never re-parsed here), and a `previewUrl` ending `/` loses the slash. Anything
    else the parser objects to is not touched: it stays `you decide`. Returns [(key, old, new, line)];
    `line` is what the commit lists, with any credential in the old URL removed."""
    out = []
    pr = d.get("publicRepo")
    if isinstance(pr, str) and not siteconfig._REPO_RE.match(pr):
        try:
            slug = github_url.slug(pr)
        except github_url.GithubUrlError:
            slug = None
        if slug and siteconfig._REPO_RE.match(slug):
            d["publicRepo"] = slug
            out.append(("publicRepo", pr, slug, "publicRepo: %s -> %s" % (github_url.redact(pr), slug)))
    pu = d.get("previewUrl")
    if isinstance(pu, str) and pu.startswith("https://") and pu.endswith("/"):
        d["previewUrl"] = pu.rstrip("/")
        out.append(("previewUrl", pu, d["previewUrl"], "previewUrl: dropped trailing slash"))
    return out


def pageless_folders(tree_files, kind="portfolio"):
    """The names of the `content/` folders that have no `page.md` (T9), the way the content layer
    reports them (`layout_problems`, so adopt and the build cannot disagree on what counts)."""
    return [p.path[len("content/"):].rstrip("/")
            for p in site_content.layout_problems(tree_files, kind)
            if p.found == "no page.md" and p.path.startswith("content/")]


def _title_of(name):
    return re.sub(r"[-_]+", " ", name).strip().title() or name


def layout_changes(tree, choices, kind="portfolio"):
    """What adopt does about each `content/<f>/` that has no `page.md`, as the person decided (default
    `source`): ({path: bytes} written, [paths] removed, [(old, new, line)] listed). `source` MOVES the
    folder to `content/_<f>/` (not built; every byte kept); `portfolio` adds a `page.md` so it is one.
    Raises Refused for a decision that names no such folder, a destination that exists, or a symlink
    (a move would lose it)."""
    writes, removed, listed = {}, [], []
    names = pageless_folders(TreeFiles(tree), kind)
    for name in sorted(choices or {}):
        if name not in names:
            raise Refused("your decision names content/%s, which is not a folder without a page.md "
                          "(run `adopt.py inventory` again)" % name)
    for name in names:
        choice = (choices or {}).get(name, "source")
        folder = "content/%s/" % name
        if choice == "portfolio":
            writes[folder + "page.md"] = ("---\ntitle: %s\n---\n" % _title_of(name)).encode("utf-8")
            listed.append((folder, folder + "page.md", "content/%s: page.md added, so it is a portfolio" % name))
            continue
        dest = "content/_%s/" % name
        moving = [p for p in tree.paths() if p.startswith(folder)]
        if any(p.startswith(dest) for p in tree.paths()):
            raise Refused("content/_%s already exists, so content/%s cannot be renamed to it; move one of "
                          "them yourself first" % (name, name))
        for p in moving:
            if tree.mode(p) == "120000":
                raise Refused("%s is a symlink, which a rename would lose; move content/%s yourself" % (p, name))
            writes[dest + p[len(folder):]] = tree.read(p)
            removed.append(p)
        listed.append((folder, dest, "content/%s -> content/_%s (source material, not built)" % (name, name)))
    return writes, removed, listed


def converted_site_files(tree, data, paper, folders=None, kind=None):
    """{path: bytes} of site.json and the token-rewritten pages that the adopt transform produces;
    shared by apply and by the plugin side of parity. Returns (files, notes). site.json is written
    with the lowest schema the CONVERTED tree needs (a label map, a page section), so a plain site
    stays schema 1 and `notes["schema"]` / `notes["schemaReasons"]` say when it is not.

    The mechanical problems are fixed here (design 7.2): `notes["normalised"]` lists each changed
    value, `notes["labels"]` each label conversion, `notes["layout"]` each folder move or page.md, and
    `notes["removed"]` the paths a move takes away (a caller that writes `files` removes those too).
    `notes["olds"]` is [(what, old string)] for the kept-file search that warns a script may depend on
    the old form. `folders` is the person's {name: choice} for the folders without a page.md. A hand-made
    meta-refresh page that is nothing but a redirect becomes a `redirects` entry and is removed
    (design 7.5): `notes["redirects"]` lists each (a RedirectPage) and `notes["redirectsLeft"]` the refresh
    pages that stay, with the reason. `kind` is the site kind the person confirmed (design 7.7)."""
    files, notes = {}, {"tokens": [], "unknown": [], "resume": None, "labels": [], "schema": 1,
                        "schemaReasons": [], "normalised": [], "layout": [], "removed": [], "olds": [],
                        "redirects": [], "redirectsLeft": [], "kind": kind}
    d, resume = _converted_dict(tree, data, paper, kind)
    notes["resume"] = resume
    notes["normalised"] = normalise_values(d)
    if "work" in d:
        d["work"], notes["labels"] = label_conversions(d["work"])
    notes["redirects"], notes["redirectsLeft"] = redirect_pages(tree, d.get("redirects"))
    if notes["redirects"]:
        rd = dict(d["redirects"]) if isinstance(d.get("redirects"), dict) else {}
        rd.update((r.key, r.target) for r in notes["redirects"])
        d["redirects"] = rd
    try:
        cfg = siteconfig.parse_data(d)
    except siteconfig.SiteConfigError as e:
        raise Refused("the converted site.json is not valid: %s" % e)
    lw, notes["removed"], notes["layout"] = layout_changes(tree, folders, cfg.siteKind)
    files.update(lw)
    notes["removed"] = list(notes["removed"]) + [r.path for r in notes["redirects"]]
    names = portfolio_folders(tree) + sorted(n for n, c in (folders or {}).items() if c == "portfolio")
    for p in token_files(tree):
        if p in notes["removed"]:
            continue
        text = tree.text(p)
        new, ch, unk = rewrite_tokens(text, names, layout=(p == "site/templates/layout.html"))
        notes["tokens"].extend((p, a, b) for a, b in ch)
        notes["unknown"].extend((p, t) for t in unk)
        if new != text:
            files[p] = new.encode("utf-8")
    seen = TreeFiles(tree, files, notes["removed"])
    notes["schemaReasons"] = siteconfig.schema_2_reasons(cfg, seen)
    notes["schema"] = siteconfig.required_schema(cfg, seen)
    files["site/site.json"] = siteconfig.canonical_text(cfg, seen).encode("utf-8")
    for key, old, _new, _line in notes["normalised"]:
        notes["olds"].append((key, old))
    for old, new, _line in notes["layout"]:
        if not new.endswith("/page.md"):               # a move: a script may name the old folder path
            notes["olds"].append(("folder", old.rstrip("/")))
    return files, notes


def old_form_hits(tree, olds, skip=("site/site.json",)):
    """[(path, line number, old string, what)]: where a file the person KEEPS still holds a value adopt
    replaced (design 7.2: "your own script may depend on the old form"). The search is a literal substring
    over the tree as it will stand after apply (so a retired copy is not searched), in text files only, and
    a hit must end where the value ends (`content/news` is not found inside `content/newsletter`). The
    first match on a line is the hit."""
    hits = []
    pats = [(what, old, re.compile(re.escape(old) + r"(?![A-Za-z0-9_-])")) for what, old in olds if old]
    if not pats:
        return hits
    for p in tree.paths():
        if p in skip or p.startswith(("site/dist/", ".git/", ".site-studio/")) or "node_modules" in p.split("/"):
            continue
        base = posixpath.basename(p)
        ext = posixpath.splitext(base)[1].lower()
        if ext and ext not in _TEXT_EXTS:
            continue
        if tree.mode(p) == "120000":
            continue
        try:
            raw = tree.read(p)
        except KeyError:
            continue
        if len(raw) > _TEXT_MAX or b"\0" in raw:
            continue
        for n, line in enumerate(raw.decode("utf-8", "replace").split("\n"), 1):
            for what, old, rx in pats:
                if old in line and rx.search(line):
                    hits.append((p, n, old, what))
    return hits


def site_problems(tree, data, paper=None, kind=None):
    """Every problem in what adopt WOULD write, all at once: `siteconfig.problems()` over the
    converted site.json (BEFORE the mechanical label conversion, so a pair-form label is reported and
    marked `apply fixes this`), then `content.layout_problems()` over the tree. A list of
    `siteconfig.Problem`; empty means nothing stands in the way (design section 7.1). A meta-refresh page
    adopt will turn into a redirect is one more mechanical problem (design 7.5)."""
    d, _resume = _converted_dict(tree, data, paper, kind)
    probs = list(siteconfig.problems(d))
    cfg = None
    if not probs:
        try:
            cfg = siteconfig.parse_data(d)
        except siteconfig.SiteConfigError:
            cfg = None
    else:
        fixed = dict(d)
        if "work" in fixed:
            fixed["work"], _conv = label_conversions(fixed["work"])
        try:
            cfg = siteconfig.parse_data(fixed)
        except siteconfig.SiteConfigError:
            cfg = None
    files = {}
    for p in token_files(tree):
        text = tree.text(p)
        new = rewrite_tokens(text, portfolio_folders(tree), layout=(p == "site/templates/layout.html"))[0]
        if new != text:
            files[p] = new.encode("utf-8")
    probs += site_content.layout_problems(TreeFiles(tree, files), cfg.siteKind if cfg else "portfolio", cfg)
    probs += redirect_problems(redirect_pages(tree, d.get("redirects"))[0])
    return probs


def format_problems(probs):
    """The lines `check` and `inventory` print for a list of problems."""
    if not probs:
        return []
    fixes = sum(1 for p in probs if p.mechanical)
    L = ["%d problem(s) in what adopt would write: apply fixes %d, you decide %d" % (len(probs), fixes,
                                                                                  len(probs) - fixes)]
    L += ["  - %s" % p.line() for p in probs]
    return L


def problem_dicts(probs):
    return [{"path": p.path, "found": p.found, "expected": p.expected, "fix": p.fix,
             "mechanical": p.mechanical, "message": p.message} for p in probs]


def run_parity(repo, infos, basis, tree, data, which=None, run=None, folders=None, kind=None):
    """Build both ways and compare (named change M13). Returns a dict with `verdict`
    (EQUAL / DIFFERENT / UNVERIFIED / NOT APPLICABLE), `reason`, `differences`, `notes`.

    BOTH SIDES COME FROM `basis.sha` (dev #855, design 7.3): the local builder runs on a copy of the working
    copy, which must hold `basis.sha`'s tree, and the plugin side is built from `basis.sha`'s committed files
    with the adopt transform. A basis that is not buildable (`basis.reason`: HEAD diverged from, or behind,
    origin/main) is UNVERIFIED up front."""
    base = basis.sha
    res = {"verdict": "UNVERIFIED", "reason": "", "differences": [], "notes": []}
    entry = builder_entry(infos)
    if entry is None:
        res.update(verdict="NOT APPLICABLE", reason="no local builder was found (no JavaScript file classified as a builder)")
        return res
    if basis.reason:
        res["reason"] = "%s; the builder is kept" % basis.reason
        return res
    node = (which or shutil.which)("node")
    if not node:
        res["reason"] = "no Node on this computer, so the local builder cannot run; the builder is kept"
        return res
    if gitt(repo, "rev-parse", "HEAD^{tree}", check=False) != gitt(repo, "rev-parse", base + "^{tree}"):
        res["reason"] = ("the working copy differs from the parity basis %s %s (parity builds the working copy, "
                         "which must be what the basis holds); the builder is kept" % (basis.label(), base[:7]))
        return res
    ignored_present = gitt(repo, "ls-files", "-o", "-i", "--exclude-standard", "--directory", check=False).split("\n")
    ignored_present = [p for p in ignored_present if p and not p.startswith(("node_modules", "site/dist", ".claude/worktrees"))]
    res["notes"].append("the local build ran on a COPY of the working copy of %s %s, which includes ignored files%s"
                        % (basis.label(), base[:7],(" (present: %s)" % ", ".join(ignored_present[:6])) if ignored_present else " (none present)"))
    scratch = tempfile.mkdtemp(prefix="adopt-parity-")
    try:
        a_dir = os.path.join(scratch, "local")
        _copy_working_copy(repo, a_dir)
        shutil.rmtree(os.path.join(a_dir, "site", "dist"), ignore_errors=True)
        guard = os.path.join(scratch, "guard.js")
        with open(guard, "w", encoding="utf-8") as fh:
            fh.write(_NET_BLOCK)
        env = scrubbed_env(os.path.join(scratch, "home"), node)
        os.makedirs(env["HOME"], exist_ok=True)
        try:
            p = subprocess.run([node, "-r", guard, entry], cwd=a_dir, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, timeout=120)
        except subprocess.TimeoutExpired:
            res["reason"] = "the local builder did not finish in 120 seconds; the builder is kept"
            return res
        if p.returncode != 0:
            err = [l for l in p.stderr.decode("utf-8", "replace").strip().split("\n") if l.strip()]
            why = next((l for l in err if re.search(r"error", l, re.I)), err[-1] if err else "")
            res["reason"] = "the local builder failed (exit %d: %s); the builder is kept" % (p.returncode, why.strip()[:120])
            return res
        local_out = os.path.join(a_dir, "site", "dist")
        if not os.path.isdir(local_out):
            res["reason"] = "the local builder wrote no site/dist; the builder is kept"
            return res
        local = _walk(local_out)
        # the plugin side: committed files of origin/main + the adopt transform, in a fresh repo
        b_dir = os.path.join(scratch, "plugin")
        os.makedirs(b_dir)
        _archive_to(repo, base, b_dir)
        date = gitt(repo, "log", "-1", "--format=%cI", base)
        ident = {"GIT_AUTHOR_NAME": "adopt parity", "GIT_AUTHOR_EMAIL": "parity@example.invalid",
                 "GIT_COMMITTER_NAME": "adopt parity", "GIT_COMMITTER_EMAIL": "parity@example.invalid",
                 "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date, "GIT_CONFIG_NOSYSTEM": "1",
                 "GIT_CONFIG_GLOBAL": os.devnull}
        git(b_dir, "init", "-q", "-b", "main", env=ident)
        git(b_dir, "add", "-A", "-f", ".", env=ident)
        git(b_dir, "commit", "-q", "-m", "origin/main", "--allow-empty", env=ident)
        files, cnotes = converted_site_files(tree, data, None, folders, kind)
        for rel in cnotes["removed"]:
            try:
                os.remove(os.path.join(b_dir, rel))
            except OSError:
                pass
        for rel, blob in files.items():
            os.makedirs(os.path.dirname(os.path.join(b_dir, rel)), exist_ok=True)
            with open(os.path.join(b_dir, rel), "wb") as fh:
                fh.write(blob)
        cfg = siteconfig.parse_text(files["site/site.json"].decode("utf-8"))
        if cfg.resume and cfg.resume.get("pdf") and os.path.isfile(os.path.join(b_dir, cfg.resume["pdf"])):
            side = os.path.join(b_dir, cfg.resume["pdf"] + ".json")
            if not os.path.exists(side):
                sha = lambda p: hashlib.sha256(open(os.path.join(b_dir, p), "rb").read()).hexdigest()  # noqa: E731
                with open(side, "w", encoding="utf-8") as fh:
                    json.dump({"source_sha256": sha(cfg.resume["path"]), "pdf_sha256": sha(cfg.resume["pdf"]),
                               "text_sha256": "0" * 64}, fh)
                res["notes"].append("the plugin side was given the resume PDF sidecar the examples never wrote")
        git(b_dir, "add", "-A", "-f", ".", env=ident)
        git(b_dir, "commit", "-q", "-m", "adopt transform", "--allow-empty", env=ident)
        import build as _build  # noqa: E402
        out_dir = os.path.join(scratch, "plugin-out")
        try:
            _build.publish_build(b_dir, out_dir)
        except _build.BuildError as e:
            res["reason"] = "the plugin's build refused this repo (%s); the builder is kept" % e
            return res
        diffs = compare_builds(local, _walk(out_dir))
        res["differences"] = diffs
        res["verdict"] = "EQUAL" if not diffs else "DIFFERENT"
        res["reason"] = "the two builds are equal after the stated exclusions and normalisation" if not diffs else \
            "%d difference(s)" % len(diffs)
        return res
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


# ---------------------------------------------------------------- settings.json and hooks

_PATH_TOKEN = re.compile(r"(?<![\w./}$-])(?:\$\{?CLAUDE_PROJECT_DIR\}?/|\./)?((?:scripts|tools|site|\.claude)/[A-Za-z0-9_.@+-]+(?:/[A-Za-z0-9_.@+-]+)*)")
_SEGMENT_SPLIT = re.compile(r"\s*(?:;|&&|\|\|)\s*")
_INTERP = re.compile(r"^(?:(?:bash|sh|zsh|node|python3?)\s+)?(?:\$\{?CLAUDE_PROJECT_DIR\}?/|\./)?")


def _segments(command):
    return [s for s in _SEGMENT_SPLIT.split(command) if s.strip()]


def merge_settings(text, starter_text):
    """The person's settings plus the plugin's registration and ask rules (design 6.3). Keeps every
    key and rule already there. Returns the settings dict (hooks untouched)."""
    cur = json.loads(text) if text else {}
    st = json.loads(starter_text)
    cur.setdefault("extraKnownMarketplaces", {})
    for k, v in st["extraKnownMarketplaces"].items():
        cur["extraKnownMarketplaces"].setdefault(k, v)
    cur.setdefault("enabledPlugins", {})
    for k, v in st["enabledPlugins"].items():
        cur["enabledPlugins"].setdefault(k, v)
    perms = cur.setdefault("permissions", {})
    ask = perms.setdefault("ask", [])
    for rule in st["permissions"]["ask"]:
        if rule not in ask:
            ask.append(rule)
    return cur


def process_hooks(settings, removed, cap_of, spec):
    """Handle hook commands that name a removed file. Returns (settings, listed, blocked) where
    `listed` is [(event, old command, new command or None)] and `blocked` the set of removed paths
    that a remaining hook still needs (they must be kept)."""
    listed, blocked = [], set()
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return settings, listed, blocked
    for event in list(hooks):
        groups = hooks[event]
        if not isinstance(groups, list):
            continue
        new_groups = []
        for g in groups:
            if not isinstance(g, dict) or not isinstance(g.get("hooks"), list):
                new_groups.append(g)
                continue
            kept = []
            for h in g["hooks"]:
                cmd = h.get("command") if isinstance(h, dict) else None
                if not isinstance(cmd, str):
                    kept.append(h)
                    continue
                new_segs, changed = [], False
                for seg in _segments(cmd):
                    m = [x for x in _PATH_TOKEN.finditer(seg) if x.group(1) in removed]
                    if not m:
                        new_segs.append(seg)
                        continue
                    path = m[0].group(1)
                    cap = spec.caps.get(cap_of.get(path) or "", {})
                    if cap.get("hook") == "plugin":
                        changed = True
                        continue
                    if cap.get("hook") == "rewrite" and cap.get("script"):
                        script = 'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/%s"' % cap["script"]
                        new_segs.append(_rewrite_segment(seg, m[0], script))
                        changed = True
                        continue
                    blocked.add(path)
                    new_segs.append(seg)
                if changed:
                    new = "; ".join(new_segs)
                    listed.append((event, cmd, new or None))
                    if new:
                        h2 = dict(h)
                        h2["command"] = new
                        kept.append(h2)
                else:
                    kept.append(h)
            if kept:
                g2 = dict(g)
                g2["hooks"] = kept
                new_groups.append(g2)
        if new_groups:
            hooks[event] = new_groups
        else:
            del hooks[event]
    if not hooks:
        del settings["hooks"]
    return settings, listed, blocked


def _rewrite_segment(seg, m, script):
    """Replace `<interpreter> <path>` with the plugin script, keeping the arguments."""
    start = m.start()
    pre = seg[:start]
    im = re.search(r"(?:bash|sh|zsh|node|python3?)\s+$", pre)
    if im:
        start = im.start()
    return seg[:start] + script + seg[m.end():]


def dangling_hook_paths(settings, post_paths):
    """Repo paths named by remaining hook commands that are absent from the new tree."""
    out = []
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return out
    for event, groups in hooks.items():
        for g in groups if isinstance(groups, list) else []:
            for h in (g.get("hooks") or []) if isinstance(g, dict) else []:
                cmd = h.get("command") if isinstance(h, dict) else None
                if isinstance(cmd, str):
                    for m in _PATH_TOKEN.finditer(cmd):
                        if m.group(1) not in post_paths:
                            out.append((event, m.group(1)))
    return out


# ---------------------------------------------------------------- CLAUDE.md

_ENGINE_HEADING = re.compile(
    r"\b(repo split|layout|team|agents?|publish(ing)?|gates?|environment|set-?up|deploy(ment)?|build(ing)?|commands?|"
    r"workflow|how (this|it) works|engine|tools|checks?|trees?|branching|landing)\b", re.I)


def transform_claude_md(text):
    """Keep every section about the person; replace the engine sections (the examples' repo split,
    layout, team, publishing, gates, environment...) with one pointer to the plugin and the S8 line.
    A level-1 title and any text before the first heading are kept. Returns the new text."""
    lines = text.replace("\r\n", "\n").split("\n")
    out, i, n = [], 0, len(lines)
    pointer_done = False
    pointer = ["This repo's build, checks, publishing and review tools come from the site-studio plugin.", "",
               POINTER_LINE, ""]
    cur_level = None
    skipping = False
    skip_level = 0
    for line in lines:
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            if skipping and level <= skip_level:
                skipping = False
            if not skipping and level >= 2 and _ENGINE_HEADING.search(m.group(2)):
                skipping, skip_level = True, level
                if not pointer_done:
                    out.extend(pointer)
                    pointer_done = True
                continue
        if skipping:
            continue
        if POINTER_LINE in line:
            pointer_done = True
        out.append(line)
    body = "\n".join(out).rstrip("\n")
    if not pointer_done:
        body = body + "\n\n" + "\n".join(pointer).rstrip("\n")
    return body.rstrip("\n") + "\n"


def append_rules(text, rules):
    """Carry each `rule` unit, verbatim, into CLAUDE.md under RULES_HEADING with the path it came from
    (design 10). The heading is added when it is missing; when it is already there the new blocks go at the end
    of ITS section. Returns the new text (unchanged when there is nothing to carry)."""
    if not rules:
        return text
    blocks = "".join("\n### From %s\n\n%s\n" % (r["source"], r["text"].strip("\n")) for r in rules)
    body = text if text.endswith("\n") else text + "\n"
    m = re.search(r"^%s[ \t]*$" % re.escape(RULES_HEADING), body, re.M)
    if not m:
        return body + "\n" + RULES_HEADING + "\n" + blocks
    nxt = re.compile(r"^## ", re.M).search(body, m.end())
    cut = nxt.start() if nxt else len(body)
    return body[:cut].rstrip("\n") + "\n" + blocks + ("\n" + body[cut:] if nxt else "")


# ---------------------------------------------------------------- .gitignore, facts, handoff

def update_gitignore(text):
    have = set(l.strip().strip("/") for l in text.split("\n") if l.strip() and not l.strip().startswith("#"))
    add = [l for l in GITIGNORE_LINES if l.strip("/") not in have]
    if not add:
        return text, []
    body = text if (not text or text.endswith("\n")) else text + "\n"
    return body + "".join(l + "\n" for l in add), add


def _next_decision_number(tree):
    nums = []
    for p in tree.paths():
        m = re.match(r"^decisions/(\d{2,})-", p)
        if m:
            nums.append(int(m.group(1)))
    return (max(nums) + 1) if nums else 1


def _slug(s):
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s or "rule"


def write_facts(tree, facts, date):
    """Data files first: append each fact under a heading naming its source file and the date.
    Returns [(source, target)]."""
    moved = []
    by_target = {}
    rule_files = {}
    for fa in facts:
        if fa["kind"] == "context":
            target = "decisions/00-context.md"
        elif fa["kind"] == "voice":
            target = "BRAND.md"
        else:
            name = _slug(fa.get("name") or "rule")
            if name not in rule_files:
                rule_files[name] = "decisions/%02d-%s.md" % (_next_decision_number(tree) + len(rule_files), name)
            target = rule_files[name]
        by_target.setdefault(target, {}).setdefault(fa["source"], []).append(fa["text"].strip())
    for target in sorted(by_target):
        if tree.exists(target):
            body = tree.text(target)
            body = body if body.endswith("\n") else body + "\n"
        else:
            title = {"decisions/00-context.md": "# Context\n", "BRAND.md": "# Brand\n"}.get(
                target, "# %s\n" % posixpath.splitext(posixpath.basename(target))[0].split("-", 1)[-1].replace("-", " ").title())
            body = title
        for source in sorted(by_target[target]):
            body += "\n## From %s (%s)\n\n" % (source, date)
            for t in by_target[target][source]:
                body += "- %s\n" % t.replace("\n", " ")
            moved.append((source, target))
        tree.write(target, body)
    return moved


# ---------------------------------------------------------------- the commit (plumbing only)

def commit_branch(repo, tree, base, branch, message):
    """One commit on a NEW branch, from `base`, containing `tree`'s pending writes and removals.
    Uses a private index and plumbing: the person's index, working tree and HEAD are untouched."""
    if git(repo, "show-ref", "--verify", "--quiet", "refs/heads/" + branch, check=False).returncode == 0:
        raise Refused("the branch %s already exists; delete it or pass another --date" % branch)
    tmp = tempfile.mkdtemp(prefix="adopt-index-")
    try:
        env = {"GIT_INDEX_FILE": os.path.join(tmp, "index")}
        git(repo, "read-tree", base, env=env)
        lines = []
        for path in sorted(tree.removed):
            if "\n" in path or "\t" in path:
                raise Refused("a path contains a tab or newline: %r" % path)
            lines.append("0 %s\t%s" % ("0" * 40, path))
        for path in sorted(tree.writes):
            if "\n" in path or "\t" in path:
                raise Refused("a path contains a tab or newline: %r" % path)
            sha = git(repo, "hash-object", "-w", "--stdin", input=tree.writes[path]).decode().strip()
            lines.append("%s %s\t%s" % (tree.mode(path), sha, path))
        if lines:
            git(repo, "update-index", "--index-info", input=("\n".join(lines) + "\n").encode("utf-8"), env=env)
        new_tree = git(repo, "write-tree", env=env).decode().strip()
        who = git(repo, "var", "GIT_COMMITTER_IDENT", check=False)
        if who.returncode != 0:
            raise Refused("git has no committer identity; set user.name and user.email and run apply again")
        commit = git(repo, "commit-tree", new_tree, "-p", base, "-m", message).decode().strip()
        git(repo, "update-ref", "refs/heads/" + branch, commit, "")
        return commit
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- apply

def _fmt_pct(x):
    return "%.2f" % x


def prepare(repo, date, spec=None):
    """Everything apply will commit, computed without writing anything. Raises Refused."""
    spec = spec or load_spec()
    basis, tree, data = preconditions(repo)
    base = basis.sha
    try:
        plan = load_plan(repo)
    except PlanError as e:
        raise Refused(str(e))
    if plan is None:
        raise Refused("there is no plan yet; run `adopt.py inventory` and make your decisions first")
    if plan["base"] != base:
        raise Refused("the parity basis moved since the inventory (%s -> %s); run `adopt.py inventory` again"
                      % (plan["base"][:7], base[:7]))
    infos = inventory(tree, spec)
    by_path = dict((i["path"], i) for i in infos)
    decisions = plan["files"]
    # 1. every file proposed for removal needs a decision
    undecided = [i["path"] for i in infos if i["class"] in ("DUPLICATE", "PARTIAL", "AMBIGUOUS")
                 and (decisions.get(i["path"]) or {}).get("removal") is None]
    if undecided:
        raise Refused("no decision yet for %d file(s), first %s: run `adopt.py confirm <path>` or `--keep`"
                      % (len(undecided), undecided[0]))
    resume = detect_resume(tree)
    paper = plan["paper"] or resume["paper"]
    if resume["needsAnswer"] and paper is None:
        raise NeedsAnswer("resume.paper needs your answer: there is no resume PDF to read the paper size from; "
                          "run `adopt.py paper Letter` or `adopt.py paper A4`")
    removals, kept, facts, reasons, unit_facts, rule_units = {}, [], [], {}, [], []
    parity = plan["parity"]
    for i in infos:
        d = decisions.get(i["path"]) or {}
        cls = i["class"]
        if cls in ("CUSTOM", "MIXED"):
            if cls == "CUSTOM":
                kept.append((i["path"], "no plugin counterpart" + shadow_suffix(i)))
            continue
        if d.get("removal") == "keep":
            kept.append((i["path"], "kept by your decision (%s, score %s)" % (cls, _fmt_pct(i["score"]))
                         + shadow_suffix(i)))
            continue
        # a decision to remove
        eff = i
        if cls == "AMBIGUOUS":
            if not d.get("as"):
                raise Refused("%s is AMBIGUOUS between %s: say which with `adopt.py confirm %s --as <capability>`"
                              % (i["path"], " and ".join(c for c, _s in i["candidates"]), i["path"]))
            eff = classify_text(spec, i["path"], i["kind"], tree.text(i["path"]), as_cap=d["as"])
            if eff["capability"] is None:
                raise Refused("%s does not match %s" % (i["path"], d["as"]))
        prose = i["kind"] in ("agent", "command", "skill")
        if prose:
            if not d.get("reviewed"):
                raise Refused("the facts in %s are unreviewed: read it, record what is yours with `adopt.py "
                              "unit`/`fact`, then run `adopt.py reviewed %s`; nothing is removed before its facts "
                              "are moved" % (i["path"], i["path"]))
            for u in eff["residual_units"]:
                ud = (d.get("units") or {}).get(u["id"])
                if ud is None:
                    raise Refused("%s: unit %s is not dispositioned (person data, or behaviour to keep): %s"
                                  % (i["path"], u["id"], u["text"].split("\n")[0][:60]))
                if ud["disposition"] == "keep":
                    raise Refused("%s: unit %s is marked keep, so the file stays; run `adopt.py confirm %s --keep`"
                                  % (i["path"], u["id"], i["path"]))
                if ud["disposition"] == "rule":
                    rule_units.append({"source": i["path"], "id": u["id"], "text": u["text"]})
                    continue
                unit_facts.append({"source": i["path"], "kind": ud["kind"], "text": u["text"], "name": ud.get("name")})
        else:
            if spec.caps[eff["capability"]].get("needsParity"):
                if not parity or parity["verdict"] not in ("EQUAL", "ACCEPTED"):
                    raise Refused("%s is a local builder file and parity is %s: it stays (run `adopt.py parity`)"
                                  % (i["path"], (parity or {}).get("verdict", "not run")))
            elif eff["class"] == "PARTIAL":
                raise Refused("%s is PARTIAL (residual %s) and nothing says its extra behaviour is safe to drop: "
                              "run `adopt.py confirm %s --keep`" % (i["path"], _fmt_pct(eff["residual"]), i["path"]))
        removals[i["path"]] = eff
        reasons[i["path"]] = ("matched by what it does: %s (score %s, residual %s; signals: %s)"
                              % (eff["capability"], _fmt_pct(eff["score"]), _fmt_pct(eff["residual"]),
                                 ", ".join(eff["signals"])))
    for fa in plan["facts"]:
        if fa["source"] in removals:
            facts.append(fa)
    facts = unit_facts + facts
    # 2. data files first
    moved = write_facts(tree, facts, date)
    # 3. config second
    changes = []
    site_files, notes = converted_site_files(tree, data, plan["paper"], plan["folders"], plan.get("siteKind"))
    for p, blob in sorted(site_files.items()):
        tree.write(p, blob)
    for p in notes["removed"]:
        tree.remove(p)
    changes.append("site/site.json: added schema, engine and resume; every other key kept"
                   + ("; written as schema %d (%s)" % (notes["schema"], "; ".join(
                       "%s %s" % (w, what) for w, what, _e in notes["schemaReasons"]))
                      if notes["schema"] > 1 else ""))
    for _key, _old, _new, line in notes["normalised"]:
        changes.append(line)
    for _old, _new, line in notes["layout"]:
        changes.append(line)
    for r in notes["redirects"]:
        changes.append("redirects: %s -> '%s': %s (the page is deleted and the build writes one at the same "
                       "address%s)" % (r.path, r.key, json.dumps(r.target),
                                       "; its own text is dropped: %s" % json.dumps(r.dropped) if r.dropped else ""))
    changes.append(kind_change_line(tree, plan.get("siteKind")))
    changes = [c for c in changes if c]
    if notes["labels"]:
        changes.append("work.labels: converted %d labels" % len(notes["labels"]))
        for where, found, key, label in notes["labels"]:
            changes.append("%s: %s -> key %s, label %s" % (where, found, key, json.dumps(label)))
    for p, a, b in notes["tokens"]:
        changes.append("%s: token %s -> %s" % (p, a, b))
    claude_old = tree.text("CLAUDE.md") if tree.exists("CLAUDE.md") else "# Rules for this repo\n"
    claude_new = transform_claude_md(claude_old)
    claude_new = append_rules(claude_new, rule_units)
    tree.write("CLAUDE.md", claude_new)
    changes.append("CLAUDE.md: person sections kept, engine sections replaced by one pointer to the plugin")
    for r in rule_units:
        changes.append("CLAUDE.md: standing rule carried from %s (unit %s) under \"%s\""
                       % (r["source"], r["id"], RULES_HEADING))
    gi_old = tree.text(".gitignore") if tree.exists(".gitignore") else ""
    gi_new, gi_add = update_gitignore(gi_old)
    if gi_add:
        tree.write(".gitignore", gi_new)
        changes.append(".gitignore: added %s" % ", ".join(gi_add))
    # settings and hooks
    cap_of = dict((p, e["capability"]) for p, e in removals.items())
    st_old = tree.text(".claude/settings.json") if tree.exists(".claude/settings.json") else ""
    with open(STARTER_SETTINGS, "r", encoding="utf-8") as fh:
        starter = fh.read()
    try:
        settings = merge_settings(st_old, starter)
    except ValueError:
        raise Refused(".claude/settings.json is not valid JSON, so adopt cannot merge into it")
    hook_list = []
    for _round in range(2):
        trial = json.loads(json.dumps(settings))
        trial, hook_list, blocked = process_hooks(trial, set(removals), cap_of, spec)
        if not blocked:
            break
        for p in sorted(blocked):
            removals.pop(p, None)
            kept.append((p, "a hook still calls it and no plugin hook replaces it" + shadow_suffix(by_path.get(p, {}))))
    else:
        raise Refused("hooks still name files adopt would remove")
    settings = trial
    tree.write(".claude/settings.json", json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
    changes.append(".claude/settings.json: plugin registration and ask rules added; your own rules kept")
    # 4. removals last
    for p in sorted(removals):
        if removals[p]["kind"] == "skill":
            folder = posixpath.dirname(p) + "/"
            for q in [x for x in tree.paths() if x.startswith(folder)]:
                tree.remove(q)
        else:
            tree.remove(p)
        if posixpath.basename(p) == "package.json":
            lock = posixpath.dirname(p) + "/package-lock.json"
            if tree.exists(lock):
                tree.remove(lock)
    for path, d in sorted(decisions.items()):
        ruled = sorted(uid for uid, u in (d.get("units") or {}).items() if u.get("disposition") == "rule")
        if not ruled:
            continue
        if path not in removals:
            raise Refused("%s: unit %s is marked rule, but the file stays; a standing rule is carried only out of "
                          "a file adopt removes. Mark the unit person-data or keep, or confirm the file for removal"
                          % (path, ruled[0]))
        if removals[path]["kind"] not in ("agent", "command", "skill"):
            raise Refused("%s: unit %s is marked rule, but only an agent, command or skill file carries a "
                          "standing rule" % (path, ruled[0]))
    post = set(tree.paths())
    dangling = dangling_hook_paths(settings, post)
    if dangling:
        raise Refused("a hook would still name %s, which is not in the new tree; apply finished nothing"
                      % ", ".join(sorted(set(p for _e, p in dangling))))
    notes["oldFormHits"] = old_form_hits(tree, notes["olds"])
    # 5. HANDOFF.md entry
    branch = BRANCH_PREFIX + date
    handoff_old = tree.text("HANDOFF.md") if tree.exists("HANDOFF.md") else "# Handoff\n"
    entry = ("\n## Adopt site-studio (%s)\n\n- Branch `%s`, one commit, from %s %s. Not merged and not pushed.\n"
             "- Removed %d local file(s); moved %d fact group(s) into the data files; kept %d file(s) as customisations or by decision.\n"
             % (date, branch, basis.label(), base[:7], len(removals), len(moved), len(kept)))
    tree.write("HANDOFF.md", (handoff_old if handoff_old.endswith("\n") else handoff_old + "\n") + entry)
    message = build_message(date, basis, removals, reasons, spec, moved, changes, hook_list, kept, parity, notes)
    return {"base": base, "basis": basis, "tree": tree, "branch": branch, "message": message, "removals": removals,
            "kept": kept, "claude": (claude_old, claude_new), "hooks": hook_list, "moved": moved,
            "notes": notes}


def kind_change_line(tree, confirmed):
    """The commit line about the site kind (design 7.7): what the person confirmed, or, when nothing was
    confirmed and the tree does not look like a portfolio, that none was written and how to set one."""
    if confirmed:
        return "siteKind: %s (you confirmed it%s)" % (confirmed, "" if confirmed != "portfolio" else
                                                      "; it is the default, so site.json does not carry it")
    inferred, why = infer_kind(tree)
    if inferred == "portfolio":
        return ""
    return ("siteKind: not set, so this builds as a portfolio; it looks like a %s site (%s): run `adopt.py kind "
            "%s` and apply again to write it" % (inferred, why, inferred))


def build_message(date, basis, removals, reasons, spec, moved, changes, hook_list, kept, parity, notes):
    if basis.kind == "HEAD":
        src = "Converted from HEAD %s on %s." % (basis.sha[:7], basis.branch)
    else:
        src = "Converted from origin/main %s." % basis.sha[:7]
    L = ["site-studio adopt: retire this repo's local copies of the plugin's tools (%s)" % date, "",
         "%s One commit on a new branch; main is untouched; nothing is pushed." % src]
    if basis.ahead:
        L.append("Includes %d commit%s not on origin/main %s:" % (len(basis.ahead), "" if len(basis.ahead) == 1 else "s",
                                                                  basis.origin[:7]))
        L += ["- %s %s" % (s[:7], subj) for s, subj in basis.ahead]
    L.append("")
    L.append("Removed (file | counterpart | why):")
    if removals:
        for p in sorted(removals):
            L.append("- %s | %s | %s" % (p, counterpart_of(spec, removals[p]["capability"]), reasons[p]))
    else:
        L.append("- (nothing)")
    L += ["", "Moved data (from | to):"]
    L += ["- %s | %s" % (a, b) for a, b in moved] or ["- (nothing)"]
    L += ["", "Transformed config:"] + ["- %s" % c for c in changes]
    if notes.get("oldFormHits"):
        L += ["", "Your own script may depend on the old form (kept files that still hold a value adopt "
                  "replaced):"]
        L += ["- %s:%d: %s (the old %s)" % (p, n, github_url.redact(old), what)
              for p, n, old, what in notes["oldFormHits"]]
    L += ["", "Hooks removed or rewritten:"]
    L += (["- %s: `%s` -> %s" % (e, o, ("`%s`" % n) if n else "removed (the plugin's own hook does this job)")
           for e, o, n in hook_list] or ["- (none)"])
    L += ["", "Kept (customisations and decisions):"] + (["- %s | %s" % (p, why) for p, why in sorted(kept)] or ["- (none)"])
    if notes.get("redirectsLeft"):
        L += ["", "Meta-refresh pages left as hand pages (adopt could not turn them into redirects):"]
        L += ["- %s: %s" % t for t in notes["redirectsLeft"]]
    if notes["unknown"]:
        L += ["", "Tokens the plugin's build will refuse (fix by hand):"] + ["- %s: %s" % t for t in notes["unknown"]]
    L += ["", "Parity: %s" % (("%s (%s)" % (parity["verdict"], parity.get("reason", ""))) if parity else "not run")]
    return "\n".join(L) + "\n"


def do_apply(repo, date, dry_run=False):
    p = prepare(repo, date)
    out = []
    old, new = p["claude"]
    diff = "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), "CLAUDE.md (%s)" % p["basis"].label(), "CLAUDE.md (adopt)"))
    if dry_run:
        out.append("adopt dry run: would create %s from %s %s with ONE commit; nothing written."
                   % (p["branch"], p["basis"].label(), p["base"][:7]))
        out.append(p["message"])
        out.append("CLAUDE.md diff:\n" + (diff or "(no change)"))
        return "\n".join(out), None
    commit = commit_branch(repo, p["tree"], p["base"], p["branch"], p["message"])
    out.append("adopt: created %s (commit %s) from %s %s. Review it with `git show %s`; main is untouched, "
               "nothing was pushed." % (p["branch"], commit[:7], p["basis"].label(), p["base"][:7], p["branch"]))
    out.append(p["message"])
    out.append("CLAUDE.md diff:\n" + (diff or "(no change)"))
    return "\n".join(out), commit


# ---------------------------------------------------------------- the CLI

def _need_plan(repo, base):
    plan = _plan_for(repo, base)
    return plan


def cmd_inventory(repo, as_json):
    basis, tree, data = preconditions(repo)
    base = basis.sha
    spec = load_spec()
    infos = inventory(tree, spec)
    resume = detect_resume(tree)
    plan = _plan_for(repo, base)
    for i in infos:
        plan["files"].setdefault(i["path"], {"removal": None, "reviewed": False, "units": {}})
    for stale in [p for p in plan["files"] if p not in set(i["path"] for i in infos)]:
        del plan["files"][stale]
    save_plan(repo, plan)
    folders = portfolio_folders(tree)
    unknown, sections = [], []
    for p in token_files(tree):
        _t, ch, u = rewrite_tokens(tree.text(p), folders, layout=(p == "site/templates/layout.html"))
        unknown += [(p, t) for t in u]
        sections += [(p, a, b) for a, b in ch if "{{#page:" in b]
    kind = plan.get("siteKind")
    probs = site_problems(tree, data, plan["paper"], kind)
    redirects = redirect_pages(tree, data.get("redirects"))
    signals = detect_signals(tree, data, redirects)
    known = set(f.key for f in FEATURES)
    inferred, inferred_why = infer_kind(tree)
    if as_json:
        return json.dumps({"base": base,
                           "basis": {"sha": base, "kind": basis.kind, "branch": basis.branch,
                                     "origin": basis.origin, "reason": basis.reason,
                                     "ahead": [{"sha": s, "subject": subj} for s, subj in basis.ahead]},
                           "files": infos, "resume": resume, "unknownTokens": unknown,
                           "problems": problem_dicts(probs),
                           "redirects": {"convert": [{"path": r.path, "key": r.key, "target": r.target,
                                                      "dropped": r.dropped} for r in redirects[0]],
                                         "left": [{"path": p, "reason": why} for p, why in redirects[1]]},
                           "features": [{"key": k, "where": w, "known": k in known,
                                         "line": feature_lines([(k, w)])[0].strip("- ").strip()}
                                        for k, w in signals],
                           "inferredKind": {"kind": inferred, "why": inferred_why}, "siteKind": kind,
                           "sections": [{"path": p, "found": a, "section": b} for p, a, b in sections]},
                          indent=2, default=list)
    L = ["adopt inventory (%s %s)" % (basis.label(), base[:7])] + basis.up_front() + [
         "",
         "%-10s %-38s %-34s %5s %8s  %s" % ("class", "file", "plugin counterpart", "score", "residual", "evidence")]
    for i in infos:
        L.append("%-10s %-38s %-34s %5s %8s  %s" % (
            i["class"], i["path"], counterpart_of(spec, i["capability"])[:34] if i["class"] != "CUSTOM" else "none",
            _fmt_pct(i["score"]) if i["class"] != "MIXED" else "-",
            _fmt_pct(i["residual"]) if i["class"] in ("DUPLICATE", "PARTIAL") else "-",
            (", ".join(i["signals"]) if i["signals"] else (
                "best: " + ", ".join("%s %s" % b for b in i["best"]) if i["class"] == "CUSTOM" and i["best"] else
                ("candidates: " + ", ".join("%s %s" % c for c in i["candidates"]) if i["candidates"] else "")))
            + ("; " + namesake_text(i) if i.get("namesake") else "")))
    for i in infos:
        if i["residual_units"]:
            L.append("")
            L.append("Residual units in %s (person data to move, a standing rule to carry, or behaviour to keep):"
                     % i["path"])
            for u in i["residual_units"]:
                L.append("  %s: %s" % (u["id"], u["text"].split("\n")[0][:90]))
    for i in infos:
        if i.get("shadows"):
            L.append("")
            L.append("SHADOW: %s %s. While it is kept, %s"
                     % (i["path"], namesake_text(i) or "has the name of site-studio's %s agent" % i["shadows"],
                        shadow_note(i["shadows"])))
    L.append("")
    if resume["md"]:
        L.append("resume: %s%s; paper: %s" % (resume["md"], (" + " + resume["pdf"]) if resume["pdf"] else "",
                 ("%s (read from %s)" % (resume["paper"], resume["source"])) if resume["paper"] else
                 "NEEDS YOUR ANSWER (no readable resume PDF); run `adopt.py paper Letter` or `adopt.py paper A4`"))
    else:
        L.append("resume: none found; site.json gets resume: null")
    if unknown:
        L.append("tokens the plugin's build will refuse: " + ", ".join("%s in %s" % (t, p) for p, t in unknown))
    for p, t in unknown:
        if re.sub(r"\s", "", t) == "{{resumeLink}}":
            L.append("step for you: %s holds %s somewhere other than as an anchor's whole href. The plugin "
                     "has no such token: wrap the link in %s, and point it at {{link:resume}}, by hand."
                     % (p, t, section_for_resume("<a href=\"{{link:resume}}\">...</a>")))
    if sections:
        L.append("page sections adopt will write (a link that is there when the resume is built, gone when "
                 "it is not):")
        for p, a, b in sections:
            L.append("  %s: %s -> %s" % (p, " ".join(a.split()), " ".join(b.split())))
    if probs:
        L.append("")
        L += format_problems(probs)
        L.append("")
    for name in pageless_folders(TreeFiles(tree)):
        choice = plan["folders"].get(name, "source")
        L.append("content/%s/ has no page.md: apply will %s. %s" % (
            name,
            "add a page.md, so it becomes a portfolio" if choice == "portfolio" else
            "rename it to content/_%s (kept as source material, not built)" % name,
            "To rename it instead: `adopt.py folder %s source`." % name if choice == "portfolio" else
            "To make it a portfolio instead: `adopt.py folder %s portfolio`." % name))
    sch = site_json_schema_line(tree, data, plan["paper"], plan["folders"], kind)
    if sch:
        L.append(sch)
    if redirects[0]:
        L.append("meta-refresh pages adopt will turn into site.json redirects (the build writes an equivalent "
                 "page at the same address):")
        L += ["  %s -> redirects '%s': %s" % (r.path, r.key, json.dumps(r.target)) for r in redirects[0]]
    if redirects[1]:
        L.append("meta-refresh pages that stay hand pages (adopt will not turn them into redirects):")
        L += ["  %s: %s" % t for t in redirects[1]]
    if signals:
        L.append("")
        L.append("what this site does, and what site-studio does about it:")
        L += feature_lines(signals)
    L.append("")
    L.append("this looks like a %s site (%s); %s" % (
        inferred, inferred_why,
        ("you confirmed %s" % kind) if kind else
        "confirm it with `adopt.py kind %s`, or choose portfolio, hub or custom; apply writes only a kind you "
        "confirmed" % inferred))
    counts = {}
    for i in infos:
        counts[i["class"]] = counts.get(i["class"], 0) + 1
    L.append("summary: " + ", ".join("%s %d" % kv for kv in sorted(counts.items())))
    return "\n".join(L)


def site_json_schema_line(tree, data, paper, folders=None, kind=None):
    """The inventory line that says site.json will be written as schema 2, and why (so a person on a
    second machine with an older site-studio is not surprised); None while schema 1 holds the site."""
    try:
        _files, notes = converted_site_files(tree, data, paper, folders, kind)
    except Refused:
        return None
    if notes["schema"] < 2:
        return None
    return ("site.json will be written as schema %d, because %s; a site-studio older than 0.2.0 will say "
            "it is newer than it understands, and ask to be updated"
            % (notes["schema"], "; ".join("%s %s" % (w, what) for w, what, _e in notes["schemaReasons"])))


def _current_base(repo):
    """The parity basis as of the last fetch (the plan commands make no network call): HEAD when it is a
    fast-forward of origin/main as last fetched, else origin/main. A commit made after the inventory
    changes it, which is the point: the plan was made for another tree."""
    if not gitt(repo, "rev-parse", "--verify", "-q", "refs/remotes/origin/main", check=False):
        raise Refused("origin/main does not resolve; run `adopt.py inventory` first")
    return parity_basis(repo).sha


def _set(repo, path, fn):
    tree = None
    plan = _plan_for(repo, _current_base(repo))
    entry = plan["files"].get(path)
    if entry is None:
        raise Refused("%s is not in the plan; run `adopt.py inventory` first" % path)
    fn(plan, entry, tree)
    save_plan(repo, plan)


def main(argv=None):
    rc = platform_check.windows_refusal_rc("adopt.py")
    if rc is not None:
        return rc
    ap = argparse.ArgumentParser(prog="adopt.py", allow_abbrev=False)
    ap.add_argument("--repo", default=os.getcwd())
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("check")
    s = sub.add_parser("inventory")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("confirm")
    s.add_argument("path")
    s.add_argument("--keep", action="store_true")
    s.add_argument("--as", dest="as_cap")
    s = sub.add_parser("unit")
    s.add_argument("path")
    s.add_argument("unit_id")
    s.add_argument("disposition", choices=UNIT_DISPOSITIONS)
    s.add_argument("--kind", choices=FACT_KINDS)
    s.add_argument("--name")
    s = sub.add_parser("fact")
    s.add_argument("path")
    s.add_argument("--kind", choices=FACT_KINDS, required=True)
    s.add_argument("--text", required=True)
    s.add_argument("--name")
    s = sub.add_parser("reviewed")
    s.add_argument("path")
    s = sub.add_parser("paper")
    s.add_argument("size", choices=("Letter", "A4"))
    s = sub.add_parser("folder")
    s.add_argument("name")
    s.add_argument("choice", choices=FOLDER_CHOICES)
    s = sub.add_parser("kind")
    s.add_argument("site_kind", choices=siteconfig.SITE_KINDS)
    s = sub.add_parser("parity")
    s.add_argument("--accept", action="store_true")
    s = sub.add_parser("apply")
    s.add_argument("--date", default=time.strftime("%Y-%m-%d"))
    s.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    repo = os.path.abspath(args.repo)
    try:
        if args.cmd == "check":
            basis, tree, data = preconditions(repo)
            for line in basis.up_front():
                print(line)
            probs = site_problems(tree, data, None, _plan_for(repo, basis.sha).get("siteKind"))
            for line in format_problems(probs):
                print(line)
            blocked = [p for p in probs if not p.mechanical]
            if blocked:
                print("adopt check: %s %s cannot be converted until the %d problem(s) marked "
                      "`you decide` are settled" % (basis.label(), basis.sha[:7], len(blocked)))
                return 1
            print("adopt ok: %s %s can be converted" % (basis.label(), basis.sha[:7]))
        elif args.cmd == "inventory":
            print(cmd_inventory(repo, args.json))
        elif args.cmd == "confirm":
            def fn(plan, e, tree):
                e["removal"] = "keep" if args.keep else "confirm"
                if args.as_cap:
                    if args.as_cap not in load_spec().caps:
                        raise Refused("unknown capability %s" % args.as_cap)
                    e["as"] = args.as_cap
            _set(repo, args.path, fn)
            print("adopt: %s -> %s" % (args.path, "keep" if args.keep else "remove (after apply)"))
        elif args.cmd == "unit":
            def fn(plan, e, tree):
                if args.disposition == "person-data" and not args.kind:
                    raise Refused("--kind context|voice|rule is required for person data")
                u = {"disposition": args.disposition}
                if args.disposition == "person-data":
                    u["kind"] = args.kind
                    if args.name:
                        u["name"] = args.name
                e.setdefault("units", {})[args.unit_id] = u
            _set(repo, args.path, fn)
            print("adopt: %s %s -> %s" % (args.path, args.unit_id, args.disposition))
        elif args.cmd == "fact":
            def fn(plan, e, tree):
                fa = {"source": args.path, "kind": args.kind, "text": args.text}
                if args.name:
                    fa["name"] = args.name
                plan["facts"].append(fa)
            _set(repo, args.path, fn)
            print("adopt: recorded a %s fact from %s" % (args.kind, args.path))
        elif args.cmd == "reviewed":
            def fn(plan, e, tree):
                e["reviewed"] = True
            _set(repo, args.path, fn)
            print("adopt: facts in %s marked reviewed" % args.path)
        elif args.cmd == "paper":
            plan = _plan_for(repo, _current_base(repo))
            plan["paper"] = args.size
            save_plan(repo, plan)
            print("adopt: resume.paper will be %s" % args.size)
        elif args.cmd == "folder":
            name = args.name.strip("/")
            if name.startswith("content/"):
                name = name[len("content/"):]
            if not name or "/" in name:
                raise Refused("name one folder directly under content/, for example `adopt.py folder news "
                              "portfolio`")
            plan = _plan_for(repo, _current_base(repo))
            plan["folders"][name] = args.choice
            save_plan(repo, plan)
            print("adopt: content/%s -> %s" % (name, "renamed to content/_%s (source material)" % name
                                                if args.choice == "source" else "gets a page.md and is a portfolio"))
        elif args.cmd == "kind":
            plan = _plan_for(repo, _current_base(repo))
            plan["siteKind"] = args.site_kind
            save_plan(repo, plan)
            print("adopt: the site kind is %s%s" % (args.site_kind, " (the default; site.json will not carry it)"
                                                    if args.site_kind == "portfolio" else
                                                    " (apply writes siteKind: %s, schema 2)" % args.site_kind))
        elif args.cmd == "parity":
            basis, tree, data = preconditions(repo)
            plan = _plan_for(repo, basis.sha)
            res = run_parity(repo, inventory(tree), basis, tree, data, folders=plan["folders"],
                             kind=plan.get("siteKind"))
            if args.accept:
                if res["verdict"] != "DIFFERENT":
                    raise Refused("there are no differences to accept (parity is %s)" % res["verdict"])
                res["verdict"] = "ACCEPTED"
            plan["parity"] = {"verdict": res["verdict"], "reason": res["reason"]}
            save_plan(repo, plan)
            print("parity: %s -- %s" % (res["verdict"], res["reason"]))
            for n in res["notes"]:
                print("  note: %s" % n)
            for kind, path, detail in res["differences"]:
                print("  %s: %s%s" % (kind, path, (" (%s)" % detail) if detail else ""))
        elif args.cmd == "apply":
            text, _commit = do_apply(repo, args.date, args.dry_run)
            print(text)
        else:
            ap.print_usage()
            return 2
    except NeedsAnswer as e:
        print("adopt needs an answer: %s" % e)
        return 3
    except Refused as e:
        print("adopt refused: %s" % e)
        return 1
    except PlanError as e:
        print("adopt refused: %s" % e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
