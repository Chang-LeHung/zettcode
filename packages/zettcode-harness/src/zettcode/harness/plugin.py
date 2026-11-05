"""The plugin that hands the agent the just-in-time harness."""

from __future__ import annotations

from typing import TYPE_CHECKING

from zettcode.engine.extensions.harness_switch import HarnessSwitch
from zettcode.engine.permission import ShellPolicy
from zettcode.engine.plugins.plugin import Plugin, PluginSetting
from zettcode.engine.plugins.services import HARNESS, POLICY

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zett_agent.extensions.base import AgentExtension
    from zett_agent.jit_harness import JITToolHost

    from zettcode.engine.plugins.context import PluginContext
    from zettcode.engine.plugins.state import AgentBuild


class Harness(Plugin):
    """The just-in-time harness: the model keeps small Python tools of its own, when the reader has it on.

    The extension is always registered and inert until the switch is on, so ``/harness on`` reaches the next
    request of a client that was already built. Each session keeps its tools in its own folder under
    ``config.harness_dir``, which is ``~/.zettcode/harness`` unless the configuration object says otherwise.
    """

    name = "harness"
    description = "The just-in-time tool harness, off by default"
    setting = PluginSetting("jit_harness", "harness", "jit")

    def activate(self, ctx: PluginContext) -> None:
        """Register the switchable extension; the framework's harness is imported when the agent is built."""
        from zettcode.engine.harness_paths import harness_root

        switch = ctx.service(HARNESS, HarnessSwitch)
        root = harness_root(ctx.config)
        policy = ctx.service(POLICY, ShellPolicy)

        def host() -> JITToolHost:
            """Where one session's repository code runs.

            A child process either way, so a crash, a hang or a runaway allocation in code the model wrote stays
            out of this window. The boundary comes from the policy — none at `full`, the boundary `safe` uses below
            it — and `None` on a machine that has no sandbox.
            """
            from zett_agent.jit_harness import SubprocessToolHost

            return SubprocessToolHost(sandbox=policy.jit_sandbox())

        def boundary() -> str:
            """What a session's child was built around: the sandbox itself, or none.

            The *level* is not the key. `ask` and `safe` hand the harness the same sandbox, and restarting a child for
            nothing costs the model its loaded repository — the next tool call fails until it is loaded again — so this
            changes only when the boundary does.
            """
            sandbox = policy.jit_sandbox()
            return "none" if sandbox is None else type(sandbox).__name__ + str(id(sandbox))

        def build(_: AgentBuild) -> AgentExtension:
            from .extension import SwitchedHarness

            return SwitchedHarness(
                root,
                switch,
                host_factory=host,
                boundary=boundary,
                unbounded=policy.sandbox_missing,
                legacy_root=ctx.config.harness_dir,
            )

        ctx.agent.register_extension_factory("SwitchedHarness", build)
