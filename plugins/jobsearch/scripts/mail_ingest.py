#!/usr/bin/env python3
"""
Fetch, ingest and coverage for mail read through a claude.ai connector (Gmail, Microsoft 365,
Fastmail, Superhuman) -- pure standard library (docs/design-mail-any-connector.md sections 3, 4, 7.1
and 14, dev #799).

    python3 scripts/mail_ingest.py preflight --tools mcp__<server>__<tool> [...]
    python3 scripts/mail_ingest.py plan      --server <server>
    python3 scripts/mail_ingest.py ingest    --account <address>
    python3 scripts/mail_ingest.py needs-body --account <address>
    python3 scripts/mail_ingest.py query     --account <address> --query "<gmail query>"
    python3 scripts/mail_ingest.py status

THE SPLIT (design A1)
---------------------
A script is not known to be able to call a claude.ai connector, and the model is the only caller one
has. So the MODEL fetches -- `inbox-scan` reads the connector's own search and read tools and writes
a normalised bundle -- and this SCRIPT ingests: it refuses what it cannot read, and the six mail
consumers then read the bundle through `mail_client.BundleMailbox` with their own matching.

THE BUNDLE (section 3.2): a JSON-lines file. Line 1 is a header (`bundle`, `connector`, `server`,
`account`, `phase`, `window`, `exhausted`, `observed_empty`, `fetched_at`, `pages`); every other line
is one message record. The header carries the connector's OWN page ids, exactly as the connector
returned them, so `ingest` can refuse a DROPPED page and a record that appears on NO page:

    exhausted: true      requires the last page's `next` to be null
    every page id        must appear as some record's `provider_id` or `thread_id`
    every record         must appear on some page, unless it carries `expanded_from: <page id>`
    exhausted + 0 records is refused unless `observed_empty` and every page has `ids: []`

That is a CONSISTENCY check, not a fidelity check: a model that invents a record AND lists its id on
a page passes. Whether `ingest` could compare ids against the dispatch's real tool results is
UNDETERMINED (probe P4). Fidelity is listed under Not claimed (section 11).

WHERE IT LIVES, AND THE TEST SEAM (section 3.4)
-----------------------------------------------
`<profile>/.jobsearch/mail_bundle/<connector>/<account>.jsonl` (kept) and `.../incoming/` (where the
agent writes). NO machine fallback: `state_root()` falls back to $HOME for a disposable profile, so
every path here refuses instead -- `no genuine profile: mail is never written under HOME`.
`JOBSEARCH_BUNDLE_DIR` is honoured ONLY when `is_disposable_profile()` is true and the directory sits
inside that profile's tree or under the temp dir; for a genuine profile it is refused, so it can never
redirect real mail.

THE PREFLIGHT (section 7.1, section 14 R2-S0 / R2-S1 / S2 / S3)
---------------------------------------------------------------
Runs before `inbox-scan` is dispatched and prints exactly one verdict. ANYTHING BUT `covered` skips
the fetch for that run and announces it. NOTHING WAITS: a permission prompt does not time out, and a
scheduled run has nobody to answer it. `covered` means "no grant gap found in the reported tool names
and the settings sources read" -- NOT "will not prompt" (M2): an organisation's per-tool `ask`, the
CLI's `--settings`, `--allowedTools` and `--permission-mode` are invisible to it (Not claimed).

THE CONNECTOR TABLE is `mail_connectors.CONNECTORS`, in `mail_connectors.py` (criterion #799-1); this
file reads a row through `connector_table()` and uses only `label`, `search_tool`, `body_tool`,
`read_tools` and `server_hints`. Tests inject a table by patching `connector_table`. The query
language the consumers speak is evaluated by `mail_query.py`; the backend that serves it is
`mail_client.py`. They are named here BY FILE NAME on purpose: `publish_manifest.py` follows
`<name>.py` mentions to decide what ships, and a bare `import` is invisible to it.

Exit codes: 0 done / `covered`; 1 `preflight` found anything but `covered`; 2 refused (a bad bundle,
an unusable location, an unreadable selection).
"""

import argparse
import datetime as _dt
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(os.path.realpath(__file__))))
import _root
import _atomic
import journal as _journal
import mail_client as _mc
import mail_query as _mq

BUNDLE_VERSION = 1
RECORD_VERSION = 1
SEAM_ENV = "JOBSEARCH_BUNDLE_DIR"

# One daily cadence plus two hours (design 3.5). A bundle whose window ends longer ago is STALE.
CONNECTOR_BUNDLE_STALE_HOURS = 26
# Bodies are fetched only for the messages some consumer's query is unknown for, ranked, capped.
CONNECTOR_BODY_FETCH_MAX = 25
# A cap on one account's bundle (section 14 S4). Past it the window narrows and says so.
CONNECTOR_BUNDLE_MAX_RECORDS = 400
BODY_TEXT_MAX_CHARS = 20000
# The fetch phase is bounded (section 14 M2): the agent stops and ingests what it holds.
FETCH_MAX_MINUTES = 15
FETCH_MAX_PAGES = 12
# A window that ends within this of `now` is "to now" for the NOT COVERED printout (OURS): the
# fetch finishes minutes before the sweeps run, and a daily "NOT COVERED: after 08:00" line a
# few minutes long would train its reader to skim. The tail is not lost: the next plan reaches
# back to `covered_through`, so the next run fetches it.
TAIL_GRACE = _dt.timedelta(hours=1)

FOLDERS = ("inbox", "sent", "archive", "spam", "trash", "other")
REPORT_HINT = "if this connector's results changed shape, report it: report_issue.py"

_HEADER_KEYS = {"bundle", "connector", "server", "account", "phase", "window", "exhausted",
                "observed_empty", "fetched_at", "pages", "part", "records", "bodies_fetched",
                "kind", "capped", "ingested_at", "pages_checked"}
_RECORD_KEYS = {"v", "message_id", "provider_id", "thread_id", "in_reply_to", "references", "from",
                "to", "cc", "subject", "date", "folders", "attachments", "preview", "body_text",
                "body_truncated", "expanded_from"}
_BODY_KEYS = {"v", "message_id", "provider_id", "body_text", "body_truncated", "attachments"}
_MESSAGE_ID_RE = re.compile(r"^<[^<>\s@]+@[^<>\s]+>$")
_ADDRESS_RE = re.compile(r"^[^@\s<>]+@[^@\s<>]+$")
_ACCOUNT_FILE_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+$")

