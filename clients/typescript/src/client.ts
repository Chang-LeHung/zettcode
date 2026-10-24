/** The client for `zettcode-server`: every endpoint, and a `Run` that streams one prompt and can answer it. */

import { RunCancelledError, RunFailedError, ZettCodeError } from "./errors.js";
import { sseFrames } from "./sse.js";
import type {
  ApprovalPolicy,
  Compaction,
  ContextReport,
  CurrentSession,
  Health,
  ImageInput,
  Mention,
  Message,
  ModelCheck,
  ModelInfo,
  ModelInput,
  ModelUpdate,
  Permission,
  Plugins,
  PromptOptions,
  RunEvent,
  RunOptions,
  RunResult,
  RunState,
  Resumable,
  SelfCompaction,
  SessionInfo,
  SessionStatsInfo,
  Settings,
  SettingsUpdate,
  StreamFrame,
  Usage,
  WaitingMessage,
  WorkspaceUsage,
} from "./types.js";

/** Where the client points, and how it authenticates. */
export interface ClientOptions {
  /** The server's address; `http://127.0.0.1:3290` by default. */
  baseUrl?: string;
  /** The bearer token, when the server was started with one. */
  token?: string;
  /** Headers added to every request. */
  headers?: Record<string, string>;
  /** The `fetch` to use; the global one by default, which Node 18+ and every editor host has. */
  fetch?: typeof globalThis.fetch;
}

/** A failure body, as every endpoint writes it. */
interface ErrorBody {
  error?: string;
  message?: string;
  detail?: unknown;
}

const DEFAULT_BASE = "http://127.0.0.1:3290";

/** The client: one server, one workspace, every endpoint. */
export class ZettCodeClient {
  /** The server's address without a trailing slash. */
  readonly baseUrl: string;
  private readonly token: string | undefined;
  private readonly extraHeaders: Record<string, string>;
  private readonly fetchImpl: typeof globalThis.fetch;

  constructor(options: ClientOptions = {}) {
    this.baseUrl = (options.baseUrl ?? DEFAULT_BASE).replace(/\/+$/, "");
    this.token = options.token;
    this.extraHeaders = options.headers ?? {};
    this.fetchImpl = options.fetch ?? globalThis.fetch;
    if (typeof this.fetchImpl !== "function") {
      throw new ZettCodeError("This runtime has no fetch; pass one in ClientOptions");
    }
  }

  // -- transport ---------------------------------------------------------
  /** Add the headers every request carries: JSON in, JSON out, and the token. */
  private headers(extra: Record<string, string> = {}): Record<string, string> {
    const headers: Record<string, string> = { ...this.extraHeaders, ...extra };
    if (this.token) {
      headers.authorization = `Bearer ${this.token}`;
    }
    return headers;
  }

  /** Send one request and return the response, refusing an error body with its status and code. */
  async raw(path: string, init: RequestInit = {}): Promise<Response> {
    const response = await this.fetchImpl(`${this.baseUrl}${path}`, {
      ...init,
      headers: this.headers((init.headers as Record<string, string>) ?? {}),
    });
    if (!response.ok) {
      throw await failure(response);
    }
    return response;
  }

