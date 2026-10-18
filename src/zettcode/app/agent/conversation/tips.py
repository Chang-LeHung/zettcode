"""Small tips for the reader, shown under the waiting row while a request runs.

A request can take a while and the screen has nothing to say meanwhile, so it says something that might be
useful: a command, a key, a thing the program does that a reader would not find by typing. Each tip is one
sentence that names what to type, and each is true of this program as it is: ``tests/test_tips.py`` holds
that every command a tip names exists.

The tips are not chosen for the request (they are not about it): they come in an order that is different each
time the program starts, and each request begins one tip further along, so a reader who sends ten requests sees
ten different tips before one comes round again.
"""

from __future__ import annotations

import random
from collections.abc import Callable, MutableSequence, Sequence

#: What the reader may be told, in the words they will see.
TIPS: tuple[str, ...] = (
    "Type while it works: your message can steer this request, or wait and follow it.",
    "Press Shift-Enter (or Alt-Enter) to add a line to your message instead of sending it.",
    "Type @ to mention a file or a skill. A file is read when the message is sent.",
    "Start a message with @name to send it to another running ZettCode session.",
    "/btw <question> is answered on the side and never joins the conversation.",
    "/compact summarizes the conversation now, instead of waiting for the window to fill.",
    "/context shows what is filling the context window, and where this session is stored.",
    "/effort <level> sets how much the model reasons before it answers.",
    "/permission changes how much of the shell may run without asking, even in the middle of a request.",
    "/resume picks up an earlier session; /fork carries this one into a new session.",
    "/title names this session; /export writes it to a standalone HTML file.",
    "/model changes the model for the next request, and /config adds or removes models.",
    "/theme dark or /theme light switches the palette in one step.",
    "Ctrl-R searches what you have sent before; Up recalls the last message.",
    "Ctrl-V attaches an image from the clipboard, for a model that takes images.",
    "Page Up scrolls the conversation, and Esc jumps back to the newest line.",
    "Drag in the conversation to copy text. Hold Shift or Alt to use your terminal's own selection.",
    "Put project instructions in AGENTS.md and they are given to the model with every request.",
    "A SKILL.md in ~/.zettcode/skills teaches ZettCode a job it can repeat.",
    "/usage shows tokens, cache and cost by day, model and session; /resume lists them per session.",
    "/statusline chooses what the header and the status line show, and turns the pet on.",
    "/pet picks a companion that sleeps while idle and works while a request runs; drag it anywhere.",
    "/self-compact lets the model decide for itself when to compact this session.",
    "zettcode resume <id> opens a stored session; zettcode update installs the newest release.",
    "zettcode doctor checks every configured model from a shell, with no session started.",
    "zettcode --auto runs shell commands without asking for that run; /permission can change it later.",
    "Press Esc to stop a request; /continue picks it up again where it left off.",
    "A plugin is a Python package: install it and ZettCode gains its commands, tools, themes or pets.",
    "These tips can be turned off: tips = false under [transcript] in the configuration.",
)


class TipDeck:
    """Hands each request its tips, beginning one further along than the request before.

    Args:
        tips: What to hand out.
        shuffle: Puts them in an order once, when the program starts; ``random.shuffle`` by default, injectable so
            a test can fix the order.
    """

    def __init__(
        self, tips: Sequence[str] = TIPS, *, shuffle: Callable[[MutableSequence[str]], None] = random.shuffle
    ) -> None:
        self._tips = list(tips)
        shuffle(self._tips)
        self._requests = 0

    def next(self) -> tuple[str, ...]:
        """Return all the tips in the order this request will show them: the first it shows is the one that follows."""
        if not self._tips:
            return ()
        start = self._requests % len(self._tips)
        self._requests += 1
        return tuple(self._tips[start:] + self._tips[:start])
