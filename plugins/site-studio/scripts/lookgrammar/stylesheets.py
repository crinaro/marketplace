"""stylesheets: the check of a look's `stylesheets` -- the path held under `site/src/`, the file a regular file
with no symlink above it, and the CSS text that loads nothing from another host (moved out of looks.py
unchanged, S1b; R5N-11)."""

import os
import posixpath
import re
import stat
from lookgrammar.errors import LookError
from lookgrammar.slotvalues import safe_url


def check_stylesheet_path(path, where="stylesheets"):
    """A look's stylesheet path, normalised and held under `site/src/` (R5N-11). Returns the normal form."""
    if not isinstance(path, str) or not path:
        raise LookError("%s: a stylesheet path is a non-empty string" % where, fix="write site/src/looks/<name>.css")
    if "\\" in path or "\x00" in path:
        raise LookError("%s: the stylesheet path %r holds a backslash" % (where, path), fix="use forward slashes")
    if path.startswith("/"):
        raise LookError("%s: the stylesheet path %r starts with '/'" % (where, path), fix="start it with site/src/")
    if ".." in path.split("/"):
        raise LookError("%s: the stylesheet path %r climbs out of its folder with '..'" % (where, path), fix="name the file under site/src/")
    norm = posixpath.normpath(path)
    if norm != path or not norm.startswith("site/src/") or not norm.endswith(".css") or norm == "site/src/":
        raise LookError("%s: the stylesheet path %r is not a normalised site/src/**.css path" % (where, path),
                        fix="write it as site/src/looks/<name>.css")
    return norm


def check_stylesheet_file(root, rel, where="stylesheets"):
    """The file a `stylesheets` path names must exist under `root` as a regular file, never a symlink, with
    no symlink among the folders above it (R5N-11)."""
    norm = check_stylesheet_path(rel, where)
    cur = root
    for part in norm.split("/"):
        cur = os.path.join(cur, part)
        try:
            st = os.lstat(cur)
        except OSError:
            raise LookError("%s: %s does not exist" % (where, norm), fix="add the file, or remove it from stylesheets")
        if stat.S_ISLNK(st.st_mode):
            raise LookError("%s: %s goes through a symlink" % (where, norm), fix="make it a regular file")
    if not stat.S_ISREG(os.lstat(cur).st_mode):
        raise LookError("%s: %s is not a regular file" % (where, norm), fix="make it a regular file")
    return norm


_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_CSS_STRING = re.compile(r"\"(?:[^\"\\\n]|\\.)*\"|'(?:[^'\\\n]|\\.)*'", re.S)
_CSS_URL = re.compile(r"url\(\s*(?:\"([^\"]*)\"|'([^']*)'|([^)\s\"']*))\s*\)", re.I)


def scan_stylesheet(css, where="stylesheet"):
    """Refuse a stylesheet that loads another host's file (R5N-11): `@import`, a `url(...)` or an
    `@font-face src` whose address is not relative, and a CSS escape that could spell one of those past
    this scan. Returns None when clean."""
    text = _CSS_COMMENT.sub("", css)
    for m in _CSS_URL.finditer(text):
        arg = next(g for g in m.groups() if g is not None) if any(g is not None for g in m.groups()) else ""
        if "\\" in arg:
            raise LookError("%s: a url(%s) holds a backslash, which could hide a scheme" % (where, arg[:40]), fix="write the address plainly")
        try:
            safe_url(arg, relative_only=True)
        except LookError as e:
            raise LookError("%s: url(%s) is refused: %s" % (where, arg[:40], e), fix="use a file the site carries, by a relative path")
    bare = _CSS_STRING.sub('""', text)
    if re.search(r"@import", bare, re.I):
        raise LookError("%s: @import loads another file" % where, fix="link the stylesheet from the layout instead")
    if "\\" in bare:
        raise LookError("%s: a CSS escape outside a string could spell @import or url(" % where,
                        fix="write the rule without an escape")
    return None
