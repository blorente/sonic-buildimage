"""Progress reporting, directly to stderr."""

import sys

DONE = "DONE"


def start(message: str) -> None:
    """Announce work about to happen, leaving the line open for its outcome."""
    print(f"{message}... ", end="", file=sys.stderr, flush=True)


def finish() -> None:
    """Close the line `start` opened."""
    print(DONE, file=sys.stderr)
