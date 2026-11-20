"""pane_line: the optional ` fallback=<extension|none> ext=<code|->` tail of a SWEEP block's `PANE` line (dev 858; jobsearch 0.90.0).

Capability module of `linkedin_sweep.py`, which parses the block, judges the pane and files the gap.

`PANE state=<displayed|hidden|unknown|not-pane> mode=<normal|hidden> [fallback=<extension|none> ext=<code|->]`. `fallback=extension`
says the pane could not paint and the Chrome extension took the remaining surfaces (`ext=-`, or the code of a fault it hit on the way);
`fallback=none` says it did not (`ext=` names why: a `jd_read.EXTENSION_CODES` code such as `unattended-unprobed`). A hidden pass's
`pane-hidden` gap carries that code as `fallback={extension: <code>}`, so the open gap says why the automatic switch did not happen."""

import re
import jd_read as _jd

PANE_LINE = re.compile(r"^PANE state=(?P<state>\S+) mode=(?P<mode>\S+)(?: fallback=(?P<fb>\S+) ext=(?P<ext>\S+))?$")
PANE_LINE_FALLBACKS = ("extension", "none")


def ext_codes():
    return tuple(_jd.EXTENSION_CODES)


def ext_ok(fallback, ext):
    """A PANE line's `ext`: a `jd_read.EXTENSION_CODES` code, or `-` (only beside `fallback=extension`, which met no fault)."""
    if ext == "-":
        return fallback == "extension"
    return ext in ext_codes()


def tail_error(fallback, ext):
    """The reason a PANE line's `fallback=` / `ext=` tail is refused, or None when it is absent or well formed."""
    if fallback is None:
        return None
    if fallback not in PANE_LINE_FALLBACKS:
        return "PANE fallback=%s is not one of %s" % (fallback, "|".join(PANE_LINE_FALLBACKS))
    if not ext_ok(fallback, ext):
        return "PANE ext=%s is not a Chrome-extension code (one of %s%s)" % (
            ext, ", ".join(ext_codes()), "; or - when fallback=extension met no fault")
    return None


def line_error(match, states, modes):
    """The reason a matched PANE line is refused (its state or mode outside `states` / `modes`, or its tail), else None."""
    if match.group("state") not in states:
        return "PANE state=%s is not one of %s" % (match.group("state"), "|".join(states))
    if match.group("mode") not in modes:
        return "PANE mode=%s is not one of %s" % (match.group("mode"), "|".join(modes))
    return tail_error(match.group("fb"), match.group("ext"))


def judge_tail(lines, fallback, ext):
    """Append the verdict line the tail earns to `lines`, and return the code a `pane-hidden` gap carries (`{"extension": ext}`
    only when the extension did NOT take over and said why), else None."""
    if fallback == "extension":
        lines.append("FALLBACK extension -- the Browser pane was not painting; the surfaces were read on the Chrome "
                     "extension (ext=%s)" % ext)
    elif fallback == "none":
        lines.append("!! FALLBACK none -- the Chrome extension did not take over (ext=%s)" % ext)
    return {"extension": ext} if fallback == "none" and ext not in (None, "-") else None
