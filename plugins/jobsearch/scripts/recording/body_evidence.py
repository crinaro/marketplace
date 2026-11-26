"""body_evidence: the quote of the DESCRIPTION a rendered read must carry (jobsearch 0.94.0, dev 1063; docs/design-role-first.md 6.1).

A rendered read used to need only a quote of the posting's title or Apply text. A title is on the page of a posting whose description never filled, so a
shell passed as a read (the 1063 incident). `read-jd --via render --body "<60-200 characters from the description>"` is the second quote, and this module is
the ONE function that says whether it is a description or only the header again:

  1. after the role's title, company and place are removed from it, and then a fixed list of header words (apply, easy, save, applicants, promoted, ago,
     reposted, ...), fewer than `MIN_LETTERS` (40) Unicode letters are left -> refused (a script without spaces is measured the same way: a letter is a letter);
  2. where the quote has spaces, fewer than `MIN_WORDS` (6) distinct words are left -> refused (forty letters of three words repeated is not prose);
  3. it equals `--evidence` -> refused (the same words twice are one observation);
  4. it is not 60 to 200 characters on one line (`jd_read.BODY_MIN`, `BODY_CAP`) -> refused.

Stated, not solved: the header list is ENGLISH, so a localised header can pass on length alone. PARTIAL: the reader reports the quote and no script sees the
page; this proves a quote is more than the header, not that it came from the description. A page's character count does not decide anything here: 1,500
characters is one observation, and a short employer page is a real posting.

Pure: reads nothing. Capability module of `recording/reads.py`. Python 3.9+, standard library only."""

import re
import unicodedata

import jd_read as _jd

MIN_LETTERS = 40
MIN_WORDS = 6
LEN_MIN, LEN_MAX = _jd.BODY_MIN, _jd.BODY_CAP

# The header words of a LinkedIn-style top card and the controls beside it. Whole words, compared case-folded. English only (stated above).
HEADER_WORDS = frozenset((
    "apply", "easy", "save", "saved", "share", "report", "promoted", "reposted", "posted", "ago", "applicants", "applicant", "clicked", "viewed",
    "over", "people", "hours", "hour", "days", "day", "weeks", "week", "months", "month", "minutes", "minute", "actively", "reviewing", "hiring",
    "recruiting", "responses", "managed", "contract", "temporary", "internship", "hybrid", "remote", "onsite", "matches", "followers", "employees",
    "linkedin"))

_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def fold(text):
    """`text` NFKC-normalised, case-folded and whitespace-collapsed: how the quote and the names it is judged against are compared."""
    return " ".join(unicodedata.normalize("NFKC", str(text or "")).casefold().split())


_NO_SPACE_SCRIPTS = ("CJK", "HIRAGANA", "KATAKANA", "HANGUL", "THAI", "LAO", "KHMER", "MYANMAR")


def _unspaced(phrase):
    """True when `phrase` is written in a script that puts no spaces between words, so a word boundary cannot be asked of it."""
    return any(unicodedata.name(ch, "").startswith(_NO_SPACE_SCRIPTS) for ch in phrase)


def _without(text, phrases):
    """`text` with each phrase (folded; the longest first, so a title is removed whole before its words) taken out. A phrase in a script with spaces comes out
    only as whole words (a company called `T` must not eat the t of every word); one in a script without spaces comes out wherever it stands."""
    for p in sorted({fold(p) for p in phrases if fold(p)}, key=len, reverse=True):
        if _unspaced(p):
            text = text.replace(p, " ")
        else:
            text = re.sub(r"(?<!\w)%s(?!\w)" % re.escape(p), " ", text)
    return text


def remainder(body, title, company, places):
    """The words of `body` that are neither the role's own names nor header words, as a list (casefolded): the part of the quote that says anything.
    The title, the company and each place are removed first as whole phrases (a script without spaces is only ever removed this way), then their own
    words one by one (a partial title still goes), then the header words."""
    text = _without(fold(body), [title, company] + list(places))
    own = set()
    for name in (title, company) + tuple(places):
        own.update(w for w in _WORD.findall(fold(name)) if len(w) > 1)
    return [w for w in _WORD.findall(text) if w not in own and w not in HEADER_WORDS]


def body_refusal(body, *, title, company, places, evidence):
    """`None` when `body` is acceptable body evidence of the role (`title`, `company`, `places`), else the sentence the verb refuses with (nothing is
    written). `evidence` is `--evidence`, which the body must differ from. A value that is not a string is refused too."""
    if not isinstance(body, str) or not body.strip():
        return "--body is empty: quote 60 to 200 characters of the posting's DESCRIPTION (not its title or header)"
    if "\n" in body or "\r" in body:
        return "--body is one line: quote 60 to 200 characters of the description on one line"
    body = body.strip()
    if len(body) < LEN_MIN or len(body) > LEN_MAX:
        return ("--body is %d characters; a quote of the description is %d to %d (never truncated for you)" % (len(body), LEN_MIN, LEN_MAX))
    if fold(body) == fold(evidence):
        return "--body equals --evidence: the body is a second, different quote of the page, from its description"
    words = remainder(body, title, company, places)
    letters = sum(1 for w in words for ch in w if ch.isalpha())
    if letters < MIN_LETTERS:
        return ("--body is the posting's header, not its description: with the role's title, company and place and the header words (apply, easy, save, "
                "applicants, promoted, ago, ...) taken out only %d letters are left, and a description quote carries at least %d. Quote a sentence "
                "from the description itself" % (letters, MIN_LETTERS))
    if " " in body.strip() and len(set(words)) < MIN_WORDS:
        return ("--body is the posting's header, not its description: with the role's title, company and place and the header words taken out only %d "
                "distinct word(s) are left, and a description quote carries at least %d. Quote a sentence from the description itself"
                % (len(set(words)), MIN_WORDS))
    return None
