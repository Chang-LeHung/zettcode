"""Official models for the vendor API keys found in the environment.

A reader who has ``OPENAI_API_KEY``, ``ANTHROPIC_API_KEY``, ``DEEPSEEK_API_KEY``, ``ZAI_API_KEY`` or
``MOONSHOT_API_KEY`` set does not have to type an address or a model id to try that vendor. The plugin knows the
current official models of each host, registers them as :class:`~zettcode.plugin_api.ProvidedModel` entries, and
leaves the token to the runtime, which reads it from the variable named here and never writes it to the
configuration.

The list is deliberately static: a start asks no vendor for anything, so a key in the environment costs no network
round trip. It is on by default: a key in the environment is enough for the host to be offered, and a machine whose
own configuration lists no model starts on the first one a plugin offers, so the first run is a prompt box rather
than an instruction. ``[plugins] disable = ["models"]`` is the way back out. A vendor is left out, rather than
failing the plugin, when an earlier plugin has registered its host name, or when the reader's entries or an earlier
plugin already show any one of its models: one conflict must not cost the vendors that do not conflict.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from zettcode.plugin_api import Plugin, PluginContext, ProvidedModel, Provider

logger = logging.getLogger("zettcode.models")

#: The one place the version is written; ``pyproject.toml`` reads it from here.
__version__ = "0.5.1"


@dataclass(frozen=True, slots=True)
class VendorModel:
    """One official model a host serves, as the vendor documents it.

    Attributes:
        model: The model id a request takes.
        display: What ``/model`` shows for it.
        context_window: Tokens it can carry.
        multimodal: Whether it takes images; ``None`` is the host's own answer.
    """

    model: str
    display: str
    context_window: int
    multimodal: bool | None = None


@dataclass(frozen=True, slots=True)
class Vendor:
    """One host an environment variable can open.

    Attributes:
        name: The provider name, which is unique across the application.
        label: What a list shows for the host.
        env: The variables that may hold the key, most specific first.
        base_url: The address the client appends its route to.
        api: Which protocol the host speaks.
        models: The vendor's current official models, in the order a list shows them; a machine with no configuration
            of its own starts on the first one.
        multimodal: Whether the host's models take images, until one says otherwise.
    """

    name: str
    label: str
    env: tuple[str, ...]
    base_url: str
    api: str
    models: tuple[VendorModel, ...]
    multimodal: bool = False

    def key(self) -> tuple[str, str] | None:
        """Return the variable that holds this host's key and the key itself, or ``None`` when none is set."""
        for variable in self.env:
            value = os.getenv(variable)
            if value:
                return variable, value
        return None


