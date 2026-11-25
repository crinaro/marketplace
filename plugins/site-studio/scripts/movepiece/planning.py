"""planning.py -- `plan`: the whole move computed ENTIRELY IN MEMORY through `build.accept` (the site as it is, the
site with the folder moved and no redirects, and the finished tree), and every refusal (`MoveError`) that
stops it before a byte is written. It writes nothing (design-template-fidelity section 8 A1, issue #877).
"""

import addresses
import re
from building import constants, running, tokens
from building.lookneeds import look_needs
from configschema import canonical, model, frontmatter
from contentmodel import grammar, keytables
from movepiece.rewrite import _decode, is_reference_json, nfc, rewrite_front_names, rewrite_links, rewrite_project


REASON = "moved with %s"
_HOME_FILES = ("content/home.md", "content/home/index.md")


class MoveError(ValueError):
    """A refusal. The message is the line the person reads and names what to do."""


def _site_json(cfg, redirects, files, record_text, at_least):
    """The site.json text for `cfg` with `redirects`, written by siteconfig at the schema the tree needs (never
    below `at_least`)."""
    d = cfg.to_dict()
    d["redirects"] = dict(redirects)
    new = model.parse_data(d)
    tree = dict(files)
    if record_text is not None:
        tree[addresses.RECORD_REL] = record_text.encode("utf-8")
    return canonical.canonical_text(new, tree, grammar.interpretation_reasons(tree), at_least=at_least,
                                    look_needs=look_needs(tree))


def _redirect_out(old):
    """The output path `build.build_redirect` writes for a redirects key."""
    clean = old.strip("/")
    return clean if clean.lower().endswith(constants.HTML_EXTS) else clean + "/index.html"


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
    acc = running.accept(dict((k, v) for k, v in tree.items() if k.startswith(("site/", "content/"))))
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
    cfg = model.parse_text(raw.decode("utf-8", "replace"))
    if cfg.siteKind != "portfolio":
        raise MoveError("this is a %s site, which has no portfolios and no pieces to move; run move.py in a portfolio "
                        "site" % cfg.siteKind)
    addresses.check_prewrite(cfg, files)
    old_key, new_key = "%s/%s" % (old, slug), "%s/%s" % (target, slug)
    old_dir, new_dir = "content/%s/" % old_key, "content/%s/" % new_key
    if old == target:
        raise MoveError("%s is already in %s; name a different portfolio" % (old_key, target))
    if target in keytables.RESERVED_PORTFOLIO_NAMES:
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
        if is_reference_json(path):         # schema 9: a reference's `project` names the piece by its folder, so it follows the move
            raw = _decode(moved_files[path])
            new_text, n = rewrite_project(raw, old_key, new_key) if raw is not None else (None, 0)
            if n:
                moved_files[path] = new_text.encode("utf-8")
                rewrote.append((path, n))
            continue
        text = _decode(moved_files[path]) if frontmatter._expanded_file(path) else None
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
        key = tokens._page_dir(path)
        if counterpart in mid.output and key and key != tokens._page_dir(counterpart):
            redirects[key] = tokens._page_dir(counterpart)
            report.append("redirect %s -> %s" % (key, tokens._page_dir(counterpart)))
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
    report.append("site/site.json: written at schema %d" % model.parse_text(
        final["site/site.json"].decode("utf-8")).schema)
    removed = sorted(p for p in files if p.startswith(old_dir))
    return final, removed, report
