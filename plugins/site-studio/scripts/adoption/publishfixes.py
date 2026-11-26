"""adoption.publishfixes -- who can fix each thing the publish would refuse, and what can still stop `apply` (dev 1068, design 1.3 and 2.4).

Part of the `adoption` package behind the entry point `adopt.py`. Two closed tables, both held complete by a test that walks the code.

ROWS: one row per finding form of the site gate, `(family, template, who, fix)`. `template` is the source form of the message, `%s`-style (the
walk in `tests/adoption/test_publishfixes.py` reads every `self.r.add(` of `sitechecks/` and the one `Finding(` of `privacy.py` the build gate
makes, and requires each call's form to be a row's template; `sitechecks/sourcescan.py` is `--scan-source`, which no publish runs, and the walk
asserts it is the only other receiver, so a new one is red). A row no call matches yet is allowed: the one S2's new finding needs is here
before the call is. `who` is one of

  adopt    `apply` or a setting does it (the fix names the setting);
  site     an edit in `content/` or `site/` (the printed line names the file where the finding's page has a source);
  person   an answer, an account, a new PDF, a file only they can make;
  plugin   nothing a site can do: `adopt.py report` files it.

`who` is never read from a site's text. A message no row matches is printed as `plugin`, with its own text, and never dropped.

STOPS: one row per place `apply` can still be refused after every check above has passed, keyed by `file::function`, with how many raises
that function holds, why the refusal cannot be known earlier (a category of `STOP_CATEGORIES`) and which §1.2 check says it first, if one does.
`adopt.py check --online` prints the categories under "can still stop apply". The walk requires every `raise DeployError`, `raise NotChecked`,
`raise error(`, `raise ReviewError` and `Stop(` of the publish path to be counted by a row, and every exception named in `deploy.py`'s `except`
clauses to be in `EXCEPTIONS`: a new raise, or a new exception name, is red until a row says why it cannot be known earlier.

THE REFUSALS OF `apply` ITSELF (dev 1068, review R1, item 2): the walk also counts every `raise Refused`, `NeedsAnswer` and `PlanError` of the functions
`adoption.apply.do_apply` can reach in `apply`, `wouldwrite`, `convert`, `carry`, `dispose`, `parity`, `plan`, `accounting`, `state`, `base` (a verb's own
refusals, in the same files, are not on that path) and in `finish.py`. Each row says one of two things, and the test holds that they are not mixed:

  named        category `named`, and the checks that say it first in the third place: `check` names it before `apply` does, by asking the same function
               (`apply` = `adoption.applyrefusals`, which runs `apply.stage`, the branch, the identity and the path rules read-only), by reading the same
               plan or basis first (`plan`, `basis`), by the stale-choice line (`stale`), as a decision still to make (`decide`: no exit code) or as a
               problem the build lists (`problems`)
  unavoidable  any other category: why it cannot be known earlier, and no check named
"""

import re
from collections import namedtuple

ADOPT, SITE, PERSON, PLUGIN = "adopt", "site", "person", "plugin"
GATE_FAMILIES = ("structure", "comments", "links", "reachable", "privacy", "domain", "media", "unfinished", "performance", "head", "nav", "basepath",
                 "size")                                  # the thirteen families of the site gate: a `publish/gate/<family>` cause exists for each
WHO_ORDER = (ADOPT, SITE, PERSON, PLUGIN)
WHO_LABEL = {ADOPT: "adopt fixes", SITE: "the site", PERSON: "you", PLUGIN: "the plugin"}

Row = namedtuple("Row", "family template who fix")

_EDIT = "edit the page's source"
_HAND = "edit the hand-written page (it is not made from content/)"

