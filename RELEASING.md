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
   variables → Actions** with a PyPI API token that may publish every project released from here — every
   distribution `make order` lists and the two plugins. A token scoped to one PyPI
   project cannot publish the others, so this has to be an account-scoped token — or one secret per project, and a
   line in the workflows choosing it. The workflows read exactly this name.
2. Optional: add a `pypi` environment under **Settings → Environments** and
   require reviewers there if you want a manual approval before publishing. Both
   workflows publish through that environment.

Alternatively, either workflow can use PyPI Trusted Publishing instead of the token. Both publish with
`UV_PUBLISH_TOKEN` today, so the change is the same in each: add `permissions: {id-token: write}` to the publish
job, drop the `UV_PUBLISH_TOKEN` environment entry, and pass `uv publish --trusted-publishing automatic` in place
of the token. PyPI then has to be configured with a trusted publisher for every project the run publishes —
ten of them for `release.yml`'s tag — which is why the token is what this repository uses.

## Cutting a release

1. Make sure the `zett-agent` range in `packages/zettcode-engine/pyproject.toml` still covers the release
   you depend on — raise its floor when a newer zett-agent is what you built
   against — then move every distribution to the new version in one command:

   ```bash
   make version VERSION=0.5.0
   ```

   It writes `packages/zettcode-engine/src/zettcode/version.py`, each plugin's `__init__.py` (a plugin keeps a
   literal rather than reading the engine's file, so its sdist builds outside this checkout), and every requirement
   on one of our own distributions, which becomes `>=0.5.0,<0.6`. Then it runs `uv lock`, because a floor is part of
   what the lock resolved. Commit everything it touched: `.github/scripts/versions.py --check` reports any place left
   behind, and both `test_versions.py` (on every pull request) and the release workflow run it.
2. Regenerate the terminal preview: the header of `docs/public/terminal.svg` names
   the version, so a committed bump that leaves it alone fails
   `test_docs.py::test_published_brand_assets_match_the_shared_terminal_pixels`
   (CI runs it on every pull request).

   ```bash
   uv run python docs/scripts/render_terminal.py
   ```

   Do not pass `--logo-output` for this: the site's logo is the brand mark, and the
   script's own mark is a different drawing.
3. Tag and push:

   ```bash
   git tag v0.4.6
   git push origin main
   git push origin v0.4.6
   ```

4. The workflow builds every distribution the generator orders, in that order, checks that every distribution in the
   tree is on the tag's version, publishes them to PyPI, and then opens a GitHub release with generated notes.
   `pip install zettcode` then writes both `zettcode` and `zettcode-server`, which is the package the VS Code
   extension installs for itself.

5. The plugins go out at the same number, after the program — never before it. A plugin requires
   `zettcode-plugin-api>=<new>,<next>` and the program's tag is what publishes that, so the plugins cannot be
   released first; and `packages/zettcode/pyproject.toml` names them at the new version in an extra, which cannot
   resolve until they are. The window between the two steps is the only moment `pip install "zettcode[all]"` fails,
   and it is minutes. Either push one tag per plugin or run `release-packages.yml` with `all` ticked; a version PyPI
   already has is skipped, so a re-run is harmless.

   ```bash
   git tag monitor-v0.4.6 && git push origin monitor-v0.4.6
   ```

   Then check the extras resolve from PyPI, in a scratch environment so nothing from this checkout can answer for
   them (this is also what `make smoke` proves locally, from the wheels this tree builds):

   ```bash
   uv run --no-project --python 3.12 --with "zettcode[all]==0.4.6" python -c "import zettcode.monitor, zettcode.recap"
   ```

A manual `workflow_dispatch` run only builds the artifacts, unless it is started with `publish` ticked: then it uploads
them too, in the same order and with the same stop at the first failure, but with no tag and no GitHub release.
`exclude` (space separated names) leaves distributions out of that upload. Use the pair to release the parts ahead of the
program: `publish` with `exclude` set to `zettcode`, then the `v<version>` tag later, which skips what PyPI already has
and publishes `zettcode` last.

**The first release of several new projects can be throttled.** PyPI allows a personal account **four new project
names in twenty-four hours** (ten for an organization; the published docs say twenty an hour, and the wall is lower),
counted as a sliding window, and **every attempt counts, a rejected one included**. A release that creates more than
that therefore stops part-way with `429 Too many new projects created`. The number to plan with is *the names PyPI
does not have yet*, not the number of distributions — a distribution published once is no longer new — so count them
before tagging:

