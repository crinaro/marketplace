#!/usr/bin/env python3
"""The presence WORKING SET — the second always-published STATE artifact (ADR-028, public #62).

⭐ THE DEFECT THIS CLOSES. The engine published one artifact — the dashboard — and nothing for
`presence/`: the claim union, every declared resume variant, the standing rules. That layer
could only be reviewed by reading markdown, and a person cannot see what a printed page looks
like from its source. Reviewing a page by reading its source is exactly how a formatting defect
ships: three consecutive role lines with no blank line between them read fine in the file and
merge into one paragraph in whatever renders them. The owner assembled this review by hand for
weeks; this makes it a query.

⭐ A SECOND DEFECT THIS CLOSES (public #77). `n_active` — the count behind the union title,
the tab label, and the header — used to be `len(panes that rendered)`, so a profile with three
declared variants that all failed to render (a bad path, a retired status, a broken row) was
told by its OWN presence page "No variants are declared." The store's declaration and the
page's claim about that declaration must never disagree: `n_active` now counts DECLARED
variants (status != "retired", classify_variants() below), whether they render or not — the
same definition `generate_dashboard._variant_staleness()` already used (public #74). And a
variant that cannot render gets a tab anyway, carrying a notice that names exactly why
(retired, file missing, file unreadable, no file declared, or an unreadable row) — visible
where the reader is already looking, not only summarized on the Open items tab.

## What it writes (every run, unconditionally — including on a profile with ZERO variants)

    views/presence_set.html          the page: one tab per declared variant — its source, or
                                     the reason it has none — an open-items tab, a rules tab
    views/presence_set_ledger.json   what each pane was generated FROM (source path + sha256),
                                     the derived open items, the category vocabulary — verified
                                     AGAINST the page by --check, never trusted alone
    views/presence_set_url.txt       written by the SESSION on first publish (the Artifact tool
                                     is model-invoked; no script can publish) — same contract as
                                     views/dashboard_artifact_url.txt

Publication is not conditional on anything. That invariant is what keeps this outside ADR-020's
failure: the collapse removed pages whose EXISTENCE depended on the data; this page exists on a
zero-variant profile exactly as it does on five.

## The seven rules (ADR-028), each a decision this file is built to keep

1. A PANE CONTAINS ITS SOURCE AND NOTHING ELSE. STATE never carries narrative (ADR-019). Counts,
   captions, placeholders and inline markers live in the STRIP above the pane's border or on the
   open-items tab — never inside `<div class="pane">`.
2. RULES AND OPEN ITEMS ARE SEPARATE TABS. A decision parked among open items is re-litigated
   every session; an open item filed among the rules never gets done.
3. EVERY PANE IS GENERATED FROM ITS SOURCE FILE. The ledger records the sha256 of the bytes each
   pane was rendered from, and `--check` recomputes it: a hand-assembled pane, or one whose
   source moved on, fails.
4. A CATEGORY LEGEND IS RENDERED AS GROUPING. Open items sit under the category vocabulary
   (CATEGORIES below, enum order); an empty category is NAMED as empty, never omitted.
5. RESOLVED ITEMS LEAVE THE ARTIFACT. Every open item here is DERIVED — it exists exactly while
   its condition holds — so nothing can be "done" on the page. `--check` re-derives and fails on
   any item the page carries that the sources no longer produce.
6. A SURFACE WITH A HARD LIMIT IS MEASURED AGAINST IT, and the number shown — in the strip.
   Step 1 declares the `print` surface only (surfaces.py), which has no cap; the strip says so.
7. THE RENDERER IS PARAGRAPH-FAITHFUL — CommonMark, both directions: adjacent non-blank lines
   join with a SPACE into one paragraph (a real renderer merges them, so the merge is VISIBLE in
   the preview instead of hidden), and a blank line ENDS a paragraph (never joined). This is a
   check, not a normaliser: a multi-line paragraph is reported as an open item under
   `paragraph`, because the file cannot say whether it is an editor wrap or missing blank
   lines, and the renderer refuses to guess. `generate_dashboard.render_md_doc` joins with
   `<br>` — the defect, live in shipped code; deliberately not reused.

## The union tab's title answers public #60

With no active variants the union IS the resume the owner sends, and the tab says so in plain
words. With variants it is the superset nobody sends, and the tab says THAT. The filename stays
`presence/claims.md` either way (ADR-018); the title is where the meaning lives.

## The round-trip check (`--check`) — grep the OUTPUT, mechanised

The first PREVIEW_CHARS characters of every source paragraph, heading, item and quote must
appear in the page's tag-stripped text, inside the pane that claims that source. A preview that
renders is not a preview that is correct. Exit 1 on: a pane whose ledger sha does not match its
source or the page; a retired variant with a rendered CONTENT pane; a derived item the page
shows that no longer derives (a resolved item still rendered); a category not named; a probe
that does not round-trip; the union title not matching the store's variant state; a variant
DECLARED in data/resume_variants.jsonl with no tab at all, rendered or absent (checked
straight against that file, never through a rebuild that could reproduce the same drop —
public #77); an absent tab whose stated cause no longer matches the store.

Reads: presence/claims.md (`_tree.py` key `claims`), presence/rules.md (`presence_rules`),
data/resume_variants.jsonl via resume_variants.py (states, violations, stamps), surfaces.py.
Writes: views/ only. Never the sources.

Usage:
    python3 scripts/presence_set.py            # generate the page + ledger
    python3 scripts/presence_set.py --check    # round-trip the generated page against its sources
    python3 scripts/presence_set.py --json     # the ledger, to stdout, without writing

Python 3.9+. Standard library only.
"""

import argparse
import datetime
import hashlib
import html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _root import profile_root as _profile_root
import _tree
import surfaces as _surf
import resume_variants as _rv

PAGE_KEY, LEDGER_KEY, URL_KEY = "presence_set", "presence_set_ledger", "presence_set_url"
LEDGER_SCHEMA = 2   # 2: variants.active is DECLARED (not rendered); variants.absent replaces
                    # variants.unrenderable and names every drop cause, retired included
PREVIEW_CHARS = 40

