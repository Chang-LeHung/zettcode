"""The two memory indexes and the daemon guide are system messages the model starts a request with."""

from __future__ import annotations

from pathlib import Path

from zett_agent.agent import AgentRunConfig, AgentRunContext, AgentState
from zett_agent.messages import SystemMessage

from zettcode.memory.extension import (
    MAX_ENTRYPOINT_BYTES,
    MAX_ENTRYPOINT_LINES,
    DaemonGuideExtension,
    MemoryExtension,
    canonical_git_root,
    project_memory_directory,
)


def _context(*tools: str) -> AgentRunContext:
    state = AgentState()
    state._messages.append(SystemMessage(content="the project instructions"))
    return AgentRunContext(AgentRunConfig(session_id="s1"), state, {name: object() for name in tools})


def _system(context: AgentRunContext) -> list[str]:
    return [message.content for message in context.state.messages if isinstance(message, SystemMessage)]


def _extension(tmp_path: Path, workspace: Path | None = None) -> MemoryExtension:
    work = workspace or tmp_path / "work"
    work.mkdir(exist_ok=True)
    return MemoryExtension(
        project_root=tmp_path / "projects",
        personal_root=tmp_path / "personal",
        workspace=work,
    )


def test_the_two_scopes_have_their_own_folders(tmp_path: Path):
    extension = _extension(tmp_path)

    assert extension.personal_directory() == tmp_path / "personal"
    assert extension.project_directory() == project_memory_directory(tmp_path / "projects", tmp_path / "work")
    assert extension.personal_directory() != extension.project_directory()


def test_a_worktree_and_its_repository_share_the_project_memory(tmp_path: Path):
    repository = tmp_path / "repo"
    (repository / ".git").mkdir(parents=True)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {repository / '.git' / 'worktrees' / 'wt'}\n")
    (repository / ".git" / "worktrees" / "wt").mkdir(parents=True)
    (repository / ".git" / "worktrees" / "wt" / "commondir").write_text("../..\n")

    assert canonical_git_root(worktree) == repository
    assert project_memory_directory(tmp_path / "projects", worktree) == project_memory_directory(
        tmp_path / "projects", repository
    )


def test_a_git_marker_that_is_not_utf8_falls_back_to_its_own_directory(tmp_path: Path):
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / ".git").write_bytes(b"gitdir: \xe9\n")

    assert canonical_git_root(repository) == repository


def test_a_worktree_commondir_that_is_not_utf8_falls_back_to_the_worktree(tmp_path: Path):
    repository = tmp_path / "repo"
    (repository / ".git" / "worktrees" / "wt").mkdir(parents=True)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {repository / '.git' / 'worktrees' / 'wt'}\n")
    (repository / ".git" / "worktrees" / "wt" / "commondir").write_bytes(b"\xe9\n")

    assert canonical_git_root(worktree) == worktree


async def test_both_missing_indexes_still_say_where_memory_is_and_how_to_start_it(tmp_path: Path):
    extension = _extension(tmp_path)
    context = _context()

    await extension.on_state(context)

    (memory,) = _system(context)[1:]
    assert str(extension.personal_directory()) in memory
    assert str(extension.project_directory()) in memory
    assert memory.count("No `MEMORY.md` yet") == 2


async def test_the_two_indexes_are_read_on_every_request(tmp_path: Path):
    extension = _extension(tmp_path)
    extension.personal_directory().mkdir(parents=True)
    (extension.personal_directory() / "MEMORY.md").write_text(
        "# Personal\n\n- [Role](role.md) — data scientist\n", encoding="utf-8"
    )
    extension.project_directory().mkdir(parents=True)
    (extension.project_directory() / "MEMORY.md").write_text(
        "# Project\n\n- [Freeze](freeze.md) — merge freeze\n", encoding="utf-8"
    )
    context = _context()

    await extension.on_state(context)

    memory = _system(context)[-1]
    assert "## Personal index (MEMORY.md)" in memory and "data scientist" in memory
    assert "## Project index (MEMORY.md)" in memory and "merge freeze" in memory


async def test_an_index_that_is_not_utf8_is_a_warning_not_a_failed_request(tmp_path: Path):
    extension = _extension(tmp_path)
    extension.project_directory().mkdir(parents=True)
    (extension.project_directory() / "MEMORY.md").write_bytes(b"# Project\n\n- [Role](role.md) \x97 data scientist\n")
    context = _context()

    await extension.on_state(context)

    memory = _system(context)[-1]
    assert "the index cannot be read" in memory
    assert "It is there but could not be read" in memory


async def test_an_index_over_either_limit_is_cut_with_a_marker(tmp_path: Path):
    extension = _extension(tmp_path)
    extension.project_directory().mkdir(parents=True)
    (extension.project_directory() / "MEMORY.md").write_text(
        "\n".join(f"- line {n}" for n in range(MAX_ENTRYPOINT_LINES + 1))
    )
    context = _context()

    await extension.on_state(context)
    lines = _system(context)[-1]
    assert f"{MAX_ENTRYPOINT_LINES} lines" in lines and "line truncated" not in lines

    (extension.project_directory() / "MEMORY.md").write_text("x" * (MAX_ENTRYPOINT_BYTES + 100))
    second = _context()
    await extension.on_state(second)
    bytes_ = _system(second)[-1]
    assert f"{MAX_ENTRYPOINT_BYTES} bytes" in bytes_


async def test_the_rules_name_the_types_and_what_not_to_store(tmp_path: Path):
    extension = _extension(tmp_path)

    memory = extension.instructions()

    assert "type: user | feedback | project | reference" in memory
    assert "corrections *and* confirmations" in memory
    assert "current task" in memory and "git history" in memory and "logs" in memory
    assert "Write absolute dates" in memory
    assert "If the reader says to ignore memory" in memory


async def test_the_daemon_guide_is_offered_only_when_the_request_can_start_and_reach_one():
    guide = DaemonGuideExtension()
    with_shell = _context("bash", "send_message")
    without_send = _context("bash")
    without_shell = _context("send_message")

    await guide.on_state(with_shell)
    await guide.on_state(without_send)
    await guide.on_state(without_shell)

    message = _system(with_shell)[-1]
    assert "-m zettcode daemon spawn" in message and "send_message" in message
    assert _system(without_send) == ["the project instructions"]
    assert _system(without_shell) == ["the project instructions"]


async def test_both_messages_are_added_after_the_instructions_already_there(tmp_path: Path):
    extension = _extension(tmp_path)
    context = _context("bash", "send_message")

    await extension.on_state(context)
    await DaemonGuideExtension().on_state(context)

    messages = _system(context)
    assert messages[0] == "the project instructions"
    assert "Memory" in messages[1] and "Background agents" in messages[2]
