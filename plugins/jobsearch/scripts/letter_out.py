#!/usr/bin/env python3
"""Turn a drafted cover letter into a deliverable (a Google Doc, or a local .docx), and check the letters staged for it.

⭐ TWO MODES, because Google Drive used to be unconditional, which made a Google account a requirement. `local_docx` writes a
real .docx with the stdlib alone (`_docx.py`). ⚠️ This script never creates the Google Doc: the connector is CREATE-ONLY (no
update, delete or move), so the session pushes it once, when the text is final, with the job-search folder as `parentId`.

    ~/.claude/jobsearch/run letter_out.py --status | --set-mode local_docx | --render "<an employer>" [--out FILE.docx]
    ~/.claude/jobsearch/run letter_out.py --check [--advisory] [--json]     # the STAGED LETTERS block (design 8.2)
    ~/.claude/jobsearch/run letter_out.py --preflight <opp_id> [--record]   # may a letter be written? (design 8.1)
    ~/.claude/jobsearch/run letter_out.py --answer <opp_id> write-anyway    # ONLY on the candidate's word, for a no-pitch stop
    ~/.claude/jobsearch/run letter_out.py --set-guide <path | none>         # ONLY on the candidate's word (design 5.2)

⭐ THE BODY COMES FROM `> `-QUOTED LINES ONLY, as the dashboard parsers read it: a plain-text body once published EMPTY, and
every check passed on a file that read perfectly. ONE CHECK, TWO CALLERS (dev 1073): `--check` and `--render` run
`letters.check.check_entry` over entries from `letters.entries`, with the inputs `_inputs()` reads, so they cannot disagree.
`--render` REFUSES (exit 1, nothing written) a letter with a FAIL. `--check --advisory` always exits 0 (a run-start line); an
input it cannot read prints `NOT CHECKED`, never a quiet pass. `--json` prints one object for the status page: `guide` (the
verdict line), `problems` (the writing rules'), `pending`, `closed`, `letters` (heading, fails, notes), `stops` (open
letter-stopped asks: id, title), or `{"not_checked": why}`; the exit code is `--check`'s. It does not count pages.

⭐ `--preflight` (dev 1071): `ok` or `stop no-fit | no-pitch | guide`, exit 0 or 1; an unknown opp_id or unreadable store is
`NOT CHECKED`, exit 2, nothing filed. `--record` files a stop as ONE `asks.jsonl` row, id `letter-stopped:<opp_id>`, through
`record.py` and `letters.stop_asks` (every write read back, never the exit code alone): an open row is kept while the same stop
persists, a different reason replaces its text, a resolved row is not reopened by the same stop (a different reason files a new
row, id suffixed `~<n>`), an `ok` closes the open row. The outcome goes to stderr. `--answer <opp_id> write-anyway` resolves
the open `no-pitch` stop on the candidate's word, and then `--preflight` passes that role. ENGINE SKEW is the `skew` of
`lifecycle.py --report --json` (a child: an entry point is never imported, G5.L2); unreadable, it is read as none.
`config.json` is edited as TEXT (`letters.jsonedit`): its escapes and key order stay; only the changed key moves.
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _root import profile_root
import _atomic
import _fit_pitch
import _tree
import profile as prof
from _docx import write_docx
from letters import check as _check, entries as _entries, guide as _guide, jsonedit as _jsonedit, rules as _rules
from letters import stop_asks as _asks
from migrations import stamp as _stamp

MODES = ("drive", "local_docx")
DEFAULT_MODE = "drive"


def _config_path():
    return os.path.join(profile_root(), "config.json")


def _load_config():
    with open(_config_path(), encoding="utf-8") as fh:
        return json.load(fh)


def _edit_config(*edits):
    """Apply `(path, value)` edits to config.json's TEXT, atomically (`jsonedit.REMOVE` removes): no other byte moves, so its
    `\\uXXXX` escapes and key order stay. True when written; else says why and writes nothing."""
    try:
        with open(_config_path(), encoding="utf-8", newline="") as fh:
            text = fh.read()
        for path, value in edits:
            text = _jsonedit.remove_path(text, path) if value is _jsonedit.REMOVE else _jsonedit.set_path(text, path, value)
    except ValueError as e:
        print("config.json NOT changed: %s" % e)
        return False
    _atomic.write_text(_config_path(), text)         # a partial write would destroy the whole config
    return True


def output_settings():
    """The letter-output block, with defaults applied. Never invents a folder id."""
    cfg = _load_config()
    drive = cfg.get("drive", {}) or {}
    return {"mode": DEFAULT_MODE, "local_dir": "letters", **(cfg.get("writing", {}).get("cover_letter_output") or {}),
            "drive_folder_id": drive.get("job_search_folder_id"), "drive_folder_name": drive.get("job_search_folder_name")}


def set_mode(mode):
    if mode not in MODES:
        print("Unknown mode %r. Choose one of: %s" % (mode, ", ".join(MODES)))
        return 2
    block = ("writing", "cover_letter_output")
    why = ("drive = push to the job-search Drive folder (needs a Google account and the documents connector). "
           "local_docx = write a .docx next to the repo, no Google account required.")
    has_dir = "local_dir" in ((_load_config().get("writing") or {}).get("cover_letter_output") or {})
    if not _edit_config((block + ("mode",), mode), *([] if has_dir else [(block + ("local_dir",), "letters")]),
                        (block + ("_why",), why)):
        return 1
    print("Cover-letter output mode set to %r." % mode)
    return status()


def set_guide(arg):
    """`--set-guide <path|none>` (design 5.2): `letters.guide.plan_set_guide` decides; this writes it atomically or refuses."""
    cfg, root = _load_config(), profile_root()
    ch = _guide.plan_set_guide(cfg, root, arg)
    if ch.action == "refuse" or (ch.action == "remove" and "letter_guide" not in (cfg.get("writing") or {})):
        print("Letter guide NOT changed: %s. Nothing written." % (ch.reason or "none was declared"))
        return 1 if ch.reason else 0
    if not _edit_config((("writing", "letter_guide"), ch.value if ch.action == "set" else _jsonedit.REMOVE)):
        return 1
    print("Letter guide %s.\n%s" % ("removed" if ch.action == "remove" else "set to %s (required headings: %s)"
                                    % (ch.value["path"], ", ".join(ch.value["required_headings"]) or "none"),
                                    _guide.check_guide(_load_config(), root).line))
    return 0


def _letters_text():
    """The cover-letters file's text, or None when there is no such file."""
    p = _tree.path(profile_root(), "cover_letters")
    return open(p, encoding="utf-8").read() if os.path.exists(p) else None


