"""plan.py -- the size-copy plan and the names an import writes: widths, caps, copy names, the job a resizer receives and the result an import returns.

Moved out of images.py unchanged (S1b, dev 939); the interface and the design notes are in images.py."""

import os
import re
from imaging.errors import ImageError


SIZE_WIDTHS = (480, 720, 960, 1200, 1440)
LONG_EDGE_CAP = 2000
MIN_COPY_GAP = 100
SOURCE_EXTS = {"jpeg": ".jpg", "png": ".png", "webp": ".webp", "gif": ".gif"}
_COPY_STEM_RE = re.compile(r"-\d+w$")


def display_size(width, height, orientation):
    """Displayed (upright) size of a stored width x height image with an EXIF orientation."""
    return (height, width) if orientation in (5, 6, 7, 8) else (width, height)


def capped_size(w, h, cap=LONG_EDGE_CAP):
    if max(w, h) <= cap:
        return (w, h)
    s = cap / float(max(w, h))
    return (max(1, int(round(w * s))), max(1, int(round(h * s))))


def plan_copies(main_width, nbytes, size_copy_over_kb=250):
    """Widths of the size copies an upright original of `main_width` and `nbytes` needs."""
    if nbytes <= size_copy_over_kb * 1024:
        return []
    return [w for w in SIZE_WIDTHS if w <= main_width - MIN_COPY_GAP]


def copy_name(path, width):
    stem, ext = os.path.splitext(path)
    return "%s-%dw%s" % (stem, width, ext)


class ResizeJob(object):
    def __init__(self, data, fmt, orientation, width, height, main_size, copy_widths, cap):
        self.data, self.fmt, self.orientation = data, fmt, orientation
        self.width, self.height = width, height
        self.main_size, self.copy_widths, self.cap = main_size, list(copy_widths), cap


class ImportResult(object):
    def __init__(self):
        self.path = None
        self.copies = []
        self.width = self.height = 0
        self.orientation_applied = 1
        self.fmt = None
        self.bytes = 0
        self.stripped = 0
        self.converted_from = None
        self.used_resizer = False
        self.notes = []


def clean_stem(name):
    stem = os.path.splitext(os.path.basename(name))[0]
    stem = re.sub(r"\s+", "-", stem.strip())
    stem = re.sub(r"[^A-Za-z0-9._-]", "", stem).strip(".-_")
    return stem or "image"


def resolve_dest(src, dest, fmt):
    ext = SOURCE_EXTS[fmt]
    if dest.endswith(("/", os.sep)) or os.path.isdir(dest):
        path = os.path.join(dest, clean_stem(src) + ext)
    else:
        stem, given = os.path.splitext(dest)
        keep = given.lower() in (".jpg", ".jpeg") if fmt == "jpeg" else given.lower() == ext
        path = dest if keep else stem + ext
    if _COPY_STEM_RE.search(os.path.splitext(os.path.basename(path))[0]):
        raise ImageError("the name %r ends -<width>w, the size-copy naming; pick another name"
                         % os.path.basename(path))
    return path
