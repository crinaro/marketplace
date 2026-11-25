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
    kept        repository files that are not content (`.site-studio/**`, README, LICENSE, ...) and what the person kept (rule K: a
                kept file the old builder does not use and the plugin's build would not newly publish; one the old builder uses
                is `published` or `no-landing` as without the choice, one the build would newly publish is `undisposed`)
    no-landing  the old builder used it and the plugin's build cannot hold it: content the visitor would lose; it BLOCKS

`unobservable/<family>` is not a disposition: it is a group the counterfactual could not split inside its run cap, which
stays undisposed (and so blocks) with only a count.

THE ARCHIVE RECORD (`archive/ARCHIVE.json`, design 3.5): {"schema": 1, "files": [{"from", "disposition", "rule"}]}, sorted
by `from`, no dates; `parse_archive` is its strict reader and `archive_path` the one place that says where a file lands.
"""

import hashlib
import json
import posixpath
import re

import parity_classes

from adoption.base import PlanError, Refused
from adoption.parity import current_parity, stale_parity
from adoption.plan import _current_base, _plan_for, save_plan
from adoption.tree import Tree

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
      unsettledWhy {path: why} (optional): why each of them is unsettled (`usage.WHY_*`), printed in place of a general reason
      late        {path: keep|own|nested} (optional): the late files the counterfactual was asked about (design-reference-layout 4.2)
      lateUnsettled {path: keep|own|nested} (optional): the late files it left unsettled, which block nothing (4.3, 4.4): a kept
                  file and the plugin's own `decisions/**` and `BRAND.md` are `kept`, "not measured: why"; a nested repository
                  file stays `archived` as 0.8.0 archived it, the reason saying it was not tried
      serves      {path: address} (optional): the files the person KEEPS (and the old builder is not shown to use) that the plugin's
                  build serves, at the address it serves them ("" when it is not known): rule K (design-reference-layout 4.3)
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
        if path in ev["old"] or path in ev["unsettled"] or (ev.get("lateUnsettled") or {}).get(path) == "own":
            raise Refused("%s: the old builder uses it (or that could not be settled), so it cannot be archived or made a "
                          "draft; `adopt.py file %s --clear` forgets your choice" % (path, path))
        return ("draft", "your choice") if choice == "draft" else ("archived", "your choice")
    if choice == "engine" and not path.startswith(("content/", "site/src/")):
        return "engine", "your choice: the old builder's own file"
    if choice == "keep" and is_workflow(path):
        return "kept", "your choice"
    if not ev["measured"]:
        return "undisposed", "not measured (no local build): the file stays where it is"
    why = (ev.get("unsettledWhy") or {}).get(path)
    late = (ev.get("lateUnsettled") or {}).get(path)
    served = (ev.get("serves") or {}).get(path) if choice == "keep" and path not in ev["old"] else None
    if served is not None:                               # rule K (3) (4.3): the build would newly publish it, settled or not
        return "undisposed", _would_publish(path, served)
    if late:                                             # a late file the bounds left over blocks nothing: it stays where it is
        if late == "nested":
            return "archived", "nothing was found to build or read it (%s)" % (why or "not tried")
        return "kept", "not measured: %s" % (why or "not tried")
    if choice == "keep" and path not in ev["old"]:       # rule K (4.3): a kept file is judged here, never hidden; a used one follows 1 and 2
        return "kept", "your choice"
    if path in ev["unsettled"]:
        return "undisposed", why or "the counterfactual could not isolate it"
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
    if (ev.get("late") or {}).get(path) == "own":       # the plugin's own dev-repo file, tried and not used (4.4)
        return "kept", "the plugin's own dev-repo file; the old builder does not use it"
    return "archived", "nothing builds or reads it"


def address_of(out_path):
    """The address a visitor types for the output path `out_path`: `work/a/index.html` is `/work/a/`, `media/s.txt` is `/media/s.txt`."""
    if not re.search(r"(?:^|/)index\.html?$", out_path):
        return "/" + out_path
    folder = re.sub(r"(?:^|/)index\.html?$", "", out_path).strip("/")
    return "/%s/" % folder if folder else "/"


def _would_publish(path, address):
    """Rule K (3), the reason of a kept file the plugin's build would publish and the old site does not (design-reference-layout 4.3)."""
    where = (" at %s" % address) if address else ""
    if is_piece_index(path):
        return ("keeping it would publish this piece%s, where your old site has nothing: `adopt.py file %s --clear` forgets the "
                "choice, and the piece is a draft as today" % (where, path))
    return ("keeping it would publish it%s, where your old site has nothing: `adopt.py file %s archive` it, or `adopt.py file %s "
            "--clear`" % (where, path, path))


