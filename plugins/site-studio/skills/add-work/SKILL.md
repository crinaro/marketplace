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

**The image is the person's own work, and it stays theirs.** Never redraw, retouch, upscale, recolour or
AI-generate the person's own work; propose a change and let them make it. Preparing an image strips its
metadata and makes size copies; it never changes what the picture shows. If a photo seems to need a retouch,
say what you see and let the person decide how.

**Importing images needs Chrome, on every kind of session.** With no Chrome, the import refuses
and names the install step: say that, and stop the image part. The text of the piece can still be
written.

## 3. The story

Bring in `portfolio-advisor` with the piece's folder: it drafts the story only from the facts in
the folder and returns the questions for every gap. Ask the person those questions. Write the
piece's text from their answers; a fact they did not give is not written.

### Order and blocks (schema 3 and 4; offer, never assume)

- **Order.** A piece may carry `order: <whole number>` in its front matter, and it is read **only** when
  the portfolio's `page.md` sets `sort: "order"`: pieces with an `order` come first, ascending, then the
  rest by date. Ask before you add either; without `sort: "order"` the number does nothing.
- **Blocks.** On a site whose `site/site.json` says `"schema": 3`, the piece's Markdown may hold
  `:::tiles` (rows `figure | label`), `:::quote` (the words, then `— Name, Role, *Title*`),
  `:::gallery` (image lines), `:::videos` (rows `title | url`, and `| media/poster.jpg` for a photo that
  plays the video) and `:::carousel`, each closed by a line holding only `:::`. Write one only when the
  person asks for it. **A video's poster is an image they commit under `media/`; a web address is
  refused**, so ask for the photo. Nothing loads from the video's host until the visitor clicks. A line
  that merely starts with `:::` and is meant as text takes a backslash in front: `\:::`.
- **The first block on a site that is not yet schema 3.** Run
  `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/build.py" raise-schema --repo <dev repo>` and **show the person
  its report**: each page that would change, and each problem (an unknown block, a built-in key in a
  `meta` list). The person decides: `--keep-text PATH:LINE` leaves a line as text, and only after they say
  yes do you run it again with `--confirm`. A site already at schema 3 needs no raise.

### Schema 4: more blocks, and keys a view reads (offer, never assume)

On a site at schema 4 (`"schema": 4` in `site/site.json`) the piece's Markdown may also hold:

- **`:::quotes`**: several quotes in a grid. Each quote is its words, then a line
  `— Name, Role, *Title*` that ends it.
- **A gallery item that plays a video:** an image line followed by a space and a YouTube, Vimeo or
  public Drive address (the image's own caption still goes in its quotes). Without a script the item
  is a link to the video; with the plugin's script it plays in place. Nothing loads from the video's
  host until the visitor clicks. The image is a file the person commits under `media/`.
- **Any number of blocks in a home-page `:::part`** (a part held one at a time before schema 4).

A piece may carry front-matter keys that only a portfolio's index view reads: `employer`, `role`,
`current: true` and `period` (the `roles` view), `pin: lat, lon` (the `map` view), `tileImage`, `tileAlt`
and `tileRole` (the `showcase` view), and `year` (the card number). Ask for one only when the portfolio's
`page.md` sets that view or card number, and write only what the person gives you: a role, a period or a
coordinate you guessed is a wrong fact on a public page. `employer` is required of every piece under the
`roles` view. A piece the person is still working on takes `draft: true`: the preview shows it, a publish
build leaves it out.

A site at schema 3 gets none of this until the person asks. To raise it, run `build.py raise-schema --to 4`
the way the block raise above runs: show its report, and only after their yes run it again with `--confirm`.
Raising to 4 changes no page, and a 0.3.x install of the plugin on another computer then refuses the tree
until it is updated: say so first.

### An unlisted Vimeo link (schema 9; offer, never assume)

An unlisted Vimeo address carries a private code (`vimeo.com/<id>/<code>`, or `?h=<code>`). By default the build
leaves the code out of the player's address, so the video shows Vimeo's own notice instead of playing, and every build
names each such link (file and line). When the person adds one, **offer `blocks.unlistedVideos`**, and say what it
publishes: the private code goes into the page, where any visitor can read it. In a `:::videos` row or a gallery video the
page's own link already shows it; on a line that holds only the link, this is the first time it is published. A public
Vimeo or YouTube link needs none of this. Only on their yes: raise the site first if it is below schema 9
(`build.py raise-schema --repo <dev repo> --to 9`: show its report, and add `--confirm` after their yes; a copy of the
plugin older than 0.9.0 on another computer then says "update site-studio"), add `"unlistedVideos": true` to the
`blocks` object in `site/site.json`, then run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/siteconfig.py" check site/site.json`.

### A reference for this piece (schema 9; offer, never assume)

When the person adds a reference for the piece (a `ref: <name>` line in its body, or a page just captured for it),
offer to say which piece it is for: `"project": "<the piece's folder name>"` in that reference's `reference.json`
(`<portfolio>/<folder>` when two portfolios hold the same folder name). It is a plain key that prints nothing by
itself; where the look has a "used by" line, the reference names this piece even when no `ref:` line does, and **it follows the
piece if it is moved** to another portfolio. It needs schema 9 (raise the site as above, with the same warning about
older copies). `/site-studio:capture` asks the same question for each page it saves.

### Moving a piece to another portfolio

When the person wants an existing piece under another portfolio, do not move the folder by hand:
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/move.py" <portfolio>/<slug> <target portfolio> --repo <dev repo>`. It needs
a clean `site/`, `content/` and `.site-studio/` (an uncommitted `HANDOFF.md` does not count), and a site at
schema 3 (otherwise it names `build.py raise-schema` and writes nothing). It computes the whole move in
memory first and writes nothing unless the finished site builds and keeps or releases every address the piece
had published: each page gets a redirect, every other file (an image, a PDF) is recorded as released in
`.site-studio/addresses.json` with the reason "moved with <slug>", and `{{link:...}}` and the home
page's `featured` and `showcase` names follow the piece, and so does a reference's `project` that names it. **A move writes the site at schema 4** (the
address record is a schema-4 file, so a 0.3.x install refuses the tree instead of publishing it without
the address guard): tell the person that before you run it. Read its output to the person, then commit
exactly the paths it printed (it never commits). The released files are named at the next publish's dry run,
and the person approves them there.

## 4. Preview

`preview.py`, then show the piece as `/site-studio:preview` does. Change what the person asks.

## 5. Save

`check_site.py` on the build: fix any gate failure before saving. Then commit the piece's folder
and any page it changed, with explicit paths. Pushing the private dev repo is offered and the
person approves it. Note the piece in `HANDOFF.md`. Publishing is separate: `/site-studio:review`
first, then the person types `/site-studio:publish`.
