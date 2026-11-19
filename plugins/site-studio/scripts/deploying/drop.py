"""deploying.drop -- `deploy.py drop <path>... --reason TEXT`: release published addresses on purpose (design section 8 A1).
It records them in `.site-studio/addresses.json`, writes `site.json` at the schema that then needs, commits those two
paths and publishes nothing.
"""
import addresses
import sys
from building import gitfiles, outcomes, running
from configschema import diagnostics, model
from deploying.constants import EXIT_OK
from deploying.gitrun import DeployError, _git, _toplevel


def run_drop(repo, paths, reason, out=None):
    """`deploy.py drop <path>... --reason TEXT` (design section 8 A1). Records each path as released in
    `.site-studio/addresses.json`, writes `site.json` at the schema that then needs (4: the guard reason, so every
    0.3.x install refuses the tree), and COMMITS those two paths and nothing else. It publishes nothing and asks
    nothing: the next dry run lists the released addresses and the publish ask names them. It refuses, writing
    nothing, on a dirty `site/`, `content/` or `.site-studio/`, a tree below schema 3 or holding a part name schema
    4 fixes (the raise-schema pre-write check, R2-3), a path that is not an output path, and a tree the build would
    refuse once the record exists. A cloud session is NOT refused (R2-6): this is a content edit."""
    out = out or sys.stdout
    reason = (reason or "").strip()
    if not reason or "\n" in reason:
        raise DeployError("--reason needs one line saying why the address is released (a visitor or a search "
                          "result may still use it)")
    try:
        repo = _toplevel(repo)
        for path in paths:
            addresses.check_path(path, "the path")
        addresses.require_clean(repo)
        files = gitfiles._disk_files(repo)
        raw = files.get("site/site.json")
        if raw is None:
            raise DeployError("site/site.json is not in this folder; run this inside the dev repo")
        cfg = model.parse_text(raw.decode("utf-8", "replace"))
        addresses.check_prewrite(cfg, files)
        before = addresses.read_record_file(repo)
        after = addresses.merge(before, dropped=[(p, reason) for p in sorted(set(paths))])
        if after == before:
            print("nothing to record: %s already released" % ", ".join(sorted(set(paths))), file=out)
            return EXIT_OK
        text = addresses.dump(after)
        site_json = addresses.site_json_text(cfg, files, text)
        tree = dict(files)
        tree["site/site.json"] = site_json.encode("utf-8")
        tree[addresses.RECORD_REL] = text.encode("utf-8")
        acc = running.accept(dict((k, v) for k, v in tree.items() if k.startswith(("site/", "content/"))))
        if acc.problems:
            raise DeployError("the site would not build once the address record exists (%s); fix that first, "
                              "then run drop again" % acc.problems[0].line())
    except (addresses.AddressError, outcomes.BuildError, diagnostics.SiteConfigError) as e:
        raise DeployError(str(e))
    addresses.write_text(repo, addresses.RECORD_REL, text)
    addresses.write_text(repo, "site/site.json", site_json)
    new = sorted(set(paths) - set(d["path"] for d in before["dropped"]))
    _git(repo, "add", "--", addresses.RECORD_REL, "site/site.json")
    _git(repo, "commit", "-q", "-m", "site-studio: release %d published address%s" % (
        len(new), "" if len(new) == 1 else "es"), "--", addresses.RECORD_REL, "site/site.json")
    print("released %d published address%s, committed (%s and site/site.json):"
          % (len(new), "" if len(new) == 1 else "es", addresses.RECORD_REL), file=out)
    for path in new:
        print("  ! %s (%s)" % (path, reason), file=out)
    print("nothing is published yet. Push this commit to the main branch (a pull request merge), run the dry run, "
          "which lists these addresses, then confirm.", file=out)
    return EXIT_OK
