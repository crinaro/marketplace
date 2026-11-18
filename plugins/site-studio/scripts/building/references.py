"""Where a reference's card image is published (design-template-fidelity R1, F-d of step 1.9).

A reference whose `reference.json` has no `image` (every tree before schema 4) keeps its card as it always was: the one
`card.<ext>` file in its folder, published at `references/<name>/card.<ext>`. At schema 4 an `image` names the card, and
it is published at its OWN path, `references/<name>/<image>` (the path the reference folder holds it at), so an address
a visitor or another site already holds keeps serving the same bytes. The size copies beside it (`<stem>.wNNN.<ext>`,
and the `<stem>-NNNw.<ext>` naming) are published at their own paths too, and `img_tag` finds them for the card's srcset.

`image` is a schema-4 key (`siteconfig.V4_REFERENCE_KEYS`; a tree below schema 4 refuses it when its content is read), so
the `image` branch below cannot run for a tree an earlier release accepted.
"""
import posixpath
import re

from building.tokens import SIZE_COPY_SHAPES


def _folder(ref):
    return "content/references/%s/" % ref.name


def uses_image_key(ref):
    """True when the reference names its card by `image` (schema 4), not by a `card.<ext>` file."""
    return bool(ref.card_path) and "image" in ref.data


def card_out(ref):
    """The output path of a reference's card image."""
    if uses_image_key(ref):
        return "references/%s/%s" % (ref.name, ref.card_path[len(_folder(ref)):])
    ext = posixpath.splitext(ref.card_path)[1].lower()
    return "references/%s/card%s" % (ref.name, ext)


def size_copies(ref, files):
    """{repo path: output path} of the size copies of a reference's `image`, found by the shapes `img_tag` reads at
    schema 3 and above. Empty for a reference with no `image` key."""
    if not uses_image_key(ref):
        return {}
    folder = posixpath.dirname(ref.card_path)
    stem, ext = posixpath.splitext(posixpath.basename(ref.card_path))
    shapes = [re.compile(r"^%s-(\d+)w%s$" % (re.escape(stem), re.escape(ext)))] + [
        re.compile(pat % (re.escape(stem), re.escape(ext))) for pat, _name in SIZE_COPY_SHAPES]
    out = {}
    for p in sorted(files):
        if posixpath.dirname(p) == folder and any(r.match(posixpath.basename(p)) for r in shapes):
            out[p] = "references/%s/%s" % (ref.name, p[len(_folder(ref)):])
    return out
