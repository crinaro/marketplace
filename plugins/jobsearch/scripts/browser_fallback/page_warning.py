"""page_warning: is this LinkedIn page an ORDINARY one, and if not, which warning is it? (jobsearch 0.94.0, dev 1065; docs/design-role-first.md 19.6, WN1, WN2; review items 5, 6, 12).

THE OWNER'S CONDITION (19.6). A warning, a sign-in or identity challenge, a CAPTCHA, an unusual-activity page or a commercial-use-limit page, on ANY LinkedIn page the run opens (a search, a
posting, a reply surface), ends that pass at once: no retry, no further LinkedIn page that run, the scheduled search off until the owner turns it on. **A page that cannot reliably be told from
an ordinary one counts as a warning: doubtful = warning.** No warning page has been seen, so no list of phrases can be what this rests on. IT RESTS ON A RULE: a page is ORDINARY only when it is
RECOGNIZED as that kind of page (positive evidence) AND NOTHING ON IT IS UNEXPLAINED. The phrase list is a second net, never the first.

THREE KINDS, ONE SOURCE. `kind` is `results` (a job-search results page: `/jobs/`), `posting` (a LinkedIn posting page, the jd-reader's: `/jobs/view/`) or `reply` (the reply pass's pages: inbox and
requests `/messaging/`, invitations and connections `/mynetwork/`, `/notifications/`, `/feed/`). Each kind has a read-only script and the same strict verdict:

  `WARN_JS_FOR[kind]`  a read-only script, run once on a page that has loaded, on the pane's own executor. It reads the page TWICE, `GAP` apart (timers only, never a frame), and returns
                       `{first: <read>, second: <read>}`; a `<read>` is the facts below and never page text. Rendered from ONE template (`SCRIPT`), so the three differ only in the facts they add. Each is
                       fenced byte-equal in `agents/linkedin-runner.md` (`<!-- page-warning:begin -->`, `<!-- page-warning-posting:begin -->`, `<!-- page-warning-reply:begin -->`).
  `WARN_JS`            is `WARN_JS_FOR["results"]`, unchanged in name for every caller.
  `verdict(raw, kind="results")`  STRICT, in Python, never the agent's reading: `ORDINARY cards=<n>` (results), `ORDINARY` (posting, reply), `WARNING <kind>[ reason=<word>]` or `NO-PAGE`.
                       `<kind>` is one of `search_rows.WARNING_KINDS`; a `reason=` word follows `unclear` always (`REASONS`) and no other kind.

THE FACTS OF A READ (the only keys; an answer with another set of keys, or a value of another type, is `WARNING unclear reason=shape`):

  every kind   proto, host, path (`location`: a redirect to a sign-in or checkpoint address is seen) · ready (`readyState` complete) · password (password inputs) · challenge (challenge frames and
               forms) · modal (open dialogs and modals that hold text) · notice (elements that SPEAK: `role` alert or status, `aria-live` other than off, a toast, authwall or captcha class, with
               text) · banner (blocks of prose, 5 words or more, outside every recognized region) · lang (the document's `lang`) · kinds (the warning kinds whose phrase is on the page)
  results      cards, text, dismiss: the job cards (counted by id: two elements of one card are one card, `ready_content`'s rule), how many have text, how many have their own dismiss control
  posting      about: the characters of the "About the job" block (its heading's parent, or a pure wrapper above it; `ready_content`'s rule), 0 when there is none
  reply        region: the characters of the page's `main` landmark

ORDINARY NEEDS ALL OF: a LinkedIn host; the kind's path; the page loaded; the two reads EQUAL; no password input; no challenge frame or form; no open modal with text; no speaking element with
text (`notice`); a document language that is English or not stated; no block of prose outside the recognized regions (`banner`); no phrase of the list ANYWHERE on the page; and the kind's own
evidence: results, 1 or more cards EACH with text AND its own dismiss control; posting, an "About the job" block of `ABOUT_MIN` (400) characters or more; reply, a `main` landmark holding
`REPLY_MIN` characters or more. ANYTHING ELSE THAT LOADED IS A WARNING, of the most severe kind the evidence names (`SEVERITY`: challenge, unusual-activity, usage-limit, restricted, sign-in), or
`unclear` when it names none, and then ALWAYS with a `reason=` word that says which rule fired: the person is told it may be a layout change, never a silent off.

THE RECOGNIZED REGIONS (what the `banner` rule does not read): a job card; an "About the job" block that holds no card and no navigation (a wrapper that holds either is the page, not a block);
`main` and `[role=main]`; `nav`, `header`, `footer`, `aside` and their roles. Prose elsewhere is a block with no block-level descendant and 5 words or more, whose text the page really shows
(hidden and script text is not read).

WHAT A PHRASE NOW MEANS (review item 6, D8). The phrase list is matched in ALL the page's text, the cards and the "About the job" block included: before, a card's text and that block were
removed first, so a warning rendered inside either was never read. **The accepted cost: a job whose own text uses a phrase now reads as a warning**: a posting for a fraud analyst that says
"unusual activity", a card titled "Unusual Activity Analyst", a role that names "third-party software". Doubtful = warning, said so.

WHAT IT COSTS, PLAINLY (UNMEASURED: no real LinkedIn page was read; every figure below is a consequence of a rule, not a count). One warning of any kind, on any of the three kinds of page, turns
the scheduled search off until the owner turns it on (WN3), so a false one costs the next scheduled search. Each rule turns off every ordinary page that shows what it looks for:
  * `notice`: any element that speaks, with text. An ordinary page with an `aria-live` region that carries text (a result count announced to a screen reader, a badge) reads as a warning.
  * `modal`: a cookie or survey dialog that is open.
  * `language`: an account whose LinkedIn language is not English reads a warning on every page; so does any page whose `lang` is not `en`.
  * `banner`: a block of 5 or more words that sits in none of the recognized regions (a layout that puts the results outside `main`, a promotion or a footer note outside `aside` and `footer`).
  * `no-cards`: a search with no results has no card, so it is a warning until the wording of an empty page is seen and pinned. `cards-without-text` and `no-dismiss` are a layout change or a
    page in another language (its dismiss controls are not labelled "Dismiss"). `no-about`: a posting whose block is under 400 characters. `no-main`: a reply page with no `main` landmark.
  * a phrase anywhere: see above.
How many ordinary pages these turn off is UNKNOWN until one real page of each kind has been read; the first scheduled run is that probe, and the `reason=` word names the rule that fired.

WHAT IS STILL A HOLE (stated, not fixed): a warning that uses none of the phrases, no speaking element, no stated non-English language, and sits INSIDE a recognized region (a banner in `main`,
`header` or `aside`, text inside the "About the job" block, a card); a warning drawn only as an image; a page with no `lang` whose banner is in a layout region; a reply page's evidence is weak
(the path and 20 characters of `main`): it is not the name check the runner makes on the feed, which a script without parameters cannot make; the phrase list is INFERRED and was never seen
on a real warning page.

`NO-PAGE` is only a tool error (the caller passes it as `tool_error=True`, never as text) or a page of the browser itself (`about:`, `chrome-error:` ...): no LinkedIn page was shown, so
nothing can be said about LinkedIn and no warning is recorded. An answer of any OTHER shape, including text that is not JSON, is `WARNING unclear reason=shape`: junk is never `NO-PAGE`.

READ-ONLY. The scripts click, scroll, type, request and navigate nothing, and reach only `location.protocol|hostname|pathname`, `document.readyState`, `document.querySelectorAll`,
`document.body`, `getAttribute`, `closest`, `parentElement`, `children`, `textContent`, `innerText`, `setTimeout` and `Promise` (`ALLOWED_CALLS`; `tests/browser_fallback/test_page_warning.py` runs
every SHIPPED constant under node against a Proxy that throws on anything else).

Pure. Python 3.9+, standard library only."""

