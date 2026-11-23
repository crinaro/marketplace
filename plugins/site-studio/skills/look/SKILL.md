---
name: look
description: 'Set the markup a site''s pages are printed through: copy a look site-studio ships, check the look the site carries, or derive one from the person''s own pages so the site keeps the structure and classes an earlier site had, or draft a suggestion to site-studio from what the site''s own look adds. Use when the person wants the site''s HTML structure to match another site, or asks which look it uses, or wants to offer a look addition to others. Not for colours, fonts or brand direction (brand-advisor), and not for moving a site over from its own builder (adopt).'
---

# Look

A site's **look** is a file, `site/looks/<name>.json`, that says what HTML site-studio prints for each
of its blocks, cards and views: the tiles, the quotes, the gallery, the piece cards, the roles and map
views, the resume's role cards. The stylesheets the file names are part of the look and are copied
with it. With no look the plugin prints its own markup. Choosing a look never changes what the person wrote, only the tags
and class names around it, so it is how a site keeps the structure its stylesheet already knows.

**site-studio supplies reusable tools, patterns and templates; the person and their session shape the look.** From
0.7.0 a site's own look file (`site/looks/local.json`), its key maps (`reads`) and its own named blocks and views are
the normal way to work, not a workaround: the plugin measures what the site adds, keeps it when derive runs again,
and can offer it back to site-studio when it would help other sites ("Offer an addition back", below). Say it that
way to the person.

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
  It prints one line per construct with its count of instances `mapped`, `unmapped`, `ambiguous` or
  `not reached`; from 0.6.0 a construct that is not wholly mapped, `ambiguous` included, also gives
  its reason and the first page that held such an instance (`(<reason>, first on <page>)`). Read every
  line to the person: a construct that is not `mapped` keeps the plugin's own markup, and the report
  says so. Where a card is printed differently in one place (a home feed, the home samples), derive
  reads that place's cards as their own part (`feed.item`, `home-samples.item`) when the site-wide
  card reads unmapped or ambiguous, and keeps that reading only when it maps more. **Known limits in this version,** measured on the plugin's example template and not
  on a real site: a construct derive cannot map keeps the plugin's markup and is printed `unmapped`
  or `ambiguous`; which constructs a real site hits is not known until derive runs on it. Say so
  rather than calling the derived look a match.

## The person's own look file (0.7.0)

