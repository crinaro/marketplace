#!/usr/bin/env python3
"""Turn a DECLARED resume variant into a document an employer can actually receive — GitHub
issue #64, `letter_out.py`'s twin.

⭐ WHY THIS EXISTS. The plugin already treats a resume variant as a document delivered to an
employer: `data/resume_variants.jsonl` declares the set, an opportunity names the one to send,
and an applications[] row records the one actually sent. But until this script, nothing turned
the declared markdown file into a document — a cover-letter renderer existed
(`letter_out.py`) and a resume renderer did not, so the variant stayed markdown while a real
`.docx`/Drive document was assembled by hand outside the engine, with no ATS-safe formatting
rules encoded anywhere and no check that the printed page even opens with a name/phone/email
header (the two concrete failures issue #64 reports).

⭐⭐ THE GATE RUNS BEFORE ANY TARGET — never read or store `visibility` here. This script asks
`resume_variants.report()` for the row and refuses to render at all when its `state` is one of
`resume_variants.FAIL_STATES` (`unplaced` and `private-on-public` included, ADR-027/public
#59): a public-surface variant printing a claim nobody reviewed for a public audience must
never become a document, docx or Drive alike. The gate owns `surface`/`visibility`
exclusively — this script only reads the row's already-derived `state`/`why`/`violations`.

⭐ THE SHIPPED DEFAULT RENDER CONFIG IS COMPLETE AND OPINIONATED (issue #64's own correction to
its point 11) — `DEFAULT_RENDER` below, never a set of fallbacks a fresh profile must first
assemble. `config.json`'s `writing.resume_output.render` OVERRIDES it per key, via a deep
merge; a key the profile does not set is never read as zero — see `_deep_merge`. Rendering with
no `render:` block at all is byte-equal to rendering with `render: {}` (both resolve to the
same merged dict) — the regression issue #64 itself asked for.

ATS-SAFE BY CONSTRUCTION, ENCODED RATHER THAN RE-DERIVED (issue #64's comments 1-12):
  - real `Heading1`/`Heading2` PARAGRAPH STYLES for section structure, never direct formatting
    a parser has to guess at;
  - a bullet is a literal glyph character on an ordinary paragraph — no `<w:numPr>` (no
    auto-numbered list), no table, no text box, one column;
  - widow/orphan control set on EVERY paragraph (off by default in hand-assembled XML — a
    generated document has no word-processor UI default to inherit it from);
  - keep-with-next chained across every paragraph of a short section (under
    `render.keep_with_next_max_paragraphs`) except its last, so a heading can never strand
    alone at a page foot with its own content pushed to the next page;
  - an explicit page break is authorable from the SOURCE, via `render.page_break_marker`
    (default `<!-- pagebreak -->`) on its own line — where a page falls is the author's
    editorial judgment, never a renderer heuristic;
  - a page-count line is always printed as an ESTIMATE (`~N pages (estimate)`), never asserted
    as fact — a naive character count is not a real pager.
  - ⭐ dev #480 / public #113 — the estimate above is computed from what was COMPOSED, so it
    cannot see what a parsing gap dropped before composition ever ran; it hid exactly the loss
    it exists to warn about once one existed. `content_loss_fraction()` is a second, independent
    measurement straight against the SOURCE file's own word count, printed loudly (and returned
    as exit code 3, not 0) whenever it crosses `CONTENT_LOSS_THRESHOLD` — so a future parsing
    gap is still caught even when this exact one is not the last.

⭐ THE HEADER IS REFUSED, NOT BLANKED, WHEN IDENTITY IS INCOMPLETE. A declared variant begins
at the job title; the union file's own header lives nowhere on it. This script builds the
header itself from `profile.user()["identity"]` (`full_name`, `phone`, `primary_email` — the
same three fields `cover_letter_header_template` already names) and REFUSES to render at all
when any of the three is empty, rather than shipping a resume with no phone number to an ATS
that expects one (issue #64's second concrete failure).

⭐ ONE FILE, NEVER A DELIVERY-NAMED COPY OF AN INTERNAL ONE (issue #64 point 10). The output
filename IS the artifact: `<name-slug>_resume_<variant-id>.docx`, both slugs built by
collapsing every run of non-alphanumeric characters to one underscore (issue #64 point 9's
"repeated separators" trap — a middle initial's period next to a space would otherwise double
up).

Usage:
    python3 variant_out.py --status
    python3 variant_out.py --set-mode local_docx
    python3 variant_out.py --render <variant-id> [--target docx|gdoc] [--out PATH] [--dry-run]

Python 3.9+. Standard library only.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _root import profile_root
import profile as prof
import resume_variants as rv
import _docx
# dev #545 — the rendered-resume directory is a LAYOUT fact, so it comes from the one table
# every script and the tree migration already share, never a bare string typed here.
import _tree
# jobsearch 0.93.0 (B8): moved to presence/ by split_module.py; every moved name stays importable
# from here, the facade the tests and callers use.
from presence.variant_blocks import (
    _norm,
    _BOLD_RE,
    _strip_markdown_emphasis,
    _strip_preamble,
    parse_variant_blocks,
)
from presence.variant_compose import (
    MODES,
    DEFAULT_MODE,
    DEFAULT_RENDER,
    _config_path,
    _load_config,
    _write_config,
    _deep_merge,
    output_settings,
    set_mode,
    status,
    _slug,
    identity_header,
    filename,
    _section_spans,
    _keep_next_flags,
    compose_paragraphs,
    page_estimate,
    CONTENT_LOSS_THRESHOLD,
    source_word_count,
    composed_word_count,
    content_loss_fraction,
)

# ---------------------------------------------------------------- identity / filename

def _identity_header():
    """`identity_header` on this profile's `user.json` (see presence/variant_compose.py)."""
    return identity_header(prof.user())


