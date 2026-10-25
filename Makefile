UV ?= uv
#: The editor CLI `make install-vscode` installs into: `code`, `code-insiders`, `cursor`, or a path to one.
CODE ?= code

# The repository is a uv workspace of one package, `zettcode/`: the terminal agent and the HTTP server it serves
# are one distribution, so one `pip install` writes both `zettcode` and `zettcode-server`. Tooling is configured once,
# in the root `pyproject.toml`; `make check` runs it all.
#
# `make smoke` builds here rather than into dist/, so the wheel it installs is
# the one it just built and not a release wheel left over from an earlier run.
SMOKE_DIR := .smoke

LINT_PATHS := zettcode/src zettcode/tests zettcode/perf docs/scripts

# `make check` runs only what the tree has changed, so a change to the VS Code webview does not spend three minutes
# on the Python suite: CI runs every suite on every pull request, and that is where the whole gate lives. The files
# are read against BASE, where this branch left the main line.
BASE ?= $(shell git merge-base HEAD origin/main 2>/dev/null || git rev-parse --verify HEAD)
CHANGED := $(shell { git diff --name-only $(BASE); git ls-files --others --exclude-standard; } 2>/dev/null | sort -u)
# A changed Makefile can change any of these rules, so it counts as every file.
EVERYTHING := $(filter Makefile,$(CHANGED))
# Files that need Ruff, mypy and the Python suite.
PYTHON := $(if $(EVERYTHING),1,$(filter zettcode/% pyproject.toml uv.lock,$(CHANGED)))
# Files Ruff alone covers (`make lint` reads docs/scripts too).
RUFFED := $(if $(PYTHON),1,$(filter docs/scripts/%,$(CHANGED)))
# The TypeScript client, and the extension, which bundles that client's source.
CLIENT := $(if $(EVERYTHING),1,$(filter clients/typescript/%,$(CHANGED)))
EXTENSION := $(if $(EVERYTHING),1,$(filter clients/vscode/% clients/typescript/%,$(CHANGED)))

.PHONY: help install lint typecheck test python client vscode vscode-package install-vscode build smoke check check-all hooks docs docs-build docs-preview demo demo-all demos demo-thinking palettes themes perf perf-scaling perf-store perf-profile perf-startup perf-imports FORCE

DEMOS := text status_bar spinner progress_bar list table diff markdown textarea completion dialog collapsible toast tasks scroll layout

help:
	@echo "Available targets:"
	@echo "  make install  Sync the workspace from uv.lock"
	@echo "  make lint     Check formatting and linting with Ruff"
	@echo "  make typecheck Check the shipped code with mypy"
	@echo "  make test     Run the test suite"
	@echo "  make python   Lint, type-check and test the Python side"
	@echo "  make client   Build and test the TypeScript client"
	@echo "  make vscode   Type-check, test and build the VS Code extension"
	@echo "  make vscode-package   Also package the extension as a .vsix"
	@echo "  make install-vscode  Package it and install it into the editor $(CODE); reinstall is forced"
	@echo "  make build    Build the sdist and wheel into dist/"
	@echo "  make smoke    Build the wheel into $(SMOKE_DIR)/ and run both programs' --help from it"
	@echo "  make check    Run what the change needs (BASE=main to compare with another ref)"
	@echo "  make check-all   Run every suite, as CI does"
	@echo "  make hooks    Install the git hooks (blocks a commit that fails mypy)"
	@echo "  make docs     Serve the user guide at http://localhost:5173"
	@echo "  make docs-build   Build the guide into docs/.vitepress/dist"
	@echo "  make palettes     Regenerate docs/internal/palettes.html (every widget in every palette)"
	@echo "  make themes       Rewrite zettcode/src/zettcode/tui/themes from docs/scripts/palette_data.py"
	@echo "  make demo     Browse the widgets interactively"
	@echo "  make demo-all Print every widget preview"
	@echo "  make demos    List the widget names"
	@echo "  make demo-x   Print one widget preview ($(DEMOS))"
	@echo "  make demo-thinking  Watch a live turn's waiting row sweep"
	@echo "  make perf     Break one frame into stages at 200 turns"
	@echo "  make perf-scaling   Cost per interaction against transcript size"
	@echo "  make perf-store     Session append/read cost against log size"
	@echo "  make perf-profile   cProfile the streaming scenario"
	@echo "  make perf-startup   Time a launch, stage by stage, up to the first frame"
	@echo "  make perf-exit      Time a quit, and the interpreter teardown it pays for"
	@echo "  make perf-imports   Measure what each deferrable import would really save"

install:
	$(UV) sync --all-packages

lint:
	$(UV) run --no-sync ruff format --check $(LINT_PATHS)
	$(UV) run --no-sync ruff check $(LINT_PATHS)

typecheck:
	$(UV) run --no-sync mypy

test:
	cd zettcode && $(UV) run --no-sync pytest

python: lint typecheck test

# The TypeScript client has its own toolchain: Node 20+, no runtime dependencies.
client:
	cd clients/typescript && npm install --no-audit --no-fund && npm test

# The VS Code extension is a webview client for the server. Its test runner bundles the
# webview into a temporary directory and drives it in jsdom, so no editor is needed to run the suite.
vscode:
	cd clients/vscode && npm install --no-audit --no-fund
	cd clients/vscode && npm run check && npm test && npm run build

