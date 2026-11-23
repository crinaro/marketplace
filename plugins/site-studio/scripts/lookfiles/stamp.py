"""lookfiles.stamp -- whose is each entry of `site/looks/derived.json` (design-adopt-ownership-line sections 2.5 and 4, rule E;
round 2, S2 and S5/M7), and the one writer of that file and its stamp, `.site-studio/derived-look.json`.

An entry is a construct (its parts and its `assets` entry), a `reads` target, or the `stylesheets` list (one unit). Its hash is
the sha256 of `json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))`, a construct's value being
`[parts, assets entry or null]`. The stamp holds the hash of each entry derive wrote in its last run, and nothing else.

    E1  the entry's hash is the stamp's: derive's. A new reading replaces it.
    E2  another hash, or no stamp entry: the person's. Kept exactly; derive's new reading for it is not written; no stamp entry.
    E3  in the stamp, absent from the file: handed back. Derive writes it anew.
    E4  no stamp (a site adopted before 0.7.0): recovered from the adoption commit, read by `recover`, never written by a reader.
        1. the commit that added `.site-studio/adopt-parity.json` (the oldest), when it is PROVABLY `apply`'s: its record's
           `basis` is its first parent (round 2, S2), and `look` names the same file there and now. That commit's look file is
           derive's output whole, so its hashes stand in for the stamp. Any construct that differs reads E2, with one line (S5/M7).
        2. otherwise (no such commit; a squash or rebase merge; `look` names another file; a shallow clone): every entry is the
           person's, with one line saying which case and how to hand one back. A missing stamp never reads as "nothing was edited".

Python 3.9, standard library only; git is run read-only, and only by `recover`.

    entry_hashes(data)                          {entry name: hash} of a parsed look file (a dict)
    stamp_text(data, look_ref, plugin)          the stamp for what derive wrote
    parse_stamp(text)                           the strict reader (StampError)
    ownership(data, stamp, source)              an `Ownership`: E1 to E3 over the entries of `data`
    recover(repo, ref, look_ref)                E4: (pseudo-stamp or None, lines)
    ownership_at(files, look_ref, repo, ref)    the stamp of `files`, or E4's answer, as an `Ownership`
    merged(new, old, own, keep_out=())          rule E: derive's reading `new` with the person's entries of `old` kept
    look_text(data)                             the file's text, as derive writes it
    files_for(new, old, own, look_ref, plugin)  ({look_ref: bytes, STAMP_REL: bytes}, lines): what a writer writes
"""

import hashlib
import json
import os
import re
import subprocess

from configschema.configkeys import DERIVED_LOOK_PATH, STAMP_REL

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STAMP_SCHEMA = 1
ADOPTION_RECORD = ".site-studio/adopt-parity.json"     # adoption.base.PARITY_RECORD_REL (a test pins the two equal)
STYLESHEETS = "stylesheets"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_STAMP_KEYS = ("schema", "file", "plugin", "constructs", "reads", "stylesheets")


class StampError(ValueError):
    """The stamp cannot be read. The message names the file and the fix."""


def entry_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def construct_value(data, cid):
    """A construct's hashed value: [parts, its `assets` entry or None]."""
    return [(data.get("constructs") or {}).get(cid), (data.get("assets") or {}).get(cid)]


def entry_hashes(data):
    """{entry name: hash}: `<construct>` for each construct, `reads:<target>` for each reads entry, `named:<name>` for each named
    construct (kept in the stamp's `constructs`), `stylesheets` for the list (when the file holds one)."""
    out = dict((cid, entry_hash(construct_value(data, cid))) for cid in (data.get("constructs") or {}))
    out.update(("reads:" + t, entry_hash(v)) for t, v in (data.get("reads") or {}).items())
    out.update(("named:" + n, entry_hash(v)) for n, v in (data.get("named") or {}).items())     # section 6.6: per name
    if data.get("stylesheets"):
        out[STYLESHEETS] = entry_hash(list(data["stylesheets"]))
    return out


def _stamp_dict(hashes, look_ref, plugin):
    return {"schema": STAMP_SCHEMA, "file": look_ref, "plugin": plugin,
            "constructs": dict((k, h) for k, h in hashes.items() if k != STYLESHEETS and not k.startswith("reads:")),
            "reads": dict((k[len("reads:"):], h) for k, h in hashes.items() if k.startswith("reads:")),
            "stylesheets": hashes.get(STYLESHEETS)}


def stamp_text(hashes, look_ref, plugin):
    """The stamp's text for the entries derive wrote (`hashes`, {entry name: hash}), keys in the design's order."""
    d = _stamp_dict(hashes, look_ref, plugin)
    body = ",\n".join("  %s: %s" % (json.dumps(k), json.dumps(d[k], sort_keys=True, ensure_ascii=False)) for k in _STAMP_KEYS)
    return "{\n%s\n}\n" % body