  /** Send one request and parse its JSON answer. */
  async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await this.raw(path, init);
    return (await response.json()) as T;
  }

  private json(method: string, body: unknown): RequestInit {
    return {
      method,
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    };
  }

  // -- health, models, settings -----------------------------------------
  /** Whether the server is up, and which session it serves. No token needed. */
  health(): Promise<Health> {
    return this.request<Health>("/health");
  }

  /** Every configured model, with the active one marked; works before a model is configured. */
  async models(): Promise<{ models: ModelInfo[]; current: string | null }> {
    return this.request("/models");
  }

  /**
   * Add a model to the configuration file, and use it when the server had none.
   *
   * This is how a fresh server becomes usable: it starts without a model, and the first one added builds the agent.
   */
  addModel(model: ModelInput): Promise<{ models: ModelInfo[]; current: string | null }> {
    return this.request("/models", this.json("POST", model));
  }

  /** Change one model (named by its display name or its id); the token is kept unless a new one is given. */
  updateModel(name: string, changes: ModelUpdate): Promise<{ models: ModelInfo[]; current: string | null }> {
    return this.request(`/models/${encodeURIComponent(name)}`, this.json("PATCH", changes));
  }

  /** Remove a model; the last one cannot go, because a configuration with no models cannot run. */
  removeModel(name: string): Promise<{ models: ModelInfo[]; current: string | null }> {
    return this.request(`/models/${encodeURIComponent(name)}`, { method: "DELETE" });
  }

  /** The model, effort and permission the next prompt uses. */
  settings(): Promise<Settings> {
    return this.request<Settings>("/settings");
  }

  /** Change what the next prompt starts with; a field left out stays as it is. */
  updateSettings(update: SettingsUpdate): Promise<Settings> {
    return this.request<Settings>("/settings", this.json("PATCH", update));
  }

  /** The plugins the server loaded, and the ones that failed. */
  plugins(): Promise<Plugins> {
    return this.request<Plugins>("/plugins");
  }

  // -- sessions ----------------------------------------------------------
  /** The stored sessions of the workspace, most recently active first. */
  async listSessions(limit = 20): Promise<SessionInfo[]> {
    const body = await this.request<{ sessions: SessionInfo[] }>(`/sessions?limit=${encodeURIComponent(String(limit))}`);
    return body.sessions;
  }

  /** Start an empty conversation and make it current. */
  createSession(title?: string): Promise<SessionInfo> {
    return this.request<SessionInfo>("/sessions", this.json("POST", title === undefined ? {} : { title }));
  }

  /** The conversation the next prompt continues. */
  currentSession(): Promise<CurrentSession> {
    return this.request<CurrentSession>("/sessions/current");
  }

  /** Continue a stored conversation; the next prompt goes to it. */
  openSession(sessionId: string): Promise<CurrentSession> {
    return this.request<CurrentSession>(`/sessions/${encodeURIComponent(sessionId)}/open`, { method: "POST" });
  }

  /** Name the current conversation. */
  renameSession(title: string): Promise<SessionInfo> {
    return this.request<SessionInfo>("/sessions/current/rename", this.json("POST", { title }));
  }

  /** Ask the model for a name, and give the conversation one. */
  nameSession(): Promise<SessionInfo> {
    return this.request<SessionInfo>("/sessions/current/name", { method: "POST" });
  }

  /** Carry this conversation's context into a new session and continue there. */
  forkSession(): Promise<CurrentSession> {
    return this.request<CurrentSession>("/sessions/current/fork", { method: "POST" });
  }

  /** Summarize the conversation now; `applied` is false when there was nothing to fold. */
  compactSession(): Promise<Compaction> {
    return this.request<Compaction>("/sessions/current/compact", { method: "POST" });
  }

  /** How full the context window is, or `null` before a request has been measured. */
  context(): Promise<ContextReport | null> {
    return this.request<ContextReport | null>("/sessions/current/context");
  }

  /**
   * The messages the model is working with, oldest first. With `full`, the whole conversation as it was written: what a
   * compaction folded away is there, and each summary (role `summary`) stands where it was made.
   */
  async history(options: { full?: boolean } = {}): Promise<Message[]> {
    const query = options.full === true ? "?full=true" : "";
    const body = await this.request<{ messages: Message[] }>(`/sessions/current/history${query}`);
    return body.messages;
  }

  /** The conversation as a standalone HTML page. */
  async exportSession(): Promise<string> {
    const response = await this.raw("/sessions/current/export");
    return response.text();
  }

  /** Ask something answered from the conversation but kept out of it, as `/btw` does. */
  async ask(question: string, timeout?: number): Promise<string> {
    const body = await this.request<{ answer: string }>(
      "/sessions/current/ask",
      this.json("POST", timeout === undefined ? { question } : { question, timeout }),
    );
    return body.answer;
  }

  /** `ask`, with the answer streamed: iterate the run for `text_delta` events, or await `run.result`. */
  askStream(question: string, timeout?: number, options: RunOptions = {}): Run {
    return new Run(
      this,
      "/sessions/current/ask/stream",
      timeout === undefined ? { question } : { question, timeout },
      options,
    );
  }

  /** What this session has spent. */
  usage(): Promise<Usage> {
    return this.request<Usage>("/usage");
  }

  /** What every stored session of the workspace spent, as the terminal's `/usage` page shows it. */
  usageLedger(): Promise<WorkspaceUsage> {
    return this.request<WorkspaceUsage>("/usage/ledger");
  }

  /** The stored totals of some sessions, or of the current one: the `/resume` panel's columns. */
  async sessionStats(ids?: string[]): Promise<SessionStatsInfo[]> {
    if (ids === undefined) {
      const current = await this.request<SessionStatsInfo | null>("/sessions/current/stats");
      return current === null ? [] : [current];
    }
    if (ids.length === 0) {
      return [];
    }
    const query = encodeURIComponent(ids.join(","));
    const body = await this.request<{ stats: SessionStatsInfo[] }>(`/sessions/stats?ids=${query}`);
    return body.stats;
  }

  /** Whether the model may compact this session itself, and the session's own choice. */
  selfCompaction(): Promise<SelfCompaction> {
    return this.request<SelfCompaction>("/sessions/current/self-compaction");
  }

  /** Let the model compact this session itself, stop it, or follow the configuration with `null`. */
  setSelfCompaction(choice: boolean | null): Promise<SelfCompaction> {
    return this.request<SelfCompaction>("/sessions/current/self-compaction", this.json("PUT", { choice }));
  }

  /** The files, skills and plugin resources an `@` in a prompt can reference. */
  async mentions(query = "", limit = 50): Promise<Mention[]> {
    const body = await this.request<{ mentions: Mention[] }>(
      `/mentions?query=${encodeURIComponent(query)}&limit=${encodeURIComponent(String(limit))}`,
    );
    return body.mentions;
  }

  /** The messages other sessions sent that this chat has not answered yet, oldest first. */
  async messages(): Promise<WaitingMessage[]> {
    const body = await this.request<{ messages: WaitingMessage[] }>("/messages");
    return body.messages;
  }

  /** Ask every configured model one short question and report which of them answer, as `zettcode doctor`. */
  async doctor(timeout = 30): Promise<ModelCheck[]> {
    const body = await this.request<{ checks: ModelCheck[] }>("/doctor", this.json("POST", { timeout }));
    return body.checks;
  }

  // -- running -----------------------------------------------------------
  /** Run one prompt and stream it. Iterate `run.events`, await `run.result`, or both. */
  prompt(text: string, options: PromptOptions = {}): Run {
    const body: Record<string, unknown> = {
      text,
      ...wireOptions(options),
    };
    if (options.images) {
      body.images = options.images.map((image) => ({ data: image.data, media_type: image.mediaType }));
    }
    if (options.mentions !== undefined) {
      body.mentions = options.mentions;
    }
    return new Run(this, "/prompts", body, options);
  }

  /** Continue the interrupted request where it stopped, streaming it like `prompt`. */
  resume(options: RunOptions = {}): Run {
    return new Run(this, "/runs/resume", wireOptions(options), options);
  }

  /** Answer one message another session sent, streaming the turn exactly as `prompt` does. */
  answerMessage(id: string, options: RunOptions = {}): Run {
    return new Run(this, `/messages/${encodeURIComponent(id)}`, wireOptions(options), options);
  }

  /** Send a message to another session, as a draft beginning with `@name` does; returns who took it. */
  sendMessage(to: string, text: string): Promise<{ to: string; disposition: string }> {
    return this.request<{ to: string; disposition: string }>(
      "/sessions/current/send",
      this.json("POST", { to, text }),
    );
  }

  /** Whether a run is going, and what it waits on. */
  runState(): Promise<RunState> {
    return this.request<RunState>("/runs/current");
  }

  /** Where the conversation was interrupted, or that it was not. */
  resumable(): Promise<Resumable> {
    return this.request<Resumable>("/runs/resumable");
  }

  /** Approve or deny a shell command a run is suspended on. */
  async approve(callId: string, approve: boolean, remember = false): Promise<boolean> {
    const body = await this.request<{ resolved: boolean }>(
      "/runs/approvals",
      this.json("POST", { call_id: callId, approve, remember }),
    );
    return body.resolved;
  }

  /** Answer a question a run is suspended on; `null` declines it. */
  async answer(callId: string, answer: string | null): Promise<boolean> {
    const body = await this.request<{ resolved: boolean }>("/runs/questions", this.json("POST", { call_id: callId, answer }));
    return body.resolved;
  }

  /** Send a message into the run in progress; false when nothing was running to take it. */
  async steer(text: string): Promise<boolean> {
    const body = await this.request<{ steered: boolean }>("/runs/steer", this.json("POST", { text }));
    return body.steered;
  }

  /** Stop the run in progress; its stream then ends with `cancelled`. */
  async cancelRun(): Promise<boolean> {
    const body = await this.request<{ cancelled: boolean }>("/runs/cancel", { method: "POST" });
    return body.cancelled;
  }
}

