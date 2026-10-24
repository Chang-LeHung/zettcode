"""Render every component of the interface in every candidate palette into one HTML page.

Run from the repository root::

    make palettes                                            # writes docs/internal/palettes.html (ignored by git)
    uv run python docs/scripts/palette_gallery.py --list     # the palettes and scenes it knows
    uv run python docs/scripts/palette_gallery.py --png /tmp/shot.png --scene shell --palette nord

Nothing here is drawn by hand. Each scene is the real widget tree, laid out and painted by the same code the program
runs, once per palette, and the cells it painted (glyph, colours, weight) are written into the page. So what the
page shows is what a terminal would show, including the colours the program *computes* (the effort gauge and the
header's light blend theme colours at paint time, which CSS variables could not reproduce). The page itself is a
single self-contained file: no network, no fonts to download.

No model is started, no network is used, and every session file stays in a temporary directory.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from html import escape
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from palette_data import NOTES, Palette, palettes  # noqa: E402

from zettcode.app.agent.agent import ZettCodeAgent  # noqa: E402
from zettcode.app.agent.conversation.entries import EntryStatus  # noqa: E402
from zettcode.app.agent.runtime import ZettCodeEngine  # noqa: E402
from zettcode.app.ui import app as app_module  # noqa: E402
from zettcode.app.ui.app import ZettCodeApp  # noqa: E402
from zettcode.app.ui.labels import header_left  # noqa: E402
from zettcode.app.ui.shell import PAGE_SCREEN  # noqa: E402
from zettcode.app.ui.widgets import (  # noqa: E402
    EFFORT_ROWS,
    SELF_COMPACT_ROWS,
    EffortPage,
    SelfCompactPage,
    bottom_panel,
)
from zettcode.config import ModelConfig, ZettCodeConfig  # noqa: E402
from zettcode.engine.relay import Relayed  # noqa: E402
from zettcode.plugins.builtins import BUILTIN_PLUGINS, ShellRows  # noqa: E402
from zettcode.plugins.loader import load_plugins  # noqa: E402
from zettcode.tui import Canvas, Screen, Theme, TuiApp  # noqa: E402
from zettcode.tui.gallery import GALLERY, render_entry  # noqa: E402
from zettcode.tui.testing import Harness  # noqa: E402

WIDTH = 104
OUTPUT = Path("docs/internal/palettes.html")


# -- the environment every app scene runs in ---------------------------------------------------------------------


class PreviewRows(ShellRows):
    """The real header, but naming an illustrative project instead of a temporary directory."""

    def render_header_left(self, context) -> str:
        return header_left(Path("~/projects/api"), context.session.name, context.session.handle).text()


def preview_plugins() -> tuple[object, ...]:
    """Every built-in plugin, with the illustrative header rows in place of the shell's own."""
    return (PreviewRows(), *(plugin for plugin in BUILTIN_PLUGINS if plugin.name != "shell"))


class Env:
    """A throwaway runtime and store, shared by every scene, and a clock that stands still."""

    now = 0.0

    def __init__(self) -> None:
        self._directory = tempfile.TemporaryDirectory(prefix="zettcode-palettes-")
        self._previous = Path.cwd()
        workspace = Path(self._directory.name) / "api"
        workspace.mkdir()
        config = ZettCodeConfig(
            workspace=workspace,
            store=Path(self._directory.name) / "sessions",
            models=(
                ModelConfig(model="gpt-5-mini", display_model="gpt-5-mini", token="x"),
                ModelConfig(model="claude-sonnet-4-5", display_model="Claude Sonnet 4.5", token="x"),
                ModelConfig(model="deepseek-chat", display_model="DeepSeek Chat", token="x"),
            ),
            plugins_enabled=False,
            skills_enabled=False,
            mcp_enabled=False,
        )
        self.runtime = ZettCodeEngine.preview(config)
        self.runtime.plugins = load_plugins(config, builtins=preview_plugins())
        self.workspace = workspace

    def close(self) -> None:
        os.chdir(self._previous)
        self.runtime.session_locks.release()
        self._directory.cleanup()

    def app(self, theme: Theme, width: int = WIDTH, height: int = 40) -> ZettCodeApp:
        """A fresh shell, painted in ``theme``, at a fixed size, with the clock the animations read held still."""
        shell = ZettCodeApp(ZettCodeAgent(self.runtime), theme=theme, auto_theme=False)
        shell.transcript.clock = lambda: self.now
        shell.app.resize(width, height)
        shell.app.mount()
        shell._session_title = "Pagination for /users"
        return shell


