"""fetch_gate: rules 4, 5 and 6 of design-browser-fallback.md 6.1, applied once per `read-batch --fallback` call.

Capability module of `posting_fetch.py`, which passes its host, its audience seam and its own `admitted` in."""

from browser_fallback.fetch_key import KEY, key_value
from browser_fallback.fetch_notice import NOTICE_REMEDY, notice_exists
from browser_fallback.fetch_sandbox import remedy


def auto_gate(root, host, audience, admit):
    """`(go, code, remedy)` for one `read-batch --fallback` call. `code` is None when `go`; otherwise one of `off`, `unreadable`,
    `sandbox-unconfirmed`, `notice-missing` (the `FETCH_CODES` the caller stores), and `remedy` is the line to print. Nothing is
    ever sent unless `go`:

      4. the key reads `absent` or `on` (`off` and `unreadable` never fetch; `absent` also needs `audience` "everyone");
      5. the host is admitted (`admit(root)`, the caller's `fetch_sandbox.admitted` with its seams);
      6. for a key that reads `absent`, the notice row exists. `on` is its own disclosure (TERMS_LINES printed at `--set on`)."""
    value, why = key_value(root)
    if value == "unreadable":
        return False, "unreadable", why
    if value == "off":
        return False, "off", "%s is off" % KEY
    if value == "absent" and audience != "everyone":
        return False, "off", "%s is not set, and the automatic fetch is limited to users who turned it on" % KEY
    ok, why = admit(root)
    if not ok:
        return False, "sandbox-unconfirmed", "%s. To use it, %s" % (why, remedy(host))
    if value == "absent":
        exists, why = notice_exists(root)
        if not exists:
            return False, "notice-missing", "%s (%s)" % (NOTICE_REMEDY, why)
    return True, None, None
