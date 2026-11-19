"""SCRIPT: the page's one allowed script, and nothing else that runs (OWNER REQUEST 2026-10-13, "Copy as prompt";
contract amended by design-dashboard-redesign §6.1, moved here by dashboard-redesign E).

    check_scripts(page, ledger, expected) -> (gaps, line)

The page was script-free by choice (design r3 Prior art: the page survives being saved and mailed). The owner chose ONE
script, so the rule is an allowlist of exactly that one, keyed by its marker (`ALLOWED_OPEN`), never "any script".
Since the tick-box model (§6.1) its contract is: the one allowlisted script **copies text already on the page:
attribute values, joined by newlines.** It touches no network, no storage and no navigation, and it builds no markup.
So each of these is a gap:
  * a second script, or a script tag that is not the allowed one (an external `src` included);
  * the allowed script more than once;
  * a token in a script body that reaches the network, storage or navigation, or that builds or injects markup
    (`FORBIDDEN`): the script reads `data-head`, `data-line` and `data-tail` and writes text, nothing more;
  * an inline event handler (`on...=`) or a `javascript:` URL anywhere on the page.
Pure: no I/O; `ledger` and `expected` are accepted for the uniform signature and not read."""
import re

ALLOWED_OPEN = '<script data-dashboard-script="copy-as-prompt">'
_OPEN_RE = re.compile(r"<script\b[^>]*>", re.I)
_BODY_RE = re.compile(r"<script\b[^>]*>(.*?)</script\s*>", re.I | re.S)
_INLINE_HANDLER_RE = re.compile(r"<[a-z][^>]*\son[a-z]+\s*=", re.I)
FORBIDDEN = ("fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket", "EventSource", "import(", "localStorage",
             "sessionStorage", "indexedDB", "document.cookie", "window.open", "location.", "postMessage", "eval(",
             "new Function",
             # dashboard-redesign E (§6.1): it copies attribute values; it never builds or injects markup
             "innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "createElement")


def check_scripts(page, ledger=None, expected=None):
    """(gaps, line): at most ONE script, the allowlisted copy-as-prompt one, within its contract."""
    gaps = []
    opens = _OPEN_RE.findall(page)
    others = [o for o in opens if o != ALLOWED_OPEN]
    for o in others:
        gaps.append("SCRIPT — %s is not the one script this page allows (%s); the page is otherwise script-free"
                    % (o[:80], ALLOWED_OPEN))
    n_allowed = len(opens) - len(others)
    if n_allowed > 1:
        gaps.append("SCRIPT — the copy-as-prompt script appears %d times; exactly one is allowed" % n_allowed)
    for body in _BODY_RE.findall(page):
        for tok in FORBIDDEN:
            if tok in body:
                gaps.append("SCRIPT — the page's script uses %r; it may only copy text already on the page: attribute "
                            "values, joined by newlines (no network, no storage, no navigation, no markup)" % tok)
    if _INLINE_HANDLER_RE.search(page):
        gaps.append("SCRIPT — an inline event handler attribute (on...=) is on the page")
    if re.search(r'href="\s*javascript:', page, re.I):
        gaps.append("SCRIPT — a javascript: URL is on the page")
    return gaps, "script: %d (allowed: the copy-as-prompt script, at most once)" % len(opens)
