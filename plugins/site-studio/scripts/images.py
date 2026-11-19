#!/usr/bin/env python3
"""images.py -- image import for site-studio: strip hidden metadata, read dimensions, plan size
copies (dev #835; design sections 5.3, 10; named change M12(b)). Python 3.9, stdlib only, and NO
browser: pixels are never decoded or drawn here. The drawing is a RESIZER the caller passes in
(phase 2's resize.py draws into a Chrome canvas; phase-1 tests pass a fake). Importing is done once,
at import time; the build never touches an image (it only copies files and reads their headers).

THE INTERFACE (design 10)
    import_media(src, dest, resizer, *, platform=None, sips=None, overwrite=False,
                 size_copy_over_kb=250) -> ImportResult

  src       a file path. JPEG, PNG, WebP and GIF are imported; HEIC and TIFF are converted to JPEG
            with `sips` first on a Mac and REFUSED elsewhere, saying why; anything else is refused.
  dest      a directory (the file name is derived from the source stem and cleaned) or a file path.
            The extension is corrected to the real format. A stem already ending `-<digits>w` is
            refused: that is the size-copy naming and would be mistaken for one.
  resizer   `resizer(job) -> {"main": bytes or None, "copies": {width: bytes}}`, called ONLY when
            work needs pixels: the orientation is not upright, the long edge is over LONG_EDGE_CAP
            (2000), or size copies are needed. `job` is a ResizeJob (attributes below). It may be
            None for an image that needs no pixels done; one that does then raises ImageError naming
            the Chrome step. Whatever the resizer returns is VALIDATED, never trusted: right
            format, right dimensions, no metadata, and no orientation tag.
  returns   ImportResult: .path .copies .width .height .orientation_applied .fmt .bytes
            .stripped .converted_from .used_resizer .notes. width/height are the FINAL upright
            dimensions of the written original.

ResizeJob: .data (metadata-stripped source bytes, EXIF orientation NOT applied to the pixels) .fmt
('jpeg'|'png'|'webp'|'gif') .orientation (1..8, EXIF numbering) .width .height (stored) .main_size
(w, h) the upright, capped size the written original must have .copy_widths (list of ints) .cap.

ORIENTATION (named change M12(b)) -- THE ORDER IS: READ, THEN STRIP, THEN THE RESIZER APPLIES.
EXIF Orientation is read from the SOURCE before any metadata is removed, because stripping it first
makes a portrait phone photo come out sideways. Orientation is a pixel operation, and no decoder
exists in the standard library, so this module does not pretend to do it: it records the value,
strips the tag, and hands the value to the resizer as `job.orientation` with the instruction that
`main` and every copy come back UPRIGHT (rotated or flipped into the pixels) with no orientation tag
at all. The choice, stated once: ORIENTATION IS BAKED INTO THE PIXELS AND THE TAG IS DROPPED, so the
published file has the same appearance in every viewer and the header dimensions the build reads for
width/height attributes are the displayed ones. For orientations 5 to 8 the displayed width and
height are the stored height and width, and `main_size` already reflects that. After the resizer
returns, the dimensions are checked against `main_size`: a resizer that ignored the orientation
(output still stored-shaped) is refused ("did not apply the orientation"), so a sideways image cannot
be imported silently. (Limit: a SQUARE image cannot show that mistake in its dimensions; the contract
is the resizer's, and phase 2's real-Chrome tests own the pixel check.) An image that is already
upright (orientation 1 or absent), within the cap and small enough needs no resizer and keeps its
stripped bytes. HEIC/TIFF: whether sips bakes the rotation into the JPEG it writes or leaves an EXIF
tag is UNDETERMINED here, and either is handled, because orientation is re-read from the converted
JPEG before it is stripped.

WHAT IS STRIPPED (byte rewriting, ported in spirit from the examples' strip step)
  JPEG: every APPn and COM segment except a JFIF APP0 (its embedded thumbnail removed), an ICC
        profile in APP2 (colour, not identity) and an Adobe APP14 (the colour transform); all bytes
        after EOI (MPF secondary images and gain maps ride there).
  PNG:  tEXt, zTXt, iTXt, eXIf, tIME and every unknown ancillary chunk; everything after IEND.
  WebP: EXIF and XMP chunks (the VP8X flags cleared and the RIFF size rewritten).
  GIF:  comment, plain-text and application extensions other than the NETSCAPE/ANIMEXTS loop.

SIZE COPIES (the convention every later phase follows)
  `<stem>-<width>w.<ext>` beside the original, in the same folder, same format as the original. The
  widths come from SIZE_WIDTHS (480, 720, 960, 1200, 1440), only those at least 100 px narrower than
  the final original, and only when the written original is larger than `size_copy_over_kb` (the
  `sizeCopyOverKB` budget of site.json, default 250) -- an image over the budget needs copies.

inspect_metadata(data) is the READ side, shared with check_site.py's privacy family: it names what
hidden metadata a finished image still carries (gps, owner, serial, exif, xmp, iptc, comment, text,
time, thumbnail), so the gate and the stripper agree on what hidden means.

WHERE THE CODE IS (S1b, dev 939). This file is the command line (`images.py info <file>`, `images.py import <src>
<dest>`); the functions live in the package imaging/: errors (ImageError), sniff (format, dimensions), jpeg, png,
webp, gif (one stripper each), exif (orientation, inspect_metadata), strip (strip_metadata), plan (size copies and
names), sips (HEIC and TIFF), importer (import_media). Nothing imports this file.
"""
import sys

from imaging.errors import ImageError
from imaging.exif import inspect_metadata, read_orientation
from imaging.importer import import_media
from imaging.sniff import detect_format, read_dimensions


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) == 2 and argv[0] == "info":
        with open(argv[1], "rb") as fh:
            data = fh.read()
        fmt = detect_format(data)
        print("format: %s" % fmt)
        print("stored size: %s" % (read_dimensions(data),))
        print("orientation: %d" % read_orientation(data))
        meta = inspect_metadata(data)
        print("metadata: %s" % (", ".join(sorted(set(k for k, _d in meta))) or "none"))
        return 0
    if len(argv) == 3 and argv[0] == "import":
        try:
            r = import_media(argv[1], argv[2], None)
        except ImageError as e:
            print("import refused: %s" % e)
            return 1
        print("imported: %s (%dx%d, %s)" % (r.path, r.width, r.height, r.fmt))
        return 0
    print("usage: images.py info <file> | images.py import <src> <dest>")
    return 2


if __name__ == "__main__":
    sys.exit(main())
