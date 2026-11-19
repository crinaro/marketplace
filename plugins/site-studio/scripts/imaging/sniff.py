"""sniff.py -- which format a file's bytes are, and the width and height its header stores. Nothing is decoded.

Moved out of images.py unchanged (S1b, dev 939); the interface and the design notes are in images.py."""

import struct
from imaging.jpeg import _SOF, _jpeg_segments
from imaging.webp import _riff_chunks


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
