// The gateway page's service worker. It does one thing: show a conversation's notification and, when it is tapped, bring
// the page back at that conversation. A page that is not in front cannot always make a notification itself (Android's
// Chrome refuses `new Notification`), but the worker can. It caches nothing and answers no request.

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const id = event.notification.data && event.notification.data.id;
  const hash = id ? `#/chats/${encodeURIComponent(id)}` : "";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
      const open = windows[0];
      if (open) {
        // The page reads its address from the hash, so moving the hash is moving the page.
        const target = new URL(open.url);
        target.hash = hash;
        return open.focus().then(() => open.navigate(target.toString()).catch(() => undefined));
      }
      return self.clients.openWindow(`/${hash}`);
    }),
  );
});
