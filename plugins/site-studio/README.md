# site-studio: your own portfolio, resume or links site, published on GitHub Pages

site-studio helps you build, check, preview and publish a personal site from inside Claude Code. You
keep your content, photos, notes and decisions in a **private** repository. When you say so, the
plugin builds the finished site and publishes only the generated files to a **public** repository
that GitHub Pages serves.

site-studio gives you tools, patterns and templates to reuse; you and your Claude Code session decide how your site
looks. Your own look file, your key maps and your own named blocks and views are the normal way to work, not a
workaround. When something you added would help other people, site-studio can draft a suggestion from its structure
alone, from any site: a site you adopted from its own builder carries the comparison with your old pages, and any
other site carries the proof that the addition builds and passes the checks. It is sent only when you say yes.

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
| **Google Chrome** (Chromium on Linux) | importing photos, visual checks, capturing a page, making the resume PDF, and (from 0.6.0) the pictures adopt makes of each page that differs. Building and publishing do not need it; without it adopt shows the differences as text |
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
  itself, listing each fix. From 0.5.0 a piece key that some view or setting of site-studio reads is
  never called unused: where your portfolio does not use that view, a note says which view reads the
  key and that you can list it to print it as it is, or set the view.
- It builds your site with your own builder and with site-studio's and compares the two (the
  **parity** check). It converts your content to site-studio's form only where the comparison shows a
  visitor would not see a difference, and it tells you about every difference it finds. A
  difference that is only in markup a visitor never sees is reported as its own result, not hidden.
- Where a setting has to be chosen to make the two match (a page's order, whether a card shows a
  number, which look the pages use), it tries the choices and keeps the one that matches, or the one
  with clearly fewer differences when none matches. Without `node` it cannot measure, so it asks you
  and never guesses.
- **From 0.6.0, what is left to accept is one list, with pictures.** Every difference a visitor would
  see that no setting, look or kept page removed is an *ACCEPT candidate*, one row per page.
  `adopt.py parity --keep <folder>` makes pictures of each such page from both builds (wide and
  narrow, light and dark) and a file, `compare.html`, that puts them old beside new; it prints the
  file's path for you to open. Claude puts that folder beside your repository, so it is still there
  when you come back. Accepting needs those pictures: it is refused until they exist and are of the
  same differences. This is the one adopt step that starts a browser (headless Chrome); on a computer
  without Chrome you are shown the differences as text instead, and can accept them that way.
- **From 0.6.0, a page can be kept exactly as your old site served it** (`carried`), such as your
  404 page. It no longer changes when the site does (a new menu item will not appear on it), every
  build reminds you of that, and the first build after your site's address changes stops until you
  correct the page's addresses. Adopt offers the pages only your old builder makes; a page that
  differs can be kept that way by your choice.
- **From 0.6.0 adopt measures more of a template site's settings**: the featured shelf grouped as
  each portfolio's index, a count on each group heading, a piece's dated roles, a back link per
  portfolio, the menu's title item and extra links, the separator in each page's title, where
  images are published (so old image addresses keep working), and the index views (roles, map,
  steps, showcase). The look it works out from your old pages is kept part by part: a part that
  would lose content goes back to site-studio's markup, and the rest stays.
- **A difference that is not one is no longer counted.** Two addresses that name the same file (a
  link written `./` on one site and `../work/` on the other, a stylesheet with a version number
  added) are markup a visitor does not see, and parity prints them under their own heading, apart
  from what a visitor sees.
- Every file in the repository gets one fate, shown to you: published, kept as a draft, archived,
  part of the old builder, or kept as it is. A file your old builder used and site-studio cannot
  hold is named, because a visitor would lose it; that stops the adoption until you decide.
- **From 0.9.0, the files adopt could not test are said, with the reason, before `apply`.** A file it ran out of
  runs or time on, or that your own builder would not answer for, is listed as undisposed with why, and a short list of
  commands settles it (`adopt.py file <path or folder> keep`, then `adopt.py parity` again). Adopt now spends up to four
  minutes more on `parity` to test such files in groups (six if your builder hangs), only on a site that needs it, and
  Claude runs it in the background. Keeping a file leaves it where it is in your private repository; it does not hide a
  file your old builder used and site-studio cannot hold.
- **From 0.9.0, adopt suggests a layout for your references, and writes it unless you say no.** For each reference it
  works out which piece it is for (`project`), what it is (`type`, such as Post or Film) and where its audience saw it
  (`channel`, such as Instagram), from the pages and the address. Claude reads you every word before you say yes, and
  `adopt.py setting referenceLayout none` leaves your references as they are (`project,channel` is the answer for a site not
  in English). Nothing a visitor sees changes. **The cost:** a site with references adopted this way is settings version 9,
  and an older copy of site-studio on another computer says "update site-studio". While your own builder is still your
  publisher, adopt writes none of it. It never writes a closed list of your words into `site/site.json`: the closing text
  is printed for you to copy.
