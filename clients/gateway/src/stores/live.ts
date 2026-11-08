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
import { applyThreads, lobby, loadThreads } from "./threads";

let socket: EventSocket | null = null;

function notify(event: Extract<GatewayEvent, { type: "inbound" }>): void {
  if (!prefs.notify) return;
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
  const shown = new Notification(event.sender, { body: event.text, tag: event.id });
  shown.onclick = () => {
    window.focus();
    location.hash = `#/chats/${encodeURIComponent(event.id)}`;
    shown.close();
  };
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
  socket?.stop();
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
