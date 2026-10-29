/** The transcript model: one turn's text, reasoning, tool calls and the events that change them. */

import type { ImageInput, Message, RunEvent, RunResult, Usage } from "../../../typescript/src/types.js";

export type TurnStatus = "running" | "done" | "failed" | "cancelled";
export type ToolStatus = "running" | "ok" | "failed" | "skipped";

export interface ToolNode {
  callId: string;
  name: string;
  arguments: Record<string, unknown>;
  output: string;
  status: ToolStatus;
  startedAt: number;
  finishedAt?: number;
}

export interface TextBlock {
  kind: "text";
  text: string;
}

export interface ReasoningBlock {
  kind: "reasoning";
  text: string;
}

export interface ToolBlock {
  kind: "tool";
  tool: ToolNode;
}

export interface NoticeBlock {
  kind: "notice";
  text: string;
  /** `warn` is something the reader may need to act on (an MCP server is down); anything else is progress. */
  level?: "info" | "warn";
}

export interface SteerBlock {
  kind: "steered";
  text: string;
  /** Drawn the moment the message was sent; true until the run reports that the model has taken it up. */
  pending?: boolean;
}

/** A change made between requests (the model, the reasoning effort, the shell permission), drawn as a line across the view. */
export interface AnnouncementBlock {
  kind: "announcement";
  text: string;
}

export interface CompactionBlock {
  kind: "compaction";
  running: boolean;
  applied: boolean;
  summary: string | null;
}

export interface ApprovalBlock {
  kind: "approval";
  callId: string;
  command: string;
  /** The directory the call runs in, when it names one instead of the workspace. */
  workDir?: string;
  /** `null` while it waits; true or false once answered or decided by a policy. */
  approved: boolean | null;
}

export interface QuestionBlock {
  kind: "question";
  callId: string;
  question: string;
  options: string[];
  allowMultiple: boolean;
  answered: boolean;
  /** The answer given, or `null` when the question was declined. */
  answer?: string | null;
}

export type Block =
  | TextBlock
  | ReasoningBlock
  | ToolBlock
  | NoticeBlock
  | SteerBlock
  | AnnouncementBlock
  | CompactionBlock
  | ApprovalBlock
  | QuestionBlock;

export interface TurnStop {
  reason: string;
  message: string | null;
}

export interface Turn {
  id: string;
  prompt: string;
  images: ImageInput[];
  /** Pictures a restored turn has, whose bytes are not in the history. */
  imageCount?: number;
  startedAt: number;
  finishedAt?: number;
  status: TurnStatus;
  blocks: Block[];
  usage?: Usage;
  stop?: TurnStop;
  error?: string;
  /** A `/btw` answer: shown beside the conversation, not part of it. */
  aside?: boolean;
  /** This turn continued an interrupted request instead of starting one. */
  resumed?: boolean;
  /** Set when another session sent the message this turn answers. */
  from?: { id: string; name: string };
  /** Set when this turn is a message another session was sent, rather than a prompt. */
  sent?: { to: string; note: string };
}

/** How much of one tool's output a transcript keeps; a runaway build log must not become the webview. */
export const MAX_TOOL_OUTPUT = 120_000;

/** A row that belongs to a command and not to the conversation carries this in its id. */
export const COMPACT_TURN = "turn-compact-";

let turnCounter = 0;

/** A new turn id, unique within this editor session. */
export function newTurnId(prefix = "turn"): string {
  turnCounter += 1;
  return `${prefix}-${Date.now().toString(36)}-${turnCounter}`;
}

/** Start the user's half of a turn. */
export function createTurn(prompt: string, images: ImageInput[] = [], now = Date.now(), id = newTurnId()): Turn {
  return {
    id,
    prompt,
    images: images.map((image) => ({ ...image })),
    startedAt: now,
    status: "running",
    blocks: [],
  };
}

/**
 * A turn that only announces a change, as the terminal does with a centred line between two rules. It has no message
 * and no answer, is over the moment it is made, and is not part of the conversation the model sees.
 */
