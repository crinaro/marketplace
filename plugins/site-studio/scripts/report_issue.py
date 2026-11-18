#!/usr/bin/env python3
"""report_issue.py -- the blocker reporter (template-fidelity step 1.5r; design section 8 RP, R3 rulings A4 to A6,
R3N-12, R3N-13, R3N-16, R4 rows 9 and 10, R5.8). Python 3.9, standard library only.

A MODULE, NOT A COMMAND. `adopt.py` (step 1.9r) and `doctor.py --hook` (the way back to the person) import it; it has
no command line of its own, so it is not in `ENTRY_POINTS`. It is the same CONTRACT as
`plugins/jobsearch/scripts/report_issue.py`, REPLICATED here and never imported (principle 2: an install depends only
on what it and its profile carry), with one difference that is the point: a jobsearch report is written by a person
and scanned for personal data; a site-studio report is built from a CLOSED GRAMMAR by this module and so can carry
nothing the person's site holds.

THE CONTRACT (each line is checked in tests/test_report_issue.py)
  * the tracker comes from THIS plugin's own `plugin.json` `repository`, read from the directory this file lives in,
    never a search of the filesystem (jobsearch #59);
  * version provenance: the plugin version, the `site.json` schema, the plan and record schemas, node present yes or
    no, as structured fields (jobsearch #61);
  * a refusal of personal-data shapes (`LEAK_PATTERNS`, copied, plus a URL), and two checks the jobsearch reporter
    does not need: the GRAMMAR (every line of the body matches its template and every variable token is in its
    enumeration, an integer or a version) and the SITE TERMS (no word of the body equals a term collected from the
    site, unless it is plugin vocabulary). Any hit refuses, exit 2, nothing filed (RP "three ways");
  * print first, file only on the person's yes (`file=True`); a `gh` that is missing, not signed in or failing prints
    the report and the tracker URL and files nothing (the `FileNotFoundError` arm is load-bearing: jobsearch #89);
  * no `--email`: out of scope, the printed report can be pasted.

THE CAUSE ID (`CAUSE_RE`, closed grammar). `ss-adopt/<group>/<key>[/<row>]`, every part from a plugin enumeration and
never from the site. Anything outside an enumeration maps to that enumeration's `other` (or `unclassified`) member, and
the count of the cause says how many there were; the value is never echoed (Q1.8). The groups:

    refusal/<code>                       `REFUSAL_CODE_IDS`; unmapped is `refusal/unclassified`
    no-landing/<family>/<area>           `parity_classes.FAMILIES` x `AREAS`
    parity/<kind>[/<row>]                `parity_classes.kind()`'s closed labels; `<row>` is a construct id or `unattributed`
    conversion/<class>                   `CONVERSION_CLASS_IDS`
    builder/fails/<class>                `CONVERSION_CLASS_IDS` or `combined`
    builder/unmeasurable/<language>      `LANGUAGES`
    builder/invocation-differs
    unobservable/<family>
    draft/unsupported/<unit>             `UNITS`
    publish/gate/<family>                `GATE_FAMILIES` (check_site.FAMILIES, asserted equal by a test)
    publish/address
    apply/<stop>                         `APPLY_STOPS`: where the one-process `apply` ended at step 3, 4 or 5 (the publish, the
                                         wait for Pages, the retirement of the old builder); a stop only Pages answers is an
                                         `env/pages-*` cause
    look/unmapped/<construct>            `looks.CONSTRUCTS` (R5.8: the shipped enumeration)
    look/ambiguous/<construct>           `looks.CONSTRUCTS`

EVERY CAUSE HAS A KIND, and only a PLUGIN cause is ever filed (R3N-13 amends decision 17):
    plugin       a release of the plugin can resolve it. Filed on the person's yes, one issue per cause id.
    person       only the person can resolve it: `publish/other-publisher`, `publish/pages-workflow`,
                 `publish/serves-dev-repo`, `refusal/unknown-piece-key`, `apply/run-in-progress`, `apply/no-review`,
                 `apply/push-refused`. Printed with its fix by the caller, never filed.
    environment  `env/*`. Printed with its fix by the caller, never filed.

THE RECORD (`.site-studio/adopt-reports.json`, design 3.5): `parse_reports` is the strict reader and lives HERE so
`doctor.py --hook` reads it with no `adopt` and no `build` import (R3N-16); `dump_reports` is the one writer form.
`may_resolve` is what the SessionStart line counts.

DEDUP (A6, decision 20, revised Q2.8, R3N-12; `dedupe`). Before filing a cause, `gh issue list --state all --search
"<cause id> in:title"` and an EXACT title match on our side (U-10: GitHub's title search tokenises, so a near miss
must file):
    open                      -> `existing`, its number recorded, nothing filed
    closed as not planned     -> `existing` (a decision already made), nothing filed
    closed as completed       -> the fix version is read from a closing comment's `site-studio--v<x.y.z>` tag
                                 (U-17, INFERRED from the release-record convention). An install OLDER than it:
                                 `upgrade`; the same or newer: `regressed`, filed again
    any other stateReason, no tag, a failing or missing `gh`, a list as long as `--limit` with no match
                              -> NOT CHECKED: state unchanged, nothing filed, the reason printed
This module never calls the network on its own: `file=False` runs no subprocess at all.
"""
import json
import os
import re
import subprocess
import sys

import looks
import parity_classes

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)

PREFIX = "ss-adopt"
TITLE_PREFIX = "site-studio adopt: "
FIXED_TAG = re.compile(r"site-studio--v(\d+\.\d+\.\d+)")
LIST_LIMIT = 100                       # `gh issue list --limit`; printed, because a list that long may hide a match
GH_TIMEOUT = 60

# ------------------------------------------------------------------------------------------- the enumerations
# Replicated where the owning module cannot be imported cheaply (the SessionStart hook imports this file); each
# replica is asserted EQUAL to its owner by tests/test_report_issue.py, so a drift is a red test, not a wrong id.
REFUSAL_CODE_IDS = ("unknown-reference-key", "unknown-page-key", "unknown-token", "unknown-piece-key",
                    "piece-both", "redirect-collision", "held-choice", "unclassified")
