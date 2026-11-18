"""adoption.engine -- the engine set E: the old builder's own code, and the invocation that publishes it (design 8 AO, R3
ruling A3, R3N-1, R3N-11, Q1.11, Q1.12; step 1.9r).

Part of the `adoption` package behind the entry point `adopt.py`.

THE ENGINE SET (a closed rule, computed BEFORE any file is disposed; OURS, U-15: our fixtures are authored from the same
assumptions as the rule, so `check` prints E with each file's rule before anything moves and the first real run is the probe):

  builder, content-loader, deploy   every tracked code file (`ENGINE_EXTS`, and the bare names `ENGINE_NAMES`), anywhere
                                    outside `content/`, `site/src/` and `archive/`, that the capability signals
                                    (`spec/capabilities.json`) classify as one of those three; and, because a small builder
                                    scores below the signals' threshold (OURS, U-15), the file a publishing workflow or a
                                    `package.json` script RUNS (`node <file>`, `python3 <file>`, `bash <file>`) is the
                                    builder, and a code file that runs an engine file is a deploy script
  builder-module                    a module the builder loads: a static scan of its relative `require()` / `import` from the
                                    entry, followed to a fixed point (a dynamic `import()` is missed, so that module stays
                                    kept, the safe direction, U-12); a file under content/ or site/src/ is content, never
  package                           `package.json` and its lockfile, when every `scripts` entry names only engine files or no
                                    other code file remains; otherwise kept, with a line per `scripts` entry that now names
                                    an archived file
  workflow                          a PUBLISHING workflow (one with a publish marker, any `git push`, a `contents: write` or
                                    `pages: write` grant, or one that runs an engine file) whose every step serves publishing
                                    AND whose target is shown to be `publicRepo` (R3N-1, owner decision 26): a literal
                                    `external_repository`, `repository-name` or push URL naming it. A target that is an
                                    unresolvable `${{ }}` is the person's to confirm (`adopt.py file <wf> engine`); a workflow
                                    that also does other things (tests, lint, release) is listed for the person; a publisher
                                    with NO external target publishes the DEV repo itself (`publish/serves-dev-repo`): it
                                    blocks, is a person cause, and is never archived

THE MEASURED INVOCATION (Q1.12, R4 row 25). Parity runs the builder as the publisher does. When the publishing workflow's step
(or the `package.json` script it calls) is `node <entry> [literal arguments]` and its `env:` values are literal, parity runs
exactly that: `Invocation(args, env)`. A `${{ }}` expression in an argument or an env value, a chained shell command, another
tool: `builder/invocation-differs` (UNVERIFIED). A workflow value for a key the scrubbed environment sets itself (`PATH`, `HOME`,
`TMPDIR`, `TZ`, `LC_ALL`, `LANG`, `NODE_OPTIONS`, `NO_COLOR`) is `invocation-differs` too. With no publishing workflow the
plain `node <entry>` stands.

PURE where it can be: the scans take text, and `compute_engine` takes a tree-like object (`paths()`, `text()`, `exists()`).
"""

import json
import posixpath
import re

from adoption.base import Refused
from adoption.classify import classify_text
from adoption.parity import builder_entry

ENGINE_EXTS = (".js", ".mjs", ".cjs", ".ts", ".mts", ".py", ".rb", ".go", ".php", ".sh", ".bash", ".zsh")
ENGINE_NAMES = ("Makefile", "Rakefile", "justfile")
ENGINE_CAPS = ("builder", "content-loader", "deploy")
PUBLISH_MARKERS = ("actions/deploy-pages", "actions/upload-pages-artifact", "peaceiris/actions-gh-pages",
                   "JamesIves/github-pages-deploy-action")
