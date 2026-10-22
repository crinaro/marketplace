---
description: "Review the public-profile layer: every public-profile variant with each field measured against its recorded character cap, its open items and the presence rules. Use when the user wants to check their LinkedIn profile text. Not for signing LinkedIn in; that is /jobsearch:linkedin."
---

# Review the public-profile layer

**One name, two paths.** With the plugin's mod on, this opens a review pane (tabs: the claim union,
one per public-profile variant, Open items, Rules; action: Revise with Claude) and this file never
runs. This file is the other path: mods off, a Remote Control session, or any client that cannot
draw a pane. It replaces the retired presence page (`views/presence_set.html`, ADR-028).

Run it from the user's search directory and print what it says, verbatim:

```bash
~/.claude/jobsearch/run presence_set.py --text --surface public-profile
```

- **Print the output as it is.** Every field is shown with its recorded character cap and the count
  in a strip line outside the preview (ADR-028 rule 6): a field over its cap says so, and nothing
  here rounds that away. Do not re-flow the paragraphs.
- It is **read-only**. Revising a variant is a separate step: hand it to `profile-optimizer`, then
  run this again. Nothing is posted to LinkedIn by this command or by the review pane.
- A `NOT CHECKED (reason)` line means that source could not be read; say so, never call it empty.
