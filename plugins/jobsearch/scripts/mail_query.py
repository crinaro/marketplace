#!/usr/bin/env python3
"""
The Gmail-search subset the six mail consumers write, evaluated over a normalised record --
THREE-VALUED, pure standard library (docs/design-mail-any-connector.md section 4.2, dev #799).

WHY THIS EXISTS
---------------
Under gmail-multi a consumer's query goes to Gmail itself (`X-GM-RAW`) and Gmail answers. Under a
claude.ai connector the model fetches a window of messages into a bundle and a SCRIPT must answer
the same questions over it. This file is that answer, and it answers honestly: every evaluation
returns TRUE, FALSE or UNKNOWN (`None`), and UNKNOWN is never turned into a miss.

    evaluate(query, record, now=None) -> True | False | None
    parse(query)                      -> a tree; raises QueryUnsupported

GRAMMAR (the consumers' own, one table)
---------------------------------------
    query   := or_expr
    or_expr := and_expr ("OR" and_expr)*
    and_expr:= unary (["AND"] unary)*            implicit AND by juxtaposition
    unary   := "-" unary | atom
    atom    := "(" or_expr ")" | field ":" fval | phrase | word
    field   := from | to | cc | subject | in | newer_than | older_than | after | before | filename
    fval    := "(" or_expr ")" | phrase | word   field:(A OR B) distributes the field over the group

`OR` and `AND` are operators only in upper case (Gmail's own rule: a lower-case `or` is a search
word). `in:` takes `inbox`, `sent` or `anywhere`. `newer_than`/`older_than` take `Nd`;
`after`/`before` take `YYYY/MM/DD`. Anything else -- a label, `has:`, `{a b}`, `AROUND` -- raises
`QueryUnsupported`, never a silent guess: a query this file cannot answer must stop the caller.

THE THREE VALUES
----------------
A record carries `null` for what was NOT FETCHED (a body, an attachment list, the folders). A
term over a null field is UNKNOWN, never false. `needs-body` in `mail_ingest.py` is the consumer
of exactly that distinction: it lists the messages whose answer a body fetch could change.

    and: any FALSE -> FALSE; else any UNKNOWN -> UNKNOWN; else TRUE
    or : any TRUE  -> TRUE ; else any UNKNOWN -> UNKNOWN; else FALSE
    not: UNKNOWN stays UNKNOWN -- so a negated approximation can never narrow a result silently

WORD AGAINST SUBSTRING (OURS: Gmail's own matching is not published)
---------------------------------------------------------------------
For each text term (on `from:`, `to:`, `cc:`, `subject:`, `filename:` and bare words) the evaluator
computes BOTH a word-token match (the term's tokens appear contiguously among the field's tokens)
and a casefolded substring match. When they agree that is the value; when they disagree
(`from:ladders` against a sender at theladders.example.com) the value is UNKNOWN. One exception, taken from the
Gmail help page: a domain or address term (`from:calendly.com`) on `from:`/`to:`/`cc:` is an
address SUBSTRING and nothing else.

DATES
-----
`newer_than:Nd` is a timestamp comparison against `now`. `after:`/`before:` name a calendar day
whose midnight Gmail takes in the ACCOUNT's timezone, which this file does not know: a record
within `_DAY_AMBIGUITY` of the boundary is UNKNOWN rather than guessed.
"""

import datetime as _dt
import functools
import re

# A record whose timestamp lies within this of an `after:`/`before:` day boundary is UNKNOWN: the
# day's midnight is taken in the account's own timezone (UTC-12 .. UTC+14).
_DAY_AMBIGUITY = _dt.timedelta(hours=14)

FIELDS = ("from", "to", "cc", "subject", "in", "newer_than", "older_than", "after", "before",
          "filename")
_TEXT_FIELDS = ("from", "to", "cc", "subject", "filename")
_IN_VALUES = ("inbox", "sent", "anywhere")

_NDAYS_RE = re.compile(r"^(\d+)d$")
_DAY_RE = re.compile(r"^(\d{4})[/-](\d{2})[/-](\d{2})$")
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


class QueryUnsupported(ValueError):
    """The query uses syntax this evaluator does not implement. Loud by design (never a guess)."""


# --------------------------------------------------------------------------
# Tokenizer and parser
# --------------------------------------------------------------------------

