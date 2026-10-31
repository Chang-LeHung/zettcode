"""`zettcode prompt`: one prompt in, the answer on stdout, everything else on stderr, a status the shell can test.

The agent, its tools, the session store and the permission policy are the real ones; only the provider is a scripted
model (see ``sdk_helpers``), so what is checked is this command and not a canned reply.
"""

from __future__ import annotations

import asyncio
import io
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

import zettcode.sdk as zc
from sdk_helpers import ScriptedModel, asks_for, call, config_for, models, refusal, says, wire
from zettcode import cli, oneshot
from zettcode.cli import Options, parse_args
from zettcode.oneshot import NoPrompt, prompt_program, read_prompt
from zettcode.sdk.errors import RunError, RunTimeoutError

posix_shell = pytest.mark.skipif(sys.platform == "win32", reason="runs `echo` in the platform shell")


class Tty(io.StringIO):
    def isatty(self) -> bool:
        return True


def ask(tmp_path: Path, text: str | None = "question", *, stdin: io.StringIO | None = None, **changes):
    """Run the command the way the shell would, and return (status, stdout, stderr)."""
    config = changes.pop("config", None) or config_for(tmp_path)
    options = Options(workspace=config.workspace, command="prompt", prompt=text, **changes)
    out, err = io.StringIO(), io.StringIO()
    status = prompt_program(options, stdin=stdin or io.StringIO(), stdout=out, stderr=err, config=config)
    return status, out.getvalue(), err.getvalue()


# -- the command line ----------------------------------------------------------------------------------------------


def test_the_prompt_is_a_subcommand_that_carries_what_it_was_given(tmp_path: Path):
    assert parse_args(["-w", str(tmp_path), "prompt", "hello"]) == Options(
        workspace=tmp_path, command="prompt", prompt="hello"
    )
    options = parse_args(["prompt", "hi", "-m", "Sonnet", "-s", "abc", "-e", "high"])
    assert (options.model, options.resume, options.effort) == ("Sonnet", "abc", "high")
    assert (options.command, options.prompt) == ("prompt", "hi")


def test_without_a_model_or_a_session_it_asks_for_neither_so_the_first_model_and_a_new_session_are_used():
    options = parse_args(["prompt", "hi"])

    assert options.model is None and options.resume is None and options.effort is None


def test_the_workspace_may_come_before_the_word_or_after_it(tmp_path: Path):
    assert parse_args(["-w", str(tmp_path), "prompt", "hi"]).workspace == tmp_path
    assert parse_args(["prompt", "hi", "-w", str(tmp_path)]).workspace == tmp_path
    assert parse_args(["prompt", "hi"]).workspace == Path.cwd(), "the one after the word does not undo the default"
    assert parse_args(["-w", str(tmp_path), "prompt", "hi", "--model", "m"]).workspace == tmp_path


def test_the_session_given_before_the_word_still_applies():
    assert parse_args(["--resume", "abc", "prompt", "hi"]).resume == "abc"
    assert parse_args(["--resume", "abc", "prompt", "hi", "--session", "abc"]).resume == "abc"


def test_two_sessions_that_disagree_are_a_mistake():
    with pytest.raises(SystemExit):
        parse_args(["--resume", "abc", "prompt", "hi", "--session", "def"])


def test_the_permission_is_not_a_choice_the_command_offers():
    """There is nobody to ask, so the level is fixed (see `test_every_shell_command_runs_...`), not an option."""
    with pytest.raises(SystemExit):
        parse_args(["prompt", "hi", "--permission", "deny"])


def test_the_prompt_word_runs_the_one_shot_program_and_exits_with_its_status(monkeypatch):
    seen = []
    monkeypatch.setattr(sys, "argv", ["zettcode", "prompt", "hello"])
    monkeypatch.setattr(oneshot, "prompt_program", lambda options: seen.append(options) or 7)
    monkeypatch.setattr(cli, "launch", lambda options: pytest.fail("the terminal must not open"))

    with pytest.raises(SystemExit) as result:
        cli.main()

    assert result.value.code == 7 and seen[0].prompt == "hello"


# -- where the prompt comes from -----------------------------------------------------------------------------------


