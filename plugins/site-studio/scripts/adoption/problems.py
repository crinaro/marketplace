"""adoption.problems -- every problem at once: what the plugin's own build refuses in the tree adopt would write, grouped by cause.

Part of the `adoption` package behind the entry point `adopt.py`. Documentation that was in `adopt.py`'s docstring about this module's code:

EVERY PROBLEM AT ONCE (dev #855, design-site-adoption section 7.1). `check` and `inventory` build the
site.json adopt WOULD write and run `siteconfig.problems()` over it and `content.layout_problems()` over
the tree, then print EVERY problem with its fix, each marked `apply fixes this` (mechanical) or `you
decide`. The converted site.json is written with the lowest schema its tree needs (a `[key, label]`
pair converted into `work.labels`, or a `{{resumeLink}}` anchor rewritten into a page section, makes it
schema 2, and the inventory says so).
"""

import json
import posixpath
import re

from building import acceptance, running, tokens  # noqa: E402
from contentmodel import errors, frontmatter, keytables, layout as layout_mod  # noqa: E402
from configschema import configkeys, diagnostics, model, treeschema, workcheck  # noqa: E402

from adoption.base import Refused
from adoption.spec import CONVERSION_CLASSES, OPT_IN_CLASSES
from adoption.tree import TreeFiles
from adoption.tokens import home_feed, portfolio_folders, rewrite_tokens, site_json_labels, token_files
from adoption.redirects import redirect_pages, redirect_problems
from adoption.convert import (
    _converted_dict, _give_resume_sidecar, _snapshot, converted_site_files,
    label_conversions, normalise_redirect_keys, piece_renames,
)
from adoption.parity import decide_conversions, template_fingerprint
from adoption.keycover import cover_keys, split_notes

# A template key `pieceKeys` leaves under `view: showcase`, with the plugin key the steps view reads it as (design-movement-view
# rule 5 and 6.2): `check` names it once, with that fix.
SHOWCASE_LEFT = {"tilePhotoPosition": "tilePosition"}

def accept_problems(tree, data, paper=None, folders=None, kind=None, only=None, settings=None, dispositions=None, persons=None,
                    hints=None):
    """(problems, Acceptance or None): what the PLUGIN'S OWN BUILD refuses in the tree adopt would write
    (design-site-fidelity section 4.2). The one source of "can be converted": `build.accept` over the
    converted tree, so `check`, `inventory`, `apply` and the build cannot disagree. Every problem carries its
    path, its line where the build knows it, and its fix, and none is mechanical: adopt's own conversions
    were already made in `converted_site_files`, so what is left is for the person to settle."""
    try:
        files, notes = converted_site_files(tree, data, paper, folders, kind, only, settings=settings,
                                            dispositions=dispositions, persons=persons, hints=hints)
    except Refused as e:
        msg = str(e)
        if msg.startswith("the converted site.json is not valid"):
            return [], None                   # `site_problems` lists those one by one already
        return [diagnostics.make_problem("adopt cannot convert this tree: %s" % msg, None, "a tree adopt "
                                        "cannot convert", "one it can", "settle what the message names, "
                                        "then run the check again")], None
    seen = TreeFiles(tree, files, notes["removed"])
    snap = _snapshot(tree, seen)
    _give_resume_sidecar(snap)
    try:
        acc = running.accept(snap)
    except Exception as e:      # noqa: BLE001 -- accept does not raise; this is the belt to its braces
        return [acceptance._not_checked("build.accept", e)], None
    return reword_unmodelled(every_refusal(snap, acc.problems), snap), acc


