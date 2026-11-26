"""letters: the cover-letter checks, pure functions over values (jobsearch 0.95.0, design-cover-letters.md; dev 1071, 1072, 1073).

* `entries`  parse a cover-letters file into entries; the `**Purpose:**` / `**Needs:**` grammar and the paragraph count.
* `rules`    the writing values (header, signature, targets, banned characters, US-English terms) from config and user dicts.
* `guide`    the profile's declared letter guide: its verdict, and the pure half of `--set-guide`.
* `check`    per-entry findings, the whole-file report, the `marked.json` contract and the preflight decision.

Nothing here reads a profile at import, imports an entry point, or prints; the entry points (`letter_out.py`, `profile.py`,
`check_narrative.py`) do the reading and hand values in.
"""
