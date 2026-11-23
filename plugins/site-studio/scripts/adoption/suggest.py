"""adoption.suggest -- `adopt.py suggest`: which of the person's look entries could help other sites (design-adopt-ownership-line
section 13.1 to 13.3, rule C, decision 6b, dev 1012; the owner's answer to O-5, "any site").

Part of the `adoption` package behind the entry point `adopt.py`.

WHAT IT READS. Commits only: HEAD's `site/site.json`, the look files it names (`look`, `lookLocal`), the stamp, the parity record
and, when it holds a parity on HEAD, the plan; every look `templates/looks/` ships. An uncommitted look edit is not read and is
named in one line. It needs `rev-parse --is-inside-work-tree` and nothing else of `parity.preconditions`: no fetch, no clean
check, no cloud refusal. It writes no file. On a site the plugin builds (adopted, or started with `/site-studio:setup`) it makes
one build of HEAD and runs the site checks on it, which is the build evidence.

A UNIT is one entry that is the person's by rule E (`lookfiles.stamp`): a construct or named construct of `local.json`, an E2 one
of the file `look` names, with the `reads` entries whose target names it; a `reads` entry on a construct the person did not write
is a unit of its own. A construct derive wrote (E1) is never a unit.

THE RULES, in order; the first that fails decides and its reason is printed:
    G1 used        the unit renders on at least one page (the HEAD build; before apply, the measured row's pages)
    G2 evidence    PARITY: its rows (the plan's when it holds a parity on HEAD, else the committed record's, valid while the
                   record's `effective` and the entry's hash match, round 2 M6) are measured with `yours` 0. A valid row that
                   leaves a visible difference is `no`. BUILD (O-5 b, any other site): no valid row, and the HEAD build passes
                   the site checks. Neither form is `no`: "no evidence".
    G3 portable    every part places a slot; no literal address, custom element, decoration or `assets` entry; at most 99 tokens
    G4 new         its fragment (`lookfiles.strip`) is no shipped look's entry for that construct
    G5a derive gap the row's `derived` is above 0 or null, or its status is ambiguous or unmapped: `suggest`, kind `derive`
    G5b new use    its uses are not all in one shipped entry: `suggest`, kind `pattern`; else `ask`, kind `markup`

The classes (`suggest`, `ask`, `no`) are computed on every run and never stored; the person's decisions are the record
(`adoption.suggestions`), which the caller passes in as `states`.

    review(repo)                  a `Review`: the units, each judged, and the lines to say first
    cmd_suggest(repo, states)     the verb: prints, returns None
"""

import json
import os
import re
import shutil
import tempfile

import looks
from adoption.base import PARITY_RECORD_REL, PlanError, Refused, git, gitt
from adoption.lookperson import effective_hash
from adoption.parity import parse_parity_record
from adoption.plan import load_plan
from adoption.tree import Tree
from building import running
from building.outcomes import BuildError
from configschema import model as config_model
from configschema.configkeys import DERIVED_LOOK_PATH, LOOK_LOCAL_PATH, STAMP_REL
from configschema.diagnostics import SiteConfigError
from adoption.lookkeep import rendering_on
from lookfiles import stamp, strip
from lookfiles.renderlog import recording
from lookgrammar.constructs import CONSTRUCTS, OPTIONAL_PARTS, URL_ATTRS
from lookgrammar.errors import LookError
from lookgrammar.reads import READS
from sitechecks.checker import check_tree

SHIPPED_DIR = os.path.join(looks.PLUGIN_ROOT, "templates", "looks")
ID_FORM = "ss-look/%s/%s/h%s"
TOKENS_MAX = 99
CLOUD_LINE = ("suggest: this is a cloud session, so a draft can be printed and filed only on your own computer; open the repo "
              "there to run adopt.py report --suggestion")
APPLY_FIRST = "a suggestion can be recorded and filed after adopt.py apply"
NO_EVIDENCE = ("no parity evidence for this version of the entry: commit it, then run adopt.py parity (before apply) or adopt.py "
               "remeasure")