# What a template site uses that the plugin does not model, by the issue that tracks it (dev 942, 944, 945, 965). The build
# says "unknown key", "unknown token" or "must be grid or page", and a fix of "remove it": true for a typo, wrong for a
# template's own key, which the person's builder still renders and a visitor still sees. `check` says what is so instead.
# 0.5.0 models every piece and reference key 0.4.2 listed here (design-movement-view sections 3, 6.1); what stays is named by
# design 7: `current` as the map's highlighted pin (dev 965; {key: (the view, issue)}, read by `keycover.cover_keys`, whose
# note for a key read elsewhere says it), and the home page's range list (dev 942), a token. The range list's token name is
# not in any fixture or report: `range` is assumed (INFERRED) until the owner's adopt run names it.
UNMODELLED_PIECE_KEYS = {"current": ("map", 965)}
UNMODELLED_REFERENCE_KEYS = {}
UNMODELLED_VIEWS = {}             # `movement` is modelled as `steps` (the `viewNames` conversion, dev 945)
UNMODELLED_TOKENS = {"range": 942}
_STAYS = "your builder stays your publisher"
_PIECE_KEY = re.compile(r"^(?P<f>\S+): front matter key '(?P<k>[^']+)' is not published; ")
_REFERENCE_KEY = re.compile(r"^(?P<f>content/references/[^/]+/reference\.json): unknown key '(?P<k>[^']+)'$")
_TEMPLATE_TOKEN = re.compile(r"^(?P<f>\S+): unknown token \{\{(?P<t>[A-Za-z]+)[^{}]*\}\}$")
_VIEW_VALUE = re.compile(r"^view:[ \t]*[\"']?([^\"'\s#]+)", re.M)


def _reworded(p, message, fix):
    return diagnostics.make_problem(message, p.path, p.found, p.expected, fix, False, p.lineno)


def reword_unmodelled(probs, files=None):
    """`probs` with each refusal or warning about a template construct the plugin does not model yet worded as that
    (dev 945, 942, 944; U1): "not modelled yet (dev N); your builder stays your publisher", and a fix that never says to
    remove what a visitor sees. Same path, line and standing (`you decide`), so grouping and counts are unchanged.
    `files` ({path: bytes}) lets a `view` refusal read the page's own value; without it that refusal is left as it is."""
    out = []
    for p in probs:
        m = _TEMPLATE_TOKEN.match(p.message)
        if m and UNMODELLED_TOKENS.get(m.group("t")) and not p.mechanical:
            n = UNMODELLED_TOKENS[m.group("t")]
            out.append(_reworded(p, "%s: the template's %s list is not modelled (dev %d); %s" % (m.group("f"), m.group("t"), n, _STAYS),
                                 "nothing the plugin prints replaces it (dev %d): keep this page on your builder, or write the "
                                 "list your builder prints into the page as text, which does not grow as pieces are added" % n))
            continue
        m = _REFERENCE_KEY.match(p.message)
        if m and UNMODELLED_REFERENCE_KEYS.get(m.group("k")) and not p.mechanical:
            n = UNMODELLED_REFERENCE_KEYS[m.group("k")]
            out.append(_reworded(p, "%s: the template's key '%s' is not modelled yet (dev %d); %s"
                                 % (m.group("f"), m.group("k"), n, _STAYS),
                                 "nothing to change in this file: the plugin has no reference '%s' yet (dev %d), so the key "
                                 "stays as written, for your builder, until the plugin does" % (m.group("k"), n)))
            continue
        if files and p.path and p.path in files and p.message.endswith("'view' must be \"grid\" or \"page\"") and not p.mechanical:
            v = _VIEW_VALUE.search(files[p.path].decode("utf-8", "replace"))
            n = UNMODELLED_VIEWS.get(v.group(1)) if v else None
            if n:
                out.append(_reworded(p, "%s: the template's %s view is not modelled yet (dev %d); %s"
                                     % (p.path, v.group(1), n, _STAYS),
                                     "nothing to change in this file: your builder still renders this index. `adopt.py convert "
                                     "viewKeys` is the one way to leave the view behind: the index becomes the plugin's grid, "
                                     "which a visitor sees as a different page"))
                continue
        out.append(p)
    return out



_OTHER_PORTFOLIO = re.compile(r"the ([^ ]+) portfolio's meta and cardMeta do not list it")


