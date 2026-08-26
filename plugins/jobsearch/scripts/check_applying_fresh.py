#!/usr/bin/env python3
"""Is `views/applying.md` STALE — does it predate the records it is supposed to show?

WHY THIS EXISTS
----------------
`applying.py` (public #27 / dev #233) generates the working view for an application session:
D5 — "records generate this view; nothing here is authored" — but D5's other half, that a
generated view is DECLARED *and* GATED, was only ever half true for this one. It was declared
(applying.py exists, application-session/SKILL.md regenerates it at open and close) and never
gated: nothing measured whether the file on disk still matched the records it claims to
summarize. `check_dashboard_fresh.py` is the shape this copies — mtime, oldest-member-of-the-
set — but scoped to what THIS view actually reads, not inherited wholesale from the dashboard's
own list (kb/, call_preps/, resume.md and channels.jsonl feed the dashboard; none of them are
read anywhere in applying.py's render path).

⭐ THE SOURCES BELOW ARE DERIVED FROM READING applying.py's render(), NOT COPIED. The dashboard's
own freshness gate shipped for months silently skipping kb/ and call_preps/ because its SOURCES
list was extended by memory rather than by re-reading what the generator actually touches (dev
#233's own fix note). Copying that list here would reproduce the exact trap on a different view:
`render()` calls `trigger.report()`, which reads `opportunities.jsonl`, `asks.jsonl`,
`messages.jsonl`, and (via `precondition.report()` and `draft_rows()`) `drafts.md` and
`cover_letters.md` — and `render()` itself separately loads `companies.jsonl` for the display
name. That set, and nothing more, is SOURCES below.

⚠️ `views/applying.md` is NOT an Artifact — it is opened directly, in session, never published
(generate_dashboard.py's own docstring: "the working surface for applying is NOT here and not
an artifact at all"). So there is no publish dimension to this gate, unlike
check_dashboard_fresh.py's two: mtime staleness is the whole story here.

    ⚠️ mtime, not content. A fresh view can still be wrong for other reasons — the standing
    habit from check_dashboard_fresh.py applies here too: grep the output after regenerating.

Usage:
    python3 check_applying_fresh.py            # exit 1 if stale
    python3 check_applying_fresh.py --fix       # regenerate (applying.py), then re-check

Python 3.9+. Standard library only.
"""

import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _root import profile_root as _profile_root
import _tree
ENGINE_SCRIPTS = os.path.dirname(os.path.realpath(__file__))

ROOT = _profile_root()

OUTPUT = "views/applying.md"

# Read directly from applying.py's render(): trigger.report() (opportunities/asks/messages +
# precondition/draft_rows' drafts.md+cover_letters.md) plus render()'s own companies.jsonl
# load for the display name. Nothing else is opened anywhere in the render path.
SOURCES = [
    "data/opportunities.jsonl", "data/companies.jsonl",
    "data/asks.jsonl", "data/messages.jsonl",
    _tree.rel("drafts"), _tree.rel("cover_letters"),
]


def mtime(p):
    return os.path.getmtime(p) if os.path.exists(p) else 0


def stale():
    """[(source, seconds_newer)] relative to an EXISTING view (empty means current), or
    None if the view has never been generated at all.

    ⚠️ 'never generated' is a DISTINCT state from 'stale', deliberately — a profile that has
    never run application-session has nothing queued to show, and reporting that as a
    failure would be a red a fresh install can never clear on its own, same trap
    check_dashboard_fresh.py's 'never-published' state exists to avoid (coordinator.py #1:
    "a gate a user cannot satisfy is not a gate")."""
    out_path = os.path.join(ROOT, OUTPUT)
    d = mtime(out_path)
    if not d:
        return None
    bad = []
    for s in SOURCES:
        m = mtime(_tree.resolve_rel(ROOT, s))
        if m > d:
            bad.append((s, int(m - d)))
    return bad


def main():
    ap = argparse.ArgumentParser(description="Is views/applying.md behind its sources?")
    ap.add_argument("--fix", action="store_true", help="Regenerate, then re-check.")
    args = ap.parse_args()

    bad = stale()
    if args.fix and (bad is None or bad):
        print("Regenerating (%s)..."
             % ("never generated yet" if bad is None else "%d source(s) newer" % len(bad)))
        r = subprocess.run([sys.executable, os.path.join(ENGINE_SCRIPTS, "applying.py")],
                           capture_output=True, text=True)
        print("  " + (r.stdout.strip().splitlines() or ["?"])[-1])
        if r.returncode:
            print("  !! applying.py failed:\n" + r.stderr.strip()[:400])
            return 1
        bad = stale()

    if bad is None:
        print("APPLYING VIEW NEVER GENERATED — no application session has run yet; nothing "
             "to compare.")
        print("  Run 'python3 applying.py' (or open application-session) once this check is "
             "armed.")
        return 0

    if not bad:
        print("APPLYING VIEW CURRENT — no source is newer than %s." % OUTPUT)
        print("  (Freshness is not correctness: still GREP THE OUTPUT for what you added.)")
        return 0

    print("⚠️  APPLYING VIEW IS STALE — %d source(s) are newer than %s." % (len(bad), OUTPUT))
    print("=" * 72)
    for s, secs in sorted(bad, key=lambda x: -x[1]):
        mins = secs // 60
        print("  %-32s newer by %s" % (s, "%d min" % mins if mins else "%d sec" % secs))
    print("\n  applying.py's own read-only-by-construction rule (D5) only holds if the file")
    print("  on disk actually reflects the record — a stale queue can point at a resume")
    print("  variant, hold, or precedent that has since changed underneath it.")
    print("\n  Fix:  python3 scripts/check_applying_fresh.py --fix")
    return 1


if __name__ == "__main__":
    sys.exit(main())
