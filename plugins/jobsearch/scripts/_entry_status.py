"""Is a staged entry over? The one reading of an entry's own `**Status:**` line (dev #1071, jobsearch 0.95.0).

`drafts.md` and `cover_letters.md` entries carry a `**Status:**` line. `precondition.py` has read a line that
OPENS with `sent`, or says `moot` or `do not send`, as "over" since public #29; it kept the three patterns private
to itself, so any other reader that needed them (the cover-letter checks in `letters/`, which may not import an
entry point) had to write its own copy. This core module is the one home of the patterns and of the letters'
own, stricter answer.

* `STATUS_RE`  finds the entry's `**Status:**` line and captures its text.
* `SENT_RE`    is matched at the START of that text. Deliberately conservative: "PART A SENT · part B
               pending" is a legitimate, still-actionable mid-sequence state and is NOT closed; only a
               status that opens with "sent" asserts the whole entry is done.
* `MOOT_RE`    is searched anywhere in that text (`moot`, `do not send`, `do-not-send`).
* `is_closed(entry_text)` is the LETTERS' rule, deliberately stricter than the three patterns above (review of
  0.95.0, item 7). The first `**Status:**` text is lowercased and its leading non-letters (emoji, punctuation,
  spaces) stripped; the entry is closed iff that text BEGINS with the whole word `sent`, `submitted`, `applied`
  or `moot`. Exception: `sent to <someone> for ...` ("sent to Pat for a read-through") is a draft out for
  review, not a sent letter, so it stays pending. `do not send` never closes: "drafted; do not send until the
  referral lands" is still a letter to check. Everything else, and no Status line, is pending.

  Why the letters need more than `precondition.py`'s rule: `precondition` asks "is this draft still a send
  I owe?", where `moot` or `do not send` anywhere in the line rightly takes it off the list. The letter
  checks ask "is this letter finished, so nothing should still check it?", and a closed entry is never
  checked, so closing too much hides a letter that is still being written.
  `migrations/m_0_95_0_letter_entries.py` keeps its own frozen copy of this rule.

`precondition.py` imports the three patterns from here, so every reader of `precondition.STATUS_RE` /
`SENT_RE` / `MOOT_RE` keeps working unchanged.

A core module: standard library only, no entry point, no profile read. Python 3.9+.
"""

import re

STATUS_RE = re.compile(r"^\*\*Status:\*\*\s*(.+?)\s*$", re.M | re.I)
SENT_RE = re.compile(r"^\s*sent\b", re.I)
MOOT_RE = re.compile(r"\bmoot\b|\bdo[\s-]*not[\s-]*send\b", re.I)


_CLOSING_RE = re.compile(r"^(?:sent|submitted|applied|moot)\b")
_SENT_FOR_RE = re.compile(r"^sent\s+to\s+.+?\s+for\b")


def is_closed(entry_text):
    """True when the first `**Status:**` text opens with sent, submitted, applied or moot (the letters' rule; see the module docstring)."""
    sm = STATUS_RE.search(entry_text)
    if not sm:
        return False
    text = re.sub(r"^[^a-z]+", "", sm.group(1).lower())
    if not _CLOSING_RE.match(text):
        return False
    return not _SENT_FOR_RE.match(text)
