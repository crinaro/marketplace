#!/usr/bin/env python3
"""Does profile PROSE still agree with the `config.json` key that owns the value? REPORT ONLY.

dev #495 / public #56 and dev #493 / public #78. A value restated in a narrative document
(a comp floor in `strategy.md`, a "still unconfirmed" line in the handoff letter, a premise
about search scope in a pending decision or a drafted decline) is a SECOND copy of something
`config.json` already owns. Nothing compared the copy to the owner, so the copy drifted and was
read back as current: a floor three raises old, a question reported open after the config
recorded it confirmed, "not open to relocation" carried into a decline while
`geography.relocation.open` said the opposite.

⭐ THE THREE COMPARISONS (each reads an EXISTING config key; no key is added by this check)
-------------------------------------------------------------------------------------------
1. FIGURE   a line naming a "floor" and a money figure, against `compensation.tiers[].floor`
             (the tier is picked by the setting the line names: remote / hybrid / local-onsite /
             relocation; no setting named means the figure must equal SOME tier's floor).
2. OPEN     a line that marks the pay BASIS question open ("basis unconfirmed", "open question",
             "not yet confirmed", ...) while `compensation.tiers[].basis_confirmed` is recorded
             `true`. `basis_confirmed` is the only "confirmed" field config.json carries today;
             `OPEN_MARKER`/`_check_open_questions` are the one place to extend that.
3. SCOPE    (#493) in an OPEN ask (`data/asks.jsonl`, via `your_move.open_asks`) or `drafts.md`:
             a premise about search scope (`SCOPE_PREMISES`) that contradicts the `geography.*`
             key it comes from, OR that cites no config key at all. A premise agreeing with config
             but citing no key is still reported: the point of #493 is that scope is stated FROM a
             key, so a reader can check it, not recalled from an earlier conversation.

WHAT IT SCANS (declared and printed, never inferred): the profile's `strategy.md`, `handoff.md`,
`drafts.md`, `CLAUDE.md` (the INSTALLED rulebook: `install_rulebook.py` copies the engine's
`RULEBOOK.md` there, and a session reads it as fact at start-up; dev #706 / public #152), and every
OPEN ask. Deliberately NOT scanned: `log.md` and `archive/` (history is stale by nature),
`claims.md`/`projects.md` (the candidate's proof points). A figure-or-open-question comparison
(1, 2) runs on every scanned document; the scope comparison (3) runs only on open asks and
`drafts.md`, because that is what #493 reports. The printed `scope:` line names every document
the scan covers, present or not, so a missing `CLAUDE.md` reads as missing, not as clean.
Comparison 2 reads one LINE at a time, so an open-question sentence wrapped across two lines is
not seen in a document; the engine-side check below reads across a wrap.

⭐ THE ENGINE-SIDE CHECK (dev #706 / public #152): `--engine-rulebook`. The scan above reads a
PROFILE's copy; this reads the engine's own `RULEBOOK.md` (the template every profile's CLAUDE.md
is copied from) and FAILS, exit 1, when a line asserts a VALUE for a config key. A rulebook is
shipped to every profile, so a value it states ("the relocation tier's `basis_confirmed` is still
`false`") is true for nobody in particular and read as current by everybody, and goes stale the
moment one profile changes. The key set is every key `config_keys.py` registers (`READER_KEYS`)
plus the keys this file already compares (`SCOPE_PREMISES`' `geography.*` keys and
`compensation.tiers[].basis_confirmed`). ⚠️ `basis_confirmed` is NOT a `config_keys.py` key (that
registry describes the scalar adjustable surface; `compensation.tiers` is absent from it on
purpose), so the registry alone would have passed the very line #706 reported. The rulebook may
NAME a key, or the command that prints it; it may not state what the key holds. This mode is the
one exception to "exit 0 always" below: it checks the repo, not a user's profile, so there is no
unattended run to wedge. It prints how many lines and keys it covered, and an unreadable
rulebook is `NOT CHECKED` with exit 1.

⭐ A CLEAN RESULT IS NEVER EMPTY. The last line always reads `checked N documents, M figures; ...`.
A scan that found no documents, or no config to compare against, prints `NOT CHECKED: <why>` —
a missing thing must never read as an empty thing.

⚠️ ADVISORY, EXIT 0 ALWAYS, AND IT NEVER WRITES. Matching prose to config is inexact (a line
quoting a floor's HISTORY, "was <old>, now <new>", reports the old figure), and a prose section that
looks like a duplicate can be the only surviving copy of a decision. So a finding is a question
for the owner, one line each: document, line, the config key, both values. This script has no
write path (it only reads), and no flag adds one. An absent config key is not
a contradiction (a default is not a recorded value); it is simply not compared.

Usage:
    check_prose_drift.py                 # the profile, or the synthetic fixture when there is none
    check_prose_drift.py --root PATH     # an explicit profile root (a test's temp profile)
    check_prose_drift.py --engine-rulebook [PATH]
                                         # ENGINE check: exit 1 if RULEBOOK.md states a config value

Python 3.9+. Standard library only.
"""

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _root import profile_or_fixture as _pof                       # noqa: E402
import _tree                                                       # noqa: E402
import config_keys as _ck                                          # noqa: E402
import your_move as _ym                                            # noqa: E402

