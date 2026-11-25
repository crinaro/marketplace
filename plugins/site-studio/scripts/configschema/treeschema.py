"""treeschema: which schema a site needs. The schema-2, 3, 4, 5, 6, 7, 8 and 9 reasons a tree can hold, `required_schema` (the one
place that says), `tree_schema_problems` and `check_tree_schema` (the build's refusal of a file whose schema is
below what its tree needs) and `kind_conflicts`. K reasons are keys older plugins refused; I reasons are new
readings of text they accepted (see the `siteconfig.py` docstring)."""

import json
import re
from collections import namedtuple
from configschema.configkeys import (
    ADDRESSES_RECORD,
    CARD_ALT_TITLE,
    NAV_HOME_TITLE,
    V3_PAGE_KEYS,
    V4_HOME_PAGE_KEYS,
    V4_PAGE_KEYS,
    V4_PAGE_VIEWS,
    V4_REFERENCE_KEYS,
    V4_RESUME_KEYS,
    V4_RESUME_PAGE_KEYS,
    V4_WORK_KEYS,
    V5_PAGE_VIEWS,
    V5_REFERENCE_KEYS,
    V5_WORK_KEYS,
    V6_BLOCKS_KEYS,
    V6_TOP_KEYS,
    V7_TOP_KEYS,
    V6_WORK_KEYS,
    RESUME_TITLE_FORMS,
    V8_NAV_KEYS,
    V8_RESUME_KEYS,
    V9_BLOCKS_KEYS,
    V9_REFERENCE_KEYS,
    V9_TOP_KEYS,
)
from configschema.diagnostics import SiteConfigError, make_problem
from configschema.frontmatter import (
    _expanded_file,
    _page_md_labels,
    _text_of,
    front_matter_keys,
    front_matter_pairs,
)
from configschema.partblocks import multi_block_part_lines, part_collision_problems
from configschema.workcheck import labels_nonempty, validate_portfolio_settings


_SECTION_RE = re.compile(r"\{\{\s*#page:")
_FEATURED_RE = re.compile(r"\{\{\s*featured\s*\}\}")


# What a 0.1.0 install would do with each tree feature: the clause the refusal names.
_EFFECT_SECTION = "site-studio 0.1.0 would publish it as text"
_EFFECT_FEATURED = "site-studio 0.1.0 would refuse it as an unknown token"
_EFFECT_HOME = "site-studio 0.1.0 would refuse the build as two pages writing index.html"


def schema_2_reasons(cfg, files=None):
    """Every reason this site needs schema 2, as [(where, feature, effect on 0.1.0)]. `files` is the
    site's tree as {repo path: bytes or str} (None: only `site.json` is known). Empty when schema 1
    holds the site. The five conditions of design-site-adoption section 3."""
    out = []
    if cfg.siteKind != "portfolio":
        out.append(("site/site.json", "sets siteKind %s" % cfg.siteKind,
                    "site-studio 0.1.0 would refuse the unknown key"))
    if labels_nonempty(cfg.work.get("labels")):
        out.append(("site/site.json", "sets display labels", "site-studio 0.1.0 would refuse the unknown key"))
    if cfg.featuredFrom != "home":
        out.append(("site/site.json", "sets featuredFrom %s" % cfg.featuredFrom,
                    "site-studio 0.1.0 would refuse the unknown key"))
    if files:
        for path in sorted(files):
            text = None
            if path.startswith("content/") and path.endswith("/page.md") and path.count("/") == 2:
                text = _text_of(files[path])
                if _page_md_labels(path, text):
                    out.append((path, "sets display labels", "site-studio 0.1.0 would refuse the unknown key"))
            if not _expanded_file(path):
                continue
            text = _text_of(files[path]) if text is None else text
            for rx, name, effect in ((_SECTION_RE, "uses {{#page:...}}", _EFFECT_SECTION),
                                     (_FEATURED_RE, "uses {{featured}}", _EFFECT_FEATURED)):
                if rx.search(text):
                    out.append((path, name, effect))
        if (cfg.siteKind == "portfolio" and "site/src/index.html" in files
                and "content/home.md" not in files):
            out.append(("site/src/index.html", "is the home page, with no content/home.md",
                        _EFFECT_HOME))
    return out


_HOME_TOKEN_RE = re.compile(r"\{\{\s*home\s*:")


