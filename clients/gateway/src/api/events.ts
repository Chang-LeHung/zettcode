// The one WebSocket: it tells the page what moved, and the page asks for the rest. It reconnects by itself, and says
// so, because a page that is not hearing anything must not look as if nothing is happening.

import type { GatewayEvent } from "../types";

export interface EventHandlers {
  event(event: GatewayEvent): void;
  /** The socket opened (true) or closed (false). */
  connection(up: boolean): void;
  /** The gateway closed the socket because the browser is not signed in. */
  unauthorized(): void;
}

const UNAUTHORIZED = 4401;

export class EventSocket {
  private socket: WebSocket | null = null;
  private attempts = 0;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private wanted = false;

  constructor(private readonly handlers: EventHandlers) {}

  start(): void {
    this.wanted = true;
    if (this.socket) return;
    const scheme = location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(`${scheme}//${location.host}/api/events`);
    this.socket = socket;
    socket.onopen = () => {
      this.attempts = 0;
      this.handlers.connection(true);
    };
    socket.onmessage = (message) => {
      try {
        this.handlers.event(JSON.parse(String(message.data)) as GatewayEvent);
      } catch {
        // A frame that is not one of ours is not worth stopping for.
      }
    };
    socket.onclose = (closed) => {
      this.socket = null;
      this.handlers.connection(false);
      if (closed.code === UNAUTHORIZED) {
        this.handlers.unauthorized();
        return;
      }
      if (this.wanted) {
        this.attempts += 1;
        this.timer = setTimeout(() => this.start(), Math.min(8000, 400 * 2 ** Math.min(this.attempts, 5)));
      }
    };
    socket.onerror = () => socket.close();
  }

  stop(): void {
    this.wanted = false;
    clearTimeout(this.timer);
    this.socket?.close();
    this.socket = null;
  }
}
