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
    unplaced      no `surface` declared, or an undeclared one (ADR-027) — fails --check; an
                  undeclared surface is a STATE, never a default, so a row this module cannot
                  place either way is loud, never guessed
    private-on-public
                  a public-surface row prints a claim with no per-claim `[public]` marking —
                  fails --check; public #59's own defect, now mechanized (ADR-027)
    retired       terminal; informational row, no claim checks

Also reported, never failing: union bullets outside the addenda that appear in NO active
variant (the observed failure in reverse — a differentiator resting unprinted), and submitted
applications carrying no `resume_variant` while active variants exist (unattributable
positioning).

## Visibility (public #59, ADR-027) — union membership is provenance, not clearance

A claim can be true, present in the union, and still unpublishable on the open web (a
security-posture claim about a former employer is the reported instance — appropriate inside a
screened hiring process, harmful once indexed and public). ADR-027's decision, not this
module's own invention:

- **A declared variant carries `surface`, never `visibility` directly** (`data/
  resume_variants.jsonl`; `surfaces.py` is the one lookup table). `visibility` is DERIVED from
  `surface` by property — *private* = the candidate chooses every recipient, *public* = any
  reader can reach it without being chosen — never stored a second time.
- **An undeclared, or unrecognized, `surface` is not a default — it is the `unplaced` state,
  and it fails.** Neither a private-by-default nor a public-by-default guess is acceptable
  (ADR-027's own words: "a surface nobody classified silently permits everything" versus
  "turns every existing variant red at upgrade, which trains bypassing the check"); the gate
  refuses to guess either way.
- **Claim marking is a bracketed tag at the HEAD of the union bullet's own text** —
  `[public]`/`[private]`, never a section default, never a cross-reference table, never an id.
  Because the tag sits at the head of a line the existing whole-text substring containment
  (`b in union_norm`) already tolerates it as a prefix — the printed, UNTAGGED wording is still
  literally a substring of the tagged union line, so ordinary containment needs no change.
  `union_claim_tags()` reads the tag directly off each bullet.
- **Pairing is nesting plus the tag**, for the failure message only, never for the pass/fail
  decision itself: a `[private]`-tagged bullet indented directly under a `[public]`-tagged one
  is that claim's original wording, paired with its reviewed, safe public version.
- **The `[public]` tag is a per-claim review stamp, not metadata inherited from a section.**
  Deliberately no section-level default — a section default lets claims onto a public page
  nobody individually reviewed, which is the failure ADR-027 exists to close. On a
  public-surface variant, a printed bullet whose matching union claim is `[private]`-tagged
  OR carries no tag at all fails `private-on-public` — cannot-decide always resolves to RED on
  this axis, never a guess either way.

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
import applications as _apps
import surfaces as _surf

UNION_FILE = _tree.rel("claims")           # presence/claims.md; legacy spellings resolve via _tree
STORE_FILE = os.path.join("data", "resume_variants.jsonl")

# Sections of the union whose bullets are deliberately unprinted — exempt from the orphan
# check. Matches the "Additional Detail (elicited beyond the resume)" addenda headings.
ADDENDA_HEADING_RE = re.compile(r"additional\s+detail", re.I)

BULLET_RE = re.compile(r"^\s*[-*+]\s+(.+?)\s*$")
# Same bullet grammar as BULLET_RE, with the leading indentation captured separately —
# union_claim_tags() needs it to pair a nested `[private]` twin with its `[public]` parent; the
# plain containment path (bullets_with_sections) never needed nesting, only section membership.
BULLET_INDENT_RE = re.compile(r"^(\s*)[-*+]\s+(.+?)\s*$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")

# public #59, ADR-027 — the per-claim marking, at the HEAD of a union bullet's own text. No
# section default, no cross-reference table, no id: the tag IS the claim's review stamp.
CLAIM_TAG_RE = re.compile(r"^\[(public|private)\]\s*(.+)$", re.I)

# applications[].status values that prove a submission happened — mirrored from
# validate_data.SUBMITTED_APP_STATUS as a literal, same move as precondition.py's OUTCOMES:
# a drifted mirror is caught by the regression suite, not by an import cycle at run start.
SUBMITTED = {"submitted", "acknowledged", "rejected", "advanced", "closed"}

FAIL_STATES = frozenset({"drifted", "no-claims", "unstamped", "missing-file", "unreadable",
                        "unplaced", "private-on-public"})


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
    """[(normalized_bullet, heading_path_of_its_section)] in file order.

    public #67 — heading_path is the full ancestor chain ("Outer > Inner"), not just the
    nearest heading. A single flat `heading` variable overwritten on every heading line loses
    the addenda association the moment a sub-heading nests under it: an "## Additional Detail"
    section containing "### <topic>" sub-headings reported every bullet under the sub-heading
    as having heading "<topic>" alone, so ADDENDA_HEADING_RE.search(heading) in report() no
    longer matched "additional detail" and those claims were counted as claims outside the
    addenda — overstated, not actually orphaned. Joining the ancestor chain keeps the match
    working via the same substring search, however deep the nesting goes.
    """
    out, stack = [], []   # stack: [(level, text), ...], outermost first
    for line in (text or "").splitlines():
        hm = HEADING_RE.match(line)
        if hm:
            level, htext = len(hm.group(1)), hm.group(2)
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, htext))
            continue
        bm = BULLET_RE.match(line)
        if bm:
            out.append((_norm(bm.group(1)), " > ".join(t for _, t in stack)))
    return out


