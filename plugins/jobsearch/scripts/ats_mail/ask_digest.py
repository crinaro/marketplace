"""The asks the ATS sweep files: their ids, their dedup keys, their noise suppression and their text.

design-inbound-resolution.md §4.4: an ask is deduplicated by a key per ISO week, never by uid, and every further message
the key absorbs is appended to the ask's `note`, never a second row.

⭐ dev #1031 (public #266) — MAIL THAT MATCHED NO APPLICATION IS ONE QUESTION PER SENDER DOMAIN PER WEEK. The key used to
be (sender domain, normalized subject) for every kind, so a job-board or social digest, whose subject changes with every
send, filed one ask per message, all with the same title, none phrased as a question: 22 such rows produced 82 percent of
one profile's `check_sections` report (each row unphrased and read as a role item, every pair a duplicate). The kinds in
`AGGREGATED_KINDS` (an unmatched or unidentified message) are now keyed by the sender domain alone, so a week's mail from
one domain is one row whose note lists every message; the text asks the owner a question and names the config key, so
it reads as a system ask. A `proposed` status change still names one application and keeps its per-subject key.
Owner-approved shape (presence-report group): the id keeps its `ask-ats-<kind>-<hash>-<week>` form, so no migration.

A `resolution: noise` answer (dev #376 item 2) suppresses a future ask whose key matches the answered row's key: for an
aggregated kind that is the whole domain, and a row answered before this change (keyed by domain and subject) still
quiets exactly the subject it was answered for.
"""
import datetime
import hashlib
import re

AGGREGATED_KINDS = ("unresolved", "unidentified")
_SUBJECT_PREFIX_RE = re.compile(r"^\s*(re|fwd?)\s*:\s*", re.I)
_ASK_ID_RE = re.compile(r"^ask-ats-[a-z]+-([0-9a-f]{10})-\d{4}W\d{2}$")
CONFIG_KEY = "`ats.receipt_sender_domains` in config.json"


def normalize_subject(subject):
    """§4.4 — strip Re:/Fwd: prefixes, digits, and whitespace runs, for the dedup hash."""
    s = (subject or "").strip()
    while True:
        s2 = _SUBJECT_PREFIX_RE.sub("", s)
        if s2 == s:
            break
        s = s2
    s = re.sub(r"\d+", "", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def iso_week(date_iso):
    try:
        d = datetime.date.fromisoformat(str(date_iso)[:10])
    except ValueError:
        d = datetime.date.today()
    y, w, _wd = d.isocalendar()
    return "%04dW%02d" % (y, w)


def ask_key_hash(domain, subject):
    """The (domain, normalized subject) key's own hash, independent of `kind` and of the ISO week."""
    return hashlib.sha1(("%s|%s" % ((domain or "").lower(), normalize_subject(subject)))
                        .encode("utf-8")).hexdigest()[:10]


def digest_key(kind, domain, subject):
    """The dedup key's hash for `kind`: the domain alone for an aggregated kind (dev #1031), else domain and subject."""
    return ask_key_hash(domain, "" if kind in AGGREGATED_KINDS else subject)


def ask_key_hash_from_id(ask_id):
    """The key hash embedded in an `ask-ats-<kind>-<hash>-<week>` id, or None for any other id."""
    m = _ASK_ID_RE.match(ask_id or "")
    return m.group(1) if m else None


def is_digest_id(ask_id):
    """True for an id this module minted: two such rows are keyed apart by the engine's own dedup key."""
    return ask_key_hash_from_id(ask_id) is not None


def ask_digest_id(kind, domain, subject, date_iso):
    """§4.4 — one id per (kind, dedup key, ISO week)."""
    return "ask-ats-%s-%s-%s" % (kind, digest_key(kind, domain, subject), iso_week(date_iso))


def noise_suppressed(kind, domain, subject, asks):
    """True when an ask answered `noise` carries this message's key: the current key, or the legacy per-subject one."""
    keys = {digest_key(kind, domain, subject), ask_key_hash(domain, subject)}
    return any(a.get("resolution") == "noise" and ask_key_hash_from_id(a.get("id")) in keys for a in asks)


def ask_text(kind, domain, subject, company_name=None):
    """(title, ask) for a NEW ask of `kind`: a question to the owner, naming the sender domain."""
    first = (subject or "")[:60]
    if kind == "unresolved":
        return ("Mail from %s matched no live application this week: which one is it, or is it noise?" % domain,
                "Mail from %s this week could not be resolved to a live application (first: %r; every message is "
                "listed in this ask's note). Does it belong to one of your applications? Answer with the "
                "application, resolve this ask as noise to quiet the domain, or add it to %s if it is an ATS."
                % (domain, first, CONFIG_KEY))
    if kind == "unidentified":
        return ("Is %s the ATS for %s? Its mail is not from a configured domain" % (domain, company_name or domain),
                "Mail from %s this week (first: %r) names %s, a live application's company, but %s is not a "
                "configured or derived ATS domain. Is it that company's ATS? If so, add it to %s."
                % (domain, first, company_name or domain, domain, CONFIG_KEY))
    return ("Is the ATS status change from %s right?" % domain,
            "A parsed ATS status change from %s (%s) is proposed, not applied. Confirm whether it is right, or "
            "correct it." % (domain, first))