import json

from browser_fallback.ready_content import ABOUT_MIN

GAP_MS = 2500                       # between the two reads (timers only; a chain of 3 timers at most, well under 4)
WAIT_POLLS = 2                      # at most this many extra waits for `readyState` to be complete before the first read
KINDS = ("results", "posting", "reply")
REPLY_MIN = 20                      # characters of the `main` landmark a reply page must hold
PROSE_WORDS = 5                     # words of a block of prose the `banner` rule reads

# INFERRED, never seen on a real warning page: lower-case phrases of the warning pages LinkedIn is reported to show, with straight apostrophes (the script folds curly ones and runs of
# white space before it matches). They are matched in ALL the page's text. The rule does not rest on them: they are the second net.
PHRASES = {
    "challenge": ["security check", "security verification", "verify you are not a robot", "i'm not a robot", "complete the puzzle", "solve this puzzle", "let's do a quick",
                  "captcha", "verify your identity", "confirm your identity", "confirm it's you", "verify it's you", "prove you're human", "prove you are human",
                  "bestaetigen sie ihre identitaet", "bestätigen sie ihre identität", "verifica tu identidad", "vérifiez votre identité"],
    "unusual-activity": ["unusual activity", "suspicious activity", "unusual traffic", "detected activity", "unusual sign-in",
                         "ungewoehnliche aktivitaet", "ungewöhnliche aktivität", "actividad inusual", "activité inhabituelle", "atividade incomum"],
    "usage-limit": ["commercial use limit", "reached the limit", "search limit", "weekly limit", "monthly limit", "upgrade to see more", "too many requests", "rate limit",
                    "hit your limit", "too many searches"],
    "restricted": ["account has been restricted", "account is restricted", "temporarily restricted", "restricted your account", "prohibited software", "third-party software",
                   "automated activity", "limited your access", "temporarily limited", "access has been limited", "limit your access", "zugriff eingeschraenkt"],
    "sign-in": ["sign in to view", "sign in to continue", "sign in to see", "join now to see", "join linkedin to see", "welcome back", "session has expired", "session expired",
                "you've been signed out", "you have been signed out", "log in to continue", "please sign in"],
}
SEVERITY = ("challenge", "unusual-activity", "usage-limit", "restricted", "sign-in")      # the most severe kind the evidence names is the verdict's
PATH_KINDS = (("/checkpoint", "challenge"), ("/authwall", "sign-in"), ("/uas/", "sign-in"), ("/login", "sign-in"), ("/signup", "sign-in"))
KIND_PATHS = {"results": ("/jobs/",), "posting": ("/jobs/view/", "/comm/jobs/view/"), "reply": ("/messaging/", "/mynetwork/", "/notifications/", "/feed/", "/in/")}
RESULTS_PATH = KIND_PATHS["results"][0]
CARD_IDS = '[componentkey^="job-card-component-ref-"], [data-occludable-job-id], [data-job-id]'     # `ready_content.CARD_ID_SELECTOR`, held equal by a test
DISMISS = 'button[aria-label^="Dismiss"]'
CHALLENGE = ('iframe[src*="captcha"], iframe[src*="challenge"], iframe[src*="arkose"], iframe[src*="recaptcha"], '
             'form[action*="checkpoint"], form[action*="challenge"]')
