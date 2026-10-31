/** The client for `zettcode-server`: every endpoint, and a `Run` that streams one prompt and can answer it. */

import { RunCancelledError, RunFailedError, ZettCodeError } from "./errors.js";
import { sseFrames } from "./sse.js";
import type {
  CommandAnswer,
  CommandInfo,
  ApprovalPolicy,
  Compaction,
  ContextReport,
  CurrentSession,
  Disposition,
  Health,
  ImageInput,
  MentionInfo,
  Message,
  ModelCheck,
  ModelInfo,
  ModelInput,
  ModelUpdate,
  Permission,
  PluginEntry,
  PluginReport,
  PromptOptions,
  RunEvent,
  RunOptions,
  RunResult,
  RunState,
  ResumeInfo,
  SelfCompaction,
  SendMode,
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

/** The request init for a JSON body. */
function jsonInit(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  };
}

/** The client: one server, one workspace, every endpoint. */
export class ZettCodeClient {
  /** The server's address without a trailing slash. */
  readonly baseUrl: string;
  private readonly token: string | undefined;
  private readonly extraHeaders: Record<string, string>;
  private readonly fetchImpl: typeof globalThis.fetch;
  /** The stored conversations: `list`, `new`, `open`, `latest`. */
  readonly sessions: Sessions;
  /** The current conversation: `rename`, `fork`, `compact`, `history`, `ask`, `prompt` and the rest. */
  readonly session: Session;