- **From 0.9.0, an unlisted Vimeo link can play.** By default the build leaves an unlisted video's private code out of the
  player, so the video shows Vimeo's own notice. Where your old pages carried the code, adopt can turn on
  `"blocks": {"unlistedVideos": true}`; that puts the code in the page, where any visitor can read it, so Claude says so first.
- **From 0.10.0, what the publish would refuse is said before `apply`, with who can fix it.** `check`, `inventory`, `parity`,
  `apply --dry-run` and `apply` ask the same publish checks of the same converted site and print one list, grouped as what adopt
  fixes, what the site's own pages need, what only you can do, and what only the plugin can (that last is filed upstream; the
  others never are). After a `parity`, `check` exits 1 with "can be converted, but the publish would refuse it" while that list is
  not empty. `adopt.py check --online` also reads your public repository, its Pages settings and its published addresses (it needs
  `gh`, logged in, and the network, and changes nothing), and lists what `apply` can still stop on. A check that could not run
  is shown as not checked, never as passed.
- **From 0.10.0, your resume PDF is proved by adopt.** Where the plugin's reader finds at least 95% of your resume page's words in
  your existing PDF, `apply` writes the proof beside it and the PDF does not change. Where it finds less (the reader can be wrong
  about joined letters, hyphenation and languages written without spaces), `adopt.py proof --as-is` is your word that the PDF is
  right (the privacy review then opens it), and `adopt.py proof --print` prints a new one with Chrome (visitors then get a
  different file). A privacy review applies until 00:00 UTC of its day: run `apply` again before then, or the review is made again.
- **From 0.10.0, three more settings, none changing a published page unless its owner sets the key.** `images.sizes`: where your old
  pages' pictures had no size, adopt leaves them as they were (`as-written`) and the publish check stops asking for sizes; `held`
  adds sizes to generated pages with one small extra stylesheet and is only ever your choice (its costs: one more file, and an
  older browser, from before about 2022, or a missing file gets the plain layout; parity reads it as a difference you accept,
  and it needs a privacy review). `sitemap: indexable` leaves redirect and `noindex` pages out of `sitemap.xml`, set when your old
  sitemap did not list them. `blankMeta: "omit"` prints no row or card separator for a front matter line with no value, set when
  your old site showed none. The publish check also counts the pictures that load only as a visitor scrolls apart, up to
  `budgets.lazyImagesMaxMB` (20 MB by default, never below `pageImagesMaxMB`), and tells, rather than refuses, pieces that share a
  title (including "Untitled"); a hand-written page with no title is still refused.
- **From 0.10.0, a residual unit of an old file can be answered "the plugin covers this; drop it"** (`adopt.py unit <path> <id>
  covered`, or `unit <path> --rest covered` for the rest). The words stay in `archive/`, and the commit lists each one.
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
  and it leans toward calling a difference visible. The pictures `--keep` makes are for you to look at;
  nothing compares them by pixel, and nothing can tell that you opened them.
- **That a site adopted with 0.6.0 opens in an older copy of site-studio.** A measured setting new in
  0.6.0 makes the site schema 6; a copy older than 0.6.0 on another computer says "update
  site-studio" and changes nothing.
- **That a site adopted with 0.9.0 opens in an older copy of site-studio** when it has references (the suggested
  layout) or an unlisted video turned on: both make the site settings version 9, and a copy older than 0.9.0 says
  "update site-studio" and changes nothing.
- **That a site adopted with 0.10.0 opens in an older copy of site-studio** when adopt set `images.sizes`, `sitemap` or
  `blankMeta`: each makes the site settings version 10, and a copy older than 0.10.0 says "update site-studio" and changes nothing.
  So does adopt's own working file when it holds an answer new in 0.10.0.
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
  old image or PDF is recorded as released, and you approve that when you publish). From 0.9.0 it offers to
  turn on an unlisted Vimeo link (saying what that publishes) and to say which piece a reference is for.
- **Resume** (`/site-studio:resume`): one Markdown source makes the resume page and its PDF. A
  resume can show each role as a card, and an adopted site's PDF keeps the file name it was published
  under, so links to it keep working.
- **Capture** (`/site-studio:capture`): saves one public web page you name as a reference with a
  preview card. It asks what you did on it and shows your answer as a role line on the card. From 0.9.0 it also
  suggests which of your pieces the page is for, what it is and where it was seen, from the address, and stores only the
  words you say yes to. It never signs in and never crawls.
- **Import profile** (`/site-studio:import-profile`): brings a public profile into your resume from
  a file you downloaded yourself, one proposed change at a time.