/** Translate the client's camelCase run options into the wire's snake_case, dropping what was not set. */
export function wireOptions(options: RunOptions): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  if (options.approvals !== undefined) {
    const policy: Record<string, unknown> = { mode: options.approvals.mode ?? "deny" };
    if (options.approvals.commands !== undefined) {
      policy.commands = options.approvals.commands;
    }
    body.approvals = policy;
  }
  if (options.questions !== undefined) body.questions = options.questions;
  if (options.timeout !== undefined) body.timeout = options.timeout;
  if (options.answerTimeout !== undefined) body.answer_timeout = options.answerTimeout;
  if (options.keepEvents !== undefined) body.keep_events = options.keepEvents;
  return body;
}

/** One prompt: the frames as they arrive, the result as a promise, and the answers it may need. */
export class Run implements AsyncIterable<StreamFrame> {
  /** The frames of the run, in order, ending after `result`, `error` or `cancelled`. */
  readonly events: AsyncIterable<StreamFrame>;
  /** Resolves with the run's result; rejects with `RunFailedError` or `RunCancelledError`. */
  readonly result: Promise<RunResult>;

  private readonly client: ZettCodeClient;
  private readonly path: string;
  private readonly body: Record<string, unknown>;
  private readonly options: RunOptions;
  private readonly queue = new EventQueue<StreamFrame>();
  private readonly controller = new AbortController();
  private settle!: (result: RunResult) => void;
  private fail!: (error: Error) => void;
  private settled = false;

