---
description: "See every job source this search uses (LinkedIn job search, boards such as Indeed and Dice, alert emails, company job-board feeds, curated and investment-firm boards), whether each is on, how it is reached and whether it is covered, and turn any of them on or off, including the boards in the shipped catalog. Also choose how the search reaches each board: a site plugin, Claude's in-app browser, or the Chrome extension. Not for recording a role you saw on a board; that is `record.py board-sighting`."
argument-hint: "[on <source> | off <source> | browser,plugin,chrome | <channel> <plugin-name>]"
---

# Sourcing routes

**What the routes below set:** how a channel is REACHED. Not what it requires, which is a property of the
site itself, and not how often it is reviewed (that is `/jobsearch:tier` and the channel review). Whether a source
is used at all is the on/off verb in *Your sources* further down.

Show every routable channel and the current preference:

```bash
~/.claude/jobsearch/run route.py
```

Ask about one channel:

```bash
~/.claude/jobsearch/run route.py --channel indeed
```

## Your sources: see every one, turn any on or off (0.76.0)

Every job source this search uses is listed in one place, from the profile's own stores: LinkedIn job search, the
boards a browser reads (Indeed), alert emails (LinkedIn, Dice, Indeed), company job-board feeds as a whole, and the
boards the candidate opens by hand (investment-firm portfolio boards and curated startup boards). For each one:
its kind, whether it is **on**, where it came from (`yours` or a shipped catalog entry), how it is reached, and
whether it is covered. A fact the script cannot know prints `NOT CHECKED`, never `0`. The view is read-only:

```bash
~/.claude/jobsearch/run sources.py --text
```

Print its output verbatim under the heading **Your sources**, including its trailing **You could turn on** block
(catalog entries the profile does not hold, offered because the profile already points at them, or because a
source of that kind has no signal to wait for). That block is a suggestion, never an action: stop and let the
candidate choose.

**Turning a source on or off is one verb, for every kind**, and it is the only way this command changes it:

```bash
~/.claude/jobsearch/run record.py source off dice
~/.claude/jobsearch/run record.py source on dice
```

`<id>` is a channel the candidate holds, a catalog entry (turning one on copies and stamps it, exactly what
`record.py channel-catalog add` does), `linkedin-jobsearch` (the LinkedIn job search), or `company-feeds` (every
company feed at once; it never touches a company's own slug). Run `off` or `on` **only after the candidate names
which source**; `--dry-run` previews it. Never answer "stop searching X" by editing `relationship_status` with
`record.py set`: the verb stores what it found so `on` puts back exactly that. A recruiter, a referral or a
company's career page is not a source and is refused with the right verb. The mod's Sources block runs the same
verb. In a profile shared by two machines the verb says that a machine on an engine older than 0.76.0 keeps running
a source until it upgrades, and that the change reaches the other machines after the next run.

A source the candidate holds by hand that matches a catalog entry gets a one-line tip with the `--attach` form, which
ties that row to the catalog so catalog updates reach it (`record.py channel-catalog add <entry> --attach
<channel_id>`; `--kind curated|portfolio|swept-board|alert-sender` turns on a whole kind). The 0.76.0 upgrade asks
once about a hand row that is *nearly* a shipped template: answer it with `--attach`, or
`record.py source keep-mine <channel_id>` to leave the row as it is. A source the catalog later changes is updated at
the next session start when the candidate has not edited it, and asked about when they have
(`record.py channel-catalog take|keep <channel_id>`).

**The new-install defaults** (written once, when a profile is created; an existing profile is never given a source):
company feeds and the alert-email senders the catalog marks default-on are on; the LinkedIn job search and the
curated and portfolio boards are off (the LinkedIn job search has an explicit retired row, so it is off rather than
on-by-absence). Turn the LinkedIn job search on with `record.py source on linkedin-jobsearch` (the runner reads
LinkedIn; it takes no LinkedIn action).

## Feeds

Companies whose own links name a Greenhouse, Lever, Ashby or Workday board are read by a script, not a browser
(`companies[].ats`). Show what is slugged, each company's last outcome, any board the candidate must settle,
and every company careers page not yet linked to a company:

```bash
~/.claude/jobsearch/run feed_poll.py --status
```

Read-only; it fetches nothing. Settle an `ATS AMBIGUOUS` line, or decline or clear a feed, with
`record.py ats <company_id> --url <address> | --none | --clear`. A page a feed covered today is not in the
browser worklist; one it could not read is. The feed needs four hosts allowed (`boards-api.greenhouse.io`,
`api.lever.co`, `api.eu.lever.co`, `api.ashbyhq.com`), which the 0.72.0 upgrade adds to the profile
project's sandbox settings; Workday needs the one entry `*.myworkdayjobs.com`, added by the 0.76.0 upgrade
(whether the sandbox honours it is UNVERIFIED, so a Workday company may show `not covered` until it does).
For each Workday site `--status` prints `covered (sitemap window; completeness assumed)` (the site's list of
jobs is assumed complete, not proven) and a line `window N (cap 100) · baseline <state> · seen N · baseSalary
present on N page(s)`. A Workday company that is not covered carries the code, for example
`not covered: sitemap-capped` (more jobs than the window shows) or `not covered: locale-mismatch` (the
address you gave is in a different language from the site's pages); the browser covers it.

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