def account(paths, ev):
    """{path: (disposition, reason)} for every path, EXACTLY one each, and the piece-folder rule: every other file in a
    drafted piece's folder takes `draft` and stays in place (Q1.3). The result covers `paths` and nothing else, so a test
    can compare it with `git ls-files`. A file whose archive address already holds another tracked file stays `undisposed` with the
    reason (`ARCHIVE_TAKEN`): adopt never writes over a file of the person's own."""
    out = dict((p, disposition_of(p, ev)) for p in paths)
    for p, (d, _why) in list(out.items()):
        if d == "draft":
            folder = piece_folder_of(p)
            for q in paths:
                if folder and q.startswith(folder) and q != p and out[q][0] in ("archived", "published"):
                    out[q] = ("draft", "inside a draft piece's folder")
    held = set(paths)
    for p, (d, _why) in list(out.items()):
        if d == "archived" and not p.startswith("archive/") and archive_path(p) in held:
            out[p] = ("undisposed", ARCHIVE_TAKEN % (archive_path(p), p))
    return out


ARCHIVE_TAKEN = ("%s already holds a file of yours, so adopt will not archive this file over it: rename or move one of them, or keep "
                 "this one where it is (`adopt.py file %s keep`)")


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


def plan_choices(plan, workflows=False):
    """{path: disposition} of the person's choices for files in `plan`; the workflows left out unless asked for. Without them it is
    what `run_accounting` stores as `accounting["choices"]` and `stale_choices` compares (`apply` reads a workflow's choice itself,
    `adoption.engine`); with them it is what `--clear` may forget."""
    return dict((p, e["disposition"]) for p, e in plan["files"].items()
                if e.get("disposition") and (workflows or not is_workflow(p)))


def stale_choices(plan):
    """[path] whose choice differs between the plan and the accounting that stands (`plan["parity"]["accounting"]["choices"]`, 4.3):
    a choice made, changed or forgotten after `parity`, which `apply` would otherwise act on unmeasured (0.8.0 archived a file
    kept after `parity`, unsaid). It compares the choices, never a reason string. Empty when there is no accounting this site-studio
    measured: a parity another version measured is read as none (`stale_parity`), and one with no `choices` is not one this version
    stored."""
    acct = (current_parity(plan.get("parity")) or {}).get("accounting")
    if not acct or not isinstance(acct.get("choices"), dict):
        return []
    was, now = dict((p, d) for p, d in acct["choices"].items() if not is_workflow(p)), plan_choices(plan)
    return sorted(p for p in set(was) | set(now) if was.get(p) != now.get(p))


MEASURED_VERDICTS = ("EQUAL", "MARKUP-ONLY", "ACCEPTED", "DIFFERENT")      # a verdict that says something about pages


def answers(plan):
    """{answer: what it says now} of the person's answers parity builds with, less the files': each setting the plan writes (a derived
    look as its sha256; one that writes nothing is no answer), the site kind, each folder, each conversion they chose. `cmd_parity`
    stores it as `parity["answers"]`; `stale_answers` compares."""
    out = {}
    for name, row in (plan.get("settings") or {}).items():
        if row["how"] in ("measured", "chosen") and row["value"] is not None and not (name == "referenceLayout" and not row["value"]):
            text = json.dumps(row["value"], sort_keys=True)
            out["setting %s" % name] = hashlib.sha256(text.encode("utf-8")).hexdigest() if isinstance(row["value"], dict) else text
    if plan.get("siteKind") not in (None, "portfolio"):
        out["kind"] = plan["siteKind"]
    out.update(("folder %s" % n, c) for n, c in (plan.get("folders") or {}).items())
    out.update(("convert %s" % c, "yes") for c in plan.get("convert") or ())
    return out


def stale_answers(plan):
    """[answer] that differ between the plan and the parity that stands (review of 2026-11-25, the class): a setting, kind, folder or
    conversion set, changed or forgotten after `parity`, which `apply` would write unmeasured and record under a verdict that is not
    about it. Empty where parity measured no page (UNVERIFIED: nothing is claimed) or holds no `answers` of this version's."""
    parity = current_parity(plan.get("parity")) or {}
    if parity.get("verdict") not in MEASURED_VERDICTS or not isinstance(parity.get("answers"), dict):
        return []
    was, now = parity["answers"], answers(plan)
    return sorted(a for a in set(was) | set(now) if was.get(a) != now.get(a))


def stale_line(plan):
    """The line that names `stale_choices` and `stale_answers` and the way on, or "" when there are none."""
    paths, told = stale_choices(plan), stale_answers(plan)
    said = ([("for %d file(s)" % len(paths), paths)] if paths else []) + ([("on %d answer(s)" % len(told), told)] if told else [])
    if not said:
        return ""
    return ("your choice %s is newer than the last `adopt.py parity` (%s): run `adopt.py parity` again, which measures it"
            % (" and ".join(w for w, _n in said), "; ".join(", ".join(n[:5]) + (" and %d more" % (len(n) - 5) if len(n) > 5 else "")
                                                             for _w, n in said)))




def undisposed_rows(accounting):
    """[(path, why)] for every `undisposed` file of a stored accounting, sorted by path (A6)."""
    return sorted((p, v[1]) for p, v in ((accounting or {}).get("dispositions") or {}).items() if v[0] == "undisposed")


