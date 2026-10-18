"""An opt-in model tool requests compaction at the next safe model boundary."""

from __future__ import annotations

from zett_agent.agent import AgentRunConfig, AgentRunContext, AgentState
from zett_agent.messages import SystemMessage

from test_compaction import FakeContext, FakeModel, _dialogue
from test_zettcode_app import build_app
from zettcode.app.agent.dialogue.side import question
from zettcode.app.agent.extensions.compaction import OnDemandCompaction
from zettcode.app.agent.storage import SessionStore
from zettcode.app.commands import CommandContext


def context():
    state = AgentState()
    state._messages.append(SystemMessage(content="instructions"))
    return AgentRunContext(AgentRunConfig(session_id="s1"), state, {})


async def test_disabled_sessions_do_not_offer_a_compaction_tool():
    extension = OnDemandCompaction(None)
    ctx = context()
    await extension.on_tool(ctx)
    assert "compact_context" not in ctx.tools


async def test_enabled_sessions_offer_the_tool_and_it_only_requests_a_safe_boundary():
    extension = OnDemandCompaction(None, self_compact=lambda sid: sid == "s1")
    ctx = context()
    await extension.on_tool(ctx)
    assert set(ctx.tools) == {"compact_context"}
    result = await ctx.tools["compact_context"].handler()
    assert "next model call" in result
    assert ctx in extension._requested
    assert len(ctx.state.messages) == 1, "a tool does not mutate the context while siblings might run"


async def test_a_requested_pass_uses_the_released_compaction_and_keeps_the_current_turn():
    extension = OnDemandCompaction(
        None, max_tokens=1_000_000, keep_recent_tokens=200_000, self_compact=lambda sid: True
    )
    ctx = FakeContext(_dialogue(), FakeModel())
    extension._requested.add(ctx)
    await extension.before_model(ctx, request=None)
    assert ctx not in extension._requested
    assert ctx.published
    assert [m.content for m in ctx.state.messages[2:]] == ["does the suite pass?", "yes, all green"]
    assert extension.keep_recent_tokens == 200_000


async def test_a_side_question_never_gets_the_tool_or_applies_a_pending_request():
    extension = OnDemandCompaction(None, self_compact=lambda sid: True)
    ctx = context()
    ctx.input_message = question("what does it mean?")
    await extension.on_tool(ctx)
    assert not ctx.tools
    extension._requested.add(ctx)
    await extension.before_model(ctx, request=None)
    assert ctx not in extension._requested
    assert len(ctx.state.messages) == 1


async def test_the_switch_is_rechecked_when_an_already_registered_tool_runs():
    enabled = [True]
    extension = OnDemandCompaction(None, self_compact=lambda sid: enabled[0])
    ctx = context()
    await extension.on_tool(ctx)
    enabled[0] = False
    assert "disabled" in await ctx.tools["compact_context"].handler()
    assert ctx not in extension._requested


async def test_command_reads_and_sets_the_current_sessions_choice():
    app = build_app()
    command = next(c for c in app.commands if c.name == "/self-compact")
    result = await command.handler(CommandContext("", None))
    assert result.widget is not None, "on its own it opens the panel"
    result = await command.handler(CommandContext("on", None))
    assert "**on**" in result.message and app.agent.self_compaction_choice is True and app.agent.self_compaction
    await command.handler(CommandContext("off", None))
    assert app.agent.self_compaction_choice is False and not app.agent.self_compaction
    await command.handler(CommandContext("default", None))
    assert app.agent.self_compaction_choice is None
    for bad in ("maybe", "on off", "global", "global default", "global maybe"):
        result = await command.handler(CommandContext(bad, None))
        assert "Usage" in result.message


async def test_a_fresh_runtime_reads_the_saved_choice_and_new_sessions_stay_disabled(tmp_path, monkeypatch):
    from zettcode.app.agent.runtime import ZettCodeRuntime
    from zettcode.config import ModelConfig, ZettCodeConfig

    monkeypatch.setattr("zettcode.app.agent.runtime.os.chdir", lambda path: None)
    config = ZettCodeConfig(
        workspace=tmp_path, store=tmp_path / "sessions", models=(ModelConfig(model="test", token="test"),)
    )
    store = SessionStore(config.store, config.workspace)
    store.set_self_compact("s1", True)
    runtime = ZettCodeRuntime.preview(config)
    try:
        ctx = context()
        await runtime.compaction.on_tool(ctx)
        assert "compact_context" in ctx.tools, "a new process reads the stored session's choice"
        ctx = context()
        ctx.config = AgentRunConfig(session_id=runtime.session_id)
        await runtime.compaction.on_tool(ctx)
        assert not ctx.tools, "a fresh session does not inherit the previous session's choice"
    finally:
        await runtime.aclose()
