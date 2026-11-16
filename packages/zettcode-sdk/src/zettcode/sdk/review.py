"""``/code-review``: the brief a review runs as a turn, for every front end.

The command owns no page and no shell: it writes what the model reads and returns a preset, so the terminal, the
server and the editor behind it all send the same request. It lives beside the other commands every front end can run
(see :mod:`zettcode.sdk.commandline`) because it needs nothing a screen holds.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from typing import TYPE_CHECKING

from zettcode.engine.plugins.commands import PlainCommandContext, TurnCommandResult

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zettcode.engine.plugins.context import PluginContext

__all__ = ["CodeReview"]


class CodeReview:
    """``/code-review``: ask for a review of the uncommitted changes, in this conversation."""

    #: What the model is asked, in pieces: a preset for the turn, not a report about it. The reader gets the review
    #: as an answer they could have asked for by typing all of this themselves.
    INTRO = "Review the uncommitted changes in this workspace."
    COLLECT = (
        "Collect them first: `git status --short` for what changed, `git diff HEAD` for the patch, and the contents "
        "of any untracked file that belongs to the change."
    )
    #: The reviewer is a session of its own, at the shell level of the reader who asked — never above it, since
    #: nobody here approved anything. The name is chosen for this review rather than fixed in the text: every
    #: review naming its daemon the same thing made the machine's daemon list unreadable. `{spawn}` is the line with
    #: `REVIEW_NAME` in it; the model replaces that one token rather than reassembling the command.
    DAEMON = (
        "Have it read by a reviewer of its own, so this conversation keeps its context. `{command} list` shows the "
        "daemons running on this machine. If a reviewer for this change is already there — you named it in an "
        "earlier round, or its name says what it is reviewing — reuse it rather than starting another: it has read "
        "the earlier rounds and already knows this change, which makes it the better reviewer. Send it what you "
        'need with `send_message(to="<session id>", message=...)` — the request as you would put it, and that the '
        "change is the uncommitted diff this workspace holds, which it can collect itself. Only when there is none, "
        "choose a short name for this reviewer — hyphens are fine, and it should say what it reviews, such as "
        "`review-api`, `review-parser`, `review-auth`, or a word from the change — and run\n"
        "\n"
        "    {spawn}\n"
        "\n"
        "with `REVIEW_NAME` replaced by that name; take the session id it prints. Give it a name that "
        "tells it apart from the other reviewers on this machine, rather than the same name for every review. Keep the "
        "same name for every round of this review, so `{command} list` finds it again, and do not give two "
        "reviewers the same name.\n"
        "\n"
        "Say in that message, every round, that it must answer: send its findings back to you with `send_message`, "
        "and if it has nothing to change, say that in a word. A reviewer that goes quiet leaves the change "
        "waiting, and a review that found nothing cannot be told apart from one that never happened.\n"
        "\n"
        "Keep the reviewer running while you work on what it found: make the changes here, then send it the new "
        "state of the change for another look, and go round again until it has nothing left to say. A reviewer "
        "stopped after the first round cannot tell you whether the fix worked. If a round brings no answer at all, "
        "send the request once more; if that also goes unanswered, read what it did say: its conversation is "
        "`~/.zettcode/sessions/*/<session id>/data.jsonl`, and the last assistant message in it is its review — "
        "report that here, then stop it with `{command} kill <session id>` so that it is not left running. If a "
        "daemon cannot be started here, say why and do the review yourself."
    )
    #: A reviewer is told plainly what it is: the instruction is the safeguard, and the reader is told the same in
    #: the guide, since a session at `full` could change things if it chose to.
    NOT_YOURS = (
        "Tell the reviewer plainly that it reads and does not change: no edits, no writes, no commits, no command "
        "that modifies the workspace. The changes are yours to make, and you keep making them, round after round, "
        "until nothing it found is left."
    )
    #: Under `deny` there is no shell for a daemon to collect a diff with, and the session that asked has none
    #: either: the review is a reading one.
    ALONE = (
        "This session runs no shell commands, so neither the diff nor a daemon to read it can be gathered: review "
        "the files themselves with the reading tools, and say which ones you read."
    )
    SHAPE = (
        "In the review, name concrete problems with `file:line` — correctness, error handling, tests, naming — say "
        "what you would change and why, and do not restate the diff.\n"
        "\n"
        "What to pay attention to: {focus}"
    )

    #: The shell levels a reviewer may be started at. `ask` has no meaning in a process nobody sits at, so it is
    #: started `safe`: sandboxed, which is still more than a reader at `ask` has granted.
    LEVELS = {"full": "full", "safe": "safe", "ask": "safe"}

    def register(self, ctx: PluginContext) -> None:
        """Offer it to every front end: what it answers with is a turn, not a page."""
        ctx.commands.register(
            "/code-review",
            "review the uncommitted changes: /code-review [what to look for]",
            self.review,
            when_busy="queue",
        )

    def review(self, context: PlainCommandContext) -> TurnCommandResult:
        """Run the review as one turn, with what the reader typed as its focus.

        The command adds no work of its own: it writes the brief and returns it as a preset, and the ordinary turn
        does the rest — the echo in the transcript, the session, the streaming, the line it ends on. Nothing is
        gathered here, so the model decides what the review needs and how to get it.

        The transcript shows the command the reader typed, not the brief it stands for: the brief is what the model
        reads, and `shown` is what the conversation keeps.
        """
        argument = context.argument.strip()
        focus = argument or "anything that would make this change wrong or hard to keep"
        shown = f"/code-review {argument}" if argument else "/code-review"
        return TurnCommandResult(prompt=self.brief(level=context.level, focus=focus), shown=shown)

    def brief(self, *, level: str, focus: str) -> str:
        """Return what the model reads, for a reader whose shell level is ``level``.

        The reviewer is started at the reader's own level (`ask` becoming `safe`, which is what a level that asks
        means in a process nobody can answer in), and not at all under `deny`.
        """
        command = self.command()
        parts = [self.INTRO, self.COLLECT]
        if level in self.LEVELS:
            spawn = f"{command} spawn --name REVIEW_NAME --permission {self.LEVELS[level]}"
            parts.append(self.DAEMON.format(command=command, spawn=spawn))
            parts.append(self.NOT_YOURS)
        else:
            parts.append(self.ALONE)
        parts.append(self.SHAPE.format(focus=focus))
        return "\n\n".join(parts)

    @staticmethod
    def command() -> str:
        """Return the command that runs this installation's daemon, quoted for the shell that will run it.

        `python -m zettcode.daemon` and the interpreter that is running this terminal: a checkout whose console
        script is not on the PATH, or a virtualenv nothing else can see, still works. The quoting follows the
        platform's shell, because a Windows path with a space cannot be passed the way POSIX quotes it.
        """
        argv = [sys.executable, "-m", "zettcode.daemon"]
        return subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)
