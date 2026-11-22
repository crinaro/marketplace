"""guard_routes: the routing checks `check_mail_guard_matcher.py` runs over the send guard's hooks.json entries (moved out of that
entry point, which is over its 300-line budget, unchanged by `split_module.py`; jobsearch 0.91.0 B7).

The connector entry's PROPERTY lives here: names generated from the guard's OWN vocabulary (`generated_names`), the matcher
evaluated through `node` the way Claude Code evaluates it (`node_route`), and `check_connector_entry`, which holds "whatever the
floor denies, the matcher routes". The gate's docstring states why each exists.

Capability module of `check_mail_guard_matcher.py`. Python 3.9+, standard library only."""

import itertools
import json
import shutil
import subprocess


UUID = "0a1b2c3d-0000-4000-8000-000000000000"
# The server shapes the generated population is crossed with.
SERVERS = (UUID, "claude_ai_Gmail", "claude_ai_Outlook", "outlook-work",
           "plugin_fastmail_fastmail", "plugin_acme_superhuman", "microsoft365")
# Names that are READ tools and must NOT be routed (design §5.4: `search_threads` does not).
READ_NAMES = ("search_threads", "get_thread", "get_message", "list_labels", "search_email",
              "read_email", "read_thread", "list_threads", "outlook_email_search", "read_resource",
              "get_attachment", "query_email_and_calendar")


def case_class(word):
    """`send` -> `[Ss][Ee][Nn][Dd]`: every letter a case class, so any casing matches."""
    return "".join("[%s%s]" % (c.upper(), c) for c in word)


def expected_connector_matcher(g):
    """CONNECTOR_SEND_MATCHER recomputed from CONNECTOR_SEND_VERBS: the literal in the guard and
    the verb list it is derived from cannot drift apart unseen."""
    return "^mcp__.*(%s)" % "|".join(case_class(v) for v in g.CONNECTOR_SEND_VERBS)


def render_styles(tokens):
    """One token list rendered in every separator/case style the platform's tool names use."""
    cap = [t.capitalize() for t in tokens]
    return {
        "_".join(tokens),                                  # send_mail
        "-".join(tokens),                                  # send-mail
        tokens[0] + "".join(cap[1:]),                      # sendMail
        "".join(cap),                                      # SendMail
        "_".join(t.upper() for t in tokens),               # SEND_MAIL
        "_".join(cap),                                     # Send_Mail
        "".join(tokens),                                   # run together, lower case
        "".join(t.upper() for t in tokens),                # SENDMAIL
    }


def generated_names(g):
    """Names built from the guard's OWN vocabulary x separators x server shapes."""
    mail = sorted(g.FLOOR_MAIL_TOKENS | {"mail", "email", "emails", "outlook", "inbox", "gmail"})
    acts = sorted(g.FLOOR_SEND_TOKENS | g.FLOOR_REPLY_TOKENS | g.FLOOR_RULE_TOKENS
                  | {"send", "forward", "forwarding", "unsubscribe", "autoreply", "reply",
                     "replies", "filter", "filters", "rule", "rules"})
    verbs = sorted(g.FLOOR_RULE_VERBS | {"create", "update", "set"})
    lists = [[a] for a in acts]
    lists += [[v, a] for v in verbs for a in acts]
    lists += [["set", "automatic", "replies"], ["create", "reply", "draft"], ["auto", "reply"]]
    tools = set()
    for m, toks in itertools.product(mail, lists):
        for order in (toks + [m], [m] + toks):
            tools |= render_styles(order)
    names = set()
    for tool in tools:
        for server in SERVERS:
            names.add("mcp__%s__%s" % (server, tool))
    return sorted(names)


