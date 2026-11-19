"""listing: `build.py --list`: what the working tree holds (portfolios, pieces, references, pages), drafts included,
and its one-line-per-item text form."""

from contentmodel import frontmatter
import os
from building.acceptance import _load_model
from building.gitfiles import _disk_files
from building.outcomes import BuildError
from configschema import diagnostics, model as model_mod, treeschema
from contentmodel.errors import ContentError


def inventory(repo):
    """`--list`: what the working tree holds, drafts included."""
    repo = os.path.abspath(repo)
    files = _disk_files(repo)
    raw = files.get("site/site.json")
    if raw is None:
        raise BuildError("site/site.json is not in the working tree", fix="add site/site.json, or run /site-studio:setup in the dev repo")
    try:
        cfg = model_mod.parse_text(frontmatter.decode_text(raw, "site/site.json"))
        treeschema.check_tree_schema(cfg, files)
        model = _load_model(files, cfg, True, False)
    except (diagnostics.SiteConfigError, ContentError) as e:
        raise BuildError(str(e), path=getattr(e, "path", None), lineno=getattr(e, "lineno", None), fix=getattr(e, "fix", None) or "fix the problem named above, then try again")
    inv = {"portfolios": [], "references": sorted(model.references),
           "pages": [n for n, p in (("home", model.home), ("about", model.about),
                                    ("resume", model.resume)) if p is not None]}
    if cfg.siteKind != "portfolio":
        inv["siteKind"] = cfg.siteKind
    for pf in model.portfolios:
        inv["portfolios"].append({
            "slug": pf.slug, "label": pf.settings["label"],
            "pieces": [{"slug": p.slug, "title": p.title, "draft": p.draft, "date": p.date,
                        "group": p.meta.get(pf.settings["groupBy"]) if pf.settings["groupBy"] else None}
                       for p in pf.pieces]})
    return inv


def format_inventory(inv):
    lines = []
    if inv.get("siteKind"):
        lines.append("site kind: %s (every page is site/src as written; nothing is generated)"
                     % inv["siteKind"])
    for pf in inv["portfolios"]:
        lines.append("portfolio %s (%s): %d piece(s)" % (pf["slug"], pf["label"], len(pf["pieces"])))
        for p in pf["pieces"]:
            extra = " [draft]" if p["draft"] else ""
            if p["group"]:
                extra += " group=%s" % p["group"]
            lines.append("  %s/%s  %s%s" % (pf["slug"], p["slug"], p["title"], extra))
    if inv["references"]:
        lines.append("references: %s" % ", ".join(inv["references"]))
    lines.append("pages: %s" % (", ".join(inv["pages"]) or "none"))
    return "\n".join(lines)
