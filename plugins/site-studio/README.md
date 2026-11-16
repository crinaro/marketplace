# site-studio: your own portfolio, resume or links site, kept in a private repo and published on GitHub Pages

site-studio helps you build, check, preview and publish a personal site. You keep your content,
photos, brand notes and decisions in a **private** "dev" repository. When you decide, the plugin
builds the finished site and publishes only the generated files to a separate **public** repository
that GitHub Pages serves. Nothing private ever goes public, because the public repo never holds it.

It does these jobs, each as a command you type or ask for in plain words:

- **Set up** (`/site-studio:setup`): asks first what kind of site you are making (see below), checks
  that there is not already a site in the folder or under the name you chose, then creates the two
  repositories, turns on GitHub Pages and, if you want one, your own domain, and gets your computer
  ready, one plain step at a time. A folder that already holds a site is sent to adopt instead.
- **Add work** (`/site-studio:add-work`): takes the files for one piece of work, prepares the
  images, asks you for the story, previews it and saves it.
- **Resume** (`/site-studio:resume`): one Markdown source makes both the resume page and its PDF.
- **Capture** (`/site-studio:capture`): saves one public web page you name as a reference with a
  preview card. It never signs in and never crawls.
- **Import profile** (`/site-studio:import-profile`): brings a public profile into your resume from a
  file you downloaded yourself, and proposes each change for you to pick.
- **Preview** (`/site-studio:preview`): shows the site as it will look, drafts included.
- **Review** (`/site-studio:review`): checks the built site before publishing: automatic checks,
  then an editor, a privacy reader and a visual check, and one ordered list of what to fix.
- **Ideas** (`/site-studio:ideas`): three advisors (brand, portfolio, presence) put two or three
  concrete options in front of you. Nothing here publishes.
- **Adopt** (`/site-studio:adopt`): if you already have a site repo that carries its own copy of
  these tools, converts it. Your content stays; the copies are retired on one branch for you to
  review. It lists every problem it finds in what it would write, all at once, and fixes the
  mechanical ones itself (a clone-style `publicRepo`, a trailing slash, a content folder without a
  `page.md`, label pairs) and lists each fix in its commit. It turns a hand-made page that only
  forwards (a meta refresh) into a `redirects` entry, says which features your site uses and what
  site-studio does about each, and proposes a site kind for you to confirm. It works from your
  checkout's `HEAD` when that is ahead of `origin/main`, so a fix you just committed is what it
  measures, and it says so first. It asks the plugin's own build whether your converted site would
  build, so `check` never says "can be converted" about a site the build would refuse. A conversion is
  made for you only when a comparison with what your own builder publishes finds no page a visitor
  would see changed; anything else is listed for you to decide, with the difference named. While that
  comparison is not equal, your own builder stays the publisher and `/site-studio:publish` refuses to
  replace it (see "A published site never changes under you").
  If one of your own agent files holds a standing rule of yours, adopt can carry that rule into your
  site repo's `CLAUDE.md` (under "Standing rules carried by adopt") before it removes the file, so every
  agent keeps working to it. Files under `.claude/rules/` reach the plugin's agents too, so you may move
  those rules there if you prefer (measured on one Claude Code version, in a terminal session).
- **Publish** (`/site-studio:publish`): a dry run first, then a public push after you confirm.
- **Pages check** (`pages_check.py`, run by setup and publish, and summarised in the doctor report):
  reads your public repo's GitHub Pages settings and tells you, one line each, what still needs
  resolving and who does it. It only reads.
- **Protect** (`repos.py protect`, offered by setup and publish, always after asking): adds a rule on
  the public repo's `main` that stops anyone force-pushing or deleting it.

## Three kinds of site

`site/site.json` says which, in `siteKind`:

- **`portfolio`** (the default): a generated home page, portfolios of work, an about page and a resume
  page with its PDF. This is what 0.1.0 made, and a portfolio that uses nothing newer is still written so
  that 0.1.0 can read it.
- **`hub`**: one hand-written page of links (`site/src/index.html`), for you or for a group of people.
  Nothing is generated.
- **`custom`**: any other hand-made site, built page by page from `site/src/` as you wrote it.

A hub or custom site uses the same checks, preview, review and publish as a portfolio; it only has no
pieces or resume to check. Newer features that need `"schema": 2` in `site/site.json`, and the plugin
writes the lowest schema your site needs:

- a **hand-made home page**: a `site/src/index.html` with no `content/home.md` is the home page, as
  written (both together are refused, naming both files, unless the hand page takes its copy from
  `content/home.md` with `{{home:<part>}}`, a 0.3.0 feature below);
- **display labels**: `work.labels` names what a field is called where it is printed, without changing
  the plain keys in `meta` and `groups`;
- a **page section**, `{{#page:resume}}...{{/page}}`, that shows a link only when that page is built, and
  **`{{featured}}`**, which shows the featured pieces wherever you put it. By default the featured
  pieces are the `featured:` list in `content/home.md`; with `"featuredFrom": "flags"` they are the
  pieces whose own front matter says `featured: true`.

`docs/content-model.md` (in the development repository, not the installed plugin) has the details. If you
used 0.1.0 on another computer, update site-studio there before you build a schema 2 site.

## What 0.3.0 adds (schema 3, all opt-in)

Nothing here changes a site that does not use it. A site moves to `"schema": 3` only through
`python3 build.py raise-schema`, which lists every page that would change first and writes nothing
until you confirm each one or keep a line as text:

- **a hand-made home fed by your home page.** Keep `site/src/index.html` as you wrote it and put
  `{{home:title}}`, `{{home:intro}}`, `{{home:photo}}`, `{{home:endorsement}}`, `{{home:feed}}`,
  `{{home:contact}}` (and `{{featured}}`) where the copy belongs; a `:::part stats` block in
  `content/home.md` is a part of its own, `{{home:stats}}`. Both files together are still refused unless
  the hand page uses one of these.
- **portfolio page keys**: `order` (the menu order), `tagline`, `sort` (`"order"` sorts pieces by their own
  `order`), `menuLinks` (`"single-piece"` links the one piece) and `view` (`"page"` serves your own index
  page). A resume page may carry `contact`, and a site with no resume PDF is not asked for a paper size.
  Under `"single-piece"` with exactly one piece, the portfolio's index address is served as a redirect to that
  piece (and your own `view: "page"` index is never replaced).
- **six Markdown blocks**: `:::tiles`, `:::quote`, `:::gallery`, `:::videos`, `:::carousel` and
  `:::part`, and a titled image. A video is a poster you committed that plays the video **after a click**;
  nothing loads from the video's host before it. Each block works without JavaScript.
- **`content/home/index.md` and `content/about/index.md`**, each with its own `media/`, as the home and
  about pages, so nothing in an adopted repo has to move; and `<name>.w400.jpg` size copies beside an
  original, which keep their names and their addresses.

### A published site never changes under you

The promise: **site-studio may change how it builds a site, never how your published site looks or works
for a visitor.** In practice:

- A new site-studio version builds any site its predecessor built to **the same bytes**. A new key, block
  or reading applies only at the schema that introduces it, and a tree that holds text 0.2.0 showed as text
  stays text until you raise it, line by line.
- Every plugin style is in one cascade layer (`@layer site-studio`) with `ss-` class names, and a page links
  the stylesheet only where it uses a block. Whatever CSS you wrote beats it, and your own pages and layout
  are never edited.
- An adopted site records what the comparison found in `.site-studio/adopt-parity.json`. Unless it says
  EQUAL or ACCEPTED, `/site-studio:publish` refuses and leaves your own builder as the publisher, and what it
  says depends on the verdict. DIFFERENT names the first difference: run `python3 adopt.py remeasure` to
  measure again, or `--accept` to record that you accept the differences you were shown. NOT APPLICABLE
  (no builder of yours was found, so nothing was compared): `--accept` records that site-studio's build
  replaces your site, unmeasured. UNVERIFIED (the comparison could not run, for example there is no node):
  `--accept` refuses it, because nothing was measured to show you. Install node, then run `adopt.py remeasure`
  again.
- Something site-studio does not build (a roles or map index, a project-specific block renderer) is not
  removed: your own builder keeps publishing it, or you keep that page as your own file in `site/src`
  (`view: "page"` for an index).

If you used 0.2.0, update site-studio on every computer you build from before you raise a site to schema 3.

## Install

1. In Claude Code, add this marketplace from its **URL** (not from a local folder, which works on
   one computer only) and install **site-studio**:

   ```
   /plugin marketplace add crinaro/marketplace
   /plugin install site-studio@crinaro-marketplace
   ```
2. Open a session and type `/site-studio:setup`.

## What you need

