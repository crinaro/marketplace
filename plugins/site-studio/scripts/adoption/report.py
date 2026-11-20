"""adoption.report -- what `check` and `inventory` print.

Part of the `adoption` package behind the entry point `adopt.py`. Documentation that was in `adopt.py`'s docstring about this module's code:

REPORTS THAT TELL THE WHOLE TRUTH (0.3.1; dev #879, #893, #887, #890). None of this changes what adopt converts or what
parity measures; it changes what is SAID, and what is kept.
- PARITY NAMES CAUSES (#879). Every hunk of every differing file is read (`file_hunks`), and the hunks are grouped
  across files by their own text (`difference_report`): one change repeated on 27 pages is one line with its page count,
  and a file past HUNKS_PER_FILE hunks says how many it did not list. A hunk that is only an ADDITION inside `<head>` is
  its own class, listed after the body causes and never in place of one. `parity --keep DIR` leaves the two builds in
  DIR/local and DIR/plugin (refused when DIR exists and is not empty); `remeasure --accept` prints the causes it accepts
  BEFORE it writes the record that says ACCEPTED. `parity --accept` accepts only the differences a previous `parity`
  on the SAME basis already stored as DIFFERENT (`differences_were_shown`): it prints them before the plan that says
  ACCEPTED is saved; otherwise it lists them, records DIFFERENT and says to run `parity --accept` again. The plan's `differences` keep their three strings: the report is
  transient, never stored.
- CHECK SAYS EVERY REFUSAL, ONCE PER CAUSE (#893). `every_refusal` re-reads each file the build refused at its FIRST
  unknown key or token and lists all of them, with lines. `format_problems` groups problems that share a cause and marks
  a redirect or `{{link:X}}` to a refused portfolio as following from that portfolio's own problem, so the count of
  `you decide` is the count of causes. A fix adopt makes is never grouped.
- DECISIONS SURVIVE A MOVING BASIS (#887). `check` no longer lists a folder the person decided; a plan made for another
  basis is CARRIED (`carry_plan`): a decision about a path that exists and did not change is kept, the rest are cleared
  and printed by name. The plan's keys are unchanged.
- A BUILDER THAT FAILS IS NOT A BUILDER THAT DIFFERS (#890). When P1 shows the kept builder exits non-zero on the converted
  tree, P1 says FAILS, each conversion that does it is named with the builder's own failure line, and `apply` (and
  `apply --dry-run`) refuse a chosen conversion that does it while parity is not EQUAL or ACCEPTED.

PARITY_IGNORED lists what the plugin adds and the examples never wrote. It follows the design's
list plus ONE addition: the `decoding` attribute on `<img>`, because build.py writes
`decoding="async"` on every image and the design's list names only srcset, sizes, width, height
and loading (a finding; without it no repo with an image could pass).
"""

import json
import re

from adoption.base import Refused
from adoption.spec import load_spec
from adoption.classify import _fmt_pct, namesake_text, shadow_note
from adoption.tree import TreeFiles, counterpart_of, inventory
from adoption.tokens import (
    detect_resume, home_feed, link_step_reason, link_token_folder,
    portfolio_folders, rewrite_tokens, section_for_link, section_for_resume,
    site_json_labels, token_files,
)
from adoption.redirects import redirect_pages
from adoption.convert import converted_site_files, holds_markdown, pageless_folders
from adoption.fileacct import measured_folders
from adoption.keycover import note_lines
from adoption.features import FEATURES, detect_signals, feature_lines, infer_kind
from adoption.parity import conversion_lines, decide_conversions, preconditions, template_fingerprint
from adoption.problems import plan_settings, format_problems, held_problems, problem_dicts, site_problems, size_copy_note
from adoption.plan import _plan_for, save_plan