MODAL = '[role="dialog"], [role="alertdialog"], [aria-modal="true"], dialog[open]'
PASSWORD = 'input[type="password"]'
NOTICE = '[role="alert"], [role="status"], [class*="toast"], [class*="authwall"], [class*="captcha"], [class*="global-alert"]'
LIVE = '[aria-live]'                # counted unless its value is `off`
MAIN = 'main, [role="main"]'
LAYOUT = MAIN + ', nav, header, footer, aside, [role="navigation"], [role="banner"], [role="contentinfo"], [role="complementary"]'
BLOCKS = 'div, p, section, article, ul, ol, li, table, form, h1, h2, h3, h4, h5, h6, header, footer, nav, aside, main, dialog'
NOISE = 'script, style, noscript, template, code, svg'
BROWSER_PROTOS = ("", "about:", "chrome-error:", "chrome:", "edge:", "data:", "blob:")
COMMON_KEYS = ("proto", "host", "path", "ready", "password", "challenge", "modal", "notice", "banner", "lang", "kinds")
KIND_KEYS = {"results": ("cards", "text", "dismiss"), "posting": ("about",), "reply": ("region",)}
STR_KEYS = ("proto", "host", "path", "lang")
INT_KEYS = ("password", "challenge", "modal", "notice", "banner", "cards", "text", "dismiss", "about", "region")
READ_KEYS = {kind: COMMON_KEYS + KIND_KEYS[kind] for kind in KINDS}
# Every `reason=` word that can follow `WARNING unclear`.
REASONS = ("shape", "changing", "not-linkedin", "loading", "wrong-path", "language", "modal", "notice", "banner", "no-cards", "cards-without-text", "no-dismiss", "no-about", "no-main")

