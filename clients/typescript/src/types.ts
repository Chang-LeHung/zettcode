/** What the server sends and accepts: the wire format of `zettcode-server`, in TypeScript. */

/**
 * The shell permission levels. `safe` runs every command in an operating-system sandbox that writes only the workspace
 * and `/tmp`; `full` runs them with the user's own access. A server also takes `auto`, the old name of `full`, and
 * answers with `full`.
 */
export type Permission = "deny" | "ask" | "safe" | "full";

/** How a run answers the shell commands the model asks to run. */
export type ApprovalMode = "deny" | "auto" | "commands" | "ask";

/** Whether a question the model asks waits for the client. */
export type QuestionMode = "ask" | "decline";

export interface ApprovalPolicy {
  /** `deny` refuses everything, `auto` approves everything, `commands` approves the named ones, `ask` asks you. */
  mode?: ApprovalMode;
  /** The commands `commands` approves, such as `"git status"` or `"pytest"`. */
  commands?: string[];
}

/** An image sent with a prompt, base64 encoded. */
export interface ImageInput {
  data: string;
  mediaType: string;
}

export interface Usage {
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  reasoning_tokens: number;
  seconds: number;
  requests: number;
  context_tokens: number;
}

export interface ModelInfo {
  name: string;
  model: string;
  context_window: number;
  multimodal: boolean;
  efforts: string[];
  active: boolean;
  /** Share of the window, in percent, at which a request is summarized first. */
  compact_percent: number;
  /** Whether the provider searches the web for this model. */
  web_search: boolean;
  /** The tool type that search is sent as; `null` takes the default for the API the model speaks. */
  web_search_name: string | null;
}

/** One model to add to the configuration file; the keys are the file's own. */
export interface ModelInput {
  model: string;
  token?: string;
  display_model?: string;
  base_url?: string;
  anthropic?: boolean;
  responses_api?: boolean;
  /** Say that the endpoint speaks chat completions (the default); not combinable with `anthropic` or `responses_api`. */
  chat?: boolean;
  multimodal?: boolean;
  /** Sampling temperature, from 0 to 2 (to 1 for an Anthropic model). Left out, the provider's own default is used. */
  temperature?: number;
  /**
   * Let the provider search the web for the model. DeepSeek is searched only over its Anthropic-compatible endpoint
   * (`anthropic: true`); on its chat endpoint the server refuses it.
   */
  web_search?: boolean;
  /** The exact tool type the endpoint expects for that search; left out, the default for the API is sent. */
  web_search_name?: string;
  context_window?: number;
  compact_percent?: number;
  reasoning_efforts?: string[];
}

/**
 * Changes to one configured model; a key left out stays as it is, the token included. A key sent as `null` is
 * removed from the entry (everything but the model id and the token can be): `temperature: null` goes back to the
 * provider's own, and `anthropic: null` takes the flag out of the file rather than leaving `anthropic = false`.
 */
export type ModelUpdate = Partial<Pick<ModelInput, "model" | "token">> & {
  [K in Exclude<keyof ModelInput, "model" | "token">]?: ModelInput[K] | null;
};

export interface Settings {
  model: ModelInfo;
  effort: string;
  efforts: string[];
  permission: Permission;
  permissions: string[];
  /** Whether the just-in-time harness is on: the model may write small Python tools of its own and run them. */
  harness: boolean;
  /** Why a compaction point set by `updateSettings` was not written to the configuration file; it then holds for this run only. */
  unsaved?: string | null;
}

export interface SettingsUpdate {
  model?: string;
  effort?: string;
  permission?: Permission | "auto";
  /** Turn the just-in-time harness on or off for the prompts that follow. It starts off. */
  harness?: boolean;
  /** Move the active model's compaction point; more than 0 and at most 100. Refused while a run is in progress. */
  compact_percent?: number;
}

export interface Health {
  status: "ok";
  version: string;
  workspace: string;
  /** Whether a model is configured, so a prompt can run; a fresh machine is false until `addModel`. */
  ready: boolean;
  session: string | null;
  models: number;
  busy: boolean;
}

export interface SessionInfo {
  id: string;
  title: string | null;
  created_at: string | null;
  updated_at: string | null;
  current: boolean;
}

export interface CurrentSession {
  id: string;
  title: string | null;
  locked: boolean;
  usage: Usage;
}

export interface ToolRecord {
  call_id: string;
  name: string;
  arguments: Record<string, unknown>;
  output: string;
  ok: boolean;
  skipped: boolean;
}

export interface Message {
  /** `user`, `assistant` or `tool`; `summary` is what a compaction left in place of the older messages. */
  role: string;
  text: string;
  tool_calls: ToolRecord[];
  tool_call_id: string | null;
  tool_name: string | null;
  ok: boolean;
  images: number;
  /** A user message's images, base64 encoded, so a reopened session can show them again. */
  pictures?: { data: string; media_type: string }[];
  /** What the model call that wrote an assistant message spent, when the store recorded it. */
  usage?: Usage | null;
  /** How long the message took to produce; zero for a message typed by a person. */
  seconds?: number;
}

export interface Compaction {
  applied: boolean;
  summary: string;
  compressed: number;
  kept: number;
}

export interface ContextShare {
  name: string;
  tokens: number;
  items: number;
}

