#!/usr/bin/env python3
"""siteconfig.py -- the strict parser, and the ONLY writer, of `site/site.json` (schema 1).

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
  `marker_status` / `is_canonical_marker` report whether a file's marker is in that form, so
  `doctor.py` can say "re-save site.json" rather than silently not starting.

SCHEMA VERSIONING. The key is `site.json`'s own `schema`, never the plugin release. Schema 1 is the
only schema in 0.1.0, so no migration ships.
"""
import json
import os
import re
import sys
import tempfile

SCHEMA_MAX = 1
ENGINE_MARKER = "site-studio"
CANONICAL_MARKER_LINE = '  "engine": "site-studio",'

KEY_ORDER = (
    "schema", "engine", "name", "siteTitle", "publicRepo", "previewUrl", "domain", "cutover",
    "publicEmails", "privateTerms", "work", "redirects", "resume", "budgets",
)
WORK_KEYS = ("label", "description", "required", "meta", "cardMeta", "groupBy", "groups")
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


class SiteConfigError(ValueError):
    """site.json cannot be read, or a value in it is wrong. The message is one line."""


def newer_schema_message(n):
    return ("site.json schema %s is newer than this plugin understands (it reads up to %d); "
            "update site-studio" % (n, SCHEMA_MAX))


# ---------------------------------------------------------------- small typed readers

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


def _bad(where, want, v):
    raise SiteConfigError("site.json: '%s' must be %s, got %s" % (where, want, _kind(v)))


def _str(v, where, optional=False):
    if v is None and optional:
        return None
    if not isinstance(v, str):
        _bad(where, "a string", v)
    if not v.strip():
        raise SiteConfigError("site.json: '%s' must not be empty" % where)
    if v != v.strip():
        raise SiteConfigError("site.json: '%s' has leading or trailing whitespace" % where)
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


def _str_list(v, where):
    if not isinstance(v, list):
        _bad(where, "a list of strings", v)
    out = []
    for i, item in enumerate(v):
        out.append(_str(item, "%s[%d]" % (where, i)))
    return out


def _number(v, where):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad(where, "a number", v)
    if v <= 0:
        raise SiteConfigError("site.json: '%s' must be greater than zero" % where)
    return v


def _object(v, where, allowed):
    if not isinstance(v, dict):
        _bad(where, "an object", v)
    for k in v:
        if k not in allowed:
            raise SiteConfigError("site.json: unknown key '%s.%s'" % (where, k))
    return v


def _rel_path(v, where):
    v = _str(v, where)
    if v.startswith("/") or "\\" in v or ".." in v.split("/") or "//" in v or v.endswith("/"):
        raise SiteConfigError("site.json: '%s' must be a relative path inside the repo" % where)
    return v


# ---------------------------------------------------------------- sections

def validate_portfolio_settings(raw, where):
    """The `work` object of site.json, and the front matter of a portfolio's page.md, share this
    shape. `where` prefixes error messages. Returns a fully-defaulted dict."""
    if not isinstance(raw, dict):
        _bad(where, "an object", raw)
    out = {"label": "Work", "description": "", "required": ["title"], "meta": [], "cardMeta": [],
           "groupBy": None, "groups": []}
    for k in raw:
        if k not in WORK_KEYS:
            raise SiteConfigError("site.json: unknown key '%s.%s'" % (where, k))
    if "label" in raw:
        out["label"] = _str(raw["label"], where + ".label")
    if "description" in raw:
        out["description"] = _text(raw["description"], where + ".description")
    for k in ("required", "meta", "cardMeta", "groups"):
        if k in raw:
            out[k] = _str_list(raw[k], where + "." + k)
    if "groupBy" in raw:
        out["groupBy"] = _str(raw["groupBy"], where + ".groupBy", optional=True)
        if out["groupBy"] is not None and not _KEY_RE.match(out["groupBy"]):
            raise SiteConfigError("site.json: '%s.groupBy' must be a plain key name" % where)
    if bool(out["groups"]) != (out["groupBy"] is not None):
        raise SiteConfigError("site.json: '%s.groupBy' and '%s.groups' go together" % (where, where))
    for k in ("required", "meta", "cardMeta"):
        for item in out[k]:
            if not _KEY_RE.match(item):
                raise SiteConfigError("site.json: '%s.%s' holds '%s', which is not a plain key name"
                                      % (where, k, item))
    return out


def _resume(raw):
    if raw is None:
        return None
    d = _object(raw, "resume", RESUME_KEYS)
    if "paper" not in d:
        raise SiteConfigError("site.json: 'resume.paper' is required (\"Letter\" or \"A4\"); "
                              "no default is guessed from a locale")
    paper = d["paper"]
    if paper not in PAPERS:
        raise SiteConfigError("site.json: 'resume.paper' must be \"Letter\" or \"A4\"")
    path = _rel_path(d.get("path", DEFAULT_RESUME_PATH), "resume.path")
    if not path.startswith("content/") or not path.endswith(".md"):
        raise SiteConfigError("site.json: 'resume.path' must be a .md file under content/")
    pdf = d.get("pdf", DEFAULT_RESUME_PDF)
    if pdf is not None:
        pdf = _rel_path(pdf, "resume.pdf")
        if not pdf.startswith("content/") or not pdf.endswith(".pdf"):
            raise SiteConfigError("site.json: 'resume.pdf' must be a .pdf file under content/")
    return {"path": path, "pdf": pdf, "paper": paper}


def _redirects(raw):
    if not isinstance(raw, dict):
        _bad("redirects", "an object", raw)
    out = {}
    for old, new in raw.items():
        _rel_path(old, "redirects key '%s'" % old)
        new = _str(new, "redirects['%s']" % old)
        if not re.match(r"^https?://", new):
            _rel_path(new, "redirects['%s']" % old)
        if new.strip("/") == old.strip("/"):
            raise SiteConfigError("site.json: redirect '%s' points at itself" % old)
        out[old] = new
    return out


