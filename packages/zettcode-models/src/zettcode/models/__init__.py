"""Official models for the vendor API keys found in the environment.

A reader who has ``OPENAI_API_KEY``, ``ANTHROPIC_API_KEY``, ``DEEPSEEK_API_KEY`` or ``ZAI_API_KEY`` set does not
have to type an address or a model id to try that vendor. The plugin knows the current official model of each host,
registers it as one :class:`~zettcode.plugin_api.ProvidedModel`, and leaves the token to the runtime, which reads it
from the variable named here and never writes it to the configuration.

The list is deliberately static: a start asks no vendor for anything, so a key in the environment costs no network
round trip. It is off by default — ambient keys should not change a model list unless the reader enables the plugin
with ``[plugins] enable = ["models"]``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from zettcode.plugin_api import Api, Plugin, PluginContext, ProvidedModel, Provider

#: The one place the version is written; ``pyproject.toml`` reads it from here.
__version__ = "0.1.0"


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
    api: Api
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
VENDORS: tuple[Vendor, ...] = (
    Vendor(
        "openai",
        "OpenAI",
        ("OPENAI_API_KEY",),
        "https://api.openai.com/v1",
        Api.CHAT,
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
        Api.ANTHROPIC,
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
        Api.CHAT,
        "deepseek-v4.1-flash",
        "DeepSeek V4.1 Flash",
        1_000_000,
    ),
    Vendor(
        "zai",
        "Z.AI",
        ("ZAI_API_KEY", "ZHIPUAI_API_KEY", "ZHIPU_API_KEY"),
        "https://api.z.ai/api/paas/v4",
        Api.CHAT,
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
        api=vendor.api,
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

    @classmethod
    def default_enabled(cls) -> bool:
        """Stay off until the reader asks for it: ambient keys should not change a model list by themselves."""
        return False

    def activate(self, ctx: PluginContext) -> None:
        """Register the host of every key that is set, with its current official model."""
        clashes: list[str] = []
        for vendor in VENDORS:
            key = vendor.key()
            if key is None:
                continue
            try:
                ctx.agent.register_provider(_provider(vendor, key[0]))
            except ValueError as error:
                # A clash is not swallowed: the loader reports this plugin failed, so the reader sees why the host
                # is absent instead of finding it missing with no word. Every clash is named, not only the first.
                clashes.append(f"{vendor.label}: {error}")
        if clashes:
            raise ValueError("; ".join(clashes))


__all__ = ["ModelsPlugin", "Vendor", "VENDORS", "__version__"]
