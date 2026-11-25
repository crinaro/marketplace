"""adoption.keycover -- what reads a piece key the plugin's build would not publish (design-movement-view section 6.1, dev #965).

Part of the `adoption` package behind the entry point `adopt.py`. The build warns about every piece key it does not publish
(`contentmodel/strays.py`: "front matter key 'K' is not published; ... add the key to meta or cardMeta, or remove it"). 0.4.2
counted a key as read only once `parity` had chosen the setting that reads it, so a key some view or setting of the plugin
reads was told to be removed. Here every such warning is sorted into one of three, from the code's own tables and nothing else
(`VIEW_PIECE_KEYS`, `V5_PIECE_KEYS`, the `pieceKeys` synonyms of `adoption.convert`):

  covered         the converted tree, with the plan's settings and every pending conversion applied, reads it. Not listed.
                  A pending conversion counts before parity has run (`summary`, which `pieceKeys` makes `teaser`).
  read elsewhere  a view or setting reads a key of that name, and this portfolio does not use it (`pin` under a roles
                  view, `role` in a plain grid). One note per key and portfolio (the build's own line, so its places group
                  as one cause), with both ways out, "list it in meta" and "set the view", and never "remove". It ends with
                  what parity knows about the site.
  unknown         no reader anywhere: the build's own warning stands.

Whether the old builder prints a key is parity's to say, on the page, for all three. The note keeps the build's wording as its
first half, so `waits_on_work_keys` and the blocker codes (`blockers.REFUSAL_CODES`) read it as they read the build's line.
"""

import re

from contentmodel.keytables import V5_PIECE_KEYS, VIEW_PIECE_KEYS
from contentmodel.strays import UNKNOWN_KEY_FIX, UNREAD_TAIL
from configschema import diagnostics

from adoption.convert import PIECE_KEY_SYNONYMS, TILE_KEY_SYNONYMS

COVERED, ELSEWHERE, UNKNOWN = "covered", "read elsewhere", "unknown"

# The names in `VIEW_PIECE_KEYS` and `V5_PIECE_KEYS` that are values of `view`; every other name there is a portfolio setting.
VIEW_NAMES = ("roles", "map", "showcase", "steps")

# The build's warning (`strays.stray_warnings`): group 1 the key, group 2 the portfolio.
_PIECE_KEY = re.compile(r"^\S+: front matter key '([^']+)' is not published; .* the ([^ ]+) portfolio's meta and cardMeta do not "
                        r"list it$")


def readers(key):
    """Every view and setting the plugin's tables say reads piece key `key`, as sorted `view: <name>` and
    `setting <name>` strings; [] when none does."""
    names = set(n for n, keys in VIEW_PIECE_KEYS.items() if key in keys) | set(V5_PIECE_KEYS.get(key, ()))
    return sorted(("view: %s" if n in VIEW_NAMES else "setting %s") % n for n in names)


def synonym_sources():
    """The piece keys a `pieceKeys` conversion renames, whatever the view: the sources of `PIECE_KEY_SYNONYMS` and of every
    row of `TILE_KEY_SYNONYMS`."""
    out = set(src for src, _dst in PIECE_KEY_SYNONYMS)
    for rows in TILE_KEY_SYNONYMS.values():
        out.update(src for src, _dst in rows)
    return out


def sort_key(key, read_here=(), pending=()):
    """`COVERED`, `ELSEWHERE` or `UNKNOWN` for piece key `key` in one portfolio. `read_here` is the keys the converted tree
    reads there; `pending` the keys a pending conversion renames in that piece (a `pieceKeys` source, counted before parity has
    run)."""
    if key in read_here or (key in pending and key in synonym_sources()):
        return COVERED
    return ELSEWHERE if readers(key) else UNKNOWN


def parity_tail(portfolio, parity=None):
    """What parity knows about `portfolio`'s pages, as the last clause of a note: the page it named, that it could not
    measure (with the reason its record gives: design-adopt-parity-2 section 7.5, dev 977; it said "no local build" of a site
    that had one), that it measured no difference there, or that it has not run."""
    if not parity:
        return "whether your builder prints it is parity's to say, on the page: `adopt.py parity` measures it"
    if parity.get("verdict") in ("UNVERIFIED", "NOT APPLICABLE"):
        why = " ".join(str(parity.get("reason") or "").split())
        return "parity could not measure this site (%s)" % (why or "its record gives no reason")
    for d in parity.get("differences") or ():
        page = d[1] if isinstance(d, (list, tuple)) and len(d) > 1 else None
        if page and page.startswith(portfolio + "/"):
            return "parity names %s" % page
    return "parity measured no difference on %s/" % portfolio


