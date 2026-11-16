#!/usr/bin/env python3
"""siteconfig.py -- the strict parser, and the ONLY writer, of `site/site.json` (schemas 1, 2 and 3).

dev #835, design section 3.2 and named change S10. Python 3.9, standard library only.

WHAT THIS FILE IS FOR
---------------------
`site.json` is a stored data shape (CLAUDE.md principle 4): a named field, a strict parser that
refuses what it cannot read, and a loud failure on an unknown key or a wrong type. Nothing in
the plugin reads `site.json` any other way, and nothing writes it any other way.

* `parse_text` / `load` read. An unknown key, a wrong type, a duplicate key, a bad value: each
  refuses with a `SiteConfigError` naming the field.
* A file whose `schema` is NEWER than this plugin reads gets ONE distinct refusal and never an
  unknown-key error (an older install reading a newer file must say "update", not "bad key"):
  `site.json schema N is newer than this plugin understands (it reads up to M); update site-studio`.
* `write` is the only writer. It always writes the one canonical form (S10): every known key, in
  schema order, two-space indent, UTF-8, one trailing LF. That form carries the marker line
  `  "engine": "site-studio",` exactly, which is what the SessionStart prefilter greps for.
  `marker_status` / `is_canonical_marker` report whether a file's marker is in that form, and
  `marker_state` says which way it is wrong, so `doctor.py` can say "re-save site.json" for a marker
  that is there but respelled rather than silently not starting, and "this is a site site-studio does
  not manage yet; type /site-studio:adopt" for a site.json with no marker at all (dev #855). A re-save
  cannot help a file site-studio never made.

SCHEMA VERSIONING. The key is `site.json`'s own `schema`, never the plugin release. Schema 1 is the
only schema in 0.1.0. 0.2.0 adds schema 2 (design-site-adoption section 3, dev #857) WITHOUT a
migration, by one rule: the writer writes the LOWEST schema that holds the site, and "the site" is
`site.json` AND the tree the builder reads.

* Schema 1 is read exactly as 0.1.0 reads it. `siteKind` defaults to `portfolio`, there are no
  labels, and `featuredFrom` is `"home"`.
* Schema 2 accepts everything schema 1 does, plus exactly three keys: `siteKind` (top level),
  `featuredFrom` (top level) and `labels` (inside a portfolio-settings object). A schema-1 file
  carrying any of them is refused (`'siteKind' needs "schema": 2`), so a hand edit cannot quietly
  make a file that 0.1.0 then misreads. Schema 3 or above gets the "update site-studio" refusal.
* `required_schema(cfg, files)` is the one place that says which schema a site needs; it returns 2
  when any of five conditions holds (a non-portfolio kind, a non-empty labels map, `featuredFrom`
  `"flags"`, a section or `{{featured}}` in a layout, page or Markdown body, or a hand-made home
  page with no `content/home.md`). `canonical_text` / `write` take the files the caller holds and
  emit that schema and only that schema's keys, so a portfolio with no 0.2.0 feature stays
  schema 1 and stays readable by a 0.1.0 install. `check_tree_schema` is the build's refusal of a
  schema-1 file over a tree that needs 2. git's `repositoryformatversion` is the model.

SCHEMA 3 (site-fidelity, 0.3.0; design-site-fidelity section 3). No migration, by the same rule, and
the owner invariant behind it: site-studio never changes how a published site looks or works. A
schema-3 reason is one of two kinds. K: a key or form 0.2.0 REFUSED, so no tree 0.2.0 accepted can hold
one (the resume with no PDF and no `paper`; a `page.md` carrying `order`, `tagline`, `sort`, `menuLinks`
or `view`; a `{{home:` token in `site/src`; `content/home/index.md` or `content/about/index.md`; a
`contact` key on the resume page). A K reason below schema 3 is refused by `check_tree_schema`. I: a new
interpretation of text 0.2.0 ACCEPTED (a block fence line, a titled image line, a `.wNNN` size copy).
An I reason below schema 3 is NEVER refused: the build keeps 0.2.0's reading of it byte for byte, so a tree
0.2.0 accepted builds identically under 0.3.0. `build.py raise-schema` is the one way a site gets to
schema 3, and it lists every output difference first. `required_schema(cfg, files, interpretations=...)`
takes the I-1 and I-2 reasons from its caller (`content.interpretation_reasons`), because `siteconfig`
cannot import `content`; it refuses to run with `files` and no `interpretations`, so no caller can forget
the scan.
"""
import json
import os
import re
import sys
import tempfile
from collections import namedtuple

SCHEMA_MAX = 3
ENGINE_MARKER = "site-studio"
CANONICAL_MARKER_LINE = '  "engine": "site-studio",'

KEY_ORDER = (
    "schema", "engine", "name", "siteTitle", "publicRepo", "previewUrl", "domain", "cutover",
    "publicEmails", "privateTerms", "work", "redirects", "resume", "budgets",
)
# Schema 2 adds these two top-level keys (and `labels` inside WORK_KEYS). KEY_ORDER stays the
# schema-1 key set; CANON_ORDER is the written order with the schema-2 keys placed in it.
V2_TOP_KEYS = ("siteKind", "featuredFrom")
CANON_ORDER = (
    "schema", "engine", "name", "siteTitle", "siteKind", "publicRepo", "previewUrl", "domain",
    "cutover", "publicEmails", "privateTerms", "work", "featuredFrom", "redirects", "resume",
    "budgets",
)
SITE_KINDS = ("portfolio", "hub", "custom")
FEATURED_FROM = ("home", "flags")
WORK_KEYS = ("label", "description", "required", "meta", "cardMeta", "groupBy", "groups", "labels")
LABEL_PARTS = ("meta", "groups")
RESUME_KEYS = ("path", "pdf", "paper")
PAPERS = ("Letter", "A4")

# The performance limits of design 4.3 (B's numbers), overridable in `budgets`.
BUDGET_DEFAULTS = {
    "sizeCopyOverKB": 250,    # an image over this needs size copies
    "firstViewMaxMB": 1.5,    # first-view images per page, at 2x
    "pageImagesMaxMB": 5,     # all images per page, at 2x
    "treeMaxMB": 200,         # whole published tree (the Pages limit is 1 GB)
}

DEFAULT_RESUME_PATH = "content/resume/resume.md"
DEFAULT_RESUME_PDF = "content/resume/resume.pdf"

_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$")
_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


