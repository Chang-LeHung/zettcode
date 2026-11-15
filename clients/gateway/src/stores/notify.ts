// What the page shows when something arrives while nobody is looking: the notification of a message, the permission to show
// one, and the service worker that shows it when the page is not the front window. The socket (`live.ts`) says that a
// message came; what to do about it is here.

import { t } from "../i18n";
import { nativeBridge } from "../lib/native";
import type { GatewayEvent } from "../types";
import { prefs } from "./prefs";
import { route } from "./route";
import { threadOf } from "./threads";

/** Tell the person a message arrived, unless they are looking at it or have turned notifications off. */
export function notifyInbound(event: Extract<GatewayEvent, { type: "inbound" }>): void {
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
