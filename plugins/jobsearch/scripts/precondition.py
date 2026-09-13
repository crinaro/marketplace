#!/usr/bin/env python3
"""A draft's send-precondition, as data instead of prose. Resolves against the pipeline.

⭐ THE DEFECT THIS CLOSES (GitHub issue #6)
-------------------------------------------
A multi-part sequence stages part A (sent) and part B (held until the recipient accepts or
replies). The precondition on part B lived in `**Status:**` prose, so **the dashboard rendered
every staged draft under a heading meaning "awaiting your approval to send"** — including the ones
the candidate cannot act on at all. One observed state: seven items presented as needing them, one
genuinely actionable.

That inverts the surface. The decision surface's invariant is that a Your Move line must read as a question
or an imperative aimed at the candidate, and **a draft that cannot be sent yet is neither**. The
predictable result is that the candidate learns to skim the one list that is supposed to be unskippable.

⭐⭐ AND THE DATA WAS ALREADY THERE. Every outreach touch carries `outcome`
(awaiting/accepted/replied/…), `responded_on`, `contact_id` and `message_ref`. The system could
always answer *"has this person accepted or replied?"* — what was missing was any machine-readable
link from the draft to the touch it waits on. **A missing join, not missing information**, which
is why this is cheap to fix and expensive to leave.

## The general rule this is the first instance of

    ⭐ A FACT A RUN KNOWS GOES INTO THE QUERYABLE STORE, NEVER INTO NARRATIVE.

Issues #4 and #5 are the same defect in different clothes — a coverage gap in a run-log narrative,
a run's findings in a session buffer that never reaches disk. The engine has solved it once before:
open fit questions carried urgency in prose until `act_by` made it a sortable field. This module is
that move applied to drafts, and the shape is meant to be copied rather than re-invented.

## The field

One meta line in the draft entry, alongside `**Medium:**` and the rest:

    **Blocked until:** contact:dana-holbrook outcome:accepted|replied

`contact:` is a `contact_id` as it appears in `contacts[]`. `outcome:` is one or more values from
the outreach outcome enum, `|`-separated. The draft is **sendable** when any outreach touch to that
contact has one of those outcomes.

⚠️ **An unparseable value is reported, never guessed.** A precondition nobody can read is worse
than none: it looks handled and is not. `--check` fails on one, so a typo surfaces at run start
rather than by a draft silently sitting in the wrong group.

## ⭐ THE LEGACY PROSE FORM IS DETECTED, NEVER TREATED AS ABSENT (GitHub issue #13)

The first release of this module shipped the field with no migration and no enforcement, so a
profile predating it kept its preconditions in prose — and this tool reported every one of those
drafts **sendable, "no precondition"**. Four drafts saying *in their own titles* that they were
held pending someone's acceptance rendered as `9 sendable, 0 blocked`. A false green is worse
than the prose it replaced, because it stops anyone looking.

The root error: "no draft is blocked" and "no draft has been migrated" are opposite states, and
absence-of-field rendered them identically. So now:

- a draft whose text carries a **hold phrase** (`HOLD_RE`) but no structured field is state
  `unresolved` — a migration gap, named as such, never sendable;
- `**Blocked until:** unresolved`, which `migrate.py`'s 0.18.0 migration writes under each
  detected prose hold, is the same state as durable data rather than a heuristic re-match;
- `--check` fails on `unresolved` exactly as on `unreadable`, and the summary reports the count.

The way out of `unresolved` is a human (or the drafting agent) replacing it with the real join:
`contact:<contact_id> outcome:<...>` — or, for a false positive, rewording the prose. The
default direction is deliberate: the cheap error is a draft waiting for a look, the expensive
one is a blocked draft presented as actionable.

## ⭐ A TERMINAL STATUS ENDS AN ENTRY — IT MUST NOT NEED A SECOND STEP (public #29)

The panel derivation used to answer one question only — *is this blocked on someone else?* — and
never asked whether the entry was **already over**. A draft's `**Status:**` line already carries
that fact (`SENT 2026-08-20 — remove at next weekly pass`, `MOOT / DO-NOT-SEND — role closed`),
written by the send-recording flow or by whoever decided the role was dead — but nothing here
read it, so a sent or moot entry kept reporting `state: sendable, "no precondition"` and rendered
under Ready to send forever, exactly like a genuinely pending message. The **removal** side of
the bug was the same shape as issue #6's "needs a second, separate step" failure: retiring the
markdown entry was left to a later weekly pass, and a moot outcome had no removal path AT ALL.

The fix does not add a removal step — it removes the NEED for one. `TERMINAL_RE` recognises the
Status line's own terminal words and reports `state: "sent"` / `"moot"` directly, so a consumer
that excludes `TERMINAL` from what it renders is derived, not maintained: the entry disappears
from the queue the moment its own Status line says it is done, with no second write required.
The physical markdown entry may still be cleaned up later (or never) — it no longer matters,
because nothing that reads `precondition.report()` is fooled by its presence.

⚠️ **Deliberately conservative on SENT.** `SENT_RE` only matches a Status line that STARTS with
`sent` — never one that merely CONTAINS it. "PART A SENT · part B pending" is a legitimate,
still-actionable mid-sequence state (`check_sent_drafts.py`'s own docstring names it), and must
keep rendering; only a status that OPENS with "sent" is asserting the whole entry is done.

## ⭐ COVER LETTERS ARE COVERED TOO — THE PAIR IS A PAIR EVERYWHERE (dev #169)

This module originally parsed `drafts.md` alone, while `check_sent_drafts.py` and the dashboard
treated `drafts.md` / `cover_letters.md` as siblings. The consequence was the dangerous half of
that asymmetry: **a cover letter carrying a send-hold rendered as READY** on the one artifact
that leaves the building — not blocked, not an error, ready. `FILES` below owns the pair;
`report()` walks every file in it and tags each row with `file`, so consumers group per file
instead of assuming everything is a draft. The loudness rules are identical for both files: a
prose hold is `unresolved`, an unreadable field is `unreadable`, and `--check` fails on either
wherever it lives.

Usage:
    python3 precondition.py            # every entry: sendable / blocked / unresolved / unreadable
    python3 precondition.py --json
    python3 precondition.py --check    # exit 1 on an unparseable or unresolved precondition

Python 3.9+. Standard library only.
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _root import profile_root
import _tree

FIELD_RE = re.compile(r"^\*\*Blocked until:\*\*\s*(.+?)\s*$", re.M | re.I)
TOKEN_RE = re.compile(r"(contact|outcome)\s*:\s*([A-Za-z0-9_|-]+)")

# The literal the migration writes when it finds a prose hold it cannot structure itself.
UNRESOLVED_RE = re.compile(r"^unresolved\b", re.I)

# public #29 — the entry's OWN `**Status:**` line, read for a TERMINAL outcome. Conservative on
# purpose (see the module docstring): SENT_RE anchors to the START of the status text so a
# mid-sequence "PART A SENT · part B pending" note is never swept up with a truly-done entry.
STATUS_RE = re.compile(r"^\*\*Status:\*\*\s*(.+?)\s*$", re.M | re.I)
SENT_RE = re.compile(r"^\s*sent\b", re.I)
MOOT_RE = re.compile(r"\bmoot\b|\bdo[\s-]*not[\s-]*send\b", re.I)

# The legacy prose forms actually observed in the field (issue #13: "held until she accepts",
# "held until each accepts", "still pending her acceptance") plus their near neighbours.
# Deliberately pronoun-restricted so a drafted message ADDRESSED to the recipient ("once you
# accept") does not trip it; a false positive only parks a draft as `unresolved` for a look,
# while a false negative reproduces the false green this exists to close.
HOLD_RE = re.compile(
    r"\bheld\s+(?:until|pending)\b"
    r"|\bhold\s+until\b"
    r"|\bpending\s+(?:[\w'’]+\s+){0,3}?acceptance\b"
    r"|\bawaiting\s+(?:[\w'’]+\s+){0,2}?acceptance\b"
    r"|\b(?:until|once)\s+(?:she|he|they|each|either|both|the\s+recipient)\s+"
    r"(?:accepts?|replies|responds?)\b",
    re.I)

# States that must NEVER render as "needs you". Owned here so consumers (generate_dashboard.py)
# group by membership instead of re-deriving the set — `state != "blocked"` was how `unreadable`
# drafts ended up under "awaiting your approval to send".
#
# ⭐ Query or Citation C1 (design-query-or-citation.md §3.5) — six states join this set, from
# `brief.verdict()`: `unaddressed`/`unbriefed`/`brief-mismatch`/`stale-brief` (NEEDS_HUMAN, below)
# and `unverified-cold`/`unverified-silent` (WAITS_ON_SURFACE, below — neither owner nor other
# side: the draft waits for a session with a keychain).
NOT_SENDABLE = frozenset({"blocked", "unreadable", "unresolved", "sent", "moot",
                          "unaddressed", "unbriefed", "brief-mismatch", "stale-brief",
                          "unverified-cold", "unverified-silent"})

# public #29 — states that are OVER, not merely un-sendable: a "blocked" entry still needs a
# human's eyes when its precondition clears, but a "sent"/"moot" one needs nothing further from
# anyone. A consumer that renders "awaiting your approval" work excludes TERMINAL entirely
# (never lumps them under "blocked", which reads as "blocked on someone else" and would mislead).
TERMINAL = frozenset({"sent", "moot"})

# ⭐ dev/audit 2026-09-02 (public #37) — NOT_SENDABLE is not one thing. `blocked` waits on
# the OTHER side; `unreadable` and `unresolved` wait on the OWNER, because nobody can say what
# the hold even is. The dashboard grouped all three under "waiting on someone else", so a
# precondition nobody could read sat in the muted in-flight count looking handled. A consumer
# renders NEEDS_HUMAN as a loud needs-you set and counts it there. (Declined: widening the
# vocabulary so those rows parse — a strict parser IS the design; the fix is loudness.)
NEEDS_HUMAN = frozenset({"unreadable", "unresolved",
                         "unaddressed", "unbriefed", "brief-mismatch", "stale-brief"})

# ⭐ Query or Citation C1 (D8) — the THIRD render class the shipped code did not have: neither
# "needs you" nor "waiting on the other side", but waiting for a SESSION WITH A CAPABILITY (a
# keychain-holding surface that can actually run the mailbox probe). Rendering these as muted
# "waiting" recreates public #37's failure for a state that is not in either dict; rendering
# them as NEEDS_HUMAN would send the owner chasing something only a different surface can do.
WAITS_ON_SURFACE = frozenset({"unverified-cold", "unverified-silent"})

# ⭐ The states an entry can be in while STILL QUEUED — everything report() emits except the
# TERMINAL pair. The dashboard's drafts and cover-letter lists filter on this vocabulary
# (public #48, stage 1): sendable rows await the owner, blocked rows wait on the other side,
# unreadable/unresolved rows wait on the owner to rewrite the hold. One list per file, one
# dimension, this set — the "Waiting on someone else" and "held" sections it replaces were
# the same entries rendered under a second heading.
OPEN_STATES = frozenset({"sendable"}) | (NOT_SENDABLE - TERMINAL)

# ⭐ THE one definition of "an entry" in the staged pair: a `## ` heading and everything up to
# the next one. drafts_with_preconditions, entry_media and migrate.py's medium-line relocation
# (0.37.0) all split on this — three walkers that split differently would disagree about which
# entry a line belongs to, which is the "absorbed into the previous draft" failure the file's
# own header warns about.
ENTRY_RE = re.compile(r"^##\s+(.+?)$(.*?)(?=^##\s|\Z)", re.M | re.S)

# The entry's own `**Medium:**` line, read for the FIRST value from validate_data.MEDIA it
# carries. The line is free text in the field ("linkedin-connection-note + linkedin-message
# (held until each accepts)", "email-reply (into the existing thread — ...)"), so the first
# enum token is the medium of the touch the entry opens with; a line naming no enum value at
# all — or no line — is `unknown`, which MEDIA itself reserves for exactly that, and the
# dashboard flags it on the row rather than guessing.
#
# ⭐ 0.37.0 (dev #265, first instance) — the label's bold may close after the label
# (`**Medium:** value`) OR after the value (`**Medium: value**`); a model writing the line
# does both. The two forms differ ONLY in where the bold-close falls, and the relax was
# approved on the condition that validation strength is unchanged, so everything else is
# identical in both: the line-start anchor and the literal `**Medium:` label (a token in
# prose, or a labelled fragment inside another field's value, is still prose), one value
# region per line (the text after the label, or the bold's interior — never text after the
# close), and the same first-vocabulary-token selection over it. TestMediumLineBoldForms
# holds every refusal the strict form made, each failed on purpose before landing.
MEDIUM_RE = re.compile(
    r"^\*\*Medium:(?:\*\*\s*(?P<after>.+?)|[ \t]*(?P<within>[^*\n]*?)\*\*.*?)\s*$",
    re.M | re.I)


# validate_data.MEDIA, mirrored as a literal for the same reason OUTCOMES is below: this
# module must run on a profile with no user.json (`precondition.py --check` at run start),
# and importing validate_data reads the owner token at import time. test_checks.py asserts
# the two sets are identical, so the copy cannot drift.
MEDIA = frozenset({"linkedin-connection-note", "linkedin-inmail", "linkedin-message",
                   "email-cold", "email-reply", "phone", "sms", "other", "unknown"})


def medium_of(body):
    """validate_data.MEDIA value for a drafts.md / cover_letters.md entry body."""
    m = MEDIUM_RE.search(body or "")
    if not m:
        return "unknown"
    text = (m.group("after") or m.group("within") or "").lower()
    hits = []
    for tok in MEDIA:
        for mm in re.finditer(r"(?<![a-z0-9-])%s(?![a-z0-9-])" % re.escape(tok), text):
            hits.append((mm.start(), tok))
    return min(hits)[1] if hits else "unknown"


# Sentinels used by drafts_with_preconditions for the non-parse states (see its docstring).
PROSE_HOLD = "prose-hold"
UNRESOLVED = "unresolved"
SENT = "sent"
MOOT = "moot"


class BriefHold(object):
    """Query or Citation C1 — wraps one of `brief.verdict()`'s six states
    (`unaddressed`/`unbriefed`/`brief-mismatch`/`stale-brief`/`unverified-cold`/
    `unverified-silent`) so `report()` can tell it apart from a `**Blocked until:**` parse
    result without a fifth string sentinel colliding with PROSE_HOLD/UNRESOLVED/SENT/MOOT."""
    __slots__ = ("state", "why")

    def __init__(self, state, why):
        self.state = state
        self.why = why


def _brief_state(root, title, body):
    """The brief-side draft state, or `None` (falls through to the `**Blocked until:**` logic
    below — unchanged). `brief.py` is imported LAZILY, inside this function, never at this
    module's top level: `brief.py` itself imports `precondition` for the entry-parsing
    primitives below (`FILES`, `ENTRY_RE`, `medium_of`, …), and a top-level import in both
    directions is a cycle. `precondition.py` stays the single owner of sendability —
    `report()` is the only caller of this function; `brief.verdict()` is never called from
    anywhere else in this module."""
    import brief as _brief
    return _brief.verdict(root, title, body)

# ⭐ The staged-message pair, owned HERE (dev #169). check_sent_drafts.py already treats these
# two as siblings; this module and the dashboard did not, which is exactly how a held cover
# letter rendered as ready. Anything that consumes preconditions iterates THIS tuple rather
# than assuming drafts.md. Since the 0.32.0 tree migration (public #28) the pair lives under
# its phases; `_tree.resolve_rel` falls back to the legacy root location on an unmigrated
# profile, and the `file` label on every row carries THESE canonical names on both shapes.
FILES = (_tree.rel("drafts"), _tree.rel("cover_letters"))

# The outreach outcome enum, mirrored from validate_data. Kept as a literal so a precondition
# naming a value that does not exist is caught here rather than resolving to "never satisfied".
OUTCOMES = {"awaiting", "accepted", "replied", "no-response", "declined", "meeting-booked"}


class PreconditionError(ValueError):
    """Unparseable. Deliberately loud — see the module docstring."""


def parse(raw):
    """'contact:x outcome:accepted|replied' -> {'contact': 'x', 'outcomes': {...}}"""
    found = dict(TOKEN_RE.findall(raw or ""))
    contact = found.get("contact")
    outcomes = {o for o in (found.get("outcome") or "").split("|") if o}
    if not contact:
        raise PreconditionError("no `contact:<contact_id>` in %r" % raw)
    if not outcomes:
        raise PreconditionError("no `outcome:<value>` in %r" % raw)
    bad = outcomes - OUTCOMES
    if bad:
        raise PreconditionError(
            "outcome %s is not in the enum {%s} — a value that cannot occur means the draft is "
            "blocked forever and nothing will say so"
            % (", ".join(sorted(bad)), ", ".join(sorted(OUTCOMES))))
    return {"contact": contact, "outcomes": outcomes}


def touches_by_contact(root):
    """person_id -> [outreach rows], across every opportunity (ADR-031 B1 — the join is
    `outreach[].person_id` now; the `contact:<id>` PROSE GRAMMAR keyword is unchanged, since
    it names a role in the sentence, not the JSON field it resolves against)."""
    out = {}
    path = os.path.join(root, "data", "opportunities.jsonl")
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                for o in r.get("outreach") or []:
                    cid = o.get("person_id")
                    if cid:
                        out.setdefault(cid, []).append(o)
    except OSError:
        pass
    return out


def resolve(pre, touches):
    """Satisfied? Returns (bool, evidence_or_reason). Evidence names WHICH touch satisfied it."""
    rows = touches.get(pre["contact"]) or []
    if not rows:
        return False, "no outreach touch to %r yet" % pre["contact"]
    for o in rows:
        if o.get("outcome") in pre["outcomes"]:
            return True, "%s outcome=%s on %s" % (pre["contact"], o.get("outcome"),
                                                  o.get("responded_on") or o.get("date") or "?")
    have = sorted({str(o.get("outcome")) for o in rows})
    return False, "%s has %s; waiting for %s" % (pre["contact"], "/".join(have),
                                                 "|".join(sorted(pre["outcomes"])))


def drafts_with_preconditions(root, filename=None):
    """[(title, raw_or_None, parsed)] for every '## ' entry, where parsed is one of:

        None               no field, no hold phrase — genuinely sendable
        PROSE_HOLD         no field, but the text carries a hold phrase — the legacy prose
                           form of issue #13; a migration gap, never sendable
        UNRESOLVED         a `**Blocked until:** unresolved …` marker (what the migration
                           writes) — known blocked, join not yet structured
        SENT               the entry's own `**Status:**` line OPENS with "sent" — done,
                           terminal (public #29)
        MOOT               the entry's own `**Status:**` line names it moot / do-not-send —
                           done, terminal (public #29)
        PreconditionError  a field nobody can read — loud, never guessed over
        dict               a parsed precondition, ready for resolve()
        BriefHold          Query or Citation C1 — one of brief.verdict()'s six states
                           (drafts.md ONLY — cover_letters.md is exempt, §3.4)
    """
    filename = filename or FILES[0]
    path = _tree.resolve_rel(root, filename)
    try:
        with open(path, encoding="utf-8") as fh:
            md = fh.read()
    except OSError:
        return []
    out = []
    for m in ENTRY_RE.finditer(md):
        title, body = m.group(1).strip(), m.group(2)
        # public #29 — a TERMINAL Status wins outright, before any Blocked-until join is even
        # considered: a sent or moot entry is over regardless of what it was once waiting on.
        sm = STATUS_RE.search(body)
        if sm:
            status_text = sm.group(1)
            if SENT_RE.match(status_text):
                out.append((title, status_text, SENT))
                continue
            if MOOT_RE.search(status_text):
                out.append((title, status_text, MOOT))
                continue
        # Query or Citation C1 (§3.4) — the brief-side gate outranks the Blocked-until join: an
        # entry that names no recipient, or cites no current brief, cannot even be asked whether
        # an outreach touch resolved its hold. `cover_letters.md` is exempt (a cover letter is
        # addressed to an application, not a person; §3.4).
        if filename == FILES[0]:
            bstate = _brief_state(root, title, body)
            if bstate:
                out.append((title, None, BriefHold(bstate[0], bstate[1])))
                continue
        fm = FIELD_RE.search(body)
        if not fm:
            if HOLD_RE.search(title) or HOLD_RE.search(body):
                out.append((title, None, PROSE_HOLD))
            else:
                out.append((title, None, None))
            continue
        raw = fm.group(1)
        if UNRESOLVED_RE.match(raw):
            out.append((title, raw, UNRESOLVED))
            continue
        try:
            out.append((title, raw, parse(raw)))
        except PreconditionError as e:
            out.append((title, raw, e))
    return out


def report(root, filenames=FILES):
    """Rows for every entry in every file of the pair. Each row carries `file` (dev #169) so a
    consumer groups per file — two files can legitimately hold same-titled entries."""
    touches = touches_by_contact(root)
    rows = []
    for filename in filenames:
        media = entry_media(root, filename)
        start = len(rows)
        for title, raw, parsed in drafts_with_preconditions(root, filename):
            if parsed is None:
                rows.append({"file": filename, "title": title, "state": "sendable",
                             "why": "no precondition"})
            elif isinstance(parsed, BriefHold):
                rows.append({"file": filename, "title": title, "state": parsed.state,
                             "why": parsed.why})
            elif parsed is PROSE_HOLD:
                rows.append({"file": filename, "title": title, "state": "unresolved",
                             "why": "hold phrase in prose but no structured precondition — the "
                                    "pre-0.18.0 form; write `**Blocked until:** contact:<id> "
                                    "outcome:<...>` (or reword the prose if it is not a hold)"})
            elif parsed is UNRESOLVED:
                rows.append({"file": filename, "title": title, "state": "unresolved",
                             "why": "known blocked, precondition not yet structured (%s) — replace "
                                    "with `contact:<id> outcome:<...>`" % raw})
            elif parsed is SENT:
                rows.append({"file": filename, "title": title, "state": "sent",
                             "why": "Status line reports it sent (%s) — terminal, no longer "
                                    "queued" % raw})
            elif parsed is MOOT:
                rows.append({"file": filename, "title": title, "state": "moot",
                             "why": "Status line reports it moot / do-not-send (%s) — terminal, "
                                    "no longer queued" % raw})
            elif isinstance(parsed, PreconditionError):
                rows.append({"file": filename, "title": title, "state": "unreadable",
                             "why": str(parsed)})
            else:
                ok, why = resolve(parsed, touches)
                rows.append({"file": filename, "title": title,
                             "state": "sendable" if ok else "blocked", "why": why})
        for r in rows[start:]:
            r["medium"] = media.get(r["title"], "unknown")
    return rows


def entry_media(root, filename=None):
    """{title: validate_data.MEDIA value} for every '## ' entry in one file of the pair —
    the same split drafts_with_preconditions uses, so the two cannot disagree on what an
    entry is."""
    filename = filename or FILES[0]
    path = _tree.resolve_rel(root, filename)
    try:
        with open(path, encoding="utf-8") as fh:
            md = fh.read()
    except OSError:
        return {}
    out = {}
    for m in ENTRY_RE.finditer(md):
        out[m.group(1).strip()] = medium_of(m.group(2))
    return out


# ── States & Views V1b (design-states-and-views.md §4) — the GENERATED preamble ────────────
#
# The header used to be free prose someone maintained by hand. §4's own rule: "the header
# becomes generated ... a header that cannot drift from the parser cannot regrow into
# documentation." This marker is what makes "generated" and "not yet migrated" TWO DIFFERENT
# states rather than one — the same discipline issue #13 gave PROSE_HOLD vs UNRESOLVED: a
# profile that predates this migration has no marker at all, which is not itself a defect;
# a marker whose body no longer matches what the parser generates TODAY is (public #29's own
# "a missing thing reads as an empty thing" trap, applied to a header instead of a field).
GENERATED_MARKER = "<!-- GENERATED by precondition.py --format — do not hand-edit; see below -->"


def format_header():
    """§4 row 5 — the drafts.md preamble, generated from the parser's OWN constants (MEDIA,
    the meta-line grammar, OPEN_STATES/TERMINAL) rather than typed prose. This is the exact
    text `m_0_47_0_drafts_working_set` writes as the new preamble and `--format` prints;
    `draft_checks()` compares the live file's preamble against this, byte for byte after
    stripping trailing newlines, to catch a hand edit (a header that cannot drift cannot
    regrow into documentation)."""
    lines = [
        "# drafts.md — the working set (design-states-and-views.md §4)",
        "",
        GENERATED_MARKER,
        "",
        "This file holds ONLY entries under review right now: sendable, blocked on someone",
        "else, or needing you to resolve a precondition. A sent or moot entry is pruned on the",
        "next `precondition.py --prune` — its fact lives in `data/opportunities.jsonl`",
        "(`research_log[]`) or `data/channels.jsonl` (`log[]`), never here twice.",
        "",
        "Meta lines, one per entry (a `## <title>` heading, then indented lines below it):",
        "",
        "  **To:**            contact:<person-id> | unaddressed",
        "  **Medium:**        one of {%s}" % ", ".join(sorted(MEDIA)),
        "  **Blocked until:** contact:<person-id> outcome:<value>[|<value>...] | unresolved",
        "  **Triggered by:**  opp:<id> [app:<id>] | reply:<message-id> | elapsed:<date> | manual",
        "  **Brief:**         brief:<id>",
        "  **Status:**        SENT <date> | MOOT / DO-NOT-SEND — <reason>",
        "",
        "Open states (stay here): %s" % ", ".join(sorted(OPEN_STATES)),
        "Terminal states (pruned by --prune): %s" % ", ".join(sorted(TERMINAL)),
        "",
    ]
    return "\n".join(lines) + "\n"


def _preamble_text(md):
    """The text before the first `## ` heading — the whole file when there is none."""
    m = re.search(r"^##\s", md or "", re.M)
    return md[:m.start()] if m else (md or "")


def draft_checks(root):
    """§4's own red conditions, checked as data rather than left to a reader noticing:

    - a TERMINAL entry (sent/moot) still sitting in drafts.md — it should have been
      `--prune`d;
    - the generated preamble has been hand-edited (regrown into prose).

    Scoped to drafts.md (`FILES[0]`) only: §4 is drafts.md's own working-set rule ("`drafts.md`
    becomes the working set and nothing else") — a cover letter's terminal state already lives
    on its own `cover_letters.jsonl` row (ADR-031 B2) and is unaffected by this design."""
    problems = []
    filename = FILES[0]
    path = _tree.resolve_rel(root, filename)
    try:
        with open(path, encoding="utf-8") as fh:
            md = fh.read()
    except OSError:
        md = ""
    pre = _preamble_text(md)
    if GENERATED_MARKER in pre and pre.rstrip("\n") != format_header().rstrip("\n"):
        problems.append(
            "%s: the generated preamble has been hand-edited — regenerate it with "
            "`precondition.py --format` rather than editing it directly (design §4: a "
            "header that cannot drift from the parser cannot regrow into documentation)"
            % filename)
    for r in report(root, filenames=(filename,)):
        if r["state"] in TERMINAL:
            problems.append(
                "%s: %r is a TERMINAL entry (%s) still in the file — run `--prune` to "
                "relocate it to the record (design §4)"
                % (filename, r["title"][:60], r["state"]))
    return problems


# ── §4's tombstone relocation — the shared decision core for `--prune` and the migration ───

# "SENT 2026-08-20 — ..." / "sent 2026-08-20" — the date the entry's own Status line names,
# when it has one (a MOOT entry's status rarely carries a date at all).
_STATUS_DATE_RE = re.compile(r"\bsent\s+(\d{4}-\d{2}-\d{2})", re.I)


def _load_jsonl_rows(root, name):
    out = []
    try:
        with open(os.path.join(root, "data", name), encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def _opp_anchor(root, body):
    """The opportunity id a `**Triggered by: opp:<id>**` line names, but ONLY when that id
    actually resolves in `opportunities.jsonl` — an id that does not resolve is exactly as
    unusable as no anchor at all, and must not be guessed over. `trigger.py` is imported
    LAZILY: it imports `precondition` at its own top level, so a top-level import here would
    cycle (the same reason `_brief_state` imports `brief.py` lazily)."""
    import trigger as _trigger
    m = _trigger.TRIGGER_FIELD_RE.search(body or "")
    if not m:
        return None
    try:
        t = _trigger.parse_trigger(m.group(1))
    except _trigger.TriggerError:
        return None
    opp_id = t.get("opp")
    if not opp_id:
        return None
    if any(o.get("id") == opp_id for o in _load_jsonl_rows(root, "opportunities.jsonl")):
        return opp_id
    return None


def _to_person(root, body):
    """The person id a `**To:**` line resolves to, or None — `brief.py`'s own resolver,
    reused rather than re-derived (lazy import, same cycle-avoidance reason as above)."""
    import brief as _brief
    raw = _brief.parse_to(body)
    if raw is None:
        return None
    pid, ok, _why = _brief.resolve_to(root, raw)
    return pid if ok else None


def _channel_anchor(root, person_id):
    """A channel this person is involved in with NO opportunity anchor at all — a
    relationship contact, §4's 'the channel's log[] for channel-anchored ones'. The
    involvement's own `channel_id` is trusted to resolve (validate_data.py already refuses a
    dangling one on the store itself)."""
    if not person_id:
        return None
    for row in _load_jsonl_rows(root, "involvements.jsonl"):
        if row.get("person_id") == person_id and row.get("channel_id") and not row.get("opp_id"):
            return row["channel_id"]
    return None


def _sent_row_exists(root, opp_id, person_id, date):
    """True when this send is ALREADY a fact elsewhere — an `outreach[]` row on this
    opportunity for this person dated the same day, or an outbound `messages.jsonl` row
    anchored the same way (§4: 'if the message id it names resolves ... or an outreach[] row
    matches by contact + date -> delete'). Undated (no date on the Status line) never matches
    — refusing to guess is safer than a false 'already recorded'."""
    if not date:
        return False
    if opp_id:
        for o in _load_jsonl_rows(root, "opportunities.jsonl"):
            if o.get("id") != opp_id:
                continue
            for out in (o.get("outreach") or []):
                if (out.get("person_id") == person_id
                        and str(out.get("date") or "")[:10] == date):
                    return True
    for m in _load_jsonl_rows(root, "messages.jsonl"):
        if m.get("direction") != "outbound":
            continue
        if person_id and m.get("person_id") != person_id:
            continue
        if opp_id and m.get("opp_id") not in (opp_id, None):
            continue
        if str(m.get("sent_on") or "")[:10] == date:
            return True
    return False


def plan_prune(root, filename=None, today=None):
    """The decision core shared by `--prune` and `m_0_47_0_drafts_working_set` — computing
    what happens to drafts.md's TERMINAL entries never touches disk itself, so both callers
    apply the identical answer to "what does this tombstone relocate to" rather than two
    implementations that could drift.

    An entry with a `**Status:**` line opening SENT and a matching `outreach[]`/`messages`
    row already recording the send is `deleted_only` — the fact already exists. Every other
    terminal entry RELOCATES: to the named opportunity's `research_log[]` when
    `**Triggered by: opp:<id>**` resolves, else to a channel-only involvement's
    `channels[].log[]`. An entry with NEITHER anchor is `unresolved` — left exactly where it
    was, counted, never guessed and never dropped (§4: "nothing is dropped without a row
    somewhere").

    Returns {'new_text': <drafts.md text with every non-unresolved terminal entry's paragraph
    removed, or None if the file cannot be read>, 'relocations': [...], 'deleted_only':
    [(title, reason)], 'unresolved': [(title, reason, why)]}."""
    filename = filename or FILES[0]
    path = _tree.resolve_rel(root, filename)
    try:
        with open(path, encoding="utf-8") as fh:
            md = fh.read()
    except OSError:
        return {"new_text": None, "relocations": [], "deleted_only": [], "unresolved": []}

    import datetime
    today = today or datetime.date.today().isoformat()

    relocations, deleted_only, unresolved = [], [], []
    remove_spans = []
    for m in ENTRY_RE.finditer(md):
        title, body = m.group(1).strip(), m.group(2)
        sm = STATUS_RE.search(body)
        if not sm:
            continue
        status_text = sm.group(1)
        if SENT_RE.match(status_text):
            reason = "sent"
        elif MOOT_RE.search(status_text):
            reason = "moot"
        else:
            continue

        opp_id = _opp_anchor(root, body)
        person_id = _to_person(root, body)
        chan_id = None if opp_id else _channel_anchor(root, person_id)

        if reason == "sent":
            dm = _STATUS_DATE_RE.search(status_text)
            date = dm.group(1) if dm else None
            if _sent_row_exists(root, opp_id, person_id, date):
                deleted_only.append((title, reason))
                remove_spans.append(m.span())
                continue
            row_date = date or today
        else:
            row_date = today

        note = "relocated from drafts.md (%s) — %s: %s" % (reason, title, status_text)
        if opp_id:
            relocations.append({"anchor_kind": "opp", "anchor_id": opp_id,
                                "row": {"date": row_date, "note": note},
                                "title": title, "reason": reason})
            remove_spans.append(m.span())
        elif chan_id:
            relocations.append({"anchor_kind": "channel", "anchor_id": chan_id,
                                "row": {"date": row_date, "note": note},
                                "title": title, "reason": reason})
            remove_spans.append(m.span())
        else:
            unresolved.append((title, reason,
                               "no **Triggered by: opp:** and no **To:** contact resolving to "
                               "a channel-only involvement — left in place, not dropped"))

    new_text = md
    for start, end in sorted(remove_spans, reverse=True):
        new_text = new_text[:start] + new_text[end:]
    return {"new_text": new_text, "relocations": relocations,
           "deleted_only": deleted_only, "unresolved": unresolved}


def cmd_prune(root):
    """`--prune`: relocate/delete every TERMINAL entry in drafts.md, via `record.py` (so the
    relocation gets the SAME lock/validate/rollback guarantees any other write to
    opportunities.jsonl or channels.jsonl gets) — never touches drafts.md itself until every
    relocation has actually landed (durability before deletion)."""
    plan = plan_prune(root)
    if plan["new_text"] is None:
        print("no %s found — nothing to prune" % FILES[0])
        return 0

    import subprocess
    record_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "record.py")
    failed = []
    for r in plan["relocations"]:
        if r["anchor_kind"] == "opp":
            args = [sys.executable, record_py, "append", r["anchor_id"], "research_log",
                   json.dumps(r["row"])]
        else:
            args = [sys.executable, record_py, "append", r["anchor_id"], "log",
                   json.dumps(r["row"]), "--file", "channels"]
        res = subprocess.run(args, capture_output=True, text=True)
        if res.returncode != 0:
            failed.append((r["title"], (res.stdout + res.stderr).strip()[-400:]))

    if failed:
        print("PRUNE — drafts.md working set")
        print("  ⛔ %d relocation(s) FAILED — drafts.md is UNCHANGED (nothing is deleted "
              "before its row lands):" % len(failed))
        for title, why in failed:
            print("    %s: %s" % (title[:60], why))
        return 1

    if plan["relocations"] or plan["deleted_only"]:
        import _atomic
        _atomic.write_text(_tree.resolve_rel(root, FILES[0]), plan["new_text"])

    print("PRUNE — drafts.md working set")
    print("  %d relocated (no row existed — see research_log[]/channels[].log[])"
         % len(plan["relocations"]))
    print("  %d deleted (a row already exists — nothing lost)" % len(plan["deleted_only"]))
    if plan["unresolved"]:
        print("  %d TERMINAL entr%s left in place — no resolvable anchor:"
             % (len(plan["unresolved"]), "y" if len(plan["unresolved"]) == 1 else "ies"))
        for title, reason, why in plan["unresolved"]:
            print("    %s (%s): %s" % (title[:60], reason, why))
    if not (plan["relocations"] or plan["deleted_only"] or plan["unresolved"]):
        print("  nothing to prune — no terminal entries in the file")
    return 0


def cmd_format(root):
    """`--format`: the generated preamble (§4 row 5), followed by the working set itself —
    every OPEN_STATES entry across the pair, ordered as closely to the owner's own workflow
    order as a text listing can get: by the linked opportunity's `workflow_state()` cell where
    `**Triggered by: opp:<id>** resolves, a catch-all bucket otherwise. This is a TEXT
    ordering convenience only, not the surface itself — V2 (design §9) owns the real per-cell
    dashboard rendering with links and chips; if it ships a canonical `your_move.cell_of()`,
    this should import that rather than keep its own copy."""
    print(format_header())
    rows = [r for r in report(root) if r["state"] in OPEN_STATES]
    if not rows:
        print("(the working set is empty — nothing sendable, blocked, or needing you)")
        return 0

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import your_move as _ym
    import applications as _apps
    opps = _load_jsonl_rows(root, "opportunities.jsonl")
    opps_by_id = {o.get("id"): o for o in opps}
    _apps_rows, _apps_errs, _apps_present = _apps.load(root)
    apps_by_opp = _apps.group_by_opp(_apps_rows)
    today = None

    _CELL_RANK = {"4": 0, "1": 1, "E": 2, "parked": 3, "2": 4, "A": 5, "8": 6, "7": 7,
                 "6": 8, "3": 8, "+": 9}

    def _cell(title, body):
        opp_id = _opp_anchor(root, body)
        opp = opps_by_id.get(opp_id)
        if opp is None:
            return "?"
        try:
            ws = _ym.workflow_state(root, opp, apps_by_opp.get(opp_id, []), today=today)
        except Exception:                                    # noqa: BLE001 — ordering only
            return "?"
        if ws["conversation"] == "reply-owed":
            return "4"
        if ws["application"] == "undecided":
            return "1"
        if ws["ended_because"]:
            return "E"
        if ws["application"] == "parked":
            return "parked"
        if ws["application"] == "pursuing":
            return "2"
        if ws["application"] == "in-process":
            return "+"
        if ws["application"] == "applied":
            if ws["conversation"] == "accepted":
                return "A"
            if ws["conversation"] == "silent" and ws["networking_closed_in_force"]:
                return "8"
            if ws["conversation"] in ("silent", "silence-unverified"):
                return "7"
            return "6"
        return "?"

    entries = {}
    for fn in FILES:
        fpath = _tree.resolve_rel(root, fn)
        try:
            with open(fpath, encoding="utf-8") as fh:
                fmd = fh.read()
        except OSError:
            continue
        for m in ENTRY_RE.finditer(fmd):
            entries[(fn, m.group(1).strip())] = m.group(2)

    by_row = {}
    for r in rows:
        body = entries.get((r["file"], r["title"]), "")
        c = _cell(r["title"], body) if r["file"] == FILES[0] else "?"
        by_row[(r["file"], r["title"])] = c

    rows.sort(key=lambda r: (_CELL_RANK.get(by_row[(r["file"], r["title"])], 99), r["file"],
                             r["title"]))
    print("THE WORKING SET — %d entr%s\n" % (len(rows), "y" if len(rows) == 1 else "ies"))
    for r in rows:
        cell = by_row[(r["file"], r["title"])]
        print("  [cell %-6s] %-10s %s › %s" % (cell, r["state"], r["file"], r["title"][:60]))
        print("            %s" % r["why"])
    return 0


def medium_drift(rows):
    """(unknown, total) over the DRAFTS file's open rows — the drift meter dev #265 asks for,
    as a measured number rather than an impression.

    Measured over the open queue (OPEN_STATES), not every entry: a sent or moot entry is
    over, and its medium line stops mattering the moment it is. Drafts only — cover letters
    carry no medium dimension (generate_dashboard.COVER_DIMS: a letter is pasted into a
    form, not sent on a medium), so counting them would dilute the rate with rows that can
    never be anything but `unknown`. The dashboard's medium filter label already shows the
    same count per value on the page; this is the same number where a run reads it, so the
    hygiene block can watch it move without opening the page."""
    open_rows = [r for r in rows if r.get("file") == FILES[0] and r["state"] in OPEN_STATES]
    return (sum(1 for r in open_rows if r.get("medium") == "unknown"), len(open_rows))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if any precondition is unreadable or unresolved")
    ap.add_argument("--format", action="store_true",
                    help="States & Views V1b (design §4): print the generated drafts.md "
                         "preamble plus the working set itself, in the owner's own order")
    ap.add_argument("--prune", action="store_true",
                    help="States & Views V1b (design §4): relocate every TERMINAL (sent/moot) "
                         "drafts.md entry to the record it belongs to, then remove it")
    args = ap.parse_args()

    root = profile_root()
    if args.format:
        return cmd_format(root)
    if args.prune:
        return cmd_prune(root)

    rows = report(root)
    if args.json:
        print(json.dumps(rows, indent=1))
    else:
        print("SEND PRECONDITIONS — what can actually be sent right now\n")
        for filename in FILES:
            file_rows = [r for r in rows if r.get("file") == filename]
            if not file_rows:
                continue
            print("  %s" % filename)
            for r in file_rows:
                mark = {"sendable": "✅", "blocked": "⏳", "unreadable": "⛔",
                        "unresolved": "🚧", "sent": "🏁", "moot": "🏁",
                        # Query or Citation C1 (D8) — the six new states, so text mode never
                        # KeyErrors on one the way it did before this dict was closed.
                        "unaddressed": "⛔", "unbriefed": "⛔", "brief-mismatch": "⛔",
                        "stale-brief": "⛔", "unverified-cold": "⏸", "unverified-silent": "⏸",
                        }[r["state"]]
                print("    %s %-10s %s" % (mark, r["state"], r["title"][:70]))
                print("          %s" % r["why"])
        n_send = sum(1 for r in rows if r["state"] == "sendable")
        n_block = sum(1 for r in rows if r["state"] == "blocked")
        n_unres = sum(1 for r in rows if r["state"] == "unresolved")
        n_term = sum(1 for r in rows if r["state"] in TERMINAL)
        line = "\n  %d sendable · %d blocked on someone else" % (n_send, n_block)
        if n_unres:
            line += " · %d unresolved (precondition in prose, not yet structured)" % n_unres
        if n_term:
            line += " · %d sent/moot (terminal — public #29)" % n_term
        print(line)
        n_unknown, n_open = medium_drift(rows)
        if n_open:
            print("  medium drift (dev #265): %d of %d open draft(s) name no MEDIA value on a "
                  "`**Medium:**` line" % (n_unknown, n_open))
        if n_unknown:
            print("     each renders flagged `medium: unknown`; the writer owns the line "
                  "(outreach-drafter), the 0.37.0 migration relocates the one legacy shape")
        if n_block:
            print("  ⭐ Blocked drafts must NOT render as 'needs you'. A line there has to be a")
            print("     question or an imperative aimed at the candidate; a draft the candidate cannot send")
            print("     is neither, and padding that list is how it stops being read.")
        if n_unres:
            print("  🚧 An unresolved draft is treated as blocked, not sendable — 'no draft is")
            print("     blocked' and 'no draft has been migrated' are opposite states (#13).")
            print("     Structure each with `**Blocked until:** contact:<id> outcome:<...>`.")

    if args.check:
        # Query or Citation C1 (§3.5) — NEEDS_HUMAN is the ONE exit-1 set, not a hand-repeated
        # tuple: a WAITS_ON_SURFACE row (unverified-cold/unverified-silent) is counted, never a
        # red close — "a WAITS_ON_SURFACE draft is not a red close, or every application-session
        # close on S4/S5 is red forever."
        bad = [r for r in rows if r["state"] in NEEDS_HUMAN]
        for r in bad:
            print("⛔ %s › %s [%s]: %s" % (r.get("file", "?"), r["title"][:60],
                                           r["state"], r["why"]), file=sys.stderr)
        # States & Views V1b (design §4) — draft_checks() is the ONE terminal-entry-present /
        # regrown-preamble check; a `--check` that never ran it would let both regress quietly.
        draft_problems = draft_checks(root)
        for p in draft_problems:
            print("⛔ %s" % p, file=sys.stderr)
        return 1 if (bad or draft_problems) else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
