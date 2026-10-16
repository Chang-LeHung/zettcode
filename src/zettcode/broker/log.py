"""The one line a broker writes about itself: to standard error, which a background broker points at its log."""

from __future__ import annotations

import sys
import time


def log(message: str) -> None:
    """Write one timestamped line to standard error and flush it, so a crash loses nothing."""
    print(time.strftime("%Y-%m-%d %H:%M:%S"), message, file=sys.stderr, flush=True)