ROWS = (
    # structure
    Row("structure", "the %s family examined nothing", PLUGIN, "the gate looked at nothing in this family; `adopt.py report` files it"),
    Row("structure", "the tree holds no HTML page: nothing was checked", SITE, "the build made no page: add the site's pages under content/ or site/src/"),
    Row("structure", "required file is missing", PLUGIN, "the build leaves out a file every site needs; `adopt.py report` files it"),
    Row("structure", "a %s folder must never be published", SITE, "move that folder out of what is published, or into a folder the build does not read"),
    Row("structure", "this file is a source or maintenance file and must never be published", SITE, "remove it from site/src/ or content/, or keep it under archive/"),
    Row("structure", "source, editor or OS leftover must never be published", SITE, "delete the file from the repo"),
    Row("structure", "file name is not URL-safe (space or reserved character)", SITE, "rename the file with letters, digits, - and _ only"),
    Row("structure", "a symbolic link must never be published", SITE, "replace the link with the file itself"),
    Row("structure", "no <!doctype>", SITE, _HAND + ": start it with <!doctype html>"),
    Row("structure", "<html> has no lang attribute", SITE, _HAND + ": write <html lang=\"en\"> (the language of the page)"),
    Row("structure", "malformed markup: %s", SITE, _HAND + ": close or repair the tag named"),
    Row("structure", "expected exactly one <h1>, found %d", SITE, "give the page one top heading (content is the person's: the plugin never writes it)"),
    Row("structure", "an unexpanded site-studio token or section; to show braces as text, write &#123;&#123;", SITE,
        "the page holds a {{token}} the build did not fill: fix its name, or write the braces as &#123;&#123;"),
    # comments
    Row("comments", "HTML comment left in the published page (%d characters)", SITE, "remove the <!-- comment --> from the page's source"),
    Row("comments", "CSS comment left in an inline <style>", SITE, "remove the /* comment */ from the page's <style>"),
    Row("comments", "CSS comment left in the published stylesheet", SITE, "remove the /* comment */ from the stylesheet"),
    Row("comments", "comment left in the SVG", SITE, "remove the comment from the SVG file"),
    Row("comments", "sourceMappingURL names a local file", SITE, "remove the sourceMappingURL line, or publish the map's file"),
    # links
    Row("links", "an empty href", SITE, "give the link an address, or remove the anchor"),
    Row("links", "a javascript: link", SITE, "use a real address, or a button for what the script does"),
    Row("links", "protocol-relative URL %s: write https://", SITE, "write the address with https://"),
    Row("links", "insecure link %s: use https", SITE, "write the address with https://"),
    Row("links", "%s link %s: %s", SITE, "point the link at a page or file that is built, or remove it"),
    Row("links", "meta URL %s: %s", SITE, "correct the address in the page's <meta> tag"),
    Row("links", "fragment #%s is not an id on %s", SITE, "link to an id the page has, or add the id"),
    # reachable
    Row("reachable", "there is no index.html to start from", SITE, "add a home page (content/home.md or site/src/index.html)"),
    Row("reachable", "page cannot be reached from the home page by following links", SITE, "link to it from a page a visitor reaches, or make it a draft"),
    Row("reachable", "published but not referenced by any page or stylesheet", SITE, "reference the file from a page, or remove it"),
    # privacy
    Row("privacy", "contains the private term %s%s", SITE, "remove the term from the page, or its file name"),
    Row("privacy", "phone number %s%s", SITE, "remove the number, or publish it on purpose in a way the site allows (publicEmails is for addresses)"),
    Row("privacy", "street address %s%s", SITE, "remove the address from the page"),
    Row("privacy", "email address %s is not in publicEmails%s", SITE, "remove the address, or list it in site.json publicEmails if it is meant to be public"),
    Row("privacy", "tel: link %s", SITE, "remove the tel: link"),
    Row("privacy", "hidden image metadata (%s): %s", SITE, "import the picture again (the importer strips it), or export it without metadata"),
    Row("privacy", "PDF metadata names an author (%s)", PERSON, "export the PDF again without an author, or print a new one with `adopt.py proof --print`"),
    Row("privacy", "PDF metadata Creator %r is not a known generator", PERSON, "export the PDF again from a known program, or print a new one with `adopt.py proof --print`"),
    Row("privacy", "PDF metadata Title %r is not the title of any page in this build", PERSON, "set the PDF's Title to a page's title, or print a new one with `adopt.py proof --print`"),
    Row("privacy", "PDF XMP metadata names a %s (%s)", PERSON, "export the PDF again without that metadata, or print a new one with `adopt.py proof --print`"),
    # domain
    Row("domain", "cutover is true but the build has no CNAME file", PLUGIN, "the build writes the CNAME when domain and cutover are set; `adopt.py report` files it"),
    Row("domain", "a CNAME is published before cutover; the site would not be served from its preview address", PLUGIN, "`adopt.py report` files it"),
    Row("domain", "CNAME does not hold the domain %s", PLUGIN, "`adopt.py report` files it"),
    Row("domain", "absolute URL to %s (%s)", SITE, "make the address relative, or point it at the site's own address"),
    Row("domain", "canonical is %s, expected %s", SITE, "correct the page's canonical link, or remove a hand-written one"),
    Row("domain", "og:url is %s, expected %s", SITE, "correct the page's og:url, or remove a hand-written one"),
    Row("domain", "<loc> %s is outside %s", PLUGIN, "the sitemap lists an address outside the site; `adopt.py report` files it"),
    Row("domain", "<loc> %s is not a page in this build", PLUGIN, "the sitemap lists a page the build does not make; `adopt.py report` files it"),
    Row("domain", "page is missing from sitemap.xml", PLUGIN, "the sitemap leaves a built page out; `adopt.py report` files it"),
    Row("domain", "Sitemap line %s is outside %s", PLUGIN, "robots.txt names a sitemap outside the site; `adopt.py report` files it"),
    # media
    Row("media", "this image format is not shown by browsers; convert it at import", SITE, "convert the picture to JPEG, PNG, WebP or AVIF and import it again"),
    Row("media", "the image header cannot be read", SITE, "the file is not a readable picture: replace it"),
    Row("media", "long edge %d px is over the %d px cap", SITE, "import the picture again (the importer makes a smaller one), or resize it"),
    Row("media", "an <img> with no src", SITE, "give the image a src, or remove it"),
    Row("media", "<img src=%s> has no alt attribute (use alt=\"\" if decorative)", SITE, "write what the picture shows as its alt text, or alt=\"\" for decoration (only the person can say)"),
    Row("media", "alt text %r is a file name", SITE, "write what the picture shows instead of its file name"),
    Row("media", "<img src=%s>: the image header cannot be read", SITE, "replace the picture file: the page names one that is not a readable picture"),
    Row("media", "<img src=%s> has no %s attribute (layout shift)", ADOPT, "settled by the images.sizes setting (`adopt.py setting images.sizes as-written`, or `held` to add them)"),
    Row("media", "<img src=%s> has an empty or non-numeric %s (%r): write the picture's %s in pixels, or leave the attribute out under images.sizes as-written", ADOPT,
        "settled by the images.sizes setting (`adopt.py setting images.sizes as-written`), or write the number of pixels"),
    Row("media", "<img src=%s> %s=%s but the file is %d", SITE, "write the picture's true width and height, or remove the attribute"),
    Row("media", "<img src=%s> has a srcset but no sizes attribute", ADOPT, "settled by the images.sizes setting (`adopt.py setting images.sizes as-written`)"),
    Row("media", "srcset candidate %s has no width descriptor", SITE, "write the candidate's width, as 480w"),
    Row("media", "srcset says %s is %sw but the file is %d wide", SITE, "correct the width in the srcset, or replace the file"),
    Row("media", "<iframe src=%s> has no title", SITE, "give the iframe a title attribute"),
    Row("media", "<iframe> from %s, which is not a recognised video host", SITE, "use a recognised video host, or a link instead of an embed"),
    Row("media", "a video facade loads %s from another address before any click (<%s %s>); a facade may load only a poster committed under media/", SITE,
        "commit the poster under media/ and name it there"),
    Row("media", "the block stylesheet loads %s from another address; it may load nothing from outside the site", SITE, "copy the file into the site, or remove the rule"),
    # unfinished
    Row("unfinished", "unfinished marker %r in the page text", SITE, "finish the sentence, or remove the marker"),
    Row("unfinished", "noindex page that is not a redirect stub (a draft left in?)", SITE, "publish it (remove noindex), or make it a draft so it is not built"),
    Row("unfinished", "untitled page", SITE, "give the page a title (content is the person's: the plugin never writes it)"),
    Row("unfinished", "the page has no content", SITE, "add the page's text, or remove the page"),
    Row("unfinished", "a link that goes nowhere (href=%r)", SITE, "give the link a real address, or remove it"),
    Row("unfinished", "development address %r left in", SITE, "replace it with the site's own address"),
    # performance
    Row("performance", "%d KB is over the %s KB budget and the image has no size copies (<stem>-<width>w.<ext>); import it again", SITE,
        "import the picture again so it gets size copies, or raise budgets.sizeCopyOverKB in site.json"),
    Row("performance", "first-view images weigh %.2f MB at 2x, over the %s MB budget", SITE, "use lighter pictures where the page first opens, or raise budgets.firstViewMaxMB in site.json"),
    Row("performance", "images on the page weigh %.2f MB at 2x, over the %s MB budget", SITE, "use lighter pictures, or raise budgets.pageImagesMaxMB in site.json"),
    Row("performance", "lazy images on the page weigh %.2f MB at 2x, over the %s MB budget", SITE, "use lighter pictures, or raise budgets.lazyImagesMaxMB in site.json"),
    # head
    Row("head", "no <meta charset=\"utf-8\">", SITE, _HAND + ": add <meta charset=\"utf-8\"> to its head"),
    Row("head", "no <meta name=\"viewport\" content=\"width=device-width, ...\">", SITE, _HAND + ": add the viewport meta to its head"),
    Row("head", "empty <title>", SITE, "give the page a title"),
    Row("head", "no meta description", SITE, "give the page a description (front matter `description`, or a <meta name=\"description\">)"),
    Row("head", "no canonical link", SITE, _HAND + ": add <link rel=\"canonical\"> to its head"),
    Row("head", "no %s meta", SITE, _HAND + ": add the share meta tag named"),
    Row("head", "the title %r is also used by %s", SITE, "give the pages different titles (a search result shows them)"),
    # nav
    Row("nav", "the home page has no primary navigation", SITE, "add a <nav> with the site's main links to the home page"),
    Row("nav", "primary nav differs from the home page's (missing %s; extra %s)", SITE, "make the page's navigation match the home page's"),
    Row("nav", "the page does not link to the home page", SITE, "link the page to the home page (a logo or a nav link)"),
    Row("nav", "the page has no <nav>", SITE, "add the site's navigation to the page"),
    # basepath
    Row("basepath", "a <base> tag changes how every relative link resolves", SITE, "remove the <base> tag"),
    Row("basepath", "carried %s %s lies outside the site's path %s: a carried page is never rewritten, so correct the address in site/carried/%s, or remove %s from carried", SITE,
        "correct the address in the carried page, or remove it from `carried`"),
    Row("basepath", "carried %s %s names the site's path, and site.json gives no address to read it against: set previewUrl, or domain with cutover", SITE,
        "set previewUrl in site.json, or domain with cutover"),
    Row("basepath", "root-absolute %s %s breaks under the /<repo>/ preview path", SITE, "write the address relative to the page"),
    Row("basepath", "development origin %s", SITE, "replace it with the site's own address"),
    Row("basepath", "absolute URL %s is on this site's host but outside %s", SITE, "write the address relative to the page"),
    Row("basepath", "file: URL %s", SITE, "replace it with a published address"),
    Row("basepath", "script uses the root-absolute path %s", SITE, "write the script's address relative to the page"),
    # size
    Row("size", "the published tree is %.1f MB, over the %s MB budget (Pages allows 1 GB)", SITE, "remove or shrink the largest files, or raise budgets.treeMaxMB in site.json"),
    Row("size", "file is %.0f MB; GitHub warns at 50 MB and refuses 100 MB", SITE, "shrink or remove the file: GitHub refuses one over 100 MB"),
    # the checks adopt adds to the gate's families (publishchecks, dev 1068 design 1.2)
    Row("build", "%s", SITE, "settle what the build says (the line names the file and its fix)"),
    Row("proof", "the resume PDF %s has no proof beside it (%s)", PERSON, "make the proof: `adopt.py proof` (the plugin's reader checks the PDF against the resume page; `--as-is` if you vouch for it)"),
    Row("markup", "the MARKUP-ONLY record no longer holds: %s", ADOPT, "run `adopt.py parity`: it measures the converted tree again"),
    Row("private", "%s is on the private list and would be published", SITE, "rename or remove it: a private name must never reach the public repo"),
    Row("case", "%s and %s differ only in case (a Mac's disk keeps one of them)", SITE, "rename one of the two so the names differ by more than case"),
    Row("online", "%s", PERSON, "none of these is the plugin's to fix: the line names the repo, the setting or the address and what to do"),
    Row("staging", "%s", PERSON, "an ignore rule or filter in your git configuration changes what the public repo would hold: remove it, or publish from a computer without it"),
)

