"""Validated settings for the ZettCode runtime, and the file they come from.

``~/.zettcode/config.toml`` (or ``$ZETTCODE_CONFIG``) lists the models ZettCode
may call: an OpenAI-compatible chat-completions or Responses endpoint, or
Anthropic's Messages API, one entry each. The first model is active at startup;
``/model`` selects another for later requests. The same file says whether
project ``AGENTS.md`` files are read, whether the model may ask questions, where
skills live, which MCP server file to read, how much transcript to keep on
screen, and whether to look for a newer release; session storage and other
runtime settings keep code defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar, overload

from zett_agent.extensions.shell_approval import ShellApprovalMode
from zett_agent.model import ReasoningEffort

from ._compat import tomllib
from .paths import (
    DEFAULT_MCP_CONFIG,
    DEFAULT_STORE,
    DEFAULT_THEME_FILE,
    DEFAULT_THEMES_DIR,
    DEFAULT_UPDATE_FILE,
    config_path,
)
from .providers import Api
from .statusline import NAMES as STATUSLINE_NAMES

#: The concrete type :func:`_typed` verifies a raw config value against.
T = TypeVar("T")

#: Top-level keys the config file may set; anything else is a typo.
CONFIGURABLE = frozenset(
    {
        "models",
        "transcript",
        "agents_md",
        "ask_user",
        "skills",
        "mcp",
        "plugins",
        "update",
        "harness",
        "sessions",
        "compaction",
        "ui",
        "statusline",
    }
)

#: Keys one ``[[models]]`` entry may set.
MODEL_KEYS = frozenset(
    {
        "model",
        "display_model",
        "token",
        "base_url",
        "anthropic",
        "responses_api",
        "multimodal",
        "context_window",
        "compact_percent",
        "reasoning_efforts",
    }
)

#: Keys the ``[transcript]`` table may set.
TRANSCRIPT_KEYS = frozenset({"max_entries", "mouse_scroll_speed", "tips"})

#: Keys the ``[agents_md]`` table may set.
AGENTS_MD_KEYS = frozenset({"enabled"})

#: Keys the ``[ask_user]`` table may set.
ASK_USER_KEYS = frozenset({"enabled"})

#: Keys the ``[skills]`` table may set.
SKILL_KEYS = frozenset({"enabled", "roots", "scope"})

#: Keys the ``[mcp]`` table may set.
MCP_KEYS = frozenset({"enabled", "config", "scope"})

#: Keys the ``[compaction]`` table may set.
COMPACTION_KEYS = frozenset({"self"})

#: Where a directory-backed feature is looked for: the user's own files, the workspace's, or both.
#: A workspace file sits beside the project and is reviewed with it; the user's is the fallback every
#: checkout shares.
SCOPES = frozenset({"global", "workspace", "both"})

#: The scope a ``[skills]`` or ``[mcp]`` table uses when it names none: both, merged. The user's own
#: files and the workspace's are used together, the workspace's winning a name inside that project. A
#: workspace MCP entry is a command that gets run and a skill is instructions the model follows, and both
#: come from whatever repository is open; a reader who does not want a checkout's files read says
#: ``scope = "global"``.
DEFAULT_SCOPE = "both"

#: Keys the ``[plugins]`` table may set.
PLUGIN_KEYS = frozenset({"enabled", "disable"})

#: Keys the ``[update]`` table may set.
UPDATE_KEYS = frozenset({"enabled"})

#: Keys the ``[sessions]`` table may set.
SESSIONS_KEYS = frozenset({"enabled"})

#: Keys the ``[ui]`` table may set.
UI_KEYS = frozenset({"theme", "pet"})

#: The statusline parts that are hidden by default and made visible by choice.
OFF_BY_DEFAULT: frozenset[str] = frozenset({"pet"})

#: Keys the ``[statusline]`` table may set: the name of each part of the header and the status line.
STATUSLINE_KEYS = frozenset(STATUSLINE_NAMES)

#: Keys the ``[harness]`` table may set.
HARNESS_KEYS = frozenset({"subagent", "subagent_max_iterations", "todowrite"})

#: Model calls one subagent may make for the task it was given. A child that is exploring or editing
#: a real codebase makes dozens (a search, a read, an edit, a re-read, for each file), and the framework's
#: own default of 18 ended such a task halfway with a half-finished report; this is a ceiling against a
#: child that never stops, not a target.
DEFAULT_SUBAGENT_MAX_ITERATIONS = 512

#: Where ZettCode's own skills live, searched after any ``[skills] roots`` and after the workspace's
#: own directory. The user-level fallback for every checkout.
DEFAULT_SKILL_ROOT = "~/.zettcode/skills"

#: The skills a workspace may ship, relative to it. Scanned for ``[skills] scope`` of ``workspace``
#: or ``both``, ahead of the user's own, so a project's version of a skill wins in that project.
WORKSPACE_SKILL_ROOT = ".zettcode/skills"

#: The MCP server file a workspace may ship, relative to it. Read for ``[mcp] scope`` of
#: ``workspace`` or ``both``, and merged over the user's file by server name.
WORKSPACE_MCP_CONFIG = ".zettcode/mcp.json"

#: API root of an Anthropic model whose entry names no ``base_url``. The
#: Messages API lives at the root itself, not under ``/v1``.
DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com"

#: Routes a client appends to ``base_url`` itself. Writing one out is a common
#: reading of "the API address", and keeping it would double the path —
#: ``…/v1/messages/v1/messages``, which a gateway answers with 404 for a route it
#: does not serve — so the trailing route is removed and whatever comes before it
#: is kept as written.
CLIENT_ROUTES = ("/chat/completions", "/v1/messages", "/responses")

#: Tokens per model a request may carry before it is compacted, when the config
#: does not say otherwise; and the share of the trigger kept verbatim.
DEFAULT_CONTEXT_WINDOW = 128_000
DEFAULT_COMPACT_PERCENT = 80.0
KEEP_SHARE = 4

#: Conversation entries kept on screen before the oldest are dropped. The
#: session file keeps the whole tree, so this bounds scrollback, not history.
DEFAULT_TRANSCRIPT_MAX_ENTRIES = 1024

#: Rows one mouse-wheel event scrolls the transcript by: one, as Codex does, however fast they come.
DEFAULT_MOUSE_SCROLL_SPEED = 1.0

#: The fastest it may be set to: a notch of the wheel moves a page, and no more can be wanted.
MAX_MOUSE_SCROLL_SPEED = 20.0


@dataclass(frozen=True, slots=True)
class ModelConfig:
    """One configured model: what to call, where, with which token, over which API.

    Three request protocols are reachable from one entry. The default is an
    OpenAI-compatible chat-completions endpoint; ``responses_api`` chooses the
    Responses protocol on such an endpoint; ``anthropic`` chooses Anthropic's
    Messages API, which is not OpenAI-compatible and is served by its own
    adapter. The last two are alternatives, not layers.

    Attributes:
        model: Model id sent to the endpoint; must not be blank.
        token: Credential for the endpoint; must not be blank.
        display_model: Name shown in the UI; ``None`` shows :attr:`model`.
        base_url: Address the client appends its route to; a trailing route the
            entry wrote out is dropped. ``None`` uses the client's default,
            which is the Anthropic address for an Anthropic model and the
            vendor's own for an OpenAI-compatible one.
        anthropic: Speak Anthropic's Messages API instead of an
            OpenAI-compatible one.
        responses_api: Use the Responses API rather than chat completions, on
            an OpenAI-compatible endpoint.
        multimodal: Whether the model accepts images as well as text.
        context_window: Tokens the model can carry, which is what ``/context``
            measures against.
        compact_percent: Share of :attr:`context_window` at which a request is
            compacted, in percent.
        reasoning_efforts: The reasoning levels this model accepts, cheapest first. The empty
            tuple, the default, means every level: a provider that cannot express one maps it
            onto its closest, which is what makes the default right for an endpoint whose
            support is unknown. An entry names the subset when the endpoint rejects the rest.
    """

    model: str
    token: str
    display_model: str | None = None
    base_url: str | None = None
    anthropic: bool = False
    responses_api: bool = False
    multimodal: bool = False
    context_window: int = DEFAULT_CONTEXT_WINDOW
    compact_percent: float = DEFAULT_COMPACT_PERCENT
    reasoning_efforts: tuple[ReasoningEffort, ...] = ()

    def __post_init__(self) -> None:
        """Reject a model that cannot be called."""
        if not self.model.strip():
            raise ValueError("Model cannot be empty")
        if self.anthropic and self.responses_api:
            raise ValueError(
                f"Model {self.model!r} cannot use both APIs: the Responses API is OpenAI-compatible only, "
                "so clear 'responses_api' or 'anthropic'"
            )
        if not self.token.strip():
            variable = "ANTHROPIC_API_KEY" if self.anthropic else "OPENAI_API_KEY"
            raise ValueError(f"Missing token for model {self.model!r}; set 'token' or {variable}")
        if self.base_url is not None:
            root = _without_client_route(self.base_url)
            if root != self.base_url:
                object.__setattr__(self, "base_url", root)
        if self.context_window < 1:
            raise ValueError(f"context_window must be positive for model {self.model!r}")
        if not 0 < self.compact_percent <= 100:
            raise ValueError(f"compact_percent must be between 0 and 100 for model {self.model!r}")
        # Cheapest first, one of each: the order is the picker's rail, and a repeat would put two
        # nodes on one level.
        levels = tuple(sorted(set(self.reasoning_efforts), key=tuple(ReasoningEffort).index))
        if levels != self.reasoning_efforts:
            object.__setattr__(self, "reasoning_efforts", levels)

    @property
    def shown_name(self) -> str:
        """Return the name to display for the model."""
        return self.display_model or self.model

    @property
    def api(self) -> Api:
        """Return which API this model speaks: ``anthropic``, ``responses``, or ``chat``.

        Named for the picker and for messages: the three are one model entry's
        whole choice of protocol, and a reader needs to see at a glance which
        one an entry they wrote actually selected.
        """
        if self.anthropic:
            return Api.ANTHROPIC
        return Api.RESPONSES if self.responses_api else Api.CHAT

    @property
    def efforts(self) -> tuple[ReasoningEffort, ...]:
        """Return the reasoning levels this model accepts, cheapest first.

        Every level when the entry names none: a provider maps one it cannot express onto its closest, so
        the widest choice is the honest default for an endpoint whose support the entry does not describe.
        """
        return self.reasoning_efforts or tuple(ReasoningEffort)

    def accepted_effort(self, level: ReasoningEffort) -> ReasoningEffort:
        """Return the level to send when ``level`` was asked for, moved to the nearest one that is accepted.

        A level the model does not take is moved, never refused: the levels are ordered, and the closest
        one is what a caller who asked for ``ultra`` on a model that stops at ``high`` means. A tie goes
        to the cheaper level, which is the one the endpoint is known to serve.

        Args:
            level: The level that was asked for.
        """
        accepted = self.efforts
        if level in accepted:
            return level
        order = tuple(ReasoningEffort)
        position = order.index(level)
        return min(accepted, key=lambda candidate: (abs(order.index(candidate) - position), order.index(candidate)))

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
        theme: Name of the palette to start in (``[ui] theme``): a built-in one, or a file of the reader's in
            ``themes_dir``. ``None`` follows the terminal's light or dark. A ``theme_file`` wins over it.
        themes_dir: Where the reader's own palettes are, one ``<name>.toml`` each.
        pet: Name of the pet to start with (``[ui] pet``): one the built-in plugin or another plugin offers.
            ``None`` is the default pet.
        reasoning_effort: How much reasoning budget to request per turn.
        shell_approval: When the agent must ask before running a shell command.
        reduced_motion: Suppress decorative animation.
        parallel_tool_call: Let the agent issue tool calls in parallel.
        max_iterations: Tool-call rounds allowed in one turn.
        transcript_max_entries: Conversation entries the shell keeps on screen;
            older ones are dropped from the display while the session file
            keeps the whole tree.
        mouse_scroll_speed: Rows one mouse-wheel event scrolls the transcript
            by. A fraction is carried to the next event, so ``0.5`` is a row
            every second event and ``3`` is three rows a notch.
        tips: Show a small tip under the waiting row while a request runs.
        agents_md_enabled: Read the ``AGENTS.md`` files that apply to the
            workspace and give them to the model as project instructions.
        ask_user_enabled: Give the model the ``ask_user`` tool, which pauses a
            turn until the reader answers a question in the shell.
        skills_enabled: Discover local skills and advertise them to the model.
        skill_roots: Extra skill directories, searched before the directory :attr:`skills_scope`
            names; a relative entry is resolved against the workspace.
        skills_scope: Which of the workspace's ``.zettcode/skills`` and the user's
            ``~/.zettcode/skills`` to scan: ``"both"`` (the default) the project's first, so its version of
            a skill wins inside it; ``"workspace"`` the project's only, ``"global"`` the user's only.
        mcp_enabled: Load MCP servers from :attr:`mcp_config` and the workspace's ``.zettcode/mcp.json``.
        mcp_config: JSON file naming MCP servers; ``None`` uses ``~/.zettcode/mcp.json``.
        mcp_scope: Which MCP server files to read, with the same three words; ``"both"`` (the default)
            merges them, a server named in both taken from the workspace's file.
        self_compaction: Whether a session lets the model request compaction unless it says otherwise;
            the default a new session starts with, and what ``/self-compact`` shows until it is changed.
        statusline_hidden: The names of the header and status-line parts the reader switched off in the
            ``[statusline]`` table (``ctx = false``); see :mod:`zettcode.statusline`. Every part not named
            is shown.
        plugins_enabled: Load third-party plugins published under the
            ``zettcode.plugins`` entry-point group. The builtin rows always
            load, so switching this off leaves the shell looking the same.
        disabled_plugins: Entry-point names not to load when
            :attr:`plugins_enabled` is true; a way to switch off one plugin
            without uninstalling it.
        subagent_enabled: Offer the ``task`` tool, whose profiles run a child
            agent with its own context and session log.
        subagent_max_iterations: Model calls one such child may make for one task.
        todowrite_enabled: Offer the ``todo_write`` tool, whose list the shell
            shows in its plan panel. Off by default: a plan is a turn spent
            updating it, and not every session wants one.
        sessions_enabled: Register with the background session broker, so this session can be
            messaged by the others and message them: ``@name`` in the composer and the
            ``send_message`` and ``list_sessions`` tools.
        update_enabled: Ask PyPI, in the background, whether a newer release
            exists, and offer it on a later start.
        update_file: Where that check leaves what it found; one small JSON file.
    """

    workspace: Path
    models: tuple[ModelConfig, ...]
    store: Path = DEFAULT_STORE
    theme_file: Path | None = None
    theme: str | None = None
    themes_dir: Path = DEFAULT_THEMES_DIR
    pet: str | None = None
    reasoning_effort: ReasoningEffort = ReasoningEffort.MEDIUM
    shell_approval: ShellApprovalMode = ShellApprovalMode.REVIEW
    reduced_motion: bool = False
    parallel_tool_call: bool = True
    max_iterations: int = 360
    transcript_max_entries: int = DEFAULT_TRANSCRIPT_MAX_ENTRIES
    mouse_scroll_speed: float = DEFAULT_MOUSE_SCROLL_SPEED
    tips: bool = True
    agents_md_enabled: bool = True
    ask_user_enabled: bool = True
    skills_enabled: bool = True
    skill_roots: tuple[Path, ...] = ()
    skills_scope: str = DEFAULT_SCOPE
    mcp_enabled: bool = True
    mcp_config: Path | None = None
    mcp_scope: str = DEFAULT_SCOPE
    self_compaction: bool = False
    statusline_hidden: tuple[str, ...] = ()
    plugins_enabled: bool = True
    disabled_plugins: tuple[str, ...] = ()
    subagent_enabled: bool = True
    subagent_max_iterations: int = DEFAULT_SUBAGENT_MAX_ITERATIONS
    todowrite_enabled: bool = False
    sessions_enabled: bool = True
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
        if self.subagent_max_iterations < 1:
            raise ValueError("subagent_max_iterations must be positive")
        if self.transcript_max_entries < 1:
            raise ValueError("transcript_max_entries must be positive")
        if not 0 < self.mouse_scroll_speed <= MAX_MOUSE_SCROLL_SPEED:
            raise ValueError(f"mouse_scroll_speed must be greater than 0 and at most {MAX_MOUSE_SCROLL_SPEED:g}")
        if self.skills_scope not in SCOPES:
            raise ValueError(f"skills_scope must be one of {', '.join(sorted(SCOPES))}")
        if self.mcp_scope not in SCOPES:
            raise ValueError(f"mcp_scope must be one of {', '.join(sorted(SCOPES))}")
        if stray := [name for name in self.statusline_hidden if name not in STATUSLINE_KEYS]:
            raise ValueError(f"statusline_hidden names no part: {', '.join(stray)}")
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
        object.__setattr__(self, "themes_dir", self.themes_dir.expanduser().resolve())

    def skill_search_roots(self) -> tuple[Path, ...]:
        """Return every skill directory to scan, most specific first.

        The configured roots come first so a run can point at a team directory or at a project-local
        one, then the directory :attr:`skills_scope` names: a project's skills ahead of the user's, so
        a name declared in both belongs to the project the reader is in. A name declared twice belongs
        to the earlier directory.
        """
        scope = self.skills_scope
        roots: list[Path] = list(self.skill_roots)
        if scope in ("workspace", "both"):
            roots.append(_resolve_root(WORKSPACE_SKILL_ROOT, self.workspace))
        if scope in ("global", "both"):
            roots.append(_resolve_root(DEFAULT_SKILL_ROOT, self.workspace))
        # Ordered, one of each: a configured root may name the same directory a scope does.
        return tuple(dict.fromkeys(roots))

    def mcp_files(self) -> tuple[Path, ...]:
        """Return the MCP server files to read, the one that wins a server name first.

        The workspace's file comes first for the same reason its skills do, and a file ``[mcp] config``
        names replaces the user's own rather than joining it: a reader who points at a team file means
        that file.
        """
        scope = self.mcp_scope
        files: list[Path] = []
        if scope in ("workspace", "both"):
            files.append(_resolve_root(WORKSPACE_MCP_CONFIG, self.workspace))
        if scope in ("global", "both"):
            files.append((self.mcp_config or Path(DEFAULT_MCP_CONFIG)).expanduser().resolve())
        return tuple(dict.fromkeys(files))


