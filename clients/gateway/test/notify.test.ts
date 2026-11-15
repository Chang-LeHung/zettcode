// When a message arrives for a conversation, and what the page does about it: nothing while it is being read, put away, or
// not wanted; the shell's notice when there is one; otherwise the browser's, if the person allowed it.

import "./dom-setup";
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";
import { enableNotifications, notificationState, notifyInbound, setWorker } from "../src/stores/notify";
import { prefs } from "../src/stores/prefs";
import { route } from "../src/stores/route";
import { applyThreads } from "../src/stores/threads";
import type { GatewayEvent, Thread } from "../src/types";

type Inbound = Extract<GatewayEvent, { type: "inbound" }>;

const event: Inbound = { type: "inbound", id: "01a", sender: "builder", text: "build is red" };

class FakeNotification {
  static made: { title: string; options?: { body?: string; tag?: string } }[] = [];
  static last: FakeNotification | null = null;
  static permission = "granted";
  static asked = 0;
  static answer = "granted";
  static async requestPermission(): Promise<string> {
    FakeNotification.asked += 1;
    FakeNotification.permission = FakeNotification.answer;
    return FakeNotification.answer;
  }
  onclick: (() => void) | null = null;
  closed = false;
  constructor(title: string, options?: { body?: string; tag?: string }) {
    FakeNotification.made.push({ title, options });
    FakeNotification.last = this;
  }
  close(): void {
    this.closed = true;
  }
}

const bridge = globalThis as unknown as { window: { __zettcodeNative?: unknown } };
/** The page's address, which a click on a notice moves: the test page has none of its own. */
const place = { hash: "" };

function visible(on: boolean): void {
  Object.defineProperty(document, "hidden", { value: !on, configurable: true });
}

function threads(archived: boolean): void {
  applyThreads([{ id: "01a", archived, unread: 0, kind: "daemon", status: "idle" } as unknown as Thread]);
}

beforeEach(() => {
  FakeNotification.made = [];
  FakeNotification.last = null;
  FakeNotification.permission = "granted";
  FakeNotification.asked = 0;
  FakeNotification.answer = "granted";
  Object.assign(globalThis, { Notification: FakeNotification });
  prefs.notify = true;
  route.nav = "chats";
  route.arg = "";
  visible(false);
  threads(false);
  setWorker(null);
  place.hash = "";
  Object.assign(globalThis, { location: place });
});

afterEach(() => {
  delete bridge.window.__zettcodeNative;
});

test("a message for a conversation that is not being looked at is shown by the browser, one notice per conversation", () => {
  notifyInbound(event);

  assert.deepEqual(FakeNotification.made, [{ title: "builder", options: { body: "build is red", tag: "01a" } }]);
});

test("clicking the notice opens that conversation and closes the notice", () => {
  notifyInbound(event);

  FakeNotification.last?.onclick?.();

  assert.equal(place.hash, "#/chats/01a");
  assert.equal(FakeNotification.last?.closed, true);
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

test("the settings page is told the permission, or that the browser cannot show notifications", () => {
  FakeNotification.permission = "denied";
  assert.equal(notificationState(), "denied");

  Object.assign(globalThis, { Notification: undefined });
  assert.equal(notificationState(), "Not supported by this browser");

  bridge.window.__zettcodeNative = { notify: () => undefined };
  assert.equal(notificationState(), "granted", "the shell needs no permission");
});

test("the permission is asked for only when the person has not answered yet", async () => {
  FakeNotification.permission = "default";
  FakeNotification.answer = "denied";
  assert.equal(await enableNotifications(), false);
  assert.equal(FakeNotification.asked, 1);

  FakeNotification.permission = "granted";
  assert.equal(await enableNotifications(), true);
  assert.equal(FakeNotification.asked, 1, "a granted permission is not asked again");

  Object.assign(globalThis, { Notification: undefined });
  assert.equal(await enableNotifications(), false);

  bridge.window.__zettcodeNative = { notify: () => undefined };
  assert.equal(await enableNotifications(), true);
});