export function announcement(text: string, now = Date.now(), id = newTurnId()): Turn {
  const turn = createTurn("", [], now, id);
  turn.aside = true;
  turn.status = "done";
  turn.finishedAt = now;
  turn.blocks.push({ kind: "announcement", text });
  return turn;
}

/** Whether a turn is one of those announcements and nothing else. */
export function isAnnouncement(turn: Turn): boolean {
  return turn.prompt === "" && turn.blocks.length === 1 && turn.blocks[0]?.kind === "announcement";
}

/** Apply one stream event to a running turn. */
export function applyEvent(turn: Turn, event: RunEvent, now = Date.now()): void {
  switch (event.type) {
    case "text_delta":
      appendText(turn, "text", event.text);
      return;
    case "reasoning_delta":
      appendText(turn, "reasoning", event.text);
      return;
    case "tool_started": {
      const existing = findTool(turn, event.call_id);
      if (existing) {
        existing.name = event.name;
        existing.arguments = event.arguments;
        existing.status = "running";
        existing.startedAt = now;
      } else {
        turn.blocks.push({
          kind: "tool",
          tool: {
            callId: event.call_id,
            name: event.name,
            arguments: event.arguments,
            output: "",
            status: "running",
            startedAt: now,
          },
        });
      }
      return;
    }
    case "tool_finished": {
      const tool = findTool(turn, event.call_id);
      const node: ToolNode =
        tool ??
        {
          callId: event.call_id,
          name: event.name,
          arguments: {},
          output: "",
          status: "running",
          startedAt: now,
        };
      if (!tool) {
        turn.blocks.push({ kind: "tool", tool: node });
      }
      node.name = event.name;
      node.output = capOutput(event.output);
      node.status = event.skipped ? "skipped" : event.ok ? "ok" : "failed";
      node.finishedAt = now;
      settleCall(turn, event.call_id);
      return;
    }
    case "server_tool_started": {
      // A hosted tool — a web search, a fetch — is run by the endpoint: it has no permission and no skip, and its
      // row is the same shape as a local tool's, so one renderer draws both.
      const existing = findTool(turn, event.call_id);
      if (existing) {
        existing.name = event.name;
        existing.arguments = event.arguments;
        existing.status = "running";
        existing.startedAt = now;
      } else {
        turn.blocks.push({
          kind: "tool",
          tool: {
            callId: event.call_id,
            name: event.name,
            arguments: event.arguments,
            output: "",
            status: "running",
            startedAt: now,
          },
        });
      }
      return;
    }
    case "server_tool_finished": {
      const tool = findTool(turn, event.call_id);
      const node: ToolNode =
        tool ?? {
          callId: event.call_id,
          name: event.name,
          arguments: {},
          output: "",
          status: "running",
          startedAt: now,
        };
      if (!tool) {
        turn.blocks.push({ kind: "tool", tool: node });
      }
      node.name = event.name;
      node.arguments = { ...node.arguments, ...event.arguments };
      node.output = capOutput(event.output);
      node.status = event.ok ? "ok" : "failed";
      node.finishedAt = now;
      settleCall(turn, event.call_id);
      return;
    }
    case "approval_requested": {
      const block: ApprovalBlock = {
        kind: "approval",
        callId: event.call_id,
        command: event.command,
        workDir: event.work_dir ?? undefined,
        approved: event.approved,
      };
      const existing = turn.blocks.find(
        (candidate): candidate is ApprovalBlock => candidate.kind === "approval" && candidate.callId === event.call_id,
      );
      if (existing) {
        existing.command = event.command;
        existing.workDir = event.work_dir ?? undefined;
        existing.approved = event.approved;
      } else {
        turn.blocks.push(block);
      }
      if (event.approved !== null) {
        markApproval(turn, event.call_id, event.approved);
      }
      return;
    }
    case "question_asked": {
      const existing = turn.blocks.find(
        (candidate): candidate is QuestionBlock => candidate.kind === "question" && candidate.callId === event.call_id,
      );
      if (existing) {
        existing.question = event.question;
        existing.options = event.options;
        existing.allowMultiple = event.allow_multiple;
        existing.answered = existing.answered || event.answered;
      } else {
        turn.blocks.push({
          kind: "question",
          callId: event.call_id,
          question: event.question,
          options: event.options,
          allowMultiple: event.allow_multiple,
          answered: event.answered,
        });
      }
      return;
    }
    case "usage_updated":
      turn.usage = event.usage;
      return;
    case "compaction_started":
      turn.blocks.push({ kind: "compaction", running: true, applied: false, summary: null });
      return;
    case "compaction_finished": {
      const running = findLastCompaction(turn);
      if (running) {
        running.running = false;
        running.applied = event.applied;
        running.summary = event.summary;
      } else {
        turn.blocks.push({ kind: "compaction", running: false, applied: event.applied, summary: event.summary });
      }
      return;
    }
    case "model_stopped":
      turn.stop = { reason: event.reason, message: event.message };
      return;
    case "steered": {
      // A steer is drawn the moment it is sent; the run reporting it later settles that block instead of adding a second.
      const waiting = turn.blocks.find(
        (block): block is SteerBlock => block.kind === "steered" && block.pending === true && block.text === event.text,
      );
      if (waiting) {
        waiting.pending = false;
      } else {
        turn.blocks.push({ kind: "steered", text: event.text });
      }
      return;
    }
    case "notice":
      turn.blocks.push({ kind: "notice", text: event.text, level: event.level === "warn" ? "warn" : "info" });
      return;
    case "finished":
      if (event.text && !turn.blocks.some((block) => block.kind === "text")) {
        turn.blocks.push({ kind: "text", text: event.text });
      }
      return;
    case "event":
      turn.blocks.push({ kind: "notice", text: `A newer server sent an event this client does not know: ${event.name}` });
      return;
    default:
      return;
  }
}

