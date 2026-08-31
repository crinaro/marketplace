#!/usr/bin/env python3
"""The pending tombstone-stub ledger for RETIRED published-page URLs — the one-artifact
collapse (2026-08-29; owner-approved 2026-08-26).

WHY THIS EXISTS
---------------
The old publishing model shipped a data-dependent artifact SET (router + state view +
threshold-selected phase pages). Collapsing it to one artifact retires every per-page URL
except `views/dashboard_artifact_url.txt` — but a retired URL keeps SERVING its last
snapshot forever unless something publishes a "moved" stub over it, and the Artifact tool
is model-invoked only: **no script can publish**. So the retirement is two-phase:

  1. `migrate.m_0_34_0_dashboard_collapse` only RECORDS: each surviving
     `views/*_url.txt` (other than the dashboard's own) becomes a row here, state
     `pending`. **The url file is not deleted at that step.**
  2. A tool-holding session DRAINS: it publishes the constant moved-stub
     (`--stub-html` writes the file to publish) to the row's URL, then — only on a
     confirmed publish — runs `--published <page>`, which marks the row `stubbed` and
     retires the url file.

⭐ THE ORDERING IS LOAD-BEARING. Retiring a url file before its stub publish is
confirmed makes that URL **permanently unstubbable** — nothing would remember it
exists, which is exactly the dangling-live-URL outcome this design removes. The row
stores the URL itself at record time, so even a url file lost by other means stays
stubbable from the ledger.

States (a row with any other state is UNREADABLE and this tool goes loud — a
precondition nobody can read is worse than none):

  pending     recorded, stub not yet confirmed published — drain it.
  stubbed     stub publish confirmed; the url file has been retired. Terminal.
  failed      a stub publish failed against this URL (e.g. artifact deleted
              server-side). Kept standing and surfaced each run as an OWNER decision
              to retry or drop — never silently retried forever, never silently
              dropped. `--published` after a later successful publish still resolves
              it; `--dropped` records the owner's decision to abandon the URL.
  unresolved  the url file existed but its content did not parse as a URL. Only a
              human can say what it was; the file is kept.

An ABSENT url file at migration time means "that page never published" and is benign —
it records nothing here. Two phases on the reference profile are in exactly that state.

Usage:
    python3 scripts/pending_stubs.py                  # report; exit 1 only on unreadable rows
    python3 scripts/pending_stubs.py --check          # exit 1 if anything still needs draining
    python3 scripts/pending_stubs.py --json           # rows, machine-readable
    python3 scripts/pending_stubs.py --stub-html <page>   # write the stub file to publish
    python3 scripts/pending_stubs.py --published <page>   # AFTER a confirmed stub publish
    python3 scripts/pending_stubs.py --failed <page> --why "..."
    python3 scripts/pending_stubs.py --dropped <page> --why "..."   # owner decision only

Python 3.9+. Standard library only.
"""

import argparse
import datetime
import json
import os
import sys

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from _root import profile_root as _profile_root
import _atomic

STORE_REL = os.path.join("data", "pending_stubs.jsonl")
VALID_STATES = ("pending", "stubbed", "failed", "unresolved", "dropped")
# The one URL the collapse keeps — never a stub target.
SURVIVING_URL_FILES = ("dashboard_artifact_url.txt",)

# The constant moved-stub, the DASHBOARD_TOMBSTONE pattern: it carries no state beyond
# the pointer, so it can never itself go stale. %s is the surviving dashboard URL when
# known, else a sentence naming where to find it.
MOVED_STUB_TEMPLATE = """<title>This page has moved</title>
<body style="font-family:sans-serif;max-width:34em;margin:3em auto;line-height:1.5">
<h1>This page has moved</h1>
<p>The dashboard is <strong>one page</strong> now — the router and the per-phase pages
were folded into it (2026-08-29). %s</p>
</body>
"""


def store_path(root):
    return os.path.join(root, STORE_REL)


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_rows(root):
    """Every row, strictly parsed. Raises ValueError on a row it cannot vouch for —
    an unparseable ledger row must be LOUD, never skipped (it would look handled)."""
    path = store_path(root)
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                raise ValueError("%s line %d: not JSON" % (STORE_REL, n))
            if not isinstance(row, dict) or not row.get("page"):
                raise ValueError("%s line %d: no 'page' field" % (STORE_REL, n))
            if row.get("state") not in VALID_STATES:
                raise ValueError("%s line %d: state %r is not one of %s"
                                 % (STORE_REL, n, row.get("state"),
                                    "/".join(VALID_STATES)))
            rows.append(row)
    return rows


def save_rows(root, rows):
    _atomic.write_jsonl(store_path(root), rows)


def record(root, page, url_file_rel, url, state="pending"):
    """Add one row (idempotent on `page`) — the migration's entry point. Returns True
    when a row was added, False when the page was already recorded."""
    rows = load_rows(root)
    if any(r["page"] == page for r in rows):
        return False
    rows.append({"page": page, "url_file": url_file_rel, "url": url,
                 "state": state, "recorded_at": _now()})
    save_rows(root, rows)
    return True


def surviving_dashboard_url(root):
    for cand in (os.path.join(root, "views", "dashboard_artifact_url.txt"),
                 os.path.join(root, "dashboard_artifact_url.txt")):
        try:
            with open(cand, encoding="utf-8") as fh:
                u = fh.read().strip()
            if u.startswith(("http://", "https://")):
                return u
        except OSError:
            pass
    return None


