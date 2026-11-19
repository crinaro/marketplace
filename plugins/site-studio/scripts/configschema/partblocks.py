"""partblocks: the home-part and fenced-block scans of a Markdown body: which part names are fixed at a schema,
where a custom part collides with one, and which lines hold more than one block inside a part."""

import re
from configschema.configkeys import V4_PART_FIXED
from configschema.diagnostics import make_problem
from configschema.frontmatter import _text_of


_PART_OPEN_RE = re.compile(r"^:::part[ \t]+(\S+)")
_BLOCK_OPEN_RE = re.compile(r"^:::([A-Za-z][A-Za-z0-9_-]*)(?:[ \t].*)?$")
_BLOCK_CLOSE_RE = re.compile(r"^:::[ \t]*$")


def fixed_part_names(schema):
    """The home parts schema `schema` adds to the fixed names (`content.PART_FIXED` holds the 0.3.x ones): the
    five home keys at 4 and above, none below. This is the part-name precedence of design section 3.1 rule 7."""
    return V4_PART_FIXED if schema >= 4 else ()


def part_collision_problems(files):
    """One Problem per `:::part <name>` line in the content Markdown whose name is a part fixed at schema 4
    ("`:::part showcase` collides with the home key `showcase`; rename the part"). The ONE function that says so:
    the build at schema 4 and above refuses with these, and `build.py raise-schema --to 4` and the address
    commands run it before they write anything. Below schema 4 nothing calls it: such a part is accepted and
    renders as in 0.3.x."""
    out = []
    for path in sorted(files or ()):
        if not (path.startswith("content/") and path.lower().endswith(".md")):
            continue
        for n, line in enumerate(_text_of(files[path]).replace("\r\n", "\n").split("\n"), 1):
            m = _PART_OPEN_RE.match(line)
            if m and m.group(1) in V4_PART_FIXED:
                name = m.group(1)
                out.append(make_problem("%s:%d: ':::part %s' collides with the home key '%s'; rename the part"
                                        % (path, n, name, name), path, ":::part %s" % name,
                                        "a part name that is not one of %s" % ", ".join(V4_PART_FIXED),
                                        "rename the part (the home keys %s are fixed names at schema 4)"
                                        % ", ".join(V4_PART_FIXED), False, n))
    return out


def multi_block_part_lines(text):
    """The 1-based line of every block that is the SECOND (or later) one inside a `:::part` in `text`: 0.3.x
    refused a part holding more than one block, and schema 4 reads any number (design R3 C), so such a part is a
    schema-4 K reason. A line starting with a backslash is text and never matches. The scan follows the grammar's
    own nesting (one block open at a time inside a part), so a part with one block, and blocks outside any part,
    are not reasons."""
    out = []
    in_part = inner = in_other = False
    seen = 0
    for n, line in enumerate(text.replace("\r\n", "\n").split("\n"), 1):
        line = line.rstrip()
        m = _BLOCK_OPEN_RE.match(line)
        if m:
            if in_part:
                if not inner and m.group(1) != "part":
                    inner = True
                    seen += 1
                    if seen == 2:
                        out.append(n)
            elif not in_other:
                if m.group(1) == "part":
                    in_part, seen = True, 0
                else:
                    in_other = True
        elif _BLOCK_CLOSE_RE.match(line):
            if inner:
                inner = False
            elif in_part:
                in_part = False
            elif in_other:
                in_other = False
    return out
