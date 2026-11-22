"""PageData: the contract between the loader (`generate_dashboard.build_page`) and the renderers
(dashboard-redesign A; step D1 adds Today's fields)."""


class PageData(object):
    """The page-wide values of one render: every flat-script constant, derivation and clock read a
    renderer used to fetch at render time, filled once by the loader (`generate_dashboard.build_page`).
    Fields not given are None; an unknown field is refused (a misspelt field must not read as empty).

    now                 the render's ONE clock (a naive local datetime); renderers derive the day from it
    currency            profile.currency_symbol()
    terminal_statuses   validate_data.TERMINAL_OPP_STATUSES
    plan_groups         your_move.PLAN_GROUPS, the Network list's group order
    needs_human         precondition.NEEDS_HUMAN
    queued_by_contact   {contact id: the pending deferred item that clears its queued draft}
    pick_rows           {page key: (action record id, action_block.record_line(id, name))} for every row a tick box
                        can name: drafts, cover letters, roles, plan rows, listed companies (D2; `dashboard.levels`)
    pick_heads          {action: action_block.head(action)}, for each group button's `data-head` (D2)
    title, run_id, network_rel, net_sent_proposals   the page's heading, the generating run, the
                        Network file's name and the count of sent proposals, for the page frame
    today_drafts, today_plan, today_roles, today_targets, quiet_days   Today's sources, each in its owner's
                        order (D1; their shapes are in `dashboard.rank`'s docstring)
    today_counts        the counts Today's empty sentence names (D1; the keys are in `dashboard.today`'s docstring)
    network_text        the Network list's prompt fragments (D2b; the shape is in `dashboard.network`'s docstring)
    targets_text        the Targets list's prompt fragments (D2b; the shape is in `dashboard.targets`'s docstring)
    targets_ask         the ids of the listed companies that get the staffing question (D2b; §8 signals T1, T2)
    targets_not_raised  the qualifying companies no run has raised yet ("N more will be raised by later runs", E1b)
    ref_of              {plan row key: the key of the primary row it refers to} (`network.ref_targets`, dev 973): the
                        Network row renders as a reference, and Today's item for it links that primary row
    handoff             {"pages": {person id: recorded LinkedIn address}, "outbox": {draft_ref: outbox row}}: what a Drafts
                        row hands off (`drafts.handoff_data`, jobsearch 0.91.0 B7a); None renders no hand-off
    """
    FIELDS = ("now", "currency", "terminal_statuses", "handoff",
              "plan_groups", "needs_human", "queued_by_contact", "title",
              "run_id", "network_rel", "net_sent_proposals", "today_drafts", "today_plan", "today_roles",
              "today_targets", "today_counts", "quiet_days", "pick_rows", "pick_heads",
              "network_text", "targets_text", "targets_ask", "targets_not_raised", "ref_of")

    def __init__(self, **values):
        unknown = sorted(set(values) - set(self.FIELDS))
        if unknown:
            raise TypeError("PageData has no field %s" % ", ".join(unknown))
        for name in self.FIELDS:
            setattr(self, name, values.get(name))
