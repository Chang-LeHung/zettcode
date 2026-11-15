// When a message arrives for a conversation, and what the page does about it: nothing while it is being read, put away, or
// not wanted; the shell's notice when there is one; otherwise the browser's, if the person allowed it.

import "./dom-setup";
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";
import { notifyInbound, setWorker } from "../src/stores/notify";
import { prefs } from "../src/stores/prefs";
import { route } from "../src/stores/route";
import { applyThreads } from "../src/stores/threads";
import type { GatewayEvent, Thread } from "../src/types";

type Inbound = Extract<GatewayEvent, { type: "inbound" }>;

const event: Inbound = { type: "inbound", id: "01a", sender: "builder", text: "build is red" };

class FakeNotification {
  static made: { title: string; body?: string }[] = [];
  static permission = "granted";
  onclick: (() => void) | null = null;
  constructor(title: string, options?: { body?: string }) {
    FakeNotification.made.push({ title, body: options?.body });
  }
  close(): void {}
}

const bridge = globalThis as unknown as { window: { __zettcodeNative?: unknown } };

function visible(on: boolean): void {
  Object.defineProperty(document, "hidden", { value: !on, configurable: true });
}

function threads(archived: boolean): void {
  applyThreads([{ id: "01a", archived } as unknown as Thread]);
}

beforeEach(() => {
  FakeNotification.made = [];
  FakeNotification.permission = "granted";
  Object.assign(globalThis, { Notification: FakeNotification });
  prefs.notify = true;
  route.nav = "chats";
  route.arg = "";
  visible(false);
  threads(false);
  setWorker(null);
});

afterEach(() => {
  delete bridge.window.__zettcodeNative;
});

test("a message for a conversation that is not being looked at is shown by the browser", () => {
  notifyInbound(event);

  assert.deepEqual(FakeNotification.made, [{ title: "builder", body: "build is red" }]);
});

test("nothing is shown when notifications are off", () => {
  prefs.notify = false;

  notifyInbound(event);

  assert.equal(FakeNotification.made.length, 0);
});

test("nothing is shown for a conversation that was put away", () => {
  threads(true);

  notifyInbound(event);

  assert.equal(FakeNotification.made.length, 0);
});

test("nothing is shown while the person is reading that very conversation, but a hidden page or another one is told", () => {
  visible(true);
  route.arg = "01a";
  notifyInbound(event);
  assert.equal(FakeNotification.made.length, 0, "it is open in front of them");

  route.arg = "02b";
  notifyInbound(event);
  assert.equal(FakeNotification.made.length, 1, "another conversation is open");

  route.arg = "01a";
  visible(false);
  notifyInbound(event);
  assert.equal(FakeNotification.made.length, 2, "the page is not in front");

  route.nav = "graph";
  visible(true);
  notifyInbound(event);
  assert.equal(FakeNotification.made.length, 3, "a different part of the page is open");
});

test("the shell's notice is used when there is one, and the browser is not asked", () => {
  const told: [string, string][] = [];
  bridge.window.__zettcodeNative = { notify: (title: string, text: string) => told.push([title, text]) };

  notifyInbound(event);

  assert.deepEqual(told, [["builder", "build is red"]]);
  assert.equal(FakeNotification.made.length, 0);
});

test("a browser that was not allowed to show notifications, or has none, stays quiet", () => {
  FakeNotification.permission = "denied";
  notifyInbound(event);
  assert.equal(FakeNotification.made.length, 0);

  Object.assign(globalThis, { Notification: undefined });
  assert.doesNotThrow(() => notifyInbound(event));
});