def union_claim_tags(text):
    """(tag_by_text, twin_of_private) — ADR-027's per-claim marking, over the union file.

    tag_by_text     {stripped claim text: "public"|"private"} for every union bullet whose OWN
                    text starts with `[public]`/`[private]` (case-insensitive). An untagged
                    bullet is simply absent here — union bullets never require a tag; only
                    PRINTING one on a public-surface variant does. The tag is stripped from the
                    text this dict keys on, because the tag itself is never printed.
    twin_of_private {private claim text: its paired public claim's stripped text} — for the
                    private-on-public failure message ONLY. A `[private]`-tagged bullet nested
                    directly under a `[public]`-tagged one (bullet indentation, independent of
                    heading depth) is treated as that claim's original wording; a private
                    bullet with no such parent simply has no entry.

    Nesting never affects the pass/fail decision — only which suggestion the message can make.
    A printed bullet's own tag (found by a plain dict lookup on its text) decides everything.
    """
    tag_by_text = {}
    twin_of_private = {}
    bullet_stack = []      # [(indent, tag_or_None, claim_text), ...] — reset at every heading
    for line in (text or "").splitlines():
        if HEADING_RE.match(line):
            bullet_stack = []
            continue
        bm = BULLET_INDENT_RE.match(line)
        if not bm:
            continue
        indent = len(bm.group(1))
        raw = bm.group(2)
        while bullet_stack and bullet_stack[-1][0] >= indent:
            bullet_stack.pop()
        parent = bullet_stack[-1] if bullet_stack else None
        tm = CLAIM_TAG_RE.match(raw)
        if tm:
            tag = tm.group(1).lower()
            claim = _norm(tm.group(2))
            tag_by_text[claim] = tag
            if tag == "private" and parent is not None and parent[1] == "public":
                twin_of_private[claim] = parent[2]
            bullet_stack.append((indent, tag, claim))
        else:
            bullet_stack.append((indent, None, _norm(raw)))
    return tag_by_text, twin_of_private


def _levenshtein_le(a, b, limit):
    """True if the edit distance between a and b is <= limit. Small words only (tag tokens) —
    a plain O(len(a)*len(b)) table, stdlib-only, no reason to reach for anything smarter at
    this size."""
    if abs(len(a) - len(b)) > limit:
        return False
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
        prev = cur
    return prev[-1] <= limit


_TAG_WORD_RE = re.compile(r"^\[([A-Za-z]{3,10})\]")


def suspected_tag_typos(text):
    """[(bullet_text, word)] — a union bullet whose head carries a bracketed word close to
    "public"/"private" (edit distance <= 2, case-insensitive) that CLAIM_TAG_RE does NOT
    recognize ("[pubic] ..." is the shape a fat-fingered mark takes).

    Never a SAFETY gap under this design — an unrecognized tag reads as no tag at all, which
    already fails CLOSED on a public-surface variant (`private-on-public`'s own "cannot-decide
    -> red, never a guess" rule). Reported anyway so the typo is found by inspection rather
    than by a private-on-public failure with no visible cause."""
    hits = []
    for line in (text or "").splitlines():
        bm = BULLET_INDENT_RE.match(line)
        if not bm:
            continue
        raw = bm.group(2)
        if CLAIM_TAG_RE.match(raw):
            continue
        tm = _TAG_WORD_RE.match(raw)
        if not tm:
            continue
        word = tm.group(1)
        wl = word.lower()
        if _levenshtein_le(wl, "public", 2) or _levenshtein_le(wl, "private", 2):
            hits.append((_norm(raw), word))
    return hits


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


