"""runcheck.py -- `check`, the whole Pages report: the reads in order (repo, Pages, then the item builders of
pagesitems.py and protection.py), with `get` and `sleep` as the test seams (dev #835, design amendment 1).
"""

import time
from pagesaudit.ghget import _get
from pagesaudit.pagesitems import _pages_items
from pagesaudit.protection import _protection_items, _writer_items
from pagesaudit.values import GhError, Item, PagesCheckError, Resp, YOU


def check(public_repo, cfg, get=_get, sleep=time.sleep):
    """The whole report: [Item(key, state, line, who)], state in ok / info / resolve / wait /
    not_checked. `get(path, paginate=False) -> Resp` and `sleep(seconds)` are the test seams. Raises
    PagesCheckError when the check cannot run (no repo name, gh missing or logged out, the repo read
    failed)."""
    if not public_repo or not isinstance(public_repo, str) or public_repo.count("/") != 1:
        raise PagesCheckError("site.json has no publicRepo, so there is no public repo to check. "
                              "Set publicRepo (setup step 2) and run again.")
    owner = public_repo.split("/", 1)[0]
    base = "repos/%s" % public_repo
    items = []

    def add(key, state, line, who=""):
        items.append(Item(key, state, line, who))

    def rd(path, paginate=False):
        try:
            return get(path, paginate)
        except GhError as e:
            return Resp(None, None, str(e))

    # ---- read 1: the repo
    try:
        r1 = get(base)
    except GhError as e:
        raise PagesCheckError("cannot reach GitHub with gh (%s). Run /site-studio:setup's step 1." % e)
    if r1.status != 200 or not isinstance(r1.data, dict):
        raise PagesCheckError("cannot read %s on GitHub (%s)"
                              % (public_repo, r1.message or ("HTTP %s" % r1.status)))
    repo = r1.data
    owner_obj = repo.get("owner") if isinstance(repo.get("owner"), dict) else {}
    owner_login = owner_obj.get("login") or owner
    owner_is_org = owner_obj.get("type") == "Organization"
    perms = repo.get("permissions") if isinstance(repo.get("permissions"), dict) else {}
    is_admin = bool(perms.get("admin"))
    where = "the organization's" if owner_is_org else "your profile's"

    if repo.get("visibility") != "public":
        add("C1", "resolve", "%s is not public. site-studio publishes to a public repo, and Pages on a "
            "private repo needs a paid plan." % public_repo, "you: the repo's Settings, then General")
    if repo.get("archived"):
        add("C2", "resolve", "%s is archived, so nothing can be pushed to it." % public_repo,
            "you: unarchive it in Settings")

    # ---- read 2: Pages
    pages = None
    r2 = rd(base + "/pages")
    if r2.status == 404:
        add("C3", "resolve", "GitHub Pages is off for %s. Turn it on under Settings, then Pages, then "
            "'Deploy from a branch', branch main, folder / (root). For a new site, setup's first-publish "
            "already does this." % public_repo, "you, or setup on a new site")
    elif r2.status == 200 and isinstance(r2.data, dict):
        pages = r2.data
    else:
        add("C3", "not_checked", "NOT CHECKED: the Pages settings of %s (%s)."
            % (public_repo, r2.message or "no answer"), YOU)

    if pages is not None:
        _pages_items(pages, cfg, owner_login, where, base, rd, sleep, add)

    _protection_items(public_repo, base, is_admin, rd, add)
    _writer_items(public_repo, base, owner_login, owner_is_org, rd, add)
    return items
