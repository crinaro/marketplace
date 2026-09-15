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
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _root import profile_root
import profile as prof
import resume_variants as rv
import _docx

MODES = ("drive", "local_docx")
# ⭐ Unlike letter_out.py, whose `drive` default is historical ("it was the original behavior.
# It is not the better mode" — commands/letters.md), this renderer has no prior behavior to
# inherit. local_docx needs no Google account, no connector, no network — the deliberate
# default for a brand-new capability.
DEFAULT_MODE = "local_docx"

# The shipped, opinionated default — see the module docstring. Every key is individually
# overridable from `config.json.writing.resume_output.render.*` via `_deep_merge`; a profile
# that sets none of them gets exactly this.
DEFAULT_RENDER = {
    "font": "Times New Roman",
    "margin_twips": 1080,
    "heading_color": "595959",       # mid-gray — structural labels, never the evidence text
    "body_color": "000000",          # black — proper nouns, achievement bullets
    "heading1_size_half_pt": 28,     # 14pt
    "heading2_size_half_pt": 24,     # 12pt
    "body_size_half_pt": 22,         # 11pt — letter_out's own long-standing default
    "bullet_glyph": "•",
    "bullet_indent_twips": 360,
    "keep_with_next_max_paragraphs": 5,
    "page_break_marker": "<!-- pagebreak -->",
    "chars_per_page_estimate": 3200,
    # An ascending scale, one gap per RELATIONSHIP TYPE, held constant regardless of what
    # follows (issue #64 point 4): tightest between a heading and an immediately-nested
    # sub-heading, then between list items, then a heading and its own content, then largest
    # between top-level entries (the last paragraph of one section and the next heading).
    "gaps": {
        "sub_label": 40,
        "list_item": 80,
        "label_to_content": 160,
        "top_level": 280,
    },
}


# ---------------------------------------------------------------- config

def _config_path():
    return os.path.join(profile_root(), "config.json")


def _load_config():
    with open(_config_path(), encoding="utf-8") as fh:
        return json.load(fh)


def _write_config(cfg):
    p = _config_path()
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, p)          # atomic — a partial write would destroy the whole config


def _deep_merge(default, override):
    """`default` with `override` applied per key, recursively for nested dicts. A missing key
    in `override` is never read as zero — it simply keeps `default`'s own value. Never mutates
    either argument."""
    if not isinstance(override, dict) or not override:
        return dict(default)
    out = dict(default)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def output_settings():
    """The resume-output block, with the shipped default applied. Never invents a folder id."""
    cfg = _load_config()
    w = cfg.get("writing", {})
    block = w.get("resume_output") or {}
    out = dict(block)
    out.setdefault("mode", DEFAULT_MODE)
    out.setdefault("local_dir", "resumes")
    drive = cfg.get("drive", {}) or {}
    out["drive_folder_id"] = drive.get("job_search_folder_id")
    out["drive_folder_name"] = drive.get("job_search_folder_name")
    out["render"] = _deep_merge(DEFAULT_RENDER, block.get("render") or {})
    return out


def set_mode(mode):
    if mode not in MODES:
        print("Unknown mode %r. Choose one of: %s" % (mode, ", ".join(MODES)))
        return 2
    cfg = _load_config()
    w = cfg.setdefault("writing", {})
    block = w.setdefault("resume_output", {})
    block["mode"] = mode
    block.setdefault("local_dir", "resumes")
    block["_why"] = ("drive = push to the job-search Drive folder (needs a Google account and "
                     "the documents connector). local_docx = write a .docx next to the profile, "
                     "no Google account required — the default here.")
    _write_config(cfg)
    print("Resume output mode set to %r." % mode)
    return status()


def status():
    s = output_settings()
    print("RESUME-VARIANT OUTPUT")
    print("=" * 74)
    print("  Mode        : %s" % s["mode"])
    if s["mode"] == "drive":
        if s["drive_folder_id"]:
            print("  Drive folder: %s (%s)" % (s["drive_folder_name"], s["drive_folder_id"]))
            print()
            print("  ⭐ Pass that id as `parentId` when creating the document. The connector")
            print("     CANNOT MOVE A FILE, so a document created without a parent lands in My")
            print("     Drive root and the only fix is a second copy for you to delete.")
        else:
            print("  Drive folder: NOT CONFIGURED")
            print()
            print("  ⚠️ Mode is `drive` but config.json has no drive.job_search_folder_id, so a")
            print("     document would land in My Drive root and could not be moved.")
            print("     Set the folder id, or switch to a local file:")
            print("       ~/.claude/jobsearch/run variant_out.py --set-mode local_docx")
    else:
        print("  Writes to  : %s/" % os.path.join(profile_root(), s["local_dir"]))
        print("  No Google account, connector or network needed.")
    print()
    print("  Switch:  ~/.claude/jobsearch/run variant_out.py --set-mode %s"
          % ("local_docx" if s["mode"] == "drive" else "drive"))
    return 0


