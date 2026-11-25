"""The warnings about files a piece folder holds that nothing publishes, and the keys that are read where they
are used."""

from configschema.configkeys import BUILTIN_PIECE_KEYS
from configschema.diagnostics import make_problem
from configschema.frontmatter import front_matter_keys

from contentmodel.frontmatter import decode_text
from contentmodel.keytables import VIEW_PIECE_KEYS, piece_keys_read
from contentmodel.pagefiles import parse_showcase_entry
from lookgrammar.reads import READS


# ---------------------------------------------------------------- strays a piece folder carries (dev #885, dev #882)

STRAY_FILE_FIX = "pieces have one page; put this in index.md, or start the name with _ to keep it as source"

UNKNOWN_KEY_FIX = "add the key to meta or cardMeta, or remove it"


def reads_pairs(look):
    """dev 1058: [(target, key)], sorted, of the piece front matter keys the look's `reads` names: each `from` source that is not
    an `@` built-in and the `unless` key, of a target whose scope is `piece` or `page` (a page target reads a piece's own front
    matter on its page). Scope `reference` names keys of a `reference.json`, never of a piece. [] for no look."""
    out = set()
    for target, spec in (getattr(look, "reads", None) or {}).items():
        if READS.get(target, {}).get("scope") not in ("piece", "page"):
            continue
        out.update((target, src) for src in (spec.sources or ()) if not src.startswith("@"))
        if spec.unless:
            out.add((target, spec.unless))
    return sorted(out)


UNREAD_TAIL = ", and no page reads it"


def unread_notes(look, model):
    """dev 1058: one build note, sorted, per (target, key) the look's `reads` names (`reads_pairs`) that some piece holds and
    that no page read: "`summary` is named by the look's `reads` piece-teaser.wrap.text, and no page reads it". Meant for a
    COMPLETE, unrefused render (the caller's to know): `look.read_keys` is what the render filled. Per key and target, not per
    piece; "read", not "printed". A note, never a warning."""
    held = set(k for pf in model.portfolios for piece in pf.pieces for k in piece.meta)
    read = getattr(look, "read_keys", None) or set()
    return ["`%s` is named by the look's `reads` %s%s" % (key, target, UNREAD_TAIL)
            for target, key in sorted(reads_pairs(look), key=lambda tk: (tk[1], tk[0])) if key in held and (target, key) not in read]


def piece_known_keys(portfolio, featured_from="home", showcased=False, look=None):
    """The front matter keys of a piece that the build reads or shows: the built-in ones, `description` (the
    page's meta description), the portfolio's `groupBy` key, every key `meta` or `cardMeta` lists, `featured`
    under `featuredFrom: flags` (where the piece's own flag picks the featured pieces), and the keys a setting
    reads (`VIEW_PIECE_KEYS`: those of the portfolio's `view` and of `cardNumber` when it is on) and, with the effective `look` (dev 1058),
    the keys its `reads` takes from a piece (`reads_pairs`). `showcased`
    is True for a piece the home page's `showcase` names: its tile keys are read wherever its portfolio's view
    is (design R4 row 6). Under a schema-5 trigger, the `V5_PIECE_KEYS` rows it turns on and the key `cardKicker`
    names (design-movement-view section 3.3), and under schema 6's `pieceRoles` the `V6_PIECE_KEYS` rows (`currentRole`
    among them; design-adopt-parity-2 section 3.2), both through `piece_keys_read`; without a trigger none of them is
    known here, so `currentRole` in a 0.5.x tree is reported as not published, as 0.5.x reports it."""
    known = set(BUILTIN_PIECE_KEYS) | {"description"}
    known.update(key for _target, key in reads_pairs(look))          # dev 1058: what the effective look's `reads` takes
    known.update(portfolio.settings["meta"])
    known.update(portfolio.settings["cardMeta"])
    if portfolio.settings["groupBy"]:
        known.add(portfolio.settings["groupBy"])
    if featured_from == "flags":
        known.add("featured")
    known.update(VIEW_PIECE_KEYS.get(portfolio.settings.get("view"), ()))
    if portfolio.settings.get("cardNumber"):
        known.update(VIEW_PIECE_KEYS["cardNumber"])
    if showcased:
        known.update(VIEW_PIECE_KEYS["showcase"])
    known.update(piece_keys_read(portfolio.settings))
    return known