def _inputs():
    """What both checks need, read once: (rules, guide verdict, stamp_ok, skew, marked, full_name)."""
    root, cfg, user = profile_root(), _load_config(), prof.user()
    skew = False
    try:        # `lifecycle.py` is an entry point (G5.L2: never imported), so its own `--report --json` says it: rc 3 = a mismatch, still read
        skew = bool(json.loads(subprocess.run([sys.executable, os.path.join(HERE, "lifecycle.py"), "--report", "--json"],
                                              capture_output=True, text=True, timeout=60).stdout)["skew"])
    except Exception as e:      # noqa: BLE001 - said, never silent
        print("NOT CHECKED: engine skew (%s: %s); read as no skew" % (type(e).__name__, str(e)[:120]), file=sys.stderr)
    return (_rules.writing_rules(cfg, user), _guide.check_guide(cfg, root),
            _check.version_at_least(_stamp.read_stamp(root)), skew, _check.read_marked(root),
            (user.get("identity") or {}).get("full_name") or "")


def check(advisory, as_json=False):
    """`--check [--advisory] [--json]`: the STAGED LETTERS block (or its JSON object); exit 1 on any FAIL, always 0 under `--advisory`."""
    try:
        ins = _inputs()
        rep = _check.check_file(_letters_text(), *ins)
        stops = _asks.open_stops(profile_root()) if as_json else None
    except Exception as e:      # noqa: BLE001 - a run-start line must say it could not look, never pass quietly
        why = "%s: %s" % (type(e).__name__, str(e)[:160])
        print(json.dumps({"not_checked": why}) if as_json else "STAGED LETTERS — NOT CHECKED: %s" % why)
        return 0 if advisory else 1
    print(json.dumps({"guide": rep.guide.line, "problems": ins[0]["problems"], "pending": rep.pending, "closed": rep.closed,
                      "letters": rep.rows, "stops": stops}) if as_json else rep.text())
    return rep.exit_code(advisory)