def cmd_inventory(repo, as_json):
    basis, tree, data = preconditions(repo)
    base = basis.sha
    spec = load_spec()
    infos = inventory(tree, spec)
    resume = detect_resume(tree)
    cleared_msgs = []
    plan = _plan_for(repo, base, cleared_msgs.append)
    for i in infos:
        plan["files"].setdefault(i["path"], {"removal": None, "reviewed": False, "units": {}})
    for stale in [p for p in plan["files"] if p not in set(i["path"] for i in infos)]:
        del plan["files"][stale]
    save_plan(repo, plan)
    folders = portfolio_folders(tree)
    unknown, sections = [], []
    for p in token_files(tree):
        _t, ch, u = rewrite_tokens(tree.text(p), folders, layout=(p == "site/templates/layout.html"), home=home_feed(tree),
                                   labels=site_json_labels(data))
        unknown += [(p, t) for t in u]
        sections += [(p, a, b) for a, b in ch if "{{#page:" in b]
    kind = plan.get("siteKind")
    notes = []                       # design-movement-view 6.1: a key read elsewhere is a note, not a decision
    probs = site_problems(tree, data, plan["paper"], kind, measured_folders(tree, plan), plan["convert"], plan_settings(plan),
                          plan.get("parity"), notes) + held_problems(tree, data, plan)
    redirects = redirect_pages(tree, data.get("redirects"))
    signals = detect_signals(tree, data, redirects)
    known = set(f.key for f in FEATURES)
    inferred, inferred_why = infer_kind(tree)
    if as_json:
        return json.dumps({"base": base,
                           "basis": {"sha": base, "kind": basis.kind, "branch": basis.branch,
                                     "origin": basis.origin, "reason": basis.reason,
                                     "ahead": [{"sha": s, "subject": subj} for s, subj in basis.ahead]},
                           "files": infos, "resume": resume, "unknownTokens": unknown,
                           "problems": problem_dicts(probs), "cleared": cleared_msgs,
                           "redirects": {"convert": [{"path": r.path, "key": r.key, "target": r.target,
                                                      "dropped": r.dropped, "boiler": list(r.boiler)}
                                                     for r in redirects[0]],
                                         "left": [{"path": p, "reason": why} for p, why in redirects[1]]},
                           "features": [{"key": k, "where": w, "known": k in known,
                                         "line": feature_lines([(k, w)])[0].strip("- ").strip()}
                                        for k, w in signals],
                           "inferredKind": {"kind": inferred, "why": inferred_why}, "siteKind": kind,
                           "sections": [{"path": p, "found": a, "section": b} for p, a, b in sections]},
                          indent=2, default=list)
    L = ["adopt inventory (%s %s)" % (basis.label(), base[:7])] + basis.up_front() + cleared_msgs + [
         "",
         "%-10s %-38s %-34s %5s %8s  %s" % ("class", "file", "plugin counterpart", "score", "residual", "evidence")]
    for i in infos:
        L.append("%-10s %-38s %-34s %5s %8s  %s" % (
            i["class"], i["path"], counterpart_of(spec, i["capability"])[:34] if i["class"] != "CUSTOM" else "none",
            _fmt_pct(i["score"]) if i["class"] != "MIXED" else "-",
            _fmt_pct(i["residual"]) if i["class"] in ("DUPLICATE", "PARTIAL") else "-",
            (", ".join(i["signals"]) if i["signals"] else (
                "best: " + ", ".join("%s %s" % b for b in i["best"]) if i["class"] == "CUSTOM" and i["best"] else
                ("candidates: " + ", ".join("%s %s" % c for c in i["candidates"]) if i["candidates"] else "")))
            + ("; " + namesake_text(i) if i.get("namesake") else "")))
    for i in infos:
        if i["residual_units"]:
            L.append("")
            L.append("Residual units in %s (person data to move, a standing rule to carry, or behaviour to keep):"
                     % i["path"])
            for u in i["residual_units"]:
                L.append("  %s: %s" % (u["id"], u["text"].split("\n")[0][:90]))
    for i in infos:
        if i.get("shadows"):
            L.append("")
            L.append("SHADOW: %s %s. While it is kept, %s"
                     % (i["path"], namesake_text(i) or "has the name of site-studio's %s agent" % i["shadows"],
                        shadow_note(i["shadows"])))
    L.append("")
    if resume["md"]:
        L.append("resume: %s%s; paper: %s" % (resume["md"], (" + " + resume["pdf"]) if resume["pdf"] else "",
                 ("%s (read from %s)" % (resume["paper"], resume["source"])) if resume["paper"] else
                 ("NEEDS YOUR ANSWER (no readable paper size in the PDF); run `adopt.py paper Letter` or "
                  "`adopt.py paper A4`") if resume["needsAnswer"] else
                 "none asked: there is no resume PDF, so site.json gets \"pdf\": null and no paper size"))
    else:
        L.append("resume: none found; site.json gets resume: null")
    if unknown:
        L.append("tokens the plugin's build will refuse: " + ", ".join("%s in %s" % (t, p) for p, t in unknown))
    for p, t in unknown:
        if re.sub(r"\s", "", t) == "{{resumeLink}}":
            L.append("step for you: %s holds %s somewhere other than as an anchor's whole href. The plugin "
                     "has no such token: wrap the link in %s, and point it at {{link:resume}}, by hand."
                     % (p, t, section_for_resume("<a href=\"{{link:resume}}\">...</a>")))
            continue
        folder = link_token_folder(t, folders)
        if folder:
            # dev #889: a `{{<folder>Link}}` that is not an anchor's whole href is a STEP, never reported as converted
            L.append("step for you: %s holds %s somewhere other than as an anchor's whole href, and adopt did not "
                     "rewrite it: your builder rendered a whole anchor there, and %s. The plugin has no such token: "
                     "write %s by hand, with your own label."
                     % (p, t, link_step_reason(t, folder, data), section_for_link(folder, "LABEL")))
    if sections:
        L.append("page sections adopt will write (a link that is there when the resume is built, gone when "
                 "it is not):")
        for p, a, b in sections:
            L.append("  %s: %s -> %s" % (p, " ".join(a.split()), " ".join(b.split())))
    if probs or notes:
        L.append("")
        L += format_problems(probs) + note_lines(notes)
        L.append("")
    L += _pageless_lines(tree, plan)
    sch = site_json_schema_line(tree, data, plan["paper"], plan["folders"], kind)
    if sch:
        L.append(sch)
    if size_copy_note(tree):
        L.append(size_copy_note(tree))
    block = _conversion_block(tree, data, plan)
    if block:
        L += [""] + block
    plain = [r for r in redirects[0] if not r.boiler]
    boiler = [r for r in redirects[0] if r.boiler]
    if plain:
        L.append("meta-refresh pages adopt will turn into site.json redirects (the build writes an equivalent "
                 "page at the same address):")
        L += ["  %s -> redirects '%s': %s" % (r.path, r.key, json.dumps(r.target)) for r in plain]
    if boiler:
        L.append("redirect pages with head boilerplate (a redirect, with more in its head; converting one is `you "
                 "decide`, because the build's redirect page drops that, and the default keeps the page as "
                 "written):")
        L += ["  %s -> redirects '%s': %s; converting drops %s" % (r.path, r.key, json.dumps(r.target),
                                                                     ", ".join(r.boiler)) for r in boiler]
    if redirects[1]:
        L.append("meta-refresh pages that stay hand pages (adopt will not turn them into redirects):")
        L += ["  %s: %s" % t for t in redirects[1]]
    if signals:
        L.append("")
        L.append("what this site does, and what site-studio does about it:")
        L += feature_lines(signals)
    L.append("")
    L.append("this looks like a %s site (%s); %s" % (
        inferred, inferred_why,
        ("you confirmed %s" % kind) if kind else
        "confirm it with `adopt.py kind %s`, or choose portfolio, hub or custom; apply writes only a kind you "
        "confirmed" % inferred))
    counts = {}
    for i in infos:
        counts[i["class"]] = counts.get(i["class"], 0) + 1
    L.append("summary: " + ", ".join("%s %d" % kv for kv in sorted(counts.items())))
    return "\n".join(L)


