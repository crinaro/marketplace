# Rules for this repo

This is the private dev repo for the site "@@SITE_TITLE@@". It builds the public site `@@PUBLIC_REPO@@`. It was set up by the site-studio plugin.

If /site-studio commands are unknown, this session does not have the plugin (cloud sessions do not install repo-declared plugins); open the repo on your own computer.

- Content lives in `content/`, the page shell and static pages in `site/`. Notes, drafts and decisions stay in this repo; only the built site is ever public.
- The site is published only by typing `/site-studio:publish`, which asks you before anything goes live.
- Never edit `site/dist/` (it is rebuilt) or the public repo by hand.
- Nothing personal goes into a page unless you want it public forever: no home address, no private phone number, no photo with a location in it.
- `site/site.json` is written by the plugin; change settings through its commands.
