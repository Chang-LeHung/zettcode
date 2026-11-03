# `zettcode-recap`, on its own: its suite, its sources and its types.
#
# The same work with the whole workspace in it is `make test`, `make lint` and `make typecheck` at the root; this file
# is for the days one distribution is all that changed.

UV ?= uv

.PHONY: test lint typecheck

# This distribution's suite only, with the pytest configuration in this package's `pyproject.toml`.
test:
	@if [ -d tests ]; then $(UV) run --no-sync pytest; else echo "zettcode-recap: no tests in this distribution"; fi

# Ruff over this package, with the configuration at the workspace root.
lint:
	$(UV) run --no-sync ruff format --check src tests
	$(UV) run --no-sync ruff check src tests

# mypy over this package's sources, with the root's settings and package bases. Run from the root: from
# inside the package the same file resolves under two module names (`src.zettcode.tui` and `zettcode.tui`).
typecheck:
	@cd ../.. && $(UV) run --no-sync mypy packages/zettcode-recap/src