def _tokenize(query):
    """[(kind, a, b), ...]: LP RP OR AND NOT PHRASE(text) WORD(text) FIELD(name) FTERM(name, value)."""
    out, i, n = [], 0, len(query)
    while i < n:
        c = query[i]
        if c.isspace():
            i += 1
        elif c == "(":
            out.append(("LP", None, None))
            i += 1
        elif c == ")":
            out.append(("RP", None, None))
            i += 1
        elif c == '"':
            j = query.find('"', i + 1)
            if j < 0:
                raise QueryUnsupported("unterminated quote in %r" % query)
            out.append(("PHRASE", query[i + 1:j], None))
            i = j + 1
        elif c == "-" and i + 1 < n and not query[i + 1].isspace() and query[i + 1] != ")":
            out.append(("NOT", None, None))
            i += 1
        elif c in "{}":
            raise QueryUnsupported("braces ({a b}) are not supported in %r" % query)
        else:
            j = i
            while j < n and not query[j].isspace() and query[j] not in '()"':
                j += 1
            word = query[i:j]
            i = j
            if word == "AROUND":
                raise QueryUnsupported("AROUND (proximity) is not supported in %r" % query)
            if word == "OR":
                out.append(("OR", None, None))
            elif word == "AND":
                out.append(("AND", None, None))
            elif ":" in word:
                name, _, value = word.partition(":")
                name = name.lower()
                if name not in FIELDS:
                    raise QueryUnsupported("unsupported operator %r in %r" % (name + ":", query))
                if value:
                    out.append(("FTERM", name, value))
                else:
                    out.append(("FIELD", name, None))
            else:
                out.append(("WORD", word, None))
    return out


class _Parser(object):
    def __init__(self, tokens, query):
        self.t, self.i, self.query = tokens, 0, query

    def peek(self):
        return self.t[self.i][0] if self.i < len(self.t) else None

    def take(self):
        tok = self.t[self.i]
        self.i += 1
        return tok

    def parse(self):
        if not self.t:
            raise QueryUnsupported("empty query")
        node = self.or_expr()
        if self.i != len(self.t):
            raise QueryUnsupported("unbalanced parenthesis in %r" % self.query)
        return node

    def or_expr(self):
        parts = [self.and_expr()]
        while self.peek() == "OR":
            self.take()
            parts.append(self.and_expr())
        return parts[0] if len(parts) == 1 else ("or", parts)

    def and_expr(self):
        parts = [self.unary()]
        while self.peek() not in (None, "OR", "RP"):
            if self.peek() == "AND":
                self.take()
            parts.append(self.unary())
        return parts[0] if len(parts) == 1 else ("and", parts)

    def unary(self):
        if self.peek() == "NOT":
            self.take()
            return ("not", self.unary())
        return self.atom()

    def atom(self):
        kind = self.peek()
        if kind == "LP":
            self.take()
            node = self.or_expr()
            if self.peek() != "RP":
                raise QueryUnsupported("unbalanced parenthesis in %r" % self.query)
            self.take()
            return node
        if kind == "FIELD":
            _k, name, _ = self.take()
            nxt = self.peek()
            if nxt == "LP":
                self.take()
                inner = self.or_expr()
                if self.peek() != "RP":
                    raise QueryUnsupported("unbalanced parenthesis in %r" % self.query)
                self.take()
                return _distribute(name, inner, self.query)
            if nxt == "PHRASE":
                _k, text, _ = self.take()
                return _term(name, text, True, self.query)
            raise QueryUnsupported("%s: has no value in %r" % (name, self.query))
        if kind == "FTERM":
            _k, name, value = self.take()
            return _term(name, value, False, self.query)
        if kind == "PHRASE":
            _k, text, _ = self.take()
            return _term(None, text, True, self.query)
        if kind == "WORD":
            _k, text, _ = self.take()
            return _term(None, text, False, self.query)
        raise QueryUnsupported("unexpected %s in %r" % (kind or "end of query", self.query))


def _term(field, text, is_phrase, query):
    if field in ("newer_than", "older_than"):
        m = _NDAYS_RE.match(text)
        if not m:
            raise QueryUnsupported("%s: takes Nd (days), got %r in %r" % (field, text, query))
        return ("age", field, int(m.group(1)))
    if field in ("after", "before"):
        m = _DAY_RE.match(text)
        if not m:
            raise QueryUnsupported("%s: takes YYYY/MM/DD, got %r in %r" % (field, text, query))
        try:
            day = _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            raise QueryUnsupported("%s: %r is not a calendar day in %r" % (field, text, query))
        return ("day", field, day)
    if field == "in":
        if text.lower() not in _IN_VALUES:
            raise QueryUnsupported("in:%s is not supported (inbox, sent, anywhere) in %r"
                                   % (text, query))
        return ("in", text.lower())
    if not _TOKEN_RE.findall(text):
        raise QueryUnsupported("a term with no letters or digits (%r) in %r" % (text, query))
    return ("text", field, text, bool(is_phrase))


def _distribute(field, node, query):
    """`field:(A OR B)`: apply `field` to every bare term inside the group."""
    kind = node[0]
    if kind in ("and", "or"):
        return (kind, [_distribute(field, n, query) for n in node[1]])
    if kind == "not":
        return ("not", _distribute(field, node[1], query))
    if kind == "text":
        if node[1] is not None:
            raise QueryUnsupported("a field inside %s:(...) in %r" % (field, query))
        return _term(field, node[2], node[3], query)
    raise QueryUnsupported("a field inside %s:(...) in %r" % (field, query))