# ⭐ THE CATEGORY VOCABULARY — enum order is render order, and every name renders even when
# empty (rule 4). Step 1 derives rows for the first three; `limit` and `question` are declared
# now so the legend is stable across steps: `limit` fills when a surface with a cap exists
# (step 3, surfaces.py), `question` when asks can be filed against a presence file (step 2).
CATEGORIES = (
    ("paragraph", "Paragraph drift",
     "adjacent source lines that render as ONE paragraph (rule 7) — an editor wrap, or blank "
     "lines the file is missing; the file has to say which"),
    ("containment", "Containment",
     "a variant bullet absent from the claim union — `drifted` in resume_variants.py"),
    ("reconcile", "Reconcile",
     "the union changed since the variant's last stamp — `stale` in resume_variants.py"),
    ("limit", "Surface limit",
     "a field measured over its surface's character cap (rule 6) — no declared surface "
     "carries a cap yet (surfaces.py)"),
    ("question", "Open question",
     "an ask filed against a presence file — arrives when asks carry a presence target"),
)
CATEGORY_NAMES = tuple(c[0] for c in CATEGORIES)

# ── the block parser (rule 7) ─────────────────────────────────────────────────────────────

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
BULLET_RE = re.compile(r"^(\s*)([-*+])\s+(.*)$")
ORDERED_RE = re.compile(r"^(\s*)(\d{1,9})[.)]\s+(.*)$")
RULE_RE = re.compile(r"^\s{0,3}((\*\s*){3,}|(-\s*){3,}|(_\s*){3,})$")
FENCE_RE = re.compile(r"^\s{0,3}(```|~~~)")


def _is_block_start(s):
    """Can this line interrupt a paragraph? (CommonMark: heading, fence, rule, bullet,
    blockquote, table row. A bare number list also interrupts here — the one CommonMark
    exception, `2.` not interrupting, is not worth a wrong merge in a resume.)"""
    return bool(HEADING_RE.match(s) or FENCE_RE.match(s) or RULE_RE.match(s)
                or BULLET_RE.match(s) or ORDERED_RE.match(s)
                or s.lstrip().startswith(">") or s.lstrip().startswith("|"))


def _hard_break(raw):
    """CommonMark hard line break: two or more trailing spaces, or a trailing backslash."""
    return raw.endswith("  ") or raw.endswith("\\")


def parse_blocks(md):
    """[(block dict)] — kinds: heading, para, list, quote, rule, code, table. Line numbers
    are 1-based and inclusive so a finding can name where in the file it sits."""
    lines = md.splitlines()
    blocks, i, n = [], 0, len(lines)
    while i < n:
        raw = lines[i]
        s = raw.strip()
        if not s:
            i += 1
            continue
        start = i + 1
        fm = FENCE_RE.match(raw)
        if fm:
            fence, body = fm.group(1), []
            i += 1
            while i < n and not lines[i].strip().startswith(fence):
                body.append(lines[i])
                i += 1
            i += 1                                    # the closing fence (or EOF)
            blocks.append({"kind": "code", "lines": body, "start": start, "end": i})
            continue
        hm = HEADING_RE.match(s)
        if hm:
            blocks.append({"kind": "heading", "level": len(hm.group(1)), "text": hm.group(2),
                           "start": start, "end": start})
            i += 1
            continue
        if RULE_RE.match(raw):
            blocks.append({"kind": "rule", "start": start, "end": start})
            i += 1
            continue
        if s.startswith(">"):
            paras, cur = [], []
            while i < n and lines[i].strip().startswith(">"):
                t = lines[i].strip()[1:].strip()
                if t:
                    cur.append((t, _hard_break(lines[i].rstrip("\n"))))
                elif cur:
                    paras.append(cur)
                    cur = []
                i += 1
            if cur:
                paras.append(cur)
            blocks.append({"kind": "quote", "paras": paras, "start": start, "end": i})
            continue
        if s.startswith("|"):
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.match(r"^:?-{2,}:?$", c) for c in cells if c):
                    rows.append(cells)
                i += 1
            blocks.append({"kind": "table", "rows": rows, "start": start, "end": i})
            continue
        bm = BULLET_RE.match(raw) or ORDERED_RE.match(raw)
        if bm:
            items = []
            while i < n:
                raw = lines[i]
                if not raw.strip():
                    # a blank line ends the list unless the next non-blank line is an item
                    j = i + 1
                    while j < n and not lines[j].strip():
                        j += 1
                    if j < n and (BULLET_RE.match(lines[j]) or ORDERED_RE.match(lines[j])):
                        i = j
                        continue
                    break
                m = BULLET_RE.match(raw) or ORDERED_RE.match(raw)
                if m:
                    items.append({"indent": len(m.group(1).expandtabs(4)),
                                  "ordered": m.group(2)[0].isdigit(),
                                  "lines": [(m.group(3).strip(), _hard_break(raw))],
                                  "start": i + 1, "end": i + 1})
                    i += 1
                    continue
                if _is_block_start(raw) and not raw.startswith((" ", "\t")):
                    break
                # lazy continuation: a non-blank, non-item line belongs to the open item —
                # this is the merge a real renderer performs, kept visible on purpose
                items[-1]["lines"].append((raw.strip(), _hard_break(raw)))
                items[-1]["end"] = i + 1
                i += 1
            blocks.append({"kind": "list", "items": items, "start": start, "end": i})
            continue
        # a paragraph: consecutive non-blank lines nothing else claims
        plines = []
        while i < n and lines[i].strip() and not (_is_block_start(lines[i]) and plines):
            plines.append((lines[i].strip(), _hard_break(lines[i])))
            i += 1
        blocks.append({"kind": "para", "lines": plines, "start": start, "end": i})
    return blocks


# ── inline ─────────────────────────────────────────────────────────────────────────────────

def esc(s):
    return html.escape(s, quote=False)


_STRONG_RE = re.compile(r"\*\*(.+?)\*\*")
_EM_RE = re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])|(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)")
_CODE_RE = re.compile(r"`([^`]+)`")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")


