"""run_lines: what the browser fallback did in a run, read back from the stored `jd_read` attempts (dev 858; design-browser-fallback.md 4.3, 4.4, 5, 8.1).

Capability module of `run_summary.py`, which prints these lines in a run's detail.

---- the browser fallback, read back from the stored attempts (jobsearch 0.90.0; design-browser-fallback.md 4.3, 4.4, 5, 8.1) ----

"Never silent": the run discloses what the fallback did from DATA, not from the reader's word. Three things are read from this run's
`jd_read` attempts in `opportunities.jsonl` (the only place they live), and each is a line the summary prints or does not:

  BROWSER FALLBACK: extension read <n>, could not <m> (<code> <k>, ...), fetch read <f>, withheld <w> (<code> <k>, ...), NOT CHECKED <x>
  NOT CHECKED <id>: pane not painting; extension <code|none>; fetch <code|none>             one per role the chain left unread
  READY CHECK: <n> not-ready reads on a painting page                                       a selector that may no longer match
  UNPARSEABLE fallback <id>                                                                 a stored code this engine does not know

A role is IN THE STORY when one of its attempts in this run carries a 0.90.0 fallback mark: a `fallback.extension` code, a gate of
`not-painting` or `probe-error`, `browser: extension`, or a `via fetch` attempt. `extension read` counts a role read with `browser:
extension`; `could not` counts a role whose latest render attempt carries a `fallback.extension` code, by that code; `fetch read`
counts a role the fetch answered (`read`, or `closed`: it read the page); `withheld` counts a role whose latest fetch attempt is a
`pane-hidden` carrying `fallback.fetch`, by that code (sent nothing, or got an answer it could not use). A role is NOT CHECKED when it
is in the story and every attempt it has in this run is a `pane-hidden`: no rung read it, and no page outcome stands for it.
The attempts are read RAW, not through `jd_read.parse`: a strict parser would refuse the whole role for one unknown code, and the point
is to print the one it cannot read. A code outside `jd_read.EXTENSION_CODES` / `FETCH_CODES` prints `UNPARSEABLE fallback <id>`.
"""

import collections
import json
import os
import jd_read as _jd

NOT_CHECKED_LINE_CAP = 25                      # the segment's count always names every role; the per-role lines stop here, and say so


def _opportunity_rows(root):
    """`(rows, None)` or `(None, why)`: the opportunities store as raw dicts, a missing file as empty (a profile that never captured a
    role has nothing to disclose), a line that is not JSON as a reason (a broken store must not read as an empty one)."""
    path = os.path.join(root, "data", "opportunities.jsonl")
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                if line.strip():
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        return None, "opportunities.jsonl line %d is not JSON" % n
    except FileNotFoundError:
        return [], None
    except OSError as e:
        return None, "opportunities.jsonl cannot be read (%s)" % e
    return [r for r in rows if isinstance(r, dict)], None


def _run_attempts(row, run_id):
    jr = row.get("jd_read")
    atts = jr.get("attempts") if isinstance(jr, dict) else None
    atts = [a for a in atts if isinstance(a, dict) and a.get("run") == run_id] if isinstance(atts, list) else []
    return sorted(enumerate(atts), key=lambda ia: (str(ia[1].get("at") or ""), ia[0]))


def _evidence(att):
    ev = att.get("evidence")
    return ev if isinstance(ev, dict) else {}


def _fallback_code(att, key):
    """`(code, ok)` for `evidence.fallback.<key>` of one attempt: `(None, True)` when it carries none, `(code, True)` for a known code,
    `(code, False)` for one this engine does not know, or a `fallback` that is not the object it should be."""
    fb = _evidence(att).get("fallback")
    if fb is None:
        return None, True
    if not isinstance(fb, dict) or key not in fb:
        return repr(fb)[:40], False
    code = fb[key]
    known = tuple(_jd.EXTENSION_CODES) if key == "extension" else _jd.FETCH_CODES
    return code, code in known


def _codes_text(counter):
    return " (%s)" % ", ".join("%s %d" % (c, n) for c, n in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))) if counter else ""


