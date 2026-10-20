"""The shapes the HTTP API promises, so a client has a schema and not a guess.

These are the server's own types. The SDK's values are converted into them at the edge (see
:mod:`zettcode_server.serialize`), which keeps the wire format a decision of this package: the SDK may gain a field
without changing what a client sees, and a field is only published when it is meant.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

#: The shell permission levels, as the SDK names them.
PermissionName = Literal["deny", "ask", "safe", "auto"]

#: How a run answers the shell commands the model asks to run.
ApprovalMode = Literal["deny", "auto", "commands", "ask"]

#: Whether a question the model asks waits for the client.
QuestionMode = Literal["ask", "decline"]


class ApprovalPolicy(BaseModel):
    """The rule a run answers shell approvals with.

    A run over HTTP is unattended unless the client stays in the conversation: the agent is suspended inside the shell
    tool until the request is answered. ``deny`` refuses every command (the default), ``auto`` approves every one, and
    ``commands`` approves only the commands named and refuses the rest. ``ask`` leaves each one to the client: it
    arrives in the stream as ``approval_requested`` and is answered with ``POST /runs/approvals``, or denied once
    ``answer_timeout`` runs out.

    Attributes:
        mode: Which rule applies.
        commands: The commands ``commands`` approves, such as ``"git status"``. A command matches when it is one of
            them or continues one with arguments; one holding a shell character (``;``, ``|``, ``&&``) never matches.
    """

    mode: ApprovalMode = "deny"
    commands: list[str] = Field(default_factory=list)


class RunOptions(BaseModel):
    """What every run answers with, whether it starts a prompt or continues an interrupted one.

    Attributes:
        approvals: How shell commands the model asks to run are answered.
        questions: ``ask`` sends a question the model asks down the stream and waits for
            ``POST /runs/questions``; ``decline`` tells the model the reader is not there.
        timeout: Seconds the whole run may take before it is stopped, or ``None`` for no deadline.
        answer_timeout: Seconds an ``ask`` approval or question waits for the client before the safe default is
            applied (deny, decline), so a client that went away cannot hang the run.
        keep_events: Include every event in the final result as well, as the SDK's ``keep_events`` does.
    """

    approvals: ApprovalPolicy = Field(default_factory=ApprovalPolicy)
    questions: QuestionMode = "decline"
    timeout: float | None = Field(default=None, gt=0)
    answer_timeout: float = Field(default=300.0, gt=0, le=3600)
    keep_events: bool = False


class ImageIn(BaseModel):
    """An image sent with a prompt, base64 encoded.

    Attributes:
        data: The file's bytes, base64 encoded (no data-URL prefix).
        media_type: ``image/png``, ``image/jpeg``, ``image/gif`` or ``image/webp``.
    """

    data: str = Field(min_length=1)
    media_type: str = Field(min_length=1)


class PromptRequest(RunOptions):
    """One prompt, streamed as it runs.

    Attributes:
        text: What to ask the agent; ``@path`` references are resolved when ``mentions`` is on.
        images: Pictures for a model that takes them.
        mentions: Resolve ``@`` references in the text, as the terminal does.
    """

    text: str = Field(min_length=1)
    images: list[ImageIn] = Field(default_factory=list)
    mentions: bool = True


class ResumeRequest(RunOptions):
    """Continue the request that was interrupted; nothing is asked, so only the answers are named."""


class HealthOut(BaseModel):
    """What ``/health`` answers: the process is up, and what it has to work with."""

    status: Literal["ok"] = "ok"
    version: str
    workspace: str
    #: Whether a model is configured, so a prompt can run. A fresh machine is ``false`` until ``POST /models``.
    ready: bool = False
    session: str | None = None
    models: int = 0
    busy: bool


class UsageOut(BaseModel):
    """Token counts, for the session or for one run."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    seconds: float = 0.0
    requests: int = 0
    context_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        """Return input plus output, as the SDK's ``Usage.total_tokens``."""
        return self.input_tokens + self.output_tokens


class ModelOut(BaseModel):
    """One configured model."""

    name: str
    model: str
    context_window: int
    multimodal: bool
    efforts: list[str]
    active: bool = False
    compact_percent: float = 80.0


class ModelsOut(BaseModel):
    """Every configured model, and which one a run would use."""

    models: list[ModelOut]
    current: str | None = None


class SettingsOut(BaseModel):
    """The model, reasoning effort and permission a run starts with."""

    model: ModelOut
    effort: str
    efforts: list[str]
    permission: PermissionName
    permissions: list[str]
    unsaved: str | None = None


