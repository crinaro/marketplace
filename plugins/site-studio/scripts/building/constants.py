"""Fixed names and limits the builder reads: the extensions, the plugin's own output files, the
placeholders `accept` stands in with."""


PLUGIN_ASSETS = {"css": "site-studio/blocks.css", "js": "site-studio/video.js",
                 "schema-4": "site-studio/schema-4.css"}

JUNK_NAMES = (".DS_Store", "Thumbs.db")

HTML_EXTS = (".html", ".htm")

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp")

SIZES_ATTR = "(min-width: 60rem) 60rem, 100vw"

PREVIEW_SITE_URL = "http://localhost"

DEFAULT_ASSET_NOTE = "unreadable image dimensions"

ACCEPT_YEAR = 2000          # a placeholder: `accept` writes and publishes nothing, and `{{year}}` is its only reader

ACCEPT_PREVIEW_URL = "https://example.invalid"      # stands in for a missing previewUrl, once it is reported
