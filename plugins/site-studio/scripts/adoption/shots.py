"""adoption.shots -- the pictures of both pages, and the accept rule that needs them (design-adopt-parity-2 7.3, owner decision 3).

Part of the `adoption` package behind the entry point `adopt.py`.

`adopt.py parity --keep DIR` leaves the two builds in DIR/local and DIR/plugin, and this module renders every `page` row of the
ACCEPT list (`adoption.accepts`) from each build that has the page into DIR/shots/old and DIR/shots/new: the four views
`render.py` makes (1440 and 390 wide, light and dark), named as `render.py` names them (`slug(page)-<desktop|phone>-<light|dark>.png`).
It runs `render.render_site` through `render.py --site DIR --base PATH --pages ... --out ... --json` and reads its REPORT
(`<out>/report.json`), never an exit code: a page that overflows sideways still has its PNGs, a view that could not load has none
and is named. Each build is served under its own path (`--base`): the plugin's under the path its own `robots.txt` names
(`parity.served_at`, the path `classify_p2` reads it under), the old build's under the path its own output assumes
(`sameresource.build_path`, step 7's, not edited here). It writes DIR/shots/compare.html (each page, its four views, old beside new,
by relative address) and DIR/shots/report.json (both render reports and every line below: error texts hold addresses and a browser's
words, so they stay in the kept folder, never in the plan).

What the plan stores (`parity.shots`, plan schema 3, `adoption/plan.py`): per page, each PNG's file name and sha256, or
`{"none": "chrome-not-found"}` when no browser is on the machine. The code is from a closed set (`NONE_CODES`), never the browser's
message, which holds `CHROME_PATH`'s value (a path on the person's machine): the message is printed, the code stored.

    no browser on the machine (`render.py --chrome` finds none)  `none: chrome-not-found`; the accept is allowed (owner decision 3a)
    a browser that is found and will not start (render.py         no `shots`, the builds kept, a refusal carrying the browser's
      refuses: `browser.BrowserError`, `_start_failure`'s words)  sentence (owner decision 3b); `--accept` then refuses as for any plan
                                                                  without them
    every view of a page failed                                   that side's map is stored EMPTY, its line printed and in
                                                                  report.json, and `--accept` refuses on it (never an empty list)

`--accept` (`check_accept`) records ACCEPTED only when, beside 0.5.0's rule (the stored differences equal the new measure), the
stored `open` rows equal the new ones and, for every `page` row and each build that has the page, the stored `shots` names at least
one picture and each named file is in `--shots DIR/shots` with its stored sha256. A stored `none` is honoured only where the browser
is still not found (`render.py --chrome`: `browser.lookup_chrome`, a path lookup that starts nothing). `remeasure` holds to the same
rule through DIR/shots/shots.json, since an adopted repo has no plan (`for_remeasure`).

RENDER.PY AS A PROCESS (dated note 2026-11-21, step 9b): design 7.3 has this module call `render.render_site` in-process, importing
`render` (and so `browser`) only inside the `--keep` path. The segmentation standard refuses both: nothing imports an entry point
(G5.L2; `render.py` and `browser.py` have `__main__` blocks), an import inside a function of a capability module is debt (G4), and a
mirrored test may not import one either (G7). So the one call is a process, as `adoption` already runs `git` and `node`, and what 7.3
protects holds by construction: no adopt process imports `browser` at all, and a browser starts only inside `render.py`, which only
`--keep` runs. The seams a test replaces are `runner` (one render of one build) and `finder` (the browser lookup); the real
`render_site` with a fake `browser_factory` is driven through them by `tests/test_render.py` (a flat test may import an entry point).

    make_pictures(keep, rows, differences, log, runner, finder)  --keep: (the `shots` member or None, a refusal or None)
    check_accept(prev, res, shots_dir, finder)                  --accept: the line the accept adds, or Refused naming what is missing
    for_parity(res, prev, keep, shots_dir, accepting)           `cmd_parity`'s one call: a Pictures (store, finish)
    for_remeasure(res, accept, keep, shots_dir)                 `cmd_remeasure`'s one call: the commit message's tail, or Refused
"""

import hashlib
import html
import json
import os
import subprocess
import sys

from adoption.accepts import page_paths, sides_of
from adoption.base import Refused
from adoption.parity import served_at, stale_parity
from parityscan.sameresource import build_path

NONE_CODES = ("chrome-not-found",)          # owner decision 3 (a): the one code a stored `none` may hold
SIDES = (("old", "local"), ("new", "plugin"))       # (the side's name in `shots`, its folder under the kept DIR)
SHOTS_DIR = "shots"
MANIFEST = "shots.json"                      # remeasure's record of what `--keep` measured and pictured
REPORT = "report.json"
KEEP_AGAIN = "run `adopt.py %s --keep <dir>` again"
RENDER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "render.py")
RENDER_TIMEOUT = 1800                        # seconds for one build's renders: four views a page, each with its own load timeout


