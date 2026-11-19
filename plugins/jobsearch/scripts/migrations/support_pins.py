"""The network-first pin (0.86.0): its version and whether a profile's journal still needs it.

One module of `migrations/` (design-component-segmentation.md §5); moved out of `migrate.py` unedited by S2."""

from migrations.stamp import ver


NETWORK_FIRST_PIN = "0.86.0"


def _network_first_pin_needed(profile, recs=None):
    """True when the profile's journal carries no pin at or above 0.86.0. `recs` is the journal as `journal.read` returned
    it, or None to scan (tolerantly, `journal.pin_scan`)."""
    import journal as _journal
    pin = _journal.profile_pin(recs) if recs is not None else _journal.pin_scan(profile)
    return pin is None or ver(pin) < ver(NETWORK_FIRST_PIN)
