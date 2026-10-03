"""A widget a shell can present on its own, full screen or as a panel."""

from __future__ import annotations

from ..core.widget import Widget


class Page(Widget):
    """A widget meant to be presented as a whole screen or a bottom panel.

    A shell stacks a page over the conversation and reads
    :attr:`overlay_rows` to decide its footprint. The framework itself never
    reads the hint: it is the contract between a page and the shell that
    presents it. Subclasses supply the content, the way :class:`ListPage` does.
    """

    #: Rows the shell should give this page when it presents it as a bottom
    #: panel; ``None`` asks for the whole screen.
    overlay_rows: int | None = None
