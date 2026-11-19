#!/usr/bin/env python3
"""move.py -- move one piece to another portfolio without losing an address (design-template-fidelity section 8 A1,
issue #877; step 1.6). Python 3.9, standard library only.

    move.py <portfolio>/<slug> <portfolio> [--repo DIR]

`content/<old>/<slug>/` becomes `content/<target>/<slug>/` (the slug is kept). The piece's published addresses
change with it, and a visitor, a bookmark or a search result may hold any of them, so the move keeps each one:

  * every HTML page the old folder published gets a `redirects` entry (old page -> new page), written through
    `siteconfig` (the one writer of site.json), and a redirect that already pointed into the old path is retargeted
    to the new one; a redirect whose address a real page now holds is removed (a page replaces it);
  * every other file the old folder published (an image, a size copy, a PDF) cannot be kept by a redirect page, so
    it is RECORDED AS RELEASED in `.site-studio/addresses.json` with the reason "moved with <slug>", and the move
    itself is recorded in `moved`; the next dry run lists those addresses and the person's approval names them;
  * `{{link:<old>/<slug>...}}` in any token-expanded file, and the home page's `featured` and `showcase` names,
    are rewritten to the new place;
  * `site.json` is written at the schema the tree then needs (the record is a schema-4 reason, so every 0.3.x
    install refuses the tree rather than publish it with no guard; section 3.1 rule 8).

The move is computed ENTIRELY IN MEMORY first, through `build.accept` (the build's own acceptance): the site as it
is, the site with the folder moved and no redirects (to learn exactly which addresses the move ends, from the
build's output and not from a guess), and the finished tree. It writes NOTHING unless the finished tree builds with
no problem and keeps or releases every address the site had. A move can therefore only refuse, never half-write.

REFUSES, writing nothing: uncommitted changes in `site/`, `content/` or `.site-studio/` (a publish leaves
HANDOFF.md uncommitted, and that does not block a move); a site below schema 3 or holding a `:::part` whose name
schema 4 fixes (the raise-schema pre-write check, R2-3, naming `build.py raise-schema`); a site that does not build
today; a source piece or target portfolio that does not exist, a reserved target name, the same portfolio, or a
name clash (the target folder, or an address under it, is already in use); and a finished tree the build refuses
(for instance a piece that lacks a key the target portfolio requires), naming the problem.

It NEVER COMMITS: it prints every path it wrote and removed, and `/site-studio:add-work` commits the move.
It does not refuse in a cloud session (R2-6): it is a content edit like add-work, and the publish refusal is the
control. Because it reads pages from `build.accept`, a later piece with detail pages is covered with no change.

The code is the package `movepiece/`: rewrite.py (the text edits), planning.py (`plan` and every refusal, in memory),
execute.py (`run`: write, print). This file is the command line.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import addresses  # noqa: E402
from building import outcomes  # noqa: E402
from contentmodel import errors  # noqa: E402
import platform_check  # noqa: E402
from configschema import diagnostics  # noqa: E402
from movepiece.execute import EXIT_REFUSED, run  # noqa: E402
from movepiece.planning import MoveError  # noqa: E402


def main(argv=None):
    rc = platform_check.windows_refusal_rc("move.py")
    if rc is not None:
        return rc
    ap = argparse.ArgumentParser(prog="move.py", allow_abbrev=False,
                                 description="Move a piece to another portfolio and keep its published addresses.")
    ap.add_argument("piece", metavar="PORTFOLIO/SLUG", help="the piece to move, such as work/harbor-lights")
    ap.add_argument("target", metavar="PORTFOLIO", help="the portfolio it moves to")
    ap.add_argument("--repo", default=".", help="the dev repo (default: the current folder)")
    args = ap.parse_args(argv)
    try:
        return run(args.repo, args.piece, args.target)
    except (MoveError, addresses.AddressError, outcomes.BuildError, diagnostics.SiteConfigError, errors.ContentError) as e:
        print("move refused: %s" % e)
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
