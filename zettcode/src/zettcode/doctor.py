"""Find out whether the configured models work: what ``zettcode doctor`` does.

A model entry can be wrong in ways that only show up on the first request: a token that was revoked, a base URL
with a typo, a model id the endpoint does not serve, an endpoint that speaks the other protocol. The reader finds out
in the middle of a task. This module asks every configured model one trivial question, all at once, and says for each
whether it answered and, if it did not, in the provider's own words why not.

The question costs a handful of tokens: a one-line prompt at the cheapest reasoning level the entry accepts. Nothing
is written to a session, no tool is offered, and no extension runs: the request goes to the provider adapter
directly, so what is measured is the entry and the endpoint and nothing of this program.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import ModelConfig, ZettCodeConfig

#: Seconds one model may take to answer before it is reported as not answering.
TIMEOUT = 30.0

#: What every model is asked. One short line, so the reply is a token or two.
QUESTION = "Reply with the single word: ok"

#: Characters of a provider's explanation kept in the report; the rest is a page of HTML or a stack of JSON.
DETAIL_LIMIT = 200


@dataclass(frozen=True, slots=True)
class Probe:
    """What asking one model came to.

    Attributes:
        model: The entry that was asked.
        ok: Whether it answered.
        seconds: How long the answer, or the failure, took.
        detail: When it answered, the reply (trimmed); when it did not, why.
        tokens: ``(input, output)`` tokens the answer cost, or ``None`` when it did not answer or did not say.
    """

    model: ModelConfig
    ok: bool
    seconds: float
    detail: str = ""
    tokens: tuple[int, int] | None = None


def _one_line(text: str) -> str:
    """Return ``text`` as a single line no longer than :data:`DETAIL_LIMIT`."""
    line = " ".join(text.split())
    return line if len(line) <= DETAIL_LIMIT else line[: DETAIL_LIMIT - 1] + "…"


async def _ask(model: ModelConfig) -> tuple[str, tuple[int, int] | None]:
    """Send the question to ``model`` and return its reply and the tokens it cost; raises what the provider raises."""
    from zett_agent.messages import UserMessage
    from zett_agent.model import ModelEventType, ModelRequest

    from .engine.core import _build_provider

    provider = _build_provider(model)
    try:
        request = ModelRequest(messages=[UserMessage(content=QUESTION)], reasoning_effort=model.efforts[0])
        async for event in provider.stream(request):
            if event.type is not ModelEventType.RESPONSE or event.response is None:
                continue
            response = event.response
            stop = response.stop
            if stop is not None and stop.reason.value == "refusal":
                raise RuntimeError(f"the model refused the question: {stop.describe()}")
            content = response.message.content
            reply = content if isinstance(content, str) else "".join(getattr(part, "text", "") for part in content)
            usage = response.usage
            tokens = (usage.input_tokens, usage.output_tokens) if usage.input_tokens or usage.output_tokens else None
            return reply, tokens
        raise RuntimeError("the stream ended without a reply")
    finally:
        await provider.aclose()


async def probe(
    model: ModelConfig,
    *,
    timeout: float = TIMEOUT,
    ask: Callable[[ModelConfig], Awaitable[tuple[str, tuple[int, int] | None]]] = _ask,
) -> Probe:
    """Ask one model the question and report how it went; never raises.

    Args:
        model: The entry to ask.
        timeout: Seconds to wait for the answer.
        ask: Sends the question; injectable so a test needs no network.
    """
    started = time.monotonic()
    try:
        reply, tokens = await asyncio.wait_for(ask(model), timeout)
    except asyncio.TimeoutError:
        return Probe(model, False, time.monotonic() - started, f"no answer within {timeout:g} seconds")
    except Exception as error:  # noqa: BLE001 - every kind of failure is an answer to "does it work"
        text = _one_line(str(error)) or type(error).__name__
        return Probe(model, False, time.monotonic() - started, text)
    return Probe(model, True, time.monotonic() - started, _one_line(reply), tokens)


async def diagnose(
    models: Sequence[ModelConfig],
    *,
    timeout: float = TIMEOUT,
    ask: Callable[[ModelConfig], Awaitable[tuple[str, tuple[int, int] | None]]] = _ask,
) -> list[Probe]:
    """Ask every model at once and return the probes in the order the models are configured."""
    return list(await asyncio.gather(*(probe(model, timeout=timeout, ask=ask) for model in models)))


def format_report(probes: Sequence[Probe]) -> list[str]:
    """Return the lines that tell the reader which models work, one per model, and a closing tally."""
    if not probes:
        return ["no models are configured"]
    width = max(len(probe.model.shown_name) for probe in probes)
    lines: list[str] = []
    for item in probes:
        mark = "ok  " if item.ok else "FAIL"
        name = item.model.shown_name.ljust(width)
        if item.ok:
            cost = f", {item.tokens[0]} in / {item.tokens[1]} out" if item.tokens else ""
            lines.append(f"{mark} {name}  {item.seconds:.1f}s  {item.model.api.value}{cost}")
        else:
            lines.append(f"{mark} {name}  {item.seconds:.1f}s  {item.model.api.value}: {item.detail}")
    failed = sum(not item.ok for item in probes)
    lines.append(
        f"{len(probes)} model{'s' * (len(probes) != 1)} checked: "
        + ("all answered" if not failed else f"{len(probes) - failed} answered, {failed} did not")
    )
    return lines


def doctor_program(
    config: ZettCodeConfig,
    *,
    timeout: float = TIMEOUT,
    ask: Callable[[ModelConfig], Awaitable[tuple[str, tuple[int, int] | None]]] = _ask,
    say: Callable[[str], None] = print,
) -> int:
    """Check the configured models from the command line: what ``zettcode doctor`` does.

    Args:
        config: The settings, whose models are asked.
        timeout: Seconds each model may take.
        ask: Sends the question; injectable so a test needs no network.
        say: Where the report goes.

    Returns:
        ``0`` when every model answered, ``1`` when one did not or none is configured.
    """
    from . import __version__
    from .paths import config_path

    say(f"ZettCode {__version__} · config {config_path()}")
    probes = asyncio.run(diagnose(config.models, timeout=timeout, ask=ask))
    for line in format_report(probes):
        say(line)
    return 0 if probes and all(item.ok for item in probes) else 1
