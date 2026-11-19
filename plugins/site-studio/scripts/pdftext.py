#!/usr/bin/env python3
"""pdftext.py -- read the TEXT of a PDF, and say honestly whether it was READ (dev #835, design
section 7.1). Python 3.9, stdlib only. Read-only: it never writes a file.

WHY THIS EXISTS. The privacy gate (check_site.py) must find a phone number or an address inside a
published PDF. Chrome's `printToPDF` writes its text as glyph ids -- `<0026...> Tj` -- inside
Flate streams. Successfully inflating the stream is therefore NOT reading: the text never
appears. A reader that inflates and greps would report a clean PDF that was never examined. So this
module decides, by OUTCOME, one of two things about a PDF: READ, or NOT READ. There is no third
answer and no "mostly".

WHAT "READ" MEANS (design 7.1, rule 1 -- the only rule implemented here)
  DECODED COMPLETELY. Every text-showing operator (Tj, TJ, ' and ") in every content stream --
  page content and Form XObjects reached by `Do` -- maps through its font's ToUnicode CMap
  (bfchar / bfrange), or is a literal string in a simple font whose encoding is a standard one
  (WinAnsi, MacRoman, Standard; a base-14 Type1 font with no /Encoding is Standard). No code is
  left unmapped (a destination of U+FFFD or nothing counts as unmapped), and the decoded text is
  non-empty on every page that has a text operator. A PDF with no text operator at all (an
  image-only scan) is NOT READ. Anything else is NOT READ, each with a stated reason: an encrypted
  file, an unmapped glyph, an unsupported stream filter, a font this module cannot decode, a parse
  failure. This module never raises on a hostile or damaged file; it returns NOT READ.

  Rule 2 of the design (a PDF the plugin printed itself must also be proven against its source
  text, at least 95% of the words) is a comparison the caller makes with `word_coverage()`, since
  it needs the resume page and the sidecar that only check_site.py has.

M8 -- WHAT HAS AND HAS NOT BEEN VALIDATED (named change M8, dev #835). Rule 1 has been validated
ONLY against generator PDFs: tests/test_pdftext.py writes PDFs that mimic Chrome's structure (a
Type0 font, Identity-H, a ToUnicode CMap) with plain Python, and they are not Chrome's output. Until
`tests/test_privacy_pdf.py` (phase 2) passes on real Chrome output, "decoded completely" is proven
against our own imitation of Chrome. Whether every Chrome version embeds ToUnicode is also not
established here; phase 2 records the Chrome version in the review packet so a version change
shows. Where Chrome did not embed a map, this module's answer is NOT READ, which is the safe
direction.

KNOWN LIMITS (all of them fail toward NOT READ or toward a wider scan, never toward "clean")
  * Word boundaries come from positioning operators and, where the font's glyph widths are
    known, from geometry (F10, below). A `Td`/`TD` move on the same baseline (ty == 0) that leaves
    a gap under JOIN_GAP_EM of an em after the previous run's own advance is NOT a word break, so
    a kerned pair that Chrome writes as two runs ("T" + "estfield") reads as one word. Every other
    move (a large gap, a baseline change, `Tm`, `T*`, `ET`, or a font whose widths are unknown) is
    still a break, so a word that is split anywhere else reads as two. `search_forms()` also
    offers the text with ALL whitespace removed, and the privateTerms scan uses both.
  * Annotation /Contents and form-field values are appended to the text; outline (bookmark)
    titles, embedded files and JavaScript are not read. Text drawn as vector outlines or as an
    image is invisible here by nature (design 7.1: images are covered by the judgement half).
  * Only Flate, ASCIIHex and ASCII85 stream filters, with no predictor, are decoded for content,
    ObjStm and CMap streams; any other filter there is NOT READ.

F10 (dev #835, measured 2026-11-12 on Chrome 157). Chrome writes each text run as `<glyphs> Tj`
and starts the next run with `tx 0 Td`. In the PDF content model `Td` is relative to the START of
the previous line, so `tx` is the previous run's ADVANCE, not the gap after it: a kerned "T" at 16 pt
is followed by `8 0 Td` (0.5 em), which a threshold on |tx| alone could never tell from a word
break. The reader therefore measures the gap, `tx - advance(previous run)`, from the font's own
widths (/W and /DW for a CID font, /Widths for a simple one); the advance is the sum of the glyph
widths x font size, less TJ adjustments. Chrome puts real space glyphs (code 3, mapped to U+0020)
inside its runs, so a gap of at most JOIN_GAP_EM is a kern or rounding. JOIN_GAP_EM = 0.15 em: a
Latin word space is 0.22 to 0.33 em (Helvetica 0.278, Times 0.25, Georgia 0.24), kerning only
tightens (gap <= 0) and tracking added by CSS is about 0.1 em at most. Where the widths are unknown
the old rule stands (a move is a break). Not modelled, and failing toward a break: Tc, Tw and Tz.

METADATA. `read_pdf()` also returns the document /Info strings and a few XMP fields (Author,
Creator, Producer, Title, Subject, Keywords, Company; dc:creator, dc:title, pdf:Producer,
xmp:CreatorTool), because the privacy family judges them (check_site.py).

CLI: python3 pdftext.py <file.pdf> [--json]   prints READ / NOT READ and the reason(s); exit 0 READ, 1 NOT READ, 2 a
usage error or an unreadable file. `--help` prints the usage and exits 0.

WHERE THE CODE IS (S1b, dev 939). This file is the command line; the reader lives in the package pdfreading/: values
(limits, object types), lexer, document (the object table, stream decoding), cmap (ToUnicode), fonts, streamrun (content
streams, the word-gap measure), result (PdfReadResult), reader (`read_pdf`), wordcoverage (`normalise_text`, `words`,
`word_coverage`). Nothing imports this file.
"""
import argparse
import json
import sys

from pdfreading.reader import read_pdf


def parser():
    """The command line (finding 1058: before 0.4.2 there was no parser, and `--help` was read as a file path)."""
    p = argparse.ArgumentParser(prog="pdftext.py",
                                description="Read the text of a PDF and say whether it was READ or NOT READ, with the reason(s).")
    p.add_argument("pdf", help="the PDF file to read")
    p.add_argument("--json", action="store_true", help="print the whole result as JSON")
    return p


def main(argv=None):
    args = parser().parse_args(sys.argv[1:] if argv is None else argv)
    try:
        with open(args.pdf, "rb") as fh:
            data = fh.read()
    except OSError as e:
        print("pdftext.py: cannot read %s: %s -- fix: give the path of a PDF file that exists and you can read" % (args.pdf, e.strerror or e),
              file=sys.stderr)
        return 2
    r = read_pdf(data)
    if args.json:
        print(json.dumps(r.to_dict(), sort_keys=True))
    else:
        print("READ" if r.read else "NOT READ: " + "; ".join(r.reasons))
    return 0 if r.read else 1

if __name__ == "__main__":
    sys.exit(main())
