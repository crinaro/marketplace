"""fetch_limits: the two numbers a user is told about the posting fetch (dev 858; design-browser-fallback.md 6.4).

Capability module of `posting_fetch.py`, which owns the pacing and the cap and imports them from here, so the notice row's text
(`fetch_notice`) and the fetch itself can never state two different numbers."""

MIN_INTERVAL_S = 3.0
POSTING_FETCH_CAP = 40       # GETs per run per machine: a fixed engine cap, read from no setting
