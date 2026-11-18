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
"""
import argparse
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import addresses  # noqa: E402
import build  # noqa: E402
import content as C  # noqa: E402
import platform_check  # noqa: E402
import siteconfig  # noqa: E402

EXIT_OK, EXIT_REFUSED = 0, 1
REASON = "moved with %s"
_HOME_FILES = ("content/home.md", "content/home/index.md")
_FRONT_KEYS = ("featured", "showcase")


class MoveError(ValueError):
    """A refusal. The message is the line the person reads and names what to do."""


def nfc(s):
    return unicodedata.normalize("NFC", s)


def link_pattern(old_key):
    """`{{link:<old_key>}}`, `{{link:<old_key>/...}}`, `#` and `?` forms: never a longer name that merely starts
    the same (`harbor-lights-2`)."""
    return re.compile(r"(\{\{\s*link:)" + re.escape(old_key) + r"(?=[/#?]|\s*\}\})")


def rewrite_links(text, old_key, new_key):
    """(new text, count) with every `{{link:<old_key>...}}` pointing at `new_key`."""
    return link_pattern(old_key).subn(lambda m: m.group(1) + new_key, text)


def rewrite_front_names(text, old_key, new_key):
    """(new text, count): the piece name in the `featured` and `showcase` lists of a home page's front matter,
    where `old_key` stands alone (a showcase entry's image path, `media/<old_key>.jpg`, is not a name)."""
    if not text.startswith("---\n"):
        return text, 0
    lines = text.split("\n")
    end = next((i for i in range(1, len(lines)) if lines[i].rstrip() == "---"), None)
    if end is None:
        return text, 0
    name = re.compile(r"(?<![A-Za-z0-9/_.-])" + re.escape(old_key) + r"(?![A-Za-z0-9/_.-])")
    key, total = None, 0
    for i in range(1, end):
        m = re.match(r"^([A-Za-z][A-Za-z0-9_]*):", lines[i])
        if m:
            key = m.group(1)
        if key in _FRONT_KEYS:
            lines[i], n = name.subn(new_key, lines[i])
            total += n
    return "\n".join(lines), total


def _decode(raw):
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _site_json(cfg, redirects, files, record_text, at_least):
    """The site.json text for `cfg` with `redirects`, written by siteconfig at the schema the tree needs (never
    below `at_least`)."""
    d = cfg.to_dict()
    d["redirects"] = dict(redirects)
    new = siteconfig.parse_data(d)
    tree = dict(files)
    if record_text is not None:
        tree[addresses.RECORD_REL] = record_text.encode("utf-8")
    return siteconfig.canonical_text(new, tree, C.interpretation_reasons(tree), at_least=at_least)


def _redirect_out(old):
    """The output path `build.build_redirect` writes for a redirects key."""
    clean = old.strip("/")
    return clean if clean.lower().endswith(build.HTML_EXTS) else clean + "/index.html"


def _retarget(new, old_key, new_key):
    """A redirect target that pointed into the old piece, pointed at the new one; anything else unchanged."""
    if re.match(r"^https?://", new):
        return new
    clean = new.strip("/")
    if clean == old_key or clean.startswith(old_key + "/"):
        return new_key + clean[len(old_key):]
    return new


def _problem_text(acc, cap=3):
    """The first `cap` problems of an acceptance, each as the build words it, and how many more there are."""
    lines = [p.line() for p in acc.problems[:cap]]
    more = len(acc.problems) - cap
    return "; ".join(lines) + ("; and %d more" % more if more > 0 else "")


def _accept_or_refuse(tree, what):
    acc = build.accept(dict((k, v) for k, v in tree.items() if k.startswith(("site/", "content/"))))
    if acc.problems:
        raise MoveError("%s (%s); nothing was changed, so fix what it says, then run the move again"
                        % (what, _problem_text(acc)))
    return acc


def plan(files, record, old, slug, target):
    """The whole move, computed in memory. `files` is {path: bytes} for `site/` and `content/`, `record` the
    current address record. Returns (tree, removed, report): `tree` the finished {path: bytes} (site.json and the
    record included), `removed` the sorted paths that no longer exist, `report` the lines to print. Raises
    `MoveError` on any refusal; nothing is written here."""
    raw = files.get("site/site.json")
    if raw is None:
        raise MoveError("site/site.json is not in this folder; run this inside the dev repo")
    cfg = siteconfig.parse_text(raw.decode("utf-8", "replace"))
    if cfg.siteKind != "portfolio":
        raise MoveError("this is a %s site, which has no portfolios and no pieces to move; run move.py in a portfolio "
                        "site" % cfg.siteKind)
    addresses.check_prewrite(cfg, files)
    old_key, new_key = "%s/%s" % (old, slug), "%s/%s" % (target, slug)
    old_dir, new_dir = "content/%s/" % old_key, "content/%s/" % new_key
    if old == target:
        raise MoveError("%s is already in %s; name a different portfolio" % (old_key, target))
    if target in C.RESERVED_PORTFOLIO_NAMES:
        raise MoveError("%s is a reserved name, not a portfolio; name one of the site's portfolios" % target)
    pre = _accept_or_refuse(files, "this site does not build today, so a move cannot be checked; fix that first")
    names = [pf.slug for pf in pre.model.portfolios]
    if old not in names:
        raise MoveError("%s is not a portfolio of this site (%s); write the piece as <portfolio>/<slug>"
                        % (old, ", ".join(names) or "none"))
    if target not in names:
        raise MoveError("%s is not a portfolio of this site (%s); name one of them, or create the portfolio "
                        "first" % (target, ", ".join(names)))
    if old_dir + "index.md" not in files:
        raise MoveError("%s has no piece %s (content/%sindex.md is missing); check the name with `build.py "
                        "--list`" % (old, slug, old_key + "/"))
    if any(p.startswith(new_dir) for p in files):
        raise MoveError("%s already exists in %s; rename one of the two pieces first, then move" % (slug, target))
    # the site as it is and as it would be with the folder moved, neither carrying a redirect: the difference of
    # their outputs is exactly the set of addresses the move ends
    base_files = dict(files)
    base_files["site/site.json"] = _site_json(cfg, {}, files, None, cfg.schema).encode("utf-8")
    moved_files = dict(base_files)
    for path in sorted(files):
        if path.startswith(old_dir):
            moved_files[new_dir + path[len(old_dir):]] = moved_files.pop(path)
    report, rewrote = [], []
    for path in sorted(moved_files):
        text = _decode(moved_files[path]) if siteconfig._expanded_file(path) else None
        if text is None:
            continue
        new_text, n = rewrite_links(text, old_key, new_key)
        if path in _HOME_FILES:
            new_text, m = rewrite_front_names(new_text, old_key, new_key)
            n += m
        if n:
            moved_files[path] = new_text.encode("utf-8")
            rewrote.append((path, n))
    before = _accept_or_refuse(base_files, "this site does not build without its redirects, so a move cannot be "
                                           "checked; fix that first")
    mid = _accept_or_refuse(moved_files, "the site does not build once %s is in %s" % (slug, target))
    old_prefix, new_prefix = nfc(old_key) + "/", nfc(new_key) + "/"
    clash = sorted(p for p in before.output if nfc(p).startswith(new_prefix))
    if clash:
        raise MoveError("an address under %s is already in use (%s); rename the piece or move the other one first"
                        % (new_key, clash[0]))
    lost = sorted(p for p in before.output if p not in mid.output)
    pages = [p for p in lost if addresses.is_html(p) and p in before.pages]
    others = [p for p in lost if p not in pages]
    real_pages = set(mid.output)
    redirects = {}
    for key, value in sorted(cfg.redirects.items()):
        if _redirect_out(key) in real_pages:
            report.append("removed redirect %s: a page now lives at that address" % key)
            continue
        redirects[key] = _retarget(value, old_key, new_key)
    dropped = []
    for path in pages:
        counterpart = new_prefix + nfc(path)[len(old_prefix):]
        key = build._page_dir(path)
        if counterpart in mid.output and key and key != build._page_dir(counterpart):
            redirects[key] = build._page_dir(counterpart)
            report.append("redirect %s -> %s" % (key, build._page_dir(counterpart)))
        else:
            dropped.append((path, REASON % slug))
    dropped.extend((p, REASON % slug) for p in others)
    new_record = addresses.merge(record, dropped=dropped, moved=[(old_key, new_key)])
    record_text = addresses.dump(new_record)
    at_least = max(4, cfg.schema)
    final = dict(moved_files)
    final["site/site.json"] = _site_json(cfg, redirects, moved_files, record_text, at_least).encode("utf-8")
    final[addresses.RECORD_REL] = record_text.encode("utf-8")
    after = _accept_or_refuse(final, "the finished site would not build")
    for path in sorted(before.output):
        if path not in after.output and path not in set(d[0] for d in dropped) and \
                path not in set(d["path"] for d in record["dropped"]):
            raise MoveError("this move would end %s without a redirect or a record; nothing was changed, and this "
                            "is a fault to report with /site-studio:report" % path)
    for path, why in dropped:
        report.append("released %s (%s)" % (path, why))
    for path, n in rewrote:
        report.append("rewrote %d reference%s in %s" % (n, "" if n == 1 else "s", path))
    report.append("recorded the move %s -> %s in %s" % (old_key, new_key, addresses.RECORD_REL))
    report.append("site/site.json: written at schema %d" % siteconfig.parse_text(
        final["site/site.json"].decode("utf-8")).schema)
    removed = sorted(p for p in files if p.startswith(old_dir))
    return final, removed, report


def run(repo, piece, target, out=None):
    out = out or sys.stdout
    parts = piece.split("/")
    if len(parts) != 2 or not all(C.SLUG_RE.match(p) for p in parts) or not C.SLUG_RE.match(target):
        raise MoveError("write the piece as <portfolio>/<slug> and the target as <portfolio>, each in lower-case "
                        "letters, digits and hyphens (work/harbor-lights writing)")
    old, slug = parts
    repo = _toplevel(repo)
    addresses.require_clean(repo)
    files = build._disk_files(repo)
    record = addresses.read_record_file(repo)
    final, removed, report = plan(files, record, old, slug, target)
    written = sorted(p for p in final if files.get(p) != final[p] or p == addresses.RECORD_REL)
    for path in written:
        addresses.write_bytes(repo, path, final[path])
    for path in removed:
        os.remove(os.path.join(repo, *path.split("/")))
    d = os.path.join(repo, "content", old, slug)
    for dirpath, _dirs, _names in sorted(os.walk(d), key=lambda t: -len(t[0])):
        try:
            os.rmdir(dirpath)
        except OSError:
            pass
    print("moved content/%s/%s to content/%s/%s (%d file%s)"
          % (old, slug, target, slug, len(removed), "" if len(removed) == 1 else "s"), file=out)
    for line in report:
        print(line, file=out)
    stage = sorted(set(written) | set(removed))
    print("nothing is committed. Stage these paths with git add, then commit (add-work commits the move): %s"
          % " ".join(stage), file=out)
    return EXIT_OK


def _toplevel(repo):
    import subprocess
    try:
        p = subprocess.run(["git", "-C", repo, "rev-parse", "--show-toplevel"], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise MoveError("could not run git (%s); install git, then try again" % e.__class__.__name__)
    if p.returncode != 0:
        raise MoveError("%s is not inside a git repo; run this in the dev repo" % repo)
    return os.path.realpath(p.stdout.decode("utf-8", "replace").strip())


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
    except (MoveError, addresses.AddressError, build.BuildError, siteconfig.SiteConfigError, C.ContentError) as e:
        print("move refused: %s" % e)
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