def test_a_prompt_on_the_command_line_is_used_as_it_is_and_standard_input_is_left_alone():
    class Silent(io.StringIO):
        def read(self, *args):
            raise AssertionError("an input that is open but silent must not be waited on")

    assert read_prompt("  explain  ", Silent()) == "  explain  "


def test_no_prompt_or_a_dash_reads_standard_input():
    assert read_prompt(None, io.StringIO("from a pipe\n")) == "from a pipe\n"
    assert read_prompt("-", io.StringIO("also from a pipe")) == "also from a pipe"


def test_a_terminal_is_never_waited_on_for_a_prompt_that_was_not_typed():
    with pytest.raises(NoPrompt, match="no prompt"):
        read_prompt(None, Tty("would block"))


@pytest.mark.parametrize("text", ["", "   ", "\n"])
def test_an_empty_prompt_is_refused(text: str):
    with pytest.raises(NoPrompt, match="empty"):
        read_prompt(text, io.StringIO(""))
    with pytest.raises(NoPrompt, match="empty"):
        read_prompt(None, io.StringIO(text))


def test_a_missing_prompt_is_a_usage_error_that_costs_nothing(tmp_path: Path, monkeypatch):
    model = wire(monkeypatch, ScriptedModel("never asked"))

    status, out, err = ask(tmp_path, None, stdin=Tty())

    assert (status, out) == (oneshot.EXIT_USAGE, "") and "no prompt" in err and not model.requests


# -- the answer, and what is not the answer ------------------------------------------------------------------------


def test_the_answer_is_all_of_stdout_and_the_rest_is_on_stderr(tmp_path: Path, monkeypatch):
    wire(monkeypatch, ScriptedModel("the answer", chunk=3))

    status, out, err = ask(tmp_path)

    assert status == oneshot.EXIT_OK
    assert out == "the answer\n", "streamed, with the one newline that keeps the shell prompt off its last line"
    assert "the answer" not in err and "session:" in err


def test_the_prompt_reaches_the_model_unchanged(tmp_path: Path, monkeypatch):
    model = wire(monkeypatch, ScriptedModel("ok"))

    ask(tmp_path, "what does\n  this do?")

    assert model.requests[0].messages[-1].text == "what does\n  this do?"


def test_a_prompt_from_a_pipe_is_sent_whole(tmp_path: Path, monkeypatch):
    model = wire(monkeypatch, ScriptedModel("ok"))

    status, _out, _err = ask(tmp_path, None, stdin=io.StringIO("diff --git a b\n+line\n"))

    assert status == oneshot.EXIT_OK and model.requests[0].messages[-1].text == "diff --git a b\n+line\n"


def test_a_tool_the_model_used_is_reported_on_stderr_and_never_in_the_answer(tmp_path: Path, monkeypatch):
    target = tmp_path / "project" / "note.txt"
    target.parent.mkdir(exist_ok=True)
    target.write_text("hello\n", encoding="utf-8")
    wire(monkeypatch, ScriptedModel(asks_for(call("read_file", {"path": str(target)}, call_id="r")), "it says hello"))

    status, out, err = ask(tmp_path)

    assert status == oneshot.EXIT_OK and out == "it says hello\n"
    assert "[read_file]" in err and "[read_file]" not in out


# -- the model -----------------------------------------------------------------------------------------------------


def chosen(monkeypatch, *steps):
    """Wire a scripted model that also records which configured model each request was built for."""
    from zettcode.engine import core as runtime_module

    scripted = ScriptedModel(*steps)
    used: list[str] = []

    def build(selected):
        used.append(selected.model)
        return scripted

    monkeypatch.setattr(runtime_module, "_build_provider", build)
    return scripted, used


def test_the_first_model_in_the_config_answers_when_none_is_named(tmp_path: Path, monkeypatch):
    _model, used = chosen(monkeypatch, "ok")

    status, _out, _err = ask(tmp_path, config=config_for(tmp_path, models=models("first", "second", "third")))

    assert status == oneshot.EXIT_OK and used == ["first"]


def test_a_named_model_answers_instead(tmp_path: Path, monkeypatch):
    _model, used = chosen(monkeypatch, "ok")

    status, _out, _err = ask(tmp_path, config=config_for(tmp_path, models=models("first", "second")), model="second")

    assert status == oneshot.EXIT_OK and used == ["second"]


