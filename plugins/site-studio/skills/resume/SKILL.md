---
name: resume
description: 'Update the person''s resume, the one Markdown source the resume page and its PDF are made from. Use for any resume change to the site or to make the PDF. Not for tailoring a resume to a job application, which belongs to a job-search plugin (jobsearch''s application-session).'
---

# Resume

The resume has one source: the Markdown file `site/site.json`'s `resume.path` names. The resume
page and its PDF are both made from it; never edit the page or the PDF directly.

## 1. Change the source

Make the change the person asks for in the Markdown source. Every fact is theirs: a date, title or
result they did not give is a question, not a guess.

### The header, the headings and role cards (schema 4; offer, never assume)

On a site at schema 4 the resume's front matter may also hold `tagline` (one line under the title) and
`links` (a map of label to an `https` address, printed in the header). Both are the person's words and
addresses: write only what they give you.

Two `resume` settings in `site/site.json` change how the body prints, and both are the person's choice:

- **`layout: cards`** turns each `###` heading written as `Role · Organisation` (a space, a middle dot,
  a space) into a role card that runs to the next heading of level three or above. The page and the PDF
  both print the cards. The default is `plain`.
- **`headings: as-written`** prints a `#` as h1 instead of h2, so the outline matches the page the
  person moved from. The default `shift` prints it as h2, because the page title owns the h1.

To set one, put that one key in the site's `resume` object at the value the person chose, then run
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/siteconfig.py" check site/site.json`. A site below schema 4 refuses
these keys (`needs "schema": 4`): raise it first with `build.py raise-schema --to 4`, show its report and
wait for the person's yes, as `/site-studio:add-work` does. Raising changes no page.

## 2. Make the PDF

`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/resume_pdf.py"` builds the resume page with drafts and
prints it to PDF at the paper size in `resume.paper` (Letter or A4), with backgrounds. It writes
the sidecar `resume.pdf.json` beside the PDF (hashes of the source, the PDF and its text), which is
committed and never published.

- **It needs Chrome.** With no Chrome it refuses and names the install step.
- **The build refuses a stale PDF:** if the source changed and the PDF was not remade, the next
  build says so. Remake it here.
- **The PDF's file name is an address.** `site/site.json`'s `resume.pdf` names the file, and it is
  published as `resume/<that name>`. If the person's earlier site published it under another name,
  `/site-studio:adopt` sets `resume.pdf` to that name and renames the committed PDF and its sidecar
  to match, so the old address keeps working. Never rename the PDF, or change `resume.pdf`, by hand:
  a link someone holds would stop working, and the next publish refuses until the old address is
  kept or released on purpose (see `/site-studio:publish`).

## 3. Look and save

Show the resume page with `/site-studio:preview`, and the PDF. Then commit the source, the PDF and
the sidecar with explicit paths, and note the change in `HANDOFF.md`. The PDF is public once
published, so it goes through `/site-studio:review` like any document.

Tailoring a resume to one job application is not this plugin's work: a job-search plugin
(`jobsearch`) does that.
