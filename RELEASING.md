# Releasing

The program and the distributions it is made of are published from this repository to PyPI by
`.github/workflows/release.yml`. The repository is a uv workspace under a PEP 420 `zettcode` namespace, and
`packages/` holds every distribution: the program (`zettcode`, the one a reader installs and the one that writes both
console scripts), the parts it is built from, and the plugins, which are released on their own lines by
`.github/workflows/release-packages.yml`. One `v<version>` tag publishes the program and its parts together — one
version, read from one file — in the dependency order `.github/scripts/release_order.py` computes from the
packages' own `pyproject.toml` files (nothing keeps that list; `make order` writes it to `packages/order.txt`,
which is generated and not in git).

The gateway's web page is built from `clients/gateway` into `packages/zettcode-gateway/src/zettcode/gateway/static`. That output is not
in git: the release workflow (and `make build` / `make smoke`) builds it with Node 20+ before the wheel is made, and
`artifacts` in `packages/zettcode-gateway/pyproject.toml` puts it in that wheel. Build a release by hand with
`make build`, not with a bare `uv build`, or the wheel will have no page.

## One-time setup

1. Create the repository secret `PYPI_API_TOKEN` under **Settings → Secrets and
   variables → Actions** with a PyPI API token that may publish every project released from here — the nine
   nine distributions the program is made of and the two plugins, eleven projects. A token scoped to one PyPI
   project cannot publish the others, so this has to be an account-scoped token — or one secret per project, and a
   line in the workflows choosing it. The workflows read exactly this name.
2. Optional: add a `pypi` environment under **Settings → Environments** and
   require reviewers there if you want a manual approval before publishing. Both
   workflows publish through that environment.

Alternatively, either workflow can use PyPI Trusted Publishing instead of the token. Both publish with
`UV_PUBLISH_TOKEN` today, so the change is the same in each: add `permissions: {id-token: write}` to the publish
job, drop the `UV_PUBLISH_TOKEN` environment entry, and pass `uv publish --trusted-publishing automatic` in place
of the token. PyPI then has to be configured with a trusted publisher for every project the run publishes —
eleven of them for `release.yml`'s tag — which is why the token is what this repository uses.

## Cutting a release

1. Make sure the `zett-agent` range in `packages/zettcode-engine/pyproject.toml` still covers the release
   you depend on — raise its floor when a newer zett-agent is what you built
   against — then set the final version in `packages/zettcode-engine/src/zettcode/version.py` (for
   example `0.1.11`) and commit it. Every distribution reads that one file; there is nothing else to bump.
2. Regenerate the terminal preview: the header of `docs/public/terminal.svg` names
   the version, so a committed bump that leaves it alone fails
   `test_docs.py::test_published_brand_assets_match_the_shared_terminal_pixels`
   (CI runs it on every pull request).

   ```bash
   uv run python docs/scripts/render_terminal.py
   ```

   Do not pass `--logo-output` for this: the site's logo is the brand mark, and the
   script's own mark is a different drawing.
3. If the release moves an extra (`packages/zettcode/pyproject.toml` names `monitor` and `recap`), publish its
   plugin first: the plugin's `zettcode-plugin-api` range has to allow the old line and the new one, so it
   installs against both. `make smoke` installs the built program wheel with both extras and fails if an extra
   cannot be resolved or the plugin does not register its command.
4. Tag and push:

   ```bash
   git tag v0.1.11
   git push origin main
   git push origin v0.1.11
   ```

5. The workflow builds every distribution the generator orders, in that order, verifies the tag matches the
   version, publishes them to PyPI, and then opens a GitHub release with generated notes. `pip install
   zettcode` then writes both `zettcode` and
   `zettcode-server`, which is the package the VS Code extension installs for
   itself.

A manual `workflow_dispatch` run only builds and uploads the artifacts;
publishing and the GitHub release both require a tag push.

**The first release of several new projects can be throttled.** PyPI allows a personal account **four new project
names in twenty-four hours** (ten for an organization; the published docs say twenty an hour, and the wall is lower),
counted as a sliding window, and **every attempt counts, a rejected one included**. A release that creates more than
that — this one creates eight — therefore stops part-way with `429 Too many new projects created`. The publish step
waits a minute before creating a name PyPI does not have and stops the run when an upload fails rather than retrying
into the quota, which would only push the window out. The job is idempotent: `uv publish --check-url` skips every
file PyPI already has, so **one re-run about a day later** (Actions → the run → "Re-run failed jobs") publishes
whatever is left, in the same order. If the whole set has to go out at once, ask for an increase at
https://github.com/pypi/support/issues/new/choose before the release; it usually takes a day or two.

## The plugins in `packages/`

`packages/` holds the plugin distributions this repository publishes — `zettcode-monitor` and `zettcode-recap` today.
Each is a separate PyPI project with its own version and its own tag, and each is a member of this workspace: they
share `uv.lock`, the root tooling and the suite `make check` runs, and are still published on their own schedule.
A plugin depends on `zettcode-plugin-api` and imports nothing else of ours; the rest of `packages/` is the program
and its parts, released by `release.yml` above.

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

Either way, the package's tests run on Python 3.10 and 3.15 from the paths, beside the program in the same checkout
— the plugin is tested the way a reader installs it, with the test dependencies its own `dev` group declares. Then
the distributions are built, their metadata is checked, and each is published with `PYPI_API_TOKEN`, so the
one-time setup above covers them.

Two rules the checkouts cannot enforce on their own — the first one now fails in the plugin's own suite, and only
its ordering is left to whoever releases:

- **A new line of ZettCode needs the plugin published first.** When the program moves to 0.4, widen the plugin's
  `zettcode-plugin-api` range to allow both lines (`>=0.3,<0.5`) — the plugin's suite fails until you do, because
  the range is checked against the version in this checkout — and publish that plugin **before** the release whose
  extra names it. Only the order is unchecked, and the wrong one leaves a window in which
  `pip install "zettcode[monitor]"` cannot resolve.
- **Raise a plugin's `zettcode` floor when it starts using newer API, and say so in its `README.md`.** No test can see
  this: the release run and the plugin's own suite both run against this checkout, which has whatever the plugin just
  started calling, so a floor that is too low publishes and only fails later, in a reader's environment.

## CI

`.github/workflows/ci.yml` runs on every push to `main` and on every pull
request: Ruff format and lint checks, mypy, the pytest suites — the program's and
each plugin's, since the workspace holds all of them — and a packaging job that
builds the wheel and runs `zettcode --help` and `zettcode-server --help` from it
so a console script cannot silently break.
