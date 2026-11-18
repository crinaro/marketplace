"""Loading a portfolio's head, the resume and the unit of work each load is, with the resume PDF's staleness
check."""

import hashlib
import json
import posixpath

from siteconfig import SiteConfigError, front_matter_keys

from contentmodel.errors import ContentError
from contentmodel.frontmatter import _check_keys, decode_text, parse_front_matter
from contentmodel.grammar import body_start_line
from contentmodel.keytables import CARD_EXTS, SHA_RE, resume_page_keys
from contentmodel.links import _URL_SCHEME_OR_PROTOREL
from contentmodel.models import Page
from contentmodel.pagefiles import _check_contact, _check_v4_page_keys


def _unit(collect, fn, *args):
    """Run one unit of the load. With `collect` None this is a plain call (the first `ContentError`
    raises, as it always did). With a list, a refusal is APPENDED and the unit is skipped, so
    `build.accept` can report every problem at once (design-site-fidelity section 4.1). Returns the
    unit's value, or None when it was skipped."""
    try:
        return fn(*args)
    except (ContentError, SiteConfigError) as e:
        if collect is None:
            raise
        collect.append(e)
        return None


def _key_line(text, v3, probs, key=None):
    """The 1-based line of the page.md key a refusal is about (`key`, else the first schema-3 key the first
    problem names), or None when it cannot be found."""
    wanted = key or next((k for k in v3 if probs and ("'%s'" % k) in probs[0].message), None)
    for k, n in front_matter_keys(text):
        if k == wanted:
            return n
    return None


def _reference_image(rj, name, image, files):
    """The repo path of a reference's `image` (schema 4): a relative path inside the reference's own folder,
    an image of a kind a card may be, and a file that is committed."""
    bad = None
    norm = posixpath.normpath(image) if image.strip() else ""
    if not image.strip() or "\\" in image or image.startswith("/") or norm.startswith("../") or norm in (".", ".."):
        bad = "must be a relative path inside the reference's own folder"
    elif _URL_SCHEME_OR_PROTOREL.match(image):
        bad = "must be a file in the reference's folder, not an address"
    elif not norm.lower().endswith(CARD_EXTS):
        bad = "must be an image (%s)" % ", ".join(e.lstrip(".") for e in CARD_EXTS)
    if bad:
        raise ContentError("%s: 'image' %r %s" % (rj, image, bad), path=rj,
                           fix="name the card image as a path under content/references/%s/, such as "
                               "media/preview.jpg" % name)
    full = "content/references/%s/%s" % (name, norm)
    if full not in files:
        raise ContentError("%s: 'image' %r is not a file in content/references/%s/" % (rj, image, name), path=rj,
                           fix="commit the image there, or fix the path")
    return full


def _load_resume(files, cfg, check_resume_pdf, c):
    src = cfg.resume["path"]
    pdf = cfg.resume["pdf"]
    if src in files:
        text = decode_text(files[src], src)
        meta, body = parse_front_matter(text, src)
        _check_keys(meta, resume_page_keys(cfg.schema), src)   # K-5: contact from schema 3; tagline, links from 4
        if "contact" in meta:
            _check_contact(meta, src)
        if cfg.schema >= 4:
            _check_v4_page_keys(meta, src)
        c.resume = Page(src, meta, body, body_start_line(text))
    elif check_resume_pdf:
        raise ContentError("site.json configures a resume but %s is not committed" % src, path=src,
                           fix="commit the resume file, or set resume to null in site.json")
    if pdf and pdf in files:
        c.resume_pdf = (pdf, files[pdf])
    if check_resume_pdf and c.resume is not None and pdf:
        _check_resume_pdf(files, src, pdf)


def _check_resume_pdf(files, src, pdf):
    side = pdf + ".json"
    if pdf not in files:
        raise ContentError("the resume PDF %s is not committed; make it with the resume skill" % pdf, fix="make the PDF with the resume skill and commit it")
    if side not in files:
        raise ContentError("%s is missing: without it nothing proves %s matches the resume source"
                           % (side, pdf), fix="make the PDF again with the resume skill, which writes the sidecar")
    try:
        rec = json.loads(decode_text(files[side], side))
    except ValueError as e:
        raise ContentError("%s is not valid JSON: %s" % (side, e), fix="fix the JSON syntax in the file")
    if not isinstance(rec, dict) or set(rec) != {"source_sha256", "pdf_sha256", "text_sha256"} \
            or not all(isinstance(v, str) and SHA_RE.match(v) for v in rec.values()):
        raise ContentError("%s must hold exactly source_sha256, pdf_sha256 and text_sha256 "
                           "(64 hex digits each)" % side, fix="make the PDF again with the resume skill")
    if hashlib.sha256(files[src]).hexdigest() != rec["source_sha256"]:
        raise ContentError("the resume PDF is stale: %s changed after %s was made; remake the PDF "
                           "with the resume skill" % (src, pdf), fix="remake the PDF with the resume skill")
    if hashlib.sha256(files[pdf]).hexdigest() != rec["pdf_sha256"]:
        raise ContentError("the resume PDF is stale: %s does not match its sidecar %s" % (pdf, side), fix="remake the PDF with the resume skill")
