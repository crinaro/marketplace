"""docx_package: the Word file as a zip package — read its document part, splice byte ranges into it, write it back
with every other part kept, back up the file a write replaces, and replace it only if it is still the file that was
scanned (design-resume-docx.md §3.4, §4.1; B9; §R2 M2-6, M2-8, M2-9).

**The invariant, and its measure** (M2-6): a rewrite changes one part. For every other part `zf.read(name)` is equal,
and so are `filename`, the order of entries, `compress_type`, `date_time`, `extra` and `external_attr`
(`differences()` is the measure, and `rewrite_part()` checks its own output with it before returning). Inside the
rewritten part every byte outside the edit list is kept (`splice()`). **Not preserved:** the compressed bytes (Python's
zlib recompresses a stream another writer made) and `flag_bits`; the file's sha256 changes on every write.

**Backups** (§3.4, M2-8): before a write replaces the managed file, its bytes are copied to
`<stem>.before-<op>-<YYYYMMDD-HHMMSS>.docx` beside it, `<op>` one of `update`, `keep`, `fresh`. A backup is never
overwritten: a second backup in the same second takes `-2`, `-3`, ... after the stamp. `prune_update_backups()` keeps
a variant's ten newest `before-update` files and deletes older ones, matching that exact name pattern only; a
`before-keep` or `before-fresh` file is never deleted.

**R12's seam** (M2-9): `replace_file(tmp, target, expect_sha256, rehash=sha256_file)` re-hashes the target and
replaces it only when the hash is the one the scan saw; a test passes a `rehash` that changes the target first. The
window between that hash and `os.replace` stays open: R12 narrows the race and does not close it.

Refused, nothing written (`PackageRefusal`, with the design's rule id): R8 (not a zip, no `word/document.xml`, a
duplicate entry name, a part over 5 MB), R12 (the target changed since the scan), and an edit list that overlaps
itself, leaves the part, or touches a protected range. Capability module. Python 3.9+, standard library only."""

import datetime
import hashlib
import io
import os
import re
import tempfile
import zipfile

PART = "word/document.xml"
MAX_BYTES = 5 * 1024 * 1024
BACKUP_OPS = ("update", "keep", "fresh")
KEEP_UPDATE_BACKUPS = 10
_CHUNK = 1 << 16


