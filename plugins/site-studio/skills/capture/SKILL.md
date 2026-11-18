---
name: capture
description: 'Save one public web page the person names as a reference and preview card, logged out, one page per URL. Use to bring in a post, article or old page. Never crawls, never signs in; a profile comes in through import-profile. Not for adding a whole piece of work (add-work).'
---

# Capture

`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/capture.py" <url> …` saves each page the person named into
`content/references/<slug>/`: `reference.json` (the URL, title, description, site, published date,
kind and capture date, and the person's role on it when they gave one), `text.md` (raw material, never published as it is) and a card image.

The rules, all enforced by the script:

- **One page per URL, the URLs the person gave.** Never follow links, never crawl.
- **Logged out**, in a fresh browser profile. A page that needs a login is reported as "not
  publicly viewable" and is not captured. Never sign in, and never ask for a password.
- A 45-second limit per page.
- **It needs Chrome.** With no Chrome, it refuses and names the install step.
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

After capture, show the card and the saved fields (the role included). The card is public once a page uses it, so it
goes through `/site-studio:review` like any image. A profile (LinkedIn or similar) is not captured
here: the person downloads their own copy, and `/site-studio:import-profile` reads it.
