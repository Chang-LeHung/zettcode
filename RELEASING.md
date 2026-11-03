# Releasing

`zettcode` is published from this repository to PyPI by
`.github/workflows/release.yml`. The repository is a uv workspace:
`zettcode/` is the terminal agent and its HTTP server, and `packages/*` are the
plugins published on their own lines. One `v*` tag publishes the program — both
console scripts, one version — and the plugins are released from
`.github/workflows/release-packages.yml`, below.

The gateway's web page is built from `clients/gateway` into `zettcode/src/zettcode/gateway/static`. That output is not
in git: the release workflow (and `make build` / `make smoke`) builds it with Node 20+ before the wheel is made, and
`artifacts` in `zettcode/pyproject.toml` puts it in the wheel. Build a release by hand with `make build`, not with a bare
`uv build`, or the wheel will have no page.

## One-time setup

1. Create the repository secret `PYPI_API_TOKEN` under **Settings → Secrets and
   variables → Actions** with a PyPI API token that may publish every project released from here: `zettcode` and each
   plugin in `packages/`. A token scoped to one PyPI project cannot publish the others, so this has to be an
   account-scoped token — or one secret per project, and a line in the workflows choosing it. The workflows read
   exactly this name.
2. Optional: add a `pypi` environment under **Settings → Environments** and
   require reviewers there if you want a manual approval before publishing. Both
   workflows publish through that environment.

Alternatively, `release.yml` can use PyPI Trusted Publishing instead of the token: drop its `password:` input, which
leaves the `id-token: write` the job already asks for as the way in. `release-packages.yml` publishes with
`UV_PUBLISH_TOKEN`, so a trusted-publishing setup there needs that job to gain `permissions: {id-token: write}` and
`uv publish --trusted-publishing automatic` in place of the token.

## Cutting a release

1. Make sure the `zett-agent` range in `zettcode/pyproject.toml` still covers the release
   you depend on — raise its floor when a newer zett-agent is what you built
   against — then set the final version in `zettcode/src/zettcode/__init__.py` (for
   example `0.1.11`) and commit it.
2. Regenerate the terminal preview: the header of `docs/public/terminal.svg` names
   the version, so a committed bump that leaves it alone fails
   `test_docs.py::test_published_brand_assets_match_the_shared_terminal_pixels`
   (CI runs it on every pull request).

   ```bash
   uv run python docs/scripts/render_terminal.py
   ```

   Do not pass `--logo-output` for this: the site's logo is the brand mark, and the
   script's own mark is a different drawing.
3. If the release moves the `monitor` extra (`zettcode/pyproject.toml`), publish its plugin
   first: `zettcode-monitor` with a `zettcode` range that allows the old line and the new
   one, so it installs against both. `make smoke` installs the built wheel with `[monitor]`
   and fails if the extra cannot be resolved or the plugin does not register its command.
4. Tag and push:

   ```bash
   git tag v0.1.11
   git push origin main
   git push origin v0.1.11
   ```

5. The workflow builds the sdist and wheel, verifies the tag matches its project
   version, publishes to PyPI, and then opens a GitHub release with generated
   notes. `pip install zettcode` then writes both `zettcode` and
   `zettcode-server`, which is the package the VS Code extension installs for
   itself.

A manual `workflow_dispatch` run only builds and uploads the artifacts;
publishing and the GitHub release both require a tag push.

## The plugins in `packages/`

`packages/` holds the plugin distributions this repository publishes — `zettcode-monitor` and `zettcode-recap` today.
Each is a separate PyPI project with its own version and its own tag, and each is a member of this workspace: they
share `uv.lock`, the root tooling and the suite `make check` runs, and are still published on their own schedule.

One workflow releases all of them, `.github/workflows/release-packages.yml`, so a new directory under `packages/`
needs no workflow of its own. It reads each package's `pyproject.toml` — the name, and the version hatchling reads
from `__init__.py` — and asks PyPI. **A version PyPI already has is skipped**: the run reports it and succeeds instead
of failing on a duplicate upload, so re-running a release or re-pushing a tag is a no-op. Two ways to start it:

1. Push a tag named `<name>-v<version>`, where `<name>` is the directory or the plugin name the package's
   `zettcode.plugins` entry point declares: `monitor-v0.3.0` and `zettcode-monitor-v0.3.0` both name the monitor. The
   tag's version must be the version in the commit it points at, and one tag releases one package.

   ```bash
   git tag monitor-v0.3.0
   git push origin monitor-v0.3.0
   ```

2. Run the workflow by hand. A directory in `package` releases that one; tick `all` and leave `package` empty and
   every package whose version PyPI does not have yet is released, which is how several bumps go out in one run. A
   manual run that names neither is refused, so a bare "Run workflow" publishes nothing by accident.

Either way, the package's tests run on Python 3.10 and 3.15 from the paths, beside the `zettcode` in the same
checkout — the plugin is tested the way a reader installs it, with the test dependencies its own `dev` group
declares. Then the distributions are built, their metadata is checked, and each is published with
`PYPI_API_TOKEN`, so the one-time setup above covers them.

Two rules the checkouts cannot enforce on their own — the first one now fails in the plugin's own suite, and only
its ordering is left to whoever releases:

- **A new line of `zettcode` needs the plugin published first.** When the program moves to 0.4, widen the plugin's
  `zettcode` range to allow both lines (`>=0.3,<0.5`) — the plugin's suite fails until you do, because the range is
  checked against the version in this checkout — and publish that plugin **before** the release whose extra names
  it. Only the order is unchecked, and the wrong one leaves a window in which `pip install "zettcode[monitor]"`
  cannot resolve.
- **Raise a plugin's `zettcode` floor when it starts using newer API, and say so in its `README.md`.** No test can see
  this: the release run and the plugin's own suite both run against this checkout, which has whatever the plugin just
  started calling, so a floor that is too low publishes and only fails later, in a reader's environment.

## CI

`.github/workflows/ci.yml` runs on every push to `main` and on every pull
request: Ruff format and lint checks, mypy, the pytest suites — the program's and
each plugin's, since the workspace holds all of them — and a packaging job that
builds the wheel and runs `zettcode --help` and `zettcode-server --help` from it
so a console script cannot silently break.