/** Draw a message the reader steers into a running request, at once, before the run reports it. */
export function echoSteer(turn: Turn, text: string): SteerBlock {
  const block: SteerBlock = { kind: "steered", text, pending: true };
  turn.blocks.push(block);
  return block;
}

/** Take back a steer that never reached a run. */
export function retractSteer(turn: Turn, block: SteerBlock): void {
  const index = turn.blocks.indexOf(block);
  if (index >= 0) {
    turn.blocks.splice(index, 1);
  }
}

/** Finish a turn with the run's result, without duplicating text that was already streamed. */
export function finishTurn(turn: Turn, result: RunResult, now = Date.now()): void {
  if (!turn.blocks.some((block) => block.kind === "text") && result.text) {
    turn.blocks.push({ kind: "text", text: result.text });
  }
  turn.usage = result.usage;
  if (result.stop) {
    turn.stop = { reason: result.stop, message: result.stop_message };
  }
  turn.status = "done";
  turn.finishedAt = now;
  turn.error = undefined;
  settlePending(turn, now);
}

/** Mark a turn failed with a message the transcript can show. */
export function failTurn(turn: Turn, message: string, now = Date.now()): void {
  turn.status = "failed";
  turn.error = message;
  turn.finishedAt = now;
  settlePending(turn, now);
}

/** Mark a turn stopped by the reader. */
export function cancelTurn(turn: Turn, now = Date.now()): void {
  turn.status = "cancelled";
  turn.finishedAt = now;
  settlePending(turn, now);
}

/** Record an approval the reader gave (or refused). */
export function markApproval(turn: Turn, callId: string, approve: boolean): void {
  for (const block of turn.blocks) {
    if (block.kind === "approval" && block.callId === callId) {
      block.approved = approve;
    }
  }
}

/** Record an answer to a question; `null` declines it. */
export function markAnswer(turn: Turn, callId: string, answer: string | null): void {
  for (const block of turn.blocks) {
    if (block.kind === "question" && block.callId === callId) {
      block.answered = true;
      block.answer = answer;
      if (answer !== null && !block.options.includes(answer)) {
        block.options = [...block.options, answer];
      }
    }
  }
}

