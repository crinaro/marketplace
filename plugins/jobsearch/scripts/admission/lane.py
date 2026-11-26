"""lane: the roles that meet the owner's criteria are read first, newest first, inside a bound on open decisions (jobsearch 0.94.0,
step P2; dev 1062; docs/design-role-first.md 4.1, 4.3, RF6, RF7).

`lifecycle.drain_plan` builds its candidate buckets as before. When the profile carries the 0.94.0 pin, `build` takes out of them every role
the first look RELEASED (`Ctx.released`; a waiting role and also its `retry`, `held` and `returned` re-admissions), so a released role never spends
a company slot or splits a company, and chooses the lane:

  capacity   `cap` is what the plan may admit in all (`min(300, 10800 // per_role_s)`, 0 with no render route). The lane takes at most
             `search.matching_roles_per_run` of it, and at most half of it while any company candidate waits, so a company the owner chose is
             never starved by the backlog. `admit` gives the companies the rest.
  order      `retry`, `returned`, `held`, then NEW roles newest first (`posted.date`, else the first sighting, then the id): a posting loses value
             with age (OURS, the owner asked for newest first; Kanban pulls the highest priority instead).
  bound      `search.open_decisions_max` is a work-in-progress limit (Kanban's, DOCUMENTED): new lane roles are at most
             `room = max(0, bound - open - in_flight)`. `open` is the roles at `ready` at a company that is not a stated target; `in_flight` the
             roles at such a company that were admitted after the release instant and are not finished (a failure, read, screened, awaiting
             research, or YOUR READ for an environment cause). A role whose posting a SCRIPT can read (its address is not a LinkedIn one: feed,
             ATS, plain page) is limited only by `open` plus the in-flight roles whose cause is not an environment one, so roles stuck on a hidden
             pane never block roles that need no pane. Retries are already in `in_flight` and stay admissible.

`Lane.matching()` is the `matching` block of the `drain planned` row; `Lane.text` says why the room is 0 in words (design 4.3), the same words
on the plan, the start line and the summary. Pure: no I/O, no clock; it imports no entry point (G5). Python 3.9+, standard library only."""

import datetime
import urllib.parse

from admission import hold as _hold, plan as _plan, release as _rel

ORDER = ("retry", "returned", "held", "new")             # the lane's own class order; `legacy` never applies to a released role
SCRIPT_TEXT = "%d role decisions are open"
OPEN_TEXT = "%d role decisions are open or being read"
HIDDEN_TEXT = "%d matching roles could not be read from a hidden pane: run the drain attended"


def posted_date(row):
    """The date a posting says it was posted (`posted.date`, with a source that is not `unknown`), else None."""
    p = row.get("posted") if isinstance(row, dict) else None
    if isinstance(p, dict) and p.get("source") not in (None, "unknown"):
        try:
            return datetime.date.fromisoformat(str(p.get("date")))
        except ValueError:
            return None
    return None


def newest_key(entry):
    """The sort key of one candidate `(since, key, unit)`: the newest first (`posted.date`, else the first sighting `since`), then the id."""
    since, key, unit = entry
    day = posted_date(unit.rows[0]) or since
    return (-day.toordinal(), key)


def _linkedin(url):
    host = (urllib.parse.urlparse(url).hostname or "") if isinstance(url, str) else ""
    return host == "linkedin.com" or host.endswith(".linkedin.com")


def script_readable(unit):
    """True when a SCRIPT can read this role's posting: its first address (`jd_url`, else a capture item's `ref`, else the first sighting's) is
    not a LinkedIn one (those are browser-first, `recording.fetching`). A role with no address at all is not."""
    for row in unit.rows:
        urls = [row.get("jd_url"), row.get("ref")] + [s.get("source_url") for s in (row.get("sightings") or ()) if isinstance(s, dict)]
        first = next((u for u in urls if isinstance(u, str) and u.strip()), None)
        if first is not None:
            return not _linkedin(first)
    return False


def _ids(ctx, u):
    opp_ids, item_ids = ctx.unit_ids(u)
    return opp_ids + item_ids + [i for o in opp_ids for i in ctx.opp_ids(ctx.opps_by_id[o])[1:]]


