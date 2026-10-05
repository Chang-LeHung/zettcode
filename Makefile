UV ?= uv

.PHONY: help install lint typecheck test build smoke check hooks demo demo-all demos demo-thinking FORCE

DEMOS := text status_bar spinner progress_bar list table diff markdown textarea completion dialog collapsible toast tasks scroll layout

help:
	@echo "Available targets:"
	@echo "  make install  Sync the ZettCode environment from uv.lock"
	@echo "  make lint     Check formatting and linting with Ruff"
	@echo "  make typecheck Check the shipped code with mypy"
	@echo "  make test     Run the test suite"
	@echo "  make build    Build the sdist and wheel into dist/"
	@echo "  make smoke    Install the built wheel and run 'zettcode --help'"
	@echo "  make check    Run lint, typecheck, and tests"
	@echo "  make hooks    Install the git hooks (blocks a commit that fails mypy)"
	@echo "  make demo     Browse the widgets interactively"
	@echo "  make demo-all Print every widget preview"
	@echo "  make demos    List the widget names"
	@echo "  make demo-x   Print one widget preview ($(DEMOS))"
	@echo "  make demo-thinking  Watch a live turn's running rows blink"

install:
	$(UV) sync

lint:
	$(UV) run ruff format --check src tests
	$(UV) run ruff check src tests

typecheck:
	$(UV) run mypy

test:
	$(UV) run pytest

build:
	$(UV) build

smoke: build
	$(UV) run --no-project --python 3.14 --with ./dist/*.whl zettcode --help

check: lint typecheck test

# The global hooksPath delegates to .git/hooks, so a local copy is what runs.
hooks:
	install -m 755 .githooks/pre-commit .git/hooks/pre-commit
	@echo "installed .git/hooks/pre-commit (mypy blocks the commit)"

FORCE:

demos:
	$(UV) run python -m zettcode.tui.gallery --list

# An explicit target beats the demo-% pattern rule below, which is what lets a
# demo live outside the framework gallery.
demo-thinking:
	$(UV) run python -m zettcode.app.ui.demo

demo:
	$(UV) run python -m zettcode.tui.gallery

demo-all:
	$(UV) run python -m zettcode.tui.gallery --print

demo-%: FORCE
	$(UV) run python -m zettcode.tui.gallery $*
