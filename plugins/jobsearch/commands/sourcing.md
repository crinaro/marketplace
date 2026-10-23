---
description: Choose how the search reaches each job board — a site plugin, Claude's in-app browser, or the Chrome extension — and see which channels are routable right now.
argument-hint: "[browser,plugin,chrome | <channel> <plugin-name>]"
---

# Sourcing routes

**What this sets:** how a channel is REACHED. Not whether it is searched — that is
`/jobsearch:tier` and the channel review — and not what it requires, which is a property of the
site itself.

Show every routable channel and the current preference:

```bash
~/.claude/jobsearch/run route.py
```

Ask about one channel:

```bash
~/.claude/jobsearch/run route.py --channel indeed
```

## Feeds

Companies whose own links name a Greenhouse, Lever or Ashby board are read by a script, not a browser
(`companies[].ats`). Show what is slugged, each company's last outcome, any board the candidate must settle,
and every company careers page not yet linked to a company:

```bash
~/.claude/jobsearch/run feed_poll.py --status
```

Read-only; it fetches nothing. Settle an `ATS AMBIGUOUS` line, or decline or clear a feed, with
`record.py ats <company_id> --url <address> | --none | --clear`. A page a feed covered today is not in the
browser worklist; one it could not read is. The feed needs four hosts allowed (`boards-api.greenhouse.io`,
`api.lever.co`, `api.eu.lever.co`, `api.ashbyhq.com`), which the 0.72.0 upgrade adds to the profile
project's sandbox settings.

**`manual-candidate` channels.** A board whose terms forbid automated access (Wellfound, Work at a Startup,
Welcome to the Jungle) is a channel with `access: manual-candidate`. `route.py` prints `candidate: you open
it` and no mechanism for it, and `channels_due.py` lists it under FOR YOU TO OPEN, never to a browser. Only
its alert email, if the channel sets `alert_sender`, is swept. Do not change a channel to `manual-candidate`
to make it skip a route that failed: it states what the site requires.

**Portfolio boards (0.75.0).** An investment firm's job board is a `manual-candidate` channel too, with
`portfolio_of` (the firm's company id) and `board_hosts` (the board's own hosts, which no run may open). Record
a role the candidate saw there with `record.py board-sighting <channel_id> --company ... --title ... --url
<the company's own posting URL>`; a `--url` on one of the board's hosts is refused. `portfolio_boards.py`
reports what each board produced and whether it is covered; it fetches nothing. A role whose every address is
on a board host is recorded `unavailable: manual-board`, never read.

## Change the order mechanisms are tried

`$ARGUMENTS` may already name one. Valid mechanisms: `plugin`, `browser`, `chrome`.

```bash
~/.claude/jobsearch/run route.py --set-preference browser,plugin,chrome
```

**What each one means:**

| mechanism | what it is | when it is the right first choice |
|---|---|---|
| `plugin` | a dedicated plugin for that site | it is installed, and it beats scraping the site's HTML |
| `browser` | Claude's own in-app Browser pane | the usual default — in-process, holds a signed-in session |
| `chrome` | the Chrome extension | the in-app pane is not signed in, or the site only works in a real profile |

⭐ **`chrome` was the original default and is no longer the best one.** This plugin was built
before Claude had a browser of its own, so everything authenticated went through the extension.
The in-app pane arrived later and needs no second application awake. Chrome remains a genuine
fallback — not a legacy artifact — because a site that only works in the candidate's real,
signed-in profile still needs it.

## Point a channel at a plugin

```bash
~/.claude/jobsearch/run route.py --set-plugin indeed indeed-jobs
~/.claude/jobsearch/run route.py --set-plugin indeed ""     # clear it
```

The plugin is only offered for the channel it is named for, and only when `plugin` appears in the
preference order. **A plugin named for a channel that is not in the rotation is refused** — a
setting that is never read is one the candidate will later believe is in force.

## When something is unroutable

```bash
~/.claude/jobsearch/run route.py --check
```

Exits non-zero if any channel's `access` value cannot be read, or still carries a legacy value
that fuses the mechanism into the requirement (`login-chrome`). ⚠️ **An unroutable channel gets
skipped, and a skipped channel looks exactly like one that was searched and found nothing** — so
this is a real finding, not a tidiness check.

If `--check` reports legacy values, the migration handles it; nothing here needs doing by hand:

```bash
~/.claude/jobsearch/run migrate.py
```

## What NOT to do

- **Do not edit `config.json` by hand to set these.** The setter validates before it writes; a
  typo stored in config falls through to the default at run time and looks like it was honoured.
- **Do not change a channel's `access` to force a mechanism.** `access` states what the site
  requires. Rewriting it to steer the route is how the two got fused in the first place.
- **Do not read a route as proof a mechanism works.** `route.py` reports the ordered list to try;
  it cannot see whether the pane is signed in or a plugin is installed. Whichever surface is
  actually used should be reported by the run.
