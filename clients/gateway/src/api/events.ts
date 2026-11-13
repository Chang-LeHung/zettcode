// The one WebSocket: it tells the page what moved, and the page asks for the rest. It reconnects by itself, and says
// so, because a page that is not hearing anything must not look as if nothing is happening.

import type { GatewayEvent } from "../types";
import { connection, tokenProtocol } from "./connection";

export interface EventHandlers {
  event(event: GatewayEvent): void;
  /** The socket opened (true) or closed (false). */
  connection(up: boolean): void;
  /** The gateway closed the socket because the browser is not signed in. */
  unauthorized(): void;
}

const UNAUTHORIZED = 4401;

/** The address of the one socket: the gateway's own for the page, the chosen server's for an app. */
export function socketUrl(): string {
  const base = connection.baseUrl || `${location.protocol}//${location.host}`;
  const url = new URL(`${base}/api/events`);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

/** The protocols a socket offers: the app's token, which a browser cannot put in an ``Authorization`` header. */
export function socketProtocols(): string[] {
  return connection.token ? ["zettcode", tokenProtocol(connection.token)] : [];
}

export class EventSocket {
  private socket: WebSocket | null = null;
  private attempts = 0;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private wanted = false;

  constructor(private readonly handlers: EventHandlers) {}

  start(): void {
    this.wanted = true;
    if (this.socket) return;
    const protocols = socketProtocols();
    const socket = protocols.length
      ? new WebSocket(socketUrl(), protocols)
      : new WebSocket(socketUrl());
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

  /** Whether the socket is open right now. */
  get open(): boolean {
    return this.socket?.readyState === WebSocket.OPEN;
  }

  /**
   * The page came back (it was shown again, the phone got a network, or it was restored from the back/forward cache).
   * A phone suspends a page's sockets without telling it, so one that looks open may be dead: when the page was away
   * for a while, drop it and open a new one, whose opening reads everything again. A socket that is not open is
   * retried at once, without the back-off a running page would wait.
   */
  wake(awayMs: number): void {
    if (!this.wanted) return;
    if (this.socket && this.socket.readyState === WebSocket.CONNECTING) return;
    if (this.socket && awayMs < STALE_AFTER) return;
    clearTimeout(this.timer);
    this.attempts = 0;
    const old = this.socket;
    this.socket = null;
    if (old) {
      // Its close must not schedule a retry of its own or tell the page the connection dropped.
      old.onclose = null;
      old.onerror = null;
      old.onmessage = null;
      old.close();
    }
    this.start();
  }
}

/** How long a page may have been away before a socket that looks open is no longer trusted. */
export const STALE_AFTER = 20_000;
