---
name: setup
description: 'Create the site''s two repositories, turn on GitHub Pages and an optional custom domain, and get this computer ready, one plain step at a time. Not for a site repo that already carries its own copy of the tools (adopt).'
disable-model-invocation: true
---

# Set up a site

The person typed this. Go one step at a time. Before each step, say in one plain sentence what it
does. Ask before every install. Every password is typed by the person into the system's own
prompt, never into this chat. Never run `sudo`.

Every script runs as `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/<name>.py"`.

## Step 1: this computer

Run `doctor.py` and read its report. Fix only what it reports, by platform:

- **macOS:** the Command Line Tools (`xcode-select --install`, which brings git and Python); then
  the GitHub CLI `gh` (GitHub's macOS installer, or Homebrew if it is already there); then
  `gh auth login` and `gh auth setup-git`; then Chrome, into `/Applications`, or into
  `~/Applications` when the person has no admin rights.
- **Linux:** do not guess the package manager and do not run the install. Name what is missing and
  point at the vendor pages: `git` and `python3` 3.9 or newer from the distribution; `gh` from
  GitHub CLI's Linux install page; Chrome or Chromium on `PATH`, or `CHROME_PATH` set. The person
  runs the install. Then `gh auth login` and `gh auth setup-git`.
- **Windows:** say `doctor.py`'s one sentence (Windows is not supported yet) and stop setup here.
- **1b, only if this plugin's browser tools are the Node fallback** (ADR-001 says whether): say
  that it installs Node's Playwright library into the plugin's own data folder and how large it
  is, and ask. Install on yes; on no, install nothing.

Run `doctor.py` again. Go on only when its report is clean, or the person chooses to go on without
Chrome (then adding photos and capturing pages will refuse until Chrome is there; say so).

## Step 2: the owner, the name, and the paper size

- The owner: the person's own GitHub account or an organization.
- The site name. Explain the two kinds of GitHub Pages site plainly: the account's own site,
  served at the root of `<owner>.github.io`, or a project site, served under `/<repo>/` until a
  custom domain is set.
- The resume paper size, Letter or A4. Ask; do not guess it from the computer's language.

## Step 3: the two repositories

`repos.py create`. It makes the private dev repo (`<name>-dev`) and the public repo (`<name>`),
fills the dev repo from the plugin's starter site, commits and pushes it.

Then confirm, by reading the files, that the dev repo has:

- **its `CLAUDE.md` pointer line, exactly:**

  `If /site-studio commands are unknown, this session does not have the plugin (cloud sessions do not install repo-declared plugins); open the repo on your own computer.`

- **`.gitignore`** with `.claude/worktrees/` (the desktop app keeps session worktrees inside the
  repo), `site/dist/`, `.site-studio/review/` and `originals/`;
- **`.claude/settings.json`** registering this plugin from its marketplace (so a fresh clone
  carries it), with ask rules for the deploy script, `repos.py protect` and `repos.py
  first-publish`, `git push`, `gh secret set` and `gh api` write calls. These rules are a second
  tripwire behind the plugin's own publish guard, not a security boundary.

If any of the three is missing, say which and stop: that is a defect in the plugin to report, not
something to patch by hand here.

## Step 3b: protect the public site's `main` (optional; ask first)

Say in one sentence: "This stops anyone, you included, from force-pushing to the public site's
`main` or deleting it; publishing still works, because it only adds commits." Ask. Run it on yes,
and only on yes:

`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/repos.py" protect`

Read out what it printed. Its exit code says what happened:

- **0:** the protection is in place, or was just added.
- **3:** a ruleset of that name exists but differs from the plugin's. Read out each difference, ask,
  and on yes run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/repos.py" protect --fix`.
- **5, GitHub's rulesets are not available on this plan:** say "GitHub's rulesets are not available
  on this plan; classic branch protection gives the same two protections (no force-push, no
  deletion) and publishing still works." Ask, and on yes run
  `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/repos.py" protect --classic`. If that is refused too, or
  the person says no, report it as **not available on this plan** and go on: `main` is not
  protected against force-push or deletion, and publishing still works.
- **1, any other refusal** (most often "only an admin of the repo can add this"): read out its
  line, which names where to add the protection by hand, and go on.

A "no" is respected for the rest of the session. Protection is never a condition of publishing.

## Step 4: the first publish, and what is left on GitHub's side

`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/repos.py" first-publish`. It builds and checks the starter
site, pushes it to the public repo, turns on Pages from `main`, and reads back the first Pages
build. Report what it printed; a build still running after its wait is said as "not live yet",
never as live.

Then run the Pages check, which only reads and never changes anything:
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/pages_check.py"`. Read out every line it printed, each with
the "Who" it names (for example "you" or "GitHub"), and its summary line. Exit 3 is amber, not a
failure: it means something is still to resolve or still waiting. Exit 1 means the check could not
run; say why, and go on. On a new site a build that is still running, or a rule to add, is normal.

## Step 5: a custom domain (optional)

Only if the person wants one. The split is fixed: the plugin edits `site/site.json` and checks;
**the person does everything at GitHub and at the DNS provider.** The plugin never verifies the
domain, never sets the Pages custom domain and never turns on HTTPS. It makes no write call for
any of them, so there is nothing for it to retry or repair.

1. **The plugin:** set `domain` in `site/site.json` and leave `cutover` false for now. Run
   `pages_check.py`: it says the domain is planned.
2. **The person, verifying the domain** (this stops anyone else publishing on it): add the DNS TXT
   record GitHub shows under the profile's (or the organization's) Settings, then Pages, then Add a
   domain, and press Verify there. Read out the exact line `pages_check.py` prints; do not invent
   a record name.
3. **The person, at the DNS provider:** add the records `pages_check.py` names for an apex or a
   subdomain. Wait for the person to say the DNS is changed.
4. **The plugin:** set `cutover: true`. The person publishes with `/site-studio:publish` (the
   build then writes the `CNAME` file).
5. **The person, the custom-domain field:** if `pages_check.py` says Pages has no custom domain,
   they type the domain under the repo's Settings, then Pages, then Custom domain, and save.
   Saving adds a commit with a `CNAME` file to `main`. Say that this is expected and harmless: the
   next publish replaces the whole tree and carries the same file.
6. **The person, Enforce HTTPS:** tick it under the repo's Settings, then Pages, once GitHub offers
   it. That can take up to a day after the certificate is issued.

After every action of the person's, run `pages_check.py` again and read out what it still says.
**Loop until the only lines left are waits** (GitHub checking DNS, or getting the certificate), then
say plainly what is still waiting and who it waits on, and stop. Do not poll for hours: tell the
person to run `pages_check.py` again later. A to-resolve line is theirs to fix; read it, say who
fixes it, and wait for them.

## Step 6: say plainly

GitHub Pages is for a personal or project site, not for running an online business. Say so if the
person describes a shop or a paid service.

Record in `HANDOFF.md`: the two repos, the Pages URL, whether `main` is protected, the domain
state, and what `pages_check.py` last said was still to resolve or waiting.
