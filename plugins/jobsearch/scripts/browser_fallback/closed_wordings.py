"""closed_wordings: the phrases a posting shows where Apply would be, and the one reader of them (jobsearch 0.94.0, dev 1063; docs/design-role-first.md 6.4).

`CLOSED_MARKERS` is the tuple, and `posting_fetch.CLOSED_MARKERS` is this object (posting_fetch re-exports it: its file may not grow, and the fetch's `parse` and `read-jd`'s
check must read ONE tuple). Two phrases were observed on real pages:

  "No longer accepting applications"      counts wherever it stands (its 0.93.0 rule, unchanged)
  "Not currently accepting applications"  counts in `--status-text` (the words where the Apply control is) wherever it stands, and in a quote or a page's text only when it is
                                          not followed by from, by, via, through or for: a description that says which senders it does not accept is not a closed posting

Matching is case-folded with whitespace collapsed. ENGLISH ONLY, so a page in another language is NEVER closed by a script: the reader's own `read-failed --outcome closed` with
the page's words is the path, as before. Other English phrases are not added without a seen page (OD-7).

Pure. Capability module of `recording/reads.py` and `posting_fetch.py` (a `browser_fallback` module: both already import that package). Python 3.9+, standard library only."""

import re

CLOSED_MARKERS = ("No longer accepting applications", "Not currently accepting applications")
CLOSED_MARKER = CLOSED_MARKERS[0]              # the 0.93.0 name, pinned by tests/posting_shapes.json
NOT_CLOSED_BEFORE = ("from", "by", "via", "through", "for")


def closed_hit(text, status_text=False):
    """True when `text` carries a closed phrase, by the rules in the module docstring. `status_text` says `text` IS the words where the Apply control is."""
    hay = " ".join(str(text or "").casefold().split())
    for i, marker in enumerate(CLOSED_MARKERS):
        m, at = " ".join(marker.casefold().split()), 0
        while True:
            at = hay.find(m, at)
            if at < 0:
                break
            at += len(m)
            nxt = re.match(r"\W*(\w+)", hay[at:])
            if i == 0 or status_text or not (nxt and nxt.group(1) in NOT_CLOSED_BEFORE):
                return True
    return False