_SIZE_COPY_RE = re.compile(r"^(?P<stem>.+)\.w(?P<w>\d+)(?P<ext>\.\w+)$")
_EFFECT_K = "site-studio 0.2.0 would refuse it"
_EFFECT_I_TEXT = "site-studio 0.2.0 publishes it as text"
_EFFECT_I_FILE = "site-studio 0.2.0 publishes it as a plain media file"

Reason = namedtuple("Reason", "where what effect lineno kind")


def schema_3_reasons(cfg, files=None, interpretations=None, kinds=("K", "I")):
    """Every reason this site needs schema 3, as [Reason(where, what, effect, lineno, kind)]. `kind` is
    "K" (a key or form 0.2.0 refused) or "I" (a new reading of text 0.2.0 accepted). `files` is the
    tree as {repo path: bytes or str}; `interpretations` is `content.interpretation_reasons(files)`,
    [(path, lineno, form)] (I-1 and I-2), which this module cannot compute (it cannot import `content`).
    `kinds` narrows the answer: `check_tree_schema` asks for K only, because an I reason is never
    refused below schema 3."""
    out = []
    if "K" in kinds:
        if (cfg.resume is not None and cfg.resume.get("pdf") is None and cfg.resume.get("paper") is None):
            out.append(Reason("site/site.json", "has a resume with no PDF and no paper size", _EFFECT_K,
                              None, "K"))
        for path in sorted(files or ()):
            low = path.lower()
            parts = path.split("/")
            if path.startswith("content/") and path.endswith("/page.md") and len(parts) == 3:
                for key, n in front_matter_keys(files[path]):
                    if key in V3_PAGE_KEYS:
                        out.append(Reason(path, "sets %s" % key, _EFFECT_K, n, "K"))
            if path.startswith("site/src/") and low.endswith((".html", ".htm")):
                m = _HOME_TOKEN_RE.search(_text_of(files[path]))
                if m:
                    n = _text_of(files[path])[:m.start()].count("\n") + 1
                    out.append(Reason(path, "uses a {{home:...}} token", _EFFECT_K, n, "K"))
            if path in ("content/home/index.md", "content/about/index.md"):
                out.append(Reason(path, "is a home or about page in folder form", _EFFECT_K, None, "K"))
        if cfg.resume is not None and files and cfg.resume.get("path") in files:
            for key, n in front_matter_keys(files[cfg.resume["path"]]):
                if key == "contact":
                    out.append(Reason(cfg.resume["path"], "sets contact on the resume page", _EFFECT_K, n, "K"))
    if "I" in kinds:
        for path, n, form in (interpretations or ()):
            out.append(Reason(path, "holds %s" % form, _EFFECT_I_TEXT, n, "I"))
        for path in sorted(files or ()):
            if not path.startswith("content/") or "/media/" not in path:
                continue
            folder, _, base = path.rpartition("/")
            m = _SIZE_COPY_RE.match(base)
            if m and (folder + "/" + m.group("stem") + m.group("ext")) in files:
                out.append(Reason(path, "is a .w%s size copy of %s%s" % (m.group("w"), m.group("stem"),
                                                                        m.group("ext")),
                                  _EFFECT_I_FILE, None, "I"))
    return out


_EFFECT_K4 = "site-studio 0.3 would refuse it"
_EFFECT_GUARD = "no page changes; older site-studio installs will refuse to publish this site"
_NAVLINKS_RE = re.compile(r"\{\{\s*navLinks\s*\}\}")
_QUOTES_OPEN_RE = re.compile(r"^:::quotes(?:[ \t].*)?$")


