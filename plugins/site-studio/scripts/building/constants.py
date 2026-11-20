"""Fixed names and limits the builder reads: the extensions, the plugin's own output files, the
placeholders `accept` stands in with."""

import os

# The scripts directory: this file sits one level below it (it was `HERE` in build.py, where the file was in the directory itself).
SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PLUGIN_ASSETS = {"css": "site-studio/blocks.css", "js": "site-studio/video.js",
                 "schema-4": "site-studio/schema-4.css",
                 "schema-5": "site-studio/schema-5.css"}     # design-movement-view 4.2: the five 0.5.0 constructs only

JUNK_NAMES = (".DS_Store", "Thumbs.db")

HTML_EXTS = (".html", ".htm")

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp")

SIZES_ATTR = "(min-width: 60rem) 60rem, 100vw"

PREVIEW_SITE_URL = "http://localhost"

DEFAULT_ASSET_NOTE = "unreadable image dimensions"

ACCEPT_YEAR = 2000          # a placeholder: `accept` writes and publishes nothing, and `{{year}}` is its only reader

ACCEPT_PREVIEW_URL = "https://example.invalid"      # stands in for a missing previewUrl, once it is reported

# The plugin's own output files (site-fidelity section 7.7): the block stylesheet and the facade script live in
# the PLUGIN at templates/output/, are copied into a site's output only when a page uses a block, and never
# touch the person's source. Each is `{kind: (path under templates/output/ and in the output)}`.
OUTPUT_TEMPLATES = os.path.normpath(os.path.join(SCRIPTS_DIR, "..", "templates", "output"))

# The content model that SHIPS (dev #876): `reference/content-model.md`, generated from the code's own tables by
# tests/gen_content_model.py and checked against them by tests/test_content_model_generated.py. It is found from this
# file's own location, never from ${CLAUDE_PLUGIN_ROOT}, which Claude Code does not set in the environment of a
# command run through the Bash tool. A message that points a person at it names this absolute, installed path.
CONTENT_MODEL = os.path.normpath(os.path.join(SCRIPTS_DIR, "..", "reference", "content-model.md"))
