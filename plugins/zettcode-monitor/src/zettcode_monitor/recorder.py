"""Record every model call of a session, request and reply, while the session's switch is on.

A session's folder under the monitor root holds:

* ``state.json`` -- ``{"enabled": true}`` once monitoring was turned on. Monitoring is off until then.
* ``calls.jsonl`` -- one JSON object per model call, appended as the call ends.

The switch is read from ``state.json`` the first time a session is seen, so a resumed session picks up where it was
left without anyone telling the recorder. Every call stores its whole request, so early messages repeat from call to
call; each record is complete on its own.
"""

from __future__ import annotations

import base64
import json
import os
import time
from collections.abc import AsyncIterator
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from zett_agent.agent import AgentRunContext
from zett_agent.extensions.base import AgentExtension
from zett_agent.messages import AnyMessage, ImageBytesSource, ImageContent, ImageUrlSource, TextContent
from zett_agent.model import ModelEvent, ModelEventType, ModelRequest, ModelResponse

STATE_FILE = "state.json"
CALLS_FILE = "calls.jsonl"

_ROLES = {"SystemMessage": "system", "UserMessage": "user", "AssistantMessage": "assistant", "ToolMessage": "tool"}


def default_root() -> Path:
    """Return ``$ZETTCODE_MONITOR_DIR`` or ``~/.zettcode/monitor``."""
    override = os.environ.get("ZETTCODE_MONITOR_DIR")
    return Path(override).expanduser() if override else Path.home() / ".zettcode" / "monitor"


def _text(content: object) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        parts = []
        for part in content:
            if isinstance(part, TextContent):
                parts.append(part.text)
            elif isinstance(part, ImageContent):
                parts.append("[image]")
            else:
                parts.append(str(part))
        return "\n".join(parts)
    return str(content)


def _images(content: object) -> list[str]:
    """Return the images of a message body as URLs a page can show: data URLs for bytes, the URL itself otherwise."""
    found: list[str] = []
    if isinstance(content, (list, tuple)):
        for part in content:
            if not isinstance(part, ImageContent):
                continue
            source = part.source
            if isinstance(source, ImageBytesSource):
                found.append(f"data:{source.media_type};base64,{base64.b64encode(source.data).decode('ascii')}")
            elif isinstance(source, ImageUrlSource):
                found.append(source.url)
    return found


def _plain(value: object) -> Any:
    """Return ``value`` as JSON-able data; enums become their value and anything unknown its ``str``."""
    if is_dataclass(value) and not isinstance(value, type):
        return _plain(asdict(cast(Any, value)))
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    inner = getattr(value, "value", None)
    return inner if isinstance(inner, str) else str(value)


def encode_message(message: AnyMessage, *, images: bool = False) -> dict[str, Any]:
    """Return a message as ``role`` and ``text``, plus reasoning, tool calls or tool-result fields when it has them.

    An image is only a ``[image]`` marker in the text unless ``images`` is set, which also lists its data URLs.
    """
    kind = type(message).__name__
    entry: dict[str, Any] = {"role": _ROLES.get(kind, kind), "text": _text(getattr(message, "content", ""))}
    if images:
        found = _images(getattr(message, "content", None))
        if found:
            entry["images"] = found
    reasoning = getattr(message, "reasoning", None)
    if reasoning:
        entry["reasoning"] = _text(reasoning)
    calls = getattr(message, "tool_calls", None)
    if calls:
        entry["tool_calls"] = [
            {"id": call.id, "name": call.name, "arguments": _plain(call.arguments), "error": _plain(call.error)}
            for call in calls
        ]
    call_id = getattr(message, "tool_call_id", None)
    if call_id:
        entry.update(tool_call_id=call_id, name=getattr(message, "name", ""), success=getattr(message, "success", True))
    for field in ("provider", "model"):
        value = getattr(message, field, None)
        if value:
            entry[field] = value
    blocks = getattr(message, "replay_blocks", None)
    if blocks:
        entry["replay_blocks"] = _plain(blocks)
    return entry


class ServerToolTrace:
    """Fold the stream events of provider-hosted tools (web search, web fetch, ...) into one record per call.

    These calls are never part of the final message: the provider runs them and only the stream reports them, so a
    recorder that keeps just the response would lose them.
    """

    def __init__(self) -> None:
        self._calls: dict[str, dict[str, Any]] = {}
        self._buffers: dict[str, str] = {}

    def observe(self, event: ModelEvent) -> None:
        """Take in one stream event; anything that is not a hosted-tool event is ignored."""
        kind = event.type
        if kind is ModelEventType.SERVER_TOOL_STARTED and event.server_tool_call is not None:
            call = event.server_tool_call
            self._calls[call.id] = {"id": call.id, "name": call.name, "input": _plain(call.input), "status": "running"}
        elif kind is ModelEventType.SERVER_TOOL_INPUT_DELTA and event.server_tool_input_delta is not None:
            delta = event.server_tool_input_delta
            self._buffers[delta.call_id] = self._buffers.get(delta.call_id, "") + delta.delta
        elif kind in (ModelEventType.SERVER_TOOL_COMPLETED, ModelEventType.SERVER_TOOL_FAILED):
            result = event.server_tool_result
            if result is None:
                return
            entry = self._calls.setdefault(result.call_id, {"id": result.call_id, "name": result.name, "input": None})
            entry["output"] = _plain(result.output)
            entry["status"] = "failed" if kind is ModelEventType.SERVER_TOOL_FAILED else "completed"
            if result.error_code:
                entry["error_code"] = result.error_code

    def calls(self) -> list[dict[str, Any]]:
        """Return the calls in the order they started, streamed input assembled when the start carried none."""
        done = []
        for call_id, entry in self._calls.items():
            entry = dict(entry)
            streamed = self._buffers.get(call_id)
            if entry.get("input") is None and streamed:
                try:
                    entry["input"] = json.loads(streamed)
                except ValueError:
                    entry["input"] = streamed
            done.append(entry)
        return done


