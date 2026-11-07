UV ?= uv
#: The editor CLI `make install-vscode` installs into: `code`, `code-insiders`, `cursor`, or a path to one.
CODE ?= code

# The repository is a uv workspace, and every distribution lives in `packages/`: the program (`zettcode`, the
# one a reader installs, which writes both console scripts) and the parts it is made of — the engine, the widget
# framework, the broker, the SDK, the server, the gateway, the terminal application — plus the plugins published
# on their own lines. They share one environment, one lock file and the tooling in the root `pyproject.toml`;
# `make check` runs it all.
#
# `make smoke` builds here rather than into dist/, so the wheel it installs is
# the one it just built and not a release wheel left over from an earlier run.
SMOKE_DIR := .smoke

PACKAGES := packages
LINT_PATHS := conftest.py support docs/scripts .github/scripts $(PACKAGES)
# The distributions the program is built from, in dependency order. Nothing keeps the list: it is generated from
# the `pyproject.toml` files (`release.yml` runs the same script), and `make order` writes it to
# `packages/order.txt` for a reader — that file is generated and not in git.
ORDER := .github/scripts/release_order.py
# Recursive (`=`), so the script runs when a target needs the list, not on every `make help`.
SPLIT = $(shell $(UV) run --no-sync python $(ORDER))
#: How many jobs run at once: 80% of the machine's logical cores, rounded down, so the editor and the tests can share
#: it. `JOBS=4 make check` caps it by hand, `TEST_JOBS=1 make test` restores one suite at a time, and `CHECK_JOBS`
#: is what the clients use after the Python side. CI runs the suites one at a time, where a shared runner's timings
#: are part of what is checked.
JOBS ?= $(shell n=$$(sysctl -n hw.ncpu 2>/dev/null || nproc 2>/dev/null || echo 4); j=$$((n * 8 / 10)); if [ "$$j" -lt 1 ]; then j=1; fi; echo $$j)
TEST_JOBS ?= $(if $(CI),1,$(JOBS))
CHECK_JOBS ?= $(JOBS)
# Each distribution's suite runs on its own, in that distribution's directory: its `pyproject.toml` is the pytest
# configuration it is written against (`testpaths`, `asyncio_mode`), and one run over several would take the
# root's instead of theirs. `support/test_all.py` finds them; each package also has a `Makefile` with the same
# targets for its own work.
# `make check` runs only what the tree has changed, so a change to the VS Code webview does not spend three minutes
# on the Python suite. CI reads the same split from the pull request's own diff and runs the suites a change needs,
# with the Makefile and the workflows counting as every file. The files are read against BASE, where this branch left
# the main line.
BASE ?= $(shell git merge-base HEAD origin/main 2>/dev/null || git rev-parse --verify HEAD)
CHANGED := $(shell { git diff --name-only $(BASE); git ls-files --others --exclude-standard; } 2>/dev/null | sort -u)
# A changed Makefile or workflow can change any of these rules, so either counts as every file (CI reads the same
# rule from the pull request's diff).
EVERYTHING := $(filter Makefile .github/workflows/%,$(CHANGED))
# Files that need Ruff, mypy and the Python suite. The release helper is Python that only the workflow runs, and the
# suite holds its tests.
PYTHON := $(if $(EVERYTHING),1,$(filter $(PACKAGES)/% support/% conftest.py .github/scripts/% pyproject.toml uv.lock,$(CHANGED)))
# Files Ruff alone covers (`make lint` reads docs/scripts too).
RUFFED := $(if $(PYTHON),1,$(filter docs/scripts/%,$(CHANGED)))
# The TypeScript client, and the extension, which bundles that client's source.
CLIENT := $(if $(EVERYTHING),1,$(filter clients/typescript/%,$(CHANGED)))
GATEWAY := $(if $(EVERYTHING),1,$(filter clients/gateway/%,$(CHANGED)))
EXTENSION := $(if $(EVERYTHING),1,$(filter clients/vscode/% clients/typescript/%,$(CHANGED)))
#: What `make check` runs: the Python side first (lint, typecheck and the suites together), then the clients the
#: change touches at once. The editor's jsdom suite is timing-sensitive, so it does not run beside the whole Python
#: suite; the clients are only a few seconds of the total.
PYTHON_TARGET = $(if $(PYTHON),python,$(if $(RUFFED),lint))
CLIENT_TARGETS = $(strip $(if $(CLIENT),client) $(if $(EXTENSION),vscode) $(if $(GATEWAY),gateway-ui))
#: A sub-make inherits a jobserver when the caller started one; forcing -j then only replaces it with a warning.
CLIENT_JOBS = $(if $(findstring j,$(MAKEFLAGS)),,$(CHECK_JOBS))

.PHONY: help install lint typecheck test order python client gateway-page gateway-ui vscode vscode-package install-vscode build smoke check check-all hooks docs docs-build docs-preview demo demo-all demos demo-thinking palettes themes perf perf-scaling perf-store perf-profile perf-startup perf-imports FORCE

