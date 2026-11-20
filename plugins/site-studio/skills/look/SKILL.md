---
name: look
description: 'Set the markup a site''s pages are printed through: copy a look site-studio ships, check the look the site carries, or derive one from the person''s own pages so the site keeps the structure and classes an earlier site had. Use when the person wants the site''s HTML structure to match another site, or asks which look it uses. Not for colours, fonts or brand direction (brand-advisor), and not for moving a site over from its own builder (adopt).'
---

# Look

A site's **look** is a file, `site/looks/<name>.json`, that says what HTML site-studio prints for each
of its blocks, cards and views: the tiles, the quotes, the gallery, the piece cards, the roles and map
views, the resume's role cards. The stylesheets the file names are part of the look and are copied
with it. With no look the plugin prints its own markup. Choosing a look never changes what the person wrote, only the tags
and class names around it, so it is how a site keeps the structure its stylesheet already knows.

Every command runs as `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/look.py" <command> [--repo <dev repo>]`
(the repo defaults to the current folder). Exit codes: `0` done, `1` refused (the line says what to
do; nothing was written). **No command commits.** Each prints the paths it wrote; commit exactly
those, with explicit paths, after the person has seen what changed.

## What to run

- **`list`**: the looks site-studio ships and the looks this site carries, and which one the site
  uses. Run it first.
- **`check`**: reads the site's look and says which constructs it leaves to the plugin's own markup,
  every literal word it carries (text the look prints on the pages by itself), and any live video
  player. From 0.5.0 it also lists each **decoration** (a drawing the look holds as an inline SVG of
  shapes and gradients: no text, no link, nothing loaded), notes one without `aria-hidden="true"`,
  and notes each part of the site's look that shows a portfolio's pieces without the `{{kicker}}`
  that portfolio's `cardKicker` prints through. Run it after any change to a look file, including a
  hand edit.
- **`use <id or path>`**: copies a shipped look (by its id) or a look file from another repository
  (by its path) into `site/looks/`, with the stylesheets it names, and writes the `look` key in
  `site/site.json`. It **never overwrites** a file that holds other bytes: it names the file and
  stops. The whole tree is built in memory before anything is written, so a look that would leave
  the site unbuildable writes nothing.
- **`derive`**: makes a look from a site this repository's own content built, so the new site prints
  the markup the old one did. It reads the pages, finds where each block and card appears, and writes
  `site/looks/<name>.json` (default `derived`; `--name` chooses another, `--replace` overwrites one).
  It prints one line per construct: `mapped`, `unmapped`, `ambiguous` or `not reached`. Read every
  line to the person: a construct that is not `mapped` keeps the plugin's own markup, and the report
  says so. **Known limits in this version,** measured on the plugin's example template and not
  on a real site: a construct derive cannot map keeps the plugin's markup and is printed `unmapped`
  or `ambiguous`; which constructs a real site hits is not known until derive runs on it. Say so
  rather than calling the derived look a match.

## Before `use` or `derive`

- **A site-studio site is needed** (`site/site.json` readable). `derive` also needs the repository's
  own content to be what built the pages: to carry an old site's look to a new site, derive in the
  old site's repository, then run `use <path to that file>` in the new one.
- **The site must be schema 4, or reachable from schema 3.** Writing a look raises the site to
  schema 4 through the one writer, and a 0.3.x install of the plugin (another computer that has not
  updated) refuses a schema-4 tree. Tell the person that before they say yes. A site below schema 3
  is refused with the fix: run `build.py raise-schema` first, as `/site-studio:add-work` does, show
  its report and wait for their yes. **A look that uses anything new in 0.5.0** (the steps view's
  parts, a kicker, a card picture, a piece link or teaser, the full-title slot, or a decoration) raises
  the site to schema 5 when `use` or `derive` writes it, and the command says so: tell the person that
  a copy of the plugin older than 0.5.0 on another computer will then say "update site-studio".
- **A value with nowhere to print.** If a portfolio turns on `cardImage` (roles view), `pieceLink`,
  `pieceTeaser` or `cardKicker` and the site's own look has no slot for it, the build refuses and
  names the part and the slot to add. Add the slot to that part of the look, or remove the setting.
- **The tree must be clean** in `site/`, `content/` and `.site-studio/`: commit or discard first.
- **Literal words.** A look that carries words of its own (a heading, a label) is listed, construct
  by construct, and `use` refuses without `--accept-literals`. Show the person the words and add the
  flag only after they say yes. A derived look keeps the person's own words from the pages it read,
  and lists them; they are the person's, and they become public with the site.
- **A live player.** A look may place a live video player on the page. `check` says so, per part. The
  plugin's own markup places one in a single place: a video address written alone on a line, which has
  been a live embed since 0.2.0 and is kept as it was so no site changes. The `:::videos` block and a
  gallery video load nothing from the video's host until the visitor clicks. For a look that places a
  player in a `videos` item, tell the person that a visitor's browser then loads the video host when
  the page loads. **`derive` can map a live player** (a `videos` item with the iframe in it, a gallery
  video whose caption holds a link to the video), but only when the site is built with
  `"blocks": {"videoEmbed": "live"}` in `site.json`: the key keeps the player's own address, which is
  the value `derive` finds in the old page, where the default adds `dnt=1` and no page holds that. The
  key sets the address and nothing else; the look decides whether a player loads with the page. Adopt
  sets the key itself where the old pages hold live players; on a site already moved over, set it only
  if the person asks for the live players.
- **A link in a gallery video's caption.** The caption part of `gallery-video` takes the video's own
  `url`, `embed` and `title` as well as its `text`, so a look can write a link to the video beside the
  caption (an old site's "Watch now"). The link's words are the person's own and are listed as literal
  text. A gallery video is titled by its caption first, then its alt text, then its host.

## Where `derive` reads the pages from

- **`--build <folder>`**: a folder of built pages already on this computer, such as the folder the
  old site's builder writes its pages to. No network, no question about whose site it is. Prefer it.
- **No flag**: the site's published pages, fetched from its own GitHub Pages address (this needs
  `gh`, logged in, and the network). At most 40 pages, never a script, stylesheet or image, and
  `robots.txt` is honoured. **`--url`** names another start page on the same host set.
- **`--owned-host <host>`**: a host the person publishes on that is not their Pages address. It
  needs the person to type the host back **in their own terminal**: the script prints the exact
  command to run there. Give that command to the person as printed. Never answer its confirmation
  yourself, never try to get a terminal for it, and say that the check cannot verify ownership, only
  that a person was present. With no person (a scheduled or cloud session) only the Pages address
  is accepted.
- Every network or `gh` failure refuses with its own fix and writes no look. It never reports "not
  yours" and never reports everything `unmapped`: if the pages were not built from this
  repository's content it says so and stops.

## After a look is in place

Show the person the result with `/site-studio:preview`, and offer `/site-studio:review` before the
next publish: the look's markup and any literal words go public with the pages. Commit the printed
paths (the look file, its stylesheets and `site/site.json`) with explicit paths, and note the choice
in `HANDOFF.md`. Publishing stays the person's own `/site-studio:publish`.

`/site-studio:adopt` chooses a look for a site it moves over: it derives one from the old builder's
own pages and keeps it only if parity then measures no visitor-visible difference. This skill is for
changing a look afterwards, on a site that is already on site-studio.

## Where it runs

On the person's own computer: the desktop app or a terminal, macOS or Linux. Windows is refused in
one sentence. In a cloud session the plugin is usually absent; where it is present, `derive` may not
reach GitHub or the site, and its refusals say so. A look that holds no literal words and no live
player changes nothing a visitor reads or loads.