  constructor(options: ClientOptions = {}) {
    this.baseUrl = (options.baseUrl ?? DEFAULT_BASE).replace(/\/+$/, "");
    this.token = options.token;
    this.extraHeaders = options.headers ?? {};
    this.fetchImpl = options.fetch ?? globalThis.fetch;
    if (typeof this.fetchImpl !== "function") {
      throw new ZettCodeError("This runtime has no fetch; pass one in ClientOptions");
    }
    this.sessions = new Sessions(this);
    this.session = new Session(this);
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
    return jsonInit(method, body);
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

  /** Choose the model the next prompt uses, by the name `models()` lists. */
  useModel(name: string): Promise<Settings> {
    return this.updateSettings({ model: name });
  }

  /** Choose the reasoning level. */
  useEffort(name: string): Promise<Settings> {
    return this.updateSettings({ effort: name });
  }

  /** Choose the shell permission level; it applies from the next shell command. */
  usePermission(name: Permission | "auto"): Promise<Settings> {
    return this.updateSettings({ permission: name });
  }

  /** Turn the just-in-time harness on or off for the prompts that follow. */
  useHarness(on: boolean): Promise<Settings> {
    return this.updateSettings({ harness: on });
  }

  /** The plugins the server loaded, the ones that failed, and every one a switch can reach. */
  plugins(): Promise<PluginReport> {
    return this.request<PluginReport>("/plugins");
  }

  /**
   * Turn one plugin's work on or off for the next start, and read it as the list now shows it.
   *
   * Nothing loads or unloads in the running server: a switch is read once, when a process starts. A compiled-in plugin
   * is switched by a configuration key, an installed one by the plugin switch file. Call `plugins()` again for the
   * whole list, and restart the server for the change to take effect.
   */
  setPluginEnabled(name: string, enabled: boolean): Promise<PluginEntry> {
    return this.request<PluginEntry>(`/plugins/${encodeURIComponent(name)}`, {
      method: "PUT",
      body: JSON.stringify({ enabled }),
    });
  }

  /** The commands every front end may run — the ones a plugin registered on `ctx.commands`. */
  async commands(): Promise<CommandInfo[]> {
    const body = await this.request<{ commands: CommandInfo[] }>("/commands");
    return body.commands;
  }

  /**
   * Run one of them. An answer with a `prompt` is a preset for a turn: the caller sends it as the next prompt, with
   * `shown` as the conversation's line and the prompt as the instructions. An answer with `markdown` is a document to
   * show in a view of its own; `message` is still the line it adds to the conversation, and may be empty.
   */
  runCommand(name: string, argument = ""): Promise<CommandAnswer> {
    const path = name.startsWith("/") ? name.slice(1) : name;
    return this.request<CommandAnswer>(`/commands/${encodeURIComponent(path)}`, {
      method: "POST",
      body: JSON.stringify({ argument }),
    });
  }

  // -- usage -------------------------------------------------------------
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
  useSelfCompaction(choice: boolean | null): Promise<SelfCompaction> {
    return this.request<SelfCompaction>("/sessions/current/self-compaction", this.json("PUT", { choice }));
  }

  /** The files, skills and plugin resources an `@` in a prompt can reference. */
  async mentions(query = "", options: { limit?: number } = {}): Promise<MentionInfo[]> {
    const limit = options.limit ?? 50;
    const body = await this.request<{ mentions: MentionInfo[] }>(
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
  async checkModels(options: { timeout?: number } = {}): Promise<ModelCheck[]> {
    const body = await this.request<{ checks: ModelCheck[] }>(
      "/doctor",
      this.json("POST", { timeout: options.timeout ?? 30 }),
    );
    return body.checks;
  }

  // -- running -----------------------------------------------------------
  /** Run one prompt and stream it. Iterate `run.events`, await `run.result`, or both. */
  prompt(text: string, options: PromptOptions = {}): Run {
    return this.session.prompt(text, options);
  }

  /** Answer one message another session sent, streaming the turn exactly as `prompt` does. */
  relay(id: string, options: RunOptions = {}): Run {
    return new Run(this, `/messages/${encodeURIComponent(id)}`, wireOptions(options), options);
  }

  /** Send a message to another session explicitly, without a model turn; returns who took it. */
  send(
    to: string,
    text: string,
    options: { mode?: SendMode } = {},
  ): Promise<{ to: string; disposition: Disposition }> {
    return this.request<{ to: string; disposition: Disposition }>(
      "/sessions/current/send",
      this.json("POST", { to, text, mode: options.mode ?? "steer" }),
    );
  }

  /** Whether a run is going, and what it waits on. */
  runState(): Promise<RunState> {
    return this.request<RunState>("/runs/current");
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

  /** Stop the run in progress; its stream then ends with `cancelled`. */
  async cancelRun(): Promise<boolean> {
    const body = await this.request<{ cancelled: boolean }>("/runs/cancel", { method: "POST" });
    return body.cancelled;
  }
}

/** The stored conversations of the workspace; reach it as `client.sessions`. */
export class Sessions {
  constructor(private readonly client: ZettCodeClient) {}

  /** The stored sessions of the workspace, most recently active first. */
  async list(options: { limit?: number } = {}): Promise<SessionInfo[]> {
    const limit = options.limit ?? 20;
    const body = await this.client.request<{ sessions: SessionInfo[] }>(
      `/sessions?limit=${encodeURIComponent(String(limit))}`,
    );
    return body.sessions;
  }

  /** Start an empty conversation and make it current. */
  new(title?: string): Promise<SessionInfo> {
    return this.client.request<SessionInfo>(
      "/sessions",
      jsonInit("POST", title === undefined ? {} : { title }),
    );
  }

  /** Continue a stored conversation; the next prompt goes to it. Unlike Python, this returns its data and not a handle. */
  open(sessionId: string): Promise<CurrentSession> {
    return this.client.request<CurrentSession>(`/sessions/${encodeURIComponent(sessionId)}/open`, { method: "POST" });
  }

  /** Continue the conversation that was active most recently, or `null` when the workspace has none. */
  async latest(): Promise<CurrentSession | null> {
    const [newest] = await this.list({ limit: 1 });
    return newest === undefined ? null : this.open(newest.id);
  }
}

/** The current conversation: what the next prompt continues; reach it as `client.session`. */
export class Session {
  constructor(private readonly client: ZettCodeClient) {}

  /** Its data as of now: `id`, `title`, `locked` and `usage`, which Python reads as properties. */
  info(): Promise<CurrentSession> {
    return this.client.request<CurrentSession>("/sessions/current");
  }

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
    if (options.instructions !== undefined) {
      body.instructions = options.instructions;
    }
    return new Run(this.client, "/prompts", body, options);
  }

  /** Name the current conversation. */
  rename(title: string): Promise<SessionInfo> {
    return this.client.request<SessionInfo>("/sessions/current/rename", jsonInit("POST", { title }));
  }

  /** Ask the model for a name, and give the conversation one. */
  nameIt(): Promise<SessionInfo> {
    return this.client.request<SessionInfo>("/sessions/current/name", { method: "POST" });
  }

  /** Carry this conversation's context into a new session and continue there. */
  fork(): Promise<CurrentSession> {
    return this.client.request<CurrentSession>("/sessions/current/fork", { method: "POST" });
  }

  /** Summarize the conversation now; `applied` is false when there was nothing to fold. */
  compact(): Promise<Compaction> {
    return this.client.request<Compaction>("/sessions/current/compact", { method: "POST" });
  }

  /** How full the context window is, or `null` before a request has been measured. */
  context(): Promise<ContextReport | null> {
    return this.client.request<ContextReport | null>("/sessions/current/context");
  }

  /**
   * The messages the model is working with, oldest first. With `full`, the whole conversation as it was written: what a
   * compaction folded away is there, and each summary (role `summary`) stands where it was made.
   */
  async history(options: { full?: boolean } = {}): Promise<Message[]> {
    const query = options.full === true ? "?full=true" : "";
    const body = await this.client.request<{ messages: Message[] }>(`/sessions/current/history${query}`);
    return body.messages;
  }

  /** The conversation as a standalone HTML page. */
  async export(): Promise<string> {
    const response = await this.client.raw("/sessions/current/export");
    return response.text();
  }

  /** Ask something answered from the conversation but kept out of it, as `/btw` does. */
  async ask(question: string, options: { timeout?: number } = {}): Promise<string> {
    const body = await this.client.request<{ answer: string }>(
      "/sessions/current/ask",
      jsonInit("POST", options.timeout === undefined ? { question } : { question, timeout: options.timeout }),
    );
    return body.answer;
  }

  /** `ask`, with the answer streamed: iterate the run for `text_delta` events, or await `run.result`. */
  askStream(question: string, options: RunOptions = {}): Run {
    return new Run(
      this.client,
      "/sessions/current/ask/stream",
      options.timeout === undefined ? { question } : { question, timeout: options.timeout },
      options,
    );
  }

  /** Where the conversation was interrupted, or that it was not. */
  resumable(): Promise<ResumeInfo> {
    return this.client.request<ResumeInfo>("/runs/resumable");
  }

  /** Continue the interrupted request where it stopped, streaming it like `prompt`. */
  resume(options: RunOptions = {}): Run {
    return new Run(this.client, "/runs/resume", wireOptions(options), options);
  }

  /**
   * Send a message into the run in progress, built as a prompt is (pictures, and `@` mentions when asked for).
   * Resolves to the text the run will report it by (the `steered` event's `text`), or `null` when nothing took it.
   */
  async steer(text: string, options: { images?: ImageInput[]; mentions?: boolean } = {}): Promise<string | null> {
    const body: Record<string, unknown> = { text };
    if (options.images) {
      body.images = options.images.map((image) => ({ data: image.data, media_type: image.mediaType }));
    }
    if (options.mentions !== undefined) {
      body.mentions = options.mentions;
    }
    const reply = await this.client.request<{ steered: boolean; text?: string | null }>(
      "/runs/steer",
      jsonInit("POST", body),
    );
    return reply.steered ? (reply.text ?? text) : null;
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
  steer(text: string, options: { images?: ImageInput[]; mentions?: boolean } = {}): Promise<string | null> {
    return this.client.session.steer(text, options);
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