DEMOS := text status_bar spinner progress_bar list table diff markdown textarea completion dialog collapsible toast tasks scroll layout

help:
	@echo "Available targets:"
	@echo "  make install  Sync the workspace from uv.lock"
	@echo "  make lint     Check formatting and linting with Ruff"
	@echo "  make typecheck Check the shipped code with mypy"
	@echo "  make test     Run every distribution's suite, $(TEST_JOBS) at a time (TEST_JOBS=1 for one at a time)"
	@echo "  JOBS=$(JOBS) TEST_JOBS=$(TEST_JOBS) CHECK_JOBS=$(CHECK_JOBS)  how many run at once (80% of the cores)"
	@echo "  make order    Write the release order to packages/order.txt (generated, not in git)"
	@echo "  make python   Lint, type-check and test the Python side"
	@echo "  make client   Build and test the TypeScript client"
	@echo "  make vscode   Type-check, test and build the VS Code extension"
	@echo "  make vscode-package   Also package the extension as a .vsix"
	@echo "  make install-vscode  Package it and install it into the editor $(CODE); reinstall is forced"
	@echo "  make build    Build the sdist and wheel into dist/"
	@echo "  make smoke    Build the wheel into $(SMOKE_DIR)/ and run both programs' --help from it"
	@echo "  make check    Run what the change needs (BASE=main to compare with another ref)"
	@echo "  make check-all   Run every suite, whether or not the change needs it"
	@echo "  make hooks    Install the git hooks (blocks a commit that fails mypy)"
	@echo "  make docs     Serve the user guide at http://localhost:5173"
	@echo "  make docs-build   Build the guide into docs/.vitepress/dist"
	@echo "  make palettes     Regenerate docs/internal/palettes.html (every widget in every palette)"
	@echo "  make themes       Rewrite packages/zettcode-tui/src/zettcode/tui/themes from docs/scripts/palette_data.py"
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
	@$(UV) run --no-sync python support/test_all.py $(TEST_JOBS)

# The dependency order a release publishes in, written out for a reader (`packages/order.txt`).
order:
	$(UV) run --no-sync python $(ORDER) > $(PACKAGES)/order.txt
	@cat $(PACKAGES)/order.txt

python: lint typecheck test

# The TypeScript client has its own toolchain: Node 20+, no runtime dependencies.
client:
	cd clients/typescript && npm install --no-audit --no-fund && npm test

# The gateway's page is a Vue and TypeScript app that is built into its distribution
# (packages/zettcode-gateway/src/zettcode/gateway/static).
# The build output is not in git: it is made here, and in CI and the release workflow before a wheel is built, and
# pyproject's `artifacts` puts it in the wheel. Rebuild it after any change under clients/gateway.
gateway-page:
	cd clients/gateway && npm install --no-audit --no-fund
	cd clients/gateway && npm run build

gateway-ui: gateway-page
	cd clients/gateway && npm run check && npm test

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

build: gateway-page
	@for pkg in $(SPLIT); do $(UV) build --package $$pkg || exit 1; done

