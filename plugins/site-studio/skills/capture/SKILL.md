---
name: capture
description: 'Save one public web page the person names as a reference and preview card, logged out, one page per URL. Use to bring in a post, article or old page. Never crawls, never signs in; a profile comes in through import-profile. Not for adding a whole piece of work (add-work).'
---

# Capture

`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/capture.py" <url> …` saves each page the person named into
`content/references/<slug>/`: `reference.json` (the URL, title, description, site, published date,
kind and capture date), `text.md` (raw material, never published as it is) and a card image.

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

After capture, show the card and the saved fields. The card is public once a page uses it, so it
goes through `/site-studio:review` like any image. A profile (LinkedIn or similar) is not captured
here: the person downloads their own copy, and `/site-studio:import-profile` reads it.
