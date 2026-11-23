"""adoption.suggestions -- the person's decisions about look suggestions, and filing one (design-adopt-ownership-line sections 13.4
and 13.5; round 2, S3, S4, M4, M8; the owner's answers to O-1 and O-5).

Part of the `adoption` package behind the entry point `adopt.py`.

THE RECORD, `.site-studio/look-suggestions.json`. Decisions only: one row per id, `state` offered (an `ask` the person said yes
to), filed, existing or declined, `issue`, the unit it was made from (`unit`, `file`, `sha256`) and its `evidence` (parity or
build). No body and no evidence number. It is written only on an adopted site (`site/site.json` converted at HEAD), and every write
is ONE commit of that file alone on the current branch, never pushed (round 2, S3): each writer prints `COMMITTED`. Before
`apply`, `--offer`, `--file` and `--decline` write nothing and say `APPLY_FIRST`. The parser is strict.

THE COMMANDS.
    suggest --offer ID                    records `offered` for an `ask` id (refused in a cloud session, S4)
    report --suggestion ID                prints exactly what would be filed, then `to file exactly this: ... --digest <12 hex>`
    report --suggestion ID --file --digest D
        1. the site is adopted, `gh` is on the path and git has a committer identity (`reports.filing_preflight`)
        2. the body is rebuilt from HEAD (a stale id is refused) and its digest must be D (M4: the caller derived the digest of
           the current text; that the text was displayed is the harness ask's, UNVERIFIED until probe P-7)
        3. the three refusals (`report_issue.leak_problems` with this body's line check; an empty term set is a refusal)
        4. `report_issue.dedupe(title_prefix=, refile=False, search=<digest token> in:title)`: an issue of the exact title, open
           or closed, is `existing`; `not-checked` files nothing (exit 1)
        5. `gh issue create --title --body`, no label (O-1)
        6. the record, committed alone
    report --suggestion ID --decline      records `declined`; the id is not offered again
`report --suggestion` refuses in a cloud session in every form, as `report` does.
"""

import json
import os
import re
import sys

import report_issue
from adoption import reports, suggest
from adoption.base import Refused, git, gitt
from adoption.tree import Tree
from contentmodel import frontmatter
from contentmodel.errors import ContentError
from reportcause import suggestion as grammar

RECORD_REL = ".site-studio/look-suggestions.json"
RECORD_SCHEMA = 1
STATES = ("offered", "filed", "existing", "declined")
EVIDENCE = ("parity", "build")
_ROW_KEYS = ("evidence", "file", "id", "issue", "sha256", "state", "unit")
COMMITTED = ("committed on %s, not pushed: the next publish refuses until it reaches main, and another session sees it only "
             "then")
APPLY_FIRST = "finish adopt.py apply first: a suggestion is recorded in the adopted repo"
CLOUD = "adopt runs on your own computer, not in a cloud session; open the repo there"
STALE = "the look changed since the review: run adopt.py suggest again"
NOT_SHOWN = "the text to file is not the text that was shown; run adopt.py report --suggestion %s and read it"
_HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")
_WORD = re.compile(r"[^\W\d_][^\W_]*")


class RecordError(ValueError):
    """The record is not one this plugin wrote; the message names the file and the fix."""


# ------------------------------------------------------------------------------------------------- the record
def parse_record(text):
    """The strict reader: exactly schema, plugin and suggestions; each row exactly `_ROW_KEYS` with a parsable id, a known state
    and evidence, sorted by id. Returns the rows."""
    fix = "restore it from an earlier commit (`git log -- %s`); adopt writes it, so never edit it by hand" % RECORD_REL
    try:
        d = json.loads(text)
    except ValueError:
        raise RecordError("%s is not JSON -- fix: %s" % (RECORD_REL, fix))
    if not isinstance(d, dict) or sorted(d) != ["plugin", "schema", "suggestions"]:
        raise RecordError("%s must hold exactly schema, plugin and suggestions; %s" % (RECORD_REL, fix))
    if isinstance(d["schema"], bool) or d["schema"] != RECORD_SCHEMA:
        raise RecordError("%s: schema %r is not understood (this site-studio reads 1); update site-studio, because a newer one "
                          "wrote it" % (RECORD_REL, d["schema"]))
    if not isinstance(d["suggestions"], list):
        raise RecordError("%s: suggestions must be a list; %s" % (RECORD_REL, fix))
    for n, row in enumerate(d["suggestions"]):
        why = _row_problem(row)
        if why:
            raise RecordError("%s: suggestions[%d] %s -- fix: %s" % (RECORD_REL, n, why, fix))
    ids = [r["id"] for r in d["suggestions"]]
    if ids != sorted(set(ids)):
        raise RecordError("%s: suggestions must be sorted by id, one row per id; %s" % (RECORD_REL, fix))
    return d["suggestions"]


