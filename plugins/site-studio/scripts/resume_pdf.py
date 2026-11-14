#!/usr/bin/env python3
"""resume_pdf.py -- print the built resume page to PDF with Chrome and write the sidecar that lets
the build and the privacy gate prove the PDF matches its source (dev #835; design 5.3 and 7.1;
named changes M8; findings F8 and F10). Python 3.9, standard library only; Chrome via browser.py.

    python3 resume_pdf.py [--repo R] [--quiet]

WHAT IT DOES
  1. builds the working tree WITH DRAFTS into a temp folder (preview.py) and serves it on 127.0.0.1;
  2. prints `resume/index.html` to PDF at `site.json` resume.paper (Letter or A4), backgrounds on;
  3. READS THE PDF BACK with the shipped reader (pdftext.read_pdf) and compares it to the BUILT
     resume page's <main> text, word for word: the very comparison `check_site.py` makes (7.1 rule 2,
     F8: >= 95% of the page's words). A PDF the gate would call NOT READ is REFUSED here, before
     anything is written, with the coverage and the reasons;
  4. writes <resume.pdf> and its sidecar <resume.pdf>.json, exactly
        {"pdf_sha256", "source_sha256", "text_sha256"}      64 lowercase hex digits each
     source_sha256 = SHA-256 of the RAW bytes of the resume source (resume.md) as it is on disk;
     pdf_sha256    = SHA-256 of the PDF bytes;
     text_sha256   = SHA-256 of pdftext.normalise_text(<the built page's <main> text>), the content
                     rule 2 compares against (the page's own text, never the PDF's);
  5. prints the Chrome version (named change M8: a later Chrome change shows in the packet), the
     paths, the hashes, the word coverage, and, unless --quiet, the exact text compared.

The sidecar is committed beside the PDF and never published (the build refuses a stale PDF: any
change to resume.md or to the PDF bytes breaks the match). If resume.md has uncommitted changes the
script says so, because the PUBLISH build reads the commit.

PRINT STYLE (F10, measured 2026-11-12). Chrome writes a kerned pair such as "T" + "estfield" as two
text runs joined by a position move, and the `fi` ligature as one glyph; a PDF reader that treats
every position move as a word break then reads "Testfield" as "t estfield". The reader (pdftext.py)
does that, deliberately conservative. This script therefore prints with `font-kerning: none` and
`font-variant-ligatures: none` (injected through Runtime.evaluate before printing, only into the
print of this PDF, never into the site), so a word is one run and the gate can read the resume it
was meant to read. The cost is slightly looser letter-spacing in the PDF.
UPDATE (follow-up 1c, 2026-11-13): pdftext.py now joins runs whose measured gap is under 0.15 em,
so a kerned, ligatured print reads in full too (test_resume_pdf `TestKerning`, test_pdftext
`RealChromeKerning`). The print style is kept as belt and braces; it is no longer required.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import browser    # noqa: E402
import check_site  # noqa: E402
import pdftext    # noqa: E402
import preview    # noqa: E402
import siteconfig  # noqa: E402

COVERAGE_NEEDED = 0.95      # design 7.1 rule 2; check_site.py's bound
RESUME_PAGE = "resume/index.html"
PRINT_STYLE = ("*,*::before,*::after{font-kerning:none !important;font-variant-ligatures:none !important;"
               "text-rendering:optimizeSpeed !important}")


class ResumeError(ValueError):
    pass


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def page_main_text(out_dir):
    """The words rule 2 compares against: the built resume page's <main> text, the 'Download as
    PDF' caption excluded, exactly as check_site.py derives it."""
    path = os.path.join(out_dir, *RESUME_PAGE.split("/"))
    with open(path, "r", encoding="utf-8") as fh:
        page = check_site.parse_page(RESUME_PAGE, fh.read())
    return " ".join(page.main_text)


def print_pdf(url, paper):
    """(pdf bytes, chrome packet) for the page at `url`."""
    with browser.Browser() as b:
        p = b.new_page(width=1000, height=1200, scale=1)
        p.goto(url)
        if p.status != 200:
            raise ResumeError("the resume page answered HTTP %s" % p.status)
        p.scroll_through()
        p.evaluate("(function(){var s=document.createElement('style');s.textContent=%s;"
                   "document.head.appendChild(s);return true;})()" % json.dumps(PRINT_STYLE))
        return p.pdf(paper), b.packet()


