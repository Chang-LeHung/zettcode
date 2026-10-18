"""Keep what a shell command printed out of the reader's workspace.

zett-agent's ``bash`` tool keeps a command's full output when the preview it returns is cut
short, so the model can read the rest. It keeps it in a ``.zett-tool-output`` folder *inside the
directory it runs in* — the reader's own project — and names the files in the text it returns::

    ... [output truncated; full streams kept at .zett-tool-output/shell-ab12cd/stdout.txt and
    .zett-tool-output/shell-ab12cd/stderr.txt]

That puts files the reader never asked for among their source, where they turn up in a status
listing, a search, a backup, or a commit. The path is hard-coded in the tool, and the tool is
zett-agent's to own, so it is not re-implemented here; and the folder cannot simply be made a
link to somewhere else, because the tool resolves it and then asks for the result relative to the
working directory, which a link out of it breaks the moment output is truncated.

What can be done, and is done here, is to deal with the result: after the tool has run and before
its result is stored or sent anywhere, the folder it named is moved into the session's own folder
under the store — ``~/.zettcode/sessions/<workspace>/<session>/tool-output/`` — and the paths in
the text are rewritten to where the files now are. The model reads them with ``read_file`` by
absolute path, which that tool accepts, so nothing about how it uses them changes; the reader's
project is left as it was found; and the output goes away with the session it belongs to.
"""

from __future__ import annotations

import asyncio
import re
import shutil
from pathlib import Path, PurePosixPath

from zett_agent.agent import AgentRunContext
from zett_agent.extensions.base import AgentExtension
from zett_agent.messages import ToolCall, ToolMessage

from ..storage import SessionStore

#: The tool whose output is moved.
SHELL_TOOL = "bash"

#: The folder the tool makes inside the directory it runs in.
OUTPUT_ROOT = ".zett-tool-output"

#: Where, inside a session's folder, the moved output is kept.
KEPT_AS = "tool-output"

#: The note the tool ends its result with when a preview was cut short. It is matched at the very
#: end of the text and nowhere else: a command can print anything it likes, and a line that merely
#: looks like this one, earlier in the output, is the command's own and must not be acted on.
_NOTE = re.compile(r"full streams kept at (?P<out>\S+) and (?P<err>\S+)\]\s*\Z")


class ToolOutputExtension(AgentExtension):
    """Move a shell command's kept output out of the workspace and into the session's folder."""

    def __init__(self, store: SessionStore) -> None:
        """Keep the store whose session folders the output moves into."""
        self._store = store

    async def after_tool(
        self,
        context: AgentRunContext,
        call: ToolCall,
        result: ToolMessage,
        error: Exception | None,
    ) -> None:
        """Rewrite a truncated shell result so its files are in the session's folder.

        Both outcomes carry the note — a command that failed has its output kept the same way —
        so the result is handled whether or not ``error`` is set. Nothing here may fail a tool
        call: whatever goes wrong, the result is left as the tool wrote it, and the files stay
        where the tool put them, which still works.
        """
        if call.name != SHELL_TOOL:
            return
        try:
            await self._move_kept_output(context, result)
        finally:
            self._tidy()

    async def _move_kept_output(self, context: AgentRunContext, result: ToolMessage) -> None:
        """Move the output the result's note names, and rewrite the note to say where it went."""
        if not isinstance(result.content, str):
            return
        note = _NOTE.search(result.content)
        session_id = context.config.session_id
        if note is None or not isinstance(session_id, str):
            return
        moved = await asyncio.to_thread(self._relocate, note.group("out"), note.group("err"), session_id)
        if moved is None:
            return
        text, out, err = result.content, *moved
        result.content = (
            text[: note.start("out")] + out + text[note.end("out") : note.start("err")] + err + text[note.end("err") :]
        )

    @staticmethod
    def _tidy() -> None:
        """Remove the tool's output root when nothing is in it, so the project is as it was found.

        The tool makes the root on *every* call, before it knows whether the output will need
        keeping, and takes only its own folder away again: a command that printed a line leaves an
        empty ``.zett-tool-output`` behind, which is the folder a reader sees in their project.

        This is done here, on the event loop, and not with the move on a thread, on purpose. A
        command about to run makes the root and then, on the very next line and with nothing
        awaited between, makes its folder in it; two commands on the loop cannot interleave
        there, and a removal from a thread could land between the two and fail a command that
        did nothing wrong. A root with anything in it — a neighbour's running command — is not
        empty, and the removal fails, which is the right answer.
        """
        try:
            (Path.cwd().resolve() / OUTPUT_ROOT).rmdir()
        except OSError:
            pass

    def _relocate(self, out: str, err: str, session_id: str) -> tuple[str, str] | None:
        """Move the folder the two paths name, and return where its two files now are.

        Only a folder the tool itself would have made is moved: a direct child of the tool's
        output root, named like its own, holding exactly the two streams it names. Anything
        else — a path a command printed, a folder that is not there — is left alone.

        Returns:
            The new paths of the standard output and error files, or ``None`` when nothing was
            moved.
        """
        first, second = PurePosixPath(out), PurePosixPath(err)
        if (
            len(first.parts) != 3
            or first.parts[0] != OUTPUT_ROOT
            or not first.parts[1].startswith("shell-")
            or first.parts[:2] != second.parts[:2]
            or first.name != "stdout.txt"
            or second.name != "stderr.txt"
            or len(second.parts) != 3
        ):
            return None
        source = Path.cwd().resolve() / OUTPUT_ROOT / first.parts[1]
        try:
            if not (source / "stdout.txt").is_file() or not (source / "stderr.txt").is_file():
                return None
            kept = self._store.session_dir(session_id) / KEPT_AS
            kept.mkdir(parents=True, exist_ok=True)
            target = kept / source.name
            suffix = 1
            while target.exists():
                suffix += 1
                target = kept / f"{source.name}-{suffix}"
            shutil.move(str(source), str(target))
        except (OSError, ValueError):
            return None
        return str(target / "stdout.txt"), str(target / "stderr.txt")
