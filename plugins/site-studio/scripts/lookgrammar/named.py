"""lookgrammar/named.py -- a look's `named`: blocks and views a site names (design-adopt-ownership-line section 6.6, owner
answer O-3 (a); site-studio 0.7.0). Python 3.9, standard library only. Imports no `looks`: the caller hands over the part
checker (`looks.check_part`) and the default look's table reader (`looks.default_renders`), as `lookgrammar.reads` takes them.

    "named": { "<name>": {"like": "<base>", "parts": {"<part>": "<markup>", ...}}, ... }

Each entry takes the DATA SHAPE of one plugin construct (`like`, a row of `NAMED_BASES`) and supplies its own markup, in
look grammar only: its parts are the base's parts, each checked by the base's rows of `CONSTRUCTS`. No slot table, line
syntax or logic is the site's. A part the entry leaves out renders from the default look's entry for the base; the
entry links the plugin files its own `assets` would, which is none (the rule of any construct a look writes: a look that
writes its own markup brings its own stylesheet). The base's `reads` entries and variant parts apply to it.

    NAMED_BASES                         base construct -> (BLOCK or VIEW, the name content uses for the base)
    reserved()                          every plugin block, view, construct and fixed part name (a name may be none)
    parse_named(where, value, check_part, shipped, template)   ({name: Named}, [problem line]): every refusal
    pair_problems(where, named, reads, default_has)            the base's choice targets and variant parts, per entry
    merge(base, local)                  rule P2 per name: local's entry replaces base's whole
    replaced_lines(where, base, local, base_where)             P5: one line per name both files hold
    block_names(look) / block_base(look, name)                 the names content may open as `:::name`, and the base
    view_base(look, name)               the base view (`roles`, `showcase`, `steps`) of a named view, or None
    as_look(look, name)                 the look a named construct prints through: the effective look with the base's
                                        entry replaced by the named entry's parts
    tree_views(files, look_ref, local_ref)   {name: base view} read from the two look files of a tree, for the `page.md`
                                        `view` check, which runs before the build loads the look (step 0 probe U-T1)

A name the effective look does not hold is refused where it is used, as before 0.7.0: an unknown block, or a `view` value
that is not one of the listed ones. With no `named` key nothing here changes a byte (every answer is empty)."""

import copy
import json
import re

from configschema.configkeys import PAGE_VIEWS, V4_PAGE_VIEWS, V4_PART_FIXED, V5_PAGE_VIEWS
from contentmodel.grammar import BLOCK_NAMES, BLOCK_NAMES_V4, PART_FIXED
from lookgrammar.constructs import CONSTRUCTS
from lookgrammar.reads import CHOICE, READS, variant_part

BLOCK, VIEW = "block", "view"
# Section 6.6: the bases a named construct may take. Not `map-view`: its drawing is the plugin's.
NAMED_BASES = {
    "tiles": (BLOCK, "tiles"), "quote": (BLOCK, "quote"), "quotes": (BLOCK, "quotes"), "gallery": (BLOCK, "gallery"),
    "videos": (BLOCK, "videos"), "carousel": (BLOCK, "carousel"),
    "roles-view": (VIEW, "roles"), "showcase-view": (VIEW, "showcase"), "steps-view": (VIEW, "steps"),
}
MAX_NAME = 40
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")      # the block-open pattern (`contentmodel.grammar._OPEN`)


class Named(object):
    """One parsed entry: `like` (a `NAMED_BASES` row) and `parts` {part: markup}."""

    def __init__(self, like, parts):
        self.like = like
        self.parts = dict(parts)

    def __eq__(self, other):
        return isinstance(other, Named) and (self.like, self.parts) == (other.like, other.parts)

    def __repr__(self):
        return "Named(%r, %r)" % (self.like, self.parts)