def schema_4_reasons(cfg, files=None):
    """Every reason this site needs schema 4, as [Reason(where, what, effect, lineno, "K")]. All are K reasons
    (design section 3.1 rule 2): a key, value, token or form 0.3.x refuses, plus the guard reason (rule 8), so no
    tree 0.3.x accepted holds one and no output changes. `files` is the tree as {repo path: bytes or str}; it must
    include `.site-studio/addresses.json` when the tree has one."""
    out = []
    here = "site/site.json"

    def add(where, what, lineno=None, effect=_EFFECT_K4):
        out.append(Reason(where, what, effect, lineno, "K"))
    if cfg.nav.get("home") is False:            # the one schema-4 nav setting; schema 6's are `schema_6_reasons`'
        add(here, "sets nav.home false")
    if cfg.look is not None:
        add(here, "sets look")
    for k in cfg.blocks:
        if k not in V6_BLOCKS_KEYS and k not in V9_BLOCKS_KEYS:      # schema 6's and 9's are those schemas' reasons
            add(here, "sets blocks.%s" % k)
    for k in V4_RESUME_KEYS:
        if cfg.resume is not None and k in cfg.resume:
            add(here, "sets resume.%s" % k)
    for k in V4_WORK_KEYS:
        if k in cfg.work:
            add(here, "sets work.%s" % k)
    for path in sorted(files or ()):
        low = path.lower()
        parts = path.split("/")
        text = None
        if path == ADDRESSES_RECORD:
            add(path, "is the address record (the guard reason)", None, _EFFECT_GUARD)
            continue
        if path.startswith("content/") and path.endswith("/page.md") and len(parts) == 3:
            for key, val, n in front_matter_pairs(files[path]):
                if key in V4_WORK_KEYS or key in V4_PAGE_KEYS:
                    add(path, "sets %s" % key, n)
                elif key == "view" and val in V4_PAGE_VIEWS:
                    add(path, "sets view %s" % val, n)
        if path in ("content/home.md", "content/home/index.md"):
            for key, n in front_matter_keys(files[path]):
                if key in V4_HOME_PAGE_KEYS:
                    add(path, "sets %s" % key, n)
        if cfg.resume is not None and path == cfg.resume.get("path"):
            for key, n in front_matter_keys(files[path]):
                if key in V4_RESUME_PAGE_KEYS:
                    add(path, "sets %s on the resume page" % key, n)
        if (len(parts) == 4 and parts[0] == "content" and parts[1] == "references"
                and parts[3] == "reference.json"):
            try:
                data = json.loads(_text_of(files[path]))
            except ValueError:
                data = None
            if isinstance(data, dict):
                for key in V4_REFERENCE_KEYS:
                    if key in data:
                        add(path, "sets %s" % key)
        if not _expanded_file(path):
            continue
        text = _text_of(files[path])
        m = _NAVLINKS_RE.search(text)
        if m:
            add(path, "uses the {{navLinks}} token", text[:m.start()].count("\n") + 1)
        if cfg.schema >= 3 and path.startswith("content/") and low.endswith(".md"):
            # A `:::` line is a block only where the grammar is 3 or above; below that it is text 0.3.x accepts.
            for n, line in enumerate(text.replace("\r\n", "\n").split("\n"), 1):
                if _QUOTES_OPEN_RE.match(line):
                    add(path, "holds a :::quotes block", n)
            for n in multi_block_part_lines(text):
                add(path, "holds a :::part with more than one block", n)
    return out


_EFFECT_K5 = "site-studio 0.4 would refuse it"
_EFFECT_LOOK5 = "site-studio 0.4 would refuse the look as unknown"
_LOOK_PATH_RE = re.compile(r"^site/looks/[a-z0-9][a-z0-9-]*\.json$")
NEEDS_050 = "0.5.0"


def schema_5_reasons(cfg, files=None, look_needs=None):
    """Every reason this site needs schema 5, as [Reason(where, what, effect, lineno, "K")]. All are K reasons
    (design-movement-view section 3.1 rule 1): a key, value or look form 0.4.x refuses, so no tree 0.4.x accepted holds
    one and raising a tree from 4 to 5 changes no output. The rows are section 3.2's: a schema-5 portfolio setting in
    `site.json` `work` or a `page.md` (`cardImage: cover` in a grid is a reason by presence), `view: steps`, a schema-5
    `reference.json` key, and every `site/looks/*.json` whose `look_needs` value is 0.5.0 (not only the look `site.json`
    names). `files` is the tree as {repo path: bytes or str}. `look_needs` is {look path: the newest release that look
    needs}, which this module cannot compute (it does not import the look grammar): whoever passes `files` passes it
    too (section 3.4 point 1), as `interpretations` is passed to `schema_3_reasons`, and a call with `files` and no
    `look_needs` is refused rather than read as "no look needs anything"."""
    if files is not None and look_needs is None:
        raise ValueError("schema_5_reasons(cfg, files) needs look_needs= ({site/looks/<name>.json: release}, from "
                         "building.lookneeds.look_needs(files)); pass {} only when you know the tree holds no look")
    out = []
    here = "site/site.json"

    def add(where, what, lineno=None, effect=_EFFECT_K5):
        out.append(Reason(where, what, effect, lineno, "K"))
    for k in V5_WORK_KEYS:
        if k in cfg.work:
            add(here, "sets work.%s" % k)
    for path in sorted(files or ()):
        parts = path.split("/")
        if path.startswith("content/") and path.endswith("/page.md") and len(parts) == 3:
            for key, val, n in front_matter_pairs(files[path]):
                if key in V5_WORK_KEYS:
                    add(path, "sets %s" % key, n)
                elif key == "view" and val in V5_PAGE_VIEWS:
                    add(path, "sets view %s" % val, n)
        if (len(parts) == 4 and parts[0] == "content" and parts[1] == "references"
                and parts[3] == "reference.json"):
            try:
                data = json.loads(_text_of(files[path]))
            except ValueError:
                data = None
            if isinstance(data, dict):
                for key in V5_REFERENCE_KEYS:
                    if key in data:
                        add(path, "sets %s" % key)
    for path in sorted(look_needs or {}):
        if look_needs[path] == NEEDS_050 and _LOOK_PATH_RE.match(path) and (files is None or path in files):
            add(path, "is a look that needs site-studio 0.5.0", None, _EFFECT_LOOK5)
    return out


