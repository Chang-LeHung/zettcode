# The SSH plugin alone; shared tool configuration remains at the workspace root.
UV ?= uv

.PHONY: test lint typecheck build

test:
	$(UV) run --no-sync pytest

lint:
	$(UV) run --no-sync ruff format --check src tests
	$(UV) run --no-sync ruff check src tests

typecheck:
	@cd ../.. && $(UV) run --no-sync mypy packages/zettcode-ssh/src

build:
	$(UV) build
