"""The pieces of the acceptance run: loading the model, turning a refusal into a `Problem`, the schema-3
meta-key rule, the carriage-return check."""

import re

import content as C
import siteconfig
from content import ContentError

from building.constants import HTML_EXTS
from building.outcomes import BuildError


def _load_model(files, cfg, drafts, check_resume_pdf):
    """The content model for a site. A `portfolio` loads `content/`; a `hub` or `custom` builds
    nothing from it, so it gets an empty model after every refusal of design section 4.1 is
    checked: portfolio-only keys, portfolio content, and a missing `site/src/index.html`."""
    layout = [p.message for p in C.layout_problems(files, cfg.siteKind, cfg)]
    if cfg.siteKind == "portfolio":
        if layout:
            raise ContentError("; ".join(layout), fix="fix each problem listed, then build again")
        return C.load_content(files, cfg, drafts=drafts, check_resume_pdf=check_resume_pdf)
    problems = siteconfig.kind_conflicts(cfg) + layout
    if "site/src/index.html" not in files:
        problems.append("a %s site's home page is site/src/index.html, and it is missing" % cfg.siteKind)
    if problems:
        raise ContentError("; ".join(problems), fix="fix each problem listed, then build again")
    return C.Content()


def _problem_from(e, default_path=None):
    """One `siteconfig.Problem` for a `BuildError` or `ContentError`: its message, its `path`/`lineno`/`fix`
    when it carries them, else the file named at the head of the message (`path:12: ...`), else the
    unit being built. Never mechanical: only the person can fix a refusal the build raises."""
    msg = str(e)
    path = getattr(e, "path", None)
    lineno = getattr(e, "lineno", None)
    if path is None:
        m = re.match(r"^([^\s:][^\s]*?)(?::(\d+))?: ", msg)
        if m and ("/" in m.group(1) or "." in m.group(1)):
            path = m.group(1)
            if lineno is None and m.group(2):
                lineno = int(m.group(2))
    fix = getattr(e, "fix", None) or "fix the problem named here, then run the check again"
    return siteconfig.make_problem(msg, path or default_path, "refused by the build", "accepted by the build",
                                   fix, False, lineno)


def _not_checked(stage_name, e, default_path=None):
    """A refusal that is not a refusal: an exception the build did not mean to raise. It is loud, never a
    traceback and never a quiet pass (CLAUDE.md: a missing thing reads as an empty thing)."""
    return siteconfig.make_problem("NOT CHECKED: %s raised %s: %s" % (stage_name, type(e).__name__, e),
                                   default_path, "an exception the build did not mean to raise",
                                   "a refusal with a fix", "report this to site-studio, with the file named "
                                   "here", False)


def _cr_problems(out):
    probs = []
    for rel in sorted(out, key=lambda p: p.encode("utf-8")):
        if (rel.lower().endswith(C.TEXT_EXTS) or rel in ("CNAME", "robots.txt")
                or rel.lower().endswith(HTML_EXTS)) and b"\r" in out[rel]:
            probs.append(siteconfig.make_problem("%s would be written with a carriage return" % rel, rel,
                                                 "a carriage return", "LF line endings",
                                                 "save the file with LF line endings"))
    return probs


def _meta_key_problems(model, cfg):
    """Schema 3 only (design-site-fidelity section 6.2): a `meta` or `cardMeta` list that names a key the build
    already reads or shows (`siteconfig.BUILTIN_PIECE_KEYS`) is refused, because the build shows it already and
    a second copy would print it twice. Below schema 3 such a list builds exactly as 0.2.0 built it, so this is
    never asked of a schema-1 or schema-2 reading. The Problem names the file the list is in: the portfolio's
    page.md when that page sets the list, else site.json (`work`'s base)."""
    out = []
    for pf in model.portfolios:
        for part in ("meta", "cardMeta"):
            for key in pf.settings[part]:
                if key not in siteconfig.BUILTIN_PIECE_KEYS:
                    continue
                path = pf.page_source if (pf.page_source and part in pf.page_keys) else "site/site.json"
                out.append(siteconfig.make_problem(
                    "%s: '%s' lists the built-in key '%s', which the build shows already" % (path, part, key),
                    path, "'%s' in %s" % (key, part), "no built-in key in %s" % part,
                    "remove '%s' from %s; the build shows it already" % (key, part)))
    return out


def warning_line(w):
    """One warning as the build prints it: where (with the line when known), what is not published, the fix."""
    at = "%s:%d: " % (w.path, w.lineno) if (w.lineno and w.path) else ""
    msg = w.message
    if at and msg.startswith(w.path + ": "):
        msg = msg[len(w.path) + 2:]
    return "%s%s -- fix: %s" % (at, msg, w.fix)


def _refusal(problems):
    """One `BuildError` that carries every problem; its message is the join of theirs (exactly the one
    problem's message when there is one)."""
    first = problems[0]
    return BuildError("; ".join(p.message for p in problems), path=first.path, lineno=first.lineno,
                      fix=first.fix, problems=problems)
