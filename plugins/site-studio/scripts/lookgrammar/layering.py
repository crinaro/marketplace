"""layering: the effective look, two parsed look files laid over each other (design-adopt-ownership-line section 3,
rule P; site-studio 0.7.0). Python 3.9, standard library only. Imports no `looks`: the caller hands over the part parser
and the default look's table reader, as `lookgrammar.decoration` and `lookgrammar.reads` take them.

Effective look = the plugin default, then the file `look` names, then the file `lookLocal` names. The unit is the
construct.

    merge(base, local, parser_cls, default_has)   P2 to P4 and P7: the merged look, or a LookError naming both files
    replaced_lines(base, local)                    P5: one line per construct and per `reads` target both files hold
    owner_lines(look)                              which file each construct of a merged look comes from (`look.py check`)
    unread(files, look_ref, local_ref)             P6: the look files in a tree no key names, which nothing reads
    unread_notes(files, look_ref, local_ref)       P6: the note each of them gets on every build and check

P1 is the caller's: each file is parsed alone (`looks.parse(..., cross=False)`), so a refusal names that file. A tree
with no `lookLocal` never reaches `merge`: its look is parsed as it was before 0.7.0 (`cross=True`), byte for byte.
`named` (section 6.6, step 6b) merges per name as `reads` does per target: local's entry replaces base's whole (P2), P5 lists
it, and its choice pairs are checked on the merge (P4)."""

import re

from configschema.configkeys import LOOK_LOCAL_PATH
from lookgrammar import decoration
from lookgrammar import named as looknamed
from lookgrammar import reads as lookreads
from lookgrammar.constructs import CONSTRUCTS
from lookgrammar.errors import LookError

# The look files of a tree: the same pattern `building/lookneeds.LOOK_PATH_RE` reads (a test pins the two equal).
LOOK_FILE_RE = re.compile(r"^site/looks/[a-z0-9][a-z0-9-]*\.json$")
LOCAL_UNUSED = '%s is not used: site/site.json has no "lookLocal"'
UNNAMED_UNUSED = '%s is not used: site/site.json names it in neither "look" nor "lookLocal"'


def unread(files, look_ref, local_ref):
    """The sorted look files of `files` ({repo path: bytes}) that neither `look_ref` nor `local_ref` names: no build reads
    them (section 2.1, "not a reason"), so they change no byte and need no release."""
    named = set(r for r in (look_ref, local_ref) if r)
    return sorted(p for p in files if LOOK_FILE_RE.match(p) and p not in named)


def unread_notes(files, look_ref, local_ref):
    """P6: one note per look file no key names. `site/looks/local.json` without `lookLocal` gets the design's own words."""
    return [(LOCAL_UNUSED if p == LOOK_LOCAL_PATH else UNNAMED_UNUSED) % p for p in unread(files, look_ref, local_ref)]


def replaced_lines(base, local):
    """P5, no silent shadow: each construct and each `reads` target `local` holds that `base` holds too ([] with no base)."""
    if base is None:
        return []
    out = ['%s replaces "%s" of %s' % (local.where, c, base.where) for c in sorted(set(local.constructs) & set(base.constructs))]
    out += ['%s replaces reads "%s" of %s' % (local.where, t, base.where) for t in sorted(set(local.reads) & set(base.reads))]
    out += looknamed.replaced_lines(local.where, getattr(base, "named", {}), getattr(local, "named", {}), base.where)
    return out


def owner_lines(look):
    """`look.py check`'s line per construct a merged look writes: the file it renders from (a construct neither file writes
    renders from the plugin's own look, which `check` already says per construct)."""
    owners = getattr(look, "owners", {})
    return ["%s renders from %s" % (c, owners[c]) for c in sorted(owners) if c in CONSTRUCTS]


def _asset_problems(base, local):
    """An `assets` entry of `local` for a construct `local` writes no part of, while `base` writes that construct. Alone, such
    an entry does nothing (the construct renders from the other file); laid over `base` it would read as replacing base's
    links and silently not. Loud instead (P7)."""
    if base is None:
        return []
    return ["%s: `assets` names %s, which it writes no part of, and %s writes %s; a construct is replaced whole, so write "
            "its parts in %s too, or remove the assets entry" % (local.where, c, base.where, c, local.where)
            for c in sorted(local.assets) if c not in local.constructs and c in base.constructs]


def merge(base, local, parser_cls, default_has):
    """The effective look of `base` (the parsed `look` file, or None: the default alone) under `local` (the parsed `lookLocal`
    file). Each was parsed alone with `cross=False`; nothing here drops, repairs or skips a part (P7).

    P2: a construct `local` writes replaces base's whole, its parts and its `assets` entry; a part it omits renders from the
    plugin default, never from `base`; a `named` entry likewise, per name. P3: `reads` per target, local's entry winning; `stylesheets` base's list, then
    local's entries not already in it. P4: the checks that span files run here, on the merged constructs, naming both files:
    a decoration id written in both, a `reads` choice whose variant part neither writes, `{{usedBy}}` with no part to fill it
    (`reads.pair_problems`). The gated-trigger check (0.5.0 section 4.4) runs in the build on the look this returns.

    The result is the class of `local` (a `looks.Look`) with `layers` (the file paths, base first), `owners` ({construct: the
    file it renders from}) and `replaced` (`replaced_lines`)."""
    held = set(local.constructs)
    constructs = {} if base is None else dict((c, dict(p)) for c, p in base.constructs.items() if c not in held)
    constructs.update((c, dict(p)) for c, p in local.constructs.items())
    assets = {} if base is None else dict((c, list(k)) for c, k in base.assets.items() if c not in held)
    assets.update((c, list(k)) for c, k in local.assets.items() if c in held)
    sheets = [] if base is None else list(base.stylesheets)
    sheets += [s for s in local.stylesheets if s not in sheets]
    reads = {} if base is None else dict(base.reads)
    reads.update(local.reads)
    named = looknamed.merge(None if base is None else getattr(base, "named", {}), getattr(local, "named", {}))
    where = local.where if base is None else "%s over %s" % (local.where, base.where)
    problems = _asset_problems(base, local)
    problems += decoration.look_problems(where, constructs, parser_cls)
    problems += lookreads.pair_problems(where, constructs, reads, default_has)
    problems += looknamed.pair_problems(where, named, reads, default_has)
    if problems:
        raise LookError("\n".join(problems), fix="fix each line above in the file it names, then run the check again")
    merged = type(local)(constructs, sheets, assets, where, reads, named)
    merged.layers = (local.where,) if base is None else (base.where, local.where)
    merged.owners = dict((c, local.where if c in held else base.where) for c in constructs)
    merged.replaced = replaced_lines(base, local)
    return merged
