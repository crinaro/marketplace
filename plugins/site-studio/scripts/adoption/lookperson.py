"""adoption.lookperson -- the person's rows (design-adopt-ownership-line section 4, "The row (L1)"; criterion L1, dev 1009): one row
per look entry of the person's (each construct and `reads` target of `site/looks/local.json`, each named construct, and each
construct of `site/looks/derived.json` that is the person's by rule E), for two callers: `parity`, after the last pass, and
`remeasure`, on HEAD, when the kept builder ran. Both pass `rows`, which builds through `build_without`.

Part of the `adoption` package behind the entry point `adopt.py`.

  1. W is the final build (already built). B is the same tree with every person's entry taken out (`lookwrite.without`), so
     derive's reading or the default renders (one build, recorded).
  2. An entry's pages are those where its construct renders in B (`lookkeep.rendering_on`: what renders where is the content's,
     the markup is the look's). The row compares the visible differences on those pages, W (`yours`) against B (`derived`).
  3. An entry no render call of B shows, and every `reads` entry, is taken out alone (one build each): its pages are those where
     B's render calls show it, plus the pages whose bytes differ between W and that build (dev 1039: a `head.description` entry
     prints through no look part yet changes every piece page). Only when both are empty is it `not reached`. A build without the
     entry that REFUSES (the roles view needs the `employer` the entry reads) reads as "every page it renders on in W" (one more
     build of W, recorded, made once).
  4. Where two entries share a page that is not EQUAL in W, each is taken out alone too. Steps 3 and 4 share ONE cap,
     PERSON_BUILDS_MAX, entries of step 3 first: a run is at most 1 + PERSON_BUILDS_MAX builds, +1 when a build without an entry
     refuses. Past the cap an entry with no page of its own takes the pages W and B differ on, and, like the rest, says "measured
     together with ...".

The person's entry is used whatever the numbers say: the measurement informs, the file decides. A worse entry keeps parity
DIFFERENT, which keeps the person's builder as the publisher. A build the tree with them refuses and without them accepts is a
`refused` row with the build's own message and fix. Nothing here writes a file.

THE RECORD (section 2.8, round 2 M6). `record_look` gives the parity record's `look` (each row's value, exactly section 2.7's) and
`effective`, the sha256 of the effective look and `site.json` as committed: a row is evidence for an entry only while its
`sha256` is the entry's hash and `effective` still matches (`row_valid`), so any later look or config commit voids it.
"""

import hashlib
import json

from adoption import lookwrite
from adoption.lookkeep import rendering_on
from adoption.scoring import Output, not_seen
from building import running
from lookfiles.pagedom import Page, walk
from lookfiles.renderlog import recording
import parity_classes

PERSON_BUILDS_MAX = 8            # section 4: B, then at most this many builds of one entry taken out alone
STATUSES = ("mapped", "ambiguous", "unmapped", "none")
HOWS = ("measured", "not measured")


class Row(object):
    """One entry's row: the plan row `look.<construct>` or `reads.<target>` (section 2.7) and the line parity prints."""

    def __init__(self, entry, pages, yours, derived, status, kind, first="", together=(), message="", fix="", refuses=False):
        self.entry, self.pages, self.yours, self.derived, self.status = entry, pages, yours, derived, status
        self.kind, self.first, self.together, self.message, self.fix = kind, first, list(together), message, fix
        self.refuses = refuses            # the build without this entry is refused: there is no derived number to give

    @property
    def how(self):
        return "not measured" if self.kind in ("you decide", "refused") else "measured"

    def value(self):
        return {"file": self.entry.file, "sha256": self.entry.sha256, "pages": len(self.pages), "yours": self.yours,
                "derived": self.derived, "status": self.status}

    def reason(self):
        e, n = self.entry, len(self.pages)
        what = '"%s"%s' % (e.key.split(":", 1)[-1], " (reads)" if e.key.startswith("reads:") else "")
        if self.kind == "refused":
            return "refused -- %s -- fix: %s" % (self.message, self.fix)
        if self.kind == "not reached":
            return "not reached -- no page renders it"
        theirs = ("the derived reading leaves %d" % self.derived if self.derived is not None else
                  "the build refuses without it" if self.refuses else
                  "derive has no reading of it, and without it the plugin's own markup renders")
        tail = ("; measured together with %s" % ", ".join(self.together)) if self.together else ""
        if self.kind == "you decide":
            back = ('delete %s from %s and commit to hand it back' if e.edited else
                    'remove %s from %s and commit to use the derived reading') % (what, e.file)
            return "you decide -- yours leaves %d (first: %s), the derived reading %d; yours is used; %s%s" % (
                self.yours, self.first, self.derived, back, tail)
        return "measured -- yours leaves %d visible difference(s) on the %d page(s) it renders on; %s%s" % (
            self.yours, n, theirs, tail)

    def plan_row(self):
        return {"value": self.value(), "how": self.how, "reason": self.reason()}

    def line(self):
        e = self.entry
        return "%s (%s%s): %s" % (e.name, e.file, ", edited" if e.edited else "", self.reason())


