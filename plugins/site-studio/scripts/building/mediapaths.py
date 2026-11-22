"""Where a folder's media is published under `mediaPaths`, and which copies `sizeCopies: any-format` admits (schema 6;
design-adopt-parity-2 section 4.6, owner decision 1: a measured `mediaPaths` keeps an adopted site's old image addresses).

A pattern (checked by `configschema.sectioncheck._media_pattern`) is two to four `/`-separated segments, each a slug or
`{name}`, the last `{file}`: the file's path under its folder's `media/`. `home` places `content/home/media/**`, `about`
places `content/about/media/**`, and `references` places `content/references/<name>/media/**` with `{name}` the
reference's folder name. The three maps that say where a media file is published (`_PageBase.media_out`,
`references.card_out`, `references.size_copies`) ask this module, and every `src` and `srcset` follows because each is
computed from them. Two sources at one address refuse the build in `_PageBase.add`, as they always did.

**Without the key nothing moves**: every function here returns the address it was given, so a tree 0.5.x accepts (which
cannot hold either key: both are schema-6 reasons) builds the bytes it built.
"""

FOLDER_MEDIA = (("home", "content/home/media/"), ("about", "content/about/media/"))
REFERENCE_MEDIA = "content/references/%s/media/"


def patterns(cfg):
    """`site.json` `mediaPaths` ({folder: pattern}); {} for a tree without it, or no config at all."""
    return getattr(cfg, "mediaPaths", None) or {}


def any_format(cfg):
    """True under `sizeCopies: "any-format"`: a size copy may carry another raster extension than its original."""
    return getattr(cfg, "sizeCopies", None) == "any-format"


def place(pattern, file, name=None):
    """The output path `pattern` gives `file` (a path under the folder's `media/`), with `{name}` read as `name`."""
    segs = pattern.split("/")
    return "/".join([file if s == "{file}" else name if s == "{name}" else s for s in segs])


def media_map(media, cfg):
    """{repo path: output path} of the published media `media` (the model's map, 0.5.x's addresses), each home or about
    media file placed by its folder's pattern when `mediaPaths` names that folder. Every other file keeps its address."""
    pats = patterns(cfg)
    out = {}
    for repo, default in media.items():
        out[repo] = default
        for folder, prefix in FOLDER_MEDIA:
            if folder in pats and repo.startswith(prefix):
                out[repo] = place(pats[folder], repo[len(prefix):])
    return out


def reference_out(name, repo_path, default, cfg):
    """The output path of a file of reference `name` (its card picture or a size copy): `default` without
    `mediaPaths.references`; else the pattern's address for a file under the reference's `media/`, and None for one
    the pattern cannot place (a `card.<ext>`, or an `image` outside `media/`), which the card's caller refuses."""
    pats = patterns(cfg)
    if "references" not in pats:
        return default
    prefix = REFERENCE_MEDIA % name
    if not repo_path.startswith(prefix):
        return None
    return place(pats["references"], repo_path[len(prefix):], name)