BundleError = _mc.BundleError
BundleAbsent = _mc.BundleAbsent


class BundleRefused(_mc.BundleError):
    """`ingest` (or a bundle read) refused a file. `line` is the 1-based line, 0 for a whole-file
    finding. Every refusal reads `MAIL BUNDLE REFUSED (<connector>) ... report_issue.py`."""

    def __init__(self, connector, line, reason):
        self.connector, self.line, self.reason = connector, line, reason
        _mc.BundleError.__init__(
            self, "MAIL BUNDLE REFUSED (%s) line %d: %s -- %s" % (connector, line, reason, REPORT_HINT))


# --------------------------------------------------------------------------
# The connector table
# --------------------------------------------------------------------------

def connector_table():
    """{value: row} from `mail_connectors.CONNECTORS` (criterion #799-1). Raises `ConnectorNotSelected`
    (a selection with no backend) when that module cannot be read."""
    try:
        import mail_connectors
    except ImportError as exc:
        raise _mc.ConnectorNotSelected("the connector table (mail_connectors.py) cannot be read: %s" % exc)
    table = mail_connectors.CONNECTORS
    if isinstance(table, dict):
        return dict(table)
    return {_row_get(r, "value"): r for r in table}


def _row_get(row, key, default=None):
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def row_for(connector):
    """The connector table's row for `connector`, or `ConnectorNotSelected` (a selection with NO bundle
    backend: its row is absent, or the table cannot be read). The message names the connector."""
    try:
        table = connector_table()
    except _mc.ConnectorNotSelected as exc:
        raise _mc.ConnectorNotSelected(
            "your mail connector is '%s', which has no bundle backend (%s)" % (connector, exc))
    if connector not in table:
        raise _mc.ConnectorNotSelected(
            "your mail connector is '%s', which has no row in the connector table, so no bundle "
            "backend" % connector)
    return table[connector]


# --------------------------------------------------------------------------
# Time
# --------------------------------------------------------------------------

def utcnow():
    """Now, aware UTC — through `mail_client._clock`, the ONE patch point a test freezes."""
    return _mc._clock()


def parse_aware(raw):
    """An aware datetime from an ISO 8601 string with an offset (`Z` accepted), else None."""
    if not isinstance(raw, str):
        return None
    try:
        d = _dt.datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo is not None else None


def iso_z(d):
    return d.astimezone(_dt.timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_local_naive(d):
    """The journal's own form: a naive LOCAL ISO timestamp (see `journal.now_iso`)."""
    return d.astimezone().replace(tzinfo=None, microsecond=0)


def from_local_naive(d):
    return d.astimezone(_dt.timezone.utc) if d.tzinfo else d.astimezone().astimezone(_dt.timezone.utc)


# --------------------------------------------------------------------------
# Where a bundle lives
# --------------------------------------------------------------------------

def _under(path, parent):
    p, q = os.path.realpath(path), os.path.realpath(parent)
    return p == q or p.startswith(q.rstrip(os.sep) + os.sep)


def bundle_root(profile=None):
    """`<profile>/.jobsearch/mail_bundle`, or the test seam. Raises `BundleError` for no profile, a
    disposable profile without the seam, or the seam for a genuine profile (section 3.4)."""
    profile = profile or _root.profile_root()
    override = os.environ.get(SEAM_ENV, "").strip()
    if override:
        if not _root.is_disposable_profile(profile):
            raise BundleError("%s is honoured only for a disposable (test) profile and is refused "
                              "for a genuine one: it must never redirect real mail" % SEAM_ENV)
        if not (_under(override, profile) or _under(override, tempfile.gettempdir())):
            raise BundleError("%s=%s is outside the profile's tree and the temp directory"
                              % (SEAM_ENV, override))
        return override
    if _root.is_unbound(profile) or not _root.looks_like_profile(profile):
        raise BundleError("no profile: no job-search profile is bound here, so there is nowhere to "
                          "keep a mail bundle")
    if _root.is_disposable_profile(profile):
        raise BundleError("no genuine profile: mail is never written under HOME (%s is a "
                          "disposable profile)" % profile)
    return os.path.join(profile, _root.STATE_DIRNAME, "mail_bundle")


def _safe_account(account):
    if not isinstance(account, str) or not _ACCOUNT_FILE_RE.match(account) or ".." in account:
        raise BundleError("%r is not an address this file will build a path from" % (account,))
    return account.lower()


def connector_dir(connector, profile=None):
    if not re.match(r"^[a-z0-9-]+$", connector or ""):
        raise BundleError("%r is not a connector value" % (connector,))
    return os.path.join(bundle_root(profile), connector)


def kept_path(connector, account, profile=None):
    return os.path.join(connector_dir(connector, profile), _safe_account(account) + ".jsonl")


def incoming_dir(connector, profile=None):
    return os.path.join(connector_dir(connector, profile), "incoming")


def incoming_paths(connector, account, profile=None):
    """The agent's output: `<account>.jsonl`, or `<account>.part1.jsonl`, `.part2.jsonl` ... (a
    bundle over the record cap comes in parts)."""
    d, name = incoming_dir(connector, profile), _safe_account(account)
    out = []
    if os.path.isdir(d):
        base = name + ".jsonl"
        rx = re.compile(r"^%s\.part(\d+)\.jsonl$" % re.escape(name))
        parts = sorted((int(m.group(1)), f) for f in os.listdir(d) for m in [rx.match(f)] if m)
        if os.path.exists(os.path.join(d, base)):
            out.append(os.path.join(d, base))
        out.extend(os.path.join(d, f) for _n, f in parts)
    return out


# --------------------------------------------------------------------------
# The strict parser
# --------------------------------------------------------------------------

def record_key(rec, connector):
    """The dedupe key: the RFC 5322 Message-ID, else `x-provider:<connector>:<provider_id>` (A6)."""
    if rec.get("message_id"):
        return rec["message_id"]
    return "x-provider:%s:%s" % (connector, rec["provider_id"])


def uid_for(key):
    """A stable, ASCII-digit uid for a record key (the source-tag grammar is `<tag>:<account>:<digits>`)."""
    import hashlib
    return str(int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:12], 16))