FREE_TEXT = ("build", "staging", "online")       # families whose one row is `%s`: the form printed is the message itself
_FORM = re.compile(r"%[-+ #0]*\d*(?:\.\d+)?[sdrfixXeEgGc]")


def literal_of(template):
    """The fixed text of a template (every `%`-form removed): how specific a row is."""
    return "".join(_FORM.split(template))


def compile_template(template):
    """The regular expression a template's messages match: each `%`-form is `.*`."""
    return re.compile("^" + ".*".join(re.escape(p) for p in _FORM.split(template)) + "$", re.S)


def form_text(template):
    """A template as a person reads it: each `%`-form as an ellipsis."""
    return _FORM.sub("...", template)


def render(template):
    """A message of this template with every `%`-form filled by `x`."""
    return _FORM.sub("x", template)


_CACHE = {}


def _compiled():
    """The rows' regular expressions, the most specific first (compiled on first use: a module does no work when it is imported)."""
    if "rows" not in _CACHE:
        _CACHE["rows"] = sorted(((compile_template(r.template), literal_of(r.template), n) for n, r in enumerate(ROWS)),
                                key=lambda t: (-len(t[1]), t[2]))
    return _CACHE["rows"]


def row_index(family, message):
    """The index in ROWS of the row this finding is, or None. Rows of the finding's family only; the most specific row first (the longest fixed
    text), so a general form never takes a specific one's message."""
    for rx, _lit, n in _compiled():
        if ROWS[n].family == family and rx.match(message):
            return n
    return None