SAME_REPO_MARKERS = ("actions/deploy-pages", "actions/upload-pages-artifact")
LOCKFILES = ("package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml")
SCRUBBED_KEYS = ("PATH", "HOME", "TMPDIR", "TZ", "LC_ALL", "LANG", "NODE_OPTIONS", "NO_COLOR")
LANGUAGE_OF = {".py": "python", ".sh": "shell", ".bash": "shell", ".zsh": "shell", ".rb": "ruby", ".go": "go",
               ".php": "php", ".ts": "typescript", ".mts": "typescript"}
_OUT = ("content/", "site/src/", "archive/", "node_modules/", ".git/")
_REQUIRE = re.compile(r"""\brequire\(\s*['"](\.{1,2}/[^'"]+)['"]\s*\)""")
_IMPORT = re.compile(r"""(?:^|[\s;])(?:import|export)\b[^'"\n]*?\bfrom\s*['"](\.{1,2}/[^'"]+)['"]|(?:^|[\s;])import\s*['"](\.{1,2}/[^'"]+)['"]""",
                     re.M)


def is_code(path):
    base = posixpath.basename(path)
    return (posixpath.splitext(base)[1].lower() in ENGINE_EXTS or base in ENGINE_NAMES) and not path.startswith(_OUT) \
        and "node_modules" not in path.split("/")


def looks_like_builder(text):
    """OURS, structural: the file reads `content` and writes the output folder (`dist`, `site/dist`, `public`, `_site`). A
    small builder scores below the capability signals' threshold, so this is the second way a file is the builder."""
    return bool(re.search(r"content", text) and re.search(r"\b(?:site/)?dist\b|\bpublic\b|\b_site\b", text)
                and re.search(r"writeFile(?:Sync)?|copyFile(?:Sync)?|open\([^)]*['\"]w|write_text|shutil\.copy", text))


def is_code_workflow(path):
    return bool(re.match(r"^\.github/workflows/[^/]+\.ya?ml$", path))


def code_files(tree):
    return [p for p in tree.paths() if is_code(p)]


_RUNS = re.compile(r"(?:^|[\s;&|(])(?:node|python3?|bash|sh|ruby|php|go run|tsx?|deno run)\s+(?:--?[\w-]+(?:=\S+)?\s+)*([\w./-]+)")


def _package_scripts(tree):
    """[(directory, {script name: command})] for every tracked package.json."""
    out = []
    for p in tree.paths():
        if posixpath.basename(p) == "package.json" and "node_modules" not in p.split("/"):
            try:
                out.append((posixpath.dirname(p), json.loads(tree.text(p)).get("scripts") or {}))
            except (ValueError, AttributeError, KeyError):
                pass
    return out


def invoked_files(tree):
    """{path: where} for each code file a workflow's `run:` line or a `package.json` script RUNS: `node site/build.js`, or
    `node build.js` in site/package.json (which is `site/build.js`). The file is a builder (or the builder's helper)."""
    out = {}
    commands = []
    for p in tree.paths():
        if re.match(r"^\.github/workflows/[^/]+\.ya?ml$", p):
            commands += [("", r.strip(), p) for st in _steps(tree.text(p)) for r in st["run"].split("\n") if r.strip()]
    for d, scripts in _package_scripts(tree):
        commands += [(d, str(c), (d + "/" if d else "") + "package.json") for c in scripts.values()]
    for d, cmd, where in commands:
        for m in _RUNS.finditer(cmd):
            path = posixpath.normpath(posixpath.join(d, m.group(1)))
            if is_code(path) and tree.exists(path):
                out.setdefault(path, where)
    return out


def resolve_module(tree, from_path, spec):
    """The tracked file a relative specifier names (with the extension and `index` forms Node tries), or None."""
    base = posixpath.normpath(posixpath.join(posixpath.dirname(from_path), spec))
    for cand in (base, base + ".js", base + ".mjs", base + ".cjs", base + ".ts", base + "/index.js", base + "/index.mjs"):
        if tree.exists(cand):
            return cand
    return None


