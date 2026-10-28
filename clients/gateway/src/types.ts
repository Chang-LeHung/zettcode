// The shapes the gateway's JSON uses. They mirror zettcode/src/zettcode/gateway/service.py and chat.py; a field that is
// added there is added here, and nothing else on the page reads a response any other way.

export type Kind = "daemon" | "session" | "external";

/** What a thread is doing. `offline` is a daemon the broker does not list yet; `dead` is one whose process is gone. */
export type Status = "idle" | "working" | "starting" | "stopping" | "offline" | "dead";

export interface Thread {
  id: string;
  kind: Kind;
  name: string;
  handle: string;
  title: string;
  workspace: string;
  status: Status;
  online: boolean;
  model: string | null;
  effort: string | null;
  permission: string | null;
  pid: number;
  started_at: number;
  updated_at: number;
  preview: string;
  unread: number;
  /** The session runs a message as its own prompt and answers by itself. */
  direct: boolean;
  /** An unreachable session that another process has open. */
  locked: boolean;
}

export type ChatItem =
  | { kind: "out" | "in" | "reply" | "user" | "note"; text: string }
  | { kind: "from"; text: string; sender: string; via: string }
  | { kind: "tool"; name: string; brief: string; ok?: boolean; output?: string };

export interface Limits {
  max_text: number;
  rate_limit: number;
  rate_window: number;
  used: number;
}

export interface GatewayStatus {
  version: string;
  gateway: { id: string; handle: string };
  broker: { reachable: boolean };
  limits: Limits;
}

export interface ThreadDetail {
  thread: Thread;
  items: ChatItem[];
  total: number;
  truncated: boolean;
  /** What the turn running now has said so far, or null when none is running. */
  live: LiveTurn | null;
}

export interface LiveTool {
  id: string;
  name: string;
  brief: string;
  ok: boolean | null;
}

/** A turn as it happens: the answer so far, whether the model is reasoning, and the tools it has called. */
export interface LiveTurn {
  text: string;
  thinking: boolean;
  tools: LiveTool[];
}

/** One piece of a turn, as the socket delivers it. */
export type StreamPiece =
  | { kind: "begin" | "thinking" | "end" }
  | { kind: "text"; text: string }
  | { kind: "tool"; id: string; name: string; brief: string }
  | { kind: "tool_end"; id: string; ok: boolean };

export interface ModelOption {
  name: string;
  model: string;
  default: boolean;
  context_window: number;
  multimodal: boolean;
  efforts: string[];
  api: string;
}

export interface GatewayConfig {
  version: string;
  roots: string[];
  allow_full: boolean;
  permissions: string[];
  models: ModelOption[];
}

export interface SpawnForm {
  workspace: string;
  model: string;
  effort: string;
  permission: string;
  name: string;
  resume: string;
  message: string;
}

export interface SendReply {
  to: string;
  disposition: "started" | "queued" | string;
  direct: boolean;
  status: GatewayStatus;
}

export interface SpawnReply {
  thread: Thread | null;
  first?: { ok: boolean; disposition?: string; error?: { code: string; message: string } };
}

export interface DirectoryListing {
  path: string;
  parent: string | null;
  dirs: { name: string; path: string }[];
}

/** An event the socket delivers. */
export type GatewayEvent =
  | { type: "threads"; threads: Thread[]; status: GatewayStatus }
  | { type: "thread"; id: string }
  | { type: "stream"; id: string; event: StreamPiece }
  | { type: "inbound"; id: string; sender: string; text: string };

/** A message sent from this page that the stored conversation does not show yet. */
export interface Pending {
  key: number;
  text: string;
  /** How many of this text the conversation must hold before this message counts as shown. */
  target: number;
  state: "sending" | "started" | "queued" | "failed";
  at: number;
  error?: { code: string; message: string; uncertain: boolean };
}
