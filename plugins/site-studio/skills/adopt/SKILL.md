---
name: adopt
description: 'Move an existing site repo onto site-studio when it carries its own copy of site-studio''s scripts: your content stays, site-studio publishes the converted site after you say yes and archives the old builder, or it stops and says what blocks it. Not for starting a new site (setup).'
disable-model-invocation: true
---

# Adopt an existing site repo

The person typed this. Adopt keeps everything that is the person's (content, decisions, brand,
media, their own customisations) and moves the site's building and publishing onto this plugin. It
measures first, on a copy, and changes nothing the person's site publishes until a measurement says
a visitor would see no difference. Then `adopt.py apply` does the rest in **one process, behind one
ask**: it publishes the converted site, waits for GitHub Pages to build it, archives the old
builder, and pushes that to the dev repo's `main`. **After that, pushing to the dev repo publishes
nothing, and the person must be told so.** `apply` ends in exactly one of two states, and you say
which:

- **completed:** site-studio has published the converted site, and the old builder is archived under
  `archive/` (nothing is deleted);
- **blocked:** something stopped it. `main` is unchanged, nothing of the old builder moved, **the old
  builder keeps publishing**, and the line says what to do next.

Adopt reads the public repo in steps 1 and 2 of `apply` (one clone, `gh` reads only) and writes to it
only in step 3, only through `deploy.py`, the path `/site-studio:publish` takes.

Every step runs as `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/adopt.py" [--repo <dev repo>] <step>`
(the repo defaults to the current directory). Exit codes: `0` done (for `apply`: **completed**), `1`
refused (the line says why; nothing changed), `2` a usage error, or `report` found a report it would
not file, `3` adopt needs an answer from the person (ask it, record it, re-run), `4` **`apply` ended
blocked**. For `apply` the first line says which: `adopt completed`, or `adopt blocked at step N of
5`; from step 3 on, a `cause:` line names the stop's cause id (`ss-adopt/apply/<stop>`, or
`ss-adopt/env/...` for what only the person's own environment can answer). Quote that line to the
person. The exit code alone tells a completed `apply` from a blocked one.

The person's decisions are kept in `.site-studio/adopt-plan.json`, written only by the `adopt.py`
steps below. Never edit that file by hand.

## Preconditions

Run `adopt.py check` first. It prints `adopt ok: <origin/main or HEAD> <sha> can be converted`, or
refuses with the reason. **It exits `1` while any `you decide` problem exists**, after printing every problem with its fix, so a red `check` is a list to work through, not a failure to report. Do not work around a refusal. Before that line it may print, once, which
tree adopt will convert and whether parity can run (the **parity basis**, below), and every problem
it found in what it would write, all at once, each marked `apply fixes this` or `you decide`.

- On the person's own computer: the desktop app or a terminal. In a cloud session, stop and say
  adopt runs on their own computer.
- The dev repo has no uncommitted changes. Untracked `.claude/worktrees/` and adopt's own plan
  file do not count.
- **`apply` needs `gh`, logged in, and the network:** it reads the public repo to check that a
  publish would be accepted, then publishes. `check`, `inventory` and `parity` need neither. A read
  that cannot be answered (no `gh`, no network) is printed as `NOT CHECKED`, never as a pass.
- **adopt fetches for itself.** `check`, `inventory`, `parity` and `apply` run
  `git fetch origin main` and refuse if the fetch fails. Do not fetch on its behalf. The steps that
  record a decision (`confirm`, `unit`, `fact`, `reviewed`, `paper`, `folder`, `convert`, `kind`) make no network
  call. They work against the `origin/main` that the last `inventory` fetched, so run `inventory`
  first.
- **The parity basis: one commit, which every step uses.** It is the checkout's `HEAD` when `HEAD`
  is origin/main or is ahead of it (a fast-forward), and `origin/main` otherwise. The inventory, the
  converted tree, both sides of parity, the new branch's parent and the "has anything moved" check all
  use that one commit. So "fix it, commit it, run adopt again" works, on a `claude/<name>` session
  worktree (the desktop app starts each session on one) and on `main` alike: adopt does not need
  the checkout to be on `main`. **When `HEAD` is ahead, adopt says so first and lists the commits;
  the apply branch will include them. Show that list to the person before you go on.** If `HEAD`
  has diverged from `origin/main`, or fallen behind it, adopt converts `origin/main`, says up front
  that **parity will be UNVERIFIED**, and the local builder is kept; tell the person to bring the
  branch and `origin/main` together first if they want parity. A commit made after the inventory
  moves the basis, and `apply` refuses with "the parity basis moved since the inventory": run
  `inventory` again.
- **The repo must be one adopt can read:** `site/site.json` exists and carries `name`,
  `siteTitle` and `publicRepo`. Anything else (another site generator, no `site/site.json`, a
  `site.json` without those keys) is refused with a pointer to `/site-studio:setup`; say so and
  stop. A `site.json` that already has `schema` and `engine` is refused as already converted.

## 1. Inventory: match by what each file does