def module_closure(tree, entry):
    """{path} of every file the entry loads by a static relative require or import, followed to a fixed point."""
    seen, todo = set(), [entry]
    while todo:
        cur = todo.pop()
        if cur in seen or not tree.exists(cur):
            continue
        seen.add(cur)
        try:
            text = tree.text(cur)
        except KeyError:
            continue
        for m in _REQUIRE.finditer(text):
            r = resolve_module(tree, cur, m.group(1))
            if r:
                todo.append(r)
        for m in _IMPORT.finditer(text):
            r = resolve_module(tree, cur, m.group(1) or m.group(2))
            if r:
                todo.append(r)
    seen.discard(entry)
    return set(p for p in seen if not p.startswith(_OUT))


# ---------------------------------------------------------------- workflows

def _steps(text):
    """[{"uses": str|None, "run": str, "env": {k: v}, "with": {k: v}}]: the steps of the workflow's jobs, read by line (no
    YAML library: stdlib only). A step starts at a `- ` line one level below `steps:`; a `run: |` block is its lines."""
    lines = text.split("\n")
    out, cur, in_steps, step_indent, block = [], None, False, None, None
    for line in lines:
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" "))
        if block is not None:
            if stripped and indent > block[0]:
                cur["run"] += ("\n" if cur["run"] else "") + stripped
                continue
            block = None
        if re.match(r"^steps:\s*$", stripped):
            in_steps, step_indent = True, None
            continue
        if not in_steps:
            continue
        if stripped.startswith("- ") and (step_indent is None or indent == step_indent):
            step_indent = indent
            cur = {"uses": None, "run": "", "env": {}, "with": {}, "_ctx": None}
            out.append(cur)
            stripped = stripped[2:].strip()
        elif stripped and indent < (step_indent or 0) + 0 and not stripped.startswith("- "):
            in_steps = False
            continue
        if cur is None or not stripped:
            continue
        m = re.match(r"^(uses|run|env|with):\s*(.*)$", stripped)
        if m:
            k, v = m.group(1), m.group(2).strip()
            if k == "uses":
                cur["uses"] = v.strip("'\"")
            elif k == "run":
                if v in ("|", ">", "|-", ">-"):
                    block = (indent, True)
                else:
                    cur["run"] = v
            else:
                cur["_ctx"] = k
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_.-]*):\s*(.*)$", stripped)
        if m and cur.get("_ctx") in ("env", "with") and indent > (step_indent or 0) + 1:
            cur[cur["_ctx"]][m.group(1)] = m.group(2).strip().strip("'\"")
    return out


_SERVING_RUN = re.compile(r"^(?:npm (?:ci|install|run [\w:-]+|start)|npx --yes [\w-]+ build|node \S+(?: .*)?|python3? \S+(?: .*)?|"
                          r"bash \S+|sh \S+|pip3? install\b.*|git (?:config|add|commit|push|remote|init|checkout|switch|branch|"
                          r"fetch|pull|status|clone)\b.*|cp\b.*|mkdir\b.*|cd\b.*|echo\b.*|touch\b.*|rm\b.*|ls\b.*|"
                          r"yarn(?: install| build)?|pnpm (?:install|run [\w:-]+)|\./\S+)\s*$")
_SERVING_USES = re.compile(r"^actions/(?:checkout|setup-[\w-]+|cache|configure-pages)@|^(?:actions/deploy-pages|"
                           r"actions/upload-pages-artifact|peaceiris/actions-gh-pages|JamesIves/github-pages-deploy-action)")


