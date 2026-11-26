#!/usr/bin/env python3
"""jd_read.py -- the ONE parser of `opportunities[].jd_read`, the stored record of a JD read
(dev #820 / public #175; design-role-pipeline.md section 4.2, 9 and section 17 N16).

WHY THIS EXISTS
---------------
Before 0.82.0 a read was `fit.jd_source`, a free string on the research field. `unavailable: dead-link`
with a placeholder requirement was accepted with no evidence, a hand-read role could not get in without
a fabricated `fit`, and four modules each decided for themselves what "reviewed" meant. A fact a run
knows goes into the queryable store with a strict parser (CLAUDE.md), so this module is that parser.

THE SHAPE
---------
    "jd_read": {"attempts": [{"at", "run", "url", "via", "outcome", "evidence"}, ...]}

  at        `YYYY-MM-DDTHH:MM:SS` (a date alone is refused: the order of two attempts is read off it)
  run       the run id that made the attempt, or the literal `legacy` (see below)
  url       the address read, or null (`--url -`: there was none)
  via       how it was read: fetch | render | feed | ats-api | candidate; or `legacy`
  outcome   read | closed | dead-link | manual-board | no-url | login-wall | challenge |
            render-failed | surface-cannot-read | site-not-allowed | pane-hidden
  evidence  an object, never empty (shapes below)

The outcome CLASSES are disjoint and together cover `OUTCOMES`:

  read        the posting was read; the role's facts are re-derived from it
  TERMINAL    closed, dead-link          -- settles the role to `gone`
  CANDIDATE   manual-board, no-url,
              login-wall                 -- only the candidate can read it: settles to `your-read`
  HOST_CLASS  challenge, render-failed,
              surface-cannot-read,
              site-not-allowed           -- the machine or the pane failed: the run's work is unfinished
  NOT_ATTEMPTED  pane-hidden             -- (0.85.0, dev #839 / public #182, dev #840 / public #181) the page was
                                            NEVER READ, because the Browser pane was hidden or the reader's tab
                                            stayed in the background: no page attempt was made, so it is no
                                            evidence about the role. It is `environment`-class in `lifecycle`
                                            and is never a `read-failed` or `render-failed`.

`OUTCOMES` is the four classes above `NOT_ATTEMPTED` (the outcomes `read-failed` may record); `ALL_OUTCOMES` is
`OUTCOMES + NOT_ATTEMPTED`, every outcome this parser accepts. A `pane-hidden` attempt is written only by
`record.py not-attempted`, and only `via render`.

EVIDENCE
--------
  outcome `read`   {quote, chars?, sha1?, replaced?, attestation?}
                   `quote` is 1-200 characters and is required under `render` (a model attestation: the
                   posting's own title or Apply text) and under `candidate` (the candidate's own
                   one-line note, which must also carry `attestation: "candidate"`). `chars` and `sha1`
                   are written only by `record.py read-batch`, from the body it fetched itself.
  any failure      {text}  1-200 characters: the status line, the error text or the page's own words, and
                   (0.85.0, written by `record.py read-failed --via render`) optionally `page` (the page result
                   as given), `pane` (the PARSED pane state: hidden | displayed | unknown, never the raw line)
                   and `probe` (the verdict `pane_probe.verdict` returned)
  not-attempted    {text, pane, tab_active}  `pane` is the parsed pane state, and `tab_active` (yes | no) is the
                   MODEL'S word about its own tab, which its name says: the engine cannot check it
  via `legacy`     {legacy}  `fit.jd_source=<value, at most 200 characters>`, for EVERY outcome

`legacy` is legal ONLY together with `run: "legacy"`, and only from the migration
(`make_attempt(..., migration=True)`); a verb that tries to write it is refused. It is the pre-0.82.0
read, kept so a role that was read before the upgrade does not turn into an unread process failure.

THE 0.90.0 KEYS (dev #858; design-browser-fallback.md section 8.1)
------------------------------------------------------------------
Four evidence keys say WHICH browser read a page and what the fallback ladder did. Each is a closed vocabulary and
each value is checked here, so an unknown code is refused at write and is never stored:

  browser   pane | extension          `via render` only: the browser that made the attempt (absent on an older row
                                      = a pre-0.90.0 row, read as `pane`)
  ready     READY | NOT-READY | READY-ERROR     the `page_ready.py --verdict` word, on a failed or not-attempted attempt
  gate      paints | not-painting | probe-error the `pane_probe.py --gate` word (`probe-again` is never stored: it is
                                      a request to probe again), on a failed or not-attempted attempt
  fallback  {"extension": <code>}     `via render`: why the extension rung did not read (EXTENSION_CODES)
            {"fetch": <code>}         `via fetch`, outcome `pane-hidden` only: what the scripted fetch did when it
                                      did not read (FETCH_CODES)

`gate` REPLACES `probe` for new writes (the writer, `record.py`, stops accepting `probe`); this parser still reads a
`probe` on an older row. A `via fetch` `pane-hidden` attempt is written only by `record.py read-batch --fallback`
and carries `{text, fallback: {fetch: <code>}}`, with no `pane` and no `tab_active` (nothing was opened).
The installed 0.86.0-0.89.x reader REFUSES these keys, which is why the profile carries the 0.90.0 pin (section 8.2).

THE 0.94.0 SHAPES (dev 1063; docs/design-role-first.md 6.1, 6.3)
-----------------------------------------------------------------
  body        `via render` read only: 60-200 characters quoted from the DESCRIPTION, not the header (the title-only quote that passed as a
              read is what 1063 is about). It never equals `quote`. Whether the text really is description is `record.py`'s check, not
              this parser's (the page is not here).
  withdrawn   a COMPENSATING attempt, never an edit of history: `{at, run, url, via, outcome: "withdrawn", evidence: {text, of}}`, where `of`
              is the `at` of a `read` attempt listed EARLIER in the same record and not later than the withdrawal. The read stays in the
              record; `standing()` is the read-side list that leaves out the withdrawn read and the withdrawal itself. `attempts()` stays
              the lossless list every WRITER rewrites from. `via` is a verb's own (never `legacy`); `run` the writer's run id.
  An engine older than 0.94.0 refuses both (strict parser), which is why a profile carries the 0.94.0 pin before either is written.

NO FREE TEXT PASSES AS A READ. An unknown key, an unknown outcome, an empty evidence object, a `render`
read without a quote, a bad `at` -- each raises `JdReadError` naming the field.

Python 3.9+. Standard library only. Pure: reads only what it is handed.
"""

