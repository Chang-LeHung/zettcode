"""The entry point: a client for one workspace, its settings, and the sessions in it.

::

    import zettcode.sdk as zc

    async with zc.Client("~/project", model="gpt-5", permission="safe") as client:
        result = await client.prompt("find the failing test and fix it", on_approval=zc.approve_commands("pytest"))
        print(result.text, result.usage.total_tokens)

A client is the terminal application without the terminal: the same agent, tools, plugins, MCP servers, skills,
project instructions, session store and permission levels, driven from code. It reads the same config file unless
it is given a configuration of its own (see :class:`Client`).
"""

from __future__ import annotations

import asyncio
import dataclasses
import difflib
import functools
import os
import weakref
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Any, cast

from .errors import (
    ClientClosedError,
    ConfigurationError,
    SessionBusyError,
    SessionNotFoundError,
    WorkspaceConflictError,
)
from .events import AnyEvent
from .handlers import ApprovalHandler, QuestionHandler
from .session import EventCallback, Prompt, RunStream, Session
from .types import (
    Image,
    IncomingMessage,
    MentionInfo,
    ModelCheck,
    ModelInfo,
    RunResult,
    SessionInfo,
    SessionStatsInfo,
    Usage,
    WorkspaceUsage,
)

if TYPE_CHECKING:  # pragma: no cover - annotations only; the agent is imported when a client is made
    from ..app.agent.agent import ZettCodeAgent
    from ..app.agent.conversation.transcript import Transcript
    from ..app.agent.dialogue.ask import AskUserQuestion
    from ..app.agent.dialogue.mentions import MentionRegistry
    from ..app.agent.extensions.messenger import Messenger
    from ..broker.client import Delivered, Receipt
    from ..config import ModelConfig, ZettCodeConfig

__all__ = ["Client", "PluginReport", "Sessions", "prompt", "prompt_sync"]

#: What a client switches off unless it is told otherwise. The terminal application joins the broker that lets
#: sessions message each other and checks for a release in the background; a program embedding the agent should
#: not do either of those behind its back.
EMBEDDED_DEFAULTS: dict[str, object] = {"sessions_enabled": False, "update_enabled": False}


@functools.cache
def _settings() -> frozenset[str]:
    """Return the names of the settings a client accepts. Read from the config class on first use, which imports it."""
    from ..config import ZettCodeConfig

    return frozenset(field.name for field in dataclasses.fields(ZettCodeConfig))


@functools.cache
def _path_settings() -> tuple[frozenset[str], frozenset[str]]:
    """Return the settings that hold a path, and the ones that hold several, so a string can stand for either."""
    import typing

    from ..config import ZettCodeConfig

    single: set[str] = set()
    several: set[str] = set()
    for name, hint in typing.get_type_hints(ZettCodeConfig).items():
        text = str(hint)
        if "Path" not in text:
            continue
        (several if text.startswith("tuple") else single).add(name)
    return frozenset(single), frozenset(several)


@functools.cache
def _enum_settings() -> dict[str, type]:
    """Return the settings that hold one of a fixed set of values, by the enum that lists them."""
    import enum
    import typing

    from ..config import ZettCodeConfig

    return {
        name: hint
        for name, hint in typing.get_type_hints(ZettCodeConfig).items()
        if isinstance(hint, type) and issubclass(hint, enum.Enum)
    }


def _coerced(settings: Mapping[str, object]) -> dict[str, object]:
    """Return the settings read the way a config file's strings are: paths as paths, choices as their enum.

    The configuration stores whatever it is given for these, so a misspelt ``reasoning_effort`` would be accepted
    here and fail on the first request; checking it now is what turns it into an error that lists the valid values.
    """
    single, several = _path_settings()
    choices = _enum_settings()
    values: dict[str, object] = {}
    for name, value in settings.items():
        if name in single and isinstance(value, str):
            value = Path(value).expanduser()
        elif name in several and isinstance(value, (list, tuple)):
            value = tuple(Path(item).expanduser() if isinstance(item, str) else item for item in value)
        elif name in choices:
            value = _choice(name, value, choices[name])
        values[name] = value
    return values