class SettingsUpdate(BaseModel):
    """A change to what a run starts with; every field left out stays as it is."""

    model: str | None = None
    effort: str | None = None
    permission: PermissionName | None = None
    compact_percent: float | None = Field(default=None, gt=0, le=100)


class ModelCreate(BaseModel):
    """One model to write into the configuration file.

    The keys are the file's own, so what is added here is what ``/config add`` writes and what the terminal reads.
    A token may be left out when the environment names one (``OPENAI_API_KEY``, ``ANTHROPIC_API_KEY``).
    """

    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1)
    token: str | None = None
    display_model: str | None = None
    base_url: str | None = None
    anthropic: bool = False
    responses_api: bool = False
    multimodal: bool = False
    context_window: int | None = Field(default=None, ge=1)
    compact_percent: float | None = Field(default=None, gt=0, le=100)
    reasoning_efforts: list[str] = Field(default_factory=list)

    def entry(self) -> dict[str, object]:
        """Return the file keys to write, leaving out what was not given."""
        data = self.model_dump(exclude_none=True)
        for flag in ("anthropic", "responses_api", "multimodal"):
            if not data.get(flag):
                data.pop(flag, None)
        if not data.get("reasoning_efforts"):
            data.pop("reasoning_efforts", None)
        return data


class ModelUpdate(BaseModel):
    """Changes to one configured model; a key left out stays as it is, and the token is kept."""

    model_config = ConfigDict(extra="forbid")

    model: str | None = Field(default=None, min_length=1)
    token: str | None = None
    display_model: str | None = None
    base_url: str | None = None
    anthropic: bool | None = None
    responses_api: bool | None = None
    multimodal: bool | None = None
    context_window: int | None = Field(default=None, ge=1)
    compact_percent: float | None = Field(default=None, gt=0, le=100)
    reasoning_efforts: list[str] | None = None

    def changes(self) -> dict[str, object]:
        """Return only the keys the request set, as the file writes them."""
        return self.model_dump(exclude_unset=True, exclude_none=True)


class SessionOut(BaseModel):
    """One stored session, as a list shows it."""

    id: str
    title: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    current: bool = False


class SessionsOut(BaseModel):
    """The stored sessions, most recently active first."""

    sessions: list[SessionOut]


class CurrentSessionOut(BaseModel):
    """The conversation the next prompt continues."""

    id: str
    title: str | None = None
    locked: bool = False
    usage: UsageOut


class SessionCreate(BaseModel):
    """The body of a new session: a name for it, or none until one is written."""

    title: str | None = Field(default=None, max_length=500)


class RenameRequest(BaseModel):
    """A new name for a session."""

    title: str = Field(min_length=1, max_length=500)


class ToolOut(BaseModel):
    """One tool call and how it ended."""

    call_id: str
    name: str
    arguments: dict[str, object] = Field(default_factory=dict)
    output: str = ""
    ok: bool = True
    skipped: bool = False


class MessageOut(BaseModel):
    """One message of a stored conversation."""

    role: str
    text: str
    tool_calls: list[ToolOut] = Field(default_factory=list)
    tool_call_id: str | None = None
    tool_name: str | None = None
    ok: bool = True
    images: int = 0
    pictures: list[ImageIn] = Field(default_factory=list)
    usage: UsageOut | None = None
    seconds: float = 0.0


class HistoryOut(BaseModel):
    """A stored conversation, oldest message first."""

    messages: list[MessageOut]


class CompactionOut(BaseModel):
    """A compaction: how much was folded into the summary, and how much was kept."""

    applied: bool
    summary: str = ""
    compressed: int = 0
    kept: int = 0


class ContextShareOut(BaseModel):
    """One source filling the context window."""

    name: str
    tokens: int
    items: int = 0


class ContextOut(BaseModel):
    """How full the context window is, and what is filling it."""

    window: int
    used: int
    measured_by: str
    shares: list[ContextShareOut] = Field(default_factory=list)
    partial: bool = False
    from_provider: bool = False


class ResultOut(BaseModel):
    """What a finished run came to."""

    text: str
    session_id: str
    usage: UsageOut
    tools: list[ToolOut] = Field(default_factory=list)
    stop: str | None = None
    stop_message: str | None = None
    questions: list[str] = Field(default_factory=list)


class CancelledOut(BaseModel):
    """Whether there was a run to stop."""

    cancelled: bool


class ApprovalAnswer(BaseModel):
    """The client's answer to one shell approval the run is waiting on.

    Attributes:
        call_id: The ``call_id`` of the ``approval_requested`` frame.
        approve: Run the command, or refuse it.
        remember: Let the same kind of command run unasked for the rest of the run.
    """

    call_id: str = Field(min_length=1)
    approve: bool = Field(strict=True)
    remember: bool = Field(strict=True, default=False)


