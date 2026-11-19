"""adoption.hookpaths -- what adopt does to hook commands in the site repo's `.claude/settings.json` that name a removed file.

Part of the `adoption` package behind the entry point `adopt.py`; moved out of `apply.py` unchanged. A hook command naming a
file adopt removes is dropped when the plugin's own hook does the same job, rewritten to the plugin's script when the capability
has a counterpart, and otherwise the file is kept (`process_hooks`); `dangling_hook_paths` is the backstop that finds any
remaining hook naming a repo path absent from the new tree."""

import re


_PATH_TOKEN = re.compile(r"(?<![\w./}$-])(?:\$\{?CLAUDE_PROJECT_DIR\}?/|\./)?((?:scripts|tools|site|\.claude)/[A-Za-z0-9_.@+-]+(?:/[A-Za-z0-9_.@+-]+)*)")
_SEGMENT_SPLIT = re.compile(r"\s*(?:;|&&|\|\|)\s*")
_INTERP = re.compile(r"^(?:(?:bash|sh|zsh|node|python3?)\s+)?(?:\$\{?CLAUDE_PROJECT_DIR\}?/|\./)?")


def _segments(command):
    return [s for s in _SEGMENT_SPLIT.split(command) if s.strip()]


def process_hooks(settings, removed, cap_of, spec):
    """Handle hook commands that name a removed file. Returns (settings, listed, blocked) where
    `listed` is [(event, old command, new command or None)] and `blocked` the set of removed paths
    that a remaining hook still needs (they must be kept)."""
    listed, blocked = [], set()
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return settings, listed, blocked
    for event in list(hooks):
        groups = hooks[event]
        if not isinstance(groups, list):
            continue
        new_groups = []
        for g in groups:
            if not isinstance(g, dict) or not isinstance(g.get("hooks"), list):
                new_groups.append(g)
                continue
            kept = []
            for h in g["hooks"]:
                cmd = h.get("command") if isinstance(h, dict) else None
                if not isinstance(cmd, str):
                    kept.append(h)
                    continue
                new_segs, changed = [], False
                for seg in _segments(cmd):
                    m = [x for x in _PATH_TOKEN.finditer(seg) if x.group(1) in removed]
                    if not m:
                        new_segs.append(seg)
                        continue
                    path = m[0].group(1)
                    cap = spec.caps.get(cap_of.get(path) or "", {})
                    if cap.get("hook") == "plugin":
                        changed = True
                        continue
                    if cap.get("hook") == "rewrite" and cap.get("script"):
                        script = 'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/%s"' % cap["script"]
                        new_segs.append(_rewrite_segment(seg, m[0], script))
                        changed = True
                        continue
                    blocked.add(path)
                    new_segs.append(seg)
                if changed:
                    new = "; ".join(new_segs)
                    listed.append((event, cmd, new or None))
                    if new:
                        h2 = dict(h)
                        h2["command"] = new
                        kept.append(h2)
                else:
                    kept.append(h)
            if kept:
                g2 = dict(g)
                g2["hooks"] = kept
                new_groups.append(g2)
        if new_groups:
            hooks[event] = new_groups
        else:
            del hooks[event]
    if not hooks:
        del settings["hooks"]
    return settings, listed, blocked


def _rewrite_segment(seg, m, script):
    """Replace `<interpreter> <path>` with the plugin script, keeping the arguments."""
    start = m.start()
    pre = seg[:start]
    im = re.search(r"(?:bash|sh|zsh|node|python3?)\s+$", pre)
    if im:
        start = im.start()
    return seg[:start] + script + seg[m.end():]


def dangling_hook_paths(settings, post_paths):
    """Repo paths named by remaining hook commands that are absent from the new tree."""
    out = []
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return out
    for event, groups in hooks.items():
        for g in groups if isinstance(groups, list) else []:
            for h in (g.get("hooks") or []) if isinstance(g, dict) else []:
                cmd = h.get("command") if isinstance(h, dict) else None
                if isinstance(cmd, str):
                    for m in _PATH_TOKEN.finditer(cmd):
                        if m.group(1) not in post_paths:
                            out.append((event, m.group(1)))
    return out
