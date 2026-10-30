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

It runs on ZettCode 0.1.11 and later, across the 0.1 and the 0.2 line (`zettcode>=0.1.11,<0.3`): the plugin API it is
built on is the same in both, and 0.1.1 is the release that says so — 0.1.0 stopped at `<0.2` and could not be
installed beside a 0.2.x release. ZettCode 0.3 is a different plugin API, and the plugin for it is 0.2.0 or later.
Install it into the same environment as ZettCode, then restart. With a `uv tool` install:

    uv tool install --force --with zettcode-monitor zettcode

From a checkout of this repository:

    uv tool install --force --with ./plugins/zettcode-monitor zettcode

## Releasing

The version is `__version__` in `src/zettcode_monitor/__init__.py`. Set it, commit, then tag and push:

    git tag monitor-v0.1.1
    git push origin monitor-v0.1.1

`.github/workflows/release-monitor.yml` checks the tag against the version, runs the tests, builds, and publishes with
the same `PYPI_API_TOKEN` secret as zettcode. The `monitor-v*` tag is separate from zettcode's `v*` tag. The first
publish needs the `zettcode-monitor` project name to be free on PyPI.

## Test

Run this from `plugins/zettcode-monitor`:

    PYTHONPATH=src <zettcode-venv>/bin/python -m pytest tests

This package is not a member of the root uv workspace, so `make check` does not cover it.