class PackageRefusal(Exception):
    """A package operation refused with nothing written; `rule` is the design's refusal id, `detail` says why."""

    def __init__(self, rule, detail):
        Exception.__init__(self, "%s: %s" % (rule, detail))
        self.rule = rule
        self.detail = detail


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    """The sha256 of a file's bytes, read in chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _open_zip(docx_bytes):
    try:
        zf = zipfile.ZipFile(io.BytesIO(docx_bytes))
    except (zipfile.BadZipFile, OSError, ValueError) as e:
        raise PackageRefusal("R8", "not a readable zip (%s)" % type(e).__name__)
    names = [i.filename for i in zf.infolist()]
    if len(set(names)) != len(names):
        zf.close()
        raise PackageRefusal("R8", "the zip holds a duplicate entry name")
    return zf


def read_part(docx_bytes, name=PART):
    """The decompressed bytes of one part (default `word/document.xml`), or raises `PackageRefusal` (R8)."""
    with _open_zip(docx_bytes) as zf:
        try:
            info = zf.getinfo(name)
        except KeyError:
            raise PackageRefusal("R8", "the zip has no %s, so it is not a Word document" % name)
        if info.file_size > MAX_BYTES:
            raise PackageRefusal("R8", "%s unpacks to %d bytes, more than %d" % (name, info.file_size, MAX_BYTES))
        try:
            return zf.read(info)
        except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError) as e:
            raise PackageRefusal("R8", "%s cannot be read (%s)" % (name, type(e).__name__))


def splice(data, edits, protected=()):
    """`data` with each `(start, end, new_bytes)` of `edits` replacing `data[start:end]`; every other byte kept.

    Offsets are into the original `data`. Refused (rule `splice`): an edit out of range or reversed, two edits that
    overlap (two insertions at one offset count as overlapping: their order would be a guess), or an edit that
    overlaps a `protected` range (an insertion strictly inside one counts)."""
    n = len(data)
    ordered = sorted(edits, key=lambda e: (e[0], e[1]))
    prev_end = -1
    prev_start = -1
    for start, end, new in ordered:
        if not (0 <= start <= end <= n):
            raise PackageRefusal("splice", "edit %d:%d is outside the part (0:%d)" % (start, end, n))
        if not isinstance(new, (bytes, bytearray)):
            raise PackageRefusal("splice", "edit %d:%d carries %s, not bytes" % (start, end, type(new).__name__))
        if start < prev_end or start == prev_start:
            raise PackageRefusal("splice", "edit %d:%d overlaps the edit before it" % (start, end))
        for ps, pe in protected:
            hit = (ps < start < pe) if start == end else (start < pe and end > ps)
            if hit:
                raise PackageRefusal("splice", "edit %d:%d touches the protected range %d:%d" % (start, end, ps, pe))
        prev_end = end
        prev_start = start
    out = []
    pos = 0
    for start, end, new in ordered:
        out.append(data[pos:start])
        out.append(bytes(new))
        pos = end
    out.append(data[pos:])
    return b"".join(out)


def _copy_info(info):
    z = zipfile.ZipInfo(info.filename, info.date_time)
    z.compress_type = info.compress_type
    z.comment = info.comment
    z.extra = info.extra
    z.create_system = info.create_system
    z.create_version = info.create_version
    z.extract_version = info.extract_version
    z.internal_attr = info.internal_attr
    z.external_attr = info.external_attr
    return z


def rewrite_part(docx_bytes, new_part, name=PART):
    """The package `docx_bytes` with part `name` replaced by `new_part` and every other entry kept by the M2-6
    measure (`differences()`); checked before it is returned."""
    if len(new_part) > MAX_BYTES:
        raise PackageRefusal("R8", "the rewritten %s would be %d bytes, more than %d"
                             % (name, len(new_part), MAX_BYTES))
    buf = io.BytesIO()
    with _open_zip(docx_bytes) as src:
        if name not in src.namelist():
            raise PackageRefusal("R8", "the zip has no %s, so it is not a Word document" % name)
        with zipfile.ZipFile(buf, "w") as dst:
            dst.comment = src.comment
            for info in src.infolist():
                payload = new_part if info.filename == name else src.read(info)
                dst.writestr(_copy_info(info), payload)
    out = buf.getvalue()
    diffs = differences(docx_bytes, out, rewritten=name)
    if diffs:
        raise PackageRefusal("package", "the rewrite broke the package invariant: %s" % "; ".join(diffs))
    return out


def differences(before, after, rewritten=PART):
    """The M2-6 measure: a list of what differs between two packages outside the part `rewritten` (empty means the
    invariant holds). Compared: the entry order and names; per entry `compress_type`, `date_time`, `extra`,
    `external_attr`; and, for every entry but `rewritten`, the decompressed bytes."""
    out = []
    with _open_zip(before) as a, _open_zip(after) as b:
        ia, ib = a.infolist(), b.infolist()
        if [i.filename for i in ia] != [i.filename for i in ib]:
            return ["the entries or their order differ"]
        for x, y in zip(ia, ib):
            for field in ("compress_type", "date_time", "extra", "external_attr"):
                if getattr(x, field) != getattr(y, field):
                    out.append("%s: %s differs" % (x.filename, field))
            if x.filename != rewritten and a.read(x) != b.read(y):
                out.append("%s: content differs" % x.filename)
    return out


_STAMP = "%Y%m%d-%H%M%S"


def _backup_re(stem, op):
    return re.compile(r"^%s\.before-%s-(\d{8}-\d{6})(?:-(\d+))?\.docx$" % (re.escape(stem), re.escape(op)))


def _stem(target):
    base = os.path.basename(target)
    return base[:-5] if base.lower().endswith(".docx") else base


def write_backup(target, op, now=None):
    """Copy the target's bytes to `<stem>.before-<op>-<YYYYMMDD-HHMMSS>.docx` beside it, never overwriting a backup
    (a taken name gets `-2`, `-3`, ...). Returns the backup's path. `now` is injectable for tests."""
    if op not in BACKUP_OPS:
        raise ValueError("backup op %r is not one of %s" % (op, ", ".join(BACKUP_OPS)))
    with open(target, "rb") as f:
        data = f.read()
    stamp = (now or datetime.datetime.now()).strftime(_STAMP)
    folder = os.path.dirname(os.path.abspath(target))
    base = "%s.before-%s-%s" % (_stem(target), op, stamp)
    n = 1
    while True:
        path = os.path.join(folder, base + (".docx" if n == 1 else "-%d.docx" % n))
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            n += 1
            continue
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        return path


def backups(target, op):
    """The target's `before-<op>` backups beside it, oldest first (by stamp, then by `-N`)."""
    folder = os.path.dirname(os.path.abspath(target))
    pat = _backup_re(_stem(target), op)
    found = []
    for name in os.listdir(folder):
        m = pat.match(name)
        if m:
            found.append((m.group(1), int(m.group(2) or 1), os.path.join(folder, name)))
    return [p for _s, _n, p in sorted(found)]


def prune_update_backups(target, keep=KEEP_UPDATE_BACKUPS):
    """Delete all but the `keep` newest `before-update` backups of the target; returns the deleted paths. Only the
    exact `before-update` name pattern is touched: `before-keep` and `before-fresh` files are kept for ever."""
    old = backups(target, "update")
    gone = old[:-keep] if keep > 0 else old
    for path in gone:
        os.remove(path)
    return gone


def write_temp(target, data):
    """Write `data` to a new temporary file beside the target (same directory, so `os.replace` is atomic), fsynced.
    Returns its path; the name starts with `.` and ends `.tmp`, so no resume-directory glob reads it as a variant."""
    folder = os.path.dirname(os.path.abspath(target))
    fd, path = tempfile.mkstemp(dir=folder, prefix="." + os.path.basename(target) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        _discard(path)
        raise
    return path


def _discard(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def replace_file(tmp, target, expect_sha256, rehash=sha256_file):
    """Replace `target` with `tmp` (R12) only if the target is still the file the scan saw: `expect_sha256` is its
    hash then, or None when there was no file. `rehash` is the seam (M2-9). On refusal `tmp` is removed and the
    target is untouched. The window between the re-hash and `os.replace` stays open: this narrows the race."""
    exists = os.path.lexists(target)
    if expect_sha256 is None:
        if exists:
            _discard(tmp)
            raise PackageRefusal("R12", "%s appeared since the scan; run it again" % os.path.basename(target))
    else:
        actual = rehash(target) if exists else None
        if actual != expect_sha256:
            _discard(tmp)
            raise PackageRefusal("R12", "%s changed since the scan (%s); run it again"
                                 % (os.path.basename(target), "now missing" if actual is None else "bytes differ"))
    os.replace(tmp, target)