def check_variant(root, rec, union_text, union_norm, union_bullet_set,
                  union_tag_by_text=None, union_twin_of_private=None):
    """One report row for one store record.

    `union_tag_by_text`/`union_twin_of_private` come from union_claim_tags() — passed in
    rather than recomputed per row, the same "compute once in report(), reuse per record"
    shape `union_bullet_set`/`union_norm` already use.
    """
    union_tag_by_text = union_tag_by_text or {}
    union_twin_of_private = union_twin_of_private or {}
    vid = rec.get("id") or "?"
    row = {"id": vid, "archetype": rec.get("archetype"), "file": rec.get("file"),
           "status": rec.get("status"), "state": "ok", "why": "", "violations": [],
           "stale": False, "surface": rec.get("surface"), "visibility": None}
    if not rec.get("id") or not rec.get("file"):
        row["state"] = "unreadable"
        row["why"] = "row lacks id/file — validate_data.py has the details"
        return row
    if rec.get("status") == "retired":
        row["state"] = "retired"
        row["why"] = "terminal — history stays resolvable, no claim checks"
        return row
    surface = rec.get("surface")
    if surface not in _surf.names():
        row["state"] = "unplaced"
        known = ", ".join(_surf.names())
        if surface is None:
            row["why"] = ("no surface declared — ADR-027: 'an undeclared surface is not a "
                         "default; it is a state, and it fails' — declare the surface on "
                         "the variant row (known: %s)" % known)
        else:
            row["why"] = ("surface %r is not declared in surfaces.py (known: %s) — an "
                         "undeclared surface fails rather than guesses" % (surface, known))
        return row
    # ⭐ derived, never stored a second time (ADR-027) — computed here from `surface`, the
    # one lookup this module (and presence_set.py, and any future renderer) reads.
    visibility = _surf.visibility(surface)
    row["visibility"] = visibility
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
    # public #59, ADR-027 — the pass containment alone cannot make: a public-surface variant
    # printing a claim with no per-claim `[public]` marking. Checked only for a `public`
    # surface, and only after ordinary containment already passed (a bullet absent from the
    # union entirely is still `drifted`, never this).
    if visibility == "public":
        leaked = [b for b in vbullets if union_tag_by_text.get(b) != "public"]
        if leaked:
            first = leaked[0]
            tag = union_tag_by_text.get(first)
            twin = union_twin_of_private.get(first) if tag == "private" else None
            row["state"] = "private-on-public"
            row["violations"] = leaked
            if twin:
                row["why"] = ("prints a claim marked [private] — union membership alone is "
                             "not sufficient for a public page; use its public wording: %r"
                             % twin)
            elif tag == "private":
                row["why"] = ("prints a claim marked [private] with no declared [public] "
                             "twin — union membership alone is not sufficient for a public "
                             "page; add a `[public]` twin bullet directly above it, or "
                             "remove the claim")
            else:
                row["why"] = ("prints a claim with no per-claim [public] marking — union "
                             "membership alone is not sufficient for a public page; mark it "
                             "`[public]` (nest the original wording as `[private]` beneath "
                             "it when the two differ), or remove the claim")
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
    if visibility == "public":
        # public #59, closed for this row: every printed claim traces to the union AND every
        # one of them carries its own `[public]` review stamp — a stronger claim than the
        # 0.37.1 stopgap below.
        row["why"] = ("stamped %s — public-safe: every printed claim traces to the union and "
                     "carries its own [public] marking" % (rec.get("union_reconciled_on") or "?"))
    else:
        # ⚠️ the 0.37.1 stopgap's own limit, still true for a PRIVATE-surface row: this module
        # proves provenance, not audience fitness — but a private-surface variant never claims
        # public fitness in the first place, so there is nothing left unchecked that this
        # row's own visibility promises.
        row["why"] = ("stamped %s — provenance only (surface %r, private)"
                     % (rec.get("union_reconciled_on") or "?", surface))
    return row


def uncovered_applications(root, active_ids):
    """Submitted applications with no resume_variant, while active variants exist.

    ⭐ ADR-031 B2: delegates to `applications.uncovered()` — the top-level `applications`
    store's own module, never a nested array walk here any more (public #70's own validator
    rule, validate_data.py, now enforces the hard version of this same question; this stays
    the soft/advisory report's feed)."""
    return _apps.uncovered(root, active_ids)


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
    union_tag_by_text, union_twin_of_private = union_claim_tags(union_text)
    for btext, word in suspected_tag_typos(union_text):
        out["problems"].append(
            "%s: bullet %r carries %r — close to \"public\"/\"private\" but not a recognized "
            "tag (edit distance <= 2); fix the spelling, or it is read as UNTAGGED — blocked "
            "from every public surface, never silently printed" % (UNION_FILE, btext, word))

    active_bullets = set()
    for rec in rows:
        row = check_variant(root, rec, union_text, union_norm, union_bullet_set,
                           union_tag_by_text, union_twin_of_private)
        out["variants"].append(row)
        if row["state"] in ("ok", "stale", "drifted", "private-on-public") and rec.get("file"):
            try:
                with open(os.path.join(root, rec["file"]), encoding="utf-8") as fh:
                    active_bullets |= {b for b, _ in bullets_with_sections(fh.read())}
            except OSError:
                pass

    # The observed failure in reverse: a union claim outside the addenda printed NOWHERE.
    # Flagged, never failing — a claim may legitimately rest between page redesigns.
    if any(r["state"] in ("ok", "stale", "drifted", "private-on-public")
          for r in out["variants"]):
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
                    help="exit 1 on drifted/no-claims/unstamped/missing-file/unreadable/"
                         "unplaced/private-on-public or a broken store; stale and orphans "
                         "are flagged, never failing")
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
            # public #59 — "ok" alone reads as one verdict for two different guarantees;
            # the display label says which without changing the machine state any reader
            # (presence_set.py, generate_dashboard.py, the tests) compares against.
            label = r["state"]
            if r["state"] == "ok":
                label = "ok (public-safe)" if r.get("visibility") == "public" \
                       else "ok (provenance only)"
            print("  %s %-19s %-14s archetype=%-14s %s"
                  % (mark, label, str(r["id"]), str(r["archetype"]), str(r["file"])))
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