def make_resume_pdf(repo, log=print, quiet=False):
    """Print, verify and write. Returns the sidecar dict plus paths. Raises ResumeError."""
    repo = os.path.abspath(repo)
    cfg = siteconfig.load(os.path.join(repo, "site", "site.json"))
    res = cfg.resume
    if not res:
        raise ResumeError("site.json has no resume (set it, or ask for one with the resume skill)")
    if not res.get("pdf"):
        raise ResumeError("site.json resume.pdf is null: this site publishes no resume PDF")
    src_path = os.path.join(repo, *res["path"].split("/"))
    pdf_path = os.path.join(repo, *res["pdf"].split("/"))
    if not os.path.isfile(src_path):
        raise ResumeError("the resume source %s does not exist" % res["path"])
    with open(src_path, "rb") as fh:
        source_bytes = fh.read()
    with preview.Preview(repo) as pv:
        if RESUME_PAGE not in [p for p, _k in pv.result.pages]:
            raise ResumeError("the build has no resume page; check site.json resume and %s" % res["path"])
        main_text = page_main_text(pv.out_dir)
        pdf, packet = print_pdf(pv.page_url(RESUME_PAGE), res["paper"])
    if not pdftext.words(main_text):
        raise ResumeError("the built resume page has no text, so a PDF of it could never be checked")
    read = pdftext.read_pdf(pdf)
    cov = pdftext.word_coverage(main_text, read.text) if read.status == "read" else None
    if read.status != "read" or cov is None or cov < COVERAGE_NEEDED:
        raise ResumeError(
            "the printed PDF would not pass the privacy gate (rule 2): %s; nothing was written" % (
                "; ".join(read.reasons) if read.status != "read" else
                "its text covers %s of the resume page's words (needs 95%%)" % (
                    "none" if cov is None else "%d%%" % int(cov * 100))))
    sidecar = {"pdf_sha256": sha256_hex(pdf), "source_sha256": sha256_hex(source_bytes),
               "text_sha256": sha256_hex(pdftext.normalise_text(main_text).encode("utf-8"))}
    os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
    for path, data in ((pdf_path, pdf),
                       (pdf_path + ".json",
                        (json.dumps(sidecar, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8"))):
        tmp = path + ".part"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    dirty = _uncommitted(repo, res["path"])
    log("resume PDF: %s (%d bytes, %s)" % (res["pdf"], len(pdf), res["paper"]))
    log("sidecar: %s.json" % res["pdf"])
    log("chrome: %s (%s)" % (packet["chrome"], packet["platform"]))
    log("source_sha256: %s (%s)" % (sidecar["source_sha256"], res["path"]))
    log("pdf_sha256: %s" % sidecar["pdf_sha256"])
    log("text_sha256: %s" % sidecar["text_sha256"])
    log("text: %d words in the resume page's <main>; the PDF decodes to %d%% of them (the gate needs 95%%)" % (
        len(pdftext.words(main_text)), int(cov * 100)))
    if dirty:
        log("note: %s has uncommitted changes; commit it, then the publish build (which reads the commit) "
            "will match this PDF" % res["path"])
    if not quiet:
        log("content compared (the built resume page's <main> text):")
        log("  " + " ".join(main_text.split()))
    return {"sidecar": sidecar, "pdf": res["pdf"], "packet": packet, "coverage": cov, "text": main_text}


def _uncommitted(repo, rel):
    try:
        p = subprocess.run(["git", "-C", repo, "status", "--porcelain", "--", rel], stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, universal_newlines=True, timeout=30)
        return bool(p.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return False


def build_parser():
    ap = argparse.ArgumentParser(prog="resume_pdf.py", allow_abbrev=False,
                                 description="Print the resume page to PDF and write its sidecar.")
    ap.add_argument("--repo", default=".", help="the dev repo (default: the current directory)")
    ap.add_argument("--quiet", action="store_true", help="do not print the text that was compared")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        make_resume_pdf(args.repo, print, args.quiet)
        return 0
    except (ResumeError, browser.BrowserError, siteconfig.SiteConfigError, OSError, ValueError) as e:
        print("resume PDF refused: %s" % e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
