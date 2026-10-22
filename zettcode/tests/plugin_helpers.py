"""Loading the built-in agent plugins the way the runtime does, without a runtime.

The agent-side plugins build on state the runtime hands them by name, so they cannot be loaded bare. This
gives a test the same bundle, over a fresh session store and policy, and the extensions it would give the agent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from zettcode.app.agent.extensions.compaction import CompactionCounter
from zettcode.app.agent.extensions.harness_switch import HarnessSwitch
from zettcode.app.agent.permission import ShellPolicy
from zettcode.app.agent.storage import SessionStore
from zettcode.plugins import AGENT_PLUGINS, AgentBuild, Plugins, load_plugins
from zettcode.plugins import services as names

if TYPE_CHECKING:
    from zett_agent.extensions.base import AgentExtension

    from zettcode.app.agent.runtime import ZettCodeRuntime
    from zettcode.config import ZettCodeConfig


def runtime_inputs(runtime: ZettCodeRuntime) -> dict[str, object]:
    """Return what a runtime hands its plugins, so a test can load another bundle over the same state."""
    return {
        names.POLICY: runtime.policy,
        names.HARNESS: runtime.harness,
        names.PERSISTENCE: runtime.persistence,
        names.MODELS: runtime._models,
        names.COMPACTION_COUNTER: runtime.compaction_counter,
        names.SELECTED_MODEL: runtime.active_model,
    }


def agent_plugins(config: ZettCodeConfig, **shared: object) -> Plugins:
    """Load only the agent-side built-in plugins for ``config``, over fresh state; ``shared`` adds or replaces."""
    state: dict[str, object] = {
        names.POLICY: ShellPolicy.from_mode(config.shell_approval, config.workspace),
        names.HARNESS: HarnessSwitch(on=config.jit_harness),
        names.PERSISTENCE: SessionStore(config.store, config.workspace),
        names.MODELS: {},
        names.COMPACTION_COUNTER: CompactionCounter(),
        names.SELECTED_MODEL: config.models[0],
    }
    state.update(shared)
    return load_plugins(config, builtins=AGENT_PLUGINS, entry_points=[], shared=state)


def agent_extensions(config: ZettCodeConfig, **shared: object) -> tuple[AgentExtension, ...]:
    """Return the extensions the built-in agent plugins give the agent for ``config``, factories built."""
    plugins = agent_plugins(config, **shared)
    assert plugins.failures == ()
    return plugins.agent_extensions(AgentBuild(model=object()))  # type: ignore[arg-type]