import datetime
import re

VIAS = ("fetch", "render", "feed", "ats-api", "candidate")     # what a VERB may write (candidate: dev #820)
LEGACY_VIA = "legacy"
LEGACY_RUN = "legacy"
ALL_VIAS = VIAS + (LEGACY_VIA,)

READ = "read"
TERMINAL = ("closed", "dead-link")
CANDIDATE = ("manual-board", "no-url", "login-wall")
HOST_CLASS = ("challenge", "render-failed", "surface-cannot-read", "site-not-allowed")
OUTCOMES = (READ,) + TERMINAL + CANDIDATE + HOST_CLASS
# 0.85.0 (dev #839 / public #182, dev #840 / public #181; design-hidden-pane-reads.md section 7.1, 16 entry 19). The
# page was never read, so this is NOT a failed read: a fourth class, kept outside `OUTCOMES` (which is what
# `read-failed` may record, and which the four classes above cover exactly). `ALL_OUTCOMES` is what the parser accepts.
NOT_ATTEMPTED = ("pane-hidden",)
# 0.94.0 (dev 1063, design-role-first.md 6.3): a fifth class, `withdrawal`: an attempt that says an earlier read was wrong. Kept outside `OUTCOMES`
# (what `read-failed` may record) as `NOT_ATTEMPTED` is: only `record.py read-withdraw`, the same-write contradiction rule and the migration write it.
WITHDRAWAL = ("withdrawn",)
WITHDRAWN = "withdrawn"
ALL_OUTCOMES = OUTCOMES + NOT_ATTEMPTED + WITHDRAWAL
# 0.90.0 (dev #858, design-browser-fallback.md 8.1): a not-attempted attempt is written `via render` (the browser read that
# could not happen: `record.py not-attempted`, the only verb for it) or, for `pane-hidden` only, `via fetch` (the scripted
# fetch rung withheld or failed: `record.py read-batch --fallback`). `NOT_ATTEMPTED_VERB_VIA` is the one the VERB writes.
NOT_ATTEMPTED_VIA = ("render", "fetch")
NOT_ATTEMPTED_VERB_VIA = "render"
NOT_ATTEMPTED_FETCH_OUTCOMES = ("pane-hidden",)
PANE_EVIDENCE_STATES = ("hidden", "displayed", "unknown")     # `pane_probe.pane_state`'s answers, mirrored (pure module)
TAB_ACTIVE_VALUES = ("yes", "no")

