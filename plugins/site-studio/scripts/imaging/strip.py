"""strip.py -- strip_metadata: one entry for the four formats' strippers, chosen by the format the bytes are.

Moved out of images.py unchanged (S1b, dev 939); the interface and the design notes are in images.py."""

from imaging.errors import ImageError
from imaging.gif import strip_gif
from imaging.jpeg import strip_jpeg
from imaging.png import strip_png
from imaging.sniff import detect_format
from imaging.webp import strip_webp


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