def workflow_facts(text, public_repo, engine_paths=()):
    """What `check` needs to know about one workflow: {publishing, serving_only, target, steps}. `target` is `public` (a
    literal target naming `public_repo`), `unresolved` (a `${{ }}` expression where the target is), `other` (a literal that
    is not `public_repo`), or `same` (a publisher with no external target: the dev repo's own Pages or branch)."""
    steps = _steps(text)
    uses = [s["uses"] or "" for s in steps]
    runs = [r.strip() for s in steps for r in s["run"].split("\n") if r.strip() and not r.strip().startswith("#")]
    marker = any(any(m in u for m in PUBLISH_MARKERS) for u in uses)
    pushes = any(re.search(r"\bgit\b[^\n]*\bpush\b", r) for r in runs)
    writes = bool(re.search(r"^\s*(?:contents|pages):\s*write\s*$", text, re.M))
    runs_engine = any(any(posixpath.basename(e) in r or e in r for e in engine_paths) for r in runs if r) and (marker or pushes or writes)
    publishing = marker or pushes or writes or runs_engine
    serving = True
    for s in steps:
        if s["uses"]:
            if not _SERVING_USES.search(s["uses"]):
                serving = False
        for r in [x.strip() for x in s["run"].split("\n") if x.strip() and not x.strip().startswith("#")]:
            if not _SERVING_RUN.match(r) or re.search(r"\b(?:test|lint|htmlhint|eslint|prettier|release)\b", r):
                serving = False
    target = "same"
    ext = re.findall(r"^\s*(?:external_repository|repository-name|repository):\s*(\S+)\s*$", text, re.M)
    expr = r"\$\{\{[^}]*\}\}"
    urls = re.findall(r"https://(?:[^\s'\"$]|%s)*github\.com(?:[^\s'\"$]|%s)*" % (expr, expr), text)
    candidates = [e.strip("'\"") for e in ext if e.strip("'\"") not in ("${{ github.repository }}",)] + \
                 [u for u in urls if "${{" in u or "/" in u.split("github.com", 1)[1]]
    if candidates:
        if any(public_repo and public_repo in c for c in candidates):
            target = "public"
        elif any("${{" in c for c in candidates):
            target = "unresolved"
        else:
            target = "other"
    if any(m in u for u in uses for m in SAME_REPO_MARKERS):
        target = "same"
    return {"publishing": publishing, "serving_only": serving, "target": target, "steps": steps, "runs": runs}


def workflow_class(facts, choice=None):
    """(`not-publishing` | `engine` | `listed` | `serves-dev-repo` | `other-publisher`, why): one workflow's place in the
    design (AO, R3N-1). `choice` is the person's `files[path].disposition` (`engine` or `keep`)."""
    if not facts["publishing"]:
        return "not-publishing", "it does not publish"
    if facts["target"] == "same" and choice != "engine":
        return "serves-dev-repo", ("it publishes this repository itself (no external target), which is the owner's "
                                   "recommendation to move to a public repo of published content only")
    if choice == "keep":
        return "other-publisher", "kept by your decision while it publishes: two publishers on one public repo"
    if choice == "engine":
        return "engine", "your decision"
    if facts["target"] == "public" and facts["serving_only"]:
        return "engine", "a publishing workflow whose every step serves publishing, shown to target your public repo"
    return "listed", ("it also does something other than publish (tests, lint, a release step), or its target is an "
                      "expression adopt cannot read: `adopt.py file <path> engine|keep`")


# ---------------------------------------------------------------- the set