def build_without(build, files, entries, reading):
    """(output, recorded calls): one build of `files` ({path: bytes}, the converted tree) with `entries` taken out. `build(files)`
    returns the build's output (`scoring.Output`: the pages and the build's problems)."""
    with recording() as calls:
        out = build(lookwrite.without(files, entries, reading))
    return out, list(calls)


def visible(local, out, pages):
    """(how many visible differences, the first as "<page>: <kind>") between the old build and `out` on `pages`."""
    res = parity_classes.classify_differences(dict((p, local[p]) for p in pages if p in local),
                                              dict((p, out[p]) for p in pages if p in out))
    if res["verdict"] in ("EQUAL", "MARKUP-ONLY"):
        return 0, ""
    shown = [d for d in res["visible"] or () if not not_seen(d)]
    if not shown and res["visible"]:
        return 0, ""
    return len(shown) or 1, ("%s: %s" % (shown[0].path, shown[0].kind)) if shown else "a difference"


def _pages_of(entries, out, calls):
    html = dict((p, b.decode("utf-8", "replace")) for p, b in out.items() if p.lower().endswith((".html", ".htm")))
    on = rendering_on(html, calls, set(e.construct for e in entries))
    return dict((e.name, sorted(p for p, cids in on.items() if e.construct in cids)) for e in entries)


def _changed(w_out, other):
    """The pages (html) of W whose bytes differ from `other`'s build of the same name: where taking an entry out shows."""
    return sorted(p for p, b in w_out.items() if p.lower().endswith((".html", ".htm")) and other.get(p) != b)


def _has_reading(entry, files, reading):
    """Does B render a derived reading where `entry` stood (else the plugin's own markup does)?"""
    if entry.file == lookwrite.DERIVED_LOOK_PATH:
        data = reading or {}
    else:
        try:
            data = json.loads(files[lookwrite.DERIVED_LOOK_PATH].decode("utf-8")) if lookwrite.DERIVED_LOOK_PATH in files else {}
        except ValueError:
            data = {}
    kind, _sep, rest = entry.key.partition(":")
    if kind == "reads":
        return rest in (data.get("reads") or {})
    return (rest if kind == "named" else entry.key) in (data.get("named" if kind == "named" else "constructs") or {})