def _row_problem(row):
    if not isinstance(row, dict) or tuple(sorted(row)) != _ROW_KEYS:
        return "must hold exactly %s" % ", ".join(_ROW_KEYS)
    try:
        grammar.parse_id(row["id"])
    except grammar.SuggestionError as e:
        return "id: %s" % e
    if row["state"] not in STATES:
        return "state must be one of %s" % ", ".join(STATES)
    if row["evidence"] not in EVIDENCE:
        return "evidence must be parity or build"
    if not (isinstance(row["sha256"], str) and _HEX64.match(row["sha256"])) or not isinstance(row["unit"], str) \
            or not isinstance(row["file"], str):
        return "unit and file are text and sha256 is 64 hex"
    if row["issue"] is not None and (isinstance(row["issue"], bool) or not isinstance(row["issue"], int) or row["issue"] < 1):
        return "issue must be an issue number or null"
    if row["state"] == "existing" and row["issue"] is None:
        return "an existing row names its issue"
    return None


def dump_record(rows):
    """The one written form: sorted by id, sorted keys, no date and no body."""
    out = sorted((dict(r) for r in rows), key=lambda r: r["id"])
    for r in out:
        why = _row_problem(r)
        if why:
            raise RecordError("%s: %s -- fix: this is a fault in site-studio; update the plugin" % (RECORD_REL, why))
    return json.dumps({"schema": RECORD_SCHEMA, "plugin": report_issue.plugin_version(), "suggestions": out},
                      indent=1, sort_keys=True) + "\n"


def rows_at(repo, ref="HEAD"):
    shown = git(repo, "show", "%s:%s" % (ref, RECORD_REL), check=False)
    if shown.returncode != 0:
        return []
    try:
        return parse_record(shown.stdout.decode("utf-8", "replace"))
    except RecordError as e:
        raise Refused(str(e))


def states_at(repo):
    """{id: row} of the committed record (what `suggest` prints beside each unit)."""
    return dict((r["id"], r) for r in rows_at(repo))


def commit_record(repo, rows, message):
    """Write the record and commit it alone on the current branch (an identity check, `git add -f`, a path-limited commit, as
    `reports.commit_record` does). Returns the line that says so."""
    if git(repo, "var", "GIT_COMMITTER_IDENT", check=False).returncode != 0:
        raise Refused("git has no committer identity; set user.name and user.email and run it again")
    path, text = os.path.join(repo, *RECORD_REL.split("/")), dump_record(rows)
    branch = gitt(repo, "branch", "--show-current", check=False) or "(detached HEAD)"
    if git(repo, "show", "HEAD:" + RECORD_REL, check=False).stdout == text.encode("utf-8"):
        return "the record already says so on %s: nothing to commit" % branch
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    git(repo, "add", "-f", "--", RECORD_REL)
    git(repo, "commit", "-q", "-m", message, "--", RECORD_REL)
    return COMMITTED % branch


def _with(rows, unit, state, issue=None):
    keep = [r for r in rows if r["id"] != unit.id]
    return keep + [{"id": unit.id, "unit": unit.name, "file": unit.file, "sha256": unit.entries[0][1], "state": state,
                    "issue": issue, "evidence": unit.evidence}]


# ------------------------------------------------------------------------------------------------- the unit asked for
def find(repo, sid):
    """(Review, the unit whose id is `sid` now). A malformed id and an id the look no longer gives are refused."""
    try:
        grammar.parse_id(sid)
    except grammar.SuggestionError as e:
        raise Refused(str(e))
    rv = suggest.review(repo)
    unit = next((u for u in rv.units if u.id == sid), None)
    if unit is None:
        raise Refused(STALE)
    return rv, unit


def cmd_offer(repo, sid, out=print):
    """`adopt.py suggest --offer ID`: the person said yes to an `ask`."""
    if os.environ.get("CLAUDE_CODE_REMOTE") == "true":
        raise Refused(CLOUD)
    if git(repo, "rev-parse", "--is-inside-work-tree", check=False).returncode == 0 and not _adopted(repo):
        raise Refused(APPLY_FIRST)
    rv, unit = find(repo, sid)
    if unit.cls != "ask":
        raise Refused("%s is a `suggest` line, which needs no offer: adopt.py report --suggestion %s prints its draft" % (sid, sid))
    line = commit_record(repo, _with(rows_at(repo), unit, "offered"), "adopt suggest: %s offered" % sid)
    out("suggest: %s is offered; adopt.py report --suggestion %s prints its draft" % (sid, sid))
    out(line)