def page(shell: ZettCodeApp, widget, rows: int) -> None:
    """Put a panel over the conversation the way the shell does."""
    shell.app.push_screen(Screen(bottom_panel(widget, rows=rows), name=PAGE_SCREEN, modal=True))
    shell.app.request_layout()


def crop(canvas: Canvas, rows: slice) -> Canvas:
    """Return some rows of a canvas as a canvas of their own."""
    kept = canvas.cells[rows]
    out = Canvas(canvas.width, len(kept))
    out.cells = [list(row) for row in kept]
    return out


def stack(*canvases: Canvas, gap: int = 1) -> Canvas:
    """Put canvases one above the other, with ``gap`` blank rows between."""
    width = max(item.width for item in canvases)
    height = sum(item.height for item in canvases) + gap * (len(canvases) - 1)
    out = Canvas(width, height)
    y = 0
    for item in canvases:
        for row in item.cells:
            for x, cell in enumerate(row):
                out.cells[y][x] = cell
            y += 1
        y += gap
    return out


# -- scenes -----------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Scene:
    id: str
    group: str
    title: str
    note: str
    build: Callable[[Env, Theme], Canvas]


EDITS = [
    {
        "old_text": "def list_users(db):\n    return db.query(User).all()",
        "new_text": "def list_users(db, limit: int = 20, offset: int = 0):\n    limit = min(limit, MAX_LIMIT)\n    return db.query(User).offset(offset).limit(limit).all()",
    }
]
NEW_TEST = (
    "def test_pagination_caps_the_limit(client):\n"
    "    response = client.get('/users?limit=500')\n"
    "    assert response.status_code == 200\n"
    "    assert len(response.json()['items']) <= 100\n"
)
ANSWER = (
    "Added pagination to **GET /users**.\n\n"
    "## What changed\n\n"
    "- `limit` defaults to 20 and is capped at 100.\n"
    "- `offset` starts at 0; both parameters are validated.\n"
    "- The response includes the total, so clients can page without counting.\n\n"
    "> The cap lives in `MAX_LIMIT`, so a deployment can lower it without touching the handler.\n\n"
    "```python\n"
    "def list_users(db, limit: int = 20, offset: int = 0):\n"
    "    limit = min(limit, MAX_LIMIT)\n"
    "    return db.query(User).offset(offset).limit(limit).all()\n"
    "```\n\n"
    "All six tests pass, including the new pagination checks. See [the API notes](https://example.com/api)."
)


def conversation(env: Env, theme: Theme, *, finished: bool = True) -> ZettCodeApp:
    shell = env.app(theme, height=84)
    transcript = shell.transcript
    transcript.begin_turn("Add limit/offset pagination to GET /users, cap it at 100, and cover it with a test.")
    transcript.start_thinking()
    transcript.append_thinking(
        "I'll look at the route and the existing tests first, then add validated pagination.\n\n"
        "The cap should be a constant so a deployment can change it."
    )
    env.now += 1.4
    transcript.complete_thinking()
    calls = (
        ("c1", "read_file", {"path": "src/api/users.py"}, "def list_users(db): ..."),
        ("c2", "grep", {"pattern": "list_users", "path": "src"}, "src/api/users.py:12\nsrc/api/routes.py:40"),
        ("c3", "glob", {"pattern": "tests/**/test_users*.py"}, "tests/test_users.py"),
        ("c4", "view_image", {"path": "docs/schema.png"}, "image 1280x720"),
        ("c5", "edit", {"path": "src/api/users.py", "edits": EDITS}, "Edited src/api/users.py"),
        ("c6", "write_file", {"path": "tests/test_pagination.py", "content": NEW_TEST}, "wrote 4 lines"),
        ("c7", "delete_file", {"path": "tests/old_fixture.py"}, "deleted"),
        (
            "c8",
            "todo_write",
            {
                "todos": [
                    {"content": "Add limit and offset", "status": "completed"},
                    {"content": "Cap the limit at 100", "status": "completed"},
                    {"content": "Cover it with a test", "status": "in_progress"},
                ]
            },
            "ok",
        ),
        ("c9", "task", {"description": "Check other callers of list_users"}, "No other callers."),
        ("c10", "bash", {"command": "pytest tests/test_users.py -q"}, "......\n6 passed in 0.24s"),
        ("c11", "send_message", {"to": "docs", "message": "the /users endpoint is paginated now"}, "Delivered."),
    )
    for call_id, tool, arguments, output in calls:
        transcript.start_tool(call_id, tool, arguments)
        env.now += 0.8
        transcript.complete_tool(call_id, output, wait=False)
    transcript.start_tool("c12", "bash", {"command": "pytest tests/test_flaky.py -q"})
    env.now += 1.1
    transcript.complete_tool("c12", "E   AssertionError: expected 200, got 500", status=EntryStatus.FAILED, wait=False)
    transcript.append_answer(ANSWER)
    if finished:
        transcript.summarize_changes(env.workspace)
        transcript.settle_wait("Processed for 14s · 09:41")
    return shell


