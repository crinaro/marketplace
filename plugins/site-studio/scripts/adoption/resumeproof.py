"""adoption.resumeproof -- the proof a converted site's resume PDF is missing: made by adopt where the PDF already says what the resume page says (dev 1068, design 2.1 to 2.3).

Part of the `adoption` package behind the entry point `adopt.py`. The sidecar `<resume pdf>.json` holds three hashes. The build checks `source_sha256` and
`pdf_sha256`; NOTHING reads `text_sha256`. What makes it a proof is the privacy gate's rule 2: the PDF's own decoded text holds at least 95% of the words of the
built resume page's `<main>` (`wordcoverage.NEEDED`, `wordcoverage.meets`, `sitechecks.page.main_words`: one object each, used here as the gate and
`resume_pdf.py` use them, never written again). The examples' builders never wrote a sidecar, so a converted site met "resume.pdf.json is missing" first at step 3 of
`apply`. `prove(files)` asks, of the converted tree, what a person can be told in advance:

  none        no resume, or no PDF configured, or a file missing the build names itself: nothing to prove
  committed   a sidecar already beside the PDF that matches the converted source and the PDF: used as it is ("nothing changes for a site already converted")
  stale       a sidecar that does NOT match: kept, never overwritten (the build refuses it, and says so); the person decides
  writes      the plugin's reader finds the bound's share of the page's words in the EXISTING PDF: `apply` writes the real sidecar, three true hashes, in its one
              commit; the PDF's bytes never change
  low         the reader finds less: the finding says the share, ten words it did not find, and that this can be the reader's fault (joined letters, hyphens
              at line ends, languages written without spaces)
  extra       the reader finds the page in the PDF, and the PDF holds more (dev 1068, review R2): under the bound's share of the PDF's own words are words the resume
              page holds (all its visible text, header and footer too, as a print carries them). A PDF of the page plus private notes is "all of the page found", so
              the measure runs BOTH ways, each at `wordcoverage.NEEDED`; the finding lists ten words the PDF holds that the page does not
  short       the page's `<main>` holds fewer than `MIN_PAGE_WORDS` words: too few for a word count to show the PDF says what the page says, so it is never proved
  unreadable  the reader cannot read the PDF: the same, with its reasons
  vouched     `adopt.py proof --as-is` stored the PDF's hash AND the converted resume source's hash in the plan (`resumeProof`), and both are still those files: `apply`
              writes the sidecar, the commit says the person vouched for it, and the gate still lists the PDF NOT READ, so the privacy review opens it. A new PDF OR a
              changed resume voids it, and the finding says so ("you vouched for this PDF against an older resume"), as a stale sidecar is said to be (review R2)
  unbuilt     the build refuses the tree (its refusals are listed), so the resume page does not exist yet: the PDF was not read against it
  empty       the built resume page has no words, so no PDF of it could ever be checked

THE STAND-IN (`stand_in`) is the one place a placeholder sidecar is made: a converted tree whose PDF has no sidecar is given one for the length of a build that
only asks "does the plugin accept this tree", so the rest of a list can be computed while the proof finding stands. Its `text_sha256` is all zeros and it is NEVER
written to a commit, a snapshot or a person's checkout (`is_stand_in`; `apply` refuses a sidecar that is one). The finding is always printed beside it
(`publishchecks`). This module sits below `problems`, `fileacct` and `measure`, which ask the same question of their own builds and so call the same function.
"""

import collections
import hashlib
import json

from building import running  # noqa: E402
from configschema import diagnostics, model  # noqa: E402
from pdfreading import reader, wordcoverage  # noqa: E402
from sitechecks import page as page_mod  # noqa: E402

RESUME_PAGE = "resume/index.html"
NOT_SHOWN_MAX = 10
ZERO = "0" * 64
VOUCHED_LINE = "the person vouched for the resume PDF"          # the words of the conversion commit that the review-cover step reads back

# The fewest words a resume page's `<main>` may hold for a word count to prove anything (dev 1068, review R2). 20 = 1 / (1 - NEEDED): the smallest page on which
# the 95% bound lets even one word differ. Below it the bound is all-or-nothing on a handful of common words ("Resume", "Experience") that unrelated documents
# share, so a page that short is never "proved" by counting: the person's `--as-is` and the privacy review's own reading answer it.
MIN_PAGE_WORDS = 20

NONE, COMMITTED, STALE, WRITES, LOW, UNREADABLE, VOUCHED, UNBUILT, EMPTY, EXTRA, SHORT = (
    "none", "committed", "stale", "writes", "low", "unreadable", "vouched", "unbuilt", "empty", "extra", "short")