def rows(entries, local, w_out, files, build, reading=None, status=None):
    """The rows of `entries` (`lookwrite.person_entries`): `local` the old build, `w_out` the final build W, `files` the tree W was
    built from, `build(files)` one more build, `reading` derive's look (a dict, for an E2 entry's derived reading) and `status`
    derive's status per construct. Returns ([Row], builds made)."""
    if not entries:
        return [], 0
    b_out, calls = build_without(build, files, entries, reading)
    builds = 1
    status = status or {}
    st = lambda e: status.get(e.construct) if status.get(e.construct) in STATUSES else "none"      # noqa: E731
    w_bad, b_bad = list(getattr(w_out, "problems", ()) or ()), list(getattr(b_out, "problems", ()) or ())
    if w_bad and not b_bad:
        p = w_bad[0]
        return [Row(e, [], None, None, st(e), "refused", message=p.message, fix=getattr(p, "fix", "") or "fix the line it names")
                for e in entries], builds
    pages = _pages_of(entries, b_out, calls)
    needs = [e.name for e in entries if not pages[e.name] or e.key.startswith("reads:")]     # dev 1039: pages B's calls miss
    shared = sorted(set(e.name for e in entries if any(
        q in pages[e.name] for o in entries if o is not e for q in pages[o.name]) and visible(local, w_out, pages[e.name])[0]))
    alone, changed, refuses = {}, {}, set()
    for name in (needs + [n for n in shared if n not in needs])[:PERSON_BUILDS_MAX]:
        alone[name], _c = build_without(build, files, [e for e in entries if e.name == name], reading)
        builds += 1
        if name in needs:
            if getattr(alone[name], "problems", ()) and not w_bad:
                refuses.add(name)      # refused without it, accepted with it: it renders wherever its construct does in W
            else:
                changed[name] = _changed(w_out, alone[name])
    if refuses:
        w_calls = build_without(build, files, [], reading)[1]
        builds += 1
        w_pages = _pages_of([e for e in entries if e.name in refuses], w_out, w_calls)
        changed.update(dict((n, w_pages[n]) for n in refuses))
    fallback = _changed(w_out, b_out) if not b_bad else []        # past the cap: the pages W and B differ on, all entries together
    out = []
    for e in entries:
        mine = sorted(set(pages[e.name]) | set(changed.get(e.name, ())))
        lone = not mine and e.name not in alone
        if lone:
            mine = fallback
        if not mine:
            out.append(Row(e, [], 0, None, st(e), "not reached"))
            continue
        yours, first = visible(local, w_out, mine)
        gone = e.name in refuses
        derived = visible(local, alone.get(e.name, b_out), mine)[0] if _has_reading(e, files, reading) and not gone else None
        # past the cap, an entry that shares a page with another keeps B's numbers, taken out with them: said so
        together = ([o.name for o in entries if o is not e and (lone or set(pages[o.name]) & set(mine))]
                    if lone or (e.name in shared and e.name not in alone) else [])
        kind = "you decide" if derived is not None and yours > derived else "measured"
        out.append(Row(e, mine, yours, derived, st(e), kind, first, together, refuses=gone))
    return out, builds


ACCENT_LINE = "tile %d of %d on %s carries a class the others lack; a look sets apart the first or the last"


def accent_lines(local, pages):
    """Probe P-A's limit (section 6.5), worded as an ACCEPT: on each old page of `pages` (where the person's `tiles` entries render),
    a run of three or more sibling elements of one tag that share a class, of which exactly one carries a class the others lack,
    and it is neither the first nor the last. No `reads` entry can set it apart there: the home and about pages' front matter is a
    closed key list, and a tile line has no field for a mark."""
    out = []
    for path in sorted(p for p in pages if p in local):
        for el in walk(Page(path, local[path].decode("utf-8", "replace")).root):
            kids = [k for k in getattr(el, "kids", ()) if getattr(k, "tag", None)]
            for tag in sorted(set(k.tag for k in kids)):
                run = [set((dict(k.attrs).get("class") or "").split()) for k in kids if k.tag == tag]
                if len(run) < 3 or not set.intersection(*run):
                    continue
                own = [i for i, c in enumerate(run) if c - set().union(*(o for j, o in enumerate(run) if j != i))]
                if len(own) == 1 and 0 < own[0] < len(run) - 1:
                    out.append(ACCENT_LINE % (own[0] + 1, len(run), path))
    return out


def counting(evaluate):
    """`build(files)` for `rows`: the plugin's build of a tree, counted in `evaluate.builds` (section 8.3's bound counts it)."""
    def build(files):
        evaluate.builds = getattr(evaluate, "builds", 0) + 1
        acc = running.accept(files)
        return Output(acc.output, acc.problems)
    return build