`adopt.py inventory` (add `--json` for the full record, which carries `problems`, each with its fix, and
`sections`, the `{{#page:...}}` sections adopt wrote from local tokens). It walks `.claude/agents`,
`.claude/commands`, `.claude/skills`, `scripts/`, `tools/`, `site/*.js`, `CLAUDE.md` and
`.claude/settings.json`, and classifies each file by what it does, not by its name. Show the
person one table: the local file, what it does in one line, the plugin counterpart, the evidence
(score, residual, signals), the proposed action. Read every flagged file yourself before you show
it. A **SHADOW** warning means a local agent has the name of one of the plugin's agents. That holds
whatever the file does: a project agent outranks the plugin's agent of the same name when it is
called by its bare name, so **while the file is kept** it replaces the plugin's agent, on this
computer and on any computer the repo is cloned to. The inventory says whether the file does the
same job (and what it scored) or only shares the name. Show every SHADOW line, and for a file that
stays, suggest renaming it to `<name>-local`. Adopt reads this repo's `.claude/agents/` only: a
same-named agent in the person's own `~/.claude/agents/` also replaces the plugin's, and adopt
cannot see it. The plugin's own review and ideas steps call its agents by their scoped names
(`site-studio:<name>`), which a same-named file does not replace. Show any `tokens the plugin's
build will refuse` line as well.

**The template's `{{<folder>Link}}` token ** adopt renames it to `{{link:<folder>}}` only where it is an
`<a>` tag's whole `href` value. A bare one (`<nav>{{workLink}}</nav>`) stood for a whole anchor, so adopt wraps it as
`{{#page:<folder>}}<a href="{{link:<folder>}}">LABEL</a>{{/page}}`, with the label from `site/site.json` (`work.label`),
and the inventory shows that section. Where it has no label (another portfolio, a piece name, no `work.label`) or the
token sits inside another tag or anchor, it is left as written and the inventory prints a `step for you` line: read
that line to the person, who writes the anchor by hand. It is never listed as converted.

Record each decision as the person makes it:

- **DUPLICATE:** archived (moved under `archive/`, never deleted) only after the person confirms:
  `adopt.py confirm <path>`. To keep it:
  `adopt.py confirm <path> --keep`. Any residual units are shown first.
