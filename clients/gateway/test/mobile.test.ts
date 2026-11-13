import "./dom-setup";
import assert from "node:assert/strict";
import { test } from "node:test";
import { EventSocket, STALE_AFTER } from "../src/api/events";
import { attachPull, MAX_PULL, pullOf, THRESHOLD } from "../src/lib/pull";
import { connect, disconnect, registerWorker, setWorker, showNotice } from "../src/stores/live";

// -- pull to refresh ----------------------------------------------------------------------------

test("only a steep downward pull from the top of the list is a pull", () => {
  assert.equal(pullOf(80, 0, 10), null, "the list is scrolled: that is scrolling, not a pull");
  assert.equal(pullOf(-30, 0, 0), null, "upwards is scrolling the list");
  assert.equal(pullOf(40, 60, 0), null, "mostly sideways is a swipe along a row");
  assert.deepEqual(pullOf(40, 5, 0), { distance: 20, ready: false });
});

test("the pull is ready only once the finger has gone far enough, and the indicator never goes past its maximum", () => {
  assert.equal(pullOf(THRESHOLD * 2 - 1, 0, 0)?.ready, false);
  assert.equal(pullOf(THRESHOLD * 2, 0, 0)?.ready, true);
  assert.equal(pullOf(5000, 0, 0)?.distance, MAX_PULL);
});

function touch(type: string, x: number, y: number): Event {
  const event = new window.Event(type, { bubbles: true, cancelable: true });
  Object.defineProperty(event, "touches", { value: type === "touchend" ? [] : [{ clientX: x, clientY: y }] });
  return event;
}

function listWith(scrollTop = 0) {
  const el = document.createElement("div");
  Object.defineProperty(el, "scrollTop", { value: scrollTop, configurable: true });
  const changes: unknown[] = [];
  let refreshed = 0;
  const detach = attachPull(el, {
    change: (pull) => changes.push(pull),
    refresh: () => {
      refreshed += 1;
    },
  });
  return { el, changes, detach, refreshed: () => refreshed };
}

test("letting go after a long enough pull refreshes once, and a short one does not", async () => {
  const long = listWith();
  long.el.dispatchEvent(touch("touchstart", 10, 0));
  long.el.dispatchEvent(touch("touchmove", 10, THRESHOLD * 2 + 10));
  long.el.dispatchEvent(touch("touchend", 10, 0));
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(long.refreshed(), 1);
  assert.equal(long.changes.at(-1), null, "the indicator is put away when it is done");

  const short = listWith();
  short.el.dispatchEvent(touch("touchstart", 10, 0));
  short.el.dispatchEvent(touch("touchmove", 10, THRESHOLD));
  short.el.dispatchEvent(touch("touchend", 10, 0));
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(short.refreshed(), 0);
});

test("a touch that starts on a scrolled list, or is cancelled, or comes after the gesture is removed, refreshes nothing", async () => {
  const scrolled = listWith(40);
  scrolled.el.dispatchEvent(touch("touchstart", 10, 0));
  scrolled.el.dispatchEvent(touch("touchmove", 10, 300));
  scrolled.el.dispatchEvent(touch("touchend", 10, 0));

  const cancelled = listWith();
  cancelled.el.dispatchEvent(touch("touchstart", 10, 0));
  cancelled.el.dispatchEvent(touch("touchmove", 10, 300));
  cancelled.el.dispatchEvent(touch("touchcancel", 10, 0));

  const removed = listWith();
  removed.detach();
  removed.el.dispatchEvent(touch("touchstart", 10, 0));
  removed.el.dispatchEvent(touch("touchmove", 10, 300));
  removed.el.dispatchEvent(touch("touchend", 10, 0));
  await new Promise((resolve) => setTimeout(resolve, 0));

  assert.equal(scrolled.refreshed() + cancelled.refreshed() + removed.refreshed(), 0);
});

// -- waking the socket --------------------------------------------------------------------------

