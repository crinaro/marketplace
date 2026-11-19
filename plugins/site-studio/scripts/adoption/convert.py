"""adoption.convert -- the conversions adopt applies to a tree: value, key and layout rewrites, the converted site files.

Part of the `adoption` package behind the entry point `adopt.py`. Documentation that was in `adopt.py`'s docstring about this module's code:

APPLY NORMALISES THE MECHANICAL PROBLEMS AND LISTS EACH (dev #855, design 7.2). A clone-URL `publicRepo`
becomes `owner/name` (through `github_url.slug`), a `previewUrl` loses its trailing slash, a `content/<f>/`
with no `page.md` is renamed `content/_<f>/` (kept as source material, not built; `adopt.py folder <f>
portfolio` adds a `page.md` instead), and `[key, label]` pairs become the `work.labels` map. Every one is a
line of the commit. For each replaced value, a literal search of the files the person KEEPS (not the retired
copies) names `file:line` under "your own script may depend on the old form". Anything that is not
mechanical (an unknown key, a non-https previewUrl) is never rewritten: it stays `you decide`.
"""

import hashlib
import json
import posixpath
import re

from contentmodel import grammar, keytables, layout  # noqa: E402
import github_url  # noqa: E402
from configschema import canonical, configkeys, diagnostics, model, treeschema, workcheck  # noqa: E402

from adoption.base import Refused
from adoption.dispose import apply_dispositions, conv_name
from adoption.blocks import block_rewrites, blocks_left
from adoption.settings import apply_settings, showcase_pieces
from adoption.template import (
    RESUME_OWNED_KEYS, home_key_rewrite, home_path, nav_token_rewrites, page_file_renames, person_name_change,
    reference_rewrites, resume_header_rewrite, resume_pdf_rename,
)
from adoption.tree import Overlay, TreeFiles
from adoption.tokens import (
    detect_resume, home_feed, portfolio_folders, rewrite_tokens,
    site_json_labels, token_files,
)
from adoption.redirects import redirect_pages

# Text files adopt searches for a value it replaced (design 7.2); anything else is left unread.
_TEXT_EXTS = (".sh", ".bash", ".zsh", ".py", ".js", ".mjs", ".cjs", ".ts", ".rb", ".json", ".md", ".yml",
              ".yaml", ".toml", ".html", ".htm", ".txt", ".cfg", ".ini", ".mk", ".csv")
_TEXT_MAX = 512 * 1024


def _converted_dict(tree, data, paper, kind=None):
    """The dict adopt would hand `siteconfig.parse_data`: the person's own site.json keys, plus the
    schema, the engine marker and `resume`, and the site kind the person CONFIRMED (design 7.7: `hub` or
    `custom` is written, `portfolio` is the default and is not, and nothing confirmed writes nothing). Its
    labels, if any, are still in the form they were written in. Returns (dict, detect_resume result)."""
    resume = detect_resume(tree)
    d = dict(data)
    d["schema"] = configkeys.SCHEMA_MAX
    d["engine"] = configkeys.ENGINE_MARKER
    if kind in ("hub", "custom"):
        d["siteKind"] = kind
    if resume["md"]:
        d["resume"] = {"path": resume["md"], "pdf": resume["pdf"]}
        answer = paper or resume["paper"]
        if resume["pdf"]:
            d["resume"]["paper"] = answer or "Letter"     # `prepare` refuses to apply while this is still a guess
        elif answer:
            d["resume"]["paper"] = answer
    else:
        d["resume"] = None
    return d, resume


def label_conversions(work):
    """Normalise a local site.json `work` object (design-site-adoption section 5): a `[key, label]`
    pair, or a `{"key": ..., "label": ...}` object, in `meta`, `cardMeta` or `groups` becomes the plain
    key, and its label goes into the sibling `labels` map. Returns (new work, [(where, found, key,
    label)]), one row per conversion, for the inventory and the commit to list. Anything that is not
    one of those two shapes is left alone for the parser to refuse."""
    if not isinstance(work, dict):
        return work, []
    out, conv = dict(work), []
    labels = {"meta": {}, "groups": {}}
    existing = work.get("labels")
    if isinstance(existing, dict):
        for part in configkeys.LABEL_PARTS:
            if isinstance(existing.get(part), dict):
                labels[part].update(existing[part])
    for k in ("meta", "cardMeta", "groups"):
        v = work.get(k)
        if not isinstance(v, list):
            continue
        plain = []
        for i, item in enumerate(v):
            pl = None if isinstance(item, str) else workcheck.pair_label(item)
            if pl is None:
                plain.append(item)
                continue
            key, label = pl
            labels["groups" if k == "groups" else "meta"].setdefault(key, label)
            conv.append(("work.%s[%d]" % (k, i), json.dumps(item), key, label))
            plain.append(key)
        out[k] = plain
    if conv:
        out["labels"] = dict((part, m) for part, m in labels.items() if m)
    return out, conv