- **PARTIAL:** kept by default: with no decision at all, `apply` keeps the file and lists it as "kept
  by default (no decision)". Go through every residual unit the inventory lists, by its id:
  `adopt.py unit <path> <unit-id> person-data --kind context|voice|rule [--name <slug>]` ("person
  data, move it"), `adopt.py unit <path> <unit-id> rule` ("a standing rule of mine, keep it for
  every agent": see **Standing rules** below) or `adopt.py unit <path> <unit-id> keep` ("behaviour
  the plugin lacks, keep it"). The file becomes removable only when every unit is decided and none
  is `keep`, or when parity (step 3) passes.
- **AMBIGUOUS:** show both scores; the person decides which capability it is:
  `adopt.py confirm <path> --as <capability>` (or `--keep`).
- **CUSTOM:** kept, listed as a customisation.
- **MIXED** (`CLAUDE.md`, settings): split, in step 4.
- **DATA:** never removed.

`apply` refuses while a DUPLICATE or AMBIGUOUS file (the ones adopt proposes to remove) has no
decision; an undecided PARTIAL is kept. `apply --dry-run` never refuses on undecided files: it
previews, and says which a real apply would stop on.

**Problems in what adopt would write.** The inventory (and `check`) lists every problem at once,
each with its fix. **The list comes from the plugin build's own acceptance**, run in memory over the
converted tree, not from rules adopt keeps: so anything the build would refuse (an unknown token, a dead
link, a missing image, a key it does not read, a block it cannot parse) is listed up front with
`path:line` and its fix, and `check` never says "can be converted" about a site the build then refuses. An
unexpected failure inside that build prints `NOT CHECKED`, never a traceback; read it to the person and
report it. **`apply fixes this`** are the mechanical ones: adopt makes the change itself
and lists it in the commit (a clone-URL `publicRepo` becomes `owner/name`; a `previewUrl` loses its
trailing slash; `[key, label]` pairs become the `work.labels` map; a `content/<name>/` folder with
no `page.md` and no Markdown in it is renamed `content/_<name>/`, kept as source material and not
built; a trailing slash on a `redirects` key or target is dropped, and the same address is served).
**`you decide`** problems are never rewritten, and `apply` refuses until the person settles them. For a
folder with no `page.md`, ask whether it should be source material or a portfolio; for a portfolio run
`adopt.py folder <name> portfolio`, and `adopt.py folder <name> source` renames it to
`content/_<name>/`. **A folder that holds Markdown is never moved without that answer** (it may be pages
the person's own builder publishes), and **a reserved name** (`home`, `about`, `media`, `resume`,
`references`) is never moved at all: at schema 3 `content/home/index.md` and `content/about/index.md`,
each with its own `media/`, are the home and about pages, so nothing in the repo moves (parity measures
whether their media addresses match the old builder's). When apply replaces a value, it also names each file the person keeps that still holds the old
text (`file:line`, under "Your own script may depend on the old form"): read that list to the
person, because adopt cannot tell whether their script needs updating.

**The list is by cause, not by count.** `check` reports **every** refusal in a file, not the first (every
unknown key in each `reference.json`, every unknown token in a page, every unknown front-matter key), each with its
line. It then groups them: problems that say the same thing about the same kind of file are **one cause** on one line
("35 places, one cause: ...", with the first few named), and a redirect or `{{link:X}}` that names a portfolio the
build refuses is listed as **following from** that portfolio's own problem ("follows from content/work/page.md:4;
resolves with it"). **The number after `you decide` is the number of causes, so it is the number of decisions to
settle**: read it that way to the person, and settle the cause (the consequences go with it). A fix adopt makes
itself is never grouped. A decision recorded with `adopt.py folder`, `convert` or `paper` is read by `check` the same
way parity reads it: a folder the person has decided is not listed as undecided again.

**Strays the build only warns about.** The build and preview print a named warning for a `.md` other than `index.md` or a sub-folder other than `media/` or `_*` in a piece folder, and for a piece front matter key that is neither built in nor in the portfolio's `meta`/`cardMeta`; the published bytes do not change. Where nothing has been converted yet, `check` lists each as a problem with its fix and refuses (`you decide`), so `adopt ok` is not said over a page that would go unpublished. Read each fix to the person.

**When the basis moves,** the decisions do not all go with it. After the person commits a hand fix and runs
`inventory` again, a decision about a path that still exists and did not change is **kept**; every one cleared is
printed by name ("2 decision(s) cleared because the basis moved: content/notes -> source; the parity result ..."). Read
that line to the person: the cleared ones are the ones to decide again, and the parity result is always one of them,
because it measured another tree. If the old basis is no longer in the repo, nothing can be compared, so all are
cleared and the line says why.

**Old addresses (meta-refresh pages).** A hand-made page under `site/src/` that is nothing but a
redirect (a refresh with a delay of 0, a canonical link, a link or a script to the same place, and a
few words) is listed as a problem `apply fixes`: apply writes it into `site.json` `redirects`, keyed the
way the build serves it, deletes the page and lists it in the commit, with any text it drops. The build
then writes an equivalent page at the same address. A refresh page that is more than that (a delay above
0, a paragraph of its own, a target the build has no page for, or a key `site.json` already sends
elsewhere) stays a hand page. The inventory and the commit list each one with its reason: read those to
the person. If the site has a local builder, its parity will show the generated redirect page as a
difference from the hand-made one; that is expected: the local builder does not write that page, so parity reports DIFFERENT, and the person
decides whether to accept it with `adopt.py parity --accept`, after reading what `parity` listed (step 3).

**Conversions that depend on the site's own builder.** The `check` and `inventory` output ends with a
`conversions` list: each conversion, whether it is `GENERAL` (follows from site-studio's own model) or
`TEMPLATE` (follows from the template this plugin replaces), and `apply fixes this`, `waits on parity`
or `you decide`. A conversion is made only when parity measures that it changes no page a visitor
loads, and, while the person's builder is kept, that it does not change what that builder publishes.
For a site made from the old template, a piece file named `work.md` is renamed `index.md` on those
terms (the commit lists each rename, content untouched), and a piece's `tilePhoto` key is written as `cover`
when the piece has none (the value is untouched). The template's local home tokens in a hand-made home
page (`{{homeTitle}}`, `{{homeIntro}}`) are rewritten to the build's own `{{home:<part>}}` on the same
terms, so the hand page is fed by the home copy: `{{homeIntro}}` alone in a paragraph becomes
`{{home:intro}}`, and anywhere else (a meta description) it is frozen, replaced by the first line of
the copy as the text a builder writes there, so it does not update when the home copy changes; the
commit marks each frozen one, and parity measures the page. The other template conversions follow the
same terms and are each measured by parity before they are `apply fixes this`: a reference in the
template's format (`myRole` becomes the visible `role` line, `captured_from` becomes `fetched`; no file
moves, so no image address changes), the home page's own keys (the headline, intro, stats, quote,
showcase and contact become the build's home keys and `:::part` blocks), the resume header (`name`,
`headline` and `linkedin` become the title, tagline and a contact link), the `<nav>{{nav}}</nav>` wrapper
(rewritten to `{{navLinks}}`, so the nav is not nested), the person's name on the resume when
`site.json`'s `name` is a domain, the resume PDF renamed to the name the old builder published it
under, and the template's `tile:`, quote, `video:` and image lines as the plugin's `:::tiles`, `:::quote`,
`:::videos` and `:::gallery` blocks. Three conversions are `you decide` by their
nature, and apply leaves the page as written unless the person chooses them: a portfolio `view` the
plugin does not model is removed so that index becomes the plugin's grid (`adopt.py convert viewKeys`; the
`roles`, `map` and `showcase` views are modelled at schema 4 and are kept, not removed; until the person
chooses, the build refuses a view it does not know and the site stays on the person's builder); a
meta-refresh page with
**head boilerplate** (an icon, a manifest, a theme colour) is recognised as a redirect, but the
build's redirect page drops those, so the line names each dropped element (`adopt.py convert
redirectBoiler` converts it); and **other resume front-matter fields** become body paragraphs, which
adds visible text, so each field is named and a list has no default (`adopt.py convert resumeFields`;
`adopt.py convert <name> --keep` undoes the choice). Read each line to the person. Parity names the
page that differs once a chosen conversion is part of what it builds.

**A `{{home:<part>}}` token the person wrote, and what adopt leaves as the person's own.** adopt
rewrites only the template's local tokens (above); a `{{home:<part>}}` the person already wrote is the
build's own token (schema 3, a hand-made home page fed by `content/home.md`), so it is listed as
covered, once, and left exactly as written; the
build then refuses a part the home page does not have, naming the file and line. Since 0.4.0 the plugin
builds roles, map and showcase indexes, the resume's role cards, a few more blocks and a per-site markup
look from content, so a site whose own builder printed those can be converted and measured. What the
plugin still does not build (a block renderer of the person's own, an index it has no view for) is not
changed: the person's builder keeps publishing it. adopt does not write `view: "page"` or freeze a section
for the person; if they want an index to stay their own file under `site/src`, they set `view: "page"` in
that portfolio's `page.md` themselves, and adopt's parity measures the result.

**What the site does, and its kind.** After the problems, the inventory lists the features it found
(a resume link that disappears when there is no resume, pieces marked `featured: true`, a hand-made
home page, an old address that forwards, custom field names) and what site-studio does about each; a
local token is classified by the build's own token table: one the build accepts is "covered"
(`{{featured}}` renders the featured selection), and one it refuses says so, with the fix. "site-studio
has no equivalent" is said only for a signal that is not a token. Read that list to the person. It then
says which **site kind** it infers (`portfolio`, `hub` or `custom`): that is only a proposal. Ask the
person which kind the site is, and record the answer with `adopt.py kind portfolio|hub|custom`.
**Apply writes only a kind the person confirmed**: with none, it writes none and says in the commit
how to set one; `portfolio` is the default and is never written. A hub or custom site is written as
schema 2.

**Standing rules.** A residual unit marked `rule` is carried, verbatim and with its source path,
into the site repo's `CLAUDE.md` under `## Standing rules carried by adopt`, after the file it came
from is removed, and the commit lists each. It is refused on a file that stays: a rule travels only
out of a file adopt removes. Every agent the plugin dispatches loads the project's `CLAUDE.md`, and
a file under `.claude/rules/` reaches a plugin agent as well (measured on Claude Code 2.1.325, in a
terminal session; not measured elsewhere). Tell the person they may move those rules
there if they prefer; adopt itself writes `CLAUDE.md` only.

**Every tracked file gets one disposition.** The inventory (and `apply`) lists each file as:

- **published:** the old builder used it and the plugin's build puts it on a page or uses it as an input;
- **draft:** a piece the old builder did not publish; it is marked `draft: true` and its folder stays
  together;
- **archived:** nothing builds or reads it any more. It moves under `archive/` (a leading `.claude/` is
  written `_claude/`, so no skill can load from it) and is listed in `archive/ARCHIVE.json`. Nothing is
  deleted;
- **engine:** the old builder itself; it moves to `archive/` only in `apply`'s last step, after
  site-studio has published;
- **kept:** repository files that are not content (the README, licence, `CLAUDE.md`, `HANDOFF.md`,
  `.site-studio/`) and anything the person chose to keep;
- **no landing spot:** the old builder used it and the plugin's build cannot hold it, so a visitor
  would lose it. **This blocks `apply`.**

"Used" is measured from what each build outputs and from what changes when a file is removed, never
guessed. A file that cannot be measured (for example, no `node`) blocks, or waits for the person.
Show the person the list by disposition and ask about every file in the last group. To record a
choice for one file: `adopt.py file <path> archive|draft|keep|engine`.

**Measured settings.** A conversion that picks one value from a short list is a *setting*. adopt
measures these, in this order: the site's `look`; whether the home page's featured pieces come from each
piece's `featured: true` (`featuredFrom`); a portfolio's piece order (`sort.<portfolio>`); a nav without
a Home item (`nav.home`); resume headings as written (`resume.headings`) and the resume's role cards
(`resume.layout`); whether site.json's `work` keys apply to every portfolio (`workKeys`); card values
without their labels (`cardLabels`); a number on each card (`cardNumber`) and how it prints
(`cardNumberFormat`: `padded`, `plain` or `order`); a back link above each piece title (`backLink`); a
menu link that goes straight to a one-piece portfolio (`menuLinks.<portfolio>`) and what that
portfolio's index is (`onePieceIndex.<portfolio>`: a redirect page, or the listing it was); the
heading level inside a carousel slide (`blocks.headingLevel`); whether a lone reference card sits in the
reference grid (`blocks.loneReferenceGrid`); the home page's `<title>` form
(`titleForm`), whether its intro holds the whole body or its first block (`introScope`) and the order of
its parts (`partOrder`); and a portfolio's index view (`view.<portfolio>`).

- **How a value is chosen.** adopt builds the plugin's side once per candidate and compares only the
  pages that setting can change. It keeps the first value that makes those pages equal (or markup-only),
  and otherwise the one with **strictly fewer** visitor-visible differences than the default, saying so.
  A tie is `you decide`, naming each candidate's first difference, and the default stays.
- **Settings are judged together.** Each setting is judged with every other at its chosen value, in up
  to three passes, because a setting such as a card number only helps under the right look. When a
  derived look is in play, each candidate is judged under the look derived for it.
- **Two differences never decide a choice,** because every candidate has them: the text of
  `<meta name="description">` (the description a search result shows; no page does) and the plugin's own
  stylesheet and script files under `site-studio/`. Both are still differences: the description is
  VISIBLE and ends the run as an ACCEPT (see "Page descriptions" in step 3), and the verdict can be
  `DIFFERENT` for it alone.
- **`blocks.videoEmbed`** (`facade`, the default, or `live`) is offered only where the converted tree
  holds a `:::videos` block or a gallery video row, and is judged last, on every page, under the look
  derived for each candidate. `live` keeps a video's own address (Vimeo's without `dnt=1`), which is the
  value the look derive finds in the old player, so with it the look maps `videos` and `gallery-video`.
  The key is only the address; whether a player loads with the page is the look's markup.
