"""Migration 0.95.0: `m_0_95_0_letter_entries()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, frozen once released (§5.5). Frozen means self-contained (docs/design-cover-letters.md §13.2): this module imports no other migration and
does not import `letters/`; it carries its OWN copy of the status rule (`_entry_status.py`'s, as it reads at 0.95.0) and of the entry and meta-line rules. Its output, `archive/migrations/0.95.0/marked.json`, and
`letters/check.py`'s reading of it are one contract, held by the end-to-end case in `tests/migrations/test_m_0_95_0_letter_entries.py`."""

import _tree
import datetime
import json
import os
import re
import shutil
from migrations.support_config import _load_config, _rewrite_config
from migrations.support_jsonl import _read_asks_tolerant, _rewrite_jsonl

VERSION = "0.95.0"


# KEYED "0.95.0" (docs/design-cover-letters.md §9, §12 MG1; jobsearch group file docs/groups/jobsearch-0.95.0.md) -- 0.94.0 is the newest jobsearch release at the branch base. A profile stamped "0.94.0" (or lower) fires a migration keyed
# "0.95.0" through pending_for()'s strict `<`. It runs LAST among the migrations; it needs no pin (0.95.0 writes none: an older engine is refused nothing, it drafts letters without the two lines).
ARCHIVE_DIR = ("archive", "migrations", "0.95.0")
PURPOSE_MARKER_LINE = "**Purpose:** unrecorded (drafted before 0.95.0)"
NEEDS_MARKER_LINE = "**Needs:** unrecorded"
ASK_ID = "letter-guide-candidate"
GUIDE_FLOOR_WORDS = 20
_QUESTIONS_MARK = "questions that would sharpen"
_ENTRY_RE = re.compile(r"^##\s+(.+?)$(.*?)(?=^##\s|\Z)", re.M | re.S)
_META_RE = re.compile(r"^\*\*([^*:]+):\*\*\s*(.*)$")
_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*$")
_RULES = ("---", "***", "___")
# `_entry_status.py`'s rule as it reads at 0.95.0 (review item 7); a copy, so a later change to that module can never change what this migration marks. An entry is CLOSED iff its Status text, lowercased with leading non-letters
# stripped, begins with the whole word sent, submitted, applied or moot; `sent to <someone> for ...` (a read, a review, a look) is NOT closed; "do not send" never closes. Anything else, and no Status line, is pending.
_STATUS_RE = re.compile(r"^\*\*Status:\*\*\s*(.+?)\s*$", re.M | re.I)
_LEAD_RE = re.compile(r"^[\W\d_]+")
_CLOSING_RE = re.compile(r"(sent|submitted|applied|moot)\b")
_SENT_FOR_RE = re.compile(r"sent\s+to\s+.+?\s+for\b")
_PENDING = "  ⏳ 0.95.0 PENDING -- %s. This runs again next session."


def _is_closed(entry_text):
    sm = _STATUS_RE.search(entry_text)
    if not sm:
        return False
    text = _LEAD_RE.sub("", sm.group(1).lower())
    word = _CLOSING_RE.match(text)
    return bool(word) and not (word.group(1) == "sent" and _SENT_FOR_RE.match(text))


def _is_prose(line):
    """A line that would read as stray prose folded onto the meta line above it."""
    s = line.strip()
    return bool(s) and not s.startswith((">", "**", "###")) and s not in _RULES


def _labels(lines):
    return {m.group(1).strip().lower() for m in (_META_RE.match(x.strip()) for x in lines if not x.strip().startswith(">")) if m}


def _insert(body, missing, eol):
    """`body` (an entry's text after its title) with the marker lines for `missing` placed under the last meta line of the leading block (and any prose that continues it), else under the title."""
    lines = body.split("\n")
    at = 0
    for i in range(1, len(lines)):
        s = lines[i].strip()
        if s.startswith(">"):
            break
        if _META_RE.match(s):
            at = i
    new = [PURPOSE_MARKER_LINE if lab == "purpose" else NEEDS_MARKER_LINE for lab in missing]
    if at:
        while at + 1 < len(lines) and _is_prose(lines[at + 1]):
            at += 1
    elif len(lines) > 1 and _is_prose(lines[1]):
        new.append("")          # prose straight under the title: a blank line keeps the marker lines one-line values
    return "\n".join(lines[:at + 1] + [x + eol for x in new] + lines[at + 1:])


