// The gateway's endpoints, typed. A view calls these and never builds a URL.

import type {
  AgentReply,
  AgentType,
  DirectoryListing,
  GatewayConfig,
  ModelOption,
  GraphData,
  OlderMessages,
  Picture,
  GatewayStatus,
  SendReply,
  SpawnForm,
  SpawnReply,
  Thread,
  Timeline,
  ThreadDetail,
} from "../types";
import { request } from "./http";

const id = (value: string): string => encodeURIComponent(value);

export const gateway = {
  session: () => request<{ authenticated: boolean; open: boolean }>("GET", "/api/session"),
  login: (token: string) => request<{ authenticated: boolean }>("POST", "/api/login", { token }),
  logout: () => request<{ authenticated: boolean }>("POST", "/api/logout"),
  threads: () => request<{ threads: Thread[]; status: GatewayStatus }>("GET", "/api/threads"),
  thread: (threadId: string, all = false) =>
    request<ThreadDetail>("GET", `/api/threads/${id(threadId)}${all ? "?all=1" : ""}`),
  recheck: (threadId: string) => request<{ thread: Thread }>("POST", `/api/threads/${id(threadId)}/recheck`),
  read: (threadId: string) => request<{ ok: true }>("POST", `/api/threads/${id(threadId)}/read`),
  send: (threadId: string, text: string, reply: boolean, pictures: Picture[] = []) =>
    request<SendReply>("POST", `/api/threads/${id(threadId)}/send`, {
      text,
      reply,
      ...(pictures.length ? { images: pictures.map(({ media_type, data }) => ({ media_type, data })) } : {}),
    }),
  spawn: (form: Partial<SpawnForm>) => request<SpawnReply>("POST", "/api/daemons", form),
  stop: (threadId: string, force = false) =>
    request<{ result: string }>("POST", `/api/daemons/${id(threadId)}/stop`, { force }),
  remove: (threadId: string) => request<{ result: string }>("DELETE", `/api/daemons/${id(threadId)}`),
  log: (threadId: string) => request<{ text: string }>("GET", `/api/daemons/${id(threadId)}/log`),
  config: () => request<GatewayConfig>("GET", "/api/config"),
  agents: () => request<{ agents: AgentType[] }>("GET", "/api/agents"),
  createAgent: (form: { kind: string; title?: string; session_id?: string; group?: string }) =>
    request<AgentReply>("POST", "/api/agents", form),
  removeAgent: (sessionId: string) => request<{ ok: true }>("DELETE", `/api/agents/${id(sessionId)}`),
  addModel: (entry: Record<string, unknown>) =>
    request<{ models: ModelOption[] }>("POST", "/api/models", entry),
  changeModel: (name: string, changes: Record<string, unknown>) =>
    request<{ models: ModelOption[] }>("PATCH", `/api/models/${encodeURIComponent(name)}`, changes),
  removeModel: (name: string) => request<{ models: ModelOption[] }>("DELETE", `/api/models/${encodeURIComponent(name)}`),
  graph: () => request<GraphData>("GET", "/api/graph"),
  older: (before: number, limit = 50, group = "") =>
    request<OlderMessages>(
      "GET",
      `/api/graph/older?before=${before}&limit=${limit}${group ? `&group=${encodeURIComponent(group)}` : ""}`,
    ),
  sendGroup: (name: string, text: string) =>
    request<{ delivered: { to: string; disposition: string }[] }>("POST", `/api/groups/${id(name)}/send`, { text }),
  timeline: (since: number, until: number, limit = 20000) =>
    request<Timeline>("GET", `/api/graph/timeline?since=${since}&until=${until}&limit=${limit}`),
  directories: (path: string) => request<DirectoryListing>("GET", `/api/dirs?path=${encodeURIComponent(path)}`),
};
