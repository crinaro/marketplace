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
steps below. Never edit that file by hand. From 0.10.0 it is written at plan schema 6 only when it holds an answer 0.10.0 adds
(`covered`, `proof --as-is`, or one of the three settings below). A copy of the plugin older than 0.10.0 reading such a plan refuses it, with
"update site-studio if the plan came from a newer one, or delete .site-studio/adopt-plan.json" or "unknown key 'settings'; edit or delete
.site-studio/adopt-plan.json". **Tell the person to update site-studio on that computer, never to delete the plan**: deleting it loses every answer.

## Preconditions

Run `adopt.py check` first. It prints `adopt ok: <origin/main or HEAD> <sha> can be converted`, or
refuses with the reason. **It exits `1` in two cases, and says which in one fixed sentence**, after printing every problem with its fix, so a red `check` is a list to work through, not a failure to report:

- A `you decide` problem exists. The last line reads (`<basis>` is `origin/main` or `HEAD`):

  ```
  adopt check: <basis> <sha> cannot be converted until the N problem(s) marked `you decide` are settled
  ```

- The tree can be converted, a `parity` has been measured, and the publish checks (next section) refuse the converted site:

  ```
  adopt check: <basis> <sha> can be converted, but the publish would refuse it: N finding(s)
  ```

  The same line says "apply would refuse it: N refusal(s)" (alone, or after the publish's count) when `apply` itself would refuse before
  writing anything: a covered or rule unit of a file that stays, an archive address already taken, a path with a tab or newline, a branch
  that already exists, no git identity, an unreadable reports record. Each is listed under "apply would refuse" with its fix, by `check`
  and again after `parity`'s verdict; this can be said before any `parity` too.

  Read the list printed before it to the person, and do not call the site ready. Before any `parity` the list is for the
  plugin's default look, says so ("before parity: measured with the plugin's own markup; `adopt.py parity` gives the final
  list"), and never changes the exit code.

Do not work around a refusal. Before that line it may print, once, which
tree adopt will convert and whether parity can run (the **parity basis**, below), and every problem
it found in what it would write, all at once, each marked `apply fixes this` or `you decide`.

- On the person's own computer: the desktop app or a terminal. In a cloud session, stop and say
  adopt runs on their own computer.
- The dev repo has no uncommitted changes. Untracked `.claude/worktrees/` and adopt's own plan
  file do not count.
- **`apply` needs `gh`, logged in, and the network:** it reads the public repo to check that a
  publish would be accepted, then publishes. `check`, `inventory` and `parity` need neither (beyond the fetch
  below); `adopt.py check --online` and `apply --dry-run` read the public repo through `gh` and the network too (read
  only: nothing is published). A read that cannot be answered (no `gh`, no network) is printed as `NOT CHECKED`
  (a `not checked` row in the list), never as a pass.
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
**Inventory has no copy of the old pages**, so a wrap it cannot check against an old page (a bare token directly
before a `{{#page:...}}` section, say) is listed under "page sections that wait on parity" (`sectionsWaitingOnParity`
in `--json`), never as "adopt will write". `adopt.py parity` writes the wrap only where the old page holds exactly that
anchor, and otherwise leaves the token listed. Read that list to the person as not yet decided.

Record each decision as the person makes it:

- **DUPLICATE:** archived (moved under `archive/`, never deleted) only after the person confirms:
  `adopt.py confirm <path>`. To keep it:
  `adopt.py confirm <path> --keep`. Any residual units are shown first.
- **PARTIAL:** kept by default: with no decision at all, `apply` keeps the file and lists it as "kept
  by default (no decision)". Go through every residual unit the inventory lists, by its id:
  `adopt.py unit <path> <unit-id> person-data --kind context|voice|rule [--name <slug>]` ("person
  data, move it"), `adopt.py unit <path> <unit-id> rule` ("a standing rule of mine, keep it for
  every agent": see **Standing rules** below), `adopt.py unit <path> <unit-id> keep` ("behaviour
  the plugin lacks, keep it") or, from 0.10.0, `adopt.py unit <path> <unit-id> covered` ("the plugin covers this; drop it").
  `adopt.py unit <path> --rest covered` answers every unit not answered yet, printing each one's first line **before** it
  stores them: read those lines to the person first. For a PARTIAL script that has no units to go through,
  `adopt.py confirm <path> --covered` is the same answer for the whole file (never for a local builder file, which is dropped
  only after parity says the site is the same). `covered` is refused on a unit of a file that stays (a drop travels only with
  the file it is in); the file is archived, never deleted, so the words stay in `archive/`, and the commit lists each covered
  unit by file and first line under "Covered by the plugin (dropped)". The file becomes removable only when every unit is
  decided and none is `keep`, or when parity (step 3) passes.
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

**Strays the build only warns about.** The build and preview print a named warning for a `.md` other than `index.md` or a sub-folder other than `media/` or `_*` in a piece folder, and for a piece front matter key that is neither built in nor in the portfolio's `meta`/`cardMeta`; the published bytes do not change. Where nothing has been converted yet, `check` lists each as a problem with its fix and refuses (`you decide`), so `adopt ok` is not said over a page that would go unpublished. Read each fix to the person. From 0.5.0 a piece key some view or setting of the plugin reads is never listed as an unused stray: a key the converted tree reads (a pending conversion counts before parity runs) is not listed at all, and a key another view reads that this portfolio does not use (`pin` under a grid) is a **note**, not a decision, naming that view, with both ways out (list it in `meta` to print it as it is, or set the view) and what parity knows about the page. Read the note; never offer "remove" for it.

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
decides whether to accept it with `adopt.py parity --accept`, after reading what `parity` listed and
opening the pictures `--keep` made (step 3).

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
`roles`, `map` and `showcase` views are modelled at schema 4 and are kept, not removed; from 0.5.0 a
template's `view: movement` is not removed either: `viewNames` renames it to the steps view, `view: steps`,
and parity measures that index like any conversion; until the person
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
plugin still does not build (a block whose data shape is the person's own, an index no view or named view can print) is not
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

**Files adopt could not settle (0.9.0).** A file adopt could not test stays **undisposed**, and an undisposed file blocks
`apply`. Each one now says which it was, in these words: `not tried: the bound of N runs (and N more in groups) was
reached`, `not tried: the time bound was reached`, `tried, and your builder timed out without it`, `not tested: your
builder does not run on the unchanged tree`, or `not tested: your builder differs from itself on the unchanged tree`.
Read the reason to the person: the first two mean adopt ran out of runs or time, the last three mean their own builder
could not answer.

- **Groups, and what they cost in time.** After its first pass, `parity` tries what is left in groups, and then the files
  the person kept, each with a bound of its own (32 more runs or 120 seconds). A site that 0.8.0 could not settle, or where
  the person keeps files, can make `parity` take **up to four minutes longer** (six if their builder hangs), and it prints
  nothing while it works. **Run `parity` in the background, or with the longest timeout the tool allows**, and tell
  the person it may take several minutes. A site that settled before takes no longer.
- **`adopt.py file <path or folder> keep`** works for any tracked file, and `keep` and `archive` take a whole folder (with
  or without the `/`; one choice is recorded for each file below it, and the count is printed). `draft` and `engine` take
  one file. **`adopt.py file <path or folder> --clear`** forgets the choice, and a path with none is refused naming the
  choices there are. A file added later is asked about, and a file that changed on a moved basis loses its choice by name.
- **A choice newer than `parity` is refused** (a file's, and from the 0.9.0 review any setting, kind, folder or conversion:
  `adopt.py setting`, `kind`, `folder` and `convert` print the same line). `check` names them, and `apply` (a dry run
  too) refuses: "your choice for N file(s) is newer than the last `adopt.py parity` ... run `adopt.py parity` again, which
  measures it". Run `parity` again and then `apply`.
- **The undisposed block, before `apply`.** `check` and `inventory` (and `inventory --json`, under `undisposed`) and
  `apply --dry-run` print "N file(s) are undisposed and will block apply:", one line per reason with its count and every
  file, and the way out: `adopt.py file <path or folder> keep`, then `adopt.py parity`. Read it to the person before
  anything else; do not wait for `apply` to stop. With no `parity` run on this basis it says "not measured yet: run
  `adopt.py parity`".
- **`decisions/` and `BRAND.md`** are the plugin's own files in the dev repo. Adopt keeps them unless the old builder is shown
  to use them, and never counts them against the site. A nested `README` or licence file is tried like any other, and
  one it could not test is archived, with the reason "not tried".
- **What a kept file can and cannot do.** `keep` leaves the file at its path in the dev repo, in the same private repository.
  It does not hide a loss: a file the old builder uses that the plugin cannot hold stays **no landing spot** and still blocks.
  If keeping a file would make the plugin's build publish it where the old site had nothing, the file is undisposed:
  "keeping it would publish it at `<address>`, where your old site has nothing", with two ways out, `archive` it or
  `--clear`. It is no way around a file the build refuses. And a file that is kept and could not be tested stays where it is,
  "not measured", and blocks nothing; a visitor-facing loss still shows in parity's comparison of every page.

**Measured settings.** A conversion that picks one value from a short list is a *setting*. adopt
measures these, in this order: the site's `look`; whether the home page's featured pieces come from each
piece's `featured: true` (`featuredFrom`); a portfolio's piece order (`sort.<portfolio>`); a nav without
a Home item (`nav.home`); resume headings as written (`resume.headings`) and the resume's role cards
(`resume.layout`); whether site.json's `work` keys apply to every portfolio (`workKeys`); card values
without their labels (`cardLabels`); a number on each card (`cardNumber`) and how it prints
(`cardNumberFormat`: `padded`, `plain` or `order`); from 0.5.0, per portfolio, the picture a card shows
(`cardImage.<portfolio>`: `photo`, or `cover` on a roles card), the card picture's own alt text
(`cardAlt.<portfolio>`), a kicker line from one of the pieces' own keys (`cardKicker.<portfolio>`), an
outbound link on each piece page (`pieceLink.<portfolio>`) and the teaser paragraph under a piece's title
(`pieceTeaser.<portfolio>`); a back link above each piece title, one text per portfolio from 0.6.0
(`backLink.<portfolio>`; the old site-wide `backLink` is gone); a
menu link that goes straight to a one-piece portfolio (`menuLinks.<portfolio>`) and what that
portfolio's index is (`onePieceIndex.<portfolio>`: a redirect page, or the listing it was); the
heading level inside a carousel slide (`blocks.headingLevel`); whether a lone reference card sits in the
reference grid (`blocks.loneReferenceGrid`); the home page's `<title>` form
(`titleForm`), whether its intro holds the whole body or its first block (`introScope`) and the order of
its parts (`partOrder`); and a portfolio's index view (`view.<portfolio>`: from 0.6.0 also `roles`,
`map`, `steps` or `showcase`, offered by the keys the pieces carry).

From 0.6.0 adopt also measures, each a schema-6 key (`${CLAUDE_PLUGIN_ROOT}/reference/content-model.md`): the featured
shelf printed as each portfolio's index, group by group (`featuredView`: `flat` or `grouped`); the
menu's first item as the site title (`nav.home`: `"title"`) and the `https:` and `mailto:` links every
old menu holds after the built-in items (`nav.extra`); the text between a page's title and the site
title (`titleSeparator`); per portfolio, a count on each group heading with the word after it
(`groupCount.<portfolio>`, the words written as `labels.counts`), a card picture's alt as the piece's
title (`cardAlt.<portfolio>`: `"title"`) and a piece's dated roles (`pieceRoles.<portfolio>`); the level
a heading in a page's body is written at (`blocks.headings`); where each media folder is published
(`mediaPaths.<folder>`, for `references`, `home` and `about`), and a size copy in another format
(`sizeCopies`); and the old site's own pages served as it wrote them (`carried`, below).

From 0.8.0 adopt also measures, each a schema-8 key: the menu's own words for the about and resume pages, read
from the old menu (`nav.labels.about`, `nav.labels.resume`; written only when the old word is not the plugin's
`About` or `Resume`), measured on every page's menu; and whether the resume page's `<title>` leads with that menu
word rather than the resume's own title (`resume.titleForm`: `"page"`), measured on the resume page.

From 0.10.0 adopt also settles three things the publish checks would otherwise refuse, each a schema-10 key (a copy of the plugin older
than 0.10.0 says "update site-studio" on a site that holds one). **Two of them are read from the old site, never measured**, and the row
says so ("read from your old pages", "read from your old sitemap, which parity cannot compare"):

- **`images.sizes`** (`as-written` or `held`). When the old pages' pictures carry no `width` and `height` and the converted pages' still do,
  adopt writes **`as-written`** by itself: no byte of any page changes (a site that measured EQUAL stays EQUAL) and the publish check stops
  asking for sizes on the whole site, hand-written pages included. Its cost, which you say: pages shift while their pictures load, as they
  did, and a picture added later without a size is counted in a note, not refused. **`held` is only ever the person's choice**
  (`adopt.py setting images.sizes held`; `--clear` forgets it). It adds `width` and `height` to the pictures of generated pages, and links
  one more file, `site-studio/held.css`, that keeps the layout. Its costs, said when it is chosen: one more file on pages with pictures; a visitor
  whose browser is older than about 2022 (an old iPhone is the likely case), or for whom that file does not load, gets the plain way;
  `parity` is expected to read DIFFERENT (the added file, its link and the `data-` attribute), the person accepts after `parity --keep`'s pictures, and a privacy review is needed,
  with the `apply` after it on the same UTC day. It completes only the look adopt derived; **a look the person wrote is never edited**,
  and **pictures in hand-written pages, and any the build did not size, stay as they are and are counted in a note**, never refused; adopt
  never adds a `srcset`. A picture `held` sized must carry its true size. `parity` does not see image sizes, so
  when the person's own look adds them it says "parity does not see image sizes: look at the pictures (`adopt.py parity --keep`)".
- **`sitemap`** (`indexable`; `adopt.py setting sitemap none` declines). Adopt writes it when the converted site has a page that tells search
  to leave it out (a `noindex` robots meta, or a meta refresh) and the old build's own `sitemap.xml` lists none of them, or there was none:
  the new `sitemap.xml` then leaves those pages out, and the publish check no longer refuses a `noindex` page that is carried or whose
  source is `site/src/<same path>`; any other `noindex` page is refused as before. When the old sitemap listed them adopt leaves the
  sitemap as it was and says so.
- **`blankMeta.<portfolio>`** (`omit`; `adopt.py setting blankMeta.work false` declines). Offered per portfolio where a piece holds a front
  matter line with no value (`year:`) for a key the portfolio lists, and judged like any setting by parity: a blank value then prints no row
  on the piece page and no empty separator on a card. `false` and `0` are values, not blanks.

A published site is never changed by any of the three unless its owner sets the key.

- **A per-portfolio value adopt cannot write.** A setting that lives in a portfolio's `page.md` (a sort order, say) has
  no place to go when a portfolio other than `work` has no `content/<portfolio>/page.md`. The row then reads `not
  written: needs content/<p>/page.md with <key>: <value>; the default stays`, never "no candidate changes what a
  visitor sees"; create the page.md with that key, or leave it. For `work`, a key `site.json`'s `work` object cannot
  hold (`sort`, say) is written into a new `content/work/page.md` holding only that key when `work` has none.
- **`workKeys: all`** copies the work portfolio's `meta` and `cardMeta` keys to the other portfolios, except a key the
  build already shows there itself (`role` under the steps view or `pieceRoles`); the notes name each key it left out.
- **The candidates file.** The file `.site-studio/look-candidates.json` never holds one instance's
  value as fixed text: where the old instances differ, the part carries the slot their own values equal, or the flag
  `{{?differs: a | b}}`. The build refuses the flag by part name, so a copy of it cannot reach a page.
- **`reads` entries (0.8.0).** `adopt.py parity` also proposes measured `reads` entries into that file, for the three
  picture places, the kicker line (`kicker.wrap.text`) and `@kind` with the `kind-*` words, each only when it leaves
  strictly fewer visible differences than the build without it. A line reads `reads.<target>: proposed -- N fewer
  visible difference(s) on M page(s); copy it into site/looks/local.json`; a target adopt did not try says why
  (`not proposed: build budget`, at most nine builds a run). **Adopt writes none of it into `site/looks/local.json`:
  the person copies an entry and commits it** (see the `look` skill). Where `cardImage` is a tie, the row names the
  picture entries that settle it.
- **An entry of the person's that the build refuses without** (a `reads` entry whose removal makes the build refuse,
  such as the roles view's `employer`) is measured on every page it renders on, and its row says "the build refuses
  without it" in place of "derive has no reading of it".
- **A count's word.** Which word a group's count prints with is the person's entry in
  `labels.counts`, never a rule of the plugin (owner decision 4). Where the words cannot be written
  (the portfolio's groups are listed in its `page.md`, and the groups use different words), the count
  prints alone, and adopt lists that page as an ACCEPT candidate: tell the person so.
- **`carried`** offers the pages only the old build has (the 404 page first), byte for byte, and a
  file such as a script only when a page of the new site loads it. It never offers `CNAME`,
  `robots.txt`, `sitemap.xml` or `.nojekyll`, a page whose addresses do not fit the path the plugin's
  build is served at (its reason says to carry it after cutover), or a page only an uncommitted file
  makes. A carried page does not change when the site does (a new menu item will not appear on it);
  every build says so, and the first build after the site's address changes stops until its addresses
  are corrected. Tell the person both before they keep one. To keep a page that differs as written:
  `adopt.py setting carried <path>`.

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
- **`blocks.unlistedVideos`** (absent, the default, or `true`; schema 9) is offered only where an old page's player
  address carries a private code (an unlisted Vimeo link, `vimeo.com/<id>/<code>`) and the converted tree links a Vimeo
  video, and is judged together with `blocks.videoEmbed`. **Say what it publishes before `apply`'s yes:** with `true` the
  video's private code goes into the page, where any visitor can read it. Under a `:::videos` row or a gallery video the
  page's own link already shows it; on a line that holds only the link it is published for the first time. Without it
  the player shows Vimeo's own notice instead of the video, and every build names each link it left the code out of.
  The person's word: `adopt.py setting blocks.unlistedVideos true` or `false` (`--clear` forgets it).
- **`referenceLayout`** is the suggested reference layout. It has its own section below, because every word of it is
  read to the person first.
- Each is `apply fixes this` when parity measures no visitor-visible difference, and otherwise `you
  decide`, with the difference named. **Without `node` nothing is measured**: every setting reads `you
  decide: not measured`, and none is filled in with a default; the `look` in particular is never
  guessed. The person may choose a value (`adopt.py setting <name> <value>`; a chosen value is kept and
  never measured, so say that) or forget the choice so the next parity measures it again
  (`adopt.py setting <name> --clear`).

**The suggested reference layout (0.9.0).** For each reference the site holds (`content/references/<name>/reference.json`),
adopt suggests three plain keys, so the facts sit in their own keys before the site's look changes: `project` (which
piece it is for), `type` (what it is, such as `Post` or `Film`) and `channel` (where its audience saw it, such as
`Instagram`). It is part of what `apply` writes **unless the person says no**, and nothing is written they have not
been shown. Nothing a visitor sees changes: a key prints only where the site's look places its slot, and adopt writes
the keys only where parity measures that no page gets worse (it usually says "changes no page"). A hub or custom site
holds no references, so it is offered nothing.

1. `check`, `inventory`, `parity` and `apply --dry-run` each print one block headed `suggested reference layout`. **Read
   every word in it to the person before `apply`'s yes:** every sure row of each key, every reference named (nothing is
   cut short), each key marked `written` or `not written` with why, **every distinct `type` and `channel` word, with its
   count** (`every word: Post (3); Video (1)`), each `you decide` row with the line to add by hand, and each reference adopt
   could not read (`not read, nothing suggested or written`: a byte order mark, a member named twice, no plain `title`).
   A `you decide` row is never written, and none blocks `apply`. The words come from the address (`instagram.com/p/...`
   is an Instagram post) and from the reference's own `kind`, and a link to a file host such as Vimeo or Google Drive
   gets no `channel`. **Any doubt is the person's, never sure:** the address and the `kind` disagree on the type, `site`
   or `kind` names another platform, one video is shown by two pieces (in either address form), an address hides where
   it leads (a backslash, a user part, a share or redirect link), or the site's pages say a language other than English
   (the `type` words are English).
2. **Ask before `parity`, or run `parity` again after.** Yes needs no command. No: `adopt.py setting referenceLayout none`.
   Some: `adopt.py setting referenceLayout project,channel` (any of `project`, `type`, `channel`, with commas). `all` is
   back to everything and `--clear` forgets the choice, as for any setting. What the person says is kept and never
   measured away, but it is measured: **a choice made after `parity` (this one or any setting, kind, folder or conversion)
   makes `apply` refuse until `parity` runs again**, and the block says "not written yet: your choice is newer than the
   last `adopt.py parity`". Saying no to keys the old pages printed can make parity DIFFERENT: read what it names.
3. **The cost, said before the yes:** a site with references adopted this way is written at **schema 9**, which an
   older copy of site-studio on another computer refuses ("update site-studio"). With `none`, or no references,
   adopt does not raise the site for this.
4. **It waits while the person's own builder publishes.** Under a parity that is not EQUAL, MARKUP-ONLY or ACCEPTED the
   keys are not written (their builder may refuse a key it does not know); the block says "written when site-studio
   takes over". A layout the person chose also waits while parity is DIFFERENT. Until `parity` has run the block says
   "not measured yet" (with no `node` it never will), and only a layout the person chose is written. When a page would
   get worse the block says "not written: `<page>` gets worse with the suggested layout", and `adopt.py setting
   referenceLayout <keys>` writes some of it anyway, which is the person's call.
5. A key a reference already holds is never changed, a blank one included, so **a blank key keeps one reference out**:
   the person writes `"channel": ""` in that reference's `reference.json`. Nothing is written for a reference or piece
   the file accounting archives, or outside the site's own `references` list when it has one.
6. **The closing list is text to copy.** The block includes the `"references"` text for `site/site.json` that would
   close the lists to the words in use. Adopt never writes them: a closed list refuses the next new word, so say that
   before the person copies it.
7. `apply`'s summary repeats the words it wrote.

**The look.** When the plugin's own markup does not match the old site's, adopt derives a look from the
old builder's own pages and the converted content (`site/looks/derived.json`, the same work as
`/site-studio:look derive`). From 0.6.0 the look is **kept per construct**, never refused whole: it
answers only for what it loses that the plugin's own look shows. A construct that loses content is
dropped (listed `look: <construct> dropped: loses content`) and the rest of the look is kept. What
neither look prints is listed once, "the plugin's build does not print: <page>, <what>", and becomes an
ACCEPT candidate. The look's row ends with how many constructs mapped and the share of the old pages'
class names that are on the new pages, under the derived look and under the plugin's ("62% against
9%"). A construct it cannot map keeps the plugin's own markup and is reported as `look/unmapped/<construct>`
or `look/ambiguous/<construct>`, with the reason and the first page that held it. **Measured on the plugin's template fixture, this version's derive maps
every construct the fixture uses**, and the only visible difference left is the page descriptions a
search result shows (named for the person to accept). What a real site needs is not known until adopt
runs on it; say that plainly. A construct derive cannot map is a limit of this version, not something
the person did.