# ------------------------------------------------------------------------------------------------- the body and its checks
def draft(rv, unit):
    """(title, body) of one unit, from HEAD and the measured rows only."""
    row = unit.row or {}
    parity = unit.evidence == "parity"
    body = grammar.format_body({
        "id": unit.id, "kind": unit.kind, "construct": unit.construct, "compared": unit.compared, "uses": unit.new_uses,
        "evidence": unit.evidence, "measured_at": grammar.short_sha(rv.measured_at) if parity and rv.measured_at else "",
        "verdict": rv.verdict if parity else None, "pages": unit.pages, "yours": row.get("yours") if parity else None,
        "derived": row.get("derived") if parity else None, "status": row.get("status") if parity else None,
        "literals": unit.stripped.literals, "version": report_issue.plugin_version(), "site_schema": rv.schema,
        "record_schema": RECORD_SCHEMA, "fragment": unit.stripped.text})
    return grammar.TITLE_PREFIX + unit.id, body


def site_terms(repo, rv):
    """The words a suggestion must never hold (section 13.5 layer 2): `reports.site_terms` (paths, content words) plus every class,
    id and `data-*` token, literal word and `reads` key of the site's look files, and every front-matter key of `content/`. Each
    is returned by its source too, so a test plants one per source."""
    tree = Tree(repo, "HEAD")
    sources = {"paths and content": set(reports.site_terms(repo)), "class": set(), "id": set(), "data": set(), "literal": set(),
               "reads": set(), "front matter": set()}
    for path in [p for p in tree.paths() if p.startswith("site/looks/") and p.endswith(".json")]:
        try:
            data = json.loads(tree.read(path).decode("utf-8"))
        except ValueError:
            continue
        parts = [t for c in (data.get("constructs") or {}).values() if isinstance(c, dict) for t in c.values()]
        parts += [t for e in (data.get("named") or {}).values() if isinstance(e, dict) for t in (e.get("parts") or {}).values()]
        sources["reads"].update(k for v in (data.get("reads") or {}).values() for k in _keys(v))
        sources["literal"].update(n.lower() for n in (data.get("named") or {}))
        for text in (t for t in parts if isinstance(t, str)):
            for kind, value in re.findall(r'\s(class|id|data-[a-z0-9-]+)="([^"]*)"', text):
                into = "data" if kind.startswith("data-") else kind
                sources[into].update(w.lower() for w in re.findall(r"[^\W_]+(?:[-_.][^\W_]+)*", re.sub(r"\{\{\w+\}\}", " ", value)))
                if into == "data":
                    sources["data"].add(kind[len("data-"):].lower())
            plain = re.sub(r"<[^>]*>", " ", re.sub(r'="[^"]*"', "", text))
            values = " ".join(re.findall(r'="([^"]*)"', text))
            sources["literal"].update(w.lower() for w in _WORD.findall(re.sub(r"\{\{\w+\}\}|&#?\w+;", " ", plain + " " + values))
                                      if len(w) >= 3)
    for path in [p for p in tree.paths() if p.startswith("content/") and p.endswith(".md")]:
        try:
            meta = frontmatter.parse_front_matter(tree.read(path).decode("utf-8", "replace"), path)[0]
        except (ContentError, ValueError, TypeError, IndexError):
            meta = dict.fromkeys(re.findall(r"(?m)^([A-Za-z][A-Za-z0-9_]*):", tree.read(path).decode("utf-8", "replace")))
        sources["front matter"].update(str(k).lower() for k in (meta or {}) if isinstance(k, str))
    return sources


def _keys(v):
    if isinstance(v, list):
        return [k for k in v if isinstance(k, str) and not k.startswith("@")]
    if isinstance(v, dict):
        return [k for x in v.values() for k in _keys(x if isinstance(x, list) else [x])]
    return []


def refusals(title, body, sources, shipped_ids, grammar_on=True, terms_on=True, shapes_on=True):
    """[(layer, why, found)] of the three refusals over one suggestion. An empty set of site terms is itself a refusal."""
    raw = set().union(*sources.values()) if sources else set()
    if terms_on and not raw:
        return [("site-terms", "NOT CHECKED: no site terms were read", "")]
    vocab = grammar.vocabulary(tuple(sorted(shipped_ids)))
    terms = set(t for t in raw if t not in vocab and not grammar.is_placeholder(t))
    return report_issue.leak_problems(title, body, terms, grammar=grammar_on, site_terms=terms_on, shapes=shapes_on,
                                      lines=lambda t, b: grammar.line_problems(t, b, shipped_ids))