AREAS = ("content", "site", "root")
# adopt.CONVERSION_CLASSES' names (0.3.1) plus the classes 0.4.0 adds; asserted a superset of adopt's table.
CONVERSION_CLASS_IDS = ("normalise", "redirectKeys", "labels", "redirects", "redirectBoiler", "layout", "tokens",
                        "viewKeys", "pieces", "pieceKeys", "resumeFields", "archive", "draft", "references", "personName", "blocks",
                        "resumePdfName", "pageFiles", "homeKeys", "resumeHeader", "navTokens", "other")
LANGUAGES = ("python", "shell", "ruby", "go", "php", "typescript", "make", "workflow", "other")
UNITS = ("about", "home", "resume", "portfolio", "site-src")
GATE_FAMILIES = ("structure", "comments", "links", "reachable", "privacy", "domain", "media", "unfinished",
                 "performance", "head", "nav", "basepath", "size")
ENV_CAUSES = ("no-node", "builder-fails", "builder-nondeterministic", "pages-unread", "no-public-repo",
              "public-target", "public-unreachable", "pages-not-built", "pages-errored")
# Where `adopt.py apply` can end after its checks (steps 3 to 5): `adoption.publish.Stop` and `adoption.finish` name one of these.
APPLY_STOPS = ("run-in-progress", "publish-refused", "no-review", "not-publishable", "archive-refused", "push-refused")
PERSON_CAUSES = (("publish", "other-publisher"), ("publish", "pages-workflow"), ("publish", "serves-dev-repo"),
                 ("refusal", "unknown-piece-key"), ("apply", "run-in-progress"), ("apply", "no-review"),
                 ("apply", "push-refused"))
VERDICTS = ("EQUAL", "MARKUP-ONLY", "DIFFERENT", "ACCEPTED", "UNVERIFIED", "NOT APPLICABLE")
UNATTRIBUTED = "unattributed"
STATES = ("pending", "filed", "existing", "declined", "resolved", "regressed", "upgrade")

# `Unmapped is counted, never echoed` (Q1.8): the member an out-of-enumeration value becomes, per slot. None means
# the slot has no such member and a value outside it is refused (a construct id comes from the shipped table, so a
# value outside it is a defect in the caller).
FALLBACKS = {"refusal-code": "unclassified", "family": "other", "class": "other", "fails-class": "other",
             "language": "other", "unit": None, "gate": None, "area": None, "construct": None, "apply-stop": None}


def families():
    return tuple(parity_classes.FAMILIES)


def constructs():
    """The shipped construct ids (`looks.CONSTRUCTS`): the one source of a `<row>` and of a `look/` construct."""
    return tuple(sorted(looks.CONSTRUCTS))


def _enum(slot):
    if slot == "refusal-code":
        return REFUSAL_CODE_IDS
    if slot == "family":
        return families()
    if slot == "area":
        return AREAS
    if slot == "class":
        return CONVERSION_CLASS_IDS
    if slot == "fails-class":
        return tuple(c for c in CONVERSION_CLASS_IDS if c != "other") + ("combined", "other")
    if slot == "language":
        return LANGUAGES
    if slot == "unit":
        return UNITS
    if slot == "gate":
        return GATE_FAMILIES
    if slot == "construct":
        return constructs()
    if slot == "apply-stop":
        return APPLY_STOPS
    raise ValueError("unknown slot %r; this is a fault in site-studio: update the plugin, and report it on the plugin's GitHub issues page if it persists" % (slot,))


# The shapes: a tuple of literals and `<slot>` markers. `kind` and `row` are special slots (below).
SHAPES = (
    ("refusal", "<refusal-code>"),
    ("no-landing", "<family>", "<area>"),
    ("parity", "<kind>"),
    ("conversion", "<class>"),
    ("builder", "fails", "<fails-class>"),
    ("builder", "unmeasurable", "<language>"),
    ("builder", "invocation-differs"),
    ("unobservable", "<family>"),
    ("draft", "unsupported", "<unit>"),
    ("publish", "gate", "<gate>"),
    ("publish", "address"),
    ("publish", "pages-workflow"),
    ("publish", "other-publisher"),
    ("publish", "serves-dev-repo"),
    ("apply", "<apply-stop>"),
    ("look", "unmapped", "<construct>"),
    ("look", "ambiguous", "<construct>"),
)

# The shape of an id, nothing more; `parse_cause` is the check against the enumerations.
CAUSE_RE = re.compile(r"\A%s(?:/[A-Za-z0-9][A-Za-z0-9-]*){2,5}\Z" % re.escape(PREFIX))


class CauseError(ValueError):
    """An id that is outside the closed grammar, or a value that cannot be mapped into it."""


def kind_labels_ok(kind):
    """True when `kind` is one of `parity_classes.kind()`'s closed labels."""
    pc = parity_classes
    parts = kind.split("/")
    if kind in ("head-only", "text"):
        return True
    if len(parts) != 2:
        return False
    head, tail = parts
    if head == "element":
        return tail == "other" or tail in pc.STANDARD_ELEMENTS
    if head == "attribute":
        return tail == "other" or tail in pc.STANDARD_ATTRIBUTES
    if head in ("file", "only-local", "only-plugin"):
        return tail in pc.FAMILIES
    return False


def _kind_prefix_len(segments):
    """How many segments (1 or 2) of `segments` form a parity kind, or 0."""
    if not segments:
        return 0
    if segments[0] in ("head-only", "text"):
        return 1
    if len(segments) >= 2 and kind_labels_ok("/".join(segments[:2])):
        return 2
    return 0