MAY_BE_VOUCHED = (LOW, UNREADABLE, EXTRA, SHORT)       # the states `Proof.finding` speaks for: the person answers them with `--as-is`, or makes the PDF and the page agree
FIX_PERSON = ("`adopt.py proof --as-is` if you vouch for this PDF (the privacy review then opens it), `adopt.py proof --print` to print a new one "
              "(needs Chrome), or update the PDF or the resume page")


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def _config(files):
    """The converted site.json's configuration, or None when the files hold none that parses."""
    try:
        return model.parse_text(files["site/site.json"].decode("utf-8"))
    except (KeyError, UnicodeDecodeError, diagnostics.SiteConfigError):
        return None


def resume_paths(files):
    """(source path, pdf path) of the resume the converted site.json configures, each None when it names none."""
    cfg = _config(files)
    res = cfg.resume if cfg is not None and isinstance(cfg.resume, dict) else {}
    return res.get("path"), res.get("pdf")


def stand_in(files):
    """`files` with the placeholder sidecar a build needs to accept a converted tree whose resume PDF has none (true hashes of the source and the PDF, a zero
    `text_sha256`). A sidecar already there is never touched. Returns a new dict; the placeholder is never to be committed (see the module docstring)."""
    out = dict(files)
    src, pdf = resume_paths(files)
    if pdf and src and pdf in files and src in files and (pdf + ".json") not in files:
        out[pdf + ".json"] = json.dumps({"source_sha256": sha(files[src]), "pdf_sha256": sha(files[pdf]), "text_sha256": ZERO}).encode("utf-8")
    return out


def is_stand_in(blob):
    """True when `blob` is a sidecar whose `text_sha256` is the placeholder's zeros."""
    try:
        return json.loads(blob.decode("utf-8")).get("text_sha256") == ZERO
    except (ValueError, UnicodeDecodeError, AttributeError):
        return False


Vouch = collections.namedtuple("Vouch", "pdf source")      # what `--as-is` stored: the PDF's sha256 and the converted resume source's (None for a bare PDF hash)


def vouched_sha(plan):
    """The `Vouch` `adopt.py proof --as-is` stored in `plan` (the PDF's hash AND the converted resume source's, dev 1068 review R2), or None. The name is the one
    `apply`, `verbs` and `publishchecks` already call, and what they hand on is this value, which `prove` reads."""
    row = plan.get("resumeProof") if isinstance(plan, dict) else None
    if not (isinstance(row, dict) and isinstance(row.get("asIs"), str)):
        return None
    return Vouch(row["asIs"], row["source"] if isinstance(row.get("source"), str) else None)


def vouch_row(files, proof):
    """The `resumeProof` row `adopt.py proof --as-is` stores for `proof` over the converted tree `files`: `{"asIs": the PDF's sha256, "source": the resume source's}`.
    Both are bound, so a later change of either voids the vouch (`prove`)."""
    src, _pdf = resume_paths(files)
    return {"asIs": sha(files[proof.pdf]), "source": sha(files[src])}


def _vouch_against(vouched, src_blob, pdf_blob):
    """(holds, why): `holds` only when BOTH stored hashes are the files'; `why` is the sentence for a vouch that does not hold (else "")."""
    if vouched is None:
        return False, ""
    if not isinstance(vouched, Vouch):                       # a bare PDF hash binds nothing to the resume: it never holds
        vouched = Vouch(vouched, None)
    if vouched.pdf != sha(pdf_blob):
        return False, ("you vouched for another version of this PDF, and it has changed since: vouch for this one with `adopt.py proof --as-is`, or update the PDF")
    if vouched.source != sha(src_blob):
        return False, ("you vouched for this PDF against an older resume, and the resume has changed since: vouch again with `adopt.py proof --as-is`, or update the "
                       "PDF to the resume as it is now")
    return True, ""


