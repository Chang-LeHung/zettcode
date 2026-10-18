/** The TypeScript client for `zettcode-server`. */

export { ZettCodeClient, Run, failure, wireOptions } from "./client.js";
export type { ClientOptions } from "./client.js";
export { ZettCodeError, RunCancelledError, RunFailedError } from "./errors.js";
export { parseBlock, sseFrames } from "./sse.js";
export { totalTokens } from "./types.js";
export type {
  ApprovalMode,
  ApprovalPolicy,
  Compaction,
  ContextReport,
  ContextShare,
  CurrentSession,
  Health,
  ImageInput,
  Message,
  ModelInfo,
  PendingRequest,
  Permission,
  Plugins,
  PromptOptions,
  QuestionMode,
  Resumable,
  RunEvent,
  RunOptions,
  RunResult,
  RunState,
  SessionInfo,
  Settings,
  SettingsUpdate,
  StreamFrame,
  ToolRecord,
  Usage,
} from "./types.js";