# The closed set `fit.jd_source: "unavailable: <reason>"` accepted from 0.67.0 (validate_data.
# JD_UNAVAILABLE_REASONS, mirrored here and pinned equal by a test). Each reason is also an outcome.
LEGACY_REASONS = ("login-wall", "dead-link", "no-url", "surface-cannot-read", "manual-board")
LEGACY_UNAVAILABLE_RE = re.compile(r"^unavailable: (%s)$" % "|".join(LEGACY_REASONS))
LEGACY_UNAVAILABLE_PREFIX = "unavailable"

EVIDENCE_CAP = 200
# 0.90.0 (dev #858): `NEW_EVIDENCE_KEYS` are the four keys below; each tuple gains the ones design 8.1 names for it.
# `probe` stays readable on an older row and is no longer WRITTEN (`gate` replaces it); a fetch attempt's own keys are
# `FETCH_NOT_ATTEMPTED_EVIDENCE_KEYS`.
READ_EVIDENCE_KEYS = ("quote", "chars", "sha1", "replaced", "attestation", "browser", "body")
WITHDRAWN_EVIDENCE_KEYS = ("text", "of")
BODY_MIN, BODY_CAP = 60, EVIDENCE_CAP        # 0.94.0: characters of description a rendered read must quote (design 6.1)
FAILED_EVIDENCE_KEYS = ("text", "page", "pane", "probe", "browser", "ready", "gate", "fallback")   # only `text` is required
NOT_ATTEMPTED_EVIDENCE_KEYS = ("text", "pane", "tab_active", "browser", "ready", "gate", "fallback")
FETCH_NOT_ATTEMPTED_EVIDENCE_KEYS = ("text", "fallback")
NEW_EVIDENCE_KEYS = ("browser", "ready", "gate", "fallback")
# The profile pin a WRITER requires before it stores a `NEW_EVIDENCE_KEYS` key (record.py's guard; design 8.2). It is the
# `profile-schema` pin `m_0_90_0_browser_fallback` writes (`migrate.BROWSER_FALLBACK_PIN`); this module is pure and cannot
# import migrate, so the literal is mirrored here.
NEW_KEYS_PIN = "0.90.0"
# The profile pin a WRITER requires before it stores a `body` or a `withdrawn` attempt (0.94.0; `journaling.pins.ROLE_FIRST_PIN`, which this pure
# module cannot import, so the literal is mirrored here and a test pins the two equal).
ROLE_FIRST_PIN = "0.94.0"
BROWSERS = ("pane", "extension")
READY_WORDS = ("READY", "NOT-READY", "READY-ERROR")             # page_ready.py --verdict's words, mirrored (pure module)
GATE_WORDS = ("paints", "not-painting", "probe-error")          # pane_probe.paint_gate's words that are STORED (not probe-again)
# `fallback.extension`: why the extension rung did not read (design 4.2); the value says whether the scripted fetch is
# admitted after it (the table's own "admits the fetch" cell, read by `record.py` and `posting_fetch.auto_gate`).
EXTENSION_CODES = {
    "tools-absent": True, "not-connected": True, "not-this-computer": True, "browser-ambiguous": True,
    "unattended-unprobed": True, "not-preferred": True, "lock-held": True, "navigate-timeout": True,
    "not-painting": True,
    "not-ready": False, "challenge": False, "permission-denied": False, "not-signed-in": False,
}
# `fallback.fetch`: what the scripted fetch did when it did not read (design 8.1).
FETCH_CODES = ("off", "unreadable", "sandbox-unconfirmed", "notice-missing", "rate-limited", "http", "refused",
               "unreachable")
LEGACY_EVIDENCE_KEYS = ("legacy",)
ATTEMPT_KEYS = ("at", "run", "url", "via", "outcome", "evidence")

_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")


class JdReadError(ValueError):
    """A `jd_read` value (or an attempt being made) that this parser refuses. Loud on purpose."""


