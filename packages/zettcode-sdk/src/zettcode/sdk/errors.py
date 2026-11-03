"""The errors the SDK raises.

Everything the SDK raises on purpose is a :class:`ZettCodeError`, so a program can catch one class for "ZettCode
refused or failed". The original error is kept as ``__cause__`` wherever there was one, and a few of these also
inherit the built-in a caller would already be catching (``LookupError``, ``TimeoutError``), so existing handlers
keep working.

Cancellation is never wrapped: ``asyncio.CancelledError`` goes through untouched, because swallowing or renaming it
breaks the caller's own cancellation.
"""

from __future__ import annotations

__all__ = [
    "ClientClosedError",
    "ConfigurationError",
    "DaemonStartError",
    "NothingToDoError",
    "RunError",
    "RunTimeoutError",
    "SendError",
    "SessionBusyError",
    "SessionLockedError",
    "SessionNotFoundError",
    "WorkspaceConflictError",
    "ZettCodeError",
]


class ZettCodeError(Exception):
    """Base class of every error the SDK raises on purpose."""


class ConfigurationError(ZettCodeError, ValueError):
    """The configuration, or something chosen from it, is not usable.

    Raised for an unreadable config file, an unknown setting name, a model, reasoning effort, or permission level
    that does not exist, and a workspace that is not a directory. The message says which, and what would have worked.
    """


class ClientClosedError(ZettCodeError):
    """The client was closed, so it can no longer run anything."""


class SessionBusyError(ZettCodeError):
    """A run is already in progress on this client.

    A client has one conversation running at a time, exactly as the terminal application does. Wait for the run to
    end, stop it (leave the ``async for`` or cancel the task), or use another client for parallel work.
    """


class SessionLockedError(ZettCodeError):
    """Another process has this session open, so this one may only read it.

    Sessions are locked by the process that has them open. Reading history is still possible; running, renaming,
    compacting and exporting are refused until the other process lets go.
    """


class SessionNotFoundError(ZettCodeError, LookupError):
    """The store holds no session with that id, or its file cannot be read."""


class NothingToDoError(ZettCodeError):
    """The request is fine but there is nothing for it to act on.

    Continuing a conversation that was not interrupted, or compacting one that is already compacted. The message
    says why, in the application's own words.
    """


class WorkspaceConflictError(ZettCodeError):
    """Another client in this process already works in a different directory.

    The coding tools resolve relative paths against the process's working directory, which is global to the
    process, so two clients on different workspaces would edit each other's files. Close the other client, or run the
    second one in a process of its own.
    """


class RunError(ZettCodeError):
    """A run ended with an error from the model, the provider, or the network.

    Attributes:
        retryable: Whether trying the same request again could succeed: a timeout, a dropped connection, a rate
            limit, or a server error. A rejected key or a malformed request is not.
        partial_text: What the model had already said when the error came, which is often still worth keeping.
    """

    def __init__(self, message: str, *, retryable: bool = False, partial_text: str = "") -> None:
        super().__init__(message)
        self.retryable = retryable
        self.partial_text = partial_text


class RunTimeoutError(RunError, TimeoutError):
    """A run took longer than the ``timeout`` it was given and was stopped.

    The conversation keeps whatever the run had already added to it, as it does for a run the reader stops.
    """

    def __init__(self, seconds: float, *, partial_text: str = "") -> None:
        super().__init__(f"The run did not finish within {seconds:g}s", retryable=True, partial_text=partial_text)
        self.seconds = seconds


class SendError(ZettCodeError):
    """A message to another session did not arrive.

    Attributes:
        reason: ``offline`` when there is no broker, ``lost`` when the connection ended with the message in flight (it
            may or may not have been delivered), otherwise the broker's own reason (``unknown``, ``ambiguous``,
            ``rejected``, ``timeout``, ``loop``, ``rate``, ``empty``, ``too_long``).
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class DaemonStartError(ZettCodeError):
    """A background agent was started and never became reachable.

    Attributes:
        log: The file the child process wrote its first words to, when there is one: the reason it gave is in it.
    """

    def __init__(self, message: str, log: str | None = None) -> None:
        super().__init__(message)
        self.log = log
