"""Every Python source file a scan over "every shipped script" must read: the top-level scripts and every module
of every regular package beside them (finding 1113; segmentation S4a).

WHY. After the segmentation splits, a script's code lives in a package (`recording/`, `migrations/`,
`validation/`, `journaling/`, ...). A scan that globbed `scripts/*.py` stopped seeing that code, and S3 patched each
scan by adding `recording/` by hand; `migrations/` (S2) stayed unseen, so a defect planted in a migration passed
them (finding 1113). Each new package would need the same hand edit in every scan. This module is the one
definition instead: a package is any directory directly under the scripts directory that holds an `__init__.py`
(a regular package, design §3.2), except `tests/`, and all of its `.py` files at any depth are listed.

Core module (design §3.1): standard library only, no knowledge of any capability. Python 3.9+.
"""

import os

EXCLUDED = ("tests",)
_SKIP = ("__pycache__",)


def packages(scripts_dir):
    """Sorted names of the regular packages directly under `scripts_dir`, `tests` excluded."""
    out = []
    for name in sorted(os.listdir(scripts_dir)):
        full = os.path.join(scripts_dir, name)
        if (name not in EXCLUDED and not name.startswith(".") and os.path.isdir(full)
                and os.path.isfile(os.path.join(full, "__init__.py"))):
            out.append(name)
    return out


def package_modules(scripts_dir):
    """Every `.py` file inside those packages, as sorted paths relative to `scripts_dir` with `/` separators."""
    out = []
    for pkg in packages(scripts_dir):
        for dirpath, dirs, files in os.walk(os.path.join(scripts_dir, pkg)):
            dirs[:] = sorted(d for d in dirs if d not in _SKIP and not d.startswith("."))
            rel = os.path.relpath(dirpath, scripts_dir).replace(os.sep, "/")
            out.extend(rel + "/" + f for f in sorted(files) if f.endswith(".py"))
    return sorted(out)


def relative(scripts_dir, top=True):
    """The top-level `*.py` (when `top`) then every package module, relative to `scripts_dir`, sorted within each."""
    head = sorted(f for f in os.listdir(scripts_dir)
                  if f.endswith(".py") and os.path.isfile(os.path.join(scripts_dir, f))) if top else []
    return head + package_modules(scripts_dir)


def paths(scripts_dir, top=True):
    """`relative()` as absolute paths."""
    return [os.path.join(scripts_dir, *r.split("/")) for r in relative(scripts_dir, top)]