def find_entry(needle, text, full_name):
    """The entry whose heading matches `needle`. Exits loudly on no file, no entry, no match, several, or no body."""
    found = _entries.parse_entries(text or "", full_name)
    hits = [e for e in found if needle.lower() in e.heading.lower()]
    if text is None or len(hits) != 1:
        raise SystemExit("No cover_letters.md." if text is None else "No entries found in cover_letters.md" if not found
                         else "%s %r. Entries:\n  %s" % ("No entry matching" if not hits else "Several entries match",
                                                        needle, "\n  ".join(e.heading for e in (hits or found))))
    if not hits[0].has_body:
        raise SystemExit("⛔ %r has NO `> `-quoted body.\nThe body must be blockquoted or it publishes EMPTY — and an empty "
                         "body is\nindistinguishable from 'not drafted yet'. Fix cover_letters.md, then re-run." % hits[0].heading)
    return hits[0]


def preflight(opp_id, record):
    """`--preflight <opp_id> [--record]`: exit 0 ok, 1 stop, 2 NOT CHECKED (nothing filed)."""
    try:
        with open(os.path.join(profile_root(), "data", "opportunities.jsonl"), encoding="utf-8") as fh:
            opp = next((o for o in (json.loads(l) for l in fh if l.strip()) if o.get("id") == opp_id), None)
        verdict = _guide.check_guide(_load_config(), profile_root())
        if opp is None:
            raise ValueError("no opportunity with that id")
        state = _fit_pitch.state(opp)       # the candidate's "write it anyway" counts only while the fit still found no pitch
        said = _asks.answered(profile_root(), opp_id) if state == "no-pitch" else None
    except (OSError, ValueError) as e:
        print("LETTER PREFLIGHT %s NOT CHECKED: %s" % (opp_id, e))
        return 2
    pf = _check.preflight(opp_id, opp.get("title"), state, verdict, **({"answered": said} if said else {}))
    print(pf.line)
    if record:
        print("ask: %s" % _asks.file_ask(profile_root(), HERE, pf, opp, verdict, datetime.date.today().isoformat()), file=sys.stderr)
    return 0 if pf.ok else 1


def answer(opp_id, verb):
    """`--answer <opp_id> write-anyway`: run only on the candidate's word. Resolves the open no-pitch stop; refuses otherwise."""
    if verb != _asks.ANSWER:
        print("Unknown answer %r. The one answer is %r." % (verb, _asks.ANSWER))
        return 2
    code, msg = _asks.answer(profile_root(), HERE, opp_id, datetime.date.today().isoformat())
    print(msg)
    return code


def status():
    s = output_settings()
    print("COVER-LETTER OUTPUT\n" + "=" * 74 + "\n  Mode        : %s" % s["mode"])
    if s["mode"] == "drive" and s["drive_folder_id"]:
        print("  Drive folder: %s (%s)\n" % (s["drive_folder_name"], s["drive_folder_id"]))
        print("  ⭐ Pass that id as `parentId` when creating the document. The connector\n"
              "     CANNOT MOVE A FILE, so a document created without a parent lands in My\n"
              "     Drive root and the only fix is a second copy for you to delete.")
    elif s["mode"] == "drive":
        print("  Drive folder: NOT CONFIGURED\n")
        print("  ⚠️ Mode is `drive` but config.json has no drive.job_search_folder_id, so a\n"
              "     document would land in My Drive root and could not be moved.\n"
              "     Set the folder id, or switch to a local file:\n"
              "       ~/.claude/jobsearch/run letter_out.py --set-mode local_docx")
    else:
        print("  Writes to  : %s/\n  No Google account, connector or network needed." % os.path.join(profile_root(), s["local_dir"]))
    print("\n  Switch:  ~/.claude/jobsearch/run letter_out.py --set-mode %s" % ("local_docx" if s["mode"] == "drive" else "drive"))
    return 0


