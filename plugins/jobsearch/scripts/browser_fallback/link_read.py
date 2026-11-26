"""link_read: the read-only reader of the job ids on a LinkedIn results page already loaded, and the strict match of those ids to the roles a pass read
(jobsearch 0.94.0, dev 1064, 1065; docs/design-role-first.md 7.1 to 7.4, 19.3 N13, 19.4, 19.5; criteria HD1, HD2, HD8).

WHY. A pass that reads a results page by text sees each card's title and company and no link, so it can capture next to nothing. The ids ARE on the loaded page (TESTED 2026-11-25, one
page: 25 of 25 cards carry one, in `componentkey="job-card-component-ref-<digits>"`). `LINKS_JS` reads them, sending and opening nothing, and `match` attaches an id to a role only when it
is certain.

THE OWNER'S DECISION (OD-6, yes, 2026-11-25) AND ITS EXPOSURE. LinkedIn bars software that scrapes or automates. `LINKS_JS` is a script that reads a page for data, so it sits nearer the
prohibited side than reading text. It is NOT claimed to be permitted. It runs at most once per results page, at most 25 links a search and 500 a pass (OD-10, OD-11), in any session.

`LINKS_JS` (fenced byte-equal in `agents/linkedin-runner.md`, `<!-- links-js:begin -->`) returns `{path, search, state, cards, entries: [{id, text}]}` for the page it runs on:

  path, search  `location.pathname` and `location.search` (the SETTLED address: `address_drift` compares it with the address the pass sent, N14; the query string is never stored)
  state         `document.readyState`
  cards         the cards on the page, counted WITHOUT their ids: the nearest `li` of each dismiss control, else the number of ids read
  entries       one per distinct id: its digits and the first 160 characters of that card's own text. The id comes from `[componentkey^="job-card-component-ref-"]` (N13), and ONLY
                when the page has none of those, from `[data-occludable-job-id]` / `[data-job-id]`, and only when it has none of those, from a `/jobs/view/<digits>` link.

READ-ONLY. It reaches only `location.pathname|search`, `document.readyState`, `document.querySelectorAll`, `getAttribute`, `closest`, `innerText` (and `Array`, `RegExp`, `Object`);
`tests/browser_fallback/test_link_read.py` runs the SHIPPED constant under node against a Proxy that throws on anything else. PARTIAL: an instruction, a stub and a text scan; nothing at runtime
stops another script (the same standing limit as clicks in hidden mode), and the layout is measured on one page of one account.

THE VERDICT (7.4, N13). `read_verdict(raw, roles, tool_error)` is STRICT and returns `(line, ids)`, `line` ONE of the five forms the ROLES block's `LINKS` line carries and the `roles` event
counts (`journaling.search_rows.LINKS_VERDICTS`):

  LINKS matched=<m> unmatched=<k>        cards with ids were read; `m` of the pass's roles got an id, `k` did not
  LINKS PARTIAL cards=<n> ids=<m>        the card count differs from the id count (either way): never a silent short list; ids are still given where the match is certain
  LINKS NO-IDS cards=<n>                 the page loaded and no card carries an id: the roles are nourl, the page shows none
  LINKS NOT-LOADED                       no cards, not a `/jobs/` page (a sign-in wall, a detached page), or the page was not complete: nourl, not read
  LINKS READ-ERROR                       a tool error (the caller passes `tool_error`), a timeout, text that is not JSON, or any other shape: nourl, not read

AN ID GOES TO A ROLE ONLY WHEN EXACTLY ONE ENTRY'S TEXT HOLDS BOTH ITS TITLE AND ITS COMPANY, and no other role holds the same entry (two roles that would share a card get no id).
Else the role stays `ROLE nourl`. A match on the title alone is never made (a company posts the same title in many places).

Pure. Python 3.9+, standard library only."""

import json
import re
import urllib.parse

