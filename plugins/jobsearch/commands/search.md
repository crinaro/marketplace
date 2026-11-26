---
description: "Look for roles now: sweep employer career pages (`companies`), job boards and aggregators (`boards`), or both, on any day, without waiting for the posture's scheduled days, or run the LinkedIn job search (`linkedin`, in the desktop app). Needs the explicit `attended` form, in a session you are present for. Not the full daily run (that is /jobsearch:daily-run attended); not finding a company's job-board feed (that is /jobsearch:sourcing employers attended)."
argument-hint: "[companies|boards|linkedin] [attended]"
---

# Search now

`$ARGUMENTS` picks the kind and the form:

| you type | sweeps | the gate call's kind flag |
|---|---|---|
| `/jobsearch:search attended` | career pages and job boards | none (both kinds) |
| `/jobsearch:search companies attended` | employer career pages (`company-site` channels) | `--kind company` |
| `/jobsearch:search boards attended` | job boards and aggregators (`job-board`, `aggregator`) | `--kind board` |
| `/jobsearch:search linkedin attended` | the LinkedIn job search, one results page a search (jobsearch 0.94.0): [its own form, below](#the-linkedin-form) | none: `linkedin_sweep.py search-plan --attended` |
| `companies` or `boards`, **without** `attended` | nothing: a preview of what is due | the same, with `--dry-run` |
| `linkedin` **without** `attended` | nothing: it says the search runs only as `/jobsearch:search linkedin attended`, in the desktop app, and stops | none |

This is one sweep and what it finds, not a full run. It does not read mail, run LinkedIn's reply pass, draft, or rebuild the
dashboard; the next daily run does those. (`linkedin attended` is its one LinkedIn step, and it is the job search only: it never reads
a message, an invitation or a profile.) A role the sweep finds is captured, read, screened and, when the screen keeps
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
     `RESIDUE (render)` lines, each role's page in its own fresh tab, and a posting only the candidate can open is listed under YOUR READ
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

## The linkedin form

`/jobsearch:search linkedin attended` (jobsearch 0.94.0, dev 1055, 1064, 1065; design-role-first.md 8.1, 19.5, 19.6). It needs the Browser pane of the
Claude desktop app, and it is the only way the search runs with a person at it. It is a search of its own, with its own run and its own gate, **not** the
board gate above: no posture, no quota and no `channels_due.py` call apply. Only the literal word `attended` passes `--attended`. Without it, run nothing
and say `LinkedIn job search: it runs only as /jobsearch:search linkedin attended, in the desktop app`.

1. Journal the start and keep the run id it prints:

   ```bash
   ~/.claude/jobsearch/run journal.py --start search
   ```

2. Declare the browser, as the drain declares its render route: `--browser yes` when `mcp__Claude_Browser__preview_start` is among your tools (a
   deferred one counts: load it through ToolSearch, then declare `yes`); `no` otherwise, and always `no` for a `mcp__remote-devices__Claude_Browser__` tool.
   Then ask the gate, which also writes the dispatch row and the plan, so it cannot be forgotten:

   ```bash
   ~/.claude/jobsearch/run linkedin_sweep.py search-plan --attended --browser <yes|no> --run <id>
   ```

   `--attended` ignores the every-N-days cadence (a scheduled search's `not-due`, 48 hours at the default), a skip and a stop: a person is here. Print its output verbatim.

3. **A warning line comes first.** If the output opens with `LINKEDIN WARNING <date> (<kind>): scheduled LinkedIn search is OFF. Open LinkedIn yourself
   and look. To turn it back on: ~/.claude/jobsearch/run journal.py --linkedin-search-on --attended --warning <date>`, say it before anything else, in
   plain words: LinkedIn warned an earlier run, so the scheduled search stays off until the person has looked at LinkedIn themselves and says so; this
   attended search may still run. The plain form is the one above. **A warning with a reason prints it in the label and says in a sentence what it may mean:** `LINKEDIN WARNING <date> (<kind>, reason=<word>): scheduled LinkedIn search is OFF. <note> Open LinkedIn yourself and look. To turn it back on: ...`, where the note is `This may be a LinkedIn layout change or a search with no results rather than a warning; it is treated as a warning.` after the reasons `no-cards`, `cards-without-text`, `no-dismiss`, `no-about`, `no-main`, `shape` and `language`, and `The page could not be judged (a tool error or an answer nobody could read), which counts as a warning.` after `tool-error`, `empty-result`, `unparsable-verdict` and `judge-error`. Say the note as printed: it is why the search is off, and a layout change is the likeliest cause of the first.
   **Run `--linkedin-search-on` only when the person says, in this session, to turn scheduled searching back on**, with the
   date of the NEWEST warning: nothing else turns it on (not a good search, not time, not an update). **If `--linkedin-search-on` is refused** with `⛔ not turned back on: this turn-on is stamped <at> (UTC <at>), BEFORE the warning it names (<at>, UTC <at>). This machine's clock is behind the warning's, or the profile came from another time zone. Nothing was written: wait until the clock is past the warning's time (or correct it), then run it again.` (exit 2), nothing was written and the search is still off: tell the person that, in those words, and run the same call again only after the clock has passed the warning's time. Never edit the journal, and never name another date to get past it.

4. **Exit 3 is a refusal, a complete answer.** The first line reads `SEARCH-PLAN REFUSED reason=<word>: <sentence>`: print it, say
   `linkedin job search: NOT RUN (<the reason word>)`, close the journal with `journal.py --run <id> --end`, and dispatch nothing. The reasons an attended call can
   meet: `no-browser` (this session has no Browser pane: run it in the desktop app), `linkedin-warning` (LinkedIn warned during this very run: this run opens no
   further LinkedIn page, so start a new run later), `off` (the person turned the source off; `record.py source on linkedin-jobs` turns it on), `no-pin` (the
   profile has not been moved to 0.94.0 yet; its sentence names the migration) and `no-titles` (`targets.titles` is empty). Exit 2 is a malformed call: report it.

5. **Exit 0: dispatch `linkedin-runner` once, in the foreground and waited for,** with a brief that carries the run id, `pass: search`, `search: attended`,
   `attended: yes`, the profile root, and the plan block exactly as printed (from `--- SEARCH PLAN v1` to `--- END SEARCH PLAN ---`). Nothing else: it holds
   no worklist, reads no reply surface, and its own text (`agents/linkedin-runner.md`, "THE SEARCH PASS") carries the rest. Read the plan's `LATER` line to the
   person: those pairs wait for a later search.

6. **When it hands back, say its first line first.** `STOP LINKEDIN WARNING kind=<kind>` means a page was a warning, a sign-in, a CAPTCHA or a page nobody could
   tell from one: the pass ended at once, nothing was retried, waited on or answered, and **no further LinkedIn page is opened in this run** (do not dispatch
   the runner again, and open nothing on LinkedIn yourself). Tell the person the scheduled search is now off, that they should open LinkedIn themselves
   and look, and the command that turns it back on. Whatever the runner read before the stop is still recorded in step 7.

7. Check the ROLES block it filed, then accept it, with the same outcomes and exit codes as daily-run's LinkedIn pass:

   ```bash
   ~/.claude/jobsearch/run deferred.py --add-roles <hand-back file> --run <id> --surface linkedin-jobsearch --check
   ```

   and then the same call without `--check`. A `QUERY PLAN` line says how many of the planned searches were read and lists each one not run as
   `NOT-ATTEMPTED <geo> <title>`: print them as printed, **never a count of roles as a measure of the search.** A hand-back with no block (a stop on the
   first page, or a search that could not read) files none: say so.

8. **Drain what it found** by step 4 of the attended form above (read daily-run's **4b. THE DRAIN**, its research step **5. RESEARCH**, and follow it with this
   session's run id and render-route declaration), then close the journal: `~/.claude/jobsearch/run journal.py --run <id> --end`. A search that was dispatched
   and never returned is a crashed pass, named by the run, never papered over by hand.

9. Print the run's own lines: `~/.claude/jobsearch/run run_summary.py --run <id>`, and quote its `linkedin job search:` line (`<p> planned · <r> read ·
   <c> cards · <i> ids · <n> recorded · <h> held · <b> cut short · <f> filters dropped · stopped by <none|reason>`, or `NOT RUN (<reason>; last <date>)`),
   the warning line first when it prints one. If the person would rather not be asked again soon: `~/.claude/jobsearch/run journal.py --linkedin-search-skip
   --until <date>` skips the due line until a date (at most 30 days); `record.py source off linkedin-jobs` turns the search off.

No CAPTCHA, sign-in or bot check is ever attempted here, by this command or by the runner: if LinkedIn shows one, the person clears it in their own browser,
and the search is run again later.

## What NOT to do

- Do not sweep a kind the candidate did not name: `boards` is never also career pages, and `linkedin` is never part of `companies` or `boards`.
- Do not run it on a timer. Scheduling is the posture's job (`/jobsearch:tier`); this command is for a person
  who wants to look now.
