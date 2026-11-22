"""Retained-output reads cannot become arbitrary local workspace reads."""

from types import SimpleNamespace

import pytest
from zett_agent.messages import ToolCall

from zettcode.engine.storage import SessionStore
from zettcode.truncation.extension import LongOutputExtension


async def test_bounded_session_reader_and_remote_independence(tmp_path):
    store = SessionStore(tmp_path / "store", tmp_path)
    extension = LongOutputExtension(store)
    path = extension._write("".join(f"line {n}\n" for n in range(1, 3001)), ToolCall("id", "grep", {}), "one")
    tools = {}
    context = SimpleNamespace(
        config=SimpleNamespace(session_id="one"), register_tool=lambda tool: tools.update({tool.name: tool})
    )
    await extension.on_tool(context)
    result = await tools["read_tool_output"].handler(file_path=str(path), offset=2500, limit=2)
    assert "2500\tline 2500" in result and "2501\tline 2501" in result
    assert "offset=2502" in result
    resumed = LongOutputExtension(store)
    assert "line 2500" in resumed._read("one", str(path), 2500, 2)
    alias = tmp_path / "store-alias"
    alias.symlink_to(tmp_path / "store", target_is_directory=True)
    aliased_store = SessionStore(alias, tmp_path)
    assert "line 2500" in LongOutputExtension(aliased_store)._read("one", str(path), 2500, 2)
    await aliased_store.close()
    with pytest.raises(ValueError, match="this session"):
        extension._read("other", str(path), 1, 2)
    local = tmp_path / "private"
    local.write_text("secret", encoding="utf-8")
    with pytest.raises(ValueError, match="this session"):
        extension._read("one", str(local), 1, 2)
    shell = path.parent / "shell-test"
    shell.mkdir()
    stream = shell / "stdout.txt"
    stream.write_text("retained shell output\n", encoding="utf-8")
    assert "retained shell output" in resumed._read("one", str(stream), 1, 2)
    with pytest.raises(ValueError, match="this session"):
        resumed._read("one", str(shell / "private.txt"), 1, 2)
    nested = shell / "sub"
    nested.mkdir()
    with pytest.raises(ValueError, match="this session"):
        resumed._read("one", str(nested / "stdout.txt"), 1, 2)
    linked = path.parent / "shell-link"
    linked.symlink_to(shell, target_is_directory=True)
    with pytest.raises(ValueError, match="this session"):
        resumed._read("one", str(linked / "stdout.txt"), 1, 2)
    stream.unlink()
    stream.symlink_to(local)
    with pytest.raises(ValueError, match="this session"):
        resumed._read("one", str(stream), 1, 2)
    path.unlink()
    path.symlink_to(local)
    with pytest.raises(ValueError, match="this session"):
        extension._read("one", str(path), 1, 2)
    await store.close()
