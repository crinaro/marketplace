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
dashboard; the next daily run does those. A role the sweep finds is captured, read, screened and, when the screen keeps
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
   worklist, and a page a feed covered today is not either. It also lifts `company_split`: an attended
   `companies` sweep offers every due career page, whatever its split day, and spends no split day, so each
   page's scheduled day still comes.

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

   **Then say what did not get swept (dev #811 / public #170).** Each `CHANNEL GAP` line in the
   `--add-roles` output is a worklist channel that was `unreachable`, `not-attempted` or
   `channel-unaccounted` (the sweeper handed back nothing for it), with its reason. **Name every one of
   them to the person present, with its reason**, and what they can do about it:
   - `upstream-error` (a challenge or block page) or `credential-missing` (a sign-in wall): they can
     open that channel in their own browser, clear the challenge or sign in, and re-run
     `/jobsearch:search boards attended`. The sweeper never clicks through either.
   - `surface-unreachable`: if the browser asked you to approve this site, approve it once in the
     Claude desktop app's Browser pane, then re-run `/jobsearch:search boards attended`.
   - `channel-unaccounted`: the sweeper stopped without saying why. Say so; the channel waits for the
     next sweep.

   Then print the run's own coverage line, so an attended run reads partial the way an unattended one
   does: `~/.claude/jobsearch/run run_summary.py --run <id>`, and quote its `sourcing (board)` line
   (`PARTIAL` when anything above was listed, `complete` when nothing was).
   That summary is **stdout-only** for this command: `kind search` does not call `run_summary.py --post`, so nothing here
   reaches the coordinator inbox. If the summary prints an `EXPIRED (no human contact in N days)` line (applications whose
   owed follow-up expired since the last completed daily or search run, dev #914), quote it to the person present; it is said
   once, by the first completed run after the expiry.

4. **Drain what it found, now, by the daily run's own steps** (owner ruling O6, scoped to target companies since
   jobsearch 0.86.0: a role **at a company the candidate has targeted** (`active-target`) that passes the screen is
   researched when it is found, on every posture, `minimal` included; and the owner's ruling for the drain: a run
   finishes every role it takes on, and what it takes on is counted in target companies. **A role at a company the
   candidate has not targeted is not admitted:** its sighting is recorded, it is held (`held-for-company`) with its read,
   screen and research waiting, and its company becomes a "look into this company?" item, which this command names and
   never decides). Read `${CLAUDE_PLUGIN_ROOT}/skills/daily-run/SKILL.md` section
   **4b. THE DRAIN** (its research step is **5. RESEARCH**) and follow it as written, with this session's run id and
   this session's own render-route declaration. It is the one definition; this command restates none of its rules, so
   a change to it reaches this command with no edit here. The scripts it runs, in its order, so you know what you are
   about to do:

   - link the sightings of roles already known: `record.py capture-batch --run <id> --link-only`;
   - raise the companies to look into: `record.py raise-companies --run <id>` (at most `search.companies_raised_per_run`
     new ones a run; it decides nothing about a company, the candidate answers with
     `record.py company-status <id> active-target|watching|passed`; a profile whose 0.86.0 migration has not run is refused
     with its reason, which you print and go on);
   - plan the intake: `lifecycle.py --drain-plan --run <id> --render-route yes|no`. Read `fanout`, `fetch_calls` and
     `solo` from what it prints, never a number of your own;
   - capture: `record.py capture-batch --run <id> --admitted`, repeated until `deadline-left 0`;
   - read: `record.py read-batch --run <id> --fetch` for what a script can read, then `jd-reader` for the
     `RESIDUE (render)` lines, in one fronted tab, and a posting only the candidate can open is listed under YOUR READ
     with its link and reason, never skipped. A LinkedIn role neither the Browser pane nor Claude in Chrome could read
     is read from its public posting automatically, when your sandbox settings allow the host; `posting_fetch.py --set
     on|auto|off` changes that (`off` stops it; terms in docs/user/jobsearch/posting-fetch.md);
   - re-screen what was read: `record.py read-batch --run <id> --fetch` again, until `deadline-left 0`;
   - research, only past the gate: `deferred.py --add-research <opp_id>` exits 0 for a role screened `keep`, and an
     `opportunity-researcher` dispatch takes those; an exit 2 is a refusal with its reason, quoted to the
     candidate, and a `review:<rule>` role waits for the candidate's look;
   - close: `lifecycle.py --drain-close --run <id>`, and put its `drain:` line, and every `LEFT` line it prints, in
     what you tell the candidate verbatim. Exit 3 is a role left unfinished: say so; the next run takes it again. A held role
   is not a failure and is never in `LEFT`: say how many roles are held, from the `held N (...)` term of the `ROLES` line
   that `lifecycle.py --report` prints, and that each such company waits for the candidate's answer.

   This session holds no run lock, so none of these takes `--already-locked`. Do not pass `--attended` to any of
   them: it lifts the drafting gate, and nothing here drafts.

   The researcher's hand-back (dev #776, dev #861) names TWO files: an `EMPLOYER-POSTING` file (one line per role) and a
   `fit` file (one JSON line per role). Pass each, whole, in this order: `~/.claude/jobsearch/run record.py posting
   --from-file <the posting file>`, then `~/.claude/jobsearch/run record.py fit --from-file <the fit file>` (no
   `--already-locked`; never a line on a command line). A refusal is quoted to the candidate with its remedy line.
   A role is `ready` only once its `fit` is on record. If `record.py fit` answers `invalid choice: 'fit'` it is an older
   engine: quote that exit and continue.

5. Close the journal: `~/.claude/jobsearch/run journal.py --run <id> --end`. Tell the candidate how many roles came
   back and how many are new (from the `--add-roles` output), the `drain:` line step 4's close printed (admitted, finished, left, waiting for
   intake) with any `LEFT` lines, and how many were researched now, from the scripts' own output, never a count
   of your own.

## What NOT to do

- Do not sweep a kind the candidate did not name: `boards` is never also career pages.
- Do not run it on a timer. Scheduling is the posture's job (`/jobsearch:tier`); this command is for a person
  who wants to look now.
