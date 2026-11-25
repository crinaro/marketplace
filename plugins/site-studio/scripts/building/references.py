"""Where a reference's card image is published (design-template-fidelity R1, F-d of step 1.9).

A reference whose `reference.json` has no `image` (every tree before schema 4) keeps its card as it always was: the one
`card.<ext>` file in its folder, published at `references/<name>/card.<ext>`. At schema 4 an `image` names the card, and
it is published at its OWN path, `references/<name>/<image>` (the path the reference folder holds it at), so an address
a visitor or another site already holds keeps serving the same bytes. The size copies beside it (`<stem>.wNNN.<ext>`,
and the `<stem>-NNNw.<ext>` naming) are published at their own paths too, and `img_tag` finds them for the card's srcset.

`image` is a schema-4 key (`siteconfig.V4_REFERENCE_KEYS`; a tree below schema 4 refuses it when its content is read), so
the `image` branch below cannot run for a tree an earlier release accepted.

0.8.0 (design-adopt-local-reach section 1.3, G3): `card_title` (the using piece's name on a `{{cardTitle}}` of the `used-by` part)
and `kind_word` (what the `reads` built-in `@kind` prints: the text of the site's own `reference-card.kind-<kind>` part).

Schema 6 (design-adopt-parity-2 section 4.6): `mediaPaths.references` places a card and its copies under the reference's
`media/` by its pattern (`building.mediapaths`); a card it cannot place refuses the build, naming it. `sizeCopies:
any-format` lets a `.wNNN` copy carry another raster extension (`SIZE_COPY_EXTS`) than its original. Neither key is held
by a tree 0.5.x accepts (both are schema-6 reasons), and without them every function here is 0.5.x's.
"""
import html
import posixpath
import re

import looks
from configschema.configkeys import SIZE_COPY_EXTS
from contentmodel.grammar import _REFLINE

from building import mediapaths
from building.outcomes import BuildError
from building.tokens import SIZE_COPY_SHAPES


def _folder(ref):
    return "content/references/%s/" % ref.name


def uses_image_key(ref):
    """True when the reference names its card by `image` (schema 4), not by a `card.<ext>` file."""
    return bool(ref.card_path) and "image" in ref.data


def card_out(ref, cfg=None):
    """The output path of a reference's card image (`cfg`: the site's config, read for `mediaPaths`)."""
    if uses_image_key(ref):
        default = "references/%s/%s" % (ref.name, ref.card_path[len(_folder(ref)):])
    else:
        default = "references/%s/card%s" % (ref.name, posixpath.splitext(ref.card_path)[1].lower())
    out = mediapaths.reference_out(ref.name, ref.card_path, default, cfg)
    if out is None:
        media = mediapaths.REFERENCE_MEDIA % ref.name
        raise BuildError("%s: mediaPaths.references places the files under %s, and this card is not there"
                         % (ref.card_path, media), path=ref.card_path,
                         fix="move the picture under %s and name it with image, or remove mediaPaths.references" % media)
    return out


def copy_shapes(stem, ext, named=True, any_format=False):
    """The size-copy namings of an image `<stem><ext>`, compiled, group 1 the width: `<stem>-NNNw<ext>` always; the
    `SIZE_COPY_SHAPES` namings too when `named` (schema 3 and above), whose extension under `any_format` (`sizeCopies:
    any-format`) may be any of `SIZE_COPY_EXTS` as well as the original's. `img_tag` and `size_copies` both read it."""
    s, e = re.escape(stem), re.escape(ext)
    shapes = [re.compile(r"^%s-(\d+)w%s$" % (s, e))]
    if named:
        if any_format:
            e = "(?:%s)" % "|".join([e] + [re.escape(x) for x in SIZE_COPY_EXTS if x != ext])
        shapes += [re.compile(pat % (s, e)) for pat, _name in SIZE_COPY_SHAPES]
    return shapes


def size_copies(ref, files, cfg=None):
    """{repo path: output path} of the size copies of a reference's `image`, found by `copy_shapes` as `img_tag` reads
    them at schema 3 and above, each placed as its card is (`mediaPaths`). Empty for a reference with no `image` key."""
    if not uses_image_key(ref):
        return {}
    folder = posixpath.dirname(ref.card_path)
    stem, ext = posixpath.splitext(posixpath.basename(ref.card_path))
    shapes = copy_shapes(stem, ext, True, mediapaths.any_format(cfg))
    out = {}
    for p in sorted(files):
        if posixpath.dirname(p) == folder and any(r.match(posixpath.basename(p)) for r in shapes):
            default = "references/%s/%s" % (ref.name, p[len(_folder(ref)):])
            out[p] = mediapaths.reference_out(ref.name, p, default, cfg) or default
    return out


def used_by(model):
    """{reference name: the first piece, in site order (the portfolios, then each one's pieces, as the build reads them),
    whose body names it on a `ref:` line} (design-adopt-ownership-line section 6.4, U-U1: the pre-pass, from the model,
    before any page renders). A cover or `tileImage` of the form `ref:<name>` shows the reference's picture, not its
    card, and is not counted.

    Schema 9 (design-reference-layout section 1.2): a reference whose `project` names a piece (`Reference.project`, set when the content
    loads) is used by THAT piece, and a `ref:` line does not say otherwise; when that piece is a draft, or is not built, the reference
    has no entry at all (no page to link to) and a `ref:` line does not fill it in. Every other reference is read as it always was."""
    out, held = {}, set()
    for name, ref in getattr(model, "references", {}).items():
        if getattr(ref, "project", None):
            held.add(name)
            piece = model.piece(ref.project)
            if piece is not None and not piece.draft:
                out[name] = piece
    for pf in model.portfolios:
        for piece in pf.pieces:
            for line in piece.body.splitlines():
                m = _REFLINE.match(line)
                if m and m.group(1) not in held:
                    out.setdefault(m.group(1), piece)
    return out


def draft_note(ref):
    """The build note for a reference whose `project` names a draft piece (its card prints no `used by`: there is no page to link to),
    or None for any other reference."""
    if ref is None or not getattr(ref, "project", None) or not ref.project_draft:
        return None
    return ("content/references/%s/reference.json: 'project' names %s, which is a draft, so this reference's card names no piece "
            "until the piece is published" % (ref.name, ref.project))


def card_title(piece):
    """`{{cardTitle}}` of `reference-card.used-by` (0.8.0, G3): the using piece's `shortTitle`, else its `title`. A function of
    its own so `markdownenv.used_by_html` calls it only where a look places the slot."""
    return piece.card_title


def kind_word(look, kind):
    """`@kind` of `reference-card.site.text` (0.8.0, G3, owner decision O-2 (a)): the literal text of the site's own part
    `reference-card.kind-<kind>`, its entities read as the characters they name (the value prints through a text slot), or None
    when the look writes no part for that kind: the plugin holds no word of its own. `kind` is free text in a `reference.json`,
    so a hand-written `podcast` names no part and gives None."""
    if not isinstance(kind, str):
        return None
    own = looks.optional_part("reference-card", "kind-%s" % kind, look)
    return None if own is None else html.unescape(own)
