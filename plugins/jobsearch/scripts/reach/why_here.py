"""why_here: the line that says WHY a role is on the page, from facts the role already stores (jobsearch 0.94.0, step P6; dev 1062, 1065;
docs/design-role-first.md 4.5, RF8).

    Head of Widgets matches "Head of Widgets" · 300-350K stated, remote floor 250K · remote (stated) · posted 2 days ago · employer posting: not checked

Five clauses, in this order: the title against the owner's target titles, the pay against the floor that applies, the setting, the posting's
age, and whether the employer's own posting was checked. EVERY clause has a known text and an unknown text, and the unknown is SAID, never
filled in: `pay not stated` (the listing showed none), `pay not read` (nothing was ever recorded), `setting not stated`, `posted date not
shown`, `employer posting: not checked | live <date> | closed | could not confirm`. Nothing is stored, and nothing is inferred to close a gap:
a pay is printed only when the row holds one, a floor only when the profile's own `resolve_floor` names it, an age only from a stored date.
The pay's basis is the pay's own source (`stated` by the employer, a board's `estimate`, `yours` when the candidate wrote it, `recorded` for the
older `comp` object, whose source nobody stored).

  `short(opp, ctx, today, posting)`  the line on an OPEN card, at most `SHORT_WORDS` (14) words: `title · 300-350K stated ≥ 250K · remote ·
                                     2 days · not checked`. A WORD is a whitespace-separated token with a letter or a digit in it, so the
                                     separators and comparison signs are not words (`words()`); the example above is 9 of them. The page has
                                     one open word to spare (the budget test), so on the card it REPLACES the pay-and-place meta line and the
                                     posting line.
  `full(opp, ctx, today, posting)`   the line above, for the card's closed detail and `your_move`'s decide rows. `text` wraps the engine's own
                                     words and `theirs` the role's and the target's (the page passes `esc` and the `data-theirs` wrapper).
  `context(profile, pf, ck)`         the owner's criteria as one object: the target titles, the floor of a role and the currency. The profile
                                     module `pf` and `config_keys` `ck` are HANDED IN by an entry point (a package imports none, G5).

`posting` is the optional `your_move.posting_labels` entry `{"code", ...}` of the role: it only says that a confirmed posting has gone stale.
Pure: no I/O, no clock (`today` is a date passed in). Python 3.9+, standard library only."""

import datetime
from typing import Callable, NamedTuple, Optional, Tuple

SHORT_WORDS = 14
SEP = " · "
NOT_CHECKED = "criteria not checked"
_KNOWN_SETTINGS = ("remote", "hybrid", "onsite", "relocation")
_BASIS = {"employer-stated": "stated", "board-estimate": "estimate"}


class Ctx(NamedTuple):
    """The owner's criteria, as the clauses need them. `titles` the configured target titles (empty: none configured), `matches(title)` the
    profile's own answer (True, False, None for cannot-say), `target(title)` the target title it matches, `floor(opp)` `(setting, floor)` or
    None, `currency` the profile's code (None: unset)."""
    titles: Tuple[str, ...]
    matches: Callable
    target: Callable
    floor: Callable
    currency: Optional[str]


def context(profile, pf, ck):
    """The `Ctx` of one profile. `pf` is the `profile` module (`title_matches`, `_matching_target`, `resolve_floor`, `tiers`), `ck` is
    `config_keys` (`resolve_currency`); an entry point hands them in. A profile that is not a mapping gives a context that checks nothing."""
    prof = profile if isinstance(profile, dict) else {}
    tg = prof.get("targets") if isinstance(prof.get("targets"), dict) else {}
    titles = tuple(t for t in (tg.get("titles") or []) if isinstance(t, str) and t)
    try:
        currency = ck.resolve_currency(prof)
    except (ValueError, KeyError, TypeError, AttributeError):
        currency = None

    def matches(title):
        try:
            return pf.title_matches(title, prof)
        except (ValueError, KeyError, TypeError, AttributeError):
            return None

    def floor(opp):
        loc = opp.get("location") if isinstance(opp.get("location"), dict) else {}
        try:
            r = pf.resolve_floor(loc, prof)
            if r.get("hold") or not r.get("setting"):
                return None
            return r["setting"], (r["floor"] if r.get("floor") is not None else pf.tiers(prof)[r["setting"]]["floor"])
        except (ValueError, KeyError, TypeError, AttributeError):
            return None

    return Ctx(titles, matches, lambda title: pf._matching_target(title, list(titles)), floor, currency)


