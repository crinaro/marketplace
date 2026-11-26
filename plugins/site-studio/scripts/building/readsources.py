"""building/readsources.py -- a look's `reads` resolved at build time (design-adopt-ownership-line section 6.2, rule K;
site-studio 0.7.0). The grammar, the table and the parser are `lookgrammar/reads.py`; this module answers, for one read
site, what the effective look's entry for its target makes the build print. Every read site of section 6.2 reads through
here, and with no entry for its target (`reads` absent or `{}`) each answer is what 0.6.0 read (`ReadsDefaultsAreBase`).

    entry(look, target)                      the look's `Spec` for the target, or None
    slot(look, target, lookup, builtins, default)   a slot's value: the entry's first source that gives a non-empty value (as
                                             text, through `frontmatter.meta_text`), else the row's default chain
                                             exactly as 0.6.0 read it (the raw value), else None (the caller's `then`). A row
                                             that carries a `setting` (0.8.0: `kicker.wrap.text`, `cardKicker`) has no chain of
                                             its own: the chain is the caller's `default`, the key(s) the setting names
    rows(look, target, meta, keys)           the keys of a rows target that print: those `meta` holds, less each whose
                                             value equals the `unless` key's (NFC, whitespace squashed)
    choice(look, target, lookup, count, where)   the entries (indices from 0, in the order picked) a choice target sends
                                             through its variant part: the entry's first source that gives a position,
                                             else the row's default chain; None when nothing picks

A `lookup(source)` returns the value a front-matter key holds (None when absent); `builtins` maps a built-in `@name` of
the row to its value (None when the read site has nothing for it, as `@caption` on a bare video line, U-R1). A choice's
`@first` and `@last` are positions, never values. A key's position is a whole number from 1, or several comma separated;
one outside the list, or a value that is not a position, is refused naming the page (`ContentError`), as `currentRole` is.
Imports `contentmodel` and `lookgrammar` only.
"""
import re
import unicodedata

from contentmodel import frontmatter
from contentmodel.errors import ContentError
from lookgrammar.reads import CHOICE, READS, ROWS, SLOT

FIRST, LAST = "@first", "@last"
_POSITIONS = re.compile(r"^\s*\d{1,6}\s*(?:,\s*\d{1,6}\s*)*$")


def entry(look, target):
    """The effective look's `Spec` for `target`, or None (no look, no `reads`, or no entry for it)."""
    if target not in READS:
        raise KeyError("no reads target %r; this is a fault in site-studio: update the plugin, and report it on the plugin's GitHub issues page if it persists" % target)
    return getattr(look, "reads", {}).get(target) if look is not None else None


def _kind(target, kind):
    if READS[target]["kind"] != kind:
        raise KeyError("reads %s is a %s target, not a %s one; this is a fault in site-studio: update the plugin, and report "
                       "it on the plugin's GitHub issues page if it persists"
                       % (target, READS[target]["kind"], kind))


def record(look, target, key):
    """dev 1058: a page's value came from the entry's `key` (or its `unless` key was compared): `look.read_keys` says so, for
    the note that names a key no page reads. A look without the set (a stand-in) records nothing."""
    keys = getattr(look, "read_keys", None)
    if keys is not None:
        keys.add((target, key))


def _value(source, lookup, builtins):
    if source.startswith("@"):
        return (builtins or {}).get(source)
    return lookup(source)


def slot(look, target, lookup, builtins=None, default=None):
    """The value of a slot target, or None when neither the entry nor the default chain gives one (the caller then
    prints what 0.6.0 prints: the word Video, the excerpt, the refusal of a required key). An entry's value is text (a
    list joined, a boolean yes or no); the default chain's is the raw value, as 0.6.0 handed it on. A row with a `setting`
    reads `default` (a tuple of keys, the caller's; None is no chain) in place of the row's own empty one; a row without
    one takes no `default` (a fault in the caller, raised)."""
    _kind(target, SLOT)
    row = READS[target]
    if default is not None and not row["setting"]:
        raise KeyError("reads %s has no setting, so it takes no caller default chain; this is a fault in site-studio: update "
                       "the plugin, and report it on the plugin's GitHub issues page if it persists" % target)
    spec = entry(look, target)
    for src in (spec.sources or ()) if spec is not None else ():
        v = _value(src, lookup, builtins)
        if v is not None:
            text = frontmatter.meta_text(v)
            if text.strip():
                if not src.startswith("@"):
                    record(look, target, src)
                return text
    for src in ((default or ()) if row["setting"] else row["default"]):
        v = _value(src, lookup, builtins)
        if v:
            return v
    return None