def _transform(text):
    """(new_text, [headings marked]) for the cover-letters `text`: every pending entry (not the Questions section, not sent or moot) lacking `**Purpose:**` and/or `**Needs:**` gets the marker line(s) it lacks."""
    eol = "\r" if "\r\n" in text else ""
    out, pos, headings = [], 0, []
    for m in _ENTRY_RE.finditer(text):
        heading, body = m.group(1).strip(), m.group(2)
        if _QUESTIONS_MARK in heading.lower() or _is_closed(m.group(0)):
            continue
        have = _labels(body.split("\n"))
        missing = [lab for lab in ("purpose", "needs") if lab not in have]
        if not missing:
            continue
        out += [text[pos:m.start(2)], _insert(body, missing, eol)]
        pos = m.end(2)
        headings.append(heading)
    out.append(text[pos:])
    return "".join(out), headings


def _write_text(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    try:
        shutil.copymode(path, tmp)
    except OSError:
        pass
    os.replace(tmp, path)               # atomic: never a half-written file


def _preserve(src, dest):
    """Copy `src` to `dest` byte for byte, through a temp name, unless `dest` already holds the true original of an earlier run. Returns an error text or None."""
    if os.path.exists(dest):
        return None
    tmp = dest + ".tmp"
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(src, tmp)
        with open(src, "rb") as a, open(tmp, "rb") as b:
            if a.read() != b.read():
                raise OSError("the copy differs from the original")
        os.replace(tmp, dest)
    except (OSError, shutil.Error) as exc:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return str(exc)
    return None


def _write_marked(archive, headings):
    """Write `marked.json` as the union of what is there and `headings`; never fewer. Returns an error text or None."""
    path = os.path.join(archive, "marked.json")
    have = []
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            have = data["headings"]
            if not isinstance(have, list) or not all(isinstance(h, str) for h in have):
                raise ValueError("headings is not a list of text")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return "marked.json exists and cannot be read (%s), so it was not changed" % exc
    union = have + [h for h in dict.fromkeys(headings) if h not in have]
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"version": VERSION, "headings": union}, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)
    except OSError as exc:
        return "marked.json could not be written (%s)" % exc
    return None


def _mark_entries(profile, apply_it):
    """Steps 1 to 5 of design §9.1: `(done, message)`. PRESERVE (the file, then `marked.json`), THEN TRANSFORM; a failed copy is pending and writes nothing."""
    path = _tree.path(profile, "cover_letters")
    if not os.path.exists(path):
        return True, ""
    rel = os.path.relpath(path, profile)
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        return False, _PENDING % ("%s cannot be read (%s); nothing was marked and nothing was written" % (rel, exc))
    new_text, headings = _transform(text)
    if not headings:
        return True, ""
    n = len(headings)
    if not apply_it:
        return True, "  would mark %d pending letter(s) in %s as unrecorded (the original is kept in archive/migrations/0.95.0/)" % (n, rel)
    archive = os.path.join(profile, *ARCHIVE_DIR)
    err = _preserve(path, os.path.join(archive, "cover_letters.md"))
    if err:
        return False, _PENDING % ("%s could not be preserved to archive/migrations/0.95.0/ (%s); nothing was written" % (rel, err))
    err = _write_marked(archive, headings)
    if err:
        return False, _PENDING % ("%s; %s was not changed" % (err, rel))
    try:
        _write_text(path, new_text)
    except OSError as exc:
        return False, _PENDING % ("%s could not be written (%s)" % (rel, exc))
    with open(path, encoding="utf-8", newline="") as fh:
        if _transform(fh.read())[1]:
            return False, _PENDING % ("%s still has pending letters without both lines after the write" % rel)
    return True, ("  ✅ cover_letters.md — %d pending letter(s) marked unrecorded; the writer adds both lines when it next revises one\n"
                  "     the original is kept at archive/migrations/0.95.0/cover_letters.md" % n)


def _resolve(profile, value):
    """The real path of `value` under `profile`, or None when it is absolute, climbs with `..`, or leaves the profile."""
    if os.path.isabs(value) or value.startswith(("~", "/", "\\")) or re.match(r"^[A-Za-z]:", value) or ".." in re.split(r"[\\/]+", value):
        return None
    root = os.path.realpath(profile)
    real = os.path.realpath(os.path.join(profile, value))
    return real if real == root or real.startswith(root + os.sep) else None


