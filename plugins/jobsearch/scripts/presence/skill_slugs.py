"""skill_slugs: the one `slug()` a requirement's `topic` and a stated LinkedIn skill are compared through
(design-presence-report.md §5.6, §8.1).

`+` becomes ` plus ` and `#` becomes ` sharp `, then the rule `recording/common._slug` implements: case-fold, every
run of characters outside `a-z0-9` becomes one `-`, trimmed, capped at `SLUG_MAX`. So "C++" is `c-plus-plus`, "C#"
is `c-sharp`, "Node.js" is `node-js`, ".NET" is `net`. Stated limit: no synonyms ("K8s" is not `kubernetes`).

A stored `topic` must be its own slug and match `TOPIC_RE` (at most six words): `topic_refusal` says why not.
`record.py fit`, `record.py fit-key`, `record.py retopic` and `validate_data.py` all ask this one function."""

import re

SLUG_MAX = 48
TOPIC_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+){0,5}$")


def slug(text):
    """The comparison form of a topic or a skill: see the module docstring."""
    s = str(text or "").replace("+", " plus ").replace("#", " sharp ")
    return re.sub(r"[^a-z0-9]+", "-", s.casefold()).strip("-")[:SLUG_MAX].strip("-")


def topic_refusal(topic):
    """None when `topic` may be stored, else the reason it may not."""
    if not isinstance(topic, str) or not topic:
        return "topic must be a non-empty string (got %r)" % (topic,)
    if slug(topic) != topic:
        return "topic %r is not its own slug (slug: %r)" % (topic, slug(topic))
    if not TOPIC_RE.match(topic):
        return ("topic %r does not match %s (one to six words of a-z0-9 joined by '-')"
                % (topic, TOPIC_RE.pattern))
    return None