def compute_engine(tree, data, spec, plan_files=None):
    """E for `tree` (a Tree or Overlay): {"files": {path: rule}, "listed": [(workflow path, why)], "causes": [(cause group,
    key)], "notes": [lines], "entry": builder entry or None, "workflows": {path: class}}. `plan_files` is the plan's `files`
    ({path: {"disposition": ...}}) for the person's workflow choices."""
    plan_files = plan_files or {}
    files, notes, causes, listed, wf = {}, [], [], [], {}
    infos = []
    for p in code_files(tree):
        text = tree.text(p)
        kind = "code"
        info = classify_text(spec, p, kind, text)
        info["kind"] = kind
        infos.append(info)
        if info["capability"] in ENGINE_CAPS and info["class"] in ("DUPLICATE", "PARTIAL", "AMBIGUOUS"):
            files[p] = info["capability"]
    entry = builder_entry(infos)
    run = dict((p, w) for p, w in invoked_files(tree).items() if looks_like_builder(tree.text(p)))   # a lint script is not
    for path in sorted(run):
        files.setdefault(path, "builder")
    js = sorted((p for p in files if p in run and posixpath.splitext(p)[1].lower() in (".js", ".mjs", ".cjs")),
                key=lambda p: (0 if posixpath.basename(p).lower().startswith("build") else 1, p))
    if entry is None and js:
        entry = js[0]
    for root in sorted(set([entry] if entry else []) | set(p for p in files if posixpath.splitext(p)[1].lower() in (".js", ".mjs", ".cjs") and files[p] == "builder")):
        for m in module_closure(tree, root):
            files.setdefault(m, "builder-module")
    for p in code_files(tree):                      # a code file that reads content/ and writes the output folder is a builder
        if (p in files and files[p] not in ("content-loader", "deploy")) or p.startswith(("test", "tests/")):
            continue
        if looks_like_builder(tree.text(p)) and posixpath.splitext(p)[1].lower() not in (".sh", ".bash", ".zsh"):
            files[p] = "builder"            # a loader that also writes the output IS the builder (a small one scores as a loader)
    if entry is None:
        js = sorted((p for p, r in files.items() if r == "builder" and posixpath.splitext(p)[1].lower() in (".js", ".mjs", ".cjs")),
                    key=lambda p: (0 if posixpath.basename(p).lower().startswith("build") else 1, p))
        entry = js[0] if js else None
        for m in (module_closure(tree, entry) if entry else ()):
            files.setdefault(m, "builder-module")
    for p in code_files(tree):                      # a code file that RUNS an engine file is a deploy script
        if p in files:
            continue
        text = tree.text(p)
        if any(re.search(r"(?:^|[\s;&|(])(?:node|python3?|bash|sh|\./)\s*%s\b" % re.escape(e), text) for e in list(files)
               if files[e] in ("builder",)):
            files[p] = "deploy"
    for p, e in sorted(plan_files.items()):          # a file the person says is the old builder's own (`adopt.py file <p> engine`)
        if e.get("disposition") == "engine" and tree.exists(p) and not is_code_workflow(p):
            files.setdefault(p, "builder-module")
    # package.json and its lockfile
    pkg = "package.json"
    if tree.exists(pkg):
        try:
            scripts = (json.loads(tree.text(pkg)).get("scripts") or {})
        except (ValueError, AttributeError):
            scripts = {}
        names_other = [p for p in code_files(tree) if p not in files]
        refs = []
        for k, cmd in sorted(scripts.items()):
            tokens = re.findall(r"[\w./-]+\.(?:js|mjs|cjs|ts|py|sh)\b", str(cmd))
            refs.append((k, tokens))
        only_engine = all(all(t in files or posixpath.normpath(t) in files for t in toks) for _k, toks in refs)
        if only_engine or not names_other:
            files[pkg] = "package"
            for lock in LOCKFILES:
                if tree.exists(lock):
                    files[lock] = "package"
        else:
            for k, toks in refs:
                if any(t in files for t in toks):
                    notes.append("package.json script `%s` names a file that will be archived; package.json stays" % k)
    # workflows
    public = (data or {}).get("publicRepo")
    for p in sorted(tree.paths()):
        if not re.match(r"^\.github/workflows/[^/]+\.ya?ml$", p):
            continue
        facts = workflow_facts(tree.text(p), public, list(files))
        choice = (plan_files.get(p) or {}).get("disposition")
        cls, why = workflow_class(facts, choice)
        wf[p] = cls
        if cls == "engine":
            files[p] = "workflow"
        elif cls == "listed":
            listed.append((p, why))
        elif cls == "serves-dev-repo":
            causes.append(("publish", "serves-dev-repo"))
        elif cls == "other-publisher":
            causes.append(("publish", "other-publisher"))
    return {"files": files, "listed": listed, "causes": causes, "notes": notes, "entry": entry,
            "workflows": wf, "infos": infos}


