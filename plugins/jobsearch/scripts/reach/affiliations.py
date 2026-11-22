"""affiliations: the schools, bootcamps, past employers and communities the candidate is part of (jobsearch 0.91.0,
design-build-reach.md 7.1). One stated fact in `user.json` (layer 1, who the person is):

    affiliations   [{kind, name, linkedin_url?, career_services?}] or absent
        kind              "school" | "bootcamp" | "employer" | "community"
        name              non-empty string, as the candidate writes it
        linkedin_url      optional; stored as https://www.linkedin.com/(school|company|groups)/<slug>/
        career_services   optional, school and bootcamp only: true, or an https address

**Absent means never asked; `[]` means asked, none** (the rule `people.ties` follows). `state` derives which of the three a
`user.json` is in, and an unreadable value raises: it is never read as "no affiliations". The list order is the candidate's
own ranking, kept as written (OURS: any engine-chosen order between a school and a past employer would be a guess about the
candidate's network).

`parse` is the strict parser: it refuses an unknown key or kind, an empty name, a non-list, and `career_services` on an
employer or community, and returns the entries in the stored form. `normalize_linkedin_url` runs BEFORE the address is
validated: `http` or `https`, host `linkedin.com` or any `*.linkedin.com` (a country subdomain, or none), the path
`/(school|company|groups)/<slug>` with or without a trailing slash, query and fragment dropped. Anything else is refused with
the accepted forms printed. `check` is what `validate_data` runs: `parse`, plus a stored address that is not in the stored
form (a hand edit) is a problem, so a reader may rely on the one form.

An affiliation only angles a lookup link the CANDIDATE opens (7.2, built in B4); the engine searches for no person from it
(ADR-037). Capability module of `record.py` and `validate_data.py`. Python 3.9+, standard library only."""

import re
from urllib.parse import urlsplit

KINDS = ("school", "bootcamp", "employer", "community")
KEYS = ("kind", "name", "linkedin_url", "career_services")
CAREER_SERVICES_KINDS = ("school", "bootcamp")
PAGE_KINDS = ("school", "company", "groups")
STORED_URL = "https://www.linkedin.com/%s/%s/"
_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.%-]*$")
_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
ACCEPTED_URL_FORMS = ("accepted: http(s)://[<www or a country code>.]linkedin.com/<school|company|groups>/<slug>[/] "
                      "(a query or fragment is dropped); stored as https://www.linkedin.com/<school|company|groups>/<slug>/")

NOT_ASKED, NONE, LISTED = "not-asked", "none", "listed"


class AffiliationError(ValueError):
    """An `affiliations` value (or one entry of it) this parser cannot read. The message says what and how to fix it."""


def normalize_linkedin_url(url):
    """`url` in the one stored form `https://www.linkedin.com/<school|company|groups>/<slug>/`, or raises AffiliationError
    naming the accepted forms. The kind segment is matched without regard to case and stored lower case; the slug is kept as
    written."""
    if not isinstance(url, str) or not url.strip():
        raise AffiliationError("linkedin_url must be a non-empty string; %s" % ACCEPTED_URL_FORMS)
    try:
        parts = urlsplit(url.strip())
    except ValueError as e:
        raise AffiliationError("linkedin_url %r does not read as an address (%s); %s" % (url, e, ACCEPTED_URL_FORMS))
    if parts.scheme.lower() not in ("http", "https"):
        raise AffiliationError("linkedin_url %r must start http:// or https://; %s" % (url, ACCEPTED_URL_FORMS))
    if "@" in parts.netloc or ":" in parts.netloc:
        raise AffiliationError("linkedin_url %r carries a user or a port; %s" % (url, ACCEPTED_URL_FORMS))
    host = parts.netloc.lower()
    if host != "linkedin.com":
        sub = host[:-len(".linkedin.com")] if host.endswith(".linkedin.com") else None
        if not sub or not _LABEL.match(sub):
            raise AffiliationError("linkedin_url %r is not a linkedin.com address; %s" % (url, ACCEPTED_URL_FORMS))
    segs = parts.path.split("/")
    if segs and segs[-1] == "":
        segs = segs[:-1]                                  # one trailing slash, or none
    if len(segs) != 3 or segs[0] != "" or segs[1].lower() not in PAGE_KINDS or not _SLUG.match(segs[2]) \
            or segs[2] in (".", ".."):
        raise AffiliationError("linkedin_url %r is not a school, company or group page; %s" % (url, ACCEPTED_URL_FORMS))
    return STORED_URL % (segs[1].lower(), segs[2])


