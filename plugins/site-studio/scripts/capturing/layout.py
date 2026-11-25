"""capturing/layout.py -- capture's layout words: the flags, the schema check, and the suggestion printed after every page
(site-studio 0.9.0, dev 1061; design-reference-layout section 1.5; owner answers O-2 and O-3). Python 3.9, standard library only.

`project`, `type` and `channel` say which piece a reference is for, what it is and where its audience saw it. This module does three
things and stores nothing itself:

  * `check_words` checks `--project`, `--type`, `--channel` BEFORE any browser starts: one URL, one line of text, `type` and
    `channel` at most `REFERENCE_VALUE_MAX` characters, the site at schema 9 and a portfolio site (a hub or custom site does not
    load references), a value the site's own list holds, and a `project` that names exactly one of the site's pieces. A site whose
    `site.json` cannot be read is NOT CHECKED: the words are stored, with a note saying so (as `--role` is).
  * `schema_problem` is that same schema check for `--role` (schema 4); it was `capture.py`'s own until 0.9.0.
  * `suggestion` returns the lines printed after each captured page: the three keys, each with where its value came from
    (`type Post (the address)`), and the site's pieces for `project`. It NEVER stores anything: only a flag's words reach
    `reference.json`. A key the reference already holds, a value the site's list does not hold, and an address that names
    nothing are each printed as "no suggestion" with the reason, never as a guess.

    read_site(out_root)                         the site's schema, kind, lists and pieces, or why they are unknown (never raises)
    schema_problem(site, names, schema, what)   (refusal, note) for storing `names` on this site
    check_words(words, site, n_urls)            ({key: the person's cleaned words}, note): raises LayoutError
    suggestion(name, url, ref, site)            [line] to print for a captured page

The pieces are read from paths (`content/<portfolio>/<slug>/index.md`, neither folder starting `_`, the portfolio not a reserved
name), not from a loaded model: a piece the build refuses for its own reason still counts, and a draft is a piece.
"""
import collections
import json
import os
import unicodedata

from capturing import platforms
from configschema import diagnostics, model
from configschema.configkeys import REFERENCE_VALUE_MAX, V9_REFERENCE_KEYS
from contentmodel.keytables import RESERVED_PORTFOLIO_NAMES

ROLE_SCHEMA = 4      # the schema that first accepts a reference's `role` (siteconfig.V4_REFERENCE_KEYS)
LAYOUT_SCHEMA = 9    # the schema that first accepts `project`, `type` and `channel` (configkeys.V9_REFERENCE_KEYS)
PIECES_NAMED = 10    # how many of the site's pieces the suggestion names; the rest are counted
FLAGS = {"project": "--project", "type": "--type", "channel": "--channel"}

Site = collections.namedtuple("Site", "schema kind types channels pieces unknown")


class LayoutError(ValueError):
    """A flag refused before a browser starts; capture.py re-raises it as its own CaptureError."""


def _pieces(content):
    """[(portfolio, slug)] under `content`, from paths only."""
    found = []
    try:
        portfolios = sorted(os.listdir(content))
    except OSError:
        return found
    for p in portfolios:
        if p.startswith("_") or p in RESERVED_PORTFOLIO_NAMES or not os.path.isdir(os.path.join(content, p)):
            continue
        try:
            slugs = sorted(os.listdir(os.path.join(content, p)))
        except OSError:
            continue
        found += [(p, s) for s in slugs if not s.startswith("_") and os.path.isfile(os.path.join(content, p, s, "index.md"))]
    return found


def read_site(out_root):
    """The site that holds `out_root` (<repo>/content/references): `Site(schema, kind, types, channels, pieces, unknown)`. When its
    `site/site.json` is missing or cannot be read every field is None and `unknown` says why; a missing thing is never an empty one."""
    content = os.path.dirname(os.path.abspath(out_root))
    cfg_path = os.path.join(os.path.dirname(content), "site", "site.json")
    if not os.path.isfile(cfg_path):
        return Site(None, None, None, None, None, "no site/site.json beside %s, so the site's schema is unknown" % out_root)
    try:
        cfg = model.load(cfg_path)
    except diagnostics.SiteConfigError as e:
        return Site(None, None, None, None, None, "%s could not be read (%s), so the site's schema is unknown" % (cfg_path, e))
    refs = cfg.references or {}
    return Site(cfg.schema, cfg.siteKind, refs.get("types"), refs.get("channels"), _pieces(content), None)