def classify(family, message, fix=None):
    """{"who", "fix", "form", "row"} for one finding. A message no row matches is `plugin`, with its own text as the form (never dropped,
    never read from the site for `who`). A finding that carries its own fix (a build refusal) keeps it."""
    n = row_index(family, message)
    if n is None:
        return {"who": PLUGIN, "fix": "a finding this plugin has no row for: `adopt.py report` files it", "form": message, "row": None}
    row = ROWS[n]
    return {"who": row.who, "fix": fix or row.fix, "form": form_text(row.template) if row.family not in FREE_TEXT else message, "row": n}


# --- what apply can still refuse --------------------------------------------------------------------------------------------------------

STOP_CATEGORIES = {
    "ask": "your answer at the publish ask: it is yours, and it is for the exact digest",
    "review": "no privacy review covers this build: the review is bound to the digest, which holds the conversion commit's date, so it exists "
              "only once `apply` commits; `check` says in advance whether one will be needed, and a review carries to a later `apply` only on the "
              "same UTC day",
    "moved": "something outside this run: a workflow started on the dev repo, main moved, the public repo moved or changed settings, or the "
             "network or `gh` stopped answering; any of them can change between the question and the publish",
    "pages": "Pages does not build the site, or builds it late: GitHub answers only after the push",
    "refused": "the push to the dev repo's main is refused (a token without the workflow scope, protection): GitHub answers only the push",
    "hooks": "a commit hook or signing setting of yours makes git refuse the publish commit: running them is the act itself",
    "changed": "a file or a choice changed after the last `parity`: `apply` refuses before writing",
    "notchecked": "what was not checked, listed as such: a check that could not run is never a pass",
    "elsewhere": "a command `apply` never runs (`deploy.py drop`, the preflight's own input)",
    "named": "`adopt.py check` says it first: it asks the same function read-only (`adoption.applyrefusals`), or reads the same plan or basis first (dev 1068, review R1)",
    "later": "a step after the publish (the old builder's archive and the push of the branch) asks about the tree and the repo as they stand then, so only that step can say",
}