def _career_services(value, kind, where):
    if kind not in CAREER_SERVICES_KINDS:
        raise AffiliationError("%s: career_services applies to a school or bootcamp only, not a %s" % (where, kind))
    if value is True:
        return True
    if isinstance(value, str):
        p = urlsplit(value.strip())
        if p.scheme == "https" and p.netloc and " " not in value.strip():
            return value.strip()
    raise AffiliationError("%s: career_services is true, or an https address (got %r); leave it out when there is none"
                           % (where, value))


def parse_entry(entry, where="affiliations[0]"):
    """One entry in the stored form (keys in KEYS order, absent optional keys left out), or raises AffiliationError."""
    if not isinstance(entry, dict):
        raise AffiliationError("%s must be an object {kind, name, linkedin_url?, career_services?}, not %s"
                               % (where, type(entry).__name__))
    unknown = sorted(k for k in entry if k not in KEYS)
    if unknown:
        raise AffiliationError("%s: unknown key(s) %s (known: %s)" % (where, ", ".join(map(repr, unknown)), ", ".join(KEYS)))
    kind = entry.get("kind")
    if kind not in KINDS:
        raise AffiliationError("%s: kind %r is not one of %s" % (where, kind, ", ".join(KINDS)))
    name = entry.get("name")
    if not isinstance(name, str) or not name.strip():
        raise AffiliationError("%s: name must be a non-empty string, as you write it" % where)
    out = {"kind": kind, "name": name}
    if "linkedin_url" in entry:
        try:
            out["linkedin_url"] = normalize_linkedin_url(entry["linkedin_url"])
        except AffiliationError as e:
            raise AffiliationError("%s: %s" % (where, e))
    if "career_services" in entry:
        out["career_services"] = _career_services(entry["career_services"], kind, where)
    return out


def parse(value):
    """The `affiliations` value in the stored form: a list (possibly empty) of entries, in the candidate's order. Raises
    AffiliationError on anything else: `null` is not absent, and a bare object is not a list of one."""
    if not isinstance(value, list):
        raise AffiliationError("affiliations must be a list of {kind, name, ...} (or [] for none, asked); got %s"
                               % ("null" if value is None else type(value).__name__))
    return [parse_entry(e, "affiliations[%d]" % i) for i, e in enumerate(value)]


def state(user):
    """`(NOT_ASKED, None)` when `user` (the user.json object) has no `affiliations` key, `(NONE, [])` for `[]`, and
    `(LISTED, entries)` otherwise, entries in the stored form. Raises AffiliationError on an unreadable value."""
    if not isinstance(user, dict):
        raise AffiliationError("user.json must be a JSON object")
    if "affiliations" not in user:
        return NOT_ASKED, None
    entries = parse(user["affiliations"])
    return (LISTED if entries else NONE), entries


def not_asked(user):
    """True when the candidate has never been asked (the key is absent). An unreadable value raises: it was asked."""
    return state(user)[0] == NOT_ASKED


def check(value):
    """The problems `validate_data` reports for a present `affiliations` value: the parser's refusal, or each stored address
    that is not in the stored form. An empty list means the value is clean."""
    try:
        entries = parse(value)
    except AffiliationError as e:
        return [str(e)]
    return ["affiliations[%d]: linkedin_url %r is not in the stored form %r; write the list with `record.py affiliations`"
            % (i, raw.get("linkedin_url"), e["linkedin_url"])
            for i, (raw, e) in enumerate(zip(value, entries))
            if "linkedin_url" in e and raw.get("linkedin_url") != e["linkedin_url"]]


def describe(kind, entries):
    """One line for a reader: what the state is, in words."""
    if kind == NOT_ASKED:
        return "not asked (no `affiliations` in user.json)"
    if kind == NONE:
        return "asked, none"
    return "%d listed: %s" % (len(entries), "; ".join("%s %s" % (e["kind"], e["name"]) for e in entries))
