"""guarding.confirmask -- the ask for a `deploy.py --confirm`: the one place the guard reads the review rows and the site config.

It is imported only by the entry point, and only once a confirm has matched, so the guard's hot path (every command that merely
names a publish script) starts no review reader and no config parser. N, the digest and the review all come from records the
dry run and the review wrote, never from the guard (M5(c)).
"""
import os

from configschema import model
from reviews import dryrun, rows as review_rows, store
from guarding.texts import RELEASED_SHOWN


def released_clause(rec):
    """The ask's words for the addresses the dry run recorded as released ('' when none): the count and the first
    few paths, so the person's yes is a yes to them (R2-1)."""
    paths = [p if len(p) <= 60 else p[:57] + "..." for p, _r in rec["released"]]
    if not paths:
        return ""
    more = ", +%d more" % (len(paths) - RELEASED_SHOWN) if len(paths) > RELEASED_SHOWN else ""
    return " and release %d published address%s (%s%s)" % (
        len(paths), "" if len(paths) == 1 else "es", ", ".join(paths[:RELEASED_SHOWN]), more)


def ask(pending):
    """The ask of a `deploy.py --confirm` that got this far (decision.decide returned it as a ConfirmAsk): the dry-run record,
    the review row for the digest and the site's own config say what is being approved. Raises on anything it cannot read
    (the caller fails closed). Returns (decision, reason, matched) as `decide` does."""
    repo, digest, msg, matches, matched = pending
    cfg = model.load(os.path.join(repo, "site", "site.json"))
    rec = dryrun.read_dryrun(repo)
    if rec is None or rec["digest"] != digest:
        return "deny", ("No dry run for this digest in %s: run `deploy.py --dry-run` first and pass "
                        "the digest it prints." % repo), matched
    status, row = store.verdict_for(digest, repo)
    review = ("Review: NONE for this digest (deploy.py will refuse)" if row is None else          # a stand-in row says so (reviews.rows)
              "Review: " + review_rows.describe(status.upper() if status == "blocked" else status, row))
    reason = "Publish %d files to %s%s, public forever? %s. Digest %s." % (
        rec["files"], cfg.publicRepo or "(no publicRepo set)", released_clause(rec), review, digest[:12])
    if msg:
        reason += " Message: %s" % (msg if len(msg) <= 120 else msg[:117] + "...")
    if any(m[0] == "report" for m in matches):
        reason += " The same command also files site-studio adopt reports."
    if any(m[0] == "apply" for m in matches):
        reason += " The same command also runs adopt.py apply, which publishes and retires the old builder."
    return "ask", reason, matched
