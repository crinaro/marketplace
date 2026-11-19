"""deploying.dryrun -- `--dry-run`: stage and verify, print the changes, the review row and `confirm: <digest>`, and write the
dry-run record the publish guard reads (review_record.write_dryrun).
"""
from reviews.dryrun import DRYRUN_VERSION, write_dryrun
import shutil
import sys
import time
from deploying.addressguard import print_released
from deploying.constants import EXIT_OK, LIST_CAP
from deploying.gitrun import _git
from deploying.prepare import prepare, print_warnings, review_summary
from deploying.staging import stage_and_verify
from deploying.target import public_target, verify_public_target


def run_dry(repo, public_url=None, hooks=None, build_fn=None, out=None, dev_origin=None, adopt=False):
    out = out or sys.stdout
    repo, cfg, work, out_dir, result, note = prepare(repo, hooks, build_fn, adopt)
    try:
        print_warnings(result, out)
        url = public_url or public_target(cfg)[1]
        st = stage_and_verify(repo, out_dir, result, url, "site-studio dry run", work, hooks, cfg=cfg)
        verify_public_target(repo, cfg, st, public_url, dev_origin)
        status, review = review_summary(repo, result.digest)
        if note:
            print(note, file=out)
        if st.pages_note:
            print(st.pages_note, file=out)
        if st.commit is None:
            print("nothing to publish: the public repo already holds this exact build (digest %s)"
                  % result.digest, file=out)
            return EXIT_OK
        counts = {"A": 0, "M": 0, "D": 0}
        for code, _p in st.changes:
            counts[code[0]] = counts.get(code[0], 0) + 1
        print("dry run for %s: %d files in the build; %d added, %d changed, %d removed"
              % (cfg.publicRepo, len(result.files), counts["A"], counts["M"], counts["D"]), file=out)
        for code, path in st.changes[:LIST_CAP]:
            print("  %s %s" % ({"A": "+", "M": "~", "D": "-"}.get(code[0], "?"), path), file=out)
        if len(st.changes) > LIST_CAP:
            print("  ... and %d more" % (len(st.changes) - LIST_CAP), file=out)
        print_released(st, out)
        print(review, file=out)
        print("digest: %s" % result.digest, file=out)
        write_dryrun(repo, {
            "v": DRYRUN_VERSION, "digest": result.digest, "files": len(result.files), "added": counts["A"],
            "changed": counts["M"], "removed": counts["D"], "publicRepo": cfg.publicRepo, "released": st.released,
            "head": _git(repo, "rev-parse", "HEAD").strip(), "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        if status in ("clear", "accepted"):
            print("confirm: %s" % result.digest, file=out)
        else:
            print("not publishable yet: %s" % ("the review is BLOCKED" if status == "blocked"
                                               else "no review covers this digest"), file=out)
        return EXIT_OK
    finally:
        shutil.rmtree(work, ignore_errors=True)