# `file::function` -> (raises it holds, categories, the §1.2 checks that say it first, or ()).
STOPS = {
    "adopt_head.py::require_head_ahead_of_origin_main": (4, ("moved",), ()),
    # apply's own refusals (dev 1068, review R1, item 2): a `named` row is asked by `check` first, any other category cannot be known earlier
    "adoption/accounting.py::parse_archive": (6, ("named",), ("apply",)),
    "adoption/apply.py::_checked_plan": (4, ("named",), ("plan", "stale")),
    "adoption/apply.py::_refuse_stray_rules": (3, ("named",), ("apply",)),
    "adoption/apply.py::archive_file": (1, ("named",), ("apply",)),
    "adoption/apply.py::check_branch_free": (1, ("named",), ("apply",)),
    "adoption/apply.py::refuse_no_identity": (1, ("named",), ("apply",)),
    "adoption/apply.py::refuse_path": (1, ("named",), ("apply",)),
    "adoption/apply.py::refuse_placeholder": (1, ("named",), ("apply",)),
    "adoption/apply.py::reports_at": (1, ("named",), ("apply",)),
    "adoption/apply.py::stage": (2, ("named",), ("apply",)),
    "adoption/base.py::git": (1, ("moved",), ()),
    "adoption/carry.py::carried_bytes": (2, ("named",), ("apply",)),
    "adoption/convert.py::converted_site_files": (1, ("named",), ("apply", "problems")),
    "adoption/convert.py::layout_changes": (4, ("named",), ("apply", "problems")),
    "adoption/dispose.py::apply_dispositions": (1, ("named",), ("apply",)),
    "adoption/finish.py::_record_run": (1, ("named",), ("apply",)),
    "adoption/parity.py::_record_look": (2, ("named",), ("plan",)),
    "adoption/parity.py::example_site_json": (5, ("named",), ("basis",)),
    "adoption/parity.py::parity_basis": (1, ("named",), ("basis",)),
    "adoption/parity.py::parse_parity_record": (12, ("named",), ("plan",)),
    "adoption/parity.py::preconditions": (5, ("named",), ("basis",)),
    "adoption/plan.py::_parity_v3": (6, ("named",), ("plan",)),
    "adoption/plan.py::_person_row": (2, ("named",), ("plan",)),
    "adoption/plan.py::parse_plan": (31, ("named",), ("plan",)),
    "adoption/state.py::digest_after_move": (1, ("later",), ()),
    "adoption/state.py::output_digest": (1, ("later",), ()),
    "adoption/state.py::retire_engine": (8, ("later", "moved"), ()),
    "adoption/wouldwrite.py::collect_removals": (8, ("named",), ("apply", "decide")),
    "adoption/wouldwrite.py::decided_conversions": (1, ("named",), ("apply", "problems")),
    "adoption/wouldwrite.py::hook_plan": (2, ("named",), ("apply", "decide")),
    "adoption/wouldwrite.py::refuse_undecided": (2, ("named",), ("decide",)),
    "adoption/finish.py::run": (2, ("refused",), ()),
    "adoption/publish.py::_confirm": (6, ("ask", "pages", "moved"), ("build", "gate", "address", "staging")),
    "adoption/publish.py::check_no_run_in_progress": (2, ("moved",), ()),
    "adoption/publish.py::covered": (4, ("review",), ()),
    "adoption/publish.py::pages_built": (4, ("pages",), ()),
    "adoption/publish.py::publish": (4, ("review", "moved"), ("build", "gate", "address", "staging", "public-target")),
    "deploying/addressguard.py::check_pages_source": (2, ("moved", "notchecked"), ("pages-source",)),
    "deploying/addressguard.py::committed_record": (1, ("moved",), ("address",)),
    "deploying/addressguard.py::guard_addresses": (1, ("moved",), ("address",)),
    "deploying/addressguard.py::read_pages": (5, ("notchecked", "moved"), ("pages-source",)),
    "deploying/adoptgate.py::check_adopt_record": (2, ("changed",), ()),
    "deploying/adoptgate.py::recheck_markup_only": (2, ("changed",), ("markup",)),
    "deploying/confirm.py::run_confirm": (4, ("ask", "changed"), ()),
    "deploying/drop.py::run_drop": (4, ("elsewhere",), ()),
    "deploying/gates.py::run_gates": (2, ("changed",), ("gate",)),
    "deploying/gitrun.py::_git": (3, ("moved", "hooks"), ()),
    "deploying/headcheck.py::refuse_if_remote": (1, ("moved",), ()),
    "deploying/headcheck.py::require_head_on_origin_main": (3, ("moved", "changed"), ()),
    "deploying/materialize.py::materialize": (2, ("moved",), ("staging",)),
    "deploying/preflight.py::_run_preflight": (2, ("elsewhere",), ()),
    "deploying/prepare.py::prepare": (2, ("changed",), ("build",)),
    "deploying/pushing.py::push_and_verify": (4, ("moved", "refused"), ()),
    "deploying/pushing.py::push_main": (1, ("refused",), ()),
    "deploying/staging.py::stage_and_verify": (2, ("changed",), ("staging", "private")),
    "deploying/target.py::check_not_dev_repo": (2, ("moved",), ("public-target",)),
    "deploying/target.py::check_public_repo": (8, ("moved", "notchecked"), ("public-target",)),
    "deploying/target.py::check_push_url": (2, ("moved",), ("public-target",)),
    "deploying/target.py::check_remote_main": (2, ("moved",), ()),
    "deploying/target.py::public_target": (1, ("changed",), ("public-target",)),
    "reviews/basics.py::git": (3, ("review", "hooks"), ()),
    "reviews/dryrun.py::check_dryrun": (1, ("review",), ()),
    "reviews/store.py::_validate_row": (1, ("review",), ()),
    "reviews/store.py::load_rows": (2, ("review",), ()),
}
EXCEPTIONS = frozenset(("DeployError", "ReviewError"))        # what `deploy.py`'s `except` clauses may name


def stop_lines():
    """The lines `check --online` prints under "can still stop apply": each category once, with why it cannot be known earlier."""
    used = []
    for _key, (_n, cats, _first) in sorted(STOPS.items()):
        for c in cats:
            if c not in used:
                used.append(c)
    return ["  - %s" % STOP_CATEGORIES[c] for c in STOP_CATEGORIES if c in used and c not in ("elsewhere", "named")]