def test_a_model_nobody_configured_is_a_usage_error_that_lists_the_ones_there_are(tmp_path: Path, monkeypatch):
    model = wire(monkeypatch, ScriptedModel("never asked"))

    status, out, err = ask(tmp_path, config=config_for(tmp_path, models=models("first", "second")), model="third")

    assert status == oneshot.EXIT_USAGE and out == ""
    assert "third" in err and "first" in err and "second" in err and not model.requests


def test_an_effort_the_model_does_not_take_is_a_usage_error(tmp_path: Path, monkeypatch):
    wire(monkeypatch, ScriptedModel("never asked"))

    status, out, err = ask(tmp_path, effort="not-a-level")

    assert status == oneshot.EXIT_USAGE and out == "" and "not-a-level" in err


# -- the session ---------------------------------------------------------------------------------------------------


def session_of(err: str) -> str:
    return next(line.split(": ", 1)[1] for line in err.splitlines() if line.startswith("session: "))


def test_every_run_starts_a_new_session_unless_one_is_named(tmp_path: Path, monkeypatch):
    wire(monkeypatch, ScriptedModel("one", "two"))
    config = config_for(tmp_path)

    first = session_of(ask(tmp_path, "a", config=config)[2])
    second = session_of(ask(tmp_path, "b", config=config)[2])

    assert first != second


def test_a_named_session_is_continued_with_what_it_said_before(tmp_path: Path, monkeypatch):
    model = wire(monkeypatch, ScriptedModel("first reply", "second reply"))
    config = config_for(tmp_path)
    _status, _out, err = ask(tmp_path, "my first question", config=config)

    status, out, err_again = ask(tmp_path, "and then?", config=config, resume=session_of(err))

    assert status == oneshot.EXIT_OK and out == "second reply\n"
    assert session_of(err_again) == session_of(err), "the same conversation, so the id is the same"
    sent = str(model.requests[1].messages)
    assert "my first question" in sent and "first reply" in sent


def test_a_session_nobody_stored_is_a_usage_error_before_anything_is_sent(tmp_path: Path, monkeypatch):
    model = wire(monkeypatch, ScriptedModel("never asked"))

    status, out, err = ask(tmp_path, resume="no-such-session")

    assert status == oneshot.EXIT_USAGE and out == "" and "no-such-session" in err and not model.requests


# -- when it does not end well -------------------------------------------------------------------------------------


def test_a_refusal_prints_what_was_said_and_fails(tmp_path: Path, monkeypatch):
    wire(monkeypatch, ScriptedModel(refusal("I can't help with that.")))

    status, out, err = ask(tmp_path)

    assert status == oneshot.EXIT_FAILED
    assert out == "I can't help with that.\n", "what the model did say is still the answer"
    assert "refusal" in err and "stopped" in err


def test_a_provider_error_fails_with_its_words_on_stderr_and_nothing_on_stdout(tmp_path: Path, monkeypatch):
    wire(monkeypatch, ScriptedModel(ValueError("the key was rejected")))

    status, out, err = ask(tmp_path)

    assert status == oneshot.EXIT_FAILED and out == "" and "rejected" in err


def test_what_was_said_before_the_error_is_kept(monkeypatch, tmp_path: Path):
    """A run that dies half way has already told the reader something; losing it would be a worse failure."""
    from zettcode.sdk import session as session_module

    original = session_module.RunStream.__anext__

    async def failing(self):
        event = await original(self)
        if type(event).__name__ == "TextDelta":
            raise RunError("connection dropped", retryable=True, partial_text="half an ans")
        return event

    wire(monkeypatch, ScriptedModel("half an answer"))
    monkeypatch.setattr(session_module.RunStream, "__anext__", failing)

    status, out, err = ask(tmp_path)

    assert status == oneshot.EXIT_FAILED and "connection dropped" in err
    assert out.startswith("half an ans"), "what had already been streamed stays"


def test_an_interrupt_ends_the_run_quietly_with_the_status_a_shell_expects(tmp_path: Path, monkeypatch):
    async def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    wire(monkeypatch, ScriptedModel("never"))
    monkeypatch.setattr(oneshot, "run_prompt", interrupted)

    assert ask(tmp_path)[0] == oneshot.EXIT_INTERRUPTED


# -- permission: nobody is there to ask ----------------------------------------------------------------------------