def _default_theme_file() -> Path | None:
    """Return the conventional palette file when the user has created one."""
    return DEFAULT_THEME_FILE if DEFAULT_THEME_FILE.is_file() else None


def _without_client_route(base_url: str) -> str:
    """Return ``base_url`` without a trailing route the client appends itself.

    ``http://gw.test:8787/v1/messages`` is what a reader writes when they mean
    the Messages route, and the client adds that part; keeping it would send
    every request to ``…/v1/messages/v1/messages``, which a gateway answers with
    a 404 for a path it does not serve — a message about the request that gives
    no hint about the line of configuration behind it. Only the route goes: a
    prefix in front of it is part of where the API lives and stays. A value that
    is nothing but the route is left alone, having nothing in front of it to
    keep, so the request fails where the reader can see it.
    """
    stripped = base_url.rstrip("/")
    for route in CLIENT_ROUTES:
        prefix = stripped[: -len(route)]
        if stripped.endswith(route) and prefix:
            return prefix
    return base_url


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
    anthropic = _setting(entry, "anthropic", bool, False)
    # The conventional variable for the API this entry speaks, so an Anthropic
    # model does not have to borrow a key named after OpenAI.
    variable = "ANTHROPIC_API_KEY" if anthropic else "OPENAI_API_KEY"
    token = entry.get("token") or os.getenv(variable, "")
    try:
        return ModelConfig(
            model=_typed(model, f"{label} key 'model'", str),
            token=_typed(token, f"{label} key 'token'", str),
            display_model=_setting(entry, "display_model", str, None),
            base_url=_setting(entry, "base_url", str, None),
            anthropic=anthropic,
            responses_api=_setting(entry, "responses_api", bool, False),
            multimodal=_setting(entry, "multimodal", bool, False),
            context_window=_typed(
                entry.get("context_window", DEFAULT_CONTEXT_WINDOW), f"{label} key 'context_window'", int
            ),
            compact_percent=_number(
                entry.get("compact_percent", DEFAULT_COMPACT_PERCENT), f"{label} key 'compact_percent'"
            ),
            reasoning_efforts=_read_reasoning_efforts(
                entry.get("reasoning_efforts"), f"{label} key 'reasoning_efforts'"
            ),
        )
    except ValueError as error:
        # The same model id can be configured twice against different endpoints,
        # so which entry a rule refused has to be in the message.
        raise ValueError(f"{label}: {error}") from error


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