def words(line):
    """The words of a short line: the whitespace-separated tokens that hold a letter or a digit (never a `·` or a `≥`)."""
    return [w for w in line.split() if any(ch.isalnum() for ch in w)]


def _k(n):
    return ("%g" % (round(n / 1000.0, 1))) + "K"


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _span(lo, hi, year, code):
    """`300-350K`, `300K`, `300K+`, `up to 350K`; a figure not per year is printed whole with its unit by the caller."""
    f = _k if year else (lambda n: "%g" % n)
    if lo is not None and hi is not None:
        text = f(lo) if lo == hi else "%s-%s" % (f(lo).rstrip("K") if year else f(lo), f(hi))
    elif lo is not None:
        text = f(lo) + "+"
    else:
        text = "up to " + f(hi)
    return ("%s %s" % (code, text)) if code else text


def _pay(opp, ctx):
    """`(known, short, full)` for the pay clause. The comparison with the floor is made only for a yearly figure in the profile's own
    currency, on the top of the band (the screen's own rule); otherwise the figure stands alone."""
    comp, lp = opp.get("comp"), opp.get("listed_pay")
    figure = None
    if isinstance(comp, dict) and _num(comp.get("max")) is not None:
        period = comp.get("period")
        figure = (_num(comp.get("min")), comp["max"], period if isinstance(period, str) else "year", None, "recorded")
    elif isinstance(lp, dict) and lp.get("state") == "none-shown":
        return False, "pay not stated", "pay not stated"
    elif isinstance(lp, dict) and lp.get("state") in _BASIS and isinstance(lp.get("ranges"), list):
        rs = [r for r in lp["ranges"] if isinstance(r, dict) and (_num(r.get("min")) is not None or _num(r.get("max")) is not None)]
        if len(rs) != 1:
            return (bool(rs),) + (("pay by place", "pay listed by place") if rs else ("pay not read", "pay not read"))
        r = rs[0]
        figure = (_num(r.get("min")), _num(r.get("max")), r.get("interval") or "year", str(r.get("currency") or "").upper() or None,
                  "yours" if lp.get("source") == "candidate" else _BASIS[lp["state"]])
    elif "comp" in opp and comp is None and not isinstance(lp, dict):
        return False, "pay not stated", "pay not stated"
    if figure is None:
        return False, "pay not read", "pay not read"
    lo, hi, interval, code, basis = figure
    year = interval == "year"
    same = code in (None, ctx.currency) if ctx.currency else code is None
    shown = _span(lo, hi, year, None if same else code)
    if not year:
        shown += "/" + str(interval)
    flo = ctx.floor(opp) if year and same else None
    top = hi if hi is not None else lo
    if flo is None or top is None or (hi is None and lo < flo[1]):
        return True, "%s %s" % (shown, basis), "%s %s" % (shown, basis)
    return True, "%s %s %s %s" % (shown, basis, "≥" if top >= flo[1] else "<", _k(flo[1])), "%s %s, %s floor %s" % (
        shown, basis, flo[0], _k(flo[1]))


