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

from .brief import LOCKED, MAX_DESCRIPTION, MAX_SHOWN, SUBCOMMANDS, brief_for, split_argument

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
        "- `/harness gen [description]` — turn it on and have a tool built\n"
        "- `/harness reset` — turn it off for later requests; nothing it wrote is deleted"
    )


def register_plain(ctx: PluginContext) -> None:
    """Register the one plain ``/harness``, with the switch this process's runtime provides."""
    switch = ctx.service(HARNESS, HarnessSwitch)

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
            switch.on = False
            return TextCommandResult(
                message=(
                    "**Harness is off for this run**: later requests have none of its tools. Nothing was deleted; "
                    "`/harness gen` builds on it."
                )
            )
        return TextCommandResult(message=_usage(switch, tried=word))

    ctx.commands.register(
        "/harness",
        "the just-in-time harness: /harness gen [what to build], /harness reset",
        run,
        when_busy="refuse",
        subcommands=SUBCOMMANDS,
    )
