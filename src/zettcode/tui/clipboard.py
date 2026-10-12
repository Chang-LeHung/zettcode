"""Where a copy goes: the machine's own clipboard, or the terminal's.

A program writes to *a* clipboard, and which one the reader means depends on where the
program is running. On the reader's own machine the two are the same thing. Over ``ssh`` they
are not: the program runs on the server, the reader sits at a terminal on another machine, and
the clipboard they will paste from is that machine's. A system clipboard tool on the server
reaches the server's clipboard — if it reaches anything at all — and the reader finds nothing
when they paste.

The only way across the connection is the terminal itself. OSC 52 (``ESC ] 52 ; c ; <base64>
BEL``) asks the terminal to put text on *its* clipboard, and it travels over the same byte
stream as everything else the program prints, so it arrives wherever the reader is. That is
why it is the route over ``ssh`` and only a fallback on a local machine: where a system tool
works, using it never needs the terminal's permission — several terminals ask the reader, or
refuse by default, before letting a program write their clipboard.

This module only decides and encodes. Writing is :func:`zettcode.tui.runner.clipboard_writer`'s
job, and the shell reads :func:`copy_route` to say truthfully where the text went.
"""

from __future__ import annotations

import base64
import os
from collections.abc import Mapping
from typing import Literal

#: Environment variable that overrides the choice: ``system``, ``terminal``, or ``auto``.
#: Detection reads the environment, and the environment can be wrong — ``sudo`` and some
#: multiplexers drop the variables, and a forwarded X display makes the server's clipboard
#: the right one — so the reader can say.
CLIPBOARD_ENV = "ZETTCODE_CLIPBOARD"

#: Variables the SSH server sets for the session it starts; any one of them means the program
#: is running on the far side of a connection.
SSH_VARIABLES = ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY")

CopyRoute = Literal["system", "terminal"]


def is_remote(environ: Mapping[str, str] | None = None) -> bool:
    """Return whether this process was started through an SSH session.

    Args:
        environ: Environment to read; defaults to ``os.environ``.
    """
    env = os.environ if environ is None else environ
    return any(env.get(name) for name in SSH_VARIABLES)


def copy_route(environ: Mapping[str, str] | None = None) -> CopyRoute:
    """Return which clipboard a copy should reach.

    ``terminal`` over ``ssh``, ``system`` otherwise, unless :data:`CLIPBOARD_ENV` says
    which. A value that is neither ``system`` nor ``terminal`` — ``auto``, or a typo — leaves
    the detection in charge, because a mistyped override that silently disabled copying would
    be worse than one that is ignored.

    Args:
        environ: Environment to read; defaults to ``os.environ``.
    """
    env = os.environ if environ is None else environ
    override = env.get(CLIPBOARD_ENV, "").strip().lower()
    if override == "system":
        return "system"
    if override == "terminal":
        return "terminal"
    return "terminal" if is_remote(env) else "system"


def osc52(text: str, environ: Mapping[str, str] | None = None) -> str:
    """Return the escape sequence that asks the terminal to copy ``text``.

    Inside tmux the sequence is sent twice: bare, which tmux honours when its
    ``set-clipboard`` option is ``on``, and wrapped in tmux's passthrough, which it forwards to
    the outer terminal when ``allow-passthrough`` is on. Which of the two a given tmux accepts
    is a setting the program cannot see, and both carry the same text, so a copy that lands
    twice is the same copy.

    Args:
        text: What to put on the clipboard.
        environ: Environment to read; defaults to ``os.environ``.
    """
    env = os.environ if environ is None else environ
    payload = base64.b64encode(text.encode()).decode()
    sequence = f"\x1b]52;c;{payload}\x07"
    if env.get("TMUX"):
        # DCS tmux ; <sequence with every ESC doubled> ST: the doubling is how a passthrough
        # tells the escapes it carries from the one that ends it.
        return sequence + "\x1bPtmux;" + sequence.replace("\x1b", "\x1b\x1b") + "\x1b\\"
    return sequence
