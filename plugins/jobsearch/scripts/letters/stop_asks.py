"""The asks a letter stop files, and the candidate's answer to one (jobsearch 0.95.0; dev 1071; design § 8.1).

`letter_out.py --preflight <opp_id> --record` files a stop as ONE `asks.jsonl` row, id `letter-stopped:<opp_id>`; this module
holds everything that reads or changes those rows, so the entry point stays small. Every write goes through a `record.py` child
(it takes its own lock and validates); **nothing here writes `asks.jsonl` itself**, and **every write is read back**: the child's
exit code is not the evidence, because `record.py` exits 1 AFTER a successful write when the store was already failing
validation for an unrelated row (dev 1071, review item 4), and exits 0 on a write that did not land. `set_field` and
`create_row` re-read the store and compare the values.

* `rows(root)`                    every row of `<root>/data/asks.jsonl` (an absent file is no rows).
* `mine(all_rows, opp_id)`        the rows of one role's stops: id `letter-stopped:<opp_id>` or that with a `~<n>` suffix.
* `reason_of(row)`                the stop's reason (`no-fit`, `no-pitch`, `guide`): the row's `note`, `letter-preflight:<reason>`
                                  (the schema's `trigger_kind` vocabulary refuses a new kind, so the reason rides in `note`),
                                  else read from the title words for a row filed before the note existed; None if neither.
* `set_field(root, here, rid, field, value)` / `create_row(root, here, row)`  None on success, else `NOT recorded: ...`.
* `file_ask(root, here, pf, opp, verdict, today)`  file, keep, replace or leave a stop's ask, or close it on `ok`; the outcome
                                  word. `pf` is a `letters.check.Preflight`; `verdict` a `letters.guide.Verdict`.
* `answer(root, here, opp_id, today)`  the candidate's "write it anyway": resolves the OPEN stop with `resolution:
                                  "write-anyway"` and `resolved_on`, and ONLY a `no-pitch` stop; `(exit code, message)`.
* `answered(root, opp_id)`        `(reason, iso_date)` of the latest such answer for the role, or None: what
                                  `letters.check.preflight(..., answered=)` takes.
* `open_stops(root)`              `[{"id", "title"}]` for every open stop ask (`--check --json`).

`here` is the directory holding `record.py`. Standard library only. Python 3.9+.
"""

import json
import os
import re
import subprocess
import sys

ANSWER = "write-anyway"
NOTE_PREFIX = "letter-preflight:"
# stop reason -> (the ask's title words, the two decisions it offers)
STOPS = {"no-fit": ("no fit analysis yet", "research this role first (the letter follows), or drop the letter"),
         "no-pitch": ("the fit found nothing aligned", "write the letter anyway, or pass on the role"),
         "guide": ("your letter guide is broken", "keep the guide's new headings (run `letter_out.py --set-guide %s`, "
                   "which re-records them), or stop using a guide (`letter_out.py --set-guide none`)")}
_BASE = "letter-stopped:"


def rows(root):
    path = os.path.join(root, "data", "asks.jsonl")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


def mine(all_rows, opp_id):
    base = _BASE + opp_id
    return [r for r in all_rows if r.get("id") == base or str(r.get("id")).startswith(base + "~")]


def reason_of(row):
    note = row.get("note")
    if isinstance(note, str) and note.startswith(NOTE_PREFIX):
        return note[len(NOTE_PREFIX):] or None
    for reason, (words, _decide) in STOPS.items():
        if str(row.get("title", "")).endswith(": " + words):
            return reason
    return None


