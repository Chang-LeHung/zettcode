// Joins the event socket to the stores: what the gateway says moved becomes a change in the lists, a refresh of the
// open conversation, or a notification. Nothing else in the page talks to the socket.

import { EventSocket } from "../api/events";
import { t } from "../i18n";
import { nativeBridge } from "../lib/native";
import type { GatewayEvent } from "../types";
import { applyTraffic, loadGraph } from "./graph";
import { applyGroupTraffic } from "./groups";
import { chat, markRead, refreshChat } from "./chat";
import { prefs } from "./prefs";
import { auth } from "./auth";
import { route } from "./route";
import { applyStream, resetStreams } from "./stream";
import { servers } from "./servers";
import { applyThreads, lobby, loadThreads, threadOf } from "./threads";

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

function notify(event: Extract<GatewayEvent, { type: "inbound" }>): void {
  if (!prefs.notify) return;
  // A conversation that was put away stays quiet, as it does in the unread counts.
  if (threadOf(event.id)?.archived) return;
  const watching = !document.hidden && route.nav === "chats" && route.arg === event.id;
  if (watching) return;
  // The shell's notice is the one that works while the page is not the front window; a browser falls back to the
  // Web Notification API, which the gateway page has always used.
  const shell = nativeBridge();
  if (shell?.notify) {
    shell.notify(event.sender, event.text);
    return;
  }
  if (typeof Notification === "undefined" || Notification.permission !== "granted") return;
  showNotice(event.sender, event.text, event.id);
}

/**
 * Show one notification: through the service worker when there is one, because a page that is not in front may not be
 * allowed to make it itself (Android's Chrome never is) and the worker can; otherwise, or when the worker fails, as the
 * page's own, and a browser that refuses that too has nothing left to try.
 */
export function showNotice(title: string, body: string, id: string): void {
  if (worker) {
    void worker.showNotification(title, { body, tag: id, data: { id } }).catch(() => plain(title, body, id));
    return;
  }
  plain(title, body, id);
}

function plain(title: string, body: string, id: string): void {
  try {
    const shown = new Notification(title, { body, tag: id });
    shown.onclick = () => {
      window.focus();
      location.hash = `#/chats/${encodeURIComponent(id)}`;
      shown.close();
    };
  } catch {
    // Nothing left to try.
  }
}

/** For a test: the registration the page shows notifications through. */
export function setWorker(registration: ServiceWorkerRegistration | null): void {
  worker = registration;
}

/** The service worker that shows notifications, once the browser has one: only a secure page (https or localhost) may. */
let worker: ServiceWorkerRegistration | null = null;
let registered = false;

/**
 * Register the worker, once the person is signed in (a signed-out page has no use for it). A read-only sign-in registers
 * it too, which is harmless: the worker caches nothing and answers no request. It also listens for the worker asking the
 * page to open a conversation, which is how a browser whose workers cannot navigate a window reaches the chat.
 */
export function registerWorker(): void {
  if (registered || !("serviceWorker" in navigator) || nativeBridge()) return;
  registered = true;
  navigator.serviceWorker.addEventListener("message", (message: MessageEvent) => {
    const hash = (message.data as { type?: string; hash?: string } | null)?.hash;
    // Only a chat address: the worker is ours, but the page moves only to where it would move itself.
    if ((message.data as { type?: string } | null)?.type === "open-chat" && typeof hash === "string" && hash.startsWith("#/chats/")) {
      location.hash = hash;
    }
  });
  navigator.serviceWorker
    .register("/sw.js")
    .then((registration) => (worker = registration))
    .catch(() => undefined);
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
    notify(event);
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

/** The text a notification permission request leaves behind, for the settings page. */
export function notificationState(): string {
  if (nativeBridge()?.notify) return "granted";
  if (typeof Notification === "undefined") return t("Not supported by this browser");
  return Notification.permission;
}

export async function enableNotifications(): Promise<boolean> {
  if (nativeBridge()?.notify) return true;
  if (typeof Notification === "undefined") return false;
  const permission = Notification.permission === "default" ? await Notification.requestPermission() : Notification.permission;
  return permission === "granted";
}
