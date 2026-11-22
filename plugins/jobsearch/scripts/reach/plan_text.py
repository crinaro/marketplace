"""plan_text: the week's reach-out plan and the 3B7 actions as text, over the dicts `reachouts.plan` and `reachouts.due` return
(jobsearch 0.91.0, design-build-reach.md 12 B2).

Reads only what it is handed: no store, no config, no clock. Nothing here sends; every line is a draft or a link for the candidate.
Moved out of `reachouts.py` unchanged by split_module.py (step B2-A), so the entry point can take the employment filter without
growing.

Capability module of `reachouts.py`. Python 3.9+, standard library only."""


def render(p):
    out = ["NETWORK BUDGET %s: %d a week · sent %d · open drafts %d · remaining %d"
           % (p["week"], p["budget"], p["sent_this_week"], p["open_drafts"], p["remaining"])]
    if p["remaining"] == 0 and p["budget"] > 0:
        out.append("  the week's budget is spent: no new reach-out is drafted this run")
    if p["budget"] == 0:
        out.append("  network.new_reachouts_per_week is 0: new reach-outs are off")
    for l in p["lines"]:
        label = "SECOND-CONTACT" if l["kind"] == "second-contact" else "REACH-OUT"
        out.append("%s %s (%s) at %s -- %s (draft this; nothing is sent)"
                   % (label, l["person_id"], l["person_name"] or "no name", l["company_name"] or l["company_id"], l["why"]))
    for l in p.get("followups", []):
        out.append("FOLLOW-UP %s (%s) at %s -- %s (draft this; nothing is sent)"
                   % (l["person_id"], l["person_name"] or "no name", l["company_name"] or l["company_id"], l["why"]))
    for l in p.get("quiet", []):
        out.append("QUIET %s (%s) at %s -- %s" % (l["person_id"], l["person_name"] or "no name",
                                                  l["company_name"] or l["company_id"], l["why"]))
    for l in p.get("age_unknown", []):
        out.append("AGE-UNKNOWN %s (%s) -- %s, so it cannot be called a send unobserved; it still counts against the budget "
                   "(record the send with record.py touch, or delete the draft)" % (l["ref"], l["person"], l["reason"]))
    for l in p.get("role_specific", []):
        out.append("ROLE-SPECIFIC %s (%s) at %s -- %s (not budgeted; a draft for the candidate to send)"
                   % (l["person_id"], l["person_name"] or "no name", l["company_name"] or l["company_id"], l["why"]))
    for l in p.get("reconnects", []):
        out.append("RECONNECT %s (%s) at %s -- %s (not budgeted; a draft for the candidate to send)"
                   % (l["person_id"], l["person_name"] or "no name", l["company_name"] or l["company_id"] or "no company", l["why"]))
    for b in p.get("build", []):          # 0.91.0 (design-build-reach.md 6.2): a way in where there is none; in the budget
        if b["kind"] != "plain-lookup":   # a plain lookup IS the company's LOOKUP line below, now holding a budget slot
            out.append(_build_line(b, "budgeted"))
    for b in p.get("build_pointers", []):
        out.append(_build_line(b, "not budgeted"))
    for l in p["lookups"]:
        out.append("LOOKUP %s (%s)%s (a link for the candidate to open; no LinkedIn step is automated)"
                   % (l["company_id"], l["company_name"] or l["company_id"],
                      " " + l["linkedin_url"] if l["linkedin_url"] else ""))
    for w in p.get("weekly", []):
        out.append("%s %s (this week; not budgeted; nothing is registered or sent)" % (w["kind"].upper(), w["why"]))
    for l in p.get("looked_none", []):
        out.append("LOOKED %s (%s) -- looked %s and found nobody; the LOOKUP returns on %s (search.warm_lookup_days)"
                   % (l["company_id"], l["company_name"] or l["company_id"], l["looked_on"], l["lookup_returns_on"]))
    for l in p.get("confirm", []):        # 0.91.0: one line per target with unconfirmed people; not budgeted, nothing drafted
        out.append("CONFIRM %s (%s) -- %s" % (l["company_id"], l["company_name"] or l["company_id"], l["why"]))
    return "\n".join(out)


def _build_line(b, budget):
    """One BUILD line (`reach/build.py`): kind, company, whom or what, the words and the link, and whether it is in the budget."""
    who = b.get("person_id") or b.get("affiliation") or b.get("opp_id") or ""
    extra = "".join(" -- %s" % v for v in (b.get("words"), b.get("link")) if v)
    say = " (say: %s)" % ", ".join(b["say"]) if b.get("say") else ""
    return ("BUILD %s %sat %s -- %s%s%s (%s; a draft or a link for the candidate; nothing is sent)"
            % (b["kind"].upper(), who + " " if who else "", b.get("company_name") or b.get("company_id"), b["why"], extra, say, budget))


def render_due(actions):
    """The `--due` output: one line per 3B7 action, drafts and links only (nothing here sends)."""
    if not actions:
        return "3B7: nothing is due"
    out = ["3B7: %d action%s due" % (len(actions), "" if len(actions) == 1 else "s")]
    for a in actions:
        if a["kind"] == "second-contact":
            out.append("SECOND-CONTACT %s (%s) at %s -- %s (draft this; nothing is sent)"
                       % (a["person_id"], a["person_name"] or "no name", a["company_name"] or a["company_id"], a["why"]))
        elif a["kind"] == "follow-up":
            out.append("FOLLOW-UP %s (%s) at %s -- %s (draft this; nothing is sent)"
                       % (a["person_id"], a["person_name"] or "no name", a["company_name"] or a["company_id"], a["why"]))
        elif a["kind"] == "quiet":
            out.append("QUIET %s (%s) at %s -- %s" % (a["person_id"], a["person_name"] or "no name",
                                                      a["company_name"] or a["company_id"], a["why"]))
        else:
            out.append("LOOKUP %s (%s)%s -- %s (a link for the candidate to open; no LinkedIn step is automated)"
                       % (a["company_id"], a["company_name"] or a["company_id"],
                          (" " + a["linkedin_url"]) if a.get("linkedin_url") else "", a["why"]))
    return "\n".join(out)
