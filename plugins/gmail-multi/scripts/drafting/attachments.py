"""The `attachments` argument of `gmail_create_draft`: which files a draft may carry, read once and attached.

docs/design-resume-docx.md §7.2 (gmail-multi 0.6.0). A list of absolute paths, at most `MAX_FILES`. Each
must be an existing regular file that is not a symlink, named `.docx` or `.pdf` with bytes that agree (a
zip holding `[Content_Types].xml` and `word/document.xml`, or a `%PDF-` start), at most `MAX_FILE_BYTES`,
and all of them together at most `MAX_TOTAL_BYTES` (OURS, because a resume is kilobytes). A refusal raises
`AttachmentRefused` naming the file and the rule, and the caller has built nothing: `load` runs before the
mailbox is opened, so a refused call makes no draft at all.

WHAT THE RULES ARE WORTH. They refuse files that are not documents. Any `.docx` or `.pdf` on disk passes,
one saved from inbound mail included (design O26).

ONE READ PER FILE. `load` reads each file once (`_read_bytes`) and keeps the bytes: the bytes it sniffs,
hashes and counts are the bytes `attach` puts in the message, so the `attached` line (`drafting/
attached_line.py`) describes what was attached, never a later copy of the file.

SYMLINKS. The path's last component may not be a symlink (checked with `lstat`, and the read opens with
`O_NOFOLLOW` where the platform has it). A symlinked parent directory is not refused: macOS's `/tmp` and
`/var` are symlinks.

Capability module: no `__main__`, nothing runs at import. Standard library only. Python 3.9+.
"""

import hashlib
import io
import os
import stat
import zipfile
from collections import namedtuple

from drafting import attached_line

MAX_FILES = 5
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 10 * 1024 * 1024
MIME = {".docx": ("application", "vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ".pdf": ("application", "pdf")}
DOCX_MEMBERS = ("[Content_Types].xml", "word/document.xml")
PDF_MAGIC = b"%PDF-"

Part = namedtuple("Part", "path basename maintype subtype data sha256 line")


class AttachmentRefused(ValueError):
    """A file the draft may not carry. The message names the file and the rule; no draft was made."""


def _refuse(path, rule):
    raise AttachmentRefused("attachments refused, no draft was created: %s: %s" % (path, rule))


def _read_bytes(path):
    """The file's bytes, read once, refusing to follow a symlink where the platform allows."""
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as fh:
        return fh.read(MAX_FILE_BYTES + 1)


def _checked_path(path):
    """`(extension, size on disk)` of one path that passes the path, type-by-name and size rules."""
    if not isinstance(path, str) or not path:
        _refuse(repr(path), "each attachment must be a path given as a string")
    if not os.path.isabs(path):
        _refuse(path, "the path must be absolute")
    try:
        st = os.lstat(path)
    except OSError:
        _refuse(path, "the path must be an existing regular file (it does not exist)")
    if stat.S_ISLNK(st.st_mode):
        _refuse(path, "the path must be an existing regular file (it is a symlink)")
    if not stat.S_ISREG(st.st_mode):
        _refuse(path, "the path must be an existing regular file (it is not a regular file)")
    ext = os.path.splitext(path)[1].lower()
    if ext not in MIME:
        _refuse(path, "the type must be .docx or .pdf")
    if st.st_size > MAX_FILE_BYTES:
        _refuse(path, "over %d bytes for one file" % MAX_FILE_BYTES)
    return ext, st.st_size


def _sniffed(path, ext, data):
    """Refuse bytes that do not agree with the extension."""
    if len(data) > MAX_FILE_BYTES:
        _refuse(path, "over %d bytes for one file" % MAX_FILE_BYTES)
    if ext == ".pdf":
        if not data.startswith(PDF_MAGIC):
            _refuse(path, "the type must agree with the bytes (a .pdf starts with %PDF-)")
        return
    try:
        names = set(zipfile.ZipFile(io.BytesIO(data)).namelist())
    except (zipfile.BadZipFile, ValueError, OSError):
        names = set()
    if not all(m in names for m in DOCX_MEMBERS):
        _refuse(path, "the type must agree with the bytes (a .docx is a zip holding %s)" % " and ".join(DOCX_MEMBERS))


def load(paths):
    """Every file of the `attachments` argument as a `Part`, or `AttachmentRefused` and nothing read past it.

    `None` or an empty list is no attachment: `[]`. Every path is checked before any file is read."""
    if paths is None:
        return []
    if not isinstance(paths, list):
        _refuse(repr(paths), "`attachments` must be a list of absolute paths")
    if len(paths) > MAX_FILES:
        _refuse("%d files" % len(paths), "more than %d attachments" % MAX_FILES)
    checked = [(p,) + _checked_path(p) for p in paths]
    if sum(size for _p, _e, size in checked) > MAX_TOTAL_BYTES:
        _refuse(", ".join(paths), "over %d bytes together" % MAX_TOTAL_BYTES)
    parts = []
    for path, ext, _size in checked:
        try:
            data = _read_bytes(path)
        except OSError as exc:
            _refuse(path, "the path must be an existing regular file (it could not be read: %s)" % exc.strerror)
        _sniffed(path, ext, data)
        basename = os.path.basename(path)
        digest = hashlib.sha256(data).hexdigest()
        try:
            line = attached_line.format_line(digest, len(data), basename)
        except ValueError:
            _refuse(path, "the file name must be one line")
        parts.append(Part(path, basename, MIME[ext][0], MIME[ext][1], data, digest, line))
    if sum(len(p.data) for p in parts) > MAX_TOTAL_BYTES:
        _refuse(", ".join(paths), "over %d bytes together" % MAX_TOTAL_BYTES)
    return parts


def attach(msg, parts):
    """Add each part to `msg` (an `EmailMessage` whose body is set), which makes it `multipart/mixed`."""
    for p in parts:
        msg.add_attachment(p.data, maintype=p.maintype, subtype=p.subtype, filename=p.basename)
    return msg


def result_lines(parts):
    """The `attached` lines for the tool's result, one per part, in order."""
    return [p.line for p in parts]