def normalise_values(d):
    """The mechanical fixes to two site.json values (design 7.2), made IN PLACE on the dict adopt is about
    to parse: a `publicRepo` that is a GitHub clone URL becomes `owner/name` (through `github_url.slug`,
    the one normaliser, never re-parsed here), and a `previewUrl` ending `/` loses the slash. Anything
    else the parser objects to is not touched: it stays `you decide`. Returns [(key, old, new, line)];
    `line` is what the commit lists, with any credential in the old URL removed."""
    out = []
    pr = d.get("publicRepo")
    if isinstance(pr, str) and not configkeys._REPO_RE.match(pr):
        try:
            slug = github_url.slug(pr)
        except github_url.GithubUrlError:
            slug = None
        if slug and configkeys._REPO_RE.match(slug):
            d["publicRepo"] = slug
            out.append(("publicRepo", pr, slug, "publicRepo: %s -> %s" % (github_url.redact(pr), slug)))
    pu = d.get("previewUrl")
    if isinstance(pu, str) and pu.startswith("https://") and pu.endswith("/"):
        d["previewUrl"] = pu.rstrip("/")
        out.append(("previewUrl", pu, d["previewUrl"], "previewUrl: dropped trailing slash"))
    return out


def normalise_redirect_keys(d):
    """Strip ONE trailing `/` from each `redirects` key and each internal target, IN PLACE on the dict adopt is about
    to parse (design-site-fidelity section 5.4, F4). The build writes `<old>/index.html` for a key either way, so
    the same URL is served; `site.json` holds one spelling. A key whose stripped form meets another entry's with a
    DIFFERENT target is left exactly as written (`you decide`). Returns ([(old key, new key, old target, new
    target)], [(key, other key)] collisions)."""
    rd = d.get("redirects")
    if not isinstance(rd, dict):
        return [], []
    strip = lambda s: s[:-1] if isinstance(s, str) and len(s) > 1 and s.endswith("/") else s  # noqa: E731
    want = {}
    for k, v in rd.items():
        nv = v if (not isinstance(v, str) or re.match(r"^https?://", v)) else strip(v)
        want[k] = (strip(k), nv)
    seen, collide = {}, []
    for k, (nk, nv) in want.items():
        if nk in seen and seen[nk][1] != nv:
            collide.append((seen[nk][0], k))
        seen.setdefault(nk, (k, nv))
    bad = set(x for pair in collide for x in pair)
    out, changes, new = {}, [], {}
    for k, v in rd.items():
        nk, nv = want[k] if k not in bad else (k, v)
        out[nk] = nv
        if (nk, nv) != (k, v):
            changes.append((k, nk, v, nv))
    if changes:
        d["redirects"] = out
    return changes, collide


def piece_renames(tree, portfolios):
    """([(content/<p>/<s>/work.md, content/<p>/<s>/index.md)], [folders holding both]) (F2, design-site-fidelity
    section 5.2): each piece folder of a portfolio that holds `work.md` and no `index.md`. A folder holding both is
    never renamed and is `you decide`."""
    paths = set(tree.paths())
    pairs, both = [], []
    for p in sorted(paths):
        parts = p.split("/")
        if (len(parts) == 4 and parts[0] == "content" and parts[1] in portfolios and not parts[2].startswith("_")
                and parts[3] == "work.md"):
            idx = "/".join(parts[:3] + ["index.md"])
            (both if idx in paths else pairs).append(p if idx in paths else (p, idx))
    return pairs, both


_FM_LINE = re.compile(r"^([A-Za-z][A-Za-z0-9_]*):(?:[ \t]+(.*?))?[ \t]*$")
# The template's piece keys that mean one of the build's own (design-site-fidelity section 6.2). The rule every
# row satisfies: the target is one of `shortTitle`, `teaser`, `cover`, `coverPosition`; the source is not a common
# front-matter word (`title`, `name`, `summary`, `description`, `image`, `photo`, `picture`, `text`, `position`,
# `order`, `date`, `tags`, `type`, `kind`, `status`, `featured`, `draft`, `label`, `meta`); a row never overwrites a
# key the piece already has; and it is mechanical only with the fingerprint and under 5.0.3. Amended by design
# template-fidelity 8 P1 (owner decision 9): a deny-listed source key (`summary`) may have a TEMPLATE row, ONLY with the
# fingerprint and a measured P2 (`decide_conversions` holds a TEMPLATE class without one).
PIECE_KEY_SYNONYMS = (("tilePhoto", "cover"), ("summary", "teaser"), ("dates", "period"))      # `summary` (P1, #882): TEMPLATE, fingerprint,
                                                                         # never over an existing `teaser`