def shell_scene(env: Env, theme: Theme) -> Canvas:
    return conversation(env, theme).app.render()


def working_scene(env: Env, theme: Theme) -> Canvas:
    shell = env.app(theme, height=24)
    transcript = shell.transcript
    transcript.begin_turn("Refactor the session store so it never writes an empty session.")
    transcript.start_thinking()
    transcript.append_thinking("The lock file is created before any message exists, so the folder has to be tidied.")
    transcript.start_tool("w1", "bash", {"command": "pytest -q tests/test_session_locks.py"})
    transcript.wait_for_model()
    shell._set_busy(True)
    shell._queue_steering("stop editing and explain the diff first")
    shell.composer.set_text("and open a pull request when it passes")
    return shell.app.render()


def locked_scene(env: Env, theme: Theme) -> Canvas:
    shell = env.app(theme, height=14)
    shell.transcript.notice(
        "This session is open in another ZettCode process, so it is read-only here. "
        "It unlocks by itself when that one lets go; /new starts a new session, /fork carries this conversation into one."
    )
    shell.composer.locked = True
    return shell.app.render()


def messages_scene(env: Env, theme: Theme) -> Canvas:
    shell = env.app(theme, height=56)
    transcript = shell.transcript
    transcript.notice("Resumed session 01a145fa · 14 messages")
    transcript.begin_turn("What does the lock file do?")
    transcript.append_answer(
        "It records which process has the session open, so two terminals never write to one session."
    )
    transcript.begin_turn("btw, which tests cover it?", side=True)
    transcript.append_answer("`tests/test_session_locks.py` and `tests/test_session_lock_runtime.py`.")
    transcript.relayed_message(Relayed("peer-1", "docs", "can you tell me the new default page size?", via="agent"))
    transcript.sent_message("docs", "it is 20, capped at 100")
    transcript.model_changed("gpt-5-mini", "Claude Sonnet 4.5")
    transcript.effort_changed("high", "xhigh")
    transcript.permission_changed("ask", "safe")
    transcript.error("error: connection reset by peer — try /continue")
    transcript.announce("Compacted 38 messages into a summary")
    transcript.settle_wait("Processed for 3s · 09:40")
    return shell.app.render()


def completion_scene(env: Env, theme: Theme) -> Canvas:
    shell = env.app(theme, height=22)
    shell.transcript.notice("Type / to see the commands")
    Harness(app=shell.app).write("/")
    return shell.app.render()


def effort_scene(env: Env, theme: Theme, level: str = "high") -> Canvas:
    shell = env.app(theme, height=18)
    shell.transcript.notice("Reasoning effort is medium")
    levels = shell.agent.efforts
    panel = EffortPage(levels, "medium", on_select=lambda _: None, on_cancel=lambda: None)
    page(shell, panel, EFFORT_ROWS)
    panel.choose(levels.index(level))
    panel._set_off -= 5  # the slide is over
    shell.app.tick()
    return shell.app.render()


def self_compact_scene(env: Env, theme: Theme) -> Canvas:
    shell = env.app(theme, height=18)
    shell.transcript.notice("Self-compaction is off: this session follows the default (off)")
    panel = SelfCompactPage(None, False, on_apply=lambda *_: None, on_cancel=lambda: None)
    page(shell, panel, SELF_COMPACT_ROWS)
    panel.choose(0, 2)  # this session: on, not applied yet
    panel.session_rail.set_off -= 5  # the slide is over
    shell.app.tick()
    return shell.app.render()


