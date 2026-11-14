---
name: import-profile
description: 'Bring the person''s public profile into their resume from a file they downloaded themselves (a profile PDF or a data export), proposing each change for them to pick. Use when the resume should match a profile. Never signs in or scrapes. Not for setting up a job search from a resume, which belongs to a job-search plugin (jobsearch''s onboarding).'
---

# Import a profile into the resume

The input is a file the person downloaded themselves: a profile saved as PDF, or the platform's
data export. This skill never signs in, never opens the profile in a browser and never scrapes it.

## 1. Read the file

- **A profile PDF:** `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/pdftext.py"` recovers its text and
  says whether it read the file. If it reports NOT READ (a scanned or encrypted PDF), say so and
  ask for the data export instead. Never guess the text.
- **A data export:** read its files (CSV or JSON) directly. Use only the sections that belong on a
  resume: positions, education, certifications, skills.

## 2. Compare with the resume

The resume's one Markdown source is the file `site/site.json`'s `resume.path` names. List every
difference: a role, a date, a title, a skill present in one and not the other, or said
differently.

## 3. Propose, one change at a time

For each difference, show the profile's version and the resume's version and let the person pick
one, edit it, or skip it. Nothing is changed without their pick. A profile is not a source of
truth over the resume: it is one more thing the person says about themselves.

## 4. Write and hand on

Write the picked changes to the resume source, then follow `/site-studio:resume` from its PDF step
(the PDF and its sidecar are remade, so the build does not refuse a stale PDF). Note in
`HANDOFF.md` what changed and that the profile file was the source.

Setting up a job search from a resume is not this plugin's work: a job-search plugin
(`jobsearch`) does that.
