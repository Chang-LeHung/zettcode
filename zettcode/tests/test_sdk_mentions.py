"""`Client.mentions`: the `@` resources a prompt can carry, as a menu lists them."""

from __future__ import annotations

from pathlib import Path

import pytest

from zettcode.sdk import Client


def build(workspace: Path) -> Client:
    """A client on a workspace of the test's own, with no provider contact."""
    return Client(workspace, models=[{"model": "example", "token": "t"}])


async def test_the_workspaces_files_are_offered_with_their_paths(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "cli.py").write_text("")
    (tmp_path / "README.md").write_text("")
    client = build(tmp_path)
    try:
        found = client.mentions("cli")
        readme = client.mentions("RE")
    finally:
        await client.aclose()

    assert found[0].token == "@src/cli.py" and found[0].kind == "file" and found[0].name == "src/cli.py"
    assert found[0].description.endswith("B"), "the menu line is the file's size"
    assert [mention.name for mention in readme] == ["README.md"], "the query ignores case"


async def test_an_empty_query_lists_what_the_providers_consider_likeliest_and_the_limit_caps_it(tmp_path: Path):
    for name in ("a.py", "b.py", "c.py"):
        (tmp_path / name).write_text("")
    client = build(tmp_path)
    try:
        everything = client.mentions()
        two = client.mentions(limit=2)
    finally:
        await client.aclose()

    assert len(everything) >= 3
    assert len(two) == 2 and two == everything[:2]


async def test_a_limit_that_is_not_a_positive_integer_is_refused(tmp_path: Path):
    client = build(tmp_path)
    try:
        for wrong in (0, -1, True):
            with pytest.raises(ValueError, match="limit"):
                client.mentions(limit=wrong)
    finally:
        await client.aclose()


async def test_a_closed_client_offers_nothing(tmp_path: Path):
    from zettcode.sdk.errors import ClientClosedError

    client = build(tmp_path)
    await client.aclose()

    with pytest.raises(ClientClosedError):
        client.mentions("x")