def _send_hold(heading):
    """The entry's send-precondition state, or None (dev #169): an outward path says so. Advisory, never silent."""
    try:
        import precondition as _pre
        for r in _pre.report(profile_root(), filenames=(_tree.rel("cover_letters"),)):
            if r["title"] == heading and r["state"] in _pre.NOT_SENDABLE:
                return r
    except Exception:
        pass                     # advisory: a broken resolver must not block a render
    return None


def render(needle, out_path=None):
    rules, _verdict, stamp_ok, skew, marked, name = _inputs()
    e = find_entry(needle, _letters_text(), name)
    found = _check.check_entry(e, rules, stamp_ok, skew, marked)
    s = output_settings()

    print("Entry : %s\nBody  : %d words" % (e.heading, len(e.body_text.split())))
    hold = _send_hold(e.heading)
    if hold:
        print("\n⏳ SEND-HOLD ON THIS LETTER [%s]: %s\n   Rendering anyway — but this letter is NOT ready to submit until the\n"
              "   precondition resolves (dev #169)." % (hold["state"], hold["why"]))
    for level, title in ((_check.FAIL, "⚠️ FIX BEFORE SENDING:"), (_check.NOTE, "Notes:")):
        if any(lv == level for lv, _t in found):
            print("\n%s\n%s" % (title, "\n".join("   - %s" % t for lv, t in found if lv == level)))
    print()
    if any(lv == _check.FAIL for lv, _t in found):      # a letter with a FAIL is never made into a document (dev 1073)
        print("⛔ NOT rendered: fix the FAIL above in cover_letters.md, then re-run. Nothing was written.")
        return 1

    if s["mode"] == "drive":
        print("Mode is `drive` — this script does NOT create the document.\n"
              "The connector is CREATE-ONLY, so push exactly once, when the text is final:\n\n"
              "   parentId: %s\n\nThen READ THE DOCUMENT BACK to verify it — the create response's reported size is\n"
              "meaningless for a native Google Doc." % (s["drive_folder_id"] or "!! NOT CONFIGURED !!"))
        return 1 if not s["drive_folder_id"] else 0

    # ⭐ The drafted body often already carries the canonical header (the writer follows the same template);
    # prepending it again printed the name and contact block twice. `e.header` is that block, when present.
    header = [] if e.header is not None else rules["header"] or [name]
    body = [x for i, p in enumerate(e.quote_paragraphs) for x in ([""] if i else []) + p.split("\n")]
    slug = re.sub(r"[^A-Za-z0-9]+", "-", e.heading).strip("-").lower()[:60]
    out_path = out_path or os.path.join(profile_root(), s["local_dir"], "%s.docx" % slug)
    write_docx(out_path, header, body)
    print("Wrote %s (%d bytes)\n" % (out_path, os.path.getsize(out_path)))
    print("⭐ OPEN IT AND CHECK THE PAGE COUNT before sending. The one-page rule is a real\n"
          "   constraint — a second page carrying only a signature is a defect. If it spills,\n"
          "   cut margins before cutting substance.")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--set-mode", metavar="MODE", choices=MODES)
    ap.add_argument("--render", metavar="ENTRY")
    ap.add_argument("--out", metavar="PATH")
    ap.add_argument("--check", action="store_true", help="the STAGED LETTERS block; exit 1 on a FAIL")
    ap.add_argument("--advisory", action="store_true", help="with --check: print the block, always exit 0")
    ap.add_argument("--preflight", metavar="OPP_ID", help="may a letter be written for this role?")
    ap.add_argument("--record", action="store_true", help="with --preflight: file or close the ask")
    ap.add_argument("--json", action="store_true", help="with --check: one JSON object for the status page")
    ap.add_argument("--answer", nargs=2, metavar=("OPP_ID", "ANSWER"), help="the candidate's answer to a stop: write-anyway")
    ap.add_argument("--set-guide", metavar="PATH", help="declare the letter guide (a profile path), or `none`")
    a = ap.parse_args()
    return (set_mode(a.set_mode) if a.set_mode else set_guide(a.set_guide) if a.set_guide
            else check(a.advisory, a.json) if a.check else preflight(a.preflight, a.record) if a.preflight
            else answer(*a.answer) if a.answer else render(a.render, a.out) if a.render else status())


if __name__ == "__main__":
    sys.exit(main())
