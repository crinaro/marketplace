"""values.py -- the values the Pages check passes around: a response (`Resp`), a report line (`Item`), the two
errors, the exit codes, the states and their labels, and who resolves a line (`YOU`, `YOU_DNS`, `YOU_SETTINGS`).
"""

import collections


EXIT_OK, EXIT_RED, EXIT_AMBER = 0, 1, 3


Resp = collections.namedtuple("Resp", "status data message")
Item = collections.namedtuple("Item", "key state line who")


class GhError(Exception):
    """`gh` is missing, logged out, or did not answer: one call could not be made."""


class PagesCheckError(Exception):
    """The check cannot run at all (exit 1). The message is one line."""


YOU = "you"
YOU_DNS = "you, at your DNS provider"
YOU_SETTINGS = "you: the repo's Settings, then Pages"


STATES = ("ok", "info", "resolve", "wait", "not_checked")
LABEL = {"info": "info", "resolve": "to resolve", "wait": "waiting", "not_checked": "not checked"}
APPS_NOTE = ("Apps installed on the account are not checked, and the www alias is checked only for DNS.")
