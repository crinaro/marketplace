---
name: add-work
description: 'Add or update one piece of work on the site: gather the files, prepare the images, get the story from the person, preview it, save it. Use whenever the person has new work to show. Not for the resume (resume) or for a captured post alone (capture).'
---

# Add work

One piece of work, added or updated under `content/`, with its images prepared and its story in
the person's own facts. Every computable step is a script; run each script's `--help` once for its
exact arguments.

Every script runs as `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/<name>.py"`.

## 1. Gather

- Ask for the files: photos, drawings, PDFs, links. Full-size originals go in the piece's
  `originals/` folder, which git ignores: they carry metadata and never enter any repo.
- `build.py --list` shows the existing pieces, so an update goes to the right folder and a new
  piece does not duplicate one.
- Ask for the fields `site/site.json`'s `work` section marks as required for a piece.

## 2. Prepare the images

`images.py` imports each image: it strips the metadata (location included), reads the dimensions,
converts HEIC and TIFF on a Mac, and has `resize.py` make the size copies through Chrome. The
prepared copies are what get committed.

**Importing images needs Chrome, on every kind of session.** With no Chrome, the import refuses
and names the install step: say that, and stop the image part. The text of the piece can still be
written.

## 3. The story

Bring in `portfolio-advisor` with the piece's folder: it drafts the story only from the facts in
the folder and returns the questions for every gap. Ask the person those questions. Write the
piece's text from their answers; a fact they did not give is not written.

## 4. Preview

`preview.py`, then show the piece as `/site-studio:preview` does. Change what the person asks.

## 5. Save

`check_site.py` on the build: fix any gate failure before saving. Then commit the piece's folder
and any page it changed, with explicit paths. Pushing the private dev repo is offered and the
person approves it. Note the piece in `HANDOFF.md`. Publishing is separate: `/site-studio:review`
first, then the person types `/site-studio:publish`.
