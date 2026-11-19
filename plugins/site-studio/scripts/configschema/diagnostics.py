"""diagnostics: how a refusal is carried: `Problem`, `SiteConfigError` and the collector that gathers every
problem in a config instead of stopping at the first (design-site-adoption section 7.1)."""

from collections import namedtuple
from configschema.configkeys import SCHEMA_MAX


class Problem(namedtuple("Problem", "path found expected fix mechanical lineno", defaults=(None,))):
    """One thing wrong in a config or a content tree (design-site-adoption section 7.1).

    `path` where it is ('work.meta[0]', 'content/news/'), `found` what is there, `expected` what
    would be right, `fix` the one-line remedy, `mechanical` True when adopt's `apply` makes the
    fix itself (it prints `apply fixes this`) and False when only the person can decide (`you
    decide`), `lineno` the 1-based line in `path` when the check knows it (else None; design-site-
    fidelity section 4.1: the field is `lineno`, never `line`, which would shadow the method below).
    `message` is the one-line text `parse_data` raises with; it is not a tuple field, so two Problems
    that differ only in wording compare equal."""
    message = ""

    def line(self):
        message = self.message
        if self.lineno and self.path:
            at = "%s:%d: " % (self.path, self.lineno)
            if message.startswith(self.path + ": "):
                message = at + message[len(self.path) + 2:]         # `path: text` becomes `path:line: text`
            elif not message.startswith(at):
                message = at + message
        return "%s -- fix: %s (%s)" % (message, self.fix, "apply fixes this" if self.mechanical else "you decide")


def make_problem(message, path=None, found=None, expected=None, fix=None, mechanical=False, lineno=None):
    p = Problem(path, found, expected,
                fix or ("edit %s in site/site.json" % ("'%s'" % path if path else "it")), bool(mechanical),
                lineno)
    p.message = message
    return p


class SiteConfigError(ValueError):
    """site.json cannot be read, or a value in it is wrong. The message is one line. `problem` is the
    structured form of ONE refusal (None when the error was not raised by a check); `problems` is the
    whole list when `parse_data` raised for several at once."""

    def __init__(self, message, path=None, found=None, expected=None, fix=None, mechanical=False,
                 lineno=None):
        ValueError.__init__(self, message)
        self.problem = make_problem(message, path, found, expected, fix, mechanical, lineno)
        self.problems = [self.problem]

    @classmethod
    def of(cls, problems):
        """One error that carries every problem, its message the one-line join of theirs."""
        problems = list(problems)
        e = cls("; ".join(p.message for p in problems))
        e.problem = problems[0] if problems else e.problem
        e.problems = problems
        return e


def newer_schema_message(n):
    return ("site.json schema %s is newer than this plugin understands (it reads up to %d); "
            "update site-studio" % (n, SCHEMA_MAX))


class _Collector(object):
    """Runs one check at a time and keeps what it refused instead of stopping at the first."""

    def __init__(self):
        self.problems = []

    def add(self, message, path=None, found=None, expected=None, fix=None, mechanical=False):
        self.problems.append(make_problem(message, path, found, expected, fix, mechanical))

    def run(self, fn, *args, **kw):
        """(ok, value). A SiteConfigError from `fn` is recorded and ok is False."""
        try:
            return True, fn(*args, **kw)
        except SiteConfigError as e:
            self.problems.append(e.problem)
            return False, None