_EFFECT_K6 = "site-studio 0.5 would refuse it"
_EFFECT_LOOK6 = "site-studio 0.5 would refuse the look as unknown"
_ASSET_VERSION_RE = re.compile(r"\{\{\s*assetVersion\s*\}\}")
_LABELS_OPEN_RE = re.compile(r"^labels:[ \t]*(.*)$")
_COUNTS_INLINE_RE = re.compile(r"(?:^|[{,\s])counts\s*:")
NEEDS_060 = "0.6.0"


def _labels_parts(text):
    """The part names (`meta`, `groups`, `counts`) a `page.md`'s front matter `labels:` holds, read from the lines as
    written: an inline flow map, or the first indentation level of the lines under `labels:`. Tolerant: what it cannot
    read it does not name (the content model's own parse refuses that file anyway)."""
    lines = _text_of(text).replace("\r\n", "\n").split("\n")
    if not lines or lines[0] != "---":
        return set()
    out = set()
    for i in range(1, len(lines)):
        if lines[i].rstrip() == "---":
            break
        m = _LABELS_OPEN_RE.match(lines[i])
        if not m:
            continue
        if m.group(1).strip():
            if _COUNTS_INLINE_RE.search(m.group(1)):
                out.add("counts")
            continue
        indent = None
        for line in lines[i + 1:]:
            if line.rstrip() == "---" or (line.strip() and line[:1] not in " \t"):
                break
            if not line.strip():
                continue
            depth = len(line) - len(line.lstrip())
            indent = depth if indent is None else indent
            key = re.match(r"^([A-Za-z][A-Za-z0-9_]*)\s*:", line.strip())
            if depth == indent and key:
                out.add(key.group(1))
    return out


