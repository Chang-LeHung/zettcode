"""``/harness`` for a process with no screen: the switch, ``gen`` as a preset, and ``reset`` as words.

The panel and the session picker are the terminal's, in :mod:`zettcode.jit_harness.command`. This module is what the
server and the editor behind it run: it imports no widgets, only the harness switch and the brief, and it registers
one plain command named exactly as the terminal's, so a process has one form of each name.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from zettcode.engine.extensions.harness_switch import HarnessSwitch
from zettcode.engine.plugins.commands import PlainCommandContext, TextCommandResult, TurnCommandResult
from zettcode.engine.plugins.services import HARNESS

from .brief import CACHE_MISS, LOCKED, MAX_DESCRIPTION, MAX_SHOWN, SUBCOMMANDS, brief_for, split_argument
from .selection import HARNESS_CHOICES, HarnessChoices

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zettcode.engine.plugins.context import PluginContext


def _shown(description: str) -> str:
    """Return the command line the front end keeps; no terminal columns here, so a character budget is enough."""
    asked = description.strip().replace("\r\n", " ").replace("\r", " ").replace("\n", " ").replace("\t", " ")
    line = f"/harness gen {asked}" if asked else "/harness gen"
    return line if len(line) <= MAX_SHOWN else f"{line[: MAX_SHOWN - 1]}\u2026"


def _usage(switch: HarnessSwitch, tried: str = "") -> str:
    state = "on" if switch.on else "off"
    said = f"`/harness {tried}` is not a word `/harness` takes.\n\n" if tried else ""
    return (
        f"{said}The just-in-time harness is **{state}** for this run.\n\n"
        "- `/harness gen [description]` — turn it on and have tools built\n"
        "- `/harness reset` — turn it off for later requests; nothing it wrote is deleted\n"
        "- `/harness use <name>` — share a library harness with every session (`--none`: each its own)\n"
        "- `/harness save <name>` — keep this session's harness in the library\n"
        "- `/harness fork <name> <new name>` — copy a library harness to change on its own"
    )


def register_plain(ctx: PluginContext) -> None:
    """Register the one plain ``/harness``, with the switch this process's runtime provides."""
    switch = ctx.service(HARNESS, HarnessSwitch)
    choices = ctx.find(HARNESS_CHOICES, HarnessChoices)

    def run(context: PlainCommandContext) -> TextCommandResult | TurnCommandResult:
        word, rest = split_argument(context.argument)
        if word == "gen" and context.host is not None and context.host.locked:
            return TextCommandResult(message=LOCKED)
        if not word:
            return TextCommandResult(message=_usage(switch))
        if word == "gen":
            switch.on = True
            asked = rest.strip()
            notification = ""
            if len(asked) > MAX_DESCRIPTION:
                lost = len(asked) - MAX_DESCRIPTION
                notification = (
                    f"Your description was cut at {MAX_DESCRIPTION} characters: the last {lost} "
                    f"{'character was' if lost == 1 else 'characters were'} not sent."
                )
            return TurnCommandResult(prompt=brief_for(rest), shown=_shown(rest), notification=notification)
        if word == "reset":
            if rest:
                return TextCommandResult(message=f"`/harness reset` takes nothing after it.\n\n{_usage(switch)}")
            was_on = switch.on
            switch.on = False
            cost = f"\n\n{CACHE_MISS}" if was_on else ""
            return TextCommandResult(
                message=(
                    "**Harness is off for this run**: later requests have none of its tools. Nothing was deleted; "
                    f"`/harness gen` builds on it.{cost}"
                )
            )
        if word in {"use", "save", "fork"}:
            from . import library

            if word == "use":
                text = library.use(ctx.config, choices, rest, harness_on=switch.on)
            elif word == "save":
                if context.host is None:
                    text = "`/harness save` needs a session, and this front end has none to name."
                else:
                    text = library.save(ctx.config, choices, context.host.session_id, rest)
            else:
                text = library.fork(ctx.config, rest)
            return TextCommandResult(message=text)
        return TextCommandResult(message=_usage(switch, tried=word))

    ctx.commands.register(
        "/harness",
        "the just-in-time harness: /harness gen [what to build], /harness reset",
        run,
        when_busy="refuse",
        subcommands=SUBCOMMANDS,
    )