MAX_LINKS_SEARCH = 25               # ids taken from one search's page (OD-10), held by `search_page.py links` with the journal's count
MAX_LINKS_PASS = 500                # ids taken in one pass (OD-11)
KEY_PREFIX = "job-card-component-ref-"
KEY_SELECTOR = '[componentkey^="%s"]' % KEY_PREFIX
OLD_SELECTOR = "[data-occludable-job-id], [data-job-id]"
LINK_SELECTOR = 'a[href*="/jobs/view/"]'
DISMISS_SELECTOR = 'button[aria-label^="Dismiss"]'
TEXT_MAX = 160
RESULTS_PATH = "/jobs/"
ENTRY_KEYS = ("id", "text")
READ_KEYS = ("path", "search", "state", "cards", "entries")
VIEW_URL = "https://www.linkedin.com/jobs/view/%s/"

# The only identifiers LINKS_JS may reference: documentation the test's own failure points back to. The test derives what the constant really contains and holds it to this list.
ALLOWED_CALLS = ("location.pathname", "location.search", "document.readyState", "document.querySelectorAll", "getAttribute", "closest", "innerText", "Array", "Object", "RegExp")

LINKS_JS = r"""(() => {
  const KEY = "[componentkey^=\"job-card-component-ref-\"]", OLD = "[data-occludable-job-id], [data-job-id]", LINK = "a[href*=\"/jobs/view/\"]", DISMISS = "button[aria-label^=\"Dismiss\"]", MAX = 160;
  const text = e => (e.innerText || '').replace(/\s+/g, ' ').trim();
  const best = Object.create(null), order = [];
  const take = (id, e) => {
    if (!id) return;
    if (best[id] === undefined) { best[id] = ''; order.push(id); }
    const t = text(e);
    if (t.length > best[id].length) best[id] = t;
  };
  for (const e of Array.from(document.querySelectorAll(KEY))) {
    const m = /^job-card-component-ref-(\d+)$/.exec(e.getAttribute('componentkey') || '');
    take(m ? m[1] : '', e);
  }
  if (order.length === 0) {
    for (const e of Array.from(document.querySelectorAll(OLD))) {
      const m = /^(\d+)$/.exec(e.getAttribute('data-occludable-job-id') || e.getAttribute('data-job-id') || '');
      take(m ? m[1] : '', e);
    }
  }
  if (order.length === 0) {
    for (const a of Array.from(document.querySelectorAll(LINK))) {
      const m = /\/jobs\/view\/(\d+)/.exec(a.getAttribute('href') || '');
      take(m ? m[1] : '', a.closest('li') || a);
    }
  }
  const lis = [];
  for (const b of Array.from(document.querySelectorAll(DISMISS))) {
    const c = b.closest('li');
    if (c && !lis.includes(c)) lis.push(c);
  }
  return {path: location.pathname, search: location.search, state: document.readyState,
          cards: lis.length > 0 ? lis.length : order.length,
          entries: order.map(id => ({id: id, text: best[id].slice(0, MAX)}))};
})()"""


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def _norm(text):
    return " ".join(str(text or "").casefold().split())


def _well_formed(read):
    """The exact shape `LINKS_JS` returns, every type held; `entries` have distinct digit ids and text of at most `TEXT_MAX` characters."""
    if not isinstance(read, dict) or set(read) != set(READ_KEYS):
        return False
    if not all(isinstance(read[k], str) for k in ("path", "search", "state")) or not _is_int(read["cards"]) or not isinstance(read["entries"], list):
        return False
    seen = set()
    for e in read["entries"]:
        if not isinstance(e, dict) or set(e) != set(ENTRY_KEYS) or not isinstance(e["id"], str) or not re.fullmatch(r"\d{1,20}", e["id"]):
            return False
        if not isinstance(e["text"], str) or len(e["text"]) > TEXT_MAX or e["id"] in seen:
            return False
        seen.add(e["id"])
    return True


