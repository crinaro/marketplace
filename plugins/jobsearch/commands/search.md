---
description: "Look for roles now: sweep employer career pages (`companies`), job boards and aggregators (`boards`), or both, on any day, without waiting for the posture's scheduled days. Needs the explicit `attended` form, in a session you are present for. Not the full daily run (that is /jobsearch:daily-run attended); not finding a company's job-board feed (that is /jobsearch:sourcing employers attended)."
argument-hint: "[companies|boards] [attended]"
---

# Search now

`$ARGUMENTS` picks the kind and the form:

| you type | sweeps | the gate call's kind flag |
|---|---|---|
| `/jobsearch:search attended` | career pages and job boards | none (both kinds) |
| `/jobsearch:search companies attended` | employer career pages (`company-site` channels) | `--kind company` |
| `/jobsearch:search boards attended` | job boards and aggregators (`job-board`, `aggregator`) | `--kind board` |
| any of the above **without** `attended` | nothing: a preview of what is due | the same, with `--dry-run` |

This is one sweep and what it finds, not a full run. It does not read mail, run LinkedIn, draft, or rebuild the
dashboard; the next daily run does those. A role the sweep finds is captured, screened and, when the screen keeps
it, researched in this same session (step 4), the way the daily run does it: a posture level governs how often
an UNATTENDED run searches, never whether a found role is looked into. Free company feeds (`feed_poll.py`) are
not this command either: they run every daily run.

## Why it needs the explicit `attended` form

A scheduled task's prompt can be a slash command, and Claude Code documents no in-session marker that tells a
scheduled session from a typed one. If this command were attended by default, a scheduled prompt of
`/jobsearch:search boards` would sweep on every fire and walk around the posture's scheduled days. So it follows
daily-run's rule: **never infer attended.** Only the literal word `attended` in `$ARGUMENTS` passes `--attended`.
Never add it because the session looks interactive, the time of day, or a missing scheduler line.

## The bare form: a preview, nothing swept

Without `attended`, ask the gate without writing anything, with the kind flag from the table (omit it for both):

```bash
~/.claude/jobsearch/run channels_due.py --board-decision --dry-run --kind board
```

Print its output verbatim. Then say that the sweep runs only from the attended form, for example
`/jobsearch:search boards attended`, in a session the candidate is present for, and stop. Dispatch nothing.

## The attended form

1. Journal the start and keep the run id it prints:

   ```bash
   ~/.claude/jobsearch/run journal.py --start search
   ```

2. Ask the **same gate daily-run asks**, with `--attended` and the kind flag from the table (omit it for both):

   ```bash
   ~/.claude/jobsearch/run channels_due.py --board-decision --run <id> --attended --kind board
   ```

   `--attended` lifts the posture's `company_days` and `board_days`, and the posture's `max_agents_per_run` cap
   (this sweep needs one agent, so `minimal`, whose cap is 0 because it runs no unattended sweeps, can still run
   it by hand). It never adds a channel: `manual-candidate`, `human`, `n/a` and retired channels are never in the
   worklist, and a page a feed covered today is not either.

   - **Exit 0:** dispatch `board-sweeper` once, with exactly the ids on the `  worklist:` line, each reached by its
     configured route. The call has already written the dispatch row, marked `attended: true`. **That row spends no
     scheduled slot:** a Monday `/jobsearch:search boards attended` leaves Tuesday's scheduled board sweep due.
   - **Exit 1:** print its `BOARD DISPATCH no ...` line and dispatch nothing. Nothing is due for that kind, no due
     channel has a route this machine can run.
   - **Exit 3:** print its line and dispatch nothing. A posture, `company_days`, `board_days`,
     `max_agents_per_run` or journal it cannot read is never read as permission.

3. When the sweeper hands back, gate its roles exactly as daily-run does, then the same call without `--check`:

   ```bash
   ~/.claude/jobsearch/run deferred.py --add-roles <hand-back file> --run <id> --surface board --check
   ```

   and then the same call without `--check`, with the same outcomes and exit codes as daily-run's board pass.

4. **Capture, screen and research what it found, now, by the daily run's own steps** (owner ruling O6: a role that
   is found and passes the screen is researched when it is found, on every posture, `minimal` included). Read
   `${CLAUDE_PLUGIN_ROOT}/skills/daily-run/SKILL.md` sections **4b. CAPTURE AND SCREEN** and **5. RESEARCH** and
   follow them as written, with this session's run id. They are the one definition; this command restates none of
   their rules, so a change to them reaches this command with no edit here. The scripts they run, so you know what
   you are about to do:

   - capture: `deferred.py --claimable --run <id>`, then `record.py create ... --from-item <item id>` for each
     `capture-role` item, then `deferred.py --done <item id>` (this session holds no run lock, so §4b's
     "no `--already-locked`" is exactly right);
   - screen, in ONE call for every role captured: `profile.py --minimal-screen <opp_id> [<opp_id> ...]`, and
     `record.py decide <opp_id> pass ...` for a `VERDICT remove:<rule>` role;
   - research: one `opportunity-researcher` dispatch for the roles whose block reads `VERDICT keep`, within §5's
     batch size, and `deferred.py --add-research <opp_id>` for any kept role over it, which the next run drains.
     `deferred.py` refuses research for a role that is not `keep`, and a `VERDICT review:<rule>` role waits for the
     candidate's look.

   Do not pass `--attended` to any of these: it lifts the drafting gate, and nothing here drafts.

5. Close the journal: `~/.claude/jobsearch/run journal.py --run <id> --end`. Tell the candidate how many roles came
   back and how many are new (from the `--add-roles` output), the `MINIMAL SCREEN SUMMARY` line, and how many were
   researched now and how many queued, from the scripts' own output, never a count of your own.

## What NOT to do

- Do not sweep a kind the candidate did not name: `boards` is never also career pages.
- Do not run it on a timer. Scheduling is the posture's job (`/jobsearch:tier`); this command is for a person
  who wants to look now.