  constructor(client: ZettCodeClient, path: string, body: Record<string, unknown>, options: RunOptions = {}) {
    this.client = client;
    this.path = path;
    this.body = body;
    this.options = options;
    this.events = {
      [Symbol.asyncIterator]: () => this.queue[Symbol.asyncIterator](),
    };
    this.result = new Promise<RunResult>((resolve, reject) => {
      this.settle = (result) => {
        if (!this.settled) {
          this.settled = true;
          resolve(result);
        }
      };
      this.fail = (error) => {
        if (!this.settled) {
          this.settled = true;
          reject(error);
        }
      };
    });
    // The promise is consumed by whoever asks for it; an unhandled rejection must not crash the process.
    this.result.catch(() => undefined);
    if (options.signal) {
      if (options.signal.aborted) {
        this.controller.abort(options.signal.reason);
      } else {
        options.signal.addEventListener("abort", () => this.controller.abort(options.signal?.reason), { once: true });
      }
    }
    void this.start();
  }

  /** The run's own signal, already linked to the one the caller passed. */
  get signal(): AbortSignal {
    return this.controller.signal;
  }

  /** Iterate the frames directly: `for await (const frame of run)`, as well as `run.events`. */
  [Symbol.asyncIterator](): AsyncIterator<StreamFrame> {
    return this.queue[Symbol.asyncIterator]();
  }

  /** Run one prompt, streaming everything it says, in order. */
  private async start(): Promise<void> {
    try {
      const response = await this.client.raw(this.path, {
        method: "POST",
        headers: { "content-type": "application/json", accept: "text/event-stream" },
        body: JSON.stringify(this.body),
        signal: this.controller.signal,
      });
      if (!response.body) {
        throw new RunFailedError("The server answered without a stream");
      }
      for await (const frame of sseFrames(response.body, this.controller.signal)) {
        this.options.onEvent?.(frame);
        this.queue.push(frame);
        if (frame.event === "result") {
          this.queue.end();
          this.settle(frame.data as RunResult);
          return;
        }
        if (frame.event === "error") {
          const payload = frame.data as { error?: string; message?: string };
          const error = new RunFailedError(payload.message ?? "The run failed", payload.error ?? "run");
          this.queue.end();
          this.fail(error);
          return;
        }
        if (frame.event === "cancelled") {
          this.queue.end();
          this.fail(new RunCancelledError());
          return;
        }
        await this.answerIfAsked(frame);
      }
      throw new RunFailedError("The stream ended without a result");
    } catch (error) {
      const failure = error instanceof Error ? error : new Error(String(error));
      this.queue.fail(failure);
      this.fail(failure instanceof ZettCodeError ? failure : new RunFailedError(failure.message));
    }
  }

