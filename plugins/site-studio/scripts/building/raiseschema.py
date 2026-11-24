"""raiseschema: the `raise-schema` verb of `build.py`: the report of every output difference raising a site's schema
would make, and the one command that raises it."""

import argparse
from contentmodel import frontmatter, grammar
import os
from building.constants import ACCEPT_YEAR
from building.gitfiles import _disk_files
from building.lookneeds import look_needs
from building.outcomes import BuildError
from building.raising import RaiseReport, _first_difference, _keep_text
from configschema import (
    canonical as canonical_mod,
    diagnostics,
    model as model_mod,
    configkeys,
    partblocks,
)
from configschema.diagnostics import SiteConfigError
from contentmodel.errors import ContentError
from building.running import _accept


def raise_report(files, to=3, edited=None):
    """The raise to schema `to`, as a report (design-site-fidelity section 3.4): the site is built twice in
    memory with `accept`, both times with `site.json` declaring schema `to` (so a key 0.2.0 refused is
    admitted), once with the CURRENT grammar and recognitions and once with schema `to`'s. `edited` is the
    tree the second build reads when `--keep-text` has escaped some lines; the first build always reads
    `files`. Writes nothing."""
    raw = files.get("site/site.json")
    if raw is None:
        return RaiseReport([], [], [diagnostics.make_problem("site/site.json is not in the build input",
                                                            "site/site.json", "missing", "a site.json",
                                                            "commit site/site.json, or run /site-studio:setup in "
                                                            "the dev repo")], None)
    cfg = model_mod.parse_text(frontmatter.decode_text(raw, "site/site.json"))
    cur = cfg.schema

    def raised(tree):
        tree = dict(tree)
        interps = grammar.interpretation_reasons(tree)
        text = canonical_mod.canonical_text(cfg, tree, interps, at_least=to, look_needs=look_needs(tree))
        tree["site/site.json"] = text.encode("utf-8")
        return tree, text
    old_tree, _t = raised(files)
    new_tree, site_json = raised(edited if edited is not None else files)
    a = _accept(old_tree, False, ACCEPT_YEAR, lambda _s: None, grammar=cur)
    b = _accept(new_tree, False, ACCEPT_YEAR, lambda _s: None, grammar=to)
    seen = set((p.path, p.message) for p in a.problems)
    problems = [p for p in b.problems if (p.path, p.message) not in seen]
    diffs = []
    for path in sorted(set(a.output) | set(b.output)):
        x, y = a.output.get(path), b.output.get(path)
        if x != y:
            info = b.pages.get(path) or a.pages.get(path) or {}
            diffs.append((path, info.get("source"),
                          "only after the raise" if x is None else "gone after the raise" if y is None
                          else _first_difference(x, y)))
    return RaiseReport(diffs, problems, list(a.problems), site_json)


def raise_schema_main(argv):
    """`build.py raise-schema --repo DIR [--to 3|4|5|6|7|8] [--keep-text PATH:LINE ...] [--confirm]`: move a site to schema 3
    (the default), 4, 5 or 6. Lists every output difference first and refuses until each is confirmed or kept as text; a
    problem the new schema raises is never confirmable (at 4 that includes a custom `:::part` whose name the schema
    now fixes: the refusal names both, and nothing is written). Reads and writes the working tree; the person commits.
    A raise to 4 changes no page when the tree holds no schema-3 reading (design 3.1 rule 2: every schema-4 name is
    a key or token 0.3.x refused), and says "no page changes"; so does a raise from 4 to 5 (design-movement-view 3.1
    rule 1: every schema-5 name is one 0.4.x refused), and from 5 to 6 (design-adopt-parity-2 3.1 rule 1: every schema-6
    name is one 0.5.x refused)."""
    ap = argparse.ArgumentParser(prog="build.py raise-schema", allow_abbrev=False)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--keep-text", action="append", default=[], metavar="PATH:LINE")
    ap.add_argument("--to", type=int, choices=(3, 4, 5, 6, 7, 8), default=3, help="the schema to raise to (default 3)")
    ap.add_argument("--confirm", action="store_true", help="accept the listed differences and write the new schema")
    args = ap.parse_args(argv)
    repo = os.path.abspath(args.repo)
    try:
        files = _disk_files(repo)
        raw = files.get("site/site.json")
        if raw is None:
            raise BuildError("site/site.json is not in the working tree", fix="run this inside the dev repo")
        cfg = model_mod.parse_text(frontmatter.decode_text(raw, "site/site.json"))
        if cfg.schema >= args.to:
            print("site.json is already schema %d; nothing to raise" % cfg.schema)
            return 0
        edited = _keep_text(files, args.keep_text) if args.keep_text else None
        clash = partblocks.part_collision_problems(files) if args.to >= 4 else []
        if clash:          # design 3.1 rule 7: a custom part with a name schema 4 fixes is named, both names, before anything is written
            print("raise-schema refused: schema 4 fixes the home part names %s, and this site has %d custom part(s) "
                  "that use one. Rename each, then raise again:" % (", ".join(configkeys.V4_PART_FIXED), len(clash)))
            for p in clash:
                print("  - %s" % p.line())
            return 1
        rep = raise_report(files, args.to, edited)
    except (BuildError, SiteConfigError, ContentError) as e:
        print("raise-schema refused: %s" % e)
        return 1
    if rep.base_problems:
        print("raise-schema refused: this site does not build today, so there is nothing to compare. "
              "Fix these first:")
        for p in rep.base_problems:
            print("  - %s" % p.line())
        return 1
    for p in rep.problems:
        print("you decide: %s" % p.line())
    for path, source, detail in rep.differences:
        print("would change: %s%s (%s)" % (path, " from %s" % source if source else "", detail))
    kept = [s for s in args.keep_text if any(src and s.rpartition(":")[0] == src for _p, src, _d in rep.differences)]
    if kept:
        print("raise-schema refused: %s is still read differently at schema %d, so keeping it as text did not "
              "keep the page as it is" % (", ".join(kept), args.to))
        return 1
    if rep.problems:
        print("raise-schema refused: %d problem(s) schema %d raises; none can be confirmed, each needs its own "
              "fix first" % (len(rep.problems), args.to))
        return 1
    if rep.differences and not args.confirm:
        print("raise-schema refused: %d page(s) would change. Keep a line as text with --keep-text PATH:LINE, "
              "or accept every change listed with --confirm" % len(rep.differences))
        return 1
    tree = edited if edited is not None else files
    for path in sorted(args.keep_text and set(s.rpartition(":")[0] for s in args.keep_text) or ()):
        with open(os.path.join(repo, *path.split("/")), "wb") as fh:
            fh.write(tree[path])
    with open(os.path.join(repo, "site", "site.json"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(rep.site_json)
    print("raised to schema %d: %s" % (args.to, "no page changes" if not rep.differences else
                                        "%d page change(s) confirmed" % len(rep.differences)))
    return 0