def _usable(profile, value):
    """(relpath, [`##` headings], None) when `value` names an existing `.md` file inside the profile that a letter guide could be; else (None, None, why)."""
    if not isinstance(value, str) or not value.strip():
        return None, None, "its value is not a path"
    value = value.strip()
    real = _resolve(profile, value)
    if real is None or not value.lower().endswith(".md") or not os.path.isfile(real):
        return None, None, "%s is not an existing .md file inside the profile" % value
    try:
        with open(real, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except (OSError, UnicodeDecodeError):
        return None, None, "%s cannot be read" % value
    words, heads = 0, []
    for line in lines:
        hm = _HEADING_RE.match(line)
        if hm:
            if len(hm.group(1)) == 2 and hm.group(2):
                heads.append(hm.group(2))
            continue
        words += len(line.split())
    if words < GUIDE_FLOOR_WORDS:
        return None, None, "%s is empty or under the %d-word floor" % (value, GUIDE_FLOOR_WORDS)
    seen, recorded = set(), []
    for h in heads:
        if re.sub(r"\s+", "", h).casefold() not in seen:
            seen.add(re.sub(r"\s+", "", h).casefold())
            recorded.append(h)
    return os.path.normpath(value.replace("\\", "/")).replace(os.sep, "/"), recorded, None


def _ask_row(found, unusable, today):
    """One `asks.jsonl` row, kind=system, a STABLE id (0.63.0's shape): a decision, never mechanical work. `found` is `[(key, path)]` for guide keys that name a usable file, `unusable` `[(key, why)]` for letter-named keys that could not be used."""
    named = "; ".join(["writing.%s naming %s" % (k, rel) for k, rel in found] + ["writing.%s, which could not be used (%s)" % (k, why) for k, why in unusable])
    text = ("found %s. Use it as your letter guide?" % named if len(found) == 1 and not unusable
            else "found %s. Which of these, if any, is your letter guide?" % named if found
            else "found %s. Which file, if any, is your letter guide?" % named)
    return {"id": ASK_ID, "kind": "system", "title": "A letter guide may already be declared under another name",
            "ask": text + " Say which in a session and it runs `letter_out.py --set-guide <path>` (or `--set-guide none` to decline); nothing changes until you answer.",
            "created": today, "act_by": None, "opp_id": None, "channel_id": None, "resolves_when": None, "resolved_on": None, "resolution": None,
            "trigger_kind": None, "trigger_ref": None, "note": None}


def _file_ask(profile, found, unusable, apply_it):
    """Add the `letter-guide-candidate` row unless one with that id is there (kept as it is: `created` does not reset, a resolved row is not reopened). `(done, message)`."""
    path = os.path.join(profile, "data", "asks.jsonl")
    rows, err = _read_asks_tolerant(path)
    if err:
        return False, _PENDING % ("data/asks.jsonl cannot be read (%s), so the letter-guide ask was not filed" % err)
    if any(isinstance(r, dict) and r.get("id") == ASK_ID for r in rows):
        return True, ""
    names = ", ".join("writing.%s" % k for k in [k for k, _x in found] + [k for k, _x in unusable])
    if not apply_it:
        return True, "  would file the ask %s about %s (nothing is adopted without an answer)" % (ASK_ID, names)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _rewrite_jsonl(path, rows + [_ask_row(found, unusable, datetime.date.today().isoformat())])
    return True, "  ❓ found %s; none was adopted. Ask %s filed: use one as your letter guide?" % (names, ASK_ID)


def _adopt_guide(profile, apply_it):
    """Design §9.3: adopt exactly one letter-named `writing.*guide*` key, else file the one decision ask, which also covers a letter-named key that could not be used (it is never dropped with only a note). `(done, message)`."""
    path, cfg, err = _load_config(profile)
    if err:
        return False, _PENDING % ("config.json cannot be read (%s), so no letter guide was looked for" % err)
    writing = cfg.get("writing") if isinstance(cfg, dict) else None
    if not isinstance(writing, dict) or writing.get("letter_guide") is not None:
        return True, ""
    keys = [k for k in writing if k != "letter_guide" and isinstance(k, str) and not k.startswith("_") and "guide" in k.lower()]        # a `_`-led key is a comment, never a candidate
    named = [k for k in keys if "letter" in k.lower() or "cover" in k.lower()]
    found, unusable = {}, []
    for k in sorted(keys, key=lambda x: (x not in named, x)):
        rel, heads, why = _usable(profile, writing[k])
        if rel:
            found[k] = (rel, heads)
        elif k in named:
            unusable.append((k, why))
    if len(named) == 1 and named[0] in found:
        key = named[0]
        rel, heads = found[key]
        if not apply_it:
            return True, "  would adopt writing.%s as writing.letter_guide (%s)" % (key, rel)
        err = _preserve(path, os.path.join(profile, *ARCHIVE_DIR, "config.json"))
        if err:
            return False, _PENDING % ("config.json could not be preserved to archive/migrations/0.95.0/ (%s); no letter guide was adopted" % err)
        writing["letter_guide"] = {"path": rel, "required_headings": heads}
        _rewrite_config(path, cfg)
        return True, "  ✅ writing.letter_guide — adopted writing.%s (%s, %d required heading(s)); the original key stays" % (key, rel, len(heads))
    if not found and not unusable:
        return True, ""
    return _file_ask(profile, [(k, v[0]) for k, v in found.items()], unusable, apply_it)


def m_0_95_0_letter_entries(profile, apply_it):
    """0.95.0 -- a staged cover letter carries its purpose and its needs (dev 1071, 1072, 1073; docs/design-cover-letters.md §7, §9).

    From 0.95.0 every pending entry of the cover-letters file names `**Purpose:**` and `**Needs:**`, and `letter_out.py --check` fails a pending entry without them. A letter drafted before that has neither, and inventing a purpose
    for it would be a guess presented as fact. So this marks it, and the check reads the mark against a record this migration keeps.

    WHAT IT DOES, IN THIS ORDER
      1. Resolve the cover-letters file through `_tree` (`applying/cover_letters.md`, or the legacy root name). Absent: nothing to mark.
      2. Find the PENDING entries lacking `**Purpose:**`, `**Needs:**`, or both. Pending means not the "Questions that would sharpen" section and a `**Status:**` line that does not begin with the whole word sent, submitted, applied or moot (`sent to <someone> for ...` is a request
         for a read and stays pending; "do not send" never closes; this module's own copy of the rule). None: nothing to mark.
      3. PRESERVE: the file is copied byte for byte to `archive/migrations/0.95.0/cover_letters.md` (a copy already there is the true original of an earlier run and is kept), and `archive/migrations/0.95.0/marked.json`,
         `{"version": "0.95.0", "headings": [...]}`, is written as the UNION of what it held and the headings marked now, so it never shrinks. `archive/` is a root directory `_tree.py --audit` accounts for, whichever layout the profile has.
         A copy or a record that cannot be written returns PENDING with the reason and writes nothing to the letters.
      4. TRANSFORM: each marker line it lacks (`**Purpose:** unrecorded (drafted before 0.95.0)`, `**Needs:** unrecorded`) goes directly under the entry's last meta line (and the prose that continues it), else under the title. Through a temp
         file and `os.replace`. Every other byte, sent and moot entries and the Questions section included, is untouched. The disk is re-read: an entry still lacking a line is PENDING.
      5. ADOPT a hand-declared guide (design §9.3): when `writing.letter_guide` is not declared and exactly one other `writing.*` key has a name containing `guide` and `letter` or `cover`, (a name beginning `_` is a comment, never a key) with a value naming an existing `.md` file inside the
         profile that is not under the guide floor, `writing.letter_guide = {path, required_headings: <its current ## headings>}` is written, key order kept, the original key left, `config.json` first copied to
         `archive/migrations/0.95.0/config.json`. Any other `writing.*guide*` key (several letter-named ones included), and a letter-named key whose value cannot be used (a `.txt` path, an object, a missing file, a file under the floor), adopts NOTHING: one `asks.jsonl` row, id
         `letter-guide-candidate`, kind system, names the key and why it could not be used, and asks which, if any, to use.
         An open row (or any row with that id) is kept as it is.

    IDEMPOTENT: a second run finds every pending entry carrying both lines, a declared guide or the ask already filed, and writes nothing. UNDO: restore the copies named above; the marker lines are harmless text.
    `apply_it` False writes nothing and says what it would do. Returns `(done, message)`; a refusal is `(False, "  ⏳ 0.95.0 PENDING -- <reason>. ...")` and the migration is offered again next session."""
    done_a, msg_a = _mark_entries(profile, apply_it)
    done_b, msg_b = _adopt_guide(profile, apply_it)
    return done_a and done_b, "\n".join(m for m in (msg_a, msg_b) if m)