def view_key_rewrites(tree, portfolios):
    """{content/<portfolio>/page.md: (new text, the `view` value removed)} for each portfolio page whose front matter
    sets a `view` other than `grid` or `page` (design-site-fidelity sections 6.2 and 10): the plugin does not model that
    index layout, and refuses the key. Removing the line leaves the plugin's grid. It changes the page a visitor
    loads, so it is `you decide` by nature (OPT_IN), and parity builds it to name the page."""
    out = {}
    for name in portfolios:
        path = "content/%s/page.md" % name
        if not tree.exists(path):
            continue
        text = tree.text(path)
        if not text.startswith("---\n"):
            continue
        lines = text.split("\n")
        end = next((i for i, l in enumerate(lines[1:], 1) if l.rstrip() == "---"), None)
        if end is None:
            continue
        for i in range(1, end):
            m = _FM_LINE.match(lines[i].rstrip("\r"))
            if m and m.group(1) == "view":
                val = (m.group(2) or "").strip().strip("\"'")
                if val not in configkeys.PAGE_VIEWS + configkeys.V4_PAGE_VIEWS:
                    out[path] = ("\n".join(lines[:i] + lines[i + 1:]), val)
                break
    return out


def piece_key_rewrites(tree, portfolios, showcase=frozenset()):
    """{piece file path: (new text, [(source key, target key)])} for each piece file (`work.md` or `index.md` in
    `content/<portfolio>/<slug>/`) that carries a PIECE_KEY_SYNONYMS source key and not its target. Only the key
    name on that front-matter line changes: the value, the other lines and the body stay byte for byte. A piece in
    `showcase` (a set of `portfolio/slug`: its portfolio's view is showcase, or the home showcase names it) reads its tile
    picture from `tileImage`, so there `tilePhoto` is `tileImage`, not `cover` (design 8 V1)."""
    out = {}
    for path in sorted(tree.paths()):
        parts = path.split("/")
        if not (len(parts) == 4 and parts[0] == "content" and parts[1] in portfolios and not parts[2].startswith("_")
                and parts[3] in ("work.md", "index.md")):
            continue
        text = tree.text(path)
        if not text.startswith("---\n") and not text.startswith("---\r\n"):
            continue
        lines = text.split("\n")
        end = next((i for i, l in enumerate(lines[1:], 1) if l.rstrip() == "---"), None)
        if end is None:
            continue
        keys = set()
        for l in lines[1:end]:
            m = _FM_LINE.match(l.rstrip("\r"))
            if m:
                keys.add(m.group(1))
        done = []
        for src, dst in PIECE_KEY_SYNONYMS:
            if src == "tilePhoto" and "%s/%s" % (parts[1], parts[2]) in showcase:
                dst = "tileImage"
            if src in keys and dst not in keys:
                for i in range(1, end):
                    if lines[i].startswith(src + ":"):
                        lines[i] = dst + ":" + lines[i][len(src) + 1:]
                        done.append((src, dst))
                        break
        for i in range(1, end):                       # the template writes a flag as yes or no; the plugin reads true or false
            m = re.match(r"^(current|featured):[ \t]*(yes|no)[ \t]*$", lines[i].rstrip("\r"), re.I)
            if m:
                lines[i] = "%s: %s" % (m.group(1), "true" if m.group(2).lower() == "yes" else "false")
                done.append((m.group(1) + ": " + m.group(2), m.group(1) + ": " + ("true" if m.group(2).lower() == "yes" else "false")))
        if done:
            out[path] = ("\n".join(lines), done)
    return out


TEMPLATE_VIEW_FOLDERS = {"roles": "roles", "experience": "roles"}   # folder -> the view the template renders it as when its page.md names none


