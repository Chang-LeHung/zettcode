/** The messages the extension host and the chat webview exchange. */

import type {
  ContextReport,
  CurrentSession,
  Health,
  ImageInput,
  Mention,
  ModelInfo,
  ModelInput,
  PendingRequest,
  Permission,
  Resumable,
  SelfCompaction,
  Settings,
} from "../../../typescript/src/types.js";
import type { DiffRow } from "./diff.js";
import type { ChangeSummary } from "./ledger.js";
import type { Turn } from "./state.js";

export type ServerStatus = "idle" | "starting" | "ready" | "error";

/** One row of the recent-sessions drawer. */
export interface SessionRow {
  id: string;
  title: string | null;
  updatedAt: string | null;
  entries: number;
  tokens: number;
  current: boolean;
}

/** Everything about the server and the conversation that is not the transcript itself. */
export interface WebviewState {
  server: { status: ServerStatus; message: string };
  /**
   * False until the first load has finished. Until then the server, the models and the session are all unknown,
   * so the view shows the mark and nothing it could get wrong, like "no model".
   */
  loaded: boolean;
  /**
   * What the host is busy loading after the first load, such as "Opening the conversation", or null. A long conversation
   * takes a moment to read back, and without a word about it the view looks stuck on the old one.
   */
  loading: string | null;
  /** False until a model is configured, which is when a prompt can run. */
  ready: boolean;
  health: Health | null;
  settings: Settings | null;
  models: ModelInfo[];
  currentModel: string | null;
  session: CurrentSession | null;
  sessions: SessionRow[];
  busy: boolean;
  pending: PendingRequest | null;
  resumable: Resumable | null;
  selfCompaction: SelfCompaction | null;
  context: ContextReport | null;
  /** The application's version from `/health`, for the footer. */
  version: string | null;
}

/** A file the reader pasted, as the page knows it. */
export interface PastedFile {
  name: string;
  size: number;
  /** The bytes as base64, when the file is small enough to send. */
  data?: string;
}

/** A picture the webview is about to send, with a name for its chip. */
export interface AttachedImage extends ImageInput {
  name: string;
}

export type HostMessage =
  | { type: "init"; state: WebviewState; turns: Turn[] }
  | { type: "state"; state: WebviewState }
  | { type: "turn"; turn: Turn }
  | { type: "turn-delta"; turnId: string; text?: string; reasoning?: string }
  | { type: "turns"; turns: Turn[]; earlier?: number }
  | { type: "earlier"; turns: Turn[]; earlier: number }
  | { type: "sessions"; sessions: SessionRow[] }
  | { type: "mentions"; query: string; items: Mention[] }
  | { type: "images"; images: AttachedImage[] }
  | { type: "files"; paths: string[] }
  | { type: "notice"; level: "info" | "warn" | "error"; text: string; summary?: string }
  | { type: "changes"; turnId: string; files: ChangeSummary[] }
  | { type: "diff-rows"; turnId: string; path: string; rows: DiffRow[]; truncated: boolean }
  | { type: "history"; open: boolean }
  | { type: "find" }
  | { type: "model-form"; open: boolean };

export type WebviewMessage =
  | { type: "ready" }
  | { type: "focused"; focused: boolean }
  | { type: "prompt"; text: string; images: ImageInput[] }
  | { type: "steer"; text: string }
  | { type: "cancel" }
  | { type: "approve"; callId: string; approve: boolean; remember: boolean }
  | { type: "answer"; callId: string; answer: string | null }
  | { type: "open"; target: string }
  | { type: "open-external"; url: string }
  | { type: "new-session" }
  | { type: "open-session"; id: string }
  | { type: "refresh-sessions" }
  | { type: "rename-session"; title?: string }
  | { type: "name-session" }
  | { type: "fork-session" }
  | { type: "compact" }
  | { type: "load-earlier" }
  | { type: "export" }
  | { type: "usage" }
  | { type: "doctor" }
  | { type: "plugins" }
  | { type: "add-model"; model: ModelInput }
  | { type: "remove-model"; name: string }
  | { type: "set-model"; name: string }
  | { type: "set-effort"; effort: string }
  | { type: "set-permission"; permission: Permission }
  | { type: "set-compact"; percent: number }
  | { type: "set-self-compaction"; choice: boolean | null }
  | { type: "refresh" }
  | { type: "restart-server" }
  | { type: "resume" }
  | { type: "ask"; question: string }
  | { type: "mentions"; query: string }
  | { type: "pick-files" }
  /**
   * Files the reader pasted that are not pictures. The page has each one's name and bytes (base64, up to a limit; a
   * larger file has only its size) but no path, so the host finds or makes one.
   */
  | { type: "paste-files"; files: PastedFile[] }
  | { type: "copy"; text: string }
  | { type: "open-settings" }
  | { type: "open-diff"; turnId: string; path: string }
  | { type: "view-diff"; turnId: string; path: string }
  | { type: "context" };
