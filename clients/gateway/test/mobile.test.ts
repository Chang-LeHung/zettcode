import "./dom-setup";
import assert from "node:assert/strict";
import { test } from "node:test";
import { EventSocket, STALE_AFTER } from "../src/api/events";
import { attachPull, MAX_PULL, pullOf, THRESHOLD } from "../src/lib/pull";

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