/** Return the tool a call id names, or `null`. */
export function findTool(turn: Turn, callId: string): ToolNode | null {
  for (const block of turn.blocks) {
    if (block.kind === "tool" && block.tool.callId === callId) {
      return block.tool;
    }
  }
  return null;
}

/** The turn waiting on a call id, if one is. */
export function findTurnByCall(turns: Turn[], callId: string): Turn | null {
  for (const turn of turns) {
    for (const block of turn.blocks) {
      if ((block.kind === "approval" || block.kind === "question") && block.callId === callId) {
        return turn;
      }
      if (block.kind === "tool" && block.tool.callId === callId) {
        return turn;
      }
    }
  }
  return null;
}

/** What a turn took, once it has finished. */
export function turnDuration(turn: Turn): number | null {
  return turn.finishedAt === undefined ? null : Math.max(0, turn.finishedAt - turn.startedAt);
}

/**
 * Turn stored messages back into turns.
 *
 * History keeps an assistant message's tool calls without their output; the matching `tool` message carries it. Both
 * are folded into the same tool row, so an old conversation looks like the live one.
 */
export function restoreTurns(messages: Message[], now = Date.now()): Turn[] {
  const turns: Turn[] = [];
  const tools = new Map<string, ToolNode>();
  // What each turn spent, folded from the model calls the store recorded and the time every message took.
  const spent = new Map<Turn, { usage: Usage; milliseconds: number }>();
  let current: Turn | null = null;

  const account = (turn: Turn, message: Message): void => {
    const entry = spent.get(turn) ?? { usage: emptyUsage(), milliseconds: 0 };
    entry.milliseconds += Math.max(0, (message.seconds ?? 0) * 1000);
    const usage = message.usage;
    if (usage) {
      entry.usage.input_tokens += usage.input_tokens;
      entry.usage.output_tokens += usage.output_tokens;
      entry.usage.cache_read_tokens += usage.cache_read_tokens;
      entry.usage.cache_write_tokens += usage.cache_write_tokens;
      entry.usage.reasoning_tokens += usage.reasoning_tokens;
      entry.usage.seconds += usage.seconds;
      entry.usage.requests += Math.max(1, usage.requests);
    }
    spent.set(turn, entry);
  };

  const start = (prompt: string, id: string, imageCount = 0): Turn => {
    const turn: Turn = {
      id,
      prompt,
      images: [],
      imageCount,
      startedAt: now,
      status: "done",
      blocks: [],
    };
    turns.push(turn);
    tools.clear();
    current = turn;
    return turn;
  };

  messages.forEach((message, index) => {
    if (message.role === "summary") {
      // What a compaction left in place of the older messages: drawn as the compaction it was, not as something said.
      const row = createTurn("", [], now, `${COMPACT_TURN}history-${index}`);
      row.aside = true;
      row.status = "done";
      row.finishedAt = now;
      row.blocks.push({ kind: "compaction", running: false, applied: true, summary: message.text });
      turns.push(row);
      tools.clear();
      current = null;
      return;
    }
    if (message.role === "user") {
      const turn = start(message.text, `history-${index}`);
      // The pictures come back with the history; a count is all that is left when the store could not give them.
      const pictures = message.pictures ?? [];
      if (pictures.length > 0) {
        turn.images = pictures.map((picture) => ({ data: picture.data, mediaType: picture.media_type }));
      }
      if (message.images > pictures.length) {
        turn.imageCount = message.images - pictures.length;
      }
      return;
    }
    if (message.role === "tool") {
      if (!current) {
        return;
      }
      const callId = message.tool_call_id ?? `history-tool-${index}`;
      let node = tools.get(callId);
      if (!node) {
        node = {
          callId,
          name: message.tool_name ?? "tool",
          arguments: {},
          output: "",
          status: message.ok ? "ok" : "failed",
          startedAt: now,
        };
        current.blocks.push({ kind: "tool", tool: node });
        tools.set(callId, node);
      }
      node.output = capOutput(message.text ?? "");
      node.status = message.ok ? "ok" : "failed";
      node.finishedAt = now;
      account(current, message);
      return;
    }
    if (message.role !== "assistant") {
      return;
    }
    const turn: Turn = current ?? start("", `history-${index}`);
    account(turn, message);
    if (message.text) {
      appendText(turn, "text", message.text);
    }
    for (const call of message.tool_calls ?? []) {
      const node: ToolNode = {
        callId: call.call_id,
        name: call.name,
        arguments: call.arguments ?? {},
        output: "",
        status: "running",
        startedAt: now,
      };
      turn.blocks.push({ kind: "tool", tool: node });
      tools.set(call.call_id, node);
    }
  });

  for (const turn of turns) {
    for (const block of turn.blocks) {
      if (block.kind === "tool" && block.tool.status === "running") {
        block.tool.status = "ok";
      }
    }
    turn.status = "done";
    turn.finishedAt = now;
    const entry = spent.get(turn);
    if (entry !== undefined) {
      if (entry.usage.requests > 0) {
        turn.usage = entry.usage;
      }
      turn.finishedAt = now + Math.round(entry.milliseconds);
    }
  }

  return turns;
}

