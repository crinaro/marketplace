"""What a build used: `Acceptance.used`, the repo paths the build read to make its output (design-adopt-parity-2 section 8,
rule S1). Adopt's file accounting reads it (a file in `used` is published when the old builder uses it too, and is never
sent to the counterfactual), so a comment-stripped stylesheet and a renamed home file land.

`used` holds, each only when it is a file of the build input:
- every output's source (`_PageBase.owner`: pages, `site/src` files, stylesheets, scripts and media alike, and at schema 6
  each `site/carried/<path>` the `carried` key names; a `site/carried/` file in a tree without the key is never read and
  never in `used`);
- the model sources of each built page (`pages[...]["source"]` and `["lastmod_src"]`: a piece, the home, about and
  resume files), every portfolio's `page.md`, and the home's file when a `site/src` page expanded a `{{home:<part>}}`
  token;
- every printed reference's `reference.json` (`used_refs`);
- the looks the site names (`look`, and at schema 7 `lookLocal`) and their stylesheets (a look file no key names is never
  read and never in `used`), the layout when a generated page was wrapped in it, `site.json`;
- the resume PDF's sidecar (`<pdf>.json`) when the PDF is published.

Collecting it writes no byte: the output is what it was without it.
"""

GENERATED_NOT = ("site", "redirect", "carried")   # page kinds the layout never wraps (a `site/src` page, a redirect, a carried page)


def used(b, files):
    """The sorted repo paths builder `b` (an `_Builder` that has run) used, of the build input `files`."""
    found = set(src for _out, src in b.owner.values())
    for page in b.pages.values():
        found.update((page.get("source"), page.get("lastmod_src")))
    model = b.model
    # a portfolio's page.md names it in the menu even when its index is a redirect to its one piece (`menuLinks`)
    found.update(pf.page_source for pf in model.portfolios)
    if getattr(b, "_home_split", None) and model.home is not None:     # a `{{home:<part>}}` token read the home file
        found.add(model.home.source)
    found.update("content/references/%s/reference.json" % name for name in b.used_refs)
    if b.look is not None:          # the files `look` and `lookLocal` name (schema 7: laid over each other), never another
        found.update((b.cfg.look, getattr(b.cfg, "lookLocal", None)))
        found.update(b.look.stylesheets)
    if any(page.get("kind") not in GENERATED_NOT for page in b.pages.values()):
        found.add("site/templates/layout.html")
    found.add("site/site.json")
    pdf = getattr(model, "resume_pdf", None)
    if pdf and pdf[0] in found:          # published (an output's source): its sidecar is what proves it current
        found.add(pdf[0] + ".json")
    return sorted(p for p in found if isinstance(p, str) and p in files)
