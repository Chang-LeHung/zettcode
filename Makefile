UV ?= uv

.PHONY: help install lint test build smoke check demo demos FORCE

DEMOS := text status_bar spinner progress_bar list table diff markdown textarea completion dialog collapsible toast tasks scroll layout

help:
	@echo "Available targets:"
	@echo "  make install  Sync the ZettCode environment from uv.lock"
	@echo "  make lint     Check formatting and linting with Ruff"
	@echo "  make test     Run the test suite"
	@echo "  make build    Build the sdist and wheel into dist/"
	@echo "  make smoke    Install the built wheel and run 'zettcode --help'"
	@echo "  make check    Run lint and tests"
	@echo "  make demo     Print every widget preview"
	@echo "  make demos    List the widget names"
	@echo "  make demo-x   Print one widget preview ($(DEMOS))"

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

FORCE:

demos:
	$(UV) run python -m zettcode.tui_framework.gallery --list

demo:
	$(UV) run python -m zettcode.tui_framework.gallery

demo-%: FORCE
	$(UV) run python -m zettcode.tui_framework.gallery $*