def header(env: Env, theme: Theme, level: str, progress: float | None) -> Canvas:
    """The header row, with an effort switch to ``level`` ``progress`` of the way through its animation."""
    from zettcode.app.agent.conversation.effort_gauge import EFFORT_SECONDS
    from zettcode.app.agent.conversation.shimmer import SHIMMER_LEVELS, shimmer_seconds

    shell = env.app(theme, height=6)
    started = 1000.0
    with mock.patch.object(app_module, "monotonic", lambda: started + elapsed[0]):
        elapsed = [0.0]
        if progress is not None:
            shell._effort_animation = ("medium", level, started)
            seconds = shimmer_seconds(level, shell.app.width) if level in SHIMMER_LEVELS else EFFORT_SECONDS
            elapsed[0] = seconds * progress
        canvas = shell.app.render()
    return crop(canvas, slice(0, 1))


def header_scene(level: str, frames: tuple[float | None, ...]) -> Callable[[Env, Theme], Canvas]:
    def build(env: Env, theme: Theme) -> Canvas:
        return stack(*(header(env, theme, level, progress) for progress in frames), gap=1)

    return build


def sessions_scene(env: Env, theme: Theme) -> Canvas:
    from zettcode.app.agent.storage import SessionInfo
    from zettcode.app.ui.widgets import SessionsPage

    shell = env.app(theme, height=16)
    now = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)
    rows = [
        SessionInfo("01a145fa-873c-73c2", "Fix the parser crash", now - timedelta(days=1), now - timedelta(minutes=3)),
        SessionInfo("01a1210a-0d15-73a5", "Pagination for /users", now - timedelta(days=1), now - timedelta(hours=5)),
        SessionInfo("01a10b75-aaaa-7000", None, now - timedelta(days=3), now - timedelta(days=2)),
    ]
    page(shell, SessionsPage(rows, on_select=lambda _: None, on_cancel=lambda: None, now=now), 9)
    return shell.app.render()


def models_scene(env: Env, theme: Theme) -> Canvas:
    from zettcode.app.ui.widgets import ModelPage

    shell = env.app(theme, height=16)
    page(shell, ModelPage(shell.agent, on_select=lambda _: None, on_cancel=lambda: None), 9)
    return shell.app.render()


def approval_scene(env: Env, theme: Theme) -> Canvas:
    from zettcode.app.ui.widgets import ApprovalPage

    shell = env.app(theme, height=24)
    page(shell, ApprovalPage("rm -rf build/ && python -m build", on_choice=lambda _: None), 15)
    return shell.app.render()


def ask_scene(env: Env, theme: Theme) -> Canvas:
    from zettcode.app.agent.dialogue.ask import AskUserQuestion
    from zettcode.app.ui.widgets import AskUserPage

    shell = env.app(theme, height=14)
    question = AskUserQuestion(
        "s", "c", "Which format should I write the summary in?", ("Markdown", "Plain text", "JSON")
    )
    page(shell, AskUserPage(question, on_answer=lambda _: None, on_cancel=lambda: None), 8)
    return shell.app.render()


def input_scene(env: Env, theme: Theme) -> Canvas:
    from zettcode.app.ui.widgets import InputPage

    shell = env.app(theme, height=14)
    widget = InputPage(
        "Token for DeepSeek",
        on_submit=lambda _: None,
        on_cancel=lambda: None,
        help_lines=("The key from platform.deepseek.com; it is written to ~/.zettcode/config.toml.",),
        secret=True,
        initial="sk-live-123456",
    )
    page(shell, widget, 7)
    return shell.app.render()


def update_scene(env: Env, theme: Theme) -> Canvas:
    from zettcode.app.ui.widgets import UpdatePage

    shell = env.app(theme, height=14)
    page(shell, UpdatePage("0.2.0", "0.1.9", ("uv", "tool", "upgrade", "zettcode"), on_choice=lambda _: None), 8)
    return shell.app.render()


def send_kind_scene(env: Env, theme: Theme) -> Canvas:
    from zettcode.app.ui.widgets import SEND_KIND_ROWS, SendKindPage

    shell = env.app(theme, height=14)
    widget = SendKindPage("and open a pull request", on_choice=lambda _: None, on_cancel=lambda: None)
    page(shell, widget, SEND_KIND_ROWS)
    return shell.app.render()