def schema_6_reasons(cfg, files=None, look_needs=None):
    """Every reason this site needs schema 6, as [Reason(where, what, effect, lineno, "K")]. All are K reasons
    (design-adopt-parity-2 section 3.1 rule 1): a key, value, token or look element 0.5.x refuses, so no tree 0.5.x
    accepted holds one and raising a tree from 5 to 6 changes no output. The rows are section 3.2's: the schema-6
    top-level keys (each stored only when not its default), `nav.home: "title"`, `nav.extra`, `blocks.headings`, the
    schema-6 portfolio settings (`groupCount`, `pieceRoles`, `cardAlt: "title"`, `labels.counts`) in `site.json` `work`
    or a `page.md`, the `{{assetVersion}}` token in a file the build expands, and every `site/looks/*.json` whose
    `look_needs` value is 0.6.0. NOT a reason: the piece key `currentRole` (a free key 0.5.x prints nowhere), and the
    folder `site/carried/` (0.5.x ignores it; the K reason is the `carried` key alone). `files` and `look_needs` as
    `schema_5_reasons` (a call with `files` and no `look_needs` is refused)."""
    if files is not None and look_needs is None:
        raise ValueError("schema_6_reasons(cfg, files) needs look_needs= ({site/looks/<name>.json: release}, from "
                         "building.lookneeds.look_needs(files)); pass {} only when you know the tree holds no look")
    out = []
    here = "site/site.json"

    def add(where, what, lineno=None, effect=_EFFECT_K6):
        out.append(Reason(where, what, effect, lineno, "K"))
    for k in V6_TOP_KEYS:
        if k in cfg.to_dict():
            add(here, "sets %s" % k)
    if cfg.nav.get("home") == NAV_HOME_TITLE:
        add(here, "sets nav.home title")
    if "extra" in cfg.nav:
        add(here, "sets nav.extra")
    for k in V6_BLOCKS_KEYS:
        if k in cfg.blocks:
            add(here, "sets blocks.%s" % k)
    for k in V6_WORK_KEYS:
        if k in cfg.work:
            add(here, "sets work.%s" % k)
    if cfg.work.get("cardAlt") == CARD_ALT_TITLE:
        add(here, "sets work.cardAlt title")
    if (cfg.work.get("labels") or {}).get("counts"):
        add(here, "sets work.labels.counts")
    for path in sorted(files or ()):
        parts = path.split("/")
        if path.startswith("content/") and path.endswith("/page.md") and len(parts) == 3:
            for key, val, n in front_matter_pairs(files[path]):
                if key in V6_WORK_KEYS:
                    add(path, "sets %s" % key, n)
                elif key == "cardAlt" and val == CARD_ALT_TITLE:
                    add(path, "sets cardAlt title", n)
            if "counts" in _labels_parts(files[path]):
                add(path, "sets labels.counts")
        if _expanded_file(path):
            text = _text_of(files[path])
            m = _ASSET_VERSION_RE.search(text)
            if m:
                add(path, "uses the {{assetVersion}} token", text[:m.start()].count("\n") + 1)
    for path in sorted(look_needs or {}):
        if look_needs[path] == NEEDS_060 and _LOOK_PATH_RE.match(path) and (files is None or path in files):
            add(path, "is a look that needs site-studio 0.6.0", None, _EFFECT_LOOK6)
    return out


_EFFECT_LOOK7 = "site-studio 0.6 would refuse the look as unknown"
_EFFECT_K7 = "site-studio 0.6 would refuse the key as unknown"
NEEDS_070 = "0.7.0"


def schema_7_reasons(cfg, files=None, look_needs=None):
    """Every reason this site needs schema 7 (design-adopt-ownership-line section 2.1), as [Reason(..., "K")]: a key, slot,
    part or look key 0.6.0 refuses, so no tree 0.6.0 accepted holds one and raising a tree from 6 to 7 changes no output.
    The rows: the key `lookLocal` (`V7_TOP_KEYS`), and a look the build READS that needs 0.7.0. A look is read when a key
    names it: the file `look` names and the file `lookLocal` names, and no other (section 2.1); a look file no key names
    (a stray `site/looks/x.json`, or `local.json` without `lookLocal`) is not read, so it is not a reason, and 0.6.0
    builds such a tree (step 0, TESTED). `files` and `look_needs` as `schema_6_reasons`."""
    if files is not None and look_needs is None:
        raise ValueError("schema_7_reasons(cfg, files) needs look_needs= ({site/looks/<name>.json: release}, from "
                         "building.lookneeds.look_needs(files)); pass {} only when you know the tree holds no look")
    out = []
    for k in V7_TOP_KEYS:
        if k in cfg.to_dict():
            out.append(Reason("site/site.json", "sets %s" % k, _EFFECT_K7, None, "K"))
    read = set(p for p in (getattr(cfg, "look", None), getattr(cfg, "lookLocal", None)) if isinstance(p, str))
    for path in sorted(look_needs or {}):
        if (look_needs[path] == NEEDS_070 and path in read and _LOOK_PATH_RE.match(path)
                and (files is None or path in files)):
            out.append(Reason(path, "is a look that needs site-studio 0.7.0", _EFFECT_LOOK7, None, "K"))
    return out


_EFFECT_LOOK8 = "site-studio 0.7 would refuse the look as unknown"
_EFFECT_K8 = "site-studio 0.7 would refuse the key as unknown"
NEEDS_080 = "0.8.0"


