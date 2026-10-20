# Releasing

`zettcode` is published from this repository to PyPI by
`.github/workflows/release.yml`. The repository is a uv workspace: the agent is
`zettcode/`, the HTTP server is `zettcode-server/`. A `v*` tag publishes the agent;
the server has its own version and its own tag, `zettcode-server-v*`, which
`.github/workflows/release-server.yml` publishes and neither tag publishes the other.

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
   example `0.1.1`) and commit it.
2. Tag and push:

   ```bash
   git tag v0.1.1
   git push origin main
   git push origin v0.1.1
   ```

3. The workflow builds the sdist and wheel of the agent, verifies the tag matches
   its project version, publishes to PyPI, and then opens a GitHub release with
   generated notes.

A manual `workflow_dispatch` run only builds and uploads the artifacts;
publishing and the GitHub release both require a tag push.

## Cutting a server release

The VS Code extension installs `zettcode-server` from PyPI, so the server has to be
there for the extension to work on a machine that has never seen this repository.

1. Keep the `zettcode>=` floor in `zettcode-server/pyproject.toml` at the released
   agent whose SDK it was built against, then set the version in
   `zettcode-server/src/zettcode_server/__init__.py`.
2. Tag with the server's own prefix, so the agent's workflow is not triggered:

   ```bash
   git tag zettcode-server-v0.1.0
   git push origin main
   git push origin zettcode-server-v0.1.0
   ```

The workflow builds only the server, checks the tag against its version, publishes,
and opens a GitHub release. The same `PYPI_API_TOKEN` is used, so it has to cover both
projects — a project-scoped token for `zettcode` alone will not publish this one.

## CI

`.github/workflows/ci.yml` runs on every push to `main` and on every pull
request: Ruff format and lint checks, mypy, both pytest suites, and a packaging
job that builds the wheels and runs `zettcode --help` and `zettcode-server --help`
from them so a console script cannot silently break.
