# site-studio: your own portfolio or resume site, kept in a private repo and published on GitHub Pages

site-studio helps you build, check, preview and publish a personal site. You keep your content,
photos, brand notes and decisions in a **private** "dev" repository. When you decide, the plugin
builds the finished site and publishes only the generated files to a separate **public** repository
that GitHub Pages serves. Nothing private ever goes public, because the public repo never holds it.

It does these jobs, each as a command you type or ask for in plain words:

- **Set up** (`/site-studio:setup`): creates the two repositories, turns on GitHub Pages and, if you
  want one, your own domain, and gets your computer ready, one plain step at a time.
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
  review.
- **Publish** (`/site-studio:publish`): a dry run first, then a public push after you confirm.
- **Pages check** (`pages_check.py`, run by setup and publish, and summarised in the doctor report):
  reads your public repo's GitHub Pages settings and tells you, one line each, what still needs
  resolving and who does it. It only reads.
- **Protect** (`repos.py protect`, offered by setup and publish, always after asking): adds a rule on
  the public repo's `main` that stops anyone force-pushing or deleting it.

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
| **node** (optional) | adopt only, to compare a repo's own builder with this one |

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