@posix_shell
@pytest.mark.parametrize("configured", ["review", "deny"])
def test_every_shell_command_runs_whatever_level_the_config_file_names(tmp_path: Path, monkeypatch, configured: str):
    """Nothing can answer a question, so the level is always auto: a command is run, not asked about or refused."""
    marker = tmp_path / "project" / "ran"
    steps = [asks_for(call("bash", {"command": f"echo hi > {marker.name}"}, call_id="b")), "done"]
    wire(monkeypatch, ScriptedModel(*steps))
    config = replace(config_for(tmp_path), shell_approval=configured)

    status, out, err = ask(tmp_path, config=config)

    assert status == oneshot.EXIT_OK and out == "done\n"
    assert marker.exists(), "the command ran"
    assert "declined" not in err


def test_the_permission_every_run_uses_is_auto():
    assert oneshot.PERMISSION == "auto"


def test_a_question_the_model_asks_is_declined_and_the_run_goes_on(tmp_path: Path, monkeypatch):
    steps = [asks_for(call("ask_user", {"question": "Which one?"}, call_id="q")), says("I chose for myself")]
    model = wire(monkeypatch, ScriptedModel(*steps))

    status, out, _err = ask(tmp_path)

    assert status == oneshot.EXIT_OK and out == "I chose for myself\n"
    assert "declined" in str(model.requests[1].messages[-1]), "the model was told, so it did not wait for an answer"


def test_the_working_directory_is_given_back_when_it_is_over(tmp_path: Path, monkeypatch):
    import os

    wire(monkeypatch, ScriptedModel("ok"))
    before = os.getcwd()

    ask(tmp_path)

    assert os.getcwd() == before


# -- --continue: the terminal's /continue, without the terminal -----------------------------------------------------


def carry_on(tmp_path: Path, **changes):
    """Run `zettcode prompt --continue` the way the shell would, and return (status, stdout, stderr)."""
    config = changes.pop("config", None) or config_for(tmp_path)
    options = Options(workspace=config.workspace, command="prompt", continue_request=True, **changes)
    out, err = io.StringIO(), io.StringIO()
    status = prompt_program(options, stdin=Tty(), stdout=out, stderr=err, config=config)
    return status, out.getvalue(), err.getvalue()


def cut_short(config, task: str = "a task that gets interrupted") -> str:
    """Store a session whose request was stopped by a timeout, and return its id."""

    async def go() -> str:
        async with zc.Client(config=config) as client:
            # Generous: a slow interpreter can still be setting up the store when
            # a tighter timeout fires, and then there is no session to resume.
            with pytest.raises(RunTimeoutError):
                await client.prompt(task, timeout=5.0)
            return client.session.id

    return asyncio.run(go())


async def stuck(request):
    await asyncio.Event().wait()
    return "never"


def test_continue_is_a_flag_of_prompt_that_takes_no_prompt_and_names_its_session(tmp_path: Path):
    assert parse_args(["prompt", "hi"]).continue_request is False, "off unless asked for"
    assert parse_args(["-w", str(tmp_path), "prompt", "-c", "-s", "abc"]) == Options(
        workspace=tmp_path, command="prompt", continue_request=True, resume="abc"
    )
    options = parse_args(["prompt", "--continue", "-s", "abc", "-m", "M", "-e", "high", "-w", str(tmp_path)])
    assert (options.continue_request, options.resume, options.model, options.effort) == (True, "abc", "M", "high")
    assert options.prompt is None and options.workspace == tmp_path
    assert parse_args(["--resume", "abc", "prompt", "-c"]).resume == "abc", "the global spelling of the session counts"


def test_continue_without_a_session_is_a_mistake_and_nothing_picks_one_for_it(capsys):
    with pytest.raises(SystemExit) as result:
        parse_args(["prompt", "--continue"])

    assert result.value.code == 2 and "--continue needs --session" in capsys.readouterr().err


def test_a_prompt_to_continue_with_is_a_mistake_rather_than_ignored():
    """Silently dropping the words would be the worse reading of `prompt -c "and the tests?"`."""
    with pytest.raises(SystemExit):
        parse_args(["prompt", "--continue", "a prompt nobody reads"])


