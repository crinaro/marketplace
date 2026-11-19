"""sourcescan.py -- the source shape scan (`check_site.py --scan-source`; design 8.2, named change M10) and
its explicit allow-list.

SOURCE SHAPE SCAN (--scan-source; design 8.2, named change M10). The CI half of "no personal
content from the example repos entered this repo". It runs the privacy family's shape checks over a
source tree: phone numbers, street addresses, emails, EXIF GPS/owner/serial in images, and the same
in readable PDFs. It has no privateTerms or publicEmails (those are a site's own). THE ALLOW-LIST
IS EXPLICIT AND LIVES IN THIS PACKAGE: ALLOW_PHONE_RESERVED, ALLOW_EMAIL_DOMAINS and ALLOW_EMAIL_TLDS in
shapes.py, ALLOW_FILES and ALLOW_EMAILS here:
    phone  the NANP range reserved for fiction, 555-0100 to 555-0199 (anything else, including
           555-0200, is flagged);
    email  RFC 2606/6761 names: example.com, example.org, example.net and their subdomains, and the
           TLDs .test, .invalid, .example, .localhost (a lookalike such as notexample.com is not
           allowed: matching is on whole labels);
    files  named globs, each with the kinds it may carry and the reason (ALLOW_FILES, empty unless
           a real false positive is recorded there with its reason);
    emails ONE named address in ONE named file, with the reason (ALLOW_EMAILS): the marketplace's own
           published contact address, which `.claude-plugin/plugin.json` must carry as `author.email`
           for the plugin directory (dev #835, gate-keeper G2). It is the address, not the file: any
           OTHER address in plugin.json is still flagged, and the same address in any other file is
           still flagged.
Images carrying GPS are NEVER tracked in this repo: the tests that need one make it in a temp dir.
Source files that mention a pattern must not contain a real-shaped example of it; write the
documentation of a shape without a literal instance.

"""

import fnmatch
from imaging import exif
from pdfreading import reader
import os
from sitechecks.kinds import IMAGE_EXTS, TEXT_EXTS
from sitechecks.report import Finding, Report
from sitechecks.shapes import (
    email_domain_allowed,
    email_hits,
    mask,
    phone_allowed_reserved,
    phone_hits,
    street_hits,
)


# (glob over the path as scanned, kinds allowed, reason). Empty on purpose: add an entry only for a
# real false positive, with the reason, in the commit that adds it.
ALLOW_FILES = ()
# (glob over the path as scanned, ONE exact address, reason). An address, never a whole file or a
# domain: see the docstring. The marketplace publishes this address on purpose (plugin.json `author`,
# also exempt in scripts/publish_manifest.py SHAPE_OK); the scan flagged it as "outside the reserved
# domains" because it is real, and a real address in a source tree is exactly what the scan is for.
ALLOW_EMAILS = (
    (".claude-plugin/plugin.json", "marketplace" + "@" + "crinaro.ai",   # split: the scan reads this file too
     "the marketplace's own published contact address, required as author.email by the plugin directory"),
)


SKIP_DIRS = (".git", "__pycache__", "node_modules", ".mypy_cache", ".pytest_cache")


def _file_allowed(path, kind):
    p = path.replace(os.sep, "/")
    for glob, kinds, _why in ALLOW_FILES:
        if kind in kinds and (fnmatch.fnmatch(p, glob) or fnmatch.fnmatch(p, "*/" + glob)):
            return True
    return False


def _email_allowed_in(path, email):
    p = path.replace(os.sep, "/")
    e = email.lower()
    for glob, addr, _why in ALLOW_EMAILS:
        if e == addr.lower() and (fnmatch.fnmatch(p, glob) or fnmatch.fnmatch(p, "*/" + glob)):
            return True
    return False


def scan_source(paths):
    rep = Report()
    files = []
    for top in paths:
        if os.path.isfile(top):
            files.append(top)
            continue
        if not os.path.isdir(top):
            rep.add("privacy", top, "scan path does not exist")
            continue
        for d, dirs, names in os.walk(top):
            dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
            for fn in sorted(names):
                files.append(os.path.join(d, fn))
    rep.count("privacy", len(files))
    n_text = n_img = 0
    for path in files:
        low = path.lower()
        shown = path.replace(os.sep, "/")
        try:
            with open(path, "rb") as fh:
                data = fh.read(40 * 1024 * 1024)
        except OSError as e:
            rep.add("privacy", shown, "cannot read: %s" % (e.strerror or e))
            continue
        if low.endswith(IMAGE_EXTS):
            n_img += 1
            for kind, detail in exif.inspect_metadata(data):
                if kind in ("gps", "owner", "serial") and not _file_allowed(path, "image-" + kind):
                    rep.add("privacy", shown, "image carries EXIF %s (%s)" % (kind, detail))
        elif low.endswith(".pdf"):
            res = reader.read_pdf(data)
            if res.read:
                rep.pdfs_read += 1
            else:
                rep.not_read.append(Finding("privacy", shown, "NOT READ: " + "; ".join(res.reasons), "not-read"))
            _scan_text_shapes(rep, path, shown, res.text + " " + " ".join(res.info.values()))
        elif low.endswith(TEXT_EXTS):
            n_text += 1
            _scan_text_shapes(rep, path, shown, data.decode("utf-8", "replace"))
        else:
            rep.skipped.append(shown)
    rep.notes.append("scanned %d file(s): %d text, %d image; %d skipped (other types)"
                     % (len(files), n_text, n_img, len(rep.skipped)))
    if not files:
        rep.add("privacy", ",".join(paths), "the scan found no files: nothing was checked")
    rep.findings.sort(key=lambda f: f.sort_key())
    return rep


def _scan_text_shapes(rep, path, shown, text):
    for hit in phone_hits(text):
        if phone_allowed_reserved(hit) or _file_allowed(path, "phone"):
            continue
        rep.add("privacy", shown, "phone number %s outside the reserved 555-01xx range" % mask(hit))
    if not _file_allowed(path, "street"):
        for hit in street_hits(text):
            rep.add("privacy", shown, "street address %s" % mask(hit))
    for e in email_hits(text):
        if not email_domain_allowed(e) and not _file_allowed(path, "email") and not _email_allowed_in(path, e):
            rep.add("privacy", shown, "email address %s outside the reserved domains" % mask(e))
