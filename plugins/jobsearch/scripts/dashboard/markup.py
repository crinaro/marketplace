"""Markup helpers every renderer shares (dashboard-redesign A, moved from generate_dashboard.py): escaping,
`plain()` (the page carries no command), the `data-theirs` wrappers and their closed `THEIRS_SITES`, inline
markdown, and the primary-row and reference attributes (`rec_id`, `links_for`)."""
import hashlib
import html
import re


def esc(s: str) -> str:
    return html.escape(s, quote=False)


# ─────────────────────────────────────────────────────────────────────────────
# jobsearch 0.88.0 (dev #915, design 7.1-7.2): THE PAGE CARRIES NO COMMAND.
#
# `plain(text)` is the ONE choke point for ENGINE text written for the engine (a `record.py ...` hint, a
# `plays.py --check` pointer): each CLI span becomes plain words, a verb in `PLAIN_VERBS` its own phrase and anything
# else "ask Claude to ...". `THEIRS_SITES` is the closed list of spans the renderer did NOT author (the candidate's own
# role titles, names, draft bodies, snippets): `theirs()` wraps each in `data-theirs`, which check_dashboard_coverage's
# NO CLI gate does not scan, so a draft that says "python3" never turns the page red. An action is a copy-as-prompt
# BLOCK (`dashboard_actions.block`), never a command.
# ─────────────────────────────────────────────────────────────────────────────
THEIRS_SITES = ("kdoc-body", "role-title", "company-name", "person-name", "jd-detail", "fit-detail",
                "message-snippet")


PLAIN_VERBS = {
    "company-status": "answer it in your session", "decide": "tell Claude your decision",
    "screened": "tell Claude you have screened it", "read-jd": "tell Claude you read the posting yourself",
    "attended": "tell Claude whether the chat happened", "chat": "tell Claude about the chat",
    "confirm": "tell Claude yes", "decline": "tell Claude no", "proposal-status": "tell Claude it was sent",
    "touch": "tell Claude you sent it",
}


_CLI_SPAN_RE = re.compile(
    r"`?(?:~/\.claude/jobsearch/run\s+)?(?:python3\s+)?(?:scripts/)?\b([a-z_][a-z0-9_]*)\.py\b"
    r"(?:\s+([a-z][a-z-]*))?"
    r"((?:\s+(?:--?[a-z][\w-]*(?:\s+(?!(?:and|or|then|to|for|the|a|on|in|is|if|but|so)\b)[\w:.-]+)?"
    r"|<[^>]*>|\[[^\]]*\]|%s|[\w.:-]*[-\d_:][\w.:-]*))*)`?")


def plain(text):
    """Engine text with every CLI span turned into plain words (see the banner above). Never raises."""
    def _one(m):
        name, verb, flags = m.group(1), m.group(2), m.group(3) or ""
        if name == "record":
            return PLAIN_VERBS.get(verb or "", "ask Claude to record this")
        if "check" in flags or "audit" in flags or verb in ("check", "audit"):
            return "ask Claude to check this"
        return "ask Claude to run this"
    out = _CLI_SPAN_RE.sub(_one, str(text))
    out = re.sub(r"~/\.claude/jobsearch/run", "the plugin", out)
    return re.sub(r"\bpython3\b", "Claude", out)


def theirs(text, site):
    """`text` escaped and wrapped in `data-theirs="<site>"`: the candidate's own words, which the NO CLI gate skips.
    `site` must be one of `THEIRS_SITES` (a closed tuple, so the exclusion cannot grow by accident)."""
    if site not in THEIRS_SITES:
        raise ValueError("unknown data-theirs site %r" % site)
    return '<span data-theirs="%s">%s</span>' % (site, esc(str(text)))


def theirs_html(fragment, site):
    """An already-escaped fragment (a `md_inline` result) wrapped as the candidate's own words (`THEIRS_SITES`)."""
    if site not in THEIRS_SITES:
        raise ValueError("unknown data-theirs site %r" % site)
    return '<span data-theirs="%s">%s</span>' % (site, fragment)


def md_inline(s: str) -> str:
    """Escape, then apply **bold**, `code`, and [text](target) links.

    Link support added 2026-07-20 — focus entries routinely reference local files
    like [call_preps/call_prep_2026-08-05.md](call_preps/call_prep_2026-08-05.md)
    and those were rendering as literal markdown on the dashboard. (The original
    example, call_prep_acme.md, was promoted to kb/acme.md on 2026-08-03.)"""
    s = esc(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)

    def _link(m):
        text, target = m.group(1), m.group(2)
        if target.startswith(("http://", "https://")):
            return ('<a href="%s" target="_blank" rel="noopener noreferrer">%s</a>'
                    % (target, text))
        # Local repo file (call_prep_*.md, log.md, ...): no useful href from a
        # published artifact, so render as a filename chip rather than a dead link.
        return '<code class="fileref">%s</code>' % text
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _link, s)
    return s


# ─────────────────────────────────────────────────────────────────────────────
# ⭐ ONE PRIMARY ROW PER RECORD, AND A LINK TO IT (dev #496 / public #48, dev #540 / public
# #132, design-one-dashboard-surface.md r3 §2). A record has ONE primary row, in its kind's one
# list: it carries `data-rec="<kind>:<id>"` and `id="rec-<h>"`. Anywhere else the record is
# mentioned, the mention is a REFERENCE row: `data-ref="<kind>:<id>"` plus an `<a href=
# "#rec-<h>">` to the primary. `check_dashboard_coverage.py` refuses a second `data-rec` for
# one key (EXACTLY ONCE), a `data-ref` whose primary is not on the page (LINKED) and any
# `href="#x"` with no `id="x"` (ANCHOR). `<h>` is the first 12 hex digits of sha1(key): a draft
# title has spaces and is not unique, so it cannot be the id (design D5), and the same key
# (see `your_move.entry_keys`) is the ledger's, `data-rec`'s, the id's and every `data-ref`'s.
# ─────────────────────────────────────────────────────────────────────────────

def rec_id(key: str) -> str:
    """The HTML id of the primary row for `key` (`opp:x`, `draft:Title#2`, ...)."""
    return "rec-" + hashlib.sha1(str(key).encode("utf-8")).hexdigest()[:12]


def links_for(key: str) -> str:
    """ADR-024's LINKED side, named in r2 §4 and built here: the in-page href of a record's
    primary row. The row's `:target` reveal rule (`.flist [data-rec]:target`) makes the link
    land even when the row's own filter would hide it."""
    return "#" + rec_id(key)


def _rec_attrs(key: str) -> str:
    """` id="rec-…" data-rec="…"` - the primary row's attributes, id FIRST so the checker's
    `data-rec="…" data-full="1"` pairing is untouched."""
    return ' id="%s" data-rec="%s"' % (rec_id(key), esc(key))


def _ref_attrs(key: str) -> str:
    return ' data-ref="%s"' % esc(key)


def _ref_link(key: str, text: str = "the full row ↓") -> str:
    return '<a class="ref" href="%s">%s</a>' % (links_for(key), esc(text))