def _choice(name: str, value: object, kind: type) -> object:
    """Return ``value`` as a member of ``kind``, accepting a member, or its value in any case."""
    if isinstance(value, kind):
        return value
    if isinstance(value, str):
        try:
            return kind(value.strip().lower())
        except ValueError:
            pass
    allowed = ", ".join(str(member.value) for member in kind)  # type: ignore[attr-defined]
    raise ConfigurationError(f"{name} must be one of: {allowed} (got {value!r})")


#: The clients that are open in this process, and the working directory the process had before the first one.
_OPEN: weakref.WeakSet[Client] = weakref.WeakSet()
_ORIGINAL_CWD: list[str] = []


@dataclass(frozen=True, slots=True)
class PluginReport:
    """The plugins a client loaded.

    Attributes:
        loaded: Their names, in the order they take part (built-in ones first).
        failures: One message per plugin that could not be loaded; those are skipped, never fatal.
    """

    loaded: tuple[str, ...]
    failures: tuple[str, ...]


class _AgentBridge:
    """Carry the program's answers to the suspended agent, through the application's own agent."""

    def __init__(self, agent: ZettCodeAgent) -> None:
        self._agent = agent

    def approve(self, session_id: str, call_id: str, approve: bool, remember: bool) -> None:
        self._agent.respond_approval(session_id, call_id, "execute" if approve else "abort", remember)

    def answer(self, question: AskUserQuestion, text: str | None) -> None:
        if text is None:
            self._agent.decline_ask(question)
        else:
            self._agent.answer_ask(question, text)


def build_config(
    workspace: str | Path | None,
    config: ZettCodeConfig | None,
    config_path: str | Path | None,
    models: Sequence[ModelConfig | Mapping[str, object]] | None,
    settings: Mapping[str, object],
) -> ZettCodeConfig:
    """Return the configuration a client runs with.

    Where it comes from, in order: ``config`` as given; else ``models`` on top of the defaults, the config file not
    read at all; else the config file (``config_path``, ``$ZETTCODE_CONFIG`` or ``~/.zettcode/config.toml``).
    ``settings`` are then laid over it by field name.

    Raises:
        ConfigurationError: The workspace is not a directory, a setting name is unknown (with a suggestion), a model
            entry is malformed, or the file is unreadable or holds no model.
    """
    if "workspace" in settings:
        raise ConfigurationError("Pass the workspace as the first argument, not as a setting")
    from ..config import ZettCodeConfig, load_config

    known = _settings()
    unknown = sorted(name for name in settings if name not in known)
    if unknown:
        hints = []
        for name in unknown:
            close = difflib.get_close_matches(name, sorted(known), n=1)
            hints.append(f"{name!r}" + (f" (did you mean {close[0]!r}?)" if close else ""))
        raise ConfigurationError(f"Unknown setting: {', '.join(hints)}")
    chosen = workspace if workspace is not None else (config.workspace if config is not None else Path.cwd())
    try:
        root = Path(chosen).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ConfigurationError(f"The workspace {str(chosen)!r} does not exist") from error
    if not root.is_dir():
        raise ConfigurationError(f"The workspace {str(root)!r} is not a directory")
    try:
        if config is not None:
            base = replace(config, workspace=root)
            embedded: dict[str, object] = {}
        elif models is not None:
            base = ZettCodeConfig(workspace=root, models=_models(models))
            embedded = dict(EMBEDDED_DEFAULTS)
        else:
            base = load_config(root, path=config_path)
            embedded = dict(EMBEDDED_DEFAULTS)
        return replace(base, **cast("dict[str, Any]", {**embedded, **_coerced(settings)}))
    except ConfigurationError:
        raise
    except (ValueError, TypeError, AttributeError) as error:
        # AttributeError is what a value of the wrong kind raises inside the configuration's own checks.
        raise ConfigurationError(f"Invalid configuration: {error}") from error


def _models(entries: Sequence[ModelConfig | Mapping[str, object]]) -> tuple[ModelConfig, ...]:
    """Return the model entries as :class:`ModelConfig`, accepting plain mappings of the same fields."""
    from ..config import ModelConfig

    if isinstance(entries, (str, bytes)) or not isinstance(entries, Sequence) or not entries:
        raise ConfigurationError("models must be a non-empty list of ModelConfig or dicts")
    built: list[ModelConfig] = []
    for entry in entries:
        if isinstance(entry, ModelConfig):
            built.append(entry)
        elif isinstance(entry, Mapping):
            try:
                built.append(ModelConfig(**entry))  # type: ignore[arg-type]
            except (TypeError, ValueError) as error:
                raise ConfigurationError(f"Invalid model entry {dict(entry)!r}: {error}") from error
        else:
            raise ConfigurationError(f"A model entry is a ModelConfig or a dict, not {type(entry).__name__}")
    return tuple(built)