def reserved():
    """Every name a site's name may not be: the plugin's block names, `view` values, construct ids and fixed home part
    names at the newest schema (a named construct needs schema 7, the newest), sorted."""
    names = set(BLOCK_NAMES + BLOCK_NAMES_V4 + PAGE_VIEWS + V4_PAGE_VIEWS + V5_PAGE_VIEWS + PART_FIXED + V4_PART_FIXED)
    return sorted(names | set(CONSTRUCTS))


def _what(name):
    """How a clash names the plugin's own name."""
    if name in BLOCK_NAMES + BLOCK_NAMES_V4:
        return "the plugin block :::%s" % name
    if name in PAGE_VIEWS + V4_PAGE_VIEWS + V5_PAGE_VIEWS:
        return "the plugin view %r" % name
    if name in CONSTRUCTS:
        return "the plugin construct %s" % name
    return "the fixed home part %r" % name


def _name_problems(where, name):
    if not isinstance(name, str) or not NAME_RE.match(name) or len(name) > MAX_NAME:
        return ["%s: named %r is not a name: a letter, then letters, digits, - or _, at most %d characters -- fix: rename "
                "it, such as t-ledger" % (where, name, MAX_NAME)]
    if name in reserved():
        return ["%s: named %r clashes with %s -- fix: rename it, such as t-%s" % (where, name, _what(name), name)]
    return []


def _entry(where, name, value, check_part, shipped, template):
    """(Named or None, [problem line]) of one entry."""
    if not isinstance(value, dict):
        return None, ['%s: named %s is an object {"like": BASE, "parts": {PART: MARKUP}} (BASE is a plugin construct) -- fix: write it as one' % (where, name)]
    out = ["%s: named %s has the unknown member %r (like, parts) -- fix: remove it" % (where, name, k)
           for k in sorted(value) if k not in ("like", "parts")]
    like, parts = value.get("like"), value.get("parts")
    if like not in NAMED_BASES:
        out.append("%s: named %s: like is %r; it takes the data shape of one of %s -- fix: set like to one of them"
                   % (where, name, like, ", ".join(sorted(NAMED_BASES))))
        return None, out
    if not isinstance(parts, dict):
        out.append("%s: named %s: parts is an object of part -> markup (the parts of %s: %s) -- fix: write it as one"
                   % (where, name, like, ", ".join(sorted(CONSTRUCTS[like]["parts"]))))
        return None, out
    for pn in sorted(parts):
        if pn not in CONSTRUCTS[like]["parts"]:
            out.append("%s: named %s: %s has no part %r (its parts: %s)"
                       % (where, name, like, pn, ", ".join(sorted(CONSTRUCTS[like]["parts"]))))
            continue
        for msg, fix in check_part(like, pn, parts[pn], shipped=shipped, template=template):
            out.append("%s: named %s: %s%s" % (where, name, msg, " -- fix: " + fix if fix else ""))
    return (Named(like, parts) if not out else None), out


def parse_named(where, value, check_part, shipped=False, template=False):
    """({name: Named}, [problem line]) of a look's `named` value. `{}` is a valid, empty table. `check_part` is
    `looks.check_part`: each part is checked by the base's slot table, exactly as the base's own entry would be."""
    if not isinstance(value, dict):
        return {}, ['%s: `named` is an object of name -> {"like": BASE, "parts": {PART: MARKUP}} (BASE is a plugin construct) -- fix: write it as one' % where]
    clean, out = {}, []
    for name in sorted(value):
        problems = _name_problems(where, name)
        if not problems:
            entry, problems = _entry(where, name, value[name], check_part, shipped, template)
            if entry is not None:
                clean[name] = entry
        out.extend(problems)
    return clean, out


