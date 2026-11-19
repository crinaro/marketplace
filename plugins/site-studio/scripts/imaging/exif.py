"""exif.py -- the EXIF reader: orientation (read before anything is stripped) and inspect_metadata, the list of hidden metadata a finished image still carries.

Moved out of images.py unchanged (S1b, dev 939); the interface and the design notes are in images.py."""

import struct
from imaging.errors import ImageError
from imaging.gif import _gif_extensions
from imaging.jpeg import _jpeg_segments
from imaging.png import _png_chunks
from imaging.sniff import detect_format
from imaging.webp import _riff_chunks


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
