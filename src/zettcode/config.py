"""Validated settings for the ZettCode runtime, and the file they come from.

``~/.zettcode/config.toml`` (or ``$ZETTCODE_CONFIG``) lists OpenAI-compatible
models. The first model is active at startup; ``/model`` selects another for
later requests. The same file says whether project ``AGENTS.md`` files are
read, whether the model may ask questions, where skills live, which MCP server
file to read, how much transcript to keep on screen, and whether to look for a
newer release; session storage and other runtime settings keep code defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar, overload

from zett_agent.extensions.shell_approval import ShellApprovalMode
from zett_agent.model import ReasoningEffort

from ._compat import tomllib
from .paths import CONFIG_FILE, DEFAULT_STORE, DEFAULT_UPDATE_FILE

#: The concrete type :func:`_typed` verifies a raw config value against.
T = TypeVar("T")

#: Top-level keys the config file may set; anything else is a typo.
CONFIGURABLE = frozenset({"models", "transcript", "agents_md", "ask_user", "skills", "mcp", "plugins", "update"})

#: Keys one ``[[models]]`` entry may set.
MODEL_KEYS = frozenset(
    {"model", "display_model", "token", "base_url", "responses_api", "multimodal", "context_window", "compact_percent"}
)

#: Keys the ``[transcript]`` table may set.
TRANSCRIPT_KEYS = frozenset({"max_entries"})

#: Keys the ``[agents_md]`` table may set.
AGENTS_MD_KEYS = frozenset({"enabled"})

#: Keys the ``[ask_user]`` table may set.
ASK_USER_KEYS = frozenset({"enabled"})

#: Keys the ``[skills]`` table may set.
SKILL_KEYS = frozenset({"enabled", "roots"})

#: Keys the ``[mcp]`` table may set.
MCP_KEYS = frozenset({"enabled", "config"})

#: Keys the ``[plugins]`` table may set.
PLUGIN_KEYS = frozenset({"enabled", "disable"})

#: Keys the ``[update]`` table may set.
UPDATE_KEYS = frozenset({"enabled"})

#: Where ZettCode's own skills live, searched after any ``[skills] roots``. A
#: project-local directory is a configured root, not a default: only what the
#: user asks for is scanned.
DEFAULT_SKILL_ROOT = "~/.zettcode/skills"

#: Tokens per model a request may carry before it is compacted, when the config
#: does not say otherwise; and the share of the trigger kept verbatim.
DEFAULT_CONTEXT_WINDOW = 128_000
DEFAULT_COMPACT_PERCENT = 80.0
KEEP_SHARE = 4

#: Conversation entries kept on screen before the oldest are dropped. The
#: session file keeps the whole tree, so this bounds scrollback, not history.
DEFAULT_TRANSCRIPT_MAX_ENTRIES = 1024


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
        context_window: Tokens the model can carry, which is what ``/context``
            measures against.
        compact_percent: Share of :attr:`context_window` at which a request is
            compacted, in percent.
    """

    model: str
    token: str
    display_model: str | None = None
    base_url: str | None = None
    responses_api: bool = False
    multimodal: bool = False
    context_window: int = DEFAULT_CONTEXT_WINDOW
    compact_percent: float = DEFAULT_COMPACT_PERCENT

    def __post_init__(self) -> None:
        """Reject a model that cannot be called."""
        if not self.model.strip():
            raise ValueError("Model cannot be empty")
        if not self.token.strip():
            raise ValueError(f"Missing token for model {self.model!r}; set 'token' or OPENAI_API_KEY")
        if self.context_window < 1:
            raise ValueError(f"context_window must be positive for model {self.model!r}")
        if not 0 < self.compact_percent <= 100:
            raise ValueError(f"compact_percent must be between 0 and 100 for model {self.model!r}")

    @property
    def shown_name(self) -> str:
        """Return the name to display for the model."""
        return self.display_model or self.model

    @property
    def compaction_max_tokens(self) -> int:
        """Return the estimated context size at which this model is compacted."""
        return max(1, round(self.context_window * self.compact_percent / 100))

    @property
    def compaction_keep_tokens(self) -> int:
        """Return the recent tokens a compaction keeps: the last quarter of the trigger."""
        return max(1, self.compaction_max_tokens // KEEP_SHARE)


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
        transcript_max_entries: Conversation entries the shell keeps on screen;
            older ones are dropped from the display while the session file
            keeps the whole tree.
        agents_md_enabled: Read the ``AGENTS.md`` files that apply to the
            workspace and give them to the model as project instructions.
        ask_user_enabled: Give the model the ``ask_user`` tool, which pauses a
            turn until the reader answers a question in the shell.
        skills_enabled: Discover local skills and advertise them to the model.
        skill_roots: Extra skill directories, searched before
            ``~/.zettcode/skills``; a relative entry is resolved against the
            workspace, which is how a project ships skills in
            ``.zettcode/skills``.
        mcp_enabled: Load MCP servers from :attr:`mcp_config`.
        mcp_config: JSON file naming MCP servers; ``None`` uses
            ``~/.zettcode/mcp.json``.
        plugins_enabled: Load third-party plugins published under the
            ``zettcode.plugins`` entry-point group. The builtin rows always
            load, so switching this off leaves the shell looking the same.
        disabled_plugins: Entry-point names not to load when
            :attr:`plugins_enabled` is true; a way to switch off one plugin
            without uninstalling it.
        update_enabled: Ask PyPI, in the background, whether a newer release
            exists, and offer it on a later start.
        update_file: Where that check leaves what it found; one small JSON file.
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
    transcript_max_entries: int = DEFAULT_TRANSCRIPT_MAX_ENTRIES
    agents_md_enabled: bool = True
    ask_user_enabled: bool = True
    skills_enabled: bool = True
    skill_roots: tuple[Path, ...] = ()
    mcp_enabled: bool = True
    mcp_config: Path | None = None
    plugins_enabled: bool = True
    disabled_plugins: tuple[str, ...] = ()
    update_enabled: bool = True
    update_file: Path = DEFAULT_UPDATE_FILE

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
        if self.transcript_max_entries < 1:
            raise ValueError("transcript_max_entries must be positive")
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
        object.__setattr__(self, "update_file", self.update_file.expanduser().resolve())

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


def _typed(value: object, where: str, expected: type[T]) -> T:
    """Return one value, rejecting a wrong type with a located message."""
    if expected is int and isinstance(value, bool):
        raise ValueError(f"{where} must be int")
    if not isinstance(value, expected):
        raise ValueError(f"{where} must be {expected.__name__}")
    return value


def _number(value: object, where: str) -> float:
    """Return an int-or-float setting as a float, rejecting a bool and anything else."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{where} must be a number")
    return float(value)


def _resolve_root(root: str | Path, workspace: Path) -> Path:
    """Return one configured directory: ``~`` expanded, a relative path against the workspace."""
    expanded = Path(root).expanduser()
    return (expanded if expanded.is_absolute() else workspace / expanded).resolve()


@overload
def _setting(data: dict[str, object], key: str, expected: type[T], default: T) -> T: ...


@overload
def _setting(data: dict[str, object], key: str, expected: type[T], default: None = None) -> T | None: ...


def _setting(data: dict[str, object], key: str, expected: type, default: object = None) -> object:
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
        context_window=_typed(
            entry.get("context_window", DEFAULT_CONTEXT_WINDOW), f"{label} key 'context_window'", int
        ),
        compact_percent=_number(
            entry.get("compact_percent", DEFAULT_COMPACT_PERCENT), f"{label} key 'compact_percent'"
        ),
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


def _read_disabled_plugins(raw: object, source: Path) -> tuple[str, ...]:
    """Return the entry-point names the ``[plugins]`` table switches off."""
    if raw is None:
        return ()
    if not isinstance(raw, list) or any(not isinstance(entry, str) or not entry.strip() for entry in raw):
        raise ValueError(f"Config key 'plugins.disable' in {source} must be an array of non-empty strings")
    return tuple(entry.strip() for entry in raw)


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

    agents_md = _read_table(data.get("agents_md"), "agents_md", source, AGENTS_MD_KEYS)
    ask_user = _read_table(data.get("ask_user"), "ask_user", source, ASK_USER_KEYS)
    skills = _read_table(data.get("skills"), "skills", source, SKILL_KEYS)
    mcp = _read_table(data.get("mcp"), "mcp", source, MCP_KEYS)
    plugins = _read_table(data.get("plugins"), "plugins", source, PLUGIN_KEYS)
    transcript = _read_table(data.get("transcript"), "transcript", source, TRANSCRIPT_KEYS)
    update = _read_table(data.get("update"), "update", source, UPDATE_KEYS)

    return ZettCodeConfig(
        workspace=Path(workspace),
        models=_read_models(data.get("models"), source),
        theme_file=_default_theme_file(),
        reduced_motion=reduced_motion_default,
        transcript_max_entries=_typed(
            transcript.get("max_entries", DEFAULT_TRANSCRIPT_MAX_ENTRIES),
            f"Config key 'transcript.max_entries' in {source}",
            int,
        ),
        agents_md_enabled=bool(_setting(agents_md, "enabled", bool, True)),
        ask_user_enabled=bool(_setting(ask_user, "enabled", bool, True)),
        skills_enabled=bool(_setting(skills, "enabled", bool, True)),
        skill_roots=_read_skill_roots(skills.get("roots"), source),
        mcp_enabled=bool(_setting(mcp, "enabled", bool, True)),
        mcp_config=_read_mcp_config(mcp.get("config"), source),
        plugins_enabled=bool(_setting(plugins, "enabled", bool, True)),
        disabled_plugins=_read_disabled_plugins(plugins.get("disable"), source),
        update_enabled=bool(_setting(update, "enabled", bool, True)),
    )
