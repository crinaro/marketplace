"""tree.py -- a built tree as the gate reads it (`Tree`: file names and sizes, text on demand), the site's base
URL, and the classification of a URL as internal, external or insecure.
"""

import os
import re
from contentmodel import links as links_mod


class Tree(object):
    def __init__(self, root):
        self.root = root
        self.files = {}      # rel -> size
        self.symlinks = []
        self.dirs = set()
        for d, dirs, names in os.walk(root):
            for dn in list(dirs):
                full = os.path.join(d, dn)
                rel = os.path.relpath(full, root).replace(os.sep, "/")
                self.dirs.add(rel)
                if os.path.islink(full):
                    self.symlinks.append(rel)
                    dirs.remove(dn)
            for fn in names:
                full = os.path.join(d, fn)
                rel = os.path.relpath(full, root).replace(os.sep, "/")
                if os.path.islink(full):
                    self.symlinks.append(rel)
                    continue
                self.files[rel] = os.path.getsize(full)
        self._cache = {}

    def read(self, rel):
        if rel not in self._cache:
            with open(os.path.join(self.root, rel), "rb") as fh:
                self._cache[rel] = fh.read()
        return self._cache[rel]

    def text(self, rel):
        return self.read(rel).decode("utf-8", "replace")


def site_base(cfg):
    u = cfg.site_url()
    return u.rstrip("/") if u else None


def classify(url, base):
    """(kind, rest) with kind in empty fragment mail tel special external internal protorel rootabs rel. The
    URL is read as a browser reads it (`content.url_as_browser_reads`), so ' java<TAB>script:x' is a
    javascript: link here as it is on a click (dev #912)."""
    u = links_mod.url_as_browser_reads(url.strip())
    if u == "":
        return ("empty", "")
    m = re.match(r"^([A-Za-z][A-Za-z0-9+.\-]*):", u)
    if m:
        s = m.group(1).lower()
        if s in ("http", "https"):
            if base and (u == base or u.startswith(base + "/") or u.startswith(base + "?")
                         or u.startswith(base + "#")):
                rest = u[len(base):]
                return ("internal", rest if rest.startswith("/") else "/" + rest)
            return ("external", u)
        if s == "mailto":
            return ("mail", u[7:])
        if s == "tel":
            return ("tel", u[4:])
        return ("special", u)
    if u.startswith("//"):
        return ("protorel", u)
    if u.startswith("/"):
        return ("rootabs", u)
    if u.startswith("#"):
        return ("fragment", u[1:])
    return ("rel", u)


def _size_copy_of(rel, files):
    """True when `rel` is a `<stem>.w<NNN>.<ext>` copy whose original `<stem>.<ext>` is in `files` (schema 3, F4)."""
    m = re.match(r"^(?P<stem>.+)\.w\d+(?P<ext>\.\w+)$", rel)
    return bool(m) and (m.group("stem") + m.group("ext")) in files