# ── comparison 1: figures ───────────────────────────────────────────────────────────────────
# a currency sign then digits with a `k` suffix, a comma-grouped amount, or a bare `NNNk`. A bare number under 1000 with no `k` is not money.
_MONEY = re.compile(r"[$£€]\s?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s?([kK])?"
                    r"|(?<![\w$£€.,])(\d{2,3}(?:\.\d+)?)\s?[kK]\b")
_FLOOR = re.compile(r"\bfloors?\b", re.I)

# Prose spellings of a tier's `setting`; a setting this table does not know falls back to its
# own name (hyphens matching a space or nothing), so a tier the owner added is still found.
_SETTING_ALIASES = {
    "remote": r"remote",
    "hybrid": r"hybrid",
    "local-onsite": r"local[- ]?on-?site|on-?site|in-office",
    "relocation": r"relocat\w*",
}

# ── comparison 2: open questions ────────────────────────────────────────────────────────────
OPEN_MARKER = re.compile(
    r"\bopen question\b|\bunconfirmed\b|\bnot (?:yet )?confirmed\b|\bstill (?:open|to confirm)\b"
    r"|\bto be confirmed\b|\bTBC\b|\bneeds? (?:to be )?confirm\w*|\bask the candidate\b"
    r"|basis_confirmed\W{0,8}(?:is\W+)?(?:still\W+)?false", re.I)
_BASIS = re.compile(r"\bbasis\b|basis_confirmed", re.I)

# ── comparison 3: scope premises (dev #493) ─────────────────────────────────────────────────
# (name, regex, {config key: value the premise ASSERTS}). Negatives and positives are separate
# rows, and each positive refuses a negating word right before it. Every key is a `geography.*`
# key config.json already carries; `commute_anchors` is not compared (it needs a minutes parse).
_NEG = r"(?<!not )(?<!never )(?<!n't )(?<!no )"
SCOPE_PREMISES = (
    ("not open to relocation",
     re.compile(r"\b(?:not open to|never open to|unwilling to|won't|will not|wouldn't|no)\s+"
                r"(?:consider\s+)?relocat\w*"
                r"|\brelocat\w*\s+(?:is\s+)?(?:off the table|closed|out of scope|not an option"
                r"|ruled out)", re.I),
     {"geography.relocation.open": False}),
    ("open to relocation",
     re.compile(_NEG + r"\b(?:open to|willing to|will consider|considering)\s+(?:a\s+)?relocat\w*",
                re.I),
     {"geography.relocation.open": True}),
    ("remote only",
     re.compile(r"\bremote[- ]only\b|\bonly\s+remote\b", re.I),
     {"geography.remote_ok": True, "geography.hybrid_ok": False}),
    ("no hybrid",
     re.compile(r"\b(?:no|not open to|won't (?:consider|do)|excludes?)\s+hybrid\b"
                r"|\bhybrid\s+(?:is\s+)?(?:out of scope|not acceptable|ruled out|off the table)",
                re.I),
     {"geography.hybrid_ok": False}),
    ("open to hybrid",
     re.compile(_NEG + r"\b(?:open to|willing to do)\s+hybrid\b", re.I),
     {"geography.hybrid_ok": True}),
    ("no remote",
     re.compile(r"\b(?:no|not open to|excludes?)\s+remote(?![- ]only)\b", re.I),
     {"geography.remote_ok": False}),
    ("open to remote",
     re.compile(_NEG + r"\bopen to remote\b", re.I),
     {"geography.remote_ok": True}),
    ("no EU roles",
     re.compile(r"\b(?:no|not open to|excludes?)\s+(?:EU|Europe\w*)\b"
                r"|\b(?:EU|Europe\w*)\s+(?:is\s+)?(?:out of scope|ruled out|off the table)",
                re.I),
     {"geography.eu_ok": False}),
    ("open to EU roles",
     re.compile(_NEG + r"\bopen to (?:EU|Europe\w*)\b", re.I),
     {"geography.eu_ok": True}),
)