def outcome_class(outcome):
    """`read` | `terminal` | `candidate` | `host` | `not-attempted` | `withdrawal`, or raises `JdReadError` for an unknown
    outcome. `not-attempted` (0.85.0) is a page that was never read: it is no page attempt at all, and neither is a `withdrawal`
    (0.94.0): it is a statement about an earlier read."""
    if outcome == READ:
        return "read"
    if outcome in TERMINAL:
        return "terminal"
    if outcome in CANDIDATE:
        return "candidate"
    if outcome in HOST_CLASS:
        return "host"
    if outcome in NOT_ATTEMPTED:
        return "not-attempted"
    if outcome in WITHDRAWAL:
        return "withdrawal"
    raise JdReadError("outcome %r is not one of %s" % (outcome, ", ".join(ALL_OUTCOMES)))


def is_page_attempt(attempt):
    """True when `attempt` is a try at a page (every class but `not-attempted` and, from 0.94.0, `withdrawal`). A role whose only attempts are
    `not-attempted` has had no page attempt, so `lifecycle` reads it as `captured`, never `reading`."""
    return outcome_class(attempt["outcome"]) not in ("not-attempted", "withdrawal")


def parse_at(at):
    """The `datetime` of a stored `at`, or raises `JdReadError`."""
    if not isinstance(at, str) or not _AT_RE.match(at):
        raise JdReadError("at %r is not YYYY-MM-DDTHH:MM:SS" % (at,))
    try:
        return datetime.datetime.fromisoformat(at)
    except ValueError:
        raise JdReadError("at %r is not a real date and time" % (at,))


def _text(value, label, cap=EVIDENCE_CAP):
    if not isinstance(value, str) or not value.strip():
        raise JdReadError("%s must be a non-empty string -- %r" % (label, value))
    if len(value) > cap:
        raise JdReadError("%s is %d characters; the cap is %d" % (label, len(value), cap))
    return value


def _check_new_keys(via, outcome, evidence):
    """The 0.90.0 keys (dev #858), each against its closed vocabulary. `browser`, `ready` and `gate` belong to a `render`
    attempt; `fallback` is `{extension: <code>}` on a `render` attempt and `{fetch: <code>}` on a `fetch` one, never
    both and never empty. A key the attempt's tuple does not allow was already refused by the caller."""
    for key, vocab in (("browser", BROWSERS), ("ready", READY_WORDS), ("gate", GATE_WORDS)):
        if key in evidence:
            if via != "render":
                raise JdReadError("evidence.%s belongs to a `render` attempt, not via %s" % (key, via))
            if evidence[key] not in vocab:
                raise JdReadError("evidence.%s must be one of %s -- %r" % (key, ", ".join(vocab), evidence[key]))
    if "fallback" in evidence:
        fb = evidence["fallback"]
        key = {"render": "extension", "fetch": "fetch"}.get(via)
        if key is None or (key == "fetch" and outcome not in NOT_ATTEMPTED_FETCH_OUTCOMES):
            raise JdReadError("evidence.fallback belongs to a `render` attempt or a `fetch` pane-hidden attempt, not to a "
                              "via %s %s attempt" % (via, outcome))
        if not isinstance(fb, dict) or set(fb) != {key}:
            raise JdReadError("evidence.fallback on a via %s attempt must be exactly {%r: <code>} -- %r" % (via, key, fb))
        codes = tuple(EXTENSION_CODES) if key == "extension" else FETCH_CODES
        if fb[key] not in codes:
            raise JdReadError("evidence.fallback.%s must be one of %s -- %r" % (key, ", ".join(codes), fb[key]))