def _place(opp):
    """`(known, short, full)` of the setting, from the stored `location` only: a stated type (`setting_source: inferred` and an anchor's own
    echo are NOT stated), with the place named for an onsite or hybrid role."""
    loc = opp.get("location") if isinstance(opp.get("location"), dict) else {}
    kind = loc.get("type")
    if kind == "unresolved":
        return False, "setting contested", "setting contested: the posting names more than one"
    if kind not in _KNOWN_SETTINGS or loc.get("anchor_echo"):
        return False, "setting not stated", "setting not stated"
    how = "inferred" if loc.get("setting_source") == "inferred" else "stated"
    where = loc.get("primary") if kind in ("onsite", "hybrid") and isinstance(loc.get("primary"), str) and loc.get("primary") else None
    return True, "%s%s" % (kind, " (inferred)" if how == "inferred" else ""), "%s%s (%s)" % (kind, ", " + where if where else "", how)


def _age(opp, today):
    """Whole days since the stored `posted.date`, or None: absent, `source` unknown, unreadable or in the future is unknown, never zero."""
    posted = opp.get("posted")
    if not isinstance(posted, dict) or posted.get("source") in (None, "unknown"):
        return None
    try:
        days = (today - datetime.date.fromisoformat(str(posted.get("date"))[:10])).days
    except ValueError:
        return None
    return days if days >= 0 else None


def _posted(opp, today):
    days = _age(opp, today)
    if days is None:
        return False, "no date", "posted date not shown"
    if days == 0:
        return True, "today", "posted today"
    return True, "%d day%s" % (days, "" if days == 1 else "s"), "posted %d day%s ago" % (days, "" if days == 1 else "s")


def _posting(opp, posting):
    """`(short, full)` of the employer-posting clause, from the stored `employer_posting` (and the label's code when it says a confirmed
    one has gone stale: a date alone would read as live)."""
    raw = opp.get("employer_posting")
    code = (posting or {}).get("code") if isinstance(posting, dict) else None
    if not isinstance(raw, dict) or raw.get("state") not in ("confirmed", "unconfirmed", "closed"):
        return "not checked", "not checked"
    day = str(raw.get("checked_on") or "")[:10]
    if raw["state"] == "closed":
        return "closed", "closed"
    if raw["state"] == "unconfirmed" or code in ("unconfirmed", "one-signal"):
        return "could not confirm", "could not confirm"
    if code == "not-checked":
        return "not checked", ("not checked since %s" % day) if day else "not checked"
    return "live", ("live %s" % day) if day else "live"


def _title(opp, ctx):
    """`(short, title, target)`: the title against the owner's target titles. No configured title, or a profile that cannot say, is
    `criteria not checked`: the engine never reads that as a match."""
    title = str(opp.get("title") or "this role")
    if not ctx.titles or ctx.matches(title) is None:
        return "no criteria", title, None
    hit = ctx.target(title) if ctx.matches(title) else None
    return ("title" if hit else "off title"), title, hit


def clauses(opp, ctx, today, posting=None):
    """`[(short, full)]`, the five clauses in order, for a role under `ctx` on `today`. The title's full text is built by `full`."""
    pay, place, posted, state = _pay(opp, ctx), _place(opp), _posted(opp, today), _posting(opp, posting)
    return [(_title(opp, ctx)[0], None), (pay[1], pay[2]), (place[1], place[2]), (posted[1], posted[2]),
            (state[0], "employer posting: %s" % state[1])]


def short(opp, ctx, today, posting=None):
    """The short form: at most `SHORT_WORDS` words by construction (each clause's longest short text is chosen so the five fit together;
    a test enumerates them), every unknown said."""
    return SEP.join(s for s, _f in clauses(opp, ctx, today, posting))


def full(opp, ctx, today, posting=None, text=str, theirs=str):
    """The full form (the module docstring). `text(s)` wraps the engine's own words, `theirs(s)` the role's title and the target's."""
    cs = clauses(opp, ctx, today, posting)
    kind, title, hit = _title(opp, ctx)
    if kind == "no criteria":
        head = theirs(title) + text(": " + NOT_CHECKED)
    elif hit:
        head = theirs(title) + text(' matches "') + theirs(hit) + text('"')
    else:
        head = theirs(title) + text(" matches none of your titles")
    return head + "".join(text(SEP + f) for _s, f in cs[1:])