def browser_fallback_lines(root, run_id):
    """The disclosure lines described in the section comment above, for `run_id`, or `[]` when this run's attempts carry no 0.90.0
    fallback mark at all (a run that never needed the fallback says nothing about it). An unreadable store is one NOT CHECKED line.
    `root` None (a summary with no profile) says nothing."""
    if root is None:
        return []
    rows, why = _opportunity_rows(root)
    if rows is None:
        return ["BROWSER FALLBACK: NOT CHECKED (%s)" % why]
    ext_read, fetch_read, not_checked, unparseable = 0, 0, [], []
    could_not, withheld = collections.Counter(), collections.Counter()
    ready_check, story_roles = 0, 0
    for row in rows:
        atts = [a for _i, a in _run_attempts(row, run_id)]
        if not atts:
            continue
        renders = [a for a in atts if a.get("via") == "render"]
        fetches = [a for a in atts if a.get("via") == "fetch"]
        for a in renders:
            ev = _evidence(a)
            if ev.get("ready") == "NOT-READY" and ev.get("gate") == "paints":
                ready_check += 1
        ext_code, fetch_code, bad = None, None, False
        for a in renders:
            code, ok = _fallback_code(a, "extension")
            bad = bad or not ok
            ext_code = code if code is not None else ext_code
        for a in fetches:
            code, ok = _fallback_code(a, "fetch")
            bad = bad or not ok
            fetch_code = code if code is not None else fetch_code
        read_by_ext = any(a.get("outcome") == "read" and _evidence(a).get("browser") == "extension" for a in renders)
        answered_by_fetch = any(a.get("outcome") in ("read", "closed") for a in fetches)
        gate_stopped = any(_evidence(a).get("gate") in ("not-painting", "probe-error") for a in renders)
        in_story = bool(read_by_ext or answered_by_fetch or ext_code is not None or fetch_code is not None or gate_stopped
                        or fetches)
        if not in_story:
            continue
        story_roles += 1
        ext_read += 1 if read_by_ext else 0
        fetch_read += 1 if answered_by_fetch else 0
        if ext_code is not None and not read_by_ext:
            could_not[ext_code] += 1
        if fetch_code is not None and not answered_by_fetch:
            withheld[fetch_code] += 1
        if bad:
            unparseable.append(row.get("id"))
        if all(a.get("outcome") == "pane-hidden" for a in atts):
            not_checked.append((row.get("id"), ext_code, fetch_code))
    lines = []
    if story_roles:
        lines.append("BROWSER FALLBACK: extension read %d, could not %d%s, fetch read %d, withheld %d%s, NOT CHECKED %d"
                     % (ext_read, sum(could_not.values()), _codes_text(could_not), fetch_read, sum(withheld.values()),
                        _codes_text(withheld), len(not_checked)))
    for oid, ext_code, fetch_code in not_checked[:NOT_CHECKED_LINE_CAP]:
        lines.append("NOT CHECKED %s: pane not painting; extension %s; fetch %s" % (oid, ext_code or "none", fetch_code or "none"))
    if len(not_checked) > NOT_CHECKED_LINE_CAP:
        lines.append("NOT CHECKED: %d more role(s) not listed here (the count above names every one); read their `jd_read` attempts"
                     % (len(not_checked) - NOT_CHECKED_LINE_CAP))
    for oid in unparseable:
        lines.append("UNPARSEABLE fallback %s" % oid)
    if ready_check:
        lines.append("READY CHECK: %d not-ready read%s on a painting page" % (ready_check, "" if ready_check == 1 else "s"))
    return lines


def gap_fallback(gap):
    """`, extension <code>` for a gap that carries the runner's stored `fallback` (dev #858: why the extension did not take the
    surfaces the pane could not paint), else `""`: a gap without the key reads exactly as it always did."""
    fb = gap.get("fallback")
    if isinstance(fb, dict) and isinstance(fb.get("extension"), str):
        return ", extension %s" % fb["extension"]
    return ""
