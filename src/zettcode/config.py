"""Validated construction settings for the ZettCode runtime."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from zett_agent import ReasoningEffort, ShellApprovalMode


class ProviderName(StrEnum):
    """Provider adapters exposed by the initial CLI."""

    DEEPSEEK = "deepseek"
    OPENAI = "openai"


@dataclass(frozen=True, slots=True)
class ZettCodeConfig:
    """All process-level settings needed to construct one coding runtime.

    Attributes:
        workspace: Directory the agent works in; must exist, and ``~`` is
            expanded before validation.
        provider: Which adapter to build.
        model: Model name passed to the provider; must not be blank.
        api_key: Credential for the provider; must not be blank.
        store: Directory holding the JSONL session tree, one file per session;
            ``~`` is expanded. It is created on demand, so it may not exist yet.
        theme_file: Optional TOML palette loaded on top of ``theme``.
        session_id: Session to resume; ``None`` starts a fresh one.
        base_url: Overrides the provider endpoint for a self-hosted gateway.
        responses_api: Use the Responses API rather than chat completions.
        reasoning_effort: How much reasoning budget to request per turn.
        shell_approval: When the agent must ask before running a shell command.
        reduced_motion: Suppress decorative animation.
        parallel_tool_call: Let the agent issue tool calls in parallel.
        max_iterations: Tool-call rounds allowed in one turn.
        compaction_max_tokens: Context size at which compaction triggers.
        compaction_keep_tokens: Tokens preserved verbatim by compaction; must be
            smaller than ``compaction_max_tokens``.
    """

    workspace: Path
    provider: ProviderName
    model: str
    api_key: str
    store: Path
    theme_file: Path | None = None
    session_id: str | None = None
    base_url: str | None = None
    responses_api: bool = False
    reasoning_effort: ReasoningEffort = ReasoningEffort.MEDIUM
    shell_approval: ShellApprovalMode = ShellApprovalMode.REVIEW
    reduced_motion: bool = False
    parallel_tool_call: bool = True
    max_iterations: int = 36
    compaction_max_tokens: int = 128_000
    compaction_keep_tokens: int = 32_000

    def __post_init__(self) -> None:
        """Normalize the paths and reject settings that cannot build a runtime."""
        workspace = self.workspace.expanduser().resolve()
        store = self.store.expanduser().resolve()
        if not workspace.is_dir():
            raise ValueError(f"Workspace is not a directory: {workspace}")
        if not self.model.strip():
            raise ValueError("Model cannot be empty")
        if not self.api_key.strip():
            raise ValueError(f"Missing API key for {self.provider.value}")
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be positive")
        if self.compaction_keep_tokens < 1:
            raise ValueError("compaction_keep_tokens must be positive")
        if self.compaction_max_tokens <= self.compaction_keep_tokens:
            raise ValueError("compaction_max_tokens must be greater than compaction_keep_tokens")
        object.__setattr__(self, "workspace", workspace)
        object.__setattr__(self, "store", store)
        if self.theme_file is not None:
            object.__setattr__(self, "theme_file", self.theme_file.expanduser().resolve())


def provider_api_key(provider: ProviderName) -> str:
    """Read the selected provider credential without logging it."""
    match provider:
        case ProviderName.DEEPSEEK:
            return os.getenv("DEEPSEEK_API_KEY") or os.getenv("DEEPSEEK_API", "")
        case ProviderName.OPENAI:
            return os.getenv("OPENAI_API_KEY", "")


def default_model(provider: ProviderName) -> str:
    """Return a conservative default model for one provider."""
    match provider:
        case ProviderName.DEEPSEEK:
            return "deepseek-chat"
        case ProviderName.OPENAI:
            return "gpt-5-mini"
