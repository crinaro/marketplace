"""adoption.accepts -- the ACCEPT candidates still open: the `open` member of the plan's `parity` (design-adopt-parity-2 7.3, 3.2).

Part of the `adoption` package behind the entry point `adopt.py`.

`parity` ends with one list, the ACCEPT candidates: every visible difference no setting, look or carried page removed. It is
printed from two members of the plan's `parity`: `accepts`, 0.5.0's description rows, unchanged; and `open`, which this module
computes from the measure. Nothing in it is a judgement: each row is a visible difference of the final P2 (`classify_p2`'s
`differences`, `compare_builds`' words), one per path, in the closed shape plan schema 3 stores:

    {"kind": "page" | "file" | "unlinked", "path": "<output path>", "what": "<one line>"}, exactly those three keys,
    sorted by kind (in that order) then path.

    page      a page that reads DIFFERENT, or that only one build has (`.html`/`.htm`); the pictures (`adoption/shots.py`) are
              made of these rows only
    file      an address the old build served that the plugin's does not, linked by at least one old page; also any other
              file a visitor's page loads that differs between the builds or that only the plugin's build serves (design 7.3
              names only the first; the others are visible differences too, so they are rows, never silent: dated note
              2026-11-21, step 9b)
    unlinked  an address the old build served that the plugin's does not, which no old page links

A cause the plugin states about itself is said ON the row it explains (owner decision 4, design 12): a portfolio whose groups use
different unit words prints each group's count without its word (`settings.work_count_words` writes no words, and the conversion
note says why, "the count prints alone"); the `page` rows that count prints on (the portfolio's index, and the home when its
featured shelf is grouped) carry that reason in their `what`, so the difference is an ACCEPT row with its reason, never silent.

    open_rows(differences, local, site_path, notes)  the rows
    open_lines(parity)                               the lines `parity` and `check` print for them, the set-apart tiles last
    accent_lines(parity)                             probe P-A's limit (0.7.0, section 6.5) as ACCEPT rows
    page_paths(rows)                                 the `page` rows' paths
    sides_of(differences, path)                      which builds have that page: ("old", "new"), ("old",) or ("new",)
"""

import html.parser
import re
import urllib.parse

from parityscan.sameresource import build_path, file_for, resolve, srcset_candidates

OPEN_KINDS = ("page", "file", "unlinked")
OPEN_KEYS = ("kind", "path", "what")
ONLY_OLD = "only in the local build"            # `parity_classes.compare_builds`' words
ONLY_NEW = "only in the plugin build"
_PAGE = (".html", ".htm")
_UNWRITTEN = re.compile(r"^groupCount of (\S+): the words are not written \((.*); the count prints alone\)$")


def _is_page(path):
    return path.lower().endswith(_PAGE)


class _Links(html.parser.HTMLParser):
    def __init__(self):
        html.parser.HTMLParser.__init__(self, convert_charrefs=True)
        self.found = []

    def handle_starttag(self, tag, attrs):
        for k, v in attrs:
            if k in ("href", "src") and v:
                self.found.append(v)
            elif k == "srcset" and v:
                self.found.extend(u for u, _d in srcset_candidates(v))

    handle_startendtag = handle_starttag


def linking_pages(local, path, site_path=None):
    """The old pages (sorted) holding an `href`, `src` or `srcset` address that the old build serves `path` for, each read from
    its own page under the path the old build's output assumes (`sameresource.build_path`, rule U-a's reading)."""
    base = build_path(local, site_path)
    out = []
    for page in sorted(p for p in local if _is_page(p)):
        p = _Links()
        p.feed(local[page].decode("utf-8", "replace"))
        p.close()
        for a in p.found:
            r = resolve(page, a, base)
            if isinstance(r, tuple) and len(r) == 3 and file_for(urllib.parse.unquote(r[0]), {path: b""}) == path:
                out.append(page)
                break
    return out


def count_causes(notes):
    """{output page: reason} from the conversion's settings notes: the pages whose group counts print without their word."""
    notes = list(notes or ())
    grouped_home = any(n.startswith("featuredView: grouped") for n in notes)
    out = {}
    for n in notes:
        m = _UNWRITTEN.match(n)
        if not m:
            continue
        why = ("each group's count prints without its word, because site-studio writes no words here (%s): which word a group "
               "gets is not a site-studio feature" % m.group(2))
        for page in ["%s/index.html" % m.group(1)] + (["index.html"] if grouped_home else []):
            out[page] = why
    return out