class Problem(namedtuple("Problem", "path found expected fix mechanical lineno")):
    """One thing wrong in a config or a content tree (design-site-adoption section 7.1).

    `path` where it is ('work.meta[0]', 'content/news/'), `found` what is there, `expected` what
    would be right, `fix` the one-line remedy, `mechanical` True when adopt's `apply` makes the
    fix itself (it prints `apply fixes this`) and False when only the person can decide (`you
    decide`), `lineno` the 1-based line in `path` when the check knows it (else None; design-site-
    fidelity section 4.1: the field is `lineno`, never `line`, which would shadow the method below).
    `message` is the one-line text `parse_data` raises with; it is not a tuple field, so two Problems
    that differ only in wording compare equal."""
    message = ""

    def line(self):
        message = self.message
        if self.lineno and self.path:
            at = "%s:%d: " % (self.path, self.lineno)
            if message.startswith(self.path + ": "):
                message = at + message[len(self.path) + 2:]         # `path: text` becomes `path:line: text`
            elif not message.startswith(at):
                message = at + message
        return "%s -- fix: %s (%s)" % (message, self.fix, "apply fixes this" if self.mechanical else "you decide")


Problem.__new__.__defaults__ = (None,)


def make_problem(message, path=None, found=None, expected=None, fix=None, mechanical=False, lineno=None):
    p = Problem(path, found, expected,
                fix or ("edit %s in site/site.json" % ("'%s'" % path if path else "it")), bool(mechanical),
                lineno)
    p.message = message
    return p


class SiteConfigError(ValueError):
    """site.json cannot be read, or a value in it is wrong. The message is one line. `problem` is the
    structured form of ONE refusal (None when the error was not raised by a check); `problems` is the
    whole list when `parse_data` raised for several at once."""

    def __init__(self, message, path=None, found=None, expected=None, fix=None, mechanical=False,
                 lineno=None):
        ValueError.__init__(self, message)
        self.problem = make_problem(message, path, found, expected, fix, mechanical, lineno)
        self.problems = [self.problem]

    @classmethod
    def of(cls, problems):
        """One error that carries every problem, its message the one-line join of theirs."""
        problems = list(problems)
        e = cls("; ".join(p.message for p in problems))
        e.problem = problems[0] if problems else e.problem
        e.problems = problems
        return e


def newer_schema_message(n):
    return ("site.json schema %s is newer than this plugin understands (it reads up to %d); "
            "update site-studio" % (n, SCHEMA_MAX))


# ---------------------------------------------------------------- small typed readers
# Each reader RAISES one SiteConfigError carrying its own Problem. `_Collector.run` turns that into
# an entry in the list `problems()` returns and carries on, so a config with six faults reports six
# (design-site-adoption section 7.1). `parse_data` is `problems()` plus a raise: one code path.

