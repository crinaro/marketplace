"""Writing the output tree and its digest (design 3.5)."""

import hashlib
import os

import content as C

from building.constants import HTML_EXTS
from building.outcomes import BuildError
from building.tokens import nfc


def _write_outputs(out_dir, out):
    for rel in sorted(out, key=lambda p: p.encode("utf-8")):
        full = os.path.join(out_dir, *rel.split("/"))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        data = out[rel]
        if rel.lower().endswith(C.TEXT_EXTS) or rel in ("CNAME", "robots.txt") or \
                rel.lower().endswith(HTML_EXTS):
            if b"\r" in data:
                raise BuildError("%s would be written with a carriage return" % rel, fix="save the file with LF line endings")
        with open(full, "wb") as fh:
            fh.write(data)
        os.chmod(full, 0o644)


def _check_out_dir(out_dir):
    if os.path.exists(out_dir) and (not os.path.isdir(out_dir) or os.listdir(out_dir)):
        raise BuildError("%s already exists and is not empty; build into a new or empty folder"
                         % out_dir, fix="build into a new or empty folder, or delete the old output")


def _digest_tree(out_dir, site_kind="portfolio"):
    """The digest of design 3.5: SHA-256 of `<NFC path> NUL <hex sha256 of content> LF` per
    regular file, in the order of the UTF-8 bytes of the NFC path, then `siteKind NUL <kind> LF`
    when the kind is not `portfolio` (see the module docstring). Private: only `publish_build`
    calls it."""
    entries = []
    for d, _dirs, names in os.walk(out_dir):
        for n in names:
            full = os.path.join(d, n)
            rel = nfc(os.path.relpath(full, out_dir).replace(os.sep, "/"))
            with open(full, "rb") as fh:
                entries.append((rel.encode("utf-8"), hashlib.sha256(fh.read()).hexdigest()))
    h = hashlib.sha256()
    for rel_b, sha in sorted(entries):
        h.update(rel_b + b"\0" + sha.encode("ascii") + b"\n")
    if site_kind != "portfolio":
        h.update(b"siteKind\0" + site_kind.encode("ascii") + b"\n")
    return h.hexdigest()


def digest_output_tree(path, site_kind="portfolio"):
    """The design 3.5 digest of an arbitrary DIRECTORY of output files (dev #835, finding F1).

    A public wrapper over the private `_digest_tree`, same formula, so `deploy.py` can digest the
    PUBLIC clone's tree (publish step 2.5 and 5.5) without a second implementation that could
    drift. It does NOT build anything and is not reachable from `preview_build`, whose result
    still has no digest attribute. The caller owns what the directory holds.

    `site_kind` is the kind of the site the directory was built from (`PublishResult.site_kind`). A
    `hub` or `custom` site's digest carries one final kind line (module docstring), and a public
    clone's tree holds no `site.json`, so the CALLER must say the kind or the two digests differ."""
    if not os.path.isdir(path):
        raise BuildError("%s is not a folder" % path, fix="pass a folder that holds the built output")
    return _digest_tree(path, site_kind)