def _are(names):
    return ("%s is a schema %%d key" if len(names) == 1 else "%s are schema %%d keys") % " and ".join(names)


def schema_problem(site, names, schema, what):
    """(refusal, note) for storing the flags `names`, which need `schema`, on `site`. `what` is ("the role is", "it"). A site below
    `schema` is a refusal, not a note: the build refuses a reference holding the key there. An unreadable site is NOT CHECKED."""
    if site.unknown:
        return None, ("NOT CHECKED: %s; %s stored, and the build refuses %s unless the site is at schema %d"
                      % (site.unknown, what[0], what[1], schema))
    if site.schema < schema:
        return (("%s and this site is at schema %d: the build would refuse the reference as an unknown key. Nothing was captured. "
                 "Raise the site to schema %d first (build.py raise-schema --to %d shows what would change), then capture again")
                % (_are(names) % schema, site.schema, schema, schema)), None
    return None, None


def role_schema_problem(out_root):
    """(refusal, note) for storing a `role` in `out_root`."""
    return schema_problem(read_site(out_root), ("--role",), ROLE_SCHEMA, ("the role is", "it"))


def _word(key, text):
    """The person's words for `key` as the loader will read them: text, one line, not empty, and for `type` and `channel` no more
    than `REFERENCE_VALUE_MAX` characters after trimming (a `project` slug has no limit)."""
    flag = FLAGS[key]
    if not isinstance(text, str) or not text.strip():
        raise LayoutError("%s is empty: say it in a few words, or leave %s off" % (flag, flag))
    t = text.strip()
    if len(t.splitlines()) != 1:
        raise LayoutError("%s must be one line of text: put it on one line" % flag)
    if key != "project" and len(t) > REFERENCE_VALUE_MAX:
        raise LayoutError("%s is %d characters long: shorten it, a %s is at most %d" % (flag, len(t), key, REFERENCE_VALUE_MAX))
    return t


def _norm(text):
    return unicodedata.normalize("NFC", text)


def _listed(key, value, listed):
    """Refusal text when the site's list (`listed`, or None when the site sets none) does not hold `value`."""
    if not listed or _norm(value) in [_norm(w) for w in listed]:
        return None
    near = [w for w in listed if _norm(w).casefold() == _norm(value).casefold()]
    return ("%s %s is not in this site's list of %ss (%s)%s: use one of them, or add it to site.json `references`"
            % (FLAGS[key], json.dumps(value, ensure_ascii=False), key, ", ".join(listed),
               "; did you mean %s?" % json.dumps(near[0], ensure_ascii=False) if near else ""))


def _flat(text):
    return text.lower().replace("-", "")


def _project(value, pieces):
    """Refusal text unless `value` (a slug, or <portfolio>/<slug>) names exactly one of the site's `pieces`."""
    if "/" in value:
        if tuple(value.split("/", 1)) in pieces:
            return None
        slug = value.split("/", 1)[1]
    else:
        matches = sorted(p for p, s in pieces if s == value)
        if len(matches) == 1:
            return None
        if matches:
            return ("--project %s names pieces in %d portfolios (%s): write <portfolio>/<slug>"
                    % (value, len(matches), ", ".join("%s/%s" % (p, value) for p in matches)))
        slug = value
    close = [s for _p, s in pieces if _flat(s) == _flat(slug)]
    return ("--project %s names no piece on this site%s: use a piece's folder name (content/<portfolio>/<slug>/), or leave --project off"
            % (value, " (did you mean %s?)" % close[0] if close else ""))


