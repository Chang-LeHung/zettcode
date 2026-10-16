"""What a failed request says: the reason the server gave, not the sentence the library wrapped it in."""

from __future__ import annotations

import httpx
import pytest
from zett_agent.agent import AgentRunConfig
from zett_agent.client import create_agent
from zett_agent.model import RetryOptions
from zett_agent.providers.anthropic import AnthropicProvider
from zett_agent.providers.openai import OpenAIProvider

from zettcode._compat import BaseExceptionGroup
from zettcode.app.agent.errors import HINTS, MAX_DETAIL, describe_error

FAST = RetryOptions(base_delay=0.0, max_delay=0.0, max_retries=1)


async def failure(provider_class, handler) -> BaseException:
    """Run one request through a real provider against a canned HTTP exchange, and return what it failed with."""
    provider = provider_class("m", "k", transport=httpx.MockTransport(handler), base_url="https://x/v1", retry=FAST)
    client = await create_agent(
        provider, config=AgentRunConfig(session_id="s"), system_prompt="x", extensions=[], max_iterations=2
    )
    try:
        async for _ in client.stream("hi", config=AgentRunConfig(session_id="s"), model=provider):
            pass
    except Exception as error:
        return error
    raise AssertionError("the request was meant to fail")


def answering(status: int, body: object = None, *, text: str | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=text) if text is not None else httpx.Response(status, json=body)

    return handler


# -- what the real libraries raise ------------------------------------------------------------------------------


async def test_a_model_that_does_not_exist_says_so_and_where_to_fix_it():
    error = await failure(
        OpenAIProvider,
        answering(404, {"error": {"message": "The model `gpt-9` does not exist", "code": "model_not_found"}}),
    )

    said = describe_error(error)

    assert said.startswith("HTTP 404: The model `gpt-9` does not exist")
    assert "check the model id and the address with /config" in said


async def test_a_refused_key_says_so_and_never_repeats_any_of_the_key():
    error = await failure(
        OpenAIProvider,
        answering(401, {"error": {"message": "Incorrect API key provided: sk-proj-********abcd. You can find it."}}),
    )

    said = describe_error(error)

    assert "HTTP 401" in said and "check the token with /config" in said
    assert "sk-proj" not in said and "abcd" not in said, said


async def test_a_quota_error_carries_the_servers_own_words():
    error = await failure(OpenAIProvider, answering(429, {"error": {"message": "You exceeded your current quota"}}))

    assert "HTTP 429: You exceeded your current quota" in describe_error(error)


async def test_a_proxys_html_page_is_read_as_text_not_shown_as_markup():
    error = await failure(OpenAIProvider, answering(502, text="<html><body><h1>Bad gateway</h1></body></html>"))

    said = describe_error(error)

    assert "HTTP 502: a web page, not an API response \u2014 Bad gateway" in said and "<" not in said


async def test_an_overloaded_anthropic_server_is_described_the_same_way():
    error = await failure(
        AnthropicProvider,
        answering(529, {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}),
    )

    assert "HTTP 529: Overloaded" in describe_error(error)


async def test_an_anthropic_refusal_of_the_key_has_the_hint_too():
    error = await failure(
        AnthropicProvider,
        answering(401, {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}}),
    )

    assert "HTTP 401: invalid x-api-key" in describe_error(error) and HINTS[401] in describe_error(error)


async def test_a_server_that_cannot_be_reached_says_what_the_connection_did():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("[Errno 61] Connection refused")

    said = describe_error(await failure(OpenAIProvider, handler))

    assert said == "Connection error. (ConnectError: [Errno 61] Connection refused)"


async def test_a_timeout_names_what_timed_out_when_the_library_gives_no_reason():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("")

    said = describe_error(await failure(OpenAIProvider, handler))

    assert "stopped sending data" in said and said.endswith("(ReadTimeout)")


# -- the shapes, without a provider ---------------------------------------------------------------------------------


class Status(Exception):
    """An exception that carries what the SDKs' status errors carry."""

    def __init__(self, status: object, body: object = None, message: str = "", text: str = "") -> None:
        super().__init__(text)
        self.status_code, self.body, self.message = status, body, message


def test_an_sdk_error_raised_as_it_is_is_not_the_dict_it_printed():
    error = Status(500, {"message": "upstream exploded"}, text="Error code: 500 - {'message': 'upstream exploded'}")

    assert describe_error(error) == "HTTP 500: upstream exploded"


