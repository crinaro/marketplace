#!/usr/bin/env python3
"""resume_report.py: the resume and LinkedIn coverage report (design-presence-report.md §5). It stores nothing it
prints and writes nothing.

    resume_report.py [--surface print|public-profile|all] [--json]    the six sections, then the --gaps block
    resume_report.py --gaps [--attended] [--json]                     scanned:, GAP lines, questions, one DISPATCH: line
    resume_report.py --packet [--attended]                            the optimizer's brief for the dispatched gaps
    resume_report.py --topics                                         every topic with its role count (§8.1)

Advisory: always exit 0, or 2 on a bad flag. A section that cannot read a source prints `NOT CHECKED (<reason>)`,
never an empty result; an unchecked input is named on the `scanned:` line and makes the clean "no" impossible
(`DISPATCH: no (NOT CHECKED: <inputs>)`). The `DISPATCH:` line is computed in `presence/gaps.py`; the weekly review
relays it. `record.py presence-propose --dispatched` asks `--gaps --json` for the dispatchable set (§R3-2).

**Variant state arrives by one subprocess contract** (§11): this entry point runs `resume_variants.py --json` once,
with its own interpreter and the profile root pinned, and hands the parsed rows to the capability modules. A non-zero
exit or unparseable output is `variants: unreadable`; `present: false`, or no active row, is `variants: none
declared`. Neither is read as "no variants, so no gaps".

Python 3.9+, stdlib only."""

import argparse
import datetime
import json
import os
import subprocess
import sys

import config_keys
from _root import profile_root
from presence import bullets, changes, gaps, linkedin, outcomes, posture_cfg, report_text, requirements, titles
from presence.union_text import bullets_with_sections, read_union
from presence import store_rules as presence_rules

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
SURFACES = ("print", "public-profile", "all")
# resume_variants states whose row names no file this report can place and read
UNPLACEABLE = ("unreadable", "missing-file", "unplaced")
DEFAULT_RENDER_MODE = "local_docx"   # == variant_out.DEFAULT_MODE (an entry point), pinned by tests/test_resume_report.py
HANDBACK = os.path.join(".jobsearch", "handbacks", "profile-optimizer-%s-%d.jsonl")


def build_parser():
    ap = argparse.ArgumentParser(prog="resume_report.py",
                                 description="The resume and LinkedIn coverage report. Writes nothing.")
    ap.add_argument("--surface", choices=SURFACES, default="all",
                    help="the variants the sections show: print, public-profile, or all (default)")
    ap.add_argument("--json", action="store_true", help="the same report as one JSON object")
    form = ap.add_mutually_exclusive_group()
    form.add_argument("--gaps", action="store_true", help="scanned:, GAP lines, questions and the DISPATCH: line")
    form.add_argument("--packet", action="store_true", help="the profile-optimizer brief for the dispatched gaps")
    form.add_argument("--topics", action="store_true",
                      help="every stored fit.requirements[] topic with the number of roles that carry it")
    ap.add_argument("--attended", action="store_true",
                    help="the candidate is present: ASK: lines, and refused gaps are dispatchable")
    return ap


def read_json_lines(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()], None
    except (OSError, ValueError) as e:
        return None, "%s cannot be read (%s)" % (os.path.basename(path), type(e).__name__)


def read_config(root):
    try:
        with open(os.path.join(root, "config.json"), encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError) as e:
        return None, "config.json cannot be read (%s)" % e
    return (cfg, None) if isinstance(cfg, dict) else (None, "config.json is not an object")


def read_variants(root):
    """`(readable variants [{id, file, surface, status, state, text}], reason or None)` via `resume_variants.py
    --json`. A variant the report cannot place or read is left out and named in the reason."""
    env = dict(os.environ, CLAUDESEARCH_ROOT=root)
    try:
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "resume_variants.py"), "--json"],
                           capture_output=True, text=True, env=env, timeout=120)
        rep = json.loads(r.stdout) if r.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        return [], "the variant report is unreadable (%s)" % type(e).__name__
    if not isinstance(rep, dict):
        return [], "the variant report is unreadable (exit %d)" % r.returncode
    active = [v for v in rep.get("variants") or () if v.get("status") != "retired" and v.get("state") != "retired"]
    if not rep.get("present") or not active:
        return [], "none declared"
    out, bad = [], []
    for v in active:
        if v.get("state") in UNPLACEABLE:
            bad.append("%s is %s" % (v.get("id"), v.get("state")))
            continue
        try:
            with open(os.path.join(root, v["file"]), encoding="utf-8") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError, KeyError, TypeError) as e:
            bad.append("%s file cannot be read (%s)" % (v.get("id"), type(e).__name__))
            continue
        out.append(dict(v, text=text, bullets=[b for b, _s in bullets_with_sections(text)]))
    return out, ("variant " + "; ".join(bad)) if bad else None