def context_scene(env: Env, theme: Theme) -> Canvas:
    from zettcode.app.agent.extensions.context import ContextReport, ContextShare
    from zettcode.app.ui.widgets import ContextPage

    shares = tuple(
        ContextShare(name, tokens, items)
        for name, tokens, items in (
            ("System prompt", 260, 1),
            ("Environment notes", 740, 2),
            ("Tool schemas", 1520, 9),
            ("User messages", 90, 3),
            ("Assistant messages", 3100, 12),
            ("Tool output", 20216, 17),
        )
    )
    shell = env.app(theme, height=34)
    report = ContextReport(window=200000, measured_by="tiktoken cl100k_base", shares=shares, reported=28400)
    widget = ContextPage(
        report,
        path=Path("~/.zettcode/sessions/-Users-me-api/01a1/data.jsonl"),
        model="claude-opus-4-5",
        trigger=160000,
    )
    shell.app.push_screen(Screen(widget, name=PAGE_SCREEN, modal=True))
    shell.app.request_layout()
    return shell.app.render()


def usage_scene(tab: str) -> Callable[[Env, Theme], Canvas]:
    def build(env: Env, theme: Theme) -> Canvas:
        from zettcode.app.agent.storage.ledger import Ledger, SessionUsage, Tally
        from zettcode.app.ui.widgets import UsagePage

        today = date(2026, 10, 17)
        days = {
            today - timedelta(days=n): Tally(1 + n % 3, 40_000 * (1 + (n * 7) % 5), 4_000 * (1 + n % 4))
            for n in range(0, 80, 2)
        }
        started = datetime(2026, 10, 16, 9, tzinfo=timezone.utc)
        ledger = Ledger(
            sessions=[
                SessionUsage(
                    "01a145fa-873c",
                    "Fix the parser crash",
                    started,
                    started + timedelta(hours=3),
                    Tally(12, 900_000, 60_000, 800_000),
                    ("gpt-5-mini",),
                ),
                SessionUsage(
                    "01a1210a-0d15",
                    "Pagination for /users",
                    started - timedelta(days=2),
                    started - timedelta(days=2, hours=-1),
                    Tally(9, 700_000, 40_000, 300_000),
                    ("claude-sonnet-4-5",),
                ),
            ],
            models={"gpt-5-mini": Tally(30, 2_000_000, 120_000), "claude-sonnet-4-5": Tally(9, 700_000, 40_000)},
            days=days,
            total=Tally(40, 2_700_000, 160_000, 1_100_000),
        )
        shell = env.app(theme, height=26)
        page(shell, UsagePage(ledger, workspace="~/projects/api", today=today, tab=tab), 20)
        return shell.app.render()

    return build


def notifications_scene(env: Env, theme: Theme) -> Canvas:
    from zettcode.tui import Slot, Toast, VBox

    items = [Toast("saved to disk", level=level) for level in ("info", "success", "warning", "error")]
    tui = TuiApp(VBox([Slot(item, size=3) for item in items]), width=44, height=12, theme=theme)
    tui.mount()
    toasts = tui.render()
    shell = env.app(theme, height=9)
    shell.flash("copied 214 chars to clipboard", level="success")
    return stack(toasts, shell.app.render())


def code_scene(env: Env, theme: Theme) -> Canvas:
    from zettcode.tui import MarkdownView

    source = (
        "### Syntax\n\n"
        "```python\n"
        '@dataclass\nclass Palette:\n    name: str = "mocha"  # a comment\n\n'
        "    def mix(self, a, b, t=0.5):\n        return len([x for x in (a, b) if x]) + 3.14 * t\n"
        "```\n\n"
        '```bash\n$ export TOKEN="abc" && git status --short | wc -l  # count\n```\n\n'
        '```json\n{"theme": "dark", "size": 12, "ok": true, "tags": ["a", "b"]}\n```\n\n'
        "Inline `code`, **bold**, *italic*, ~~strike~~ and a [link](https://example.com).\n\n"
        "1. first\n2. second\n\n- bullet\n  - nested\n"
    )
    tui = TuiApp(MarkdownView(source, follow_tail=False), width=72, height=34, theme=theme)
    tui.mount()
    return tui.render()


def gallery_scene(entry) -> Callable[[Env, Theme], Canvas]:
    return lambda env, theme: render_entry(entry, theme=theme)