```sh
for name in $(python3 .github/scripts/release_order.py); do
  curl -sf "https://pypi.org/pypi/$name/json" > /dev/null || echo "new: $name"
done
```

Divide that by four to know how many days the release takes; `ceil(n / 4)` runs of the publish job, the first at the
tag and one re-run about a day after each failure. The publish step waits a minute before creating a name PyPI does not
have and stops the run when an upload fails rather than retrying into the quota, which would only push the window out.
The job is idempotent: `uv publish --check-url` skips every file PyPI already has, so a re-run (Actions → the run →
"Re-run failed jobs") publishes whatever is left, in the same order. If the whole set has to go out at once, ask for an
increase at https://github.com/pypi/support/issues/new/choose before the release; it usually takes a day or two.

**Every distribution in this repository carries the program's version**, the plugins included: a release moves all of
them with `make version`, and `.github/scripts/versions.py --check` refuses a tree where a plugin's `__version__` or a
requirement's floor disagrees. Two things follow for a release that changes the plugin contract
(`zettcode-plugin-api`): the program goes out first, because the plugins require the new contract and only its tag
publishes it; and the plugins go out immediately after, because the program's `monitor`/`recap`/`all` extras name them
at the new version. A program published ahead of its plugins has an extra that does not resolve yet — say so in the
release notes if the gap is going to be longer than a few minutes.

**A release that includes the contract move has to be 0.4.0, not 0.3.x.** A plugin released before it imports modules
(`zettcode.app.commands`, `zettcode.app.ui.widgets.panel`) that are no longer there, and both published plugins declare
`zettcode<0.4` and `zettcode-plugin-api>=0.3,<0.4`. On a 0.3.x release `pip install "zettcode[monitor]"` would resolve
that old plugin and fail at *import*, leaving only a line in `/plugins` — a patch upgrade quietly losing `/monitor` and
`/recap`. On 0.4.0 the plugins' own caps make the old ones *unresolvable* beside the new program, which is loud and
honest. `version.py` is therefore raised to 0.4.0 in the release commit, together with the plugins' new `zettcode`
and `zettcode-plugin-api` ranges (`test_structure.py` and each plugin's suite fail until they agree).

## The plugins in `packages/`

`packages/` holds the plugin distributions this repository publishes — `zettcode-monitor` and `zettcode-recap` today.
Each is a separate PyPI project with a tag of its own, published by `release-packages.yml` rather than by the program's
tag, and each carries the program's version: a plugin is built from this checkout at the same commit, and one number
for the lot is what a reader can hold in their head. Each is a member of this workspace too — they share `uv.lock`, the
root tooling and the suite `make check` runs. A plugin depends on `zettcode-plugin-api` and imports nothing else of
ours; the rest of `packages/` is the program and its parts, released by `release.yml` above.

One workflow releases all of them, `.github/workflows/release-packages.yml`, so a new directory under `packages/`
needs no workflow of its own. It reads each package's `pyproject.toml` — the name, and the version hatchling reads
from `__init__.py` — and asks PyPI. **A version PyPI already has is skipped**: the run reports it and succeeds instead
of failing on a duplicate upload, so re-running a release or re-pushing a tag is a no-op. Two ways to start it:

1. Push a tag named `<name>-v<version>`, where `<name>` is the directory or the plugin name the package's
   `zettcode.plugin` entry point declares: `monitor-v0.3.0` and `zettcode-monitor-v0.3.0` both name the monitor.
   The tag's version must be the version in the commit it points at, and one tag releases one package.

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

- **The program's tag goes first, the plugins straight after.** A plugin requires `zettcode-plugin-api>=<new>,<next>`
  and only the program's tag publishes that, so a plugin cannot go out first any more; the program's extra names the
  plugin at the new version, so the plugin cannot wait either. The gap between the two steps is minutes, and it is
  also the only window in which `pip install "zettcode[monitor]"` cannot resolve the new program.
- **Raise a plugin's `zettcode` floor when it starts using newer API, and say so in its `README.md`.** No test can see
  this: the release run and the plugin's own suite both run against this checkout, which has whatever the plugin just
  started calling, so a floor that is too low publishes and only fails later, in a reader's environment.

## CI

`.github/workflows/ci.yml` runs on every push to `main` and on every pull
request: Ruff format and lint checks, mypy, the pytest suites — the program's and
each plugin's, since the workspace holds all of them — and a packaging job that
builds the wheel and runs `zettcode --help` and `zettcode-server --help` from it
so a console script cannot silently break.