#: The official models offered for each host, checked against the vendors' own pages on 2026-11-18. The ids and
#: windows are the whole of this plugin's knowledge: when a vendor moves on, this table is the one place to edit.
#: OpenAI's flagship is GPT-6.2 Astra and its everyday model GPT-6.2 Sol, both on a 1,050,000 window; neither takes
#: tools on Chat Completions ("tool calling requires the Responses API"), so the host speaks ``responses``.
#: Anthropic's ids are ``claude-opus-5-5`` and ``claude-sonnet-5-5``, both on a 1M window.
#: Kimi's are ``kimi-k3.1-pro`` (the flagship) and ``kimi-k3`` (the previous flagship), both on a 1,048,576 window and
#: reachable through the Anthropic-compatible endpoint Kimi documents for Claude Code; the key must be one issued by
#: platform.kimi.ai, because a mainland-platform key is for api.moonshot.cn and is refused here.
#: DeepSeek's two entries are what its own ``/models`` answers (2026-11-18): the vendor page gave the display names
#: (``DeepSeek-V4.1-Flash`` and ``DeepSeek-V4-Pro``), and the ids a request takes are ``deepseek-flash`` and
#: ``deepseek-v4-pro`` — ``deepseek-v4.1-flash`` was refused with "the supported API model names are deepseek-flash,
#: deepseek-v4-pro". Both speak the Messages API, because that is the endpoint their hosted tools live on and the
#: one this plugin was asked to default to; ``deepseek-flash`` takes images and ``deepseek-v4-pro`` text only.
VENDORS: tuple[Vendor, ...] = (
    Vendor(
        "openai",
        "OpenAI",
        ("OPENAI_API_KEY",),
        "https://api.openai.com/v1",
        "responses",
        (
            VendorModel("gpt-6.2-astra", "GPT-6.2 Astra", 1_050_000),
            VendorModel("gpt-6.2-sol", "GPT-6.2 Sol", 1_050_000),
        ),
        multimodal=True,
    ),
    Vendor(
        "anthropic",
        "Anthropic",
        ("ANTHROPIC_API_KEY",),
        "https://api.anthropic.com",
        "anthropic",
        (
            VendorModel("claude-opus-5-5", "Claude Opus 5.5", 1_000_000),
            VendorModel("claude-sonnet-5-5", "Claude Sonnet 5.5", 1_000_000),
        ),
        multimodal=True,
    ),
    Vendor(
        "deepseek",
        "DeepSeek",
        ("DEEPSEEK_API_KEY",),
        "https://api.deepseek.com/anthropic",
        "anthropic",
        (
            VendorModel("deepseek-flash", "DeepSeek V4.1 Flash", 1_048_576),
            VendorModel("deepseek-v4-pro", "DeepSeek V4 Pro", 1_048_576, multimodal=False),
        ),
        multimodal=True,
    ),
    Vendor(
        "zai",
        "Z.AI",
        ("ZAI_API_KEY", "ZHIPUAI_API_KEY", "ZHIPU_API_KEY"),
        "https://api.z.ai/api/paas/v4",
        "chat",
        (VendorModel("glm-5.3", "GLM-5.3", 1_000_000),),
    ),
    Vendor(
        "moonshot",
        "Moonshot AI",
        ("MOONSHOT_API_KEY",),
        "https://api.moonshot.ai/anthropic",
        "anthropic",
        (
            VendorModel("kimi-k3.1-pro", "Kimi K3.1 Pro", 1_048_576),
            VendorModel("kimi-k3", "Kimi K3", 1_048_576),
        ),
        multimodal=True,
    ),
)


def _provider(vendor: Vendor, variable: str) -> Provider:
    """Return the host description for one vendor, with every model it offers."""
    return Provider(
        vendor.name,
        vendor.label,
        # The vendor names the protocol as the word Provider parses.
        api=vendor.api,  # type: ignore[arg-type]
        base_url=vendor.base_url,
        token_env=variable,
        multimodal=vendor.multimodal,
        models=tuple(
            ProvidedModel(
                model.model,
                display_model=model.display,
                context_window=model.context_window,
                multimodal=model.multimodal,
            )
            for model in vendor.models
        ),
        note="official models",
    )


class ModelsPlugin(Plugin[PluginContext]):
    """Offer the official models for each vendor whose API key is in the environment."""

    name = "models"
    description = "Official models for each vendor API key in the environment"

    def activate(self, ctx: PluginContext) -> None:
        """Register the host of every key that is set, with its current official models."""
        for vendor in VENDORS:
            key = vendor.key()
            if key is None:
                continue
            try:
                ctx.agent.register_provider(_provider(vendor, key[0]))
            except ValueError as error:
                # A name that is taken is not this plugin's: a host name an earlier plugin registered, or a shown
                # name the reader's entries or an earlier plugin already use. It is on by default, so a conflict
                # leaves that vendor out and costs the others nothing, rather than failing a plugin nobody asked
                # for. It is a warning because a vendor can carry several models now, and one taken name quietly
                # costs the host the rest of them.
                logger.warning("models.skipped", extra={"vendor": vendor.name, "reason": str(error)})


__all__ = ["ModelsPlugin", "Vendor", "VendorModel", "VENDORS", "__version__"]
