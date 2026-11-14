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
"""
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile

SIZE_WIDTHS = (480, 720, 960, 1200, 1440)
LONG_EDGE_CAP = 2000
MIN_COPY_GAP = 100
SOURCE_EXTS = {"jpeg": ".jpg", "png": ".png", "webp": ".webp", "gif": ".gif"}
_COPY_STEM_RE = re.compile(r"-\d+w$")


class ImageError(ValueError):
    """Every refusal. The message is one line saying what and why."""


# ---------------------------------------------------------------------------------------------
# format and dimensions
# ---------------------------------------------------------------------------------------------

def detect_format(data):
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[4:8] == b"ftyp" and data[8:12] in (b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1",
                                                 b"heim", b"heis"):
        return "heic"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    return None


def read_dimensions(data):
    """(width, height) as STORED in the file header, or None. No decoding."""
    fmt = detect_format(data)
    try:
        if fmt == "png":
            if data[12:16] == b"IHDR":
                return struct.unpack(">II", data[16:24])
        elif fmt == "gif":
            return struct.unpack("<HH", data[6:10])
        elif fmt == "jpeg":
            for marker, _start, seg in _jpeg_segments(data):
                if marker in _SOF and len(seg) >= 7:
                    h, w = struct.unpack(">HH", seg[3:7])
                    return (w, h)
        elif fmt == "webp":
            for typ, body in _riff_chunks(data):
                if typ == b"VP8X" and len(body) >= 10:
                    return (1 + int.from_bytes(body[4:7], "little"),
                            1 + int.from_bytes(body[7:10], "little"))
                if typ == b"VP8 " and len(body) >= 10:
                    w, h = struct.unpack("<HH", body[6:10])
                    return (w & 0x3FFF, h & 0x3FFF)
                if typ == b"VP8L" and len(body) >= 5:
                    bits = int.from_bytes(body[1:5], "little")
                    return ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
    except (struct.error, IndexError, ValueError):
        return None
    return None


# ---------------------------------------------------------------------------------------------
# JPEG
# ---------------------------------------------------------------------------------------------

_SOF = frozenset([0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF])


def _jpeg_segments(data):
    """Yield (marker, start, payload_including_length) for each marker segment up to SOS/EOI.
    Entropy data is not yielded. Raises ImageError on structural damage."""
    n = len(data)
    i = 2
    while i < n:
        if data[i] != 0xFF:
            raise ImageError("JPEG is damaged (expected a marker at byte %d)" % i)
        while i < n and data[i] == 0xFF:
            i += 1
        if i >= n:
            break
        m = data[i]
        i += 1
        if m == 0xD9:
            return
        if m == 0x01 or 0xD0 <= m <= 0xD8:
            continue
        if i + 2 > n:
            raise ImageError("JPEG is truncated")
        ln = struct.unpack(">H", data[i:i + 2])[0]
        if ln < 2 or i + ln > n:
            raise ImageError("JPEG is truncated")
        yield (m, i - 2, data[i:i + ln])
        i += ln
        if m == 0xDA:
            return


def strip_jpeg(data):
    if data[:2] != b"\xff\xd8":
        raise ImageError("not a JPEG")
    out = bytearray(b"\xff\xd8")
    n = len(data)
    i = 2
    saw_eoi = False
    while i < n:
        if data[i] != 0xFF:
            raise ImageError("JPEG is damaged (expected a marker at byte %d)" % i)
        while i < n and data[i] == 0xFF:
            i += 1
        if i >= n:
            break
        m = data[i]
        i += 1
        if m == 0xD9:
            out += b"\xff\xd9"
            saw_eoi = True
            break
        if m == 0x01 or 0xD0 <= m <= 0xD8:
            out += bytes([0xFF, m])
            continue
        if i + 2 > n:
            raise ImageError("JPEG is truncated")
        ln = struct.unpack(">H", data[i:i + 2])[0]
        if ln < 2 or i + ln > n:
            raise ImageError("JPEG is truncated")
        body = data[i + 2:i + ln]
        keep = True
        if m == 0xE0:
            if body[:5] == b"JFIF\x00" and len(body) >= 14:
                # keep the JFIF header, drop an embedded thumbnail
                body = body[:12] + b"\x00\x00"
            else:
                keep = False
        elif m == 0xE2:
            keep = body[:12] == b"ICC_PROFILE\x00"
        elif m == 0xEE:
            keep = body[:5] == b"Adobe"
        elif 0xE1 <= m <= 0xEF or m == 0xFE:
            keep = False
        if keep:
            out += bytes([0xFF, m]) + struct.pack(">H", len(body) + 2) + body
        i += ln
        if m == 0xDA:
            # entropy-coded data: copy up to the next real marker
            j = i
            while j + 1 < n:
                if data[j] == 0xFF and data[j + 1] != 0x00 and not (0xD0 <= data[j + 1] <= 0xD7) \
                        and data[j + 1] != 0xFF:
                    break
                j += 1
            else:
                j = n
            out += data[i:j]
            i = j
    if not saw_eoi:
        raise ImageError("JPEG has no end-of-image marker")
    return bytes(out)


# ---------------------------------------------------------------------------------------------
# EXIF (TIFF structure) reading, for orientation and for the metadata inspector
# ---------------------------------------------------------------------------------------------

def _tiff_ifd(tiff, off, endian, limit=512):
    """{tag: (type, count, value_or_offset_bytes)} for the IFD at `off`; {} when out of range."""
    out = {}
    if off < 8 or off + 2 > len(tiff):
        return out
    cnt = struct.unpack(endian + "H", tiff[off:off + 2])[0]
    for k in range(min(cnt, limit)):
        e = off + 2 + 12 * k
        if e + 12 > len(tiff):
            break
        tag, typ, count = struct.unpack(endian + "HHI", tiff[e:e + 8])
        out[tag] = (typ, count, tiff[e + 8:e + 12])
    return out


def parse_tiff_exif(tiff):
    """{'orientation': int|None, 'ifd0': set(tags), 'exif': set(tags), 'gps': set(tags)} or None."""
    if tiff[:2] == b"II":
        e = "<"
    elif tiff[:2] == b"MM":
        e = ">"
    else:
        return None
    if len(tiff) < 8 or struct.unpack(e + "H", tiff[2:4])[0] != 42:
        return None
    ifd0_off = struct.unpack(e + "I", tiff[4:8])[0]
    ifd0 = _tiff_ifd(tiff, ifd0_off, e)
    res = {"orientation": None, "ifd0": set(ifd0), "exif": set(), "gps": set()}
    if 0x0112 in ifd0:
        typ, cnt, val = ifd0[0x0112]
        if typ == 3 and cnt >= 1:
            v = struct.unpack(e + "H", val[:2])[0]
            res["orientation"] = v if 1 <= v <= 8 else None
    if 0x8769 in ifd0:
        off = struct.unpack(e + "I", ifd0[0x8769][2])[0]
        res["exif"] = set(_tiff_ifd(tiff, off, e))
    if 0x8825 in ifd0:
        off = struct.unpack(e + "I", ifd0[0x8825][2])[0]
        res["gps"] = set(_tiff_ifd(tiff, off, e)) or {"pointer"}
    return res


def _exif_blocks(data, fmt):
    """The raw TIFF blocks of EXIF found in `data`, and the other hidden-metadata kinds."""
    tiffs, kinds = [], []
    if fmt == "jpeg":
        try:
            for m, _s, seg in _jpeg_segments(data):
                body = seg[2:]
                if m == 0xE1 and body[:6] == b"Exif\x00\x00":
                    tiffs.append(body[6:])
                    kinds.append("exif")
                elif m == 0xE1 and (body[:29] == b"http://ns.adobe.com/xap/1.0/\x00" or b"<x:xmpmeta" in body[:200]):
                    kinds.append("xmp")
                elif m == 0xE1:
                    kinds.append("exif")
                elif m == 0xED:
                    kinds.append("iptc")
                elif m == 0xFE:
                    kinds.append("comment")
                elif m == 0xE0 and body[:5] == b"JFIF\x00" and len(body) >= 14 and (body[12] or body[13]):
                    kinds.append("thumbnail")
                elif m == 0xE0 and body[:4] == b"JFXX":
                    kinds.append("thumbnail")
                elif m == 0xE2 and body[:12] != b"ICC_PROFILE\x00":
                    kinds.append("exif")  # MPF and other APP2 payloads
                elif m in (0xE3, 0xE4, 0xE5, 0xE6, 0xE7, 0xE8, 0xE9, 0xEA, 0xEB, 0xEC, 0xEF):
                    kinds.append("exif")
        except ImageError:
            pass
    elif fmt == "png":
        for typ, body in _png_chunks(data):
            if typ == b"eXIf":
                tiffs.append(body)
                kinds.append("exif")
            elif typ in (b"tEXt", b"zTXt", b"iTXt"):
                kinds.append("text")
            elif typ == b"tIME":
                kinds.append("time")
    elif fmt == "webp":
        for typ, body in _riff_chunks(data):
            if typ == b"EXIF":
                tiffs.append(body[6:] if body[:6] == b"Exif\x00\x00" else body)
                kinds.append("exif")
            elif typ == b"XMP ":
                kinds.append("xmp")
    elif fmt == "gif":
        for label, body in _gif_extensions(data):
            if label == 0xFE:
                kinds.append("comment")
            elif label == 0xFF and not body.startswith((b"NETSCAPE2.0", b"ANIMEXTS1.0")):
                kinds.append("xmp" if body.startswith(b"XMP Data") else "exif")
    return tiffs, kinds


_OWNER_TAGS = {0x013B: "Artist", 0x8298: "Copyright", 0xA430: "CameraOwnerName"}
_SERIAL_TAGS = {0xA431: "BodySerialNumber", 0xA435: "LensSerialNumber", 0xC62F: "CameraSerialNumber"}


def read_orientation(data):
    """EXIF orientation 1..8 of an image, 1 when none or unreadable."""
    fmt = detect_format(data)
    tiffs, _k = _exif_blocks(data, fmt)
    for t in tiffs:
        info = parse_tiff_exif(t)
        if info and info["orientation"]:
            return info["orientation"]
    return 1


def inspect_metadata(data):
    """[(kind, detail)] of hidden metadata still present. Empty list means none was found.
    kinds: gps owner serial exif xmp iptc comment text time thumbnail"""
    fmt = detect_format(data)
    tiffs, kinds = _exif_blocks(data, fmt)
    found = [(k, "%s metadata present" % k) for k in dict.fromkeys(kinds)]
    for t in tiffs:
        info = parse_tiff_exif(t)
        if not info:
            continue
        if info["gps"]:
            found.append(("gps", "EXIF GPS block"))
        for tag, name in _OWNER_TAGS.items():
            if tag in info["ifd0"] or tag in info["exif"]:
                found.append(("owner", "EXIF %s" % name))
        for tag, name in _SERIAL_TAGS.items():
            if tag in info["ifd0"] or tag in info["exif"]:
                found.append(("serial", "EXIF %s" % name))
    return found


# ---------------------------------------------------------------------------------------------
# PNG / WebP / GIF
# ---------------------------------------------------------------------------------------------

def _png_chunks(data):
    i = 8
    n = len(data)
    while i + 8 <= n:
        ln = struct.unpack(">I", data[i:i + 4])[0]
        typ = data[i + 4:i + 8]
        if i + 12 + ln > n:
            return
        yield typ, data[i + 8:i + 8 + ln]
        i += 12 + ln
        if typ == b"IEND":
            return


_PNG_KEEP = frozenset([b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS", b"gAMA", b"cHRM", b"sRGB", b"iCCP",
                       b"sBIT", b"pHYs", b"bKGD", b"hIST", b"acTL", b"fcTL", b"fdAT"])


def strip_png(data):
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ImageError("not a PNG")
    out = bytearray(data[:8])
    i = 8
    n = len(data)
    saw_end = False
    while i + 12 <= n:
        ln = struct.unpack(">I", data[i:i + 4])[0]
        typ = data[i + 4:i + 8]
        if i + 12 + ln > n:
            raise ImageError("PNG is truncated")
        if typ in _PNG_KEEP:
            out += data[i:i + 12 + ln]
        i += 12 + ln
        if typ == b"IEND":
            saw_end = True
            break
    if not saw_end:
        raise ImageError("PNG has no IEND chunk")
    return bytes(out)


def _riff_chunks(data):
    i = 12
    n = len(data)
    while i + 8 <= n:
        typ = data[i:i + 4]
        ln = struct.unpack("<I", data[i + 4:i + 8])[0]
        if i + 8 + ln > n:
            return
        yield typ, data[i + 8:i + 8 + ln]
        i += 8 + ln + (ln & 1)


_WEBP_KEEP = frozenset([b"VP8 ", b"VP8L", b"VP8X", b"ICCP", b"ALPH", b"ANIM", b"ANMF"])


def strip_webp(data):
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise ImageError("not a WebP")
    body = bytearray(b"WEBP")
    for typ, chunk in _riff_chunks(data):
        if typ not in _WEBP_KEEP:
            continue
        if typ == b"VP8X" and len(chunk) >= 1:
            chunk = bytes([chunk[0] & ~0x0C & 0xFF]) + chunk[1:]
        body += typ + struct.pack("<I", len(chunk)) + chunk + (b"\x00" if len(chunk) & 1 else b"")
    return b"RIFF" + struct.pack("<I", len(body)) + bytes(body)


def _gif_blocks(data):
    """Yield (kind, start, end, label, body) walking the block structure after the header."""
    if len(data) < 13:
        raise ImageError("GIF is truncated")
    flags = data[10]
    i = 13 + (3 * (2 << (flags & 7)) if flags & 0x80 else 0)
    n = len(data)
    while i < n:
        b = data[i]
        if b == 0x3B:
            yield ("end", i, i + 1, None, b"")
            return
        if b == 0x21:
            label = data[i + 1]
            j = i + 2
            first = None
            while j < n:
                ln = data[j]
                if first is None:
                    first = data[j + 1:j + 1 + ln]
                j += 1 + ln
                if ln == 0:
                    break
            yield ("ext", i, j, label, first or b"")
            i = j
        elif b == 0x2C:
            if i + 10 > n:
                raise ImageError("GIF is truncated")
            f2 = data[i + 9]
            j = i + 10 + (3 * (2 << (f2 & 7)) if f2 & 0x80 else 0) + 1
            while j < n:
                ln = data[j]
                j += 1 + ln
                if ln == 0:
                    break
            yield ("image", i, j, None, b"")
            i = j
        else:
            raise ImageError("GIF is damaged")
    raise ImageError("GIF has no trailer")


def _gif_extensions(data):
    try:
        for kind, _s, _e, label, body in _gif_blocks(data):
            if kind == "ext":
                yield label, body
    except ImageError:
        return


def strip_gif(data):
    if data[:6] not in (b"GIF87a", b"GIF89a"):
        raise ImageError("not a GIF")
    flags = data[10] if len(data) > 10 else 0
    head_end = 13 + (3 * (2 << (flags & 7)) if flags & 0x80 else 0)
    out = bytearray(data[:head_end])
    for kind, s, e, label, body in _gif_blocks(data):
        if kind == "ext":
            if label == 0xF9 or (label == 0xFF and body.startswith((b"NETSCAPE2.0", b"ANIMEXTS1.0"))):
                out += data[s:e]
        else:
            out += data[s:e]
    return bytes(out)


def strip_metadata(data):
    fmt = detect_format(data)
    if fmt == "jpeg":
        return strip_jpeg(data)
    if fmt == "png":
        return strip_png(data)
    if fmt == "webp":
        return strip_webp(data)
    if fmt == "gif":
        return strip_gif(data)
    raise ImageError("cannot strip metadata from format %r" % fmt)


# ---------------------------------------------------------------------------------------------
# planning
# ---------------------------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------------------------
# HEIC / TIFF
# ---------------------------------------------------------------------------------------------

def _find_sips(platform, sips):
    if sips:
        return sips
    if platform == "darwin":
        return shutil.which("sips") or ("/usr/bin/sips" if os.path.exists("/usr/bin/sips") else None)
    return None


def _convert_with_sips(src, fmt, platform, sips):
    exe = _find_sips(platform, sips)
    if exe is None:
        raise ImageError("%s files can only be converted on a Mac (sips); convert it to JPEG or PNG "
                         "first, or import it from a Mac" % fmt.upper())
    tmp = tempfile.mkdtemp(prefix="ss-sips-")
    try:
        out = os.path.join(tmp, "converted.jpg")
        p = subprocess.run([exe, "-s", "format", "jpeg", src, "--out", out], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)
        if p.returncode != 0 or not os.path.exists(out):
            raise ImageError("sips could not convert the %s file" % fmt.upper())
        with open(out, "rb") as fh:
            data = fh.read()
        if detect_format(data) != "jpeg":
            raise ImageError("sips did not produce a JPEG")
        return data
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------------------------
# the import
# ---------------------------------------------------------------------------------------------

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
        raise ImageError("cannot read %s: %s" % (src, e.strerror or e))
    res = ImportResult()
    fmt = detect_format(raw)
    if fmt in ("heic", "tiff"):
        raw = _convert_with_sips(src, fmt, platform, sips)
        res.converted_from = fmt
        res.notes.append("converted from %s to JPEG with sips" % fmt.upper())
        fmt = "jpeg"
    if fmt is None:
        raise ImageError("%s is not an image this plugin imports (JPEG, PNG, WebP, GIF, or HEIC/TIFF "
                         "on a Mac)" % os.path.basename(src))
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
        raise ImageError("%s already exists; not overwritten" % path)
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
        raise ImageError("could not write %s: %s" % (path, e.strerror or e))
    res.path = path
    res.copies = [copy_name(path, cw) for cw in sorted(copies)]
    res.width, res.height = main_w2, main_h2
    res.fmt = fmt
    res.bytes = len(main_blob)
    return res


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