def scenes() -> list[Scene]:
    chosen = [
        Scene(
            "shell",
            "整体界面",
            "完整对话",
            "标题栏、用户消息、思考、所有种类的工具行（读/搜/改/写/删/命令/计划/子代理/发消息/失败）、diff、Markdown 回答、改动汇总、输入框、状态栏。",
            shell_scene,
        ),
        Scene(
            "working",
            "整体界面",
            "请求进行中",
            "正在思考、命令在跑、等待行、排队的 steering 消息、输入框里有草稿。",
            working_scene,
        ),
        Scene(
            "locked",
            "整体界面",
            "会话被另一个进程占用",
            "输入框只读：半块绘制的挂锁和一句说明，不再用彩色 emoji。",
            locked_scene,
        ),
        Scene(
            "messages",
            "整体界面",
            "各类消息",
            "通知、用户消息、旁路提问(/btw)、来自其他会话的消息(peer)、发出的消息、模型/档位/权限变更、错误、压缩提示。",
            messages_scene,
        ),
        Scene("completion", "整体界面", "命令补全菜单", "输入 / 之后的补全弹窗：选中行、说明文字。", completion_scene),
        Scene(
            "header-gauge",
            "标题栏动画",
            "档位切换 (普通)",
            "medium → xhigh，动画的几个瞬间（从上到下：切换前、中、后）。",
            header_scene("xhigh", (None, 0.25, 0.55, 0.8)),
        ),
        Scene(
            "header-max",
            "标题栏动画",
            "切到 max",
            "从右到左的扫光，几个瞬间。",
            header_scene("max", (0.08, 0.2, 0.35, 0.6, 0.85)),
        ),
        Scene(
            "header-ultra",
            "标题栏动画",
            "切到 ultra",
            "扫光 + 碎光闪烁 + 渐变到错误色。",
            header_scene("ultra", (0.08, 0.2, 0.35, 0.6, 0.85)),
        ),
        Scene(
            "effort", "面板", "/effort 轨道旋钮", "旋钮落在 high：已点亮的轨道、经过的节点、“now” 标记。", effort_scene
        ),
        Scene(
            "self-compact",
            "面板",
            "/self-compact 双轨道",
            "上轨道是本会话（default / off / on），下轨道是全局默认；旋钮在 on，标题右侧说明“未应用”。",
            self_compact_scene,
        ),
        Scene("models", "面板", "/model 选择器", "带编号的列表、当前项、选中行。", models_scene),
        Scene("sessions", "面板", "/resume 会话列表", "标题、相对时间、短 id；未命名会话。", sessions_scene),
        Scene("approval", "面板", "命令审批", "执行 shell 命令前的确认面板。", approval_scene),
        Scene("ask", "面板", "模型提问", "模型向你提问时的单选面板。", ask_scene),
        Scene("input", "面板", "输入面板 (密钥)", "密码样式的输入、帮助行。", input_scene),
        Scene("update", "面板", "升级提示", "有新版本时的面板。", update_scene),
        Scene("send-kind", "面板", "排队 / 插话选择", "请求进行中发送消息时问你：追加还是插话。", send_kind_scene),
        Scene("context", "面板", "/context 上下文占用", "窗口计量条、各来源的堆叠条和占比。", context_scene),
        Scene("usage-models", "面板", "/usage · Models", "按模型的用量条。", usage_scene("Models")),
        Scene("usage-sessions", "面板", "/usage · Sessions", "按会话的用量。", usage_scene("Sessions")),
        Scene("usage-calendar", "面板", "/usage · Calendar", "日历热力图（深浅）。", usage_scene("Calendar")),
        Scene(
            "notifications",
            "提示",
            "Toast 与复制提示",
            "info / success / warning / error 四种 toast，以及复制成功的胶囊提示。",
            notifications_scene,
        ),
        Scene(
            "code",
            "代码与 Markdown",
            "语法高亮 + Markdown",
            "关键字、字符串、注释、数字、函数、内建、行内代码、粗斜体、链接、列表。",
            code_scene,
        ),
    ]
    for entry in GALLERY:
        chosen.append(Scene(f"w-{entry.name}", "框架组件", entry.name, entry.summary, gallery_scene(entry)))
    return chosen


# -- encoding ----------------------------------------------------------------------------------------------------

FLAGS = {"bold": 1, "italic": 2, "dim": 4, "strike": 8}


def _wide(glyph: str) -> bool:
    return len(glyph) > 1 or ord(glyph[0]) > 0x2E7F


