"""The plugins that offer skills: to the composer as ``@`` references, and to the model as a list and a tool."""

from __future__ import annotations

from typing import TYPE_CHECKING

from zettcode.engine.plugins.context import PluginContext
from zettcode.engine.plugins.plugin import Plugin, PluginSetting

from .mentions import SkillMentions

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zett_agent.extensions.base import AgentExtension

    from zettcode.engine.plugins.state import AgentBuild


class SkillResources(Plugin[PluginContext]):
    """The ``@`` resource provider for the skills on this machine.

    Registering it from a plugin rather than inside the shell keeps the shell generic: it merges whatever providers
    the bundle holds, and the skills are simply one of them.
    """

    name = "skills"
    setting = PluginSetting("skills_enabled", "skills")

    def activate(self, ctx: PluginContext) -> None:
        """Offer the discovered skills as ``@`` resources, when skills are on."""
        if ctx.config.skills_enabled:
            ctx.agent.register_mention(SkillMentions(ctx.config.skill_search_roots()))


class SkillTool(Plugin[PluginContext]):
    """The skills the model can load: their list in the prompt and the tool that reads one."""

    name = "skill-tool"
    description = "Skills the model can load"

    def activate(self, ctx: PluginContext) -> None:
        """Hand the agent the skills found under the configured roots, when skills are on."""
        config = ctx.config
        if not config.skills_enabled:
            return

        def build(_: AgentBuild) -> AgentExtension:
            from zett_agent.extensions.skill import SkillExtension

            return SkillExtension(config.skill_search_roots())

        ctx.agent.register_extension_factory("SkillExtension", build)