def _person(v, what, nullable=False):
    if v is None and nullable:
        return None
    if (not isinstance(v, dict) or set(v) - {"name", "email"} or not isinstance(v.get("email"), str)
            or not _ADDRESS_RE.match(v["email"]) or not isinstance(v.get("name", ""), str)):
        raise ValueError("%s must be {name, email} with an address" % what)
    return {"name": v.get("name") or "", "email": v["email"]}


def _check_record(rec, connector, phase):
    """Validate one record dict in place-free fashion; returns the normalised record or raises
    ValueError(reason)."""
    if not isinstance(rec, dict):
        raise ValueError("a record is a JSON object")
    allowed = _RECORD_KEYS if phase == "headers" else _BODY_KEYS
    unknown = sorted(set(rec) - allowed)
    if unknown:
        raise ValueError("unknown key %s" % ", ".join(repr(k) for k in unknown))
    if rec.get("v") != RECORD_VERSION:
        raise ValueError("unknown record version v=%r" % (rec.get("v"),))
    mid, pid = rec.get("message_id"), rec.get("provider_id")
    if mid is not None and (not isinstance(mid, str) or not _MESSAGE_ID_RE.match(mid)):
        raise ValueError("message_id %r is not an RFC 5322 <local@host>" % (mid,))
    if pid is not None and (not isinstance(pid, str) or not pid.strip()):
        raise ValueError("provider_id must be a non-empty string")
    if not mid and not pid:
        raise ValueError("a record needs a message_id or a provider_id")
    out = dict(rec)
    atts = rec.get("attachments")
    if atts is not None:
        if not isinstance(atts, list) or not all(
                isinstance(a, dict) and isinstance(a.get("filename"), str)
                and not set(a) - {"filename", "content_type", "size"} for a in atts):
            raise ValueError("attachments must be null or a list of {filename, content_type?, size?}")
    if phase == "bodies":
        body = rec.get("body_text")
        if not isinstance(body, str):
            raise ValueError("a bodies record needs a body_text string")
        out["body_truncated"] = bool(rec.get("body_truncated", False))
        if len(body) > BODY_TEXT_MAX_CHARS:
            out["body_text"], out["body_truncated"] = body[:BODY_TEXT_MAX_CHARS], True
        return out
    out["from"] = _person(rec.get("from"), "from")
    for k in ("to", "cc"):
        v = rec.get(k)
        if v is not None and not isinstance(v, list):
            raise ValueError("%s must be null or a list" % k)
        out[k] = None if v is None else [_person(p, k) for p in v]
    if not isinstance(rec.get("subject"), str):
        raise ValueError("subject must be a string (it may be empty)")
    if parse_aware(rec.get("date")) is None:
        raise ValueError("date %r is not ISO 8601 with an offset" % (rec.get("date"),))
    folders = rec.get("folders", "MISSING")
    if folders == "MISSING":
        raise ValueError("folders is required (null when not known)")
    if folders is not None and (not isinstance(folders, list) or not all(f in FOLDERS for f in folders)):
        raise ValueError("folders must be null or a subset of %s" % ", ".join(FOLDERS))
    for k in ("thread_id", "in_reply_to", "preview", "body_text", "expanded_from"):
        if rec.get(k) is not None and not isinstance(rec[k], str):
            raise ValueError("%s must be null or a string" % k)
    refs = rec.get("references")
    if refs is not None and (not isinstance(refs, list) or not all(isinstance(x, str) for x in refs)):
        raise ValueError("references must be null or a list of strings")
    body = rec.get("body_text")
    out["body_truncated"] = bool(rec.get("body_truncated", False))
    if isinstance(body, str) and len(body) > BODY_TEXT_MAX_CHARS:
        out["body_text"], out["body_truncated"] = body[:BODY_TEXT_MAX_CHARS], True
    for k in _RECORD_KEYS - {"v", "from"}:
        out.setdefault(k, None if k != "body_truncated" else False)
    return out


def _check_header(h, connector, accounts, phase_ok=("headers", "bodies"), kept=False):
    """Validate a header dict; returns a normalised dict with parsed times, or raises ValueError."""
    if not isinstance(h, dict):
        raise ValueError("the first line must be a JSON object (the header)")
    unknown = sorted(set(h) - _HEADER_KEYS)
    if unknown:
        raise ValueError("unknown header key %s" % ", ".join(repr(k) for k in unknown))
    if h.get("bundle") != BUNDLE_VERSION:
        raise ValueError("unknown bundle version %r" % (h.get("bundle"),))
    if h.get("connector") != connector:
        raise ValueError("connector %r is not the selected connector %r" % (h.get("connector"), connector))
    if not isinstance(h.get("server"), str) or not h["server"].strip():
        raise ValueError("the header names no server (the connector's MCP server, from `preflight`)")
    acct = h.get("account")
    if not isinstance(acct, str) or acct.lower() not in {a.lower() for a in accounts}:
        raise ValueError("account %r is not a declared address of this profile" % (acct,))
    if h.get("phase") not in phase_ok:
        raise ValueError("phase %r is not one of %s" % (h.get("phase"), ", ".join(phase_ok)))
    w = h.get("window")
    if not isinstance(w, dict) or set(w) != {"from", "through"}:
        raise ValueError("window must be {from, through}")
    wf, wt = parse_aware(w["from"]), parse_aware(w["through"])
    if wf is None or wt is None:
        raise ValueError("window.from and window.through must be ISO 8601 with an offset")
    if wf > wt:
        raise ValueError("window.from is after window.through")
    if not isinstance(h.get("exhausted"), bool):
        raise ValueError("exhausted must be true or false")
    if not isinstance(h.get("observed_empty", False), bool):
        raise ValueError("observed_empty must be true or false")
    fa = parse_aware(h.get("fetched_at"))
    if fa is None:
        raise ValueError("fetched_at must be ISO 8601 with an offset")
    pages = h.get("pages", [] if (kept or h.get("phase") == "bodies") else None)
    if (not isinstance(pages, list) or not all(
            isinstance(p, dict) and set(p) == {"tool", "ids", "next"} and isinstance(p["tool"], str)
            and isinstance(p["ids"], list) and all(isinstance(i, str) and i for i in p["ids"])
            and (p["next"] is None or isinstance(p["next"], str)) for p in pages)):
        raise ValueError("pages must be a list of {tool, ids, next}")
    part = h.get("part")
    if part is not None and (not isinstance(part, dict) or set(part) != {"n", "of"}
                            or not all(isinstance(part[k], int) and part[k] >= 1 for k in part)
                            or part["n"] > part["of"]):
        raise ValueError("part must be {n, of} with 1 <= n <= of")
    out = dict(h)
    out.update(window_from=wf, window_through=wt, fetched=fa, pages=pages,
               observed_empty=bool(h.get("observed_empty", False)))
    return out


