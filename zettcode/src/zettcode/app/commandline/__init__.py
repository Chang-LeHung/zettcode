"""Running a command from inside the program: the history it offers, the words Tab completes, the process.

None of it draws anything. The screen is :class:`~zettcode.tui.ConsolePanel`, and
:mod:`zettcode.app.ui.widgets.bash_page` joins the two.
"""

from __future__ import annotations

from .completion import ShellCompleter
from .history import (
    SOURCES,
    BashHistory,
    CommandHistory,
    FishHistory,
    HistorySource,
    PlainHistory,
    PowerShellHistory,
    ZshHistory,
)
from .runner import (
    CommandPromptLauncher,
    CommandRunner,
    PosixLauncher,
    PowerShellLauncher,
    RunResult,
    ShellLauncher,
    detect_launcher,
)

__all__ = [
    "SOURCES",
    "BashHistory",
    "CommandHistory",
    "CommandPromptLauncher",
    "CommandRunner",
    "FishHistory",
    "HistorySource",
    "PlainHistory",
    "PosixLauncher",
    "PowerShellHistory",
    "PowerShellLauncher",
    "RunResult",
    "ShellCompleter",
    "ShellLauncher",
    "ZshHistory",
    "detect_launcher",
]