def stub_html(root):
    url = surviving_dashboard_url(root)
    if url:
        pointer = ('Bookmark the one page instead: <a href="%s">%s</a>.' % (url, url))
    else:
        pointer = ("Its URL lives in this profile's views/dashboard_artifact_url.txt "
                   "after the first publish.")
    return MOVED_STUB_TEMPLATE % pointer


def _find(rows, page):
    for r in rows:
        if r["page"] == page:
            return r
    return None


def _retire_url_file(root, row):
    """Delete the row's url file — ONLY called after a confirmed stub publish. The URL
    itself stays in the row, so this is an auditable tracked deletion, not amnesia."""
    rel = row.get("url_file") or ""
    path = os.path.join(root, rel)
    if rel and os.path.exists(path):
        os.unlink(path)
        return True
    return False


def cmd_report(root, as_json=False, check=False):
    try:
        rows = load_rows(root)
    except ValueError as e:
        print("⛔ PENDING-STUB LEDGER UNREADABLE — %s" % e)
        print("   A row nobody can read looks handled and is not. Fix the row; do not "
              "delete it.")
        return 1
    if as_json:
        print(json.dumps(rows, indent=1))
        return 0
    if not rows:
        print("No retired-URL stubs recorded — nothing to drain.")
        return 0
    open_rows = [r for r in rows if r["state"] in ("pending", "failed", "unresolved")]
    for r in rows:
        mark = {"pending": "⏳", "stubbed": "✅", "failed": "⛔",
                "unresolved": "❓", "dropped": "🗑"}[r["state"]]
        print("  %s %-10s %-32s %s" % (mark, r["state"], r["page"],
                                       r.get("url") or "(no parseable url)"))
    if open_rows:
        print("\n%d row(s) still need a tool-holding session:" % len(open_rows))
        print("  1. python3 scripts/pending_stubs.py --stub-html <page>")
        print("  2. publish that file with the Artifact tool, `url` = the row's URL")
        print("  3. python3 scripts/pending_stubs.py --published <page>   # ONLY after "
              "a confirmed publish")
        print("  A failed publish: --failed <page> --why '...' (owner decides; never "
              "silently dropped).")
        return 1 if check else 0
    print("All recorded URLs are stubbed or resolved.")
    return 0


def cmd_stub_html(root, page):
    rows = load_rows(root)
    row = _find(rows, page)
    if row is None:
        print("⛔ no ledger row for %r — nothing records that page's URL. Refusing to "
              "invent one." % page)
        return 1
    out = os.path.join(root, "views", "moved_stub.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    _atomic.write_text(out, stub_html(root))
    print("Wrote %s" % os.path.relpath(out, root))
    print("Publish it with the Artifact tool to: %s" % (row.get("url") or
          "(row has no parseable url — resolve the 'unresolved' state first)"))
    print("Then, ONLY after the publish is confirmed:")
    print("  python3 scripts/pending_stubs.py --published %s" % page)
    return 0


def cmd_published(root, page):
    rows = load_rows(root)
    row = _find(rows, page)
    if row is None:
        print("⛔ no ledger row for %r — a publish cannot be recorded against nothing." % page)
        return 1
    if row["state"] == "stubbed":
        # Idempotent: re-running after a crash between the state write and the file
        # retire finishes the retire.
        removed = _retire_url_file(root, row)
        print("Already stubbed%s." % ("; retired the leftover url file" if removed else ""))
        return 0
    row["state"] = "stubbed"
    row["stubbed_at"] = _now()
    save_rows(root, rows)              # record the confirmed publish FIRST…
    removed = _retire_url_file(root, row)   # …then retire the file (the ordering rule)
    print("✅ %s marked stubbed%s." % (page,
          "; url file retired" if removed else " (no url file left to retire)"))
    return 0


def cmd_mark(root, page, state, why):
    if state == "dropped" and not why:
        print("⛔ --dropped records an OWNER decision and needs --why quoting it.")
        return 1
    rows = load_rows(root)
    row = _find(rows, page)
    if row is None:
        print("⛔ no ledger row for %r." % page)
        return 1
    row["state"] = state
    row["why"] = why or row.get("why") or ""
    row["updated_at"] = _now()
    save_rows(root, rows)
    print("Recorded %s as %s%s." % (page, state, (" — %s" % why) if why else ""))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 while anything still needs a tool-holding session")
    ap.add_argument("--stub-html", metavar="PAGE")
    ap.add_argument("--published", metavar="PAGE")
    ap.add_argument("--failed", metavar="PAGE")
    ap.add_argument("--dropped", metavar="PAGE")
    ap.add_argument("--why", default="")
    args = ap.parse_args()
    root = _profile_root()
    if args.stub_html:
        return cmd_stub_html(root, args.stub_html)
    if args.published:
        return cmd_published(root, args.published)
    if args.failed:
        return cmd_mark(root, args.failed, "failed", args.why)
    if args.dropped:
        return cmd_mark(root, args.dropped, "dropped", args.why)
    return cmd_report(root, as_json=args.json, check=args.check)


if __name__ == "__main__":
    sys.exit(main())