def waits_on_work_keys(probs, data, settings):
    """`probs` with each "not published" key of a portfolio other than `work` that site.json's `work.meta` or `work.cardMeta`
    lists reworded while the setting `workKeys` is unmeasured (dev #942, K1): a template applies `work`'s lists to every
    portfolio, and `adopt.py parity` measures `workKeys: all`, which writes them into each other portfolio's page.md; once
    measured, `check` judges the tree with it (`plan_settings`) and the warning is gone. Same path, line and standing."""
    if "workKeys" in (settings or {}):
        return probs
    work = (data or {}).get("work") if isinstance(data, dict) else None
    listed = set()
    for k in ("meta", "cardMeta"):
        for item in (work or {}).get(k) or () if isinstance(work, dict) else ():
            listed.add(item if isinstance(item, str) else (workcheck.pair_label(item) or (None,))[0])
    out = []
    for p in probs:
        m, o = _PIECE_KEY.match(p.message), _OTHER_PORTFOLIO.search(p.message)
        if m and o and o.group(1) != "work" and m.group("k") in listed and not p.mechanical:
            out.append(_reworded(p, p.message, "run `adopt.py parity`: site.json's work.meta or work.cardMeta lists '%s', your "
                                 "builder applies those lists to every portfolio, and parity measures `workKeys: all`, which "
                                 "lists them in this portfolio's page.md" % m.group("k")))
            continue
        out.append(p)
    return out

def accept_warnings(acc, pending=(), parity=None, notes=None):
    """The build's WARNINGS over the tree adopt would write, as problems (dev #885, dev #882; adopt-honesty W1): a stray
    `.md` or sub-folder in a piece folder, a piece key neither built in nor in meta or cardMeta. They never change what
    the build publishes, so the build says them and builds, and PARITY still measures such a tree. Where nothing has been
    converted yet, `check`, `inventory` and `apply` list each with its path and fix and refuse until it is settled: never
    a quiet "adopt ok" over a page that is not published. `acc` is None when the build could not run. A piece key some
    view or setting reads is sorted by `keycover.cover_keys` (dev #965): covered, read elsewhere (a note, never "remove"),
    or unknown; `pending` and `parity` are passed on to it. A "read elsewhere" note is a note, not a decision (design 6.1): it is
    never returned, so neither `check`'s count nor `apply` waits on it; a caller that prints it passes `notes`, a list it fills."""
    if acc is None:
        return []
    model_ = getattr(acc, "model", None)
    views = dict((pf.slug, pf.settings.get("view")) for pf in getattr(model_, "portfolios", None) or ())
    probs, found = split_notes(cover_keys(reword_unmodelled(list(getattr(acc, "warnings", ()) or ())), views, pending, parity,
                                          UNMODELLED_PIECE_KEYS, SHOWCASE_LEFT))
    if notes is not None:
        notes.extend(found)
    return probs


_UNKNOWN_KEY = re.compile(r"^(content/references/[^/]+/reference\.json): unknown key '")
_UNKNOWN_FM_KEY = re.compile(r"^(\S+): unknown front matter key '[^']*' \(allowed: (.*)\)$")
_UNKNOWN_TOKEN = re.compile(r"^(\S+): unknown token \{\{[^{}]*\}\}$")
_BLOCK = re.compile(r"\{\{\s*#page:[^{}\s]+\s*\}\}.*?\{\{\s*/page\s*\}\}", re.S)
_COMMENT = re.compile(r"<!--.*?-->", re.S)


def _blank(m):
    """The matched text with every character but a newline made a space, so a position in the result is the same
    line as in the original."""
    return re.sub(r"[^\n]", " ", m.group(0))


def _tree_schema(files):
    """The schema the converted tree's site.json carries (the tree adopt would write), or the highest the build reads
    when it cannot be read: an unreadable value must not hide a key the newest schema allows (design R4 rows 6, 8)."""
    try:
        return int(json.loads(files["site/site.json"].decode("utf-8")).get("schema", 1))
    except (KeyError, ValueError, TypeError, AttributeError, UnicodeDecodeError):
        return configkeys.SCHEMA_MAX