def parse_stamp(text):
    """The strict reader: exactly the six keys, schema 1, every hash 64 hex. Returns the dict."""
    fix = "restore it from the commit that holds the look (`git log -- %s`), or delete it, and every construct reads as yours" % STAMP_REL
    try:
        d = json.loads(text)
    except ValueError as e:
        raise StampError("%s is not valid JSON (%s); fix: %s" % (STAMP_REL, e, fix))
    if not isinstance(d, dict) or set(d) != set(_STAMP_KEYS):
        raise StampError("%s must hold exactly %s; %s" % (STAMP_REL, ", ".join(_STAMP_KEYS), fix))
    if isinstance(d["schema"], bool) or d["schema"] != STAMP_SCHEMA:
        raise StampError("%s: schema %r is not understood (this site-studio reads 1); update site-studio, because a newer one "
                         "wrote it" % (STAMP_REL, d["schema"]))
    if not isinstance(d["file"], str) or not isinstance(d["plugin"], str):
        raise StampError("%s: file and plugin are text; fix: %s" % (STAMP_REL, fix))
    for key in ("constructs", "reads"):
        if not isinstance(d[key], dict) or not all(isinstance(k, str) and isinstance(v, str) and _HEX64.match(v)
                                                   for k, v in d[key].items()):
            raise StampError("%s: %s maps a name to a 64-hex hash; fix: %s" % (STAMP_REL, key, fix))
    if d["stylesheets"] is not None and not (isinstance(d["stylesheets"], str) and _HEX64.match(d["stylesheets"])):
        raise StampError("%s: stylesheets is a 64-hex hash or null; fix: %s" % (STAMP_REL, fix))
    return d


def stamp_hashes(d):
    """{entry name: hash} of a parsed stamp (the inverse of `_stamp_dict`)."""
    out = dict(d["constructs"])
    out.update(("reads:" + t, h) for t, h in d["reads"].items())
    if d["stylesheets"]:
        out[STYLESHEETS] = d["stylesheets"]
    return out


class Ownership(object):
    """Rule E over one look file: `derived` (E1, derive's), `yours` (E2, the person's), `handed_back` (E3), each a set of entry
    names; `source` ("stamp", "adoption commit" or "none") and `lines`, said where the answer is not a stamp's."""

    def __init__(self, derived=(), yours=(), handed_back=(), source="stamp", lines=()):
        self.derived, self.yours, self.handed_back = set(derived), set(yours), set(handed_back)
        self.source, self.lines = source, list(lines)

    def owner(self, name):
        return "yours" if name in self.yours else "derive's"


def ownership(data, stamp_hash, source="stamp", lines=()):
    """E1 to E3 for the entries of `data` (a parsed look file, or None) against `stamp_hash` ({entry name: hash}, or None: E4.2,
    every entry the person's)."""
    now = entry_hashes(data or {})
    if stamp_hash is None:
        return Ownership((), now, (), source, lines)
    derived = set(n for n, h in now.items() if stamp_hash.get(n) == h)
    yours = set(now) - derived
    lines = list(lines)
    if source == "adoption commit" and yours:
        lines.append("%d construct(s) differ from the adoption commit and no stamp records them; if derive wrote them, commit %s "
                     "(or delete a construct to hand it back)" % (len(yours), STAMP_REL))
    return Ownership(derived, yours, set(stamp_hash) - set(now), source, lines)


