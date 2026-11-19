"""The dashboard's renderers (design-dashboard-redesign.md §10.2): pure functions from the values the
loader in generate_dashboard.py fills (`pagedata.PageData`, and one `ledger.Ledger` per render) to the
page's HTML. They import the standard library and each other; they read no file, no clock and no
environment."""
