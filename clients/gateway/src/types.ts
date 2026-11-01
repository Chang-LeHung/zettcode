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
  display_model?: string | null;
  compact_percent?: number;
  base_url?: string | null;
  temperature?: number | null;
  web_search?: boolean;
  web_search_name?: string | null;
  can_search?: boolean;
}

/** What a model form edits: every field as the person sees it, text where the file holds a number. */
export interface ModelDraft {
  model: string;
  display_model: string;
  api: "chat" | "responses" | "anthropic";
  base_url: string;
  token: string;
  context_window: string;
  compact_percent: string;
  temperature: string;
  multimodal: boolean;
  web_search: boolean;
  efforts: string[];
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
  /** `string` is kept for a disposition a newer server adds; the page draws anything but `queued` as a turn. */
  disposition: "started" | "steered" | "queued" | "delivered" | string;
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
  | { type: "inbound"; id: string; sender: string; text: string }
  | { type: "traffic"; message: GraphMessage }
  | { type: "graph" };

/** How a message got into the broker: typed by a person, sent by an agent's tool, or sent by an outside process. */
export type Via = "user" | "agent" | "external";

export interface GraphSession {
  session_id: string;
  handle: string;
  title: string;
  workspace: string;
  status: "idle" | "working";
  kind: "zettcode" | "external";
}

export interface GraphGroup {
  name: string;
  members: string[];
  /** Epoch seconds. */
  created: number;
}

/** The undirected total of the 1:1 messages two sessions have exchanged. */
export interface GraphEdge {
  a: string;
  b: string;
  count: number;
  last: number;
}

export interface GraphParty {
  session_id: string;
  handle: string;
  title: string;
}

export interface GraphTarget {
  kind: "session" | "group";
  session_id?: string;
  handle?: string;
  title?: string;
  name?: string;
}

export interface GraphMessage {
  id: number;
  /** Epoch seconds. */
  ts: number;
  from: GraphParty;
  to: GraphTarget;
  /** The sessions the message actually reached. */
  recipients: string[];
  text: string;
  via: Via;
  hops: number;
  mode: "steer" | "followup";
  status: "delivered" | "partial";
  disposition: string;
}

/** What `GET /api/graph` answers: the roster, the groups, the pair totals and the latest messages (oldest first). */
export interface GraphData {
  sessions: GraphSession[];
  groups: GraphGroup[];
  edges: GraphEdge[];
  recent: GraphMessage[];
}

/** Stored messages from before one the page already holds: oldest first, and whether any older ones remain. */
export interface OlderMessages {
  messages: GraphMessage[];
  more: boolean;
}

/** A window of stored traffic for replay: oldest first, `span` is the oldest and newest ts held, `now` the server clock. */
export interface Timeline {
  messages: GraphMessage[];
  span: [number, number] | null;
  now: number;
}

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
