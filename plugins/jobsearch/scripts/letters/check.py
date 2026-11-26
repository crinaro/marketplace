"""The cover-letter checks: per-entry findings, the whole-file report, the `marked.json` contract and the preflight decision (jobsearch 0.95.0; dev 1071, 1073; design § 8).

Pure functions over values. The entry point (`letter_out.py`) reads the files, the profile stamp and `lifecycle`'s skew
report, and passes what it found in; nothing here reads a profile.

**`check_entry(entry, rules, stamp_ok, skew, marked)`** returns `[(level, text)]`, level `FAIL` or `note`, one row per
§ 8.2 finding, for one `letters.entries.Entry`:

* `rules`     `letters.rules.writing_rules(config, user)`.
* `stamp_ok`  True when the profile stamp is 0.95.0 or later (`version_at_least`). False reads a missing line as `migration
              pending`, a note.
* `skew`      True when `lifecycle.process_report` reports ENGINE SKEW (two engines on one profile). With the stamp at or
              above 0.95.0, a missing line is then a note (`an older engine may have drafted this`), not a FAIL.
* `marked`    the headings in `archive/migrations/0.95.0/marked.json` (`read_marked`), or None when the file is absent or
              unusable. The marker on an entry not in that set is a FAIL (the file gone and a retitled entry included).

**`check_file(text, rules, verdict, stamp_ok, skew, marked, full_name, closed=is_closed)`** parses the cover-letters `text`
(None when the file is absent), skips the entries `closed(entry.raw)` calls over (`_entry_status.is_closed`: sent or moot),
checks the rest, and returns a `Report`: `.fails`, `.notes`, `.pending`, `.closed`, `.lines`, `.text()` (§ 8.2's output block:
the guide verdict first, a `FAIL` entry as two lines, a `note` entry as one) and `.exit_code(advisory=False)`: 1 on any FAIL
(a broken guide counts), else 0; `advisory` forces 0. No entries and no declared guide prints exactly `no staged letters`.
`verdict` is a `letters.guide.Verdict`. Two pending entries with one heading each get a note (`--render` cannot pick one).
A writing rule that is present but cannot be read (`rules["unreadable"]`, dev 1072) is a header line, `  FAIL  writing rules: PROBLEM
— <what>`, one per problem, printed even when no letter is staged; each counts in `.fails`, so the exit is 1. `.rows` keep their
shape (`heading`, `fails`, `notes`). An unset rule is not one.

**US English** is matched over the spelling and its inflections (`_forms`): the plural, and for a verb in `-ise`/`-yse` or a noun in
`-our` the `-ed`, `-ing` and (for `-ise`) `-ation` forms, each with the American form for the same inflection. `organisations`
gives `use "organizations"`; `analyses` is left alone (a US noun).

**The `marked.json` contract** (§ 9.1 step 3): the frozen migration `m_0_95_0_letter_entries` writes
`archive/migrations/0.95.0/marked.json` as `{"version": "0.95.0", "headings": [<heading text>, ...]}`; `read_marked(root)`
is the one reader and returns the set of headings, or None for an absent, unreadable or differently shaped file.

**`preflight(opp_id, role, fit_state, verdict, answered=None)`** is § 8.1's decision. `fit_state` is `_fit_pitch.state(opp)`. It
returns a `Preflight`: `.ok`, `.reason` (`ok`, `ok-answered`, `no-fit`, `no-pitch`, `guide`; checked in that order), `.detail` and
`.line` (`LETTER PREFLIGHT <opp_id> ok` or `... stop <reason>: <detail>`). `answered` is the candidate's recorded answer to a
stop, `(reason, iso_date)` or None (dev 1071, review item 1): when `fit_state` is `no-pitch` and `answered[0]` is `no-pitch`
the stop is answered ("write the letter anyway"), the pitch step passes and the result is `ok-answered` with the line `LETTER
PREFLIGHT <opp_id> ok: written without a pitch, at your answer of <date>`. The guide is still judged. Any other answer, or any
other fit state, behaves as with no answer. The entry then carries `**Written without:** a pitch (your answer, <date>)`, which
`check_entry` reads as a note.

Imports `letters.entries` and the core `_entry_status`; standard library otherwise. Python 3.9+.
"""

import json
import os
import re

from _entry_status import is_closed
from letters import entries as _entries

FAIL = "FAIL"
NOTE = "note"
MARKED_REL = "archive/migrations/0.95.0/marked.json"
MARKED_VERSION = "0.95.0"
STAMP_FLOOR = "0.95.0"
UNRECORDED_HINT = "not in the 0.95.0 record; have the writer add both lines"
RECORDED_NOTE = "drafted before 0.95.0; the writer adds both lines when it next revises this letter"
MIGRATION_PENDING = "migration pending"
SKEW_NOTE = "an older engine may have drafted this"
_OPENER_RE = re.compile(r"^\s*I(?:\s+am|['’ʼ]m)\s+(?:applying|writing\s+to\s+apply)\b", re.I)
_WITHOUT_RE = re.compile(r"^a pitch \(your answer, (\d{4}-\d{2}-\d{2})\)$")
ANSWERED_OK = "ok-answered"
_PREFLIGHT_STATES = ("ok", "no-fit", "no-pitch")