def _read_reasoning_efforts(raw: object, where: str) -> tuple[ReasoningEffort, ...]:
    """Return the levels one model accepts, cheapest first; none written means every level."""
    if raw is None:
        return ()
    if not isinstance(raw, list) or any(not isinstance(entry, str) for entry in raw):
        raise ValueError(f"{where} must be an array of level names")
    known = {level.value: level for level in ReasoningEffort}
    chosen: list[ReasoningEffort] = []
    for entry in raw:
        level = known.get(entry.strip().lower())
        if level is None:
            raise ValueError(f"{where} names {entry!r}, which is not one of {', '.join(known)}")
        chosen.append(level)
    if not chosen:
        raise ValueError(f"{where} must name at least one level, or be left out for all of them")
    return tuple(sorted(set(chosen), key=tuple(ReasoningEffort).index))


def _read_scope(raw: object, source: Path, table: str) -> str:
    """Return a ``[skills]``/``[mcp]`` scope, rejecting a word that names none of the three."""
    if raw is None:
        return DEFAULT_SCOPE
    if not isinstance(raw, str) or raw.strip().lower() not in SCOPES:
        words = ", ".join(sorted(SCOPES))
        raise ValueError(f"Config key '{table}.scope' in {source} must be one of {words}, not {raw!r}")
    return raw.strip().lower()


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