- Each is `apply fixes this` when parity measures no visitor-visible difference, and otherwise `you
  decide`, with the difference named. **Without `node` nothing is measured**: every setting reads `you
  decide: not measured`, and none is filled in with a default; the `look` in particular is never
  guessed. The person may choose a value (`adopt.py setting <name> <value>`; a chosen value is kept and
  never measured, so say that) or forget the choice so the next parity measures it again
  (`adopt.py setting <name> --clear`).

**The look.** When the plugin's own markup does not match the old site's, adopt derives a look from the
old builder's own pages and the converted content (`site/looks/derived.json`, the same work as
`/site-studio:look derive`) and keeps it only if parity then measures no visitor-visible difference.
A construct it cannot map keeps the plugin's own markup and is reported as `look/unmapped/<construct>`
or `look/ambiguous/<construct>`. **Measured on the plugin's template fixture, this version's derive maps
every construct the fixture uses**, and the only visible difference left is the page descriptions a
search result shows (named for the person to accept). What a real site needs is not known until adopt
runs on it; say that plainly. A construct derive cannot map is a limit of this version, not something
the person did.

## 2. Keep the person's data, before anything is removed

For every DUPLICATE agent or command, read its body and list the statements that are the person's
data: who they are, their field, their audience, their voice, their standards. The person confirms
each one. Record each confirmed statement:

`adopt.py fact <path> --kind context|voice|rule --text "<the statement>" [--name <slug>]`

`context` (who, field, audience) goes to `decisions/00-context.md`, `voice` (voice and visual
standards) to `BRAND.md`, and `rule` (a person-specific rule) to a new `decisions/NN-<slug>.md`.
Each lands under a heading naming the file it came from and the date. When every statement of a
file is recorded, or the person says it has none: `adopt.py reviewed <path>`.

`adopt.py apply` refuses while any removal's facts are unreviewed, so nothing is removed before
its facts are moved.

**Resume paper size.** Adopt reads it from the repo's existing resume PDF. When it cannot (a PDF it
cannot read), inventory reports that it needs the answer and `apply` exits `3`. Ask the person whether
their resume is Letter or A4, then run `adopt.py paper Letter` or `adopt.py paper A4`. Never pick one
for them. **A site with no resume PDF is not asked**: apply writes `"pdf": null` and no paper size
(the site is then schema 3), since no page is printed to a paper size.

## 3. Parity: build it both ways

`adopt.py parity` builds the site twice and compares the two. The repo's own builder runs under
`node` on a **temporary copy of the working copy, ignored files included**. The plugin builds from
the parity basis's committed files with the adopt changes applied: **the same commit as the local
side**. Neither build touches the repo.

- Parity runs on the parity basis (see the preconditions): `HEAD` when it is origin/main or a
  fast-forward of it, so a commit the person just made is what is measured. When `HEAD` has
  diverged from or fallen behind `origin/main`, parity is **UNVERIFIED** and the local builder
  stays; adopt says so before it does any work.
- **EQUAL:** the local builder is a duplicate.
- **DIFFERENT:** it is kept, and the differences are listed **by cause**: every differing hunk of
  every file is read, and a change that is the same on many pages is one line with its page count and a few of
  the pages named. A difference that is only an **addition inside `<head>`** (a meta tag, a link) is its own
  class, listed after the body differences and never in place of one: a page with both shows both. A file with
  more hunks than are listed says how many it did not list. A path present in only one build is listed as it
  always was. An ignored file in the working copy is named when it is the likely cause. Show every
  difference. `adopt.py parity --keep <dir>` leaves the two builds in `<dir>/local` and `<dir>/plugin` as the
  builders wrote them, so a difference can be opened and read (`<dir>` must not exist, or be empty, and must be
  outside the repo). If the person accepts the differences, so the build becomes the plugin's, run
  `adopt.py parity --accept`. It accepts only what an earlier `parity` on the same commit already showed:
  it prints those differences (one line per cause) before it records `ACCEPTED`. If you run it before the
  person has seen them (no earlier `parity` on this commit, or the differences are not the ones the last
  run showed), it lists the differences, records `DIFFERENT`, says it did not accept, and the person is asked
  again; run `parity --accept` once more to accept exactly those. Otherwise the local
  builder is kept and the agents and commands can still be archived.
- **UNVERIFIED** (no Node on this computer, the local builder failed, or the plugin build
  refused): never a pass, and the local builder stays. When the plugin build refuses, parity lists what
  it needs in the same `path:line` and fix form `check` prints.

Parity makes two measurements, and both are named in what it prints:

- **P2, the plugin against the local builder** (the comparison above): does the converted site print what
  the person's own builder prints?
- **P1, the local builder against itself** (run when P2 is not EQUAL, because the builder is then kept):
  the person's builder on the original, against the same builder on the **converted** tree. It proves adopt's
  changes did not change what that builder publishes. When P1 differs, adopt runs it again with each
  conversion class alone (at most eight runs) and names each class that differs, with the paths. **P1 can also say
  FAILS**: the person's builder does not merely publish something else on the converted tree, it
  **exits non-zero**. adopt then runs each class alone, and the class that makes it fail is `you decide` with the
  builder's own failure line named ("your own builder FAILS on the tree this conversion makes (...)"). A
  conversion the person has **chosen** (`adopt.py convert <class>`) that does this is not written: `apply` and
  `apply --dry-run` refuse it, naming the line, while parity is not EQUAL or ACCEPTED. Tell the person the
  choices: `adopt.py convert <class> --keep` leaves the page as written, or they fix the builder and run
  `adopt.py parity` again. A builder that fails with no conversion made is not the conversion's doing: that stays
  UNVERIFIED.

