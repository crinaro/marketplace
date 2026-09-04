#!/usr/bin/env python3
"""Resume variants: the declared printed-resume set, checked against the claim union.

⭐ THE DEFECT THIS CLOSES (GitHub issue #26)
--------------------------------------------
A search spanning two buyer archetypes (an executive buyer and a technical buyer) cannot be
served by one printed resume — the page budget makes the bullet sets irreconcilable. The moment
a second variant existed, the engine could see none of it: the variant was a loose file, "which
variant does this role get" lived as prose in `next_action`, and the union file quietly became a
superset of every printed page while still being documented as the verbatim printed artifact.
The canonical file fell BEHIND the document actually being sent, and no gate could notice,
because no gate knew a variant existed.

## The model — where the authored/record seam falls (design decision D5)

- **`presence/claims.md` is the CLAIM UNION** (formerly `resume.md`; renamed with public #28
  because the old name asserted a printed artifact) — authored prose, the source of truth for
  every background
  claim in its send-ready wording, including claims printed on no current variant (its
  "Additional Detail" addenda were always this). It is NOT a printed artifact.
- **A variant file is a printed resume** — authored prose, one per declared variant.
- **The RECORDS are `data/resume_variants.jsonl`** (which variants exist, which archetype each
  serves, when each was last reconciled against the union — validated by validate_data.py),
  an opportunity's `resume_variant` (the variant to SEND), and an `applications[]` row's
  `resume_variant` (the one actually sent, so outcomes can be attributed to positioning).

With NO variants declared, the union doubles as the single printed resume and every check
here is inert — a single-resume profile owes this module nothing.

## The seam inside a variant file: bullets are claims; prose is positioning

A variant's **bullet lines** (`- `/`* `/`+ `) are claims, and every one must appear in the
union — as one of the union's own bullet lines, or verbatim inside its text (whitespace
normalized, case preserved). Summary paragraphs and headings are per-variant positioning and
are not gated. This mechanizes the standing rule "copy its own sentences; do not paraphrase":
a variant is a SELECTION from the union. When a variant genuinely needs a different wording of
a claim, that wording is added to the union first — so the union stays what its name says.

⭐ **This gate is the flow-back enforcement for the observed failure.** The canonical file fell
behind because bullets were added to the sent document and never flowed back. Under this check
that state is RED: a variant bullet absent from the union fails `--check`, so the flow-back
stops being a habit and becomes a precondition.

⭐ **And it closes the proof-point shortcut** (issue #26's second failure): a claim promoted
straight from `projects.md` into a variant never passed through the union where the candidate's
review lives. Direct promotion now fails the containment check — the only green path is
projects.md → claims.md → variant. (The FACTUAL cross-check of a promoted claim against
recorded employer types is judgment, not string matching; this narrows that window rather than
closing it, and says so.)

## States (the precondition.py rule: an unreadable or unstamped value is LOUD, never guessed)

    ok            active, stamped, every bullet contained, stamp current — PROVENANCE ONLY;
                  fitness for a public surface is not checked (public #59)
    stale         union changed since this variant's last reconcile — FLAGGED, does not fail
                  --check (the union legitimately runs ahead; reconcile and --stamp)
    drifted       ≥1 bullet not found in the union — fails --check
    no-claims     the file has no bullet lines at all, so containment would be vacuous — fails
                  --check ("a schema that silently checks nothing is worse than no schema")
    unstamped     never reconciled (`union_sha` absent) — fails --check; a declared variant
                  nobody has reconciled looks handled and is not
    missing-file  the declared file does not exist — fails --check
    unreadable    the store row cannot be used (no id/file) — fails --check
    retired       terminal; informational row, no claim checks

Also reported, never failing: union bullets outside the addenda that appear in NO active
variant (the observed failure in reverse — a differentiator resting unprinted), and submitted
applications carrying no `resume_variant` while active variants exist (unattributable
positioning).

Usage:
    python3 resume_variants.py             # list + hygiene report
    python3 resume_variants.py --json
    python3 resume_variants.py --check     # exit 1 per the table above
    python3 resume_variants.py --stamp ID  # record a reconcile: union_sha + date onto the row

Python 3.9+. Standard library only.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _root import profile_root
import _tree
import _atomic

UNION_FILE = _tree.rel("claims")           # presence/claims.md; legacy spellings resolve via _tree
STORE_FILE = os.path.join("data", "resume_variants.jsonl")

# Sections of the union whose bullets are deliberately unprinted — exempt from the orphan
# check. Matches the "Additional Detail (elicited beyond the resume)" addenda headings.
ADDENDA_HEADING_RE = re.compile(r"additional\s+detail", re.I)

BULLET_RE = re.compile(r"^\s*[-*+]\s+(.+?)\s*$")
HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$")

# applications[].status values that prove a submission happened — mirrored from
# validate_data.SUBMITTED_APP_STATUS as a literal, same move as precondition.py's OUTCOMES:
# a drifted mirror is caught by the regression suite, not by an import cycle at run start.
SUBMITTED = {"submitted", "acknowledged", "rejected", "advanced"}

FAIL_STATES = frozenset({"drifted", "no-claims", "unstamped", "missing-file", "unreadable"})


def _norm(s):
    """Whitespace-collapsed, case preserved — verbatim discipline minus formatting."""
    return " ".join((s or "").split())


def union_hash(text):
    """12-hex stamp of the union's content, line-ending and trailing-space insensitive."""
    canon = "\n".join(line.rstrip() for line in text.splitlines())
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:12]


