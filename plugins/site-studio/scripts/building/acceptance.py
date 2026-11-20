"""The pieces of the acceptance run: loading the model, turning a refusal into a `Problem`, the schema-3
meta-key rule, the carriage-return check, and a schema-5 trigger with nowhere to print (`trigger_slot_findings`)."""

import re

import content as C
import looks
from contentmodel import keytables, layout as layout_mod, models, pagefiles
from configschema import configkeys, diagnostics, treeschema
from contentmodel.errors import ContentError

from building.constants import HTML_EXTS
from building.outcomes import BuildError


def _load_model(files, cfg, drafts, check_resume_pdf):
    """The content model for a site. A `portfolio` loads `content/`; a `hub` or `custom` builds
    nothing from it, so it gets an empty model after every refusal of design section 4.1 is
    checked: portfolio-only keys, portfolio content, and a missing `site/src/index.html`."""
    layout = [p.message for p in layout_mod.layout_problems(files, cfg.siteKind, cfg)]
    if cfg.siteKind == "portfolio":
        if layout:
            raise ContentError("; ".join(layout), fix="fix each problem listed, then build again")
        return C.load_content(files, cfg, drafts=drafts, check_resume_pdf=check_resume_pdf)
    problems = treeschema.kind_conflicts(cfg) + layout
    if "site/src/index.html" not in files:
        problems.append("a %s site's home page is site/src/index.html, and it is missing" % cfg.siteKind)
    if problems:
        raise ContentError("; ".join(problems), fix="fix each problem listed, then build again")
    return models.Content()


def _problem_from(e, default_path=None):
    """One `siteconfig.Problem` for a `BuildError` or `ContentError`: its message, its `path`/`lineno`/`fix`
    when it carries them, else the file named at the head of the message (`path:12: ...`), else the
    unit being built. Never mechanical: only the person can fix a refusal the build raises."""
    msg = str(e)
    path = getattr(e, "path", None)
    lineno = getattr(e, "lineno", None)
    if path is None:
        m = re.match(r"^([^\s:][^\s]*?)(?::(\d+))?: ", msg)
        if m and ("/" in m.group(1) or "." in m.group(1)):
            path = m.group(1)
            if lineno is None and m.group(2):
                lineno = int(m.group(2))
    fix = getattr(e, "fix", None) or "fix the problem named here, then run the check again"
    return diagnostics.make_problem(msg, path or default_path, "refused by the build", "accepted by the build",
                                   fix, False, lineno)


def _not_checked(stage_name, e, default_path=None):
    """A refusal that is not a refusal: an exception the build did not mean to raise. It is loud, never a
    traceback and never a quiet pass (CLAUDE.md: a missing thing reads as an empty thing)."""
    return diagnostics.make_problem("NOT CHECKED: %s raised %s: %s" % (stage_name, type(e).__name__, e),
                                   default_path, "an exception the build did not mean to raise",
                                   "a refusal with a fix", "report this to site-studio, with the file named "
                                   "here", False)


def _cr_problems(out):
    probs = []
    for rel in sorted(out, key=lambda p: p.encode("utf-8")):
        if (rel.lower().endswith(keytables.TEXT_EXTS) or rel in ("CNAME", "robots.txt")
                or rel.lower().endswith(HTML_EXTS)) and b"\r" in out[rel]:
            probs.append(diagnostics.make_problem("%s would be written with a carriage return" % rel, rel,
                                                 "a carriage return", "LF line endings",
                                                 "save the file with LF line endings"))
    return probs


def _meta_key_problems(model, cfg):
    """Schema 3 only (design-site-fidelity section 6.2): a `meta` or `cardMeta` list that names a key the build
    already reads or shows (`siteconfig.BUILTIN_PIECE_KEYS`) is refused, because the build shows it already and
    a second copy would print it twice. Below schema 3 such a list builds exactly as 0.2.0 built it, so this is
    never asked of a schema-1 or schema-2 reading. The Problem names the file the list is in: the portfolio's
    page.md when that page sets the list, else site.json (`work`'s base)."""
    out = []
    for pf in model.portfolios:
        for part in ("meta", "cardMeta"):
            for key in pf.settings[part]:
                if key not in configkeys.BUILTIN_PIECE_KEYS:
                    continue
                path = pf.page_source if (pf.page_source and part in pf.page_keys) else "site/site.json"
                out.append(diagnostics.make_problem(
                    "%s: '%s' lists the built-in key '%s', which the build shows already" % (path, part, key),
                    path, "'%s' in %s" % (key, part), "no built-in key in %s" % part,
                    "remove '%s' from %s; the build shows it already" % (key, part)))
    return out


def warning_line(w):
    """One warning as the build prints it: where (with the line when known), what is not published, the fix."""
    at = "%s:%d: " % (w.path, w.lineno) if (w.lineno and w.path) else ""
    msg = w.message
    if at and msg.startswith(w.path + ": "):
        msg = msg[len(w.path) + 2:]
    return "%s%s -- fix: %s" % (at, msg, w.fix)


def _refusal(problems):
    """One `BuildError` that carries every problem; its message is the join of theirs (exactly the one
    problem's message when there is one)."""
    first = problems[0]
    return BuildError("; ".join(p.message for p in problems), path=first.path, lineno=first.lineno,
                      fix=first.fix, problems=problems)


# ------------------------------------------------------------- a trigger with nowhere to print (design-movement-view 4.4)
# The slot each schema-5 trigger prints through (`cardImage` is checked only under `view: roles`, where a card has no
# picture without it; `cardKicker` in every part that shows the portfolio's pieces).
TRIGGER_SLOTS = {"cardImage": "image", "pieceLink": "link", "pieceTeaser": "teaser", "cardKicker": "kicker"}
_VIEW_TILES = {"steps": ("steps-view", "item"), "showcase": ("showcase-view", "item")}
_ROLES_PARTS = (("roles-view", "item"), ("roles-view", "item-current"))