def _child(here, *argv):
    r = subprocess.run([sys.executable, os.path.join(here, "record.py")] + list(argv) + ["--file", "asks"],
                       capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()[-200:]


def _verdict(rc, tail, landed, what):
    """None when the store holds what was asked; else the refusal. A non-zero exit with the value landed is a warning, said."""
    if landed:
        if rc != 0:
            print("note: record.py exited %d after writing %s; %s" % (rc, what, re.sub(r"\s+", " ", tail)[-120:]), file=sys.stderr)
        return None
    return "NOT recorded: %s" % (tail or "record.py exited %d and the store does not hold %s" % (rc, what))


def set_field(root, here, rid, field, value):
    rc, tail = _child(here, "set", rid, field, value)
    row = next((r for r in rows(root) if r.get("id") == rid), None)
    return _verdict(rc, tail, row is not None and row.get(field) == value, "%s.%s" % (rid, field))


def create_row(root, here, row):
    rc, tail = _child(here, "create", row["id"], json.dumps(row))
    got = next((r for r in rows(root) if r.get("id") == row["id"]), None)
    return _verdict(rc, tail, got is not None and all(got.get(k) == v for k, v in row.items()), row["id"])


def _cap(detail):
    """Capitalise the first word of a sentence, never a path: a first word with a `/`, `.` or `_` is left as it is."""
    first = detail.split(" ", 1)[0]
    return detail if not first.isalpha() else first[:1].upper() + detail[1:]


def file_ask(root, here, pf, opp, verdict, today):
    """File, keep, replace or leave a stop's ask, or close it on `ok`; the outcome word. Reads `asks.jsonl`, never writes it."""
    base, found = _BASE + opp["id"], mine(rows(root), opp["id"])
    live = next((r for r in found if not r.get("resolved_on")), None)
    if pf.ok:           # an `ok` closes the open row; the resolution goes first, so a torn write leaves an OPEN row to retry
        return "no open ask" if not live else (set_field(root, here, live["id"], "resolution", "preflight ok") or set_field(
            root, here, live["id"], "resolved_on", today) or "closed")
    words, decide = STOPS[pf.reason]
    title = "No letter for %s: %s" % (opp.get("title") or opp["id"], words)
    ask = "%s. Decide: %s." % (_cap(pf.detail), decide.replace("%s", verdict.path or "<path>"))
    note = NOTE_PREFIX + pf.reason
    if live:
        return "kept" if (live.get("ask"), live.get("title")) == (ask, title) else (
            set_field(root, here, live["id"], "ask", ask) or set_field(root, here, live["id"], "title", title)
            or set_field(root, here, live["id"], "note", note) or "replaced")
    if any(r.get("ask") == ask for r in found):
        return "already answered; not reopened"
    row = {"id": base if not found else "%s~%d" % (base, len(found)), "kind": "system", "title": title, "ask": ask,
           "created": today, "act_by": None, "opp_id": opp["id"], "channel_id": None, "resolves_when": None,
           "resolved_on": None, "resolution": None, "trigger_kind": None, "trigger_ref": None, "note": note}
    return create_row(root, here, row) or "filed"


def answer(root, here, opp_id, today):
    """The candidate said "write it anyway": resolve the open `no-pitch` stop for `opp_id`. Refuses, writing nothing, otherwise."""
    live = next((r for r in mine(rows(root), opp_id) if not r.get("resolved_on")), None)
    if live is None:
        return 1, "Nothing recorded: no open letter stop for %s." % opp_id
    if reason_of(live) != "no-pitch":
        return 1, ("Nothing recorded: the open stop for %s is %s, and %r answers only a no-pitch stop."
                   % (opp_id, reason_of(live) or "of an unknown reason", ANSWER))
    err = set_field(root, here, live["id"], "resolution", ANSWER) or set_field(root, here, live["id"], "resolved_on", today)
    return (1, err) if err else (0, "Recorded: a letter for %s may be written without a pitch (your answer, %s)." % (opp_id, today))


def answered(root, opp_id):
    """`(reason, iso_date)` of the latest `write-anyway` answer to a no-pitch stop of `opp_id`, or None."""
    done = [r for r in mine(rows(root), opp_id)
            if r.get("resolved_on") and r.get("resolution") == ANSWER and reason_of(r) == "no-pitch"]
    return ("no-pitch", max(r["resolved_on"] for r in done)) if done else None


def open_stops(root):
    return [{"id": r["id"], "title": r.get("title")} for r in rows(root)
            if str(r.get("id", "")).startswith(_BASE) and not r.get("resolved_on")]