def node_route(matcher, names):
    """For each name, does `new RegExp(matcher).test(name)` — the way Claude Code evaluates a
    matcher — select it? Returns (list_of_bool, None) or (None, why-it-could-not-run)."""
    node = shutil.which("node")
    if not node:
        return None, "node not found"
    script = ("const m=new RegExp(process.argv[1]);"
              "const n=JSON.parse(require('fs').readFileSync(0,'utf8'));"
              "process.stdout.write(JSON.stringify(n.map(x=>m.test(x))));")
    try:
        r = subprocess.run([node, "-e", script, matcher], input=json.dumps(names),
                           capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        return None, "node did not run: %s" % e
    if r.returncode != 0:
        return None, "node exited %d: %s" % (r.returncode, (r.stderr or "")[:200])
    try:
        out = json.loads(r.stdout)
    except ValueError:
        return None, "node printed non-JSON: %r" % r.stdout[:120]
    if len(out) != len(names):
        return None, "node answered %d of %d names" % (len(out), len(names))
    return out, None


def check_connector_entry(g, actual):
    """(problems, notes) for the connector entry's matcher; problems == [] when clean."""
    problems, notes = [], []
    if not isinstance(actual, str) or "(?" in actual:
        problems.append("the connector matcher is not a string, or uses a (? group — JavaScript and "
                        "Python regular expressions disagree on those.")
        return problems, notes
    if actual != g.CONNECTOR_SEND_MATCHER:
        problems.append("DRIFT: hooks.json's connector matcher does not equal the guard's "
                        "CONNECTOR_SEND_MATCHER.")
    if g.CONNECTOR_SEND_MATCHER != expected_connector_matcher(g):
        problems.append("DRIFT: CONNECTOR_SEND_MATCHER does not equal the matcher recomputed from "
                        "CONNECTOR_SEND_VERBS (%s)." % ", ".join(g.CONNECTOR_SEND_VERBS))
    if not actual.startswith("^mcp__"):
        problems.append("the connector matcher is not anchored `^mcp__`.")

    published = ["mcp__%s__%s" % (UUID, n) for n in g.CONNECTOR_PUBLISHED_SEND_NAMES]
    floor_samples = ["mcp__%s__%s" % (UUID, n) for n in
                     ("outlook_send_mail", "send_email", "sendMail", "send-email", "Send_Mail",
                      "outlook_set_automatic_replies", "outlook_create_filter")]
    reads = ["mcp__%s__%s" % (UUID, n) for n in READ_NAMES]
    population = generated_names(g)
    denied = [n for n in population if g.floor_denies(n)]
    notes.append("generated %d names (%d servers); the floor denies %d of them"
                 % (len(population), len(SERVERS), len(denied)))
    if not population or not denied:
        problems.append("the generated population is empty, or the floor denied none of it — the "
                        "property below would be vacuous.")
        return problems, notes

    everything = published + floor_samples + reads + population
    routed, why = node_route(actual, everything)
    if routed is None:
        problems.append("NOT CHECKED: %s. The property gate evaluates the matcher through node "
                        "(Claude Code evaluates it as JavaScript); without it nothing was checked."
                        % why)
        return problems, notes
    verdict = dict(zip(everything, routed))
    for n in published:
        if not g.floor_denies(n):
            problems.append("COVERAGE: the published send name %s is not denied by the guard." % n)
        if not verdict[n]:
            problems.append("BEHAVIOUR: the matcher does not route the published send name %s." % n)
    for n in floor_samples:
        if not g.floor_denies(n):
            problems.append("COVERAGE: the fixed sample %s is not denied by the guard." % n)
        if not verdict[n]:
            problems.append("BEHAVIOUR: the matcher does not route the fixed sample %s." % n)
    for n in reads:
        if verdict[n]:
            problems.append("BEHAVIOUR: the matcher routes the read tool %s — it should leave it "
                            "alone." % n)
    missed = [n for n in denied if not verdict[n]]
    if missed:
        problems.append("PROPERTY: the floor denies %d generated name(s) that the matcher does NOT "
                        "route, so the deny would never run for them. First few: %s"
                        % (len(missed), ", ".join(missed[:5])))
    notes.append("property floor-denies => matcher-routes, evaluated through node: %d of %d routed"
                 % (len(denied) - len(missed), len(denied)))
    return problems, notes
