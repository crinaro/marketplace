"""adoption.accounting -- every tracked file gets exactly one disposition (design 8 FA, R3 ruling B; step 1.9r).

Part of the `adoption` package behind the entry point `adopt.py`. The six dispositions are `DISPOSITIONS` (closed). The
rules, first match wins, are `disposition_of`; the measurements they need (what the plugin's build attributes to a file,
what the old builder used, the counterfactual) come from `adoption.usage`, and this module is pure over them, so the
rules are tested on plain dicts and the measurements on real builders.

    published   the old builder used it AND the plugin's build attributes it: it lands on the page whose source it is, else
                the output path with equal bytes, else it is a build input
    draft       the old builder did not use it, it is a piece `index.md`, and the plugin would publish it (work in progress):
                `draft: true`; the piece FOLDER is the unit, every other file in it takes `draft` and stays in place
    archived    everything else: moved to `archive/<path>` (with a leading `.claude/` segment as `_claude/`), listed in
                `archive/ARCHIVE.json`, which nothing builds or reads
    engine      the old builder itself (the engine set, `adoption.engine`): never moved until site-studio has published
    kept        repository files that are not content (`.site-studio/**`, README, LICENSE, ...) and what the person marked
    no-landing  the old builder used it and the plugin's build cannot hold it: content the visitor would lose; it BLOCKS

`unobservable/<family>` is not a disposition: it is a group the counterfactual could not split inside its run cap, which
stays undisposed (and so blocks) with only a count.

THE ARCHIVE RECORD (`archive/ARCHIVE.json`, design 3.5): {"schema": 1, "files": [{"from", "disposition", "rule"}]}, sorted
by `from`, no dates; `parse_archive` is its strict reader and `archive_path` the one place that says where a file lands.
"""

import json
import posixpath
import re

import parity_classes

from adoption.base import PlanError, Refused, gitt
from adoption.plan import _current_base, _plan_for, save_plan

DISPOSITIONS = ("published", "draft", "archived", "engine", "kept", "no-landing")
ARCHIVE_REL = "archive/ARCHIVE.json"
ARCHIVE_RULES = ("unused", "person", "builder", "content-loader", "deploy", "builder-module", "package", "workflow",
                 "claude-config")
ARCHIVE_DISPOSITIONS = ("archived", "engine")
KEPT_ROOT_FILES = re.compile(r"^(?:README[^/]*|LICENSE[^/]*|CLAUDE\.md|HANDOFF\.md|\.git[^/]*|\.editorconfig)$", re.I)
_WORKFLOW = re.compile(r"^\.github/workflows/[^/]+\.ya?ml$")
_PIECE_INDEX = re.compile(r"^content/(?!references/|home/|about/|resume/|media/)([^/_][^/]*)/([^/_][^/]*)/index\.md$")


def archive_path(path):
    """Where `path` goes under `archive/`: itself below it, a leading `.claude/` segment written `_claude/` (Claude Code
    loads a nested `.claude/skills/` when a file below one is read, so no archived path may hold such a segment, Q2.4)."""
    if path.startswith("archive/"):
        return path
    if path.startswith(".claude/"):
        path = "_claude/" + path[len(".claude/"):]
    return "archive/" + path


def parse_archive(text):
    """The strict reader of `archive/ARCHIVE.json`: the list of rows, or PlanError naming what it cannot read."""
    try:
        d = json.loads(text)
    except ValueError as e:
        raise PlanError("%s is not valid JSON: %s; restore the committed copy from an earlier commit (`git log -- %s` "
                        "lists them)" % (ARCHIVE_REL, e, ARCHIVE_REL))
    if not isinstance(d, dict) or set(d) != {"schema", "files"}:
        raise PlanError("%s must hold exactly schema and files" % ARCHIVE_REL)
    if d["schema"] != 1 or isinstance(d["schema"], bool):
        raise PlanError("%s: schema %r is not understood (this adopt reads 1); update site-studio, because a newer one "
                        "wrote it" % (ARCHIVE_REL, d["schema"]))
    if not isinstance(d["files"], list):
        raise PlanError("%s: files must be a list" % ARCHIVE_REL)
    seen = []
    for row in d["files"]:
        if (not isinstance(row, dict) or set(row) != {"from", "disposition", "rule"} or not isinstance(row["from"], str)
                or row["disposition"] not in ARCHIVE_DISPOSITIONS or row["rule"] not in ARCHIVE_RULES):
            raise PlanError("%s: every row holds exactly from, disposition (%s) and rule (%s); fix the row, or restore the "
                            "committed copy from an earlier commit"
                            % (ARCHIVE_REL, ", ".join(ARCHIVE_DISPOSITIONS), ", ".join(ARCHIVE_RULES)))
        seen.append(row["from"])
    if seen != sorted(set(seen)):
        raise PlanError("%s: files must be sorted by from, one row per file" % ARCHIVE_REL)
    return d["files"]


