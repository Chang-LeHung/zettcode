"""The shell's row hooks a terminal plugin can implement.

:class:`PluginUiMixin` is this application's row group: the four slots of the header and the status line. Every hook
defaults to doing nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - annotations only, so the imports stay lazy
    from .state import ShellContext, UiBuilder, UiBuilderResult, UiRegion, UiSide

#: ``(method, region, side)`` for every slot the UI mixin exposes, in paint
#: order. The method name minus its prefix is the segment name a plugin's
#: override registers under.
UI_SLOTS: tuple[tuple[str, UiRegion, UiSide], ...] = (
    ("render_header_left", "header", "left"),
    ("render_header_right", "header", "right"),
    ("render_status_left", "status", "left"),
    ("render_status_right", "status", "right"),
)


class PluginUiMixin:
    """The four shell slots a plugin can fill.

    Each method is one named slot: the header's and the status line's left and
    right sides. Override one and it is registered under that slot's name, so
    overriding the method a builtin already implements replaces that segment
    rather than adding a second one. A plugin that needs another segment beside
    the builtin's, or decides what to register from the configuration, uses
    ``ctx.tui.register_*`` in :meth:`TuiPlugin.activate`.

    The names are deliberately specific, so a plugin's own ``status`` or
    ``header`` helper cannot be mistaken for a contribution. A builder returns
    the segment, or ``(segment, True)`` to take the side over and drop what the
    segments before it painted.
    """

    def render_header_left(self, context: ShellContext) -> UiBuilderResult:
        """Return the header's left segment, or ``(segment, True)`` to take the side over."""
        return None

    def render_header_right(self, context: ShellContext) -> UiBuilderResult:
        """Return the header's right segment, or ``(segment, True)`` to take the side over."""
        return None

    def render_status_left(self, context: ShellContext) -> UiBuilderResult:
        """Return the status line's left segment, or ``(segment, True)`` to take the side over."""
        return None

    def render_status_right(self, context: ShellContext) -> UiBuilderResult:
        """Return the status line's right segment, or ``(segment, True)`` to take the side over."""
        return None

    def ui_slots(self) -> tuple[tuple[UiRegion, UiSide, str, UiBuilder], ...]:
        """Return the slots this plugin overrides, ready to register.

        The segment name is the method's slot name, which is what makes an
        override land on the builtin segment instead of beside it.
        """
        declared: list[tuple[UiRegion, UiSide, str, UiBuilder]] = []
        for name, region, side in UI_SLOTS:
            if getattr(type(self), name) is not getattr(PluginUiMixin, name):
                declared.append((region, side, name.removeprefix("render_"), getattr(self, name)))
        return tuple(declared)