def _split_lines(text):
    return [(i, ln) for i, ln in enumerate(text.splitlines(), 1) if ln.strip()]


def _parse_file(label, text, connector, accounts, kept=False):
    lines = _split_lines(text)
    if not lines:
        raise BundleRefused(connector, 0, "%s is empty" % label)
    n0, first = lines[0]
    try:
        header = _check_header(json.loads(first), connector, accounts, kept=kept)
    except ValueError as exc:
        raise BundleRefused(connector, n0, "%s: header: %s" % (label, exc))
    recs = []
    for n, ln in lines[1:]:
        try:
            raw = json.loads(ln)
        except ValueError as exc:
            raise BundleRefused(connector, n, "%s: not valid JSON (%s)" % (label, exc))
        try:
            recs.append((n, _check_record(raw, connector, header["phase"])))
        except ValueError as exc:
            raise BundleRefused(connector, n, "%s: %s" % (label, exc))
    return header, recs


class Bundle(object):
    """One account's validated bundle: header facts plus records (a list of dicts, oldest first)."""

    def __init__(self, connector, account, header, records):
        self.connector, self.account = connector, account
        self.header = header
        self.server = header["server"]
        self.window_from, self.window_through = header["window_from"], header["window_through"]
        self.exhausted, self.observed_empty = header["exhausted"], header["observed_empty"]
        self.fetched_at = header["fetched"]
        self.capped = header.get("capped")
        self.bodies_fetched = int(header.get("bodies_fetched") or 0)
        self.records = sorted(records, key=lambda r: parse_aware(r["date"]))
        self.by_key = {record_key(r, connector): r for r in self.records}
        self.by_uid = {}
        for k in self.by_key:
            u = uid_for(k)
            if u in self.by_uid:
                raise BundleRefused(connector, 0, "two messages share the uid %s" % u)
            self.by_uid[u] = k

    def age(self, now):
        return now - self.window_through

    def stale(self, now):
        return self.age(now) > _dt.timedelta(hours=CONNECTOR_BUNDLE_STALE_HOURS)


def _same_identity(a, b):
    return all(a.get(k) == b.get(k) for k in ("from", "date", "subject"))


def parse_headers_phase(files, connector, accounts):
    """The whole-file strict parse of one account's incoming headers files (a single file, or parts).
    `files` is [(label, text)]. Returns (header, records, warnings); raises `BundleRefused`."""
    parsed = [(_label, ) + _parse_file(_label, text, connector, accounts) for _label, text in files]
    headers = [p[1] for p in parsed]
    for _l, h, _r in parsed:
        if h["phase"] != "headers":
            raise BundleRefused(connector, 1, "%s: phase %r in a headers ingest" % (_l, h["phase"]))
    first = headers[0]
    if len(parsed) > 1 or first.get("part"):
        ns = sorted((h.get("part") or {}).get("n", 0) for h in headers)
        of = {(h.get("part") or {}).get("of") for h in headers}
        if len(of) != 1 or None in of or ns != list(range(1, len(parsed) + 1)) or of != {len(parsed)}:
            raise BundleRefused(connector, 0, "parts are incomplete: the files hold parts %s of %s"
                                % (ns, sorted(x for x in of if x)))
        parsed.sort(key=lambda p: p[1]["part"]["n"])
        headers = [p[1] for p in parsed]
    for h in headers[1:]:
        for k in ("account", "server", "window_from", "window_through", "exhausted"):
            if h[k] != first[k]:
                raise BundleRefused(connector, 1, "parts disagree on %s" % k)
    pages = [pg for h in headers for pg in h["pages"]]
    records, seen = [], {}
    for label, _h, recs in parsed:
        for n, rec in recs:
            key = record_key(rec, connector)
            if key in seen:
                if not _same_identity(seen[key], rec):
                    raise BundleRefused(connector, n, "%s: the id %s appears twice with a different "
                                        "from, date or subject" % (label, key))
                continue
            seen[key] = rec
            records.append((n, label, rec))
    # page consistency (section 3.3): a dropped page and a fabricated record are both refused
    page_ids = {i for pg in pages for i in pg["ids"]}
    held = {r.get(k) for _n, _l, r in records for k in ("provider_id", "thread_id") if r.get(k)}
    if first["exhausted"]:
        if not pages:
            raise BundleRefused(connector, 0, "exhausted is true but the header lists no page")
        if pages[-1]["next"] is not None:
            raise BundleRefused(connector, 0, "exhausted is true but the last page's next is %r, "
                                "not null (a dropped page)" % pages[-1]["next"])
        if not records and not (first["observed_empty"] and all(not pg["ids"] for pg in pages)):
            raise BundleRefused(connector, 0, "exhausted with zero records needs observed_empty: "
                                "true and every page's ids empty")
    for pid in sorted(page_ids):
        if pid not in held:
            raise BundleRefused(connector, 0, "page id %s has no record" % pid)
    for n, label, r in records:
        if r.get("expanded_from"):
            if r["expanded_from"] not in page_ids:
                raise BundleRefused(connector, n, "%s: expanded_from %s is on no page"
                                    % (label, r["expanded_from"]))
        elif not ({r.get("provider_id"), r.get("thread_id")} & page_ids):
            raise BundleRefused(connector, n, "%s: record on no page" % label)
    warnings = []
    addr = first["account"].lower()
    if records and not any(
            addr in ("%s %s %s" % (r["from"]["email"], " ".join(p["email"] for p in r["to"] or []),
                                   " ".join(p["email"] for p in r["cc"] or []))).lower()
            for _n, _l, r in records):
        warnings.append("!! ACCOUNT MISMATCH? no record has %s in from, to or cc -- is the connector "
                        "signed in to that mailbox?" % first["account"])
    out = dict(first)
    out["pages"] = pages
    return out, [r for _n, _l, r in records], warnings