def _check_evidence(via, outcome, evidence):
    if not isinstance(evidence, dict) or not evidence:
        raise JdReadError("evidence must be a non-empty object -- %r" % (evidence,))
    if via == LEGACY_VIA:
        allowed = LEGACY_EVIDENCE_KEYS
    elif outcome == WITHDRAWN:
        allowed = WITHDRAWN_EVIDENCE_KEYS
    elif outcome == READ:
        allowed = READ_EVIDENCE_KEYS
    elif outcome in NOT_ATTEMPTED and via == "fetch":
        allowed = FETCH_NOT_ATTEMPTED_EVIDENCE_KEYS
    elif outcome in NOT_ATTEMPTED:
        allowed = NOT_ATTEMPTED_EVIDENCE_KEYS
    else:
        allowed = FAILED_EVIDENCE_KEYS
    unknown = sorted(set(evidence) - set(allowed))
    if unknown:
        raise JdReadError("evidence has unknown key(s) %s for a %s %s attempt (allowed: %s)"
                          % (", ".join(unknown), via, outcome, ", ".join(allowed)))
    if via == LEGACY_VIA:
        # the value is `fit.jd_source=<up to 200 chars>`
        _text(evidence.get("legacy"), "evidence.legacy", cap=EVIDENCE_CAP + len("fit.jd_source="))
        return
    _check_new_keys(via, outcome, evidence)
    if outcome == WITHDRAWN:
        _text(evidence.get("text"), "evidence.text")
        parse_at(evidence.get("of"))
        return
    if outcome in NOT_ATTEMPTED and via == "fetch":
        _text(evidence.get("text"), "evidence.text")
        if "fallback" not in evidence:
            raise JdReadError("a %s attempt via fetch needs evidence.fallback.fetch (what the scripted fetch did when it "
                              "did not read)" % outcome)
        return
    if outcome in NOT_ATTEMPTED:
        _text(evidence.get("text"), "evidence.text")
        if evidence.get("pane") not in PANE_EVIDENCE_STATES:
            raise JdReadError("a %s attempt needs evidence.pane, one of %s (the parsed pane state, never the raw "
                              "line) -- %r" % (outcome, ", ".join(PANE_EVIDENCE_STATES), evidence.get("pane")))
        if evidence.get("tab_active") not in TAB_ACTIVE_VALUES:
            raise JdReadError("a %s attempt needs evidence.tab_active, yes or no (the reader's own word about its "
                              "tab) -- %r" % (outcome, evidence.get("tab_active")))
        return
    if outcome != READ:
        _text(evidence.get("text"), "evidence.text")
        if "pane" in evidence and evidence["pane"] not in PANE_EVIDENCE_STATES:
            raise JdReadError("evidence.pane must be one of %s (the parsed state) -- %r"
                              % (", ".join(PANE_EVIDENCE_STATES), evidence["pane"]))
        for k in ("page", "probe"):
            if k in evidence:
                _text(evidence[k], "evidence.%s" % k)
        return
    if "body" in evidence:
        if via != "render":
            raise JdReadError("evidence.body belongs to a `render` read (a script or the candidate already holds the text of any other), not via %s" % via)
        body = _text(evidence["body"], "evidence.body", cap=BODY_CAP)
        if len(body) < BODY_MIN:
            raise JdReadError("evidence.body is %d characters; a quote of the description is at least %d" % (len(body), BODY_MIN))
        if body == evidence.get("quote"):
            raise JdReadError("evidence.body equals evidence.quote: the body must be a different part of the page")
    if "quote" in evidence:
        _text(evidence["quote"], "evidence.quote")
    elif via in ("render", "candidate"):
        raise JdReadError("a %s read needs evidence.quote (the posting's own title or Apply text, or "
                          "the candidate's own note)" % via)
    if via == "candidate" and evidence.get("attestation") != "candidate":
        raise JdReadError("a candidate read must carry evidence.attestation: 'candidate' -- the note is "
                          "the candidate's own word, not a quote of the page")
    if via != "candidate" and "attestation" in evidence:
        raise JdReadError("evidence.attestation is only for a candidate read")
    if via in ("fetch", "feed", "ats-api") and "quote" not in evidence \
            and not ("sha1" in evidence and "chars" in evidence):
        raise JdReadError("a %s read needs evidence.quote, or both sha1 and chars from the body that "
                          "was fetched" % via)
    if "chars" in evidence:
        c = evidence["chars"]
        if not isinstance(c, int) or isinstance(c, bool) or c < 0:
            raise JdReadError("evidence.chars must be a non-negative integer -- %r" % (c,))
    if "sha1" in evidence:
        if not isinstance(evidence["sha1"], str) or not _SHA1_RE.match(evidence["sha1"]):
            raise JdReadError("evidence.sha1 must be 40 lowercase hex digits -- %r" % (evidence["sha1"],))
    if "replaced" in evidence and not isinstance(evidence["replaced"], dict):
        raise JdReadError("evidence.replaced must be an object (the values the read replaced)")