def _norm(value):
    return " ".join(unicodedata.normalize("NFC", frontmatter.meta_text(value)).split())


def blank(value):
    """True for a front matter value that says nothing (0.10.0, design-publish-preflight section 6): nothing at all, text of spaces only,
    or an empty list. `False` and `0` are values, and so is a list of anything."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return isinstance(value, (list, tuple)) and not value


def rows(look, target, meta, keys, omit_blank=False):
    """The keys of `keys` (the `meta` or `cardMeta` setting) that print for a piece whose front matter is `meta`: each it
    holds, in order, less each whose value equals the value of the entry's `unless` key. Without an entry, or when the
    piece does not hold the `unless` key, every key it holds (0.6.0). `omit_blank` (0.10.0, a portfolio's `blankMeta: "omit"`):
    a key whose value is `blank` is not one it holds; false is 0.9.0's reading, a blank value printing its empty row."""
    _kind(target, ROWS)
    kept = [k for k in keys if k in meta and not (omit_blank and blank(meta[k]))]
    spec = entry(look, target)
    if spec is None or spec.unless is None or spec.unless not in meta:
        return kept
    against = _norm(meta[spec.unless])
    record(look, target, spec.unless)
    return [k for k in kept if _norm(meta[k]) != against]


def _positions(where, target, source, value, count):
    """[index from 0] a source's value picks, or None when it gives no position (the next source is read)."""
    if source == FIRST:
        return [0] if count() > 0 else None
    if source == LAST:
        n = count()
        return [n - 1] if n > 0 else None
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not (isinstance(value, int) or (isinstance(value, str) and _POSITIONS.match(value))):
        raise ContentError("%s: reads %s reads %s, which holds %r; it must be a position from 1 (or several, comma "
                           "separated)" % (where, target, source, value), path=where,
                           fix="write %s: 1 (or 1, 3), or remove the key" % source)
    picked = [value] if isinstance(value, int) else [int(p) for p in value.split(",")]
    n = count()
    for p in picked:
        if not 1 <= p <= n:
            raise ContentError("%s: reads %s reads %s = %d, and the list has %d entr%s" % (
                where, target, source, p, n, "y" if n == 1 else "ies"), path=where,
                fix="write %s as a position from 1 to %d, or remove the key" % (source, n))
    return [p - 1 for p in picked]


def choice(look, target, lookup, count, where):
    """The entries (indices from 0, in the order picked, no repeats) the choice target sends through its variant part,
    or None when nothing picks. `count()` is the length of the list (called only when a position needs it); `where`
    names the page a refusal names. The entry's sources are read first; when none gives a position, the row's default
    chain (`piece-roles.item-current`: `currentRole`, then `@first`; `tiles.item-accent`: none)."""
    _kind(target, CHOICE)
    spec = entry(look, target)
    for src in (spec.sources or ()) if spec is not None else ():
        picked = _positions(where, target, src, None if src.startswith("@") else lookup(src), count)
        if picked is not None:
            if not src.startswith("@"):
                record(look, target, src)
            return tuple(sorted(set(picked), key=picked.index))
    for src in READS[target]["default"]:
        if src == FIRST:
            picked = [0]          # 0.6.0's "absent, the first", whatever the list's length
        elif src.startswith("@"):
            picked = _positions(where, target, src, None, count)
        else:
            v = lookup(src)       # 0.6.0's own key: checked when the content was read, so never range-checked here
            picked = None if v is None else [int(v) - 1]
        if picked is not None:
            return tuple(picked)
    return None