def _git(repo, *args):
    try:
        p = subprocess.run(["git", "-C", repo] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return p.stdout.decode("utf-8", "replace") if p.returncode == 0 else None


HAND_BACK = 'delete a construct from %s and commit to hand it back to derive'
NO_HISTORY = "%s has no stamp (%s) and %s, so every construct in it reads as yours; " + HAND_BACK


def recover(repo, ref, look_ref):
    """E4: (the adoption commit's {entry name: hash}, []) when the history proves it, else (None, [the one line]). Read-only."""
    def none(why):
        return None, [NO_HISTORY % (look_ref, STAMP_REL, why, look_ref)]
    if repo is None:
        return none("no history was read")
    if (_git(repo, "rev-parse", "--is-shallow-repository") or "").strip() == "true":
        return none("this clone is shallow, so the adoption commit cannot be read (run `git fetch --unshallow`, then again)")
    added = (_git(repo, "log", "--diff-filter=A", "--format=%H", ref, "--", ADOPTION_RECORD) or "").split()
    if not added:
        return none("no adoption commit is in the history")
    commit = added[-1]
    record, parent = _git(repo, "show", "%s:%s" % (commit, ADOPTION_RECORD)), _git(repo, "rev-parse", "--verify", "-q", commit + "^1")
    try:
        basis = json.loads(record or "").get("basis")
    except (ValueError, AttributeError):
        basis = None
    if not basis or basis != (parent or "").strip():
        return none("the commit that added %s is not apply's own (its parity basis is not its parent: a squash or rebase "
                    "merge)" % ADOPTION_RECORD)
    try:
        then = json.loads(_git(repo, "show", "%s:site/site.json" % commit) or "").get("look")
        data = json.loads(_git(repo, "show", "%s:%s" % (commit, look_ref)) or "")
    except (ValueError, AttributeError):
        then, data = None, None
    if then != look_ref or not isinstance(data, dict):
        return none("the adoption commit's site.json names another look file")
    return entry_hashes(data), []


def ownership_at(files, look_ref, repo=None, ref="HEAD"):
    """The ownership of `look_ref`'s entries in `files` ({path: bytes}): read from the stamp in `files` when it names
    `look_ref`, else E4's answer from `repo` at `ref`. A stamp that does not parse is loud (StampError)."""
    raw = files.get(look_ref)
    data = json.loads(raw.decode("utf-8")) if raw is not None else None
    if STAMP_REL in files:
        d = parse_stamp(files[STAMP_REL].decode("utf-8", "replace"))
        if d["file"] == look_ref:
            return ownership(data, stamp_hashes(d))
    hashes, lines = recover(repo, ref, look_ref)
    return ownership(data, hashes, "adoption commit" if hashes is not None else "none", lines)


def merged(new, old, own, keep_out=()):
    """Rule E: derive's reading `new` (a look dict) with every entry of `old` that `own` says is the person's kept exactly, in
    `old`'s value; derive's reading of a kept entry is not written. `keep_out` names entries of the person's to leave out (a
    measurement of the look without them: `adoption.lookperson`). Returns (look dict, {entry name: hash} of what derive wrote)."""
    old = old or {}
    mine = set(own.yours) - set(keep_out) if own is not None else set()
    out = {"look": new.get("look", old.get("look", 1))}
    cons, assets = dict(new.get("constructs") or {}), dict(new.get("assets") or {})
    for cid in [c for c in (old.get("constructs") or {}) if c in mine]:
        cons[cid] = old["constructs"][cid]
        assets.pop(cid, None)
        if cid in (old.get("assets") or {}):
            assets[cid] = old["assets"][cid]
    reads = dict(new.get("reads") or {})
    reads.update((t, v) for t, v in (old.get("reads") or {}).items() if "reads:" + t in mine)
    named = dict(new.get("named") or {})
    named.update((n, v) for n, v in (old.get("named") or {}).items() if "named:" + n in mine)
    sheets = old.get("stylesheets") if STYLESHEETS in mine else new.get("stylesheets")
    for key, value in (("stylesheets", sheets), ("assets", assets), ("constructs", cons), ("reads", reads), ("named", named)):
        if value or key == "constructs":
            out[key] = value
    order = ["look", "constructs", "stylesheets", "assets", "reads", "named"]
    out = dict((k, out[k]) for k in order if k in out)
    wrote = dict((n, h) for n, h in entry_hashes(out).items() if n not in mine)
    return out, wrote


def look_text(data):
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def plugin_version():
    """This site-studio's version, from its own `plugin.json` (the stamp names it; `adoption.parity.plugin_version` reads the same
    file, and a test pins the two equal)."""
    try:
        with open(os.path.join(PLUGIN_ROOT, ".claude-plugin", "plugin.json"), encoding="utf-8") as fh:
            v = json.load(fh).get("version")
    except (OSError, ValueError, AttributeError):
        v = None
    return v if isinstance(v, str) and v else "unknown"


def derive_files(repo, files, target, text, ref="HEAD"):
    """What `look.py derive` writes for its reading (`text`, the look file's text) at `target`: ({path: bytes}, lines). For
    `site/looks/derived.json`, rule E against the committed file at `ref` and its stamp (or E4's answer), and the stamp beside it;
    for a look of another name, that file alone."""
    if target != DERIVED_LOOK_PATH:
        return {target: text.encode("utf-8")}, []
    raw = files.get(target)
    if raw is None:
        return {target: text.encode("utf-8"),
                STAMP_REL: stamp_text(entry_hashes(json.loads(text)), target, plugin_version()).encode("utf-8")}, []
    have = {target: raw}
    shown = _git(repo, "show", "%s:%s" % (ref, STAMP_REL))
    if shown is not None:
        have[STAMP_REL] = shown.encode("utf-8")
    own = ownership_at(have, target, repo, ref)
    written, lines = files_for(text, json.loads(raw.decode("utf-8")), own, target, plugin_version())
    return written, own.lines + lines


COMMIT_STAMP = ("commit %s with %s: while the stamp is not committed, the next derive and adopt read every construct of the look "
                "as yours")


def files_for(text, old, own, look_ref, plugin):
    """What the one writer writes for derive's reading `text` (the look file's text): ({look_ref: bytes, STAMP_REL: bytes}, lines).
    The look is `text` itself when no entry of the person's is kept, else the merge, re-serialised. `lines` name each kept entry."""
    data, wrote = merged(json.loads(text), old, own)
    kept = sorted(n for n in own.yours if n in entry_hashes(old or {}))
    lines = ['%s: "%s" is yours (%s), kept as it is; derive\'s new reading of it is not written' % (
        look_ref, n, "edited since derive wrote it" if own.source == "stamp" else "no stamp records it") for n in kept]
    body = look_text(data) if kept else text
    return {look_ref: body.encode("utf-8"), STAMP_REL: stamp_text(wrote, look_ref, plugin).encode("utf-8")}, lines
