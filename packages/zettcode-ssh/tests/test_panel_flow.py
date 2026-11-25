"""The panel's drafts, refusals, apply and cancel; a connection is checked before it is applied."""

from __future__ import annotations

import asyncio

import pytest

from zettcode.plugin_api import PasteEvent, ShellPolicy, TextEvent
from zettcode.ssh.panel import SSHPage
from zettcode.ssh.transport import Target, Transport


async def test_panel_edits_apply_and_cancel():
    applied, closed = [], []

    async def apply(target, password):
        applied.append((target, password))

    host = type("Host", (), {"invalidate": staticmethod(lambda: None)})()
    page = SSHPage(target=None, status=lambda: "off", on_apply=apply, on_close=lambda: closed.append(True))
    page.handle(TextEvent(text="alias"), host)
    page.mark = 1
    page.handle(PasteEvent(text="relative"), host)
    page.mark = 5  # Connect
    page.confirm(host)
    assert page.error and not applied and not closed
    page.values[1] = "/remote"
    page.confirm(host)
    await page.pending
    assert applied == [(Target("alias", "/remote"), "")] and closed == [True]

    gate = asyncio.Event()

    async def blocking(target, password):
        await gate.wait()
        applied.append((target, password))

    page = SSHPage(target=None, status=lambda: "off", on_apply=blocking, on_close=lambda: closed.append(True))
    page.values = ["alias", "/other", ""]
    page.mark = 5
    page.confirm(host)
    await asyncio.sleep(0)
    page.pending.cancel()
    await page.pending
    assert "Cancelled" in page.error and len(applied) == 1


async def test_permissions_refuse_a_password_target_before_spawning(monkeypatch):
    async def forbidden(*args, **kwargs):
        pytest.fail("No SSH process may run below full permission")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    target = Target("alias", "/remote", auth="password")
    transport = Transport(target, password="s3cret")
    from zettcode.ssh.plugin import RemoteTools

    tools = RemoteTools(target, ShellPolicy(), "coding", transport)
    with pytest.raises(PermissionError):
        await tools.invoke("read_file", {"file_path": "file"})
    await transport.aclose()