class FakeSocket {
  static instances: FakeSocket[] = [];
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  readyState = FakeSocket.CONNECTING;
  closed = false;
  onopen: (() => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  constructor() {
    FakeSocket.instances.push(this);
  }
  open(): void {
    this.readyState = FakeSocket.OPEN;
    this.onopen?.();
  }
  close(): void {
    this.closed = true;
    this.readyState = 3;
  }
}

function socketUnderTest() {
  FakeSocket.instances = [];
  Object.assign(globalThis, { WebSocket: FakeSocket, location: { protocol: "http:", host: "localhost" } });
  const ups: boolean[] = [];
  const socket = new EventSocket({ event: () => {}, connection: (up) => ups.push(up), unauthorized: () => {} });
  socket.start();
  FakeSocket.instances[0]!.open();
  return { socket, ups };
}

test("a short absence trusts the open socket, and a long one replaces it without telling the page it dropped", () => {
  const { socket, ups } = socketUnderTest();

  socket.wake(STALE_AFTER - 1);
  assert.equal(FakeSocket.instances.length, 1);

  socket.wake(STALE_AFTER);
  assert.equal(FakeSocket.instances.length, 2);
  assert.equal(FakeSocket.instances[0]!.closed, true);
  assert.deepEqual(ups, [true], "the old socket's close is not a dropped connection");
  assert.equal(FakeSocket.instances[0]!.onclose, null, "and it schedules no retry of its own");
});

test("a socket that is not open is retried at once, and one still connecting is left alone", () => {
  const { socket } = socketUnderTest();
  const first = FakeSocket.instances[0]!;
  first.readyState = 3;
  first.onclose?.({ code: 1006 }); // dropped: a retry is waiting out its back-off

  socket.wake(0);
  assert.equal(FakeSocket.instances.length, 2, "wake does not wait for the back-off");

  socket.wake(Number.POSITIVE_INFINITY);
  assert.equal(FakeSocket.instances.length, 2, "a socket that is still connecting is not replaced");
});

test("a socket that was stopped is not woken", () => {
  const { socket } = socketUnderTest();
  socket.stop();
  socket.wake(Number.POSITIVE_INFINITY);
  assert.equal(FakeSocket.instances.length, 1);
});

test("the page moves to a chat when the worker asks, and only to a chat", async () => {
  const heard: { fn: ((message: { data: unknown }) => void) | null } = { fn: null };
  const fake = {
    addEventListener: (_: string, fn: (message: { data: unknown }) => void) => (heard.fn = fn),
    register: async () => ({ showNotification: async () => {} }),
  };
  Object.defineProperty(globalThis, "navigator", { value: { serviceWorker: fake }, configurable: true });
  const place = { protocol: "http:", host: "localhost", hash: "#/chats" };
  Object.assign(globalThis, { location: place });

  registerWorker();
  const listener = heard.fn;
  assert.ok(listener, "the page listens for the worker");
  // The shape the worker sends: a hash built as `#/chats/${encodeURIComponent(id)}`.
  listener({ data: { type: "open-chat", hash: "#/chats/01a%2Fb" } });
  assert.equal(place.hash, "#/chats/01a%2Fb");

  place.hash = "#/chats";
  for (const data of [
    { type: "open-chat", hash: "#/groups/x" },
    { type: "open-chat", hash: "#/config" },
    { type: "open-chat", hash: 5 },
    { type: "something-else", hash: "#/chats/01a" },
    null,
    "#/chats/01a",
  ]) {
    listener!({ data });
    assert.equal(place.hash, "#/chats", `a message of ${JSON.stringify(data)} must not move the page`);
  }
});

// -- notifications ------------------------------------------------------------------------------

test("a page hidden twice is measured from the first time, so a long absence is not mistaken for a short one", () => {
  FakeSocket.instances = [];
  Object.assign(globalThis, { WebSocket: FakeSocket, location: { protocol: "http:", host: "localhost", hash: "" } });
  let hidden = true;
  Object.defineProperty(document, "hidden", { get: () => hidden, configurable: true });
  const realNow = Date.now;
  let now = 1_000_000;
  Date.now = () => now;
  try {
    connect();
    FakeSocket.instances[0]!.open();

    document.dispatchEvent(new window.Event("visibilitychange")); // hidden at t0
    now += STALE_AFTER * 3;
    document.dispatchEvent(new window.Event("visibilitychange")); // a second notice, much later, still hidden
    hidden = false;
    document.dispatchEvent(new window.Event("visibilitychange")); // back

    assert.equal(FakeSocket.instances.length, 2, "the dead socket was replaced");
  } finally {
    Date.now = realNow;
    disconnect();
  }
});

class FakeNotification {
  static made: { title: string; body?: string }[] = [];
  static refuse = false;
  static permission = "granted";
  onclick: (() => void) | null = null;
  constructor(title: string, options?: { body?: string }) {
    if (FakeNotification.refuse) throw new TypeError("Illegal constructor");
    FakeNotification.made.push({ title, body: options?.body });
  }
  close(): void {}
}

function registration(show: (title: string, options: unknown) => Promise<void>): ServiceWorkerRegistration {
  return { showNotification: show } as unknown as ServiceWorkerRegistration;
}

test("a notification goes through the worker when there is one, with the conversation to open", async () => {
  const shown: { title: string; options: any }[] = [];
  FakeNotification.made = [];
  FakeNotification.refuse = false;
  Object.assign(globalThis, { Notification: FakeNotification });
  setWorker(registration(async (title, options) => void shown.push({ title, options })));

  showNotice("builder", "hello", "01a");
  await new Promise((resolve) => setTimeout(resolve, 0));

  assert.deepEqual(shown, [{ title: "builder", options: { body: "hello", tag: "01a", data: { id: "01a" } } }]);
  assert.equal(FakeNotification.made.length, 0, "the page makes none of its own");
});

test("a worker that fails falls back to the page's own notification, and a page that may not make one stays quiet", async () => {
  FakeNotification.made = [];
  FakeNotification.refuse = false;
  Object.assign(globalThis, { Notification: FakeNotification });
  setWorker(registration(() => Promise.reject(new Error("no"))));
  showNotice("builder", "hello", "01a");
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(FakeNotification.made, [{ title: "builder", body: "hello" }]);

  // Android's Chrome: the page's own notification throws. Nothing escapes, because nothing is left to try.
  FakeNotification.refuse = true;
  setWorker(null);
  assert.doesNotThrow(() => showNotice("builder", "again", "01a"));
  setWorker(registration(() => Promise.reject(new Error("no"))));
  assert.doesNotThrow(() => showNotice("builder", "again", "01a"));
  await new Promise((resolve) => setTimeout(resolve, 0));
});
