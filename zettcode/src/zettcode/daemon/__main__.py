"""``python -m zettcode.daemon``: what ``daemon spawn`` starts, and nothing a reader calls by hand."""

from __future__ import annotations

import sys

from .cli import daemon_program

if __name__ == "__main__":
    raise SystemExit(daemon_program(sys.argv[1:]))