def render_argv(site, base, pages, out):
    """The `render.py` command line that renders `pages` of the build in `site`, served under `base`, into `out`."""
    return [sys.executable, "-B", RENDER, "--site", site, "--base", base, "--pages", ",".join(pages), "--out", out, "--json"]


def run_render(site, base, pages, out):
    """(render_site's report, None), or (None, the refusal line `render.py` printed: the browser's own sentence)."""
    try:
        p = subprocess.run(render_argv(site, base, pages, out), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=RENDER_TIMEOUT)
        said = [l for l in p.stdout.decode("utf-8", "replace").splitlines() if l.strip()]
    except subprocess.TimeoutExpired:
        return None, "render.py did not finish within %d s" % RENDER_TIMEOUT
    try:
        with open(os.path.join(out, REPORT), "r", encoding="utf-8") as fh:
            return json.load(fh), None
    except (OSError, ValueError):
        last = said[-1] if said else "render.py wrote no report (exit %d)" % p.returncode
        return None, last[len("render refused: "):] if last.startswith("render refused: ") else last


def find_chrome():
    """(True, the path) or (False, why): `render.py --chrome`, which looks Chrome up (`browser.lookup_chrome`) and starts nothing."""
    p = subprocess.run([sys.executable, "-B", RENDER, "--chrome"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
    said = [l for l in p.stdout.decode("utf-8", "replace").splitlines() if l.strip()]
    return p.returncode == 0, (said[-1] if said else "render.py --chrome printed nothing (exit %d)" % p.returncode)


def _walk(root):
    out = {}
    for d, _dirs, files in os.walk(root):
        for f in files:
            p = os.path.join(d, f)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, root).replace(os.sep, "/")] = fh.read()
    return out


def _sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _served(base):
    return "/%s/" % base if base else "/"


def _page_entry(page, sides, reports, shots_dir, lines, empty):
    """{side: {png name: sha256}} for one page, from the render reports; the lines it adds name what failed or overflowed."""
    entry = {}
    for side in sides:
        rep = reports[side]
        names = [v["png"] for v in rep.get("views") or () if v.get("page") == page]
        entry[side] = dict((n, _sha(os.path.join(shots_dir, side, n))) for n in names)
        errs = [e for e in rep.get("errors") or () if e.get("page") == page and "viewport" in e]
        first = ("%s, %s: %s" % (errs[0]["viewport"], errs[0]["scheme"], errs[0]["error"])) if errs else "no error was reported"
        if not names:
            line = ("no picture of %s could be made from the %s build: %d view(s) failed (first: %s)"
                    % (page, side, len(errs), first))
            empty.setdefault(page, {})[side] = line
            lines.append(line)
        elif errs:
            lines.append("note: %d view(s) of %s failed in the %s build (first: %s); the others are pictured"
                         % (len(errs), page, side, first))
        for o in rep.get("overflow") or ():
            if o.get("page") == page:
                lines.append("note: %s overflows sideways at %s px in the %s build (the page is %s px wide); pictured anyway"
                             % (page, o.get("width"), side, o.get("scrollWidth")))
    return entry


def _compare_html(pages, member, sides_for):
    rows = []
    for page in pages:
        rows.append("<h2>%s</h2>" % html.escape(page))
        names = sorted(set(n for side in sides_for[page] for n in member["pages"][page][side]))
        for name in names or ["(no view of this page could be rendered)"]:
            cells = []
            for side, _folder in SIDES:
                got = member["pages"][page].get(side) if side in sides_for[page] else None
                cells.append("<td>%s</td>" % (
                    "(this build has no such page)" if got is None else
                    '<img src="%s/%s" alt="%s, %s build" width="480">' % (side, html.escape(name), html.escape(name), side)
                    if name in got else "(no picture: see report.json)"))
            rows.append("<table><tr><th>%s</th><th>old</th><th>new</th></tr><tr><td></td>%s</tr></table>"
                        % (html.escape(name), "".join(cells)))
    return ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><title>adopt parity: old and new pages</title>'
            "<style>body{font:15px sans-serif;margin:16px}img{border:1px solid #888;vertical-align:top}td{vertical-align:top}"
            "</style></head><body>\n<h1>Each page that differs: the old build beside the plugin's</h1>\n%s\n</body></html>\n"
            % "\n".join(rows))