def _pageless_lines(tree, plan):
    """What apply does with each folder under content/ that has no page.md, and how to choose the other way."""
    L = []
    folders = measured_folders(tree, plan)
    for name in pageless_folders(TreeFiles(tree)):
        choice = folders.get(name)
        if choice is None and holds_markdown(tree, "content/%s/" % name):
            L.append("content/%s/ has no page.md and holds Markdown: apply leaves it where it is until you decide "
                     "(you decide). `adopt.py folder %s source` renames it to content/_%s (source material, not "
                     "built); `adopt.py folder %s portfolio` gives it a page.md." % (name, name, name, name))
            continue
        choice = choice or "source"
        L.append("content/%s/ has no page.md: apply will %s. %s" % (
            name,
            "add a page.md, so it becomes a portfolio" if choice == "portfolio" else
            "rename it to content/_%s (kept as source material, not built)" % name,
            "To rename it instead: `adopt.py folder %s source`." % name if choice == "portfolio" else
            "To make it a portfolio instead: `adopt.py folder %s portfolio`." % name))
    return L


ACCEPT_PAGES_MAX = 40          # pages named one by one; the rest are counted (the plan keeps them all)
ACCEPT_TEXT_MAX = 140          # characters of one description shown


def _address(path):
    """The address a visitor types for the output page `path`: `work/a/index.html` is `/work/a/`."""
    folder = re.sub(r"(?:^|/)index\.html?$", "", path).strip("/")
    return "/%s/" % folder if folder else "/"