def dump_archive(rows):
    """The one written form: sorted by `from`, no dates."""
    out = {"schema": 1, "files": sorted((dict(r) for r in rows), key=lambda r: r["from"])}
    parse_archive(json.dumps(out))
    return json.dumps(out, indent=2, sort_keys=True) + "\n"


def is_workflow(path):
    return bool(_WORKFLOW.match(path))


def piece_folder_of(path):
    """`content/<portfolio>/<slug>/` when `path` is a piece `index.md` (or `work.md`), else None."""
    m = re.match(r"^(content/(?!references/|home/|about/|resume/|media/)[^/_][^/]*/[^/_][^/]*)/(?:index|work)\.md$", path)
    return m.group(1) + "/" if m else None


def is_piece_index(path):
    return bool(_PIECE_INDEX.match(path))


def disposition_of(path, ev):
    """(disposition, reason) for one tracked file. `ev` is the evidence, plain data:

      engine      set of paths in the engine set E (and 0.3.0's confirmed removals)
      kept        set of paths kept by rule 2 (inventory CUSTOM/MIXED, the person's `removal: keep`, workflows kept)
      archived    set of paths already under archive/ and listed in ARCHIVE.json
      person      {path: "archive"|"draft"|"keep"|"engine"} the plan's `files[path].disposition`
      old         set of paths the old builder used (attribution or counterfactual)
      plugin      set of paths the plugin's build attributes
      unsettled   set of paths neither measurement could settle (counterfactual cap, no measurement)
      measured    False when rules 5 to 9 cannot run (no node, a builder that fails): those files stay undisposed
      state       {path: why} (optional): builder state, which the old builder stops without and publishes nothing from
                  (rule S3, `adoption.served`): `engine`
      unusedWhy   {path: why} (optional): source material no page shows (rules S2, S3): `archived` with that note (rule
                  `unused`), never a blocker

    Returns ("undisposed", why) for what cannot be measured. First rule wins (design 8 FA)."""
    if path in ev["engine"]:
        return "engine", "the old builder's own code"
    if path in ev["kept"] or path.startswith(".site-studio/") or KEPT_ROOT_FILES.match(path) or path.startswith(".claude/"):
        return "kept", "a repository file, not content"
    if path in ev["archived"]:
        return "archived", "already under archive/"
    choice = ev["person"].get(path)
    if choice in ("archive", "draft"):
        if path in ev["old"] or path in ev["unsettled"]:
            raise Refused("%s: the old builder uses it (or that could not be settled), so it cannot be archived or made a "
                          "draft; run `adopt.py file %s keep` to say it stays" % (path, path))
        return ("draft", "your choice") if choice == "draft" else ("archived", "your choice")
    if choice == "engine" and not path.startswith(("content/", "site/src/")):
        return "engine", "your choice: the old builder's own file"
    if choice == "keep" and is_workflow(path):
        return "kept", "your choice"
    if not ev["measured"]:
        return "undisposed", "not measured (no local build): the file stays where it is"
    if path in ev["unsettled"]:
        return "undisposed", "the counterfactual could not isolate it"
    if path in (ev.get("state") or {}):                  # rule S3: the old builder stops without it and publishes nothing from it
        return "engine", ev["state"][path]
    if path in ev["old"] and path in ev["plugin"]:
        return "published", "the old builder and the plugin's build both use it"
    if path in ev["old"]:
        how = (ev.get("usedWhy") or {}).get(path)          # N1: how the old builder was judged to use it, so the person can check
        return "no-landing", "the old builder uses it%s and the plugin's build cannot hold it" % ((" (%s)" % how) if how else "")
    if is_piece_index(path) and path in ev["plugin"]:
        return "draft", "the plugin would publish a piece the old builder did not"
    if path in (ev.get("unusedWhy") or {}):              # rule S2/S3: source material no page shows (rule `unused`), never a blocker
        return "archived", ev["unusedWhy"][path]
    return "archived", "nothing builds or reads it"