class QuestionAnswer(BaseModel):
    """The client's answer to one question the model asked.

    Attributes:
        call_id: The ``call_id`` of the ``question_asked`` frame.
        answer: The text to send the model; ``null`` declines the question.
    """

    call_id: str = Field(min_length=1)
    answer: str | None = None


class SteerIn(BaseModel):
    """A message for the run in progress."""

    text: str = Field(min_length=1)


class SteeredOut(BaseModel):
    """Whether a running request took the message; ``false`` when nothing was running."""

    steered: bool


class PendingOut(BaseModel):
    """The approval or question a run is waiting on, so a reconnecting client can answer it."""

    kind: Literal["approval", "question"]
    call_id: str
    command: str | None = None
    timeout_seconds: int | None = None
    remember_supported: bool = False
    question: str | None = None
    options: list[str] = Field(default_factory=list)
    allow_multiple: bool = False


class RunStateOut(BaseModel):
    """Whether a run is going, and what it waits on if it is."""

    running: bool
    pending: PendingOut | None = None


class ResolvedOut(BaseModel):
    """Whether an answer reached the request it named."""

    resolved: bool


class ResumableOut(BaseModel):
    """Where the conversation was interrupted, and what continuing would do."""

    resumable: bool
    kind: str | None = None
    description: str | None = None


class SideQuestionRequest(BaseModel):
    """A question answered on the side: it never joins the conversation.

    Attributes:
        question: What to ask.
        timeout: Seconds to wait for the answer, or ``None`` for no deadline.
    """

    question: str = Field(min_length=1)
    timeout: float | None = Field(default=None, gt=0)


class AnswerOut(BaseModel):
    """The answer to a side question."""

    answer: str


class PluginsOut(BaseModel):
    """The plugins this server loaded, and the ones that refused to load."""

    loaded: list[str]
    failures: list[str]


class MentionOut(BaseModel):
    """One ``@`` resource a prompt can carry, as a completion menu lists it."""

    token: str
    kind: str
    name: str
    description: str


class MentionsOut(BaseModel):
    """The ``@`` resources matching what was typed."""

    mentions: list[MentionOut]


class TotalsOut(BaseModel):
    """Token counters added up over some replies, as the usage ledger records them."""

    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    cache_share: float | None = None


class SessionTotalsOut(BaseModel):
    """One session in the workspace's usage."""

    id: str
    title: str | None = None
    started: datetime
    updated: datetime
    tokens: TotalsOut
    models: list[str] = Field(default_factory=list)
    entries: int = 0


class ModelTotalsOut(BaseModel):
    """What one model was charged across the workspace."""

    model: str
    tokens: TotalsOut


class DayTotalsOut(BaseModel):
    """What one day spent across the workspace."""

    day: date
    tokens: TotalsOut


class WorkspaceUsageOut(BaseModel):
    """What the workspace's stored sessions have spent, as the terminal's ``/usage`` page shows it."""

    sessions: list[SessionTotalsOut]
    models: list[ModelTotalsOut]
    days: list[DayTotalsOut]
    total: TotalsOut


class SessionStatsOut(BaseModel):
    """The totals one row of the terminal's ``/resume`` panel shows."""

    id: str
    entries: int = 0
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    cache_share: float | None = None


class SessionStatsListOut(BaseModel):
    """The stored totals of the sessions asked for."""

    stats: list[SessionStatsOut]


class SelfCompactionOut(BaseModel):
    """Whether the model may compact this session itself, and the session's own choice."""

    choice: bool | None = None
    effective: bool


class SelfCompactionUpdate(BaseModel):
    """A choice about self-compaction: ``true``, ``false``, or ``null`` to follow the configuration."""

    choice: bool | None = Field(default=None, strict=True)


class ModelCheckOut(BaseModel):
    """One model asked one short question by ``/doctor``."""

    model: str
    model_id: str
    ok: bool
    seconds: float
    detail: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None


class DoctorOut(BaseModel):
    """Every configured model, and whether it answers."""

    checks: list[ModelCheckOut]


class DoctorRequest(BaseModel):
    """How long each model may take to answer."""

    timeout: float = Field(default=30.0, gt=0, le=300)


class ErrorOut(BaseModel):
    """A failure, in a shape a client can branch on.

    Attributes:
        error: A stable code: ``not_found``, ``busy``, ``locked``, ``invalid``, ``timeout``, ``run``, ``internal``.
        message: The sentence the SDK gave, which is the one the terminal would show.
    """

    error: str
    message: str
