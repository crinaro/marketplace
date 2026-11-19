"""The coverage gate's page checks (design-dashboard-redesign.md §10.3, dashboard-redesign E): pure functions of
`(page, ledger, expected)` that `check_dashboard_coverage.py` calls after it has read the page and the ledger and
computed `expected`. Each returns `(gaps, line)`. They import the standard library and each other; they read no file,
no clock and no environment."""