def _matches(side_blob, src_blob, pdf_blob):
    """True when a committed sidecar is one the build accepts for these bytes: three hashes, the source's and the PDF's true."""
    try:
        rec = json.loads(side_blob.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return False
    return (isinstance(rec, dict) and set(rec) == {"source_sha256", "pdf_sha256", "text_sha256"}
            and rec["source_sha256"] == sha(src_blob) and rec["pdf_sha256"] == sha(pdf_blob))


def not_found(source_text, decoded_text, limit=NOT_SHOWN_MAX):
    """Up to `limit` distinct words of the page, in page order, that the PDF's text does not hold as many times as the page does (what the share is made of)."""
    have = {}
    for w in wordcoverage.words(decoded_text):
        have[w] = have.get(w, 0) + 1
    out = []
    for w in wordcoverage.words(source_text):
        if have.get(w, 0) > 0:
            have[w] -= 1
        elif w not in out:
            out.append(w)
            if len(out) == limit:
                break
    return out


class Proof(object):
    """What `prove` found: `state` (see the module docstring), `pdf` and `side` (their paths in the converted tree), `coverage` (0..1 or None), `missing` (the
    page's words the reader did not find), `reasons` (the reader's, when it could not read), `sidecar` (the bytes `apply` writes, or None) and `page_text`. For a PDF
    the reader found the page in: `back` (0..1, the share of the PDF's own words the resume page holds), `extra` (ten words the PDF holds that the page does not) and
    `words` (the words of the page's `<main>`). `stale` is the sentence for a `--as-is` that no longer holds, or ""."""

    def __init__(self, state, pdf=None, coverage=None, missing=(), reasons=(), sidecar=None, page_text="", why="", back=None, extra=(), words=0, stale=""):
        self.state, self.pdf, self.coverage, self.missing = state, pdf, coverage, list(missing)
        self.reasons, self.sidecar, self.page_text, self.why = list(reasons), sidecar, page_text, why
        self.back, self.extra, self.words, self.stale = back, list(extra), words, stale
        self.side = pdf + ".json" if pdf else None

    def percent(self):
        return None if self.coverage is None else int(self.coverage * 100)

    def read_as(self):
        """How the reader fared, in words."""
        if self.state == UNREADABLE or self.coverage is None:
            return "the plugin's reader could not read it (%s)" % ("; ".join(self.reasons) or "no reason given")
        said = "the plugin's reader found %d%% of the resume page's words in it" % self.percent()
        if self.extra:
            said += ", and the PDF holds words the resume page does not: %s" % ", ".join(self.extra)
        if self.words < MIN_PAGE_WORDS and self.back is not None:
            said += ", and the resume page holds only %d words, too few for a word count to show the PDF says what the page says" % self.words
        return said

    def finding(self):
        """The `proof` family's finding text (matches the `proof` row of `publishfixes`), or None when there is nothing for the person to settle."""
        if self.state not in MAY_BE_VOUCHED:
            return None
        if self.state in (EXTRA, SHORT):
            rule = ("only %d%% of the PDF's own words are on the resume page, and %d%% are needed" % (int((self.back or 0) * 100), int(wordcoverage.NEEDED * 100))
                    if self.state == EXTRA else "a resume page of fewer than %d words is never proved by counting its words" % MIN_PAGE_WORDS)
            return ("the resume PDF %s has no proof beside it (%s; %s; update the resume page or the PDF so they say the same, or vouch for the PDF)%s"
                    % (self.pdf, self.read_as(), rule, self._stale_tail()))
        shown = "; it did not find: %s" % ", ".join(self.missing) if self.missing else ""
        return ("the resume PDF %s has no proof beside it (%s, and %d%% are needed%s; this can be the reader's fault: joined letters, hyphens at line ends, "
                "languages written without spaces)%s" % (self.pdf, self.read_as(), int(wordcoverage.NEEDED * 100), shown, self._stale_tail()))

    def _stale_tail(self):
        return "; %s" % self.stale if self.stale else ""

    def sentence(self):
        """What `check`, `parity` and `proof` print for a PDF that has, or will have, its proof; "" for every other state. Never says the proof is written: only `apply` writes it."""
        if self.state == WRITES:
            return ("your resume PDF %s was checked against the resume page: %d%% of its words found; `apply` writes its proof, and the PDF does not change"
                    % (self.pdf, self.percent()))
        if self.state == VOUCHED:
            return ("you vouched for your resume PDF %s (%s); `apply` writes its proof, and the privacy review must open the PDF"
                    % (self.pdf, self.read_as()))
        return ""

    def commit_line(self):
        """The line `apply`'s commit carries for a proof it writes, or ""."""
        if self.state == WRITES:
            return ("%s: the resume PDF's proof written (the plugin's reader found %d%% of the resume page's words in %s; the PDF is unchanged)"
                    % (self.side, self.percent(), self.pdf))
        if self.state == VOUCHED:
            return ("%s: %s (%s); the PDF is unchanged, and the privacy review must open it" % (self.side, VOUCHED_LINE, self.read_as()))
        return ""


def sidecar_bytes(src_blob, pdf_blob, page_text):
    """The sidecar `resume_pdf.py` writes, byte for byte: three true hashes (the text's is of the page's normalised main text)."""
    rec = {"pdf_sha256": sha(pdf_blob), "source_sha256": sha(src_blob),
           "text_sha256": sha(wordcoverage.normalise_text(page_text).encode("utf-8"))}
    return (json.dumps(rec, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def prove(files, vouched=None):
    """The `Proof` for the converted tree `files` ({path: bytes}, `wouldwrite.snapshot`'s). `vouched` is the `Vouch` (`vouched_sha`) the person's `--as-is` stored, or None.
    Builds the tree once (with the stand-in) only when a PDF has no sidecar and a page can be compared. Never raises."""
    src, pdf = resume_paths(files)
    if not (pdf and src and pdf in files and src in files):
        return Proof(NONE, pdf)
    side = pdf + ".json"
    if side in files:
        return Proof(COMMITTED if _matches(files[side], files[src], files[pdf]) else STALE, pdf)
    try:
        acc = running.accept(stand_in(files))
    except Exception as e:      # noqa: BLE001 -- accept does not raise; a doubt is a state, never a proof
        return Proof(UNBUILT, pdf, why="the build could not run (%s)" % e.__class__.__name__)
    page = acc.output.get(RESUME_PAGE) if not acc.problems and acc.cfg is not None else None
    if page is None:
        return Proof(UNBUILT, pdf, why="the build refuses the tree, so there is no resume page to read the PDF against yet")
    parsed = page_mod.parse_page(RESUME_PAGE, page.decode("utf-8", "replace"))
    text = page_mod.main_words(parsed)
    if not wordcoverage.words(text):
        return Proof(EMPTY, pdf, page_text=text)
    read = reader.read_pdf(files[pdf])
    cov = wordcoverage.word_coverage(text, read.text) if read.read else None
    n_words = len(wordcoverage.words(text))
    back, extra = None, []
    if wordcoverage.meets(cov):
        # the other way (review R2): the PDF's own words in the page. A print carries the page's header and footer, so the reference is all the page's visible
        # text, not its `<main>` alone; what is left over is content the page does not hold.
        back = wordcoverage.word_coverage(read.text, parsed.visible_text)
        agrees = wordcoverage.meets(back)
        if not agrees:
            extra = not_found(read.text, parsed.visible_text)
        if agrees and n_words >= MIN_PAGE_WORDS:
            return Proof(WRITES, pdf, cov, sidecar=sidecar_bytes(files[src], files[pdf], text), page_text=text, back=back, words=n_words)
        state = SHORT if n_words < MIN_PAGE_WORDS else EXTRA
    else:
        state = LOW if read.read else UNREADABLE
    missing = not_found(text, read.text) if state == LOW else []
    holds, stale = _vouch_against(vouched, files[src], files[pdf])
    if holds:
        return Proof(VOUCHED, pdf, cov, missing, read.reasons, sidecar_bytes(files[src], files[pdf], text), text, back=back, extra=extra, words=n_words)
    return Proof(state, pdf, cov, missing, read.reasons, page_text=text, back=back, extra=extra, words=n_words, stale=stale)


def with_sidecar(files, proof):
    """`files` plus the real sidecar `proof` makes (a new dict), or `files` itself when it makes none."""
    if proof.sidecar is None:
        return files
    out = dict(files)
    out[proof.side] = proof.sidecar
    return out


def state_lines(proof):
    """What `adopt.py proof` prints of a `Proof`: the state in one or two sentences, and what answers it. Never says a proof is written: only `apply` writes it."""
    pdf, st = proof.pdf, proof.state
    if st == NONE:
        return ["resume proof: nothing to prove (the converted site configures no resume PDF, or the resume source or the PDF is not in the tree)"]
    if st == COMMITTED:
        return ["resume proof: %s has a sidecar that matches the converted resume source and the PDF; it is used as it is" % pdf]
    if st == STALE:
        return ["resume proof: %s does not match the converted resume source or the PDF it sits beside; adopt keeps it and never overwrites it. Restore the PDF "
                "it was made for, or delete the sidecar and run `adopt.py proof` again" % proof.side]
    if st in (WRITES, VOUCHED):
        return [proof.sentence()]
    if st in MAY_BE_VOUCHED:
        return ["resume proof: " + proof.finding(), "  what answers it: " + FIX_PERSON]
    if st == EMPTY:
        return ["resume proof: the built resume page has no words, so no PDF of it could ever be checked; add the resume text to the page first"]
    return ["resume proof: not read against the resume page: %s" % (proof.why or "the build does not make it yet")]
