"""The bottom panel that offers a newer release."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from ....tui import SEPARATOR, ListItem, ListPage
from ....update import display_command

#: Row values the page hands back through :meth:`UpdatePage.chosen`.
UPGRADE = "upgrade"
SKIP = "skip"


class UpdatePage(ListPage):
    """The available version, and the two things a reader can do about it.

    Shape::

        ZettCode 0.1.3 is available, you have 0.1.2
          > Upgrade now           uv tool upgrade zettcode
            Skip this version     asked again when a newer one lands
        enter select \u00b7 esc skip

    The command is part of the row, not a footnote: an upgrade installs into
    the environment this process was started from, and seeing which one is
    about to run is what makes that safe to accept. The page only reports the
    choice; the shell runs it.
    """

    def __init__(
        self,
        latest: str,
        current: str,
        command: Sequence[str],
        *,
        on_choice: Callable[[str], None],
    ) -> None:
        """Build the panel for one offered version.

        Args:
            latest: Version the index reported, shown in the title.
            current: Version running now, shown beside it.
            command: Argv the upgrade would run, shown under its row.
            on_choice: Receives :data:`UPGRADE` or :data:`SKIP`; Escape skips.
        """
        super().__init__(
            [
                ListItem(UPGRADE, "Upgrade now", display_command(command)),
                ListItem(SKIP, "Skip this version", f"asked again when a newer one than {latest} lands"),
            ],
            title=f"ZettCode {latest} is available, you have {current}",
            footer=f"enter select {SEPARATOR} esc skip",
            on_select=lambda item: on_choice(str(item.value)),
            on_cancel=lambda: on_choice(SKIP),
        )
