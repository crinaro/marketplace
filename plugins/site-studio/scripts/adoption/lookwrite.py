"""adoption.lookwrite -- the look files adopt carries through the conversion, what `apply` commits of them, the candidates file
parity writes, and the served check (design-adopt-ownership-line sections 2.5, 2.6, 3, 3.1 and 4; step 8).

Part of the `adoption` package behind the entry point `adopt.py`.

  * CARRY (`carry`, called by `settings.apply_settings` for every conversion: `check`, parity's plugin side, `apply`). Both look
    files are adopt's own inputs. `site/looks/local.json`, when the tree holds it, is laid over the look by `lookLocal` and never
    written. `site/looks/derived.json` is derive's reading (the plan's `look` value) with every entry of a committed
    `derived.json` that is the person's (rule E: `lookfiles.stamp`) kept as it is, and its stamp beside it, so `apply`'s one
    commit holds the look and the stamp together. A tree with neither file and no derived look converts as before 0.7.0.
  * THE PERSON'S ENTRIES (`person_entries`): what `adoption.lookperson` measures, one per construct and `reads` target of
    `local.json` and per E2 entry of a committed `derived.json`.
  * CANDIDATES (`candidates_text`, `write_candidates`): derive's reading of every construct it read, mapped or not, written by
    `parity` at the end of a run to `.site-studio/look-candidates.json`, a scratch file (`ADOPT_SCRATCH`), never committed and
    never read by a build. Parity writes nothing under `site/`.
  * SERVED (`served_problems`): neither look file is served. The old builder runs on a copy of the working copy, which holds a
    look file whenever the commit does; a file in its output whose bytes equal either look file is a refusal naming the file.
"""

import json
import os

import looks
from configschema.configkeys import CANDIDATES_REL, DERIVED_LOOK_PATH, LOOK_LOCAL_PATH, STAMP_REL
from lookfiles import stamp

CANDIDATES_SCHEMA = 1
COPY_LINE = ('look: %s %s (%s%s); the closest reading is in %s: copy "%s" into %s, correct it, commit it, then run adopt.py '
             'parity again')


def _root(view):
    """(repo, ref) of the git tree under a conversion's view (an `Overlay` over a `Tree`), or (None, None) for a tree with no
    history (a test's `PathTree`)."""
    base = view
    while hasattr(base, "base"):
        base = base.base
    return getattr(base, "repo", None), getattr(base, "ref", None)


