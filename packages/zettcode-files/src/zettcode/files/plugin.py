"""The plugin that offers the workspace's files as ``@`` references."""

from __future__ import annotations

from typing import TYPE_CHECKING

from zettcode.engine.plugins.plugin import Plugin

from .mentions import FileMentions

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zettcode.engine.plugins.context import PluginContext


class FileResources(Plugin):
    """The ``@`` resource provider for the workspace's own files.

    A name a skill (``zettcode-skills``) also offers is the skill: a repository holds a file called ``test`` and a
    skill is the more specific thing to mean, which the skills provider says with its ``precedence``. Nothing turns
    this off, because a workspace always has files.
    """

    name = "files"

    def activate(self, ctx: PluginContext) -> None:
        """Offer the workspace's files as ``@`` resources."""
        ctx.agent.register_mention(FileMentions(ctx.config.workspace))
