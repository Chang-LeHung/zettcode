"""Reusable probes for measuring ZettCode's render and storage hot paths.

The scripts here are not tests: they build the real application offline (no
provider, no network, no ``~/.zettcode``) and report wall time per stage, so a
performance claim can be reproduced instead of taken on faith. Run them with
``uv run python -m perf.<name>``; see ``perf/README.md`` for the methodology.
"""
