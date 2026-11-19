#!/usr/bin/env python3
"""build.py -- the site builder (dev #835, design sections 2.4, 3.3, 3.4, 3.5). Python 3.9, stdlib
only. It launches no browser and processes no media: size copies, metadata stripping and the
resume PDF are made at import time and committed; the build copies them and reads their
dimensions from the file headers.

TWO BUILDS, ONE FUNCTION EACH
-----------------------------
  publish_build(repo, out_dir) -> PublishResult      the only digested build
  preview_build(repo, out_dir) -> BuildResult        drafts included; has no digest, by design

`publish_build` is "one publish build, reproducible" (design 3.5). The output is a pure function of
the committed tree at HEAD (only `site/` and `content/` are ever read) and of nothing else:

  * every input comes from the commit's blobs (`git ls-tree -r -z`, `git cat-file --batch`), never
    the working tree, so uncommitted edits, ignored files and `core.autocrlf` cannot reach it;
  * no clock, no mtime, no mode, no locale, no TZ, no cwd, no PYTHONHASHSEED, no SOURCE_DATE_EPOCH;
  * every walk is sorted by the UTF-8 bytes of the NFC path; text is LF; JSON (none today) would
    be sort_keys with compact separators;
  * the digest is the SHA-256 of `<NFC path> NUL <sha256 of content> LF` per file, in that order,
    followed by ONE final line, `siteKind NUL <kind> LF`, when and only when the site's `siteKind`
    is not `portfolio` (dev #857, design-site-adoption section 9). A `hub` and a `custom` site build
    identically from the same `site/src`, yet the reviewers' briefs differ by kind, so a kind change
    must void every recorded verdict. A portfolio's digest has no such line, so it is byte-identical
    to the 0.1.0 digest and the upgrade voids no recorded review (tests/test_building_identity.PortfolioUnchanged).

BUILD DATES (named changes S6 and M2). A date the build prints comes from the newest commit that
touched BUILD INPUT -- `git log -1 --format=%ct HEAD -- site content` -- never from HEAD itself,
because HEAD moves on every commit, including the review-row commit (touching only
`.site-studio/`) that sits between a privacy review and a publish. It is rendered with
`time.gmtime`, so it is UTC and no time zone is read. `{{year}}` is that commit's UTC year; a
sitemap `<lastmod>` is the last commit touching that page's one source file or folder, as a UTC
`YYYY-MM-DD`. `SOURCE_DATE_EPOCH` is deliberately NOT read: a Nix shell exports it as 315532800
(1980), which would make the same commit build differently there and in the desktop app.
Because dates come from history, a SHALLOW repo is refused with one line (a shallow clone returns
the boundary commit's date), and a HISTORY REWRITE (rebase, squash, filter-branch) changes the
committer dates and therefore the digest: it VOIDS every privacy review recorded against the old
digest, and the content must be reviewed again. That is intended: the review is of what was built.

`preview_build` reads the working tree (tracked and untracked-but-not-ignored files), so a draft
the person is writing shows. It has no digest function and no digest attribute; the CLI's
`--digest` flag refuses together with `--drafts`.

SITE KINDS (dev #857, design-site-adoption section 4). `site.json` `siteKind` is `portfolio` (the
default: the generated home, portfolios, about and resume, as 0.1.0), `hub` or `custom`. A `hub` or
`custom` site builds every page from `site/src/` as written, with tokens expanded, and GENERATES
NOTHING: no home, no portfolio, no resume. It refuses portfolio content (`content/home.md`,
`content/about.md`, portfolio folders, a resume source) and the `work`, `resume` and `featuredFrom`
keys, and it requires `site/src/index.html`. `{{nav}}` on such a site is exactly one Home item.
Every other site.json key (redirects, budgets, privateTerms, publicEmails, cutover) applies
unchanged. Before it builds, `siteconfig.check_tree_schema` refuses a schema-1 `site.json` over a
tree that needs schema 2.

ONE HOME SOURCE (dev #856, design-site-adoption section 4.3). For a portfolio the home page has ONE
authored source: a hand-made `site/src/index.html` (the generated home is skipped; the site is schema
2) or `content/home.md` (the generated home, as 0.1.0), never both: two refuse, naming both files. With
neither, the generated home is built from the site title, as 0.1.0 does.

DISPLAY LABELS (dev #853, section 5). `work.labels` (or a portfolio's `page.md` `labels`) names what a
meta key and a group are CALLED where they are printed: the `<dt>` on a piece page, a labelled key's
value on a card (`Label: value`; a bare key prints its value alone, as 0.1.0), and a group heading on
the index. A key with no label keeps today's derived label.

SECTIONS AND THE FEATURED SELECTION (dev #852, section 6). `{{#page:X}}...{{/page}}` renders its block
only when page X is built in this build, and nothing otherwise; an X that could not exist for the site,
an unclosed section and a nested one are refused. `{{featured}}` renders the selection as cards: the
`content/home.md` `featured:` list (the default, as 0.1.0) or, under `featuredFrom: "flags"`, the pieces
whose front matter says `featured: true`, in portfolio then piece order, a draft never.

DEFAULT LAYOUT AND TOKENS. `site/templates/layout.html` is the page shell for generated pages and
must hold `{{content}}`. Tokens, in the layout, in `site/src` HTML pages and in Markdown bodies:
`{{siteUrl}} {{siteTitle}} {{name}} {{year}} {{root}} {{nav}} {{link:<page>}}`, and in the layout
only `{{title}} {{pageTitle}} {{description}} {{content}}`. An unknown token refuses the build.
`{{link:work}}` and `{{link:work/slug}}` give a RELATIVE link to a built page (generalised from
the examples' site-specific tokens). The convention for size copies is `<stem>-<width>w.<ext>`.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import platform_check  # noqa: E402
from building.acceptance import warning_line  # noqa: E402
from building.listing import format_inventory, inventory  # noqa: E402
from building.outcomes import BuildError  # noqa: E402
from building.raiseschema import raise_schema_main  # noqa: E402
from building.running import preview_build, publish_build  # noqa: E402


def main(argv=None):
    rc = platform_check.windows_refusal_rc("build.py")
    if rc is not None:
        return rc
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] == "raise-schema":
        return raise_schema_main(argv[1:])
    ap = argparse.ArgumentParser(prog="build.py", allow_abbrev=False,
                                 description="Build the site from the dev repo.")
    ap.add_argument("--repo", default=".", help="the dev repo (default: the current folder)")
    ap.add_argument("--out", help="output folder (default <repo>/site/dist, replaced each time)")
    ap.add_argument("--drafts", action="store_true", help="a preview build of the working tree")
    ap.add_argument("--digest", action="store_true", help="print the build digest (publish build only)")
    ap.add_argument("--list", action="store_true", help="list pieces, references and pages")
    ap.add_argument("--json", action="store_true", help="with --list: JSON")
    args = ap.parse_args(argv)
    if args.digest and args.drafts:
        ap.error("--digest refuses --drafts: a draft build has no digest")
    try:
        if args.list:
            inv = inventory(args.repo)
            print(json.dumps(inv, indent=2, sort_keys=True) if args.json else format_inventory(inv))
            return 0
        out = args.out
        if out is None:
            out = os.path.join(os.path.abspath(args.repo), "site", "dist")
            if os.path.isdir(out):
                import shutil
                shutil.rmtree(out)
        if args.drafts:
            res = preview_build(args.repo, out)
        else:
            res = publish_build(args.repo, out)
        print("built %d files into %s" % (len(res.files), res.out_dir))
        for n in res.notes:
            print("note: " + n)
        for w in res.warnings:      # printed on every build, at every schema; the output is the same without them
            print("warning: " + warning_line(w))
        if args.digest:
            print("digest: %s" % res.digest)
        return 0
    except BuildError as e:
        print("build refused: %s" % e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