# The only identifiers the scripts may reference: documentation the test's own failure points back to. The test derives what each constant really contains and holds it to this list.
ALLOWED_CALLS = ("location.protocol", "location.hostname", "location.pathname", "document.readyState", "document.querySelectorAll", "document.body",
                 "getAttribute", "closest", "parentElement", "children", "textContent", "innerText", "querySelectorAll", "setTimeout", "Promise")

# The one template. `@@CONSTS@@` is the tables above, JSON-quoted (one source: the test checks each is in the constant); `@@FOLD@@` the apostrophes it folds; `@@EXTRA@@` the facts a kind
# adds to a read. Nothing else is a hole.
SCRIPT = r"""(async () => {
  const @@CONSTS@@;
  const lower = s => (s || '').toLowerCase();
  const norm = s => lower(s).replace(/[@@FOLD@@]/g, "'").replace(/\s+/g, ' ').trim();
  const text = e => (e.innerText || '').trim();
  const sleep = () => new Promise(r => setTimeout(r, GAP));
  const read = () => {
    const keyOf = e => e.getAttribute('componentkey') || e.getAttribute('data-occludable-job-id') || e.getAttribute('data-job-id');
    const dismissed = e => e.querySelectorAll(DISMISS).length > 0 || (!!e.closest('li') && e.closest('li').querySelectorAll(DISMISS).length > 0);
    const at = Object.create(null), cards = [], regions = [];
    for (const e of Array.from(document.querySelectorAll(IDS))) {
      const id = keyOf(e);
      if (!id) continue;
      if (at[id] === undefined) { at[id] = cards.length; cards.push({t: '', d: false}); }
      const c = cards[at[id]];
      if (text(e).length > c.t.length) c.t = text(e);
      c.d = c.d || dismissed(e);
      regions.push(e);
      if (e.closest('li')) regions.push(e.closest('li'));
    }
    if (cards.length === 0) {
      const seen = [];
      for (const b of Array.from(document.querySelectorAll(DISMISS))) {
        const c = b.closest('li') || b.parentElement;
        if (c && !seen.includes(c)) { seen.push(c); cards.push({t: text(c), d: true}); regions.push(c); }
      }
    }
    const page = norm(document.body ? text(document.body) : '');
    let about = 0;
    for (const h of Array.from(document.querySelectorAll('*'))) {
      if (h.children.length !== 0 || norm(h.textContent) !== 'about the job') continue;
      let b = h.parentElement;
      for (let i = 0; i < 2 && b && b !== document.body && b.children.length === 1; i++) b = b.parentElement;
      if (!b || b === document.body) continue;
      about = Math.max(about, text(b).length - text(h).length);
      if (b.querySelectorAll(IDS + ', ' + CHROME).length === 0) regions.push(b);
    }
    const speaking = Array.from(document.querySelectorAll(NOTICE)).concat(Array.from(document.querySelectorAll(LIVE)).filter(e => e.getAttribute('aria-live') !== 'off'));
    const inRegion = e => { for (let p = e; p; p = p.parentElement) { if (regions.includes(p)) return true; } return !!e.closest(LAYOUT); };
    let banner = 0;
    for (const e of Array.from(document.querySelectorAll('*'))) {
      if (e.querySelectorAll(BLOCKS).length !== 0 || e.closest(NOISE)) continue;
      const t = norm(e.innerText);
      if (t.split(' ').length >= PROSE && page.includes(t) && !inRegion(e)) banner++;
    }
    const html = document.querySelectorAll('html')[0];
    return {proto: location.protocol, host: location.hostname, path: location.pathname, ready: document.readyState === 'complete',
            password: document.querySelectorAll(PASSWORD).length, challenge: document.querySelectorAll(CHALLENGE).length,
            modal: Array.from(document.querySelectorAll(MODAL)).filter(m => text(m).length > 0).length,
            notice: speaking.filter((e, i) => text(e).length > 0 && speaking.indexOf(e) === i).length, banner: banner, lang: html ? (html.getAttribute('lang') || '') : '',
            kinds: Object.keys(PHRASES).filter(k => PHRASES[k].some(p => page.includes(p))), @@EXTRA@@};
  };
  for (let i = 0; i < WAIT && document.readyState !== 'complete'; i++) await sleep();
  const first = read();
  await sleep();
  return {first: first, second: read()};
})()"""