def _read_theme_name(raw: object, source: Path) -> str | None:
    """Return the palette name ``[ui] theme`` asks for, rejecting what could not be typed after ``/theme``."""
    return _read_word(raw, "ui.theme", "a palette name", source)


def _read_word(raw: object, key: str, what: str, source: Path) -> str | None:
    """Return a name the reader typed into the config, rejecting what could not be typed after its command."""
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip() or any(character.isspace() for character in raw.strip()):
        raise ValueError(f"Config key '{key}' in {source} must be {what} without spaces")
    return raw.strip()


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
    harness = _read_table(data.get("harness"), "harness", source, HARNESS_KEYS)
    compaction = _read_table(data.get("compaction"), "compaction", source, COMPACTION_KEYS)
    sessions = _read_table(data.get("sessions"), "sessions", source, SESSIONS_KEYS)
    ui = _read_table(data.get("ui"), "ui", source, UI_KEYS)
    statusline = _read_table(data.get("statusline"), "statusline", source, STATUSLINE_KEYS)

    return ZettCodeConfig(
        workspace=Path(workspace),
        models=_read_models(data.get("models"), source),
        theme_file=_default_theme_file(),
        theme=_read_theme_name(ui.get("theme"), source),
        pet=_read_word(ui.get("pet"), "ui.pet", "a pet name", source),
        reduced_motion=reduced_motion_default,
        transcript_max_entries=_typed(
            transcript.get("max_entries", DEFAULT_TRANSCRIPT_MAX_ENTRIES),
            f"Config key 'transcript.max_entries' in {source}",
            int,
        ),
        mouse_scroll_speed=_number(
            transcript.get("mouse_scroll_speed", DEFAULT_MOUSE_SCROLL_SPEED),
            f"Config key 'transcript.mouse_scroll_speed' in {source}",
        ),
        tips=bool(_setting(transcript, "tips", bool, True)),
        agents_md_enabled=bool(_setting(agents_md, "enabled", bool, True)),
        ask_user_enabled=bool(_setting(ask_user, "enabled", bool, True)),
        skills_enabled=bool(_setting(skills, "enabled", bool, True)),
        skill_roots=_read_skill_roots(skills.get("roots"), source),
        skills_scope=_read_scope(skills.get("scope"), source, "skills"),
        mcp_enabled=bool(_setting(mcp, "enabled", bool, True)),
        mcp_config=_read_mcp_config(mcp.get("config"), source),
        mcp_scope=_read_scope(mcp.get("scope"), source, "mcp"),
        self_compaction=bool(_setting(compaction, "self", bool, False)),
        statusline_hidden=tuple(
            name
            for name in STATUSLINE_NAMES
            if not _typed(
                statusline.get(name, name not in OFF_BY_DEFAULT), f"Config key 'statusline.{name}' in {source}", bool
            )
        ),
        plugins_enabled=bool(_setting(plugins, "enabled", bool, True)),
        disabled_plugins=_read_disabled_plugins(plugins.get("disable"), source),
        subagent_enabled=bool(_setting(harness, "subagent", bool, True)),
        subagent_max_iterations=_typed(
            harness.get("subagent_max_iterations", DEFAULT_SUBAGENT_MAX_ITERATIONS),
            f"Config key 'harness.subagent_max_iterations' in {source}",
            int,
        ),
        todowrite_enabled=bool(_setting(harness, "todowrite", bool, False)),
        sessions_enabled=bool(_setting(sessions, "enabled", bool, True)),
        update_enabled=bool(_setting(update, "enabled", bool, True)),
    )
