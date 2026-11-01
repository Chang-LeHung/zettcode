"""The gateway's logic over a backend that answers from memory: threads, unread marks, sending, daemons, events."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from gateway_fakes import GATEWAY_ID, FakeBackend
from zettcode.gateway import service as service_module
from zettcode.gateway.chat import REPLY_REQUEST, strip_reply_request
from zettcode.gateway.service import Gateway, GatewayError
from zettcode.gateway.settings import Settings
from zettcode.sdk.errors import DaemonStartError, SendError, SessionLockedError
from zettcode.sdk.types import Message, Relay, SendLimits, ToolCallInfo

PEER = "01peerpeerpeer"
DAEMON = "01daemondaemon"


def settings(tmp_path: Path, **changes: object) -> Settings:
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    values: dict[str, object] = {"token": "t", "roots": (work,), "directory": tmp_path / "gw"}
    values.update(changes)
    return Settings(**values)  # type: ignore[arg-type]


async def make(tmp_path: Path, **changes: object) -> tuple[Gateway, FakeBackend]:
    backend = FakeBackend()
    gateway = Gateway(backend, settings(tmp_path, **changes), clock=lambda: 1000.0)
    await gateway.start(watch=False)
    return gateway, backend


def ours(text: str) -> Message:
    return Message("user", text, relay=Relay(GATEWAY_ID, "web-gateway", "user", 1))


def reply(text: str, *, call_id: str = "c1") -> Message:
    call = ToolCallInfo(call_id, "send_message", {"to": GATEWAY_ID, "message": text})
    return Message("assistant", "", tool_calls=(call,))


def drained(queue: asyncio.Queue) -> list[dict]:
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events


# -- who is listed ---------------------------------------------------------------------------------------------
async def test_daemons_and_sessions_are_listed_with_what_each_is_and_the_gateway_itself_is_not(tmp_path):
    gateway, backend = await make(tmp_path)
    backend.add_daemon(DAEMON, "/w/api", name="reviewer", model_name="deep", permission="safe")
    backend.add_peer(PEER, "fix-parser", workspace="/w/parser", title="Fix the parser", status="working")
    backend.add_peer("01ci", "ci-bot", kind="external")
    backend.add_peer(GATEWAY_ID, "web-gateway")
    await gateway.refresh()

    by_id = {view["id"]: view for view in gateway.threads()}

    assert set(by_id) == {DAEMON, PEER, "01ci"}
    daemon, session, external = by_id[DAEMON], by_id[PEER], by_id["01ci"]
    assert (daemon["kind"], daemon["name"], daemon["status"], daemon["online"]) == ("daemon", "reviewer", "idle", True)
    assert (daemon["model"], daemon["permission"], daemon["workspace"]) == ("deep", "safe", "/w/api")
    assert (session["kind"], session["name"], session["status"], session["handle"]) == (
        "session",
        "Fix the parser",
        "working",
        "fix-parser",
    )
    assert (external["kind"], external["name"]) == ("external", "ci-bot")


async def test_a_daemon_the_broker_does_not_list_is_offline_or_dead_and_cannot_be_written_to(tmp_path):
    gateway, backend = await make(tmp_path)
    backend.add_daemon("01starting", "/w", status="starting", online=False)
    backend.add_daemon("01stopping", "/w", status="stopping")
    backend.add_daemon("01dead", "/w", status="dead", online=False)
    backend.add_daemon("01quiet", "/w", status="idle", online=False)
    await gateway.refresh()

    status = {view["id"]: view["status"] for view in gateway.threads()}

    assert status == {
        "01starting": "starting",
        "01stopping": "stopping",
        "01dead": "dead",
        "01quiet": "offline",
    }
    assert gateway.threads()[-1]["id"] == "01dead", "a dead one sorts last"
    with pytest.raises(GatewayError) as refused:
        await gateway.send("01dead", "hello")
    assert (refused.value.status, refused.value.code) == (409, "offline")
    assert backend.sent == []


async def test_the_most_recently_active_thread_comes_first(tmp_path):
    gateway, backend = await make(tmp_path)
    backend.add_daemon("01a", "/w", name="a", started_at=100.0)
    backend.add_daemon("01b", "/w", name="b", started_at=200.0)
    await gateway.refresh()
    assert [view["id"] for view in gateway.threads()] == ["01b", "01a"]

    backend.say("01a", ours("hello"))
    await gateway.refresh()

    assert [view["id"] for view in gateway.threads()] == ["01a", "01b"]


# -- a thread --------------------------------------------------------------------------------------------------
async def test_a_thread_is_the_stored_conversation_as_chat_and_the_list_shows_its_last_words(tmp_path):
    gateway, backend = await make(tmp_path)
    backend.add_daemon(DAEMON, "/w/api", name="reviewer")
    backend.say(DAEMON, ours("check src/api.py\n\n" + REPLY_REQUEST.format(id=GATEWAY_ID)))
    backend.say(DAEMON, Message("assistant", "Reading it now."), reply("Found three problems."))
    await gateway.refresh()

    opened = await gateway.thread(DAEMON)

    assert [(item["kind"], item["text"]) for item in opened["items"]] == [
        ("out", "check src/api.py"),
        ("in", "Reading it now."),
        ("reply", "Found three problems."),
    ]
    assert opened["total"] == 3 and opened["truncated"] is False
    assert opened["thread"]["preview"] == "Found three problems."


async def test_a_long_conversation_returns_its_end_unless_all_of_it_is_asked_for(tmp_path):
    gateway, backend = await make(tmp_path)
    backend.add_daemon(DAEMON, "/w", name="d")
    backend.say(DAEMON, *[Message("assistant", f"line {number}") for number in range(450)])
    await gateway.refresh()

    short = await gateway.thread(DAEMON)
    everything = await gateway.thread(DAEMON, everything=True)

    assert len(short["items"]) == 400 and short["truncated"] and short["items"][-1]["text"] == "line 449"
    assert len(everything["items"]) == 450 and not everything["truncated"]


async def test_a_thread_nobody_listed_is_not_found(tmp_path):
    gateway, _ = await make(tmp_path)

    with pytest.raises(GatewayError) as refused:
        await gateway.thread("01nobody")

    assert refused.value.status == 404


async def test_a_session_with_no_stored_conversation_yet_is_an_empty_chat(tmp_path):
    gateway, backend = await make(tmp_path)
    backend.add_daemon(DAEMON, "/w", name="fresh")
    await gateway.refresh()

    opened = await gateway.thread(DAEMON)

    assert opened["items"] == [] and opened["thread"]["preview"] == ""


# -- unread ----------------------------------------------------------------------------------------------------
async def test_what_a_session_said_before_the_gateway_saw_it_is_read_and_what_it_says_after_is_not(tmp_path):
    gateway, backend = await make(tmp_path)
    backend.add_daemon(DAEMON, "/w", name="d")
    backend.say(DAEMON, Message("assistant", "old news"))
    await gateway.refresh()
    assert gateway.threads()[0]["unread"] == 0

    backend.say(DAEMON, Message("assistant", "new one"), reply("and another"))
    await gateway.refresh()
    assert gateway.threads()[0]["unread"] == 2

    await gateway.read(DAEMON)
    assert gateway.threads()[0]["unread"] == 0


async def test_a_daemon_started_here_counts_everything_it_says_as_unread(tmp_path):
    gateway, backend = await make(tmp_path)
    answer = await gateway.spawn({"workspace": str(tmp_path / "work"), "name": "fresh"})
    started = answer["thread"]["id"]

    backend.say(started, reply("first words"))
    await gateway.refresh()

    assert next(view for view in gateway.threads() if view["id"] == started)["unread"] == 1


async def test_what_was_read_is_remembered_across_a_restart(tmp_path):
    gateway, backend = await make(tmp_path)
    backend.add_daemon(DAEMON, "/w", name="d")
    backend.say(DAEMON, Message("assistant", "seen"))
    await gateway.refresh()
    backend.say(DAEMON, Message("assistant", "unseen"))
    await gateway.refresh()
    assert gateway.threads()[0]["unread"] == 1

    again = Gateway(backend, settings(tmp_path))
    await again.start(watch=False)

    assert again.threads()[0]["unread"] == 1, "the baseline was kept, so the unseen message is still unread"
    await again.read(DAEMON)
    third = Gateway(backend, settings(tmp_path))
    await third.start(watch=False)
    assert third.threads()[0]["unread"] == 0


# -- sending ---------------------------------------------------------------------------------------------------
async def test_a_message_to_a_daemon_asks_for_an_answer_and_the_chat_shows_only_what_was_typed(tmp_path):
    gateway, backend = await make(tmp_path)
    backend.add_daemon(DAEMON, "/w", name="d")
    await gateway.refresh()

    sent = await gateway.send(DAEMON, "  run the tests \r\n")

    assert sent == {"to": "d", "disposition": "started", "direct": False}
    ((to, body),) = backend.sent
    assert to == DAEMON and body.startswith("run the tests\n\n[Web gateway:") and GATEWAY_ID in body
    assert strip_reply_request(body) == "run the tests"
    assert (await gateway.thread(DAEMON))["items"] == [{"kind": "out", "text": "run the tests"}]


async def test_a_message_to_a_session_with_a_person_at_it_is_sent_as_typed_unless_an_answer_is_asked_for(tmp_path):
    gateway, backend = await make(tmp_path)
    backend.add_peer(PEER, "fix-parser", workspace="/w/p")
    await gateway.refresh()

    await gateway.send(PEER, "got a minute?")
    await gateway.send(PEER, "reply please", reply=True)
    await gateway.send(PEER, "no need", reply=False)

    assert [body for _, body in backend.sent][0] == "got a minute?"
    assert "send_message" in backend.sent[1][1] and backend.sent[2][1] == "no need"


async def test_a_message_to_a_busy_daemon_is_queued_and_says_so(tmp_path):
    gateway, backend = await make(tmp_path)
    backend.add_daemon(DAEMON, "/w", name="d")
    backend.set_status(DAEMON, "working")
    await gateway.refresh()

    assert (await gateway.send(DAEMON, "next"))["disposition"] == "queued"


async def test_a_message_that_is_empty_or_too_long_is_refused_before_the_broker_hears_of_it(tmp_path):
    gateway, backend = await make(tmp_path)
    backend.add_daemon(DAEMON, "/w", name="d")
    backend.set_limits(SendLimits(max_text=200))
    await gateway.refresh()

    with pytest.raises(GatewayError) as empty:
        await gateway.send(DAEMON, "   \n ")
    with pytest.raises(GatewayError) as long:
        await gateway.send(DAEMON, "x" * 190)

    assert (empty.value.status, empty.value.code) == (400, "empty")
    assert (long.value.status, long.value.code) == (413, "too_long")
    assert 0 < long.value.extra["limit"] < 190, "the room left once the request for an answer is counted"
    assert backend.sent == []
    await gateway.send(DAEMON, "x" * 190, reply=False)


async def test_the_gateway_stops_at_what_the_broker_allows_before_the_broker_has_to_refuse(tmp_path):
    gateway, backend = await make(tmp_path)
    backend.add_daemon(DAEMON, "/w", name="d")
    backend.set_limits(SendLimits(rate_limit=2, rate_window=60.0))
    await gateway.refresh()

    await gateway.send(DAEMON, "one")
    await gateway.send(DAEMON, "two")
    with pytest.raises(GatewayError) as refused:
        await gateway.send(DAEMON, "three")

    assert (refused.value.status, refused.value.code) == (429, "rate")
    assert refused.value.extra["retry_after"] >= 1
    assert len(backend.sent) == 2
    assert gateway.status()["limits"]["used"] == 2


@pytest.mark.parametrize(
    ("reason", "status", "uncertain"),
    [
        ("busy", 503, False),
        ("gone", 410, False),
        ("rejected", 409, False),
        ("timeout", 504, True),
        ("lost", 504, True),
        ("offline", 503, False),
        ("surprise", 400, False),
    ],
)
async def test_a_send_the_broker_refused_keeps_its_reason_and_a_lost_one_says_it_may_have_arrived(
    tmp_path, reason, status, uncertain
):
    gateway, backend = await make(tmp_path)
    backend.add_daemon(DAEMON, "/w", name="d")
    await gateway.refresh()
    backend.fail = SendError(reason, "the broker's words")

    with pytest.raises(GatewayError) as refused:
        await gateway.send(DAEMON, "hello")

    assert (refused.value.status, refused.value.code, str(refused.value)) == (status, reason, "the broker's words")
    assert refused.value.extra["uncertain"] is uncertain


async def test_the_page_sends_a_follow_up_so_it_never_steers_a_live_turn(tmp_path):
    from zettcode.gateway.backend import SdkBackend
    from zettcode.sdk.types import Delivered

    backend = SdkBackend(tmp_path / "work", tmp_path / "gw")
    calls: list[tuple[str, str, dict[str, object]]] = []

    class Client:
        async def send(self, to: str, text: str, **options: object) -> Delivered:
            calls.append((to, text, options))
            return Delivered("api", "queued")

    backend._client = Client()  # type: ignore[assignment]
    sent = await backend.send("api", "hello", direct=True)

    assert sent.disposition == "queued"
    assert calls == [("api", "hello", {"direct": True, "mode": "followup"})]


# -- what arrives ----------------------------------------------------------------------------------------------
async def test_a_message_from_a_program_with_no_stored_conversation_is_a_chat_of_what_it_sent(tmp_path):
    gateway, backend = await make(tmp_path)
    queue = gateway.subscribe()
    drained(queue)

    receipt = backend.inbound("external:ci", "ci", "build 42 is red", via="external")
    await gateway.refresh()

    assert receipt.accepted and receipt.disposition == "delivered"
    (view,) = gateway.threads()
    assert (view["id"], view["kind"], view["name"], view["online"], view["unread"]) == (
        "external:ci",
        "external",
        "ci",
        False,
        1,
    )
    assert view["preview"] == "build 42 is red"
    opened = await gateway.thread("external:ci")
    assert opened["items"] == [{"kind": "in", "text": "build 42 is red", "via": "external", "sender": "ci"}]
    kinds = [event["type"] for event in drained(queue)]
    assert kinds[0] == "inbound" and "threads" in kinds
    await gateway.read("external:ci")
    assert gateway.threads()[0]["unread"] == 0


async def test_what_a_daemon_sends_us_is_shown_once_from_its_conversation_and_not_again_from_the_message(tmp_path):
    gateway, backend = await make(tmp_path)
    backend.add_daemon(DAEMON, "/w", name="d")
    backend.say(DAEMON, Message("assistant", "baseline"))
    await gateway.refresh()

    backend.say(DAEMON, reply("the answer"))
    backend.inbound(DAEMON, "d", "the answer")
    await gateway.refresh()

    opened = await gateway.thread(DAEMON)
    assert [item["kind"] for item in opened["items"]] == ["in", "reply"]
    assert gateway.threads()[0]["unread"] == 1


# -- daemons ---------------------------------------------------------------------------------------------------
async def test_a_daemon_is_started_with_what_the_form_chose_and_listed_at_once(tmp_path):
    gateway, backend = await make(tmp_path)
    work = tmp_path / "work"
    (work / "api").mkdir()

    answer = await gateway.spawn(
        {
            "workspace": str(work / "api"),
            "model": "deep",
            "effort": "high",
            "name": "  Re\x07view   er ",
            "permission": "deny",
        }
    )

    assert backend.spawned == [
        {
            "workspace": str((work / "api").resolve()),
            "model": "deep",
            "effort": "high",
            "resume": None,
            "name": "Review er",
            "permission": "deny",
        }
    ]
    assert answer["thread"]["kind"] == "daemon" and answer["thread"]["name"] == "Review er"
    assert "first" not in answer


async def test_the_shell_level_defaults_to_safe_and_full_needs_the_command_line_to_have_allowed_it(tmp_path):
    gateway, backend = await make(tmp_path)
    work = str(tmp_path / "work")
    await gateway.spawn({"workspace": work})
    assert backend.spawned[-1]["permission"] == "safe"

    with pytest.raises(GatewayError) as refused:
        await gateway.spawn({"workspace": work, "permission": "full"})
    assert (refused.value.status, refused.value.code) == (403, "forbidden")
    with pytest.raises(GatewayError) as unknown:
        await gateway.spawn({"workspace": work, "permission": "ask"})
    assert unknown.value.status == 400
    assert len(backend.spawned) == 1

    allowed, other = await make(tmp_path, allow_full=True)
    await allowed.spawn({"workspace": work, "permission": "full"})
    assert other.spawned[-1]["permission"] == "full"


async def test_a_daemon_cannot_be_started_outside_the_roots_or_where_there_is_no_directory(tmp_path):
    gateway, backend = await make(tmp_path)
    work = tmp_path / "work"
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (work / "link").symlink_to(outside)
    (work / "file.txt").write_text("x")

    for text, status in (
        ("", 400),
        (str(outside), 403),
        (str(work / ".." / "elsewhere"), 403),
        (str(work / "link"), 403),
        (str(work / "missing"), 400),
        (str(work / "file.txt"), 400),
    ):
        with pytest.raises(GatewayError) as refused:
            await gateway.spawn({"workspace": text})
        assert refused.value.status == status, text
    assert backend.spawned == []


async def test_a_gateway_with_no_roots_starts_nothing(tmp_path):
    gateway, backend = await make(tmp_path, roots=())

    with pytest.raises(GatewayError) as refused:
        await gateway.spawn({"workspace": str(tmp_path)})

    assert refused.value.status == 403 and backend.spawned == []


async def test_a_model_or_a_level_the_configuration_does_not_have_is_refused(tmp_path):
    gateway, backend = await make(tmp_path)
    work = str(tmp_path / "work")

    for form in (
        {"workspace": work, "model": "nonesuch"},
        {"workspace": work, "model": "fast", "effort": "medium"},
        {"workspace": work, "effort": "medium"},
        {"workspace": work, "resume": "../x"},
    ):
        with pytest.raises(GatewayError) as refused:
            await gateway.spawn(form)
        assert refused.value.status == 400, form
    await gateway.spawn({"workspace": work, "effort": "high"})
    assert backend.spawned[-1]["model"] is None and backend.spawned[-1]["effort"] == "high"


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (DaemonStartError("no model is configured"), 502, "start_failed"),
        (SessionLockedError("open in another process"), 409, "locked"),
    ],
)
async def test_a_daemon_that_would_not_start_is_reported_with_what_it_said(tmp_path, error, status, code):
    gateway, backend = await make(tmp_path)
    backend.fail_spawn = error

    with pytest.raises(GatewayError) as refused:
        await gateway.spawn({"workspace": str(tmp_path / "work")})

    assert (refused.value.status, refused.value.code) == (status, code)


async def test_the_first_message_goes_once_the_daemon_is_reachable_and_a_failure_of_it_does_not_undo_the_start(
    tmp_path,
):
    gateway, backend = await make(tmp_path)
    work = str(tmp_path / "work")

    answer = await gateway.spawn({"workspace": work, "message": "start with the tests"})
    assert answer["first"]["ok"] is True and answer["first"]["disposition"] == "started"
    assert backend.sent[0][1].startswith("start with the tests")

    backend.fail = SendError("busy", "too many waiting")
    failed = await gateway.spawn({"workspace": work, "message": "again"})
    assert failed["first"]["ok"] is False and failed["first"]["error"]["code"] == "busy"
    assert failed["thread"] is not None


async def test_a_daemon_is_stopped_by_its_id_and_an_unknown_one_is_not_found(tmp_path):
    gateway, backend = await make(tmp_path)
    backend.add_daemon(DAEMON, "/w", name="d")
    await gateway.refresh()

    assert await gateway.stop(DAEMON) == {"result": "stopped"}
    assert gateway.threads() == [] and backend.stopped == [DAEMON]
    for bad, status in ((DAEMON, 404), ("../x", 400)):
        with pytest.raises(GatewayError) as refused:
            await gateway.stop(bad)
        assert refused.value.status == status


async def test_a_daemons_log_is_read_and_an_unknown_daemon_has_none(tmp_path):
    gateway, backend = await make(tmp_path)
    backend.add_daemon(DAEMON, "/w", name="d")
    backend.logs[DAEMON] = "tool grep\n"

    assert await gateway.log(DAEMON) == {"text": "tool grep\n"}
    with pytest.raises(GatewayError) as refused:
        await gateway.log("01none")
    assert refused.value.status == 404


# -- configuration and folders ---------------------------------------------------------------------------------
async def test_the_form_is_told_the_models_the_roots_and_whether_full_is_allowed(tmp_path):
    gateway, _ = await make(tmp_path, allow_full=True)

    config = gateway.config()

    assert [(model["name"], model["default"]) for model in config["models"]] == [("fast", True), ("deep", False)]
    assert config["models"][1]["efforts"] == ["low", "medium", "high"] and config["models"][1]["multimodal"]
    assert config["roots"] == [str((tmp_path / "work").resolve())]
    assert config["allow_full"] is True and config["permissions"] == ["deny", "safe", "full"]


async def test_the_folder_picker_lists_the_roots_then_their_folders_and_never_leaves_them(tmp_path):
    gateway, _ = await make(tmp_path)
    work = (tmp_path / "work").resolve()
    for name in ("beta", "Alpha", ".hidden"):
        (work / name).mkdir()
    (work / "alpha-file").write_text("x")
    (work / "Alpha" / "inner").mkdir()

    top = gateway.browse("")
    inside = gateway.browse(str(work))
    deeper = gateway.browse(str(work / "Alpha"))

    assert top == {"path": "", "parent": None, "dirs": [{"name": str(work), "path": str(work)}]}
    assert [entry["name"] for entry in inside["dirs"]] == ["Alpha", "beta"]
    assert inside["parent"] == "" and deeper["parent"] == str(work)
    assert [entry["name"] for entry in deeper["dirs"]] == ["inner"]
    with pytest.raises(GatewayError) as refused:
        gateway.browse(str(tmp_path))
    assert refused.value.status == 403


@pytest.mark.skipif(os.name == "nt", reason="one filesystem root is a POSIX idea: a Windows machine has one per drive")
async def test_with_the_whole_filesystem_allowed_the_picker_starts_at_home_and_can_go_up_to_the_top(tmp_path):
    gateway, _ = await make(tmp_path, roots=(Path("/"),))

    start = gateway.browse("")
    top = gateway.browse("/")

    assert start["path"] == str(Path.home().resolve()) and start["parent"] == str(Path.home().resolve().parent)
    assert top["parent"] is None


# -- events ----------------------------------------------------------------------------------------------------
async def test_a_page_is_given_everything_when_it_connects_and_what_changes_after(tmp_path):
    gateway, backend = await make(tmp_path)
    backend.add_daemon(DAEMON, "/w", name="d")
    await gateway.refresh()
    queue = gateway.subscribe()

    (first,) = drained(queue)
    assert first["type"] == "threads" and [view["id"] for view in first["threads"]] == [DAEMON]
    assert first["status"]["gateway"]["id"] == GATEWAY_ID and first["status"]["broker"]["reachable"] is True

    await gateway.refresh()
    assert drained(queue) == [], "nothing changed, nothing is said"

    backend.say(DAEMON, Message("assistant", "hello"))
    await gateway.refresh()
    events = drained(queue)
    assert [event["type"] for event in events] == ["threads", "thread"] and events[1]["id"] == DAEMON

    backend.set_reachable(False)
    await gateway.refresh()
    (down,) = [event for event in drained(queue) if event["type"] == "threads"]
    assert down["status"]["broker"]["reachable"] is False

    gateway.unsubscribe(queue)
    backend.say(DAEMON, Message("assistant", "again"))
    await gateway.refresh()
    assert drained(queue) == []


async def test_a_page_that_stops_reading_is_dropped_and_the_others_go_on(tmp_path):
    gateway, backend = await make(tmp_path)
    backend.add_daemon(DAEMON, "/w", name="d")
    slow, fast = gateway.subscribe(), gateway.subscribe()
    for number in range(300):
        backend.say(DAEMON, Message("assistant", f"m{number}"))
        await gateway.refresh()
        drained(fast)

    assert slow not in gateway._subscribers and fast in gateway._subscribers


async def test_the_watcher_looks_again_when_the_broker_says_something_moved(tmp_path):
    backend = FakeBackend()
    gateway = Gateway(backend, settings(tmp_path), poll=60.0)
    await gateway.start()
    try:
        queue = gateway.subscribe()
        drained(queue)

        backend.add_daemon(DAEMON, "/w", name="woken")
        for _ in range(100):
            if not queue.empty():
                break
            await asyncio.sleep(0.02)

        event = queue.get_nowait()
        assert event["type"] == "threads" and event["threads"][0]["name"] == "woken"
    finally:
        await gateway.close()
    assert backend.closed


async def test_a_session_that_takes_direct_prompts_gets_the_text_as_typed_and_is_not_asked_to_reply(tmp_path):
    gateway, backend = await make(tmp_path)
    backend.add_daemon(DAEMON, "/w", name="d", direct=True)
    await gateway.refresh()

    sent = await gateway.send(DAEMON, "run the tests")

    assert sent["direct"] is True and backend.sent == [(DAEMON, "run the tests")] and backend.direct_sent == [True]
    assert (await gateway.thread(DAEMON))["items"] == [{"kind": "user", "text": "run the tests"}]


async def test_a_session_that_cannot_take_one_falls_back_to_a_message_with_the_request_for_an_answer(tmp_path):
    gateway, backend = await make(tmp_path)
    backend.add_daemon(DAEMON, "/w", name="d", direct=False)
    await gateway.refresh()

    await gateway.send(DAEMON, "run the tests")

    assert backend.direct_sent == [False] and "[Web gateway:" in backend.sent[0][1]


async def test_an_unreachable_session_another_process_has_open_is_locked_until_that_process_lets_go(tmp_path):
    gateway, backend = await make(tmp_path)
    backend.add_daemon(DAEMON, "/w", name="d", status="dead", online=False)
    backend.say(DAEMON, Message("user", "hi"))
    backend.locked_ids.add(DAEMON)
    await gateway.refresh()
    assert gateway.threads()[0]["locked"] is True

    still = await gateway.recheck(DAEMON)
    backend.locked_ids.discard(DAEMON)
    freed = await gateway.recheck(DAEMON)

    assert still["locked"] is True and freed["locked"] is False
    with pytest.raises(GatewayError) as missing:
        await gateway.recheck("01nobody")
    assert missing.value.status == 404


async def test_a_session_with_a_person_at_it_shows_its_last_words_and_unread_without_being_opened_once(tmp_path):
    gateway, backend = await make(tmp_path)
    backend.say(PEER, Message("assistant", "what it said before we looked"))
    backend.add_peer(PEER, "fix-parser", workspace="/w/p")
    await gateway.refresh()
    backend.say(PEER, Message("assistant", "a new thing it said"))

    await gateway.refresh()

    (view,) = [item for item in gateway.threads() if item["id"] == PEER]
    assert view["preview"] == "a new thing it said" and view["unread"] == 1


async def test_a_daemon_that_is_working_is_read_when_it_goes_quiet_too(tmp_path):
    """A running daemon is a peer; only a daemon nobody is running has a record and no roster entry to follow."""
    gateway, backend = await make(tmp_path)
    backend.add_daemon(DAEMON, "/w", name="d")
    backend.add_peer(DAEMON, "review-d", workspace="/w")
    await gateway.refresh()
    backend.set_status(DAEMON, "working")
    backend.say(DAEMON, Message("assistant", "partway"))
    await gateway.refresh()
    assert [item["preview"] for item in gateway.threads() if item["id"] == DAEMON] == [""]

    backend.set_status(DAEMON, "idle")
    await gateway.refresh()

    assert [item["preview"] for item in gateway.threads() if item["id"] == DAEMON] == ["partway"]


async def test_a_session_that_is_working_is_read_when_it_goes_quiet_and_not_at_every_look(tmp_path):
    gateway, backend = await make(tmp_path)
    backend.add_peer(PEER, "fix-parser", workspace="/w/p")
    await gateway.refresh()
    backend.set_status(PEER, "working")
    backend.say(PEER, Message("assistant", "partway"))
    await gateway.refresh()
    assert [item["preview"] for item in gateway.threads() if item["id"] == PEER] == [""]

    backend.set_status(PEER, "idle")
    await gateway.refresh()

    assert [item["preview"] for item in gateway.threads() if item["id"] == PEER] == ["partway"]


async def test_a_refresh_failure_is_recorded_once_until_it_recovers(tmp_path, monkeypatch):
    gateway, _ = await make(tmp_path)
    records: list[str] = []

    def failed(*args, **kwargs):
        records.append("failed")

    def recovered(*args, **kwargs):
        records.append("recovered")

    monkeypatch.setattr(service_module.diagnostics, "exception", failed)
    monkeypatch.setattr(service_module.diagnostics, "write", recovered)

    async def broken() -> None:
        raise RuntimeError("the broker is down")

    async def differently_broken() -> None:
        raise ValueError("the roster changed shape")

    async def healthy() -> None:
        return None

    monkeypatch.setattr(gateway, "refresh", broken)
    await gateway._poll_once()
    await gateway._poll_once()
    assert records == ["failed"]

    monkeypatch.setattr(gateway, "refresh", differently_broken)
    await gateway._poll_once()
    assert records == ["failed", "failed"]

    monkeypatch.setattr(gateway, "refresh", healthy)
    await gateway._poll_once()
    assert records == ["failed", "failed", "recovered"]
