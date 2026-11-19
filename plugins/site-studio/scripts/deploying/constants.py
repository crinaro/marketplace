"""deploying.constants -- the polling bounds, the list cap and the exit codes of `deploy.py` (0 published, 1 refused or red, 2 usage, 3 amber).
"""
POLL_INTERVAL = 10
POLL_TIMEOUT = 600


LIST_CAP = 60


EXIT_OK, EXIT_RED, EXIT_USAGE, EXIT_AMBER = 0, 1, 2, 3
