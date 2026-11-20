#!/usr/bin/env python3
"""look.py -- choose, vendor, check and DERIVE a site's look (design-template-fidelity section R5.4, step 1.8D;
issue #909; decisions 33 and 38; R5N-13, R5N-15, R5N-16). Python 3.9, standard library only.

    look.py list                                  the looks site-studio ships, and the looks this site carries
    look.py use <id|path> [--accept-literals]     copy a look (and the stylesheets it names) into this site
    look.py check                                 read this site's look: omitted constructs, literal words, files,
                                                  and a schema-5 setting the look gives no place to print
    look.py derive [--build DIR | --url URL] [--owned-host HOST] [--name NAME] [--replace]
                                                  make a look from a site this repository's content built

Every command takes `--repo DIR` (default: the current folder). NOTHING here commits: a command prints each path it
wrote, and the skill that ran it commits them.

`use` copies a shipped look (`templates/looks/<id>.json`, stylesheets from `templates/looks/<id>.css`) or a look file
from another repository (`<path>`, stylesheets from that repository's `site/src/`) to `site/looks/<id>.json`, and
writes the site.json `look` key through `siteconfig` (the one writer) at schema 4, or at schema 5 when a look in the
tree needs site-studio 0.5.0 (a new construct, part, slot or asset kind; design-movement-view section 3.4), and says so;
`derive` writes site.json the same way when the look it writes raises the schema. It NEVER OVERWRITES: a target that
exists with other bytes refuses, naming it; identical bytes print "already in place". A look holding literal words
(any letter in a text node or a text attribute) is listed by construct and part and refused without
`--accept-literals`: the person is shown the words first. The finished tree is built in memory before a byte is
written, so a look that makes the site unbuildable refuses and writes nothing. `check` and `use` print the build's own
lines for a schema-5 setting (`cardKicker`, `cardImage` under `view: roles`, `pieceLink`, `pieceTeaser`) whose slot
the look leaves out (design-movement-view section 4.4): "refused: ..." where no part can print it, "note: ..." for a
part of the site's own look that leaves the kicker out; `check` also notes a `steps-view.item` with no `{{number}}`.

`derive` reads this repository's CONTENT at HEAD, builds it in memory (recording every `looks.render` call: the values
each slot got), and finds each construct instance in the pages of the site the content produced. Nothing is a model's
guess: the instance's text values are looked for in the page (TEXT ANCHORING, design R5.4(f)).

  1. Anchor. For one instance the plugin knows its slot values. In a page it finds the LOWEST element whose text (and
     attribute values) hold every one of them; it moves the anchor up where the instance is also its own child's
     anchor, and out over single-child wrappers (`li > a`), never past the part that owns it. A child part is anchored
     inside its parent's element. A part with no slot at all (a fixed heading) is placed by its neighbours and its
     page text is kept as the person's own literal text. OURS, deliberately weaker than the design's "in order": the
     lowest element holding every value, in any order, because a value may sit in an attribute and an attribute has
     no place in a text order; the cross-instance check below is what proves the result. Two things the page may not
     hold are left out of the search (step 1.9, finding F-c, from markup a template writes): a value the plugin's own
     markup writes into an ATTRIBUTE only (a `label`, an `alt`) is only used to anchor a part with nothing else to anchor
     on, because the template may carry no such attribute and a word of it found elsewhere (a title that says "Quotes")
     would pull the anchor out over its neighbours; and a value found NOWHERE in the scope (a host name the template
     does not show) is dropped, so the instance anchors on the values the page does show and the template has no slot
     for the rest. A child alone in its wrapper (a block that is all of a piece's body) is read both ways, the wrapper
     the child's or the parent's, and the instances of the part decide (the reading the other instances can share wins).
  2. Template. The anchor's subtree is serialised; each child's element becomes `{{slot}}`; a text node or attribute
     value that equals a slot's value, or holds it as a whole word, becomes that slot; a url attribute equal to a url
     slot's value becomes that slot. A NUMBER becomes `{{n}}` or `{{count}}` only where at least two instances
     disagree on it AND the digits at that place equal the slot's value in every instance (so a digit that happens to
     equal the count, such as the 3 in `col-3`, stays literal; held-out case `look-derived`).
  3. Agree. Every instance of one part yields one template, or the construct is `ambiguous`; the candidate is filled
     back with each instance's values and must equal that instance's own page text. Two non-nested anchors that give
     different templates are `ambiguous` too. Where the instances do not all agree but MORE THAN HALF share one markup,
     that markup is the part's template and the others are named `ambiguous` (a menu link the template points at a
     piece where the plugin points at the portfolio): one odd instance does not take the construct away, and the page
     it is on stays DIFFERENT in parity, which is what says so.
     A WRAPPER NEITHER OWNS ALONE (G3 flip). A part that stands alone in a wrapper can have the wrapper as its own or leave it to
     its parent, and a part used in two places (an image in a card, an image in a showcase tile that wraps it in a span) must
     read the same in both. When the first reading leaves an instance `ambiguous`, the pages are read again preferring, of the
     readings that take one element, the one that leaves the wrapper to the PARENT (the parts below hold the least markup): a
     wrapper a part owns only serves the places that carry it. The reading that maps more instances is the answer, and the first
     reading stays the answer when they tie, so a site that derived cleanly derives as it always did.
     A PART THE TEMPLATE WRITES IN ANOTHER SHAPE (step 1.10, the derive limits G3 left). (a) A part the plugin writes as several sibling
     elements (`heading-multi`: a count span, a name span) that the page holds as one element (an `h3` around the name and a count
     badge) is that element: where no run of siblings matches the plugin's own, the part is read as the one element that holds what
     the page shows of it (`_one`). (b) A part that fills the element its parent owns (`previously-item`: a span around a link and a
     period, which the template writes as a span and an `i` side by side inside the parent's `p`), or two parts that fill one element
     (two earlier roles in one `p`), are RUNS of that element's children, each from where the one before ended to the last child that
     holds one of its values (`_runs_for_sharers`). That reading is offered after the others and is only the one taken where the
     others would reach over a sibling part: the parts of one parent are side by side, never one inside another (`_choose`). (c) A
     slot the plugin's markup does not show, whose value the template shows as the WHOLE text of a line (the employer in a company
     line the plugin's item does not have), is that slot, never the person's own words (`_text_slot`): a word that is merely one of
     several in a line stays literal. (d) A value that is only a part of another value of the same instance ("Client" beside
     "Invented Client") is found at a place of its own: the longer value takes its occurrence out of the text first (`_holds_apart`);
     where no element holds them so, the instance anchors as it always did. (e) A part that could not be mapped does not take the
     parts inside it with it: each of them is read on its own inside the element that held the whole of it (`settle`), one reading
     only (a list of one stays `unmapped`: the parent decided it and the parent is gone), never over an element another of those
     parts holds, and LAST, so it only adds: where it disagrees with what the other instances fixed it is named `ambiguous` and
     what they fixed stands.
  3b. Counting instances, and a heading beside a list of one (G3 derive link 2). A reading may also COUNT INSTANCES (`derive_look`, the
     third and fourth readings): a markup more instances cannot share (`_merge`) than can is OUTVOTED, and an instance every reading
     of which holds an outvoted part is read last, its other parts committed and the outvoted ones offered after every other instance
     has fixed its markup, so one page that wraps its lone reference card in a grid is the page that differs (named `ambiguous`), not
     the home page whose feed and samples write the card bare. Where no reading of an instance agrees with what is accepted, the
     reading with the fewest disagreeing parts is kept and only those parts are named `ambiguous` (a home page keeps its wrapper, its
     heading and every part inside it where one list of links is marked up as the resume page marks it; which markup stands is the one
     accepted first when the instances tie). A part whose own markup is a wrapper around a FIXED element and a slot (the section
     around `<h2>Featured</h2>` and the list) is also read as the wrapper that holds its extent and that element (`_fixed_beside`): a
     list of ONE says nothing else of whose the section is. The fourth reading is told what the third kept, so that list reads as the
     lists of several do.
  4. Validate. A template the grammar refuses (`looks.check_part`: a script, an event attribute, an off-origin link,
     an element a look may not carry) makes the construct `unmapped`; it is never written.
Not expressible, said once: whitespace between items that is not the same between every item, a wrapper two levels
above its part that holds other content, a link the template writes in another form than the plugin does (root-relative
against relative), a construct used inside Markdown text (not at the top of its slot), and first/last/odd/even
classes. Each of them is reported `unmapped` or `ambiguous`; none is guessed.

THE REPORT (R5.4(g)): one line per construct id, `mapped`, `unmapped` (a page was read, nothing anchored),
`ambiguous` (two templates disagree) or `not reached` (the page was never read), with instance counts; then the
text-bearing elements no content explains, counted by element name only (`element/<tag>`), never echoed. A look the
person keeps holds structure PLUS the person's own literal text, and `check` and `use` list each literal. It lives
in whichever repository the person derives into, public or not; nothing here claims it is private. Outside adopt
nothing is filed anywhere; inside adopt an `unmapped` or `ambiguous` construct that leaves parity DIFFERENT is a
`look/` cause.

PRECONDITION (R5.4(c)). derive runs in the repository whose site-studio content produced the pages (`site/site.json`
readable). Not a site-studio tree: "derive needs the content that built the pages; adopt that site first". No instance
anchors on any page read: "these pages were not built from this repository's content", never an all-`unmapped`
report. For a new site, derive in the old site's repository, then `look.py use <path>` in the new one.

WHERE THE PAGES COME FROM. `--build DIR`: a folder of built pages on this machine; no network, no ownership question.
Otherwise the person's published pages, fetched with `urllib`: the start page is the `publicRepo` Pages address
(`gh api repos/<o>/<r>/pages`) or `--url`; at most 40 pages, 2 MB and 10 s each, `text/html` only, no script,
stylesheet, image or font; each response's final address must stay in the owned set; `robots.txt` is read first (2xx
honoured for the token `site-studio`, 404 allows all, any other answer refuses and names `--build`). The pages are
held in memory: nothing is spooled to a scratch folder, so there is nothing to delete after the run.

OWNERSHIP (R5.4(d), decision 33; NOT ENFORCED). The person's own Pages host set (`html_url`'s host and `cname`) is
accepted with no question. Any other host only with `--owned-host <host>` AND a confirmation this script reads from
its own terminal (the person types the host back); with no terminal on stdin it refuses and prints the command to run
in the person's own terminal. NOT ENFORCED, said where it is read (R5N-13): a terminal shows that a pseudo-terminal
exists, not that a person owns the host, and a caller can allocate one; the check stops an ordinary Bash call, nothing
more, and the output prints "ownership not verified". With no person (a cloud session, a scheduled run) only the Pages
set is accepted. Each gh failure refuses with its own fix and never says "not yours": gh missing, not logged in, no
`publicRepo`, Pages not enabled, GitHub not reachable (the error class only). Anything else: "deriving a look from a
site you do not publish is not supported".

SSRF (R5N-15; DOCUMENTED: the OWASP Server-Side Request Forgery Prevention Cheat Sheet, allowlist the destination and
check the RESOLVED address, redirects included). `host_allowed(address)` is the one seam: every connection resolves
its host, every resolved address must pass, and the socket is opened to the address that passed (so a name cannot
change its answer between the check and the connection). Loopback, link-local, private, shared, multicast and
reserved addresses are refused. A redirect is checked before it is followed. Tests reach a local server by patching
`host_allowed`; no environment variable or flag switches it off. With an HTTP(S) proxy configured the connection is
made by the proxy, whose address this script cannot check, so derive refuses: "a proxy is configured: derive with
--build".

THE COMMAND THE PERSON RUNS (R5N-16). `owned_host_command()` builds it fresh each time: the running interpreter's
absolute path, this script's absolute path resolved from the running install, and a `cd` to the site repository, every
piece quoted. It is printed, never stored, never written to a file.

EXIT CODES: 0 done; 1 refused (the line says what to do); `derive` also exits 1 when nothing could be mapped.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import addresses  # noqa: E402
import looks  # noqa: E402
import platform_check  # noqa: E402
from building import outcomes  # noqa: E402
from configschema import diagnostics  # noqa: E402
from contentmodel import errors  # noqa: E402
from lookfiles.commands import DEFAULT_NAME, EXIT_REFUSED, Env, check_command, derive_command, list_command, use_command  # noqa: E402
from lookfiles.refusals import LookCommandError  # noqa: E402


# ==================================================================================================== the command
def main(argv=None):
    rc = platform_check.windows_refusal_rc("look.py")
    if rc is not None:
        return rc
    ap = argparse.ArgumentParser(prog="look.py", allow_abbrev=False,
                                 description="Choose, copy, check and derive a site's look.")
    sub = ap.add_subparsers(dest="cmd")
    sub.required = True
    for name in ("list", "check"):
        p = sub.add_parser(name, allow_abbrev=False)
        p.add_argument("--repo", default=".", help="the site's repository (default: the current folder)")
    p = sub.add_parser("use", allow_abbrev=False)
    p.add_argument("look", metavar="ID_OR_PATH")
    p.add_argument("--accept-literals", action="store_true", help="copy a look that carries literal words")
    p.add_argument("--repo", default=".")
    p = sub.add_parser("derive", allow_abbrev=False)
    p.add_argument("--build", metavar="DIR", help="read built pages from this folder (no network)")
    p.add_argument("--url", help="start page of the published site (default: your Pages address)")
    p.add_argument("--owned-host", metavar="HOST", help="a host you publish on that is not your Pages address")
    p.add_argument("--name", default=DEFAULT_NAME, help="the look's name (default: %s)" % DEFAULT_NAME)
    p.add_argument("--replace", action="store_true", help="overwrite a look of the same name")
    p.add_argument("--repo", default=".")
    args = ap.parse_args(argv)
    env = Env()
    try:
        if args.cmd == "list":
            return list_command(args.repo, env)
        if args.cmd == "check":
            return check_command(args.repo, env)
        if args.cmd == "use":
            return use_command(args.repo, args.look, args.accept_literals, env)
        return derive_command(args.repo, args.build, args.url, args.owned_host, args.name, args.replace, env)
    except (LookCommandError, outcomes.BuildError, addresses.AddressError, diagnostics.SiteConfigError,
            errors.ContentError, looks.LookError) as e:
        print("look refused: %s" % e)
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
