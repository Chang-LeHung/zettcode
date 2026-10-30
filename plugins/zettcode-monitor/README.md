# zettcode-monitor

A ZettCode plugin. It adds `/monitor`.

- `/monitor` opens a panel in the style of `/statusline`: a **Recording** switch, an **Images** switch and an
  **Export** row. `↑ ↓` moves, `← →` and `space` set the marked switch, `enter` saves both switches and closes (on
  the **Export** row it writes the report first, saves them too, and closes), and `esc` closes without saving. The
  command takes no arguments and has no subcommands.
- Every session starts with recording off.
- Export writes an HTML report to `zettcode-monitor-<id8>.html` in the workspace.
- Images are off by default: a record keeps only an `[image]` marker. Turn **Images** on and the data of images is
  stored and shown in the report (it makes the records much larger, since every turn repeats the whole request).

Each model call stores the full request (system prompt, messages, tools, parameters) and the full response
(text, tool calls, usage), plus its duration and any error. Every turn stores the whole request again, so
messages repeat between calls. Nothing is redacted.

Data lives in `~/.zettcode/monitor/<session-id>/`. `state.json` holds the switches and `calls.jsonl` holds
the calls. The switches are read back when a session is resumed. `ZETTCODE_MONITOR_DIR` changes the root.

## Install

    pip install zettcode-monitor

It runs on ZettCode 0.3 and later (`zettcode>=0.3,<0.4`): the plugin API it is built on — `PluginContext`,
`TuiPlugin` and the three groups — is the one that line introduced, while the 0.2 line still spells it
`TerminalPlugin` / `TerminalContainer`. The 0.1.1 release on PyPI is the one for that older API: it declares
`zettcode>=0.1.11,<0.3` and runs beside a 0.2.x release. Install it into the same environment as ZettCode, then
restart. With a `uv tool` install:

    uv tool install --force --with zettcode-monitor zettcode

From a checkout of this repository:

    uv tool install --force --with ./plugins/zettcode-monitor zettcode

ZettCode 0.3.0 has to be on PyPI before this release can be installed: until that tag exists the range names a
version pip cannot find, so the release workflow's install step fails as well.

## Releasing

The version is `__version__` in `src/zettcode_monitor/__init__.py`. Set it, commit, then tag and push:

    git tag monitor-v0.2.0
    git push origin monitor-v0.2.0

Tag this only from a commit that already sets zettcode's own version to 0.3.0: the workflow installs `./zettcode` and
this plugin from the same checkout, so a tag on the 0.2 line resolves against a zettcode the plugin's floor excludes
and fails before it builds.

`.github/workflows/release-monitor.yml` checks the tag against the version, runs the tests, builds, and publishes with
the same `PYPI_API_TOKEN` secret as zettcode. The `monitor-v*` tag is separate from zettcode's `v*` tag. The first
publish needs the `zettcode-monitor` project name to be free on PyPI.

## Test

Run this from `plugins/zettcode-monitor`:

    PYTHONPATH=src <zettcode-venv>/bin/python -m pytest tests

This package is not a member of the root uv workspace, so `make check` does not cover it.
