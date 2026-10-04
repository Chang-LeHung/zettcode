"""Validated settings for the ZettCode runtime, and the file they come from.

``~/.zettcode/config.toml`` (or ``$ZETTCODE_CONFIG``) lists OpenAI-compatible
models. The first model is active at startup; ``/model`` selects another for
later requests. The same file says where skills live and which MCP server file
to read, and session storage and other runtime settings keep code defaults.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from zett_agent import ReasoningEffort, ShellApprovalMode

#: The conventional config file, read when the user has created one.
CONFIG_FILE = Path.home() / ".zettcode" / "config.toml"

#: Session storage is an application default, not a model setting.
DEFAULT_STORE = Path.home() / ".zettcode" / "sessions"

#: MCP servers are ZettCode's own file, so they are configured independently of
#: whatever other zett tools read.
DEFAULT_MCP_CONFIG = Path.home() / ".zettcode" / "mcp.json"

#: Anything written to stderr while the TUI owns the screen is kept here: a
#: child process — an MCP server announcing itself, say — cannot know that the
#: frame is the interface, and the renderer only repaints what it changed.
DEFAULT_LOG = Path.home() / ".zettcode" / "log" / "tui.log"

#: Top-level keys the config file may set; anything else is a typo.
CONFIGURABLE = frozenset({"models", "skills", "mcp"})

#: Keys one ``[[models]]`` entry may set.
MODEL_KEYS = frozenset({"model", "display_model", "token", "base_url", "responses_api", "multimodal"})

#: Keys the ``[skills]`` table may set.
SKILL_KEYS = frozenset({"enabled", "roots"})

#: Keys the ``[mcp]`` table may set.
MCP_KEYS = frozenset({"enabled", "config"})

#: Where ZettCode's own skills live, searched after any ``[skills] roots``. A
#: project-local directory is a configured root, not a default: only what the
#: user asks for is scanned.
DEFAULT_SKILL_ROOT = "~/.zettcode/skills"


@dataclass(frozen=True, slots=True)
class ModelConfig:
    """One OpenAI-compatible model: what to call, where, and with which token.

    Attributes:
        model: Model id sent to the endpoint; must not be blank.
        token: Credential for the endpoint; must not be blank.
        display_model: Name shown in the UI; ``None`` shows :attr:`model`.
        base_url: Endpoint of an OpenAI-compatible gateway; ``None`` uses the
            client's default.
        responses_api: Use the Responses API rather than chat completions.
        multimodal: Whether the model accepts images as well as text.
    """

    model: str
    token: str
    display_model: str | None = None
    base_url: str | None = None
    responses_api: bool = False
    multimodal: bool = False

    def __post_init__(self) -> None:
        """Reject a model that cannot be called."""
        if not self.model.strip():
            raise ValueError("Model cannot be empty")
        if not self.token.strip():
            raise ValueError(f"Missing token for model {self.model!r}; set 'token' or OPENAI_API_KEY")

    @property
    def shown_name(self) -> str:
        """Return the name to display for the model."""
        return self.display_model or self.model


@dataclass(frozen=True, slots=True)
class ZettCodeConfig:
    """All process-level settings needed to construct one coding runtime.

    Attributes:
        workspace: Directory the agent works in; must exist, and ``~`` is
            expanded before validation.
        store: Directory holding the JSONL session tree, one file per session;
            ``~`` is expanded. Set programmatically; it is not a TOML setting.
        models: Available models, in file order; the first is active at startup.
        theme_file: Optional TOML palette loaded on top of ``theme``.
        reasoning_effort: How much reasoning budget to request per turn.
        shell_approval: When the agent must ask before running a shell command.
        reduced_motion: Suppress decorative animation.
        parallel_tool_call: Let the agent issue tool calls in parallel.
        max_iterations: Tool-call rounds allowed in one turn.
        compaction_max_tokens: Context size at which compaction triggers.
        compaction_keep_tokens: Tokens preserved verbatim by compaction; must be
            smaller than ``compaction_max_tokens``.
        skills_enabled: Discover local skills and advertise them to the model.
        skill_roots: Extra skill directories, searched before
            ``~/.zettcode/skills``; a relative entry is resolved against the
            workspace, which is how a project ships skills in
            ``.zettcode/skills``.
        mcp_enabled: Load MCP servers from :attr:`mcp_config`.
        mcp_config: JSON file naming MCP servers; ``None`` uses
            ``~/.zettcode/mcp.json``.
    """

    workspace: Path
    models: tuple[ModelConfig, ...]
    store: Path = DEFAULT_STORE
    theme_file: Path | None = None
    reasoning_effort: ReasoningEffort = ReasoningEffort.MEDIUM
    shell_approval: ShellApprovalMode = ShellApprovalMode.REVIEW
    reduced_motion: bool = False
    parallel_tool_call: bool = True
    max_iterations: int = 360
    compaction_max_tokens: int = 128_000
    compaction_keep_tokens: int = 32_000
    skills_enabled: bool = True
    skill_roots: tuple[Path, ...] = ()
    mcp_enabled: bool = True
    mcp_config: Path | None = None

    def __post_init__(self) -> None:
        """Normalize the paths and reject settings that cannot build a runtime."""
        workspace = self.workspace.expanduser().resolve()
        store = self.store.expanduser().resolve()
        if not workspace.is_dir():
            raise ValueError(f"Workspace is not a directory: {workspace}")
        if not self.models:
            raise ValueError("At least one model must be configured")
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be positive")
        if self.compaction_keep_tokens < 1:
            raise ValueError("compaction_keep_tokens must be positive")
        if self.compaction_max_tokens <= self.compaction_keep_tokens:
            raise ValueError("compaction_max_tokens must be greater than compaction_keep_tokens")
        object.__setattr__(self, "workspace", workspace)
        object.__setattr__(self, "store", store)
        object.__setattr__(
            self,
            "skill_roots",
            tuple(_resolve_root(root, workspace) for root in self.skill_roots),
        )
        if self.theme_file is not None:
            object.__setattr__(self, "theme_file", self.theme_file.expanduser().resolve())
        if self.mcp_config is not None:
            object.__setattr__(self, "mcp_config", self.mcp_config.expanduser().resolve())

    def skill_search_roots(self) -> tuple[Path, ...]:
        """Return every skill directory to scan, most specific first.

        The configured roots come first so a run can point at a team directory
        or at a project-local one, then the user's own skills. A name declared
        twice belongs to the earlier directory.
        """
        default = _resolve_root(DEFAULT_SKILL_ROOT, self.workspace)
        return (*self.skill_roots, default)


def config_path(path: str | Path | None = None) -> Path:
    """Return the config file to read: an explicit path, ``$ZETTCODE_CONFIG``, or the default."""
    if path is not None:
        return Path(path).expanduser()
    override = os.getenv("ZETTCODE_CONFIG")
    return Path(override).expanduser() if override else CONFIG_FILE


def _default_theme_file() -> Path | None:
    """Return the conventional palette file when the user has created one."""
    candidate = Path.home() / ".zettcode" / "theme.toml"
    return candidate if candidate.is_file() else None


def _typed(value: object, where: str, expected: type) -> object:
    """Return one value, rejecting a wrong type with a located message."""
    if expected is int and isinstance(value, bool):
        raise ValueError(f"{where} must be int")
    if not isinstance(value, expected):
        raise ValueError(f"{where} must be {expected.__name__}")
    return value


def _resolve_root(root: str | Path, workspace: Path) -> Path:
    """Return one configured directory: ``~`` expanded, a relative path against the workspace."""
    expanded = Path(root).expanduser()
    return (expanded if expanded.is_absolute() else workspace / expanded).resolve()


def _setting(data: dict[str, object], key: str, expected: type, default: object) -> object:
    """Return one model setting, rejecting a wrong type."""
    value = data.get(key, default)
    if value is None:
        return None
    return _typed(value, f"Config key {key!r}", expected)


def _entry_model(entry: dict[str, object], index: int) -> ModelConfig:
    """Build one model from a ``[[models]]`` table, rejecting unknown keys."""
    label = f"Config models[{index}]"
    unknown = sorted(set(entry) - MODEL_KEYS)
    if unknown:
        raise ValueError(f"Unknown config keys in {label}: {', '.join(unknown)}")
    model = entry.get("model")
    if model is None:
        raise ValueError(f"{label} is missing 'model'")
    token = entry.get("token") or os.getenv("OPENAI_API_KEY", "")
    return ModelConfig(
        model=_typed(model, f"{label} key 'model'", str),
        token=_typed(token, f"{label} key 'token'", str),
        display_model=_setting(entry, "display_model", str, None),
        base_url=_setting(entry, "base_url", str, None),
        responses_api=_setting(entry, "responses_api", bool, False),
        multimodal=_setting(entry, "multimodal", bool, False),
    )


def _read_models(raw: object, source: Path) -> tuple[ModelConfig, ...]:
    """Build every configured model, requiring at least one."""
    if raw is None:
        raise ValueError(f"No models configured in {source}; add at least one [[models]] entry")
    if not isinstance(raw, list):
        raise ValueError("Config key 'models' must be an array of tables ([[models]])")
    if not raw:
        raise ValueError(f"No models configured in {source}; add at least one [[models]] entry")
    if any(not isinstance(entry, dict) for entry in raw):
        raise ValueError("Config key 'models' must be an array of tables ([[models]])")
    models = [_entry_model(entry, index) for index, entry in enumerate(raw, start=1)]
    return tuple(models)


def _read_table(raw: object, key: str, source: Path, allowed: frozenset[str]) -> dict[str, object]:
    """Return one optional config table, rejecting unknown keys and wrong shapes."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"Config key {key!r} must be a table ([{key}])")
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError(f"Unknown config keys in the [{key}] table of {source}: {', '.join(unknown)}")
    return raw