def _kind(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "number"
    if isinstance(v, float):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "list"
    if isinstance(v, dict):
        return "object"
    return type(v).__name__


class _Collector(object):
    """Runs one check at a time and keeps what it refused instead of stopping at the first."""

    def __init__(self):
        self.problems = []

    def add(self, message, path=None, found=None, expected=None, fix=None, mechanical=False):
        self.problems.append(make_problem(message, path, found, expected, fix, mechanical))

    def run(self, fn, *args, **kw):
        """(ok, value). A SiteConfigError from `fn` is recorded and ok is False."""
        try:
            return True, fn(*args, **kw)
        except SiteConfigError as e:
            self.problems.append(e.problem)
            return False, None


# The two site.json values that may be a URL a person pasted with a credential in it
# (a clone URL with userinfo in front of the host); a problem line must never echo one (dev #851-#857 follow-up).
_URL_FIELDS = ("publicRepo", "previewUrl")


def _shown(value):
    """`value` with any userinfo removed, for a problem line or an error: `github_url.redact`, applied
    to the text between its surrounding whitespace (redact anchors at the start). Fails closed: if the
    redactor cannot be imported, nothing of the value is shown."""
    try:
        import github_url
        core = value.strip()
        return value.replace(core, github_url.redact(core), 1) if core else value
    except Exception:
        return "<not shown>"


def _bad(where, want, v):
    raise SiteConfigError("site.json: '%s' must be %s, got %s" % (where, want, _kind(v)),
                          path=where, found=_kind(v), expected=want,
                          fix="set '%s' to %s" % (where, want))


def _str(v, where, optional=False):
    if v is None and optional:
        return None
    if not isinstance(v, str):
        _bad(where, "a string", v)
    if not v.strip():
        raise SiteConfigError("site.json: '%s' must not be empty" % where, path=where, found="empty",
                              expected="a non-empty string", fix="give '%s' a value, or remove it" % where)
    if v != v.strip():
        raise SiteConfigError("site.json: '%s' has leading or trailing whitespace" % where, path=where,
                              found=repr(_shown(v) if where in _URL_FIELDS else v),
                              expected="no surrounding whitespace",
                              fix="remove the spaces around the value of '%s'" % where)
    return v


def _text(v, where):
    """A free-text string that may be empty."""
    if not isinstance(v, str):
        _bad(where, "a string", v)
    return v


def _bool(v, where):
    if not isinstance(v, bool):
        _bad(where, "true or false", v)
    return v


def _str_list(v, where, collect=None):
    """A list of non-empty strings. With `collect`, every bad item is recorded and the good ones are
    returned; without it, the first bad item raises."""
    if not isinstance(v, list):
        _bad(where, "a list of strings", v)
    out = []
    for i, item in enumerate(v):
        if collect is None:
            out.append(_str(item, "%s[%d]" % (where, i)))
        else:
            ok, val = collect.run(_str, item, "%s[%d]" % (where, i))
            if ok:
                out.append(val)
    return out


def _number(v, where):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad(where, "a number", v)
    if v <= 0:
        raise SiteConfigError("site.json: '%s' must be greater than zero" % where, path=where,
                              found=v, expected="a number above zero", fix="set '%s' above zero" % where)
    return v


def _rel_path(v, where):
    v = _str(v, where)
    if v.startswith("/") or "\\" in v or ".." in v.split("/") or "//" in v or v.endswith("/"):
        raise SiteConfigError("site.json: '%s' must be a relative path inside the repo" % where,
                              path=where, found=v, expected="a relative path inside the repo",
                              fix="write '%s' as a path such as content/x, with no leading or trailing /"
                              % where)
    return v


# ---------------------------------------------------------------- sections

def _needs_schema_2(where):
    return SiteConfigError("site.json: '%s' needs \"schema\": 2" % where, path=where,
                           found="schema 1", expected="schema 2",
                           fix="set \"schema\": 2 in site/site.json (a save by site-studio does this)")


def _pair_key(item):
    """The key of a `[key, label]` pair or a `{"key": ..., "label": ...}` object, else None. These are
    the shapes an older hand-made site.json used for a display label (section 5); adopt converts them."""
    if (isinstance(item, list) and len(item) == 2 and all(isinstance(x, str) and x.strip() for x in item)):
        return item[0]
    if (isinstance(item, dict) and set(item) == {"key", "label"}
            and all(isinstance(x, str) and x.strip() for x in item.values())):
        return item["key"]
    return None


def pair_label(item):
    """(key, label) of a `[key, label]` pair or `{"key", "label"}` object, else None."""
    k = _pair_key(item)
    if k is None:
        return None
    return (k, item[1] if isinstance(item, list) else item["label"])


def _labels(raw, where, col):
    """The `labels` map of a portfolio-settings object: {meta: {key: label}, groups: {name: label}}.
    Both parts optional. Values are non-empty strings. Returns the fully-defaulted shape; every fault
    is recorded in `col`."""
    out = {"meta": {}, "groups": {}}
    if not isinstance(raw, dict):
        col.run(_bad, where, "an object", raw)
        return out
    for k in raw:
        if k not in LABEL_PARTS:
            col.add("site.json: unknown key '%s.%s'" % (where, k), "%s.%s" % (where, k), "unknown key",
                    "one of: " + ", ".join(LABEL_PARTS), "remove '%s.%s'" % (where, k))
    for part in LABEL_PARTS:
        if part not in raw:
            continue
        m = raw[part]
        if not isinstance(m, dict):
            col.run(_bad, "%s.%s" % (where, part), "an object", m)
            continue
        for key, label in m.items():
            if part == "meta" and not _KEY_RE.match(key):
                col.add("site.json: '%s.meta' labels '%s', which is not a plain key name" % (where, key),
                        "%s.meta" % where, key, "a plain key name", "label a key that appears in meta")
                continue
            if not key.strip():
                col.add("site.json: '%s.%s' has an empty key" % (where, part), "%s.%s" % (where, part),
                        "empty key", "a key name", "remove the empty key")
                continue
            ok, val = col.run(_str, label, "%s.%s['%s']" % (where, part, key))
            if ok:
                out[part][key] = val
    return out


def labels_nonempty(labels):
    return bool(labels) and any(labels.get(p) for p in LABEL_PARTS)


def _list_of_keys(raw, k, where, col):
    """`meta`, `cardMeta`, `groups` or `required`: a list of strings. A `[key, label]` pair (or the
    object form) is a problem adopt can fix, and its key is kept so later checks do not cascade."""
    v = raw[k]
    here = "%s.%s" % (where, k)
    if not isinstance(v, list):
        col.run(_bad, here, "a list of strings", v)
        return []
    out = []
    for i, item in enumerate(v):
        at = "%s[%d]" % (here, i)
        if k in ("meta", "cardMeta", "groups") and not isinstance(item, str):
            key = _pair_key(item)
            if key is not None:
                col.add("site.json: '%s' is a [key, label] pair; %s holds plain keys, and a display label "
                        "goes in %s.labels (adopt converts this)" % (at, k, where), at,
                        json.dumps(item), "a plain key", "move the label into %s.labels.%s"
                        % (where, "groups" if k == "groups" else "meta"), True)
                out.append(key)
                continue
        ok, val = col.run(_str, item, at)
        if ok:
            out.append(val)
    return out


def _portfolio_check(raw, where, schema, featured_from, col):
    out = {"label": "Work", "description": "", "required": ["title"], "meta": [], "cardMeta": [],
           "groupBy": None, "groups": [], "labels": {"meta": {}, "groups": {}}}
    if not isinstance(raw, dict):
        col.run(_bad, where, "an object", raw)
        return out
    for k in raw:
        if k not in WORK_KEYS:
            col.add("site.json: unknown key '%s.%s'" % (where, k), "%s.%s" % (where, k), "unknown key",
                    "one of: " + ", ".join(WORK_KEYS), "remove '%s.%s'" % (where, k))
    labels_raw = None
    if "labels" in raw:
        if schema < 2:
            col.problems.append(_needs_schema_2(where + ".labels").problem)
        else:
            labels_raw = raw["labels"]
    if "label" in raw:
        ok, val = col.run(_str, raw["label"], where + ".label")
        if ok:
            out["label"] = val
    if "description" in raw:
        ok, val = col.run(_text, raw["description"], where + ".description")
        if ok:
            out["description"] = val
    for k in ("required", "meta", "cardMeta", "groups"):
        if k in raw:
            out[k] = _list_of_keys(raw, k, where, col)
    if "groupBy" in raw:
        ok, val = col.run(_str, raw["groupBy"], where + ".groupBy", optional=True)
        if ok:
            out["groupBy"] = val
            if val is not None and not _KEY_RE.match(val):
                col.add("site.json: '%s.groupBy' must be a plain key name" % where, where + ".groupBy", val,
                        "a plain key name", "use a plain key name (letters, digits, underscore)")
    if bool(out["groups"]) != (out["groupBy"] is not None):
        col.add("site.json: '%s.groupBy' and '%s.groups' go together" % (where, where), where + ".groupBy",
                "one without the other", "both, or neither", "set groupBy and groups together, or remove both")
    for k in ("required", "meta", "cardMeta"):
        for item in out[k]:
            if not _KEY_RE.match(item):
                col.add("site.json: '%s.%s' holds '%s', which is not a plain key name" % (where, k, item),
                        "%s.%s" % (where, k), item, "a plain key name",
                        "use a plain key name (letters, digits, underscore)")
    if featured_from == "flags":
        for k in ("meta", "cardMeta"):
            if "featured" in out[k]:
                col.add("site.json: '%s.%s' lists 'featured', which is reserved while featuredFrom is flags"
                        % (where, k), "%s.%s" % (where, k), "featured", "no 'featured' in %s" % k,
                        "remove 'featured' from %s, or drop featuredFrom" % k)
    if labels_raw is not None:
        out["labels"] = _labels(labels_raw, where + ".labels", col)
        shown = set(out["meta"]) | set(out["cardMeta"])
        for key in out["labels"]["meta"]:
            if key not in shown:
                col.add("site.json: '%s.labels.meta' labels '%s', which is not in meta or cardMeta"
                        % (where, key), "%s.labels.meta" % where, key, "a key listed in meta or cardMeta",
                        "remove the label, or add '%s' to meta or cardMeta" % key)
        for key in out["labels"]["groups"]:
            if key not in out["groups"]:
                col.add("site.json: '%s.labels.groups' labels '%s', which is not in groups" % (where, key),
                        "%s.labels.groups" % where, key, "a name listed in groups",
                        "remove the label, or add '%s' to groups" % key)
    return out


def portfolio_problems(raw, where, schema=SCHEMA_MAX, featured_from="home"):
    """Every problem in a portfolio-settings object (site.json `work`, or a page.md's overrides), as
    (problems, settings). `settings` is fully defaulted and only meaningful when `problems` is empty."""
    col = _Collector()
    out = _portfolio_check(raw, where, schema, featured_from, col)
    return col.problems, out


def validate_portfolio_settings(raw, where, schema=SCHEMA_MAX, featured_from="home"):
    """The `work` object of site.json, and the front matter of a portfolio's page.md, share this
    shape. `where` prefixes error messages. `schema` is the declared schema of the site.json the
    settings belong to: `labels` is refused under schema 1. `featured_from` is the site's
    `featuredFrom`: under `flags` the name `featured` is reserved. Returns a fully-defaulted dict;
    raises ONE SiteConfigError carrying every problem."""
    probs, out = portfolio_problems(raw, where, schema, featured_from)
    if probs:
        raise SiteConfigError.of(probs)
    return out


def _resume_check(raw, col, schema=SCHEMA_MAX):
    if raw is None:
        return None
    if not isinstance(raw, dict):
        col.run(_bad, "resume", "an object", raw)
        return None
    n = len(col.problems)
    for k in raw:
        if k not in RESUME_KEYS:
            col.add("site.json: unknown key 'resume.%s'" % k, "resume.%s" % k, "unknown key",
                    "one of: " + ", ".join(RESUME_KEYS), "remove 'resume.%s'" % k)
    paper = None
    # K-1 (schema 3): a resume with no PDF has no paper size to ask about. Below schema 3 the answer is
    # always required, exactly as 0.2.0 reads it.
    no_pdf = "pdf" in raw and raw["pdf"] is None
    if "paper" not in raw and no_pdf and schema >= 3:
        pass
    elif "paper" not in raw:
        col.add("site.json: 'resume.paper' is required (\"Letter\" or \"A4\"); no default is guessed from a "
                "locale", "resume.paper", "missing", "\"Letter\" or \"A4\"",
                "add \"paper\": \"Letter\" or \"A4\" to resume (or, with no resume PDF, set \"pdf\": null "
                "and \"schema\": 3)")
    elif raw["paper"] not in PAPERS:
        col.add("site.json: 'resume.paper' must be \"Letter\" or \"A4\"", "resume.paper", raw["paper"],
                "\"Letter\" or \"A4\"", "set resume.paper to \"Letter\" or \"A4\"")
    else:
        paper = raw["paper"]
    ok, path = col.run(_rel_path, raw.get("path", DEFAULT_RESUME_PATH), "resume.path")
    if ok and (not path.startswith("content/") or not path.endswith(".md")):
        col.add("site.json: 'resume.path' must be a .md file under content/", "resume.path", path,
                "a .md file under content/", "point resume.path at the resume's .md file under content/")
    pdf = raw.get("pdf", DEFAULT_RESUME_PDF)
    if pdf is not None:
        ok2, pdf = col.run(_rel_path, pdf, "resume.pdf")
        if ok2 and (not pdf.startswith("content/") or not pdf.endswith(".pdf")):
            col.add("site.json: 'resume.pdf' must be a .pdf file under content/", "resume.pdf", pdf,
                    "a .pdf file under content/", "point resume.pdf at the resume's .pdf under content/")
    if len(col.problems) > n:
        return None
    return {"path": path, "pdf": pdf, "paper": paper}


def _redirect_entry(old, new):
    _rel_path(old, "redirects key '%s'" % old)
    new = _str(new, "redirects['%s']" % old)
    if not re.match(r"^https?://", new):
        _rel_path(new, "redirects['%s']" % old)
    if new.strip("/") == old.strip("/"):
        raise SiteConfigError("site.json: redirect '%s' points at itself" % old, path="redirects['%s']" % old,
                              found=new, expected="another page", fix="point the redirect somewhere else")
    return new


def _redirects_check(raw, col):
    if not isinstance(raw, dict):
        col.run(_bad, "redirects", "an object", raw)
        return {}
    out = {}
    for old, new in raw.items():
        ok, val = col.run(_redirect_entry, old, new)
        if ok:
            out[old] = val
    return out


def _budgets_check(raw, col):
    if not isinstance(raw, dict):
        col.run(_bad, "budgets", "an object", raw)
        return {}
    out = {}
    for k, v in raw.items():
        if k not in BUDGET_DEFAULTS:
            col.add("site.json: unknown key 'budgets.%s'" % k, "budgets.%s" % k, "unknown key",
                    "one of: " + ", ".join(sorted(BUDGET_DEFAULTS)), "remove 'budgets.%s'" % k)
            continue
        ok, val = col.run(_number, v, "budgets." + k)
        if ok:
            out[k] = val
    return out


class SiteConfig(object):
    """A validated, fully-defaulted site.json. Attributes mirror the keys."""

    def __init__(self, d):
        self.schema = d["schema"]
        self.engine = d["engine"]
        self.name = d["name"]
        self.siteTitle = d["siteTitle"]
        self.publicRepo = d["publicRepo"]
        self.previewUrl = d["previewUrl"]
        self.domain = d["domain"]
        self.cutover = d["cutover"]
        self.publicEmails = d["publicEmails"]
        self.privateTerms = d["privateTerms"]
        self.work = d["work"]
        self.redirects = d["redirects"]
        self.resume = d["resume"]
        self.budgets = d["budgets"]
        self.siteKind = d.get("siteKind", "portfolio")
        self.featuredFrom = d.get("featuredFrom", "home")

    def to_dict(self):
        """The config as a plain dict that `parse_data` reads back. A schema-2 key appears only when
        it is not its default, and `work.labels` only when non-empty, so a schema-1 config's
        dict is a schema-1 dict."""
        d = dict((k, getattr(self, k)) for k in KEY_ORDER)
        work = dict(self.work)
        if not labels_nonempty(work.get("labels")):
            work.pop("labels", None)
        d["work"] = work
        if self.siteKind != "portfolio":
            d["siteKind"] = self.siteKind
        if self.featuredFrom != "home":
            d["featuredFrom"] = self.featuredFrom
        return d

    def effective_budgets(self):
        merged = dict(BUDGET_DEFAULTS)
        merged.update(self.budgets)
        return merged

    def site_url(self):
        """The absolute address share tags use: the domain after cutover, the preview before.
        None when neither can be known."""
        if self.cutover:
            return "https://" + self.domain
        return self.previewUrl

    def __eq__(self, other):
        return isinstance(other, SiteConfig) and self.to_dict() == other.to_dict()

    def __ne__(self, other):
        return not self == other


def _no_dupes(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise SiteConfigError("site.json: duplicate key '%s'" % k)
        out[k] = v
    return out


def _clone_slug(value):
    """'owner/name' when `value` is a github.com clone URL (https, scp or ssh form), else None."""
    try:
        import github_url
        return github_url.slug(value)
    except Exception:
        return None


def _check(data):
    """Every problem in an already-decoded site.json, and the validated dict when there are none.
    The one code path under both `problems` and `parse_data`: they cannot drift, by construction."""
    col = _Collector()
    if not isinstance(data, dict):
        col.add("site.json: the top level must be an object", "(top level)", _kind(data), "an object",
                "make site/site.json one JSON object")
        return col.problems, None
    if "schema" not in data:
        col.add("site.json: 'schema' is missing", "schema", "missing", "1, 2 or 3",
                "add \"schema\": 1 (or 2 or 3 when the site uses a feature that needs it)")
        return col.problems, None
    schema = data["schema"]
    if isinstance(schema, bool) or not isinstance(schema, int):
        col.run(_bad, "schema", "a whole number", schema)
        return col.problems, None
    if schema > SCHEMA_MAX:
        # Distinct refusal, checked before anything else: never an unknown-key error.
        col.add(newer_schema_message(schema), "schema", schema, "at most %d" % SCHEMA_MAX,
                "update site-studio")
        return col.problems, None
    if schema < 1:
        col.add("site.json: 'schema' must be 1 or more", "schema", schema, "1, 2 or 3", "set \"schema\" to 1, 2 or 3")
        return col.problems, None
    for k in data:
        if k not in KEY_ORDER and k not in V2_TOP_KEYS:
            col.add("site.json: unknown key '%s'" % k, k, "unknown key", "one of: " + ", ".join(CANON_ORDER),
                    "remove '%s'" % k)
        elif k in V2_TOP_KEYS and schema < 2:
            col.problems.append(_needs_schema_2(k).problem)
    for k in ("engine", "name", "siteTitle"):
        if k not in data:
            col.add("site.json: '%s' is missing" % k, k, "missing", "a value", "add '%s' to site/site.json" % k)
    if "engine" in data and data["engine"] != ENGINE_MARKER:
        col.add("site.json: 'engine' must be \"%s\"" % ENGINE_MARKER, "engine", data["engine"],
                "\"%s\"" % ENGINE_MARKER, "set \"engine\" to \"%s\"" % ENGINE_MARKER)
    d = {"schema": schema, "engine": ENGINE_MARKER}
    for k in ("name", "siteTitle"):
        if k in data:
            ok, v = col.run(_str, data[k], k)
            d[k] = v
    ok, d["publicRepo"] = col.run(_str, data.get("publicRepo"), "publicRepo", optional=True)
    if ok and d["publicRepo"] is not None and not _REPO_RE.match(d["publicRepo"]):
        slug = _clone_slug(d["publicRepo"])
        col.add("site.json: 'publicRepo' must look like owner/name", "publicRepo", _shown(d["publicRepo"]),
                "owner/name", ("write it as %s" % slug) if slug else "write it as owner/name",
                slug is not None)
    ok, d["previewUrl"] = col.run(_str, data.get("previewUrl"), "previewUrl", optional=True)
    if ok and d["previewUrl"] is not None:
        u = d["previewUrl"]
        if not u.startswith("https://") or u.endswith("/"):
            col.add("site.json: 'previewUrl' must start with https:// and have no trailing slash",
                    "previewUrl", _shown(u), "https://... with no trailing slash",
                    ("drop the trailing slash: %s" % _shown(u.rstrip("/"))) if u.startswith("https://")
                    else "use an https:// address with no trailing slash",
                    u.startswith("https://") and u.endswith("/"))
    dom_ok, d["domain"] = col.run(_str, data.get("domain"), "domain", optional=True)
    if dom_ok and d["domain"] is not None and not _DOMAIN_RE.match(d["domain"]):
        col.add("site.json: 'domain' must be a bare lower-case host name", "domain", d["domain"],
                "a bare lower-case host name", "write the domain as example.com, with no https:// and no path")
        dom_ok = False
    ok, d["cutover"] = col.run(_bool, data.get("cutover", False), "cutover")
    if ok and d["cutover"] and dom_ok and d["domain"] is None:
        col.add("site.json: 'cutover' is true but 'domain' is not set", "cutover", True, "a domain",
                "set 'domain', or set 'cutover' to false")
    ok, d["publicEmails"] = col.run(_str_list, data.get("publicEmails", []), "publicEmails", collect=col)
    if ok:
        for e in d["publicEmails"]:
            if "@" not in e:
                col.add("site.json: 'publicEmails' holds '%s', which is not an address" % e, "publicEmails", e,
                        "an email address", "remove it, or write the address in full")
    ok, d["privateTerms"] = col.run(_str_list, data.get("privateTerms", []), "privateTerms", collect=col)
    d["siteKind"] = data.get("siteKind", "portfolio")
    if d["siteKind"] not in SITE_KINDS:
        col.add("site.json: 'siteKind' must be one of %s, got %s"
                % (", ".join(SITE_KINDS), json.dumps(d["siteKind"])), "siteKind", d["siteKind"],
                "one of " + ", ".join(SITE_KINDS), "choose portfolio, hub or custom")
    d["featuredFrom"] = data.get("featuredFrom", "home")
    if d["featuredFrom"] not in FEATURED_FROM:
        col.add("site.json: 'featuredFrom' must be one of %s, got %s"
                % (", ".join(FEATURED_FROM), json.dumps(d["featuredFrom"])), "featuredFrom", d["featuredFrom"],
                "one of " + ", ".join(FEATURED_FROM), "choose home or flags")
    featured_from = d["featuredFrom"] if d["featuredFrom"] in FEATURED_FROM else "home"
    d["work"] = _portfolio_check(data.get("work", {}), "work", schema, featured_from, col)
    d["redirects"] = _redirects_check(data.get("redirects", {}), col)
    d["resume"] = _resume_check(data.get("resume"), col, schema)
    d["budgets"] = _budgets_check(data.get("budgets", {}), col)
    if col.problems:
        return col.problems, None
    return [], d


def problems(data):
    """Every problem in an already-decoded site.json, each a `Problem` (path, found, expected, fix,
    mechanical), in the order the checks run. Empty means `parse_data` accepts it. One check
    that cannot continue (the top level is not an object, `schema` unreadable or newer) is the only
    problem reported; otherwise nothing stops at the first (design-site-adoption section 7.1)."""
    return _check(data)[0]


def parse_data(data):
    """Validate an already-decoded object. Same rules as parse_text. Raises ONE SiteConfigError that
    carries every problem (`.problems`), its message their one-line join."""
    probs, d = _check(data)
    if probs:
        raise SiteConfigError.of(probs)
    return SiteConfig(d)


def decode(text):
    """The decoded value of a site.json text: JSON, with a duplicate key refused. Raises one
    `SiteConfigError` for text that is not JSON. `parse_text` is `decode` plus `parse_data`; `build.accept`
    calls `decode`, `problems` and `parse_data` itself so it can report every problem."""
    try:
        return json.loads(text, object_pairs_hook=_no_dupes)
    except SiteConfigError:
        raise
    except ValueError as e:
        raise SiteConfigError("site.json is not valid JSON: %s" % e)


def parse_text(text):
    return parse_data(decode(text))


def load(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError as e:
        raise SiteConfigError("site.json cannot be read: %s" % e)
    except UnicodeDecodeError:
        raise SiteConfigError("site.json is not UTF-8")
    return parse_text(text)


# ---------------------------------------------------------------- which schema a site needs

_SECTION_RE = re.compile(r"\{\{\s*#page:")
_FEATURED_RE = re.compile(r"\{\{\s*featured\s*\}\}")
_LABELS_FM_RE = re.compile(r"(?m)^labels:[ \t]*(\S.*)?$")

# What a 0.1.0 install would do with each tree feature: the clause the refusal names.
_EFFECT_SECTION = "site-studio 0.1.0 would publish it as text"
_EFFECT_FEATURED = "site-studio 0.1.0 would refuse it as an unknown token"
_EFFECT_HOME = "site-studio 0.1.0 would refuse the build as two pages writing index.html"


def _text_of(v):
    return v.decode("utf-8", "replace") if isinstance(v, bytes) else v


def _expanded_file(path):
    """The files the builder token-expands: layouts, `site/src` HTML pages, Markdown bodies."""
    low = path.lower()
    if path.startswith("site/templates/"):
        return True
    if path.startswith("site/src/") and low.endswith((".html", ".htm")):
        return True
    return path.startswith("content/") and low.endswith(".md")


def _page_md_labels(path, text):
    """True when a content/<folder>/page.md front matter carries a non-empty `labels` entry."""
    if not text.startswith("---\n"):
        return False
    lines = text.split("\n")
    end = None
    for i in range(1, len(lines)):
        if lines[i].rstrip() == "---":
            end = i
            break
    if end is None:
        return False
    block = "\n".join(lines[1:end])
    m = _LABELS_FM_RE.search(block)
    if not m:
        return False
    if m.group(1):
        return m.group(1).strip() not in ("{}", "[]", "''", '""')
    # `labels:` alone: non-empty when an indented line follows it
    after = block[m.end():].lstrip("\n").split("\n")
    return bool(after) and after[0][:1] in (" ", "\t") and bool(after[0].strip())


def schema_2_reasons(cfg, files=None):
    """Every reason this site needs schema 2, as [(where, feature, effect on 0.1.0)]. `files` is the
    site's tree as {repo path: bytes or str} (None: only `site.json` is known). Empty when schema 1
    holds the site. The five conditions of design-site-adoption section 3."""
    out = []
    if cfg.siteKind != "portfolio":
        out.append(("site/site.json", "sets siteKind %s" % cfg.siteKind,
                    "site-studio 0.1.0 would refuse the unknown key"))
    if labels_nonempty(cfg.work.get("labels")):
        out.append(("site/site.json", "sets display labels", "site-studio 0.1.0 would refuse the unknown key"))
    if cfg.featuredFrom != "home":
        out.append(("site/site.json", "sets featuredFrom %s" % cfg.featuredFrom,
                    "site-studio 0.1.0 would refuse the unknown key"))
    if files:
        for path in sorted(files):
            text = None
            if path.startswith("content/") and path.endswith("/page.md") and path.count("/") == 2:
                text = _text_of(files[path])
                if _page_md_labels(path, text):
                    out.append((path, "sets display labels", "site-studio 0.1.0 would refuse the unknown key"))
            if not _expanded_file(path):
                continue
            text = _text_of(files[path]) if text is None else text
            for rx, name, effect in ((_SECTION_RE, "uses {{#page:...}}", _EFFECT_SECTION),
                                     (_FEATURED_RE, "uses {{featured}}", _EFFECT_FEATURED)):
                if rx.search(text):
                    out.append((path, name, effect))
        if (cfg.siteKind == "portfolio" and "site/src/index.html" in files
                and "content/home.md" not in files):
            out.append(("site/src/index.html", "is the home page, with no content/home.md",
                        _EFFECT_HOME))
    return out


# ---- schema 3 (site-fidelity, design section 3): K reasons (keys 0.2.0 refused) and I reasons
# (interpretations of text 0.2.0 accepted). See the module docstring.

V3_PAGE_KEYS = ("order", "tagline", "sort", "menuLinks", "view")
# What each key takes, and what a portfolio is without it (0.2.0's behaviour; design-site-fidelity section 6.2).
PAGE_SORTS = ("date", "order")
PAGE_MENU_LINKS = ("index", "single-piece")
PAGE_VIEWS = ("grid", "page")
V3_PAGE_DEFAULTS = {"order": None, "tagline": "", "sort": "date", "menuLinks": "index", "view": "grid"}
# A piece key the build already reads or shows, so a `meta`/`cardMeta` list that names one is refused at
# schema 3 (the build shows it already, and a second copy would print it twice). `featured` is reserved
# separately, only under `featuredFrom: flags`.
BUILTIN_PIECE_KEYS = ("shortTitle", "teaser", "coverPosition", "cover", "order", "title", "date", "draft")


def page_settings_problems(raw, where):
    """Every problem in the schema-3 portfolio keys of a `page.md` (`order`, `tagline`, `sort`, `menuLinks`,
    `view`), as (problems, settings). `raw` holds only those keys; `where` is the page's path. `settings` is
    fully defaulted. The value rules are the design's section 6.2 table, and every refusal names its fix."""
    out = dict(V3_PAGE_DEFAULTS)
    probs = []

    def bad(key, found, expected, fix):
        probs.append(make_problem("%s: '%s' %s" % (where, key, expected), where, found, expected, fix))
    for key, val in raw.items():
        if key == "order":
            if isinstance(val, bool) or not isinstance(val, int):
                bad(key, repr(val), "must be a whole number, such as 2", "write order as a whole number, such as order: 2")
            else:
                out[key] = val
        elif key == "tagline":
            if not isinstance(val, str) or not val.strip() or "\n" in val:
                bad(key, repr(val), "must be one line of text", "write tagline as one line of text")
            else:
                out[key] = val.strip()
        else:
            allowed = {"sort": PAGE_SORTS, "menuLinks": PAGE_MENU_LINKS, "view": PAGE_VIEWS}.get(key)
            if allowed is None:
                continue
            if val not in allowed:
                names = " or ".join('"%s"' % a for a in allowed)
                bad(key, repr(val), "must be %s" % names, "set %s to %s" % (key, names))
            else:
                out[key] = val
    return probs, out
_HOME_TOKEN_RE = re.compile(r"\{\{\s*home\s*:")
_FM_KEY_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_]*):(?:\s|$)")
_SIZE_COPY_RE = re.compile(r"^(?P<stem>.+)\.w(?P<w>\d+)(?P<ext>\.\w+)$")
_EFFECT_K = "site-studio 0.2.0 would refuse it"
_EFFECT_I_TEXT = "site-studio 0.2.0 publishes it as text"
_EFFECT_I_FILE = "site-studio 0.2.0 publishes it as a plain media file"

Reason = namedtuple("Reason", "where what effect lineno kind")


def front_matter_keys(text):
    """[(key, lineno)] for the top-level keys of a file's front matter (an unreadable block yields what
    was read). Lines are numbered from 1 over the whole file. No front matter yields []."""
    text = _text_of(text).replace("\r\n", "\n")
    if not text.startswith("---\n"):
        return []
    out = []
    for i, line in enumerate(text.split("\n")[1:], 2):
        if line.rstrip() == "---":
            break
        m = _FM_KEY_RE.match(line)
        if m:
            out.append((m.group(1), i))
    return out


def schema_3_reasons(cfg, files=None, interpretations=None, kinds=("K", "I")):
    """Every reason this site needs schema 3, as [Reason(where, what, effect, lineno, kind)]. `kind` is
    "K" (a key or form 0.2.0 refused) or "I" (a new reading of text 0.2.0 accepted). `files` is the
    tree as {repo path: bytes or str}; `interpretations` is `content.interpretation_reasons(files)`,
    [(path, lineno, form)] (I-1 and I-2), which this module cannot compute (it cannot import `content`).
    `kinds` narrows the answer: `check_tree_schema` asks for K only, because an I reason is never
    refused below schema 3."""
    out = []
    if "K" in kinds:
        if (cfg.resume is not None and cfg.resume.get("pdf") is None and cfg.resume.get("paper") is None):
            out.append(Reason("site/site.json", "has a resume with no PDF and no paper size", _EFFECT_K,
                              None, "K"))
        for path in sorted(files or ()):
            low = path.lower()
            parts = path.split("/")
            if path.startswith("content/") and path.endswith("/page.md") and len(parts) == 3:
                for key, n in front_matter_keys(files[path]):
                    if key in V3_PAGE_KEYS:
                        out.append(Reason(path, "sets %s" % key, _EFFECT_K, n, "K"))
            if path.startswith("site/src/") and low.endswith((".html", ".htm")):
                m = _HOME_TOKEN_RE.search(_text_of(files[path]))
                if m:
                    n = _text_of(files[path])[:m.start()].count("\n") + 1
                    out.append(Reason(path, "uses a {{home:...}} token", _EFFECT_K, n, "K"))
            if path in ("content/home/index.md", "content/about/index.md"):
                out.append(Reason(path, "is a home or about page in folder form", _EFFECT_K, None, "K"))
        if cfg.resume is not None and files and cfg.resume.get("path") in files:
            for key, n in front_matter_keys(files[cfg.resume["path"]]):
                if key == "contact":
                    out.append(Reason(cfg.resume["path"], "sets contact on the resume page", _EFFECT_K, n, "K"))
    if "I" in kinds:
        for path, n, form in (interpretations or ()):
            out.append(Reason(path, "holds %s" % form, _EFFECT_I_TEXT, n, "I"))
        for path in sorted(files or ()):
            if not path.startswith("content/") or "/media/" not in path:
                continue
            folder, _, base = path.rpartition("/")
            m = _SIZE_COPY_RE.match(base)
            if m and (folder + "/" + m.group("stem") + m.group("ext")) in files:
                out.append(Reason(path, "is a .w%s size copy of %s%s" % (m.group("w"), m.group("stem"),
                                                                        m.group("ext")),
                                  _EFFECT_I_FILE, None, "I"))
    return out


def required_schema(cfg, files=None, interpretations=None):
    """The lowest schema that holds the site: 3 when any schema-3 reason holds (`schema_3_reasons`), 2
    when any of five conditions holds (`schema_2_reasons`), else 1. `files` is the tree the caller
    holds (adopt: the converted tree); None means no tree feature is known. When `files` is given,
    `interpretations` MUST be too (`content.interpretation_reasons(files)`; [] when there are none): a
    caller that held a tree and forgot the scan would write a schema too low (design section 3.3)."""
    if files is not None and interpretations is None:
        raise ValueError("required_schema(cfg, files) needs interpretations= (content.interpretation_reasons"
                         "(files)); pass [] only when you know the tree holds none")
    if schema_3_reasons(cfg, files, interpretations):
        return 3
    return 2 if schema_2_reasons(cfg, files) else 1


def tree_schema_problems(cfg, files):
    """Every Problem the declared schema of `site.json` has with the tree: the schema-2 reasons under a
    schema-1 file, then the K schema-3 reasons under a file below 3. An I reason is never a problem
    (design section 3.2). Each carries `path` and `lineno`; none is mechanical."""
    out = []
    if cfg.schema < 2:
        for where, what, effect in schema_2_reasons(cfg, files):
            out.append(make_problem("%s %s, which needs \"schema\": 2 in site/site.json (%s)"
                                    % (where, what, effect), where, "schema 1", "schema 2",
                                    "set \"schema\": 2 in site/site.json (a save by site-studio does this)"))
    if cfg.schema < 3:
        for r in schema_3_reasons(cfg, files, kinds=("K",)):
            at = "%s:%d:" % (r.where, r.lineno) if r.lineno else r.where
            out.append(make_problem("%s %s, which needs \"schema\": 3 in site/site.json (run `build.py "
                                    "raise-schema`)" % (at, r.what), r.where, "schema %d" % cfg.schema,
                                    "schema 3", "run `python3 build.py raise-schema`, which lists what the "
                                    "page changes before it writes schema 3", False, r.lineno))
    return out


def check_tree_schema(cfg, files):
    """The build's refusal of a `site.json` whose schema is lower than the tree needs, naming the file
    and the feature (the hand-edit case: a person typed a section into a layout, or a `page.md` key
    from 0.3.0). Raises ONE error that carries every reason (`.problems`); with one reason its message
    is exactly that reason's."""
    probs = tree_schema_problems(cfg, files)
    if probs:
        raise SiteConfigError.of(probs)


def kind_conflicts(cfg):
    """What a `hub` or `custom` site's config may not carry (design section 4.1): the portfolio-only
    keys, when set. Empty for a portfolio."""
    if cfg.siteKind == "portfolio":
        return []
    out = []
    if cfg.work != validate_portfolio_settings({}, "work"):
        out.append("site.json 'work' is only for siteKind portfolio")
    if cfg.resume is not None:
        out.append("site.json 'resume' is only for siteKind portfolio")
    if cfg.featuredFrom != "home":
        out.append("site.json 'featuredFrom' is only for siteKind portfolio")
    return out


# ---------------------------------------------------------------- the one writer

def canonical_text(cfg, files=None, interpretations=None, at_least=None):
    """The one canonical form of a config: schema order, indent 2, one trailing LF. It writes the
    LOWEST schema that holds the site (`required_schema(cfg, files)`) and only that schema's keys:
    `siteKind` only when it is not `portfolio`, `labels` only when non-empty, `featuredFrom` only
    when `flags`. A `hub` or `custom` config leaves out `work` and `resume` when they hold
    nothing. `files` is the tree the caller holds (None: no tree feature is known); when it is given,
    so must `interpretations` be (see `required_schema`)."""
    if not isinstance(cfg, SiteConfig):
        cfg = parse_data(cfg)
    d = cfg.to_dict()
    d["schema"] = max(required_schema(cfg, files, interpretations), at_least or 1)
    d["work"] = dict((k, d["work"][k]) for k in WORK_KEYS if k in d["work"])
    if d["resume"] is not None:
        d["resume"] = dict((k, d["resume"][k]) for k in RESUME_KEYS
                           if not (k == "paper" and d["resume"][k] is None))
    if cfg.siteKind != "portfolio":
        if cfg.work == validate_portfolio_settings({}, "work"):
            del d["work"]
        if cfg.resume is None:
            del d["resume"]
    ordered = dict((k, d[k]) for k in CANON_ORDER if k in d)
    return json.dumps(ordered, indent=2, ensure_ascii=False) + "\n"


def write(path, cfg, files=None, interpretations=None, at_least=None):
    """Validate, then write `site.json` in canonical form, atomically. The only writer. `files` is
    the tree the caller holds, so the schema written is the one the whole site needs (with `files`,
    pass `interpretations` too: `content.interpretation_reasons(files)`)."""
    if not isinstance(cfg, SiteConfig):
        cfg = parse_data(cfg)
    text = canonical_text(cfg, files, interpretations, at_least)
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".site.json.", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------- the marker, for doctor

MARKER_OK, MARKER_INVALID, MARKER_ABSENT, MARKER_NONCANONICAL = "ok", "invalid", "absent", "non-canonical"


def marker_state(text):
    """Return (state, reason): WHICH way a site.json's marker is wrong, so the one caller that must give
    different advice for each (doctor.py) never has to read the reason's wording. `state` is one of
    MARKER_OK (the file parses with engine "site-studio" AND the marker is written in canonical form,
    the form the SessionStart prefilter greps for), MARKER_INVALID (not JSON), MARKER_ABSENT (no
    `"engine": "site-studio"` at all: a site.json site-studio did not make and does not manage yet, the
    one to ADOPT, dev #855) or MARKER_NONCANONICAL (the marker is there but respelled, the one a re-save
    fixes)."""
    try:
        data = json.loads(text, object_pairs_hook=_no_dupes)
    except (ValueError, SiteConfigError):
        return MARKER_INVALID, "site.json is not valid JSON"
    if not isinstance(data, dict) or data.get("engine") != ENGINE_MARKER:
        return MARKER_ABSENT, "site.json has no \"engine\": \"site-studio\" marker"
    if CANONICAL_MARKER_LINE not in text.split("\n"):
        return MARKER_NONCANONICAL, ("the engine marker is not in canonical form; re-save site.json with "
                                     "site-studio so the session-start check can find it")
    return MARKER_OK, "canonical"


def marker_status(text):
    """Return (ok, reason). ok is True only when `marker_state` is MARKER_OK. A legal-JSON respelling
    (`"engine" : "site-studio"`) parses fine and returns False, so doctor can ask for a re-save
    instead of the hook silently not starting; a site.json with no marker at all returns False too, and
    doctor tells that one to adopt (see `marker_state`)."""
    state, reason = marker_state(text)
    return state == MARKER_OK, reason


def is_canonical_marker(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return marker_status(fh.read())[0]
    except (OSError, UnicodeDecodeError):
        return False


def main(argv):
    if len(argv) == 3 and argv[1] == "check":
        try:
            cfg = load(argv[2])
        except SiteConfigError as e:
            print(str(e))
            return 1
        with open(argv[2], encoding="utf-8") as fh:
            ok, reason = marker_status(fh.read())
        print("site.json ok (schema %d); marker: %s" % (cfg.schema, reason))
        return 0 if ok else 1
    print("usage: siteconfig.py check <site.json>")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
