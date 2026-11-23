"""changes: the ONE reader of current state in `data/presence_changes.jsonl` (design-presence-report.md §8.2, §5.7).

The current value of a (target, field[, variant]) is the LAST row in file order that is `stated`, `observed`, or a
`decision` with `applied` (its `applied_value` when set, else its proposal's `value`). The decision's own position
decides, not the proposal's, and no date reorders anything: pc-7 a proposal for "B", pc-8 a restated "A", pc-9
`applied` for pc-7 gives "B". `refused` rows never carry a value and are ignored for it.

A gap key's status is that of the newest row carrying the key (a proposal or a refused row by its `gap`, a decision
through its proposal): `open`, `proposed pc-<n> since <date>`, `declined pc-<n> on <date>` or `refused pc-<n> on
<date>`. A key whose proposal was applied or superseded is `open` again while its condition remains; nothing marks a
gap done. Only an attended row clears `refused` (§R3-4): the next row for the key is the one that moves it.

Every function takes rows already read and checked, `validation/presence_rules.load_file` then `check_rows`, so a
reordered file is refused before any replay. The caller does both: importing `validation/` from here grows the
plugin's import cycle (G6). Nothing here reads a file or writes.

`document` rows (jobsearch 0.93.0, design-resume-docx.md §6.1) carry no value: `current` and `gap_state` never read
one. `document_row` builds one for the writer (`record.py presence-docx`, which mints its id and appends it), and
`newest_document` reads the team's last write or acceptance of a variant's Word file: the greatest `written_at`, a tie
going to the greater `machine` string with null lowest, then the greater id; never the line's position, so rows merged
from two machines in either order give the same answer (§3.2, §R2 S2-8). R3-1's ask, filed when a Word file's words
changed, is `asks.jsonl` id `resume-word-edited:<variant-id>` (`word_edited_ask_id`, `ask_variant`)."""

import datetime

from presence.store_rules import DOC_FIELDS, WRITTEN_AT_FORMAT, parse_written_at

VALUE_KINDS = ("stated", "observed")


def _proposals(rows):
    return {r.get("id"): r for r in rows if r.get("kind") == "proposal"}


def current(rows, target, field, variant_id=None):
    """`(value, row)` of the row that sets the current value, or `(None, None)` when nothing has."""
    props = _proposals(rows)
    found = (None, None)
    for r in rows:
        kind = r.get("kind")
        if kind in VALUE_KINDS:
            if (r.get("target"), r.get("field"), r.get("variant_id")) == (target, field, variant_id):
                found = (r.get("value"), r)
        elif kind == "decision" and r.get("decision") == "applied":
            p = props.get(r.get("proposal"))
            if p and (p.get("target"), p.get("field"), p.get("variant_id")) == (target, field, variant_id):
                found = (r["applied_value"] if r.get("applied_value") is not None else p.get("value"), r)
    return found


def decisions(rows):
    """`{proposal id: its decision row}`."""
    return {r.get("proposal"): r for r in rows if r.get("kind") == "decision"}


def open_proposals(rows):
    """The proposals with no decision, in file order."""
    decided = decisions(rows)
    return [r for r in rows if r.get("kind") == "proposal" and r.get("id") not in decided]


def gap_state(rows, key):
    """`(state, row)`: state one of open, proposed, declined, refused; `row` the proposal or refused row it names."""
    props = _proposals(rows)
    newest = None
    for r in rows:
        kind = r.get("kind")
        if kind in ("proposal", "refused") and r.get("gap") == key:
            newest = r
        elif kind == "decision" and props.get(r.get("proposal"), {}).get("gap") == key:
            newest = r
    if newest is None:
        return "open", None
    if newest.get("kind") == "refused":
        return "refused", newest
    if newest.get("kind") == "proposal":
        return "proposed", newest
    if newest.get("decision") == "declined":
        return "declined", props.get(newest.get("proposal"))
    return "open", None


def gap_status(rows, key):
    """§5.7's status text for a gap key."""
    state, row = gap_state(rows, key)
    if state == "proposed":
        return "proposed %s since %s" % (row["id"], row.get("created"))
    if state == "refused":
        return "refused %s on %s" % (row["id"], row.get("created"))
    if state == "declined":
        on = decisions(rows).get(row["id"], {}).get("created")
        return "declined %s on %s" % (row["id"], on)
    return "open"


HANDBACK_MARK = " [hand-back %s]"


