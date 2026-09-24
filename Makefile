UV ?= uv

.PHONY: help install lint test build smoke check

help:
	@echo "Available targets:"
	@echo "  make install  Sync the ZettCode environment from uv.lock"
	@echo "  make lint     Check formatting and linting with Ruff"
	@echo "  make test     Run the test suite"
	@echo "  make build    Build the sdist and wheel into dist/"
	@echo "  make smoke    Install the built wheel and run 'zettcode --help'"
	@echo "  make check    Run lint and tests"

install:
	$(UV) sync

lint:
	$(UV) run ruff format --check src tests
	$(UV) run ruff check src tests

test:
	$(UV) run pytest

build:
	$(UV) build

smoke: build
	$(UV) run --no-project --python 3.14 --with ./dist/*.whl zettcode --help

check: lint test