def stray_warnings(files, model, cfg, look=None):
    """WARNINGS (never refusals) for what a piece folder holds that the build does not publish, as
    `make_problem`-shaped items sorted by (path, line, message). Two classes, both named, both with a fix:

    - dev #885: a `.md` in a piece folder other than `index.md` (the piece is ONE page), and a sub-folder
      other than `media/`. A name starting with `_` is the way to keep something as source (the loader's own
      rule for folders; applied to the stray `.md` file too, so the fix this warning names clears it).
    - dev #882 (the unknown-key part): a front matter key that is neither built in nor named in the portfolio's
      `meta` or `cardMeta` (see `piece_known_keys`): the build publishes nothing of it.

    This is the OWNER INVARIANT's shape: the tree 0.3.0 built still builds, to the same bytes, at every schema,
    so the build says it and never refuses it. `build.accept` carries these as `.warnings`, apart from
    `.problems`, so `adopt check` can refuse them where nothing has been converted yet. Pure: it reads only
    `files` ({repo path: bytes}) and the loaded `model`. `look` (dev 1058) is the effective look when the build has loaded it:
    a key its `reads` takes from a piece is read, so it is not warned; None where the look is refused or absent."""
    below = {}      # "content/<portfolio>/<slug>" -> [path parts under the piece folder]
    for p in files:
        parts = p.split("/")
        if len(parts) >= 4 and parts[0] == "content":
            below.setdefault("/".join(parts[:3]), []).append(parts[3:])
    out = []
    showcased = set()       # the pieces the home page's `showcase` names: their tile keys are read (schema 4)
    if model.home is not None and isinstance(model.home.meta.get("showcase"), list):
        for entry in model.home.meta["showcase"]:
            parsed = parse_showcase_entry(entry) if isinstance(entry, str) else None
            if parsed:
                showcased.add(parsed[0])
    for pf in model.portfolios:
        for piece in pf.pieces:
            known = piece_known_keys(pf, cfg.featuredFrom, piece.key in showcased, look)
            rels = below.get(piece.folder, [])
            for rel in sorted(r for r in rels if len(r) == 1):
                name = rel[0]
                if name.lower().endswith(".md") and name != "index.md" and not name.startswith("_"):
                    path = "%s/%s" % (piece.folder, name)
                    out.append(make_problem(
                        "%s: this file is not published; a piece is one page, its index.md" % path, path,
                        name, "index.md as the only page", STRAY_FILE_FIX))
            subs = {}
            for rel in rels:
                if len(rel) >= 2 and rel[0] != "media" and not rel[0].startswith("_"):
                    subs[rel[0]] = subs.get(rel[0], 0) + 1
            for sub in sorted(subs):
                path = "%s/%s/" % (piece.folder, sub)
                n = subs[sub]
                out.append(make_problem(
                    "%s: this folder is not published (%d file%s in it); a piece is one page, its index.md, "
                    "and its media/ folder" % (path, n, "" if n == 1 else "s"), path, sub,
                    "media/ or a folder starting with _", STRAY_FILE_FIX))
            lines = dict(front_matter_keys(decode_text(files[piece.source], piece.source)))
            for key in piece.meta:
                if key in known:
                    continue
                out.append(make_problem(
                    "%s: front matter key '%s' is not published; it is not a built-in key and the %s "
                    "portfolio's meta and cardMeta do not list it" % (piece.source, key, pf.slug),
                    piece.source, key, "a built-in key, or one listed in meta or cardMeta", UNKNOWN_KEY_FIX,
                    lineno=lines.get(key)))
    return sorted(out, key=lambda p: (p.path or "", p.lineno or 0, p.message))
