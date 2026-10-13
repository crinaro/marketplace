#!/usr/bin/env python3
"""Apply ONE reviewer correction to ONE staged draft, in view, and record which comment it was.

⭐ WHY THIS EXISTS (dev #491 / public #87). A reviewer who reads a draft on the published
dashboard sees a sentence they want changed. Until now the only supported route was to say so in
chat and have a session hand-edit `outreach/drafts.md`; the route a *comment on the page* takes
is an edit of the RENDERED page, which changes nothing `generate_dashboard.py` reads, so the
correction vanishes at the next regeneration. This script is the store-side half: the matching,
the before/after and the write are all computable, so they live here, tested; the judgement that
turns a comment into `--find` / `--replace` lives in the coordinator skill's "Apply review
comments" step.

    apply_correction.py --draft "<title>" --find "<exact span>" --replace "<new span>" \\
                        --source comment:<thread_id> | chat   [--ordinal N] [--apply]

THE CONTRACT
------------
* **Dry run by default.** It prints the entry's sent text (the `>` lines) as a unified diff and
  writes NOTHING. `--apply` is the only thing that writes.
* **It refuses (exit 2, loud)** unless `--find` occurs EXACTLY ONCE in that entry's `>` blocks.
  "Not found" also covers already-applied and since-edited, so it is the step's idempotency check
  with no store needed. A span that would straddle two separate `>` blocks never matches.
* **The entry is addressed by title plus ordinal (D5).** A title is not unique: two entries may
  carry the same one. `--ordinal` is the 1-based position among same-titled entries, in file
  order. A title matching more than one entry with no `--ordinal` is refused and the ordinals are
  listed; a title matching none is refused.
* **`--apply` never writes silently.** The diff is printed BEFORE the write; after it, the
  `**Revised:** <date> · <source> · "<find>" → "<replace>"` line it recorded is printed too. The
  line is a `**Label:** value` meta line, a kind `generate_dashboard.parse_drafts` already
  renders as metadata and never as sent text, so no stored shape changes.
* **Idempotent (D6).** It refuses when the entry already carries a `**Revised:**` line with the
  same find and replace and the same source, or with the same find and replace from any source
  when the replace contains the find (the case where "not found" would NOT stop a second apply:
  "Hi" -> "Hi there" still finds "Hi"). A second apply therefore refuses and the file is
  byte-identical.
* **`**Revised:**` must stay inert to `precondition.py` (A3).** That module is deliberately
  unchanged; its regexes are per-label, so an unknown label is ignored. But `HOLD_RE` scans the
  WHOLE entry body, and the Revised line quotes the find text. A correction that REMOVES a hold
  phrase would leave it behind inside the Revised line and keep the draft blocked forever, which
  is the reverse of what the reviewer asked for. So the script computes the precondition-relevant
  signature of the entry with and without the Revised line and refuses if they differ.
* **Writes only to a bound, real profile.** An unbound root, the tracked fixture and the engine's
  own root are refused before any file is opened for writing (dev #81, #87, #618).

Exit codes: 0 dry run printed / applied; 2 refused (nothing written); 1 the write could not be
verified after it was made.

Python 3.9+. Standard library only.
"""

import argparse
import datetime
import difflib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _root
import _tree
import _atomic
import precondition as _pre