def _filename(variant_id):
    """`filename` on this profile's `user.json` (see presence/variant_compose.py)."""
    return filename(variant_id, prof.user())


# ---------------------------------------------------------------- render

def render(variant_id, target=None, out_path=None, dry_run=False):
    root = profile_root()
    rep = rv.report(root)
    row = next((r for r in rep["variants"] if str(r.get("id")) == str(variant_id)), None)
    if row is None:
        known = ", ".join(str(r.get("id")) for r in rep["variants"]) or "(none declared)"
        print("No declared variant %r. Known: %s" % (variant_id, known), file=sys.stderr)
        return 1

    # ⭐ THE GATE — before any target, and before anything else about this render. Never a
    # second opinion about visibility here: `row["state"]` IS resume_variants.py's verdict.
    if row["state"] in rv.FAIL_STATES:
        print("⛔ %s [%s]: %s" % (variant_id, row["state"], row["why"]), file=sys.stderr)
        for v in row.get("violations") or []:
            print("   ✗ %s" % v[:200], file=sys.stderr)
        print("Refusing to render — fix the variant first (resume_variants.py --check).",
              file=sys.stderr)
        return 1

    header, missing = _identity_header()
    if missing:
        print("⛔ identity is missing %s (user.json) — refusing to render a header-less "
              "resume. An ATS parser looks for name/phone/email FIRST; a rendered page "
              "with none of them is worse than no page at all (issue #64)." % ", ".join(missing),
              file=sys.stderr)
        return 1

    variant_file = row.get("file")
    path = os.path.join(root, variant_file)
    try:
        with open(path, encoding="utf-8") as fh:
            vtext = fh.read()
    except OSError:
        print("⛔ %r does not exist — resume_variants.py reported %r as %r; re-run it before "
              "rendering." % (variant_file, variant_id, row["state"]), file=sys.stderr)
        return 1

    s = output_settings()
    mode = {"docx": "local_docx", "gdoc": "drive"}.get(target) if target else None
    mode = mode or s["mode"]
    render_cfg = s["render"]

    blocks = parse_variant_blocks(vtext, render_cfg["page_break_marker"],
                                  render_cfg.get("preamble_marker"))
    paragraphs = compose_paragraphs(header, blocks, render_cfg)
    pages = page_estimate(paragraphs, render_cfg["chars_per_page_estimate"])
    loss = content_loss_fraction(vtext, paragraphs, header, render_cfg)

    print("Variant : %s (%s)" % (variant_id, row.get("archetype")))
    print("Surface : %s (%s)" % (row.get("surface"), row.get("visibility")))
    print("Sections: %d heading(s), %d bullet(s), %d paragraph(s)"
          % (sum(1 for b in blocks if b["type"] == "heading"),
             sum(1 for b in blocks if b["type"] == "bullet"),
             sum(1 for b in blocks if b["type"] == "paragraph")))
    print("Length  : ~%d pages (estimate)" % pages)
    # dev #480 / public #113 — the estimate above is computed from what was KEPT, so it cannot
    # by itself show what was dropped. This is the independent, second measurement: LOUD by
    # construction, never folded quietly into the estimate line above.
    if loss > CONTENT_LOSS_THRESHOLD:
        print()
        print("🛑 CONTENT LOSS DETECTED: this render keeps only about %d%% of %s's own word "
              "count. Something did not make it into the composed document — open BOTH files "
              "and compare before sending; do not trust the page estimate above alone."
              % (round(100 * (1 - loss)), variant_file))
    print()

    if dry_run:
        print("DRY RUN — nothing written. Composed outline:")
        for line in header:
            print("  [header] %s" % line)
        for b in blocks:
            brk = " (page break before)" if b["page_break"] else ""
            if b["type"] == "heading":
                print("  %s%s %s%s" % ("#" * b["level"], "", b["text"], brk))
            elif b["type"] == "bullet":
                print("  %s- %s%s" % ("  " * (1 if b["indent"] >= 2 else 0), b["text"], brk))
            else:
                print("  %s%s" % (b["text"], brk))
        return 3 if loss > CONTENT_LOSS_THRESHOLD else 0

    if mode == "drive":
        print("Mode is `drive` — this script does NOT create the document.")
        print("The connector is CREATE-ONLY, so push exactly once, when the text is final:")
        print()
        print("   parentId: %s" % (s["drive_folder_id"] or "!! NOT CONFIGURED !!"))
        print()
        print("Then READ THE DOCUMENT BACK to verify it before attaching it anywhere.")
        return 1 if not s["drive_folder_id"] else 0

    # dev #545 — resolve_rel() honours the layout's legacy fallback, so a profile the tree
    # migration has not reached yet keeps writing beside the resumes it already rendered at
    # the old root location instead of silently splitting them across two directories. A
    # local_dir the layout does not know (a profile's own override) is joined verbatim.
    out = out_path or os.path.join(_tree.resolve_rel(root, s["local_dir"]),
                                   _filename(variant_id))
    heading_styles = [
        ("Heading1", "heading 1", render_cfg["heading1_size_half_pt"], render_cfg["heading_color"]),
        ("Heading2", "heading 2", render_cfg["heading2_size_half_pt"], render_cfg["heading_color"]),
    ]
    _docx.write_docx_paragraphs(out, paragraphs, font=render_cfg["font"],
                               margin_twips=render_cfg["margin_twips"],
                               heading_styles=heading_styles)
    print("Wrote %s (%d bytes)" % (out, os.path.getsize(out)))
    print()
    print("⭐ OPEN IT AND CHECK THE PAGE COUNT before sending — the estimate above is exactly")
    print("   that, an estimate. Confirm with the candidate that THIS file is what gets attached.")
    # dev #480 / public #113 — the file above is written either way (it is still the best
    # artifact available for the candidate to go inspect), but a caller or script checking the
    # exit code must be able to tell "wrote a complete document" from "wrote a lossy one" —
    # returning 0 either way is exactly the silent-success shape this issue is about.
    return 3 if loss > CONTENT_LOSS_THRESHOLD else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--set-mode", metavar="MODE", choices=MODES)
    ap.add_argument("--render", metavar="VARIANT_ID")
    ap.add_argument("--target", choices=("docx", "gdoc"),
                    help="override the configured mode for this render only")
    ap.add_argument("--out", metavar="PATH")
    ap.add_argument("--dry-run", action="store_true",
                    help="compose and print the outline; write nothing")
    a = ap.parse_args()
    if a.set_mode:
        return set_mode(a.set_mode)
    if a.render and not (a.out or a.dry_run) and \
            (a.target or {"local_docx": "docx"}.get(output_settings()["mode"])) == "docx":
        # jobsearch 0.93.0 (design-resume-docx.md §3.4): the managed Word file has ONE writer; render() is unchanged
        print("⛔ REFUSED — %s's Word file is kept in your layout by `record.py presence-docx %s`; this would overwrite "
              "it. Write a copy with --out <path>, or preview with --dry-run." % (a.render, a.render), file=sys.stderr)
        return 1
    if a.render:
        return render(a.render, target=a.target, out_path=a.out, dry_run=a.dry_run)
    return status()


if __name__ == "__main__":
    sys.exit(main())
