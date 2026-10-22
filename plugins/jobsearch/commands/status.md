---
description: "Show the job search's status now: what needs you and by when, the inbox, the lock, the last and next background run, whether the runs did anything, dashboard freshness and gate health. Use when the user asks where things stand and no status pane is open. Not for working an item (that is the coordinator)."
---

# Status

**One name, two paths.** With the plugin's mod on, a person typing this at a terminal or in the
Desktop app gets a status pane and this file never runs. This file is the other path: mods off
(`disableAllHooks`, an organisation's managed-mods-only policy, a Claude Code older than the mods
API), a Remote Control session driven from a phone, or any client that cannot draw a pane. The
status reaches you as text either way, and it comes from the same script, so the two cannot disagree.

Run it from the user's search directory and print what it says, verbatim:

```bash
~/.claude/jobsearch/run panel.py --text --full
```

- **Print the output as it is.** Do not summarise it, re-rank it or add advice: it is a status
  line, not a briefing. If the user wants to work an item, `/coordinator` is the session for that.
- It is **read-only**: it takes no lock, acknowledges no inbox row and marks no staleness
  watermark, so it is safe to run at any time, including while a background run is mid-flight.
- A line that says `NOT CHECKED (reason)` means that source could not be read. Say so plainly; do
  not describe it as empty or as healthy.
- If `panel.py` prints `no profile here`, the working directory is not inside a job-search profile.
  Say so and stop; never look for a profile elsewhere.