- **Look** (`/site-studio:look`): a site's look is the markup its pages are printed through. Pick one
  site-studio ships, check the one your site carries, or have site-studio work one out from your own
  pages, so a site keeps the structure and class names its stylesheet already knows. It changes the
  tags around your words, not your words. From 0.7.0 you can keep a look file of your own on top (see
  "Your own look", below), and offer an addition back to site-studio.
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
- **References, 0.9.0.** A reference can say which piece it is for (`project`), what it is (`type`) and where its
  audience saw it (`channel`), as separate facts: a card prints the last two only where your own look has a place for
  them, and a hosted video need never print its host. Your site can list the words a reference may use, or words to
  store and never print. The plugin ships a JSON Schema for `reference.json`, and the content model shows the
  `.vscode/settings.json` lines that make VS Code check each reference as you type (at the release you installed).
  A piece's `project` follows it when you move the piece. Each is opt-in, under settings version 9.
- **Home and index options.** The home page's `<title>` form, whether its intro holds the whole body
  or its first block, the order of its parts, and a one-piece portfolio's index as a listing.

Version 0.5.0 adds more, each again opt-in, under settings version 5 (shown to you before it is
written; an older copy of the plugin says "update site-studio" rather than build such a site):

- **A steps view.** A portfolio's index can be an ordered run of numbered steps (`view: steps`), one
  per piece in the portfolio's own order: a picture, the step's number, its title and its role line.
- **Cards and piece pages.** Per portfolio: a card can show a piece's `photo` instead of its cover,
  give its picture the piece's own alt text, and carry a short kicker line from one of your piece
  keys (on cards, roles cards, steps and showcase tiles); a piece page can print one outbound link
  and its teaser as a paragraph under the title.
- **Pictures.** A cover, photo or tile picture can carry its own alt text and crop position, and a
  reference's card picture its own alt and position.
- **Looks.** A look can place these new values, print a piece's full title where another place
  prints the short one, choose how a step's roles are joined, give a step's or a home tile's picture
  its own markup, and hold a decoration: a small drawing (an inline SVG of shapes and gradients only,
  no text, no links, nothing loaded), such as a ribbon behind the steps. If your look has no place
  for a value you turned on, the build refuses and names the part, rather than drop it in silence.

### Your own look (0.7.0)

Version 0.7.0 makes your own markup the normal way to shape a site, again opt-in, under settings version 7 (an older
copy of the plugin says "update site-studio" rather than build such a site):

- **A look file of your own, laid over the other.** `site/looks/local.json` holds only what you write, and
  `"lookLocal": "site/looks/local.json"` in `site/site.json` switches it on. Each block, card or view it holds
  replaces the same one in the site's other look, whole; everything else stays as it was. Every place both files
  hold the same thing is listed, so nothing is hidden. On an adopted site you can also edit the look adopt worked
  out (`site/looks/derived.json`): adopt and `/site-studio:look derive` keep your edit, and to hand a part back you
  delete it. Neither file is published.
- **Key maps.** A look can say which of your front-matter keys a place reads: a video's title from a key of yours,
  a meta row left out when it repeats the title, a roles index grouped by another key, which of a piece's roles is
  the current one, which tile is set apart.
- **Your own named blocks and views.** A block or index view can carry a name of your own and markup of your own,
  over the data of one of site-studio's blocks or views, so an old site's own `:::name` block or `view:` builds
  without your old builder. A block with data rules of its own is not something site-studio builds: that page stays
  yours, as written.
- **Cards numbered by position** (`01 / 2022`, `02 / ...`) across the groups of a page, and a reference card that
  names the piece using it.
- **Two sample looks**, `sample-index` (a portfolio led by its index of work) and `sample-resume` (a site led by the
  resume and its roles), listed by `/site-studio:look`. A link hub gets none: nothing on it is generated, so a look
  has nothing to change there. Using one is your choice; no site changes because they ship.
- **Measured.** On an adopted site whose old builder is still in the repository, each entry of your own is compared
  with your old pages, on its own line, when you commit it and run the comparison again.
- **Offer an addition back.** `/site-studio:look` can check what your own look adds against what site-studio ships
  and draft a suggestion from its structure alone: every class name, address and word of your site is taken out,
  and the draft says whether it carries the comparison with your old pages or only the proof that it builds. You
  read the exact text first. To send it, type `/site-studio:adopt` and say yes: it is filed as one public issue on
  the plugin's tracker, titled `site-studio look: ...`, and nothing is sent without your yes.

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
  there either way; a look review lists what could be offered, and printing or sending a suggestion waits for
  your own computer.
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
made only of version numbers and the names of the plugin's own parts. A look suggestion is filed the same
way, one per yes, and holds only the shape of one part of your look with every class name, id, address and
word taken out, and the numbers the plugin measured. See [PRIVACY.md](PRIVACY.md).