class Client:
    """The agent for one workspace.

    Args:
        workspace: The directory the agent works in; ``None`` is the current one (or ``config.workspace``).
        config: A ready configuration. Nothing is read from disk, and the embedding defaults are not applied.
        config_path: A config file to read instead of the default one. Ignored when ``config`` or ``models`` is given.
        models: Models to use without any config file: :class:`~zettcode.config.ModelConfig` entries or dicts of the
            same fields (``{"model": "gpt-5", "token": "sk-..."}``). The first is the active one.
        model: The model to start on, by the name :attr:`models` lists.
        effort: The reasoning level to start on.
        permission: The shell permission level: ``deny``, ``ask``, ``safe`` (every command in a sandbox) or ``full``.
        resume: A session id to continue instead of starting a new conversation.
        **settings: Any other :class:`~zettcode.config.ZettCodeConfig` field, such as ``store=``, ``skills_enabled=``,
            ``mcp_enabled=``, ``subagent_enabled=``, ``todowrite_enabled=``, ``max_iterations=``. A misspelt name is
            reported with a suggestion.

    The client defaults to ``sessions_enabled=False`` and ``update_enabled=False``: a program embedding the agent
    neither joins the broker that lets terminal sessions message one another nor checks PyPI. Turning sessions on and
    calling :meth:`join_sessions` makes this client one of the sessions the others can address.

    Use it as ``async with Client(...) as client`` (or call :meth:`aclose`) so the provider connection and the session
    lock are released. The coding tools work relative to the process's working directory, so creating a client
    changes it to the workspace and closing the last client puts it back; clients on two different workspaces cannot
    be open at once in one process.

    Raises:
        ConfigurationError: The configuration, or a model, effort or permission chosen from it, is not usable.
        WorkspaceConflictError: Another open client works in a different directory.
        SessionNotFoundError: ``resume`` names a session that cannot be read.
    """

    workspace: Path

    def __init__(
        self,
        workspace: str | Path | None = None,
        *,
        config: ZettCodeConfig | None = None,
        config_path: str | Path | None = None,
        models: Sequence[ModelConfig | Mapping[str, object]] | None = None,
        model: str | None = None,
        effort: str | None = None,
        permission: str | None = None,
        resume: str | None = None,
        **settings: object,
    ) -> None:
        self._closed = False
        self._stream: RunStream | None = None
        self._handles: dict[str, Session] = {}
        self._switching = asyncio.Lock()
        self._messenger: Messenger | None = None
        resolved = build_config(workspace, config, config_path, models, settings)
        self._register(resolved.workspace)
        # Imported here, not at the top of the module: importing the SDK costs nothing until a client is made.
        from ..app.agent.agent import ZettCodeAgent
        from ..app.agent.runtime import ZettCodeEngine

        try:
            runtime = ZettCodeEngine.preview(resolved)
        except BaseException:
            self._unregister()
            raise
        self._agent = ZettCodeAgent(runtime)
        self._bridge = _AgentBridge(self._agent)
        self._fresh = {runtime.session_id}
        try:
            if model is not None:
                self.use_model(model)
            if effort is not None:
                self.use_effort(effort)
            if permission is not None:
                # The client's setting, not a decision about the session: a prompt that asks for `deny` must not
                # leave the session on `deny` for the next reader of it.
                try:
                    self._agent.runtime.use_permission(permission, remember=False)
                except ValueError as error:
                    raise ConfigurationError(str(error)) from error
            if resume is not None:
                self._resume_now(resume)
        except BaseException:
            self._dispose()
            raise
        self.sessions = Sessions(self)
        #: One reader for the workspace's ledger, so a second look at the usage reads only what changed.
        self._ledger_reader: Any = None

    # -- process-wide bookkeeping --
    def _register(self, workspace: Path) -> None:
        """Refuse a second workspace in this process, and remember the working directory to restore."""
        for other in list(_OPEN):
            if not other._closed and other.workspace != workspace:
                raise WorkspaceConflictError(
                    f"A client for {other.workspace} is open; this process's working directory is shared, "
                    f"so {workspace} must wait until it is closed"
                )
        self.workspace = workspace
        if not _OPEN:
            _ORIGINAL_CWD[:] = [os.getcwd()]
        _OPEN.add(self)

    def _unregister(self) -> None:
        _OPEN.discard(self)
        if not _OPEN and _ORIGINAL_CWD:
            original = _ORIGINAL_CWD.pop()
            try:
                os.chdir(original)
            except OSError:
                pass  # the directory it started in is gone; staying in the workspace is the lesser evil

    def _dispose(self) -> None:
        """Release what a client holds without awaiting anything; the path a failed construction takes."""
        self._closed = True
        try:
            self._agent.runtime.session_locks.release()
        finally:
            self._unregister()

    # -- the life of the client --
    async def __aenter__(self) -> Client:
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        await self.aclose()

    @property
    def closed(self) -> bool:
        """Return whether :meth:`aclose` has run."""
        return self._closed

    async def aclose(self) -> None:
        """Stop a run in progress and release the provider connections, the session store and the session lock.

        Safe to call twice, and to call while a run is in progress: the run is closed first.
        """
        if self._closed:
            return
        self._closed = True
        messenger, self._messenger = self._messenger, None
        stream = self._stream
        try:
            if messenger is not None:
                await messenger.close()
            if stream is not None:
                await stream.aclose()
        finally:
            try:
                await self._agent.runtime.aclose()
            finally:
                try:
                    self._agent.runtime.session_locks.release()
                finally:
                    self._unregister()

    def _check_open(self) -> None:
        if self._closed:
            raise ClientClosedError("This client was closed")

    def _check_free(self) -> None:
        if self._stream is not None:
            raise SessionBusyError(
                "A run is already in progress on this client. Wait for it, or close it: leave the `async with "
                "session.stream(...)` block, `await run.aclose()`, or cancel the task"
            )

    def _claim(self, stream: RunStream) -> None:
        if self._stream is not None and self._stream is not stream:
            self._check_free()
        self._stream = stream
        self._describe(busy=True)

    def _release(self, stream: RunStream) -> None:
        if self._stream is stream:
            self._stream = None
            self._describe(busy=False)

    # -- sessions --
    @property
    def config(self) -> ZettCodeConfig:
        """Return the configuration in force."""
        return self._agent.runtime.config

    @property
    def session(self) -> Session:
        """Return the current conversation, which a new client starts empty."""
        return self._handle(self._agent.session_id)

    # -- the other sessions --
    async def join_sessions(self, on_message: Callable[[IncomingMessage], Receipt]) -> bool:
        """Join the session broker, so other ZettCode sessions can find this one and send it messages.

        The terminal joins it too; a program embedding the agent does not unless it is built with
        ``sessions_enabled=True``, which is what this call needs to have anything to join.

        Args:
            on_message: Called on the event loop with every message another session sends. It must not block; what
                it returns is the answer the sender's agent is given — whether the message was taken, and whether
                the turn it starts has begun or is waiting.

        Returns:
            Whether this client is reachable now; ``False`` when sessions are switched off for it.

        Raises:
            ClientClosedError: The client was closed.
        """
        self._check_open()
        messenger = self._agent.runtime.messenger
        if messenger is None:
            return False
        self._messenger = messenger
        messenger.receiver = lambda relayed: on_message(
            IncomingMessage(
                sender_id=relayed.sender_id,
                sender=relayed.sender,
                text=relayed.text,
                via=relayed.via,
                hops=relayed.hops,
            )
        )
        self._describe(busy=self._stream is not None)
        await messenger.start()
        return True

    def relay(
        self,
        message: IncomingMessage,
        *,
        on_approval: ApprovalHandler | None = None,
        on_question: QuestionHandler | None = None,
        on_event: EventCallback | None = None,
        timeout: float | None = None,
        raw: bool = False,
        keep_events: bool = False,
    ) -> RunStream:
        """Run one turn for a message another session sent, as the terminal does when one arrives.

        The message is what the model reads, framed with where it came from; the answer belongs to this session's
        own reader, and the sender sees nothing of it unless the model replies with ``send_message``.
        """
        return self.session.relay(
            message,
            on_approval=on_approval,
            on_question=on_question,
            on_event=on_event,
            timeout=timeout,
            raw=raw,
            keep_events=keep_events,
        )

    async def send(self, to: str, text: str) -> Delivered:
        """Send a message to another ZettCode session, as the terminal's ``@name`` draft does.

        Args:
            to: The session's handle, or its id.
            text: What to say; the sender's own words, so the receiving agent is told its reader typed it.

        Returns:
            What the receiving session answered: who took it, and whether the turn started or is queued.

        Raises:
            ConfigurationError: This client did not join the sessions, so it has no line to send on.
            SendError: Nobody was reached, and why.
        """
        from ..broker.protocol import VIA_USER

        self._check_open()
        messenger = self._messenger
        if messenger is None:
            raise ConfigurationError(
                "This client has not joined the sessions; build it with sessions_enabled=True and call join_sessions"
            )
        return await messenger.send(to, text, via=VIA_USER)

    def _describe(self, *, busy: bool) -> None:
        """Tell the broker what this session is, when there is a connection to tell it."""
        messenger = self._messenger
        if messenger is None:
            return
        session = self.session
        messenger.describe(session.id, session.title, busy=busy)

    def _handle(self, session_id: str) -> Session:
        handle = self._handles.get(session_id)
        if handle is None:
            handle = self._handles[session_id] = Session(self, session_id)
        return handle

    def _transcript(self) -> Transcript:
        """Return an empty transcript shaped like the terminal's, which reading a stored session replays into."""
        from ..app.agent.conversation.transcript import Transcript

        return Transcript(presenters=self._agent.presenters, max_entries=self.config.transcript_max_entries)

    def _resume_now(self, session_id: str) -> None:
        """Continue a stored session at construction, where nothing else can be running."""
        transcript = self._transcript()
        try:
            stored = self._agent.load_session(session_id, transcript)
        except (ValueError, OSError) as error:
            raise SessionNotFoundError(f"Cannot open session {session_id!r}: {error}") from error
        self._agent.install_session(stored, transcript)

    async def _switch_to(self, session_id: str, by: RunStream | None = None) -> None:
        """Make ``session_id`` the conversation the agent works on, reading it from the store if it is stored.

        ``by`` is the run that is starting and already holds the busy slot; it may switch, nobody else may.
        """
        self._check_open()
        async with self._switching:
            if self._agent.session_id == session_id:
                return
            if self._stream is not None and self._stream is not by:
                self._check_free()
            transcript = self._transcript()
            try:
                stored = await asyncio.to_thread(self._agent.load_session, session_id, transcript)
            except (ValueError, OSError) as error:
                if session_id not in self._fresh:
                    raise SessionNotFoundError(f"Cannot open session {session_id!r}: {error}") from error
                self._agent.use_session(session_id)  # started here and never written: there is nothing to read
                return
            self._agent.install_session(stored, transcript)

    # -- what to run on --
    @property
    def models(self) -> tuple[ModelInfo, ...]:
        """Return the configured models; the one the next run uses is marked ``active``."""
        active = self._agent.active_model
        return tuple(
            ModelInfo(
                name=entry.shown_name,
                model=entry.model,
                context_window=entry.context_window,
                multimodal=entry.multimodal,
                efforts=tuple(level.value for level in entry.efforts),
                active=entry is active,
                compact_percent=entry.compact_percent,
                web_search=entry.web_search,
                web_search_name=entry.web_search_name,
            )
            for entry in self._agent.models
        )

    @property
    def model(self) -> ModelInfo:
        """Return the model the next run uses."""
        return next(info for info in self.models if info.active)

    def use_model(self, name: str | ModelInfo) -> ModelInfo:
        """Choose the model for later runs, by the name :attr:`models` lists.

        Raises:
            ConfigurationError: No such model, or two share the name (give one a ``display_model``).
        """
        self._check_open()
        wanted = name.name if isinstance(name, ModelInfo) else name
        try:
            self._agent.use_model(wanted)
        except ValueError as error:
            raise ConfigurationError(f"{error}. Configured: {', '.join(info.name for info in self.models)}") from error
        return self.model

    def use_compact_percent(self, percent: float) -> tuple[ModelInfo, str | None]:
        """Summarize the conversation at ``percent`` of the active model's window, from the next request on.

        This is the terminal's ``/context`` slider. The running session changes at once; the configuration file is
        rewritten too, so the point survives a restart.

        Args:
            percent: Share of the window, more than 0 and at most 100.

        Returns:
            The active model as it is now, and why the file was not written (``None`` when it was): the change then
            holds for this run only.

        Raises:
            ConfigurationError: ``percent`` is not between 0 and 100.
        """
        self._check_open()
        try:
            _, unwritten = self._agent.change_compact_percent(percent)
        except ValueError as error:
            raise ConfigurationError(str(error)) from error
        return self.model, unwritten

    @property
    def effort(self) -> str:
        """Return the reasoning level the next run uses."""
        return self._agent.effort

    @property
    def efforts(self) -> tuple[str, ...]:
        """Return the levels the active model accepts."""
        return self._agent.efforts

    def use_effort(self, name: str) -> str:
        """Choose how much reasoning later runs may spend.

        Raises:
            ConfigurationError: The level does not exist, or the active model does not take it (the message lists
                the ones it does).
        """
        self._check_open()
        try:
            return self._agent.use_effort(name)
        except ValueError as error:
            raise ConfigurationError(str(error)) from error

    @property
    def permission(self) -> str:
        """Return how much of the shell may run without asking: ``deny``, ``ask``, ``safe`` or ``full``."""
        return str(self._agent.permission.value)

    @property
    def permissions(self) -> tuple[str, ...]:
        """Return the permission levels there are."""
        return self._agent.permissions

    def use_permission(self, name: str) -> str:
        """Choose how much of the shell may run without asking, from the next command on.

        ``safe`` runs every command in an operating-system sandbox that writes only the workspace and ``/tmp`` (where
        the machine has one); ``full`` runs them with the user's own access. ``auto``, the old name of ``full``, is
        still taken. The level is remembered by the session, so opening it again starts there; ``permission=`` on the
        client itself is for that client's runs and is not written down.

        Raises:
            ConfigurationError: Not one of the levels.
        """
        self._check_open()
        try:
            return str(self._agent.use_permission(name).value)
        except ValueError as error:
            raise ConfigurationError(str(error)) from error

    @property
    def harness(self) -> bool:
        """Return whether the just-in-time harness is on: the model may write small Python tools and run them."""
        return self._agent.harness

    def use_harness(self, on: bool) -> bool:
        """Turn the just-in-time harness on or off, from the next prompt on. It starts off."""
        self._check_open()
        return self._agent.use_harness(on)

    # -- what is loaded --
    @property
    def usage(self) -> Usage:
        """Return what the current session has spent."""
        from ._translate import usage_from

        return usage_from(self._agent.usage)

    @property
    def plugins(self) -> PluginReport:
        """Return the plugins that loaded and the ones that did not."""
        bundle = self._agent.runtime.plugins
        return PluginReport(tuple(plugin.name for plugin in bundle.plugins), tuple(bundle.failures))

    def mentions(self, query: str = "", *, limit: int = 50) -> tuple[MentionInfo, ...]:
        """Return the ``@`` resources whose name matches ``query``, for a completion menu.

        The same resources a prompt resolves: the workspace's files, the skills on the search paths, and whatever a
        plugin offers. The query is what follows the ``@`` (``"cli"`` for ``@cli``); an empty one lists what the
        providers consider likeliest. The result is capped, because a menu shows a screenful and a large workspace
        has more files than one.

        Args:
            query: What was typed after the ``@``, without it.
            limit: Most entries to return; a positive integer.

        Raises:
            ValueError: ``limit`` is not positive.
        """
        self._check_open()
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")
        registry = self._mention_registry()
        return tuple(
            MentionInfo(mention.token, mention.kind, mention.name, mention.description)
            for mention in registry.candidates(query)[:limit]
        )

    def _mention_registry(self) -> MentionRegistry:
        """Return the ``@`` providers: the other sessions first, then what the plugins offer.

        The order is the terminal's, and it decides more than a menu: a draft that names a session means that
        session even when a file happens to have the same name.
        """
        from ..app.agent.dialogue.mentions import MentionRegistry, SessionMentions

        providers = self._agent.plugin_mentions
        messenger = self._agent.runtime.messenger
        if messenger is not None:
            providers = (SessionMentions(messenger.peers), *providers)
        return MentionRegistry(providers)

    # -- what the workspace spent, and what a session holds --
    def _ledger(self) -> Any:
        """Return the reader of this workspace's ledger, made once."""
        if self._ledger_reader is None:
            from ..app.agent.storage.ledger import LedgerReader

            self._ledger_reader = LedgerReader(self.config.store, self.config.workspace)
        return self._ledger_reader

    async def usage_ledger(self) -> WorkspaceUsage:
        """Return what every stored session of this workspace has spent, as the ``/usage`` page shows it.

        The numbers are read back from the stored conversations, so they cover the whole workspace and not only
        this conversation, and they agree with the files rather than with what this process remembers. The read runs
        off the event loop and reads only what changed since the last call on this client.
        """
        from ._translate import ledger_from

        self._check_open()
        return ledger_from(await asyncio.to_thread(self._ledger().read))

    async def session_stats(self, session_ids: Sequence[str] | None = None) -> tuple[SessionStatsInfo, ...]:
        """Return the stored totals of some sessions: entries, replies, tokens and the cached share.

        This is what the ``/resume`` panel's columns are made of, and it reads a session's file only when that file
        has changed since it was summarized. The current session is read when no ids are given.
        """
        from ._translate import stats_from

        self._check_open()
        wanted = list(session_ids) if session_ids is not None else [self.session.id]
        if not wanted:
            return ()
        found = await asyncio.to_thread(self._ledger().stats, wanted)
        return tuple(stats_from(found[session_id]) for session_id in wanted if session_id in found)

    # -- self-compaction --
    @property
    def self_compaction(self) -> bool:
        """Return whether the model may compact this session's context itself."""
        return self._agent.runtime.self_compacting(self.session.id)

    @property
    def self_compaction_choice(self) -> bool | None:
        """Return this session's own choice (``None`` when it follows the configuration's default)."""
        return self._agent.runtime.self_compaction_choice(self.session.id)

    def use_self_compaction(self, choice: bool | None) -> bool:
        """Let the model compact this session itself (``True``), stop it (``False``), or follow the default (``None``).

        The choice is stored in the session, so it is there when the session is reopened, and it applies to the next
        request (the tool is offered when one starts).

        Raises:
            OSError: The choice could not be written; the one in force is unchanged.
        """
        self._check_open()
        self._agent.runtime.choose_self_compaction(self.session.id, choice)
        return self.self_compaction

    async def check_models(self, *, timeout: float = 30.0) -> tuple[ModelCheck, ...]:
        """Ask every configured model one short question, as ``zettcode doctor`` does, and report which answer.

        The questions go to the provider adapters directly: no session is written, no tool is offered, and no
        extension runs, so what is measured is the entry and the endpoint. They are asked at once, and a model that
        does not answer within ``timeout`` seconds is reported as not answering rather than raised.
        """
        from ..doctor import diagnose
        from ._translate import checks_from

        self._check_open()
        return checks_from(await diagnose(self.config.models, timeout=timeout))

    # -- running, on the current session --
    def prompt(
        self,
        prompt: Prompt,
        *,
        images: Sequence[Image] = (),
        mentions: bool = False,
        on_approval: ApprovalHandler | None = None,
        on_question: QuestionHandler | None = None,
        on_event: Callable[[AnyEvent], object] | None = None,
        timeout: float | None = None,
        raw: bool = False,
        keep_events: bool = False,
    ) -> RunStream:
        """Send a prompt on the current session. Await the call for the result, or iterate it for the events.

        ::

            result = await client.prompt("explain this module")
            async with client.prompt("explain this module") as run:
                async for event in run:
                    ...

        Takes the arguments, and raises the errors, of :meth:`Session.prompt`.
        """
        return self.session.prompt(
            prompt,
            images=images,
            mentions=mentions,
            on_approval=on_approval,
            on_question=on_question,
            on_event=on_event,
            timeout=timeout,
            raw=raw,
            keep_events=keep_events,
        )

    #: The same method as :meth:`prompt`, for code that says "stream" when it means to iterate.
    stream = prompt

    async def run(
        self,
        prompt: Prompt,
        *,
        images: Sequence[Image] = (),
        mentions: bool = False,
        on_approval: ApprovalHandler | None = None,
        on_question: QuestionHandler | None = None,
        on_event: Callable[[AnyEvent], object] | None = None,
        timeout: float | None = None,
        keep_events: bool = False,
    ) -> RunResult:
        """Send a prompt and wait for the result; ``await client.prompt(...)`` spelled as a call."""
        return await self.prompt(
            prompt,
            images=images,
            mentions=mentions,
            on_approval=on_approval,
            on_question=on_question,
            on_event=on_event,
            timeout=timeout,
            keep_events=keep_events,
        )

    def __repr__(self) -> str:
        state = "closed" if self._closed else f"session={self._agent.session_id!r}"
        return f"Client({str(self.workspace)!r}, {state})"


