"""The bottom panel that offers a newer release."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from ....tui import SEPARATOR, ListItem, ListPage
from ....update import display_command

#: Row values the page hands back through :meth:`UpdatePage.chosen`.
UPGRADE = "upgrade"
SKIP = "skip"
LATER = "later"


class UpdatePage(ListPage):
    """The available version, and the three things a reader can do about it.

    Shape::

        ZettCode 0.1.3 is available, you have 0.1.2
          > Upgrade now        uv tool upgrade zettcode
            Skip this version  not asked about 0.1.3 again
            Not now            asked again next time
        enter select \u00b7 esc not now

    The command is part of the row, not a footnote: an upgrade installs into
    the environment this process was started from, and seeing which one is
    about to run is what makes that safe to accept. The two ways of saying no
    are kept apart on purpose — one is about this version, the other about this
    moment — and Escape takes the gentler one. The page only reports the choice;
    the shell acts on it.
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
            on_choice: Receives :data:`UPGRADE`, :data:`SKIP` or :data:`LATER`;
                Escape asks again next time.
        """
        super().__init__(
            [
                ListItem(UPGRADE, "Upgrade now", display_command(command)),
                ListItem(SKIP, "Skip this version", f"not asked about {latest} again"),
                ListItem(LATER, "Not now", "asked again next time"),
            ],
            title=f"ZettCode {latest} is available, you have {current}",
            footer=f"enter select {SEPARATOR} esc not now",
            on_select=lambda item: on_choice(str(item.value)),
            on_cancel=lambda: on_choice(LATER),
        )
