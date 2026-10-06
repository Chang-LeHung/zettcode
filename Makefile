UV ?= uv

.PHONY: help install lint typecheck test build smoke check hooks docs docs-build docs-preview demo demo-all demos demo-thinking perf perf-scaling perf-store perf-profile FORCE

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
	@echo "  make docs     Serve the user guide at http://localhost:5173"
	@echo "  make docs-build   Build the guide into docs/.vitepress/dist"
	@echo "  make demo     Browse the widgets interactively"
	@echo "  make demo-all Print every widget preview"
	@echo "  make demos    List the widget names"
	@echo "  make demo-x   Print one widget preview ($(DEMOS))"
	@echo "  make demo-thinking  Watch a live turn's running rows blink"
	@echo "  make perf     Break one frame into stages at 200 turns"
	@echo "  make perf-scaling   Cost per interaction against transcript size"
	@echo "  make perf-store     Session append/read cost against log size"
	@echo "  make perf-profile   cProfile the streaming scenario"

install:
	$(UV) sync

lint:
	$(UV) run ruff format --check src tests perf
	$(UV) run ruff check src tests perf

typecheck:
	$(UV) run mypy

test:
	$(UV) run pytest

build:
	$(UV) build

smoke: build
	$(UV) run --no-project --python 3.14 --with ./dist/*.whl zettcode --help
	@# The HTML trace ships as package data: a packaging change that drops the
	@# template, its stylesheet, or its script has to fail here, not at export time.
	$(UV) run --no-project --python 3.14 --with ./dist/*.whl python -c "from importlib.resources import files; names = sorted(p.name for p in files('zettcode.app.agent').joinpath('trace').iterdir()); assert names == ['script.js', 'style.css', 'template.html'], names; print('trace assets:', names)"

check: lint typecheck test

# The guide is a VitePress site in docs/; its own package.json pins it.
docs:
	cd docs && npm install --no-audit --no-fund && npm run docs:dev

docs-build:
	cd docs && npm install --no-audit --no-fund && npm run docs:build

docs-preview: docs-build
	cd docs && npm run docs:preview

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

# Performance probes; see perf/README.md for flags and methodology.
perf:
	$(UV) run python -m perf.frame_stages

perf-scaling:
	$(UV) run python -m perf.scaling

perf-store:
	$(UV) run python -m perf.store

perf-profile:
	$(UV) run python -m perf.profile --scenario stream