**What a visitor can see, and what parity counts.** Every difference is sorted as one a visitor can see
(content, layout, appearance, behaviour, a link that resolves differently, missing media) or markup
that a visitor does not (attribute order, build metadata, an asset path that serves the same bytes,
whitespace a browser collapses). **Whitespace that exists in only one build** is markup only when a
static read of both builds' markup, stylesheets and scripts says a browser would collapse it: it
touches the edge of a block box, nothing around it preserves whitespace, and no script or off-origin
stylesheet could change that. Otherwise it is a visible `text` difference. The read errs toward
visible, and the publish re-check cannot repeat it for whitespace (it exists only in the old build).
**Page descriptions** (owner ruling): the `<meta name="description">` a search result shows is a VISIBLE
difference, even though no page shows it, because a person reads it before the page. `parity`, and
`check` after it, name it once, before anything is published, as an ACCEPT: one line per page, with the
old and the new words ("to accept: the description a search result shows will read differently on N
pages ..."), and say when it is the only difference. A site whose only difference is that ends
`DIFFERENT` and is kept by its builder until the person has read the list and runs `adopt.py parity
--accept`; the result is `ACCEPTED`, never `EQUAL`, by design. Say that plainly, and that a page's
`description:` can be edited afterwards. The setting choice still ignores the description and the
plugin's own `site-studio/` stylesheet and script files, because every candidate has them.

**Video embeds.** An old site's video is often a live player on the page. The plugin's video block is a
click-to-load image: with no script it is a link, and nothing loads from the video's host until the
visitor clicks (a Vimeo address carries `dnt=1`). That is the default for every site that does not set
`blocks.videoEmbed` and for every new site. Adopt measures the key (see step 2): where the old pages
hold live players it sets `blocks.videoEmbed: live` and the derived look places the player, so the
video pages reach `EQUAL` apart from their descriptions. The plugin's own look never loads a player
with the page. Do not describe the click-to-load form as equal to a live player.

**What adopt does not promise.** `EQUAL` is measured here only for the fixtures the plugin's tests
build. A real template site ends `EQUAL` or `MARKUP-ONLY` (the converted site publishes), `ACCEPTED`
with the differences named (the person was shown them and said yes), or blocked with the old builder
still publishing. It is never silently changed, and you never describe a real site as identical.

A conversion is **`apply fixes this`** only when it changes no page a visitor loads. Where P2 is not equal, or
P1 shows the person's builder would publish differently, it is `you decide`, with the difference named, and
the page stays as written. A `TEMPLATE` conversion also needs the template's fingerprint in the repo (at
least two piece folders holding `work.md` and none holding `index.md`); without it, it is `you decide`.
When parity cannot run, every conversion that changes a file is `you decide`: "parity could not measure
this".

## 4. Apply: one process, behind one ask

Run `adopt.py apply --dry-run` first and show the person what it would do. It writes, publishes and
pushes nothing, and says whether a real `apply` would stop, blocked. Then `adopt.py apply`. **Ask the
person before you run it, and tell them what it does**: it publishes the converted site (public
forever), waits for GitHub Pages, archives the old builder and pushes to the dev repo's `main`. The
plugin's guard then asks once more (see "The guard" below); that one yes covers every step.

`apply` runs five steps in one process and says which one it is on:

1. **Measure and convert**: the check, the conversions, the file dispositions and parity, on the parity
   basis, as above. It makes the conversion as one commit on the branch `site-studio/adopt-<date>`,
   made with git plumbing, so the person's own checkout, index and branch never move. Its message
   lists what was archived and why, what data moved where, what configuration changed (every value it
   normalised, and which kept files still hold the old form), which hooks were rewritten, what
   customisations were kept, which commits not yet on `origin/main` it includes, and the parity result.
2. **The publish preconditions**: the dry run's own refusals, run read-only on the build it just made:
   the site gates, the address guard against the live public repo, the publish target (V1 to V3), and
   the Pages source. A site that cannot be published stops here, blocked, with the cause. **A dev repo
   that serves a GitHub Pages site itself** (one repo doing both jobs) blocks here as
   `publish/serves-dev-repo`: it is the person's to resolve, never filed. Tell them the way out: create
   a new private repo for the source, move the dev items there, and keep only the published site in the
   existing public repo, which already serves it; then run adopt again. Adopt never archives a workflow
   that publishes the dev repo's own Pages.
