"""privacy.py -- the `privacy` family of the site gate (design 7.1). A mixin of `checker.Checker`.

PRIVACY (design 7.1) -- what it scans, and how
  Every file path, every text-like file's content (html/css/js/svg/txt/xml/json/webmanifest/
  sitemap), every image's metadata and every PDF's decoded text and metadata.
    * phone numbers: NANP shapes (with optional +1, parentheses, dots, dashes or spaces), +country
      international shapes, a 7-digit local number next to a word such as phone/call/tel, and any
      tel: link. In the BUILD gate nothing is allowed: a reserved 555-01xx number is flagged, because
      a real site never needs one and a planted one must be found (the allow-list belongs only to
      --scan-source: sourcescan.py).
    * street addresses: a house number, up to four capitalised words and a street suffix (Street,
      St, Avenue, Ave, Road, Rd, Lane, Drive, ...), a PO Box, and a city, state and ZIP line.
    * email addresses not listed in `publicEmails`, in text, attributes and mailto: links, and in
      PDF text. A "name@2x.png" style asset name is not an email (a file-extension TLD).
    * every `privateTerms` entry, case-insensitively and NFC/whitespace-normalised, in text, alt
      text, file names, URLs, script contents and PDF text. PDF text is searched in two forms (as
      decoded, and with ALL whitespace removed), because a word Chrome splits across two text runs
      reads as two words.
    * hidden image metadata (images.inspect_metadata): EXIF GPS, owner, serial, any other EXIF,
      XMP, IPTC, comments, PNG text/time chunks. The pipeline strips all of it at import, so any
      survivor is a finding.
    * PDF document metadata: /Author is a finding if present. /Creator is a finding unless it is a
      known generator name (Chromium, Chrome, Skia/PDF, HeadlessChrome). /Title is a finding unless
      it equals the <title> of one of this build's own pages (a public string by construction).
      /Producer, /Subject, /Keywords and the XMP fields are scanned like text. (JUDGEMENT, dated
      2026-11-12: design 7.1 lists author, creator and title; flagging a Chrome PDF's own Creator
      and the page-title Title would reject every resume the plugin prints, so those two are
      judged against what is public rather than refused outright.)
    * PDF text counts as READ only by OUTCOME (pdftext.read_pdf: decoded completely). The family
      prints, every run, `PDFs: N read, M NOT READ (listed below)`. A NOT READ PDF is never counted
      clean and is listed (and is a record with level "not-read" in --json) for privacy-guard; it
      does not by itself fail the gate, because the judgement half (design 7.2) is what answers it.
      For the PDF the plugin printed (the resume, identified by its sidecar's pdf_sha256) rule 2 of
      7.1 also applies: the decoded text must contain at least 95% of the words of the built resume
      page's <main> text, else it is NOT READ. A resume PDF with no matching sidecar is NOT READ.
      Rule 1 of the reader has so far been validated only against generator PDFs (see pdftext.py).

"""

import hashlib
import html
from imaging import exif
from pdfreading import reader, wordcoverage
import json
import os
import posixpath
import re
from urllib.parse import unquote
from sitechecks.kinds import IMAGE_EXTS, KNOWN_GENERATORS, SITE_TEXT_EXTS
from sitechecks.report import Finding
from sitechecks.shapes import email_hits, mask, norm_for_terms, phone_hits, street_hits


