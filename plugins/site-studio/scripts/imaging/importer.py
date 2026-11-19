"""importer.py -- import_media: read, strip, bake the orientation through the resizer, vet what comes back, write the original and its size copies.

Moved out of images.py unchanged (S1b, dev 939); the interface and the design notes are in images.py."""

import os
import sys
from imaging.errors import ImageError
from imaging.exif import read_orientation
from imaging.plan import (
    ImportResult,
    LONG_EDGE_CAP,
    ResizeJob,
    capped_size,
    copy_name,
    display_size,
    plan_copies,
    resolve_dest,
)
from imaging.sips import _convert_with_sips
from imaging.sniff import detect_format, read_dimensions
from imaging.strip import strip_metadata


def _vet(blob, fmt, want_w, want_h, what, tol=1):
    """Validate one resizer output and return it stripped. Never trusted: right format, upright
    (no orientation tag other than 1), stripped again as a defence, and the expected dimensions."""
    if not isinstance(blob, (bytes, bytearray)) or detect_format(bytes(blob)) != fmt:
        raise ImageError("the resizer returned the wrong format for the %s (need %s)" % (what, fmt))
    blob = bytes(blob)
    if read_orientation(blob) != 1:
        raise ImageError("the resizer's %s still carries an orientation tag; it must be upright "
                         "with none" % what)
    blob = strip_metadata(blob)
    dims = read_dimensions(blob)
    if dims is None:
        raise ImageError("the resizer returned an unreadable %s" % what)
    if abs(dims[0] - want_w) > tol or abs(dims[1] - want_h) > tol:
        if want_w != want_h and abs(dims[0] - want_h) <= tol and abs(dims[1] - want_w) <= tol:
            raise ImageError("the resizer did not apply the orientation: the %s is %dx%d, "
                             "expected the upright %dx%d" % (what, dims[0], dims[1], want_w, want_h))
        raise ImageError("the resizer returned a %s of %dx%d, expected %dx%d"
                         % (what, dims[0], dims[1], want_w, want_h))
    return blob


def import_media(src, dest, resizer, platform=None, sips=None, overwrite=False,
                 size_copy_over_kb=250):
    platform = platform or sys.platform
    try:
        with open(src, "rb") as fh:
            raw = fh.read()
    except OSError as e:
        raise ImageError("cannot read %s: %s; check that the file exists and can be opened, then import it again" % (src, e.strerror or e))
    res = ImportResult()
    fmt = detect_format(raw)
    if fmt in ("heic", "tiff"):
        raw = _convert_with_sips(src, fmt, platform, sips)
        res.converted_from = fmt
        res.notes.append("converted from %s to JPEG with sips" % fmt.upper())
        fmt = "jpeg"
    if fmt is None:
        raise ImageError("%s is not an image this plugin imports (JPEG, PNG, WebP, GIF, or HEIC/TIFF "
                         "on a Mac); convert it to one of those first" % os.path.basename(src))
    # 1. READ the orientation from the source, BEFORE anything is stripped (M12(b))
    orientation = read_orientation(raw)
    # 2. strip
    clean = strip_metadata(raw)
    res.stripped = len(raw) - len(clean)
    dims = read_dimensions(clean)
    if dims is None or dims[0] < 1 or dims[1] < 1:
        raise ImageError("cannot read the dimensions of %s" % os.path.basename(src))
    w, h = dims
    dw, dh = display_size(w, h, orientation)
    main_w, main_h = capped_size(dw, dh)
    path = resolve_dest(src, dest, fmt)
    if os.path.exists(path) and not overwrite:
        raise ImageError("%s already exists; not overwritten; delete or rename it, or choose another name" % path)
    # 3. decide what needs pixels
    needs_main = orientation != 1 or (main_w, main_h) != (dw, dh)
    est_bytes = len(clean) if not needs_main else len(clean) * (main_w * main_h) // max(1, w * h)
    copy_widths = plan_copies(main_w, est_bytes, size_copy_over_kb)
    main_blob = clean
    copies = {}
    if needs_main or copy_widths:
        if resizer is None:
            why = ("its orientation is %d (it would come out sideways)" % orientation
                   if orientation != 1 else
                   "it is %d px wide and %d KB" % (main_w, est_bytes // 1024))
            raise ImageError("%s needs the resize step, which needs Chrome: %s. Run setup to find "
                             "Chrome, then import again" % (os.path.basename(src), why))
        job = ResizeJob(clean, fmt, orientation, w, h, (main_w, main_h), copy_widths, LONG_EDGE_CAP)
        out = resizer(job)
        if not isinstance(out, dict):
            raise ImageError("the resizer must return {'main': bytes|None, 'copies': {width: bytes}}")
        res.used_resizer = True
        got_main = out.get("main")
        if needs_main and not got_main:
            raise ImageError("the resizer returned no upright original but one is required")
        if got_main:
            main_blob = _vet(got_main, fmt, main_w, main_h, "original")
        got_copies = out.get("copies") or {}
        for cw in copy_widths:
            blob = got_copies.get(cw)
            if blob is None:
                raise ImageError("the resizer returned no %dw copy" % cw)
            ch = max(1, int(round(cw * main_h / float(main_w))))
            copies[cw] = _vet(blob, fmt, cw, ch, "%dw copy" % cw)
        extra = sorted(set(got_copies) - set(copy_widths))
        if extra:
            raise ImageError("the resizer returned copies that were not asked for: %s"
                             % ", ".join("%dw" % x for x in extra))
        res.orientation_applied = orientation
        if got_main:
            main_w2, main_h2 = read_dimensions(main_blob)
        else:
            main_w2, main_h2 = main_w, main_h
    else:
        main_w2, main_h2 = w, h
    # 4. write, atomically per file; nothing is left half-written on failure
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    written = []
    tmp = None
    try:
        plan = [(path, main_blob)] + [(copy_name(path, cw), copies[cw]) for cw in sorted(copies)]
        for target, blob in plan:
            existed = os.path.exists(target)
            tmp = target + ".part"
            with open(tmp, "wb") as fh:
                fh.write(blob)
            os.replace(tmp, target)
            tmp = None
            if not existed:
                written.append(target)
    except OSError as e:
        for t in written + ([tmp] if tmp else []):
            try:
                os.remove(t)
            except OSError:
                pass
        raise ImageError("could not write %s: %s; check that the folder can be written to and the disk has room, then import again" % (path, e.strerror or e))
    res.path = path
    res.copies = [copy_name(path, cw) for cw in sorted(copies)]
    res.width, res.height = main_w2, main_h2
    res.fmt = fmt
    res.bytes = len(main_blob)
    return res