def parse_cause(cid):
    """`(shape, values, row)` for a valid id, else CauseError. `shape` is the matched SHAPES entry; `row` is the
    trailing construct id (parity only) or None."""
    if not isinstance(cid, str) or not CAUSE_RE.match(cid):
        raise CauseError("a cause id has the form %s/<group>/<key>, from the plugin's own names; restore .site-studio/adopt-reports.json from an earlier commit (adopt writes it, so never edit it by hand)" % PREFIX)
    segs = cid.split("/")[1:]
    if segs[0] == "env":
        if len(segs) == 2 and segs[1] in ENV_CAUSES:
            return ("env", "<env>"), (segs[1],), None
        raise CauseError("an unknown environment cause; restore .site-studio/adopt-reports.json from an earlier commit (adopt writes it, so never edit it by hand)")
    for shape in SHAPES:
        if shape[0] != segs[0]:
            continue
        values, i, ok = [], 0, True
        for part in shape[1:]:
            if part == "<kind>":
                n = _kind_prefix_len(segs[1 + i:])
                if not n:
                    ok = False
                    break
                values.append("/".join(segs[1 + i:1 + i + n]))
                i += n
            elif part.startswith("<"):
                if 1 + i >= len(segs) or segs[1 + i] not in _enum(part[1:-1]):
                    ok = False
                    break
                values.append(segs[1 + i])
                i += 1
            else:
                if 1 + i >= len(segs) or segs[1 + i] != part:
                    ok = False
                    break
                i += 1
        if not ok:
            continue
        rest = segs[1 + i:]
        if not rest:
            return shape, tuple(values), None
        if shape[0] == "parity" and len(rest) == 1 and (rest[0] == UNATTRIBUTED or rest[0] in constructs()):
            return shape, tuple(values), rest[0]
        raise CauseError("a cause id has a part outside the plugin's own names; restore .site-studio/adopt-reports.json from an earlier commit (adopt writes it, so never edit it by hand)")
    raise CauseError("a cause id has a part outside the plugin's own names; restore .site-studio/adopt-reports.json from an earlier commit (adopt writes it, so never edit it by hand)")


def cause_id(*segments, **kw):
    """Build a valid id from the plugin's own names. A value outside its enumeration becomes that enumeration's
    `other` or `unclassified` member where one exists (counted by the caller, never echoed) and is otherwise refused.
    `row=` is the construct id of a parity cause. `cause_id("parity", "element/div", row="card")`."""
    row = kw.pop("row", None)
    if kw:
        raise TypeError("unexpected keyword %r; this is a fault in site-studio: update the plugin, and report it on the plugin's GitHub issues page if it persists" % sorted(kw))
    segs = [str(s) for s in segments]
    if not segs:
        raise CauseError("empty cause; this is a fault in site-studio: update the plugin, and report it on the plugin's GitHub issues page if it persists")
    if segs[0] == "env":
        out = PREFIX + "/env/" + "/".join(segs[1:])
        parse_cause(out)
        return out
    for shape in SHAPES:
        if shape[0] != segs[0]:
            continue
        out = [PREFIX, shape[0]]
        args = segs[1:]
        ai = 0
        good = True
        for part in shape[1:]:
            if ai >= len(args):
                good = False
                break
            if part == "<kind>":
                kind = args[ai]
                if not kind_labels_ok(kind):
                    head = kind.split("/")[0]
                    if head == "element":
                        kind = "element/other"
                    elif head == "attribute":
                        kind = "attribute/other"
                    else:
                        raise CauseError("a parity kind outside the closed labels; this is a fault in site-studio: update the plugin, and report it on the plugin's GitHub issues page if it persists")
                out.append(kind)
            elif part.startswith("<"):
                slot, value = part[1:-1], args[ai]
                if value not in _enum(slot):
                    fb = FALLBACKS.get(slot)
                    if fb is None:
                        raise CauseError("a value outside the %s enumeration; this is a fault in site-studio: update the plugin, and report it on the plugin's GitHub issues page if it persists" % slot)
                    value = fb
                out.append(value)
            else:
                if args[ai] != part:
                    good = False
                    break
                out.append(part)
            ai += 1
        if not good or ai != len(args):
            continue
        if row is not None:
            if shape[0] != "parity":
                raise CauseError("only a parity cause carries a row")
            out.append(row if row == UNATTRIBUTED or row in constructs() else UNATTRIBUTED)
        cid = "/".join(out)
        parse_cause(cid)
        return cid
    raise CauseError("no cause shape matches %s; this is a fault in site-studio: update the plugin, and report it on the plugin's GitHub issues page if it persists" % "/".join(segs[:1]))


def cause_kind(cid):
    """`plugin`, `person` or `environment`: what may be done with the cause (R3N-13)."""
    shape, values, _row = parse_cause(cid)
    if shape[0] == "env":
        return "environment"
    if tuple(cid.split("/")[1:3]) in PERSON_CAUSES:
        return "person"
    return "plugin"


# ------------------------------------------------------------------------------------------- the body
# One fixed sentence per group. Nothing here is taken from a site; a sentence is also plugin vocabulary.
EXPLAIN = {
    ("refusal",): "The plugin's build refuses a form of source that no conversion clears.",
    ("no-landing",): "A tracked file belongs to the old builder's output and has no place in the plugin's build.",
    ("parity",): "The plugin's build and the old builder's build differ in a way a visitor can see.",
    ("conversion",): "A conversion the plugin offers was declined or held back, and the difference it would make remains.",
    ("builder", "fails"): "The old builder fails once the plugin's conversion of that class is made.",
    ("builder", "unmeasurable"): "The old builder is written in a language the plugin cannot run to compare.",
    ("builder", "invocation-differs"): "The old builder is run by a workflow in a way the plugin cannot reproduce.",
    ("unobservable",): "The plugin could not tell which tracked files of that family the old builder used.",
    ("draft", "unsupported"): "A page that the plugin's build requires has no draft form.",
    ("publish", "gate"): "The plugin's publish gate stops on a finding of that family.",
    ("publish", "address"): "The publish gate stops on a page address that the conversion changes.",
    ("apply",): "The one-process apply stopped after its checks, at a step the plugin could not finish.",
    ("look", "unmapped"): "A construct in the template's markup has no entry the plugin's look grammar can express.",
    ("look", "ambiguous"): "A construct in the template's markup matches more than one entry of the plugin's look grammar.",
}