class Report(object):
    """The whole-file result; see the module docstring."""

    def __init__(self, guide, rows, pending, closed, has_entries, problems=()):
        self.guide = guide
        self.rows = rows
        self.pending = pending
        self.closed = closed
        self.has_entries = has_entries
        self.problems = list(problems)

    @property
    def fails(self):
        return (sum(1 for r in self.rows if r["fails"]) + (1 if self.guide.state == "broken" else 0)
                + len(self.problems))

    @property
    def notes(self):
        return sum(1 for r in self.rows if r["notes"])

    def exit_code(self, advisory=False):
        return 0 if advisory or not self.fails else 1

    @property
    def lines(self):
        bad = ["  FAIL  writing rules: PROBLEM — %s" % p for p in self.problems]
        if not self.has_entries and self.guide.state == "none" and not bad:
            return ["no staged letters"]
        head = "STAGED LETTERS — letter guide: %s — " % self.guide.short
        if not self.has_entries:
            return [head + "no staged letters"] + bad
        head += "%d pending checked" % self.pending
        if self.closed:
            head += " (%d sent or moot not checked)" % self.closed
        out = [head] + bad
        for r in self.rows:
            if r["fails"]:
                out += ["  FAIL  %s" % r["heading"], "        %s" % " · ".join(r["fails"])]
            if r["notes"]:
                out.append("  note  %s — %s" % (r["heading"], " · ".join(r["notes"])))
        return out

    def text(self):
        return "\n".join(self.lines)


class Preflight(object):
    """§ 8.1's decision: `ok`, `reason`, `detail`, and the one `line` printed."""

    def __init__(self, opp_id, reason, detail=""):
        self.ok = reason in ("ok", ANSWERED_OK)
        self.reason = reason
        self.detail = detail
        self.line = "LETTER PREFLIGHT %s %s" % (opp_id, "ok" if reason == "ok" else
                                                  "ok: %s" % detail if self.ok else "stop %s: %s" % (reason, detail))


def version_at_least(stamp, floor=STAMP_FLOOR):
    """True when the dotted `stamp` is `floor` or later. None or an unreadable stamp is False (the migration is pending)."""
    def parts(v):
        if not isinstance(v, str) or not re.match(r"^\d+(\.\d+)*$", v.strip()):
            return None
        return tuple(int(x) for x in v.strip().split("."))
    a, b = parts(stamp), parts(floor)
    return a is not None and b is not None and a >= b


def read_marked(root):
    """The set of headings the migration recorded, or None when the file is absent, unreadable or not `{version, headings}`."""
    path = os.path.join(root, *MARKED_REL.split("/"))
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") != MARKED_VERSION:
        return None
    heads = data.get("headings")
    if not isinstance(heads, list) or not all(isinstance(h, str) for h in heads):
        return None
    return set(heads)


def _line_findings(entry, label, read):
    """Findings from one named line's reading (the marker and the missing case are handled by the caller)."""
    out = []
    if read.state == "error":
        out.append((FAIL, read.error.message))
    elif read.state == "ok" and label == "Purpose":
        n = _entries.purpose_note(read.text)
        if n:
            out.append((NOTE, n))
    elif read.state == "ok":
        n = _entries.needs_note(read.items)
        if n:
            out.append((NOTE, n))
        if entry.has_body:
            for text, p in _entries.missing_paragraphs(read.items, len(entry.paragraphs)):
                out.append((FAIL, "**Needs:** \"%s\" cites P%d; the letter has %d paragraph%s"
                            % (text, p, len(entry.paragraphs), "" if len(entry.paragraphs) == 1 else "s")))
    return out


def _structure(entry, stamp_ok, skew, marked):
    reads = (("Purpose", _entries.read_purpose(entry)), ("Needs", _entries.read_needs(entry)))
    out, missing = [], []
    for label, read in reads:
        if read.state == "missing":
            missing.append("**%s:** missing" % label)
        else:
            out += _line_findings(entry, label, read)
    if missing:
        if not stamp_ok:
            out.append((NOTE, "%s (%s)" % (MIGRATION_PENDING, ", ".join(missing))))
        elif skew:
            out.append((NOTE, "%s (%s)" % (SKEW_NOTE, ", ".join(missing))))
        else:
            out += [(FAIL, m) for m in missing]
    if any(read.state == "marker" for _l, read in reads):
        if marked is not None and entry.heading in marked:
            out.append((NOTE, RECORDED_NOTE))
        else:
            out.append((FAIL, "unrecorded marker: %s" % UNRECORDED_HINT))
    return out


