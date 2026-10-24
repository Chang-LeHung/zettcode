"""The frame the command line paints before the application exists."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from zettcode.app.agent.conversation.text import compact_path as agent_compact_path
from zettcode.app.ui import labels
from zettcode.app.ui.boot import boot_tree
from zettcode.app.ui.labels import compact_path
from zettcode.tui import TuiApp

WIDTH = 70
HEIGHT = 12


def _cells(app: TuiApp) -> list[list]:
    """Return every rendered cell, laid out by row."""
    app.resize(WIDTH, HEIGHT)
    app.mount()
    return [list(row) for row in app.render().cells]


def _rows(app: TuiApp) -> list[str]:
    """Return every rendered row as text."""
    return ["".join(cell.character for cell in row) for row in _cells(app)]


def _config(tmp_path: Path) -> Path:
    """Write the config the shell and the boot frame both read, and return its path."""
    path = tmp_path / "config.toml"
    path.write_text(
        '[[models]]\nmodel = "m"\ntoken = "t"\n\n[skills]\nenabled = false\n\n[mcp]\nenabled = false\n',
        encoding="utf-8",
    )
    return path


def _shell(tmp_path: Path, monkeypatch) -> TuiApp:
    """Build the real shell around a throwaway workspace, without a provider."""
    path = _config(tmp_path)
    monkeypatch.setenv("ZETTCODE_CONFIG", str(path))
    from zettcode.app.agent.agent import TerminalAgent
    from zettcode.app.ui import ZettCodeApp
    from zettcode.cli import resolve_config

    app = ZettCodeApp(TerminalAgent.preview(resolve_config(["-w", str(tmp_path)])), auto_theme=False)
    return app.app


def test_every_row_the_boot_frame_draws_is_the_row_the_shell_draws(tmp_path: Path, monkeypatch):
    """The swap may only fill rows in, never move or restyle what is on screen.

    Every cell the placeholder draws has to be the cell the shell draws in the
    same place; the shell may fill the rest in. A border it does not draw, one
    row more than its layout reserves, or a character off by one column shows up
    as the interface flashing when the placeholder is replaced. The header's
    right side is part of that now that the first frame names the model too.
    """
    early = _cells(
        TuiApp(
            boot_tree(tmp_path.resolve(), model=labels.model_name(_config(tmp_path))),
            width=WIDTH,
            height=HEIGHT,
        )
    )
    settled = _cells(_shell(tmp_path, monkeypatch))

    assert len(early) == len(settled) == HEIGHT
    for index, row in enumerate(early):
        for column, cell in enumerate(row):
            if cell.character.strip():
                assert cell == settled[index][column], f"cell {column},{index} does not survive the swap"


def test_the_boot_frame_names_the_model_and_effort_the_shell_will_show(tmp_path: Path):
    """The header is complete from the first frame, not a tenth of a second later."""
    config = _config(tmp_path)
    rows = _rows(TuiApp(boot_tree(tmp_path.resolve(), model=labels.model_name(config)), width=WIDTH, height=HEIGHT))

    assert "m \u00b7 medium" in rows[0], rows[0]


def test_the_boot_frames_labels_come_without_the_application(tmp_path: Path, monkeypatch):
    """Naming the model costs a file read, not the settings' import graph.

    The point of the frame the command line paints is that it is drawn before
    this program's modules are imported, so the label is read from the file
    directly. The probe below fails if the header ever learns to name the model by
    importing the settings, the runtime, or a provider SDK on that path.
    """
    config = _config(tmp_path)
    monkeypatch.setenv("ZETTCODE_CONFIG", str(config))
    script = "\n".join(
        [
            "import sys",
            "from pathlib import Path",
            "from zettcode.app.ui.boot import boot_tree",
            "from zettcode.app.ui.labels import model_name",
            "from zettcode.paths import config_path",
            "from zettcode.tui import TuiApp",
            "app = TuiApp(boot_tree(Path(sys.argv[1]).resolve(), model=model_name(config_path())), width=70, height=12)",
            "app.mount()",
            "rows = [''.join(cell.character for cell in row) for row in app.render().cells]",
            "print('m \u00b7 medium' in rows[0])",
            "print('zett_agent' in sys.modules, 'zettcode.config' in sys.modules)",
        ]
    )

    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["True", "False False"]


@pytest.mark.parametrize(
    "body",
    [
        None,  # no file at all
        "[[models]]\n",  # a table that names no model
        "not toml at all",  # a file that does not parse
        'models = "m"\n',  # a shape the settings would refuse
    ],
)
def test_a_config_the_boot_frame_cannot_read_leaves_the_header_right_side_empty(tmp_path: Path, body: str | None):
    """Nothing to name means the shell fills the corner in, not a guess at it."""
    path = tmp_path / "config.toml"
    if body is not None:
        path.write_text(body, encoding="utf-8")

    assert labels.model_name(path) is None
    rows = _rows(TuiApp(boot_tree(tmp_path.resolve(), model=labels.model_name(path)), width=WIDTH, height=HEIGHT))
    assert "zettcode" in rows[0], "the left side is still the shell's"


def test_the_banner_and_the_composer_share_the_first_frame():
    """The mark and the box arrive together; deferring either is what the reader sees."""
    early = _rows(TuiApp(boot_tree(Path("/tmp")), width=WIDTH, height=HEIGHT))
    composer = next(index for index, row in enumerate(early) if "\u203a" in row)
    banner = [index for index, row in enumerate(early) if "\u2588" in row or "\u2580" in row or "\u2584" in row]

    assert banner, "the banner is not in the first frame"
    assert max(banner) < composer, "the banner is drawn above the composer"


def test_the_header_text_has_one_definition_per_layer():
    """The UI layer owns the header's text; the agent's copy must not drift.

    Both are reachable from the shell, and the boot frame may only import the
    light one, so the two are compared here rather than merged behind a heavier
    import than the first frame can afford.
    """
    long = Path("/tmp") / ("\u6df1" * 30)
    for path in (Path("/tmp"), Path.home() / "projects" / "api", long):
        for limit in (10, 38, None):
            assert compact_path(path, limit=limit) == agent_compact_path(path, limit=limit)


def test_a_resumed_session_does_not_paint_the_banner():
    """A conversation is about to arrive, so the banner would only be replaced."""
    early = _rows(TuiApp(boot_tree(Path("/tmp"), resuming=True), width=WIDTH, height=HEIGHT))
    symbols = [row for row in early if "\u2588" in row or "\u2580" in row or "\u2584" in row]

    assert symbols == []
    assert any("\u203a" in row for row in early), "the composer is still the first thing up"


def test_the_first_frames_palette_costs_a_file_read_not_the_settings(tmp_path: Path, monkeypatch):
    """The palette is read from the config file directly, like the model name beside it.

    Building the application to learn which palette to paint in is the tenth of a second this frame exists to
    avoid, and it would also import the agent runtime before the frame is on screen.
    """
    config = _config(tmp_path)
    config.write_text(config.read_text(encoding="utf-8") + '\n[ui]\ntheme = "nord"\n', encoding="utf-8")
    monkeypatch.setenv("ZETTCODE_CONFIG", str(config))
    script = "\n".join(
        [
            "import sys",
            "from zettcode import cli",
            "theme = cli.boot_theme()",
            "print(theme.name, theme.background)",
            "print('zettcode.config' in sys.modules, 'zett_agent' in sys.modules)",
        ]
    )

    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["nord #2e3440", "False False"]