def parse_attempt(att):
    """A validated copy of one stored attempt, or raises `JdReadError`. `legacy` is legal only
    together with `run: legacy` (so a hand-edit that fakes one half is caught either way); whether a
    WRITER may produce one is `make_attempt`'s rule, not this parser's."""
    if not isinstance(att, dict):
        raise JdReadError("an attempt must be an object -- %r" % (att,))
    unknown = sorted(set(att) - set(ATTEMPT_KEYS))
    missing = [k for k in ATTEMPT_KEYS if k not in att]
    if unknown:
        raise JdReadError("attempt has unknown key(s) %s" % ", ".join(unknown))
    if missing:
        raise JdReadError("attempt is missing key(s) %s" % ", ".join(missing))
    parse_at(att["at"])
    run = att["run"]
    if not isinstance(run, str) or not run.strip() or re.search(r"\s", run):
        raise JdReadError("run must be a non-empty run id without whitespace -- %r" % (run,))
    url = att["url"]
    if url is not None and (not isinstance(url, str) or not url.strip()):
        raise JdReadError("url must be a non-empty string or null -- %r" % (url,))
    via, outcome = att["via"], att["outcome"]
    if via not in ALL_VIAS:
        raise JdReadError("via %r is not one of %s" % (via, ", ".join(ALL_VIAS)))
    if (via == LEGACY_VIA) != (run == LEGACY_RUN):
        raise JdReadError("via 'legacy' and run 'legacy' are legal only together (via=%r, run=%r)"
                          % (via, run))
    outcome_class(outcome)
    if outcome in WITHDRAWAL and via == LEGACY_VIA:
        raise JdReadError("a withdrawn attempt is written by a verb or the migration, never via 'legacy'")
    if outcome in NOT_ATTEMPTED and (via not in NOT_ATTEMPTED_VIA
                                     or (via == "fetch" and outcome not in NOT_ATTEMPTED_FETCH_OUTCOMES)):
        raise JdReadError("a %s attempt is written only via %s (got via %r): it records a page the Browser pane "
                          "could not render, or (pane-hidden only) a scripted fetch that did not read, never a read by "
                          "another route" % (outcome, " or ".join(NOT_ATTEMPTED_VIA), via))
    if via == "candidate" and outcome != READ and outcome not in WITHDRAWAL:
        raise JdReadError("a candidate attempt is a read: the candidate records what the posting says, "
                          "never a failure (via 'candidate' needs outcome 'read', or 'withdrawn' from 0.94.0: a verb's word about it)")
    _check_evidence(via, outcome, att["evidence"])
    out = dict(att)
    out["evidence"] = dict(att["evidence"])
    return out


def make_attempt(at, run, url, via, outcome, evidence, *, migration=False):
    """The ONE constructor a verb or the migration calls: a validated attempt dict. Refuses `via:
    legacy` unless `migration=True` -- a verb never writes a legacy read. Use keywords."""
    if via == LEGACY_VIA and not migration:
        raise JdReadError("via 'legacy' is written only by the migration, never by a verb")
    return parse_attempt({"at": at, "run": run, "url": url, "via": via, "outcome": outcome,
                          "evidence": evidence})


def parse(value):
    """The validated list of attempts in a `jd_read` value, oldest first as stored.

      None        -> []   (no `jd_read` means no attempt)
      {"attempts": [..]}  every attempt validated; an unknown top-level key, an empty list or a
                          non-list is refused.

    Raises `JdReadError` naming the attempt index."""
    if value is None:
        return []
    if not isinstance(value, dict):
        raise JdReadError("jd_read must be an object with an `attempts` list -- got %s"
                          % type(value).__name__)
    unknown = sorted(set(value) - {"attempts"})
    if unknown:
        raise JdReadError("jd_read has unknown key(s) %s" % ", ".join(unknown))
    atts = value.get("attempts")
    if not isinstance(atts, list) or not atts:
        raise JdReadError("jd_read.attempts must be a non-empty list -- a record with no attempt says "
                          "nothing (omit jd_read instead)")
    out = []
    for i, a in enumerate(atts):
        try:
            att = parse_attempt(a)
            if att["outcome"] == WITHDRAWN:
                of = att["evidence"]["of"]
                if not any(r["outcome"] == READ and r["at"] == of for r in out) or of > att["at"]:
                    raise JdReadError("a withdrawal names the read made at %s, and no read at that time is listed before it" % of)
            out.append(att)
        except JdReadError as e:
            raise JdReadError("attempts[%d]: %s" % (i, e))
    return out


def attempts(opp):
    """The validated attempts of an opportunity row (`[]` when it has none). Raises `JdReadError`."""
    return parse(opp.get("jd_read") if isinstance(opp, dict) else None)


