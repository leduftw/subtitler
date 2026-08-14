"""Error types shared across the package."""

from __future__ import annotations


class UserFacingError(Exception):
    """An error whose message is safe to print directly to the user.

    ``main`` catches this, prints ``error: <message>`` to stderr, and exits
    with a non-zero status. Use it for expected failures (missing tools,
    bad input, provider API errors) rather than unexpected bugs.
    """