def test_continue_does_not_read_standard_input_or_ask_whether_it_is_a_terminal(tmp_path: Path, monkeypatch):
    class Silent(io.StringIO):
        def read(self, *args):
            raise AssertionError("--continue has no prompt, so there is nothing to read")

        def isatty(self) -> bool:
            raise AssertionError("nor to ask about")

    wire(monkeypatch, ScriptedModel("never asked"))
    config = config_for(tmp_path)
    options = Options(workspace=config.workspace, command="prompt", continue_request=True, resume="no-such-session")
    err = io.StringIO()

    status = prompt_program(options, stdin=Silent(), stdout=io.StringIO(), stderr=err, config=config)

    assert status == oneshot.EXIT_USAGE and "no-such-session" in err.getvalue(), (
        "it looked for the session, not at stdin"
    )


def test_a_request_that_was_cut_short_is_picked_up_in_the_session_named(tmp_path: Path, monkeypatch):
    model = wire(monkeypatch, ScriptedModel(stuck, "picked up"))
    config = config_for(tmp_path)
    stopped = cut_short(config)

    status, out, err = carry_on(tmp_path, config=config, resume=stopped)

    assert status == oneshot.EXIT_OK and out == "picked up\n"
    assert session_of(err) == stopped, "the interrupted conversation goes on; no new one is started"
    assert "a task that gets interrupted" in str(model.requests[1].messages), "and the model still has the task"


def test_the_session_named_is_the_one_picked_up_even_when_another_is_newer(tmp_path: Path, monkeypatch):
    """The workspace's latest session is not always the one that was cut short, which is why none is guessed."""
    model = wire(monkeypatch, ScriptedModel(stuck, "a different, finished answer", "picked up"))
    config = config_for(tmp_path)
    stopped = cut_short(config)
    time.sleep(0.05)
    newer = session_of(ask(tmp_path, "another conversation", config=config)[2])

    status, out, err = carry_on(tmp_path, config=config, resume=stopped)

    assert newer != stopped
    assert status == oneshot.EXIT_OK and out == "picked up\n" and session_of(err) == stopped
    assert "a task that gets interrupted" in str(model.requests[2].messages)


def test_without_a_session_there_is_nothing_to_pick_up_and_the_model_is_not_asked(tmp_path: Path, monkeypatch):
    model = wire(monkeypatch, ScriptedModel("never asked"))
    config = config_for(tmp_path)
    assert ask(tmp_path, config=config)[0] == oneshot.EXIT_OK  # a stored session exists, and is still not picked
    asked = len(model.requests)

    status, out, err = carry_on(tmp_path, config=config)

    assert status == oneshot.EXIT_USAGE and out == "" and "--continue needs --session" in err
    assert len(model.requests) == asked


def test_a_session_that_finished_has_nothing_to_continue_and_that_is_not_a_failure(tmp_path: Path, monkeypatch):
    model = wire(monkeypatch, ScriptedModel("all done"))
    config = config_for(tmp_path)
    finished = session_of(ask(tmp_path, config=config)[2])

    status, out, err = carry_on(tmp_path, config=config, resume=finished)

    assert status == oneshot.EXIT_NOTHING and status not in (oneshot.EXIT_OK, oneshot.EXIT_FAILED)
    assert out == "" and "nothing to continue" in err and len(model.requests) == 1


def test_a_session_nobody_stored_cannot_be_continued(tmp_path: Path, monkeypatch):
    model = wire(monkeypatch, ScriptedModel("never asked"))

    status, out, err = carry_on(tmp_path, resume="no-such-session")

    assert status == oneshot.EXIT_USAGE and out == "" and "no-such-session" in err and not model.requests


def test_continue_answers_on_stdout_and_runs_commands_like_a_prompt_does(tmp_path: Path, monkeypatch):
    marker = tmp_path / "project" / "ran"
    steps = [stuck, asks_for(call("bash", {"command": f"echo hi > {marker.name}"}, call_id="b")), "went on"]
    wire(monkeypatch, ScriptedModel(*steps))
    config = replace(config_for(tmp_path), shell_approval="review")
    stopped = cut_short(config)

    status, out, err = carry_on(tmp_path, config=config, resume=stopped)

    assert status == oneshot.EXIT_OK and out == "went on\n" and "[bash]" in err and "[bash]" not in out
    assert marker.exists() or sys.platform == "win32"
