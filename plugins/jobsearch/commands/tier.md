---
description: "Change how often the job search runs (the main lever on cost), and which weekdays career pages and job boards are swept. Not for turning a source on or off; that is /jobsearch:sourcing."
argument-hint: [minimal|economy|standard|full]
---

Change the user's budget tier, **and actually apply it** — the whole point is that these two stay
in agreement.

**Cost here is `runs per day × agents per run`.** Deterministic sweeps (mailbox digests, calendar
artifacts, silence detection, the dashboard) are free at every tier and always run, so a lower tier
loses timeliness, not coverage.

**A tier limits how often the search looks, never whether a role it finds is researched.** Every
role a run finds is captured and given the scripted minimal screen on every tier, and every role the
screen keeps is researched in that run on every tier, `minimal` included (jobsearch 0.78.0). What a
tier does not permit unattended, drafting, is queued rather than dropped (`deferred.py --add-draft`),
and it drains on the first run whose tier permits it. Say so when you describe a lower tier: nothing is lost, it waits. A run is unattended unless
the owner starts it with the explicit attended form, `/jobsearch:daily-run attended`.

## 1. Show where they are

```bash
~/.claude/jobsearch/run posture.py
```

## 2. If they named a tier, set it

Edit `search.posture` in their `config.json`. Do not touch the `postures` definitions unless they
ask — those are theirs to tune.

### Sweep days

A tier that lists `board` under `unattended` searches on its own, but only on the weekdays it names, in two
separate lists: `company_days` for employer career pages and `board_days` for job boards and aggregators. Defaults:
`economy` career pages Mon, boards Tue; `standard` Mon+Wed, Tue+Thu; `full` Mon+Wed+Fri, Tue+Thu+Sat; `minimal`
never. A profile upgraded to 0.78.0 moves to these days. Mail, company job feeds and LinkedIn are not on these
lists: they run every run. When they want a different rate, set it with the validated setters, never a hand edit:

```bash
~/.claude/jobsearch/run posture.py --set-company-days mon,wed [--posture <name>]   # `none` turns it off
~/.claude/jobsearch/run posture.py --set-board-days tue,thu [--posture <name>]     # `none` turns it off
```

They refuse an unknown or repeated day and say what they wrote. The days apply to unattended runs only. A person
who wants to look now uses `/jobsearch:search attended` (on `minimal` too); it ignores the days and does not use
up the scheduled sweep.

## 3. ⭐ APPLY IT TO THE SCHEDULE — this is the step that makes it real

The tier declares a `cron`; the scheduler holds the one that actually fires. **Changing the config
alone changes nothing about what you are billed.** Update the `search-daily` scheduled task's cron
to the tier's value using `update_scheduled_task`.

⚠️ **If `update_scheduled_task` is not available on this surface (anything other than the desktop
app), SKIP this step and say so in one plain line** — for example: *"Skipped applying the tier to
the schedule: it would have called `update_scheduled_task`, which needs the desktop app."* Do not
fail, and never say the schedule was changed when it was not: the tier is saved in `config.json`
but the cron that actually fires is unchanged until it is applied from the desktop app.

⚠️ **Never change a task's schedule from inside a run of that task** — it re-arms and can fire
immediately.

## 4. Confirm the trade honestly

Tell them what they just bought or gave up, in latency rather than tokens. On `minimal`, LinkedIn
is not swept unattended at all. On `economy`, a recruiter reply may sit for hours rather than
minutes. That is usually fine for a job search — but they should hear it now, not discover it when
a message sits overnight.