def encode(canvas: Canvas, colours: dict[str, int]) -> list[list[list[object]]]:
    """Turn a painted canvas into rows of runs: ``[text, foreground, background, flags, cells]``.

    Colours are indexes into the palette's table (``-1`` for the terminal default), so a colour that appears
    thousands of times is written once. A run is a stretch of cells with one style; its width in cells is
    written down, because the page lays each run out in that many columns whatever the browser's font does
    with a wide or unusual glyph.
    """

    def index(colour: str | None) -> int:
        if colour is None:
            return -1
        return colours.setdefault(colour, len(colours))

    rows: list[list[list[object]]] = []
    for row in canvas.cells:
        runs: list[list[object]] = []
        for cell in row:
            if cell.continuation:
                if runs:
                    runs[-1][4] = int(runs[-1][4]) + 1  # type: ignore[call-overload]
                continue
            style = cell.style
            foreground, background = style.foreground, style.background
            if style.reverse:
                foreground, background = background, foreground
            key = [
                index(foreground),
                index(background),
                sum(bit for name, bit in FLAGS.items() if getattr(style, name)),
            ]
            glyph = cell.character or " "
            last = runs[-1] if runs else None
            if last is not None and last[1:4] == key and not _wide(glyph) and last[4] == len(str(last[0])):
                last[0] = str(last[0]) + glyph
                last[4] = int(last[4]) + 1  # type: ignore[call-overload]
            else:
                runs.append([glyph, *key, 1])
        rows.append(runs)
    return rows


def theme_json(palette: Palette) -> dict[str, object]:
    theme = palette.theme
    roles = {
        "background": theme.background,
        "surface": theme.surface,
        "surface_alt": theme.surface_alt,
        "surface_side": theme.surface_side,
        "surface_peer": theme.surface_peer,
        "text": theme.text,
        "subtle": theme.subtle,
        "muted": theme.muted,
        "accent": theme.accent,
        "accent_bright": theme.accent_bright,
        "warning": theme.warning,
        "error": theme.error,
        "diff_added": theme.addition,
        "diff_removed": theme.deletion,
        "border": theme.border,
        "selection": theme.selection,
    }
    tools = {
        n: getattr(theme.tools, n)
        for n in ("read", "search", "image", "write", "delete", "shell", "plan", "subagent", "message")
    }
    code = {
        n: getattr(theme.code, n)
        for n in ("keyword", "string", "comment", "number", "function", "builtin", "operator", "punctuator", "inline")
    }
    return {"roles": roles, "tools": tools, "code": code}


def toml_of(palette: Palette) -> str:
    """The palette as a theme file: drop it in ``~/.zettcode/themes/<name>.toml`` and ``/theme <name>`` picks it.

    The same text is what ships in ``zettcode/src/zettcode/tui/themes/`` (see ``--export-themes``), so the page's copy
    button and the program's built-in palette cannot differ.
    """
    theme = palette.theme
    lines = [
        f'description = "{NOTES.get(palette.key, palette.label)}"',
        f'base = "{"dark" if palette.dark else "light"}"',
        "",
        "[ui]",
        f'background = "{theme.background}"',
    ]
    for name in (
        "surface",
        "surface_alt",
        "surface_side",
        "surface_peer",
        "text",
        "muted",
        "subtle",
        "accent",
        "accent_bright",
        "warning",
        "error",
        "border",
        "focus",
        "selection",
    ):
        lines.append(f'{name} = "{getattr(theme, name)}"')
    lines += [f'diff_added = "{theme.addition}"', f'diff_removed = "{theme.deletion}"', "", "[tools]"]
    lines += [
        f'{n} = "{getattr(theme.tools, n)}"'
        for n in ("read", "search", "image", "write", "delete", "shell", "plan", "subagent", "message")
    ]
    lines += ["", "[code]"]
    lines += [
        f'{n} = "{getattr(theme.code, n)}"'
        for n in (
            "inline",
            "text",
            "keyword",
            "string",
            "comment",
            "number",
            "function",
            "builtin",
            "operator",
            "punctuator",
        )
    ]
    return "\n".join(lines) + "\n"


