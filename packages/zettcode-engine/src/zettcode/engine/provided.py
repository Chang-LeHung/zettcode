"""What a plugin offered, as the configuration entries a request is built from."""

from __future__ import annotations

import os
from collections.abc import Iterable

from zett_agent.model import ReasoningEffort

from zettcode.config import DEFAULT_COMPACT_PERCENT, DEFAULT_CONTEXT_WINDOW, ModelConfig
from zettcode.providers import Api, ProvidedModel, Provider


def model_from(provider: Provider, model: ProvidedModel) -> ModelConfig:
    """Return the entry one provided model stands for.

    The provider supplies what the model does not: the protocol, the address, whether it takes images, and the
    environment variable its token is read from. The token is read here — a provided model is not in the
    configuration file, so the environment is the only place a key can come from — and a provider that names none
    is a host that takes no key, as a local server does. A variable the provider names but the environment does not
    set leaves the token empty and is recorded on the entry (``token_env``), so a list can say which key is missing.

    Raises:
        ValueError: The model, the provider, or the token they make cannot form an entry (an unknown reasoning
            level, a temperature the protocol refuses, a blank model id).
    """
    api = model.api or provider.api
    token = os.getenv(provider.token_env, "") if provider.token_env else ""
    try:
        return ModelConfig(
            model=model.model,
            token=token,
            display_model=model.display_model,
            base_url=model.base_url or provider.base_url,
            anthropic=api is Api.ANTHROPIC,
            responses_api=api is Api.RESPONSES,
            multimodal=provider.multimodal if model.multimodal is None else model.multimodal,
            context_window=model.context_window or DEFAULT_CONTEXT_WINDOW,
            compact_percent=model.compact_percent or DEFAULT_COMPACT_PERCENT,
            reasoning_efforts=tuple(ReasoningEffort(level) for level in model.reasoning_efforts),
            temperature=model.temperature,
            provider=provider.name,
            token_env=provider.token_env if provider.token_env and not token else None,
        )
    except ValueError as error:
        raise ValueError(f"Provider {provider.name!r}, model {model.model!r}: {error}") from error


def entries(providers: Iterable[Provider]) -> tuple[ModelConfig, ...]:
    """Return every model the providers offer, in the order they were registered."""
    return tuple(model_from(provider, model) for provider in providers for model in provider.models)


def merged(file_models: tuple[ModelConfig, ...], provided: tuple[ModelConfig, ...]) -> tuple[ModelConfig, ...]:
    """Return the file's models followed by the provided ones, dropping a provided name the file already shows.

    A model is chosen by the name a list shows, so two entries under one name would make ``/model`` a guess. The
    file is the reader's and wins: a provided model whose name it took is not offered. (A clash between plugins is
    refused when the later one loads, so it never reaches this function.) A file entry added after the plugins
    loaded can therefore make a provided model disappear from ``/model`` with no word; if it was the one in use,
    :meth:`ZettCodeEngine.replace_models` moves to its neighbour.
    """
    seen = {model.shown_name for model in file_models}
    merged_models: list[ModelConfig] = list(file_models)
    for model in provided:
        if model.shown_name in seen:
            continue
        seen.add(model.shown_name)
        merged_models.append(model)
    return tuple(merged_models)
