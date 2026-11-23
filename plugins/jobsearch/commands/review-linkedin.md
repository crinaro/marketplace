---
description: "Review the public-profile layer: every public-profile variant with each field's character count, the LinkedIn coverage report, its open items and the presence rules. Use when the user wants to check their LinkedIn profile text. Not for signing LinkedIn in; that is /jobsearch:linkedin."
---

# Review the public-profile layer

**One name, two paths.** With the plugin's mod on, this opens a review pane (tabs: the claim union,
one per public-profile variant, Coverage (the coverage report below), Open items, Rules; action:
Revise with Claude) and this file never
runs. This file is the other path: mods off, a Remote Control session, or any client that cannot
draw a pane. It replaces the retired presence page (`views/presence_set.html`, ADR-028).

Run it from the user's search directory and print what it says, verbatim:

```bash
~/.claude/jobsearch/run presence_set.py --text --surface public-profile
~/.claude/jobsearch/run resume_report.py --surface public-profile
```

- **Print the output as it is.** Every field is shown with its character count in a strip line
  outside the preview (ADR-028 rule 6). No LinkedIn character cap is recorded, so nothing here says
  a field is over one. Do not re-flow the paragraphs.
- The second command is the **coverage report**: the stated headline and skills against the target
  titles and the recurring requirements, and the open gaps. It stores nothing it prints.
- It is **read-only**. Revising is a separate step: hand it to `profile-optimizer`, which drafts
  proposals for the gaps the report names, then run this again. Nothing is posted to LinkedIn by
  this command or by the review pane; the candidate pastes every change.
- A `NOT CHECKED (reason)` line means that source could not be read; say so, never call it empty.
