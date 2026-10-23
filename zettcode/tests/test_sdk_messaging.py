"""Joining the sessions other ZettCode processes are in: who may reach this client, and what is offered for ``@``."""

from __future__ import annotations

from pathlib import Path

from zettcode.broker.client import Receipt
from zettcode.sdk import Client


def build(workspace: Path, **settings: object) -> Client:
    """A client on a workspace of the test's own, with no provider contact."""
    return Client(workspace, models=[{"model": "example", "token": "t"}], **settings)


async def test_a_client_that_did_not_switch_sessions_on_joins_nothing(tmp_path: Path):
    """An embedding program is not a session unless it asks to be: no broker, and nobody can address it."""
    client = build(tmp_path)
    try:
        assert await client.join_sessions(lambda message: Receipt(True)) is False
    finally:
        await client.aclose()
