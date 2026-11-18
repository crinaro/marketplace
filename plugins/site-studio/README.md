# site-studio: your own portfolio, resume or links site, published on GitHub Pages

site-studio helps you build, check, preview and publish a personal site from inside Claude Code. You
keep your content, photos, notes and decisions in a **private** repository. When you say so, the
plugin builds the finished site and publishes only the generated files to a **public** repository
that GitHub Pages serves.

Three kinds of site, set in `site/site.json` as `siteKind`:

- **portfolio** (the default): a generated home page, pages of your work, an about page and a resume
  page with its PDF.
- **hub**: one hand-written page of links, for you or for a group of people. Nothing is generated.
- **custom**: any other hand-made site, built page by page from `site/src/` as you wrote it.

All three use the same preview, review and publish steps.

## Two repositories: private for your work, public for the result

| repository | holds | who can see it |
|---|---|---|
| **dev** (private), `<name>-dev` | your content, original photos, brand notes, decisions, the resume source | you |
| **site** (public), `<name>` | only the generated site GitHub Pages serves | everyone |

Nothing private goes public, because the public repository never holds it: publishing replaces its
whole contents with the build.

**If you have one repository today**, site-studio does not split it for you, and what it can do
depends on what that repository holds:

- **It has `site/site.json` and its own copy of these tools:** use adopt, below. **If that one
  repository also serves its own GitHub Pages site** (one repository doing both jobs), adopt stops
  and tells you why: it never archives a workflow that publishes your own source. The way out is to
  create a new private repository, move your source there, keep only the published site in the
  existing public repository (which already serves it), and run adopt again. Two repositories is the
  pattern site-studio is built for.
- **It is a hand-made site without `site/site.json`:** this version cannot take it in. Adopt
  needs `site/site.json`, and `/site-studio:setup` always creates two **new** repositories and
  stops when a site is already served under the name you choose **or** at your account's own
  `<owner>.github.io`. So if your hand-made site is a project site, you can set up a new `custom`
  site under another name and copy your pages into `site/src/`; your old repository is left as it
  is. If your hand-made site *is* `<owner>.github.io`, setup stops for every name under that
  account; it can go on only under another owner, such as an organization you run.

Whichever way you go, keep source material (originals, notes, drafts) in a private repository and
only published pages in a public one. Anything that was ever public stays in that repository's git
history, so treat it as published.

## Install

In Claude Code, add this marketplace from its **URL** (a local folder works on one computer only)
and install the plugin, then type `/site-studio:setup`:

```
/plugin marketplace add crinaro/marketplace
/plugin install site-studio@crinaro-marketplace
```

## What you need

| need | used for |
|---|---|
| **Python 3.9 or newer** and **git** (on a Mac the Command Line Tools bring both) | everything; no npm or pip install |
| **gh**, the GitHub command line, signed in | setup, publish and adopt |
| **Google Chrome** (Chromium on Linux) | importing photos, visual checks, capturing a page, making the resume PDF. Building and publishing do not need it |
| **node**, only for an adopted site with its own builder | comparing your builder with site-studio's, and choosing the settings that make the two match |

Setup checks all of this, says what is missing in plain words, and asks before it installs anything.

## Start a new site

Type `/site-studio:setup`. It asks what kind of site you want and checks that there is not already
a site in the folder, under your chosen name, or at your account's own `<owner>.github.io`. Then, one plain step at a time, it gets your
computer ready, creates the two repositories, publishes a starter site, turns on GitHub Pages and,
if you want, your own domain. It asks before installing anything, and every password is typed by
you into your system's own prompt, never into the chat.

## Move an existing site over (adopt)

Type `/site-studio:adopt` if you already have a site repository that carries **its own copy of
these tools** (its own scripts, agents or builder), including a site built from the template
site-studio replaces. It reads `site/site.json`; a repository without one is not something adopt
can take (see "If you have one repository today" above).

Adopt works in two stages, and it tells you which one it is in.

**First it measures, and changes nothing your visitors see.**

- It lists every problem it finds with its fix, groups them by cause, and fixes the mechanical ones
  itself, listing each fix.
- It builds your site with your own builder and with site-studio's and compares the two (the
  **parity** check). It converts your content to site-studio's form only where the comparison shows a
  visitor would not see a difference, and it tells you about every difference it finds. A
  difference that is only in markup a visitor never sees is reported as its own result, not hidden.
- Where a setting has to be chosen to make the two match (a page's order, whether a card shows a
  number, which look the pages use), it tries the choices and keeps the one that matches, or the one
  with clearly fewer differences when none matches. Without `node` it cannot measure, so it asks you
  and never guesses.
- Every file in the repository gets one fate, shown to you: published, kept as a draft, archived,
  part of the old builder, or kept as it is. A file your old builder used and site-studio cannot
  hold is named, because a visitor would lose it; that stops the adoption until you decide.
- Your content stays. Nothing is deleted: what is no longer needed moves into an `archive/` folder.
- A standing rule in one of your own agent files can be carried into your `CLAUDE.md` under
  "Standing rules carried by adopt". Files under `.claude/rules/` also reach the plugin's agents
  (measured on one Claude Code version, in a terminal session).