def encode_request(request: ModelRequest, *, images: bool = False) -> dict[str, Any]:
    """Return everything the model was sent."""
    return {
        "messages": [encode_message(message, images=images) for message in request.messages],
        "tools": [_plain(tool) for tool in request.tools],
        "server_tools": [_plain(tool) for tool in request.server_tools],
        "reasoning_effort": _plain(request.reasoning_effort),
        "tool_choice": request.tool_choice,
        "parallel_tool_call": request.parallel_tool_call,
    }


def encode_response(response: ModelResponse, *, images: bool = False) -> dict[str, Any]:
    """Return everything the model answered."""
    return {
        "message": encode_message(response.message, images=images),
        "finish_reason": response.finish_reason,
        "usage": _plain(response.usage),
        "stop": _plain(response.stop),
    }


class MonitorExtension(AgentExtension):
    """Append one record per model call to the calling session's folder while its switch is on."""

    name = "monitor"

    def __init__(self, root: Path | None = None) -> None:
        self.root = root if root is not None else default_root()
        self._state: dict[str, dict[str, bool]] = {}
        self._counts: dict[str, int] = {}
        self._stamps: dict[str, float] = {}

    def folder(self, session_id: str) -> Path:
        return self.root / session_id

    def enabled(self, session_id: str) -> bool:
        """Return whether the session is recorded; read from disk once, then remembered."""
        return self._load(session_id)["enabled"]

    def images(self, session_id: str) -> bool:
        """Return whether image data is kept in the records; off unless the reader turned it on."""
        return self._load(session_id)["images"]

    def set_enabled(self, session_id: str, enabled: bool) -> None:
        """Switch recording for a session and remember it for the next time the session is opened."""
        self._save(session_id, enabled=enabled)

    def set_images(self, session_id: str, images: bool) -> None:
        """Keep (or stop keeping) the data of images in the records, remembered like the recording switch."""
        self._save(session_id, images=images)

    def _load(self, session_id: str) -> dict[str, bool]:
        if session_id not in self._state:
            self._state[session_id] = self._read_state(session_id)
        return self._state[session_id]

    def _save(self, session_id: str, **changes: bool) -> None:
        state = {**self._load(session_id), **changes}
        folder = self.folder(session_id)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / STATE_FILE).write_text(json.dumps(state), encoding="utf-8")
        self._state[session_id] = state

    def calls(self, session_id: str) -> list[dict[str, Any]]:
        """Return the recorded calls, oldest first; a line that cannot be read is skipped."""
        path = self.folder(session_id) / CALLS_FILE
        if not path.is_file():
            return []
        records: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                records.append(record)
        return records

    def count(self, session_id: str) -> int:
        """Return how many calls are recorded; the file is read once, then the count is kept as calls are added."""
        if session_id not in self._counts:
            self._counts[session_id] = len(self.calls(session_id))
        return self._counts[session_id]

    def _read_state(self, session_id: str) -> dict[str, bool]:
        try:
            data = json.loads((self.folder(session_id) / STATE_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        return {"enabled": data.get("enabled") is True, "images": data.get("images") is True}

    def _append(self, session_id: str, record: dict[str, Any]) -> None:
        folder = self.folder(session_id)
        folder.mkdir(parents=True, exist_ok=True)
        self._counts[session_id] = self.count(session_id) + 1
        record = {"number": self._counts[session_id], **record}
        with (folder / CALLS_FILE).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    async def before_model(self, context: AgentRunContext, request: ModelRequest) -> None:
        """Stamp the clock where the terminal's own token-rate measurement starts, so the two agree."""
        session_id = cast(str, context.config.session_id)
        if self.enabled(session_id):
            self._stamps[session_id] = time.perf_counter()

    async def on_model_request(
        self, context: AgentRunContext, request: ModelRequest, call_next: Any
    ) -> AsyncIterator[ModelEvent]:
        """Pass the stream through untouched and write the call down when it ends, however it ends."""
        session_id = cast(str, context.config.session_id)
        if not self.enabled(session_id):
            async for event in call_next(request):
                yield event
            return
        started_at = datetime.now(timezone.utc)
        keep_images = self.images(session_id)
        # The terminal's speed is measured from before_model, so start from the same stamp when there is one.
        started = self._stamps.pop(session_id, None) or time.perf_counter()
        response: ModelResponse | None = None
        error: str | None = None
        first: float | None = None
        hosted = ServerToolTrace()
        try:
            async for event in call_next(request):
                if first is None:
                    first = time.perf_counter()
                hosted.observe(event)
                if event.type is ModelEventType.RESPONSE and event.response is not None:
                    response = event.response
                yield event
        except BaseException as exc:  # noqa: BLE001 - recorded, then re-raised unchanged
            error = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
            raise
        finally:
            if response is None and error is None:
                error = "stream closed before a response"
            try:
                self._append(
                    session_id,
                    {
                        "started_at": started_at.isoformat(),
                        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                        "ttft_ms": round((first - started) * 1000, 1) if first is not None else None,
                        "request": encode_request(request, images=keep_images),
                        "response": encode_response(response, images=keep_images) if response is not None else None,
                        "server_tool_calls": hosted.calls(),
                        "error": error,
                    },
                )
            except Exception:  # noqa: BLE001 - a full disk must not fail the conversation
                pass
