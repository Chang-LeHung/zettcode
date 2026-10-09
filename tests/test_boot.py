"""The frame the command line paints before the application exists."""

from __future__ import annotations

from pathlib import Path

from zettcode.app.agent.rows import compact_path as agent_compact_path
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


def _shell(tmp_path: Path, monkeypatch) -> TuiApp:
    """Build the real shell around a throwaway workspace, without a provider."""
    path = tmp_path / "config.toml"
    path.write_text(
        '[[models]]\nmodel = "m"\ntoken = "t"\n\n[skills]\nenabled = false\n\n[mcp]\nenabled = false\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("ZETTCODE_CONFIG", str(path))
    from zettcode.app.agent.agent import ZettCodeAgent
    from zettcode.app.ui import ZettCodeApp
    from zettcode.cli import resolve_config

    app = ZettCodeApp(ZettCodeAgent.preview(resolve_config(["-w", str(tmp_path)])), auto_theme=False)
    return app.app


def test_every_row_the_boot_frame_draws_is_the_row_the_shell_draws(tmp_path: Path, monkeypatch):
    """The swap may only fill rows in, never move or restyle what is on screen.

    Every cell the placeholder draws has to be the cell the shell draws in the
    same place; the shell may fill the rest in. A border it does not draw, one
    row more than its layout reserves, or a character off by one column shows up
    as the interface flashing when the placeholder is replaced.
    """
    early = _cells(TuiApp(boot_tree(tmp_path.resolve()), width=WIDTH, height=HEIGHT))
    settled = _cells(_shell(tmp_path, monkeypatch))

    assert len(early) == len(settled) == HEIGHT
    for index, row in enumerate(early):
        for column, cell in enumerate(row):
            if cell.character.strip():
                assert cell == settled[index][column], f"cell {column},{index} does not survive the swap"


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
        for limit in (10, 38):
            assert compact_path(path, limit=limit) == agent_compact_path(path, limit=limit)


def test_a_resumed_session_does_not_paint_the_banner():
    """A conversation is about to arrive, so the banner would only be replaced."""
    early = _rows(TuiApp(boot_tree(Path("/tmp"), resuming=True), width=WIDTH, height=HEIGHT))
    symbols = [row for row in early if "\u2588" in row or "\u2580" in row or "\u2584" in row]

    assert symbols == []
    assert any("\u203a" in row for row in early), "the composer is still the first thing up"
