"""The generated home page's order of parts and what its intro holds (schema 4: `partOrder`, `introScope`).

By default the home body is ONE run (the look's `home.intro`: photo, the whole body, then the endorsement) followed by the
featured pieces, the showcase, the feed, the samples, the links and the contact list, in that order, and a `:::part` block
prints where it stands inside the run. A site whose old pages put those parts somewhere else says so in `content/home.md`:

- `introScope: first-block` shortens the intro to the body's first block and makes every other block outside the `:::part`
  blocks the part `rest`;
- `partOrder: [..]` names the parts in the order they print, the body's `:::part` blocks among them.

Either key makes each `:::part` block a part of its own. A part the order does not name follows the named ones in the default
order (`siteconfig.HOME_SECTIONS`, the body's own parts after `rest`), so nothing a page holds is dropped by leaving it out;
a part that is NAMED must be one the page holds, and anything else is refused with the fix.
"""

import posixpath

import content as C
from configschema import configkeys
from contentmodel.errors import ContentError

from building import grouping
from building.outcomes import BuildError


def wanted(meta, grammar):
    """True when the home page asks for either schema-4 key with a value that changes anything. A home that says
    `introScope: "body"` and no `partOrder` takes the default path, byte for byte."""
    return grammar >= 4 and ("partOrder" in meta or meta.get("introScope", "body") != "body")


# A part the page must be CONFIGURED for to name it: `rest` needs `introScope: "first-block"`, the five key-fed parts need their
# key. A part that is configured but holds nothing today (a feed list that is empty, a body of one block) is not refused: the
# order says where a part goes, not whether the page has content for it. `featured` is never refused either: which pieces are
# featured is a flag on the pieces (featuredFrom: "flags") as much as a key of this page. A `:::part` of the body always exists.
_KEY_FED = ("showcase", "feed", "samples", "links", "contact")


def _check_configured(name, meta, source):
    """A NAMED part the page is not configured for is refused (see `_KEY_FED`); anything else passes."""
    if name == "rest" and meta.get("introScope", "body") != "first-block":
        raise BuildError("%s: partOrder names 'rest', which this page does not have" % source, path=source,
                         fix='set introScope: "first-block" in content/home.md (rest is what follows the body\'s first block), '
                             "or remove rest from partOrder")
    if name in _KEY_FED and name not in meta:
        raise BuildError("%s: partOrder names '%s', which this page does not have" % (source, name), path=source,
                         fix="add a '%s' key to content/home.md, or remove %s from partOrder" % (name, name))


def arranged_body(b, page, out, extras, pieces, feed_cards):
    """The home page's body (the part between its heading and the page's end) with the parts in the order the page says.
    `b` is the builder, `extras` its page_extras (photo, endorsement, contact), `pieces` the featured pieces and `feed_cards`
    the feed's cards. Each part is made in the order it prints, so a plugin stylesheet is linked where its first part is."""
    meta, source, grammar = page.meta, page.source, max(b.grammar, 3)
    intro_frag, parts = b.home_split(out)
    for name in ("rest", "featured"):
        if name in parts:
            raise BuildError("%s: ':::part %s' is a name of the home page's own parts (%s)" % (source, name, ", ".join(configkeys.HOME_SECTIONS)),
                             path=source, fix="rename the part, such as :::part %s-text, then build again" % name)
    env = b.md_env(source, out, posixpath.dirname(source))
    state = {}

    def render(frag):
        try:
            return C.render_fragment_blocks(frag, env, source, grammar)
        except ContentError as e:
            raise BuildError(str(e), path=getattr(e, "path", None), lineno=getattr(e, "lineno", None),
                             fix=getattr(e, "fix", None) or "fix the problem named above, then try again")

    def intro_and_rest():
        if "split" not in state:
            blocks = render(intro_frag)
            if meta.get("introScope", "body") == "first-block":
                state["split"] = (blocks[0] if blocks else "", "\n".join(blocks[1:]))
            else:
                state["split"] = ("\n".join(blocks), "")
        return state["split"]

    makers = {
        "intro": lambda: b.r("home", "intro", {"photo": extras["photo"], "intro": intro_and_rest()[0],
                                               "endorsement": extras["endorsement"]}),
        "rest": lambda: intro_and_rest()[1],
        "featured": lambda: b.r("home", "featured", {"cards": grouping.featured_html(b, pieces, out)}) if pieces else "",
        "showcase": lambda: b.showcase_html(meta, source, out),
        "feed": lambda: b.feed_html(feed_cards),
        "samples": lambda: b.samples_html(meta.get("samples", []), out),
        "links": lambda: b.links_html(meta.get("links", {}), out, source),
        "contact": lambda: extras["contact"],
    }
    for name, frag in parts.items():
        makers[name] = lambda frag=frag: "\n".join(render(frag))
    named = list(meta.get("partOrder", []))
    for name in named:
        if name not in makers:
            raise BuildError("%s: partOrder names '%s', which is not a part of this page (its parts are %s)"
                             % (source, name, ", ".join(sorted(makers))), path=source,
                             fix="name only parts this page has: the home's own (%s) and the :::part blocks of the body%s"
                                 % (", ".join(configkeys.HOME_SECTIONS), " (here: %s)" % ", ".join(sorted(parts)) if parts else ""))
    default = ["intro", "rest"] + list(parts) + [n for n in configkeys.HOME_SECTIONS if n not in ("intro", "rest")]
    for name in named:
        _check_configured(name, meta, source)
    return "".join(makers[name]() for name in named + [n for n in default if n not in named])