def read_union(root):
    path = _tree.path(root, "claims")
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def bullets_with_sections(text):
    """[(normalized_bullet, heading_of_its_section)] in file order."""
    out, heading = [], ""
    for line in (text or "").splitlines():
        hm = HEADING_RE.match(line)
        if hm:
            heading = hm.group(1)
            continue
        bm = BULLET_RE.match(line)
        if bm:
            out.append((_norm(bm.group(1)), heading))
    return out


def load_store(root):
    """(rows, errors, present). Absence is legal — a profile that has not adopted variants —
    and is a DIFFERENT state from present-but-broken (the trap: a missing thing must never
    read as an empty thing)."""
    path = os.path.join(root, STORE_FILE)
    if not os.path.exists(path):
        return [], [], False
    rows, errs = [], []
    with open(path, encoding="utf-8") as fh:
        for i, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError as e:
                errs.append("%s line %d: invalid JSON — %s" % (STORE_FILE, i, e))
    return rows, errs, True


def check_variant(root, rec, union_text, union_norm, union_bullet_set):
    """One report row for one store record."""
    vid = rec.get("id") or "?"
    row = {"id": vid, "archetype": rec.get("archetype"), "file": rec.get("file"),
           "status": rec.get("status"), "state": "ok", "why": "", "violations": [],
           "stale": False}
    if not rec.get("id") or not rec.get("file"):
        row["state"] = "unreadable"
        row["why"] = "row lacks id/file — validate_data.py has the details"
        return row
    if rec.get("status") == "retired":
        row["state"] = "retired"
        row["why"] = "terminal — history stays resolvable, no claim checks"
        return row
    path = os.path.join(root, rec["file"])
    try:
        with open(path, encoding="utf-8") as fh:
            vtext = fh.read()
    except OSError:
        row["state"] = "missing-file"
        row["why"] = "%r does not exist under the profile root — a declared variant pointing " \
                     "at nothing is unlistable, unvalidatable and unsendable" % rec["file"]
        return row
    vbullets = [b for b, _ in bullets_with_sections(vtext)]
    if not vbullets:
        row["state"] = "no-claims"
        row["why"] = "no bullet lines found — the containment check would pass vacuously, " \
                     "which is worse than failing; a printed resume carries its claims as bullets"
        return row
    for b in vbullets:
        if b in union_bullet_set or b in union_norm:
            continue
        row["violations"].append(b)
    if row["violations"]:
        row["state"] = "drifted"
        row["why"] = "%d bullet(s) not found in %s — a claim printed but absent from the " \
                     "union either never flowed back (the observed failure) or was promoted " \
                     "straight from projects.md without review; land it in %s first" \
                     % (len(row["violations"]), UNION_FILE, UNION_FILE)
        return row
    sha = rec.get("union_sha")
    if not sha:
        row["state"] = "unstamped"
        row["why"] = "never reconciled against %s — run `--stamp %s` after a look; a declared " \
                     "variant nobody has reconciled looks handled and is not" % (UNION_FILE, vid)
        return row
    current = union_hash(union_text)
    if sha != current:
        row["stale"] = True
        row["state"] = "stale"
        row["why"] = "union changed since last reconcile (%s, stamp %s ≠ current %s) — check " \
                     "whether the new claims belong on this page, then `--stamp %s`" \
                     % (rec.get("union_reconciled_on") or "?", sha, current, vid)
        return row
    # ⚠️ public #59 stopgap (0.37.1): the green line states its LIMIT. This module proves
    # where each claim came from — nothing more. Whether a page is fit to hand to a given
    # audience is not a question it asks, and a bare "ok" read as if it were.
    row["why"] = "stamped %s — provenance only; fitness for a public surface is not checked" \
                 % (rec.get("union_reconciled_on") or "?")
    return row


def uncovered_applications(root, active_ids):
    """Submitted applications with no resume_variant, while active variants exist."""
    if not active_ids:
        return []
    out = []
    path = os.path.join(root, "data", "opportunities.jsonl")
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                for i, ap in enumerate(r.get("applications") or []):
                    if ap.get("status") in SUBMITTED and not ap.get("resume_variant"):
                        out.append("%s applications[%d] (%s)"
                                   % (r.get("id", "?"), i, ap.get("date") or "undated"))
    except OSError:
        pass
    return out


