"""File helpers shared by 0.85.0, 0.86.0 and 0.88.0: a file's sha1 and the readmit lock path.

One module of `migrations/` (design-component-segmentation.md §5); moved out of `migrate.py` unedited by S2."""

import os


def _readmit_lock_path(profile):
    """The run lock's file for this profile: `runlock.py`'s own rule (`CLAUDESEARCH_LOCK_PATH`, else
    `<profile>/.git/run_lock.json`), computed from the profile being migrated rather than from the session's root."""
    return os.environ.get("CLAUDESEARCH_LOCK_PATH") or os.path.join(profile, ".git", "run_lock.json")


def _sha1_file(path):
    import hashlib
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()