def every_refusal(files, problems):
    """`build.accept`'s problems, with EVERY refusal in a file reported, not the first (dev #893, K1). The build stops
    a unit at its first refusal: a `reference.json` at its first unknown key, a page at its first unknown token. A
    person fixing a captured-references folder or a hand-made home then ran `check` once per key. Here, for each file
    the build named such a refusal in, the file is read again and every one of its kind is listed, each with its
    line, in the form the build words it (so the two agree, and a problem the build already reported is not
    listed twice). `files` is the converted tree as `build.accept` was given it.

    A token inside a `{{#page:X}}` block is not read here (the build removes the block when X is not built, and
    adopt does not know that), so a token only there is reported by the build or not at all, never invented."""
    out = list(problems)
    have = set((p.path, p.message) for p in out)
    done = set()
    schema = _tree_schema(files)
    for p in problems:
        m = _UNKNOWN_KEY.match(p.message)
        if m and m.group(1) not in done and m.group(1) in files:
            done.add(m.group(1))
            rj = m.group(1)
            try:
                text = files[rj].decode("utf-8")
                data = json.loads(text)
            except (ValueError, UnicodeDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            out = [q for q in out if q.path != rj or not _UNKNOWN_KEY.match(q.message)]
            for k in data:
                if k in keytables.reference_keys(schema):      # the converted tree's own schema (R4 row 8)
                    continue
                at = re.search(r'"%s"\s*:' % re.escape(k), text)
                out.append(diagnostics.make_problem("%s: unknown key '%s'" % (rj, k), rj, "refused by the build",
                                                   "accepted by the build", p.fix, False,
                                                   text.count("\n", 0, at.start()) + 1 if at else None))
            have = set((q.path, q.message) for q in out)
            continue
        m = _UNKNOWN_FM_KEY.match(p.message)
        if m and m.group(1) not in done and m.group(1) in files:
            path, allowed = m.group(1), m.group(2).split(", ")
            done.add(path)
            try:
                text = files[path].decode("utf-8")
                meta, _body = frontmatter.parse_front_matter(text, path)
            except (errors.ContentError, UnicodeDecodeError):
                continue
            out = [q for q in out if q.path != path or not _UNKNOWN_FM_KEY.match(q.message)]
            for k in meta:
                if k in allowed:
                    continue
                at = re.search(r"^%s:" % re.escape(k), text, re.M)
                out.append(diagnostics.make_problem("%s: unknown front matter key '%s' (allowed: %s)" % (path, k, m.group(2)),
                                                   path, "refused by the build", "accepted by the build", p.fix, False,
                                                   text.count("\n", 0, at.start()) + 1 if at else None))
            have = set((q.path, q.message) for q in out)
            continue
        m = _UNKNOWN_TOKEN.match(p.message)
        if m and m.group(1) not in done and m.group(1) in files:
            path = m.group(1)
            done.add(path)
            try:
                origin = files[path].decode("utf-8")
            except UnicodeDecodeError:
                continue
            masked = _BLOCK.sub(_blank, _COMMENT.sub(_blank, origin))
            layout = path == "site/templates/layout.html"
            listed = []
            for tm in tokens.TOKEN_RE.finditer(masked):
                if tokens.token_known(tm.group(1), layout, schema):
                    continue
                listed.append(diagnostics.make_problem("%s: unknown token {{%s}}" % (path, tm.group(1)), path,
                                                      "refused by the build", "accepted by the build", p.fix, False,
                                                      masked.count("\n", 0, tm.start()) + 1))
            # every PLACE a token is unknown is listed, each at its line (R4 row 8: a schema-3 page with two
            # `{{navLinks}}` reports both); the build's own line for a token this scan did not find (one the build read
            # and this masked scan did not) stays
            said = set(q.message for q in listed)
            out = [q for q in out if q.path != path or not _UNKNOWN_TOKEN.match(q.message) or q.message not in said]
            out.extend(listed)
            have = set((q.path, q.message) for q in out)
    out = [_reference_line(q, files) for q in out]
    return sorted(out, key=lambda q: (q.path or "", q.lineno or 0, q.message))


_REFERENCE_VALUE = re.compile(r"^content/references/[^/]+/reference\.json: '(?P<k>[A-Za-z]+)' ")


def _reference_line(p, files):
    """`p` with its line when it is a refusal of one key's value in a `reference.json` the build gave no line for (dev #964:
    the "follows from ...reference.json" line of a `ref:` that names it then says where): the line of that key's member."""
    m = _REFERENCE_VALUE.match(p.message)
    if not m or p.lineno or p.path not in files:
        return p
    try:
        text = files[p.path].decode("utf-8")
    except (UnicodeDecodeError, AttributeError):
        return p
    at = re.search(r'"%s"\s*:' % re.escape(m.group("k")), text)
    return p if at is None else diagnostics.make_problem(p.message, p.path, p.found, p.expected, p.fix, p.mechanical,
                                                         text.count("\n", 0, at.start()) + 1)


def size_copy_note(tree):
    """One line, or None: the site holds `<stem>.w<NNN>.<ext>` copies beside their originals (design-site-fidelity
    section 5.3). At schema 3 they are `srcset` candidates and keep their names and URLs, but `srcset` is one of the
    things parity does not compare, so whether the plugin's matches the person's builder's is not measured."""
    paths = set(tree.paths())
    n = 0
    for p in paths:
        if p.startswith("content/") and "/media/" in p:
            m = treeschema._SIZE_COPY_RE.match(posixpath.basename(p))
            if m and posixpath.dirname(p) + "/" + m.group("stem") + m.group("ext") in paths:
                n += 1
    if not n:
        return None
    return ("size copies: %d file(s) named <stem>.w<NNN>.<ext> sit beside their originals. site.json is written as schema 3 "
            "so the build lists them in the image's srcset, and no file is renamed, so no image address changes. Parity "
            "does not compare srcset, so whether it matches your builder's is UNVERIFIED." % n)


def check_only(chosen=()):
    """The conversion classes `check` and `inventory` judge the tree by: every class except an OPT_IN one the person
    has not chosen, because apply will not make it. (Parity measures every class: it passes no `only`.)"""
    return set(c for c, _l, _w in CONVERSION_CLASSES if c not in OPT_IN_CLASSES or c in chosen)


def site_problems(tree, data, paper=None, kind=None, folders=None, chosen=(), settings=None, parity=None, notes=None):
    """Every problem in what adopt WOULD write, all at once: `siteconfig.problems()` over the
    converted site.json (BEFORE the mechanical label conversion, so a pair-form label is reported and
    marked `apply fixes this`), then `content.layout_problems()` over the tree. A list of
    `siteconfig.Problem`; empty means nothing stands in the way (design section 7.1). A meta-refresh page
    adopt will turn into a redirect is one more mechanical problem (design 7.5). `settings` are the plan's measured and
    chosen settings (`plan_settings`): the tree is judged as apply would write it (dev #942, K1: `workKeys: all`, measured
    by parity, puts `work`'s meta into every portfolio's page.md, and `check` still called those keys unlisted). `parity` (the
    plan's record) and `notes` (a list) go to `accept_warnings`: the "read elsewhere" notes land in `notes`, ending with what
    parity knows."""
    d, _resume = _converted_dict(tree, data, paper, kind)
    probs = list(model.problems(d))
    cfg = None
    if not probs:
        try:
            cfg = model.parse_data(d)
        except diagnostics.SiteConfigError:
            cfg = None
    else:
        fixed = dict(d)
        if "work" in fixed:
            fixed["work"], _conv = label_conversions(fixed["work"])
        normalise_redirect_keys(fixed)          # F4: a trailing slash on a redirect key is the one thing adopt fixes
        still = set((p.path, p.message) for p in model.problems(fixed))
        probs = [diagnostics.make_problem(p.message, p.path, p.found, p.expected,
                                         "drop the trailing slash (adopt does; the build writes the same address)",
                                         True, p.lineno)
                 if (p.path or "").startswith("redirects") and (p.path, p.message) not in still else p
                 for p in probs]
        try:
            cfg = model.parse_data(fixed)
        except diagnostics.SiteConfigError:
            cfg = None
    # the layout is judged over the tree as the classes that CHANGE what a folder holds (page files, the home keys, the
    # references, the token rewrites) leave it: a home written as `home.md` is converted by `pageFiles`, so it is not also
    # refused as a home with no `index.md`. The classes that move folders (`layout`) are not applied here: their folders are
    # the ones listed (and decided) below.
    shape = set(("tokens", "pageFiles", "blocks", "references", "homeKeys", "resumeHeader", "navTokens")) & check_only(chosen)
    removed = []
    try:
        files, cnotes = converted_site_files(tree, data, paper, folders, kind, shape, strict=False)
        removed = cnotes["removed"]
    except Refused:
        files = {}
        for p in token_files(tree):
            text = tree.text(p)
            new = rewrite_tokens(text, portfolio_folders(tree), layout=(p == "site/templates/layout.html"),
                                 home=home_feed(tree), labels=site_json_labels(data))[0]
            if new != text:
                files[p] = new.encode("utf-8")
    # a folder the person has DECIDED (`adopt.py folder <name> source|portfolio`) is settled: apply makes the move or
    # writes the page.md, and `accept_problems` below judges the tree with it made. It is not listed as undecided
    # (dev #887, D1: `check` read the layout of the tree as it stands, so a decided folder was still on the list).
    probs += [p for p in layout_mod.layout_problems(TreeFiles(tree, files, removed), cfg.siteKind if cfg else "portfolio", cfg)
             if not (p.found == "no page.md" and (p.path or "").startswith("content/")
                     and p.path[len("content/"):].rstrip("/") in (folders or {}))]
    probs += redirect_problems([r for r in redirect_pages(tree, d.get("redirects"))[0] if not r.boiler])
    have = set((p.path, p.message) for p in probs)
    refusals, acc = accept_problems(tree, data, paper, folders, kind, check_only(chosen), settings=settings)
    found = []
    probs += [p for p in waits_on_work_keys(refusals + accept_warnings(acc, (), parity, found), data, settings)
              if (p.path, p.message) not in have]
    if notes is not None:            # a note keeps K1's word (its key in work.meta: parity measures `workKeys`), still a note
        notes.extend(waits_on_work_keys(found, data, settings))
    probs += piece_both_problems(tree, folders) + redirect_collision_problems(tree, d)
    return probs



def plan_settings(plan):
    """The settings apply writes: those the last `parity` measured and those the person chose (`apply.prepare` reads the same)."""
    return dict((k, v["value"]) for k, v in (plan.get("settings") or {}).items() if v["how"] in ("measured", "chosen"))

def held_problems(tree, data, plan):
    """`you decide` problems that `check` and `inventory` must not leave out (dev #864 verify, F4): when a conversion
    class is held back (parity measured a change, or could not measure), apply does NOT make it, and if site.json
    needs that class to be valid (a redirect key still ending in `/`) the converted site.json is refused. `check`
    said "apply fixes this" and `apply` then refused with a message naming neither the class nor why. This returns the
    one problem that says it, so `check`, `inventory` and `apply` agree. Empty when nothing held leaves site.json
    unreadable."""
    try:
        _files, notes = converted_site_files(tree, data, plan["paper"], plan["folders"], plan.get("siteKind"))
    except Refused:
        return []
    rows = decide_conversions(notes, plan["parity"], template_fingerprint(tree), plan["convert"])
    # dev #890, B1: a conversion the person CHOSE, on which P1 showed the kept builder FAILS, is a problem here: the one
    # `apply` refuses on, so `check` never says "adopt ok" over a tree `apply` will not write
    out = [diagnostics.make_problem(
        "%s is chosen, but your own builder FAILS on the tree it makes (%s) and parity is %s"
        % (r["class"], r["failure"], (plan["parity"] or {}).get("verdict", "not run")),
        None, "a chosen conversion that breaks your own builder", "one your builder still builds",
        "`adopt.py convert %s --keep` leaves it as written; or fix the builder, run `adopt.py parity` again, and "
        "accept it once parity is EQUAL or ACCEPTED" % r["class"]) for r in broken_chosen(rows, plan)]
    held = [r for r in rows if r["status"] == "you decide"]
    if not held:
        return out
    only = set(c for c, _l, _w in CONVERSION_CLASSES) - set(r["class"] for r in held)
    try:
        converted_site_files(tree, data, plan["paper"], plan["folders"], plan.get("siteKind"), only)
    except Refused as e:
        if str(e).startswith("the converted site.json is not valid"):
            return out + [diagnostics.make_problem(
                "site.json cannot be converted while a conversion it needs is held back: %s" % str(e)[len("the converted site.json is not valid: "):],
                "site/site.json", "a site.json the build refuses", "one it reads",
                "settle the held conversion(s) first: %s" % "; ".join("%s (%s)" % (r["class"], r["reason"]) for r in held
                                                                     if r["class"] not in OPT_IN_CLASSES))]
    return out


def broken_chosen(rows, plan):
    """The rows of a conversion the person CHOSE on which P1 showed the kept builder FAILS (dev #890, B1), while parity
    is not EQUAL or ACCEPTED: the ones `apply` refuses on. One definition, so `check`, `inventory` and `apply` agree."""
    if (plan["parity"] or {}).get("verdict") in ("EQUAL", "MARKUP-ONLY", "ACCEPTED"):
        return []
    return [r for r in rows if r.get("failure") and r["class"] in OPT_IN_CLASSES and r["class"] in plan["convert"]]


def piece_both_problems(tree, folders=None):
    """One `you decide` problem per piece folder holding BOTH `work.md` and `index.md` (F2): adopt never renames
    over a file, and the plugin's build reads only `index.md`."""
    _pairs, both = piece_renames(tree, portfolio_folders(tree) + sorted(n for n, c in (folders or {}).items()
                                                                        if c == "portfolio"))
    return [diagnostics.make_problem("%s/ holds both work.md and index.md" % posixpath.dirname(p), posixpath.dirname(p) + "/",
                                    "two piece files", "one: index.md", "keep one of the two by hand: the plugin's "
                                    "build reads index.md, and adopt never renames over a file") for p in both]


def redirect_collision_problems(tree, d):
    """One `you decide` problem per pair of `redirects` keys that name the same page once their trailing slash is
    stripped but point at different targets (F4): adopt leaves both as written."""
    _changes, collide = normalise_redirect_keys(dict(d))
    return [diagnostics.make_problem("site.json redirects '%s' and '%s' are the same address with different targets"
                                    % pair, "redirects", "two entries for one address", "one entry",
                                    "keep one of them in site/site.json") for pair in collide]


_FOLLOW_REDIRECT = re.compile(r"^redirect '[^']*' points at '(?P<t>[^']*)', which is not a built page$")
_FOLLOW_LINK = re.compile(r"\{\{link:(?P<t>[^{}\s]+)\}\} names no built page")
_FOLLOW_REF = re.compile(r"^\S+: (?:ref: (?P<n>[^\s]+) names no reference under content/references/"
                         r"|\w+ ref:(?P<c>[^\s]+) names no reference with a card image)")   # a `ref:` line; a `cover: ref:X`
_FOLLOW_HOME = re.compile(r"\{\{home:[^{}]*\}\} is fed by (?P<f>\S+), which the build refuses")


def _is_pointer(q):
    return bool(_FOLLOW_REDIRECT.match(q.message) or _FOLLOW_LINK.search(q.message) or _FOLLOW_REF.match(q.message)
                or _FOLLOW_HOME.search(q.message))


def _follows(p, probs):
    """The `you decide` problem that `p` is a CONSEQUENCE of, or None (dev #893, K2; dev 943, 944). A pointer at a thing
    the build refuses is not a second thing to decide: the thing is not built, so nothing can point at it, and the
    pointer resolves the moment it does. The pointers: a redirect or a `{{link:X}}` that names a portfolio `X`; a
    `ref: X` line when `content/references/X/` is there and refused; a `{{home:<part>}}` token when the home page is
    there and refused (the message names the file). The cause is the first problem that is not itself a pointer, is not
    mechanical, and sits under that portfolio or reference folder, or is in that very file."""
    if p.mechanical:
        return None
    m = _FOLLOW_REDIRECT.match(p.message) or _FOLLOW_LINK.search(p.message)
    if m:
        first = m.group("t").strip("/").split("/")[0]
        under = "content/%s/" % first if first else None
        exact = None
    elif _FOLLOW_REF.match(p.message):
        m = _FOLLOW_REF.match(p.message)
        under, exact = "content/references/%s/" % (m.group("n") or m.group("c")), None
    elif _FOLLOW_HOME.search(p.message):
        under, exact = None, _FOLLOW_HOME.search(p.message).group("f")
    else:
        return None
    if not under and not exact:
        return None
    for r in probs:
        if (r is not p and not r.mechanical and not _is_pointer(r)
                and ((exact is not None and r.path == exact) or (under is not None and (r.path or "").startswith(under)))):
            return r
    return None


_FILE_COUNT = re.compile(r" \(\d+ files? in it\)")      # a stray folder's own size is not its cause (dev #885)


def _cause_key(p):
    """Problems with the same key are one cause: the same message once the file they are in is taken out, the same
    fix, the same standing. A message that names anything else of its own (a folder's name, a redirect's key) keeps
    its name, so two such problems stay two."""
    msg = p.message.replace(p.path, "<path>") if p.path else p.message
    return (_FILE_COUNT.sub("", msg), p.fix, p.mechanical)


def _at(p):
    return "%s:%d" % (p.path, p.lineno) if p.path and p.lineno else (p.path or "the site")


def analyse_problems(probs):
    """{items, fixes, decisions, follow}: `probs` as CAUSES (dev #893, K2). `items` is [(problems that share one
    cause, the problem they follow from or None)] in the order the first of each appeared; `fixes` and `decisions`
    count causes, not problems, so a count of `you decide` is a count of things to settle: 35 captured references in
    the template's format are one, and a redirect to a portfolio that is refused is not counted at all (it is listed
    as following from the portfolio's own problem and resolves with it)."""
    items, index, follow = [], {}, 0
    for p in probs:
        cause = _follows(p, probs)
        if cause is not None:
            items.append(([p], cause))
            follow += 1
            continue
        key = _cause_key(p)
        if p.mechanical:             # a fix adopt makes is not a decision: each is listed and counted as it always was
            items.append(([p], None))
            continue
        if key in index:
            items[index[key]][0].append(p)
        else:
            index[key] = len(items)
            items.append(([p], None))
    own = [it for it in items if it[1] is None]
    fixes = sum(1 for g, _c in own if g[0].mechanical)
    return {"items": items, "fixes": fixes, "decisions": len(own) - fixes, "follow": follow}


def format_problems(probs):
    """The lines `check` and `inventory` print for a list of problems: one line per cause (a cause shared by several
    places is one line naming how many), a consequence marked with what it follows from, and counts of causes. A
    list with no shared cause and no consequence prints exactly as it always did."""
    if not probs:
        return []
    a = analyse_problems(probs)
    plain = all(len(g) == 1 and c is None for g, c in a["items"])
    if plain:
        L = ["%d problem(s) in what adopt would write: apply fixes %d, you decide %d" % (len(probs), a["fixes"],
                                                                                      a["decisions"])]
    else:
        L = ["%d problem(s) from %d cause(s) in what adopt would write: apply fixes %d, you decide %d%s" % (
            len(probs), len(a["items"]) - a["follow"], a["fixes"], a["decisions"],
            (" (%d more follow from a cause above and resolve with it)" % a["follow"]) if a["follow"] else "")]
    for group, cause in a["items"]:
        p = group[0]
        if cause is not None:
            L.append("  - %s -- follows from %s; resolves with it" % (p.line().rsplit(" -- fix: ", 1)[0], _at(cause)))
        elif len(group) == 1:
            L.append("  - %s" % p.line())
        else:
            where = ", ".join(_at(q) for q in group[:3]) + (", and %d more" % (len(group) - 3) if len(group) > 3 else "")
            L.append("  - %d places, one cause: %s -- fix: %s (%s) [%s]" % (
                len(group), _cause_key(p)[0], p.fix, "apply fixes this" if p.mechanical else "you decide", where))
    return L


def problem_dicts(probs):
    return [{"path": p.path, "found": p.found, "expected": p.expected, "fix": p.fix,
             "mechanical": p.mechanical, "message": p.message, "lineno": p.lineno} for p in probs]


def problems_from_dicts(dicts):
    """The `Problem`s `problem_dicts` made, so a result that crossed a JSON boundary prints through
    `format_problems` exactly as the check does."""
    return [diagnostics.make_problem(d["message"], d["path"], d["found"], d["expected"], d["fix"],
                                    d["mechanical"], d.get("lineno")) for d in dicts]