# The wheels are built, not found: a glob over dist/ would happily install an older wheel that happens to be lying
# there, and a wheel that is not the one just built proves nothing about the build. Every distribution the program is
# made of is built and installed together, because they are published together and neither is on PyPI before the
# first release.
smoke: gateway-page
	rm -rf $(SMOKE_DIR)
	@for pkg in $(SPLIT); do $(UV) build --package $$pkg --out-dir $(SMOKE_DIR) || exit 1; done
	$(UV) venv --clear $(SMOKE_DIR)/venv
	$(UV) pip install --python $(SMOKE_DIR)/venv/bin/python $(SMOKE_DIR)/*.whl
	$(SMOKE_DIR)/venv/bin/zettcode --help
	$(SMOKE_DIR)/venv/bin/zettcode-server --help
	$(SMOKE_DIR)/venv/bin/zettcode gateway --help
	@# The gateway's page is built, not committed: a wheel made without it would serve an API and no page.
	$(SMOKE_DIR)/venv/bin/python -c "from importlib.resources import files; names = {p.name for p in files('zettcode.gateway').joinpath('static').iterdir()}; assert {'index.html', 'app.js', 'app.css'} <= names, names; print('gateway page:', sorted(names))"
	@# The HTML trace ships as package data: a packaging change that drops the
	@# template, its stylesheet, or its script has to fail here, not at export time.
	$(SMOKE_DIR)/venv/bin/python -c "from importlib.resources import files; names = sorted(p.name for p in files('zettcode.engine.export').joinpath('trace').iterdir()); assert names == ['script.js', 'style.css', 'template.html'], names; print('trace assets:', names)"
	@# The two plugins are built from this checkout and installed beside the program's wheels, and each has to register
	@# its command under this version. That is the layout this tree is: a plugin imports the contract (`zettcode-plugin-api`),
	@# so a plugin released before the contract moved cannot load here, and installing the *published* extras from PyPI
	@# would test those old releases and not the code in front of us. Whether the extras' ranges resolve against what is
	@# published is a question for the release, once the plugins exist on this layout; `test_each_extra_names_a_plugin...`
	@# holds the ranges against the versions built here until then.
	$(UV) build --package zettcode-monitor --out-dir $(SMOKE_DIR)/plugins
	$(UV) build --package zettcode-recap --out-dir $(SMOKE_DIR)/plugins
	$(UV) pip install --python $(SMOKE_DIR)/venv/bin/python --find-links $(SMOKE_DIR) $(SMOKE_DIR)/plugins/*.whl
	$(SMOKE_DIR)/venv/bin/python -c "import tempfile, pathlib; from zettcode.config import ModelConfig, ZettCodeConfig; from zettcode.app.plugins.loader import load_terminal_plugins; root = pathlib.Path(tempfile.mkdtemp()); (root / 'w').mkdir(); config = ZettCodeConfig(workspace=root / 'w', models=(ModelConfig(model='m', token='t'),), store=root / 'store', plugins_file=root / 'plugins.json', mcp_enabled=False, skills_enabled=False, harness_dir=root / 'harness'); bundle = load_terminal_plugins(config); names = [command.name for command in bundle.commands]; failed = dict(bundle.failed); assert '/monitor' in names and '/recap' in names, repr({k: failed[k] for k in ('monitor', 'recap') if k in failed}); print('plugins:', '/monitor', '/recap')"

check:
	@echo "--- changed since $(BASE) ---"
	@printf '%s\n' $(CHANGED) | head -20 | sed 's/^/  /'
	@test -n "$(CHANGED)" || echo "  (nothing yet; make check-all runs every suite)"
	@$(if $(PYTHON),:,$(if $(RUFFED),:,echo "  python: untouched, skipped"))
	@$(if $(CLIENT),:,echo "  typescript client: untouched, skipped")
	@$(if $(EXTENSION),:,echo "  vscode extension: untouched, skipped")
	@$(if $(GATEWAY),:,echo "  gateway page: untouched, skipped")
	@$(if $(PYTHON_TARGET),$(MAKE) --no-print-directory $(PYTHON_TARGET),:)
	@$(if $(CLIENT_TARGETS),$(MAKE) --no-print-directory $(if $(CLIENT_JOBS),-j$(CLIENT_JOBS)) $(CLIENT_TARGETS),:)

# Every suite, whatever the change: what CI runs when a change can reach all of them, and what to run before handing
# work over.
check-all:
	@$(MAKE) --no-print-directory python
	@$(MAKE) --no-print-directory $(if $(CLIENT_JOBS),-j$(CLIENT_JOBS)) client vscode gateway-ui

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
# the wheel ships whatever is in packages/zettcode-tui/src/zettcode/tui/themes. Nothing checks the two agree, so run it
# after a change and look at `git status`.
themes:
	$(UV) run --no-sync python docs/scripts/palette_gallery.py --export-themes packages/zettcode-tui/src/zettcode/tui/themes
	@git status --short packages/zettcode-tui/src/zettcode/tui/themes

# The global hooksPath delegates to .git/hooks, so a local copy is what runs.
hooks:
	install -m 755 .githooks/pre-commit .git/hooks/pre-commit
	@echo "installed .git/hooks/pre-commit (mypy blocks the commit)"

FORCE:

demos:
	$(UV) run --no-sync python -m zettcode.tui.gallery --list

# An explicit target beats the demo-% pattern rule below, which is what lets a
# demo live outside the framework gallery.
demo-thinking:
	$(UV) run --no-sync python -m zettcode.app.ui.demo

demo:
	$(UV) run --no-sync python -m zettcode.tui.gallery

demo-all:
	$(UV) run --no-sync python -m zettcode.tui.gallery --print

demo-%: FORCE
	$(UV) run --no-sync python -m zettcode.tui.gallery $*

# Performance probes; see packages/zettcode/perf/README.md for flags and methodology.
perf:
	cd packages/zettcode && $(UV) run --no-sync python -m perf.frame_stages

perf-scaling:
	cd packages/zettcode && $(UV) run --no-sync python -m perf.scaling

perf-store:
	cd packages/zettcode && $(UV) run --no-sync python -m perf.store

perf-profile:
	cd packages/zettcode && $(UV) run --no-sync python -m perf.profile --scenario stream

perf-startup:
	cd packages/zettcode && $(UV) run --no-sync python -m perf.startup --pty

perf-exit:
	cd packages/zettcode && $(UV) run --no-sync python -m perf.exit --pty

perf-imports:
	cd packages/zettcode && $(UV) run --no-sync python -m perf.imports