def undisposed_lines(accounting):
    """The block `check`, `inventory` and `apply --dry-run` print for the files that block `apply` (4.6): the count, one line per
    reason with its count and EVERY path (review of 2026-11-25, item 3: nothing held is hidden), and the way out. Empty when there are
    none."""
    rows = undisposed_rows(accounting)
    if not rows:
        return []
    by = {}
    for path, why in rows:
        by.setdefault(why, []).append(path)
    order = sorted(by.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    out = ["%d file(s) are undisposed and will block apply:" % len(rows)]
    for why, paths in order:
        out.append("  %d file(s): %s: %s" % (len(paths), why, ", ".join(paths)))
    out.append("  to settle them: `adopt.py file <path or folder> keep` says it stays where it is, then run `adopt.py parity`")
    return out


def said_before_apply(plan):
    """What `check` and `inventory` print of the file accounting (4.6), from the plan's last accounting on this basis: the stale
    choices, then the undisposed block. A parity another site-studio measured prints its own line and no block; no parity says it was
    not measured yet; a parity with no accounting prints its own reason and no instruction that cannot succeed."""
    parity = plan.get("parity")
    stale = stale_parity(parity)
    if stale:
        return ["file accounting: " + stale]
    if not parity:
        return ["file accounting: not measured yet: run `adopt.py parity`"]
    acct = parity.get("accounting")
    if not acct or acct.get("refused"):
        return ["file accounting: not run (%s)" % ((acct or {}).get("refused") or parity.get("reason") or parity.get("verdict"))]
    return [l for l in (stale_line(plan),) if l] + undisposed_lines(acct)


def _targets(tracked, path, disposition):
    """The tracked files a `file` verb on `path` names: the file, or every tracked file below a folder (with or without `/`),
    for `keep` and `archive` only (4.3)."""
    if path in tracked:
        return [path]
    prefix = path.rstrip("/") + "/"
    below = [p for p in sorted(tracked) if p.startswith(prefix)]
    if not below:
        raise Refused("%s is not a tracked file or folder at the basis; name a path that `git ls-files` lists, as in `adopt.py file "
                      "<path> keep`" % path)
    if disposition not in ("keep", "archive"):
        raise Refused("%s is a folder: `%s` takes one file at a time. `keep` and `archive` take a whole folder, and each file "
                      "below it records its own choice" % (path, disposition))
    return below


def _clear(plan, path):
    """Forget the choice for `path`, or for every file below it when it is a folder; the paths cleared. An entry the verb made and
    nothing else holds goes with it. Refused, naming the choices there are, when there is none to clear."""
    held = plan_choices(plan, workflows=True)
    prefix = path.rstrip("/") + "/"
    hit = [p for p in sorted(held) if p == path or p.startswith(prefix)]
    if not hit:
        raise Refused("%s has no choice to clear (choices: %s); name a path that has one, or leave it as it is"
                      % (path, ", ".join("%s %s" % (p, held[p]) for p in sorted(held)) or "none"))
    for p in hit:
        plan["files"][p].pop("disposition")
        if not plan["files"][p]:
            del plan["files"][p]
    return hit


def cmd_file(repo, path, disposition=None, clear=False):
    """`adopt.py file <path> archive|draft|keep|engine`, or `adopt.py file <path> --clear`: the person's choice for one tracked file, in
    the plan (plan schema 2; a `keep` on a file that is not a workflow, schema 5). `keep` takes any tracked file, and `keep` and
    `archive` a folder, one entry per tracked file below it (4.3); `draft` only a piece `index.md`, and `engine` a workflow or a file
    outside `content/` and `site/src/`. Whether the choice is allowed for THIS file (rule 4: never `archive` on a file the old builder
    uses) is judged when the files are accounted, and a choice made after `parity` says so (`stale_line`)."""
    base = _current_base(repo)
    plan = _plan_for(repo, base, print)
    if clear:
        if disposition:
            raise Refused("--clear forgets your choice, so it takes none: `adopt.py file %s --clear`" % path)
        done = _clear(plan, path)
        save_plan(repo, plan)
        return "adopt: %s: your choice is forgotten%s; the next `parity` measures it again" % (
            path, (" for %d file(s)" % len(done)) if done != [path] else "")
    if not disposition:
        raise Refused("say what to do with %s: `adopt.py file %s keep`, `archive`, `draft` or `engine`, or forget a choice with "
                      "`adopt.py file %s --clear`" % (path, path, path))
    targets = _targets(set(Tree(repo, base).paths()), path, disposition)
    for p in targets:
        if disposition == "draft" and not is_piece_index(p):
            raise Refused("only a piece's index.md can be a draft (it is the one page with a `draft` key); a page with no draft "
                          "key is archived: `adopt.py file %s archive`" % p)
        if disposition == "engine" and not is_workflow(p) and p.startswith(("content/", "site/src/")):
            raise Refused("%s is content (anything under content/ or site/src/), never the old builder's own file; `engine` is "
                          "for a workflow adopt lists, or a file outside those folders that only your old builder uses" % p)
    for p in targets:
        plan["files"].setdefault(p, {})["disposition"] = disposition
    save_plan(repo, plan)
    return "\n".join(["adopt: %s -> %s%s" % (path, disposition, (" (%d files below it)" % len(targets)) if targets != [path] else "")]
                     + [l for l in (stale_line(plan),) if l])


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
