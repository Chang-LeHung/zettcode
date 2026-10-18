/** The errors the client raises: one for the API, one for a run that failed, one for a run that was stopped. */

/** A failure the server reported, in the one shape every endpoint uses. */
export class ZettCodeError extends Error {
  /** The stable code, such as `busy`, `not_found` or `run`. */
  readonly code: string;
  /** The HTTP status, when the failure was an HTTP response. */
  readonly status: number | undefined;

  constructor(message: string, code = "internal", status?: number) {
    super(message);
    this.name = "ZettCodeError";
    this.code = code;
    this.status = status;
  }
}

/** A run failed after its stream opened; the SDK's sentence is the message. */
export class RunFailedError extends ZettCodeError {
  constructor(message: string, code = "run") {
    super(message, code);
    this.name = "RunFailedError";
  }
}

/** A run was stopped, by `cancel()` or by the connection closing. */
export class RunCancelledError extends ZettCodeError {
  constructor(message = "The run was cancelled") {
    super(message, "cancelled");
    this.name = "RunCancelledError";
  }
}