def _ways_out(found):
    """The second way out, worded for the readers `found` names: a view, a setting, or both."""
    views = [r for r in found if r.startswith("view: ")]
    if len(views) == len(found):
        return "to use it as %s does, set the view" % ("that view" if len(found) == 1 else "one of those views")
    if not views:
        return "to use it as %s does, set the setting" % ("that setting" if len(found) == 1 else "one of those settings")
    return "to use it as they do, set the view or the setting"


def cover_keys(probs, views=None, pending=(), parity=None, unmodelled=None, left=None):
    """`probs` with each build warning about an unpublished piece key sorted (design 6.1): a covered key is dropped, a key read
    elsewhere becomes that note, an unknown key is left as the build said it. `views` is {portfolio: its view} in the converted
    tree; `pending` is {(piece path, key)} a pending conversion renames; `parity` the plan's parity record or None.
    `unmodelled` is {key: (view, dev issue)}: under that view the key's note also says the view's use of it is not modelled.
    `left` is {key: plugin key}: a template key `pieceKeys` leaves under `view: showcase`, named once with its fix (set the
    view to steps). Same path, line and standing (`you decide`) as the warning."""
    out = []
    for p in probs:
        m = _PIECE_KEY.match(p.message)
        if not m or p.mechanical or p.fix != UNKNOWN_KEY_FIX:
            out.append(p)
            continue
        key, portfolio = m.group(1), m.group(2)
        view = (views or {}).get(portfolio)
        if (left or {}).get(key) and view == "showcase":
            out.append(diagnostics.make_problem(
                "%s; under view: showcase the template's '%s' has no plugin key" % (p.message, key), p.path, p.found,
                p.expected, "set the portfolio's view to steps, which reads %s; %s" % (left[key], parity_tail(portfolio, parity)),
                False, p.lineno))
            continue
        how = sort_key(key, (), set(k for path, k in pending if path == p.path))
        if how == COVERED:
            continue
        if how == UNKNOWN:
            out.append(p)
            continue
        found = readers(key)
        extra = ""
        if (unmodelled or {}).get(key) and (unmodelled[key][0] == view):
            extra = "; what view: %s does with it is not modelled yet (dev %d)" % unmodelled[key]
        out.append(diagnostics.make_problem(
            "%s; `%s` is read by %s, which content/%s does not use%s" % (p.message, key, " and ".join(found), portfolio, extra),
            p.path, NOTE, p.expected,
            "to print it as it is, list it in meta; %s; %s" % (_ways_out(found), parity_tail(portfolio, parity)),
            False, p.lineno))
    return out


# The `found` of a "read elsewhere" note (design 6.1 item 2): a note, not a decision. `split_notes` takes it out of the problems,
# so it is never counted in `you decide` and `apply` never waits on it; `note_lines` prints it once per key and portfolio.
NOTE = "a key another view or setting of the plugin reads"


READS_NOTE_FIX = "give a page that key, or take it out of the look's reads"


def reads_note_problems(build_notes, path):
    """dev 1058: the build notes `strays.unread_notes` made ("`K` is named by the look's `reads` T, and no page reads it"; the
    others of `Acceptance.notes` are left), as notes in `cover_keys`' own shape, at `path` (the look file the site names): so
    `split_notes` and `note_lines` take them as they take a "read elsewhere" note, and they are never counted in `you decide`."""
    return [diagnostics.make_problem("%s: %s" % (path, n), path, NOTE, "a page that reads it", READS_NOTE_FIX, False)
            for n in build_notes if n.endswith(UNREAD_TAIL)]


def split_notes(probs):
    """(problems, notes): `probs` without the "read elsewhere" notes `cover_keys` made, and those notes."""
    return [p for p in probs if p.found != NOTE], [p for p in probs if p.found == NOTE]


def note_lines(notes):
    """The lines `check` and `inventory` print for `split_notes`' notes: a heading, then one line per key and portfolio (the
    places it stands in, by path and line), ending with both ways out and what parity knows. [] when there is none."""
    groups, order = {}, []
    for p in notes:
        rest = p.message[len(p.path) + 2:] if p.path and p.message.startswith(p.path + ": ") else p.message
        if (rest, p.fix) not in groups:
            order.append((rest, p.fix))
        groups.setdefault((rest, p.fix), []).append("%s:%s" % (p.path, p.lineno) if p.lineno else p.path)
    if not order:
        return []
    return ["notes, not decisions (apply does not wait on them; each names a key the plugin reads elsewhere):"] + [
        "  - note: %s -- %s [%s]" % (rest, fix, ", ".join(groups[(rest, fix)])) for rest, fix in order]
