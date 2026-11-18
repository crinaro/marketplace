"""adoption.classify -- the per-file classifier and the namesake (shadow) rule.

Part of the `adoption` package behind the entry point `adopt.py`. Documentation that was in `adopt.py`'s docstring about this module's code:

THE CLASSIFIER (design 6.4.2). Per file: a SCORE per capability (summed weight of its signals found
/ its total signal weight) and a RESIDUAL (units no signal of the matched capability explains /
all units). Units: a paragraph or list item for Markdown, a top-level function or statement for
code, a top-level key for package.json. Blank lines, comments, headings and front matter are not
units. Classes: DUPLICATE, PARTIAL, AMBIGUOUS, CUSTOM, MIXED, DATA (the thresholds live in the
spec). The file name is one signal, never sufficient and never required (tested for every
capability). NAMESAKES (dev #851, design 7.6): an agent file named like one of the plugin's agents gets a
SHADOW warning WHATEVER ITS CLASS, because a project agent outranks a plugin agent of the same name when it
is called by its bare name (and adopt can see only this repo's `.claude/agents/`, never the person's
`~/.claude/agents/`). If it also scores at or above the match threshold against that agent's capability it
is a SELF-MATCH: DUPLICATE or PARTIAL, never AMBIGUOUS. If it does not, it keeps the class it earned and
carries `namesake` [capability, score]; the name alone never makes a match.
"""

import os
import posixpath

from adoption.base import PLUGIN
from adoption.spec import _applicable, _sig_found, score_capability
from adoption.units import driver_explained, units_of

AGENTS_DIR = os.path.join(PLUGIN, "agents")
CODE_EXTS = (".js", ".mjs", ".cjs", ".py", ".sh", ".bash", ".zsh", ".json")


def file_kind(path):
    parts = path.split("/")
    base = parts[-1]
    if "node_modules" in parts or base in (".DS_Store", "package-lock.json"):
        return None
    if path == "CLAUDE.md" or path == ".claude/settings.json":
        return "mixed"
    if parts[:2] == [".claude", "agents"] and len(parts) == 3 and base.endswith(".md"):
        return "agent"
    if parts[:2] == [".claude", "commands"] and len(parts) >= 3 and base.endswith(".md"):
        return "command"
    if parts[:2] == [".claude", "skills"] and len(parts) == 4 and base == "SKILL.md":
        return "skill"
    if parts[0] in ("scripts", "tools") and len(parts) >= 2:
        if posixpath.splitext(base)[1].lower() in CODE_EXTS:
            if base.lower().endswith(".json") and base != "package.json":
                return None
            return "code"
        return None
    if parts[0] == "site" and len(parts) == 2 and posixpath.splitext(base)[1].lower() in (".js", ".mjs", ".cjs"):
        return "code"
    return None


def classify_text(spec, path, kind, text, as_cap=None, shadows=None):
    """Classify one file. `shadows` is the set of this plugin's agent names (`shadow_names()` when None).

    NAMESAKES (dev #851, design 7.6). An agent file whose STEM equals a plugin agent's name is a
    SELF-MATCH when its score against that agent's capability (the capability id IS the agent's name:
    `test_adopt.RosterCapabilities` asserts it for every agent) is at or above `spec.match`. A self-match
    skips the AMBIGUOUS gap rule and is classified against that capability, DUPLICATE or PARTIAL by the
    residual rule, never AMBIGUOUS: the name is the one signal the platform acts on, but it is NEVER
    sufficient (the capability's name weight stays below `match`, `SpecShape`). A same-named file that is
    NOT a self-match keeps whatever class it earned and gains `namesake`: [capability id, score], however
    low the score; `candidates` keeps its one meaning (the capabilities at or above `match`)."""
    base = posixpath.basename(path)
    units = units_of(kind, path, text)
    scored = []
    for cid, cap in spec.caps.items():
        if as_cap is not None and cid != as_cap:
            continue
        if not _applicable(cap, kind, base):
            continue
        s, found = score_capability(spec, cap, text, base)
        scored.append((s, cid, found))
    scored.sort(key=lambda t: (-t[0], t[1]))
    info = {"path": path, "kind": kind, "units": len(units), "capability": None, "score": 0.0,
            "residual": 0.0, "residual_units": [], "signals": [], "class": "CUSTOM", "candidates": [],
            "needs_parity": False, "best": [(c, round(s, 2)) for s, c, _f in scored[:3]], "namesake": None}
    matches = [t for t in scored if t[0] >= spec.match - 1e-9]
    same = None
    if kind == "agent" and as_cap is None:
        stem = posixpath.splitext(base)[0]
        if stem in (shadows if shadows is not None else shadow_names()) and stem in spec.caps:
            same = stem
    self_hit = next((t for t in matches if t[1] == same), None) if same else None
    if same and self_hit is None:
        info["namesake"] = [same, round(next((s for s, c, _f in scored if c == same), 0.0), 2)]
    if not matches:
        return info
    top = self_hit or matches[0]
    if self_hit is None and as_cap is None and len(matches) > 1 and top[0] - matches[1][0] <= spec.gap + 1e-9:
        info["class"] = "AMBIGUOUS"
        info["candidates"] = [(c, round(s, 2)) for s, c, _f in matches]
        info["capability"] = top[1]
        info["score"] = top[0]
        return info
    cid = top[1]
    cap = spec.caps[cid]
    explainers = [s for s in cap["signals"] if not s.get("name")]
    explained = [any(_sig_found(spec, s, u, base) for s in explainers) for u in units]
    if kind == "code":
        for i in driver_explained(units, explained):
            explained[i] = True
    resid = [{"id": "u%d" % (i + 1), "text": u} for i, u in enumerate(units) if not explained[i]]
    ratio = (len(resid) / float(len(units))) if units else 0.0
    info.update(capability=cid, score=top[0], signals=top[2], residual=ratio, residual_units=resid,
                needs_parity=bool(cap.get("needsParity")))
    info["class"] = "DUPLICATE" if ratio <= spec.residual_max + 1e-9 else "PARTIAL"
    return info