class Sessions:
    """The conversations stored for the client's workspace."""

    def __init__(self, client: Client) -> None:
        self._client = client

    async def list(self, *, limit: int = 20) -> list[SessionInfo]:
        """Return the stored sessions, most recently active first.

        Raises:
            ValueError: ``limit`` is not a positive number.
        """
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")
        self._client._check_open()
        stored = await self._client._agent.list_sessions(limit=limit)
        return [SessionInfo(item.session_id, item.title, item.created_at, item.updated_at) for item in stored]

    def new(self) -> Session:
        """Start an empty conversation and make it current.

        Raises:
            SessionBusyError: A run is in progress.
        """
        client = self._client
        client._check_open()
        client._check_free()
        session_id = client._agent.new_session()
        client._fresh.add(session_id)
        return client._handle(session_id)

    async def open(self, session_id: str) -> Session:
        """Continue a stored conversation and make it current.

        The session continues on the model it last used, when the configuration still has that model.

        Raises:
            SessionNotFoundError: No such session, or its file cannot be read (an id that would leave the store
                is also reported this way).
            SessionBusyError: A run is in progress.
        """
        client = self._client
        client._check_open()
        if not isinstance(session_id, str) or not session_id.strip():
            raise SessionNotFoundError("A session id is required")
        client._check_free()
        await client._switch_to(session_id.strip())
        return client._handle(session_id.strip())

    async def latest(self) -> Session | None:
        """Continue the most recently active session, or return ``None`` when the workspace has none."""
        found = await self.list(limit=1)
        return await self.open(found[0].id) if found else None


