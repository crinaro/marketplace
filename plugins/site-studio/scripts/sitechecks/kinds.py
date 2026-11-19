"""kinds.py -- the file kinds and name lists the site gate judges a published tree by: text and image
extensions, files that must never be published, junk names, font files and their licences.
"""


TEXT_EXTS = (".html", ".htm", ".css", ".js", ".mjs", ".svg", ".txt", ".xml", ".json", ".webmanifest",
             ".md", ".py", ".yml", ".yaml", ".toml", ".jsonl", ".cfg", ".ini", ".csv", ".sh")
SITE_TEXT_EXTS = (".html", ".htm", ".css", ".js", ".mjs", ".svg", ".txt", ".xml", ".json",
                  ".webmanifest", ".map")
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
BAD_IMAGE_EXTS = (".heic", ".heif", ".tif", ".tiff", ".bmp", ".raw", ".cr2", ".nef", ".dng")
KNOWN_GENERATORS = ("chromium", "chrome", "skia/pdf", "headlesschrome", "google chrome")
VIDEO_HOSTS = ("www.youtube-nocookie.com", "player.vimeo.com", "drive.google.com")
ROOT_EXEMPT = ("robots.txt", "sitemap.xml", "CNAME", ".nojekyll", "404.html")
FONT_EXTS = (".woff2", ".woff", ".ttf", ".otf")


def is_font_licence(name):
    """A licence file a font's licence requires to travel with it: OFL.txt, LICENSE*, *.license
    (case-insensitive, on the file's base name). Only the NAME is judged here; the caller also
    requires a font file in the same folder (dev #891)."""
    low = name.lower()
    return low == "ofl.txt" or low.startswith("license") or low.endswith(".license")
FORBIDDEN_NAMES = ("CLAUDE.md", "HANDOFF.md", "BRAND.md", "site.json", "layout.html", "text.md",
                   "reference.json", "package.json", "package-lock.json")
FORBIDDEN_DIRS = (".git", ".site-studio", ".github", "decisions", "originals", "node_modules",
                  "__MACOSX", "templates")
JUNK_NAMES = (".DS_Store", "Thumbs.db", "desktop.ini")
JUNK_SUFFIXES = ("~", ".bak", ".orig", ".part", ".tmp", ".swp", ".md", ".pdf.json", ".jsonl", ".py")