def check_words(words, site, n_urls):
    """({key: cleaned words}, note) for the flags the person gave; raises LayoutError, naming the fix, and a refusal comes before any
    browser starts, with nothing written. `words` is {key: raw text} for the keys given."""
    given = [k for k in V9_REFERENCE_KEYS if k in words]
    if not given:
        return {}, None
    if n_urls != 1:
        raise LayoutError("%s needs exactly one URL: the words are about that page" % " and ".join(FLAGS[k] for k in given))
    clean = dict((k, _word(k, words[k])) for k in given)
    names = tuple(FLAGS[k] for k in given)
    if site.kind not in (None, "portfolio"):
        raise LayoutError("%s is for a portfolio site: this site is a %s site, whose references are not loaded. Nothing was captured; "
                          "leave %s off" % (" and ".join(names), site.kind, "it" if len(names) == 1 else "them"))
    problem, note = schema_problem(site, names, LAYOUT_SCHEMA, ("the layout words are", "them"))
    if problem:
        raise LayoutError(problem)
    for k in ("type", "channel"):
        if k in clean:
            problem = _listed(k, clean[k], site.types if k == "type" else site.channels)
            if problem:
                raise LayoutError(problem)
    if "project" in clean and site.pieces is not None:
        problem = _project(clean["project"], site.pieces)
        if problem:
            raise LayoutError(problem)
    return clean, note


def piece_names(pieces):
    """The names a person types for the pieces: the slug, or <portfolio>/<slug> where two portfolios hold the same slug."""
    count = collections.Counter(s for _p, s in pieces)
    return sorted(s if count[s] == 1 else "%s/%s" % (p, s) for p, s in pieces)


def _held(ref):
    """{key: value} of the layout keys the reference already holds, a blank one included (left blank on purpose: never offered again)."""
    return dict((k, ref[k]) for k in V9_REFERENCE_KEYS if k in ref)


def _said(value):
    return value if isinstance(value, str) and value.strip() else "left blank on purpose; no suggestion"


def _project_line(held, site):
    if "project" in held:
        return "  project: already set (%s)" % _said(held["project"])
    if site.pieces is None:
        return "  project: which piece is this for? (the site's pieces could not be read)"
    if not site.pieces:
        return "  project: which piece is this for? (this site has no pieces yet: add the piece first)"
    names = piece_names(site.pieces)
    more = len(names) - PIECES_NAMED
    return "  project: which piece is this for? The site's pieces: %s%s" % (", ".join(names[:PIECES_NAMED]),
                                                                      " and %d more" % more if more > 0 else "")


def _word_line(key, value, none_why, held, listed):
    """(line, value to offer or None) for `type` or `channel`."""
    if key in held:
        return "  %s: already set (%s)" % (key, _said(held[key])), None
    if value is None:
        return "  %s: no suggestion (%s)" % (key, none_why), None
    if listed and _norm(value) not in [_norm(w) for w in listed]:
        return "  %s: no suggestion (%s is not in this site's list of %ss)" % (key, value, key), None
    return "  %s %s (the address)" % (key, value), value


def suggestion(name, url, ref, site):
    """The lines to print after the page `name` (captured from `url` as `ref`): a block headed "suggested layout", or one line saying
    why none. Nothing here is stored; the person says yes, and `--project`, `--type`, `--channel` store their words."""
    if site.kind not in (None, "portfolio"):
        return ["%s: no layout suggested: this is a %s site, whose references are not loaded" % (name, site.kind)]
    if site.unknown:
        head = ("NOT CHECKED: the site's schema is unknown, so the build refuses these keys unless the site is at schema %d"
                % LAYOUT_SCHEMA)
    elif site.schema < LAYOUT_SCHEMA:
        head = ("to keep this, the site must be at schema %d: `build.py raise-schema --to %d` shows what would change"
                % (LAYOUT_SCHEMA, LAYOUT_SCHEMA))
    else:
        head = "the site is at schema %d" % site.schema
    held = _held(ref)
    g = platforms.guess(url)
    host = platforms.host_of(url) or "this address"
    cwhy = ("%s stores and plays files, so the address cannot say where it was seen" % host if g.host_kind == "file"
            else "the address hides where it leads (a backslash, a user part, a port, or a share or redirect wrapper)"
            if platforms.looks_disguised(url) else "%s names no platform the plugin knows" % host)
    tline, tvalue = _word_line("type", g.type, "the address does not say what it is", held, site.types)
    cline, cvalue = _word_line("channel", g.channel, cwhy, held, site.channels)
    offered = [(k, v) for k, v in (("type", tvalue), ("channel", cvalue)) if v]
    lines = ["%s: suggested layout (%s; nothing is stored until the person says yes)" % (name, head),
             _project_line(held, site), tline, cline]
    if offered:
        lines.append("  as text for reference.json: %s" % ", ".join('"%s": %s' % (k, json.dumps(v, ensure_ascii=False))
                                                                      for k, v in offered))
    return lines
