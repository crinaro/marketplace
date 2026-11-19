"""The coverage ledger of one render (dashboard-redesign A, moved from generate_dashboard.py): a `Ledger`
the entry point creates per `build_page` and passes down, and the ledger file's object."""


# ─────────────────────────────────────────────────────────────────────────────
# ⭐ THE COVERAGE LEDGER — Class C (dev/audit 2026-09-02). Every record in the four
# row-backed stores (opportunities, asks, commitments, call preps) is placed here as it
# renders: RENDERED (a row on the page carries `data-rec="<key>"`), REMAINDER (it is inside
# a "+K more" line whose K counts it, `data-more="<set>:<K>"`: since dashboard-redesign D2, level 3
# of a list, past its level-2 fold, the line naming the sentence that shows it, design §4), or
# TERMINAL (it has ended and the page says so by omission).
# Anything in none of those is a record the page lost
# silently — the exact shape of the backlog defect above. The ledger is written beside
# the artifact (views/dashboard_coverage.json) and `check_dashboard_coverage.py` verifies
# it AGAINST THE HTML, never trusting the ledger alone (verify the artifact, not the plan).
# Separate from check_dashboard_fresh.py on purpose: freshness is bytes and stamps; this is
# membership, and one check must not grow a second meaning.
# ─────────────────────────────────────────────────────────────────────────────
class Ledger(object):
    """The coverage ledger of ONE render (dashboard-redesign A: it was the module state `COVERAGE` behind
    `_cover` / `_cover_set`, which a second in-process render inherited). The entry point creates one per
    `build_page` and passes it down; every renderer that places a record writes here. `doc` is the ledger
    file's object once the loader has finished (`document`), and `summary` the counts `main` prints. The
    `filters` block and its CSS went with the filter chips (dashboard-redesign D2, D-6). `today` is what the Today list
    placed (`place_today`): its absence from a ledger file marks a page made before Today existed, which the coverage
    gate reads as `LEDGER PREDATES TODAY`, a regenerate gap (design §12)."""

    def __init__(self):
        self.records, self.remainders = {}, {}
        self.doc, self.summary = None, {}
        self.today = None

    def place_today(self, cap, items):
        """Today's block of the ledger file: the cap it was built with and one entry per item, in page order:
        `{"kind": <kind>, "ref": <record key>}` for a single item, `{"kind": <kind>, "count": <members>}` for a group
        item. An empty list is the sentence. Today places no record (it holds references only, §3.6 rule 1)."""
        self.today = {"cap": int(cap), "items": [dict(i) for i in items]}

    def cover(self, key, disposition, where):
        """Place one record. A record rendered anywhere is RENDERED even if another set
        trimmed it into a remainder — the strongest placement wins."""
        cur = self.records.get(key)
        if cur is None or _DISP_RANK[disposition] > _DISP_RANK[cur["disposition"]]:
            self.records[key] = {"disposition": disposition, "where": where}

    def cover_set(self, set_name, shown_keys, rest_keys):
        """One capped set: what it showed and what it trimmed into its remainder."""
        for k in shown_keys:
            if k:
                self.cover(k, "rendered", set_name)
        for k in rest_keys:
            if k:
                self.cover(k, "remainder", set_name)
        if rest_keys:
            self.remainders[set_name] = len(rest_keys)

    def document(self, today, horizon_days, terminal_statuses):
        """The ledger file's object (views/dashboard_coverage.json) for a render on `today` (a date)."""
        return {
            "generated_on": today.isoformat(),
            "window": {"today": today.isoformat(), "prep_horizon_days": horizon_days},
            "terminal_statuses": sorted(terminal_statuses),
            "records": self.records,
            "remainders": self.remainders,
            # dashboard-redesign E (design §12): what Today placed; a ledger without this block predates Today.
            "today": self.today if self.today is not None else {"cap": None, "items": []},
            # jobsearch 0.71.0 - the homes an `elsewhere` record may name.
            "elsewhere_homes": list(ELSEWHERE_HOMES),
        }


# `elsewhere` (jobsearch 0.71.0, amending ADR-024): the record is not on this page BY DESIGN and lives
# in a named home (`where` is the home: panel, review-resume or review-linkedin). It ranks lowest, so a
# record that is rendered, counted in a remainder or terminal keeps that placement.
_DISP_RANK = {"rendered": 3, "remainder": 2, "terminal": 1, "elsewhere": 0}


# The homes a record can live in once the page no longer renders it (design §4, amending ADR-024):
# `panel` is scripts/panel.py's `elsewhere` object; the two review homes are presence_set.py's panes.
ELSEWHERE_HOMES = ("panel", "review-resume", "review-linkedin")
