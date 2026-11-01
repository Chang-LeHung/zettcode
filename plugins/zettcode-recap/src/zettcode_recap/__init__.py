"""``/recap``: a short account of what this session is doing, for a reader who stepped away.

The plugin watches the turns of the conversation: a turn ending arms a wait, and a turn starting cancels it. When the
reader has not started a new turn for long enough, it asks the session's model for one small summary, reusing the
conversation's warm prompt cache without writing its own content into it (``cache="read"``). ``/recap`` asks for one
at once.

The wait is about the reader's own activity, not about the window: somebody reading the last answer is still there,
and somebody who switched to another application after a turn is as idle as one reading. So the clock is "since the
last turn ended", and any new turn — typed, from another session, or started by a command — cancels it.

It never joins the conversation: the question and the answer are a side question, so the next turn does not read
them, and it is shown as a markdown message whose text is a blockquote — the quote the renderer already draws, with
nothing of its own in the transcript. Nothing about the model's own context changes.

The delay is ``min(after_seconds, 0.8 × cache_ttl_seconds)``, defaulting to ``min(180, 0.8 × 300)`` = 180 seconds:
after that long away, a provider's cached prefix is likely gone, so waiting longer would buy a colder, dearer
summary. All four numbers are written in the plugin's own table, and the reader's value wins:

    [plugins.recap]
    after_seconds = 180       # how long no new turn may start
    cache_ttl_seconds = 300   # the provider's prompt-cache lifetime, which the delay is a fraction of
    min_messages = 3          # a conversation worth summarising
    min_since_recap = 2       # and worth summarising again
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from contextlib import suppress
from typing import TYPE_CHECKING

from zettcode.app.commands import CommandContext, CommandResult
from zettcode.app.plugins import HOST_LINK, HostLink, TuiPlugin
from zettcode.engine.plugins.context import PluginContext

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from collections.abc import Mapping
    from typing import Any

    from zettcode.app.commands import CommandHost

#: The one place the version is written; ``pyproject.toml`` reads it from here.
__version__ = "0.1.0"

__all__ = ["RecapPlugin", "__version__"]

#: What the model reads. Short by design: a recap is a line to get back to work with, not a summary of the work.
PROMPT = (
    "The user stepped away and is coming back. Recap in under 40 words, 1-2 plain sentences, no markdown. "
    "Lead with the overall goal and current task, then the one next action. Skip root-cause narrative, fix "
    "internals, secondary to-dos, and em-dash tangents."
)

#: How long one recap may take before it is dropped; one that arrives after the reader is working again is noise.
TIMEOUT_SECONDS = 60.0

#: The defaults, which a ``[plugins.recap]`` table overrides. See the module docstring for what they mean.
DEFAULTS: dict[str, object] = {
    "after_seconds": 180,
    "cache_ttl_seconds": 300,
    "min_messages": 3,
    "min_since_recap": 2,
}

#: What a recap line starts with: the label inside the quote the message renderer draws.
PREFIX = "Recap"

#: The character a working row trails off with (the transcript's own ellipsis).
ELLIPSIS = "\u2026"


def quote(text: str) -> str:
    """Return the recap as a Markdown blockquote, one marker per line so a wrapped answer stays inside it."""
    return "\n".join(
        f"> **{PREFIX}** \u00b7 {line}" if at == 0 else f"> {line}" for at, line in enumerate(text.split("\n"))
    )


def _number(given: Mapping[str, object], key: str, *, least: float) -> float:
    """Return one declared setting as a number, refusing one that could never be meant."""
    value = float(given[key])  # type: ignore[arg-type]  # `declare` checked it against the default's type
    if value < least:
        raise ValueError(f"[plugins.recap] {key} must be at least {least:g}, not {value:g}")
    return value


class RecapPlugin(TuiPlugin):
    """Summarise the session when the reader has been away, and on ``/recap``."""

    name = "recap"
    description = "summarise where the session is when you step away"

    def __init__(self) -> None:
        """Start with nothing counted and no recap on its way."""
        self._link: HostLink | None = None
        #: Bumped by every turn start: a wait armed for an older one is for a conversation that has moved on.
        self._generation = 0
        self._turns = 0
        self._since_recap = 0
        self._seeded = False
        self._session = ""
        self._timer: asyncio.Task[None] | None = None
        self._asking: asyncio.Task[None] | None = None
        self.after_seconds = 180.0
        self.cache_ttl_seconds = 300.0
        self.min_messages = 3
        self.min_since_recap = 2

    def activate(self, ctx: PluginContext) -> None:
        """Read the settings, take the shell link, and register the command and the two hooks."""
        given = ctx.settings.declare(**DEFAULTS)
        self.after_seconds = _number(given, "after_seconds", least=0)
        self.cache_ttl_seconds = _number(given, "cache_ttl_seconds", least=0)
        self.min_messages = int(_number(given, "min_messages", least=1))
        self.min_since_recap = int(_number(given, "min_since_recap", least=1))
        self._link = ctx.find(HOST_LINK, HostLink)
        if ctx.tui is None:
            return
        # `/recap` asks the shell's own side question, which takes seconds, so it returns the work to do and the shell
        # shows what it is doing until it is answered; Ctrl-C and Escape stop it.
        ctx.tui.register_command("recap", "summarise where this session is", self.command, when_busy="refuse")
        ctx.tui.register_turn_start_handler(self.turn_started)
        ctx.tui.register_turn_end_handler(self.turn_ended)

    # -- the delay ---------------------------------------------------------------------------------
    @property
    def delay(self) -> float:
        """Return how long the conversation must be quiet — no new turn — before a recap is made."""
        return min(self.after_seconds, 0.8 * self.cache_ttl_seconds)

    def due(self) -> bool:
        """Return whether the conversation is long enough, and fresh enough, to be worth a recap."""
        return self._turns >= self.min_messages and self._since_recap >= self.min_since_recap

    # -- what the shell reports --------------------------------------------------------------------
    def turn_started(self) -> None:
        """The reader is asking again: whatever recap was waiting or being written is about a conversation that
        has moved on, so it stops here."""
        self._generation += 1
        self._cancel()

    def turn_ended(self, completed: bool) -> None:
        """Count the turn, and start the idle wait.

        Called on the shell's event loop: the counting happens here, and only what has to wait — the stored history,
        the clock, the model — becomes a task.
        """
        host = self._host()
        if host is None:
            return
        # The counts describe the conversation, not the plugin: `/new` or another session leaves them behind.
        if host.client.session.id != self._session:
            self._session = host.client.session.id
            self._turns = 0
            self._since_recap = 0
            self._seeded = False
            self._cancel()
        self._turns += 1
        self._since_recap += 1
        if not self._seeded:
            self._seeded = True
            self._spawn(self._seed())
        if self.due():
            self._schedule()

    def _schedule(self) -> None:
        """Wait :attr:`delay` seconds, then recap if no turn has started since."""
        if self._timer is not None and not self._timer.done():
            return
        self._timer = self._spawn(self._wait_then_recap(self._generation))

    def _cancel(self) -> None:
        """Drop a waiting recap and stop one being written: a turn started or the session changed, so the wait and
        any recap are about a conversation that has moved on."""
        for task in (self._timer, self._asking):
            if task is not None and not task.done():
                task.cancel()
        self._timer = None
        self._asking = None

    async def _wait_then_recap(self, generation: int) -> None:
        """Sleep for the delay, then make the recap nobody asked for."""
        try:
            await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            return
        if generation != self._generation or not self.due():
            return
        with suppress(Exception):  # the timer has no reader to tell; the next turn may try again
            text = await self._recap(cancellable=True)
            if text:
                self._show(text)

    # -- the summary -------------------------------------------------------------------------------
    async def _seed(self) -> None:
        """Count what a resumed conversation already had, so ``min_messages`` means the session and not this run."""
        host = self._host()
        if host is None:
            return
        session = host.client.session.id
        typed = 0
        with suppress(Exception):  # a session another process holds, or a store that cannot be read
            history = await host.client.session.history()
            typed = sum(1 for message in history if message.role == "user" and message.relay is None)
        if session != host.client.session.id or session != self._session:
            return  # the reader left that conversation while its history was being read
        self._turns = max(self._turns, typed)
        # A resumed conversation can be worth a recap from its first new turn: the turn end that started this read
        # saw too few messages to arm anything, so it is armed here, once the stored ones are counted.
        if self.due() and (self._timer is None or self._timer.done()):
            self._schedule()

    async def _ask(self) -> str:
        """Ask the model for the summary, as the shell's own side question.

        Raises:
            RuntimeError: The shell is not built yet.
            Exception: Whatever the ask raised — a run already going, the session locked, the provider failing.
        """
        host = self._host()
        if host is None:
            raise RuntimeError("The shell is not ready yet")
        return await host.client.session.ask(PROMPT, cache="read", timeout=TIMEOUT_SECONDS)

    async def _recap(self, *, cancellable: bool) -> str:
        """Ask for the summary and return it, saying nothing itself.

        Args:
            cancellable: Whether a new turn may stop it. True for the recap nobody asked for, which would be news
                about a conversation that has moved on; false for ``/recap``, which was asked for and is answered
                whatever the conversation does next.

        Raises:
            Exception: What the session's ``ask`` raised — refused because a run is going, the session locked by
                another process, the provider failing — for a caller with a reader to tell.
        """
        if self._host() is None:
            return ""
        asking = asyncio.current_task() if cancellable else None
        if cancellable:
            self._asking = asking
        try:
            answer = await self._ask()
        finally:
            if cancellable and self._asking is asking:
                self._asking = None
        text = " ".join(answer.split()).strip()
        if text:
            self._since_recap = 0
        return text

    async def command(self, context: CommandContext) -> CommandResult:
        """``/recap``: summarise now, whatever the clock and the turn count say.

        The answer takes a model call, so the handler hands the waiting to the shell: the pinned row says what is
        happening, and the reader can stop it while it works.
        """
        if self._host() is None:
            raise ValueError("The shell is not ready yet; try again in a moment")
        return CommandResult(intro=f"{PREFIX} {ELLIPSIS} writing", run=self._write())

    async def _write(self) -> CommandResult:
        """Ask for the summary and answer with it, as the rest of ``/recap``."""
        try:
            text = await self._recap(cancellable=False)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise ValueError(f"Could not write a recap: {error}") from error
        if not text:
            return CommandResult(notification="Nothing to recap yet")
        return CommandResult(message=quote(text), notification=f"{PREFIX} ready")

    # -- helpers -----------------------------------------------------------------------------------
    def _show(self, text: str) -> None:
        """Say it in the conversation as a message — the row a command's answer uses — and ask for the frame."""
        host = self._host()
        if host is None:
            return
        host.transcript.markdown(quote(text))
        # A recap arrives between keys, so nothing else would ask for the frame that shows it.
        host.request_layout()

    def _host(self) -> CommandHost | None:
        """Return the shell, or ``None`` before it is built (and in a program that has none)."""
        return self._link.host if self._link is not None else None

    @staticmethod
    def _spawn(coroutine: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
        """Run one piece of waiting work as a task on the loop the shell already runs on."""
        task = asyncio.get_running_loop().create_task(coroutine)
        task.add_done_callback(RecapPlugin._swallow)
        return task

    @staticmethod
    def _swallow(task: asyncio.Task[None]) -> None:
        """A background failure is the plugin's own business: the shell keeps running, and a later turn may retry."""
        with suppress(asyncio.CancelledError, Exception):
            task.exception()
