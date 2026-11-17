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

- **It has `site/site.json` and its own copy of these tools:** use adopt, below.
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
| **gh**, the GitHub command line, signed in | setup and publish |
| **Google Chrome** (Chromium on Linux) | importing photos, visual checks, capturing a page, making the resume PDF. Building and publishing do not need it |
| **node**, only for an adopted site with its own builder | comparing your builder with site-studio's |

Setup checks all of this, says what is missing in plain words, and asks before it installs anything.

## Start a new site

Type `/site-studio:setup`. It asks what kind of site you want and checks that there is not already
a site in the folder, under your chosen name, or at your account's own `<owner>.github.io`. Then, one plain step at a time, it gets your
computer ready, creates the two repositories, publishes a starter site, turns on GitHub Pages and,
if you want, your own domain. It asks before installing anything, and every password is typed by
you into your system's own prompt, never into the chat.

## Move an existing site over (adopt)

Type `/site-studio:adopt` if you already have a site repository that carries **its own copy of
these tools** (its own scripts, agents or builder). It reads `site/site.json`; a repository without
one is not something adopt can take (see "If you have one repository today" above).

- It lists every problem it finds with its fix, groups them by cause, and fixes the mechanical ones
  itself, listing each fix.
- Your content stays. The copies are retired on **one new branch** for you to review. Nothing is
  merged, pushed or published.
- It builds your site with your own builder and with site-studio's and compares the two (the
  **parity** check). **Your own builder stays the publisher, and `/site-studio:publish` refuses to
  replace it, until the comparison is EQUAL or you have been shown the differences and accepted
  them.** Without `node`, an adopted site that has its own builder cannot be compared, so
  site-studio cannot publish it until `node` is installed and the comparison is run again.
- A standing rule in one of your own agent files can be carried into your `CLAUDE.md` under
  "Standing rules carried by adopt". Files under `.claude/rules/` also reach the plugin's agents
  (measured on one Claude Code version, in a terminal session).

The adopt skill holds the detail; ask Claude to walk you through it.

## Day to day

- **Add work** (`/site-studio:add-work`): takes the files for one piece, prepares the images
  (location data stripped), asks you for the story, previews it and saves it.
- **Resume** (`/site-studio:resume`): one Markdown source makes the resume page and its PDF.
- **Capture** (`/site-studio:capture`): saves one public web page you name as a reference with a
  preview card. It never signs in and never crawls.
- **Import profile** (`/site-studio:import-profile`): brings a public profile into your resume from
  a file you downloaded yourself, one proposed change at a time.
- **Ideas** (`/site-studio:ideas`): three advisors (brand, portfolio, presence) put two or three
  options in front of you. Nothing is published.
- **Preview** (`/site-studio:preview`): shows the site as it will look, drafts included.
- **Review** (`/site-studio:review`): checks the built site before publishing and gives one ordered
  list of what to fix, including anything too personal.

A **draft** is a piece with `draft: true` in its front matter. Preview shows it; a published build
never contains it.

## Publish

`/site-studio:publish` is a command only you can start. It runs a **dry run** first: it builds the
site, runs every check, and shows what would go public. A privacy review of exactly that build must
be recorded, and the reviewed commit must be on the dev repository's `origin/main`. Then you
confirm, and the plugin pushes to the public repository's `main`. It never force-pushes, and it
pushes only to the repository named by `publicRepo` in `site/site.json`.

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
error mean". Claude reads where
your site stands and answers, and for a refusal it restates the fix and reads the relevant part of
the reference. The full list of keys, tokens, blocks and settings is in `reference/content-model.md`
in the installed plugin, next to `scripts/`.

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

site-studio may change how it builds a site, never how your published site looks or works for a
visitor. A new version builds a site its predecessor built to the same files; a new feature applies
only when you opt in; and the plugin's styles never override yours.

## Privacy

Your content and settings live in your own repositories. The plugin has no server and no telemetry.
See [PRIVACY.md](PRIVACY.md).