def read_presence(root):
    """`(checked rows, None)` or `([], reason)`: a store that does not hold is never replayed (§8.2)."""
    data = os.path.join(root, "data")
    try:
        rows = presence_rules.load_file(os.path.join(data, presence_rules.STORE_FILE))
    except presence_rules.PresenceStoreError as e:
        return [], str(e)
    problems = presence_rules.check_rows(rows, presence_rules.variant_rows(data))
    return (rows, None) if not problems else ([], "%d problem(s); first: %s" % (len(problems), problems[0]))


def gather(root):
    """Every input the sections read, and `{input: reason}` for the ones that could not be checked."""
    cfg, cfg_err = read_config(root)
    unchecked = {}
    tl = titles.usable(((cfg or {}).get("targets") or {}).get("titles"))
    if cfg_err or not tl:
        unchecked["titles"] = cfg_err or "targets.titles is empty"
    variants, why = read_variants(root)
    if why:
        unchecked["variants"] = why
    text = read_union(root)
    if text is None:
        unchecked["union"] = "presence/claims.md is missing or unreadable"
    opps, opps_err = requirements.read_opportunities(root)
    rows = requirements.requirement_rows(requirements.pursued(opps or []))
    if opps_err or not rows:
        unchecked["roles"] = opps_err or "no pursued role carries a requirement row"
    apps, apps_err = read_json_lines(os.path.join(root, "data", "applications.jsonl"))
    prows, prows_err = read_presence(root)
    try:
        silence = config_keys.describe(cfg or {}, config_keys.ATS_SILENCE_DAYS)[0]
    except Exception:                                   # noqa: BLE001 - the funnel's own fallback
        silence = config_keys.ATS_SILENCE_DAYS_DEFAULT
    mode = None if cfg_err else (((cfg.get("writing") or {}).get("resume_output") or {}).get("mode")
                                 or DEFAULT_RENDER_MODE)
    return {"root": root, "cfg_err": cfg_err, "titles": [] if "titles" in unchecked else tl, "variants": variants,
            "union": None if text is None else [b for b, _s in bullets_with_sections(text)], "opps": opps,
            "opps_err": opps_err, "rows": rows, "apps": apps, "apps_err": apps_err, "presence": prows,
            "presence_err": prows_err, "silence": silence, "mode": mode,
            "posture": posture_cfg.read(root)}, unchecked


def shown(inp, surface):
    return [v for v in inp["variants"] if surface == "all" or v.get("surface") == surface]


def _variants_note(unchecked):
    return [report_text.not_checked("variants: %s" % unchecked["variants"])] if "variants" in unchecked else []


def section_title(inp, unchecked, surface):
    out = [report_text.header("title")]
    if "titles" in unchecked:
        return out + [report_text.not_checked(unchecked["titles"])], []
    found = []
    for v in shown(inp, surface):
        lines, gap = titles.variant_section(v, inp["titles"])
        out.extend(lines)
        found += [dict(gap, surface=v.get("surface"))] if gap else []
    head, hrow = changes.current(inp["presence"], "linkedin", "headline")
    if hrow is not None:
        out.extend(titles.headline_lines(head, hrow.get("created"), inp["titles"])[0])
    return out + _variants_note(unchecked) + ["  " + titles.LIMITS], found


def section_requirements(inp, unchecked):
    out = [report_text.header("requirements")]
    if "roles" in unchecked:
        return out + [report_text.not_checked(unchecked["roles"])], []
    rows = inp["rows"]
    out.append("  %d of %d requirement rows carry no topic; they are grouped only on identical wording"
               % (sum(1 for _o, q in rows if not q.get("topic")), len(rows)))
    lines, found = requirements.not_aligned_lines(rows)
    out.extend(lines)
    printed = [v for v in inp["variants"] if v.get("surface") == "print"]
    if inp["union"] is None or not printed:
        why = ("union: %s" % unchecked["union"] if inp["union"] is None else "variants: %s" % unchecked["variants"]
               if "variants" in unchecked else "no print-surface variant")
        return out + ["  (b) in the union, on no printed variant:", report_text.not_checked(why, "    ")], found
    lines, more = requirements.claim_lines(rows, requirements.union_index(inp["union"]), printed)
    return out + lines + _variants_note(unchecked), found + more