def standing_of(atts):
    """`atts` (a stored list, oldest first) without the reads a later `withdrawn` attempt names and without the withdrawals themselves, as a
    new list (0.94.0, dev 1063, design-role-first.md 6.3). A withdrawal removes the reads listed BEFORE it whose `at` is its `of`; a read listed
    after it stays, so a re-read in the same second as the withdrawn one is not lost. TOLERANT, for a caller that reads raw rows on purpose
    (`browser_fallback/run_lines.py`): an item that is not a dict, or has no `evidence`, is kept and never raises."""
    out = []
    for a in atts or ():
        if isinstance(a, dict) and a.get("outcome") == WITHDRAWN:
            ev = a.get("evidence")
            of = ev.get("of") if isinstance(ev, dict) else None
            out = [r for r in out if not (isinstance(r, dict) and r.get("outcome") == READ and r.get("at") == of)]
        else:
            out.append(a)
    return out


def standing(opp):
    """The validated attempts of `opp` that STAND: `attempts(opp)` with every withdrawn read and every withdrawal left out. The ONE list a reader of
    reads asks for (`is_read`, `latest_read`, `read_attempts`, `lifecycle`, `recording/fit.py`); a WRITER that rewrites the record keeps
    `attempts()`, the lossless list. Raises `JdReadError` on a record this parser refuses."""
    return standing_of(attempts(opp))


def latest(opp):
    """The latest attempt that stands (greatest `at`; the later one in the list on a tie), or None. Raises
    `JdReadError` on a record this parser refuses."""
    return latest_of(standing(opp))


def latest_of(atts):
    best = None
    for i, a in enumerate(atts):
        key = (a["at"], i)
        if best is None or key >= best[0]:
            best = (key, a)
    return best[1] if best else None


def read_attempts(opp):
    """Every `read` attempt, oldest first."""
    return sorted((a for a in standing(opp) if a["outcome"] == READ), key=lambda a: a["at"])


def latest_read(opp):
    """The latest `read` attempt, or None."""
    rs = read_attempts(opp)
    return rs[-1] if rs else None


def is_read(opp):
    """True when any attempt that stands is a `read` (0.94.0: a withdrawn read is not). A JD that was tried and failed is NOT read."""
    return any(a["outcome"] == READ for a in standing(opp))


def legacy_attempt(opp):
    """`(attempt, status)` for the pre-0.82.0 read evidence of an opportunity row -- what the migration
    writes. `status` is one of:

      `none`        no `jd_read` is needed: the row has none of `fit.analyzed_on` and a non-empty
                    string `fit.jd_source`, or it already has a `jd_read`
      `ok`          `attempt` is the validated legacy attempt
      `unreadable`  the evidence is there but cannot be mapped (an `unavailable: ...` whose reason is
                    outside the closed set, an `analyzed_on` that is no date); nothing is written and
                    the role stays an unread process failure -- counted, never invented

    The attempt is `{at: analyzed_on + "T00:00:00", run: "legacy", url: jd_url or null, via: "legacy",
    outcome, evidence: {legacy: "fit.jd_source=<value, at most 200 characters>"}}`. `fit` is never
    modified."""
    if not isinstance(opp, dict) or opp.get("jd_read") is not None:
        return None, "none"
    fit = opp.get("fit")
    if not isinstance(fit, dict):
        return None, "none"
    source, on = fit.get("jd_source"), fit.get("analyzed_on")
    if not on or not isinstance(source, str) or not source.strip():
        return None, "none"
    try:
        day = datetime.date.fromisoformat(str(on))
    except ValueError:
        return None, "unreadable"
    text = source.strip()
    if text.lower().startswith(LEGACY_UNAVAILABLE_PREFIX):
        m = LEGACY_UNAVAILABLE_RE.match(text)
        if not m:
            return None, "unreadable"
        outcome = m.group(1)
    else:
        outcome = READ
    url = opp.get("jd_url")
    url = url if isinstance(url, str) and url.strip() else None
    try:
        att = make_attempt(day.isoformat() + "T00:00:00", LEGACY_RUN, url, LEGACY_VIA, outcome,
                           {"legacy": "fit.jd_source=" + text[:EVIDENCE_CAP]}, migration=True)
    except JdReadError:
        return None, "unreadable"
    return att, "ok"