# dev #706 / public #152: the profile's copy of the engine's RULEBOOK.md. It stays at the profile
# root (`_tree.py` lists CLAUDE.md among the root anchors), so no layout lookup is needed.
INSTALLED_RULEBOOK = "CLAUDE.md"
# What `scan()` covers, printed as a declaration rather than read back from whatever existed.
SCAN_SCOPE = ("strategy.md", "handoff.md", "drafts.md",
              "CLAUDE.md (the installed rulebook)", "open asks")

# ── the engine-side check: a shipped rulebook states no config value (dev #706) ─────────────
ENGINE_RULEBOOK = os.path.join(os.path.dirname(HERE), "RULEBOOK.md")
# The one key the drift check compares that `config_keys.py` does not register: it lives in
# `compensation.tiers[]`, a table, not a scalar. Spelled once here, by its full path and its leaf.
_TIER_BASIS_KEY = "compensation.tiers[].basis_confirmed"

_SP = r"(?:[ \t]+|[ \t]*\n[ \t]*)"          # a space, or ONE line wrap (never a blank line)
_COPULA = r"(?:is|are|was|were|equals?|reads?|set to|now|currently|still)"
_CONNECT = (r"(?:[ \t]*(?:==|=|:)[ \t]*|" + _SP + _COPULA + r"(?:" + _SP + _COPULA + r")*" + _SP
            + r")")
# A literal value: a boolean/null, a number, or a quoted string. A bare word is not one, so
# "`ats.close` is one of ..." and "`remote_ok` is a boolean" name the key without asserting.
_VALUE = (r"(?:`?(?:true|false|null|none)`?(?![\w])|`?-?\d[\d,]*(?:\.\d+)?`?(?![\w])"
          r"|\"[^\"\n]+\"|`[^`\n]+`)")


def asserted_keys():
    """{token: key} for every config key a rulebook line must not state a value for: each key
    `config_keys.py` registers, the `geography.*` keys `SCOPE_PREMISES` compares, and the tier
    `basis_confirmed` field. A token is the dotted path, plus the leaf when it is an identifier
    (it holds an underscore) so `remote_ok` and `basis_confirmed` are caught without their prefix."""
    keys = set(_ck.READER_KEYS)
    for _name, _rx, asserts in SCOPE_PREMISES:
        keys.update(asserts)
    keys.add(_TIER_BASIS_KEY)
    tokens = {}
    for k in sorted(keys):
        tokens[k] = k
        leaf = k.split(".")[-1]
        if "_" in leaf:
            tokens.setdefault(leaf, k)
    return tokens


class RulebookAssertion(object):
    """One rulebook line that states what a config key holds: line, key, the offending text."""

    def __init__(self, line, key, text):
        self.line, self.key, self.text = line, key, text

    def render(self, doc="RULEBOOK.md"):
        return ("%s:%d: [rulebook-asserts-value] `%s` -- the rulebook ships to every profile and "
                "must name the key, not state its value: %r" % (doc, self.line, self.key,
                                                                " ".join(self.text.split())))


def rulebook_assertions(text):
    """Every place `text` states a VALUE for a config key (see `asserted_keys`). Reads across a
    single line wrap, because the sentence #706 reported was wrapped between `is` and `still false`.
    Returns [RulebookAssertion]. Never reads a file or a profile."""
    tokens = asserted_keys()
    alt = "|".join(re.escape(t) for t in sorted(tokens, key=len, reverse=True))
    rx = re.compile(r"(?<![\w.])(?P<tok>%s)(?![\w])[`\"']?%s(?P<val>%s)" % (alt, _CONNECT, _VALUE),
                    re.I)
    out = []
    for m in rx.finditer(text):
        out.append(RulebookAssertion(text.count("\n", 0, m.start()) + 1,
                                     tokens.get(m.group("tok"), m.group("tok")), m.group(0)))
    return out


def check_engine_rulebook(path=None):
    """(assertions, lines, n_keys, not_checked) for the engine's rulebook at `path`."""
    path = path or ENGINE_RULEBOOK
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        return [], 0, 0, "%s unreadable (%s)" % (path, exc)
    tokens = asserted_keys()
    if not text.strip():
        return [], 0, len(set(tokens.values())), "%s is empty" % path
    return rulebook_assertions(text), text.count("\n") + 1, len(set(tokens.values())), None


def _engine_main(path):
    found, lines, n_keys, not_checked = check_engine_rulebook(path)
    print("ENGINE RULEBOOK vs CONFIG KEYS (fails on a stated config value)")
    if not_checked:
        print("  NOT CHECKED: %s" % not_checked)
        return 1
    print("  scanned: %s, %d lines, against %d config keys" % (path or ENGINE_RULEBOOK, lines, n_keys))
    for a in found:
        print("  %s" % a.render())
    print("  %d assertion(s)" % len(found))
    return 1 if found else 0