**Then `adopt.py apply` does the rest, in one run, and asks you first.** It publishes the converted
site to your public repository, waits for GitHub Pages to build it, moves your old builder into
`archive/`, and pushes that to your dev repository's `main`. It ends in one of two states:

- **completed:** site-studio has published your site and your old builder is archived. **From then
  on, pushing to your dev repository does not publish anything.** Publishing is
  `/site-studio:publish`.
- **blocked:** something stopped it, and it says what and what to do next (the command ends with exit
  code 4, so a script can tell). Nothing of your old builder moved, and **your old builder keeps
  publishing**. Your own builder stays the publisher until the comparison is equal, or you have been
  shown the differences and accepted them.

Adopt needs your own computer and a session that can ask you the question: in a session set not to
ask, `apply` is refused and Claude leaves a note in `HANDOFF.md` saying what to do next.

### What adopt promises, and what it does not

**It promises:**

- It changes nothing your visitors see without showing you the difference first, and it never
  deletes your content: what is no longer needed moves into `archive/`.
- Your own builder keeps publishing until site-studio's version is measured to match, or you have been
  shown the differences and said yes.
- It asks before it publishes, and a stop leaves your repository's `main` as it was.

**It does not promise:**

- **That your site converts in one run.** A real site built from a template can end *accepted* (you
  were shown named differences and said yes) or *blocked* (nothing moved, your old builder still
  publishing). It is never silently changed.
- **That the two builds are equal.** site-studio has measured an exact match only on small example sites it
  builds for its own tests; on its example template site the one difference left is the description
  each page shows in a search result, which it asks you to accept. It compares the built files (markup, styles and scripts), not screenshots,
  and it leans toward calling a difference visible.
- **That it can reproduce every part of a template's markup.** In this version, on the example
  template, the part of adopt that works out a site's markup from its old pages handles every part
  it was tested on. A real site may have parts it cannot work out; adopt then keeps site-studio's
  own markup there, and the site can end blocked on those pages.

**What stops an adopt today, so it is not a surprise:**

- **Publishing needs a privacy review of exactly what it would publish.** A review is a person-and-agent
  step bound to one exact build, so adopt looks for one before it gives up. If you already reviewed
  the same build (on an earlier adopt branch, or on `main`), it uses that review. If not, and your new
  site looks identical to your old one (parity EQUAL), adopt runs the same automated privacy checks
  `/site-studio:review` starts with, on the exact files it would publish: phone numbers, street
  addresses and email addresses, hidden photo data such as location, and files nothing links to. When
  all of them pass, it publishes and **tells you plainly that no review was done by an agent**, in what
  it prints and in `HANDOFF.md`; run `/site-studio:review` whenever you want one. A difference you
  accepted, or markup-only differences, always need the normal review, and so does anything the
  checks find. Then adopt stops at the publish step, names what it found and `/site-studio:review`,
  and nothing is published. Your old builder keeps publishing.
- **Video embeds.** An old site's video is often a live player on the page. By default site-studio's
  video block is an image that loads the video only when a visitor clicks it (with no script, a
  link). Adopt measures this: where your old pages hold live players, it sets `"blocks": {"videoEmbed":
  "live"}` in `site.json`, so each video keeps the player's own address with nothing added, and the
  look it works out from your old pages puts the player on the page as before. Every site that does
  not set it, and every new site, keeps the click-to-load image.
- **Page descriptions.** The description a search engine shows under each page's title can differ from
  your old site's. No page shows it, but a person sees it in a search result, so site-studio counts it
  as a difference. Adopt names each page, with the old and the new words, as something for you to
  accept, and says it is the only difference when it is. Once you accept it the result reads
  *accepted*, not *equal*, and you can edit a page's `description:` afterwards.

**When adopt is blocked by something in site-studio itself**, it prints what it would report to the
site-studio project: a short description made only of version numbers and the names of site-studio's
own parts, never your file names, text or addresses. It files it only if you say yes. When you update
the plugin, a line at the start of a session tells you if the new version may clear your blockers;
`adopt.py remeasure` measures again.

The adopt skill holds the detail; ask Claude to walk you through it.

## Day to day

- **Add work** (`/site-studio:add-work`): takes the files for one piece, prepares the images
  (location data stripped), asks you for the story, previews it and saves it. It can also move a
  piece to another portfolio **without breaking its old addresses** (each old page redirects; each
  old image or PDF is recorded as released, and you approve that when you publish).
- **Resume** (`/site-studio:resume`): one Markdown source makes the resume page and its PDF. A
  resume can show each role as a card, and an adopted site's PDF keeps the file name it was published
  under, so links to it keep working.
- **Capture** (`/site-studio:capture`): saves one public web page you name as a reference with a
  preview card. It asks what you did on it and shows your answer as a role line on the card. It
  never signs in and never crawls.
- **Import profile** (`/site-studio:import-profile`): brings a public profile into your resume from
  a file you downloaded yourself, one proposed change at a time.