def make_pictures(keep, rows, differences, log=print, runner=None, finder=None):
    """`--keep DIR`: render every `page` row from each build that has it. Returns (the `shots` member, None), or (None, the refusal
    line) when a browser was found and would not start. `runner(site, base, pages, out)` renders one build (`run_render`, the
    default); `finder()` looks the browser up (`find_chrome`); `log` prints."""
    pages = page_paths(rows)
    if not pages:
        return {"pages": {}}, None
    found, where = (finder or find_chrome)()
    if not found:
        log("  pictures: none were made: %s" % where)
        return {"none": NONE_CODES[0]}, None
    shots_dir = os.path.join(keep, SHOTS_DIR)
    builds = dict((side, _walk(os.path.join(keep, folder))) for side, folder in SIDES)
    site = served_at(builds["new"])[0] or ""
    bases = {"old": build_path(builds["old"], site), "new": site}
    sides_for = dict((p, sides_of(differences, p)) for p in pages)
    jobs = dict((side, [p for p in pages if side in sides_for[p]]) for side, _f in SIDES)
    log("  pictures: %d page(s) differ; %d render(s) to make (four views of each, from each build that has it)"
        % (len(pages), 4 * sum(len(v) for v in jobs.values())))
    reports = {}
    for side, folder in SIDES:
        if jobs[side]:
            reports[side], refused = (runner or run_render)(os.path.join(keep, folder), bases[side], jobs[side],
                                                            os.path.join(shots_dir, side))
            if refused:
                return None, "the two builds are in %s; the pictures could not be made: %s" % (keep, refused)
    lines, empty = [], {}
    member = {"pages": dict((p, _page_entry(p, sides_for[p], reports, shots_dir, lines, empty)) for p in pages)}
    if bases["old"] != bases["new"]:
        lines.append("the old build is shown as served at `%s`, the path its own pages assume (the plugin's at `%s`)"
                     % (_served(bases["old"]), _served(bases["new"])))
    page_file = os.path.join(shots_dir, "compare.html")
    with open(page_file, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(_compare_html(pages, member, sides_for))
    with open(os.path.join(shots_dir, REPORT), "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"reports": reports, "empty": empty, "lines": lines, "bases": bases}, fh, indent=2, sort_keys=True)
        fh.write("\n")
    for line in lines:
        log("  " + line)
    log("  the pictures are in %s: open it (if it shows no pictures, open the PNG files below)" % os.path.abspath(page_file))
    for p in pages:
        for side in sides_for[p]:
            names = sorted(member["pages"][p][side])
            log("    %s, %s build: %s" % (p, side, ", ".join(os.path.join(os.path.abspath(shots_dir), side, n) for n in names)
                                         or "no picture"))
    return member, None


def _report(shots_dir):
    try:
        with open(os.path.join(shots_dir, REPORT), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _verify(pages, differences, member, shots_dir, verb):
    """Refused unless every page has at least one stored picture from each build that has it, each in `shots_dir` with its sha."""
    report = _report(shots_dir)
    for page in pages:
        for side in sides_of(differences, page):
            got = ((member.get("pages") or {}).get(page) or {}).get(side) or {}
            if not got:
                line = (((report.get("empty") or {}).get(page) or {}).get(side)
                        or "no picture of %s from the %s build is stored" % (page, side))
                raise Refused("%s; run `adopt.py %s --keep <dir>` again" % (line, verb))
            for name, sha in sorted(got.items()):
                f = os.path.join(shots_dir, side, name)
                if not os.path.isfile(f):
                    raise Refused("the picture %s/%s is gone from %s; run `adopt.py %s --keep <dir>` again" % (side, name, shots_dir, verb))
                if _sha(f) != sha:
                    raise Refused("the picture %s/%s in %s changed since it was made; run `adopt.py %s --keep <dir>` again"
                                  % (side, name, shots_dir, verb))


def _no_browser(code, finder, verb):
    """The code of a stored `none`, honoured only where the browser is still not found; else Refused."""
    if (finder or find_chrome)()[0]:
        raise Refused("this machine has a browser: run `adopt.py %s --keep <dir>` to make the pictures" % verb)
    return code


def check_accept(prev, res, shots_dir=None, finder=None):
    """`parity --accept`: the line the accept adds ("accepted with the pictures of <n> page(s)", "accepted without pictures:
    chrome-not-found"), None when no `page` row needs a picture, or Refused saying which part does not hold and what to run."""
    stale = stale_parity(prev)
    if stale:
        raise Refused("the stored parity showed you nothing this site-studio measured; run `adopt.py parity`, read it, then "
                      "accept (the stored one was %s)" % stale)
    rows = res.get("open") or []
    if [dict(r) for r in (prev or {}).get("open") or []] != rows:
        raise Refused("the ACCEPT candidates are not the ones the last `parity` stored; %s, read them and the pictures, then "
                      "accept" % (KEEP_AGAIN % "parity"))
    pages = page_paths(rows)
    if not pages:
        return None
    member = (prev or {}).get("shots")
    if not member:
        raise Refused("run `adopt.py parity --keep <dir>` first: it makes the pictures of each page that differs")
    if "none" in member:
        return "accepted without pictures: %s" % _no_browser(member["none"], finder, "parity")
    if not shots_dir:
        raise Refused("name the pictures to accept: `adopt.py parity --accept --shots <dir>/shots`, the folder `parity --keep` "
                      "printed")
    _verify(pages, res["differences"], member, shots_dir, "parity")
    return "accepted with the pictures of %d page(s)" % len(pages)


class Pictures(object):
    """What `for_parity` decided for one run: the `shots` member to store (None: none), and a refusal to end the run with."""

    def __init__(self, res, member=None, refusal=None):
        self.res, self.member, self.refusal = res, member, refusal

    def store(self, entry):
        """Put `open` and `shots` into the plan's parity entry."""
        if "open" in self.res:
            entry["open"] = [dict(r) for r in self.res["open"]]
        if self.member is not None:
            entry["shots"] = self.member

    def finish(self):
        """After everything is printed and the plan saved: a browser that would not start ends the run as a refusal."""
        if self.refusal:
            raise Refused(self.refusal)


def for_parity(res, prev, keep=None, shots_dir=None, accepting=False, log=print, runner=None, finder=None):
    """`cmd_parity`'s one call. Accepting: `check_accept` (Refused, or its line added to the reason the plan stores) and the
    stored pictures carried. `--keep`: the pictures made now. Otherwise the stored `shots` are carried only when the new measure's
    `differences` and `open` equal the stored ones; else they go with the rest of the stale measure."""
    if accepting:
        line = check_accept(prev, res, shots_dir, finder)
        if line:
            res["reason"] = "%s; %s" % (res["reason"], line) if res.get("reason") else line
        return Pictures(res, (prev or {}).get("shots"))
    if keep and res.get("kept") and "open" in res:
        member, refusal = make_pictures(keep, res["open"], res["differences"], log, runner, finder)
        return Pictures(res, member, refusal)
    if (prev and not stale_parity(prev) and prev.get("shots") and [list(d) for d in prev.get("differences") or []]
            == [list(d) for d in res["differences"]] and prev.get("open") == res.get("open")):
        return Pictures(res, prev["shots"])
    return Pictures(res)


def for_remeasure(res, accept=False, keep=None, shots_dir=None, log=print, runner=None, finder=None):
    """`cmd_remeasure`'s one call. `--keep DIR` makes the pictures and writes DIR/shots/shots.json (the differences and `open`
    rows it measured, each PNG's name and sha256, or the `none` code); `--accept` returns the commit message's tail, "(pictures of
    <n> page(s), manifest <12 hex>)" or "(no pictures: chrome-not-found)", or Refused unless shots.json's differences equal the new
    measure and every page has at least one picture from each build that has it, each file matching. The record's shape is not
    touched (its reader is strict): the trace in the repo is that commit message."""
    if keep and res.get("kept") and "open" in res:
        member, refusal = make_pictures(keep, res["open"], res["differences"], log, runner, finder)
        if refusal:
            raise Refused(refusal)
        os.makedirs(os.path.join(keep, SHOTS_DIR), exist_ok=True)
        with open(os.path.join(keep, SHOTS_DIR, MANIFEST), "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"differences": [list(d) for d in res["differences"]], "open": res["open"], "shots": member}, fh,
                      indent=2, sort_keys=True)
            fh.write("\n")
    if not accept:
        return ""
    pages = page_paths(res.get("open"))
    if not pages:
        return ""
    if not shots_dir:
        return " (no pictures: %s)" % _no_browser(NONE_CODES[0], finder, "remeasure")
    try:
        with open(os.path.join(shots_dir, MANIFEST), "rb") as fh:
            raw = fh.read()
        manifest = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError):
        raise Refused("%s holds no readable %s; run `adopt.py remeasure --keep <dir>` again" % (shots_dir, MANIFEST))
    if manifest.get("differences") != [list(d) for d in res["differences"]] or manifest.get("open") != res.get("open"):
        raise Refused("the pictures in %s were made of other differences than these; run `adopt.py remeasure --keep <dir>` "
                      "again" % shots_dir)
    member = manifest.get("shots") or {}
    if "none" in member:
        return " (no pictures: %s)" % _no_browser(member["none"], finder, "remeasure")
    _verify(pages, res["differences"], member, shots_dir, "remeasure")
    return " (pictures of %d page(s), manifest %s)" % (len(pages), hashlib.sha256(raw).hexdigest()[:12])
