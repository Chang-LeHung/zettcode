/** The TypeScript client for `zettcode-server`. */

export { ZettCodeClient, Run, Session, Sessions, failure, wireOptions } from "./client.js";
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
  DayTotals,
  Disposition,
  Health,
  ImageInput,
  MentionInfo,
  Message,
  ModelCheck,
  ModelInfo,
  ModelInput,
  ModelTotals,
  ModelUpdate,
  PendingRequest,
  Permission,
  PluginReport,
  PromptOptions,
  QuestionMode,
  ResumeInfo,
  RunEvent,
  RunOptions,
  RunResult,
  RunState,
  SelfCompaction,
  SendMode,
  SessionInfo,
  SessionStatsInfo,
  SessionTotals,
  Settings,
  SettingsUpdate,
  StreamFrame,
  ToolRecord,
  Totals,
  Usage,
  WorkspaceUsage,
} from "./types.js";