def _index_parts(pf):
    """The parts the index of portfolio `pf` shows its pieces in, as the build renders them: a card (`card.wrap`) on a
    grid, the view's tile, and under `view: roles` the employer card the build uses for each employer (`item-current`
    where one of its pieces is current). A roles portfolio with no piece yet counts both cards; `map` and `page` show
    no card or tile."""
    view = pf.settings.get("view")
    if view in _VIEW_TILES:
        return {_VIEW_TILES[view]}
    if view == "roles":
        current = {}
        for piece in pf.pieces:
            name = piece.meta.get("employer")
            name = name.strip() if isinstance(name, str) else name
            current[name] = current.get(name, False) or piece.meta.get("current") is True
        if not current:
            return set(_ROLES_PARTS)
        return set(_ROLES_PARTS[1] if cur else _ROLES_PARTS[0] for cur in current.values())
    if view in ("map", "page"):
        return set()
    return {("card", "wrap")}


def _home_parts(model, cfg, files, grammar):
    """{portfolio slug: parts} the generated home page shows a piece of that portfolio in: a featured card
    (`card.wrap`; `featured:` or the `featured: true` flags, as `selection` reads them) and, at schema 4, a home
    showcase tile (`home-showcase.item`). {} when the home page is the person's own `site/src/index.html`."""
    out = {}
    if "site/src/index.html" in files:
        return out
    meta = model.home.meta if model.home else {}
    if cfg.featuredFrom == "flags":
        featured = [pc for pf in model.portfolios for pc in pf.pieces if pc.meta.get("featured") is True and not pc.draft]
    else:
        featured = [model.piece(k) for k in meta.get("featured") or []]
    for pc in featured:
        if pc is not None:
            out.setdefault(pc.portfolio, set()).add(("card", "wrap"))
    if model.home and grammar >= 4:
        for entry in meta.get("showcase") or []:
            parsed = pagefiles.parse_showcase_entry(entry) if isinstance(entry, str) else None
            pc = model.piece(parsed[0]) if parsed else None
            if pc is not None:
                out.setdefault(pc.portfolio, set()).add(("home-showcase", "item"))
    return out


def _has_slot(look, construct, part, slot):
    """Whether the part as the build renders it (the look's own, else the default look's) holds `{{slot}}`."""
    return ("{{%s}}" % slot) in looks.part_markup(construct, part, look)


def trigger_slot_findings(model, cfg, files, look, grammar=None):
    """(problems, notes) of design-movement-view section 4.4, over the tree as built. A schema-5 trigger whose value has
    no slot in the site's look part that would carry it is refused, naming both: `cardImage` under `view: roles`
    (`{{image}}`), `pieceLink` (`{{link}}`) and `pieceTeaser` (`{{teaser}}`) in `piece.wrap`; `cardKicker` only when NO
    part that shows that portfolio's pieces (its index, the home page's featured cards and showcase tiles) has a
    `{{kicker}}`. A part OF THE SITE'S OWN LOOK that shows those pieces without one is a note, printed on every build.
    A part the look omits renders with the default look's, which has every slot. `cardKicker` in a portfolio whose pieces
    no card or tile shows at all (a `map` or `page` index, no home card or tile) does nothing under any look, so it is
    refused with or without a site look (invariant 4: no key is silent). Otherwise, no site look (`look` None): nothing."""
    problems, notes = [], []
    if cfg.siteKind != "portfolio":
        return problems, notes
    home = _home_parts(model, cfg, files, cfg.schema if grammar is None else grammar)
    for pf in model.portfolios:
        on = keytables.active_triggers(pf.settings)
        for key in sorted(k for k in TRIGGER_SLOTS if k in on):
            slot = TRIGGER_SLOTS[key]
            src = pf.page_source if (pf.page_source and key in pf.page_keys) else "site/site.json"
            if key == "cardKicker":
                parts = sorted(_index_parts(pf) | home.get(pf.slug, set()))
                if not parts:
                    problems.append(diagnostics.make_problem(
                        "%s sets cardKicker, and no card or tile shows the pieces of %s (its index is view: %s, and the "
                        "home page names none of them); the kicker would print nowhere, so remove the key"
                        % (src, pf.slug, pf.settings.get("view")), src, "cardKicker with nowhere to print",
                        "a card or tile showing the pieces of %s" % pf.slug, "remove cardKicker from %s" % src))
                    continue
            if look is None:
                continue
            if key == "cardImage":
                if pf.settings.get("view") != "roles":
                    continue
                parts = sorted(_index_parts(pf))
            elif key != "cardKicker":
                parts = [("piece", "wrap")]
            missing = [cp for cp in parts if not _has_slot(look, cp[0], cp[1], slot)]
            if key == "cardKicker" and len(missing) < len(parts):
                notes.extend("%s sets cardKicker, and %s.%s of the site's look (%s) shows pieces of %s with no "
                             "{{kicker}}, so the kicker does not print there; add the slot to that part if it should"
                             % (src, c, p, look.where, pf.slug) for c, p in missing if look.has(c, p))
                continue
            if not missing:         # every part has the slot
                continue
            named = " or ".join("%s.%s" % cp for cp in missing)
            problems.append(diagnostics.make_problem(
                "%s sets %s, and the site's look (%s) has no {{%s}} in %s; add the slot to that part, or remove the key"
                % (src, key, look.where, slot, named), src, "%s with no {{%s}} to print it" % (key, slot),
                "a {{%s}} in %s" % (slot, named), "add {{%s}} to %s in %s, or remove %s from %s"
                % (slot, named, look.where, key, src)))
    return problems, notes