# The typographic apostrophes the script folds to a straight one (U+2018, U+2019, U+02BC), written as JS escapes so the constant stays ASCII.
FOLD = "\\" + "u2018" + "\\" + "u2019" + "\\" + "u02bc"

_EXTRA = {
    "results": "cards: cards.length, text: cards.filter(c => c.t.length > 0).length, dismiss: cards.filter(c => c.d).length",
    "posting": "about: about",
    "reply": "region: Array.from(document.querySelectorAll(MAIN)).reduce((m, e) => Math.max(m, text(e).length), 0)",
}


def _consts():
    """The script's `const` list: every table of this module, JSON-quoted, under the name the script uses."""
    pairs = (("GAP", GAP_MS), ("WAIT", WAIT_POLLS), ("PHRASES", PHRASES), ("IDS", CARD_IDS), ("DISMISS", DISMISS), ("CHALLENGE", CHALLENGE), ("MODAL", MODAL), ("PASSWORD", PASSWORD),
             ("NOTICE", NOTICE), ("LIVE", LIVE), ("MAIN", MAIN), ("CHROME", LAYOUT.replace(MAIN + ", ", "")), ("LAYOUT", LAYOUT), ("BLOCKS", BLOCKS), ("NOISE", NOISE), ("PROSE", PROSE_WORDS))
    return ", ".join("%s = %s" % (name, json.dumps(value)) for name, value in pairs)


def render(kind):
    """The script of page kind `kind`. `ValueError` on a kind that is not one of `KINDS`: a typo is loud, never rendered."""
    if kind not in KINDS:
        raise ValueError("unknown page kind %r; the kinds are %s" % (kind, ", ".join(KINDS)))
    return SCRIPT.replace("@@CONSTS@@", _consts()).replace("@@FOLD@@", FOLD).replace("@@EXTRA@@", _EXTRA[kind])


_RENDERED = {}


def script(kind):
    """The script of page kind `kind`, rendered once (`render` is pure, so the same string every time). `ValueError` on an unknown kind."""
    if kind not in _RENDERED:
        _RENDERED[kind] = render(kind)
    return _RENDERED[kind]


def __getattr__(name):
    """`WARN_JS_FOR` (kind -> script) and `WARN_JS` (the results script) are module attributes rendered on first use, never at import (the segmentation rule G3: no work at import)."""
    if name == "WARN_JS_FOR":
        return {kind: script(kind) for kind in KINDS}
    if name == "WARN_JS":
        return script("results")
    raise AttributeError("module %r has no attribute %r" % (__name__, name))


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def _well_formed(read, kind):
    """True when `read` is exactly the shape the script of `kind` returns: its keys, the right types, `text` and `dismiss` no more than `cards`, `kinds` a list of known kinds."""
    if not isinstance(read, dict) or set(read) != set(READ_KEYS[kind]):
        return False
    if not all(isinstance(read[k], str) for k in STR_KEYS) or not isinstance(read["ready"], bool):
        return False
    if not all(_is_int(read[k]) for k in INT_KEYS if k in read):
        return False
    if kind == "results" and (read["text"] > read["cards"] or read["dismiss"] > read["cards"]):
        return False
    return isinstance(read["kinds"], list) and all(k in PHRASES for k in read["kinds"])


def _on_linkedin(host):
    return host == "linkedin.com" or host.endswith(".linkedin.com")