def schema_8_reasons(cfg, files=None, look_needs=None):
    """Every reason this site needs schema 8 (design-adopt-local-reach section 2.1), as [Reason(..., "K")]: a key, slot, part
    or `reads` target 0.7.0 refuses, so no tree 0.7.0 accepted holds one and raising a tree from 7 to 8 changes no output.
    The rows: `resume.titleForm` and `nav.labels` (`V8_RESUME_KEYS`, `V8_NAV_KEYS`; each stored only when not its default, so
    a tree holding the default holds no reason), and a look the build READS that needs 0.8.0 (the file `look` names and the file
    `lookLocal` names, and no other, as `schema_7_reasons`; a look file no key names is not read, so it is not a reason).
    NOT a reason: a key a new `reads` entry names (`cardMeta`, `cardKicker`, `cardImage`), nor the shipped samples. `files`
    and `look_needs` as `schema_7_reasons`."""
    if files is not None and look_needs is None:
        raise ValueError("schema_8_reasons(cfg, files) needs look_needs= ({site/looks/<name>.json: release}, from "
                         "building.lookneeds.look_needs(files)); pass {} only when you know the tree holds no look")
    out = []
    for k in V8_RESUME_KEYS:
        if cfg.resume is not None and cfg.resume.get(k, RESUME_TITLE_FORMS[0]) != RESUME_TITLE_FORMS[0]:
            out.append(Reason("site/site.json", "sets resume.%s" % k, _EFFECT_K8, None, "K"))
    for k in V8_NAV_KEYS:
        if cfg.nav.get(k):
            out.append(Reason("site/site.json", "sets nav.%s" % k, _EFFECT_K8, None, "K"))
    read = set(p for p in (getattr(cfg, "look", None), getattr(cfg, "lookLocal", None)) if isinstance(p, str))
    for path in sorted(look_needs or {}):
        if (look_needs[path] == NEEDS_080 and path in read and _LOOK_PATH_RE.match(path)
                and (files is None or path in files)):
            out.append(Reason(path, "is a look that needs site-studio 0.8.0", _EFFECT_LOOK8, None, "K"))
    return out


_EFFECT_LOOK9 = "site-studio 0.8 would refuse the look as unknown"
_EFFECT_K9 = "site-studio 0.8 would refuse the key as unknown"
NEEDS_090 = "0.9.0"


def schema_9_reasons(cfg, files=None, look_needs=None):
    """Every reason this site needs schema 9 (design-reference-layout section 5), as [Reason(..., "K")]: a key, slot or part 0.8.0
    refuses, so no tree 0.8.0 accepted holds one and raising a tree from 8 to 9 changes no output. The four rows: the key
    `references` when it is not `{}` (`V9_TOP_KEYS`; a parsed config holds it only then), `blocks.unlistedVideos`
    (`V9_BLOCKS_KEYS`), `project`, `type` or `channel` in a `reference.json` (`V9_REFERENCE_KEYS`; by presence, a blank value
    included, because 0.8.0 refuses the key itself), and a look the build READS that needs 0.9.0 (the file `look` names and the
    file `lookLocal` names, and no other, as `schema_8_reasons`). `files` and `look_needs` as `schema_8_reasons`."""
    if files is not None and look_needs is None:
        raise ValueError("schema_9_reasons(cfg, files) needs look_needs= ({site/looks/<name>.json: release}, from "
                         "building.lookneeds.look_needs(files)); pass {} only when you know the tree holds no look")
    out = []
    here = "site/site.json"
    for k in V9_TOP_KEYS:
        if k in cfg.to_dict():
            out.append(Reason(here, "sets %s" % k, _EFFECT_K9, None, "K"))
    for k in V9_BLOCKS_KEYS:
        if k in cfg.blocks:
            out.append(Reason(here, "sets blocks.%s" % k, _EFFECT_K9, None, "K"))
    for path in sorted(files or ()):
        parts = path.split("/")
        if (len(parts) == 4 and parts[0] == "content" and parts[1] == "references" and parts[3] == "reference.json"):
            try:
                data = json.loads(_text_of(files[path]))
            except ValueError:
                data = None
            if isinstance(data, dict):
                for key in V9_REFERENCE_KEYS:
                    if key in data:
                        out.append(Reason(path, "sets %s" % key, _EFFECT_K9, None, "K"))
    read = set(p for p in (getattr(cfg, "look", None), getattr(cfg, "lookLocal", None)) if isinstance(p, str))
    for path in sorted(look_needs or {}):
        if (look_needs[path] == NEEDS_090 and path in read and _LOOK_PATH_RE.match(path)
                and (files is None or path in files)):
            out.append(Reason(path, "is a look that needs site-studio 0.9.0", _EFFECT_LOOK9, None, "K"))
    return out