export interface ContextReport {
  window: number;
  used: number;
  measured_by: string;
  shares: ContextShare[];
  partial: boolean;
  from_provider: boolean;
}

export interface RunResult {
  text: string;
  session_id: string;
  usage: Usage;
  tools: ToolRecord[];
  stop: string | null;
  stop_message: string | null;
  questions: string[];
}

export interface Plugins {
  loaded: string[];
  failures: string[];
}

/** One `@` resource a prompt can carry. */
export interface Mention {
  token: string;
  kind: string;
  name: string;
  description: string;
}

/** Token counters added up over some replies, as the usage ledger records them. */
export interface Totals {
  requests: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  reasoning_tokens: number;
  total_tokens: number;
  cache_share: number | null;
}

export interface SessionTotals {
  id: string;
  title: string | null;
  started: string;
  updated: string;
  tokens: Totals;
  models: string[];
  entries: number;
}

export interface ModelTotals {
  model: string;
  tokens: Totals;
}

export interface DayTotals {
  day: string;
  tokens: Totals;
}

/** What the workspace's stored sessions have spent, as the terminal's `/usage` page shows it. */
export interface WorkspaceUsage {
  sessions: SessionTotals[];
  models: ModelTotals[];
  days: DayTotals[];
  total: Totals;
}

/** The totals one row of the terminal's `/resume` panel shows. */
export interface SessionStatsInfo {
  id: string;
  entries: number;
  requests: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  reasoning_tokens: number;
  total_tokens: number;
  cache_share: number | null;
}

/** Whether the model may compact this session itself, and the session's own choice. */
export interface SelfCompaction {
  choice: boolean | null;
  effective: boolean;
}

/** One model asked one short question by `client.doctor()`. */
export interface ModelCheck {
  model: string;
  model_id: string;
  ok: boolean;
  seconds: number;
  detail: string;
  input_tokens: number | null;
  output_tokens: number | null;
}

export interface RunState {
  running: boolean;
  pending: PendingRequest | null;
}

export interface PendingRequest {
  kind: "approval" | "question";
  call_id: string;
  command?: string | null;
  timeout_seconds?: number | null;
  remember_supported?: boolean;
  question?: string | null;
  options?: string[];
  allow_multiple?: boolean;
}

export interface Resumable {
  resumable: boolean;
  kind: string | null;
  description: string | null;
}

/** Every event a run streams, discriminated by `type`. */
export type RunEvent =
  | { type: "text_delta"; text: string }
  | { type: "reasoning_delta"; text: string }
  | { type: "tool_started"; call_id: string; name: string; arguments: Record<string, unknown> }
  | { type: "tool_finished"; call_id: string; name: string; output: string; ok: boolean; skipped: boolean }
  | { type: "server_tool_started"; call_id: string; name: string; arguments: Record<string, unknown> }
  | {
      type: "server_tool_finished";
      call_id: string;
      name: string;
      arguments: Record<string, unknown>;
      output: string;
      ok: boolean;
    }
  | { type: "approval_requested"; call_id: string; command: string; approved: boolean | null }
  | {
      type: "question_asked";
      call_id: string;
      question: string;
      options: string[];
      allow_multiple: boolean;
      answered: boolean;
    }
  | { type: "usage_updated"; usage: Usage }
  | { type: "compaction_started" }
  | { type: "compaction_finished"; applied: boolean; summary: string }
  | { type: "model_stopped"; reason: string; message: string | null }
  | { type: "steered"; text: string }
  | { type: "notice"; text: string; level?: "info" | "warn" }
  | { type: "finished"; text: string }
  | { type: "event"; name: string };

/** One frame of the event stream: its SSE name and its parsed payload. */
export interface StreamFrame {
  event: "event" | "result" | "error" | "cancelled";
  data: RunEvent | RunResult | { error: string; message: string } | { type: "cancelled" } | string;
}

/** Options every run takes, whether it starts a prompt or continues one. */
export interface RunOptions {
  approvals?: ApprovalPolicy;
  questions?: QuestionMode;
  /** Seconds the whole run may take. */
  timeout?: number;
  /** Seconds an `ask` approval or question waits for you before the safe default. */
  answerTimeout?: number;
  keepEvents?: boolean;
  /** Called with every frame before it is queued, for logging. */
  onEvent?: (frame: StreamFrame) => void;
  /** Answers an approval the run is suspended on; omit it and the server's `answerTimeout` decides. */
  onApproval?: (request: { call_id: string; command: string; timeout_seconds?: number | null }) => boolean | Promise<boolean>;
  /** Answers a question; returning `null` declines it. */
  onQuestion?: (request: {
    call_id: string;
    question: string;
    options: string[];
    allow_multiple: boolean;
  }) => string | null | Promise<string | null>;
  /** Aborts the request; the server stops the run when the connection closes. */
  signal?: AbortSignal;
}

export interface PromptOptions extends RunOptions {
  /** Pictures for a model that takes them; `data` is base64. */
  images?: ImageInput[];
  /** Resolve `@path` mentions, as the terminal does. Defaults to true on the server. */
  mentions?: boolean;
}

/** The token counts of a session or a run. */
export function totalTokens(usage: Usage): number {
  return usage.input_tokens + usage.output_tokens;
}
