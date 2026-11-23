"""requirement_rules: the checks on one `opportunities.fit.requirements[]` row, moved out of `validate_data._main`'s
fit block (design-presence-report.md §11 B1, "Files that may not grow": the two new keys' checks join the moved rows
and `_main` shrinks by the move) plus the two optional keys of §8.1:

  topic   must be its own `presence.skill_slugs.slug()` and match `TOPIC_RE`; legal on any verdict.
  claim   a non-empty string, legal only with `aligned` or `partial`. It is NOT re-checked against the claim union:
          a union edited after the write is a report state (§5.2), not a broken store. `record.py fit` checks it
          against the union at the moment of the write.

A null `topic` or `claim` is the same as an absent one."""

import re

from presence.skill_slugs import topic_refusal
from validation.basics import enum, is_date
from validation.vocab import FIT_Q_STATUS, FIT_VERDICTS

CLAIM_VERDICTS = ("aligned", "partial")


def check_requirement(q, rl, problems):
    """Append to `problems` every rule row `q` (labelled `rl`) breaks."""
    if not (q.get("requirement") or "").strip():
        problems.append("%s: empty 'requirement'" % rl)
    enum(q, "verdict", FIT_VERDICTS, rl, problems)
    enum(q, "question_status", FIT_Q_STATUS, rl, problems)
    # An alignment claim with no citation is a gap wearing a disguise.
    if q.get("verdict") in ("aligned", "partial") and not (q.get("evidence") or "").strip():
        problems.append("%s: verdict=%r requires 'evidence' — an uncited "
                        "alignment claim is not evidence of alignment"
                        % (rl, q.get("verdict")))
    # An unknown with no question is a gap nobody will ever close.
    # ⭐ act_by — added 2026-08-03. A question with a DATE is a different
    # object from one without. The candidate: "does the coordinator know to suggest a
    # draft a nudge to <a recruiter> for today?" It did not. <a recruiter>'s auto-reply
    # said she returns Monday August 3; that fact went into the question as
    # PROSE, and nothing can sort or surface prose. A date in a field can be.
    ab = q.get("act_by")
    if ab is not None and not re.match(r"^\d{4}-\d{2}-\d{2}$", str(ab)):
        problems.append("%s: act_by %r is not an ISO date" % (rl, ab))
    if q.get("verdict") == "unknown" and not (q.get("question_for_candidate") or "").strip():
        problems.append("%s: verdict='unknown' requires 'question_for_candidate' — "
                        "otherwise the gap is recorded and never harvested" % rl)
    if q.get("question_status") == "answered" and not (q.get("landed_in") or "").strip():
        problems.append("%s: question_status='answered' requires 'landed_in' "
                        "(projects.md / resume.md-addendum / resume.md / kb_<company>.md)" % rl)
    if q.get("answered_on") and not is_date(q.get("answered_on")):
        problems.append("%s: answered_on not ISO — %r" % (rl, q.get("answered_on")))
    check_presence_keys(q, rl, problems)


def check_presence_keys(q, rl, problems):
    """§8.1: the optional `topic` and `claim` of one requirement row."""
    topic = q.get("topic")
    if topic is not None:
        why = topic_refusal(topic)
        if why:
            problems.append("%s: %s" % (rl, why))
    claim = q.get("claim")
    if claim is not None:
        if not (isinstance(claim, str) and claim.strip()):
            problems.append("%s: claim must be a non-empty string (the union bullet, verbatim) — %r" % (rl, claim))
        elif q.get("verdict") not in CLAIM_VERDICTS:
            problems.append("%s: claim is legal only with verdict aligned or partial (verdict %r)"
                            % (rl, q.get("verdict")))