class PrivacyChecks(object):
    """The `privacy` family, design 7.1 (a mixin of `Checker`)."""

    # -- privacy -----------------------------------------------------------------------------
    def privacy(self):
        fam = "privacy"
        cfg = self.cfg
        t = self.t
        allowed = set(e.lower() for e in cfg.publicEmails)
        terms = [(x, norm_for_terms(x)) for x in cfg.privateTerms if x.strip()]
        n = 0

        def scan_terms(where, text, label=None):
            if not terms:
                return
            forms = [norm_for_terms(text), norm_for_terms(html.unescape(text)),
                     norm_for_terms(unquote(text))]
            for raw, nt in terms:
                if any(nt in f for f in forms):
                    self.r.add(fam, where, "contains the private term %s%s" % (mask(raw), (" " + label) if label else ""))

        def scan_shapes(where, text, label=""):
            for hit in phone_hits(text):
                self.r.add(fam, where, "phone number %s%s" % (mask(hit), label))
            for hit in street_hits(text):
                self.r.add(fam, where, "street address %s%s" % (mask(hit), label))

        def scan_emails(where, text, label=""):
            for e in email_hits(text):
                if e.lower() not in allowed:
                    self.r.add(fam, where, "email address %s is not in publicEmails%s" % (mask(e), label))

        for rel in sorted(t.files):
            n += 1
            scan_terms(rel, rel, "(in the file name)")
            scan_shapes(rel, rel.replace("/", " "), " (in the file name)")
            scan_emails(rel, rel, " (in the file name)")
        sidecar = None
        if self.repo and cfg.resume and cfg.resume.get("pdf"):
            sc = os.path.join(self.repo, cfg.resume["pdf"] + ".json")
            if os.path.isfile(sc):
                try:
                    with open(sc, "r", encoding="utf-8") as fh:
                        sidecar = json.load(fh)
                except (OSError, ValueError):
                    sidecar = None
        titles = set(p.title.strip() for p in self.pages.values())
        for rel in sorted(t.files):
            low = rel.lower()
            data = None
            if low.endswith((".html", ".htm")):
                p = self.pages[rel]
                text = html.unescape(" ".join([p.visible_text] + p.attr_text))
                scan_terms(rel, p.source)
                scan_terms(rel, p.fused_text, "(text split across tags)")
                scan_shapes(rel, text)
                scan_emails(rel, p.source)
                scan_emails(rel, text)
                for a in p.anchors:
                    h = (a["href"] or "").strip()
                    if h.lower().startswith("tel:"):
                        self.r.add(fam, rel, "tel: link %s" % mask(h[4:]))
            elif low.endswith(".pdf"):
                self._privacy_pdf(rel, allowed, scan_terms, scan_shapes, scan_emails, sidecar, titles)
            elif low.endswith(IMAGE_EXTS):
                for kind, detail in exif.inspect_metadata(t.read(rel)):
                    self.r.add(fam, rel, "hidden image metadata (%s): %s" % (kind, detail))
            elif low.endswith(SITE_TEXT_EXTS) or posixpath.basename(rel) in ("CNAME",):
                text = t.text(rel)
                scan_terms(rel, text)
                scan_emails(rel, text)
                if low.endswith((".txt", ".svg")):
                    scan_shapes(rel, html.unescape(re.sub(r"<[^>]+>", " ", text)) if low.endswith(".svg") else text)
        self.r.count(fam, n)
        self.r.notes.append("privacy: images carry text the gate cannot see; every public image is in the "
                            "judgement half's coverage set, never in a read count")

    def _privacy_pdf(self, rel, allowed, scan_terms, scan_shapes, scan_emails, sidecar, titles):
        fam = "privacy"
        data = self.t.read(rel)
        res = reader.read_pdf(data)
        reasons = list(res.reasons)
        status_read = res.read
        # metadata is judged even when the text is not read
        info, xmp = res.info, res.xmp
        if info.get("Author"):
            self.r.add(fam, rel, "PDF metadata names an author (%s)" % mask(info["Author"]))
        cr = info.get("Creator")
        if cr and not any(g in cr.lower() for g in KNOWN_GENERATORS):
            self.r.add(fam, rel, "PDF metadata Creator %r is not a known generator" % cr)
        ti = info.get("Title")
        if ti and ti.strip() not in titles:
            self.r.add(fam, rel, "PDF metadata Title %r is not the title of any page in this build" % ti)
        for k, v in list(info.items()) + [("xmp:" + a, b) for a, b in xmp.items()]:
            scan_terms(rel, v, "(PDF metadata %s)" % k)
            scan_shapes(rel, v, " (PDF metadata %s)" % k)
            scan_emails(rel, v, " (PDF metadata %s)" % k)
        for k in ("author", "creator"):
            if xmp.get(k):
                self.r.add(fam, rel, "PDF XMP metadata names a %s (%s)" % (k, mask(xmp[k])))
        # rule 2 for the PDF the plugin printed itself
        sha = hashlib.sha256(data).hexdigest()
        printed = bool(sidecar) and sidecar.get("pdf_sha256") == sha
        resume_cfg = self.cfg.resume
        is_resume_slot = bool(resume_cfg and resume_cfg.get("pdf")) and \
            rel == "resume/" + posixpath.basename(resume_cfg["pdf"])
        if status_read and is_resume_slot:
            if not printed:
                status_read = False
                reasons.append("resume PDF has no sidecar proving it against its source (rule 2)")
            else:
                page = self.pages.get("resume/index.html")
                src = " ".join(page.main_text) if page else ""
                cov = wordcoverage.word_coverage(src, res.text)
                # the page's text has the download-link caption and headings the print may omit
                # only if the author's print stylesheet hides them; the bound is the design's 95%
                if cov is None or cov < 0.95:
                    status_read = False
                    reasons.append("rule 2: the PDF's text covers %s of the resume page's words (needs 95%%)"
                                   % ("none" if cov is None else "%d%%" % int(cov * 100)))
        if res.text:
            for form in res.search_forms()[:1]:
                scan_shapes(rel, form, " (in the PDF text)")
                scan_emails(rel, form, " (in the PDF text)")
            for form in res.search_forms():
                scan_terms(rel, form, "(in the PDF text)")
        if status_read:
            self.r.pdfs_read += 1
        else:
            self.r.not_read.append(Finding("privacy", rel, "NOT READ: " + "; ".join(reasons), "not-read"))
