---
description: "Review the resume layer: the claim union, every print-surface variant as it will look, its open items and the presence rules. Use when the user wants to see or check their resume. Not for rendering a file to Drive or .docx; that is /jobsearch:resume."
---

# Review the resume layer

**One name, two paths.** With the plugin's mod on, this opens a review pane (tabs: the claim union,
one per print variant, Open items, Rules; actions: Revise with Claude, Render) and this file never
runs. This file is the other path: mods off, a Remote Control session, or any client that cannot
draw a pane. It replaces the retired presence page (`views/presence_set.html`, ADR-028), so the
review exists in exactly one place.

Run it from the user's search directory and print what it says, verbatim:

```bash
~/.claude/jobsearch/run presence_set.py --text --surface print
```

- **Print the output as it is.** The paragraphs are already split by the script and each variant's
  character counts sit in their own strip line, outside the preview (ADR-028 rules 1, 6 and 7);
  do not re-flow or "tidy" them, because the preview exists to show exactly how the page will look.
- It is **read-only**. Revising a variant is a separate step the user asks for: hand it to
  `profile-optimizer` (under the write lock, through the existing scripts), then run this again.
- A `NOT CHECKED (reason)` line means that source could not be read; say so, never call it empty.