def _all_pieces_have_employer(tree, name):
    """True when `content/<name>/` holds at least one built piece and every one carries a one-line `employer` in its front
    matter (a draft is not built, so it is not asked)."""
    seen = 0
    for path in tree.paths():
        parts = path.split("/")
        if not (len(parts) == 4 and parts[:2] == ["content", name] and not parts[2].startswith("_")
                and parts[3] in ("work.md", "index.md")):
            continue
        lines = tree.text(path).replace("\r\n", "\n").split("\n")
        end = next((i for i, l in enumerate(lines[1:], 1) if l.rstrip() == "---"), None) if lines[0].rstrip() == "---" else None
        if end is None:
            return False
        fm = dict((m.group(1), (m.group(2) or "").strip()) for m in (_FM_LINE.match(l) for l in lines[1:end]) if m)
        if fm.get("draft") == "true":
            continue
        seen += 1
        if not fm.get("employer"):
            return False
    return seen > 0


def portfolio_view_rewrites(tree, portfolios):
    """{content/<folder>/page.md: (new text, view)} for each portfolio folder the template renders as a view BY ITS FOLDER
    (`TEMPLATE_VIEW_FOLDERS`: `roles`) whose page.md names no `view` (dev 942, K4): the converted page says the view the
    old builder chose, `view: roles`, an existing key and value at schema 4. The line goes last in the front matter and
    nothing else changes. A page that names any `view` (even one the plugin does not model) is left, and so is a folder
    where any built piece has no `employer` (the roles view groups by it and the plugin's build refuses a piece without
    one, so the template cannot have rendered that folder as roles). It changes the portfolio's index, so parity
    measures it and the class (`pieceKeys`, TEMPLATE) is `apply fixes this` only if it finds no difference."""
    out = {}
    for name in portfolios:
        path = "content/%s/page.md" % name
        if name not in TEMPLATE_VIEW_FOLDERS or not tree.exists(path) or not _all_pieces_have_employer(tree, name):
            continue
        text = tree.text(path)
        if not text.startswith("---\n"):
            continue
        lines = text.split("\n")
        end = next((i for i, l in enumerate(lines[1:], 1) if l.rstrip() == "---"), None)
        keys = [m.group(1) for m in (_FM_LINE.match(l.rstrip("\r")) for l in lines[1:end or 1]) if m]
        if end is None or "view" in keys:
            continue
        out[path] = ("\n".join(lines[:end] + ["view: %s" % TEMPLATE_VIEW_FOLDERS[name]] + lines[end:]), TEMPLATE_VIEW_FOLDERS[name])
    return out


def resume_field_conversion(tree, md):          # `tree` is anything with `.text(path)`: the Overlay the classes read
    """(new text or None, [(key, value)] converted, [(key, why)] left) for the resume's front matter fields that the
    plugin's build refuses (design-site-fidelity section 5.5, TEMPLATE, always `you decide`). A one-line scalar
    `key: value` outside `title`, `description` and `contact` becomes a body paragraph `**Key:** value` at the top of
    the body, which adds visible text in the plugin's markup (so it cannot equal the person's builder). A key that
    opens a block (a list or a map) is left, with its reason: it has no default. A key another conversion owns
    (`RESUME_OWNED_KEYS`: name, headline, linkedin, website, email, location) is never made a paragraph, in the full run
    or alone (dev 946: `name` became `**Name:**` when this class ran by itself), and a front matter with nothing left
    in it loses its fence."""
    text = tree.text(md)
    flat = text.replace("\r\n", "\n")
    if not flat.startswith("---\n"):
        return None, [], []
    lines = flat.split("\n")
    end = next((i for i, l in enumerate(lines[1:], 1) if l.rstrip() == "---"), None)
    if end is None:
        return None, [], []
    keep, converted, left = [lines[0]], [], []
    i = 1
    while i < end:
        line = lines[i]
        m = _FM_LINE.match(line)
        nxt_indented = i + 1 < end and lines[i + 1][:1] in (" ", "\t", "-")
        if not m or m.group(1) in keytables.resume_page_keys(configkeys.SCHEMA_MAX) or m.group(1) in RESUME_OWNED_KEYS:
            keep.append(line)                 # a key `resumeHeader` owns is never a paragraph, whether or not it is also applied (dev 946)
        elif m.group(2) in (None, "") or nxt_indented or m.group(2)[:1] in "[{|>":
            left.append((m.group(1), "it holds a list or a map, which has no paragraph form"))
            keep.append(line)
            while i + 1 < end and lines[i + 1][:1] in (" ", "\t", "-"):
                i += 1
                keep.append(lines[i])
        else:
            val = m.group(2).strip()
            if len(val) > 1 and val[0] in "\"'" and val[-1] == val[0]:
                val = val[1:-1]
            converted.append((m.group(1), val))
        i += 1
    if not converted:
        return None, [], left
    keep += lines[end:end + 1]
    body = lines[end + 1:]
    label = lambda k: (lambda t: t[:1].upper() + t[1:])(re.sub(r"([a-z])([A-Z])", r"\1 \2", k))  # noqa: E731
    paras = []
    for k, v in converted:
        paras += ["**%s:** %s" % (label(k), v), ""]
    if len(keep) == 2:                        # nothing left to say in the front matter: no fence, never an empty `---` block
        return "\n".join(paras + body), converted, left
    return "\n".join(keep + [""] + paras + body), converted, left


