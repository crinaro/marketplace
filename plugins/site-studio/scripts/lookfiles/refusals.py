"""The two refusals the look command raises: a refusal of the command (the line says what to do) and a fetch that cannot or must not be made."""


class LookCommandError(ValueError):
    """A refusal of this command. The message is the line the person reads and says what to do."""


class FetchError(LookCommandError):
    """A fetch that cannot be made or must not be made; `kind` is a short closed label."""

    def __init__(self, message, kind="fetch"):
        LookCommandError.__init__(self, message)
        self.kind = kind