def section_outcomes(inp):
    out = [report_text.header("outcomes")]
    if inp["apps_err"] or inp["opps_err"]:
        return out + [report_text.not_checked(inp["apps_err"] or inp["opps_err"])]
    return out + outcomes.section_lines(inp["opps"], inp["apps"], inp["silence"], [v["id"] for v in inp["variants"]])


def section_linkedin(inp, unchecked):
    out = [report_text.header("linkedin")]
    if inp["presence_err"]:
        unchecked["linkedin"] = "presence_changes: %s" % inp["presence_err"]
        return out + [report_text.not_checked(unchecked["linkedin"])], [], None
    rows, index = inp["rows"], requirements.union_index(inp["union"] or [])
    top = requirements.top_topics(rows, linkedin.TOP_TOPICS)
    cited = {t: requirements.cited_claims(rows, t, index) for t in top}
    lines, found, why, question = linkedin.section(inp["presence"], inp["titles"], top, cited, inp["union"])
    if why:
        unchecked["linkedin"] = why
    return out + lines, found, question


def build(root, surface, attended):
    inp, unchecked = gather(root)
    title_lines, raw = section_title(inp, unchecked, surface)
    req_lines, more = section_requirements(inp, unchecked)
    li_lines, li_gaps, li_question = section_linkedin(inp, unchecked)
    sections = {"title": title_lines, "requirements": req_lines,
                "quantified": [report_text.header("quantified")] + [bullets.variant_line(v) for v in shown(inp, surface)]
                + _variants_note(unchecked) + ["  " + bullets.LIMITS],
                "outcomes": section_outcomes(inp),
                "readability": [report_text.header("readability"),
                                report_text.not_checked(inp["cfg_err"]) if inp["mode"] is None
                                else "  " + report_text.readability_line(inp["mode"])],
                "linkedin": li_lines}
    judged = gaps.judge(gaps.with_pools(raw, inp["union"]) + more + li_gaps, inp["presence"], inp["presence_err"],
                        attended)
    untopiced = sum(1 for _o, q in inp["rows"] if not q.get("topic"))
    questions = [q for q in (li_question, "%d requirement rows of pursued roles carry no topic (record.py fit-key "
                             "<opp_id> <index> --topic <slug>)" % untopiced if untopiced else None) if q]
    counts = {"variants": len(inp["variants"]), "roles": len({o for o, _q in inp["rows"]}), "rows": len(inp["rows"]),
              "titles": len(inp["titles"])}
    block, keys = gaps.block(judged, counts, unchecked, questions, inp["posture"], attended)
    return {"inp": inp, "sections": sections, "unchecked": unchecked, "judged": judged, "gaps_block": block,
            "keys": keys}


def handback_path(root, rows):
    """`<profile root>/.jobsearch/handbacks/profile-optimizer-<date>-<n>.jsonl`, `<n>` the lowest number no file
    holds and no stored row has consumed (so a missing hand-back's path is never handed out twice)."""
    today, n = datetime.date.today().isoformat(), 1
    while True:
        path = os.path.abspath(os.path.join(root, HANDBACK % (today, n)))
        if not os.path.exists(path) and not changes.consumed_by(rows, path):
            return path
        n += 1


def as_json(rep):
    keep = ("key", "status", "state", "draftable", "dispatchable", "why_not")
    return {"sections": rep["sections"], "unchecked": rep["unchecked"], "gaps_block": rep["gaps_block"],
            "gaps": [{k: g.get(k) for k in keep} for g in rep["judged"]],
            "dispatchable": [g["key"] for g in rep["judged"] if g["dispatchable"]],
            "dispatch": rep["gaps_block"][-1], "keys": rep["keys"]}


def main(argv=None):
    args = build_parser().parse_args(argv)
    root = profile_root()
    if args.topics:
        opps, why = requirements.read_opportunities(root)
        print("topics: NOT CHECKED (%s)" % why if opps is None else "\n".join(requirements.topics_lines(opps)))
        return 0
    rep = build(root, args.surface, args.attended)
    if args.packet:
        inp = rep["inp"]
        if not rep["keys"]:
            print("PACKET: none (%s)" % rep["gaps_block"][-1])
            return 0
        path = handback_path(root, inp["presence"])
        print("\n".join(gaps.packet_lines(rep["judged"], rep["keys"], inp["titles"], inp["union"], path)))
        return 0
    if args.json:
        print(json.dumps(as_json(rep), indent=1, sort_keys=True))
        return 0
    lines = [] if args.gaps else [l for name, _label in report_text.SECTIONS for l in rep["sections"][name]] + [""]
    print("\n".join(lines + rep["gaps_block"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
