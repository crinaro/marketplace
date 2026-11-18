"""The one refusal a content file raises."""


class ContentError(ValueError):
    """A content file cannot be read or breaks a rule. The message names the file.

    `path`, `lineno` and `fix` (design-site-fidelity section 4.1) are what `build.accept` turns into a
    `siteconfig.Problem`: where it is, the 1-based line when the check knows it, and the one-line remedy.
    `str(e)` is the message alone, unchanged, so every existing caller reads what it always read."""

    def __init__(self, message="", path=None, lineno=None, fix=None):
        ValueError.__init__(self, message)
        self.path = path
        self.lineno = lineno
        self.fix = fix