# ---------------------------------------------------------------- identity / filename

def _identity_header():
    """([name_line, contact_line], []) or (None, [missing field names]) — never a partial
    header. `full_name`/`phone`/`primary_email` are the same three `cover_letter_header_
    template` already names; a resume renderer refuses outright rather than ship a header
    missing the field an ATS parser looks for first (issue #64)."""
    ident = (prof.user() or {}).get("identity", {}) or {}
    name = (ident.get("full_name") or "").strip()
    phone = (ident.get("phone") or "").strip()
    email = (ident.get("primary_email") or "").strip()
    missing = [label for label, v in (("full_name", name), ("phone", phone),
                                      ("primary_email", email)) if not v]
    if missing:
        return None, missing
    return [name, "%s • %s" % (phone, email)], []


def _slug(s):
    return re.sub(r"[^A-Za-z0-9]+", "_", s or "").strip("_").lower()


def _filename(variant_id):
    ident = (prof.user() or {}).get("identity", {}) or {}
    name_slug = _slug(ident.get("full_name")) or "candidate"
    return "%s_resume_%s.docx" % (name_slug, _slug(str(variant_id)) or "variant")


# ---------------------------------------------------------------- composition

def _norm(s):
    return " ".join((s or "").split())


def parse_variant_blocks(text, page_break_marker):
    """[{'type': 'heading', 'level': int, 'text': str, 'page_break': bool} |
        {'type': 'bullet', 'indent': int, 'text': str, 'page_break': bool}], in file order.

    Deliberately headings and bullets ONLY (design C.3) — a variant's summary paragraphs are
    per-variant positioning, not a declared claim, and are not composed here; they stay in the
    authored file for a human reader, same as `resume_variants.py` never gates them."""
    blocks = []
    pending_break = False
    for line in (text or "").splitlines():
        if page_break_marker and line.strip() == page_break_marker:
            pending_break = True
            continue
        hm = rv.HEADING_RE.match(line)
        if hm:
            blocks.append({"type": "heading", "level": len(hm.group(1)),
                           "text": hm.group(2).strip(), "page_break": pending_break})
            pending_break = False
            continue
        bm = rv.BULLET_INDENT_RE.match(line)
        if bm:
            blocks.append({"type": "bullet", "indent": len(bm.group(1)),
                           "text": _norm(bm.group(2)), "page_break": pending_break})
            pending_break = False
    return blocks


def _section_spans(blocks):
    """[(start, end)) — one span per heading, running through every block up to (not
    including) the next heading, or the end of the list."""
    spans = []
    start = None
    for i, b in enumerate(blocks):
        if b["type"] == "heading":
            if start is not None:
                spans.append((start, i))
            start = i
    if start is not None:
        spans.append((start, len(blocks)))
    return spans


def _keep_next_flags(blocks, max_paragraphs):
    """{index: True} for every block that must chain keep-with-next to the block right after
    it — every paragraph of a section under `max_paragraphs` long EXCEPT ITS LAST (issue #64
    point 2: keep-next only binds to the immediate next paragraph, so a short section needs
    the whole chain or a heading can still strand from its own content). The companion case —
    a heading immediately followed by a nested sub-heading — is handled separately in
    `compose_paragraphs`, since a new section starts at EVERY heading here regardless of
    level, which would otherwise miss that exact pair."""
    flags = {}
    for start, end in _section_spans(blocks):
        if (end - start) < max_paragraphs:
            for i in range(start, end - 1):
                flags[i] = True
    return flags