def pageless_folders(tree_files, kind="portfolio"):
    """The names of the `content/` folders that have no `page.md` (T9), the way the content layer
    reports them (`layout_problems`, so adopt and the build cannot disagree on what counts)."""
    return [p.path[len("content/"):].rstrip("/")
            for p in layout.layout_problems(tree_files, kind)
            if p.found == "no page.md" and p.path.startswith("content/")]


def _title_of(name):
    return re.sub(r"[-_]+", " ", name).strip().title() or name


def holds_markdown(tree, folder):
    """True when a `.md` file sits anywhere under `folder` (`content/<name>/`). A folder with no page.md that
    holds Markdown may be a page the person's own builder publishes, so moving it is `you decide`."""
    return any(p.startswith(folder) and p.lower().endswith(".md") for p in tree.paths())


def layout_changes(tree, choices, kind="portfolio"):
    """What adopt does about each `content/<f>/` that has no `page.md`, as the person decided (default
    `source`): ({path: bytes} written, [paths] removed, [(old, new, line)] listed). `source` MOVES the
    folder to `content/_<f>/` (not built; every byte kept); `portfolio` adds a `page.md` so it is one.
    Raises Refused for a decision that names no such folder, a destination that exists, or a symlink
    (a move would lose it)."""
    writes, removed, listed = {}, [], []
    names = pageless_folders(TreeFiles(tree), kind)
    for name in sorted(choices or {}):
        if name in keytables.RESERVED_PORTFOLIO_NAMES:
            raise Refused("content/%s is a reserved name (the build reads it as a page or as shared files, never as "
                          "a portfolio), so adopt never moves it and there is no decision to make about it; "
                          "choose a different folder name if you meant a new portfolio" % name)
        if name not in names:
            raise Refused("your decision names content/%s, which is not a folder without a page.md "
                          "(run `adopt.py inventory` again)" % name)
    for name in names:
        folder = "content/%s/" % name
        choice = (choices or {}).get(name)
        if choice is None:
            if holds_markdown(tree, folder):
                continue         # a folder holding Markdown is never moved without the person's say (F1)
            choice = "source"
        if choice == "portfolio":
            writes[folder + "page.md"] = ("---\ntitle: %s\n---\n" % _title_of(name)).encode("utf-8")
            listed.append((folder, folder + "page.md", "content/%s: page.md added, so it is a portfolio" % name))
            continue
        dest = "content/_%s/" % name
        moving = [p for p in tree.paths() if p.startswith(folder)]
        if any(p.startswith(dest) for p in tree.paths()):
            raise Refused("content/_%s already exists, so content/%s cannot be renamed to it; move one of "
                          "them yourself first" % (name, name))
        for p in moving:
            if tree.mode(p) == "120000":
                raise Refused("%s is a symlink, which a rename would lose; move content/%s yourself" % (p, name))
            writes[dest + p[len(folder):]] = tree.read(p)
            removed.append(p)
        listed.append((folder, dest, "content/%s -> content/_%s (source material, not built)" % (name, name)))
    return writes, removed, listed


