// The gateway page's service worker. It does one thing: show a conversation's notification and, when it is tapped, bring
// the page back at that conversation. A page that is not in front cannot always make a notification itself (Android's
// Chrome refuses `new Notification`), but the worker can. It caches nothing and answers no request, so a worker
// registered by a read-only sign-in is as inert as any other.

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const id = event.notification.data && event.notification.data.id;
  const hash = id ? `#/chats/${encodeURIComponent(id)}` : "";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(async (windows) => {
      // A window already at this conversation, else any: with two open, the tap must not move the wrong one.
      const open = windows.find((w) => new URL(w.url).hash === hash) || windows[0];
      if (!open) return self.clients.openWindow(`/${hash}`);
      const target = new URL(open.url);
      target.hash = hash;
      await open.focus();
      // The page reads its address from the hash. `navigate` is not in every browser's worker (Safari, Firefox): there
      // the page is asked to move itself, which it does when it hears the message (see registerWorker).
      if (typeof open.navigate === "function") {
        try {
          await open.navigate(target.toString());
          return;
        } catch {
          // fall through to the message
        }
      }
      open.postMessage({ type: "open-chat", hash });
    }),
  );
});
