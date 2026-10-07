# Releasing

`zettcode` is published from this repository to PyPI by
`.github/workflows/release.yml`.

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

1. Make sure the `zett-agent` range in `pyproject.toml` still covers the release
   you depend on — raise its floor when a newer zett-agent is what you built
   against — then set the final version in `src/zettcode/__init__.py` (for
   example `0.1.1`) and commit it.
2. Tag and push:

   ```bash
   git tag v0.1.1
   git push origin main
   git push origin v0.1.1
   ```

3. The workflow builds the sdist and wheel, verifies the tag matches the project
   version, publishes to PyPI, and then opens a GitHub release with generated
   notes.

A manual `workflow_dispatch` run only builds and uploads the artifacts;
publishing and the GitHub release both require a tag push.

## CI

`.github/workflows/ci.yml` runs on every push to `main` and on every pull
request: Ruff format and lint checks, the pytest suite, and a packaging job that
builds the wheel and runs `zettcode --help` from that wheel so the console
script cannot silently break.
