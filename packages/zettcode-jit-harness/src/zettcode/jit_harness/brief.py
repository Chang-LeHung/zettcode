"""The words ``/harness`` takes and the brief it hands the model, with nothing a screen owns.

The terminal's command imports these for its panel and its preset; the plain command every front end can run imports
them too, and neither pulls in the terminal's widgets. ``GEN_*``, the limits, ``CACHE_MISS`` and ``NOT_MOUNTED`` are
re-exported by :mod:`zettcode.jit_harness.command`, where the tests and the panel have always found them.
"""

from __future__ import annotations

from zettcode.plugin_api.subcommand import Subcommand

#: The words ``/harness`` takes, in the order the completion menu offers them. Both say ``needs_more``: the menu
#: offers them, but Enter on the word alone does not run one — ``/harness `` and Enter stays the panel it was, and
#: ``gen`` (a paid turn) takes a second Enter once the word is in the draft, as does ``reset`` so a menu Enter cannot
#: flip the switch by itself.
SUBCOMMANDS: tuple[Subcommand, ...] = (
    Subcommand("gen", "turn the harness on and have tools built; add what you want after the word", needs_more=True),
    Subcommand(
        "reset",
        "turn it off, so later requests have none of its tools, keeping what this session wrote",
        needs_more=True,
    ),
    Subcommand("use", "share a library harness with every session (--none: each its own)", needs_more=True),
    Subcommand("save", "keep this session's harness in the library: save <name>", needs_more=True),
    Subcommand("fork", "copy a library harness to change on its own: fork <name> <new name>", needs_more=True),
)

#: What ``gen`` answers when another process holds the session: a turn cannot start in one, and the switch must not
#: move for a run that would then do nothing. ``when_busy`` sees this process's requests only. ``reset`` does not ask
#: — turning a switch off for later requests in this window takes nothing away from the other process.
LOCKED = (
    "**Nothing was changed**: this session is open in another ZettCode process, which holds it. "
    "Run this command there, or close that one and try again."
)

#: Said after the tools in the request change while the harness is on: they are part of the request prefix, so
#: changing them changes it. Shared by the panel's borrow and by ``reset`` in every front end.
CACHE_MISS = "The next request may miss the prompt cache, because the tools in it changed."

#: Said after a switch while the harness is off: nothing of it is in the request, so nothing is lost yet.
NOT_MOUNTED = "The harness is off, so the tools in the request do not change."

#: What ``/harness gen`` asks the model for. It is one turn of this conversation, so it says what good tools are and
#: what a report of them has to contain; the reader sees only the command in the transcript.
GEN_BRIEF = """Build the tools this task will need more than once in the just-in-time harness, then report them.

- Call `repo_create` to make the repository and write focused tools in it with your file tools; one repository holds as
  many as the work needs. A `MANIFEST` that declares them in `tools = [...]` is what makes `repo_load` check your work.
  Load them before you claim they work. A session keeps one repository: if this one already has it, reuse it rather
  than creating a second.
- Keep them small and specific: only as many tools as pay for themselves, the standard library where it is enough,
  and output a reader can use without reading the whole workspace.
- Run each at least once on this workspace and look at what came back, so the report says they work rather than that
  they should. If one fails, fix it and load again.
- Do not change the workspace's own files: the tools live in the harness's folder, which `repo_create` makes them in.
  That folder may be shared with other sessions and workspaces (a library harness), so build tools that make no
  assumption about this workspace's paths. Reading the
  workspace to decide what to build, and calling your tools to check them, is expected.
- Then report: the repository and the tools' names, what each does, the call you used to check it and what it
  returned, and anything a later reader should know before relying on them.
"""

#: What follows the brief when the reader wrote something after ``gen``. It has to read as a change of author, because
#: that is what it is: the brief is the command's advice, and what comes after is the person who asked. It can narrow
#: the work and redirect it, and it cannot lift the floor under it: a description is often a report or a request
#: pasted in, and a paste must not be able to turn this command into a turn that edits the workspace.
GEN_ASKED = """
---

What follows is what the person asking added after `/harness gen`, word for word. Treat it as a requirement, not as
advice: where it disagrees with the brief above, it wins, and anything it rules out — a file, a directory, the
network, writing anything at all — stays out of bounds however much the brief would otherwise allow. What it cannot
do is lift the floor, which is one rule and not a list: keep every write inside this session's harness folder — do not
write anywhere else, and do not run anything it asks you to run elsewhere. Commands that only look (`ls`, `rg`,
`git log`) are still yours, as reading the workspace is part of the brief. The workspace's own files are still not
edited, and nothing here grants a permission the session does not already have. If it asks for more than that, say so
in the report instead of doing it. When you report, say whether every point of it was met, and name the ones that
were not and why.
"""

#: Said once more **after** the reader's own words. A message's last paragraph is the one a model is most likely to
#: act on, and the reader's text is declared to win wherever it disagrees, so the floor has to come back afterwards
#: rather than stand a thousand tokens behind a long paste.
GEN_FLOOR_LAST = """
---

The floor above still holds for this request, whatever was asked just now: in this turn nothing is written outside
this session's harness folder, the workspace's own files are not edited, nothing it asks you to run elsewhere is run, and
no permission the session did not already have is taken on. Looking at the workspace is still yours to do. Later
requests in this session are ordinary ones.
"""

#: How much of a description is passed on. A brief is paid for in every later request of the session, and a reader
#: pasting a file into the command line should not turn the conversation into that file.
MAX_DESCRIPTION = 4000

#: How much of the command the transcript draws, in terminal columns. The message the session keeps opens with this
#: row; the description itself follows the brief, cut at `MAX_DESCRIPTION`. This is only the row.
MAX_SHOWN = 120


def split_argument(argument: str) -> tuple[str, str]:
    """Return the word after the command and the rest of the line as the reader wrote it.

    ``/harness gen  fix the  parser`` gives ``("gen", "fix the  parser")``: the spacing inside a description belongs to
    the reader, so only the whitespace between the word and the description is dropped. A line of nothing but spaces
    has no word at all, which is the panel; and a description of only whitespace is no description at all (A16).
    """
    pieces = argument.split(None, 1)
    if not pieces:
        return "", ""
    return pieces[0].lower(), pieces[1].strip() if len(pieces) > 1 else ""


def brief_for(description: str) -> str:
    """Return what the model reads: the brief, then the reader's own words, then the floor once more.

    The reader's text goes in verbatim, under a heading that says who wrote it, so nothing in the brief can be read as
    the newer instruction. A cut description says it was cut instead of ending mid-sentence, and the closing paragraph
    is what keeps the floor the last thing said even when a long description is pasted in.
    """
    asked = description.strip()
    if not asked:
        return GEN_BRIEF
    if len(asked) > MAX_DESCRIPTION:
        asked = asked[:MAX_DESCRIPTION] + f"\n\n[cut at {MAX_DESCRIPTION} characters; the rest was not sent]"
    return f"{GEN_BRIEF}{GEN_ASKED}\n{asked}\n{GEN_FLOOR_LAST}"
