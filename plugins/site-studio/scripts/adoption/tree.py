"""adoption.tree -- a commit's files read with git plumbing, and the inventory of what adopt would remove.

Part of the `adoption` package behind the entry point `adopt.py`.
"""

import posixpath

from adoption.base import git
from adoption.spec import load_spec
from adoption.classify import classify_text, file_kind, shadow_names

class Tree(object):
    """A commit's files, read with plumbing, plus the pending changes adopt will commit."""

    def __init__(self, repo, ref):
        self.repo = repo
        self.ref = ref
        out = git(repo, "ls-tree", "-r", "-z", "--full-tree", ref)
        self.entries = {}
        for rec in out.split(b"\0"):
            if not rec:
                continue
            meta, _, raw = rec.partition(b"\t")
            mode, typ, sha = meta.decode("ascii").split()
            path = raw.decode("utf-8", "surrogateescape")
            if typ == "blob":
                self.entries[path] = (mode, sha)
        self.writes = {}
        self.removed = set()
        self._cache = {}

    def paths(self):
        cur = set(self.entries) | set(self.writes)
        return sorted(cur - self.removed)

    def prefetch(self, paths):
        """Read every not-yet-read blob among `paths` with ONE `git cat-file --batch`, so `read` finds it
        cached. `build.accept` reads the whole of site/ and content/; a process per blob would not do."""
        want = []
        for p in paths:
            if p in self.writes or p in self.removed or p not in self.entries:
                continue
            mode, sha = self.entries[p]
            if mode != "120000" and sha not in self._cache and sha not in want:
                want.append(sha)
        if not want:
            return
        blob = git(self.repo, "cat-file", "--batch", input="".join("%s\n" % s for s in want).encode("ascii"))
        pos = 0
        for sha in want:
            nl = blob.index(b"\n", pos)
            size = int(blob[pos:nl].decode("ascii").split()[2])
            self._cache[sha] = blob[nl + 1:nl + 1 + size]
            pos = nl + 1 + size + 1

    def exists(self, path):
        return path in self.writes or (path in self.entries and path not in self.removed)

    def mode(self, path):
        if path in self.entries:
            return self.entries[path][0]
        return "100644"

    def read(self, path):
        if path in self.writes:
            return self.writes[path]
        if path in self.removed or path not in self.entries:
            raise KeyError(path)
        mode, sha = self.entries[path]
        if mode == "120000":
            return b""
        data = self._cache.get(sha)
        if data is None:
            data = self._cache[sha] = git(self.repo, "cat-file", "blob", sha)
        return data

    def text(self, path):
        return self.read(path).decode("utf-8", "replace")

    def write(self, path, data):
        if isinstance(data, str):
            data = data.encode("utf-8")
        self.writes[path] = data
        self.removed.discard(path)

    def remove(self, path):
        self.writes.pop(path, None)
        if path in self.entries:
            self.removed.add(path)


class Overlay(object):
    """A tree with pending file writes and removals laid over it, readable like a `Tree`: the conversion classes run one
    after another, and each reads what the one before wrote (a renamed piece file, a body already rewritten) rather than
    the commit's bytes. `files` is {path: bytes}; `removed` is a set of paths. Nothing is written anywhere."""

    def __init__(self, base, files=None, removed=()):
        self.base = base
        self.files = files if files is not None else {}
        self.removed = removed if isinstance(removed, set) else set(removed)       # shared: a class that renames hides the old name

    def paths(self):
        return sorted((set(self.base.paths()) | set(self.files)) - self.removed)

    def exists(self, path):
        return path in self.files or (path not in self.removed and self.base.exists(path))

    def mode(self, path):
        return self.base.mode(path) if path not in self.files else "100644"

    def read(self, path):
        if path in self.files:
            return self.files[path]
        if path in self.removed:
            raise KeyError(path)
        return self.base.read(path)

    def text(self, path):
        return self.read(path).decode("utf-8", "replace")

    def prefetch(self, paths):
        self.base.prefetch([p for p in paths if p not in self.files])

    def write(self, path, data):
        self.files[path] = data.encode("utf-8") if isinstance(data, str) else data
        self.removed.discard(path)

    def remove(self, path):
        self.files.pop(path, None)
        self.removed.add(path)


class TreeFiles(object):
    """The tree's `site/` and `content/` files, with adopt's pending page rewrites laid over them, as
    the read-only {repo path: bytes} mapping that `siteconfig.required_schema` and
    `content.layout_problems` take (they read no file themselves). Built lazily: nothing is read from
    git until a caller asks for a path's bytes."""

    def __init__(self, tree, overlay=None, removed=()):
        self.tree = tree
        self.overlay = dict((p, b) for p, b in (overlay or {}).items() if self._ours(p))
        self.removed = set(removed)
        self._keys = None

    @staticmethod
    def _ours(path):
        return path.startswith(("site/", "content/"))

    def _paths(self):
        if self._keys is None:
            self._keys = sorted((set(p for p in self.tree.paths() if self._ours(p)) | set(self.overlay))
                                - self.removed)
        return self._keys

    def __iter__(self):
        return iter(self._paths())

    def __len__(self):
        return len(self._paths())

    def __contains__(self, path):
        if path in self.removed:
            return False
        return path in self.overlay or (self._ours(path) and self.tree.exists(path))

    def __getitem__(self, path):
        if path in self.removed:
            raise KeyError(path)
        if path in self.overlay:
            return self.overlay[path]
        if self._ours(path):
            return self.tree.read(path)
        raise KeyError(path)

    def get(self, path, default=None):
        try:
            return self[path]
        except KeyError:
            return default


def inventory(tree, spec=None):
    """Classify every file adopt looks at. Returns a list of info dicts, sorted by path."""
    spec = spec or load_spec()
    shadows = shadow_names()
    out = []
    for path in tree.paths():
        kind = file_kind(path)
        if kind is None:
            continue
        if kind == "mixed":
            out.append({"path": path, "kind": kind, "class": "MIXED", "capability": None, "score": 0.0,
                        "residual": 0.0, "residual_units": [], "signals": [], "units": 0, "candidates": [],
                        "needs_parity": False, "best": [], "namesake": None, "shadows": None})
            continue
        info = classify_text(spec, path, kind, tree.text(path), shadows=shadows)
        info["shadows"] = None
        if kind == "agent":
            stem = posixpath.splitext(posixpath.basename(path))[0]
            if stem in shadows:
                info["shadows"] = stem                    # whatever its class: precedence ignores class (7.6)
        out.append(info)
    return out


def counterpart_of(spec, cid):
    return spec.data["descriptions"].get(cid, {}).get("counterpart", cid) if cid else "none"
