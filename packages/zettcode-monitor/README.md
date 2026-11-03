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

ZettCode carries this plugin as an extra, so one command installs both into the same environment:

    pip install "zettcode[monitor]"

or, with `uv tool`:

    uv tool install "zettcode[monitor]"

`pip install zettcode-monitor` beside an installed ZettCode is the same thing, for a program that pins or vendors its
plugins itself. Restart afterwards, and `/monitor` is there.

It runs on ZettCode 0.3 and later (`zettcode>=0.3,<0.4`): the plugin API it is built on — `PluginContext`,
`TuiPlugin` and the three groups — is the one that line introduced, while the 0.2 line still spells it
`TerminalPlugin` / `TerminalContainer`. The 0.1.1 release on PyPI is the one for that older API: it declares
`zettcode>=0.1.11,<0.3` and runs beside a 0.2.x release. From a checkout of this repository:

    uv tool install --force --with ./packages/zettcode-monitor zettcode

## Releasing

The version is `__version__` in `src/zettcode_monitor/__init__.py`. Set it, commit, then tag and push (the tag names
the version you just set):

    git tag monitor-v0.2.1
    git push origin monitor-v0.2.1

`.github/workflows/release-packages.yml` releases every plugin in this repository, this one included: it reads the
version from the package and asks PyPI, so **a version PyPI already has is skipped** rather than failing, and
re-pushing a tag whose version is already published succeeds without publishing anything. The tag is
`<name>-v<version>`, where the name is `monitor` (the plugin's entry-point name) or `zettcode-monitor` (its
directory); it is separate from zettcode's `v*` tag. Running the workflow by hand releases the same way, and ticking
`all` with no package named releases every plugin whose version PyPI does not have. The first publish needs the
`zettcode-monitor` project name to be free on PyPI.

The workflow installs `./zettcode` and this plugin from the same checkout and runs the tests on Python 3.10 and 3.15,
so tag this only from a commit whose `zettcode` version the plugin's `zettcode>=0.3,<0.4` allows.

When ZettCode starts a new line — 0.4, say — publish this plugin **first**, with its `zettcode` range widened to allow
both lines (`>=0.3,<0.5`), and only then release the new ZettCode whose `monitor` extra names it. The other order
leaves a window in which `pip install "zettcode[monitor]"` cannot resolve, because the extra would name a plugin that
does not accept the version being installed.

## Test

The plugin is a member of this repository's uv workspace, so it is developed and tested in the one environment the
workspace syncs. From the repository root:

    make test                                       # the program and every plugin
    uv run pytest packages/zettcode-monitor/tests   # this plugin alone