def counts(ctx, instant, progress, env_causes):
    """`(open, in_flight, hidden)` over the snapshot (design 4.3): the roles at `ready` at a company that is not a stated target; the roles at
    such a company admitted after `instant` and not finished; and, of those, the ones stopped by an environment cause (a hidden pane)."""
    n_open = n_fly = n_env = 0
    for u in ctx.units():
        st = u.stage
        if u.folded or st.name == "unclassified" or _hold.stated_target(ctx.companies_by_id, _plan.company_of(u, ctx)):
            continue
        if st.name == "ready":
            n_open += 1
        elif (st.failure or st.name in progress or (st.name == "your-read" and st.cause in env_causes)) \
                and _rel.after(ctx.admissions(_ids(ctx, u)), ctx.planned_at, instant):
            n_fly += 1
            n_env += st.cause in env_causes
    return n_open, n_fly, n_env


def bound_text(n_open, in_flight, hidden, bound):
    """Why the room is 0, or "" when it is not (design 4.3): the open decisions, the matching roles a hidden pane stopped, or both."""
    if bound - n_open - in_flight > 0:
        return ""
    parts = []
    if n_open + in_flight - hidden >= bound:
        parts.append((SCRIPT_TEXT % n_open) if n_open >= bound else (OPEN_TEXT % (n_open + in_flight - hidden)))
    if hidden:
        parts.append(HIDDEN_TEXT % hidden)
    return " · ".join(parts)


class Lane(object):
    """The lane of one plan: `entries` (admission order, `(class index, since, key, class, unit)`, the shape `plan.admit` takes), `considered`
    (every released candidate), `left` (the candidates not admitted), the three counts, and the settings."""

    def __init__(self, setting, bound):
        self.setting, self.bound = setting, bound
        self.entries, self.considered, self.left = [], 0, []
        self.open = self.in_flight = self.hidden = 0
        self.text = ""

    def lines(self, no_route):
        """The plan's own lines about the lane (`lifecycle.Plan.lines`): what it admitted, what waits, and why the room is 0."""
        m = self.matching()
        out = ["matching roles: %d of %d that meet your criteria admitted (at most %d a run); %d role decisions open, %d being worked "
               "(bound %d)%s" % (m["admitted"], m["considered"], m["setting"], m["open"], m["in_flight"], m["bound"],
                                 "; %d wait for intake" % len(self.left) if self.left else "")]
        if no_route:
            out.append("matching roles: none admitted: no render route on this surface; run on the desktop")
        if self.text:
            out.append("matching roles are held back: " + self.text)
        return out

    def matching(self):
        """The `matching` block of the `drain planned` row (`journaling.search_rows.check_matching_block`)."""
        return {"setting": self.setting, "considered": self.considered, "admitted": len(self.entries),
                "waiting": self.considered - len(self.entries), "open": self.open, "in_flight": self.in_flight, "bound": self.bound}


def build(ctx, buckets, per_run, bound, cap, progress, env_causes):
    """The `Lane` of this plan, or None when the profile has no 0.94.0 pin (the plan is then 0.93.0's, byte for byte). Takes the released
    roles out of `buckets` (`{class: [(since, key, unit)]}`) in place. `cap` is what the plan may admit in all."""
    if ctx.release_at is None:
        return None
    out = {c: [e for e in buckets[c] if e[1] in ctx.released] for c in ORDER}
    for c in ORDER:
        buckets[c][:] = [e for e in buckets[c] if e[1] not in ctx.released]
    out["new"].sort(key=newest_key)
    lane = Lane(per_run, bound)
    lane.open, lane.in_flight, lane.hidden = counts(ctx, ctx.release_at, progress, env_causes)
    lane.text = bound_text(lane.open, lane.in_flight, lane.hidden, bound)
    room_all = max(0, bound - lane.open - lane.in_flight)
    room_script = max(0, bound - lane.open - (lane.in_flight - lane.hidden))
    company_waits = any(buckets[c] for c in buckets)
    limit = min(per_run, cap // 2 if company_waits else cap)
    n_new = 0
    for cls in ORDER:
        for entry in out[cls]:
            lane.considered += 1
            since, key, unit = entry
            if len(lane.entries) >= limit:
                lane.left.append(unit)
                continue
            if cls == "new":
                if n_new >= (room_script if script_readable(unit) else room_all):
                    lane.left.append(unit)
                    continue
                n_new += 1
            lane.entries.append((0, since, key, cls, unit))
    return lane
