"""errors.py -- ImageError, the one refusal every image function raises (one line saying what and why).

Moved out of images.py unchanged (S1b, dev 939); the interface and the design notes are in images.py."""


class ImageError(ValueError):
    """Every refusal. The message is one line saying what and why."""
