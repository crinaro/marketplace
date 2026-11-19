#!/usr/bin/env python3
"""review_record.py -- the privacy-review record the publish script binds (dev #835, design 7.2,
named changes M2, M4, M12(a)). Python 3.9, standard library only.

    review_record.py begin   [--repo R]
    review_record.py add     --packet P --verdict clear|accepted|blocked --opened PATH [--opened ...]
                             [--findings FILE] [--accept F1,F3] [--repo R]
    review_record.py verdict DIGEST [--repo R]

WHAT IT GUARANTEES (and what it does not)
-----------------------------------------
`begin` runs `build.publish_build` into `.site-studio/review/build/` (an ignored folder), computes
the digest ITSELF, then the COVERAGE SET, and writes `.site-studio/review/packet.json`. `add` has
NO `--digest` argument: it rebuilds, recomputes the digest, and refuses unless it equals the
packet's. So a verdict is bound to a build this script computed, and any later byte change voids
it. A `blocked` row for a digest wins over any `clear`. ONE ROW KIND IS NOT A REVIEW (0.4.0, owner
ruling 2026-11-18): the one-process `adopt.py apply` records a `parity-EQUAL+scans` stand-in when
parity is EQUAL and every automated privacy scan passed on the exact built tree; `reviews/rows.py`
reads it, refuses any other shape of it, and every reader says it is not an agent's review. Whether the reviewing agent REALLY looked
at each file it lists as opened, whether its judgement is right, and which PAGES it actually read
are model judgement and are NOT measured; the control is the person at the publish prompt
(design 7.4). The packet and the store sit in the person's own repo with no signature: this
record protects against drift and accident, not against a model set on forging it.

THE PACKET carries `siteKind` (packet `v` 2, dev #857, design-site-adoption section 9), so the privacy
reviewer is TOLD whether it is looking at a portfolio, a links `hub` or a hand-made `custom` site. A
hub or custom site's build digest also folds the kind in (build.py's module docstring), so changing
the kind voids every recorded verdict; a portfolio's digest is unchanged, so the 0.2.0 upgrade
voids none. A `v` 1 packet, left by 0.1.0, is refused with "run begin again".

THE COVERAGE SET (named change M4) is the COMPLEMENT of an allow-list, not a list of kinds
-----------------------------------------------------------------------------------------
Every built file that is NEW or CHANGED against the baseline AND is not on the short list of
pure-text types the pattern families already scan completely (`.css`, `.txt`, `.xml`, plus the
files named `CNAME` and `.nojekyll`). HTML pages ARE in the set (page text is the main judgement
surface), and so is every type this file has never heard of: `.svg` (carries text), video, audio,
fonts, `.zip`, `.docx`, `.js`, `.json`. The count per type is printed. The first version of this
rule named only images, PDFs and capture cards; an SVG or a changed page then needed no listing.
PDFs the pattern gate could not read (NOT READ, design 7.1) are added to the set explicitly.

THE BASELINE is the live site: `gh api repos/<publicRepo>/git/trees/main?recursive=1`, git blob
ids, compared with each built file's blob id (SHA-1 of `blob <n>\\0<bytes>`, the same value
`git hash-object` prints, computed here without a process). A tree the API marks
`truncated: true`, a failed read, no `gh`, no public repo, or a repo with no `main` yet is "no
baseline": then EVERY file not on the allow-list is in the set, and the output says which baseline
was used. A truncated baseline is never treated as complete.

THE STORE (`.site-studio/reviews.jsonl`) is read strictly (CLAUDE.md principle 4): an unparseable
line, an unknown `v`, a missing or unknown field refuses LOUDLY with the line number. Never
skipped. A row is stale by digest, never by age.

`add` appends then commits ONE path, in this order (named change M12(a)): `git add --
.site-studio/reviews.jsonl`, then `git commit -- .site-studio/reviews.jsonl`. For the first review
the file is untracked, and `git commit -- <untracked path>` alone fails; the explicit add comes
first. The commit takes only that path, so anything else the person has staged stays staged. It
never pushes. `.site-studio/review/` is kept out of the tree with an ignore line.

THE LIBRARY is the `reviews/` package (the coverage set, the store, the dry-run record, the packet, `begin`, `add`; one module each), shared
with `deploying/` and `guarding/`. This file is the entry point only: the argument grammar, one dispatch, the printing and the exit code.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import platform_check  # noqa: E402
from reviews.addrow import add  # noqa: E402
from reviews.basics import ReviewError  # noqa: E402
from reviews.begin import begin  # noqa: E402
from reviews.packet import format_begin  # noqa: E402
from reviews.rows import STORE_REL, VERDICTS  # noqa: E402
from reviews.store import verdict_for  # noqa: E402


def main(argv=None):
    rc = platform_check.windows_refusal_rc("review_record.py")
    if rc is not None:
        return rc
    ap = argparse.ArgumentParser(prog="review_record.py", allow_abbrev=False,
                                 description="The privacy-review record.")
    sub = ap.add_subparsers(dest="cmd")
    sub.required = True
    b = sub.add_parser("begin", allow_abbrev=False)
    b.add_argument("--repo", default=".")
    a = sub.add_parser("add", allow_abbrev=False)
    a.add_argument("--repo", default=".")
    a.add_argument("--packet", required=True)
    a.add_argument("--verdict", required=True, choices=VERDICTS)
    a.add_argument("--opened", action="append", default=[], metavar="PATH")
    a.add_argument("--findings", help="JSON list of {id, path, summary} the reviewer returned")
    a.add_argument("--accept", default="", help="comma-separated finding ids")
    v = sub.add_parser("verdict", allow_abbrev=False)
    v.add_argument("digest")
    v.add_argument("--repo", default=".")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "begin":
            print(format_begin(begin(args.repo), os.path.abspath(args.repo)))
        elif args.cmd == "add":
            row = add(args.repo, args.packet, args.verdict, args.opened,
                      args.accept.split(","), args.findings)
            print("recorded %s for %s (%d files opened) and committed %s; nothing was pushed"
                  % (row["verdict"], row["digest"][:12], len(row["opened"]), STORE_REL))
        else:
            status, row = verdict_for(args.digest, args.repo)
            print("%s%s" % (status, "" if row is None else " (recorded %s)" % row["at"]))
            if status == "none":
                print("no review for this digest: run the review step")
        return 0
    except ReviewError as e:
        print("review refused: %s" % e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