def _looks_read(files, look_needs):
    """`look_needs` as given, else {}. Given `files` and no `look_needs`, {} means the looks are NOT scanned (called
    directly, `schema_5_reasons` refuses `files` without it; through here it is not refused). Since 0.5.0 a look can
    need 0.5.0 (design-movement-view section 3.4), so every caller that holds a tree passes
    `building.lookneeds.look_needs(files)`: `building/running.py`, `building/raiseschema.py`, `building/listing.py`,
    `lookfiles/commands.py`, `adoption/convert.py`, `addresses.py` and `movepiece/planning.py`."""
    return look_needs if look_needs is not None or files is None else {}


def required_schema(cfg, files=None, interpretations=None, look_needs=None):
    """The lowest schema that holds the site: 9 when any schema-9 reason holds (`schema_9_reasons`, design-reference-layout
    section 5), 8 when any schema-8 reason holds (`schema_8_reasons`, design-adopt-local-reach
    section 2.1), 7 when any schema-7 reason holds (`schema_7_reasons`), 6 when any schema-6 reason holds (`schema_6_reasons`, a section 3.2 row
    of design-adopt-parity-2), 5 when any schema-5 reason holds (`schema_5_reasons`, and only a
    section 3.2 row of design-movement-view is one), 4 when any schema-4 reason holds (`schema_4_reasons`), 3 when
    any schema-3 reason holds (`schema_3_reasons`), 2
    when any of five conditions holds (`schema_2_reasons`), else 1. `files` is the tree the caller
    holds (adopt: the converted tree); None means no tree feature is known. When `files` is given,
    `interpretations` MUST be too (`content.interpretation_reasons(files)`; [] when there are none): a
    caller that held a tree and forgot the scan would write a schema too low (design section 3.3). `look_needs` is
    `building.lookneeds.look_needs(files)` (see `_looks_read`)."""
    if files is not None and interpretations is None:
        raise ValueError("required_schema(cfg, files) needs interpretations= (content.interpretation_reasons"
                         "(files)); pass [] only when you know the tree holds none")
    if schema_9_reasons(cfg, files, _looks_read(files, look_needs)):
        return 9
    if schema_8_reasons(cfg, files, _looks_read(files, look_needs)):
        return 8
    if schema_7_reasons(cfg, files, _looks_read(files, look_needs)):
        return 7
    if schema_6_reasons(cfg, files, _looks_read(files, look_needs)):
        return 6
    if schema_5_reasons(cfg, files, _looks_read(files, look_needs)):
        return 5
    if schema_4_reasons(cfg, files):
        return 4
    if schema_3_reasons(cfg, files, interpretations):
        return 3
    return 2 if schema_2_reasons(cfg, files) else 1