def account(paths, ev):
    """{path: (disposition, reason)} for every path, EXACTLY one each, and the piece-folder rule: every other file in a
    drafted piece's folder takes `draft` and stays in place (Q1.3). The result covers `paths` and nothing else, so a test
    can compare it with `git ls-files`."""
    out = dict((p, disposition_of(p, ev)) for p in paths)
    for p, (d, _why) in list(out.items()):
        if d == "draft":
            folder = piece_folder_of(p)
            for q in paths:
                if folder and q.startswith(folder) and q != p and out[q][0] in ("archived", "published"):
                    out[q] = ("draft", "inside a draft piece's folder")
    return out


def no_landing_rows(accounting):
    """[(path, why)] for every `no-landing` file of a stored accounting (`plan["parity"]["accounting"]`), sorted by path (N1)."""
    return sorted((p, v[1]) for p, v in ((accounting or {}).get("dispositions") or {}).items() if v[0] == "no-landing")


def no_landing_lines(accounting):
    """The printed block for the `no-landing` files, each named by path with why it was judged used (N1: every place that
    prints the count names them too; `parity`, `inventory`, `apply`). Empty when there are none. Never goes into a public
    report: `blockers` writes the causes without paths."""
    rows = no_landing_rows(accounting)
    if not rows:
        return []
    return ["%d no-landing file(s), which the old builder uses and the plugin's build cannot hold (apply is blocked until each "
            "has a place or is decided):" % len(rows)] + ["  %s: %s" % row for row in rows]


def wholly_archived(paths, name, dispositions):
    """True when every tracked file of `content/<name>/` is `archived` by the measured accounting (F1, F2)."""
    files = [p for p in paths if p.startswith("content/%s/" % name)]
    return bool(files) and all(((dispositions or {}).get(p) or ("",))[0] == "archived" for p in files)


def open_folders(folders, paths, dispositions):
    """The folder decisions that still name a folder in the converted tree (F1): a `source` decision whose folder the file
    accounting wholly archived is satisfied, because the archive has already taken every file out of `content/<name>/` (nothing
    builds or reads it), so the layout class has nothing left to move and must not refuse the decision as naming no folder."""
    return dict((n, c) for n, c in (folders or {}).items() if not (c == "source" and wholly_archived(paths, n, dispositions)))


def counts(accounted):
    """{disposition: n} including `undisposed`, for `check`'s one line per disposition."""
    c = dict((d, 0) for d in DISPOSITIONS + ("undisposed",))
    for d, _why in accounted.values():
        c[d] += 1
    return c


def cmd_file(repo, path, disposition):
    """`adopt.py file <path> archive|draft|keep|engine`: the person's choice for one tracked file, in the plan (plan schema
    2). `draft` only on a piece `index.md`; `keep` and `engine` only on a workflow adopt lists for the person. Whether the
    choice is allowed for THIS file (rule 4: never on a file the old builder uses) is judged when the files are accounted."""
    base = _current_base(repo)
    plan = _plan_for(repo, base, print)
    tracked = set(p for p in gitt(repo, "ls-tree", "-r", "--name-only", base).split("\n") if p)
    if path not in tracked:
        raise Refused("%s is not a tracked file at %s; name a path that `git ls-files` lists, as in `adopt.py file <path> "
                      "keep`" % (path, base[:7]))
    if disposition == "draft" and not is_piece_index(path):
        raise Refused("only a piece's index.md can be a draft (it is the one page with a `draft` key); a page with no draft "
                      "key is archived: `adopt.py file %s archive`" % path)
    if disposition == "keep" and not is_workflow(path):
        raise Refused("`keep` is for a workflow under .github/workflows/ that adopt lists for you; %s is not one" % path)
    if disposition == "engine" and not is_workflow(path) and path.startswith(("content/", "site/src/")):
        raise Refused("%s is content (anything under content/ or site/src/), never the old builder's own file; `engine` is "
                      "for a workflow adopt lists, or a file outside those folders that only your old builder uses" % path)
    plan["files"].setdefault(path, {})["disposition"] = disposition
    save_plan(repo, plan)
    return "adopt: %s -> %s" % (path, disposition)


def archive_commit_rows(moves):
    """ARCHIVE.json rows for [(from, disposition, rule)]."""
    return [{"from": f, "disposition": d, "rule": r} for f, d, r in sorted(moves)]


def path_family(path):
    """The `no-landing` / `unobservable` family of a path: markdown, html, image, video, pdf, data, script, style, font,
    other (`parity_classes.family`, the one list)."""
    return parity_classes.family(path)


def path_area(path):
    """`content`, `site` or `root`: where a path sits, for a cause id (never the path itself)."""
    top = path.split("/")[0]
    return top if top in ("content", "site") else "root"


def basename_ext(path):
    return posixpath.splitext(path)[1].lower()