vscode-package: vscode
	cd clients/vscode && npx --yes @vscode/vsce package --no-dependencies

# What a reader with the extension installed needs after a change: the same package, installed over the old one.
# The version comes from the extension's own package.json, and the install is forced because reinstalling the same
# version is exactly what a local build is. `CODE` picks the CLI, for an editor that is not called `code`.
install-vscode: vscode-package
	@command -v $(CODE) >/dev/null || { \
		echo "$(CODE) is not on PATH: set CODE to the editor's CLI, such as CODE=code-insiders or CODE=cursor"; \
		exit 1; }
	cd clients/vscode && $(CODE) --install-extension "zettcode-$$(node -p 'require("./package.json").version').vsix" --force

build:
	$(UV) build --package zettcode

# The wheel is built, not found: a glob over dist/ would happily install an older
# version that happens to be lying there, and a wheel that is not the one just
# built proves nothing about the build. One wheel, two programs.
smoke:
	rm -rf $(SMOKE_DIR)
	$(UV) build --package zettcode --out-dir $(SMOKE_DIR)
	$(UV) run --no-project --python 3.14 --with ./$(SMOKE_DIR)/zettcode-*.whl zettcode --help
	$(UV) run --no-project --python 3.14 --with ./$(SMOKE_DIR)/zettcode-*.whl zettcode-server --help
	@# The HTML trace ships as package data: a packaging change that drops the
	@# template, its stylesheet, or its script has to fail here, not at export time.
	$(UV) run --no-project --python 3.14 --with ./$(SMOKE_DIR)/zettcode-*.whl python -c "from importlib.resources import files; names = sorted(p.name for p in files('zettcode.engine.export').joinpath('trace').iterdir()); assert names == ['script.js', 'style.css', 'template.html'], names; print('trace assets:', names)"

check:
	@echo "--- changed since $(BASE) ---"
	@printf '%s\n' $(CHANGED) | head -20 | sed 's/^/  /'
	@test -n "$(CHANGED)" || echo "  (nothing yet; make check-all runs every suite)"
	@$(if $(PYTHON),$(MAKE) --no-print-directory python,$(if $(RUFFED),$(MAKE) --no-print-directory lint,echo "  python: untouched, skipped"))
	@$(if $(CLIENT),$(MAKE) --no-print-directory client,echo "  typescript client: untouched, skipped")
	@$(if $(EXTENSION),$(MAKE) --no-print-directory vscode,echo "  vscode extension: untouched, skipped")

# The whole gate, which is what CI runs on every pull request: before handing work over, and always in CI.
check-all: python client vscode

# The guide is a VitePress site in docs/; its own package.json pins it.
docs:
	cd docs && npm install --no-audit --no-fund && npm run docs:dev

docs-build:
	cd docs && npm install --no-audit --no-fund && npm run docs:build

docs-preview: docs-build
	cd docs && npm run docs:preview

# The palette page is a build product, not a source: every widget is painted in every palette by the real
# widget code, and docs/internal/palettes.html is written from that (it is in .gitignore). A change to the
# theme code, the palettes, or a widget therefore means running this again; nothing checks it for you.
palettes:
	$(UV) run --no-sync python docs/scripts/palette_gallery.py
	@echo "open docs/internal/palettes.html"

# The palettes that ship are files in the package, generated from the same data the page is: one table per
# palette in docs/scripts/palette_data.py. Change a colour there, run this, and commit the files it wrote;
# the wheel ships whatever is in zettcode/src/zettcode/tui/themes. Nothing checks the two agree, so run it
# after a change and look at `git status`.
themes:
	$(UV) run --no-sync python docs/scripts/palette_gallery.py --export-themes zettcode/src/zettcode/tui/themes
	@git status --short zettcode/src/zettcode/tui/themes

# The global hooksPath delegates to .git/hooks, so a local copy is what runs.
hooks:
	install -m 755 .githooks/pre-commit .git/hooks/pre-commit
	@echo "installed .git/hooks/pre-commit (mypy blocks the commit)"

FORCE:

demos:
	cd zettcode && $(UV) run --no-sync python -m zettcode.tui.gallery --list

# An explicit target beats the demo-% pattern rule below, which is what lets a
# demo live outside the framework gallery.
demo-thinking:
	cd zettcode && $(UV) run --no-sync python -m zettcode.app.ui.demo

demo:
	cd zettcode && $(UV) run --no-sync python -m zettcode.tui.gallery

demo-all:
	cd zettcode && $(UV) run --no-sync python -m zettcode.tui.gallery --print

demo-%: FORCE
	cd zettcode && $(UV) run --no-sync python -m zettcode.tui.gallery $*

# Performance probes; see zettcode/perf/README.md for flags and methodology.
perf:
	cd zettcode && $(UV) run --no-sync python -m perf.frame_stages

perf-scaling:
	cd zettcode && $(UV) run --no-sync python -m perf.scaling

perf-store:
	cd zettcode && $(UV) run --no-sync python -m perf.store

perf-profile:
	cd zettcode && $(UV) run --no-sync python -m perf.profile --scenario stream

perf-startup:
	cd zettcode && $(UV) run --no-sync python -m perf.startup --pty

perf-exit:
	cd zettcode && $(UV) run --no-sync python -m perf.exit --pty

perf-imports:
	cd zettcode && $(UV) run --no-sync python -m perf.imports
