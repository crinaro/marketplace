---
name: capture
description: 'Save one public web page the person names as a reference and preview card, logged out, one page per URL. Use to bring in a post, article or old page. Never crawls, never signs in; a profile comes in through import-profile. Not for adding a whole piece of work (add-work).'
---

# Capture

`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/capture.py" <url> …` saves each page the person named into
`content/references/<slug>/`: `reference.json` (the URL, title, description, site, published date,
kind and capture date, and the person's role, project, type and channel for it when they gave them), `text.md` (raw material, never
published as it is) and a card image. After each page it prints a **suggested layout** (below); the suggestion is never saved by itself.

The rules, all enforced by the script:

- **One page per URL, the URLs the person gave.** Never follow links, never crawl.
- **Logged out**, in a fresh browser profile. A page that needs a login is reported as "not
  publicly viewable" and is not captured. Never sign in, and never ask for a password.
- A 45-second limit per page.
- **It needs Chrome.** With no Chrome, it refuses and names the install step.
- **An unlisted Vimeo link** (`vimeo.com/<id>/<code>`) is loaded from its player with the code, so the video the person named is the
  one captured. Capture publishes nothing; the code stays in `reference.json`'s `url` as they gave it.
- **In a cloud session**, capture works only when the session's network allows the site; when it
  does not, the script names the blocked host and the two fixes. Say them.

For the person's own old site, you may read that site's `sitemap.xml` to list its pages, and the
person picks which to capture. That is a list they approve, not a crawl.

### Ask what they did on it

Before you capture a page, ask the person one question about it: **"What did you do on this?"** A
reference card shows the answer as a short role line (for example "Wrote the feature and art-directed
its photographs"), so it should be a few words in the person's own voice, on one line. Pass it as
`--role "<their words>"`, one page at a time (`--role` takes exactly one URL). Write only what they
said: never guess a role from the page, and never fill one in for them. If they have nothing to say
about a page ("I only want it listed"), leave `--role` off and the reference has no role line.

`role` is a schema 4 setting. On a site whose `site/site.json` says a lower schema, `capture.py` refuses
the `--role` run before it opens a browser, writes nothing, and says so. Tell the person, and offer to raise the site first with
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/build.py" raise-schema --to 4 --repo <dev repo>` (show its report
and wait for their yes, as `/site-studio:add-work` does), then capture again. If it prints `NOT CHECKED`
(the site's schema could not be read), say that to the person too: the role is stored, and the build
refuses it unless the site is at schema 4. To add or change a role on a page already captured, edit the
`role` line in its `reference.json` (again, only on a site at schema 4).

### The suggested layout: which piece, what it is, where it was seen

After every page the script prints a block headed `suggested layout`. It names three keys, each with where its value came from, so the
facts sit in their own keys before the site's look changes:

- `project`: which of the site's pieces the reference is for. The block lists the site's pieces (the first ten). **Ask the person
  "Which piece is this for?"** and show that list. Never pick one for them; "none" or "not sure" is an answer, and leaves it out.
- `type`: what it is (`type Post (the address)`). `channel`: where its audience saw it (`channel Instagram (the address)`). They come
  only from the address (`instagram.com/p/…` is an Instagram post); a link to a file host such as Vimeo or Google Drive gives no
  channel, because the address cannot say where it was seen, and an address the plugin does not know gives neither. Say each in plain
  words and ask for a yes or a better word: the person may use their own (**one line, 80 characters at most**), and when the site sets
  its own list of types or channels, one of those.

**Nothing in the block is saved until the person says yes.** For each word they confirm or give, run capture again for that page with
`--force --name <the name that leads the block> --project "<piece>" --type "<word>" --channel "<word>"` (only the flags they gave; `--force` keeps
everything else in the reference, `role` included, when the address is the same). Write only their words, never the suggestion on its own
authority. They may also say no to all three; a reference with none of them is complete.

**Below schema 9** the block still prints, headed "to keep this, the site must be at schema 9". The three keys are a schema 9 setting,
exactly as `role` is a schema 4 one: run
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/build.py" raise-schema --to 9 --repo <dev repo>`, show its report, and **wait for their yes**
before capturing again with the flags (the flags are refused, before any browser starts, on a site below 9). Tell the person plainly that
a site at schema 9 can no longer be read by an older site-studio, though nothing a visitor sees changes. If the block says `NOT CHECKED`, the
site's schema could not be read: tell the person, and note that the build refuses these keys unless the site is at schema 9. A hub or
custom site gets one line and takes none of the flags: its references are not loaded.

After capture, show the card and the saved fields (the role included). `captured` is the date the page was captured; `fetched`, when a
reference has one (adopting an old site writes it), is the address the reference was captured from. Neither is printed on the site. The card is public once a page uses it, so it
goes through `/site-studio:review` like any image. A profile (LinkedIn or similar) is not captured
here: the person downloads their own copy, and `/site-studio:import-profile` reads it.
