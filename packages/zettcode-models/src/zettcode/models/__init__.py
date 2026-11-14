"""Official models for the vendor API keys found in the environment.

A reader who has ``OPENAI_API_KEY``, ``ANTHROPIC_API_KEY``, ``DEEPSEEK_API_KEY`` or ``ZAI_API_KEY`` set does not
have to type an address or a model id to try that vendor. The plugin knows the current official model of each host,
registers it as one :class:`~zettcode.plugin_api.ProvidedModel`, and leaves the token to the runtime, which reads it
from the variable named here and never writes it to the configuration.

The list is deliberately static: a start asks no vendor for anything, so a key in the environment costs no network
round trip. It is on by default: a key in the environment is enough for the host to be offered, and a machine whose
own configuration lists no model starts on the first one a plugin offers, so the first run is a prompt box rather
than an instruction. ``[plugins] disable = ["models"]`` is the way back out. A vendor whose host or shown name the
reader's own configuration already has is left out rather than failing the plugin, because one conflict must not
cost the vendors that do not conflict.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from zettcode.plugin_api import Plugin, PluginContext, ProvidedModel, Provider

logger = logging.getLogger("zettcode.models")

#: The one place the version is written; ``pyproject.toml`` reads it from here.
__version__ = "0.5.0"


@dataclass(frozen=True, slots=True)
class Vendor:
    """One host an environment variable can open.

    Attributes:
        name: The provider name, which is unique across the application.
        label: What a list shows for the host.
        env: The variables that may hold the key, most specific first.
        base_url: The address the client appends its route to.
        api: Which protocol the host speaks.
        model: The vendor's current official model id.
        display: What ``/model`` shows for it.
        context_window: Tokens it can carry.
        multimodal: Whether it takes images.
    """

    name: str
    label: str
    env: tuple[str, ...]
    base_url: str
    api: str
    model: str
    display: str
    context_window: int
    multimodal: bool = False

    def key(self) -> tuple[str, str] | None:
        """Return the variable that holds this host's key and the key itself, or ``None`` when none is set."""
        for variable in self.env:
            value = os.getenv(variable)
            if value:
                return variable, value
        return None


#: The official model offered for each host, checked against the vendors' model pages on 2026-11-10. The ids and
#: windows are the whole of this plugin's knowledge: when a vendor moves on, this table is the one place to edit.
#: DeepSeek's entry is what its own ``/models`` answers (2026-11-15): the vendor page gave the display name
#: (``DeepSeek-V4.1-Flash``), and the id a request takes is ``deepseek-flash`` — ``deepseek-v4.1-flash`` was refused
#: with "the supported API model names are deepseek-flash, deepseek-v4-pro".
VENDORS: tuple[Vendor, ...] = (
    Vendor(
        "openai",
        "OpenAI",
        ("OPENAI_API_KEY",),
        "https://api.openai.com/v1",
        "chat",
        "gpt-6.1-sol",
        "GPT-6.1 Sol",
        1_050_000,
        multimodal=True,
    ),
    Vendor(
        "anthropic",
        "Anthropic",
        ("ANTHROPIC_API_KEY",),
        "https://api.anthropic.com",
        "anthropic",
        "claude-opus-5-5",
        "Claude Opus 5.5",
        1_000_000,
        multimodal=True,
    ),
    Vendor(
        "deepseek",
        "DeepSeek",
        ("DEEPSEEK_API_KEY",),
        "https://api.deepseek.com",
        "chat",
        "deepseek-flash",
        "DeepSeek V4.1 Flash",
        1_048_576,
        multimodal=True,
    ),
    Vendor(
        "zai",
        "Z.AI",
        ("ZAI_API_KEY", "ZHIPUAI_API_KEY", "ZHIPU_API_KEY"),
        "https://api.z.ai/api/paas/v4",
        "chat",
        "glm-5.3",
        "GLM-5.3",
        1_000_000,
    ),
)


def _provider(vendor: Vendor, variable: str) -> Provider:
    """Return the host description for one vendor, with the one model it offers."""
    return Provider(
        vendor.name,
        vendor.label,
        # The vendor names the protocol as the word Provider parses.
        api=vendor.api,  # type: ignore[arg-type]
        base_url=vendor.base_url,
        token_env=variable,
        models=(
            ProvidedModel(
                vendor.model,
                display_model=vendor.display,
                context_window=vendor.context_window,
                multimodal=vendor.multimodal,
            ),
        ),
        note="official model",
    )


class ModelsPlugin(Plugin[PluginContext]):
    """Offer one official model for each vendor whose API key is in the environment."""

    name = "models"
    description = "An official model for each vendor API key in the environment"

    def activate(self, ctx: PluginContext) -> None:
        """Register the host of every key that is set, with its current official model."""
        for vendor in VENDORS:
            key = vendor.key()
            if key is None:
                continue
            try:
                ctx.agent.register_provider(_provider(vendor, key[0]))
            except ValueError as error:
                # A name the reader's own entries (or an earlier plugin) already have is theirs, not this plugin's:
                # it is on by default, so a conflict leaves that vendor out and costs the others nothing, rather
                # than failing a plugin nobody asked for.
                logger.info("models.skipped", extra={"vendor": vendor.name, "reason": str(error)})


__all__ = ["ModelsPlugin", "Vendor", "VENDORS", "__version__"]
