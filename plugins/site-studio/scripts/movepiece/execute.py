"""execute.py -- `run`: plan the move, then write it (the folder, the redirects through `siteconfig`, the released
addresses, the rewritten references) and print every path written and removed. It NEVER COMMITS: add-work
commits the move (design-template-fidelity section 8 A1, issue #877).
"""

import addresses
import os
import sys
from building import gitfiles
from contentmodel import keytables
from movepiece.planning import MoveError, plan
import subprocess


EXIT_OK, EXIT_REFUSED = 0, 1


def run(repo, piece, target, out=None):
    out = out or sys.stdout
    parts = piece.split("/")
    if len(parts) != 2 or not all(keytables.SLUG_RE.match(p) for p in parts) or not keytables.SLUG_RE.match(target):
        raise MoveError("write the piece as <portfolio>/<slug> and the target as <portfolio>, each in lower-case "
                        "letters, digits and hyphens (work/harbor-lights writing)")
    old, slug = parts
    repo = _toplevel(repo)
    addresses.require_clean(repo)
    files = gitfiles._disk_files(repo)
    record = addresses.read_record_file(repo)
    final, removed, report = plan(files, record, old, slug, target)
    written = sorted(p for p in final if files.get(p) != final[p] or p == addresses.RECORD_REL)
    for path in written:
        addresses.write_bytes(repo, path, final[path])
    for path in removed:
        os.remove(os.path.join(repo, *path.split("/")))
    d = os.path.join(repo, "content", old, slug)
    for dirpath, _dirs, _names in sorted(os.walk(d), key=lambda t: -len(t[0])):
        try:
            os.rmdir(dirpath)
        except OSError:
            pass
    print("moved content/%s/%s to content/%s/%s (%d file%s)"
          % (old, slug, target, slug, len(removed), "" if len(removed) == 1 else "s"), file=out)
    for line in report:
        print(line, file=out)
    stage = sorted(set(written) | set(removed))
    print("nothing is committed. Stage these paths with git add, then commit (add-work commits the move): %s"
          % " ".join(stage), file=out)
    return EXIT_OK


def _toplevel(repo):
    try:
        p = subprocess.run(["git", "-C", repo, "rev-parse", "--show-toplevel"], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise MoveError("could not run git (%s); install git, then try again" % e.__class__.__name__)
    if p.returncode != 0:
        raise MoveError("%s is not inside a git repo; run this in the dev repo" % repo)
    return os.path.realpath(p.stdout.decode("utf-8", "replace").strip())