_TAGS = re.compile(r"<([a-zA-Z][a-zA-Z0-9-]*)")
_ATTR = re.compile(r'\s([a-zA-Z][a-zA-Z0-9-]*)="([^"]*)"')
_SLOT = re.compile(r"\{\{([a-z][A-Za-z0-9]*)\}\}")


class Unit(object):
    """One unit and what the rules said of it. `name` is the construct or named construct's name, `construct` the plugin construct
    it renders as, `file` the look file, `edited` an E2 entry of a derived look, `parts`, `assets`, `reads` ({target: value}),
    `named` (the name, or None), `entries` [(row name, hash)]; after `judge`: `cls`, `kind`, `reason`, `evidence`, `row`, `pages`,
    `stripped`, `nearest` ((look id, Stripped) or None), `new_uses`, `id`."""

    def __init__(self, name, construct, file, edited, parts, assets, named=None):
        self.name, self.construct, self.file, self.edited = name, construct, file, edited
        self.parts, self.assets, self.named, self.reads, self.entries = dict(parts or {}), assets, named, {}, []
        self.cls = self.kind = self.reason = self.evidence = self.row = self.id = None
        self.pages, self.stripped, self.nearest, self.new_uses, self.reads_only, self.compared = 0, None, None, [], False, []

    def label(self):
        return "%s (%s%s)" % (self.name, self.file, ", edited" if self.edited else "")


class Review(object):
    """What `review` found: `units`, `lines` (said before the units), `adopted` (site.json is converted at HEAD), `verdict` and
    `measured_at` (the parity the rows came from, or None), `schema` (site.json's), `shipped` ({look id: data})."""

    def __init__(self):
        self.units, self.lines, self.adopted, self.verdict, self.measured_at, self.schema, self.shipped = [], [], False, None, None, None, {}


