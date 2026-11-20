"""The `trigger` object check shared by stores that carry one.

Capability module of `validate_data.py` (S4a, moved unedited)."""

from validation.basics import is_date
from validation.vocab import INTRODUCTION_REF_PREFIXES, TRIGGER_KINDS


def check_trigger(row, label, problems, app_refs, sent_ids, touch_ids=None, commitment_ids=None):
    """The trigger pair on an outreach row or an ask (public #27). Shared so the two call
    sites cannot drift. `app_refs` is the set of resolvable application handles for the
    record the trigger belongs to (app_id values plus dates, own-record rule); `sent_ids`
    is the message-id set for 'reply' refs. Absent pair: legal (history predates the field).
    Half a pair, a kind outside the enum, or a dangling ref: LOUD — an unreadable trigger
    looks handled and is not (the precondition.py rule).

    dev #834 (design-network-first.md 5.4): kind `introduction` carries a PREFIXED ref, `touch:<id>` or `commitment:<id>`, because an
    introduction has two possible causes (the touch that asked for it, or a chat that offered it); the prefix is resolved against
    `touch_ids` / `commitment_ids` (the id sets of the two stores). A set passed as None is not known to the caller and is not checked;
    any other form of ref is refused."""
    tk, tr = row.get("trigger_kind"), row.get("trigger_ref")
    if tk is None and tr is None:
        return
    if tk is None:
        problems.append("%s: trigger_ref %r without trigger_kind — half a trigger cannot be "
                        "resolved and must not look like one" % (label, tr))
        return
    if tk not in TRIGGER_KINDS:
        problems.append("%s: trigger_kind %r not in {%s}" % (label, tk,
                        ", ".join(sorted(TRIGGER_KINDS))))
        return
    if tk == "manual":
        if tr is not None:
            problems.append("%s: trigger_kind 'manual' with trigger_ref %r — manual means no "
                            "recorded cause; a ref here is a contradiction, name the real kind"
                            % (label, tr))
        return
    if not (isinstance(tr, str) and tr.strip()):
        problems.append("%s: trigger_kind %r requires a non-empty trigger_ref" % (label, tk))
        return
    if tk == "application" and tr not in app_refs:
        problems.append("%s: trigger_ref %r resolves to no applications[] row on this record "
                        "(by app_id or date) — a trigger naming an application that is not "
                        "there is the unlinked-draft defect inverted" % (label, tr))
    elif tk == "reply" and tr not in sent_ids:
        problems.append("%s: trigger_ref %r resolves to no message in data/messages.jsonl"
                        % (label, tr))
    elif tk == "elapsed" and not is_date(tr):
        problems.append("%s: trigger_kind 'elapsed' requires an ISO date trigger_ref (the day "
                        "the clock started), got %r" % (label, tr))
    elif tk == "introduction":
        prefix, _sep, rest = tr.partition(":")
        if prefix not in INTRODUCTION_REF_PREFIXES or not rest.strip():
            problems.append("%s: trigger_kind 'introduction' requires trigger_ref 'touch:<id>' or 'commitment:<id>' "
                            "(the touch that asked for it, or the chat that offered it), got %r" % (label, tr))
        else:
            known = touch_ids if prefix == "touch" else commitment_ids
            if known is not None and rest not in known:
                problems.append("%s: trigger_ref %r resolves to no %s record — an introduction names the touch or "
                                "the chat it came of" % (label, tr, "touches" if prefix == "touch" else "commitments"))
