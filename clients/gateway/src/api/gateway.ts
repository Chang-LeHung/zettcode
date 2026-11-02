// The gateway's endpoints, typed. A view calls these and never builds a URL.

import type {
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
  stop: (threadId: string) => request<{ result: string }>("DELETE", `/api/daemons/${id(threadId)}`),
  log: (threadId: string) => request<{ text: string }>("GET", `/api/daemons/${id(threadId)}/log`),
  config: () => request<GatewayConfig>("GET", "/api/config"),
  addModel: (entry: Record<string, unknown>) =>
    request<{ models: ModelOption[] }>("POST", "/api/models", entry),
  changeModel: (name: string, changes: Record<string, unknown>) =>
    request<{ models: ModelOption[] }>("PATCH", `/api/models/${encodeURIComponent(name)}`, changes),
  removeModel: (name: string) => request<{ models: ModelOption[] }>("DELETE", `/api/models/${encodeURIComponent(name)}`),
  graph: () => request<GraphData>("GET", "/api/graph"),
  older: (before: number, limit = 50) =>
    request<OlderMessages>("GET", `/api/graph/older?before=${before}&limit=${limit}`),
  timeline: (since: number, until: number, limit = 20000) =>
    request<Timeline>("GET", `/api/graph/timeline?since=${since}&until=${until}&limit=${limit}`),
  directories: (path: string) => request<DirectoryListing>("GET", `/api/dirs?path=${encodeURIComponent(path)}`),
};