@functools.lru_cache(maxsize=512)
def parse(query):
    """The parse tree of `query`, or `QueryUnsupported`."""
    if not isinstance(query, str):
        raise QueryUnsupported("a query is a string, got %r" % (query,))
    return _Parser(_tokenize(query), query).parse()


# --------------------------------------------------------------------------
# Evaluation (three-valued)
# --------------------------------------------------------------------------

def _and(values):
    if any(v is False for v in values):
        return False
    return None if any(v is None for v in values) else True


def _or(values):
    if any(v is True for v in values):
        return True
    return None if any(v is None for v in values) else False


def _tokens(text):
    return _TOKEN_RE.findall(text.casefold())


def _contiguous(needle, hay):
    n = len(needle)
    return bool(n) and any(hay[i:i + n] == needle for i in range(len(hay) - n + 1))


def _match_text(text, term, address_only=False):
    """True / False / None for one term against one string."""
    sub = term.casefold() in text.casefold()
    if address_only:
        return sub
    word = _contiguous(_tokens(term), _tokens(text))
    return sub if word == sub else None


def _addr_text(people):
    """One string from a list of {name, email}; None when the list was not fetched."""
    if people is None:
        return None
    return " ".join("%s %s" % (p.get("name") or "", p.get("email") or "") for p in people)


def _is_address_term(term):
    return "@" in term or bool(re.search(r"[0-9a-z]\.[0-9a-z]", term, re.I))


def _record_date(record):
    raw = record.get("date")
    if not isinstance(raw, str):
        return None
    try:
        d = _dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        return None
    return d


def _eval_text(field, term, record):
    if field == "from":
        frm = record.get("from")
        text = None if frm is None else "%s %s" % (frm.get("name") or "", frm.get("email") or "")
        return None if text is None else _match_text(text, term, _is_address_term(term))
    if field in ("to", "cc"):
        text = _addr_text(record.get(field))
        return None if text is None else _match_text(text, term, _is_address_term(term))
    if field == "subject":
        subject = record.get("subject")
        return None if subject is None else _match_text(subject, term)
    if field == "filename":
        atts = record.get("attachments")
        if atts is None:
            return None
        return _or([_match_text(a.get("filename") or "", term) for a in atts] or [False])
    # a bare word or phrase: anywhere in the message text we hold
    seen_hit, seen_unknown = False, False
    for text in (record.get("subject"), _addr_text([record["from"]]) if record.get("from") else None,
                 _addr_text(record.get("to")), _addr_text(record.get("cc"))):
        if text is None:
            continue
        v = _match_text(text, term)
        seen_hit = seen_hit or v is True
        seen_unknown = seen_unknown or v is None
    for text in (record.get("preview"), record.get("body_text")):
        if text is not None:
            v = _match_text(text, term)
            seen_hit = seen_hit or v is True
            seen_unknown = seen_unknown or v is None
    if seen_hit:
        return True
    # a miss in a preview snippet proves nothing about the body; a body never fetched is unknown
    if seen_unknown or record.get("body_text") is None:
        return None
    return False


def _eval(node, record, now):
    kind = node[0]
    if kind == "and":
        return _and([_eval(n, record, now) for n in node[1]])
    if kind == "or":
        return _or([_eval(n, record, now) for n in node[1]])
    if kind == "not":
        v = _eval(node[1], record, now)
        return None if v is None else (not v)
    if kind == "text":
        return _eval_text(node[1], node[2], record)
    if kind == "in":
        if node[1] == "anywhere":
            return True
        folders = record.get("folders")
        return None if folders is None else (node[1] in folders)
    d = _record_date(record)
    if d is None:
        return None
    if kind == "age":
        cutoff = now - _dt.timedelta(days=node[2])
        return d >= cutoff if node[1] == "newer_than" else d < cutoff
    if kind == "day":
        boundary = _dt.datetime(node[2].year, node[2].month, node[2].day, tzinfo=_dt.timezone.utc)
        if abs(d - boundary) < _DAY_AMBIGUITY:
            return None
        return d >= boundary if node[1] == "after" else d < boundary
    raise QueryUnsupported("internal: unknown node %r" % (kind,))


def evaluate(query, record, now=None):
    """True, False or None (unknown) for `query` over one normalised `record`. `now` is an aware
    datetime (default: the current UTC time). Raises `QueryUnsupported` for a query this file does
    not implement."""
    tree = parse(query) if isinstance(query, str) else query
    if now is None:
        now = _dt.datetime.now(_dt.timezone.utc)
    return _eval(tree, record, now)


def needs_body(query, record, now=None):
    """True when `query` is UNKNOWN for `record` only because something was not fetched (a body, an
    attachment list): the unknowns a body fetch could settle. A record whose body AND attachments
    are already present can never answer True here."""
    if record.get("body_text") is not None and record.get("attachments") is not None:
        return False
    return evaluate(query, record, now) is None