def pair_problems(where, named, reads, default_has):
    """[problem line] of the base's choice pairs, per entry (section 6.3 for a named construct): the base's `reads` choice
    applies to the entry, so the entry must hold the variant part it picks for (unless the default look renders it), and
    an entry writing a variant part needs the choice. Run where `reads.pair_problems` runs (with layering, on the merge)."""
    out = []
    for name in sorted(named):
        entry = named[name]
        for target in sorted(t for t, row in READS.items() if row["kind"] == CHOICE):
            construct, part = variant_part(target)
            if construct != entry.like or default_has(construct, part):
                continue
            own = part in entry.parts
            if target in reads and not own:
                out.append("%s: named %s takes %s's reads %s, which picks entries for the part %s, and the entry does not "
                           "write it -- fix: write parts.%s in named %s, or remove the reads entry"
                           % (where, name, construct, target, part, part, name))
            if own and target not in reads:
                out.append("%s: named %s writes %s, printed only for the entries reads %s picks, and the look has no such "
                           "entry -- fix: add \"%s\": [\"@first\"] (or @last, or a key) to reads, or remove the part"
                           % (where, name, part, target, target))
    return out


def merge(base, local):
    """Rule P2 per name: the merged table, `local`'s entry replacing `base`'s whole."""
    out = dict(base or {})
    out.update(local or {})
    return out


def replaced_lines(local_where, base, local, base_where):
    """P5, no silent shadow: one line per name both tables hold."""
    return ['%s replaces named "%s" of %s' % (local_where, n, base_where) for n in sorted(set(local or {}) & set(base or {}))]


def _table(look):
    return (getattr(look, "named", None) or {}) if look is not None else {}


def block_names(look):
    """The names of the look's named blocks, sorted (() for no look, or one without `named`)."""
    return tuple(sorted(n for n, e in _table(look).items() if NAMED_BASES[e.like][0] == BLOCK))


def block_base(look, name):
    """The base block a named block is parsed as (`tiles`), or None when `name` is not one of the look's named blocks."""
    e = _table(look).get(name)
    return e.like if e is not None and NAMED_BASES[e.like][0] == BLOCK else None


def view_base(look, name):
    """The base view a named view builds the data of (`roles`), or None when `name` is not one of the look's named views."""
    e = _table(look).get(name)
    return NAMED_BASES[e.like][1] if e is not None and NAMED_BASES[e.like][0] == VIEW else None


def as_look(look, name):
    """The look a named construct prints through: a copy of the effective `look` whose entry for the base is the named
    entry's parts (a part it leaves out renders from the default look's entry for the base) and whose `assets` has no
    entry for the base (it links nothing, as a construct a look writes without an `assets` entry). Every other construct,
    the `reads`, the `read_keys` (the same set, not a copy) and the stylesheets are the effective look's."""
    entry = _table(look)[name]
    sub = copy.copy(look)
    sub.constructs = dict(look.constructs)
    sub.constructs[entry.like] = dict(entry.parts)
    sub.assets = dict((c, k) for c, k in look.assets.items() if c != entry.like)
    sub.read_keys = look.read_keys      # dev 1058: what a named construct's page reads counts for the effective look
    return sub


def _raw_named(files, ref):
    raw = files.get(ref) if ref else None
    if raw is None:
        return {}
    try:
        data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    except (UnicodeDecodeError, ValueError):
        return {}
    named = data.get("named") if isinstance(data, dict) else None
    return named if isinstance(named, dict) else {}


def tree_views(files, look_ref, local_ref):
    """{name: base view} of the named views the effective look of a tree holds, read from the two look files `look_ref`
    and `lookLocal` name (local's entry winning per name, P2). The `page.md` check runs before the build loads the look,
    so it is handed these names; only an entry with a valid name and a view `like` counts. Whatever else an entry holds is
    the look load's to refuse, which it does on the same build, naming the file."""
    table = merge(_raw_named(files, look_ref), _raw_named(files, local_ref))
    out = {}
    for name, value in table.items():
        like = value.get("like") if isinstance(value, dict) else None
        if like in NAMED_BASES and NAMED_BASES[like][0] == VIEW and not _name_problems("", name):
            out[name] = NAMED_BASES[like][1]
    return out