FOOTER = ("_Filed by `site-studio` from an installed plugin. It carries structure and version only: "
          "no path, name or text from the site._")

# (field, template line). A variable is `{name}`; the grammar check parses each line with `_FIELD_RE`.
BODY = (
    ("cause", "**Cause:** `{cause}`"),
    ("explain", "{explain}"),
    ("", ""),
    ("count", "**Occurrences:** {count}"),
    ("rows", "**Catalogue rows:** {rows}"),
    ("class", "**Conversion class:** {class}"),
    ("verdict", "**Parity verdict:** {verdict}"),
    ("kind", "**Difference kind:** {kind}"),
    ("version", "**Plugin version:** {version}"),
    ("site_schema", "**site.json schema:** {site_schema}"),
    ("plan_schema", "**Plan schema:** {plan_schema}"),
    ("record_schema", "**Record schema:** {record_schema}"),
    ("node", "**node present:** {node}"),
    ("", ""),
    ("rule", "---"),
    ("footer", FOOTER),
)

_VERSION = re.compile(r"\A\d+\.\d+\.\d+\Z")
_INT = re.compile(r"\A\d+\Z")


def explain_for(cid):
    shape, _values, _row = parse_cause(cid)
    for n in (2, 1):
        key = tuple(shape[:n])
        if key in EXPLAIN:
            return EXPLAIN[key]
    raise CauseError("no explanation for a %s cause, which is never filed; this is a fault in site-studio: update the plugin, and report it on the plugin's GitHub issues page if it persists" % cause_kind(cid))


def _tick(value):
    return "`%s`" % value if value is not None else "none"


def provenance(engine=None, site_schema=None, plan_schema=None, record_schema=None, node=None):
    """The structured provenance fields (jobsearch #61). The version is read from THIS plugin's own manifest."""
    return {"version": plugin_version(engine), "site_schema": site_schema, "plan_schema": plan_schema,
            "record_schema": record_schema, "node": node}


def _format_body(cause, prov):
    """The body with NO validation: `build_body` checks, `leak_problems` is the independent safety net, and the
    tests plant a forged field through this function to prove each layer refuses it alone."""
    def num(v):
        return "`%s`" % v if isinstance(v, int) and not isinstance(v, bool) else "`unknown`"
    rows = cause.get("rows") or []
    vals = {
        "cause": cause["id"],
        "explain": cause.get("explain") or "",
        "count": "%s" % cause.get("count"),
        "rows": ", ".join("`%s`" % r for r in rows) if rows else "none",
        "class": _tick(cause.get("class")),
        "verdict": _tick(cause.get("verdict")),
        "kind": _tick(cause.get("kind")),
        "version": "`%s`" % (prov.get("version") or "unknown"),
        "site_schema": num(prov.get("site_schema")),
        "plan_schema": num(prov.get("plan_schema")),
        "record_schema": num(prov.get("record_schema")),
        "node": "unknown" if prov.get("node") is None else ("yes" if prov.get("node") else "no"),
    }
    lines = []
    for _field, template in BODY:
        lines.append(re.sub(r"\{(\w+)\}", lambda m: vals[m.group(1)], template))
    return "\n".join(lines) + "\n"


def build_report(cause, prov):
    """`(title, body)` for one PLUGIN cause. Refuses an invalid id, a person or environment cause, and a field that
    is outside its enumeration. `cause` is `{"id", "count", "rows"[, "class", "verdict", "kind"]}`."""
    cid = cause["id"]
    if cause_kind(cid) != "plugin":
        raise CauseError("a %s cause is printed with its fix and never filed" % cause_kind(cid))
    c = dict(cause)
    c["explain"] = explain_for(cid)
    if not isinstance(c.get("count"), int) or isinstance(c.get("count"), bool) or c["count"] < 1:
        raise CauseError("an occurrence count is a positive integer; this is a fault in site-studio: update the plugin, and report it on the plugin's GitHub issues page if it persists")
    for r in c.get("rows") or []:
        if r != UNATTRIBUTED and r not in constructs():
            raise CauseError("a catalogue row outside the shipped constructs; this is a fault in site-studio: update the plugin, and report it on the plugin's GitHub issues page if it persists")
    if c.get("class") is not None and c["class"] not in CONVERSION_CLASS_IDS + ("combined",):
        raise CauseError("a conversion class outside the enumeration; this is a fault in site-studio: update the plugin, and report it on the plugin's GitHub issues page if it persists")
    if c.get("verdict") is not None and c["verdict"] not in VERDICTS:
        raise CauseError("a parity verdict outside the enumeration; this is a fault in site-studio: update the plugin, and report it on the plugin's GitHub issues page if it persists")
    if c.get("kind") is not None and not kind_labels_ok(c["kind"]):
        raise CauseError("a difference kind outside the closed labels; this is a fault in site-studio: update the plugin, and report it on the plugin's GitHub issues page if it persists")
    return TITLE_PREFIX + cid, _format_body(c, prov)


# ------------------------------------------------------------------------------------------- the leak refusal
# Kept in step with `plugins/jobsearch/scripts/report_issue.py` (replicated, never imported) plus a URL, which a
# site-studio report must never carry.
LEAK_PATTERNS = (
    (r"\$\s?\d[\d,]{2,}", "a currency amount"),
    (r"\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b", "a phone number"),
    (r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "an email address"),
    (r"\b\d{6,}\b", "a bare 6+ digit number"),
    (r"\b(?i:recruiter|contact|manager)\s+[A-Z][a-z]+\s+[A-Z][a-z]+", "a person's name"),
    (r"linkedin\.com/in/[A-Za-z0-9\-_%]+", "a LinkedIn profile URL"),
    (r"/Users/[a-z0-9._\-]+", "a home directory path containing a username"),
    (r"(?i)\b(?:https?|ftp)://\S+|\bwww\.\S+", "a URL"),
)

