---
argument-hint: "[drive | local_docx | <variant-id>]"
description: Configure where a rendered resume variant goes — a Google Doc in your Drive folder, or a local .docx — and render one.
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

Render a declared variant:

```bash
~/.claude/jobsearch/run variant_out.py --render "<variant-id>"
~/.claude/jobsearch/run variant_out.py --render "<variant-id>" --dry-run
```

`--dry-run` composes and prints the outline; it writes nothing.

## The two modes

**`local_docx`** — the default. A real `.docx` written next to the profile, using the standard
library alone. **No Google account, no connector, no network.**

**`drive`** — the document becomes a Google Doc in the job-search Drive folder. Needs a Google
account and the documents connector. The folder id comes from
`config.drive.job_search_folder_id`.

Unlike `/letters` (whose `drive` default is historical, not a recommendation), this renderer has
no prior behavior to inherit — `local_docx` is the deliberate default.

## ⚠️ `--render` refuses before writing anything, on purpose

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
