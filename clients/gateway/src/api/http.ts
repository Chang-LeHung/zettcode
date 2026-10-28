// JSON over HTTP. Every failure is an ApiError that carries the code a view can branch on and a sentence to show.

import { t } from "../i18n";

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

export async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      method,
      credentials: "same-origin",
      headers: body === undefined ? {} : { "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
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
