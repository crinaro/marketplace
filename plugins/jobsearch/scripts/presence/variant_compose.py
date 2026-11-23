"""variant_compose: the settings, the header, the filename and the paragraph composition of a
rendered resume variant (jobsearch 0.93.0, B8 of docs/design-resume-docx.md).

Moved out of `variant_out.py`, an entry point, so a package module (the `presence-docx` verb, the
outbox's attachment seam) can reach them without importing an entry point. `variant_out.py`
keeps every name importable as a facade; its module docstring still explains the ATS-safe
rules these functions encode. The header and the filename take the `user.json` dict as an
argument: `profile.py`, which reads it, is an entry point, so the caller passes `prof.user()`.

Python 3.9+. Standard library only.
"""

import _tree
import json
import os
import re
from _root import profile_root
from presence.variant_blocks import _strip_preamble


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
    # dev #480 / public #113 — a variant file's own internal notes (drafting context, not
    # send-ready text) sit above this literal line; everything at or above it is excluded from
    # composition entirely, the same exact-line-match mechanism `page_break_marker` already
    # uses. A file with no such line renders exactly as before (nothing to strip).
    "preamble_marker": "--- prints below this line ---",
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
    # dev #545 / public #127 — `presence/resumes`, not a bare root `resumes/`: the old default
    # audited as UNKNOWN in _tree.py's root classification, so rendering one resume failed the
    # engine's own tree audit. A profile that already OVERRODE local_dir keeps its own value;
    # this is only the default, and _tree's legacy fallback still finds files already rendered
    # to the old root location.
    out.setdefault("local_dir", _tree.rel("resumes"))
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
    block.setdefault("local_dir", _tree.rel("resumes"))   # dev #545
    # dev #545 / public #127 — this string is WRITTEN INTO THE USER'S OWN config.json by
    # `_write_config`, so it described the pre-#127 location two lines below the line that
    # moved it: someone reading their configuration was told the wrong place to look for a
    # file we had just relocated. It now names `local_dir` itself, which keeps it true for a
    # profile that overrode the default as well as for the shipped one.
    block["_why"] = ("drive = push to the job-search Drive folder (needs a Google account and "
                     "the documents connector). local_docx = write a .docx to %s/ inside the "
                     "profile, no Google account required — the default here."
                     % block["local_dir"])
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
        # dev #545 — the path a write would ACTUALLY take, legacy fallback included, so this
        # never names a directory the next render will not use.
        print("  Writes to  : %s/" % _tree.resolve_rel(profile_root(), s["local_dir"]))
        print("  No Google account, connector or network needed.")
    print()
    print("  Switch:  ~/.claude/jobsearch/run variant_out.py --set-mode %s"
          % ("local_docx" if s["mode"] == "drive" else "drive"))
    return 0


def _slug(s):
    return re.sub(r"[^A-Za-z0-9]+", "_", s or "").strip("_").lower()


def identity_header(user):
    """([name_line, contact_line], []) or (None, [missing field names]) — never a partial
    header. `full_name`/`phone`/`primary_email` are the same three `cover_letter_header_
    template` already names; a resume renderer refuses outright rather than ship a header
    missing the field an ATS parser looks for first (issue #64). `user` is `user.json`'s dict."""
    ident = (user or {}).get("identity", {}) or {}
    name = (ident.get("full_name") or "").strip()
    phone = (ident.get("phone") or "").strip()
    email = (ident.get("primary_email") or "").strip()
    missing = [label for label, v in (("full_name", name), ("phone", phone),
                                      ("primary_email", email)) if not v]
    if missing:
        return None, missing
    return [name, "%s • %s" % (phone, email)], []


def filename(variant_id, user):
    """`<name-slug>_resume_<variant-id>.docx`; `user` is `user.json`'s dict."""
    ident = (user or {}).get("identity", {}) or {}
    name_slug = _slug(ident.get("full_name")) or "candidate"
    return "%s_resume_%s.docx" % (name_slug, _slug(str(variant_id)) or "variant")


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
        elif b["type"] == "bullet":
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
        else:  # "paragraph" -- dev #480 / public #113, see parse_variant_blocks
            space_after = gaps["top_level"] if is_last_in_section else gaps["label_to_content"]
            paras.append({"text": b["text"], "size_half_pt": render_cfg["body_size_half_pt"],
                         "color": render_cfg["body_color"], "space_after": space_after,
                         "widow": True, "keep_next": keep_next.get(i, False),
                         "page_break_before": b["page_break"]})
    return paras


def page_estimate(paragraphs, chars_per_page):
    total = sum(len(p.get("text") or "") for p in paragraphs)
    return max(1, -(-total // max(1, chars_per_page)))     # ceil division, stdlib-only


# ---------------------------------------------------------------- content-loss detection
#
# dev #480 / public #113 — fixing the parser (above) closes the specific losses this issue
# reported, but a renderer that can go on to drop content some OTHER way and still print a
# plausible page estimate is the dangerous shape, not just this one bug. `page_estimate` sums
# the KEPT paragraphs' own text — it cannot see what never became a paragraph, so it hides
# exactly the loss it exists to warn about. This is an independent second measurement, against
# the SOURCE file text directly, so a future parsing gap is still caught even if this one is
# not the last.

CONTENT_LOSS_THRESHOLD = 0.15   # >15% of the source's own word count missing from the render
                                # is loud, never a silently-accepted rounding gap


def source_word_count(vtext, preamble_marker, page_break_marker):
    """A crude, deliberately SYMMETRIC word count of the variant file's own printable text —
    after the preamble (if any), excluding blank lines and the page-break marker's own line.
    Markdown syntax (`#`, `-`/`*`/`+`, `**`) is left in place and counted as part of whatever
    line it sits on, exactly as `composed_word_count` below leaves the bullet glyph in place —
    both sides carry the same ~1-word-per-line marker overhead, so the comparison stays fair
    without either side needing to fully re-parse the markdown."""
    lines = _strip_preamble(vtext, preamble_marker).splitlines()
    total = 0
    for line in lines:
        if page_break_marker and line.strip() == page_break_marker:
            continue
        total += len(line.split())
    return total


def composed_word_count(paragraphs, skip=0):
    """The word count actually composed, INCLUDING the bullet glyph (see `source_word_count`'s
    docstring for why that is the fair comparison) but excluding the first `skip` paragraphs —
    the identity header and its blank spacer, which are never part of the source variant file
    and would otherwise make a render look less lossy than it is."""
    return sum(len((p.get("text") or "").split()) for p in paragraphs[skip:])


def content_loss_fraction(vtext, paragraphs, header_lines, render_cfg):
    """0.0..1.0 — the fraction of the source's own word count missing from what was composed,
    or 0.0 when the source has no measurable content to lose. Never negative (a render that
    legitimately adds words, e.g. the identity header already excluded, or a bullet glyph, is
    not "loss")."""
    src = source_word_count(vtext, render_cfg.get("preamble_marker"),
                            render_cfg["page_break_marker"])
    if src <= 0:
        return 0.0
    composed = composed_word_count(paragraphs, skip=len(header_lines) + 1)
    return max(0.0, 1.0 - (composed / src))