A site can carry two look files, laid over each other construct by construct: the one `look` names (on an adopted
site `site/looks/derived.json`, which derive writes and the person may edit) and `site/looks/local.json`, which only
the person writes and which wins. `site/site.json` switches the second on with one key,
`"lookLocal": "site/looks/local.json"`; the file alone does nothing, and `check` says so ("is not used: site/site.json
has no "lookLocal""). The key needs schema 7: raise the site first with `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/build.py"
raise-schema --repo . --to 7` (it lists every output difference first; from 6 to 7 it should say no page changes;
show the person and add `--confirm` on their yes), add the key, then run `siteconfig.py check site/site.json` and
`check`. Tell the person that a copy of the plugin older than 0.7.0 on another computer then says "update
site-studio".

- **A construct in `local.json` replaces the same construct of the other file whole.** A part it leaves out prints
  as the plugin's own, never as the other file's. `check` lists every construct both files hold
  (`site/looks/local.json replaces "card" of site/looks/derived.json`) and which file each construct comes from.
  Read those lines to the person.
- **An edit to `derived.json` is the person's too.** Derive keeps a construct the person changed exactly as it is,
  and writes its new reading only for constructs it wrote itself. To hand a construct back to derive, delete it.
  After `derive`, commit `.site-studio/derived-look.json` with the look, as its closing line says: that file is how
  the next derive knows which constructs are its own.
- **A key map, `reads`,** maps a place the look prints to the front-matter keys it reads, first value wins:
  `"reads": {"video-embed.wrap.title": ["@caption", "videoName"]}`. The places are a closed list (the installed
  `reference/content-model.md`, "Your own look"); an unknown one is refused with the list. With no entry a place
  reads what it always did.
- **Named blocks and views, `named`,** give a block or a view the site's own name over one plugin block or view's data:
  `"named": {"t-ledger": {"like": "tiles", "parts": {...}}}`, then `:::t-ledger` in content, or `view: t-ledger`
  for a view. The parts are the base's parts and slots; nothing else is the site's to define.
- **The card's running number:** `{{position}}` in `card.wrap` and `{{text}}` in `card.number` print
  `01 / 2022`, `02 / ...` across the groups of a page.
- **On an adopted site whose old builder is still in the repository**, commit a look edit, then run `adopt.py
  parity` (before `apply`) or `adopt.py remeasure` (after): each entry of the person's own gets its own row,
  measured against the old pages. Parity measures commits, so an uncommitted edit is not measured.

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
own pages and, from 0.6.0, keeps it per construct: a construct that loses content the plugin's own
markup shows is dropped and named, and the rest of the look is kept. When adopt shows the person
pictures of a page old beside new, it gives the path of the file to open, never says they were
"shown"; the adopt skill has the wording. This skill is for changing a look afterwards, on a site that
is already on site-studio.

**A look that uses anything new in 0.6.0** (a group heading's count, a piece's dated roles, the
`{{group}}` and video `{{title}}` slots, the nav's `brand` and `section` parts, a feed or home-samples
card part) raises the site to schema 6 when `use` or `derive` writes it; a copy of the plugin older
than 0.6.0 then says "update site-studio". Plugin styles a page links for these
(`site-studio/schema-6.css`) lose to any CSS the person wrote outside a cascade layer; against CSS the
person put in layers of their own they win on the plugin's own markup unless the person's stylesheet
starts with `@layer site-studio;`, which declares the plugin's layer first and so lowest.

## Offer an addition back

When something the person added to their look would help other sites, site-studio can draft a suggestion to its
own maintainers from the addition's **structure alone**. Nothing leaves the computer here: this section ends at a
printed draft, and filing is the person's own step in `/site-studio:adopt`.

Every command runs as `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/adopt.py" [--repo <dev repo>] <command>`.

1. **Run `adopt.py suggest`.** It needs no network and writes nothing. It reads the committed look files, so ask the
   person to commit a look edit first; an uncommitted one is named in one line and not read. It prints one line per
   entry of the person's own (a construct of `local.json`, a construct of `derived.json` they edited, a named block
   or view, a `reads` entry), with a class and the reason:
   - `suggest <id>`: it builds, and it adds something no look site-studio ships has (a derive gap, or a new use of
     the grammar);
   - `ask <id>`: the same slots in the same parts as a shipped look, and only the markup around them differs;
   - `no`: why not (not used on any page, a visible difference left, a literal address, already shipped in a named
     look).
   Read every line to the person. On a site that never had a builder to compare against (one started with
   `/site-studio:setup`, say), a suggestion carries **build evidence only**: the entry builds and passes the site
   checks, with no parity numbers. On a site adopted from a builder parity can run, it carries **parity evidence**:
   the numbers adopt measured. Each draft says which.
2. **For an `ask` line**, show the person the two fragments the script printed (theirs and the nearest shipped one)
   and say in one sentence which you think it is: a pattern another site would want (a semantic element, an
   accessibility relation, another nesting of the same slots) or this site's own styling. That one sentence is the
   only judgement here; never write any part of a suggestion yourself. On the person's word run `adopt.py suggest
   --offer <id>`, which records it as offered.
3. **For a suggestion the person wants to send, run `adopt.py report --suggestion <id>`** and show the person the
   whole text it prints: the title `site-studio look: <id>`, the body (one fixed line per field, the fragment, and
   an `Evidence:` line), and a last line naming the command that files exactly this text. The draft holds no class
   name, id, address or word from their site; say so, and let them read it.
4. **Stop there.** To file it, the person types `/site-studio:adopt` and asks to file that suggestion: filing is a
   publish to a public tracker, and it is written only in that skill, which only the person can start. Never file a
   suggestion from here, and never run `gh issue create` or any other way to open an issue yourself.
5. **If the person does not want it sent**, `adopt.py report --suggestion <id> --decline` records that, and the
   same id is not offered again.

`suggest --offer` and `--decline` each make one commit of `.site-studio/look-suggestions.json` on the current
branch and push nothing; each says so ("committed on <branch>, not pushed"). Until that commit reaches `main` the
next publish refuses, and another session sees it only then. On a site still being adopted (before `adopt.py
apply`), both refuse with "finish adopt.py apply first". In a cloud session `suggest` lists, and `suggest --offer`
and `report --suggestion` refuse: the draft can be printed only on the person's own computer.

`adopt.py parity` prints one line when an entry of the person's reproduced the old pages exactly ("look: N of your
look entries reproduce the old pages exactly; adopt.py suggest shows whether one could help other sites"). That is
the moment to offer this section; nothing else prompts it.

## Where it runs

On the person's own computer: the desktop app or a terminal, macOS or Linux. Windows is refused in
one sentence. In a cloud session the plugin is usually absent; where it is present, `derive` may not
reach GitHub or the site, and its refusals say so. `adopt.py suggest` lists there too, and printing or recording a
suggestion is refused. A look that holds no literal words and no live player changes nothing a visitor reads or loads.