def _json(view, path):
    try:
        data = json.loads(view.read(path).decode("utf-8"))
    except (KeyError, ValueError, UnicodeDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def committed_ownership(view):
    """(the committed `derived.json` as a dict, its `stamp.Ownership`), or (None, None) when the tree holds no such file."""
    old = _json(view, DERIVED_LOOK_PATH) if view.exists(DERIVED_LOOK_PATH) else None
    if old is None:
        return None, None
    files = {DERIVED_LOOK_PATH: view.read(DERIVED_LOOK_PATH)}
    if view.exists(STAMP_REL):
        files[STAMP_REL] = view.read(STAMP_REL)
    repo, ref = _root(view)
    return old, stamp.ownership_at(files, DERIVED_LOOK_PATH, repo, ref or "HEAD")


def carry(view, files, d, value, notes):
    """Lay the look over the converted tree (`files` and `d`, site.json's dict, changed in place). `value` is the `look`
    setting's value (a derived look {"id", "file"}, or None: the default look). The stamp names this site-studio's version."""
    if isinstance(value, dict) and value.get("file"):
        target = "site/looks/%s.json" % value.get("id", "derived")
        old, own = committed_ownership(view) if target == DERIVED_LOOK_PATH else (None, None)
        if own is None:
            files[target] = value["file"].encode("utf-8")
            if target == DERIVED_LOOK_PATH:
                hashes = stamp.entry_hashes(json.loads(value["file"]))
                files[STAMP_REL] = stamp.stamp_text(hashes, target, stamp.plugin_version()).encode("utf-8")
        else:
            written, lines = stamp.files_for(value["file"], old, own, target, stamp.plugin_version())
            files.update(written)
            notes["settings"].extend("look: %s" % line for line in own.lines + lines)
        d["look"] = target
        notes["settings"].append("look: a look derived from your own pages, vendored at %s" % d["look"])
    if view.exists(LOOK_LOCAL_PATH) and LOOK_LOCAL_PATH not in (notes.get("removed") or ()):
        d["lookLocal"] = LOOK_LOCAL_PATH
        notes["settings"].append("lookLocal: your own look %s is laid over the look, construct by construct" % LOOK_LOCAL_PATH)


class Entry(object):
    """One of the person's look entries: `name` (`look.<construct>`, `look.<named construct>` or `reads.<target>`), `key` (the
    stamp's entry name: the construct, `named:<name>` or `reads:<target>`), `file` (the look file that holds it), `sha256` (its
    hash), `edited` (an E2 entry of `derived.json`) and `construct` (the plugin construct it renders as: a `reads` target's, a
    named construct's base)."""

    def __init__(self, name, key, file, sha256, edited=False, construct=None):
        self.name, self.key, self.file, self.sha256, self.edited = name, key, file, sha256, edited
        self.construct = construct or key


def _entries_of(data, file, keys, edited):
    hashes = stamp.entry_hashes(data or {})
    out = []
    for key in sorted(k for k in hashes if k in keys and k != stamp.STYLESHEETS):
        kind, _sep, rest = key.partition(":")
        if kind == "reads":
            out.append(Entry("reads." + rest, key, file, hashes[key], edited, rest.split(".")[0]))
        elif kind == "named":
            like = ((data.get("named") or {}).get(rest) or {}).get("like")
            out.append(Entry("look." + rest, key, file, hashes[key], edited, like if isinstance(like, str) else rest))
        else:
            out.append(Entry("look." + key, key, file, hashes[key], edited))
    return out


def person_entries(view):
    """The person's entries in the tree `view`: every construct and `reads` target of `local.json` (when the tree holds it), then
    every E2 entry of a committed `derived.json` that `local.json` does not replace."""
    local = _json(view, LOOK_LOCAL_PATH) if view.exists(LOOK_LOCAL_PATH) else None
    out = _entries_of(local, LOOK_LOCAL_PATH, set(stamp.entry_hashes(local or {})), False)
    old, own = committed_ownership(view)
    if own is not None:
        held = set(e.key for e in out)
        out += [e for e in _entries_of(old, DERIVED_LOOK_PATH, own.yours, True) if e.key not in held]
    return out


def without(files, entries, reading=None):
    """`files` ({path: bytes}, a converted tree) with the person's `entries` taken out: removed from `local.json` (which stays
    laid, possibly empty), and in `derived.json` replaced by derive's `reading` (a look dict) or, where it has none, removed (the
    default renders). Nothing is written to disk."""
    out = dict(files)
    for path in (LOOK_LOCAL_PATH, DERIVED_LOOK_PATH):
        mine = [e for e in entries if e.file == path]
        if not mine or path not in out:
            continue
        data = json.loads(out[path].decode("utf-8"))
        for e in mine:
            if e.key.startswith("named:"):                 # derive never writes one: taken out, the name is unknown again
                (data.get("named") or {}).pop(e.key[len("named:"):], None)
                continue
            if e.key.startswith("reads:"):
                t = e.key[len("reads:"):]
                (data.get("reads") or {}).pop(t, None)
                if path == DERIVED_LOOK_PATH and t in ((reading or {}).get("reads") or {}):
                    data.setdefault("reads", {})[t] = reading["reads"][t]
                continue
            (data.get("constructs") or {}).pop(e.key, None)
            (data.get("assets") or {}).pop(e.key, None)
            if path == DERIVED_LOOK_PATH and e.key in ((reading or {}).get("constructs") or {}):
                data.setdefault("constructs", {})[e.key] = reading["constructs"][e.key]
        for key in ("reads", "assets", "named"):
            if key in data and not data[key]:
                del data[key]
        out[path] = stamp.look_text(data).encode("utf-8")
    return out


def _status(counts):
    if counts.get("mapped") and not (counts.get("unmapped") or counts.get("ambiguous")):
        return "mapped"
    return "ambiguous" if counts.get("ambiguous") else "unmapped" if counts.get("unmapped") else "not reached"


def _checks(cid, parts):
    """"passes", or the first refusal `looks.parse` gives a look holding only these parts."""
    try:
        looks.parse(json.dumps({"look": looks.LOOK_FORMAT, "constructs": {cid: parts}}), CANDIDATES_REL)
    except looks.LookError as e:
        return str(e).splitlines()[0]
    return "passes"


def candidates_text(derivation, proposals=None):
    """The candidates file for one `lookfiles.derive.Derivation` (None: no look was derived): every construct it read, in the plugin's
    construct order, and, when `proposals` (`readpropose.Proposals`) holds any, the `reads` entries adopt proposes (0.8.0, N1): each
    with its `sources`, the text-only `parts` it needs and its measured `line`. The person copies an entry into `site/looks/local.json`;
    adopt never does (the ownership line)."""
    out = {}
    for cid in looks.CONSTRUCTS:
        parts = (getattr(derivation, "candidates", None) or {}).get(cid)
        if not parts:
            continue
        status = _status(derivation.status.get(cid) or {})
        entry = {"status": status, "parts": dict(sorted(parts.items())), "checks": _checks(cid, parts)}
        if status != "mapped":
            entry.update(page=derivation.where.get(cid) or "", reason=derivation.reasons.get(cid) or "")
        out[cid] = entry
    body = {"schema": CANDIDATES_SCHEMA, "candidates": out}
    if proposals is not None and proposals.entries:
        body["reads"] = proposals.reads()
    return json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_candidates(repo, derivation, proposals=None):
    """Parity's last write: the candidates file of the look it kept (`derivation`) and of the `reads` entries proposed (`proposals`), or
    none (a stale one removed) when neither exists. Returns the lines parity prints: one for each construct not mapped, then each
    proposal's own line and each target not proposed, with its reason. Writes only `.site-studio/look-candidates.json`."""
    path = os.path.join(repo, *CANDIDATES_REL.split("/"))
    if derivation is None and not (proposals is not None and proposals.entries):
        if os.path.exists(path):
            os.remove(path)
        return list(proposals.all_lines()) if proposals is not None else []
    os.makedirs(os.path.dirname(path), exist_ok=True)
    text = candidates_text(derivation, proposals)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    lines = []
    for cid, entry in sorted(json.loads(text)["candidates"].items()):
        if entry["status"] in ("ambiguous", "unmapped"):
            lines.append(COPY_LINE % (cid, entry["status"], entry["reason"], (", first on %s" % entry["page"]) if entry["page"] else "",
                                      CANDIDATES_REL, cid, LOOK_LOCAL_PATH))
    return lines + (list(proposals.all_lines()) if proposals is not None else [])


def served_problems(local, view):
    """The served check: [line] for each output file of the old builder (`local`, {output path: bytes}) whose bytes equal a look
    file of the tree `view` (`derived.json` or `local.json`). Each line names the file and the fix."""
    out = []
    for path in (LOOK_LOCAL_PATH, DERIVED_LOOK_PATH):
        if not view.exists(path):
            continue
        blob = view.read(path)
        for served in sorted(p for p, b in local.items() if b == blob):
            out.append("your own builder publishes %s as %s, so a visitor could read your look file; change its copy rule so "
                       "it leaves site/looks/ out, commit it, then run the measurement again" % (path, served))
    return out
