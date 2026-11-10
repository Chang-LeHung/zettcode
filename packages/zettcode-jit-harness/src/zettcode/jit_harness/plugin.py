"""The plugin that hands the agent the just-in-time harness."""

from __future__ import annotations

from typing import TYPE_CHECKING

from zettcode.engine.extensions.harness_switch import HarnessSwitch
from zettcode.engine.permission import ShellPolicy
from zettcode.engine.plugins.context import PluginContext
from zettcode.engine.plugins.plugin import Plugin, PluginSetting
from zettcode.engine.plugins.services import HARNESS, POLICY
from zettcode.plugin_api.host import HOST_LINK, HostLink

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zett_agent.extensions.base import AgentExtension
    from zett_agent.jit_harness import JITToolHost

    from zettcode.engine.plugins.state import AgentBuild

    from .extension import SwitchedHarness


class Harness(Plugin[PluginContext]):
    """The just-in-time harness: the model keeps small Python tools of its own, when the reader has it on.

    The extension is always registered and inert until the switch is on, so a switch written by ``/plugins`` reaches the
    next request of a client that was already built. Each session keeps its tools in its own folder under
    ``config.harness_dir``, which is ``~/.zettcode/harness`` unless the configuration object says otherwise. The page
    ``/harness`` opens (:mod:`.page`) and the command that opens it (:mod:`.command`) ship with the part; the command
    is registered here, only for a process that has a screen and the shell's link, so the SDK and the server hold
    nothing of the terminal.
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

        #: The extension this process built, once the agent is built. The command that deletes a session's tool folder
        #: has to close that session's child first — the folder is the child's working directory, and a live process's
        #: folder cannot be removed on Windows — and this is the only handle on it.
        built: list[SwitchedHarness] = []

        def build(_: AgentBuild) -> AgentExtension:
            from .extension import SwitchedHarness

            harness = SwitchedHarness(
                root,
                switch,
                host_factory=host,
                boundary=boundary,
                unbounded=policy.sandbox_missing,
                legacy_root=ctx.config.harness_dir,
            )
            built.append(harness)
            return harness

        def release(session_id: str) -> bool:
            """Close a session's harness child, or say there is none to close."""
            return built[-1].release(session_id) if built else True

        ctx.agent.register_extension_factory("SwitchedHarness", build)

        # The page and the command that opens it are this part's; only a terminal can hold a command, and only the
        # shell attaches the link a command runs against, so a process without a screen registers nothing here.
        if ctx.tui is not None and ctx.find(HOST_LINK, HostLink) is not None:
            from .command import HarnessCommand

            HarnessCommand(release=release).activate(ctx)