3. **Publish**, through `deploy.py` (the same build, gates, address guard, privacy review, push and
   verification as `/site-studio:publish`). A review is bound to the build's digest and is made by an
   agent that opens the files, which a script cannot do. So when `deploy.py` says no review covers the
   build, `apply` does exactly two things before it gives up, and says which in the output and in
   `HANDOFF.md`:
   - **A review carries over when the digest is unchanged.** It looks for a row for the SAME digest in
     `.site-studio/reviews.jsonl` on every earlier adopt branch (`site-studio/adopt-*`), on `HEAD` and on
     `origin/main`. A row for any other build never carries, and a BLOCKED review that carries stops
     the run. This is why the stop's next step is "review a checkout of that branch, keep it, run `apply`
     again with another `--date`".
   - **Parity EQUAL stands in for the FIRST review, only when every automated privacy scan passes on the
     exact built tree:** the shape scan (phones, street addresses, emails), image metadata (EXIF and
     GPS) and unreferenced files, all `check_site`'s own. The row is recorded as `parity-EQUAL+scans`
     with a summary of the scans. It is never silent: the output says "NO AGENT REVIEW" and that
     nothing was opened by an agent, and `HANDOFF.md` carries the same line. Say that plainly when it
     happens, and offer `/site-studio:review` for a real one.
   **Only parity EQUAL qualifies.** An ACCEPTED or MARKUP-ONLY verdict always needs the normal review,
   and so does any scan finding, a PDF the scan could not read, or a scan that looked at nothing. Then
   `apply` stops here: the stop names the scan finding or the verdict and `/site-studio:review`, and
   says nothing was published. Relay the line as printed (cause `ss-adopt/apply/no-review`), and do not
   suggest a way around the review.
4. **Wait for Pages** to report that publish built.
5. **Archive the old builder** (its code, the modules it loads, its deploy script, a `package.json`
   only it uses, and every CI workflow that publishes) under `archive/`, check that the tree after the
   move still builds the published digest, make **one** commit, and push it to the dev repo's `main`.

Configuration the conversion changes, for you to show as a diff:

- **`CLAUDE.md`:** every section about the person is kept. The engine sections are replaced by
  one pointer to the plugin, and this line, exactly:

  `If /site-studio commands are unknown, this session does not have the plugin (cloud sessions do not install repo-declared plugins); open the repo on your own computer.`

  After that, any standing rules the person marked `rule` are appended under
  `## Standing rules carried by adopt`, each under a `### From <file>` line.

- **`.gitignore`:** gains `.claude/worktrees/` (the desktop app keeps session worktrees inside
  the repo), `site/dist/` and `.site-studio/review/` if they are missing.
- **`.claude/settings.json`:** gains this plugin's registration and ask rules, and keeps every
  rule the person added. For a hook that pointed at a file being moved to the archive:
  - it is **removed** when the plugin's own hook does the same job;
  - it is **rewritten** to `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/<script>"` when the plugin has a
    counterpart script. Its old arguments are kept;
  - otherwise **the file it needs is kept**.

  Every change is listed. Tell the person plainly: whether `${CLAUDE_PLUGIN_ROOT}` is defined for
  a hook in a project's own settings file is not yet known, so a rewritten hook should be read and
  tried before they rely on it. Apply refuses to finish if any hook still names a file that no
  longer exists.
- **`site/site.json`:** gains `schema`, `engine` and `resume`; every other key is kept, except the
  mechanical fixes listed under "Problems in what adopt would write", each of which is a line of
  the commit. A meta-refresh page it converted becomes a `redirects` entry, and the kind the person
  confirmed (`hub` or `custom`) becomes `siteKind`. It is written at the lowest schema the converted
  site needs (up to 4), and the inventory says when it is more than 1 and why.
- **`.site-studio/adopt-parity.json`:** the parity verdict (`EQUAL`, `MARKUP-ONLY`, `ACCEPTED`,
  `DIFFERENT`, `UNVERIFIED` or `NOT APPLICABLE`), the basis commit and each difference, with no date.
  `/site-studio:publish` reads it (see "7. After apply: the publish gate").
- **`HANDOFF.md`:** the run adds its own entry (what moved, what is kept, and, for a stop, what
  stopped it). Do not edit `HANDOFF.md` afterwards, because that would be a second commit.

## 5. The two outcomes

Read the last lines of `apply` to the person.

- **completed.** Site-studio has published the converted site, the old builder is archived, and the
  dev repo's `main` carries the result. Tell the person, in these words or close to them: **pushing
  to this repo no longer publishes anything; publishing is `/site-studio:publish`.** The branch
  `site-studio/adopt-<date>` is the run's own commit; read it with `git show --stat site-studio/adopt-<date>`
  (never `git checkout` or `git switch` to it).
- **blocked** (exit code `4`). The line begins `adopt blocked at step N of 5`, names the cause, and says
  whether the public repo has the new site. `main` is unchanged and **the person's old builder is still
  their publisher**. The conversion sits on the branch `site-studio/adopt-<date>` for them to read. To
  run `apply` again, the branch must be gone first (`git branch -D site-studio/adopt-<date>`); show
  the person that command and wait for their yes. A blocked `apply` also names any plugin cause as a
  pending report (next section).
  - **The one stop after the site is live:** step 5's push can be refused (a token without the
    `workflow` scope, or a protected `main`). The public repo then has the new site and the visitor
    sees no change, but the old publisher would run again on the next push. So this is **blocked**,
    on a cause only the person can resolve: the line names the one command left (`gh auth refresh -s
    workflow`, then the `git push` it prints). Say both: the site is live, and the old builder will
    publish again until that push is made.

Reverting a completed adopt is the dev repo's own history: nothing was deleted, and every moved
file is under `archive/`.

## 6. Blockers become reports

When `apply` or `remeasure` ends blocked, every plugin cause is written as a `pending` row in
`.site-studio/adopt-reports.json` (one row per cause id, never per occurrence), and the run prints
`blocked: N cause(s); run adopt.py report to read them`. A cause only the person can resolve (a Pages
source set to a workflow, say) or one in the person's environment is printed with its fix and never
filed.

- `adopt.py report` prints every pending report exactly as it would be filed: a cause id, a count and
  the versions, with no path, file name, class, text or address from the person's site. **Print them
  and show the person first.**