def _header_to_json(h, records_count):
    out = {k: h[k] for k in ("bundle", "connector", "server", "account", "phase") if k in h}
    out["kind"] = "kept"
    out["window"] = {"from": iso_z(h["window_from"]), "through": iso_z(h["window_through"])}
    out["exhausted"] = h["exhausted"]
    out["observed_empty"] = h["observed_empty"]
    out["fetched_at"] = iso_z(h["fetched"])
    out["pages_checked"] = len(h.get("pages") or [])
    out["records"] = records_count
    out["bodies_fetched"] = int(h.get("bodies_fetched") or 0)
    out["capped"] = h.get("capped")
    return out


def _write_kept(path, header, records):
    body = [json.dumps(_header_to_json(header, len(records)), sort_keys=True)]
    body += [json.dumps(r, sort_keys=True, ensure_ascii=False) for r in records]
    _atomic.write_text(path, "\n".join(body) + "\n")


def prune(records, now, days=None):
    """Drop records dated before `now - CONNECTOR_BACKFILL_MAX_DAYS` (every ingest and every open)."""
    cutoff = now - _dt.timedelta(days=days or _mc.CONNECTOR_BACKFILL_MAX_DAYS)
    return [r for r in records if parse_aware(r["date"]) >= cutoff]


def narrow_to_cap(header, records, cap=None):
    """Past the cap the window NARROWS to the newest records and the header says how many arrived."""
    cap = CONNECTOR_BUNDLE_MAX_RECORDS if cap is None else cap
    if len(records) <= cap:
        return header, records
    ranked = sorted(records, key=lambda r: parse_aware(r["date"]), reverse=True)[:cap]
    new_from = min(parse_aware(r["date"]) for r in ranked)
    header = dict(header)
    header["capped"] = len(records)
    header["window_from"] = max(header["window_from"], new_from)
    return header, [r for r in records if parse_aware(r["date"]) >= header["window_from"]]


def load_kept(connector, account, accounts=None, now=None, profile=None):
    """The kept bundle for `account` as a `Bundle`, pruned to the backfill depth. Raises
    `BundleAbsent` (nothing kept) or `BundleRefused` (a file that no longer parses)."""
    now = now or utcnow()
    path = kept_path(connector, account, profile)
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except FileNotFoundError:
        raise BundleAbsent("NOT COVERED: no bundle for %s under %s (nothing was fetched and ingested; "
                           "run mail_ingest.py preflight, then the inbox-scan fetch)"
                           % (account, connector))
    except OSError as exc:
        raise BundleError("NOT COVERED: the bundle for %s cannot be read (%s)" % (account, exc))
    header, recs = _parse_file(os.path.basename(path), text, connector,
                               accounts if accounts is not None else [account], kept=True)
    return Bundle(connector, account, header, prune([r for _n, r in recs], now))


def kept_or_none(connector, account, accounts=None, now=None, profile=None):
    try:
        return load_kept(connector, account, accounts, now, profile)
    except BundleAbsent:
        return None


# --------------------------------------------------------------------------
# ingest
# --------------------------------------------------------------------------

def _read_all(paths):
    out = []
    for p in paths:
        with open(p, encoding="utf-8") as fh:
            out.append((os.path.basename(p), fh.read()))
    return out


def ingest(connector, account, accounts, now=None, profile=None, out=print):
    """Validate and keep one account's incoming bundle (headers) or bodies. Raises `BundleRefused`
    / `BundleError`; writes NOTHING unless every line parsed. Returns a one-line summary."""
    now = now or utcnow()
    paths = incoming_paths(connector, account, profile)
    if not paths:
        raise BundleError("nothing to ingest for %s: no file under %s" % (account,
                                                                          incoming_dir(connector, profile)))
    files = _read_all(paths)
    phases = set()
    for label, text in files:
        lines = _split_lines(text)
        try:
            phases.add(json.loads(lines[0][1]).get("phase"))
        except (ValueError, IndexError, AttributeError):
            phases.add(None)
    if len(phases) != 1:
        raise BundleRefused(connector, 1, "the incoming files mix phases %s" % sorted(map(str, phases)))
    phase = phases.pop()
    if phase == "bodies":
        summary = _ingest_bodies(connector, account, accounts, files, now, profile, out)
    else:
        header, records, warnings = parse_headers_phase(files, connector, accounts)
        records = prune(records, now)
        header, records = narrow_to_cap(header, records)
        header["bodies_fetched"] = 0
        _write_kept(kept_path(connector, account, profile), header, records)
        for w in warnings:
            out(w)
        if header.get("capped"):
            out("NOT COVERED: window too large (%d records) -- the window narrowed to %s..%s"
                % (header["capped"], iso_z(header["window_from"]), iso_z(header["window_through"])))
        summary = ("ingested %d record(s) for %s (%s): window %s..%s, %s"
                   % (len(records), account, connector, iso_z(header["window_from"]),
                      iso_z(header["window_through"]),
                      "exhausted" if header["exhausted"] else "NOT exhausted"))
    for p in paths:
        try:
            os.remove(p)
        except OSError:
            pass
    return summary


def _ingest_bodies(connector, account, accounts, files, now, profile, out):
    kept = load_kept(connector, account, accounts, now, profile)
    parsed = [_parse_file(label, text, connector, accounts) for label, text in files]
    n_done = 0
    for header, recs in parsed:
        if header["server"] != kept.server:
            raise BundleRefused(connector, 1, "the bodies file names server %r but the bundle names %r"
                                % (header["server"], kept.server))
        for n, b in recs:
            key = b.get("message_id") if b.get("message_id") in kept.by_key else None
            if key is None and b.get("provider_id"):
                key = next((k for k, r in kept.by_key.items()
                            if r.get("provider_id") == b["provider_id"]), None)
            if key is None:
                raise BundleRefused(connector, n, "a bodies record not in the bundle (%s)"
                                    % (b.get("message_id") or b.get("provider_id")))
            tgt = kept.by_key[key]
            tgt["body_text"], tgt["body_truncated"] = b["body_text"], b["body_truncated"]
            if b.get("attachments") is not None:
                tgt["attachments"] = b["attachments"]
            n_done += 1
    h = dict(kept.header)
    h["bodies_fetched"] = kept.bodies_fetched + n_done
    h["pages"] = []
    h["fetched"] = kept.fetched_at
    _write_kept(kept_path(connector, account, profile), h, kept.records)
    return "ingested %d body/bodies for %s (%s)" % (n_done, account, connector)


