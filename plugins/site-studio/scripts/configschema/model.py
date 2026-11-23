"""model: the validated `SiteConfig` and the strict reader of `site/site.json`: `problems`, `parse_data`,
`decode`, `parse_text` and `load`. `_check` is the one code path under both `problems` and `parse_data`, so
they cannot drift."""

import json
import urllib.parse
from configschema.configkeys import (
    BUDGET_DEFAULTS,
    CANON_ORDER,
    ENGINE_MARKER,
    FEATURED_FROM,
    KEY_ORDER,
    SCHEMA_MAX,
    SITE_KINDS,
    TITLE_SEPARATOR_DEFAULT,
    V2_TOP_KEYS,
    V4_TOP_KEYS,
    V6_TOP_KEYS,
    V7_TOP_KEYS,
    _DOMAIN_RE,
    _REPO_RE,
)
from configschema.diagnostics import SiteConfigError, _Collector, newer_schema_message
from configschema.sectioncheck import (
    _blocks_check,
    _budgets_check,
    _look,
    _look_local,
    _nav_check,
    _redirects_check,
    needs_schema_6,
    needs_schema_7,
    v6_top_check,
)
from configschema.valuecheck import (
    _bad,
    _bool,
    _kind,
    _needs_schema_2,
    _needs_schema_4,
    _shown,
    _str,
    _str_list,
)
from configschema.workcheck import _portfolio_check, _resume_check, labels_nonempty
import github_url


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
        self.nav = d.get("nav", {})
        self.look = d.get("look")
        self.lookLocal = d.get("lookLocal")
        self.blocks = d.get("blocks", {})
        self.featuredView = d.get("featuredView", "flat")
        self.titleSeparator = d.get("titleSeparator", TITLE_SEPARATOR_DEFAULT)
        self.mediaPaths = d.get("mediaPaths", {})
        self.sizeCopies = d.get("sizeCopies")
        self.carried = d.get("carried", [])

    def to_dict(self):
        """The config as a plain dict that `parse_data` reads back. A schema-2 key appears only when
        it is not its default, and `work.labels` only when non-empty, so a schema-1 config's
        dict is a schema-1 dict."""
        d = dict((k, getattr(self, k)) for k in KEY_ORDER)
        if isinstance(d.get("resume"), dict) and d["resume"].get("paper") is None:
            # A resume with no PDF has no paper (K-1, schema 3): the parsed form holds `paper: None`, which `parse_data`
            # refuses as a value, so it is left out here as `canonical.canonical_text` leaves it out (0.7.0: `look.py use`
            # refused a converted site with no resume PDF, "'resume.paper' must be Letter or A4").
            d["resume"] = dict((k, v) for k, v in d["resume"].items() if k != "paper")
        work = dict(self.work)
        if not labels_nonempty(work.get("labels")):
            work.pop("labels", None)
        d["work"] = work
        if self.siteKind != "portfolio":
            d["siteKind"] = self.siteKind
        if self.featuredFrom != "home":
            d["featuredFrom"] = self.featuredFrom
        if self.nav:
            d["nav"] = dict(self.nav)
        if self.look is not None:
            d["look"] = self.look
        if self.lookLocal is not None:
            d["lookLocal"] = self.lookLocal
        if self.blocks:
            d["blocks"] = dict(self.blocks)
        if self.featuredView != "flat":
            d["featuredView"] = self.featuredView
        if self.titleSeparator != TITLE_SEPARATOR_DEFAULT:
            d["titleSeparator"] = self.titleSeparator
        if self.mediaPaths:
            d["mediaPaths"] = dict(self.mediaPaths)
        if self.sizeCopies is not None:
            d["sizeCopies"] = self.sizeCopies
        if self.carried:
            d["carried"] = list(self.carried)
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

    def site_path(self):
        """The site's path (design-adopt-parity-2 section 4.7.3): the path part of `site_url()` without its slashes
        (`site` for `https://pat.github.io/site`, `""` for a domain after cutover), or None when `site_url()` is None.
        The one function every reader of "the site's path" calls; `preview.base_path` returns it and keeps its own
        fallback to the repo's name, which is a guess good enough to serve a preview and never to judge a page on."""
        url = self.site_url()
        if url is None:
            return None
        return urllib.parse.urlsplit(url).path.strip("/")

    def __eq__(self, other):
        return isinstance(other, SiteConfig) and self.to_dict() == other.to_dict()

    def __ne__(self, other):
        return not self == other


def _no_dupes(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise SiteConfigError("site.json: duplicate key '%s'; remove the repeated key from site/site.json" % k)
        out[k] = v
    return out


def _clone_slug(value):
    """'owner/name' when `value` is a github.com clone URL (https, scp or ssh form), else None."""
    try:
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
        col.add("site.json: 'schema' is missing", "schema", "missing", "1 to %d" % SCHEMA_MAX,
                "add \"schema\": 1 (or up to %d when the site uses a feature that needs it)" % SCHEMA_MAX)
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
        col.add("site.json: 'schema' must be 1 or more", "schema", schema, "1 to %d" % SCHEMA_MAX,
                "set \"schema\" to a whole number from 1 to %d" % SCHEMA_MAX)
        return col.problems, None
    for k in data:
        if (k not in KEY_ORDER and k not in V2_TOP_KEYS and k not in V4_TOP_KEYS and k not in V6_TOP_KEYS
                and k not in V7_TOP_KEYS):
            col.add("site.json: unknown key '%s'" % k, k, "unknown key", "one of: " + ", ".join(CANON_ORDER),
                    "remove '%s'" % k)
        elif k in V7_TOP_KEYS and schema < 7:
            col.problems.append(needs_schema_7(k, schema).problem)
        elif k in V2_TOP_KEYS and schema < 2:
            col.problems.append(_needs_schema_2(k).problem)
        elif k in V4_TOP_KEYS and schema < 4:
            col.problems.append(_needs_schema_4(k, schema).problem)
        elif k in V6_TOP_KEYS and schema < 6:
            col.problems.append(needs_schema_6(k, schema).problem)
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
    if schema >= 4 and "nav" in data:
        d["nav"] = _nav_check(data["nav"], col, schema)
    if schema >= 4 and "look" in data:
        ok, look = col.run(_look, data["look"])
        if ok:
            d["look"] = look
    if schema >= 7 and "lookLocal" in data:
        ok, local = col.run(_look_local, data["lookLocal"], data.get("look"))
        if ok:
            d["lookLocal"] = local
    if schema >= 4 and "blocks" in data:
        d["blocks"] = _blocks_check(data["blocks"], col, schema)
    if schema >= 6:
        d.update(v6_top_check(data, col))
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
        raise SiteConfigError("site.json is not valid JSON: %s; fix the JSON in site/site.json at the place it names" % e)


def parse_text(text):
    return parse_data(decode(text))


def load(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError as e:
        raise SiteConfigError("site.json cannot be read: %s; check that site/site.json exists and your account can read it" % e)
    except UnicodeDecodeError:
        raise SiteConfigError("site.json is not UTF-8; save site/site.json as UTF-8")
    return parse_text(text)