- `adopt.py report --file` files them as public issues on the marketplace, after checking the open
  and closed issues for the same cause, and commits only the reports record. It is a publish to the
  guard, so it asks the person; **ask once, then run it only on their yes.**
- `adopt.py report --decline` records every pending cause as declined; a declined cause is offered
  again only for a newer plugin version.

After the plugin is updated, a session start line says "site-studio <v> may resolve N adopt blockers:
run adopt again". Then run `adopt.py remeasure` (below), or `apply` again if the run never completed.

## 7. After apply: the publish gate

**While parity is not EQUAL, MARKUP-ONLY or ACCEPTED, the person's own builder stays the publisher,
and `/site-studio:publish` refuses to replace it.** `deploy.py` reads `.site-studio/adopt-parity.json`
from `HEAD`, in a dry run and before a confirmed publish, and when its verdict is anything else it
stops, with a sentence that is true of that verdict and names a way out that works:

- **DIFFERENT**: site-studio's build differs from what the person's builder publishes (`<n>` differences, the
  first named), and their builder stays their publisher. Way out: `adopt.py remeasure`, or `--accept` once
  they have been shown the differences.
- **NOT APPLICABLE**: adopt found no builder of the person's own, so nothing was measured, and publishing
  would replace what their site publishes today, unmeasured. Way out: `adopt.py remeasure --accept` if they
  accept that; if a builder of theirs should be compared, put it in the repo and run `adopt.py remeasure`.
- **UNVERIFIED**: adopt could not measure: there is no node on this computer, the person's builder failed,
  or site-studio's build refused the converted tree (`adopt.py remeasure` prints which). So it is not known
  whether the two differ. `--accept` refuses UNVERIFIED, because nothing was measured to show them. Way out:
  install node, fix the builder, or settle what site-studio's build refuses, then run `adopt.py remeasure` again.
  Without node, an adopted site with a builder cannot be published by site-studio.
- **MARKUP-ONLY**: the pages differ only in markup a visitor does not see. It passes. For a class, `data-*`
  or added `id` difference, each publish checks again that no stylesheet or script now names what differs.
  Two kinds of difference are judged invisible once, at measure time, and are not re-checked at publish:
  - whitespace a browser collapses between block elements;
  - a `noopener` or `noreferrer` `rel` on a link that opens in the same window.

An unreadable record stops it too, naming the file. No record (a site made by setup, or adopted by an older site-studio) is the old
behaviour: nothing is read. Tell the person plainly that publishing here is held by design, not broken.

`adopt.py remeasure` is how it is released, and how a blocked run is retried after an upgrade: it
converts again, accounts for every file again and measures again against the plugin build of `HEAD`,
prints each difference (by cause, as `parity` does), rewrites the record and commits that one file.
`adopt.py remeasure --accept` records `ACCEPTED`, and **only after the person has just been shown the
differences and said yes**: it prints the differences it is accepting (one line per cause) **before**
it writes the record, so what is accepted is in front of them in the same run; it never accepts
UNVERIFIED. For a site with no local builder at all, `--accept` means "site-studio's build replaces my
site, unmeasured". It refuses in a cloud session, as adopt does. The gate runs only the one builder
file adopt classified: any other step of the person's pipeline (a CI workflow, a hosting build) is not
run, and the inventory says so.

## The guard, and when `apply` cannot ask

`adopt.py apply` (without `--dry-run`) and `adopt.py report --file` are publishes to the plugin's
guard, which decides from the session's permission mode, as it does for `deploy.py --confirm`:

| session | the guard |
|---|---|
| permission mode `default`, `acceptEdits`, `plan` | **asks** the person; their yes is the yes to the whole run |
| `auto` | **asks**; that the ask reaches the person in `auto` is UNVERIFIED |
| `bypassPermissions`, `dontAsk`, any other mode, or none | **denies**: this session is set not to ask |
| a cloud session | **denies**: adopt runs only on the person's own computer |

`apply --dry-run`, `adopt.py report` (print) and `--decline` are never held. Never try to get past a
denial, and never run the steps of `apply` yourself another way.

**When the guard denies `apply` (a scheduled run, `claude -p`, a session set not to ask), write the
hand-over yourself, because the script never ran.** Do this, in order:

1. Run `adopt.py apply --dry-run` and read it to the person. Note its verdict line and whether a real
   `apply` would stop blocked, and why.
2. Add this entry to the end of `HANDOFF.md`, in plain words, filling in what you read and nothing
   else:

   ```
   ### Adopt: waiting for you (<date>)

   - Adopt measured this site (parity: <verdict>) but did not run `adopt.py apply`: it publishes the
     converted site and retires the old builder, and this session cannot ask you first
     (permission mode: <mode>).
   - Nothing was published or pushed. Your old builder is still your publisher.
   - <If the dry run said a real apply would stop: "A real apply would stop at <step>: <why>. Fix
     that first.">
   - Next: on your own computer, in a session that asks (default or acceptEdits), type
     /site-studio:adopt and run `adopt.py apply`.
   ```
3. Commit `HANDOFF.md` alone, by its explicit path. Do not push it; `apply` includes that commit and
   lists it.
4. Tell the person the same thing in two sentences: what stopped, and the one next action. If
   `adopt.py report` printed pending reports, say they stay pending until a session that asks runs
   `adopt.py report --file`.