# --------------------------------------------------------------------------
# needs-body
# --------------------------------------------------------------------------

# watch.py's two category queries, copied here (its source is scanned for the literals by
# test_profile.py, so they stay inline there); `test_mail_query.py` pins these equal to the ones in
# watch.main() so the two cannot drift.
WATCH_ALERT_QUERY = ('(from:indeed OR from:linkedin OR from:ladders OR '
                     'subject:("new jobs" OR "job alert")) newer_than:%dd')
WATCH_MEETING_QUERY = ('(subject:(Invitation OR "Updated invitation" OR "Appointment booked" OR '
                       '"Event accepted" OR interview) OR filename:ics) newer_than:%dd')


def consumer_queries():
    """[(consumer, query)] for the consumers whose query is known before they run. The data-dependent
    ones (reconcile's per-person search, brief's probe) are not planned here: a message still unknown
    when they run counts as NOT COVERED, never as a miss."""
    import alert_sweep, meeting_check
    return [("alert_sweep", alert_sweep.build_query(1)),
            ("meeting_check", "(%s) newer_than:7d" % meeting_check.MEETING_QUERY),
            ("watch", WATCH_ALERT_QUERY % 1),
            ("watch", WATCH_MEETING_QUERY % 1)]


def needs_body(bundle, queries, now=None, cap=CONNECTOR_BODY_FETCH_MAX):
    """[(record, [consumers])]: the messages some query is unknown for BECAUSE a body or attachment
    list was not fetched, ranked by how many consumers wait on them (then newest first), capped."""
    now = now or utcnow()
    waiting = {}
    for consumer, q in queries:
        for rec in bundle.records:
            try:
                if _mq.needs_body(q, rec, now):
                    waiting.setdefault(record_key(rec, bundle.connector), set()).add(consumer)
            except _mq.QueryUnsupported:
                raise
    ranked = sorted(waiting, key=lambda k: (-len(waiting[k]),
                                            -parse_aware(bundle.by_key[k]["date"]).timestamp()))
    return [(bundle.by_key[k], sorted(waiting[k])) for k in ranked[:cap]]


# --------------------------------------------------------------------------
# preflight (section 7.1, section 14 R2-S0, R2-S1, S2, S3)
# --------------------------------------------------------------------------

def default_managed_path():
    if sys.platform == "darwin":
        return "/Library/Application Support/ClaudeCode/managed-settings.json"
    if sys.platform.startswith("win"):
        return r"C:\Program Files\ClaudeCode\managed-settings.json"
    return "/etc/claude-code/managed-settings.json"


