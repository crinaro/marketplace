#!/usr/bin/env python3
"""siteconfig.py -- the strict parser, and the ONLY writer, of `site/site.json` (schemas 1 to 4).

dev #835, design section 3.2 and named change S10. Python 3.9, standard library only.

WHAT THIS FILE IS FOR
---------------------
`site.json` is a stored data shape (CLAUDE.md principle 4): a named field, a strict parser that
refuses what it cannot read, and a loud failure on an unknown key or a wrong type. Nothing in
the plugin reads `site.json` any other way, and nothing writes it any other way.

* `parse_text` / `load` read. An unknown key, a wrong type, a duplicate key, a bad value: each
  refuses with a `SiteConfigError` naming the field.
* A file whose `schema` is NEWER than this plugin reads gets ONE distinct refusal and never an
  unknown-key error (an older install reading a newer file must say "update", not "bad key"):
  `site.json schema N is newer than this plugin understands (it reads up to M); update site-studio`.
* `write` is the only writer. It always writes the one canonical form (S10): every known key, in
  schema order, two-space indent, UTF-8, one trailing LF. That form carries the marker line
  `  "engine": "site-studio",` exactly, which is what the SessionStart prefilter greps for.
  `marker_status` / `is_canonical_marker` report whether a file's marker is in that form, and
  `marker_state` says which way it is wrong, so `doctor.py` can say "re-save site.json" for a marker
  that is there but respelled rather than silently not starting, and "this is a site site-studio does
  not manage yet; type /site-studio:adopt" for a site.json with no marker at all (dev #855). A re-save
  cannot help a file site-studio never made.

SCHEMA VERSIONING. The key is `site.json`'s own `schema`, never the plugin release. Schema 1 is the
only schema in 0.1.0. 0.2.0 adds schema 2 (design-site-adoption section 3, dev #857) WITHOUT a
migration, by one rule: the writer writes the LOWEST schema that holds the site, and "the site" is
`site.json` AND the tree the builder reads.

* Schema 1 is read exactly as 0.1.0 reads it. `siteKind` defaults to `portfolio`, there are no
  labels, and `featuredFrom` is `"home"`.
* Schema 2 accepts everything schema 1 does, plus exactly three keys: `siteKind` (top level),
  `featuredFrom` (top level) and `labels` (inside a portfolio-settings object). A schema-1 file
  carrying any of them is refused (`'siteKind' needs "schema": 2`), so a hand edit cannot quietly
  make a file that 0.1.0 then misreads. Schema 3 or above gets the "update site-studio" refusal.
* `required_schema(cfg, files)` is the one place that says which schema a site needs; it returns 2
  when any of five conditions holds (a non-portfolio kind, a non-empty labels map, `featuredFrom`
  `"flags"`, a section or `{{featured}}` in a layout, page or Markdown body, or a hand-made home
  page with no `content/home.md`). `canonical_text` / `write` take the files the caller holds and
  emit that schema and only that schema's keys, so a portfolio with no 0.2.0 feature stays
  schema 1 and stays readable by a 0.1.0 install. `check_tree_schema` is the build's refusal of a
  schema-1 file over a tree that needs 2. git's `repositoryformatversion` is the model.

SCHEMA 3 (site-fidelity, 0.3.0; design-site-fidelity section 3). No migration, by the same rule, and
the owner invariant behind it: site-studio never changes how a published site looks or works. A
schema-3 reason is one of two kinds. K: a key or form 0.2.0 REFUSED, so no tree 0.2.0 accepted can hold
one (the resume with no PDF and no `paper`; a `page.md` carrying `order`, `tagline`, `sort`, `menuLinks`
or `view`; a `{{home:` token in `site/src`; `content/home/index.md` or `content/about/index.md`; a
`contact` key on the resume page). A K reason below schema 3 is refused by `check_tree_schema`. I: a new
interpretation of text 0.2.0 ACCEPTED (a block fence line, a titled image line, a `.wNNN` size copy).
An I reason below schema 3 is NEVER refused: the build keeps 0.2.0's reading of it byte for byte, so a tree
0.2.0 accepted builds identically under 0.3.0. `build.py raise-schema` is the one way a site gets to
schema 3, and it lists every output difference first. `required_schema(cfg, files, interpretations=...)`
takes the I-1 and I-2 reasons from its caller (`content.interpretation_reasons`), because `siteconfig`
cannot import `content`; it refuses to run with `files` and no `interpretations`, so no caller can forget
the scan.

SCHEMA 4 (template-fidelity, 0.4.0; design-template-fidelity section 3). No migration, by the same rule, and
the same owner invariant. Schema 4 has K reasons ONLY (design section 3.1 rule 2): every 0.4.0 construct is a
key, value, token or form that 0.3.x REFUSES, so no tree 0.3.x accepted can hold one and raising a tree from 3
to 4 changes no output. `schema_4_reasons(cfg, files)` lists them: the site.json keys `nav`, `look` and `blocks`,
`resume.headings` and `resume.layout`, the portfolio keys `cardNumber`, `cardNumberFormat`, `cardLabels` and
`backLink` (site.json `work` and a `page.md`), `blocks.headingLevel`, `blocks.loneReferenceGrid`, `blocks.videoEmbed`, a `page.md` `mapMask` and `onePieceIndex` and a
`view` of `roles`, `map` or `showcase`, the home keys
`eyebrow`, `role`, `showcase`, `samples`, `links`, `titleForm`, `introScope` and `partOrder`, the resume keys `tagline` and `links`, the reference keys
`image`, `role`, `fetched` and `author`, the token `{{navLinks}}`, and, in a tree read as schema 3 or above, a
`:::quotes` block and a `:::part` holding more than one block (`multi_block_part_lines`). A key written with its DEFAULT value in site.json is accepted at 4 and normalised away, so it
is no reason (the `featuredFrom: "home"` rule; `blocks.headingLevel` has no default VALUE, absent is its default,
so every number is a setting and a reason; `blocks.loneReferenceGrid: false` and `blocks.videoEmbed: "facade"` are their defaults and are normalised away); the same key in a `page.md` is the person's file text and is a
reason by presence. THE GUARD REASON (rule 8): a committed `.site-studio/addresses.json` is a schema-4 reason
that changes no output; it exists so that every 0.3.x install refuses the tree with `newer_schema_message`
instead of publishing it without the address guard. PART-NAME PRECEDENCE (rule 7): the home parts `eyebrow`,
`role`, `showcase`, `samples` and `links` are fixed ONLY at schema 4 and above (`fixed_part_names`). Below 4 a
custom `:::part showcase` is accepted and renders as in 0.3.x; at 4 it is refused naming both, and
`part_collision_problems` is the one function that says so, for the build, `raise-schema --to 4` and the
address commands. `required_schema` returns 4 when any schema-4 reason holds. `files` must carry
`.site-studio/addresses.json` when the tree has one (the build's tree listing reads only `site` and `content`).
"""
import sys

from configschema.canonical import marker_status
from configschema.diagnostics import SiteConfigError
from configschema.model import load


def main(argv):
    if len(argv) == 3 and argv[1] == "check":
        try:
            cfg = load(argv[2])
        except SiteConfigError as e:
            print(str(e))
            return 1
        with open(argv[2], encoding="utf-8") as fh:
            ok, reason = marker_status(fh.read())
        print("site.json ok (schema %d); marker: %s" % (cfg.schema, reason))
        return 0 if ok else 1
    print("usage: siteconfig.py check <site.json>")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
