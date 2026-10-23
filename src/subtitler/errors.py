"""Error types shared across the package."""

from __future__ import annotations


class UserFacingError(Exception):
    """An error whose message is safe to print directly to the user.

    ``main`` catches this, prints ``subtitler: <message>`` to stderr, and exits
    with status 1. Use it for expected failures while running (missing tools,
    unusable files, provider API errors) rather than unexpected bugs.
    """


class UsageError(UserFacingError):
    """A mistake on the command line, such as a flag combination that can't work
    or a path to a file that isn't there.

    ``main`` reports it the way argparse reports its own mistakes: the usage
    line, then ``subtitler: error: <message>``, with status 2.
    """