  /** Call the caller's handler for an approval or question, and post the answer back. */
  private async answerIfAsked(frame: StreamFrame): Promise<void> {
    const data = frame.data as RunEvent;
    if (frame.event !== "event" || typeof data !== "object" || data === null || !("type" in data)) {
      return;
    }
    if (data.type === "approval_requested" && this.options.onApproval) {
      const request = data;
      const approve = await this.options.onApproval({
        call_id: request.call_id,
        command: request.command,
        timeout_seconds: null,
      });
      await this.client.approve(request.call_id, approve);
    } else if (data.type === "question_asked" && this.options.onQuestion) {
      const request = data;
      const answer = await this.options.onQuestion({
        call_id: request.call_id,
        question: request.question,
        options: request.options ?? [],
        allow_multiple: request.allow_multiple ?? false,
      });
      await this.client.answer(request.call_id, answer);
    }
  }

  /** Approve or deny a shell command this run is suspended on. */
  approve(callId: string, approve: boolean, remember = false): Promise<boolean> {
    return this.client.approve(callId, approve, remember);
  }

  /** Answer a question this run is suspended on; `null` declines it. */
  answer(callId: string, answer: string | null): Promise<boolean> {
    return this.client.answer(callId, answer);
  }

  /** Send a message into this run while it is going. */
  steer(text: string): Promise<boolean> {
    return this.client.steer(text);
  }

  /** Stop this run; its stream ends with `cancelled`. */
  cancel(): Promise<boolean> {
    return this.client.cancelRun();
  }

  /** Close the connection, which also stops the run on the server. */
  abort(): void {
    this.controller.abort();
  }
}

/** A queue that turns pushes into an async iterable, and endings into the end of iteration. */
class EventQueue<T> {
  private readonly items: T[] = [];
  private readonly waiters: ((result: IteratorResult<T>) => void)[] = [];
  private ended = false;
  private error: unknown;

  push(item: T): void {
    if (this.ended) {
      return;
    }
    const waiter = this.waiters.shift();
    if (waiter) {
      waiter({ value: item, done: false });
    } else {
      this.items.push(item);
    }
  }

  end(): void {
    this.ended = true;
    for (const waiter of this.waiters.splice(0)) {
      waiter({ value: undefined, done: true });
    }
  }

  fail(error: unknown): void {
    this.error = error;
    this.end();
  }

  [Symbol.asyncIterator](): AsyncIterator<T> {
    return {
      next: () => {
        const item = this.items.shift();
        if (item !== undefined) {
          return Promise.resolve({ value: item, done: false });
        }
        if (this.error) {
          const error = this.error;
          this.error = undefined;
          return Promise.reject(error);
        }
        if (this.ended) {
          return Promise.resolve({ value: undefined, done: true });
        }
        return new Promise<IteratorResult<T>>((resolve) => this.waiters.push(resolve));
      },
    };
  }
}

/** Turn a failed response into the error the server described, or one built from the status. */
export async function failure(response: Response): Promise<ZettCodeError> {
  let body: ErrorBody = {};
  try {
    body = (await response.json()) as ErrorBody;
  } catch {
    // A body that is not JSON (a proxy page, an empty one) is reported by its status alone.
  }
  const message =
    body.message ??
    (typeof body.detail === "string" ? body.detail : undefined) ??
    response.statusText ??
    `HTTP ${response.status}`;
  const code = body.error ?? (response.status === 401 ? "unauthorized" : response.status === 404 ? "not_found" : "invalid");
  return new ZettCodeError(message, code, response.status);
}

export type { ApprovalPolicy, ImageInput, Permission, Usage };
