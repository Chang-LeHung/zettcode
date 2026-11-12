// JSON over HTTP. Every failure is an ApiError that carries the code a view can branch on and a sentence to show.

import { reactive } from "vue";
import { t } from "../i18n";
import { apiUrl, authorization, connection } from "./connection";

export interface ErrorBody {
  code: string;
  message: string;
  uncertain?: boolean;
  retry_after?: number;
  limit?: number;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly body: ErrorBody;

  constructor(status: number, body: Partial<ErrorBody> = {}) {
    super(body.message || t("The request failed"));
    this.status = status;
    this.code = body.code ?? "http";
    this.body = { code: this.code, message: this.message, ...body };
  }
}

/** Called when the gateway says the browser is not signed in (or no longer is). */
let unauthorized: () => void = () => {};

export function onUnauthorized(handler: () => void): void {
  unauthorized = handler;
}

/** How many requests are in flight: what the thin bar at the top of the page shows. */
export const net = reactive({ active: 0 });

export async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  net.active += 1;
  try {
    return await send<T>(method, path, body);
  } finally {
    net.active -= 1;
  }
}

/** How long a request may take before it is given up on: a connection that stalls must not hold a dialog or the progress bar forever. */
export const REQUEST_TIMEOUT_MS = 120_000;

async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    return await exchange<T>(method, path, body, controller.signal);
  } catch (error) {
    // Only the timer aborts, so an abort is a timeout. A write that timed out may still have arrived.
    if (controller.signal.aborted) {
      throw new ApiError(0, { code: "timeout", message: t("The gateway did not answer in time"), uncertain: method !== "GET" });
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

async function exchange<T>(method: string, path: string, body: unknown, signal: AbortSignal): Promise<T> {
  const headers: Record<string, string> = { ...authorization() };
  if (body !== undefined) headers["content-type"] = "application/json";
  let response: Response;
  try {
    response = await fetch(apiUrl(path), {
      method,
      // A page served by the gateway is signed in by its cookie; an app carries the token and has no cookie to send.
      credentials: connection.baseUrl ? "omit" : "same-origin",
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch {
    throw new ApiError(0, { code: "offline", message: t("Cannot reach the gateway") });
  }
  let data: unknown = null;
  try {
    data = await response.json();
  } catch {
    // An answer with no body.
  }
  if (!response.ok) {
    if (response.status === 401 && path !== "/api/login") unauthorized();
    const error = (data as { error?: Partial<ErrorBody> } | null)?.error;
    throw new ApiError(response.status, error ?? { message: response.statusText });
  }
  return data as T;
}