def match(roles, entries):
    """`{index: id}` for the roles (`[{title, company}]`, in file order) that get an id: exactly one entry's text holds both the title and the company (case and spacing do not
    matter), and no other role holds that entry. A blank title or company never matches."""
    hits = {}
    for i, r in enumerate(roles):
        t, c = _norm(r.get("title")), _norm(r.get("company"))
        found = [e["id"] for e in entries if t and c and t in _norm(e["text"]) and c in _norm(e["text"])]
        if len(found) == 1:
            hits[i] = found[0]
    taken = {}
    for i, eid in hits.items():
        taken.setdefault(eid, []).append(i)
    return {i: eid for i, eid in hits.items() if len(taken[eid]) == 1}


def read_verdict(raw, roles=(), tool_error=False):
    """`(line, ids)`: `line` the `LINKS ...` line for what `LINKS_JS` returned (`raw`: its result as text or a parsed value; `tool_error` says the tool call itself failed), `ids` the
    `{role index: id}` that `match` made (empty unless cards with ids were read). Anything not exactly the shape `LINKS_JS` returns is `LINKS READ-ERROR`, never a crash and never an id."""
    if tool_error:
        return "LINKS READ-ERROR", {}
    value = raw
    if isinstance(raw, (str, bytes, bytearray)):
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            return "LINKS READ-ERROR", {}
    if not _well_formed(value):
        return "LINKS READ-ERROR", {}
    entries, cards = value["entries"], value["cards"]
    if value["state"] != "complete" or not value["path"].startswith(RESULTS_PATH) or (cards == 0 and not entries):
        return "LINKS NOT-LOADED", {}
    if not entries:
        return "LINKS NO-IDS cards=%d" % cards, {}
    ids = match(list(roles), entries)
    if cards != len(entries):
        return "LINKS PARTIAL cards=%d ids=%d" % (cards, len(entries)), ids
    return "LINKS matched=%d unmatched=%d" % (len(ids), len(list(roles)) - len(ids)), ids


_ROLE_RE = re.compile(r'^ROLE (?:url=\S+(?: q=\S+)? |nourl )title="(?P<title>[^"]*)" company="(?P<company>[^"]*)"')


def roles_of(text):
    """`[{title, company}]`: the ROLE lines of a roles file (either form), in file order. A ROLE line that does not parse is skipped here and is the block's own line fault later."""
    out = []
    for raw in str(text or "").splitlines():
        m = _ROLE_RE.match(raw.strip())
        if m:
            out.append({"title": m.group("title"), "company": m.group("company")})
    return out


def match_lines(raw, roles_text, tool_error=False, limit=None):
    """The lines `search_page.py links --match` prints: the `LINKS ...` verdict line, then one `ID <k> <id> <url>` per role that got an id (`k` the 1-based position among the file's
    ROLE lines) and one `NOURL <k>` per role that did not. A role with no id stays `ROLE nourl` with its own reason; the caller never invents a link.
    `limit` (an integer, or None for no cap) is the most ids printed: the FIRST `limit` matches in file order keep theirs, the rest print `NOURL`, the `LINKS` line counts what is printed, and
    a last line `LIMIT links kept=<k> of <m>: <why>` says what was cut (the owner's caps: 25 a search, 500 a pass). `limit=0` prints no id at all."""
    roles = roles_of(roles_text)
    line, ids = read_verdict(raw, roles, tool_error)
    cut = len(ids) - limit if limit is not None and len(ids) > limit else 0
    if cut:
        ids = {i: ids[i] for i in sorted(ids)[:max(0, limit)]}
        line = re.sub(r"matched=\d+ unmatched=\d+", "matched=%d unmatched=%d" % (len(ids), len(roles) - len(ids)), line)
    out = [line]
    for i in range(len(roles)):
        out.append("ID %d %s %s" % (i + 1, ids[i], VIEW_URL % ids[i]) if i in ids else "NOURL %d" % (i + 1))
    if cut:
        out.append("LIMIT links kept=%d of %d: the owner's caps are %d links a search and %d a pass" % (len(ids), len(ids) + cut, MAX_LINKS_SEARCH, MAX_LINKS_PASS))
    return out