_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_RUN = re.compile(r"[^\W_]+(?:[-_.][^\W_]+)*", re.UNICODE)


def scan(text, field):
    """The shapes check (jobsearch's `scan`): `[(field, why, found)]`."""
    hits = []
    for pattern, why in LEAK_PATTERNS:
        m = re.search(pattern, text or "")
        if m:
            hits.append((field, why, m.group(0)))
    return hits


def collect_terms(paths=(), tokens=(), text=()):
    """The terms a body must never contain (RP check 2), lower-cased. `paths` are `git ls-files` paths (every segment,
    stem and word of them); `tokens` are every `class` and `id` token and custom element name of either build; `text`
    is the converted content (every word of 4 or more letters). The caller supplies the inputs; deriving them is
    part of the gate and has its own test (jobsearch: a term store that was never read hid a whole class)."""
    terms = set()
    for p in paths:
        for seg in str(p).replace("\\", "/").split("/"):
            if not seg:
                continue
            terms.add(seg.lower())
            terms.add(os.path.splitext(seg)[0].lower())
            terms.update(w.lower() for w in _WORD.findall(seg))
    for t in tokens:
        t = str(t)
        terms.add(t.lower())
        terms.update(w.lower() for w in _WORD.findall(t))
    for chunk in ([text] if isinstance(text, str) else text):
        terms.update(w.lower() for w in re.findall(r"[^\W\d_]{4,}", str(chunk), re.UNICODE))
    terms.discard("")
    return frozenset(terms)


_VOCAB = []


def vocabulary():
    """Every word the plugin itself may print: the template lines, the sentences, every enumeration member and every
    construct, element and attribute name (RP check 2's exemption). A site term that is also plugin vocabulary
    (`content`, `image`, `nav`) cannot be told from the plugin's own word, so the GRAMMAR check is what holds there."""
    if _VOCAB:
        return _VOCAB[0]
    words = set()
    texts = [t for _f, t in BODY] + list(EXPLAIN.values()) + [TITLE_PREFIX, PREFIX, UNATTRIBUTED, "none", "yes", "no",
                                                                "unknown", "combined", "other", "unclassified"]
    pc = parity_classes
    members = (list(REFUSAL_CODE_IDS) + list(AREAS) + list(CONVERSION_CLASS_IDS) + list(LANGUAGES) + list(UNITS)
               + list(GATE_FAMILIES) + list(APPLY_STOPS) + list(ENV_CAUSES) + list(VERDICTS) + list(pc.FAMILIES) + list(constructs())
               + sorted(pc.STANDARD_ELEMENTS) + sorted(pc.STANDARD_ATTRIBUTES)
               + ["head-only", "text", "element", "attribute", "file", "only-local", "only-plugin"]
               + [p for s in SHAPES for p in s if not p.startswith("<")])
    for t in texts + members:
        words.update(w.lower() for w in _WORD.findall(t))
        words.update(r.lower() for r in _RUN.findall(t))
    _VOCAB.append(frozenset(words))
    return _VOCAB[0]


def _line_problems(title, body):
    """Grammar (check 1): every line is its template with only enumerated, integer or version values."""
    probs = []
    lines = body.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    if len(lines) != len(BODY):
        return [("grammar", "the body has %d lines; the template has %d" % (len(lines), len(BODY)), "")]
    cid = None
    for (field, template), line in zip(BODY, lines):
        pattern = re.escape(template)
        pattern = re.sub(r"\\\{(\w+)\\\}", r"(?P<\1>.*)", pattern)
        m = re.match(r"\A%s\Z" % pattern, line)
        if not m:
            probs.append(("grammar", "line `%s` is not its template" % (field or "blank"), line[:60]))
            continue
        g = m.groupdict()
        if field == "cause":
            cid = g["cause"]
            try:
                parse_cause(cid)
            except CauseError as e:
                probs.append(("grammar", "the cause id: %s" % e, cid[:60]))
            if title != TITLE_PREFIX + cid:
                probs.append(("grammar", "the title is not the cause id's", title[:60]))
        elif field == "explain":
            try:
                if cid is None or g["explain"] != explain_for(cid):
                    probs.append(("grammar", "the sentence is not the group's fixed sentence", g["explain"][:60]))
            except CauseError:
                probs.append(("grammar", "the sentence has no group", g["explain"][:60]))
        elif field == "count":
            if not _INT.match(g["count"]) or int(g["count"]) < 1:
                probs.append(("grammar", "the count is not a positive integer", g["count"][:60]))
        elif field == "rows":
            if g["rows"] != "none":
                for item in g["rows"].split(", "):
                    r = item[1:-1] if item[:1] == "`" and item[-1:] == "`" else None
                    if r is None or (r != UNATTRIBUTED and r not in constructs()):
                        probs.append(("grammar", "a catalogue row is not a shipped construct", item[:60]))
        elif field in ("class", "verdict", "kind"):
            v = g[field]
            if v != "none":
                inner = v[1:-1] if v[:1] == "`" and v[-1:] == "`" else None
                allowed = {"class": lambda x: x in CONVERSION_CLASS_IDS + ("combined",),
                           "verdict": lambda x: x in VERDICTS, "kind": kind_labels_ok}[field]
                if inner is None or not allowed(inner):
                    probs.append(("grammar", "the %s is outside its enumeration" % field, v[:60]))
        elif field == "version":
            inner = g["version"][1:-1] if g["version"][:1] == "`" else ""
            if not (_VERSION.match(inner) or inner == "unknown"):
                probs.append(("grammar", "the version is not a version", g["version"][:60]))
        elif field in ("site_schema", "plan_schema", "record_schema"):
            inner = g[field][1:-1] if g[field][:1] == "`" else ""
            if not (_INT.match(inner) or inner == "unknown"):
                probs.append(("grammar", "a schema is not an integer", g[field][:60]))
        elif field == "node":
            if g["node"] not in ("yes", "no", "unknown"):
                probs.append(("grammar", "node present is yes or no", g["node"][:60]))
    return probs