def for_parity(view, final, local, snapshot, evaluate, look_status):
    """`parity`'s rows, after the last pass: the person's entries of the basis tree `view`, W the build of the `final` settings
    (`evaluate`, the memo), the tree from `snapshot(final)`, every candidate having been judged under the effective look (the
    conversion lays the person's entries over each derived look: `lookwrite.carry`)."""
    entries = lookwrite.person_entries(view)
    if not entries or local is None:
        return [], []
    look = final.get("look")
    reading = json.loads(look["file"]) if isinstance(look, dict) and look.get("file") else None
    got = rows(entries, local, evaluate(final), snapshot(final), counting(evaluate), reading, look_status)[0]
    return got, accent_lines(local, set(p for r in got if r.entry.construct == "tiles" for p in r.pages))


def for_remeasure(tree, local):
    """`remeasure`'s rows on HEAD (`tree`), when the kept builder ran: W and B both built from HEAD's committed site."""
    entries = lookwrite.person_entries(tree)
    if not entries:
        return [], []
    files = dict((p, tree.read(p)) for p in tree.paths() if p.startswith(("site/", "content/")))
    build = counting(lambda _s: None)
    got = rows(entries, local, build(files), files, build)[0]
    return got, accent_lines(local, set(p for r in got if r.entry.construct == "tiles" for p in r.pages))


# ------------------------------------------------------------------------------------------------- the record (2.8, M6)
def effective_hash(read, site_json=None):
    """The sha256 of `site.json` and the look files it names (`look`, `lookLocal`), as `read(path)` gives them (bytes or None)."""
    raw = site_json if site_json is not None else read("site/site.json")
    try:
        cfg = json.loads((raw or b"{}").decode("utf-8"))
    except ValueError:
        cfg = {}
    parts = [("site/site.json", raw)] + [(p, read(p)) for p in (cfg.get("look"), cfg.get("lookLocal")) if isinstance(p, str)]
    body = json.dumps([[p, hashlib.sha256(b).hexdigest() if b is not None else None] for p, b in parts])
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def measured_rows(settings):
    """{row name: value} of the plan's `look.` and `reads.` rows (section 2.7), for the record."""
    return dict((n, r["value"]) for n, r in sorted((settings or {}).items()) if n.startswith(("look.", "reads.")))


def record_look(settings, read):
    """(the record's `look`, its `effective`) for the plan rows `settings` over the tree `read(path)` reads, or (None, None)
    when there is no row (the record is then the bytes 0.6.0 writes)."""
    look = measured_rows(settings)
    return (look, effective_hash(read)) if look else (None, None)


def tree_reader(tree):
    """`read(path)` over a tree-like object (`exists`, `read`; apply's `Tree` with its pending writes): bytes, or None."""
    return lambda p: tree.read(p) if tree.exists(p) else None


def row_valid(record, name, entry_hash, read):
    """Round 2 M6: is the committed record's row `name` evidence for the entry whose hash is `entry_hash` now? Only while the
    row's `sha256` is that hash and the record's `effective` is the tree's now (`read`): any later look or config commit voids it."""
    row = (record.get("look") or {}).get(name)
    return bool(row) and row["sha256"] == entry_hash and record.get("effective") == effective_hash(read)


def remeasured(record, measured, tree):
    """(look, effective) the record `remeasure` writes: the rows measured now (`measured`, a list of Row), or, when no builder ran
    (`measured` None: none left, or no Node), each row of the committed `record` whose `sha256` is still its entry's hash;
    (None, None) when nothing remains (the record is then the bytes 0.6.0 writes)."""
    if measured is None:              # nothing was measured: the kept rows keep the hash they were measured under (M6)
        look = kept_rows(record, lookwrite.person_entries(tree))
        return (look, record.get("effective")) if look and record.get("effective") else (None, None)
    look = dict((r.entry.name, r.value()) for r in measured)
    return (look, effective_hash(tree_reader(tree))) if look else (None, None)


def kept_rows(record, entries):
    """`remeasure` with no builder to run: each row of the record whose `sha256` is still its entry's hash; the rest dropped."""
    now = dict((e.name, e.sha256) for e in entries)
    return dict((n, v) for n, v in sorted((record.get("look") or {}).items()) if now.get(n) == v["sha256"])
