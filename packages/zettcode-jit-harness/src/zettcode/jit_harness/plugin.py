"""The plugin that hands the agent the just-in-time harness."""

from __future__ import annotations

from typing import TYPE_CHECKING

from zettcode.engine.extensions.harness_switch import HarnessSwitch
from zettcode.engine.permission import ShellPolicy
from zettcode.engine.plugins.context import PluginContext
from zettcode.engine.plugins.plugin import Plugin, PluginSetting
from zettcode.engine.plugins.services import HARNESS, POLICY
from zettcode.engine.service_contracts import SESSION_STORE, SessionStoreService
from zettcode.plugin_api.host import HOST_LINK, HostLink

from .selection import HARNESS_CHOICES, HarnessChoices

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from pathlib import Path

    from zett_agent.extensions.base import AgentExtension
    from zett_agent.jit_harness import JITToolHost

    from zettcode.engine.plugins.state import AgentBuild


class Harness(Plugin[PluginContext]):
    """The just-in-time harness: the model keeps small Python tools of its own, when the reader has it on.

    The extension is always registered and inert until the switch is on, so a switch written by ``/plugins`` reaches the
    next request of a client that was already built. Each session keeps its tools in its own folder under
    ``config.harness_dir``, which is ``~/.zettcode/harness`` unless the configuration object says otherwise. The page
    ``/harness`` opens (:mod:`.page`) and the terminal's preset (:mod:`.command`) ship with the part; a process with no
    screen gets the same name as a plain command (:mod:`.plain`), so ``gen`` and ``reset`` reach the editor without
    importing the widgets.
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
        choices = HarnessChoices(ctx.config.harness_dir / ".borrowed")
        ctx.provide(HARNESS_CHOICES, choices)

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

        def session_file(session_id: str) -> Path | None:
            """Where a session's conversation is stored, for ``profile_tools`` to read; ``None`` when nothing is."""
            store = ctx.find(SESSION_STORE, SessionStoreService)  # type: ignore[type-abstract]
            if store is None:
                return None
            try:
                return store.session_path(session_id)
            except ValueError:
                return None

        def start_in_the_library_harness() -> None:
            """Make `[harness] use` the default every session works in, when it names a harness that is there."""
            from zettcode.engine.harness_library import used_entry

            entry = used_entry(ctx.config)
            if entry is not None:
                choices.use(f"library/{entry.name}", entry.path)

        start_in_the_library_harness()

        def build(_: AgentBuild) -> AgentExtension:
            from .extension import SwitchedHarness

            return SwitchedHarness(
                root,
                switch,
                host_factory=host,
                boundary=boundary,
                unbounded=policy.sandbox_missing,
                legacy_root=ctx.config.harness_dir,
                choices=choices,
                session_file=session_file,
            )

        ctx.agent.register_extension_factory("SwitchedHarness", build)

        # The page and the preset are the terminal's; a process without a screen gets the same command name as a
        # plain command, so `gen` and `reset` work in the editor too. `command.py` imports widgets and is loaded only
        # for a screen, where the shell's link is there for it to run against.
        if ctx.tui is None:
            from .plain import register_plain

            register_plain(ctx)
        elif ctx.find(HOST_LINK, HostLink) is not None:
            from .command import HarnessCommand

            HarnessCommand().activate(ctx)
