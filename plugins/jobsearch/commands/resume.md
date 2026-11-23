---
argument-hint: "[drive | local_docx | <variant-id>]"
description: Configure where a rendered resume variant goes — a Google Doc in your Drive folder, or a local .docx — and render one. Not for reviewing resume content; that is /jobsearch:review-resume.
---

# Resume-variant output

Show the current setting:

```bash
~/.claude/jobsearch/run variant_out.py --status
```

Switch modes (`$ARGUMENTS` may name one):

```bash
~/.claude/jobsearch/run variant_out.py --set-mode local_docx
~/.claude/jobsearch/run variant_out.py --set-mode drive
```

Write or update a declared variant's Word file (`local_docx`):

```bash
~/.claude/jobsearch/run record.py presence-docx "<variant-id>" --attended
~/.claude/jobsearch/run record.py presence-docx --all --attended
```

**The Word file is kept in the layout you give it** (jobsearch 0.93.0). The first run writes the default layout.
Fix the spacing, text size or margins in Word as you like: the next update rewrites only the paragraphs whose
words changed in the md, inside your formatting. A dated backup (`<name>.before-update-<date>.docx`) is taken
before each update; the ten newest are kept. **If you change the words in Word**, nothing is overwritten and you
are asked: "You changed the Word file for <variant>. Update the resume we keep on file from it? If not, your change
will be overwritten at the next update." Yes is `--keep word`, no is `--keep md` (your file is backed up first),
each with `--attended`. A question a scheduled run filed is answered with `--keep word|md --answer
resume-word-edited:<variant-id>`. `--fresh --attended` goes back to the default layout after a `before-fresh`
backup. Under `drive` it prints `SKIPPED` and writes nothing.

Preview, or write a separate copy somewhere else:

```bash
~/.claude/jobsearch/run variant_out.py --render "<variant-id>" --dry-run
~/.claude/jobsearch/run variant_out.py --render "<variant-id>" --out "<path>"
```

`--dry-run` composes and prints the outline; it writes nothing. Under `local_docx`, `--render` without `--out` or
`--dry-run` is refused: it would overwrite the Word file `record.py presence-docx` keeps in your layout. A copy
written with `--out` is yours and is never updated.

## The two modes

**`local_docx`** — the default. A real `.docx` written next to the profile, using the standard
library alone. **No Google account, no connector, no network.**

**`drive`** — the document becomes a Google Doc in the job-search Drive folder. Needs a Google
account and the documents connector. The folder id comes from
`config.drive.job_search_folder_id`.

Unlike `/jobsearch:letters` (whose `drive` default is historical, not a recommendation), this renderer has
no prior behavior to inherit — `local_docx` is the deliberate default.

## ⚠️ A render refuses before writing anything, on purpose

`record.py presence-docx` runs the same checks before it writes the default layout.

**The visibility gate runs first, on every render, before any target.** A variant whose
`resume_variants.py --check` state is `unplaced` or `private-on-public` (public #59/ADR-027 — a
public-surface page printing a claim nobody reviewed for a public audience) is refused outright:
run `~/.claude/jobsearch/run resume_variants.py --check` first and fix what it names.

**The header is refused, not blanked, when identity is incomplete.** A declared variant begins at
the job title; this script builds the name/phone/email header itself from `user.json` and refuses
to render at all if any of the three is empty — a resume with no phone number is worse than no
resume at all when it reaches an applicant-tracking system.

## What the render encodes, so you don't have to

ATS-safe by construction: real `Heading1`/`Heading2` section styles, a bullet as a literal glyph
(never an auto-numbered list), no tables, no text boxes, one column. Widow/orphan control on every
paragraph, and a short section (a job title plus a few bullets) keeps itself from splitting across
a page break. An explicit page break is authorable from the variant file itself, on its own line:

```
<!-- pagebreak -->
```

A variant file's own drafting notes (context for a recruiter call, never send-ready text) can sit
above a literal marker line and never reach the document:

```
--- prints below this line ---
```

Everything at or above that line is excluded entirely — the same exact-line convention as the
page-break marker above. A file with no such line renders exactly as it did before this existed.

The render settings (font, margins, colors, the spacing scale) ship with a complete, opinionated
default — nothing to configure before the first render — and are overridable per key from the
`render` block under `config.writing`'s own `resume_output` section; setting one value leaves
every other one at its shipped default.

**Open the file and check the page count** before sending — the script prints an estimate, never
a fact.

## Content loss is loud, not silent (dev #480 / public #113)

The page-count estimate is computed from what was actually composed, so it cannot by itself show
you something that never made it into the document. `--render` runs a SECOND, independent check
against the source file's own word count; when more than 15% of it is missing from what was
composed, it prints a `🛑 CONTENT LOSS DETECTED` banner and **exits 3** (not 0) — in `--dry-run`
too. Exit 3 means the file was still written (it is the best artifact available to go inspect),
but do not treat that render as complete: open both files and compare before sending.
