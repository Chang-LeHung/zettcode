# Releasing

`zettcode` is published from this repository to PyPI by
`.github/workflows/release.yml`. The repository is a uv workspace of one package:
the terminal agent and its HTTP server are `zettcode/`, and one `v*` tag publishes
both console scripts. There is no second project and no second tag.

## One-time setup

1. Create the repository secret `PYPI_API_TOKEN` under **Settings → Secrets and
   variables → Actions** with a PyPI API token that may publish the `zettcode`
   project. The workflow reads exactly that name.
2. Optional: add a `pypi` environment under **Settings → Environments** and
   require reviewers there if you want a manual approval before publishing.

Alternatively, drop the `password:` input from the publish step and configure
PyPI Trusted Publishing for this repository instead; the workflow already
requests `id-token: write`.

## Cutting a release

1. Make sure the `zett-agent` range in `zettcode/pyproject.toml` still covers the release
   you depend on — raise its floor when a newer zett-agent is what you built
   against — then set the final version in `zettcode/src/zettcode/__init__.py` (for
   example `0.1.11`) and commit it.
2. Tag and push:

   ```bash
   git tag v0.1.11
   git push origin main
   git push origin v0.1.11
   ```

3. The workflow builds the sdist and wheel, verifies the tag matches its project
   version, publishes to PyPI, and then opens a GitHub release with generated
   notes. `pip install zettcode` then writes both `zettcode` and
   `zettcode-server`, which is the package the VS Code extension installs for
   itself.

A manual `workflow_dispatch` run only builds and uploads the artifacts;
publishing and the GitHub release both require a tag push.

## The monitor plugin

`plugins/zettcode-monitor` is a separate PyPI project, `zettcode-monitor`, with its own version and its own tag.
It is not a member of the uv workspace, so `make check` does not cover it; its tests run in the release workflow.

1. Set `__version__` in `plugins/zettcode-monitor/src/zettcode_monitor/__init__.py` and commit it.
2. Tag and push `monitor-v<version>` (for example `monitor-v0.1.0`). `.github/workflows/release-monitor.yml` checks the
   tag against the version, runs the tests on Python 3.10 to 3.15, builds, and publishes with the same
   `PYPI_API_TOKEN` secret.

The plugin depends on `zettcode>=0.1.11,<0.2`, the first release with `zettcode.app.plugins`; publish that release
first, because until it exists `pip install zettcode-monitor` has nothing to resolve against.

## CI

`.github/workflows/ci.yml` runs on every push to `main` and on every pull
request: Ruff format and lint checks, mypy, the pytest suite, and a packaging
job that builds the wheel and runs `zettcode --help` and `zettcode-server --help`
from it so a console script cannot silently break.