def _budgets(raw):
    if not isinstance(raw, dict):
        _bad("budgets", "an object", raw)
    out = {}
    for k, v in raw.items():
        if k not in BUDGET_DEFAULTS:
            raise SiteConfigError("site.json: unknown key 'budgets.%s'" % k)
        out[k] = _number(v, "budgets." + k)
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

    def to_dict(self):
        return dict((k, getattr(self, k)) for k in KEY_ORDER)

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


def parse_data(data):
    """Validate an already-decoded object. Same rules as parse_text."""
    if not isinstance(data, dict):
        raise SiteConfigError("site.json: the top level must be an object")
    if "schema" not in data:
        raise SiteConfigError("site.json: 'schema' is missing")
    schema = data["schema"]
    if isinstance(schema, bool) or not isinstance(schema, int):
        _bad("schema", "a whole number", schema)
    if schema > SCHEMA_MAX:
        # Distinct refusal, checked before anything else: never an unknown-key error.
        raise SiteConfigError(newer_schema_message(schema))
    if schema < 1:
        raise SiteConfigError("site.json: 'schema' must be 1 or more")
    for k in data:
        if k not in KEY_ORDER:
            raise SiteConfigError("site.json: unknown key '%s'" % k)
    for k in ("engine", "name", "siteTitle"):
        if k not in data:
            raise SiteConfigError("site.json: '%s' is missing" % k)
    if data["engine"] != ENGINE_MARKER:
        raise SiteConfigError("site.json: 'engine' must be \"%s\"" % ENGINE_MARKER)
    d = {"schema": schema, "engine": ENGINE_MARKER,
         "name": _str(data["name"], "name"), "siteTitle": _str(data["siteTitle"], "siteTitle")}
    d["publicRepo"] = _str(data.get("publicRepo"), "publicRepo", optional=True)
    if d["publicRepo"] is not None and not _REPO_RE.match(d["publicRepo"]):
        raise SiteConfigError("site.json: 'publicRepo' must look like owner/name")
    d["previewUrl"] = _str(data.get("previewUrl"), "previewUrl", optional=True)
    if d["previewUrl"] is not None:
        if not d["previewUrl"].startswith("https://") or d["previewUrl"].endswith("/"):
            raise SiteConfigError("site.json: 'previewUrl' must start with https:// and have "
                                  "no trailing slash")
    d["domain"] = _str(data.get("domain"), "domain", optional=True)
    if d["domain"] is not None and not _DOMAIN_RE.match(d["domain"]):
        raise SiteConfigError("site.json: 'domain' must be a bare lower-case host name")
    d["cutover"] = _bool(data.get("cutover", False), "cutover")
    if d["cutover"] and d["domain"] is None:
        raise SiteConfigError("site.json: 'cutover' is true but 'domain' is not set")
    d["publicEmails"] = _str_list(data.get("publicEmails", []), "publicEmails")
    for e in d["publicEmails"]:
        if "@" not in e:
            raise SiteConfigError("site.json: 'publicEmails' holds '%s', which is not an address" % e)
    d["privateTerms"] = _str_list(data.get("privateTerms", []), "privateTerms")
    d["work"] = validate_portfolio_settings(data.get("work", {}), "work")
    d["redirects"] = _redirects(data.get("redirects", {}))
    d["resume"] = _resume(data.get("resume"))
    d["budgets"] = _budgets(data.get("budgets", {}))
    return SiteConfig(d)


def parse_text(text):
    try:
        data = json.loads(text, object_pairs_hook=_no_dupes)
    except SiteConfigError:
        raise
    except ValueError as e:
        raise SiteConfigError("site.json is not valid JSON: %s" % e)
    return parse_data(data)


def load(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError as e:
        raise SiteConfigError("site.json cannot be read: %s" % e)
    except UnicodeDecodeError:
        raise SiteConfigError("site.json is not UTF-8")
    return parse_text(text)


# ---------------------------------------------------------------- the one writer

def canonical_text(cfg):
    """The one canonical form of a config: every key, schema order, indent 2, one trailing LF."""
    if not isinstance(cfg, SiteConfig):
        cfg = parse_data(cfg)
    d = cfg.to_dict()
    work = dict((k, d["work"][k]) for k in WORK_KEYS)
    d["work"] = work
    if d["resume"] is not None:
        d["resume"] = dict((k, d["resume"][k]) for k in RESUME_KEYS)
    return json.dumps(d, indent=2, ensure_ascii=False) + "\n"


def write(path, cfg):
    """Validate, then write `site.json` in canonical form, atomically. The only writer."""
    if not isinstance(cfg, SiteConfig):
        cfg = parse_data(cfg)
    text = canonical_text(cfg)
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

def marker_status(text):
    """Return (ok, reason). ok is True only when the file parses with engine "site-studio" AND
    the marker is written in canonical form, the form the SessionStart prefilter greps for.
    A legal-JSON respelling (`"engine" : "site-studio"`) parses fine and returns False, so
    doctor can ask for a re-save instead of the hook silently not starting."""
    try:
        data = json.loads(text, object_pairs_hook=_no_dupes)
    except (ValueError, SiteConfigError):
        return False, "site.json is not valid JSON"
    if not isinstance(data, dict) or data.get("engine") != ENGINE_MARKER:
        return False, "site.json has no \"engine\": \"site-studio\" marker"
    if CANONICAL_MARKER_LINE not in text.split("\n"):
        return False, ("the engine marker is not in canonical form; re-save site.json with "
                       "site-studio so the session-start check can find it")
    return True, "canonical"


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