# ------------------------------------------------------------------------------------------------- reading HEAD
def _json(tree, path):
    if not tree.exists(path):
        return None
    try:
        data = json.loads(tree.read(path).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise Refused("%s at HEAD is not valid JSON; fix it, commit it, and run adopt.py suggest again" % path)
    return data if isinstance(data, dict) else None


def shipped_looks():
    """{look id: parsed JSON} of every look `templates/looks/` ships."""
    out = {}
    for fn in sorted(os.listdir(SHIPPED_DIR)):
        if fn.endswith(".json"):
            with open(os.path.join(SHIPPED_DIR, fn), encoding="utf-8") as fh:
                out[fn[:-len(".json")]] = json.load(fh)
    return out


def _uncommitted(repo, names):
    """The one line for look files (and site.json) that differ from HEAD in the working copy, or None."""
    st = gitt(repo, "status", "--porcelain", "--untracked-files=all", "--", "site/site.json", "site/looks", check=False)
    paths = sorted(line[3:] for line in st.split("\n") if line.strip())
    if not paths:
        return None
    return ("suggest: %s %s uncommitted changes, which are not read (suggest reads the committed look): commit them, then run "
            "adopt.py suggest again" % (", ".join(paths), "has" if len(paths) == 1 else "have"))


def units_of(tree, cfg, repo):
    """(the person's units in the HEAD tree, the ownership lines): rule E over the file `look` names, and all of `lookLocal`."""
    units, lines, files = {}, [], {}
    look_ref = cfg.get("look") if isinstance(cfg.get("look"), str) else None
    local_ref = cfg.get("lookLocal") if isinstance(cfg.get("lookLocal"), str) else None
    if local_ref is None and not ("schema" in cfg or "engine" in cfg):
        local_ref = LOOK_LOCAL_PATH             # before apply, the conversion lays the file over the look (`lookwrite.carry`)
    sources = []
    if look_ref and tree.exists(look_ref):
        files = {look_ref: tree.read(look_ref)}
        if tree.exists(STAMP_REL):
            files[STAMP_REL] = tree.read(STAMP_REL)
        try:
            own = stamp.ownership_at(files, look_ref, repo, "HEAD")
        except stamp.StampError as e:
            raise Refused(str(e))
        lines.extend(own.lines)
        sources.append((look_ref, _json(tree, look_ref) or {}, own.yours, look_ref == DERIVED_LOOK_PATH))
    if local_ref and tree.exists(local_ref):
        data = _json(tree, local_ref) or {}
        sources.append((local_ref, data, set(stamp.entry_hashes(data)), False))
    reads = {}
    for ref, data, yours, edited in sources:                # local.json last: what it holds replaces the other's whole (P2, P3)
        hashes = stamp.entry_hashes(data)
        for key in sorted(k for k in hashes if k in yours and k != stamp.STYLESHEETS):
            kind, _sep, rest = key.partition(":")
            if kind == "reads":
                reads[rest] = (ref, edited, data["reads"][rest], hashes[key])
            elif kind == "named":
                entry = (data.get("named") or {}).get(rest) or {}
                units[rest] = Unit(rest, entry.get("like"), ref, edited, entry.get("parts"), None, rest)
                units[rest].entries.append(("look." + rest, hashes[key]))
            else:
                units[key] = Unit(key, key, ref, edited, (data.get("constructs") or {}).get(key),
                                  (data.get("assets") or {}).get(key))
                units[key].entries.append(("look." + key, hashes[key]))
    for target in sorted(reads):
        ref, edited, value, h = reads[target]
        host = next((u for _n, u in sorted(units.items()) if u.construct == target.split(".")[0] and not u.reads_only), None)
        if host is None:
            host = units.setdefault("reads:" + target, Unit(target, target.split(".")[0], ref, edited, {}, None))
            host.reads_only = True
        host.reads[target] = value
        host.entries.append(("reads." + target, h))
    return [units[k] for k in sorted(units)], lines


def evidence_rows(repo, tree, head):
    """(rows {row name: (value, how)}, verdict, measured at, valid(name, hash)): the plan's when it holds a parity on HEAD, else the
    committed record's (valid only while its `effective` matches HEAD, round 2 M6), else none."""
    try:
        plan = load_plan(repo)
    except PlanError:
        plan = None
    if plan and plan.get("parity") and plan.get("base") == head:
        rows = dict((n, (r["value"], r["how"])) for n, r in (plan.get("settings") or {}).items() if n.startswith(("look.", "reads.")))
        return rows, plan["parity"].get("verdict"), head, lambda n, h: n in rows and rows[n][0].get("sha256") == h
    if not tree.exists(PARITY_RECORD_REL):
        return {}, None, None, lambda n, h: False
    try:
        record = parse_parity_record(tree.read(PARITY_RECORD_REL).decode("utf-8", "replace"))
    except PlanError as e:
        raise Refused(str(e))
    rows = dict((n, (v, "measured")) for n, v in (record.get("look") or {}).items())
    now = effective_hash(lambda p: tree.read(p) if tree.exists(p) else None)
    ok = record.get("effective") == now

    def valid(name, h):
        return ok and name in rows and rows[name][0]["sha256"] == h
    return rows, record["verdict"], record["basis"] or None, valid


def head_build(repo):
    """(pages {output path: html}, recorded calls, the first refusal or None, the first site-check finding or None): one publish
    build of HEAD, recorded, and the site checks on it (what `check_site.py` runs)."""
    tmp = tempfile.mkdtemp(prefix="ss-suggest-")
    out = os.path.join(tmp, "dist")
    try:
        with recording() as calls:
            try:
                running.publish_build(repo, out)
            except BuildError as e:
                return {}, [], str(e).split("\n")[0], None
        try:
            cfg = config_model.parse_text(gitt(repo, "show", "HEAD:site/site.json", check=False))
            rep = check_tree(out, cfg, repo)
        except (SiteConfigError, ValueError) as e:
            return {}, [], None, str(e).split("\n")[0]
        pages = {}
        for root, _dirs, names in os.walk(out):
            for n in names:
                if n.lower().endswith((".html", ".htm")):
                    p = os.path.join(root, n)
                    with open(p, encoding="utf-8", errors="replace") as fh:
                        pages[os.path.relpath(p, out).replace(os.sep, "/")] = fh.read()
        first = rep.findings[0] if rep.findings else None
        return pages, list(calls), None, ("%s: %s" % (first.path, first.message)) if first else None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------------------------------------------- the rules
def portable_problem(u):
    """G3: the first reason the unit cannot be carried to another site, or None."""
    if u.assets:
        return "it has an assets entry, which carries files of the site"
    for pn in sorted(u.parts):
        text = u.parts[pn] if isinstance(u.parts[pn], str) else ""
        if not _SLOT.search(text):
            return "the part %s places no slot, so it prints the same words on every site" % pn
        for tag in _TAGS.findall(text):
            if tag.lower() == "svg":
                return "the part %s holds a decoration" % pn
            if "-" in tag:
                return "the part %s holds the custom element <%s>" % (pn, tag.lower())
        for name, value in _ATTR.findall(text):
            if name.lower() in URL_ATTRS and value and not _SLOT.fullmatch(value) and not value.startswith("#"):
                return "the part %s holds a literal address" % pn
    if len(strip.tokens_of(u.parts)) > TOKENS_MAX:
        return "it holds more than %d class and id tokens" % TOKENS_MAX
    return None


def uses_of(construct, parts, reads, named):
    """The grammar a unit (or a shipped entry) uses: `part.slot` placements, variant parts, `reads` targets with their shape, and
    `named:<like>`."""
    out = set()
    for pn, text in (parts or {}).items():
        for slot in _SLOT.findall(text if isinstance(text, str) else ""):
            out.add("%s.%s.%s" % (construct, pn, slot))
        if (construct, pn) in OPTIONAL_PARTS or not looks.default_renders(construct, pn):
            out.add("%s.%s" % (construct, pn))
    for target, value in (reads or {}).items():
        srcs = value if isinstance(value, list) else list((value or {}).get("from") or [])
        shape = sorted(s for s in srcs if isinstance(s, str) and s.startswith("@"))
        if isinstance(value, dict) and "unless" in value:
            shape.append("unless")
        out.add("reads %s%s" % (target, (" [%s]" % ", ".join(shape)) if shape else ""))
    if named:
        out.add("named:%s" % construct)
    return out


def shipped_entries(shipped, construct, default_parts):
    """[(look id, uses, Stripped)] of every shipped entry for `construct`: each look's construct and its named constructs like it."""
    out = []
    for lid in sorted(shipped):
        data = shipped[lid]
        reads = dict((t, v) for t, v in (data.get("reads") or {}).items() if t.split(".")[0] == construct)
        if construct in (data.get("constructs") or {}):
            parts = data["constructs"][construct]
            out.append((lid, uses_of(construct, parts, reads, None), strip.strip(construct, parts, reads, None, default_parts)))
        for name in sorted(data.get("named") or {}):
            entry = data["named"][name]
            if entry.get("like") == construct:
                out.append((lid, uses_of(construct, entry["parts"], reads, name),
                            strip.strip(construct, entry["parts"], reads, name, default_parts)))
    return out


def fragment_problem(stripped):
    """None when the fragment passes the template-look reading (one entry alone: the look-wide pairs run on a layered look)."""
    try:
        looks.parse(stripped.text, "fragment", shipped=True, template=True, cross=False)
    except LookError as e:
        return str(e).split("\n")[0]
    return None


def _row_of(u, rows):
    name = u.entries[0][0] if u.entries else None
    return rows.get(name, (None, None))[0] if name else None


def judge_evidence(u, rows, valid, build, adopted):
    """G1 and G2 for one unit: sets `pages`, `evidence`, `row`, or `cls = "no"` with the reason. `build` is head_build's result,
    or None before apply (the plugin does not build an unconverted site)."""
    good = [(n, h) for n, h in u.entries if valid(n, h)]
    if good and len(good) == len(u.entries):
        vals = [rows[n][0] for n, _h in good]
        worst = max((v.get("yours") or 0) for v in vals)
        if any(rows[n][1] != "measured" for n, _h in good) or worst:
            return _no(u, "leaves %d visible difference(s); a suggestion carries an entry that leaves none" % max(worst, 1))
        u.row, u.pages, u.evidence = vals[0], vals[0].get("pages") or 0, "parity"
    if build is None:
        if u.evidence is None:
            return _no(u, NO_EVIDENCE)
        if not u.pages:
            return _no(u, "not reached: no page renders it")
        return True
    pages, calls, refused, finding = build
    if refused:
        return _no(u, "refused by the build: %s" % refused)
    on = rendering_on(pages, calls, set([u.construct, u.name]))
    seen = sorted(p for p, cids in on.items() if cids)
    if not seen:
        return _no(u, "not reached: no page renders it")
    if u.evidence is None:
        if finding:
            return _no(u, "no evidence: no parity row measures this version of it, and the build of HEAD does not pass the site "
                          "checks (%s); fix that, commit, and run adopt.py suggest again" % finding)
        u.pages, u.evidence = len(seen), "build"
    return True


def _no(u, reason):
    u.cls, u.reason = "no", reason
    return False


def judge(u, rows, valid, build, adopted, shipped, default_look):
    """Every rule for one unit, in order. Sets `cls`, `kind`, `reason`, `id`."""
    if u.construct not in CONSTRUCTS:
        return _no(u, "%s reads a value of the page, not of a look construct, so no fragment of it can be compared"
                      % (u.name if u.reads_only else u.construct))
    if not judge_evidence(u, rows, valid, build, adopted):
        return False
    why = portable_problem(u)
    if why:
        return _no(u, why)
    default_parts = (default_look.get("constructs") or {}).get(u.construct)
    u.stripped = strip.strip(u.construct, u.parts, u.reads, u.named, default_parts) if u.parts or u.named else \
        strip.strip(u.construct, {}, u.reads, None, default_parts)
    bad = fragment_problem(u.stripped)
    if bad:
        return _no(u, "its fragment is not a template look: %s" % bad)
    entries = shipped_entries(shipped, u.construct, default_parts)
    u.compared = sorted(set(lid for lid, _uses, _s in entries))
    same = [lid for lid, _uses, s in entries if s.text == u.stripped.text]
    if same:
        return _no(u, "already shipped in %s" % same[0])
    row = u.row or {}
    if u.evidence == "parity" and (row.get("derived") is None or row.get("derived", 0) > 0
                                   or row.get("status") in ("ambiguous", "unmapped")):
        u.cls, u.kind = "suggest", "derive"
        u.reason = "derive reads it %s; with it the plugin's pages equal the old builder's" % (
            "as %s" % row.get("status") if row.get("status") in ("ambiguous", "unmapped") else
            "with %s visible difference(s)" % row.get("derived") if row.get("derived") else "not at all")
    else:
        mine = uses_of(u.construct, u.parts, u.reads, u.named)
        covering = [(lid, s) for lid, uses, s in entries if mine <= uses]
        if covering:
            u.cls, u.kind, u.nearest = "ask", "markup", covering[0]
            u.reason = "the slots and parts of %s; only the markup differs" % covering[0][0]
        else:
            best = max(entries, key=lambda e: len(mine & e[1])) if entries else (None, set(), None)
            u.new_uses = sorted(mine - best[1])
            u.cls, u.kind = "suggest", "pattern"
            u.reason = "places %s, which no shipped look does" % ", ".join(u.new_uses)
    u.id = ID_FORM % (u.kind, u.construct, u.stripped.digest)
    return True


# ------------------------------------------------------------------------------------------------- the review
def review(repo, build=None):
    """The whole review of HEAD (nothing written). `build` is a test's seam for `head_build`."""
    if git(repo, "rev-parse", "--is-inside-work-tree", check=False).returncode != 0:
        raise Refused("%s is not a git checkout; run adopt from your site's repo folder, or pass it with --repo" % repo)
    head = gitt(repo, "rev-parse", "--verify", "-q", "HEAD^{commit}", check=False)
    if not head:
        raise Refused("this repo has no commit yet; commit the site, then run adopt.py suggest again")
    tree = Tree(repo, head)
    rv = Review()
    cfg = _json(tree, "site/site.json")
    if cfg is None:
        raise Refused("this repo has no site/site.json at HEAD; start a site with /site-studio:setup, or adopt one with adopt.py")
    rv.adopted, rv.schema = ("schema" in cfg or "engine" in cfg), cfg.get("schema")
    line = _uncommitted(repo, ())
    if line:
        rv.lines.append(line)
    rv.units, own_lines = units_of(tree, cfg, repo)
    rv.lines.extend("note: %s" % l for l in own_lines if rv.units)
    if not rv.units:
        return rv
    rows, rv.verdict, rv.measured_at, valid = evidence_rows(repo, tree, head)
    built = (build or head_build)(repo) if rv.adopted else None
    rv.shipped = shipped_looks()
    default_look = rv.shipped.get("site-studio") or {}
    for u in rv.units:
        judge(u, rows, valid, built, rv.adopted, rv.shipped, default_look)
    return rv


def _compact(stripped):
    return json.dumps(stripped.fragment, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def unit_lines(u, state=None):
    """The line(s) `suggest` prints for one unit; `state` is the record's decision for its id ({"state", "issue"} or None)."""
    if u.cls != "no" and state is not None:
        if state["state"] == "declined":
            return ["no       %s: declined (%s); it is not offered again" % (u.label(), u.id)]
        if state["state"] in ("filed", "existing"):
            return ["no       %s: already on the tracker as issue #%s (%s)" % (u.label(), state.get("issue") or "?", u.id)]
        if state["state"] == "offered" and u.cls == "ask":
            return ["suggest  %s  %s: offered; %s" % (u.id, u.label(), u.reason)]
    if u.cls == "no":
        return ["no       %s: %s" % (u.label(), u.reason)]
    out = ["%-8s %s  %s: %s; evidence: %s" % (u.cls, u.id, u.label(), u.reason,
                                              "parity" if u.evidence == "parity" else "build only")]
    if u.cls == "ask":
        out.append("  yours:   %s" % _compact(u.stripped))
        out.append("  %s: %s" % (u.nearest[0], _compact(u.nearest[1])))
    return out


def cmd_suggest(repo, states=None, out=print):
    """`adopt.py suggest`: print the review. `states` is {id: record row} (`adoption.suggestions.states_at`)."""
    rv = review(repo)
    cloud = os.environ.get("CLAUDE_CODE_REMOTE") == "true"
    for line in rv.lines:
        out(line)
    if not rv.units:
        out("suggest: no entry of this look is yours (rule E: a construct derive wrote is not an addition), so there is nothing "
            "to offer; an entry you write in site/looks/local.json (with lookLocal) is one")
    counts = {"suggest": 0, "ask": 0, "no": 0}
    for u in rv.units:
        lines = unit_lines(u, (states or {}).get(u.id))
        counts[lines[0].split(" ", 1)[0]] += 1                 # the class as printed: the record's decision counted
        for line in lines:
            out(line)
    if rv.units:
        out("suggest: %d to draft, %d to ask the person about, %d not offered%s" % (
            counts["suggest"], counts["ask"], counts["no"],
            ("; adopt.py report --suggestion <id> prints a draft" if counts["suggest"] else "") +
            ("" if rv.adopted or not (counts["suggest"] or counts["ask"]) else "; " + APPLY_FIRST)))
    if cloud:
        out(CLOUD_LINE)
    return rv
