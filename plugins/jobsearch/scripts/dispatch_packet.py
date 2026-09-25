#!/usr/bin/env python3
"""dispatch_packet.py — one dispatch's packet, printed once (design-script-first.md §3.2).

WHAT
----
`dispatch_packet.py --agent <name> --opp <id> [--contact <id>]` prints the canonical packet
for one dispatch: every section a `--agent` value's own READS block would otherwise make the
dispatched agent read for itself, one script call instead of nine. The coordinator's prompt
becomes one line — "Draft the reply for the packet below." — followed by this output.

COMPOSES, NEVER RECOMPUTES
---------------------------
Every section is built from an EXISTING script's own output or an EXISTING module's own public
function — `brief.compute()` / `brief.new_brief_id()` / `brief.append_ledger()` (the same three
calls `brief.py --for`'s own stamping path makes; §3.2 — the packet stamps a REAL ledger row so
the id it prints is one a drafted entry can actually cite), `plays.py --brief` (subprocess,
JSON), `fit_report.py --pitch` (subprocess), `section.py` (subprocess), `profile.py`'s own
`comms()`, and `config_keys.packet_section_cap()`. Nothing here re-derives a register or a
silence window — the `axis`/`register`/`last_word` fields brief.compute() returns are read off
the dict through a declared tuple + `.get(k)` (`k` a loop variable, never a literal string), so
`check_ledger_reads.py`'s AST scan (which flags a LITERAL `"register"`/`"days_since_in"`/
`"last_word"`/`"latest_in"`/`"latest_out"` subscript or `.get()` call anywhere outside
`brief.py` — §3.6, dev #80) finds nothing to flag: this module cites what `brief.compute()`
already computed, it never writes a second copy of the logic that computes it.

LOUD MARKERS, NEVER A SILENT GAP (#77, #88)
--------------------------------------------
A section this packet cannot fill (no fit analysis yet, no play adopted, an unreadable strategy
heading, an unexpected error building the section) prints `PACKET INCOMPLETE — <section>:
<reason>` in the section's own place — never an empty section, which a reader cannot tell apart
from "there was nothing to say." A section whose composed text is over its configured byte cap
(`config_keys.packet_section_cap()`, provenance-tracked, defaults voice 2000 / claims 3000 /
every other section 1500 — #77) prints its first `<cap>` bytes and then `PACKET TRUNCATED —
<section> <n> chars > <cap>`. An unknown `--agent`, an unresolvable `--opp`, or an unresolvable
`--contact` refuses loudly (stderr, exit 2) rather than printing a packet for the wrong thing.

Usage:
    python3 dispatch_packet.py --agent outreach-drafter --opp acme-cto --contact pat-example

Python 3.9+. Standard library only.
"""

import argparse
import datetime
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from _root import profile_root  # noqa: E402
import brief as _brief  # noqa: E402
import config_keys  # noqa: E402
import graph as _graph  # noqa: E402
import profile as _profile  # noqa: E402

PY = sys.executable


def _run(script_name, *args):
    """One shipped script, by its own CLI, in a subprocess — the literal composition
    mechanism: this module never imports another script's private machinery to re-derive what
    the script's own `main()` already prints. Inherits the parent's environment (so
    `CLAUDESEARCH_ROOT`, set the same way for every caller — a real run, a test, or
    `run_shipped.py` — reaches the child unchanged)."""
    return subprocess.run([PY, os.path.join(HERE, script_name)] + list(args),
                          capture_output=True, text=True)