def leak_problems(title, body, terms=(), grammar=True, site_terms=True, shapes=True):
    """Refuse on ANY hit, three ways (RP): the GRAMMAR, the SITE TERMS and the SHAPES. Each layer can be switched off
    so a test proves every layer refuses a planted leak on its own. Returns `[(layer, why, found)]`; empty is clean.
    Terms are matched case-insensitively (a term stored in one case must meet the same token in another)."""
    probs = []
    if grammar:
        probs.extend(_line_problems(title, body))
    if site_terms:
        vocab = vocabulary()
        terms = set(t.lower() for t in terms)
        seen = set()
        for text in (title, body):
            for run in _RUN.findall(text):
                for w in [run] + _WORD.findall(run):
                    wl = w.lower()
                    if wl in terms and wl not in vocab and re.search(r"[^\W\d_]", wl) and wl not in seen:
                        seen.add(wl)
                        probs.append(("site-terms", "a word of the site", w[:60]))
    if shapes:
        probs.extend(scan(title, "title") + scan(body, "body"))
    return probs


# ------------------------------------------------------------------------------------------- the tracker
def _manifest(engine=None):
    try:
        with open(os.path.join(engine or ENGINE, ".claude-plugin", "plugin.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def tracker(engine=None):
    """The PUBLIC marketplace, from this plugin's own manifest, never a filesystem search."""
    repo = str(_manifest(engine).get("repository") or "")
    m = re.search(r"github\.com[:/]([\w.\-]+/[\w.\-]+?)(?:\.git)?/?$", repo)
    return m.group(1) if m else ""


def plugin_version(engine=None):
    v = str(_manifest(engine).get("version") or "")
    return v if _VERSION.match(v) else "unknown"


def version_tuple(v):
    return tuple(int(x) for x in v.split(".")) if isinstance(v, str) and _VERSION.match(v) else None


def run_gh(argv, runner=None):
    """`(returncode, stdout, first stderr line)`; never raises. `gh` missing is the NORMAL state of a cloud or
    headless surface: `subprocess.run` raises `FileNotFoundError` before a returncode exists, so the except arm is
    load-bearing, not defensive (jobsearch #89)."""
    if runner is not None:
        return runner(argv)
    try:
        r = subprocess.run(["gh"] + list(argv), capture_output=True, text=True, timeout=GH_TIMEOUT)
        return r.returncode, r.stdout, (r.stderr.strip().split("\n")[0][:120] if r.stderr.strip() else "")
    except FileNotFoundError:
        return 127, "", "the `gh` CLI is not on this surface"
    except (OSError, subprocess.SubprocessError) as e:
        return 1, "", "gh did not run (%s)" % type(e).__name__


class Outcome(object):
    """What the tracker says about one cause: `state` is new, existing, upgrade, regressed or not-checked."""

    def __init__(self, state, issue=None, fixed_in=None, note=""):
        self.state, self.issue, self.fixed_in, self.note = state, issue, fixed_in, note

    def __repr__(self):
        return "Outcome(%s, %s, %s, %r)" % (self.state, self.issue, self.fixed_in, self.note)


def dedupe(cid, repo, installed, runner=None, limit=LIST_LIMIT):
    """Ask the tracker, read-only, whether `cid` is already reported (A6, Q2.8, U-10, U-17, R3N-12)."""
    title = TITLE_PREFIX + cid
    rc, out, err = run_gh(["issue", "list", "--repo", repo, "--state", "all", "--search", "%s in:title" % cid,
                           "--limit", str(limit), "--json", "number,title,url,state,stateReason"], runner)
    if rc != 0:
        return Outcome("not-checked", note="gh could not list issues (%s)" % (err or "unavailable"))
    try:
        listed = json.loads(out or "[]")
    except ValueError:
        listed = None
    if not isinstance(listed, list):
        return Outcome("not-checked", note="gh answered with something that is not a list of issues")
    hits = [i for i in listed if isinstance(i, dict) and i.get("title") == title
            and isinstance(i.get("number"), int) and not isinstance(i.get("number"), bool)]
    if not hits:
        if len(listed) >= limit:
            return Outcome("not-checked", note="the search returned %d issues, the --limit, and none matched; "
                                               "a match may be past it" % limit)
        return Outcome("new")
    for i in hits:
        if str(i.get("state", "")).upper() == "OPEN":
            return Outcome("existing", issue=i["number"], note="already open")
    latest = max(hits, key=lambda i: i["number"])
    reason = str(latest.get("stateReason") or "").upper()
    if reason == "NOT_PLANNED":
        return Outcome("existing", issue=latest["number"], note="closed as not planned: a decision already made")
    if reason != "COMPLETED":
        return Outcome("not-checked", issue=latest["number"],
                       note="a closed issue with the reason %r, which this check does not judge"
                            % (reason.lower() if re.match(r"\A[A-Z_]{1,20}\Z", reason) else "unreadable"))
    rc, out, err = run_gh(["issue", "view", str(latest["number"]), "--repo", repo, "--json", "comments"], runner)
    if rc != 0:
        return Outcome("not-checked", issue=latest["number"],
                       note="gh could not read the closing comment (%s)" % (err or "unavailable"))
    try:
        comments = json.loads(out or "{}").get("comments") or []
        tags = [m for c in comments if isinstance(c, dict) for m in FIXED_TAG.findall(str(c.get("body") or ""))]
    except (ValueError, AttributeError):
        return Outcome("not-checked", issue=latest["number"], note="gh answered with unreadable comments")
    if not tags:
        return Outcome("not-checked", issue=latest["number"],
                       note="the closure names no fix version (no site-studio--v<x.y.z> tag in its comments)")
    fixed = max(tags, key=version_tuple)
    have = version_tuple(installed)
    if have is None:
        return Outcome("not-checked", issue=latest["number"], fixed_in=fixed,
                       note="this install's version is unreadable, so it cannot be compared with %s" % fixed)
    if have < version_tuple(fixed):
        return Outcome("upgrade", issue=latest["number"], fixed_in=fixed,
                       note="fixed in %s: upgrade site-studio" % fixed)
    return Outcome("regressed", issue=latest["number"], fixed_in=fixed,
                   note="closed as fixed in %s and this install is %s: offered again" % (fixed, installed))


# ------------------------------------------------------------------------------------------- the record
class ReportsError(ValueError):
    """`.site-studio/adopt-reports.json` is not a record this plugin wrote."""


_ROW_KEYS = ("id", "count", "rows", "raisedIn", "state", "issue", "fixedIn", "resolvedIn")


def _row_problem(row, n):
    where = "causes[%d]" % n
    if not isinstance(row, dict) or sorted(row) != sorted(_ROW_KEYS):
        return "%s must hold exactly %s" % (where, ", ".join(_ROW_KEYS))
    try:
        parse_cause(row["id"])
    except CauseError as e:
        return "%s.id: %s" % (where, e)
    if not isinstance(row["count"], int) or isinstance(row["count"], bool) or row["count"] < 1:
        return "%s.count must be a positive integer" % where
    if not isinstance(row["rows"], list) or row["rows"] != sorted(set(row["rows"])) or any(
            not isinstance(r, str) or (r != UNATTRIBUTED and r not in constructs()) for r in row["rows"]):
        return "%s.rows must be a sorted list of shipped construct ids" % where
    if not isinstance(row["raisedIn"], str) or not _VERSION.match(row["raisedIn"]):
        return "%s.raisedIn must be a version" % where
    if row["state"] not in STATES:
        return "%s.state must be one of %s" % (where, ", ".join(STATES))
    if row["issue"] is not None and (not isinstance(row["issue"], int) or isinstance(row["issue"], bool)
                                     or row["issue"] < 1):
        return "%s.issue must be an issue number or null" % where
    for k in ("fixedIn", "resolvedIn"):
        if row[k] is not None and (not isinstance(row[k], str) or not _VERSION.match(row[k])):
            return "%s.%s must be a version or null" % (where, k)
    if row["state"] == "upgrade" and row["fixedIn"] is None:
        return "%s is `upgrade` and needs fixedIn" % where
    if row["state"] == "resolved" and row["resolvedIn"] is None:
        return "%s is `resolved` and needs resolvedIn" % where
    if row["state"] != "resolved" and row["resolvedIn"] is not None:
        return "%s.resolvedIn is set on a row that is not resolved" % where
    return None


def parse_reports(text):
    """The strict reader (design 3.5; R3N-16: no `adopt` and no `build` import, so the SessionStart hook can use it).
    Returns the list of rows, or raises ReportsError naming the first thing it cannot read."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        raise ReportsError("adopt-reports.json is not JSON; restore .site-studio/adopt-reports.json from an earlier commit (adopt writes it, so never edit it by hand)")
    if not isinstance(data, dict) or sorted(data) != ["causes", "schema"]:
        raise ReportsError("adopt-reports.json must hold exactly schema and causes")
    if data["schema"] != 1 or isinstance(data["schema"], bool):
        raise ReportsError("adopt-reports.json schema %r is not understood by this plugin; update site-studio, because a "
                           "newer one wrote it" % (data["schema"],))
    if not isinstance(data["causes"], list):
        raise ReportsError("causes must be a list")
    ids = []
    for n, row in enumerate(data["causes"]):
        problem = _row_problem(row, n)
        if problem:
            raise ReportsError(problem)
        ids.append(row["id"])
    if ids != sorted(set(ids)):
        raise ReportsError("causes must be sorted by id, one row per cause")
    return data["causes"]


def dump_reports(rows):
    """The one written form: sorted by id, sorted keys, no dates, no site text."""
    out = {"schema": 1, "causes": sorted((dict(r) for r in rows), key=lambda r: r["id"])}
    for n, row in enumerate(out["causes"]):
        problem = _row_problem(row, n)
        if problem:
            raise ReportsError(problem)
    return json.dumps(out, indent=2, sort_keys=True) + "\n"


def group_occurrences(occurrences):
    """ONE cause per id, never one per occurrence (A4). `occurrences` are dicts `{"id", "row"[, "class", "verdict",
    "kind"]}`; the result is the sorted list `build_report` takes, `count` being how many there were."""
    groups = {}
    for o in occurrences:
        g = groups.setdefault(o["id"], {"id": o["id"], "count": 0, "rows": set(), "class": [], "verdict": [],
                                        "kind": []})
        g["count"] += 1
        if o.get("row"):
            g["rows"].add(o["row"])
        for k in ("class", "verdict", "kind"):
            if o.get(k):
                g[k].append(o[k])
    out = []
    for cid in sorted(groups):
        g = groups[cid]
        item = {"id": cid, "count": g["count"], "rows": sorted(g["rows"])}
        for k in ("class", "verdict", "kind"):
            item[k] = sorted(g[k])[0] if g[k] else None
        out.append(item)
    return out


def merge_causes(previous, causes, installed):
    """The record after a run (`apply`, `remeasure`): one row per PLUGIN cause. A cause seen before keeps its state,
    issue and `raisedIn`, its count and rows refreshed; a `declined` cause comes back `pending` only on a newer
    plugin version; a `resolved` one that reappears is `pending` again; a cause that has gone is `resolved`."""
    prev = dict((r["id"], r) for r in previous)
    out, seen = [], set()
    for c in causes:
        if cause_kind(c["id"]) != "plugin":
            continue                                       # a person or environment cause is never recorded
        seen.add(c["id"])
        old = prev.get(c["id"])
        if old is None or old["state"] == "resolved":
            row = {"id": c["id"], "state": "pending", "issue": None, "fixedIn": None, "resolvedIn": None,
                   "raisedIn": installed}
        else:
            row = dict(old)
            if old["state"] == "declined" and version_tuple(installed) and \
                    version_tuple(installed) > version_tuple(old["raisedIn"]):
                row.update(state="pending", raisedIn=installed)
        row["count"] = c["count"]
        row["rows"] = sorted(set(c.get("rows") or []))
        out.append(row)
    for cid, old in prev.items():
        if cid not in seen:
            row = dict(old)
            if old["state"] != "resolved":
                row.update(state="resolved", resolvedIn=installed, fixedIn=old["fixedIn"])
            out.append(row)
    return sorted(out, key=lambda r: r["id"])


def decline(rows, ids=None):
    """`adopt.py report --decline`: record `declined` for the pending (or named) causes."""
    out = []
    for r in rows:
        r = dict(r)
        if r["state"] in ("pending", "regressed") and (ids is None or r["id"] in ids):
            r["state"] = "declined"
        out.append(r)
    return out


def may_resolve(rows, installed):
    """How many recorded blockers this install MAY resolve (the SessionStart line, Q2.9, R3N-12): an unresolved row
    raised in an OLDER version than the install, or an `upgrade` row whose fix this install has reached. Reads the
    record only, so it reaches a person whose cause was recorded `existing` on someone else's issue, and runs no `gh`."""
    have = version_tuple(installed)
    if have is None:
        return 0
    n = 0
    for r in rows:
        if r["state"] == "resolved":
            continue
        if r["state"] == "upgrade":
            if version_tuple(r["fixedIn"]) <= have:
                n += 1
        elif version_tuple(r["raisedIn"]) < have:
            n += 1
    return n


# ------------------------------------------------------------------------------------------- the flow
_ISSUE_URL = re.compile(r"/issues/(\d+)")


def report(causes, prov, terms=(), file=False, previous=(), repo=None, runner=None, out=None, err=None,
           engine=None, grammar=True):
    """Print every report first; file them only when `file` is true. Returns `{"code", "rows", "outcomes"}`:
    `code` 0 (done), 1 (could not file or check: nothing was lost, the reports are printed) or 2 (REFUSED: a report
    carried something of the site, nothing was filed and the record is unchanged).

    `causes` are what `group_occurrences` returns. A person or environment cause is skipped with a one-line note, never
    filed. `previous` is the parsed record; `repo` defaults to the plugin's own tracker. Every report is built and
    checked BEFORE any is filed, so one refusal files none of them."""
    out = out if out is not None else sys.stdout
    err = err if err is not None else sys.stderr
    installed = prov.get("version") or plugin_version(engine)
    previous = list(previous)
    plugin_causes, outcomes = [], {}
    for c in causes:
        kind = cause_kind(c["id"])
        if kind != "plugin":
            outcomes[c["id"]] = "not-filed-" + kind
            out.write("not filed (%s cause): %s\n" % (kind, c["id"]))
        else:
            plugin_causes.append(c)
    rows = merge_causes(previous, plugin_causes, installed)
    built = []
    for c in plugin_causes:
        title, body = build_report(c, prov)
        problems = leak_problems(title, body, terms, grammar=grammar)
        if problems:
            err.write("Nothing was filed: a report carries something of the site, or is outside the plugin's "
                      "own grammar.\n\n")
            for layer, why, found in problems:
                err.write("   %-10s %s\n              found: %r\n" % (layer, why, found))
            return {"code": 2, "rows": previous, "outcomes": outcomes}
        built.append((c, title, body))
    repo = tracker(engine) if repo is None else repo
    if not file:
        out.write("DRY RUN: nothing filed. %d report(s) would be filed on --file.\n" % len(built))
    for c, title, body in built:
        out.write("\n%s\n%s\n%s" % ("repo:   %s" % (repo or "unknown"), "title:  %s" % title, body))
    if not file:
        return {"code": 0, "rows": rows, "outcomes": outcomes}
    if not repo:
        err.write("Could not determine the tracker from this plugin's manifest. Report it at the repository "
                  "this plugin was installed from; the reports are printed above.\n")
        return {"code": 1, "rows": rows, "outcomes": outcomes}
    by_id = dict((r["id"], r) for r in rows)
    code = 0
    for c, title, body in built:
        row = by_id[c["id"]]
        if row["state"] not in ("pending", "regressed"):
            outcomes[c["id"]] = "skipped-" + row["state"]
            continue
        found = dedupe(c["id"], repo, installed, runner)
        if found.state == "not-checked":
            code = 1
            outcomes[c["id"]] = "NOT CHECKED"
            err.write("NOT CHECKED %s: %s (the --limit is %d). Nothing filed; the record is unchanged.\n"
                      % (c["id"], found.note, LIST_LIMIT))
            continue
        if found.state in ("existing", "upgrade"):
            row.update(state=found.state, issue=found.issue, fixedIn=found.fixed_in)
            outcomes[c["id"]] = found.state
            out.write("%s: %s (issue #%s)\n" % (c["id"], found.note, found.issue))
            continue
        rc, stdout, why = run_gh(["issue", "create", "--repo", repo, "--title", title, "--body", body], runner)
        if rc != 0:
            code = 1
            outcomes[c["id"]] = "NOT FILED"
            if found.state == "regressed":
                row.update(state="regressed", issue=found.issue, fixedIn=found.fixed_in)
            err.write("Could not file %s (%s). Open https://github.com/%s/issues/new and paste the report above.\n"
                      % (c["id"], why or "gh unavailable", repo))
            continue
        m = _ISSUE_URL.search(stdout or "")
        row.update(state="filed", issue=int(m.group(1)) if m else None, fixedIn=None)
        outcomes[c["id"]] = "filed"
        out.write("Filed %s against %s\n%s\n" % (c["id"], repo, (stdout or "").strip()))
    return {"code": code, "rows": sorted(by_id.values(), key=lambda r: r["id"]), "outcomes": outcomes}
