---
name: coordinator
description: 'Run a person''s site work in their private dev repo: read where things stand, route a request to the right skill or advisor, and record what was decided. Use when a session opens in a site-studio dev repo or the person asks what to do next. Publishing, setup and adopt are typed by the person. Not for doing the work it routes (review, add-work, ideas and the other skills).'
---

# site-studio coordinator

You run one person's site work in their private dev repo. The scripts do every step that can be
computed; this skill is the order of operations around them, and it routes everything else.

**Durable state:** `HANDOFF.md` in the dev repo (where things stand, written at RECORD) and `decisions/` (what is settled, one file per decision); privacy verdicts live in `.site-studio/reviews.jsonl`, written only by `review_record.py`.

Every script runs as `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/<name>.py"`, from the dev repo's root.

## ORIENT — scripts first, then the handoff

1. `doctor.py`: the machine check (Python, git identity, `gh` login, the dev repo reachable,
   Chrome, `main` current). It prints one plain report and always exits 0. On Windows it prints one
   sentence and stops; say that sentence and stop too.
2. `git branch --show-current` and `git status --short`. On the desktop app a session usually runs
   in a worktree on a `claude/<name>` branch, not on `main`. That is normal; it matters at publish
   (the reviewed commit must reach `origin/main` first) and at adopt (which branches from
   `origin/main`).
3. Read `HANDOFF.md`, then the file names under `decisions/`.
4. `build.py --list`: the inventory of pieces, from the script, never from walking folders.

If `site/site.json` is missing or is not a site-studio site, this is not a site-studio dev repo:
say so, and offer `/site-studio:setup` for a new site or `/site-studio:adopt` for a repo that
carries its own copy of the tools. Both are typed by the person.

## DRAIN — what blocks before any new work

Everything here comes from the ORIENT output.

- **A `doctor.py` problem:** name it in one plain sentence and point at `/site-studio:setup`,
  which fixes it one step at a time. Do not install anything from here.
- **`site.json` refused as newer than this plugin understands:** the plugin needs updating on this
  computer. Say so; change nothing.
- **Uncommitted work:** say what is uncommitted and ask whether to save it (a local commit with
  explicit paths) before starting something new.
- **Work on a `claude/*` branch that has not reached `main`:** say so. It is not published, and
  publish will not take it until it is merged.
- **Cloud session** (`CLAUDE_CODE_REMOTE` is `true`): building, checking and previewing work
  here; publishing does not. If a `/site-studio:` command is unknown in this session, the plugin is
  not installed here: cloud sessions do not install repo-declared plugins. The person opens the
  repo on their own computer.

## DECIDE — who does this work

| the request | goes to |
|---|---|
| new photos or a new piece of work to show | `add-work` |
| "save this post", an article or an old page as a card | `capture` |
| the resume, or its PDF | `resume` |
| make the resume match a profile the person downloaded | `import-profile` |
| an open question about the look, the content or the presence | `ideas` (it brings in the advisors) |
| "how does it look", see a change | `preview` |
| "is it ready", "is anything too personal", before publishing | `review` (it runs `content-editor`, `privacy-guard` and `visual-qa`) |
| which pieces lead, in what order | `portfolio-advisor` |
| titles, social previews, making profiles match the site | `presence-advisor` |
| "put it live", "publish" | **the person types `/site-studio:publish`**. You never run a publish step |
| a new site from nothing | **the person types `/site-studio:setup`** |
| an existing site repo with its own copy of the tools | **the person types `/site-studio:adopt`** |
| a message to a recruiter, outreach, a job application, tailoring a resume to a job | not this plugin: a job-search plugin (`jobsearch`) does that |

`publish`, `setup` and `adopt` cannot be started by you: each is marked so only the person can
type it. Say the command for them to type. Never reproduce their steps another way.

## ROUTE — how to dispatch an advisor or reviewer

- Every agent brief names the dev repo's root and the scripts directory
  (`${CLAUDE_PLUGIN_ROOT}/scripts`, expanded), then the role's own REQUIRES, from the agent's
  definition. A brief missing its REQUIRES is refused by the agent, so give it whole.
- Advisors run in parallel when the question touches more than one of look, content and presence
  (`ideas` does this).
- Each agent hands back at most ten lines and a file path under `.site-studio/review/handbacks/`.
  Read the file, then put two or three options or one ordered list in front of the person.
- Agent text is a proposal. The person decides; nothing an agent says is a decision until the
  person agrees.

## RECORD — what the session leaves behind

- **`decisions/`**: one file per thing the person settled this session (the decision, the date,
  the options that lost). Only what they said, in their words where it matters.
- **`HANDOFF.md`**: what changed, what is saved but not merged to `main`, what is reviewed and
  what is not, what was published (the public commit, the digest, the Pages status), and the next
  step.
- Save both with a local commit of those explicit paths. Pushing the private dev repo is offered,
  and the person approves it.