**The person's own look is the normal way to work (0.7.0).** A construct they write in `site/looks/local.json`
(switched on by `lookLocal`), or edit in `derived.json`, is theirs: it is measured as its own row, derive never
overwrites it, and when parity prints "look: N of your look entries reproduce the old pages exactly", the `look`
skill's section "Offer an addition back" is how to draft a suggestion from it; filing one is step 6 below.

**The publish checks (0.10.0): what the publish would refuse is said before `apply`.** `check`, `inventory`, `parity`,
`apply --dry-run` and `apply` (its step 2) ask the same publish checks of the same converted tree (what `apply` would commit under
`site/` and `content/`), and print one list: the build's refusals, the resume PDF's proof, the thirteen families of the site gate,
a MARKUP-ONLY record that no longer holds, a private path in the output, two output names that differ only in case. It reads
`publish checks: N finding(s) would refuse the publish (nothing is published)`, then one group per finding form, most pages
first, each naming **who can fix it**:

- **adopt fixes** (`adopt fixes N`): `apply` or a setting does it (the line names it, such as `adopt.py setting images.sizes ...`).
- **the site**: an edit in `content/` or `site/`, named with the file where the page has a source. Tell the person; it is theirs.
- **you**: an answer, an account, a new PDF or a file only they can make (the resume PDF's proof is this: see below).
- **the plugin**: nothing a site can do; `adopt.py report` files it (step 6). A finding that is the site's, yours or adopt's is
  never recorded as a plugin cause and is never offered for filing.

Each group lists five pages and "and N more"; `adopt.py check --all` and `inventory --json` (`publish`, every finding) list all.
`parity --json` carries `publish` too. **Read the list to the person as it is printed.** Three things to say plainly:

- **Before the first `parity`** the list is "measured with the plugin's own markup": the findings of a family the look decides
  (`media`, `performance`, `head`, `reachable`) are only counted, never listed page by page, because the look `parity` chooses
  settles them. Do not ask the person to fix those yet.
- **A check that did not run is a row, never a pass:** `not checked: <what>: <why> (<how to run it>)`. After `check`, `inventory`
  and `parity` the list ends with "2 checks not asked here: the staged tree against the public repo, and the public repo, its Pages
  settings and its published addresses (`adopt.py check --online`)".
- **`adopt.py check --online`** (read only; needs `gh`, logged in, and the network) asks those two as well, warns of a `core.hooksPath`
  or `commit.gpgsign` of the person's git and of a `gh` token that lists scopes without `workflow`, and prints "can still stop apply"
  with what no check can know before `apply` (the person's answer at the publish ask; no privacy review covering this build; a
  workflow, `main` or the public repo that moved; Pages not building; the push refused; a hook that refuses the commit; a file or choice
  changed after the last `parity`).

**The resume PDF's proof (0.10.0).** The build refuses a resume PDF with no proof beside it (`<pdf>.json`), and a site adopted from
elsewhere has none. `adopt.py proof` prints where it stands, and nothing in it writes the proof: `apply` does, in its one commit.

- **The proof is measured both ways:** 95% of the resume page's words must be in the PDF, and 95% of the PDF's own words on the resume
  page (its whole printed text), so a PDF that says more than the page ("the PDF holds words the resume page does not: ...") is not
  proved; a resume page under 20 words is too short to judge and is never proved. Both go to the person's answers below.
- **The plugin's reader finds 95% or more of the resume page's words in the existing PDF, and the PDF says no more:** `check` says "your resume PDF <pdf> was
  checked against the resume page: N% of its words found; `apply` writes its proof, and the PDF does not change". Nothing to do.
- **It finds less, or cannot read it:** `check` lists "the resume PDF <pdf> has no proof beside it (the plugin's reader found N% ...,
  and 95% are needed; it did not find: ...; this can be the reader's fault: joined letters, hyphens at line ends, languages written
  without spaces)", and the answers are the person's: **`adopt.py proof --as-is`** if they say the PDF is right, **`adopt.py proof
  --print`** to print a new one, or update the PDF or the resume page. Ask which; never choose for them.
- **`proof --as-is`** stores the person's word, bound to the PDF and to the resume as they are (void when either changes: "you vouched
  for this PDF against an older resume ..., vouch again with `adopt.py proof --as-is`, or update the PDF"). `apply` writes the proof and its commit says the person
  vouched for the PDF. The gate still lists the PDF as not read, so **the privacy review must open it** (`/site-studio:review`), and
  the `apply` that follows that review must run **before 00:00 UTC of the review's day**, or the review is made again (the stop
  prints "run `adopt.py apply` again before 00:00 UTC (HH:MM here), or the review has to be made again"). `--as-is` does not answer
  the PDF's hidden details (an author, an unknown creator program, a title that is no page's): those findings stand.
- **`proof --print`** prints a new PDF from the converted resume page with Chrome and copies only the PDF to its path; the visitor
  gets that PDF, a different file, the next time either builder publishes. It refuses unless this checkout's `HEAD` is the parity
  basis, unless a `parity` has run, and while `resume.paper` is unanswered (`adopt.py paper Letter|A4`). Say that the new PDF is
  committed by the person first (look at it, commit it, then `adopt.py inventory` and `adopt.py parity`), and that a template's
  `.sha256` stamp beside the PDF may make the old builder stop after it (the next `parity` says so).

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
  difference. The causes are printed under two headings, **"a visitor sees"** and **"no visitor sees
  (does not block)"**; read the first to the person as what they would accept.
- **ACCEPT candidates.** `parity` ends with one list: every visible difference no setting, look or
  carried page removed, one row per page that differs (or that only one build has), per address no
  longer served, and per file no old page links. Each page row says what the person can do about that
  page alone: keep it as written (`adopt.py setting carried <path>`), or keep their builder.
- **The pictures.** `adopt.py parity --keep <dir>` leaves the two builds in `<dir>/local` and
  `<dir>/plugin` as the builders wrote them, and from 0.6.0 also renders every page row from each build
  that has it, four views each (wide and narrow, light and dark), into `<dir>/shots/old` and
  `<dir>/shots/new`, with `<dir>/shots/compare.html` showing each page old beside new. **Name the folder
  yourself: a new one beside the repository, `../<repo name>-parity`** (with a number after it when
  that exists), not the system's temporary folder, so it is still there when the person comes back.
  `<dir>` must not exist, or be empty, and must be outside the repo. `--keep` is the only adopt command
  that starts a browser (headless Chrome); plain `parity`, `check`, `inventory` and `apply` start none.
  It prints the number of renders first, then the path of `compare.html` and every PNG's path.
- **Give the person the path, and never say the pictures were "shown".** Reading a PNG yourself shows
  it to nobody. Say: "the pictures are in `<path of compare.html>`: open this file, then tell me
  whether to accept." In the desktop app the person can click the path; in a terminal, "open this file
  in your browser". Always add the PNG paths it printed: **"if the page shows no pictures, open these
  files"** (whether the app's pane loads the pictures beside a file outside the project is not yet
  known).
- **Accepting.** If the person accepts the differences, so the build becomes the plugin's, run
  `adopt.py parity --accept --shots <dir>/shots`. It accepts the whole record at once, never page by
  page, and only what an earlier `parity` on the same commit already showed: it prints those
  differences (one line per cause) before it records `ACCEPTED`. It refuses, saying what to run, when
  the ACCEPT candidates are not the ones the last `parity` stored, when no `--keep` made the pictures,
  when a page that differs has no picture from a build that has it, or when a picture is gone or
  changed since it was made (then run `--keep` again, into a new folder). If you run it before the
  person has seen them (no earlier `parity` on this commit, or the differences are not the ones the
  last run showed), it lists the differences, records `DIFFERENT`, says it did not accept, and the
  person is asked again. **Without a browser on the machine** no picture can be made: `--keep` stores
  `chrome-not-found`, and `--accept` then records "accepted without pictures: chrome-not-found", once
  the differences have been printed as text, and only while the machine still has no browser. **A
  browser that is installed and will not start** (running as root, or a Linux sandbox restriction) is a
  refusal with the cause and the fix, never an accept without pictures. Otherwise the local builder is
  kept and the agents and commands can still be archived.
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
pushes nothing, and says whether a real `apply` would stop, blocked. **From 0.10.0 it asks step 2's checks too**, the
offline ones and, where `gh` and the network answer, the public repo's (a row that could not be asked reads `not checked`,
never a pass), so a stop that step 2 would make is said here, in the list from "The publish checks" above, with who can fix
each finding. A dry run still cannot know what the person's answer at the publish ask, a privacy review, Pages or the push
will say: `adopt.py check --online` lists them under "can still stop apply". Then `adopt.py apply`. **Ask the
person before you run it, and tell them what it does**: it publishes the converted site (public
forever), waits for GitHub Pages, archives the old builder and pushes to the dev repo's `main`. Say too, in
the same ask, what it will write that a visitor cannot see: the words of the suggested reference layout (read
from the dry run's block, and that it makes the site schema 9), if it is on, that `blocks.unlistedVideos`
puts a video's private code in the page, and, if the person chose it, that `images.sizes: held` adds one stylesheet to pages with
pictures and needs a privacy review. **When the build needs a privacy review** (an ACCEPTED or MARKUP-ONLY verdict, `held`, a vouched
resume PDF, or a scan finding), say so now, and that the `apply` after the review must run before 00:00 UTC of the day the conversion
commit is dated, or the review is made again. The plugin's guard then asks once more (see "The guard" below); that
one yes covers every step.

`apply` runs five steps in one process and says which one it is on:

1. **Measure and convert**: the check, the conversions, the file dispositions and parity, on the parity
   basis, as above. It makes the conversion as one commit on the branch `site-studio/adopt-<date>`,
   made with git plumbing, so the person's own checkout, index and branch never move. Its message
   lists what was archived and why, what data moved where, what configuration changed (every value it
   normalised, and which kept files still hold the old form), which hooks were rewritten, what
   customisations were kept, which commits not yet on `origin/main` it includes, and the parity result.
2. **The publish preconditions**: the dry run's own refusals, run read-only on the build it just made:
   the build's acceptance of the tree (a refused build blocks here; it is never "not run"), the resume PDF's proof, the site gates, the
   address guard against the live public repo, the publish target (V1 to V3), and the Pages source. A site that cannot be
   published stops here, blocked, and prints the same list as `check`, grouped by who can fix each finding (adopt, the site,
   you, the plugin) with its fix, not only family names. A check that could not run (no `gh`, no network) is printed as
   `NOT CHECKED`; it does not block here, because step 3 asks again. **A dev repo
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
  site needs (up to 10: a measured setting from 0.6.0 is a schema-6 key, which a copy of the plugin
  older than 0.6.0 on another computer refuses with "update site-studio", `blocks.unlistedVideos` or
  the suggested reference layout makes it schema 9, which a copy older than 0.9.0 refuses the same way, and `images`,
  `sitemap`, `blankMeta` or a `card.image` part makes it schema 10, which a copy older than 0.10.0 refuses), and the
  inventory says when it is more than 1 and why.
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

### Filing a look suggestion (0.7.0)

A look suggestion is drafted in the `look` skill ("Offer an addition back": `adopt.py suggest`, then the dry print
`adopt.py report --suggestion <id>`). Filing it is here, because only the person starts this skill. When the person
asks to file one:

1. Run `adopt.py report --suggestion <id>` again and show the person the whole text: the title `site-studio look:
   <id>`, the body with its `Evidence:` line (`parity, measured at <short sha>` or `build only, no parity
   measured`), and the last line, `to file exactly this: adopt.py report --suggestion <id> --file --digest <12 hex>`.
2. **Ask once.** On their yes, run exactly that last line: `adopt.py report --suggestion <id> --file --digest
   <digest>`. One id per command, one issue per yes. It is a publish to the guard, so the guard asks too.
3. Read its result to the person. It checks, in order: the site is on site-studio (not part way through an
   adopt, before `apply`), `gh` is signed in and git has a
   committer identity; the text it would file has the digest the dry print showed (if not: "the text to file is not
   the text that was shown", so print it again and show it); the draft holds no word, class, id, address or number
   of the site; and the tracker has no issue of the same title, open or closed. Then it files one public issue on
   the plugin's tracker, with no label, and commits `.site-studio/look-suggestions.json` alone on the current
   branch, not pushed (the line says so: the next publish refuses until that commit reaches `main`). A suggestion
   already on the tracker is recorded as `existing` with its number, and nothing is filed.

`adopt.py report --suggestion <id> --decline` records the person's no; that id is not offered again. A refusal
files nothing and changes no record: read its line to the person and do not try another way. Never run `gh issue
create` yourself, never edit the body, and never file a suggestion the person has not just been shown.

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
  Three kinds of difference are judged invisible once, at measure time, and are not re-checked at publish:
  - whitespace a browser collapses between block elements;
  - a `noopener` or `noreferrer` `rel` on a link that opens in the same window;
  - from 0.6.0, an `href`, `src` or `srcset` address that names the same resource in both builds
    (rule U): the same address read from each build's own path (`./` against `../work/` from a page
    one folder down), the same same-site stylesheet or script with only a version in its query and
    equal bytes, or another same-site address whose file has equal bytes. An address the old build
    served and the new one does not is always a difference a visitor sees.

An unreadable record stops it too, naming the file. No record (a site made by setup, or adopted by an older site-studio) is the old
behaviour: nothing is read. Tell the person plainly that publishing here is held by design, not broken.

`adopt.py remeasure` is how it is released, and how a blocked run is retried after an upgrade: it
converts again, accounts for every file again and measures again against the plugin build of `HEAD`,
prints each difference (by cause, as `parity` does), rewrites the record and commits that one file.
`adopt.py remeasure --accept` records `ACCEPTED`, and **only after the person has just been shown the
differences and said yes**: it prints the differences it is accepting (one line per cause) **before**
it writes the record, so what is accepted is in front of them in the same run; it never accepts
UNVERIFIED. From 0.6.0 it needs the pictures too, by the rule `parity --accept` has: run `adopt.py
remeasure --keep <dir>` first (the folder beside the repository, as above), give the person the path
of `compare.html` and the PNG paths, then `adopt.py remeasure --accept --shots <dir>/shots`, which
refuses unless those pictures are of the differences it measures now. Its commit message names the
pictures ("pictures of <n> page(s), manifest <12 hex>") or "no pictures: chrome-not-found". For a site
with no local builder at all, `--accept` means "site-studio's build replaces my
site, unmeasured". It refuses in a cloud session, as adopt does. The gate runs only the one builder
file adopt classified: any other step of the person's pipeline (a CI workflow, a hosting build) is not
run, and the inventory says so.

## The guard, and when `apply` cannot ask

`adopt.py apply` (without `--dry-run`), `adopt.py report --file` and `adopt.py report --suggestion <id> --file
--digest <digest>` are publishes to the plugin's guard, which decides from the session's permission mode, as it does for `deploy.py --confirm`:

| session | the guard |
|---|---|
| permission mode `default`, `acceptEdits`, `plan` | **asks** the person; their yes is the yes to the whole run |
| `auto` | **asks**; that the ask reaches the person in `auto` is UNVERIFIED |
| `bypassPermissions`, `dontAsk`, any other mode, or none | **denies**: this session is set not to ask |
| a cloud session | **denies**: adopt runs only on the person's own computer |

`apply --dry-run`, `adopt.py report` and `adopt.py report --suggestion <id>` (print), and `--decline` are never
held. Never try to get past a
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