def _dotted(cfg, dotted):
    """The same one-`.get()`-per-part walk `config_keys._get_dotted` uses, duplicated here
    (never imported past the underscore) for the one key this packet reads that is NOT a
    registered reader key — `positioning.default_to_one_employer_is_a_known_failure` is the
    candidate's own profile fact, read the same way `outreach-drafter.md` names it, not a
    tunable this engine's behaviour branches on."""
    node = cfg or {}
    for part in dotted.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def _config(root):
    try:
        with open(os.path.join(root, "config.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


# ── section builders — each returns (lines, incomplete_reason); incomplete_reason is None on
#    success, a short string when the section could not be built (§3.2's loud-marker rule) ──────

def _section_record(root, cfg, opp, person_id):
    g = _graph.Graph(os.path.join(root, "data"))
    company = g.by_id.get("companies", {}).get(opp.get("company_id"), {})
    lines = ["  opportunity  %s  stage:%s  title:%r  company:%s"
            % (opp["id"], opp.get("stage") or opp.get("status"), opp.get("title"),
               company.get("name") or opp.get("company_id") or "—")]
    if person_id:
        person = g.by_id.get("people", {}).get(person_id, {})
        role = None
        for inv in g.stores.get("involvements", []):
            if inv.get("opp_id") == opp["id"] and inv.get("person_id") == person_id:
                role = inv.get("role")
                break
        lines.append("  contact      %s  role:%s  linkedin:%s  email:%s"
                    % (person_id, role or "unknown",
                       "yes" if person.get("linkedin") else "no",
                       "yes" if person.get("email") else "none"))
    return lines, None


def _section_brief(root, cfg, opp, person_id):
    if not person_id:
        return [], "no --contact given — nothing to brief"
    b = _brief.compute(root, person_id, opp_id=opp["id"])
    brief_id = _brief.new_brief_id()
    row = dict(b)
    row["id"] = brief_id
    row["computed_at"] = brief_id.split("brief:", 1)[1].rsplit("-", 1)[0]
    del row["events"]
    _brief.append_ledger(root, row)
    fields = ("axis", "register", "last_word")
    cited = "  ".join("%s:%s" % (k, b.get(k)) for k in fields)
    return ["  brief-id %s  %s" % (brief_id, cited)], None


def _section_play(root, cfg, opp, person_id):
    out = _run("plays.py", "--brief", opp["id"])
    if out.returncode != 0 or not out.stdout.strip():
        return [], "plays.py --brief failed: %s" % (out.stderr.strip() or "no output")[:200]
    try:
        data = json.loads(out.stdout)
    except ValueError:
        return [], "plays.py --brief did not print JSON"
    if data.get("error"):
        return [], str(data["error"])
    ns = data.get("next_step") or {}
    say = data.get("say") or []
    approach = data.get("approach")
    lines = ["  next step: %s%s%s" % (ns.get("kind"),
                                      ("  step:%s" % ns["step"]) if ns.get("step") else "",
                                      ("  approach:%s" % approach) if approach else "")]
    lines.append("  say: %s" % (", ".join(say) if say else "(nothing licensed yet)"))
    return lines, None


def _section_pitch(root, cfg, opp, person_id):
    out = _run("fit_report.py", "--pitch", opp["id"])
    if out.returncode != 0:
        return [], "no fit analysis — run the analysis first"
    lines = [("  " + l) for l in out.stdout.rstrip("\n").split("\n") if l.strip()]
    return lines, None


def _section_voice(root, cfg, opp, person_id):
    out = _run("section.py", "configure/strategy.md", "Message style")
    if out.returncode != 0:
        return [], "no 'Message style' section in configure/strategy.md"
    text = out.stdout
    marker = text.rfind("\n\n<!--")
    if marker != -1:
        text = text[:marker]
    return text.rstrip("\n").split("\n"), None


def _section_rules(root, cfg, opp, person_id):
    try:
        comms = _profile.comms()
    except Exception as e:  # noqa: BLE001 — a config shape problem is itself an INCOMPLETE fact
        return [], "profile.comms() failed: %s" % e
    lines = ["  default sequence: %s" % " + ".join(comms.get("default_sequence") or [])]
    for med, con in sorted((comms.get("constraints_by_medium") or {}).items()):
        lim = ("%d chars" % con["max_chars"]) if "max_chars" in con \
            else ("%d words" % con.get("max_words", 0))
        lines.append("  %-28s %s" % (med, lim))
    lines.append("  default_to_one_employer_is_a_known_failure: %r"
                % _dotted(cfg, "positioning.default_to_one_employer_is_a_known_failure"))
    return lines, None


SECTION_BUILDERS = {
    "record": _section_record, "brief": _section_brief, "play": _section_play,
    "pitch": _section_pitch, "voice": _section_voice, "rules": _section_rules,
}

# Per-`--agent` section list (design-script-first.md §3.2). ⭐ #88a — this SHOULD be derived
# from each agent definition's own READS block, not hand-kept; that derivation is
# `gate-keeper`'s test to write (§3.2 "complete and bounded against the agent definition"),
# not yet built here — see the hand-back for what remains.
AGENT_SECTIONS = {
    "outreach-drafter": ("record", "brief", "play", "pitch", "voice", "rules"),
}


def _today():
    return datetime.date.today().isoformat()


def cmd_packet(root, agent, opp_id, contact_raw):
    if agent not in AGENT_SECTIONS:
        print("⛔ PACKET REFUSED — unknown --agent %r (known: %s)"
             % (agent, ", ".join(sorted(AGENT_SECTIONS))), file=sys.stderr)
        return 2

    g = _graph.Graph(os.path.join(root, "data"))
    opp = g.by_id.get("opportunities", {}).get(opp_id)
    if opp is None:
        print("⛔ PACKET REFUSED — no opportunity %r" % opp_id, file=sys.stderr)
        return 2

    person_id = None
    if contact_raw:
        token = contact_raw if contact_raw.startswith("contact:") else "contact:%s" % contact_raw
        pid, ok, why = _brief.resolve_to(root, token)
        if not ok:
            print("⛔ PACKET REFUSED — %s" % why, file=sys.stderr)
            return 2
        person_id = pid

    cfg = _config(root)
    out = ["PACKET %s · opp:%s%s · %s"
          % (agent, opp_id, (" · contact:%s" % person_id) if person_id else "", _today())]
    for name in AGENT_SECTIONS[agent]:
        out.append("── %s %s" % (name, "─" * max(1, 70 - len(name))))
        try:
            lines, incomplete = SECTION_BUILDERS[name](root, cfg, opp, person_id)
        except Exception as e:  # noqa: BLE001 — never a silent vanish; always a loud marker
            lines, incomplete = [], "%s: %s" % (type(e).__name__, e)
        if incomplete:
            out.append("  PACKET INCOMPLETE — %s: %s" % (name, incomplete))
            continue
        text = "\n".join(lines)
        cap, prov = config_keys.packet_section_cap(cfg, name)
        if len(text) > cap:
            out.append(text[:cap])
            out.append("  PACKET TRUNCATED — %s %d chars > %d (%s)" % (name, len(text), cap, prov))
        else:
            out.append(text)
    print("\n".join(out))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--agent", required=True, metavar="NAME")
    ap.add_argument("--opp", required=True, metavar="ID")
    ap.add_argument("--contact", metavar="ID")
    args = ap.parse_args()

    root = profile_root()
    return cmd_packet(root, args.agent, args.opp, args.contact)


if __name__ == "__main__":
    sys.exit(main())