def _english(lang):
    lang = lang.strip().lower()
    return lang == "" or lang == "en" or lang.startswith(("en-", "en_"))


def _evidence(read):
    """The warning kinds one read names: from the address, a challenge frame or form, a password input and the phrases on the page."""
    kinds = set(read["kinds"])
    path = read["path"]
    kinds.update(kind for prefix, kind in PATH_KINDS if path.startswith(prefix))
    if read["challenge"]:
        kinds.add("challenge")
    if read["password"]:
        kinds.add("sign-in")
    return kinds


def _unclear_reason(read, kind):
    """The word of the first rule an equal, LinkedIn, kind-less-of-evidence read breaks, or None when the page is recognized as an ordinary page of `kind` with nothing unexplained on it."""
    if not read["ready"]:
        return "loading"
    if not read["path"].startswith(KIND_PATHS[kind]):
        return "wrong-path"
    if not _english(read["lang"]):
        return "language"
    for key, word in (("modal", "modal"), ("notice", "notice"), ("banner", "banner")):
        if read[key]:
            return word
    if kind == "results":
        if read["cards"] < 1:
            return "no-cards"
        if read["text"] != read["cards"]:
            return "cards-without-text"
        return "no-dismiss" if read["dismiss"] != read["cards"] else None
    if kind == "posting":
        return "no-about" if read["about"] < ABOUT_MIN else None
    return "no-main" if read["region"] < REPLY_MIN else None


def judge_reason(raw, tool_error=False, kind="results"):
    """`(word, warning kind, cards, reason)`: `("ordinary", None, cards or None, None)`, `("warning", kind, None, reason or None)` or `("no-page", None, None, None)` for what the script of `kind`
    returned (`raw`: its result as text, or an already-parsed value). `tool_error=True` says the tool call itself failed (an error, a timeout) and is the only way to a `no-page` that is not the
    browser's own page: text that is not JSON is `warning unclear`. `reason` is set for `unclear` and for no other kind. `ValueError` on a `kind` that is not one of `KINDS`."""
    if kind not in KINDS:
        raise ValueError("unknown page kind %r; the kinds are %s" % (kind, ", ".join(KINDS)))
    if tool_error:
        return "no-page", None, None, None
    value = raw
    if isinstance(raw, (str, bytes, bytearray)):
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            return "warning", "unclear", None, "shape"
    if not isinstance(value, dict) or set(value) != {"first", "second"} or not (_well_formed(value["first"], kind) and _well_formed(value["second"], kind)):
        return "warning", "unclear", None, "shape"
    first, second = value["first"], value["second"]
    if first != second:
        return "warning", "unclear", None, "changing"        # the page was still changing between the two reads
    if first["proto"] in BROWSER_PROTOS:
        return "no-page", None, None, None                   # a page of the browser itself: no LinkedIn page was shown
    if not _on_linkedin(first["host"]):
        return "warning", "unclear", None, "not-linkedin"
    kinds = _evidence(first)
    if kinds:
        return "warning", next(k for k in SEVERITY if k in kinds), None, None
    reason = _unclear_reason(first, kind)
    if reason:
        return "warning", "unclear", None, reason
    return "ordinary", None, (first["cards"] if kind == "results" else None), None


def judge(raw, tool_error=False, kind="results"):
    """`judge_reason` without the reason: `("ordinary", None, cards)`, `("warning", kind, None)` or `("no-page", None, None)`. The shape the journal's `search-warning` step reads."""
    word, warn, cards, _ = judge_reason(raw, tool_error, kind)
    return word, warn, cards


def verdict(raw, kind="results", tool_error=False):
    """`ORDINARY cards=<n>` (results) or `ORDINARY` (posting, reply), `WARNING <kind>[ reason=<word>]` or `NO-PAGE`: the one line the steps act on (see `judge_reason`)."""
    word, warn, cards, reason = judge_reason(raw, tool_error, kind)
    if word == "ordinary":
        return "ORDINARY cards=%d" % cards if kind == "results" else "ORDINARY"
    if word == "warning":
        return "WARNING %s%s" % (warn, " reason=%s" % reason if reason else "")
    return "NO-PAGE"