def shadow_names(agents_dir=None):
    """The names of this plugin's own agents: a repo agent with one of these names outranks the plugin's.

    Read from the shipped `agents/` directory, not from `plugins/site-studio/spec/roster.json` (dev #835, gate-keeper G3):
    the roster is a maintenance file that is withheld from the package, so the old read returned an
    empty set on every install and the shadow warning silently never fired. An agents directory that
    is missing or holds no agent is a broken install and refuses loudly instead of reading as "no
    shadows"."""
    d = agents_dir or AGENTS_DIR
    try:
        names = {posixpath.splitext(n)[0] for n in os.listdir(d) if n.endswith(".md")}
    except OSError as e:
        raise RuntimeError("adopt cannot read the plugin's agents directory (%s): %s" % (d, e))
    if not names:
        raise RuntimeError("adopt found no agent in the plugin's agents directory (%s)" % d)
    return names


# The version the scoped-name claim below was measured on (probe P-A, tests/probes/PA-RESULT.md).
SCOPED_DISPATCH_MEASURED = "Claude Code 2.1.325"


def shadow_note(name):
    """The warning for a kept local agent named like one of this plugin's (design 7.6, dev #851). A project
    agent outranks a plugin agent of the same name, whatever the project agent does, so this is said for
    EVERY same-named agent that is kept. It states its own limit: adopt reads this repo's .claude/agents/
    only. The last sentence is the probe-P-A verdict (scoped-wins): the plugin's own review and ideas steps
    dispatch the agents by their scoped names, which reached the plugin's agent past a same-named project
    agent when measured; `test_routing.PluginAgentPrecedence` checks this text against that verdict."""
    return ("%s would replace site-studio's %s wherever it is called by its bare name, on this machine and on "
            "any machine this repo is cloned to. Rename it (suggested: %s-local) or remove it. This check "
            "covers this repo's .claude/agents/ only; a same-named agent in your own ~/.claude/agents/ on any "
            "computer also replaces it. site-studio's own review and ideas steps call it as site-studio:%s, "
            "which is not replaced (measured on %s)." % (name, name, name, name, SCOPED_DISPATCH_MEASURED))


def namesake_text(info):
    """How the inventory describes a same-named file next to its class, or None for any other file."""
    if info.get("namesake"):
        cid, score = info["namesake"]
        return "is named like site-studio's %s (score %s, below the match threshold)" % (cid, _fmt_pct(score))
    if info.get("shadows") and info.get("capability") == info["shadows"]:
        return "does the same job as site-studio's %s (score %s)" % (info["shadows"], _fmt_pct(info["score"]))
    return None


def shadow_suffix(info):
    """What the commit's Kept list adds after a kept file's reason when it shares a plugin agent's name."""
    if not info.get("shadows"):
        return ""
    return " (SHADOWS the plugin's %s agent: rename it to %s-local, or remove it)" % (info["shadows"], info["shadows"])


def _fmt_pct(x):
    return "%.2f" % x
