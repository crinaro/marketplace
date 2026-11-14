---
name: preview
description: 'Show the person their site as it will look, drafts included, before anything is published. Use whenever they want to see a change. Not for the checks before publishing (review).'
---

# Preview

`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/preview.py"` builds the site with drafts into a temporary
folder, serves it on `127.0.0.1` under `/<repo>/` (the same path the published project site uses,
so a link that only works at the root shows up here), and prints the URL. Nothing is published,
and the preview build has no digest: a preview is never reviewed or published.

By where the session runs:

- **The desktop app:** open the printed URL in the app's browser pane, and also give the URL.
- **A terminal:** give the URL for the person to open.
- **A cloud session:** there is no browser to hand over. Run `render.py` on the pages the person
  asked about and show the screenshots instead.

Leave the server running while the person looks; stop it when they are done. Drafts are visible
here and nowhere else. If the person wants the site checked, that is `/site-studio:review`.
