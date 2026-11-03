"""``python -m zettcode.broker``: run the broker in the foreground."""

from __future__ import annotations

import sys

from .runner import main

if __name__ == "__main__":
    sys.exit(main())