# ---- the settled address (N14) --------------------------------------------------------------------------------------------------------------------------------------------------

PARAM_FILTERS = {"f_WT": "worktype", "location": "location", "geoId": "location", "distance": "location", "f_TPR": "date", "f_SAL": "pay", "f_E": "seniority", "f_JT": "jobtype"}


def _params(query):
    out = {}
    for part in str(query or "").lstrip("?").split("&"):
        if part:
            k, _, v = part.partition("=")
            out.setdefault(k, v)
    return out


def address_drift(sent, settled):
    """`(dropped, added, unapplied)` comparing the query string the pass SENT with the one the page SETTLED on (N14; TESTED 2026-11-25: LinkedIn's redirect dropped the location and the remote
    filter and added a pay filter nobody sent). `dropped` and `added` are filter words of `deferred.QUERY_FILTERS`, in that vocabulary's order, never `date`; `unapplied` is True when the
    window (`f_TPR`) was sent and is missing: the ROLES grammar says that with `unapplied`, not `dropped=date`. A sent filter counts as dropped when NONE of its parameters is in the settled
    address; a parameter that merely changed value is not read as dropped (LinkedIn may normalise)."""
    sent_p, settled_p = _params(sent), _params(settled)

    def tokens(params):
        return {PARAM_FILTERS[k] for k in params if k in PARAM_FILTERS}
    kept, asked = tokens(settled_p), tokens(sent_p)
    order = ("worktype", "location", "pay", "seniority", "jobtype")
    return [t for t in order if t in asked - kept], [t for t in order if t in kept - asked], "date" in asked and "date" not in kept


def _word(value):
    """A parameter's value as words: percent-decoded, `+` a space, case and spacing folded, so `Data%20Analyst` and `data+analyst` are one."""
    return " ".join(urllib.parse.unquote_plus(str(value or "")).casefold().split())


def address_mismatch(sent, settled):
    """`(reason, sentence)` when the settled address is NOT this search's first results page, else None (E7, review 2026-11-25). `keywords`: the pass sent keywords and the page settled on other ones, or on
    none: a stale or reused tab (or a redirect to recommendations) is showing ANOTHER search's results. `start`: the page is another page of results (`start` is the offset; absent is 0), not the first
    one. Compared as words, never as raw text, and never printed (the line names the slot, not the value)."""
    sent_p, settled_p = _params(sent), _params(settled)
    if "keywords" in sent_p and _word(sent_p["keywords"]) != _word(settled_p.get("keywords")):
        return "other-search", "the page's address names other keywords than this search sent: it is a stale or reused tab, or another search's results"
    s, t = _word(sent_p.get("start")) or "0", _word(settled_p.get("start")) or "0"
    if s != t:
        return "not-first-page", "the page's address is not the first page of results this search sent (start %s, sent %s)" % (t, s)
    return None


def address_line(sent, settled):
    """`ADDRESS dropped=<none|a,b> added=<none|a,b>[ unapplied]`: the slots the QUERY line of this search carries, computed (the runner pastes them, never judges them). When `address_mismatch` finds
    another search's page (other `keywords`, or another `start`) the line is `ADDRESS REFUSED reason=<other-search|not-first-page>: <why>. Take nothing from this page ...` and `search_page.py` exits 3: the
    page ends there, its pair is NOT-ATTEMPTED."""
    bad = address_mismatch(sent, settled)
    if bad:
        return "ADDRESS REFUSED reason=%s: %s. Take nothing from this page and do not use its cards or links: this pair is NOT-ATTEMPTED, and this page ends here." % bad
    dropped, added, unapplied = address_drift(sent, settled)
    return "ADDRESS dropped=%s added=%s%s" % (",".join(dropped) or "none", ",".join(added) or "none", " unapplied" if unapplied else "")