| need | used for |
|---|---|
| **Python 3.9 or newer** and **git** (on a Mac, the Command Line Tools bring both) | everything; the plugin is Python standard library only, with no npm or pip install |
| **gh**, the GitHub command line, signed in | setup and publish |
| **Google Chrome** (Chromium on Linux) | importing photos, visual checks, capturing a page, making the resume PDF. Building, checking and publishing do not need it |
| **node** (needed only for an adopted site that has its own builder) | adopt, to compare a repo's own builder with this one, and `adopt.py remeasure`. Without node that comparison is UNVERIFIED, and an adopted site with a builder cannot be published by site-studio until node is installed and `adopt.py remeasure` is run again |

`setup` runs a check and tells you what is missing, in plain words, and asks before it installs
anything. Every password is typed by you into your system's own prompt, never into the chat.

## The Pages check: what it tells you, and what stays yours

After setup's first publish and after each publish, the plugin reads the public repo's Pages state
through your own `gh` sign-in and prints a line for each thing that needs attention, with who
resolves it: you, GitHub (it is still working), or you at your DNS provider. It never changes
anything. It checks the Pages source, the build, a custom domain and its DNS, the domain
verification, the HTTPS certificate and the Enforce HTTPS setting, whether `main` is protected, and
whether anyone other than you can write to the repo.

Exit 3 means something to resolve or still waiting, which is not a failure of your publish. A line
that says NOT CHECKED means it could not read that item (usually a missing admin right), and is never
a pass. **You** add the DNS records, do the domain verification in your GitHub settings, type the
custom domain into the Pages settings if it says so, and turn on Enforce HTTPS. The plugin names
each step and checks it again. Apps installed on your account are not checked, and the `www` alias of
a domain is checked only for its DNS.

## Protecting `main`

Setup offers to add a ruleset named `site-studio: protect main` to the public repo. It blocks
force-push and deletion of `main`, and **nothing else**: no pull-request requirement and no required
checks, because publish pushes straight to `main`. It asks first, and only a repo admin can add it.
If your GitHub plan does not offer rulesets, the plugin offers classic branch protection with the
same two protections, once, and if you say no, publishing still works. The Pages check reports a
ruleset that someone changed, and `repos.py protect --fix` restores it after asking.

## Publishing uses your own GitHub login, with three guards

There is no separate publishing credential. Publish pushes with the login you already have, so three
guards stand in for a narrower key:

1. The `main` ruleset above blocks force-push and deletion and never refuses a normal push.
2. The publish script pushes only to the repo named by `publicRepo` in `site/site.json`, only to
   `main`, and never force-pushes. Before pushing it checks that `publicRepo` is not your private
   dev repo, that the public repo is public, not archived and writable by you, that git will push to
   that same repo (an SSH host alias or a rewrite to another repo is refused), and that `main` has
   not moved since the dry run. A dry run runs the same checks.
3. The Pages check reports any other account, team or write deploy key that can write to the public repo.

Whether these guards stop a force-push under GitHub's live rules has not yet been probed on a real
repo; that probe (P-10) is run by the maintainer before release.

## Publishing asks you first

`/site-studio:publish` is a command only you can start: Claude cannot run it on its own. Before the
public push, a guard shows you what will go public and asks you to confirm, and the publish script
refuses to push a build that has no recorded privacy review. **That the confirmation reaches you in
every permission mode on every surface is UNVERIFIED until probe P-7 has been run and its result
recorded**. Until then, treat the confirmation as the
thing to watch for, and do not run publish in a mode that is meant to run without you.

Publishing is refused, by design, in a cloud session. Open the repo on your own computer to publish.

## Where it runs

| where | what works |
|---|---|
| Desktop app, Mac | everything |
| Terminal, Mac or Linux | everything |
| Cloud session (if the plugin loads there at all; unverified) | editing, checks, screenshots and PDF. Capturing a page needs a wider network setting. **Publishing is refused** |
| Scheduled runs, phone, claude.ai Home | nothing publishes; a scheduled run only reports |
| **Windows** | **not supported in this release.** The plugin says so in one sentence and stops |

The full picture, with what was tested and what was not, is the maintainers' `docs/deployment.md` in
the development repository; it is not part of the installed plugin, so this page does not link to it.

## What stays on your computer

Your content, brand notes and settings live in your own repositories. The plugin has no server and
no telemetry. See [PRIVACY.md](PRIVACY.md).