def _forms(word, good):
    """[(form, replacement_or_None)]: `word` as configured, then its British inflections with the American form for each
    (dev 1072, review item 10). A verb in -ise or -yse (when the pair is the regular -ize or -yze one) gets -d and -ing, and -ise
    also the plural, -ation and -ations (`analyses` is left out: it is a US noun); a noun in -our (pair -or) gets -s, -ed and
    -ing; any other word its plural, unless it is already an -ed or -ing form. A phrase or a hyphenated word is exact only."""
    out = [(word, good)]
    if not word.isalpha():
        return out
    w, g = word.lower(), (good or "").lower()

    def put(form, american):
        out.append((form, american if good else None))
    if w.endswith(("ise", "yse")) and (not good or (g[:-3] == w[:-3] and g.endswith(("ize", "yze")))):
        if w.endswith("ise"):
            put(w + "s", g + "s")
            for suffix in ("ation", "ations"):
                put(w[:-1] + suffix, g[:-1] + suffix)
        put(w + "d", g + "d")
        put(w[:-1] + "ing", g[:-1] + "ing")
    elif w.endswith("our") and (not good or g == w[:-3] + "or"):
        for suffix in ("s", "ed", "ing"):
            put(w + suffix, g + suffix)
    elif not w.endswith(("ed", "ing")):
        put(w + "s", g + "s")
    return out


def _us_hits(body, rules):
    out, seen = [], set()
    for term, term_good in rules["us_english"]["terms"]:
        for word, good in _forms(term, term_good):
            if word.lower() in seen:
                continue
            seen.add(word.lower())
            n = len(re.findall(r"\b%s\b" % re.escape(word), body, re.I))
            if n:
                tail = "use \"%s\"" % good if good else "a variant to avoid"
                out.append((NOTE, "British spelling \"%s\" x%d; %s" % (word, n, tail)))
    return out


def _written_without(entry):
    """The note for an entry carrying `**Written without:** a pitch (your answer, <date>)`, else []. Never a FAIL."""
    out = []
    for value, _continued in entry.values("Written without"):
        m = _WITHOUT_RE.match(value)
        if m:
            out.append((NOTE, "written without a pitch, at the candidate's answer of %s" % m.group(1)))
    return out


def check_entry(entry, rules, stamp_ok, skew, marked):
    """[(level, text)] findings for one entry; the one check `--check` and `--render` share."""
    if not entry.has_body:
        return [(FAIL, "no `> `-quoted body")] + _structure(entry, stamp_ok, skew, marked) + _written_without(entry)
    body = entry.body_text
    out = []
    for ch in rules["banned"]:
        if ch in body:
            out.append((FAIL, "banned character \"%s\" x%d" % (ch, body.count(ch))))
    out += _structure(entry, stamp_ok, skew, marked)
    limit = rules["target_words"] and rules["target_words"] * 1.25
    words = len(re.findall(r"\S+", body))
    if limit and words > limit:
        out.append((NOTE, "%d words against a target of %d" % (words, rules["target_words"])))
    out += _us_hits(body, rules)
    if entry.paragraphs and _OPENER_RE.match(entry.paragraphs[0]):
        out.append((NOTE, "the first paragraph opens \"I am applying\"; the default is to open on the work"))
    return out + _written_without(entry)


def check_file(text, rules, verdict, stamp_ok, skew, marked, full_name, closed=is_closed):
    """The `STAGED LETTERS` report over every pending entry of `text`; see the module docstring."""
    entries = _entries.parse_entries(text, full_name)
    live = [e for e in entries if not closed(e.raw)]
    seen = {}
    for e in live:
        seen[e.heading.casefold()] = seen.get(e.heading.casefold(), 0) + 1
    rows = []
    for e in live:
        found = check_entry(e, rules, stamp_ok, skew, marked)
        fails = [t for lv, t in found if lv == FAIL]
        notes = [t for lv, t in found if lv == NOTE]
        if seen[e.heading.casefold()] > 1:
            notes.append("same heading as another pending entry; --render cannot pick one")
        rows.append({"heading": e.heading, "fails": fails, "notes": notes})
    return Report(verdict, rows, len(live), len(entries) - len(live), bool(entries), rules.get("unreadable") or ())


def preflight(opp_id, role, fit_state, verdict, answered=None):
    """§ 8.1: may a letter be written for `opp_id` (`role` labels it)? Order: no fit, no pitch, a broken guide. `answered` is
    `(reason, iso_date)` for the candidate's recorded answer to a stop, or None; only a `no-pitch` answer to a `no-pitch` stop
    passes that step (the guide is still judged)."""
    if fit_state not in _PREFLIGHT_STATES:
        raise ValueError("fit_state must be one of %s, got %r" % (", ".join(_PREFLIGHT_STATES), fit_state))
    label = role or opp_id
    if fit_state == "no-fit":
        return Preflight(opp_id, "no-fit", "no fit analysis for %s" % label)
    without = None
    if fit_state == "no-pitch":
        if not (isinstance(answered, (tuple, list)) and len(answered) == 2 and answered[0] == "no-pitch"):
            return Preflight(opp_id, "no-pitch", "the fit found nothing aligned for %s" % label)
        without = answered[1]
    if verdict.state == "broken":
        return Preflight(opp_id, "guide", verdict.detail)
    if without is not None:
        return Preflight(opp_id, ANSWERED_OK, "written without a pitch, at your answer of %s" % without)
    return Preflight(opp_id, "ok")
