"""adoption.spec -- the capability spec (`spec/capabilities.json`) and the table of conversion classes.

Part of the `adoption` package behind the entry point `adopt.py`.
"""

import json
import os
import re

from adoption.base import PLUGIN

SPEC_PATH = os.path.join(PLUGIN, "spec", "capabilities.json")
# The classes of conversion `converted_site_files` makes (design-site-fidelity section 5.0.1). GENERAL follows
# from site-studio's own model, whatever the site came from; TEMPLATE follows from the conventions of the
# template site-studio replaces and is offered as mechanical only when `template_fingerprint` holds. P1 runs
# each class alone, so a class is named here, once.
CONVERSION_CLASSES = (
    ("normalise", "GENERAL", "site.json values: a clone URL as owner/name, a previewUrl without its slash"),
    ("redirectKeys", "GENERAL", "site.json redirect keys and targets without their trailing slash (the same URLs are served)"),
    ("labels", "GENERAL", "[key, label] pairs in site.json as a labels map"),
    ("redirects", "GENERAL", "meta-refresh pages as site.json redirects"),
    ("redirectBoiler", "GENERAL", "meta-refresh pages with head boilerplate as site.json redirects (drops the boilerplate)"),
    ("layout", "GENERAL", "content folders with no page.md, moved to _<name> or given a page.md"),
    ("tokens", "GENERAL", "the template's local tokens as the build's own tokens"),
    ("viewKeys", "GENERAL", "a portfolio's `view` the plugin does not model (such as roles) removed, so its index is the plugin's grid"),
    ("navTokens", "GENERAL", "the nav token inside the person's own <nav> wrapper as the links-only token {{navLinks}}"),
    ("personName", "GENERAL", "site.json `name`, when it is a domain or repository name, as the name on the resume"),
    ("resumePdfName", "GENERAL", "the resume PDF renamed to the name the old builder published it under"),
    ("archive", "GENERAL", "files nothing builds or reads, moved under archive/ (design 8 FA)"),
    ("draft", "GENERAL", "a piece the old builder did not publish, marked draft: true"),
    ("pieces", "TEMPLATE", "piece files named work.md renamed index.md"),
    ("pageFiles", "TEMPLATE", "home.md and about.md renamed index.md in their folders"),
    ("pieceKeys", "TEMPLATE", "piece front-matter keys the template names differently (tilePhoto, summary) as the build's own (cover, teaser)"),
    ("blocks", "TEMPLATE", "the template's tile:, quote, video: and image lines as the plugin's block containers"),
    ("references", "TEMPLATE", "a reference's template keys (myRole, captured_from) as the plugin's (role, fetched)"),
    ("homeKeys", "TEMPLATE", "the home page's template keys (headline, intro, stats, quote, linkedin ...) as the plugin's"),
    ("resumeHeader", "TEMPLATE", "the resume's name, headline and linkedin as title, tagline and links"),
    ("resumeFields", "TEMPLATE", "other resume front-matter fields as body paragraphs"),
)
# A conversion that is `you decide` BY ITS NATURE (design-site-fidelity sections 5.5 and 5.6): it changes what a
# visitor reads, so it is never `apply fixes this`, whatever parity says. `adopt.py convert <class>` is the
# one-command default the person may choose; without it apply leaves the page as written. Parity builds the tree
# apply WILL make (`check_only`), so a chosen class is measured and the difference is named in its row. `viewKeys`
# (a portfolio `view` the plugin does not model, such as the template's roles index) is one: the build refuses the
# key, the site stays on the person's builder, and choosing it measures what the plugin's grid would change.
OPT_IN_CLASSES = ("redirectBoiler", "resumeFields", "viewKeys")
# The head elements a meta-refresh page may carry and still be a redirect (design-site-fidelity section 5.6): the
# plugin's own redirect page drops them, so converting is `you decide`.
HEAD_BOILERPLATE_LINKS = ("icon", "shortcut icon", "apple-touch-icon", "mask-icon", "manifest", "stylesheet")
HEAD_BOILERPLATE_METAS = ("theme-color", "color-scheme")


class Spec(object):
    def __init__(self, data):
        self.data = data
        th = data["thresholds"]
        self.match = th["match"]
        self.gap = th["ambiguousGap"]
        self.residual_max = th["residualMax"]
        self.caps = data["capabilities"]
        self._rx = {}

    def rx(self, pattern):
        r = self._rx.get(pattern)
        if r is None:
            r = self._rx[pattern] = re.compile(pattern, re.I | re.M)
        return r


def load_spec(path=None):
    with open(path or SPEC_PATH, "r", encoding="utf-8") as fh:
        return Spec(json.load(fh))


def _sig_found(spec, sig, text, base):
    target = base if sig.get("name") else text
    for p in sig["any"]:
        if spec.rx(p).search(target):
            return True
    return False


def _applicable(cap, kind, base):
    if kind not in cap["kinds"]:
        return False
    files = cap.get("files")
    if files and not any(re.search(f, base, re.I) for f in files):
        return False
    return True


def score_capability(spec, cap, text, base):
    total = sum(s["weight"] for s in cap["signals"])
    got = 0
    found = []
    for s in cap["signals"]:
        if _sig_found(spec, s, text, base):
            got += s["weight"]
            found.append(s["id"])
    return (got / float(total) if total else 0.0), found