def build_data(only_palettes: set[str] | None = None, only_scenes: set[str] | None = None) -> dict[str, object]:
    env = Env()
    try:
        chosen = [scene for scene in scenes() if not only_scenes or scene.id in only_scenes]
        out_palettes = []
        for palette in palettes():
            if only_palettes and palette.key not in only_palettes:
                continue
            colours: dict[str, int] = {}
            rendered: dict[str, object] = {}
            for scene in chosen:
                env.now = 0.0
                canvas = scene.build(env, palette.theme)
                rendered[scene.id] = {"w": canvas.width, "h": canvas.height, "rows": encode(canvas, colours)}
            out_palettes.append(
                {
                    "key": palette.key,
                    "label": palette.label,
                    "mood": palette.mood,
                    "dark": palette.dark,
                    "bg": palette.theme.background,
                    "text": palette.theme.text,
                    "colours": [colour for colour, _ in sorted(colours.items(), key=lambda item: item[1])],
                    "theme": theme_json(palette),
                    "tuned": {role: list(pair) for role, pair in palette.tuned.items()},
                    "toml": toml_of(palette),
                    "scenes": rendered,
                }
            )
            print(f"  {palette.key}: {len(colours)} colours", file=sys.stderr)
        return {
            "scenes": [{"id": s.id, "group": s.group, "title": s.title, "note": s.note} for s in chosen],
            "palettes": out_palettes,
        }
    finally:
        env.close()


# -- the page ----------------------------------------------------------------------------------------------------


def write_html(data: dict[str, object], path: Path) -> None:
    template = (Path(__file__).parent / "palette_gallery.html").read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(template.replace("/*__DATA__*/null", payload), encoding="utf-8")


def png(data: dict[str, object], scene_id: str, palette_key: str, target: Path) -> None:
    """Draw one scene as a PNG, for looking at while the scenes are being built (needs ``rsvg-convert``)."""
    palette = next(item for item in data["palettes"] if item["key"] == palette_key)  # type: ignore[attr-defined,index]
    shot = palette["scenes"][scene_id]
    table = palette["colours"]
    cell_w, cell_h = 9, 18
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{shot["w"] * cell_w}" height="{shot["h"] * cell_h}">',
        f'<rect width="100%" height="100%" fill="{palette["bg"]}"/>',
        '<g font-family="Menlo,monospace" font-size="14" xml:space="preserve">',
    ]
    for y, row in enumerate(shot["rows"]):
        x = 0
        for text, fg, bg, flags, cells in row:
            if bg >= 0:
                parts.append(
                    f'<rect x="{x * cell_w}" y="{y * cell_h}" width="{cells * cell_w}" height="{cell_h}" fill="{table[bg]}"/>'
                )
            if text.strip():
                colour = table[fg] if fg >= 0 else palette["text"]
                weight = ' font-weight="bold"' if flags & 1 else ""
                parts.append(
                    f'<text x="{x * cell_w}" y="{y * cell_h + 14}" fill="{colour}"{weight}>{escape(text)}</text>'
                )
            x += cells
    parts.append("</g></svg>")
    svg = target.with_suffix(".svg")
    svg.write_text("\n".join(parts), encoding="utf-8")
    subprocess.run([shutil.which("rsvg-convert") or "rsvg-convert", "-o", str(target), str(svg)], check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--list", action="store_true", help="print the palettes and scenes and exit")
    parser.add_argument("--palette", action="append", help="only these palettes (repeatable)")
    parser.add_argument("--scene", action="append", help="only these scenes (repeatable)")
    parser.add_argument("--png", type=Path, help="write the first chosen scene of the first chosen palette as a PNG")
    parser.add_argument(
        "--export-themes",
        type=Path,
        metavar="DIR",
        help="write each candidate as <name>.toml into DIR (zettcode/src/zettcode/tui/themes is where the shipped ones live)",
    )
    args = parser.parse_args()
    if args.export_themes:
        args.export_themes.mkdir(parents=True, exist_ok=True)
        for palette in palettes():
            if palette.key in ("dark", "light"):
                continue
            (args.export_themes / f"{palette.key}.toml").write_text(toml_of(palette), encoding="utf-8")
        print(f"wrote {len(palettes()) - 2} themes to {args.export_themes}")
        return
    if args.list:
        print("palettes:", ", ".join(p.key for p in palettes()))
        print("scenes:", ", ".join(s.id for s in scenes()))
        return
    data = build_data(set(args.palette or ()), set(args.scene or ()))
    if args.png:
        png(data, data["scenes"][0]["id"], data["palettes"][0]["key"], args.png)  # type: ignore[index]
        return
    write_html(data, args.output)
    print(
        f"wrote {args.output} ({args.output.stat().st_size / 1024:.0f} KiB, {len(data['palettes'])} palettes, {len(data['scenes'])} scenes)"
    )  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