def _refused(err, problems):
    err.write("Nothing was filed: the suggestion carries something of the site, or is outside its grammar.\n\n")
    for layer, why, found in problems:
        err.write("   %-10s %s\n              found: %r\n" % (layer, why, found))
    return 2


# ------------------------------------------------------------------------------------------------- report --suggestion
def cmd_report_suggestion(repo, sid, file=False, decline=False, digest=None, runner=None, out=None, err=None, engine=None):
    """`adopt.py report --suggestion ID [--file --digest D | --decline]`. Returns the exit code: 0 done, 1 not filed (the text is
    printed), 2 refused (nothing filed, the record unchanged)."""
    out = out if out is not None else sys.stdout
    err = err if err is not None else sys.stderr
    if os.environ.get("CLAUDE_CODE_REMOTE") == "true":
        raise Refused(CLOUD)
    if file and decline:
        raise Refused("--file and --decline are two answers; give one")
    if file and not digest:
        raise Refused("--file needs the --digest the dry print showed: run adopt.py report --suggestion %s and read it" % sid)
    if file or decline:
        if git(repo, "rev-parse", "--is-inside-work-tree", check=False).returncode != 0:
            raise Refused("%s is not a git checkout; run adopt from your site's repo folder, or pass it with --repo" % repo)
        if not _adopted(repo):
            raise Refused(APPLY_FIRST)
    if file:
        reports.filing_preflight(repo, runner)
    rv, unit = find(repo, sid)
    if decline:
        line = commit_record(repo, _with(rows_at(repo), unit, "declined"), "adopt suggest: %s declined" % sid)
        out.write("report: %s declined; it is not offered again\n%s\n" % (sid, line))
        return 0
    if unit.cls == "ask" and (states_at(repo).get(sid) or {}).get("state") != "offered":
        raise Refused("%s is an `ask`: the person decides first, and adopt.py suggest --offer %s records their yes" % (sid, sid))
    title, body = draft(rv, unit)
    shown = grammar.digest_of(title, body)
    if file and digest != shown:
        err.write(NOT_SHOWN % sid + "\n")
        return 2
    problems = refusals(title, body, site_terms(repo, rv), rv.shipped)
    if problems:
        return _refused(err, problems)
    repo_t = report_issue.tracker(engine)
    if not file:
        out.write("DRY RUN: nothing filed.\n\nrepo:   %s\ntitle:  %s\n%s\nto file exactly this: adopt.py report --suggestion %s "
                  "--file --digest %s\n" % (repo_t or "unknown", title, body, sid, shown))
        return 0
    return _file(repo, rv, unit, title, body, repo_t, runner, out, err)


def _adopted(repo):
    try:
        cfg = json.loads(gitt(repo, "show", "HEAD:site/site.json", check=False) or "{}")
    except ValueError:
        return False
    return isinstance(cfg, dict) and ("schema" in cfg or "engine" in cfg)


def _file(repo, rv, unit, title, body, repo_t, runner, out, err):
    """Steps 4 to 6: dedupe, file, record."""
    if not repo_t:
        err.write("Could not determine the tracker from this plugin's manifest; the suggestion is printed below.\n%s\n" % body)
        return 1
    rows = rows_at(repo)
    found = report_issue.dedupe(unit.id, repo_t, report_issue.plugin_version(), runner, title_prefix=grammar.TITLE_PREFIX,
                                refile=False, search="h%s in:title" % unit.stripped.digest)
    if found.state == "not-checked":
        err.write("NOT CHECKED %s: %s. Nothing filed; the record is unchanged.\n" % (unit.id, found.note))
        return 1
    if found.state == "existing":
        line = commit_record(repo, _with(rows, unit, "existing", found.issue), "adopt suggest: %s existing" % unit.id)
        out.write("%s: %s (issue #%s); nothing filed\n%s\n" % (unit.id, found.note, found.issue, line))
        return 0
    rc, stdout, why = report_issue.run_gh(["issue", "create", "--repo", repo_t, "--title", title, "--body", body], runner)
    if rc != 0:
        err.write("Could not file %s (%s). Open https://github.com/%s/issues/new and paste the text above.\n%s\n"
                  % (unit.id, why or "gh unavailable", repo_t, body))
        return 1
    m = re.search(r"/issues/(\d+)", stdout or "")
    line = commit_record(repo, _with(rows, unit, "filed", int(m.group(1)) if m else None), "adopt suggest: %s filed" % unit.id)
    out.write("Filed %s against %s\n%s\n%s\n" % (unit.id, repo_t, (stdout or "").strip(), line))
    return 0
