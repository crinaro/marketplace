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
`drafts.md`, and every OPEN ask. Deliberately NOT scanned: `log.md` and `archive/` (history is
stale by nature), `claims.md`/`projects.md` (the candidate's proof points). A figure-or-open-
question comparison (1, 2) runs on every scanned document; the scope comparison (3) runs only on
open asks and `drafts.md`, because that is what #493 reports.

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
             ("drafts", _tree.path(root, "drafts"), True))
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
    args = ap.parse_args(argv)
    try:
        root = args.root or _pof()
        findings, counts, scanned, not_checked = scan(root)
    except Exception as exc:                  # advisory: a crash must never wedge a run
        print("NOT CHECKED: prose-vs-config drift check could not run (%s: %s)"
              % (type(exc).__name__, exc))
        return 0
    print("PROSE vs CONFIG DRIFT (advisory, report only; nothing is edited)")
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