def handback_note(reason, handback):
    """A `refused` row's note: the reason, then the hand-back path it was judged on (when one was given), so the path
    reads as consumed even when every line was refused (§R3-5). The row keeps exactly `gap` and `note`."""
    return reason + HANDBACK_MARK % handback if handback else reason


def consumed_by(rows, handback):
    """The id of the first stored row judged on the hand-back file `handback` (a proposal read from it, or a `refused`
    row whose note names it), or None."""
    mark = HANDBACK_MARK % handback
    for r in rows:
        if r.get("kind") == "proposal" and r.get("handback") == handback:
            return r.get("id")
        if r.get("kind") == "refused" and str(r.get("note") or "").endswith(mark):
            return r.get("id")
    return None


def next_id(rows):
    """The next `pc-<n>`: one above the highest stored."""
    nums = [int(str(r.get("id"))[3:]) for r in rows if str(r.get("id")).startswith("pc-") and str(r.get("id"))[3:].isdigit()]
    return "pc-%d" % ((max(nums) if nums else 0) + 1)


# ---- document rows (design-resume-docx.md §6.1) ----------------------------------------------------------------

def written_at_now(now=None):
    """A `written_at` stamp for `now` (an aware datetime; default the current instant), in UTC, to the second."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    if now.tzinfo is None:
        raise ValueError("written_at needs an aware datetime: a naive one names no instant")
    return now.astimezone(datetime.timezone.utc).strftime(WRITTEN_AT_FORMAT)


def document_row(variant_id, doc_op, file, doc_sha256, doc_text_sha256, source_sha256, ats, machine, written_at,
                 created, removed=(), added=(), note=None):
    """A `document` row with every §6.1 field, `id` None for the writer to mint. Builds; never checks: the writer runs
    `store_rules.check_rows` over the store plus this row before it appends, as every presence verb does."""
    row = {"id": None, "kind": "document", "created": created, "by": "session", "note": note,
           "target": "variant", "variant_id": variant_id}
    row.update(zip(DOC_FIELDS, (doc_op, file, doc_sha256, doc_text_sha256, source_sha256, list(ats), machine,
                                written_at, list(removed), list(added))))
    return row


def _id_num(row):
    s = str(row.get("id"))
    return int(s[3:]) if s.startswith("pc-") and s[3:].isdigit() else 0


def document_order(row):
    """The sort key that decides "newest" among `document` rows (§3.2): `written_at`, then `machine` (null lowest),
    then the id. Raises `ValueError` on an unreadable `written_at`: the store rules refuse such a row, and nothing
    orders it by guesswork."""
    machine = row.get("machine")
    return (parse_written_at(row.get("written_at")), machine is not None, machine or "", _id_num(row))


def document_rows(rows, variant_id):
    """The variant's `document` rows, oldest first by `document_order` (never by line position)."""
    return sorted((r for r in rows if r.get("kind") == "document" and r.get("variant_id") == variant_id),
                  key=document_order)


def newest_document(rows, variant_id, doc_op=None):
    """The variant's newest `document` row (of `doc_op` when given), or None when it has none."""
    found = [r for r in document_rows(rows, variant_id) if doc_op is None or r.get("doc_op") == doc_op]
    return found[-1] if found else None


def updates_since_adopt(rows, variant_id):
    """The variant's `update` rows newer than its newest `adopt` row (all of them when it has none), oldest first:
    the rows whose `removed` and `added` the stale-save test reads (§3.2)."""
    docs = document_rows(rows, variant_id)
    last_adopt = max((i for i, r in enumerate(docs) if r.get("doc_op") == "adopt"), default=-1)
    return [r for r in docs[last_adopt + 1:] if r.get("doc_op") == "update"]


WORD_EDITED_ASK = "resume-word-edited:"


def word_edited_ask_id(variant_id):
    """R3-1's ask id for a variant whose Word file's words changed: one open ask per variant, replaced by id."""
    return WORD_EDITED_ASK + variant_id


def ask_variant(ask_id):
    """The variant id R3-1's ask `ask_id` names; raises `ValueError` on an id that is not one; `--answer` refuses it."""
    if not (isinstance(ask_id, str) and ask_id.startswith(WORD_EDITED_ASK) and len(ask_id) > len(WORD_EDITED_ASK)):
        raise ValueError("%r is not a %s<variant-id> ask id" % (ask_id, WORD_EDITED_ASK))
    return ask_id[len(WORD_EDITED_ASK):]
