"""shapes.py -- the personal-data SHAPES (phone numbers, street addresses, emails), how a hit is masked, and the
reserved-range allow-list the source scan applies (design 7.1 and 8.2).

The patterns are shapes only. Source files that mention one must not contain a real-shaped example of
it; write the documentation of a shape without a literal instance.
"""

import re
import unicodedata


# ---- the explicit allow-list of the SOURCE shape scan (named change M10) -----------------------
ALLOW_PHONE_RESERVED = re.compile(r"555[-. ]?01\d\d$")
ALLOW_EMAIL_DOMAINS = ("example.com", "example.org", "example.net")
ALLOW_EMAIL_TLDS = ("test", "invalid", "example", "localhost")


FILE_EXT_TLDS = frozenset(["png", "jpg", "jpeg", "gif", "webp", "svg", "css", "js", "html", "htm",
                           "json", "pdf", "ico", "woff", "woff2", "ttf", "otf", "map", "txt", "md"])


_PHONE_NANP = re.compile(
    r"(?<![\w.])(?:\+?1[\s.-]?)?(?:\(\s*[2-9]\d{2}\s*\)|[2-9]\d{2})[\s.-]?[2-9]\d{2}[\s.-]\d{4}(?![\d])")
_PHONE_INTL = re.compile(r"(?<![\w.])\+\d{1,3}[\s.-]?\(?\d{1,4}\)?(?:[\s.-]?\d{2,4}){2,4}(?![\d])")
_PHONE_LOCAL = re.compile(
    r"(?i)\b(?:phone|call|tel|telephone|text|fax|cell|mobile|whatsapp)\b[^\n\d]{0,12}"
    r"(?<![\d.])(\d{3}[-. ]\d{4})(?!\d)")
_STREET = re.compile(
    r"(?<![\w.])\d{1,6}[A-Za-z]?\s+(?:(?:N|S|E|W|NE|NW|SE|SW)\.?\s+)?(?:[A-Z][A-Za-z'’.-]*\s+){1,4}"
    r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct|Way|Place|Pl|Terrace|"
    r"Ter|Parkway|Pkwy|Highway|Hwy|Circle|Cir|Square|Sq|Trail|Trl|Alley|Crescent|Close)\b\.?")
_POBOX = re.compile(r"(?i)\bP\.?\s?O\.?\s+Box\s+\d+\b")
_CITYZIP = re.compile(r"\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)?,\s+[A-Z]{2}\s+\d{5}(?:-\d{4})?\b")
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")


def norm_phone_digits(s):
    return re.sub(r"\D", "", s)


def phone_hits(text):
    """[matched text] for every phone-number shape in `text`."""
    out = []
    for rx in (_PHONE_NANP, _PHONE_INTL):
        out.extend(m.group(0).strip() for m in rx.finditer(text))
    out.extend(m.group(1) for m in _PHONE_LOCAL.finditer(text))
    return out


def street_hits(text):
    out = [m.group(0).strip() for m in _STREET.finditer(text)]
    out.extend(m.group(0) for m in _POBOX.finditer(text))
    out.extend(m.group(0) for m in _CITYZIP.finditer(text))
    return out


def email_hits(text):
    out = []
    for m in _EMAIL.finditer(text):
        e = m.group(0)
        tld = e.rsplit(".", 1)[-1].lower()
        if tld in FILE_EXT_TLDS:
            continue
        out.append(e)
    return out


def email_domain_allowed(addr):
    dom = addr.rsplit("@", 1)[-1].lower().rstrip(".")
    for d in ALLOW_EMAIL_DOMAINS:
        if dom == d or dom.endswith("." + d):
            return True
    return dom.rsplit(".", 1)[-1] in ALLOW_EMAIL_TLDS


def phone_allowed_reserved(hit):
    return bool(ALLOW_PHONE_RESERVED.search(norm_phone_digits(hit)))


def norm_for_terms(s):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", s)).casefold()


def mask(s):
    """A value in a finding without echoing the whole thing: private data stays out of logs."""
    s = s.strip()
    return s if len(s) <= 4 else s[:2] + "*" * (len(s) - 4) + s[-2:]