REVISED_LABEL = "**Revised:**"
SOURCE_RE = re.compile(r"^(?:chat|comment:[A-Za-z0-9_.:\-]+)$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# `**Revised:** <date> · <source> · <json find> → <json replace>` — the two spans are JSON
# strings so a quote, a newline or an arrow INSIDE one is unambiguous to read back.
REVISED_RE = re.compile(r"^\*\*Revised:\*\*\s*(?P<date>\d{4}-\d{2}-\d{2}) · "
                        r"(?P<source>chat|comment:[A-Za-z0-9_.:\-]+) · (?P<rest>.*)$")
_RULES = ("---", "***", "___")


class Refusal(Exception):
    """The step is refused; nothing was written. The message says why and what to do."""


# ── the entry ──────────────────────────────────────────────────────────────────────────────


def draft_key(title, ordinal):
    """The one address of a draft: its title plus its 1-based ordinal among same-titled
    entries (D5). The ordinal is `1` for a title that appears once."""
    return "%s#%d" % (title, ordinal)


def list_entries(md):
    """[(title, ordinal, start, end)] for every `## ` entry, in file order, using the SAME
    split `precondition.py` uses (`ENTRY_RE`), so the two cannot disagree on what an entry is."""
    seen, out = {}, []
    for m in _pre.ENTRY_RE.finditer(md):
        title = m.group(1).strip()
        seen[title] = seen.get(title, 0) + 1
        out.append((title, seen[title], m.start(), m.end()))
    return out


def locate(md, title, ordinal=None):
    """(start, end) of the addressed entry, or Refusal."""
    hits = [e for e in list_entries(md) if e[0] == title]
    if not hits:
        raise Refusal("no entry titled %r in the drafts file. Nothing was changed. The titles "
                      "present: %s" % (title, "; ".join(repr(e[0]) for e in list_entries(md))
                                       or "(none)"))
    if ordinal is None:
        if len(hits) > 1:
            raise Refusal("%d entries are titled %r, so the title does not say which one. Pass "
                          "--ordinal with one of: %s. Nothing was changed."
                          % (len(hits), title, ", ".join(str(h[1]) for h in hits)))
        return hits[0][2], hits[0][3]
    for h in hits:
        if h[1] == ordinal:
            return h[2], h[3]
    raise Refusal("%r has %d entr%s, so --ordinal %d does not exist (use 1..%d). Nothing was "
                  "changed." % (title, len(hits), "y" if len(hits) == 1 else "ies", ordinal,
                                len(hits)))


# ── the sent text ──────────────────────────────────────────────────────────────────────────


def _split_quote(line):
    """(prefix, content) of a `>` line: leading whitespace, the `>`, and ONE optional space
    are the prefix; everything else is the sent text."""
    m = re.match(r"^(\s*>[ ]?)(.*)$", line.rstrip("\n"))
    return m.group(1), m.group(2)


def _runs(lines):
    """Contiguous runs of `>` lines as lists of line indexes. A run is one blockquote; text
    never matches across two runs, because they are separate pieces of a message."""
    runs, cur = [], []
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith(">"):
            cur.append(i)
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    return runs


def _occurrences(text, find):
    """Start offsets of every (overlapping) occurrence. Overlap counts: "aa" in "aaa" is two,
    and two is ambiguous."""
    return [m.start() for m in re.finditer("(?=%s)" % re.escape(find), text)]


def apply_to_entry(entry, find, replace):
    """-> new entry text, with `find` replaced once in the sent text. Raises Refusal unless
    `find` occurs exactly once across the entry's `>` blocks."""
    if not find:
        raise Refusal("--find is empty. Nothing was changed.")
    if find == replace:
        raise Refusal("--find and --replace are identical, so there is nothing to apply.")
    lines = entry.splitlines(keepends=True)
    hits = []   # (run, offset-in-run-text)
    run_texts = []
    for run in _runs(lines):
        contents = [_split_quote(lines[i])[1] for i in run]
        text = "\n".join(contents)
        run_texts.append((run, text))
        for off in _occurrences(text, find):
            hits.append((len(run_texts) - 1, off))
    if not hits:
        raise Refusal("the span %r is not in this entry's sent text (the `>` lines). It may "
                      "already have been applied, or the draft was edited since the comment was "
                      "written. Nothing was changed." % find)
    if len(hits) > 1:
        raise Refusal("the span %r occurs %d times in this entry's sent text, so it does not say "
                      "which one to change. Quote a longer span that occurs once. Nothing was "
                      "changed." % (find, len(hits)))
    run_ix, off = hits[0]
    run, text = run_texts[run_ix]
    end = off + len(find)
    # Line starts, as offsets into the run's joined text.
    starts, pos = [], 0
    for i in run:
        starts.append(pos)
        pos += len(_split_quote(lines[i])[1]) + 1
    first = max(k for k, s in enumerate(starts) if s <= off)
    last = max(k for k, s in enumerate(starts) if s <= end - 1)
    head = text[starts[first]:off]
    tail = text[end:(starts[last + 1] - 1) if last + 1 < len(starts) else len(text)]
    pieces = (head + replace + tail).split("\n")
    prefix = _split_quote(lines[run[first]])[0]
    rebuilt = []
    for k, piece in enumerate(pieces):
        pre = prefix if piece else prefix.rstrip()
        rebuilt.append(pre + piece + "\n")
    new_lines = (lines[:run[first]] + rebuilt + lines[run[last] + 1:])
    new = "".join(new_lines)
    # The last line of the file may have had no newline; do not invent one that was not there.
    if not entry.endswith("\n") and new.endswith("\n") and run[last] == len(lines) - 1:
        new = new[:-1]
    return new


# ── the Revised line ───────────────────────────────────────────────────────────────────────


def revised_line(date, source, find, replace):
    """The meta line recording one applied correction."""
    return "%s %s · %s · %s → %s" % (REVISED_LABEL, date, source,
                                     json.dumps(find, ensure_ascii=False),
                                     json.dumps(replace, ensure_ascii=False))


def parse_revised(line):
    """(date, source, find, replace) from a Revised line, or Refusal. Strict: a line that
    carries the label and cannot be read is refused, never skipped, because skipping it would
    let the idempotency check pass on a draft it cannot see the history of."""
    m = REVISED_RE.match(line.strip())
    if not m:
        raise Refusal("this entry has a %s line this script cannot read: %r. It is not safe to "
                      "judge whether the correction was already applied, so nothing was changed. "
                      "Fix or remove that line by hand." % (REVISED_LABEL, line.strip()))
    rest, dec = m.group("rest"), json.JSONDecoder()
    try:
        find, i = dec.raw_decode(rest)
        if rest[i:i + 3] != " → ":
            raise ValueError("no arrow")
        replace, j = dec.raw_decode(rest, i + 3)
        if rest[j:].strip() or not isinstance(find, str) or not isinstance(replace, str):
            raise ValueError("trailing text")
    except ValueError:
        raise Refusal("this entry has a %s line this script cannot read: %r. Nothing was "
                      "changed." % (REVISED_LABEL, line.strip()))
    return m.group("date"), m.group("source"), find, replace


def existing_revisions(entry):
    return [(i, parse_revised(ln)) for i, ln in enumerate(entry.splitlines())
            if ln.strip().startswith(REVISED_LABEL)]


def check_not_applied_before(entry, source, find, replace):
    """D6: refuse a second apply of the same correction."""
    for _i, (date, src, f, r) in existing_revisions(entry):
        if (f, r) != (find, replace):
            continue
        if src == source or find in replace:
            raise Refusal("this correction was already applied on %s (from %s): the entry "
                          "carries a %s line for the same change. Applying it again would "
                          "%s. Nothing was changed."
                          % (date, src, REVISED_LABEL,
                             "insert the text twice" if find in replace else "repeat it"))


def add_revised_line(entry, line):
    """The entry with `line` recorded: after the last existing Revised line, else after the
    last line of content (before any trailing rule or blank lines) with a blank line first."""
    lines = entry.splitlines(keepends=True)
    revs = [i for i, ln in enumerate(lines) if ln.strip().startswith(REVISED_LABEL)]
    if revs:
        at, lead = revs[-1] + 1, []
    else:
        content = [i for i, ln in enumerate(lines)
                   if ln.strip() and ln.strip() not in _RULES]
        at, lead = (content[-1] + 1 if content else len(lines)), ["\n"]
    if at > 0 and not lines[at - 1].endswith("\n"):
        lines[at - 1] += "\n"
    return "".join(lines[:at] + lead + [line + "\n"] + lines[at:])


def precondition_signature(entry):
    """Everything `precondition.py` reads off an entry body, as one comparable value. If adding
    the Revised line changes this, the line is not inert and the correction is refused."""
    m = _pre.ENTRY_RE.match(entry)
    if not m:
        return None
    title, body = m.group(1).strip(), m.group(2)
    status = _pre.STATUS_RE.search(body)
    field = _pre.FIELD_RE.search(body)
    contact = _pre.CONTACT_RE.search(body)
    return (bool(_pre.HOLD_RE.search(title) or _pre.HOLD_RE.search(body)),
            status.group(1) if status else None,
            field.group(1) if field else None,
            contact.group(1) if contact else None,
            _pre.medium_of(body))


# ── planning and applying ──────────────────────────────────────────────────────────────────


def plan(md, title, find, replace, source, date, ordinal=None):
    """Pure. Everything the step would do, or Refusal. Returns a dict:
    `new_md`, `old_entry`, `new_entry`, `line`, `diff` (the `>` lines, unified)."""
    if not SOURCE_RE.match(source or ""):
        raise Refusal("--source must be `chat` or `comment:<thread_id>` (letters, digits, "
                      "`_ . : -`); got %r. Which comment was applied must be recorded in a form "
                      "that can be read back." % source)
    if not DATE_RE.match(date or ""):
        raise Refusal("--date must be YYYY-MM-DD; got %r." % date)
    if "\r" in md:
        raise Refusal("the drafts file has CRLF line endings; this script would silently "
                      "rewrite them. Nothing was changed.")
    start, end = locate(md, title, ordinal)
    old_entry = md[start:end]
    check_not_applied_before(old_entry, source, find, replace)
    edited = apply_to_entry(old_entry, find, replace)
    line = revised_line(date, source, find, replace)
    new_entry = add_revised_line(edited, line)
    if precondition_signature(edited) != precondition_signature(new_entry):
        raise Refusal("recording the %s line would change this draft's precondition state "
                      "(its quoted find/replace text trips a hold, status, contact or medium "
                      "reading in precondition.py), which would block or release the draft as a "
                      "side effect of a wording fix. Nothing was changed. Make this edit by hand "
                      "in the drafts file and tell the user." % REVISED_LABEL)
    before_q = [ln for ln in old_entry.splitlines() if ln.lstrip().startswith(">")]
    after_q = [ln for ln in new_entry.splitlines() if ln.lstrip().startswith(">")]
    diff = "\n".join(difflib.unified_diff(
        before_q, after_q, fromfile="%s (before)" % title, tofile="%s (after)" % title,
        lineterm="", n=2))
    return {"new_md": md[:start] + new_entry + md[end:], "old_entry": old_entry,
            "new_entry": new_entry, "line": line, "diff": diff}


def refuse_unsafe_root(root):
    """A write must land in a bound, real profile (dev #81, #87, #618)."""
    if _root.is_unbound(root):
        raise Refusal("no profile is bound here (no CLAUDESEARCH_ROOT, and no profile above the "
                      "working directory), so there is no drafts file to write.")
    if _root.is_tracked_fixture(root):
        raise Refusal("%s is the tracked test fixture, which is generated; it is never written "
                      "to." % root)
    if _root.is_engine_root(root):
        raise Refusal("%s is the engine's own checkout, not a profile; it is never written to."
                      % root)


def run(root, title, find, replace, source, do_apply, date, ordinal=None, out=None):
    """Plan, print, and (with `do_apply`) write. Returns the exit code: 0, 2 refused, 1 an
    unverified write."""
    out = out or sys.stdout
    path = _tree.resolve_rel(root, _pre.FILES[0])

    def read():
        try:
            with open(path, encoding="utf-8", newline="") as fh:
                return fh.read()
        except OSError as e:
            raise Refusal("cannot read the drafts file %s: %s" % (path, e))

    try:
        if do_apply:
            refuse_unsafe_root(root)
        md = read()
        p = plan(md, title, find, replace, source, date, ordinal)
        shown = []
        shown.append("%s — entry %s in %s" % (
            "APPLYING" if do_apply else "DRY RUN (nothing is written)",
            repr(title) if ordinal is None else draft_key(title, ordinal),
            os.path.relpath(path, root)))
        shown.append("source: %s" % source)
        shown.append(p["diff"])
        shown.append("to record: %s" % p["line"])
        print("\n".join(shown), file=out)
        out.flush()
        if not do_apply:
            print("Re-run with --apply to write it.", file=out)
            return 0
        # The diff above is already on the page; now check nobody wrote under us, then write.
        if read() != md:
            raise Refusal("the drafts file changed while this step was being planned (another "
                          "session wrote it). Nothing was written; re-run the dry run.")
        _atomic.write_text(path, p["new_md"])
        if read() != p["new_md"]:
            print("WRITE NOT VERIFIED — the file on disk is not what was planned. Inspect %s."
                  % path, file=out)
            return 1
        print("WROTE %s" % os.path.relpath(path, root), file=out)
        print("recorded: %s" % p["line"], file=out)
        return 0
    except Refusal as e:
        print("REFUSED — %s" % e, file=out)
        return 2


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--draft", required=True, help="the entry's `## ` title, exactly")
    ap.add_argument("--ordinal", type=int, default=None,
                    help="1-based position among entries with the same title (required when a "
                         "title is not unique)")
    ap.add_argument("--find", required=True, help="the exact span in the sent text; must occur "
                                                  "exactly once")
    ap.add_argument("--replace", required=True, help="the new span (may be empty)")
    ap.add_argument("--source", required=True, help="`chat` or `comment:<thread_id>`")
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    ap.add_argument("--date", default=None, help="YYYY-MM-DD recorded on the Revised line "
                                                 "(default: today)")
    a = ap.parse_args(argv)
    date = a.date or datetime.date.today().isoformat()
    return run(_root.profile_root(), a.draft, a.find, a.replace, a.source, a.apply, date,
               a.ordinal)


if __name__ == "__main__":
    sys.exit(main())
