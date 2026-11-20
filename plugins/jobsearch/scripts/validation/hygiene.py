"""The hygiene lines the validator prints after its problem count.

Capability module of `validate_data.py` (S4a, moved unedited)."""

from validation.pay import check_pay_captured


def hygiene_lines(opps, cfg, today, owner_token):
    """The `HYGIENE` section as printable lines (an empty list when there is nothing to say)."""
    return check_pay_captured(opps)