def _git_root(start):
    d = os.path.abspath(start)
    while True:
        if os.path.exists(os.path.join(d, ".git")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def settings_sources(cwd=None, home=None, config_dir=None, managed_path=None):
    """[(label, path)] in precedence order: managed, local, project, user (R2-S1)."""
    cwd = cwd or os.getcwd()
    cfg = config_dir or os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(
        home or os.path.expanduser("~"), ".claude")
    git_root = _git_root(cwd) or cwd
    return [("managed", managed_path or default_managed_path()),
            ("local", os.path.join(git_root, ".claude", "settings.local.json")),
            ("project", os.path.join(os.path.abspath(cwd), ".claude", "settings.json")),
            ("user", os.path.join(cfg, "settings.json"))]


def read_settings(sources):
    """[(label, path, data)] for each source that EXISTS; `data` is None for an unreadable one. A
    file that is present and cannot be read is never treated as absent."""
    out = []
    for label, path in sources:
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                data = None
        except (OSError, ValueError):
            data = None
        out.append((label, path, data))
    return out


def _rules(settings, kind):
    out = []
    for _label, _path, data in settings:
        perms = (data or {}).get("permissions")
        if isinstance(perms, dict) and isinstance(perms.get(kind), list):
            out.extend(r.strip() for r in perms[kind] if isinstance(r, str))
    return out


def _mcp_rule_matches(rule, server, tool):
    return rule in ("mcp__%s" % server, "mcp__%s__*" % server, "mcp__%s__%s" % (server, tool))


def _glob_re(pattern):
    out, i = [], 0
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
            if pattern.startswith("/", i) and out[-1] == ".*":
                out[-1] = "(?:.*/)?"
                i += 1
            continue
        out.append("[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c))
        i += 1
    return re.compile("^" + "".join(out) + "$")


def _edit_rule_matches(rule, target):
    """Does an `Edit(//abs/glob)` rule match `target`? Only the `//`-anchored absolute form counts
    (section 14 R2-S0): a `Write(...)` rule never matches, and a relative form is not counted."""
    m = re.match(r"^Edit\((//.+)\)$", rule)
    if not m:
        return False
    return bool(_glob_re(m.group(1)[1:]).match(target))


def _default_mode(settings):
    for _l, _p, data in settings:
        perms = (data or {}).get("permissions")
        if isinstance(perms, dict) and isinstance(perms.get("defaultMode"), str):
            return perms["defaultMode"]
    return None


def parse_tool_name(name):
    m = re.match(r"^mcp__(.+?)__(.+)$", name or "")
    return (m.group(1), m.group(2)) if m else (None, None)


class Verdict(object):
    def __init__(self, kind, lines=None, server=None):
        self.kind, self.lines, self.server = kind, list(lines or []), server

    @property
    def covered(self):
        return self.kind == "covered"

    def text(self):
        return "\n".join([self.kind] + self.lines)


def preflight(connector, tools, *, accounts=(), cwd=None, home=None, config_dir=None,
              managed_path=None, profile=None, now=None, row=None):
    """One verdict, decided by script from the tool names the session holds and the settings sources
    the launch directory sees. See the module docstring for what `covered` means and does not."""
    now = now or utcnow()
    row = row if row is not None else row_for(connector)
    label = _row_get(row, "label", connector)
    read_tools = list(_row_get(row, "read_tools", []) or [])
    search_tool, body_tool = _row_get(row, "search_tool"), _row_get(row, "body_tool")
    held = {}
    for name in tools:
        server, tool = parse_tool_name(name)
        if server and tool in read_tools:
            held.setdefault(server, set()).add(tool)
    report = ("python3 scripts/report_issue.py --title \"mail connector %s: <what you saw>\" "
              "--symptom \"<the verdict line and the tool names>\" (tool names carry no personal "
              "data; or add --email if you have no GitHub account)" % connector)
    if not held:
        return Verdict("CONNECTOR ABSENT", [
            "none of %s's read tools (%s) are in this session. Documented reasons: no claude.ai "
            "login (an API key, apiKeyHelper, Bedrock, Vertex or a setup-token session gets no "
            "connectors), a desktop WSL session, or the connector is not connected." %
            (label, ", ".join(read_tools))])
    with_search = sorted(s for s, t in held.items() if search_tool in t)
    if not with_search:
        return Verdict("CONTRACT MISMATCH", [
            "expected %s (search) and %s (body); held: %s" % (
                search_tool, body_tool,
                "; ".join("%s: %s" % (s, ", ".join(sorted(t))) for s, t in sorted(held.items()))),
            "report it: %s" % report])
    if len(with_search) > 1:
        return Verdict("CONNECTOR AMBIGUOUS", [
            "more than one server holds %s: %s. Say which mailbox's connector this profile uses."
            % (search_tool, ", ".join(with_search))])
    server = with_search[0]
    if body_tool not in held[server]:
        return Verdict("CONTRACT MISMATCH", [
            "server %s holds %s but not %s (body); held: %s" % (
                server, search_tool, body_tool, ", ".join(sorted(held[server]))),
            "report it: %s" % report], server)
    # from here a bundle will be written: where, and is that allowed?
    try:
        cdir = connector_dir(connector, profile)
    except BundleError as exc:
        return Verdict("NOT COVERED: no bundle location", [str(exc)], server)
    settings = read_settings(settings_sources(cwd, home, config_dir, managed_path))
    for lbl, path, data in settings:
        if data is None:
            kind = ("NOT COVERED: managed settings unreadable" if lbl == "managed"
                    else "NOT COVERED: settings unreadable")
            return Verdict(kind, ["%s settings at %s exist but are not a readable JSON object"
                                  % (lbl, path)], server)
    allow, deny, ask = _rules(settings, "allow"), _rules(settings, "deny"), _rules(settings, "ask")
    needed = sorted(held[server])
    missing, blocked = [], []
    for tool in needed:
        if any(_mcp_rule_matches(r, server, tool) for r in deny + ask):
            blocked.append("mcp__%s__%s" % (server, tool))
        elif not any(_mcp_rule_matches(r, server, tool) for r in allow):
            missing.append("mcp__%s__%s" % (server, tool))
    target = os.path.join(cdir, "incoming", "x.jsonl")
    targets = {target, os.path.join(os.path.realpath(cdir), "incoming", "x.jsonl")}
    write_blocked = any(_edit_rule_matches(r, t) for r in deny + ask for t in targets)
    write_ok = (not write_blocked) and (
        any(_edit_rule_matches(r, t) for r in allow for t in targets)
        or (_default_mode(settings) == "acceptEdits"
            and _under(target, cwd or os.getcwd())))
    problems = list(blocked)
    if write_blocked:
        problems.append("Edit(%s/**) is denied or asks" % cdir)
    grant_rule = "Edit(//%s/**)" % os.path.realpath(cdir).lstrip("/")
    prior = _read_server_state(cdir)
    lines_missing = []
    if missing:
        lines_missing.append("a read tool is not covered by an allow rule: %s" % ", ".join(missing))
    if not write_ok and not write_blocked:
        lines_missing.append("the bundle write is not covered by an Edit(//...) allow rule "
                             "(a Write(...) rule never matches)")
    advice = []
    if missing:
        advice.append("add to permissions.allow: mcp__%s" % server)
    if not write_ok and not write_blocked:
        advice.append("add to permissions.allow: %s  (or run with defaultMode acceptEdits from the "
                      "profile directory)" % grant_rule)
    if problems:
        return Verdict("NOT COVERED: grant needed", [
            "denied or asking, so a prompt would stall an unattended run: %s" % "; ".join(problems),
            "remove it from permissions.deny / permissions.ask, or skip this connector"], server)
    if missing or not write_ok:
        if prior and prior != server:
            _write_server_state(cdir, server)
            return Verdict("SERVER NAME CHANGED (%s -> %s)" % (prior, server), [
                "the connector's server was named %s when this last ran; allow rules written for "
                "that name no longer match" % prior] + advice + ["report it: %s" % report], server)
        return Verdict("NOT COVERED: grant needed", lines_missing + advice, server)
    changed = prior and prior != server
    _write_server_state(cdir, server)
    lines = ["server: %s" % server,
             "fetch bound: at most %d search pages and %d minutes per account; stop and ingest what "
             "you hold" % (FETCH_MAX_PAGES, FETCH_MAX_MINUTES)]
    if changed:
        lines.insert(0, "server name changed (%s -> %s) but this server is already covered"
                     % (prior, server))
    return Verdict("covered", lines, server)


def _state_path(cdir):
    return os.path.join(cdir, "server.json")


def _read_server_state(cdir):
    try:
        with open(_state_path(cdir), encoding="utf-8") as fh:
            v = json.load(fh).get("server")
        return v if isinstance(v, str) else None
    except (OSError, ValueError, AttributeError):
        return None


def _write_server_state(cdir, server):
    try:
        _atomic.write_text(_state_path(cdir), json.dumps({"server": server}) + "\n")
    except OSError:
        pass


def stale_lines(connector, accounts, now=None, profile=None):
    """`!! BUNDLE STALE` for each account whose kept bundle's window ended more than the stale
    threshold ago -- announced on the next run (section 14 M2)."""
    now = now or utcnow()
    out = []
    for a in accounts:
        try:
            b = kept_or_none(connector, a, accounts, now, profile)
        except BundleError:
            continue
        if b is not None and b.stale(now):
            out.append("!! BUNDLE STALE: %s last fetched through %s (more than %d hours ago)"
                       % (a, iso_z(b.window_through), CONNECTOR_BUNDLE_STALE_HOURS))
    return out


# --------------------------------------------------------------------------
# plan
# --------------------------------------------------------------------------

def plan_window(recs, account, now):
    """(from, through) as aware UTC: back to the ledger's `covered_through`, capped at the connector
    backfill depth; through is now."""
    through = now
    floor = now - _dt.timedelta(days=_mc.CONNECTOR_BACKFILL_MAX_DAYS)
    cov = _journal.covered_through(recs, account)
    if cov:
        try:
            frm = from_local_naive(_dt.datetime.fromisoformat(cov))
        except ValueError:
            frm = floor
        return max(frm, floor), through
    return floor, through


def plan_lines(connector, server, accounts, now=None, recs=None, profile=None, row=None):
    now = now or utcnow()
    row = row if row is not None else row_for(connector)
    recs = recs if recs is not None else _journal.read(profile or _root.profile_root())
    out = []
    for account in accounts:
        frm, through = plan_window(recs, account, now)
        kept = kept_or_none(connector, account, accounts, now, profile)
        same_day = (kept is not None and kept.exhausted
                    and to_local_naive(kept.fetched_at).date() == to_local_naive(now).date()
                    and kept.window_from <= frm)
        out.append("account: %s" % account)
        out.append("  connector: %s (%s), server: %s" % (connector, _row_get(row, "label", connector), server))
        out.append("  window: %s .. %s" % (iso_z(frm), iso_z(through)))
        out.append("  phase: headers")
        out.append("  read tools: search %s, body %s (all: %s)" % (
            _row_get(row, "search_tool"), _row_get(row, "body_tool"),
            ", ".join(_row_get(row, "read_tools", []) or [])))
        out.append("  write the bundle to: %s" % os.path.join(
            incoming_dir(connector, profile), _safe_account(account) + ".jsonl"))
        out.append("  fetch: %s" % ("none (a bundle from today already covers the window and is "
                                    "exhausted)" if same_day else
                                    "every message in the window, inbox and sent; stop after %d "
                                    "pages or %d minutes and ingest what you hold"
                                    % (FETCH_MAX_PAGES, FETCH_MAX_MINUTES)))
    return out


# --------------------------------------------------------------------------
# status, query
# --------------------------------------------------------------------------

def status_lines(connector, accounts, now=None, profile=None):
    now = now or utcnow()
    out = []
    for a in accounts:
        try:
            b = kept_or_none(connector, a, accounts, now, profile)
        except BundleError as exc:
            out.append("%s: %s" % (a, exc))
            continue
        if b is None:
            out.append("%s: no bundle (nothing fetched and ingested)" % a)
            continue
        age_h = max(0, int(b.age(now).total_seconds() // 3600))
        out.append("%s: window %s..%s, %s, %dh ago%s; %d record(s), %d body/bodies fetched%s" % (
            a, iso_z(b.window_from), iso_z(b.window_through),
            "exhausted" if b.exhausted else "NOT exhausted", age_h,
            " (STALE)" if b.stale(now) else "", len(b.records), b.bodies_fetched,
            "; capped from %d" % b.capped if b.capped else ""))
    return out


def run_query(connector, account, query, accounts, now=None, profile=None):
    """(matches, unknown) over the kept bundle: what a model-run query (check_followups' bounce
    query) is answered from."""
    now = now or utcnow()
    b = load_kept(connector, account, accounts, now, profile)
    matches, unknown = [], []
    for rec in b.records:
        v = _mq.evaluate(query, rec, now)
        if v is True:
            matches.append(rec)
        elif v is None:
            unknown.append(rec)
    return b, matches, unknown


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _accounts(args):
    accts = _mc.configured_accounts()
    if getattr(args, "account", None):
        if args.account.lower() not in {a.lower() for a in accts}:
            raise BundleError("%s is not a declared address of this profile" % args.account)
        return [args.account]
    return accts


def _selected():
    connector = _mc.selected_connector()
    if connector == _mc.GMAIL_MULTI:
        return None
    return connector


def main(argv=None):
    ap = argparse.ArgumentParser(description="Ingest mail fetched through a claude.ai connector.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("preflight")
    p.add_argument("--tools", nargs="*", default=[], help="full mcp__<server>__<tool> names")
    p = sub.add_parser("plan")
    p.add_argument("--server", required=True)
    p.add_argument("--account")
    p = sub.add_parser("ingest")
    p.add_argument("--account", required=True)
    p = sub.add_parser("needs-body")
    p.add_argument("--account", required=True)
    p.add_argument("--query", action="append", default=[], help="an extra query to plan bodies for")
    p = sub.add_parser("query")
    p.add_argument("--account", required=True)
    p.add_argument("--query", required=True)
    sub.add_parser("status")
    args = ap.parse_args(argv)
    try:
        connector = _selected()
    except ValueError as exc:
        print("MAIL CONNECTOR UNREADABLE: %s" % exc)
        return 2
    if connector is None:
        if args.cmd == "ingest":
            print("MAIL BUNDLE REFUSED (gmail-multi) line 0: the selected connector is gmail-multi, "
                  "which reads mail itself; there is nothing to ingest")
            return 2
        print("not applicable: the selected mail connector is gmail-multi (no bundle is used)")
        return 0
    try:
        accounts = _accounts(args)
        if args.cmd == "preflight":
            v = preflight(connector, args.tools, accounts=accounts)
            print(v.text())
            for line in stale_lines(connector, accounts):
                print(line)
            return 0 if v.covered else 1
        if args.cmd == "plan":
            print("\n".join(plan_lines(connector, args.server, accounts)))
            return 0
        if args.cmd == "ingest":
            print(ingest(connector, accounts[0], _mc.configured_accounts()))
            return 0
        if args.cmd == "needs-body":
            b = load_kept(connector, accounts[0], accounts)
            qs = consumer_queries() + [("extra", q) for q in args.query]
            for rec, who in needs_body(b, qs):
                print("%s\t%d\t%s" % (rec.get("message_id") or rec["provider_id"], len(who), ",".join(who)))
            return 0
        if args.cmd == "query":
            b, matches, unknown = run_query(connector, accounts[0], args.query,
                                            _mc.configured_accounts())
            for r in matches:
                print("%s | %s | %s" % (r["date"], r["from"]["email"], r["subject"]))
            print("matched %d, unknown %d (body not fetched), window %s..%s%s" % (
                len(matches), len(unknown), iso_z(b.window_from), iso_z(b.window_through),
                "" if b.exhausted else ", NOT exhausted"))
            return 0
        if args.cmd == "status":
            print("\n".join(status_lines(connector, accounts)))
            return 0
    except _mq.QueryUnsupported as exc:
        print("QUERY UNSUPPORTED: %s" % exc)
        return 2
    except (BundleError, _mc.ConnectorNotSelected) as exc:
        print(str(exc))
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
