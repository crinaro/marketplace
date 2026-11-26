"""channel_reach: a due sourcing channel that no available agent or surface reaches (dev #1025 / public #272).

Capability module of `channels_due.py`, which prints the UNREACHABLE section of the channel review queue.

The board sweeper leaves a channel another agent owns (`channels_due.owner_elsewhere`, dev #830) to that agent, and the printed queue
keeps it DUE. Two cases mean no agent will ever review it, so it stayed due forever and read as merely overdue:

  host-label   the row is claimed for the owning agent by its name alone (a user-made `linkedin-saved-jobs` row), and that agent
               sweeps only its own catalog entry (the LinkedIn runner reads the job search, never a saved-jobs list), so nobody reads it;
  pane hidden  the owner is `linkedin-runner` and its latest passes ran with the Browser pane hidden (`hidden_passes.blocking`):
               it reads by text only and cannot open a login-only list from a hidden pane.

Each is printed with the attended action that would reach it, and leaves DUE NOW. Pure: the caller passes the due rows, the journal
records and its own ownership answer.
"""

from browser_fallback import hidden_passes as _hidden_passes

RUNNER = "linkedin-runner"
SEARCH_CHANNEL = "linkedin-jobsearch"      # the one channel the job search is (`searching.jobsearch_line.JOBSEARCH_CHANNEL`; a test holds the two equal)


def unreachable(channel, owned, recs):
    """`(why, action)` when no available agent or surface reaches this due `channel`, else None. `owned` is `(agent, rule)` from
    `channels_due.owner_elsewhere`, or None when the board sweeper may take the channel itself."""
    if not owned:
        return None
    agent, rule = owned
    cid = channel.get("id")
    if rule == "host-label":
        return ("owned by %s by its name, but %s sweeps only its own catalog entry and the board sweeper leaves it to %s, "
                "so no agent reads it" % (agent, agent, agent),
                "open it yourself, then `channels_due.py --stamp %s`; or link the row to a catalog entry "
                "(`channel_catalog_entry`) or retire it" % cid)
    if agent == RUNNER and not _hidden_passes.pinned(recs):
        if _hidden_passes.blocking(recs):          # no 0.94.0 pin: 0.93.0's rule, its words
            n, _since = _hidden_passes.hidden_streak(recs)
            return ("owned by %s, whose last %d passes ran with the Browser pane hidden" % (agent, n),
                    "%s (one attended pass with the Browser pane shown)" % _hidden_passes.REMEDY)
        return None
    if agent == RUNNER:
        # 0.94.0 (dev 1065, design 8.2): the job search is its own dispatch, so ITS channel is blocked by the search's own streak and cleared by an attended search; every other channel the
        # runner owns is blocked by the reply sweep's streak (passes that left a list unread) and cleared by `/jobsearch:linkedin`
        kind = _hidden_passes.SEARCH if cid == SEARCH_CHANNEL else _hidden_passes.REPLIES
        if kind in _hidden_passes.blocked_kinds(recs):
            n = _hidden_passes.search_streak(recs)[0] if kind == _hidden_passes.SEARCH else _hidden_passes.reply_streak(recs)[0]
            return ("owned by %s, whose last %d %s ran with the Browser pane hidden" % (agent, n, "searches" if kind == _hidden_passes.SEARCH else "passes"),
                    "%s. %s." % (_hidden_passes.remedy(kind), _hidden_passes.TEMPORARY))
    return None


def split(due, recs, owned):
    """`(reachable, unreachable)` over `due` (`[(channel, why)]`): `unreachable` is `[(channel, why, action)]`. `owned` is
    `channels_due.owned_elsewhere_of(...)`, `{channel_id: {"agent", "rule"}}` over board-admissible channels only, so a recruiter
    row whose id happens to start `linkedin-` is never read as owned."""
    keep, out = [], []
    for c, why in due:
        o = (owned or {}).get(c.get("id"))
        got = unreachable(c, (o["agent"], o["rule"]) if o else None, recs)
        if got:
            out.append((c, got[0], got[1]))
        else:
            keep.append((c, why))
    return keep, out


def lines(unreach):
    """The printed UNREACHABLE section (empty when nothing is unreachable)."""
    if not unreach:
        return []
    out = ["\nUNREACHABLE — due, but no available agent or surface reaches it; it stays due until you act:"]
    for c, why, action in unreach:
        out.append("  ✖ %-24s [%s] %s" % (str(c.get("label") or c.get("id"))[:24], c.get("access", "?"), why))
        out.append("      reach it: %s" % action)
    return out