def compose_paragraphs(header_lines, blocks, render_cfg):
    """The full paragraph list this variant renders to, in the shared `_docx.py` model."""
    gaps = render_cfg["gaps"]
    keep_next = _keep_next_flags(blocks, render_cfg["keep_with_next_max_paragraphs"])
    paras = []

    for i, line in enumerate(header_lines):
        paras.append({"text": line, "bold": (i == 0),
                     "size_half_pt": 24 if i == 0 else 20,
                     "space_after": 40, "align": "center", "widow": True})
    paras.append({"text": "", "space_after": 200, "widow": True})

    n = len(blocks)
    for i, b in enumerate(blocks):
        is_last_in_section = (i + 1 == n) or blocks[i + 1]["type"] == "heading"
        if b["type"] == "heading":
            next_is_heading = (i + 1 < n) and blocks[i + 1]["type"] == "heading"
            space_after = (gaps["sub_label"] if next_is_heading
                          else gaps["label_to_content"] if (i + 1 < n)
                          else gaps["top_level"])
            style = "Heading1" if b["level"] <= 1 else "Heading2"
            size = (render_cfg["heading1_size_half_pt"] if b["level"] <= 1
                   else render_cfg["heading2_size_half_pt"])
            # A heading immediately followed by a nested sub-heading (no bullet of its own
            # yet) must never strand from it — that sub-heading is the only "content" this
            # heading has. Forced regardless of the short-section chain above, which is
            # computed per heading-started span and would otherwise miss exactly this pair.
            paras.append({"text": b["text"], "style": style, "bold": True,
                         "size_half_pt": size, "color": render_cfg["heading_color"],
                         "space_after": space_after, "widow": True,
                         "keep_next": keep_next.get(i, False) or next_is_heading,
                         "page_break_before": b["page_break"]})
        else:
            space_after = gaps["top_level"] if is_last_in_section else gaps["list_item"]
            depth = 1 if b["indent"] >= 2 else 0
            left = render_cfg["bullet_indent_twips"] * (depth + 1)
            hanging = render_cfg["bullet_indent_twips"]
            text = "%s %s" % (render_cfg["bullet_glyph"], b["text"])
            paras.append({"text": text, "size_half_pt": render_cfg["body_size_half_pt"],
                         "color": render_cfg["body_color"], "space_after": space_after,
                         "indent": (left, hanging), "widow": True,
                         "keep_next": keep_next.get(i, False),
                         "page_break_before": b["page_break"]})
    return paras


def page_estimate(paragraphs, chars_per_page):
    total = sum(len(p.get("text") or "") for p in paragraphs)
    return max(1, -(-total // max(1, chars_per_page)))     # ceil division, stdlib-only


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

    blocks = parse_variant_blocks(vtext, render_cfg["page_break_marker"])
    paragraphs = compose_paragraphs(header, blocks, render_cfg)
    pages = page_estimate(paragraphs, render_cfg["chars_per_page_estimate"])

    print("Variant : %s (%s)" % (variant_id, row.get("archetype")))
    print("Surface : %s (%s)" % (row.get("surface"), row.get("visibility")))
    print("Sections: %d heading(s), %d bullet(s)"
          % (sum(1 for b in blocks if b["type"] == "heading"),
             sum(1 for b in blocks if b["type"] == "bullet")))
    print("Length  : ~%d pages (estimate)" % pages)
    print()

    if dry_run:
        print("DRY RUN — nothing written. Composed outline:")
        for line in header:
            print("  [header] %s" % line)
        for b in blocks:
            brk = " (page break before)" if b["page_break"] else ""
            if b["type"] == "heading":
                print("  %s%s %s%s" % ("#" * b["level"], "", b["text"], brk))
            else:
                print("  %s- %s%s" % ("  " * (1 if b["indent"] >= 2 else 0), b["text"], brk))
        return 0

    if mode == "drive":
        print("Mode is `drive` — this script does NOT create the document.")
        print("The connector is CREATE-ONLY, so push exactly once, when the text is final:")
        print()
        print("   parentId: %s" % (s["drive_folder_id"] or "!! NOT CONFIGURED !!"))
        print()
        print("Then READ THE DOCUMENT BACK to verify it before attaching it anywhere.")
        return 1 if not s["drive_folder_id"] else 0

    out = out_path or os.path.join(root, s["local_dir"], _filename(variant_id))
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
    return 0


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
    if a.render:
        return render(a.render, target=a.target, out_path=a.out, dry_run=a.dry_run)
    return status()


if __name__ == "__main__":
    sys.exit(main())