def test_the_message_is_found_in_either_of_the_two_shapes_a_body_has():
    assert describe_error(Status(500, {"error": {"message": "nested"}})) == "HTTP 500: nested"
    assert describe_error(Status(500, {"message": "flat"})) == "HTTP 500: flat"
    assert describe_error(Status(500, "plain text")) == "HTTP 500: plain text"


def test_a_status_with_nothing_said_is_just_the_status():
    assert describe_error(Status(503)) == "HTTP 503"
    assert describe_error(Status(503, {})) == "HTTP 503"


def test_a_message_that_is_only_the_printed_dict_is_dropped_rather_than_shown():
    error = Status(500, None, message="Error code: 500 - {'error': {'message': 'x'}}")

    assert describe_error(error) == "HTTP 500"


def test_the_prefix_the_sdk_puts_before_its_message_is_taken_off():
    assert describe_error(Status(500, None, message="Error code: 500 - gateway down")) == "HTTP 500: gateway down"


@pytest.mark.parametrize("status", [True, "404", 404.0, None])
def test_a_status_that_is_not_a_number_is_not_one(status):
    assert describe_error(Status(status, {"message": "m"}, text="the text")) == "the text"


def test_a_message_is_one_line_and_bounded():
    said = describe_error(Status(500, {"message": "line one\n\n   line two\t" + "x" * 1000}))

    assert "\n" not in said and "\t" not in said and "  " not in said
    assert said.startswith("HTTP 500: line one line two x") and said.endswith("\u2026")
    assert len(said) <= len("HTTP 500: ") + MAX_DETAIL


@pytest.mark.parametrize(
    "secret",
    ["sk-proj-abcdEFGH1234", "sk-ant-api03-abcdef", "Bearer abc.def.ghi", "ghp_abcdefghijklmnop", "key-0123456789"],
)
def test_anything_shaped_like_a_credential_in_what_a_server_said_is_removed(secret):
    said = describe_error(Status(401, {"message": f"Invalid credential {secret} for this project"}))

    assert secret not in said and "Invalid credential" in said and "\u2026" in said


def test_an_ordinary_sentence_with_a_dash_in_it_is_not_taken_for_a_credential():
    said = describe_error(Status(400, {"message": "max-tokens must be positive; try a well-formed request"}))

    assert "max-tokens must be positive; try a well-formed request" in said


def test_the_cause_is_added_to_a_wrapper_and_not_repeated_when_the_wrapper_says_it_already():
    inner = Status(404, {"message": "no such model"})
    wrapper = RuntimeError("it failed")
    wrapper.__cause__ = inner
    same = RuntimeError("HTTP 404: no such model")
    same.__cause__ = inner

    assert describe_error(wrapper) == (
        "it failed (HTTP 404: no such model \u2014 check the model id and the address with /config)"
    )
    assert describe_error(same) == "HTTP 404: no such model \u2014 check the model id and the address with /config"


def test_a_chain_of_causes_that_loops_ends():
    a, b = RuntimeError("a"), RuntimeError("b")
    a.__cause__, b.__cause__ = b, a

    assert describe_error(a) == "a"


def test_a_cause_with_nothing_to_add_adds_nothing():
    wrapper = RuntimeError("wrapped")
    wrapper.__cause__ = ValueError("not a server and not a connection")

    assert describe_error(wrapper) == "wrapped"


def test_groups_and_plain_errors_read_as_they_did():
    grouped = BaseExceptionGroup("group", [RuntimeError("one"), BaseExceptionGroup("inner", [KeyError("two")])])

    assert describe_error(grouped) == "one; 'two'"
    assert describe_error(ValueError("plain")) == "plain"
    assert describe_error(ValueError()) == "ValueError"


def test_every_hint_is_for_a_status_the_reader_can_act_on_and_names_where():
    assert set(HINTS) == {401, 403, 404}
    assert all("/config" in hint for hint in HINTS.values())


def test_a_wrapper_that_already_says_what_the_cause_says_is_not_followed_by_the_same_words_again():
    cause = Status(404, {"message": "no such model"})
    said = "HTTP 404: no such model \u2014 check the model id and the address with /config"
    longer = RuntimeError(f"request failed: {said}")
    longer.__cause__ = cause
    equal = RuntimeError(said)
    equal.__cause__ = cause

    assert describe_error(longer) == f"request failed: {said}"
    assert describe_error(equal) == said