def report(root):
    """{'present': bool, 'problems': [...global failures...], 'variants': [rows],
    'orphans': [...], 'uncovered': [...]} — problems is what --check fails on, beyond
    per-variant FAIL_STATES."""
    rows, errs, present = load_store(root)
    out = {"present": present, "problems": list(errs), "variants": [],
           "orphans": [], "uncovered": []}
    if not present:
        return out
    union_text = read_union(root)
    active = [r for r in rows if r.get("status") != "retired"]
    if union_text is None:
        if active:
            out["problems"].append(
                "%s is missing while %d active variant(s) are declared — the union the "
                "variants select from does not exist, so every containment check is "
                "unanswerable" % (UNION_FILE, len(active)))
        union_text = ""
    union_pairs = bullets_with_sections(union_text)
    union_bullet_set = {b for b, _ in union_pairs}
    union_norm = _norm(union_text)

    active_bullets = set()
    for rec in rows:
        row = check_variant(root, rec, union_text, union_norm, union_bullet_set)
        out["variants"].append(row)
        if row["state"] in ("ok", "stale", "drifted") and rec.get("file"):
            try:
                with open(os.path.join(root, rec["file"]), encoding="utf-8") as fh:
                    active_bullets |= {b for b, _ in bullets_with_sections(fh.read())}
            except OSError:
                pass

    # The observed failure in reverse: a union claim outside the addenda printed NOWHERE.
    # Flagged, never failing — a claim may legitimately rest between page redesigns.
    if any(r["state"] in ("ok", "stale", "drifted") for r in out["variants"]):
        for b, heading in union_pairs:
            if ADDENDA_HEADING_RE.search(heading):
                continue
            if b not in active_bullets:
                out["orphans"].append(b)

    out["uncovered"] = uncovered_applications(
        root, {r.get("id") for r in active if r.get("id")})
    return out


def stamp(root, vid):
    """Record a reconcile: union_sha + union_reconciled_on onto the named row. Returns 0/1."""
    rows, errs, present = load_store(root)
    if not present:
        print("⛔ %s does not exist — declare the variant before stamping it" % STORE_FILE,
              file=sys.stderr)
        return 1
    if errs:
        for e in errs:
            print("⛔ " + e, file=sys.stderr)
        return 1
    union_text = read_union(root)
    if union_text is None:
        print("⛔ %s is missing — there is no union to reconcile against" % UNION_FILE,
              file=sys.stderr)
        return 1
    hit = [r for r in rows if r.get("id") == vid]
    if not hit:
        known = ", ".join(sorted(str(r.get("id")) for r in rows)) or "(none)"
        print("⛔ no variant %r in %s (known: %s)" % (vid, STORE_FILE, known), file=sys.stderr)
        return 1
    hit[0]["union_sha"] = union_hash(union_text)
    hit[0]["union_reconciled_on"] = datetime.date.today().isoformat()
    _atomic.write_jsonl(os.path.join(root, STORE_FILE), rows)
    print("stamped %s: union_sha=%s on %s" % (vid, hit[0]["union_sha"],
                                              hit[0]["union_reconciled_on"]))
    state = [r for r in report(root)["variants"] if r["id"] == vid]
    if state and state[0]["state"] != "ok":
        print("⚠️  note: %s is still %r — %s" % (vid, state[0]["state"], state[0]["why"]))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 on drifted/no-claims/unstamped/missing-file/unreadable "
                         "or a broken store; stale and orphans are flagged, never failing")
    ap.add_argument("--stamp", metavar="ID",
                    help="record a reconcile against %s onto this variant" % UNION_FILE)
    args = ap.parse_args()
    root = profile_root()

    if args.stamp:
        return stamp(root, args.stamp)

    rep = report(root)
    if args.json:
        print(json.dumps(rep, indent=1))
    else:
        print("RESUME VARIANTS — the declared printed set vs the claim union (%s)\n" % UNION_FILE)
        if not rep["present"]:
            print("  no %s — no variants declared; %s doubles as the single printed "
                  "resume and nothing here applies." % (STORE_FILE, UNION_FILE))
        for p in rep["problems"]:
            print("  ⛔ %s" % p)
        for r in rep["variants"]:
            mark = {"ok": "✅", "stale": "🕰", "retired": "🪦"}.get(r["state"], "⛔")
            print("  %s %-12s %-14s archetype=%-14s %s"
                  % (mark, r["state"], str(r["id"]), str(r["archetype"]), str(r["file"])))
            if r["why"]:
                print("        %s" % r["why"])
            for v in r["violations"]:
                print("        ✗ %s" % v[:100])
        if rep["orphans"]:
            print("\n  🔎 %d union claim(s) outside the addenda printed on NO active variant "
                  "(the observed failure in reverse — flagged, not failing):"
                  % len(rep["orphans"]))
            for b in rep["orphans"][:15]:
                print("     · %s" % b[:100])
        if rep["uncovered"]:
            print("\n  🔎 %d submitted application(s) with no resume_variant while variants "
                  "are declared — outcomes cannot be attributed to positioning:"
                  % len(rep["uncovered"]))
            for u in rep["uncovered"][:15]:
                print("     · %s" % u)

    bad = [r for r in rep["variants"] if r["state"] in FAIL_STATES]
    if args.check:
        for r in bad:
            print("⛔ %s [%s]: %s" % (r["id"], r["state"], r["why"]), file=sys.stderr)
        for p in rep["problems"]:
            print("⛔ " + p, file=sys.stderr)
        return 1 if (bad or rep["problems"]) else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