def _shown(text):
    if text is None:
        return "none (a search engine picks a line of the page)"
    text = " ".join(text.split())
    return '"%s"' % (text if len(text) <= ACCEPT_TEXT_MAX else text[:ACCEPT_TEXT_MAX - 1].rstrip() + "...")


def accept_lines(parity):
    """The lines `parity` and `check` print for the pages whose search-result description will read differently. `parity` is a parity
    result (`run_parity`'s, or the plan's `parity`): its `accepts` is `[(page, old text, new text)]` (`parity_classes.description_changes`).
    It is a difference a person MEETS before the page (a search result shows it), so it is named once, page by page, as something to
    ACCEPT, with the old and the new words, and never left to the grouped causes above. Nothing is printed for a measure that found
    none, and a verdict that is not DIFFERENT has nothing to accept."""
    changes = [tuple(c) for c in (parity or {}).get("accepts") or ()]
    if not changes or parity.get("verdict") != "DIFFERENT":
        return []
    only = sum((parity.get("kinds") or {}).values()) == len(changes)        # one hunk a page, and no other visible hunk
    out = ["to accept: the description a search result shows will read differently on %d page%s. A search engine shows it under the "
           "page's title; no visitor sees it on the page. site-studio writes each page's description from its own content, where "
           "your old site wrote another text%s. Each page, with the old and the new words:"
           % (len(changes), "" if len(changes) == 1 else "s", " (this is the only difference)" if only else "")]
    for page, old, new in changes[:ACCEPT_PAGES_MAX]:
        out.append("  %s  was: %s  now: %s" % (_address(page), _shown(old), _shown(new)))
    if len(changes) > ACCEPT_PAGES_MAX:
        out.append("  ... and %d more page(s) not listed" % (len(changes) - ACCEPT_PAGES_MAX))
    out.append("  `adopt.py parity --accept` accepts these along with any other difference listed above; you can edit a page's "
               "description afterwards in its `description:` front matter.")
    return out


def _conversion_block(tree, data, plan):
    """The `conversions` lines of `check`: each conversion, its label and what parity says about it (empty
    when adopt would make none), then the pages whose search-result description will read differently, named as an ACCEPT
    (`accept_lines`, from the last `parity` on this basis; none when parity has not measured or found none)."""
    accepts = accept_lines(plan["parity"])
    try:
        _files, notes = converted_site_files(tree, data, plan["paper"], plan["folders"], plan.get("siteKind"))
    except Refused:
        return accepts
    rows = decide_conversions(notes, plan["parity"], template_fingerprint(tree), plan["convert"])
    head = (["conversions (GENERAL follows from site-studio's own model, TEMPLATE from the template's conventions):"]
            + conversion_lines(rows)) if rows else []
    return head + ([""] if head and accepts else []) + accepts


def site_json_schema_line(tree, data, paper, folders=None, kind=None):
    """The inventory line that says site.json will be written as schema 2 or 3, and why (so a person
    on a second machine with an older site-studio is not surprised); None while schema 1 holds the
    site."""
    try:
        _files, notes = converted_site_files(tree, data, paper, folders, kind)
    except Refused:
        return None
    if notes["schema"] < 2:
        return None
    return ("site.json will be written as schema %d, because %s; a site-studio older than %s will say "
            "it is newer than it understands, and ask to be updated"
            % (notes["schema"], "; ".join("%s %s" % (w, what) for w, what, _e in notes["schemaReasons"]),
               "0.3.0" if notes["schema"] >= 3 else "0.2.0"))