def md_inline(s):
    """Escape, then `code`, **strong**, *em*, [text](target). A local target renders as a
    filename chip: a published artifact has no useful href for a profile-relative path."""
    s = esc(s)
    s = _CODE_RE.sub(lambda m: "<code>%s</code>" % m.group(1), s)
    s = _STRONG_RE.sub(lambda m: "<strong>%s</strong>" % m.group(1), s)
    s = _EM_RE.sub(lambda m: "<em>%s</em>" % (m.group(1) or m.group(2)), s)

    def _link(m):
        text, target = m.group(1), m.group(2)
        if target.startswith(("http://", "https://")):
            return ('<a href="%s" target="_blank" rel="noopener noreferrer">%s</a>'
                    % (target, text))
        return '<code class="fileref">%s</code>' % text
    return _LINK_RE.sub(_link, s)


def plain_inline(s):
    """The TEXT a reader sees for an inline-marked source line — what the round trip
    compares against the tag-stripped page (rule 7's check needs the same reading the
    renderer gives, minus the tags)."""
    s = _CODE_RE.sub(lambda m: m.group(1), s)
    s = _STRONG_RE.sub(lambda m: m.group(1), s)
    s = _EM_RE.sub(lambda m: (m.group(1) or m.group(2)), s)
    s = _LINK_RE.sub(lambda m: m.group(1), s)
    return s


def _norm(s):
    return " ".join((s or "").split())


def _join(pairs, plain=False):
    """One paragraph from its source lines: a soft break is a SPACE, a hard break a <br>."""
    out = []
    for k, (text, hard) in enumerate(pairs):
        piece = plain_inline(text) if plain else md_inline(text)
        if k < len(pairs) - 1:
            piece += (" " if plain else ("<br>" if hard else " "))
        out.append(piece)
    return "".join(out)


# ── render + probes + derived rows ──────────────────────────────────────────────────────────

def _render_list(items):
    out, stack = [], []                       # stack: [(indent, tag)]
    for it in items:
        while stack and it["indent"] < stack[-1][0]:
            out.append("</li></%s>" % stack.pop()[1])
        if not stack or it["indent"] > stack[-1][0]:
            tag = "ol" if it["ordered"] else "ul"
            out.append("<%s>" % tag)
            stack.append((it["indent"], tag))
        else:
            out.append("</li>")
        out.append("<li>" + _join(it["lines"]))
    while stack:
        out.append("</li></%s>" % stack.pop()[1])
    return "".join(out)


def render_blocks(blocks):
    out = []
    for b in blocks:
        k = b["kind"]
        if k == "heading":
            out.append('<h%d class="ph">%s</h%d>' % (b["level"], md_inline(b["text"]),
                                                     b["level"]))
        elif k == "para":
            out.append("<p>%s</p>" % _join(b["lines"]))
        elif k == "list":
            out.append(_render_list(b["items"]))
        elif k == "quote":
            out.append("<blockquote>%s</blockquote>"
                       % "".join("<p>%s</p>" % _join(p) for p in b["paras"]))
        elif k == "rule":
            out.append("<hr>")
        elif k == "code":
            out.append("<pre>%s</pre>" % esc("\n".join(b["lines"])))
        elif k == "table":
            rows = b["rows"]
            if rows:
                head = "".join("<th>%s</th>" % md_inline(c) for c in rows[0])
                body = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % md_inline(c)
                                                       for c in r) for r in rows[1:])
                out.append("<table><tr>%s</tr>%s</table>" % (head, body))
    return "\n".join(out)


def probes(blocks):
    """[(text, start_line)] — every unit of text the page must carry, as a reader sees it."""
    out = []
    for b in blocks:
        k = b["kind"]
        if k == "heading":
            out.append((_norm(plain_inline(b["text"])), b["start"]))
        elif k == "para":
            out.append((_norm(_join(b["lines"], plain=True)), b["start"]))
        elif k == "list":
            for it in b["items"]:
                out.append((_norm(_join(it["lines"], plain=True)), it["start"]))
        elif k == "quote":
            for p in b["paras"]:
                out.append((_norm(_join(p, plain=True)), b["start"]))
        elif k == "code":
            for off, l in enumerate(b["lines"]):
                if l.strip():
                    out.append((_norm(l), b["start"] + 1 + off))
        elif k == "table":
            for r in b["rows"]:
                out.append((_norm(" ".join(plain_inline(c) for c in r)), b["start"]))
    return [(t, ln) for t, ln in out if t]


def paragraph_rows(blocks, rel):
    """Rule 7's derived rows: every paragraph or list item assembled from MORE THAN ONE source
    line by a soft break. Reported, never normalised — the file cannot say whether it is an
    editor wrap or missing blank lines, so the row asks the owner to decide IN THE FILE."""
    rows = []

    def _row(pairs, start, end, what):
        soft = sum(1 for _t, hard in pairs[:-1] if not hard)
        if len(pairs) > 1 and soft:
            preview = _norm(_join(pairs, plain=True))[:70]
            rows.append({
                "category": "paragraph",
                "key": "paragraph:%s:%d" % (rel, start),
                "where": "%s lines %d-%d" % (rel, start, end),
                "text": "%d source lines render as one %s: “%s…” — an editor "
                        "wrap, or blank lines the file is missing? The file has to say: "
                        "keep it (intended), or separate the lines with a blank line."
                        % (len(pairs), what, preview),
            })

    for b in blocks:
        if b["kind"] == "para":
            _row(b["lines"], b["start"], b["end"], "paragraph")
        elif b["kind"] == "list":
            for it in b["items"]:
                _row(it["lines"], it["start"], it["end"], "list item")
    return rows


# ── sources ────────────────────────────────────────────────────────────────────────────────

def sha_of(path):
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