function emptyUsage(): Usage {
  return {
    input_tokens: 0,
    output_tokens: 0,
    cache_read_tokens: 0,
    cache_write_tokens: 0,
    reasoning_tokens: 0,
    seconds: 0,
    requests: 0,
    context_tokens: 0,
  };
}

function appendText(turn: Turn, kind: "text" | "reasoning", text: string): void {
  if (!text) {
    return;
  }
  const last = turn.blocks[turn.blocks.length - 1];
  if (last?.kind === kind) {
    last.text += text;
    return;
  }
  turn.blocks.push(kind === "text" ? { kind: "text", text } : { kind: "reasoning", text });
}

function capOutput(output: string): string {
  if (output.length <= MAX_TOOL_OUTPUT) {
    return output;
  }
  return `${output.slice(0, MAX_TOOL_OUTPUT)}\n\n… the rest of this output was left out (${output.length - MAX_TOOL_OUTPUT} characters)`;
}

/** A tool ending answers anything still waiting on that call: a timeout denies and a decline is an answer. */
function settleCall(turn: Turn, callId: string): void {
  for (const block of turn.blocks) {
    if (block.kind === "approval" && block.callId === callId && block.approved === null) {
      block.approved = false;
    }
    if (block.kind === "question" && block.callId === callId && !block.answered) {
      block.answered = true;
      block.answer = null;
    }
  }
}

/**
 * A run that ends cannot still be waiting or working: an approval was denied before the stream closed, a question the
 * stop left unanswered is no longer waiting for anyone, and a tool the run left behind (stopped, replaced by a new
 * message, or lost with the connection) will never report back. It ends as skipped, so no spinner turns for ever on a
 * turn that is over.
 */
function settlePending(turn: Turn, now = Date.now()): void {
  for (const block of turn.blocks) {
    if (block.kind === "approval" && block.approved === null) {
      block.approved = false;
    }
    if (block.kind === "question" && !block.answered) {
      block.answered = true;
      block.answer = null;
    }
    if (block.kind === "tool" && block.tool.status === "running") {
      block.tool.status = "skipped";
      block.tool.finishedAt = now;
    }
    if (block.kind === "compaction" && block.running) {
      block.running = false;
    }
    if (block.kind === "steered") {
      block.pending = false;
    }
  }
}

function findLastCompaction(turn: Turn): CompactionBlock | null {
  for (let index = turn.blocks.length - 1; index >= 0; index -= 1) {
    const block = turn.blocks[index];
    if (block?.kind === "compaction" && block.running) {
      return block;
    }
  }
  return null;
}
