"""errors: `LookError`, the one refusal a look file or a render raises (moved out of looks.py unchanged, S1b).
`fix` says what to do; every other lookgrammar module raises it."""


class LookError(ValueError):
    """A look that is refused, or a render that cannot be made. `fix` says what to do."""

    def __init__(self, message, fix=None):
        ValueError.__init__(self, message)
        self.fix = fix
