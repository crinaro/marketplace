"""Delivery evidence and placeholder-address rules, and the introduced-only row rules a writer checks before it
writes (`row_rule_violations`).

Capability module of `validate_data.py` (S4a, moved unedited)."""

from validation.basics import date_part
from validation.vocab import COMMS_CUTOVER


# dev #427 — what counts as evidence that a pre-cutover delivery value was ESTABLISHED, not
# inferred. Substring match on the lowercased note, so "repl" covers reply/replied/auto-reply
# (a reply is conclusive proof of delivery); "auto-reply" stays listed so the message names it.
DELIVERY_EVIDENCE_WORDS = ("ndr", "bounce", "confirmed", "repl", "auto-reply")


def delivery_evidence(touch):
    """True when a touch carries evidence for a non-'unknown' delivery: a note naming how it
    was established, or a recorded reply (`responded_on` — the structured form of the same
    fact, which a run already knows and so must not have to restate in prose)."""
    if touch.get("responded_on"):
        return True
    note = (touch.get("note") or "").lower() if isinstance(touch.get("note"), str) else ""
    return any(w in note for w in DELIVERY_EVIDENCE_WORDS)


# RFC 2606 §3 reserves these three names so documentation and tests cannot collide with a real
# registrant. An address under one is a placeholder on EVERY install, never a person
# (owner decision A on dev #427, 2026-09-30). ⚠️ DELIBERATELY NOT the reserved TLDs (`.test`,
# `.invalid`, ...): the fixture's synthetic contacts live under `fixture.invalid`, which can
# never resolve to a real registrant yet is outside this set, so the rule and the fixture do not
# collide. The label match is a whole domain or a subdomain of it, never a substring
# (`counterexample.com` is not `example.com`).
PLACEHOLDER_EMAIL_DOMAINS = ("example.com", "example.net", "example.org")
# Template-shaped addresses — a literal pattern sitting in the structured field READS AS
# POPULATED to every query and to the dashboard (the 2026-08-03 incident the regression test's
# docstring names). Substring match on the lowercased address, as the test always did.
PLACEHOLDER_EMAIL_TEMPLATES = ("first.last@", "firstname.lastname@", "@company.com",
                               "@domain.com")


def placeholder_email_violation(email):
    """The refusal text for an address that is a placeholder, else None. Label-free, so the
    writer can compare the text before and after a change (see record.py)."""
    if not isinstance(email, str) or not email.strip():
        return None
    e = email.strip().lower()
    dom = e.rpartition("@")[2]
    reserved = any(dom == d or dom.endswith("." + d) for d in PLACEHOLDER_EMAIL_DOMAINS)
    if reserved or any(t in e for t in PLACEHOLDER_EMAIL_TEMPLATES):
        return ("email %r is a placeholder, not an address — empty is honest, a plausible fake "
                "is not (a reserved example domain or a first.last-style template)" % email)
    return None


def delivery_violation(touch):
    """dev #427 — DELIVERY IS EVIDENCE, NEVER INFERENCE. The refusal text when a pre-cutover
    touch carries a delivery value off 'unknown' with no cited evidence, else None."""
    d = date_part(touch.get("date"))
    if (touch.get("delivery") not in (None, "unknown") and d and d < COMMS_CUTOVER
            and not delivery_evidence(touch)):
        return ("delivery=%r on a row dated before %s with no evidence — a note citing how it "
                "was established (%s) or a recorded reply is required; delivery must never be "
                "inferred" % (touch.get("delivery"), COMMS_CUTOVER,
                              ", ".join(DELIVERY_EVIDENCE_WORDS)))
    return None


def _people_email_violation(person):
    return placeholder_email_violation(person.get("email"))


# store -> the rules that apply only to rows being WRITTEN or CHANGED (see the block above).
INTRODUCED_ONLY_RULES = {"touches": (delivery_violation,),
                         "people": (_people_email_violation,)}


def row_rule_violations(store, row):
    """Every introduced-only rule `row` violates, as label-free messages (possibly empty)."""
    if not isinstance(row, dict):
        return []
    return [m for m in (fn(row) for fn in INTRODUCED_ONLY_RULES.get(store, ())) if m]