- **Look** (`/site-studio:look`): a site's look is the markup its pages are printed through. Pick one
  site-studio ships, check the one your site carries, or have site-studio work one out from your own
  pages, so a site keeps the structure and class names its stylesheet already knows. It changes the
  tags around your words, not your words.
- **Ideas** (`/site-studio:ideas`): three advisors (brand, portfolio, presence) put two or three
  options in front of you. Nothing is published.
- **Preview** (`/site-studio:preview`): shows the site as it will look, drafts included.
- **Review** (`/site-studio:review`): checks the built site before publishing and gives one ordered
  list of what to fix, including anything too personal.

A **draft** is a piece with `draft: true` in its front matter. Preview shows it; a published build
never contains it.

### More ways to show your work

These are opt-in; a site that does not ask for one is built exactly as before. Each needs the site
raised to the newest settings version (schema 4), which site-studio shows you before it writes, and
which older copies of the plugin on other computers will refuse until they are updated.

- **Index views.** A portfolio's index can be a **roles** view (one card per employer, your current
  role first), a **map** (a dotted world map with one pin per piece, drawn from a file in the plugin,
  with nothing loaded from the web) or a **showcase** of tiles. They are made from your content, so
  adding a piece updates them.
- **Cards.** A card can show a number (`02 / 2025`, `2 / 2025` or just `2`), show its values without
  labels, and a piece page can link back to its portfolio.
- **Home page.** An eyebrow line, a role line, a showcase of tiles, sample reference cards and a row
  of links.
- **Resume.** A tagline and links in its header, role cards, and headings printed at the level you
  wrote them.
- **Blocks.** A grid of several quotes, and a gallery image that plays a video when clicked (with no
  JavaScript it is a link; nothing loads from the video's host until you click). A gallery video is
  titled by its caption, then its alt text. `"blocks": {"videoEmbed": "live"}` keeps a video's own
  address, as an old site's live players use it; the default is the click-to-load form.
- **References.** A card image of your choice, and a role line.
- **Home and index options.** The home page's `<title>` form, whether its intro holds the whole body
  or its first block, the order of its parts, and a one-piece portfolio's index as a listing.

The full list of keys, tokens, blocks and settings is in `reference/content-model.md` in the
installed plugin, next to `scripts/`.

## Publish

`/site-studio:publish` is a command only you can start. It runs a **dry run** first: it builds the
site, runs every check, and shows what would go public. A privacy review of exactly that build must
be recorded, and the reviewed commit must be on the dev repository's `origin/main`. Then you
confirm, and the plugin pushes to the public repository's `main`. It never force-pushes, and it
pushes only to the repository named by `publicRepo` in `site/site.json`.

- **Your published addresses are protected.** Every page, image or PDF your public site serves today
  is an address someone may hold. If a new build would end one, the dry run refuses and names it:
  keep it (a redirect for a page, a file at the same name for anything else) or release it on
  purpose. The confirmation question names every address a publish releases, so your yes covers them.
- **Cloud sessions never publish.** Open the repository on your own computer.
- **You are asked before every publish.** That the question reaches you in every permission mode on
  every surface is **not yet verified**. Do not publish from a mode meant to run without you.
- After a publish, a read-only **Pages check** lists what still needs resolving on GitHub's side
  (the domain's DNS records, domain verification, HTTPS) and who does it. You do those steps; the
  plugin only reads.
- Setup offers, and publish may offer again, a rule that stops anyone force-pushing to or deleting
  the public repository's `main`. It asks first and publishing works without it.

## Getting help

Ask in a session, even before you have a site: "what can I do", "what next", or "what does this
error mean". Claude reads where your site stands and answers, and for a refusal it restates the fix
and reads the relevant part of the reference. For adopt, it reads you the line that says whether the
run `completed` or is `blocked at step N`, the cause, and the one next step.

## Where it runs

- **Mac (desktop app or terminal):** everything. That publish's question reaches you is not yet
  verified (see Publish).
- **Linux terminal:** the same code, and the test suite runs on Linux; it has not yet been tried
  on a person's own Linux computer.
- **Cloud session:** usually the plugin is not installed there, so `/site-studio:` commands answer
  `Unknown command`; open the repository on your own computer. If it is installed, editing,
  checks and builds are expected to work (they need only Python and git), but that is not yet
  verified. Publishing and adopt are refused
  there either way.
- **Scheduled runs:** nothing publishes, and setup and adopt cannot be started by a schedule.
- **Phone, web or claude.ai:** there is no working copy of your repository, so site-studio does
  not run.
- **Windows:** not supported yet. The plugin says so in one sentence and stops.

## Your published site does not change under you

site-studio may change how it builds, maintains or publishes a site, never what a visitor
experiences: how your published site looks or works. A new version builds a site its predecessor
built to the same files; a new feature applies only when you opt in; adopting a site checks that a
visitor would see no difference before it changes how the site is built; your published addresses
keep working; and the plugin's styles never override yours.

## Privacy

Your content and settings live in your own repositories. The plugin has no server and no telemetry.
When adopt is blocked by something in the plugin itself, it can file a report, only after you say yes,
made only of version numbers and the names of the plugin's own parts. See [PRIVACY.md](PRIVACY.md).
