"""sips.py -- HEIC and TIFF to JPEG with the macOS sips tool; refused, with the reason, anywhere else.

Moved out of images.py unchanged (S1b, dev 939); the interface and the design notes are in images.py."""

import os
import shutil
import subprocess
import tempfile
from imaging.errors import ImageError
from imaging.sniff import detect_format


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