async def prompt(
    text: Prompt,
    /,
    *,
    workspace: str | Path | None = None,
    config: ZettCodeConfig | None = None,
    config_path: str | Path | None = None,
    models: Sequence[ModelConfig | Mapping[str, object]] | None = None,
    model: str | None = None,
    effort: str | None = None,
    permission: str | None = None,
    resume: str | None = None,
    images: Sequence[Image] = (),
    mentions: bool = False,
    on_approval: ApprovalHandler | None = None,
    on_question: QuestionHandler | None = None,
    on_event: Callable[[AnyEvent], object] | None = None,
    timeout: float | None = None,
    **settings: object,
) -> RunResult:
    """Send one prompt and close everything again: a client, a run, the result.

    Takes the arguments of :class:`Client` and of :meth:`Session.run`. For more than one prompt, keep a
    :class:`Client` open instead, so the conversation carries on.
    """
    async with Client(
        workspace,
        config=config,
        config_path=config_path,
        models=models,
        model=model,
        effort=effort,
        permission=permission,
        resume=resume,
        **settings,
    ) as client:
        return await client.run(
            text,
            images=images,
            mentions=mentions,
            on_approval=on_approval,
            on_question=on_question,
            on_event=on_event,
            timeout=timeout,
        )


def prompt_sync(text: Prompt, /, **options: object) -> RunResult:
    """Send one prompt from code that is not async; the blocking form of :func:`prompt`.

    Raises:
        RuntimeError: Called from inside a running event loop, where blocking would stall it; ``await prompt(...)``.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(prompt(text, **options))  # type: ignore[arg-type]
    raise RuntimeError("prompt_sync() cannot be called from a running event loop; use `await zettcode.sdk.prompt(...)`")
