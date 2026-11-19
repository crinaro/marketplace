"""pagesettings: the check of a page's settings keys (`order`, `tagline`, `sort`, `menuLinks`, `view` and the
schema-4 keys) in a `page.md` front matter or a portfolio settings object."""

from configschema.configkeys import (
    ONE_PIECE_INDEXES,
    PAGE_MENU_LINKS,
    PAGE_SORTS,
    PAGE_VIEWS,
    V3_PAGE_DEFAULTS,
    V4_PAGE_VIEWS,
)
from configschema.diagnostics import make_problem


def page_settings_problems(raw, where, schema=3):
    """Every problem in the schema-3 portfolio keys of a `page.md` (`order`, `tagline`, `sort`, `menuLinks`,
    `view`) and, at `schema` 4 and above, `mapMask`, `onePieceIndex` and the three further `view` values, as (problems,
    settings). `raw` holds only those keys; `where` is the page's path. `settings` is fully defaulted (a
    schema-4 key is in it only when `raw` holds it, so a schema-3 settings dict is what it was). The value rules
    are the design's section 6.2 table, and every refusal names its fix. `schema` is the declared schema of the
    site, DEFAULT 3 so a caller that does not pass it keeps the schema-3 reading (`content.py` passes the site's
    schema once it builds the schema-4 views): below 4 a `mapMask` or `onePieceIndex` is ignored here (the tree check refuses it
    with the schema named) and the `view` values stay `grid` and `page`."""
    out = dict(V3_PAGE_DEFAULTS)
    probs = []

    def bad(key, found, expected, fix):
        probs.append(make_problem("%s: '%s' %s" % (where, key, expected), where, found, expected, fix))
    for key, val in raw.items():
        if key == "order":
            if isinstance(val, bool) or not isinstance(val, int):
                bad(key, repr(val), "must be a whole number, such as 2", "write order as a whole number, such as order: 2")
            else:
                out[key] = val
        elif key == "tagline":
            if not isinstance(val, str) or not val.strip() or "\n" in val:
                bad(key, repr(val), "must be one line of text", "write tagline as one line of text")
            else:
                out[key] = val.strip()
        elif key == "mapMask":
            if schema < 4:
                continue
            if (not isinstance(val, str) or not val.strip() or val != val.strip() or val.startswith("/")
                    or "\\" in val or ".." in val.split("/") or "//" in val or val.endswith("/")):
                bad(key, repr(val), "must be a path inside the portfolio folder, such as media/land.txt",
                    "write mapMask as a relative path with no .. and no leading or trailing /")
            else:
                out[key] = val
        elif key == "onePieceIndex":
            if schema < 4:
                continue
            if val not in ONE_PIECE_INDEXES:
                names = " or ".join('"%s"' % a for a in ONE_PIECE_INDEXES)
                bad(key, repr(val), "must be %s" % names, "set %s to %s" % (key, names))
            else:
                out[key] = val
        else:
            allowed = {"sort": PAGE_SORTS, "menuLinks": PAGE_MENU_LINKS, "view": PAGE_VIEWS}.get(key)
            if allowed is None:
                continue
            if key == "view" and schema >= 4:
                allowed = PAGE_VIEWS + V4_PAGE_VIEWS
            if val not in allowed:
                names = " or ".join('"%s"' % a for a in allowed)
                bad(key, repr(val), "must be %s" % names, "set %s to %s" % (key, names))
            else:
                out[key] = val
    return probs, out