class Finding(object):
    """One advisory line: where (doc, line), what kind, which config key, both values."""

    def __init__(self, doc, line, kind, key, prose, config, why):
        self.doc, self.line, self.kind = doc, line, kind
        self.key, self.prose, self.config, self.why = key, prose, config, why

    def render(self):
        return ("%s:%s: [%s] %s -- config.json %s = %s; prose says %s"
                % (self.doc, self.line, self.kind, self.why, self.key, _fmt(self.config),
                   _fmt(self.prose)))


def _fmt(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return "{:,}".format(v)
    return str(v)


def _tiers(cfg):
    t = _ck._get_dotted(cfg, "compensation.tiers")
    return [x for x in t if isinstance(x, dict) and x.get("setting")] if isinstance(t, list) else []


def _setting_re(setting):
    alias = _SETTING_ALIASES.get(setting)
    if alias is None:
        alias = re.escape(setting).replace(r"\-", r"[- ]?")
    return re.compile(r"\b(?:%s)\b" % alias, re.I)


def _named_tiers(line, tiers):
    return [t for t in tiers if _setting_re(t["setting"]).search(line)]


def _figures(line):
    """The money figures on a line, as whole-currency ints."""
    out = []
    for m in _MONEY.finditer(line):
        if m.group(3):                                   # bare `210k`
            out.append(int(round(float(m.group(3)) * 1000)))
        elif m.group(2):                                 # a `k`-suffixed amount
            out.append(int(round(float(m.group(1).replace(",", "")) * 1000)))
        else:                                            # a comma-grouped or plain whole-dollar amount
            v = float(m.group(1).replace(",", ""))
            if v >= 1000:
                out.append(int(round(v)))
    return out


def _check_figures(doc, lineno, line, tiers, counts):
    found = []
    if not _FLOOR.search(line) or not tiers:
        return found
    named = _named_tiers(line, tiers)
    cands = named or tiers
    floors = [t.get("floor") for t in cands if isinstance(t.get("floor"), int)]
    if not floors:
        return found
    for fig in _figures(line):
        counts["figures"] += 1
        if fig in floors:
            continue
        if named:
            t = named[0]
            key, val = "compensation.tiers[setting=%s].floor" % t["setting"], t.get("floor")
        else:
            key = "compensation.tiers[*].floor"
            val = ", ".join("%s=%s" % (t["setting"], _fmt(t.get("floor"))) for t in tiers)
        found.append(Finding(doc, lineno, "figure", key, fig, val,
                             "a comp floor in prose disagrees with its source"))
    return found


def _check_open_questions(doc, lineno, line, tiers, counts):
    if not (OPEN_MARKER.search(line) and _BASIS.search(line)) or not tiers:
        return []
    counts["open"] += 1
    named = _named_tiers(line, tiers)
    if named:
        hit = [t for t in named if t.get("basis_confirmed") is True]
    else:
        explicit = [t for t in tiers if "basis_confirmed" in t]
        hit = explicit if explicit and all(t["basis_confirmed"] is True for t in explicit) else []
    return [Finding(doc, lineno, "open-question",
                    "compensation.tiers[setting=%s].basis_confirmed" % t["setting"], "open",
                    t["basis_confirmed"], "a question marked open is recorded as confirmed")
            for t in hit]


def _check_scope(doc, lineno, line, unit_text, cfg, counts):
    found = []
    for name, rx, asserts in SCOPE_PREMISES:
        if not rx.search(line):
            continue
        counts["scope"] += 1
        cited = any(k in unit_text for k in asserts)
        wrong = [(k, v) for k, v in asserts.items()
                 if isinstance(_ck._get_dotted(cfg, k), bool) and _ck._get_dotted(cfg, k) != v]
        if wrong:
            for k, v in wrong:
                found.append(Finding(
                    doc, lineno, "scope",
                    k, v, _ck._get_dotted(cfg, k),
                    "scope premise '%s' contradicts config%s"
                    % (name, "" if cited else " and cites no key")))
        elif not cited:
            k = sorted(asserts)[0]
            cv = _ck._get_dotted(cfg, k)
            found.append(Finding(
                doc, lineno, "scope", k, asserts[k], "not set" if cv is None else cv,
                "scope premise '%s' states scope with no config key cited" % name))
    return found


def _read_lines(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().split("\n")
    except OSError:
        return None


def _open_ask_units(root):
    """[(doc label, row line number, [text lines])] for each OPEN ask — membership is
    `your_move.open_asks`'s, never re-derived here."""
    path = os.path.join(root, "data", "asks.jsonl")
    rows, by_id_line = [], {}
    try:
        with open(path, encoding="utf-8") as fh:
            for n, raw in enumerate(fh, 1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    row = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
                    by_id_line[id(row)] = n
    except OSError:
        return []
    units = []
    for a in _ym.open_asks(rows):
        text = "\n".join(str(a.get(f) or "") for f in ("title", "ask", "note"))
        units.append(("data/asks.jsonl (ask %s)" % (a.get("id") or "?"), by_id_line[id(a)],
                      text.split("\n")))
    return units


def scan(root):
    """(findings, counts, scanned, not_checked) for the profile at `root`. Never writes."""
    counts = {"documents": 0, "figures": 0, "open": 0, "scope": 0}
    findings, scanned, not_checked = [], [], []
    try:
        with open(os.path.join(root, "config.json"), encoding="utf-8") as fh:
            cfg = json.load(fh)
        if not isinstance(cfg, dict):
            raise ValueError("not a JSON object")
    except (OSError, ValueError) as exc:
        return [], counts, scanned, ["config.json unreadable (%s): nothing to compare against"
                                     % exc]
    tiers = _tiers(cfg)
    if not tiers:
        not_checked.append("config.json has no compensation.tiers: figures and open-question "
                           "lines were not compared")

    files = (("strategy", _tree.path(root, "strategy"), False),
             ("handoff.md", os.path.join(root, "handoff.md"), False),
             ("drafts", _tree.path(root, "drafts"), True),
             (INSTALLED_RULEBOOK, os.path.join(root, INSTALLED_RULEBOOK), False))
    for label, path, scope in files:
        lines = _read_lines(path)
        name = os.path.relpath(path, root) if lines is not None else label
        if lines is None:
            continue
        counts["documents"] += 1
        scanned.append(name)
        para = []                      # (lineno, text) of the current blank-line paragraph

        def flush():
            unit = "\n".join(t for _n, t in para)
            for n, t in para:
                findings.extend(_check_scope(name, n, t, unit, cfg, counts))
            del para[:]

        for n, text in enumerate(lines, 1):
            findings.extend(_check_figures(name, n, text, tiers, counts))
            findings.extend(_check_open_questions(name, n, text, tiers, counts))
            if scope:
                if text.strip():
                    para.append((n, text))
                else:
                    flush()
        if scope:
            flush()

    asks = _open_ask_units(root)
    for name, n, lines in asks:
        counts["documents"] += 1
        unit = "\n".join(lines)
        for text in lines:
            findings.extend(_check_figures(name, n, text, tiers, counts))
            findings.extend(_check_open_questions(name, n, text, tiers, counts))
            findings.extend(_check_scope(name, n, text, unit, cfg, counts))
    if asks:
        scanned.append("%d open ask%s" % (len(asks), "" if len(asks) == 1 else "s"))
    if not counts["documents"]:
        not_checked.append("no narrative document or open ask found under the profile root")
    return findings, counts, scanned, not_checked


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", help="an explicit profile root (default: the profile, or the "
                                   "synthetic fixture when there is none)")
    ap.add_argument("--engine-rulebook", nargs="?", const="", metavar="PATH",
                    help="the ENGINE check (dev #706): read the shipped RULEBOOK.md (or PATH) and "
                         "exit 1 if a line states the value of a config key. Reads no profile.")
    args = ap.parse_args(argv)
    if args.engine_rulebook is not None:
        return _engine_main(args.engine_rulebook or None)
    try:
        root = args.root or _pof()
        findings, counts, scanned, not_checked = scan(root)
    except Exception as exc:                  # advisory: a crash must never wedge a run
        print("NOT CHECKED: prose-vs-config drift check could not run (%s: %s)"
              % (type(exc).__name__, exc))
        return 0
    print("PROSE vs CONFIG DRIFT (advisory, report only; nothing is edited)")
    print("  scope:   %s" % ", ".join(SCAN_SCOPE))
    print("  scanned: %s" % (", ".join(scanned) if scanned else "nothing"))
    for why in not_checked:
        print("  NOT CHECKED: %s" % why)
    for f in findings:
        print("  %s" % f.render())
    print("  checked %d documents, %d figures; %d open-question line(s), %d scope premise(s); "
          "%d finding(s)" % (counts["documents"], counts["figures"], counts["open"],
                              counts["scope"], len(findings)))
    if findings:
        print("  Each finding is a question: fix the prose, or the config key if the prose is "
              "right. This check changes nothing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
