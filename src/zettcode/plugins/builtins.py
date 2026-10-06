"""The rows ZettCode ships with, written as an ordinary plugin.

Keeping the default header and status here — rather than inside
:class:`~zettcode.app.ui.app.ZettCodeApp` — is what leaves the shell with one
generic renderer: it asks the merged plugin bundle for each row side and paints
whatever comes back. The builtin registers its segments first, so a plugin that
overrides one of the same builders replaces it in place instead of adding a
second segment beside it.
"""

from __future__ import annotations

from ..app.agent.mentions import SkillMentions
from ..app.agent.rows import activity_glyph, compact_path
from ..app.agent.usage import context_text, usage_text
from ..tui import HEADER, SEPARATOR, STATUS
from .container import PluginContainer
from .plugin import Plugin
from .state import ShellContext

#: Keys worth remembering while the composer has focus.
KEY_HINTS = "^C stop  ^D exit"


class ShellRows(Plugin):
    """The header and status rows a reader expects out of the box."""

    name = "shell"

    def render_header_left(self, context: ShellContext) -> str:
        """Label the app and the workspace it runs in."""
        return f"  {HEADER} zettcode  {compact_path(context.session.workspace)}"

    def render_header_right(self, context: ShellContext) -> str:
        """Show the model and the reasoning effort the next request will use."""
        return f"{context.model.name} {SEPARATOR} {context.model.effort}  "

    def render_status_left(self, context: ShellContext) -> str:
        """Show the activity glyph, status word, mode, session title, and token use."""
        activity = context.activity
        icon = activity_glyph(activity.frame) if activity.busy else STATUS
        mode = f" {SEPARATOR} auto" if activity.auto_shell else ""
        used = context_text(activity.usage, context.model.config.context_window)
        return f"  {icon} {activity.label}{mode}  {context.session.name}{usage_text(activity.usage)}{used}"

    def render_status_right(self, context: ShellContext) -> str:
        """List the keys worth remembering."""
        return f"  {KEY_HINTS}  "


class SkillResources(Plugin):
    """The builtin ``@`` resource provider: the skills on this machine.

    Registering it here rather than inside the shell keeps the shell generic: it
    merges whatever providers the bundle holds, and the skills are simply the
    one the repository ships.
    """

    name = "skills"

    def activate(self, container: PluginContainer) -> None:
        """Offer the discovered skills as ``@`` resources, when skills are on."""
        if container.config.skills_enabled:
            container.register_mention(SkillMentions(container.config))


#: Plugins loaded from the repository itself, never from a distribution.
BUILTIN_PLUGINS: tuple[Plugin, ...] = (ShellRows(), SkillResources())