def _read_skill_roots(raw: object, source: Path) -> tuple[Path, ...]:
    """Return the extra skill directories, requiring strings in an array."""
    if raw is None:
        return ()
    if not isinstance(raw, list) or any(not isinstance(entry, str) for entry in raw):
        raise ValueError(f"Config key 'skills.roots' in {source} must be an array of strings")
    return tuple(Path(entry) for entry in raw)


def _read_mcp_config(raw: object, source: Path) -> Path | None:
    """Return the MCP server file the config points at, if it points at one."""
    if raw is None:
        return None
    return Path(_typed(raw, f"Config key 'mcp.config' in {source}", str))


def load_config(
    workspace: str | Path,
    *,
    path: str | Path | None = None,
    reduced_motion_default: bool = False,
) -> ZettCodeConfig:
    """Build the runtime settings from the config file, falling back to defaults.

    Args:
        workspace: Directory the agent works in; the one value still passed on
            the command line.
        path: Config file to read; ``None`` uses ``$ZETTCODE_CONFIG`` or
            ``~/.zettcode/config.toml``.
        reduced_motion_default: Value for ``reduced_motion`` when the file does
            not set it; the caller passes the terminal/environment detection.

    Raises:
        ValueError: For an unreadable file, an unknown key, a wrong type, or a
            missing model.
    """
    source = config_path(path)
    data: dict[str, object] = {}
    if source.is_file():
        try:
            data = tomllib.loads(source.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as error:
            raise ValueError(f"Invalid config file {source}: {error}") from error
        unknown = sorted(set(data) - CONFIGURABLE)
        if unknown:
            raise ValueError(f"Unknown config keys in {source}: {', '.join(unknown)}")

    skills = _read_table(data.get("skills"), "skills", source, SKILL_KEYS)
    mcp = _read_table(data.get("mcp"), "mcp", source, MCP_KEYS)

    return ZettCodeConfig(
        workspace=Path(workspace),
        models=_read_models(data.get("models"), source),
        theme_file=_default_theme_file(),
        reduced_motion=reduced_motion_default,
        skills_enabled=bool(_setting(skills, "enabled", bool, True)),
        skill_roots=_read_skill_roots(skills.get("roots"), source),
        mcp_enabled=bool(_setting(mcp, "enabled", bool, True)),
        mcp_config=_read_mcp_config(mcp.get("config"), source),
    )
