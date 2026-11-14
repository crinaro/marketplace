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

## 2. Make the PDF

`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/resume_pdf.py"` builds the resume page with drafts and
prints it to PDF at the paper size in `resume.paper` (Letter or A4), with backgrounds. It writes
the sidecar `resume.pdf.json` beside the PDF (hashes of the source, the PDF and its text), which is
committed and never published.

- **It needs Chrome.** With no Chrome it refuses and names the install step.
- **The build refuses a stale PDF:** if the source changed and the PDF was not remade, the next
  build says so. Remake it here.

## 3. Look and save

Show the resume page with `/site-studio:preview`, and the PDF. Then commit the source, the PDF and
the sidecar with explicit paths, and note the change in `HANDOFF.md`. The PDF is public once
published, so it goes through `/site-studio:review` like any document.

Tailoring a resume to one job application is not this plugin's work: a job-search plugin
(`jobsearch`) does that.