def open_rows(differences, local, site_path=None, notes=()):
    """The ACCEPT candidates of one measure: `differences` is `classify_p2`'s list of visible differences (`[kind, path, detail]`),
    `local` the old build (`{path: bytes}`, for which old pages link a vanished file), `site_path` the path the plugin's build
    is served under (None the root), `notes` the conversion's settings notes. Sorted rows of exactly `OPEN_KEYS`."""
    causes = count_causes(notes)
    rows = []
    for kind_, path, detail in differences:
        if _is_page(path):
            what = ("only the old build has this page" if kind_ == ONLY_OLD else
                    "only the plugin's build has this page" if kind_ == ONLY_NEW else
                    "reads DIFFERENT (%s)" % (detail or "the bytes differ"))
            if path in causes:
                what = "%s; %s" % (what, causes[path])
            rows.append({"kind": "page", "path": path, "what": what})
        elif kind_ == ONLY_OLD:
            linked = linking_pages(local, path, site_path)
            rows.append({"kind": "file", "path": path,
                         "what": "the old build served it and the plugin's does not; %d old page(s) link it, first %s"
                                 % (len(linked), linked[0])} if linked else
                        {"kind": "unlinked", "path": path,
                         "what": "the old build served it and the plugin's does not; no old page links it"})
        else:
            rows.append({"kind": "file", "path": path,
                         "what": "only the plugin's build serves it" if kind_ == ONLY_NEW else
                                 "differs between the two builds (%s)" % (detail or "the bytes differ")})
    return sorted(rows, key=lambda r: (OPEN_KINDS.index(r["kind"]), r["path"]))


def page_paths(rows):
    return [r["path"] for r in rows or () if r["kind"] == "page"]


def sides_of(differences, path):
    """Which builds have the page `path` of an `open` row: ("old", "new"), or the one build that has it."""
    for kind_, p, _detail in differences or ():
        if p == path and kind_ == ONLY_OLD:
            return ("old",)
        if p == path and kind_ == ONLY_NEW:
            return ("new",)
    return ("old", "new")


def _address(path):
    folder = re.sub(r"(?:^|/)index\.html?$", "", path).strip("/")
    return "/%s/" % folder if folder else "/"


TILE_ROW = ("  tile: %s (the home and about pages' front matter is a closed key list and a tile line "
            "has no field for a mark, so no look entry can name this position; parity counts the class as markup a visitor does not "
            "see, and the record lists it)")


def accent_lines(parity):
    """Probe P-A's limit as rows of the ACCEPT list (section 6.5): each line of `parity["accents"]` (`lookperson.accent_lines`: "tile
    <n> of <m> on <page> carries a class the others lack; a look sets apart the first or the last"), whatever the verdict, because
    a class alone does not make parity DIFFERENT. Nothing when there is none."""
    rows = list((parity or {}).get("accents") or ())
    if not rows:
        return []
    return ["ACCEPT: %d tile(s) set apart at a position no look can name:" % len(rows)] + [TILE_ROW % r for r in rows]


def open_lines(parity):
    """The lines `parity` and `check` print for the open ACCEPT candidates of a parity result or a stored parity: each row, and per
    `page` row the two things a person can do about that page alone; `file`, `unlinked` and description rows have no picture and
    each says so; then the set-apart tiles no look can name (`accent_lines`, 0.7.0). Nothing for a measure with none, and no
    `open` row for a verdict that is not DIFFERENT."""
    rows = (parity or {}).get("open") or []
    if not rows or parity.get("verdict") != "DIFFERENT":
        return accent_lines(parity)
    out = ["ACCEPT candidates: %d visible difference(s) no setting, look or carried page removed. `adopt.py parity --keep <dir>` "
           "makes the pictures of each page, old beside new, and `adopt.py parity --accept --shots <dir>/shots` then accepts every "
           "one at once (the description rows above are accepted with them):" % len(rows)]
    for r in rows:
        if r["kind"] == "page":
            out.append("  page %s (%s): %s" % (_address(r["path"]), r["path"], r["what"]))
            out.append("    about this page alone: keep it as you wrote it (`adopt.py setting carried %s`), or keep your own builder"
                       % r["path"])
        else:
            out.append("  %s %s: %s (a %s, so it has no picture)" % (r["kind"], r["path"], r["what"],
                                                                    "file" if r["kind"] == "file" else "file no page links"))
    return out + accent_lines(parity)