def unmeasurable_language(tree, engine):
    """The language of a builder adopt cannot measure (`python`, `shell`, `ruby`, `go`, `php`, `typescript`, `workflow`,
    `other`), or None when `builder_entry` names a JavaScript entry or E holds no builder. A builder only a workflow
    runs (no entry file) is `workflow`."""
    if engine["entry"]:
        return None
    builders = [p for p, r in engine["files"].items() if r == "builder" and is_code(p)]
    if builders:
        exts = set(LANGUAGE_OF.get(posixpath.splitext(p)[1].lower(), "other") for p in builders)
        return sorted(exts)[0] if len(exts) == 1 else "other"
    if any(c == "engine" for c in engine["workflows"].values()):
        return "workflow"
    return None


def no_builder_at_all(engine, tree):
    """True when E is empty, no `package.json` script exists and no workflow is publishing or listed: the one NOT
    APPLICABLE case (A2, decision 23)."""
    if engine["files"] or engine["listed"] or any(c != "not-publishing" for c in engine["workflows"].values()):
        return False
    try:
        scripts = json.loads(tree.text("package.json")).get("scripts") if tree.exists("package.json") else None
    except ValueError:
        scripts = None
    return not scripts


# ---------------------------------------------------------------- the measured invocation

class Invocation(object):
    """`node <entry> args`, with the workflow's literal `env:` merged into the scrubbed environment."""

    def __init__(self, args=(), env=None, source="the plain `node <entry>` run (no publishing workflow)"):
        self.args, self.env, self.source = tuple(args), dict(env or {}), source


def invocation_for(tree, engine, entry):
    """(Invocation or None, cause or None, note): how the publisher runs the builder. A cause is
    `invocation-differs` when it cannot be reproduced literally."""
    if not entry:
        return None, None, ""
    for p, cls in sorted(engine["workflows"].items()):          # any workflow that runs the entry: it is how the publisher runs it
        facts = workflow_facts(tree.text(p), None, [entry])
        for s in facts["steps"]:
            for r in [x.strip() for x in s["run"].split("\n") if x.strip()]:
                scripts = {}
                if tree.exists("package.json"):
                    try:
                        scripts = json.loads(tree.text("package.json")).get("scripts") or {}
                    except ValueError:
                        scripts = {}
                m = re.match(r"^npm run ([\w:-]+)\s*$", r)
                cmd = scripts.get(m.group(1), "") if m else r
                nm = re.match(r"^node\s+(\S+)((?:\s+\S+)*)\s*$", cmd)
                if not nm or posixpath.normpath(nm.group(1)) != entry:
                    continue
                rest = nm.group(2).split()
                if any("${{" in a or any(c in a for c in "$`;&|<>") for a in rest) or "&&" in cmd or "|" in cmd:
                    return None, "builder/invocation-differs", "an argument is an expression or a shell form"
                env = dict(facts_env(tree.text(p), s))
                if any("${{" in v for v in env.values()):
                    return None, "builder/invocation-differs", "an env value is an expression"
                if any(k in SCRUBBED_KEYS for k in env):
                    return None, "builder/invocation-differs", "the workflow sets a variable the parity run scrubs"
                return Invocation(rest, env, "the invocation in %s" % p), None, ""
    return Invocation(), None, ""


def facts_env(text, step):
    """The literal env of a step plus the workflow-level and job-level `env:` blocks above it."""
    env = {}
    lines = text.split("\n")
    for i, line in enumerate(lines):                       # workflow-level and job-level `env:` blocks
        if re.match(r"^[ \t]*env:[ \t]*$", line):
            base = len(line) - len(line.lstrip())
            for nxt in lines[i + 1:]:
                if not nxt.strip():
                    continue
                if len(nxt) - len(nxt.lstrip()) <= base:
                    break
                kv = re.match(r"^\s+([A-Za-z_]\w*):\s*(.*)$", nxt)
                if kv:
                    env[kv.group(1)] = kv.group(2).strip().strip("'\"")
    env.update(step.get("env") or {})
    return env