def tree_schema_problems(cfg, files, look_needs=None):
    """Every Problem the declared schema of `site.json` has with the tree: the schema-2 reasons under a
    schema-1 file, then the K schema-3 reasons under a file below 3. An I reason is never a problem
    (design section 3.2), then the schema-4 K reasons (and the guard reason) under a file below 4, and at 4 and
    above the part-name collisions (design section 3.1 rule 7), then the schema-5 reasons under a file below 5, a look
    that needs 0.5.0 among them (design-movement-view section 3.4 point 2), then the schema-6 reasons under a file
    below 6 (design-adopt-parity-2 section 3.2). Each carries `path` and `lineno`; none is
    mechanical. `look_needs` is `building.lookneeds.look_needs(files)` (see `_looks_read`)."""
    out = []
    if cfg.schema < 2:
        for where, what, effect in schema_2_reasons(cfg, files):
            out.append(make_problem("%s %s, which needs \"schema\": 2 in site/site.json (%s)"
                                    % (where, what, effect), where, "schema 1", "schema 2",
                                    "set \"schema\": 2 in site/site.json (a save by site-studio does this)"))
    if cfg.schema < 3:
        for r in schema_3_reasons(cfg, files, kinds=("K",)):
            at = "%s:%d:" % (r.where, r.lineno) if r.lineno else r.where
            out.append(make_problem("%s %s, which needs \"schema\": 3 in site/site.json (run `build.py "
                                    "raise-schema`)" % (at, r.what), r.where, "schema %d" % cfg.schema,
                                    "schema 3", "run `python3 build.py raise-schema`, which lists what the "
                                    "page changes before it writes schema 3", False, r.lineno))
    if cfg.schema < 4:
        for r in schema_4_reasons(cfg, files):
            at = "%s:%d:" % (r.where, r.lineno) if r.lineno else r.where
            out.append(make_problem("%s %s, which needs \"schema\": 4 in site/site.json (run `build.py "
                                    "raise-schema --to 4`)" % (at, r.what), r.where, "schema %d" % cfg.schema,
                                    "schema 4", "run `python3 build.py raise-schema --to 4`, which lists what "
                                    "the page changes before it writes schema 4", False, r.lineno))
    else:
        out.extend(part_collision_problems(files))
    if cfg.schema < 5:
        for r in schema_5_reasons(cfg, files, _looks_read(files, look_needs)):
            at = "%s:%d:" % (r.where, r.lineno) if r.lineno else r.where
            out.append(make_problem("%s %s, which needs \"schema\": 5 in site/site.json (run `build.py "
                                    "raise-schema --to 5`)" % (at, r.what), r.where, "schema %d" % cfg.schema,
                                    "schema 5", "run `python3 build.py raise-schema --to 5`, which lists what "
                                    "the page changes before it writes schema 5", False, r.lineno))
    if cfg.schema < 6:
        for r in schema_6_reasons(cfg, files, _looks_read(files, look_needs)):
            at = "%s:%d:" % (r.where, r.lineno) if r.lineno else r.where
            out.append(make_problem("%s %s, which needs \"schema\": 6 in site/site.json (run `build.py "
                                    "raise-schema --to 6`)" % (at, r.what), r.where, "schema %d" % cfg.schema,
                                    "schema 6", "run `python3 build.py raise-schema --to 6`, which lists what "
                                    "the page changes before it writes schema 6", False, r.lineno))
    if cfg.schema < 7:
        for r in schema_7_reasons(cfg, files, _looks_read(files, look_needs)):
            at = "%s:%d:" % (r.where, r.lineno) if r.lineno else r.where
            out.append(make_problem("%s %s, which needs \"schema\": 7 in site/site.json (run `build.py "
                                    "raise-schema --to 7`)" % (at, r.what), r.where, "schema %d" % cfg.schema,
                                    "schema 7", "run `python3 build.py raise-schema --to 7`, which lists what "
                                    "the page changes before it writes schema 7", False, r.lineno))
    if cfg.schema < 8:
        for r in schema_8_reasons(cfg, files, _looks_read(files, look_needs)):
            at = "%s:%d:" % (r.where, r.lineno) if r.lineno else r.where
            out.append(make_problem("%s %s, which needs \"schema\": 8 in site/site.json (run `build.py "
                                    "raise-schema --to 8`)" % (at, r.what), r.where, "schema %d" % cfg.schema,
                                    "schema 8", "run `python3 build.py raise-schema --to 8`, which lists what "
                                    "the page changes before it writes schema 8", False, r.lineno))
    if cfg.schema < 9:
        for r in schema_9_reasons(cfg, files, _looks_read(files, look_needs)):
            at = "%s:%d:" % (r.where, r.lineno) if r.lineno else r.where
            out.append(make_problem("%s %s, which needs \"schema\": 9 in site/site.json (run `build.py "
                                    "raise-schema --to 9`)" % (at, r.what), r.where, "schema %d" % cfg.schema,
                                    "schema 9", "run `python3 build.py raise-schema --to 9`, which lists what "
                                    "the page changes before it writes schema 9", False, r.lineno))
    return out


def check_tree_schema(cfg, files, look_needs=None):
    """The build's refusal of a `site.json` whose schema is lower than the tree needs, naming the file
    and the feature (the hand-edit case: a person typed a section into a layout, or a `page.md` key
    from 0.3.0). Raises ONE error that carries every reason (`.problems`); with one reason its message
    is exactly that reason's. `look_needs`: see `tree_schema_problems`."""
    probs = tree_schema_problems(cfg, files, look_needs)
    if probs:
        raise SiteConfigError.of(probs)


def kind_conflicts(cfg):
    """What a `hub` or `custom` site's config may not carry (design section 4.1): the portfolio-only
    keys, when set. Empty for a portfolio."""
    if cfg.siteKind == "portfolio":
        return []
    out = []
    if cfg.work != validate_portfolio_settings({}, "work"):
        out.append("site.json 'work' is only for siteKind portfolio")
    if cfg.resume is not None:
        out.append("site.json 'resume' is only for siteKind portfolio")
    if cfg.featuredFrom != "home":
        out.append("site.json 'featuredFrom' is only for siteKind portfolio")
    if cfg.references:
        out.append("site.json 'references' is only for siteKind portfolio")     # no earlier tree holds it (design-reference-layout 1.2)
    return out
