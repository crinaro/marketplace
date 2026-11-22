"""Where a reference's card image is published (design-template-fidelity R1, F-d of step 1.9).

A reference whose `reference.json` has no `image` (every tree before schema 4) keeps its card as it always was: the one
`card.<ext>` file in its folder, published at `references/<name>/card.<ext>`. At schema 4 an `image` names the card, and
it is published at its OWN path, `references/<name>/<image>` (the path the reference folder holds it at), so an address
a visitor or another site already holds keeps serving the same bytes. The size copies beside it (`<stem>.wNNN.<ext>`,
and the `<stem>-NNNw.<ext>` naming) are published at their own paths too, and `img_tag` finds them for the card's srcset.

`image` is a schema-4 key (`siteconfig.V4_REFERENCE_KEYS`; a tree below schema 4 refuses it when its content is read), so
the `image` branch below cannot run for a tree an earlier release accepted.

Schema 6 (design-adopt-parity-2 section 4.6): `mediaPaths.references` places a card and its copies under the reference's
`media/` by its pattern (`building.mediapaths`); a card it cannot place refuses the build, naming it. `sizeCopies:
any-format` lets a `.wNNN` copy carry another raster extension (`SIZE_COPY_EXTS`) than its original. Neither key is held
by a tree 0.5.x accepts (both are schema-6 reasons), and without them every function here is 0.5.x's.
"""
import posixpath
import re

from configschema.configkeys import SIZE_COPY_EXTS

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
