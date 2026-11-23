---
description: "Review the resume layer: the claim union, every print-surface variant as it will look, its open items and the presence rules. Use when the user wants to see or check their resume. Not for rendering a file to Drive or .docx; that is /jobsearch:resume."
---

# Review the resume layer

**One name, two paths.** With the plugin's mod on, this opens a review pane (tabs: the claim union,
one per print variant, Coverage (the coverage report below), Open items, Rules; actions: Revise
with Claude, Render) and this file never
runs. This file is the other path: mods off, a Remote Control session, or any client that cannot
draw a pane. It replaces the retired presence page (`views/presence_set.html`, ADR-028), so the
review exists in exactly one place.

Run it from the user's search directory and print what it says, verbatim:

```bash
~/.claude/jobsearch/run presence_set.py --text --surface print
~/.claude/jobsearch/run resume_report.py --surface print
```

- **Print the output as it is.** The paragraphs are already split by the script and each variant's
  character counts sit in their own strip line, outside the preview (ADR-028 rules 1, 6 and 7);
  do not re-flow or "tidy" them, because the preview exists to show exactly how the page will look.
- The second command is the **coverage report**: what the variants say against the target titles and the
  requirements of pursued roles, and the open gaps. It stores nothing it prints.
- It is **read-only**. Revising a variant is a separate step the user asks for: hand it to
  `profile-optimizer`, which drafts proposals for the gaps the report names. Show the user each one and
  apply the ones they accept with `~/.claude/jobsearch/run record.py presence-apply <id>`: a variant file
  is theirs, in their profile, so no other approval is needed (owner ruling 2026-11-23). It checks the
  variant, puts the file back if the check fails, and records the edit. Never edit a variant file by
  hand. Then run this again, and `~/.claude/jobsearch/run record.py presence-docx <variant-id> --attended`
  so the variant's Word file gets the new words inside the user's own layout (`/jobsearch:resume`).
- **A Word file the user edited.** If they changed the words in a variant's Word file, apply refuses for
  that variant until it is settled: run `record.py presence-docx <variant-id> --attended` first and ask
  the question it prints, in its words. Yes is `--keep word --attended`, no is `--keep md --attended`.
- **A resume from somewhere else** (a `.docx`, `.md` or `.txt` file, or a Google Doc fetched through the
  Drive connector as one of those) goes into a declared variant with `~/.claude/jobsearch/run record.py
  presence-import <variant-id> --from-file <file>`. A PDF is read into a `.md` file first, verbatim.
- A `NOT CHECKED (reason)` line means that source could not be read; say so, never call it empty.