def converted_site_files(tree, data, paper, folders=None, kind=None, only=None, strict=True, settings=None, hints=None,
                         dispositions=None, persons=None):
    """{path: bytes} of site.json and the token-rewritten pages that the adopt transform produces;
    shared by apply and by the plugin side of parity. Returns (files, notes). site.json is written
    with the lowest schema the CONVERTED tree needs (a label map, a page section), so a plain site
    stays schema 1 and `notes["schema"]` / `notes["schemaReasons"]` say when it is not.

    The mechanical problems are fixed here (design 7.2): `notes["normalised"]` lists each changed
    value, `notes["labels"]` each label conversion, `notes["layout"]` each folder move or page.md, and
    `notes["removed"]` the paths a move takes away (a caller that writes `files` removes those too).
    `notes["olds"]` is [(what, old string)] for the kept-file search that warns a script may depend on
    the old form. `folders` is the person's {name: choice} for the folders without a page.md. A hand-made
    meta-refresh page that is nothing but a redirect becomes a `redirects` entry and is removed
    (design 7.5): `notes["redirects"]` lists each (a RedirectPage) and `notes["redirectsLeft"]` the refresh
    pages that stay, with the reason. `kind` is the site kind the person confirmed (design 7.7).

    The classes run one after another over an `Overlay` of the tree, so each reads what the one before wrote (a renamed
    piece, a rewritten body). `settings` is {name: value}: the measured or chosen settings (design 8, Measured settings;
    `adoption.settings`), laid over the tree after the classes. `hints` is facts the local build gave (`resumePdf`: the
    basename the old builder published the resume PDF under; `derivedLook`: the bytes of a look derived from its pages)."""
    files, notes = {}, {"tokens": [], "unknown": [], "resume": None, "labels": [], "schema": 1,
                        "schemaReasons": [], "normalised": [], "layout": [], "removed": [], "olds": [],
                        "redirects": [], "redirectsLeft": [], "kind": kind, "redirectKeys": [],
                        "redirectCollisions": [], "redirectBoiler": [], "pieces": [], "piecesBoth": [],
                        "resumeFields": [], "resumeFieldsLeft": [], "tokensFrozen": [], "pieceKeys": [], "viewKeys": [],
                        "blocks": [], "blocksLeft": [], "references": [], "pageFiles": [], "homeKeys": [],
                        "resumeHeader": [], "navTokens": [], "personName": [], "resumePdfName": [], "settings": [],
                        "archived": [], "drafted": [], "archiveRows": []}
    want = (lambda c: True) if only is None else (lambda c: c in only)
    # `only`: the conversion classes to make (None: all). `strict=False` is a P1 solo run: it is for the person's
    # own builder, which reads plain JSON, so an invalid site.json is written as it stands, not refused.
    # An OPT_IN class is made only when `only` names it (or `only` is None). Parity and `check` pass `check_only(chosen)`:
    # the tree apply will make, so an opt-in class the person has not chosen is neither built nor measured.
    d, resume = _converted_dict(tree, data, paper, kind)
    notes["resume"] = resume
    gone = set()                                  # a rename's old name: hidden from every later class
    view = Overlay(tree, files, gone)
    if want("normalise"):
        notes["normalised"] = normalise_values(d)
    if want("redirectKeys"):
        notes["redirectKeys"], notes["redirectCollisions"] = normalise_redirect_keys(d)
    if "work" in d and want("labels"):
        d["work"], notes["labels"] = label_conversions(d["work"])
    found, notes["redirectsLeft"] = redirect_pages(tree, d.get("redirects"))
    notes["redirects"] = [r for r in found if not r.boiler] if want("redirects") else []
    notes["redirectBoiler"] = [r for r in found if r.boiler] if want("redirectBoiler") else []
    if not want("redirectBoiler"):          # a page that stays as written: say what converting it would drop
        notes["redirectsLeft"] = sorted(notes["redirectsLeft"] + [
            (r.path, "a redirect page with head boilerplate (%s): converting it drops those from the page a "
                     "visitor loads, so it stays as written unless you choose `adopt.py convert redirectBoiler`"
             % ", ".join(r.boiler)) for r in found if r.boiler])
    if not want("redirects"):
        notes["redirectsLeft"] = []
    if notes["redirects"] or notes["redirectBoiler"]:
        rd = dict(d["redirects"]) if isinstance(d.get("redirects"), dict) else {}
        rd.update((r.key, r.target) for r in notes["redirects"] + notes["redirectBoiler"])
        d["redirects"] = rd
    portfolios = [f for f in portfolio_folders(tree)] + sorted(n for n, c in (folders or {}).items() if c == "portfolio")
    if want("pieces"):
        notes["pieces"], notes["piecesBoth"] = piece_renames(tree, portfolios)
        for old, new in notes["pieces"]:
            files[new] = tree.read(old)
            gone.add(old)
        if notes["pieces"]:
            notes["olds"].append(("piece file", "work.md"))
    _template_classes(view, files, gone, want, notes, d, portfolios, settings or {}, hints or {})
    if want("viewKeys"):
        for path, (new_text, val) in view_key_rewrites(view, portfolios).items():
            files[path] = new_text.encode("utf-8")
            notes["viewKeys"].append((path, val))
    if want("pieceKeys"):
        for path, (new_text, done) in piece_key_rewrites(view, portfolios, showcase_pieces(view, settings or {})).items():
            files[path] = new_text.encode("utf-8")
            notes["pieceKeys"].extend((posixpath.dirname(path) + "/", a, b) for a, b in done)
        # K4: a roles folder's own view. Read from the tree as the person wrote it, never from `view`: a page whose `view` the
        # `viewKeys` class removed DID name one, and the person's choice to leave it is not an absent key to fill
        for path, (new_text, val) in portfolio_view_rewrites(tree, portfolios).items():
            files[path] = new_text.encode("utf-8")
            notes["pieceKeys"].append((posixpath.dirname(path) + "/", "(no view key)", "view: %s" % val))
    if want("resumeFields") and resume["md"]:
        new_text, notes["resumeFields"], notes["resumeFieldsLeft"] = resume_field_conversion(view, resume["md"])
        if new_text is not None:
            files[resume["md"]] = new_text.encode("utf-8")
    apply_settings(view, files, d, settings or {}, hints or {}, notes, portfolios)
    if dispositions:             # the `archive` and `draft` classes (design 8 FA): applied last, and measured like every class
        chosen_d = dict((p, v) for p, v in dispositions.items()
                        if (v[0] == "archived" and want("archive")) or (v[0] == "draft" and want("draft")))
        apply_dispositions(view, files, gone, notes, chosen_d, persons, lambda p: conv_name(p, notes))
    try:
        cfg = model.parse_data(d)
    except diagnostics.SiteConfigError as e:
        if strict:
            raise Refused("the converted site.json is not valid: %s; if it names a setting you chose, "
                          "forget it with `adopt.py setting <name> --clear` and run adopt again" % e)
        cfg = None
    if want("layout"):
        lw, lremoved, notes["layout"] = layout_changes(view, folders, cfg.siteKind if cfg else (kind or "portfolio"))
        files.update(lw)
        notes["removed"] = list(lremoved)
    notes["removed"] = (list(notes["removed"]) + [r.path for r in notes["redirects"] + notes["redirectBoiler"]]
                         + sorted(gone))
    names = portfolio_folders(tree) + sorted(n for n, c in (folders or {}).items() if c == "portfolio")
    home = home_feed(view)
    for p in token_files(view) if want("tokens") else ():
        if p in notes["removed"]:
            continue
        text = view.text(p)
        frz = []
        new, ch, unk = rewrite_tokens(text, names, layout=(p == "site/templates/layout.html"), home=home, frozen=frz,
                                      labels=site_json_labels(data), home_rows=bool(notes["homeKeys"]),
                                      home_samples=any("featured (references)" in w for _p, w in notes["homeKeys"]))
        notes["tokens"].extend((p, a, b) for a, b in ch)
        notes["tokensFrozen"].extend((p, a, b) for a, b in frz)
        notes["unknown"].extend((p, t) for t in unk)
        if new != text:
            files[p] = new.encode("utf-8")
    seen = TreeFiles(tree, files, notes["removed"])
    if cfg is None:
        files["site/site.json"] = (json.dumps(d, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        return files, notes
    interps = grammar.interpretation_reasons(seen)
    notes["schemaReasons"] = (treeschema.schema_2_reasons(cfg, seen)
                              + [(r.where, r.what, r.effect) for r in
                                 treeschema.schema_3_reasons(cfg, seen, interps)])
    notes["schema"] = treeschema.required_schema(cfg, seen, interps)
    files["site/site.json"] = canonical.canonical_text(cfg, seen, interps).encode("utf-8")
    for key, old, _new, _line in notes["normalised"]:
        notes["olds"].append((key, old))
    for old, new, _line in notes["layout"]:
        if not new.endswith("/page.md"):               # a move: a script may name the old folder path
            notes["olds"].append(("folder", old.rstrip("/")))
    return files, notes


def _template_classes(view, files, gone, want, notes, d, portfolios, settings, hints):
    """The template classes of design 8 (B1, R1, H1, N1, RS1, A1), in an order where each reads the one before: page files
    first (a renamed home is read by `homeKeys`), then references, blocks, the home keys, the resume header and the PDF
    name, the person's name, and the nav token. Each writes into `files` and says what it did in `notes`."""
    if want("pageFiles"):
        for old, new in page_file_renames(view):
            files[new] = view.read(old)
            gone.add(old)
            notes["pageFiles"].append((old, new))
            notes["olds"].append(("page file", posixpath.basename(old)))
    if want("references"):
        for path, (text, done) in reference_rewrites(view).items():
            files[path] = text.encode("utf-8")
            notes["references"].extend((path, a, b) for a, b in done)
    if want("blocks"):
        for path, (text, forms) in block_rewrites(view).items():
            files[path] = text.encode("utf-8")
            notes["blocks"].extend((path, ln, kind) for ln, kind in forms)
        notes["blocksLeft"] = blocks_left(view)
    if want("homeKeys"):
        hp = home_path(view)
        if hp:
            new, done = home_key_rewrite(view, hp)
            if new is not None:
                files[hp] = new.encode("utf-8")
                notes["homeKeys"] = [(hp, w) for w in done]
    resume = notes["resume"]
    if resume and resume["md"]:
        if want("resumeHeader"):
            new, done = resume_header_rewrite(view.text(resume["md"]))
            if done:
                files[resume["md"]] = new.encode("utf-8")
                notes["resumeHeader"] = [(resume["md"], a, b) for a, b in done]
        if want("personName"):
            ch = person_name_change(d, view.text(resume["md"]))
            if ch:
                d["name"] = ch[1]
                notes["personName"] = [ch]
        live = hints.get("resumePdf")
        if want("resumePdfName") and resume["pdf"] and live:
            moves, new_pdf = resume_pdf_rename(view, resume["pdf"], live)
            for old, new in moves:
                files[new] = view.read(old)
                gone.add(old)
            if new_pdf:
                notes["resumePdfName"] = moves
                notes["resumeNewPdf"] = new_pdf
                if isinstance(d.get("resume"), dict):
                    d["resume"]["pdf"] = new_pdf
    if want("navTokens"):
        for path, (text, changes) in nav_token_rewrites(view).items():
            files[path] = text.encode("utf-8")
            notes["navTokens"].extend((path, ln, a, b) for ln, a, b in changes)


def old_form_hits(tree, olds, skip=("site/site.json",)):
    """[(path, line number, old string, what)]: where a file the person KEEPS still holds a value adopt
    replaced (design 7.2: "your own script may depend on the old form"). The search is a literal substring
    over the tree as it will stand after apply (so a retired copy is not searched, and nothing under `archive/` is: an
    archived copy is kept, never read), in text files only, and
    a hit must end where the value ends (`content/news` is not found inside `content/newsletter`). The
    first match on a line is the hit."""
    hits = []
    pats = [(what, old, re.compile(re.escape(old) + r"(?![A-Za-z0-9_-])")) for what, old in olds if old]
    if not pats:
        return hits
    for p in tree.paths():
        if p in skip or p.startswith(("site/dist/", ".git/", ".site-studio/", "archive/")) or "node_modules" in p.split("/"):
            continue
        base = posixpath.basename(p)
        ext = posixpath.splitext(base)[1].lower()
        if ext and ext not in _TEXT_EXTS:
            continue
        if tree.mode(p) == "120000":
            continue
        try:
            raw = tree.read(p)
        except KeyError:
            continue
        if len(raw) > _TEXT_MAX or b"\0" in raw:
            continue
        for n, line in enumerate(raw.decode("utf-8", "replace").split("\n"), 1):
            for what, old, rx in pats:
                if old in line and rx.search(line):
                    hits.append((p, n, old, what))
    return hits


def _snapshot(tree, seen):
    """{path: bytes} for everything in the `TreeFiles` view `seen`, for `build.accept`."""
    paths = list(seen)
    tree.prefetch([p for p in paths if p not in seen.overlay])
    return dict((p, seen[p]) for p in paths)


def _give_resume_sidecar(files):
    """The resume PDF sidecar the examples never wrote: parity gives the plugin side one, and so does the
    check, so a missing sidecar is not reported as a refusal the person cannot yet act on (the first publish
    after adopt asks for the PDF to be made again, by the resume skill)."""
    try:
        cfg = model.parse_text(files["site/site.json"].decode("utf-8"))
    except (KeyError, UnicodeDecodeError, diagnostics.SiteConfigError):
        return
    pdf = cfg.resume.get("pdf") if cfg.resume else None
    if pdf and pdf in files and (pdf + ".json") not in files and cfg.resume["path"] in files:
        sha = lambda b: hashlib.sha256(b).hexdigest()  # noqa: E731
        files[pdf + ".json"] = json.dumps({"source_sha256": sha(files[cfg.resume["path"]]),
                                           "pdf_sha256": sha(files[pdf]), "text_sha256": "0" * 64}).encode("utf-8")
