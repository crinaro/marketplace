"""The `journal.py` flags of the LinkedIn job search (jobsearch 0.94.0, dev 1065; docs/design-role-first.md 8.1, 19.5, 19.6), kept here so the
entry point does not grow:

  --linkedin-search-skip --until <YYYY-MM-DD>              the owner skips the search until a date at most 30 days on (`linkedin-search-skip`).
  --linkedin-search-on --attended --warning <YYYY-MM-DD>   turns the scheduled search back on after a warning, naming the NEWEST warning's date:
                                                           the only thing that does (WN3). `--attended` is a typed word (PARTIAL, as everywhere).
  --scope search [--search-reason CODE]                    with `--pass linkedin --phase returned`: the row is the search's own, and
                                                           `--search-reason` is why it was `unreachable` (`SEARCH_REASONS`).

`add_arguments` registers them, `wants` says whether a call is one of the two events, `run` writes it and prints one line. Each needs the 0.94.0
profile pin (the writers check it) and prints nothing on a refusal but the `JournalError`, which `journal.py` turns into its usual refusal.

Capability module of `journal.py`. Python 3.9+, standard library only."""

from journaling.row_kinds import record_linkedin_search_on, record_linkedin_search_skip
from journaling.tables import JournalError, SEARCH_REASONS, SEARCH_SCOPE


def add_arguments(ap):
    """Register the flags above on `ap`."""
    ap.add_argument("--linkedin-search-skip", dest="linkedin_search_skip", action="store_true",
                    help="skip the LinkedIn job search until --until (at most 30 days): a `linkedin-search-skip` event (0.94.0, dev 1065)")
    ap.add_argument("--until", metavar="YYYY-MM-DD", help="with --linkedin-search-skip: the last day the search is skipped")
    ap.add_argument("--linkedin-search-on", dest="linkedin_search_on", action="store_true",
                    help="turn the scheduled LinkedIn job search back on after a warning; needs --attended and --warning (0.94.0, dev 1065)")
    ap.add_argument("--attended", action="store_true",
                    help="with --linkedin-search-on: a person is turning it on (the word is typed, not proved)")
    ap.add_argument("--warning", metavar="YYYY-MM-DD", help="with --linkedin-search-on: the date of the NEWEST linkedin-warning")
    ap.add_argument("--scope", choices=(SEARCH_SCOPE,), default=None,
                    help="with --pass linkedin --phase returned: the row is the LinkedIn search's own (0.94.0, dev 1065)")
    ap.add_argument("--search-reason", dest="search_reason", choices=SEARCH_REASONS, default=None,
                    help="with --scope search --jobsearch unreachable: why no page was read")


def wants(args):
    """True when the call is `--linkedin-search-skip` or `--linkedin-search-on`."""
    return bool(args.linkedin_search_skip or args.linkedin_search_on)


def run(root, args, at):
    """Write the event the flags name and print one line. Raises `JournalError` on a refusal (nothing written). Returns 0."""
    if args.linkedin_search_skip and args.linkedin_search_on:
        raise JournalError("--linkedin-search-skip and --linkedin-search-on are two calls")
    if args.linkedin_search_skip:
        if not args.until:
            raise JournalError("--linkedin-search-skip requires --until YYYY-MM-DD")
        row = record_linkedin_search_skip(root, args.until, at=at)
        print("LinkedIn job search skipped until %s" % row["until"])
        return 0
    if not args.warning:
        raise JournalError("--linkedin-search-on requires --warning YYYY-MM-DD (the date of the newest LinkedIn warning) and --attended")
    row = record_linkedin_search_on(root, args.warning, bool(args.attended), at=at)
    print("scheduled LinkedIn job search turned back on (the warning of %s)" % row["warning"])
    return 0
