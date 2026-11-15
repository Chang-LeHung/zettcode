// Joins the event socket to the stores: what the gateway says moved becomes a change in the lists, a refresh of the
// open conversation, or a notification (`notify.ts` decides what that shows). Nothing else in the page talks to the socket.

import { EventSocket } from "../api/events";
import type { GatewayEvent } from "../types";
import { applyTraffic, loadGraph } from "./graph";
import { applyGroupTraffic } from "./groups";
import { chat, markRead, refreshChat } from "./chat";
import { auth } from "./auth";
import { notifyInbound, registerWorker } from "./notify";
import { applyStream, resetStreams } from "./stream";
import { servers } from "./servers";
import { applyThreads, lobby, loadThreads } from "./threads";

let socket: EventSocket | null = null;
let hiddenAt = 0;

/** The page is in front again, or the network came back: make sure the socket is one that can still be heard. */
function wake(): void {
  const away = hiddenAt ? Date.now() - hiddenAt : 0;
  hiddenAt = 0;
  socket?.wake(away);
}

function onVisibility(): void {
  // Only the first of several events while hidden counts: a phone fires more than one across a lock and unlock, and the
  // time away is measured from when the page was first hidden, not from the last notice of it.
  if (document.hidden) hiddenAt ||= Date.now();
  else wake();
}

/** A network that just came back is a reason to distrust the socket however recently the page was shown. */
function onOnline(): void {
  hiddenAt = 0;
  socket?.wake(Number.POSITIVE_INFINITY);
}

function listen(on: boolean): void {
  const act = on ? "addEventListener" : "removeEventListener";
  document[act]("visibilitychange", onVisibility);
  window[act]("online", onOnline);
  window[act]("pageshow", wake);
}

function handle(event: GatewayEvent): void {
  if (event.type === "threads") {
    applyThreads(event.threads, event.status);
    if (chat.id && !document.hidden) markRead();
  } else if (event.type === "thread") {
    void refreshChat(event.id);
  } else if (event.type === "stream") {
    applyStream(event.id, event.event);
  } else if (event.type === "inbound") {
    notifyInbound(event);
  } else if (event.type === "traffic") {
    applyTraffic(event.message);
    applyGroupTraffic(event.message);
  } else if (event.type === "graph") {
    void loadGraph().catch(() => {});
  }
}

/** Open the socket, and read everything again whenever it comes back, because events were missed while it was away. */
export function connect(): void {
  registerWorker();
  socket?.stop();
  listen(false);
  listen(true);
  socket = new EventSocket({
    event: handle,
    connection(up) {
      lobby.live = up;
      if (up) {
        resetStreams();
        void loadThreads().catch(() => {});
        void loadGraph().catch(() => {});
        if (chat.id) void refreshChat(chat.id);
      }
    },
    unauthorized() {
      auth.signedIn = false;
      if (servers.mode === "app") servers.problem = "The server refused the token; it may have been changed";
    },
  });
  socket.start();
}

export function disconnect(): void {
  listen(false);
  socket?.stop();
  socket = null;
  lobby.live = false;
}
