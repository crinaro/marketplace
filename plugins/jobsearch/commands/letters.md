---
argument-hint: "[drive | local_docx | <employer>]"
description: Configure where finished cover letters go — a Google Doc in your Drive folder, or a local .docx — and render one.
---

# Cover-letter output

See also `/jobsearch:resume` — the same output pattern (a Google Doc or a local `.docx`, no Google account
needed) for a declared resume variant, via `variant_out.py`.

Show the current setting:

```bash
~/.claude/jobsearch/run letter_out.py --status
```

Switch modes (`$ARGUMENTS` may name one):

```bash
~/.claude/jobsearch/run letter_out.py --set-mode local_docx
~/.claude/jobsearch/run letter_out.py --set-mode drive
```

Render a drafted letter:

```bash
~/.claude/jobsearch/run letter_out.py --render "<an employer>"
```

## The two modes

**`drive`** — the letter becomes a Google Doc in the job-search Drive folder. Needs a Google
account and the documents connector. The folder id comes from `config.drive.job_search_folder_id`.

**`local_docx`** — the letter is written as a real `.docx` next to the profile, using the standard
library alone. **No Google account, no connector, no network.** Use this when someone has no Drive,
or a workplace that blocks it.

⭐ `drive` is the default only because it was the original behavior. It is not the better mode —
**if `--status` reports mode `drive` with no folder id configured, that is worse than `local_docx`**,
because a document created without a `parentId` lands in My Drive root and the connector **cannot
move a file afterwards**. The only remedy is a second copy for the user to delete.

## ⚠️ In `drive` mode, the script does NOT create the document

It prints the `parentId` and stops, deliberately. **The connector is CREATE-ONLY — no update, no
delete** — so a document must be pushed exactly once, when the text is genuinely final. Never
pre-stage one. After creating it, **read the document back to verify it**: the create response's
reported size is meaningless for a native Google Doc.

## What to check before rendering either way

`--render` reports these, **refuses a letter with a FAIL** (exit 1, the reasons printed, no file written or `parentId` handed
out until the letter is fixed) and will not write an empty document:

- **The body must be `> `-blockquoted.** A letter written as plain text publishes EMPTY, and the
  source file reads perfectly while it happens — every constraint check passes against the file
  rather than the deliverable. An empty body is indistinguishable from "not drafted yet."
- **No banned characters** (the em-dash especially) and **US English**, both read from
  `config.writing`.
- **One page.** The script warns on length, but it cannot measure pages: **`--check` does not count pages**, and neither
  does `--render`. To see the page count, open the rendered file and look before sending — a second page carrying only a
  signature is a real defect. If it spills, cut margins before cutting substance.

## Check the staged letters

```bash
~/.claude/jobsearch/run letter_out.py --check
~/.claude/jobsearch/run letter_out.py --check --advisory
```

Checks every **pending** letter in `applying/cover_letters.md` (a sent or moot one is not checked) and prints one
`STAGED LETTERS` block: the letter guide's verdict first, then each letter with a FAIL or a note. A FAIL is a missing
`> `-quoted body, a banned character, a missing or unreadable `**Purpose:**` or `**Needs:**` line, a need that points at a
paragraph the body does not have, or a broken guide. A note is advice: length, US spelling, a purpose or need count outside
the defaults. Exit 1 on any FAIL. **`--advisory` prints the same block and always exits 0**, which is how an unattended run
uses it. The writer runs `--check` after staging a letter and fixes its own entry until it has no FAIL; `--render` applies the
same per-letter check, so the two never disagree.

```bash
~/.claude/jobsearch/run letter_out.py --check --json
```

prints the same facts as one JSON object for `/jobsearch:status`: `guide` (the verdict line), `problems` (what is wrong with
the writing rules), `pending`, `closed`, `letters` (each one's `heading`, `fails` and `notes`) and `stops` (the open
letter-stopped asks, each with `id` and `title`), or `{"not_checked": <why>}`. Its exit code is `--check`'s.

## Before a letter is written

```bash
~/.claude/jobsearch/run letter_out.py --preflight <opp_id>
~/.claude/jobsearch/run letter_out.py --preflight <opp_id> --record
```

Prints one line, `LETTER PREFLIGHT <opp_id> ok`, or `stop` with a reason: `no-fit` (no fit analysis for the role),
`no-pitch` (the fit found nothing aligned) or `guide` (the declared letter guide is broken). Exit 0 on `ok`, 1 on `stop`, and 2
on `NOT CHECKED` (an unknown role or an unreadable store; nothing is filed). Any exit but 0 means no letter. It is the writer's
first step and the coordinator's before dispatching one. **`--record` files the stop as an ask** (kept while the same stop
persists, closed by an `ok`), so the candidate hears of it in the panel and `/jobsearch:status`. Use it from an unattended
run; use the bare form to look.

```bash
~/.claude/jobsearch/run letter_out.py --answer <opp_id> write-anyway
```

is the candidate's answer to a `no-pitch` stop: write the letter anyway. Run it **only when the candidate gave that answer**.
It resolves that role's open stop and refuses, writing nothing, any other stop or a role with none open; `--preflight` then
reads `ok: written without a pitch, at your answer of <date>` for that role alone, and the letter's entry carries
`**Written without:** a pitch (your answer, <date>)`.

## The letter guide

A candidate who has their own way of writing letters can declare a guide, and the writer follows it instead of the default
structure. **Never run `--set-guide` from a stop or a migration ask without the candidate's answer:** it declares or drops
their guide, and the stop's own text only offers it. It edits `config.json` in place, so every other line of the file stays
exactly as it was.

```bash
~/.claude/jobsearch/run letter_out.py --set-guide presence/letter_guide.md
~/.claude/jobsearch/run letter_out.py --set-guide none
~/.claude/jobsearch/run profile.py --writing
```

- **`config.json` `writing.letter_guide`** holds `path` (relative to the profile root, inside it, at least 20 words of body
  text) and `required_headings` (the `##` headings the file must keep). `--set-guide <path>` writes both, recording the file's
  current headings, and refuses a path outside the profile, a missing file or an empty one, writing nothing. `--set-guide none`
  removes the key. Without it nothing changes: the default structure applies and nothing is checked.
- **What wins:** the writer's HARD RULES (blockquoted body, claims trace, one page, header, banned characters, no compensation,
  nothing submitted), then the guide, then the default structure. Only that the two named lines exist, parse, and cite
  paragraphs that exist is checked; a guide that asks for a shorter letter or another shape is never failed for it.
- **A broken guide stops the letter.** If the file goes missing or empty, or loses a required heading, `profile.py --writing`
  prints `letter guide: BROKEN` and exits 1, `--preflight` stops on `guide`, and `--check` fails. The writer never falls back
  to the default silently, because the candidate chose the guide. To go on, restore the file, keep its new headings with
  `--set-guide <path>`, or stop using a guide with `--set-guide none`.

`profile.py --writing` prints the rules a letter is held to: the header, the email signature, the word target, the page cap,
the banned characters and phrasing, the US-English setting and the guide line. Read these; never retype them into a letter.
