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
            render-failed | surface-cannot-read | site-not-allowed
  evidence  an object, never empty (shapes below)

The outcome CLASSES are disjoint and together cover `OUTCOMES`:

  read        the posting was read; the role's facts are re-derived from it
  TERMINAL    closed, dead-link          -- settles the role to `gone`
  CANDIDATE   manual-board, no-url,
              login-wall                 -- only the candidate can read it: settles to `your-read`
  HOST_CLASS  challenge, render-failed,
              surface-cannot-read,
              site-not-allowed           -- the machine or the pane failed: the run's work is unfinished

EVIDENCE
--------
  outcome `read`   {quote, chars?, sha1?, replaced?, attestation?}
                   `quote` is 1-200 characters and is required under `render` (a model attestation: the
                   posting's own title or Apply text) and under `candidate` (the candidate's own
                   one-line note, which must also carry `attestation: "candidate"`). `chars` and `sha1`
                   are written only by `record.py read-batch`, from the body it fetched itself.
  any failure      {text}  1-200 characters: the status line, the error text or the page's own words
  via `legacy`     {legacy}  `fit.jd_source=<value, at most 200 characters>`, for EVERY outcome

`legacy` is legal ONLY together with `run: "legacy"`, and only from the migration
(`make_attempt(..., migration=True)`); a verb that tries to write it is refused. It is the pre-0.82.0
read, kept so a role that was read before the upgrade does not turn into an unread process failure.

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

# The closed set `fit.jd_source: "unavailable: <reason>"` accepted from 0.67.0 (validate_data.
# JD_UNAVAILABLE_REASONS, mirrored here and pinned equal by a test). Each reason is also an outcome.
LEGACY_REASONS = ("login-wall", "dead-link", "no-url", "surface-cannot-read", "manual-board")
LEGACY_UNAVAILABLE_RE = re.compile(r"^unavailable: (%s)$" % "|".join(LEGACY_REASONS))
LEGACY_UNAVAILABLE_PREFIX = "unavailable"

EVIDENCE_CAP = 200
READ_EVIDENCE_KEYS = ("quote", "chars", "sha1", "replaced", "attestation")
FAILED_EVIDENCE_KEYS = ("text",)
LEGACY_EVIDENCE_KEYS = ("legacy",)
ATTEMPT_KEYS = ("at", "run", "url", "via", "outcome", "evidence")

_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")


class JdReadError(ValueError):
    """A `jd_read` value (or an attempt being made) that this parser refuses. Loud on purpose."""


def outcome_class(outcome):
    """`read` | `terminal` | `candidate` | `host`, or raises `JdReadError` for an unknown outcome."""
    if outcome == READ:
        return "read"
    if outcome in TERMINAL:
        return "terminal"
    if outcome in CANDIDATE:
        return "candidate"
    if outcome in HOST_CLASS:
        return "host"
    raise JdReadError("outcome %r is not one of %s" % (outcome, ", ".join(OUTCOMES)))


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


def _check_evidence(via, outcome, evidence):
    if not isinstance(evidence, dict) or not evidence:
        raise JdReadError("evidence must be a non-empty object -- %r" % (evidence,))
    if via == LEGACY_VIA:
        allowed = LEGACY_EVIDENCE_KEYS
    elif outcome == READ:
        allowed = READ_EVIDENCE_KEYS
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
    if outcome != READ:
        _text(evidence.get("text"), "evidence.text")
        return
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
    if via == "candidate" and outcome != READ:
        raise JdReadError("a candidate attempt is a read: the candidate records what the posting says, "
                          "never a failure (via 'candidate' needs outcome 'read')")
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
            out.append(parse_attempt(a))
        except JdReadError as e:
            raise JdReadError("attempts[%d]: %s" % (i, e))
    return out


def attempts(opp):
    """The validated attempts of an opportunity row (`[]` when it has none). Raises `JdReadError`."""
    return parse(opp.get("jd_read") if isinstance(opp, dict) else None)


def latest(opp):
    """The latest attempt (greatest `at`; the later one in the list on a tie), or None. Raises
    `JdReadError` on a record this parser refuses."""
    return latest_of(attempts(opp))


def latest_of(atts):
    best = None
    for i, a in enumerate(atts):
        key = (a["at"], i)
        if best is None or key >= best[0]:
            best = (key, a)
    return best[1] if best else None


def read_attempts(opp):
    """Every `read` attempt, oldest first."""
    return sorted((a for a in attempts(opp) if a["outcome"] == READ), key=lambda a: a["at"])


def latest_read(opp):
    """The latest `read` attempt, or None."""
    rs = read_attempts(opp)
    return rs[-1] if rs else None


def is_read(opp):
    """True when any attempt is a `read`. A JD that was tried and failed is NOT read."""
    return any(a["outcome"] == READ for a in attempts(opp))


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
