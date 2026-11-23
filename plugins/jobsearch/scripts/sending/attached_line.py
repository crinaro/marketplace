"""The `attached` line: how a drafted email's attachment is confirmed, written and read by one rule.

THE LINE. One per attached file, at the start of a line of the draft tool's result text:

    attached <sha256> <bytes> <basename>

single spaces; `<sha256>` is 64 lowercase hex digits of the bytes attached; `<bytes>` is their count in
decimal with no sign and no leading zero; `<basename>` is the file name the attachment carries and runs to
the end of the line, spaces included. A basename holding a line break of any kind (anything
`str.splitlines` splits on) cannot be written.

THE CONTRACT (docs/design-resume-docx.md §7.1 step 5, §7.2, §R2 M2-1). gmail-multi's `gmail_create_draft`
prints these lines with `format_line`; jobsearch's `outbox.py attached` reads a saved result with `parse`
and sets `carried` true only when a parsed hash and size equal its stamp. This file exists twice, byte for
byte: `plugins/gmail-multi/scripts/drafting/attached_line.py` and
`plugins/jobsearch/scripts/sending/attached_line.py`, because an install carries only its own plugin and
neither can import the other. Change one, copy it to the other: `scripts/test_mail_attached_contract.py`
holds the two identical and runs one side's real output through the other.

STRICT BOTH WAYS. `format_line` refuses a value it could not write so that `parse` reads it back.
`parse` ignores every line that does not start with `PREFIX` (the rest of a tool's result), and REFUSES,
loudly, a line that does start with it but does not match `LINE_RE`: an unreadable confirmation is never
read as "no attachment". No line at all is an empty list, which the reader decides about.

Standard library only; imports nothing of either plugin. Python 3.9+.
"""

import re
from collections import namedtuple

PREFIX = "attached "
LINE_RE = re.compile(r"^attached (?P<sha256>[0-9a-f]{64}) (?P<nbytes>0|[1-9][0-9]*) (?P<basename>.+)\Z")

Attached = namedtuple("Attached", "sha256 nbytes basename")


def format_line(sha256, nbytes, basename):
    """The one line for one attached file. ValueError when a field cannot be written and read back."""
    if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise ValueError("attached line: sha256 must be 64 lowercase hex digits, got %r" % (sha256,))
    if isinstance(nbytes, bool) or not isinstance(nbytes, int) or nbytes < 0:
        raise ValueError("attached line: bytes must be a non-negative integer, got %r" % (nbytes,))
    if not isinstance(basename, str) or not basename or "".join(basename.splitlines()) != basename:
        raise ValueError("attached line: the basename must be one non-empty line, got %r" % (basename,))
    line = "%s%s %d %s" % (PREFIX, sha256, nbytes, basename)
    if parse_line(line) != Attached(sha256, nbytes, basename):
        raise ValueError("attached line: %r does not read back" % (line,))
    return line


def parse_line(line):
    """One line that starts with `PREFIX`, as an `Attached`. ValueError when it does not match `LINE_RE`."""
    m = LINE_RE.match(line)
    if m is None:
        raise ValueError("attached line: unreadable: %r" % (line,))
    return Attached(m.group("sha256"), int(m.group("nbytes")), m.group("basename"))


def parse(text):
    """Every `attached` line of a tool's result text, in order, as `Attached` rows.

    Lines not starting with `PREFIX` are skipped. A line starting with it that does not match raises
    ValueError, naming the line."""
    return [parse_line(line) for line in text.splitlines() if line.startswith(PREFIX)]
