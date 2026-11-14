# Privacy and your data: site-studio

site-studio builds and publishes your personal site from your own repositories. This page says what
it reads, what it writes, where that goes, and who sees it.

## What it reads

- The files in **your private dev repo**: your content, photos, brand notes, decisions, resume and
  settings (`site/site.json`).
- Files you point it at: media for a piece of work, a profile export you downloaded yourself.
- A public web page, only when you name its address for a capture. It loads that page in a fresh
  Chrome profile, signed out, one page per address. It never crawls and never signs in.
- Your git settings (name, email) and whether `gh` is signed in, to tell you what is missing. It does
  not read your credentials.

## What it writes

- In your dev repo: your content and settings as you direct, a record of each privacy review under
  `.site-studio/`, and the built site in `site/dist/` (not committed).
- In your **public repo**: the generated site files, and only after the publish step you confirm.
  Everything there is public.
- Temporary Chrome profiles and a local preview on `127.0.0.1`, both removed or private to your
  computer.
- On request, a small decision log under the plugin's data folder, for testing the publish
  confirmation. It records the time, permission mode and decision, never your content.

## Where it sends things

- **To GitHub**, through your own `gh` sign-in: creating the two repositories, enabling Pages, and
  the publish push and its status check. Your content reaches the public repo only by publishing.
  Publishing uses your own login; the plugin holds no separate key.
- **To the public address you name**, when you ask for a capture.
- **To nobody else.** There is no server of ours, no telemetry and no analytics. The plugin's
  authors, and the marketplace's owner, never receive your data, your content or your site.

## What the Pages check reads from GitHub

The Pages check (and the one-line summary in the doctor report) only reads, with `GET` requests
through `gh`. About fifteen at most, all about your **public** repo: the repo's details (visibility,
archived, your permission), its Pages settings and the DNS health of its custom domain, the rules
and rulesets in effect on `main`, classic branch protection on `main`, and who can write to it: its
collaborators (their logins), its teams for an organisation repo, its deploy keys, and your own login
name. That information is shown to you and to Claude in your session. It is not sent anywhere else
and not stored by the plugin. The check never runs from a start-up hook.

Before a publish push, the publish script also reads the public repo's details and its remote
branch and tag list (`gh api` and `git ls-remote`), to confirm it is pushing where `publicRepo` says.

**Nothing is written to GitHub except where you say yes:** `POST /pages` once, at the first publish,
to turn Pages on; the ruleset on `main` or, on a plan without rulesets, classic branch protection,
only when you confirm `protect` or `protect --classic` (and `protect --fix`, to restore it); and the
publish push to `main`, after you confirm it.

## What Claude sees

What the plugin reads in a session (your files, screenshots of your pages, the text of your PDFs) is
part of your conversation with Claude, and is handled under your Claude account's terms and privacy
settings. The privacy reader inside the plugin looks at your built pages and PDFs before you publish,
to catch a personal detail you did not mean to share. Its list of what it opened is its own report, so
read the review before you confirm.

## How long it keeps it

Until you delete it. The plugin keeps nothing outside your own repositories and the temporary files
above. Uninstalling it leaves your repositories as they are.

## Who it is for

site-studio is not intended for anyone under 18.

## Contact

Questions about this page: open an issue on the marketplace repository named in this plugin's
manifest (`repository`), or use the contact address its `author` field gives.