def read_source(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def _rel(root, path):
    return os.path.relpath(path, root).replace(os.sep, "/")


def variant_key(rec, i):
    """The tab id a declared row renders under. A row missing its own `id` still gets a
    tab — public report: three declared variants rendered NOTHING, and a row lacking `id`
    is exactly the sort of row that used to vanish first. Position makes it nameable anyway."""
    vid = rec.get("id")
    return str(vid) if vid else "row%d" % (i + 1)


def classify_variants(root, rep, rows):
    """[dict] — one entry per row in `rows`, POSITIONALLY paired with `rep["variants"]`
    (both are `check_variant()` over the same list, in the same order — not an `id`-keyed
    lookup, which mishandles the very rows this exists to name: two rows sharing an id, or
    lacking one, collide or vanish under a dict keyed by `id`).

    Every row gets an entry. `renders` is True for a row that gets a content pane; when it
    is False, `cause`/`cause_label`/`why` say EXACTLY why — never a generic "cannot render"
    (public report). The causes:

        retired         terminal (rule 5) — the row's status says so
        file-missing    `file` names a path that does not exist under the profile root
        file-unreadable `file` names a path that EXISTS but could not be read as UTF-8
                        (permissions, encoding) — distinct from file-missing on purpose
        no-file         the row has no `file` at all — nothing was ever declared to read
        no-id           the row has no `id` — unnamed, unselectable
        unreadable      resume_variants.py marked the row unusable for a reason not covered
                        above; its own `why` is carried verbatim rather than guessed at
    """
    reps = rep.get("variants") or []
    out = []
    for i, rec in enumerate(rows):
        rr = reps[i] if i < len(reps) else {}
        vid = variant_key(rec, i)
        label = str(rec["id"]) if rec.get("id") else "(unnamed variant %d)" % (i + 1)
        state = rr.get("state")
        cause = cause_label = why = None
        if state == "retired":
            cause, cause_label = "retired", "Retired"
            why = rr.get("why") or "terminal — history stays resolvable, no claim checks"
        elif state == "missing-file":
            fpath = os.path.join(root, rec.get("file") or "")
            if rec.get("file") and os.path.exists(fpath):
                cause, cause_label = "file-unreadable", "File unreadable"
                why = ("%r exists under the profile root but could not be read as UTF-8 "
                       "text (permissions, or an encoding this reader does not handle) — "
                       "fix the file, then regenerate." % rec["file"])
            else:
                cause, cause_label = "file-missing", "File missing"
                why = rr.get("why") or ("%r does not exist under the profile root"
                                        % rec.get("file"))
        elif state == "unreadable":
            if not rec.get("id"):
                cause, cause_label = "no-id", "No id declared"
                why = ("this row in %s has no id — it cannot be named, selected, or "
                       "reconciled; give it one." % _rv.STORE_FILE)
            elif not rec.get("file"):
                cause, cause_label = "no-file", "No file declared"
                why = ("%s declares %r with no file — there is nothing to read; add a "
                       "file path or retire the row." % (_rv.STORE_FILE, rec["id"]))
            else:
                cause, cause_label = "unreadable", "Unreadable"
                why = rr.get("why") or "row lacks id/file — validate_data.py has the details"
        out.append({"vid": vid, "label": label, "rec": rec, "rr": rr,
                    "renders": cause is None, "cause": cause, "cause_label": cause_label,
                    "why": why})
    return out


def derive_open_items(root, rep, panes_blocks):
    """Every derived open item, grouped by CATEGORY_NAMES (enum order). `panes_blocks` is
    {rel: blocks} for the union and each rendered variant — the rules file is prose, not a
    page anyone sends, so its paragraphs are not measured."""
    items = {c: [] for c in CATEGORY_NAMES}
    for rel, blocks in panes_blocks.items():
        items["paragraph"].extend(paragraph_rows(blocks, rel))
    for r in rep["variants"]:
        if r["state"] == "drifted":
            for k, v in enumerate(r["violations"]):
                items["containment"].append({
                    "category": "containment", "key": "containment:%s:%d" % (r["id"], k),
                    "where": "%s (%s)" % (r["id"], r.get("file") or "?"),
                    "text": "bullet not found in %s: “%s” — land it in the union "
                            "first, then reconcile and `resume_variants.py --stamp %s`"
                            % (_rv.UNION_FILE, v[:120], r["id"])})
        elif r["state"] == "stale":
            items["reconcile"].append({
                "category": "reconcile", "key": "reconcile:%s" % r["id"],
                "where": "%s (%s)" % (r["id"], r.get("file") or "?"),
                "text": r["why"]})
    return items


# ── the page ───────────────────────────────────────────────────────────────────────────────

CSS = """
  :root { color-scheme: light dark;
    --bg:#f7f7f5; --fg:#1a1a1a; --muted:#777; --muted2:#666; --card-bg:#fff; --card-border:#e4e2dd;
    --divider:#f0efeb; --strip-bg:#eef4fb; --strip-border:#d5e4f5; --strip-fg:#2c5580;
    --tab-active:#1a1a1a; --tab-active-fg:#fff; --empty:#8a8a86; --warn-bg:#fef3cd; --warn-fg:#8a6d00; }
  @media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
    --bg:#17181a; --fg:#ececeb; --muted:#9a9a97; --muted2:#a8a8a5; --card-bg:#201f1f; --card-border:#34322f;
    --divider:#2b2a28; --strip-bg:#172433; --strip-border:#253a52; --strip-fg:#8fbaea;
    --tab-active:#ececeb; --tab-active-fg:#17181a; --empty:#767674; --warn-bg:#3d3210; --warn-fg:#f0c750; } }
  :root[data-theme="dark"] {
    --bg:#17181a; --fg:#ececeb; --muted:#9a9a97; --muted2:#a8a8a5; --card-bg:#201f1f; --card-border:#34322f;
    --divider:#2b2a28; --strip-bg:#172433; --strip-border:#253a52; --strip-fg:#8fbaea;
    --tab-active:#ececeb; --tab-active-fg:#17181a; --empty:#767674; --warn-bg:#3d3210; --warn-fg:#f0c750; }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: var(--bg);
         color: var(--fg); padding: 20px; font-size: 14px; margin: 0; }
  h1 { font-size: 20px; margin: 0 0 2px; }
  .updated { color: var(--muted); font-size: 12px; margin-bottom: 16px; }
  .tabs { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 14px; }
  .tabs label { cursor: pointer; padding: 6px 12px; border-radius: 8px; border: 1px solid var(--card-border);
                background: var(--card-bg); font-size: 13px; font-weight: 600; }
  input.tab { position: absolute; opacity: 0; pointer-events: none; }
  .tabpage { display: none; }
  .strip { background: var(--strip-bg); border: 1px solid var(--strip-border); color: var(--strip-fg);
           border-radius: 8px; padding: 10px 14px; font-size: 12.5px; margin-bottom: 10px; }
  .strip h2 { font-size: 15px; margin: 0 0 4px; color: var(--fg); }
  .strip .warn { background: var(--warn-bg); color: var(--warn-fg); border-radius: 6px; padding: 2px 8px;
                 font-weight: 600; }
  .pane { background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 10px;
          padding: 22px 26px; line-height: 1.45; overflow-x: auto; }
  .pane:empty { min-height: 40px; }
  .pane h1, .pane h2, .pane h3, .pane h4, .pane h5, .pane h6 { margin: 18px 0 6px; line-height: 1.25; }
  .pane h1 { font-size: 22px; } .pane h2 { font-size: 17px; } .pane h3 { font-size: 15px; }
  .pane p { margin: 0 0 10px; } .pane ul, .pane ol { margin: 0 0 10px; padding-left: 22px; }
  .pane li { margin: 2px 0; } .pane blockquote { border-left: 3px solid var(--card-border); margin: 0 0 10px;
             padding: 2px 12px; color: var(--muted2); }
  .pane pre { background: var(--divider); padding: 10px; border-radius: 6px; overflow-x: auto; }
  .pane table { border-collapse: collapse; margin: 0 0 10px; } .pane th, .pane td { border: 1px solid var(--card-border);
             padding: 4px 8px; text-align: left; vertical-align: top; }
  .pane hr { border: 0; border-top: 1px solid var(--card-border); margin: 14px 0; }
  .absent-pane { color: var(--empty); font-style: italic; font-size: 13px; padding: 18px 4px; }
  .strip .why { margin-top: 4px; }
  code { font-size: 12.5px; } code.fileref { background: var(--divider); border-radius: 4px; padding: 0 4px; }
  .cat { background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 10px;
         padding: 12px 16px; margin-bottom: 10px; }
  .cat h3 { font-size: 13px; margin: 0 0 2px; text-transform: uppercase; letter-spacing: .04em; }
  .cat .why { color: var(--muted2); font-size: 12px; margin-bottom: 8px; }
  .cat .none { color: var(--empty); font-style: italic; font-size: 13px; }
  .cat ul { margin: 0; padding-left: 20px; } .cat li { margin: 4px 0; }
  .cat .where { color: var(--muted2); font-size: 12px; }
  .foot { color: var(--muted); font-size: 12px; margin-top: 26px; }
"""


def _title(root):
    name = ""
    try:
        with open(os.path.join(root, "user.json"), encoding="utf-8") as fh:
            name = ((json.load(fh).get("identity") or {}).get("full_name") or "").strip()
    except Exception:
        pass
    return ("%s — Presence" % name) if name else "Presence"


def _pane(key, rel, sha, inner):
    """The pane: its source and nothing else (rule 1). The closing comment is the extraction
    anchor `--check` uses — nested markup can never confuse the boundary."""
    return ('<div class="pane" data-pane="%s" data-source="%s" data-sha="%s">%s<!--/pane--></div>'
            % (esc(key), esc(rel), sha or "", inner))


def union_title(n_active):
    """Public #60's answer: what THIS FILE IS, said plainly on every visit, in both cases."""
    if n_active == 0:
        return ("sent", "Your resume",
                "%s is the page you send. No variants are declared, so the claim union is the "
                "one printed resume (ADR-018’s single-resume case) — what renders "
                "below is what a reader gets." % _rv.UNION_FILE)
    return ("superset", "The claim union — not sent as-is",
            "%s is the superset the %d declared variant%s select from. It is not the page you "
            "send; the pages you send are the variant tabs, and every bullet on them must "
            "trace back here." % (_rv.UNION_FILE, n_active, "" if n_active == 1 else "s"))


def build(root, today=None):
    """(page_html, ledger) — pure: reads sources, writes nothing."""
    today = today or datetime.date.today()
    rep = _rv.report(root)
    rows, _errs, present = _rv.load_store(root)
    vrows = classify_variants(root, rep, rows)
    # ⭐ public report: `n_active` used to count PANES THAT RENDERED, so a profile whose
    # declared variants all failed to render was told the store had none — a claim the store
    # never made. `active` here is DECLARED (status != "retired"), the same definition
    # generate_dashboard._variant_staleness() already uses (public #74's fix), so the two
    # surfaces cannot disagree about how many variants exist.
    n_active = sum(1 for vr in vrows if vr["rec"].get("status") != "retired")
    absent = [vr for vr in vrows if not vr["renders"]]
    retired = sorted(vr["vid"] for vr in vrows if vr["cause"] == "retired")

    panes, ledger_panes, panes_blocks = [], [], {}
    tabs = []                                                 # (key, label)

    # ── union ──
    upath = _tree.path(root, "claims")
    urel = _rel(root, upath)
    utext = read_source(upath)
    mode, utitle, usub = union_title(n_active)
    ublocks = parse_blocks(utext or "")
    panes_blocks[urel] = ublocks
    strip = ('<div class="strip" data-union-mode="%s"><h2>%s</h2>%s%s</div>'
             % (mode, esc(utitle), esc(usub),
                "" if utext is not None else
                ' <span class="warn">%s does not exist — nothing to render</span>' % esc(urel)))
    panes.append(('union', strip, _pane("union", urel, sha_of(upath), render_blocks(ublocks))))
    ledger_panes.append({"key": "union", "label": utitle, "source": urel,
                         "sha256": sha_of(upath), "exists": utext is not None,
                         "blocks": len(ublocks), "probes": len(probes(ublocks))})
    tabs.append(("union", "Union" if n_active else "Resume"))

    # ── one tab per DECLARED variant, retired included. A row that renders gets its source
    # (rule 1); a row that cannot gets a notice naming exactly why — public report: a drop
    # must never be silent, and never visible only on the Open items tab ──
    for vr in vrows:
        rec, rr, vid = vr["rec"], vr["rr"], vr["vid"]
        key = "variant:%s" % vid
        if vr["renders"]:
            vpath = os.path.join(root, rec["file"])
            vrel = _rel(root, vpath)
            vtext = read_source(vpath) or ""
            vblocks = parse_blocks(vtext)
            panes_blocks[vrel] = vblocks
            surface = _surf.DEFAULT_SURFACE
            state = rr.get("state", "?")
            stamped = rec.get("union_reconciled_on") or "never"
            strip = ('<div class="strip"><h2>%s</h2>archetype: %s · source: <code>%s</code> '
                     '· surface: %s · containment: %s · reconciled: %s</div>'
                     % (esc(vid), esc(str(rec.get("archetype") or "?")), esc(vrel),
                        esc(_surf.describe(surface)),
                        ('<span class="warn">%s</span>' % esc(state)) if state in ("drifted", "stale")
                        else esc(state), esc(stamped)))
            panes.append((key, strip, _pane(key, vrel, sha_of(vpath), render_blocks(vblocks))))
            ledger_panes.append({"key": key, "label": vr["label"], "source": vrel,
                                 "sha256": sha_of(vpath), "exists": True, "surface": surface,
                                 "state": state, "blocks": len(vblocks),
                                 "probes": len(probes(vblocks))})
            tabs.append((key, vr["label"]))
        else:
            icon = "🪦" if vr["cause"] == "retired" else "⛔"
            strip = ('<div class="strip" data-variant-id="%s" data-variant-absent="%s">'
                     '<h2>%s — %s</h2>archetype: %s · source: <code>%s</code>'
                     '<div class="why">%s</div></div>'
                     % (esc(vid), esc(vr["cause"]), esc(vr["label"]), esc(vr["cause_label"]),
                        esc(str(rec.get("archetype") or "?")),
                        esc(rec.get("file") or "(none declared)"), esc(vr["why"])))
            body = ('<div class="absent-pane">No content renders on this tab — the notice '
                    'above says why, and what to do.</div>')
            panes.append((key, strip, body))
            tabs.append((key, "%s %s" % (icon, vr["label"])))

    # ── open items (rule 4: grouped, empty categories named; rule 5: derived only) ──
    items = derive_open_items(root, rep, panes_blocks)
    n_items = sum(len(v) for v in items.values())
    cats = []
    for name, label, why in CATEGORIES:
        rows_html = "".join(
            '<li data-item="%s"><span class="where">%s</span> — %s</li>'
            % (esc(it["key"]), esc(it["where"]), esc(it["text"])) for it in items[name])
        body = ("<ul>%s</ul>" % rows_html) if items[name] else \
            '<div class="none">none open</div>'
        cats.append('<section class="cat" data-category="%s" data-count="%d"><h3>%s</h3>'
                    '<div class="why">%s</div>%s</section>'
                    % (name, len(items[name]), esc(label), esc(why), body))
    ostrip = ('<div class="strip"><h2>Open items</h2>%d open, derived from the sources on every '
              'run — an item leaves this tab the moment its condition no longer holds; '
              'nothing here is ever marked done.%s</div>'
              % (n_items,
                 (' <span class="warn">%d variant %s why %s cannot render — %s</span>'
                  % (len(absent), "tab shows" if len(absent) == 1 else "tabs show",
                     "it" if len(absent) == 1 else "they",
                     esc(", ".join("%s (%s)" % (a["vid"], a["cause_label"])
                                   for a in absent))))
                 if absent else ""))
    panes.append(("items", ostrip, "\n".join(cats)))
    tabs.append(("items", "Open items (%d)" % n_items))

    # ── rules ──
    rpath = _tree.path(root, "presence_rules")
    rrel = _rel(root, rpath)
    rtext = read_source(rpath)
    rblocks = parse_blocks(rtext or "")
    rstrip = ('<div class="strip"><h2>Standing rules</h2>settled decisions about the union and '
              'its variants, from <code>%s</code>. A decision lives here; a question lives on '
              'the open-items tab — never both.%s</div>'
              % (esc(rrel), "" if rtext is not None else
                 ' <span class="warn">%s does not exist yet — the 0.39.0 migration creates '
                 'it at the next session start</span>' % esc(rrel)))
    panes.append(("rules", rstrip, _pane("rules", rrel, sha_of(rpath), render_blocks(rblocks))))
    ledger_panes.append({"key": "rules", "label": "Standing rules", "source": rrel,
                         "sha256": sha_of(rpath), "exists": rtext is not None,
                         "blocks": len(rblocks), "probes": len(probes(rblocks))})
    tabs.append(("rules", "Rules"))

    # ── assemble: CSS-only tabs (radio inputs precede the pages they reveal) ──
    title = _title(root)
    inputs = "".join('<input class="tab" type="radio" name="tab" id="t-%s"%s>'
                     % (esc(k), " checked" if i == 0 else "") for i, (k, _l) in enumerate(tabs))
    labels = "".join('<label for="t-%s">%s</label>' % (esc(k), esc(l)) for k, l in tabs)
    tab_css = "\n".join("  #t-%s:checked ~ .panes #p-%s { display:block; }\n"
                        "  #t-%s:checked ~ .tabs label[for=\"t-%s\"] { background: var(--tab-active); "
                        "color: var(--tab-active-fg); }" % (k, k, k, k) for k, _l in tabs)
    pages = "\n".join('<div class="tabpage" id="p-%s">\n%s\n%s\n</div>' % (esc(k), strip, body)
                      for k, strip, body in panes)
    n_absent_active = sum(1 for a in absent if a["cause"] != "retired")
    doc = ('<title>%s</title>\n<style>%s\n%s\n</style>\n'
           '<h1>%s</h1>\n<div class="updated">generated %s · %d variant tab%s%s%s</div>\n'
           '%s\n<div class="tabs">%s</div>\n<div class="panes">\n%s\n</div>\n'
           '<div class="foot">Each pane renders its source file and nothing else; the strip '
           'above it carries everything measured. Regenerate with presence_set.py; verify '
           'with presence_set.py --check (ADR-028).</div>'
           % (esc(title), CSS, tab_css, esc(title), today.isoformat(), n_active,
              "" if n_active == 1 else "s",
              (" (%d cannot render)" % n_absent_active) if n_absent_active else "",
              (" · %d retired" % len(retired)) if retired else "",
              inputs, labels, pages))
    ledger = {
        "schema": LEDGER_SCHEMA,
        "generated_on": today.isoformat(),
        "union_mode": mode,
        "variants": {
            "store_present": present,
            "active": [vr["vid"] for vr in vrows if vr["rec"].get("status") != "retired"],
            "rendered": [vr["vid"] for vr in vrows if vr["renders"]],
            "retired": retired,
            "absent": [{"id": a["vid"], "cause": a["cause"], "why": a["why"]} for a in absent],
        },
        "surfaces": {n: dict(_surf.get(n)) for n in _surf.names()},
        "categories": list(CATEGORY_NAMES),
        "panes": ledger_panes,
        "open_items": [it for name in CATEGORY_NAMES for it in items[name]],
        "_why": "what each pane was generated FROM and every derived open item — verified "
                "against the page by presence_set.py --check, never trusted alone (ADR-028)",
    }
    return doc, ledger


def write(root):
    doc, ledger = build(root)
    page = os.path.join(root, _tree.rel(PAGE_KEY))
    os.makedirs(os.path.dirname(page), exist_ok=True)
    with open(page, "w", encoding="utf-8") as fh:
        fh.write(doc)
    with open(os.path.join(root, _tree.rel(LEDGER_KEY)), "w", encoding="utf-8") as fh:
        json.dump(ledger, fh, indent=1, sort_keys=True, ensure_ascii=False)
    n = len(ledger["variants"]["active"])
    print("Wrote %s (%d bytes) and %s" % (_tree.rel(PAGE_KEY), len(doc.encode("utf-8")),
                                          _tree.rel(LEDGER_KEY)))
    print("  tabs: union (%s) · %d variant%s · open items (%d) · rules%s"
          % ("your resume" if n == 0 else "the superset", n, "" if n == 1 else "s",
             len(ledger["open_items"]),
             "" if any(p["key"] == "rules" and p["exists"] for p in ledger["panes"])
             else " (no %s yet)" % _tree.rel("presence_rules")))
    print("  publish: the SECOND artifact — %s, to the URL in %s (create it and write "
          "that url file in the same step on first publish; never mint a second URL for a "
          "page that has one). Then: presence_set.py --check, and grep the OUTPUT."
          % (_tree.rel(PAGE_KEY), _tree.rel(URL_KEY)))
    return 0


# ── the round trip ─────────────────────────────────────────────────────────────────────────

_PANE_RE = re.compile(r'<div class="pane" data-pane="([^"]*)" data-source="([^"]*)" '
                      r'data-sha="([^"]*)">(.*?)<!--/pane-->', re.S)
_ITEM_RE = re.compile(r'<li data-item="([^"]*)"')
_CAT_RE = re.compile(r'<section class="cat" data-category="([^"]*)"')
_MODE_RE = re.compile(r'data-union-mode="([^"]*)"')
_VTAB_RE = re.compile(r'<input class="tab" type="radio" name="tab" id="t-variant:([^"]*)"')
_ABSENT_RE = re.compile(r'data-variant-id="([^"]*)" data-variant-absent="([^"]*)"')


_INLINE_TAG_RE = re.compile(r"</?(?:strong|em|code|a)\b[^>]*>")


def page_text(fragment):
    """The text a reader sees: an INLINE tag vanishes (`<strong>x</strong>:` reads `x:`),
    a block tag is a boundary (a space). Stripping every tag to a space put a space between
    a bold run and its trailing punctuation and failed twelve true round trips (measured on
    a scratch copy of a real profile, first run)."""
    frag = _INLINE_TAG_RE.sub("", fragment)
    return _norm(html.unescape(re.sub(r"<[^>]+>", " ", frag)))


def check(root):
    page = os.path.join(root, _tree.rel(PAGE_KEY))
    ledger_path = os.path.join(root, _tree.rel(LEDGER_KEY))
    if not os.path.exists(page):
        print("NOT CHECKED — %s has not been generated yet (run presence_set.py)."
              % _tree.rel(PAGE_KEY))
        return 0
    try:
        with open(ledger_path, encoding="utf-8") as fh:
            ledger = json.load(fh)
    except (OSError, ValueError):
        print("⛔ ARTIFACT WITHOUT A LEDGER — %s exists but %s is missing or "
              "unreadable; regenerate (presence_set.py)." % (_tree.rel(PAGE_KEY),
                                                              _tree.rel(LEDGER_KEY)))
        return 1
    with open(page, encoding="utf-8") as fh:
        doc = fh.read()
    problems = []
    fresh_doc, fresh = build(root)                   # the sources as they are NOW

    # 1. pane set: page == ledger == what the store says today (retired: no tab; active: a tab)
    page_panes = {m.group(1): (m.group(2), m.group(3), m.group(4)) for m in _PANE_RE.finditer(doc)}
    ledger_keys = {p["key"] for p in ledger.get("panes", [])}
    fresh_keys = {p["key"] for p in fresh["panes"]}
    for k in sorted(page_panes.keys() - fresh_keys):
        if k.startswith("variant:"):
            vid = k[len("variant:"):]
            if vid in fresh["variants"]["retired"]:
                problems.append("RETIRED VARIANT STILL HAS A TAB: %s — a retired page has "
                                "left the working set (rule 5); regenerate" % vid)
                continue
        problems.append("PANE ON PAGE WITH NO CURRENT SOURCE: %s — regenerate" % k)
    for k in sorted(fresh_keys - page_panes.keys()):
        problems.append("PANE MISSING FROM PAGE: %s — an active source has no tab; "
                        "regenerate" % k)
    if ledger_keys != page_panes.keys():
        problems.append("LEDGER/PAGE DISAGREE on the pane set: ledger %s vs page %s"
                        % (sorted(ledger_keys), sorted(page_panes)))

    # 2. every pane is generated from its source (rule 3): ledger sha == page sha == source now
    fresh_by_key = {p["key"]: p for p in fresh["panes"]}
    for p in ledger.get("panes", []):
        k = p["key"]
        if k not in page_panes or k not in fresh_by_key:
            continue
        _src, page_sha, _inner = page_panes[k]
        now_sha = fresh_by_key[k]["sha256"] or ""
        if (p.get("sha256") or "") != page_sha:
            problems.append("HAND-BUILT PANE: %s — the page's sha (%s) is not the ledger's "
                            "(%s); the pane was not generated by this script (rule 3)"
                            % (k, page_sha[:12] or "none", (p.get("sha256") or "none")[:12]))
        elif (p.get("sha256") or "") != now_sha:
            problems.append("PANE STALE: %s — %s changed since generation (ledger %s, now "
                            "%s); regenerate" % (k, p.get("source"),
                                                 (p.get("sha256") or "none")[:12],
                                                 now_sha[:12] or "none"))

    # 3. the round trip (rule 7, mechanised): every probe inside the pane that claims it
    n_probes = 0
    for p in fresh["panes"]:
        k = p["key"]
        if k not in page_panes or not p["exists"]:
            continue
        text = page_text(page_panes[k][2])
        src = read_source(os.path.join(root, p["source"])) or ""
        for probe, line in probes(parse_blocks(src)):
            n_probes += 1
            if probe[:PREVIEW_CHARS] not in text:
                problems.append("ROUND TRIP: %s line %d — “%s” is in the source "
                                "and NOT in the rendered pane" % (p["source"], line,
                                                                   probe[:PREVIEW_CHARS]))
    # 3b. both directions of rule 7 on the union: a blank-separated pair must NOT merge —
    # each paragraph is its own <p>, so the page carries as many <p> in the pane as the
    # source has paragraphs (a renderer that swallowed a blank line would have fewer)
    for p in fresh["panes"]:
        k = p["key"]
        if k not in page_panes or not p["exists"]:
            continue
        src = read_source(os.path.join(root, p["source"])) or ""
        n_para = sum(1 for b in parse_blocks(src) if b["kind"] == "para")
        n_p = len(re.findall(r"<p>", re.sub(r"<blockquote>.*?</blockquote>", "",
                                            page_panes[k][2], flags=re.S)))
        if n_p != n_para:
            problems.append("PARAGRAPH COUNT: %s renders %d paragraph(s) for %d in the source "
                            "— a blank line was swallowed or invented (rule 7)"
                            % (p["source"], n_p, n_para))

    # 4. open items: derived only (rule 5) — the page shows exactly what derives now
    page_items = set(_ITEM_RE.findall(doc))
    fresh_items = {it["key"] for it in fresh["open_items"]}
    for k in sorted(page_items - fresh_items):
        problems.append("RESOLVED ITEM STILL RENDERED: %s — its condition no longer holds; "
                        "an item leaves the artifact, it is never marked done (rule 5)" % k)
    for k in sorted(fresh_items - page_items):
        problems.append("OPEN ITEM MISSING FROM PAGE: %s — regenerate" % k)

    # 5. every category is named, even when empty (rule 4)
    page_cats = _CAT_RE.findall(doc)
    for c in CATEGORY_NAMES:
        if c not in page_cats:
            problems.append("CATEGORY NOT NAMED: %s — an empty category is stated, never "
                            "omitted (rule 4)" % c)
    if page_cats != [c for c in CATEGORY_NAMES if c in page_cats]:
        problems.append("CATEGORIES OUT OF ENUM ORDER: %s" % page_cats)

    # 6. the union title states what the file IS today (public #60)
    mm = _MODE_RE.search(doc)
    if not mm or mm.group(1) != fresh["union_mode"]:
        problems.append("UNION TITLE WRONG: page says %r, the store says %r (%d active "
                        "variant(s)) — regenerate"
                        % (mm.group(1) if mm else None, fresh["union_mode"],
                           len(fresh["variants"]["active"])))

    # 7. every declared row has SOME tab — measured straight from the store, never through
    # `fresh` (which is `build(root)` again): a future defect that makes build() itself drop
    # a row could reproduce identically in both `doc` and `fresh` and hide from every check
    # above (public report — the reported defect was exactly this: the page agreed with
    # itself, and disagreed with the store). This is the one check that cannot be fooled that
    # way, because its "expected" side is read directly from data/resume_variants.jsonl.
    store_rows, _serrs, _spresent = _rv.load_store(root)
    expected_vids = {variant_key(r, i) for i, r in enumerate(store_rows)}
    page_vids = set(_VTAB_RE.findall(doc))
    for vid in sorted(expected_vids - page_vids):
        problems.append("VARIANT TAB MISSING FROM PAGE: %s — declared in %s with no tab at "
                        "all, neither rendered nor named as absent; regenerate"
                        % (vid, _rv.STORE_FILE))
    for vid in sorted(page_vids - expected_vids):
        problems.append("VARIANT TAB ON PAGE WITH NO CURRENT ROW: %s — regenerate" % vid)

    # 8. an absent tab's stated cause matches the store NOW — rule 3's staleness check,
    # extended to the notice that stands in for a pane when there is nothing to render
    fresh_absent = {a["id"]: a["cause"] for a in fresh["variants"].get("absent", [])}
    page_absent = {vid: cause for vid, cause in _ABSENT_RE.findall(doc)}
    for vid, cause in sorted(page_absent.items()):
        if vid in fresh_absent and fresh_absent[vid] != cause:
            problems.append("ABSENT NOTICE STALE: %s — page says %r, the store now says %r; "
                            "regenerate" % (vid, cause, fresh_absent[vid]))
        elif vid in expected_vids and vid not in fresh_absent:
            problems.append("ABSENT NOTICE STALE: %s — page shows it absent (%s) but it "
                            "renders now; regenerate" % (vid, cause))

    n_para_rows = sum(1 for it in fresh["open_items"] if it["category"] == "paragraph")
    if problems:
        print("⛔ PRESENCE SET DISAGREES WITH ITS SOURCES — %d problem(s):"
              % len(problems))
        for pr in problems:
            print("  - " + pr)
        print("\n  Fix: python3 scripts/presence_set.py  (then publish and stamp)")
        return 1
    print("PRESENCE SET CLEAN — %d pane(s) generated from their sources, %d probe(s) "
          "round-tripped, %d open item(s) all derived, %d/%d categories named."
          % (len(fresh["panes"]), n_probes, len(fresh["open_items"]),
             len(page_cats), len(CATEGORY_NAMES)))
    if n_para_rows:
        print("  ⚠️ %d paragraph-drift row(s) on the open-items tab — adjacent "
              "source lines rendering as one paragraph; the file decides, not this script "
              "(rule 7)." % n_para_rows)
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="round-trip the generated page against its sources; exit 1 on drift")
    ap.add_argument("--json", action="store_true", help="print the ledger; write nothing")
    args = ap.parse_args()
    root = _profile_root()
    if args.check:
        return check(root)
    if args.json:
        _doc, ledger = build(root)
        print(json.dumps(ledger, indent=1, sort_keys=True, ensure_ascii=False))
        return 0
    return write(root)


if __name__ == "__main__":
    sys.exit(main())
