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

The render settings (font, margins, colors, the spacing scale) ship with a complete, opinionated
default — nothing to configure before the first render — and are overridable per key from the
`render` block under `config.writing`'s own `resume_output` section; setting one value leaves
every other one at its shipped default.

**Open the file and check the page count** before sending — the script prints an estimate, never
a fact.
