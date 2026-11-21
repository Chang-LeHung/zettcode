import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import "./dom-setup";
import { href, lastChat, readRoute, route, watchRoute } from "../src/stores/route";
import { canRestart, restartable, restartBlocker } from "../src/lib/restart";
import { auth } from "../src/stores/auth";
import { settings } from "../src/stores/config";
import { lobby } from "../src/stores/threads";
import type { Thread } from "../src/types";

Object.assign(globalThis, { location: window.location });

test("Dashboard remembers the exact group across its subpages and returns to it", () => {
  location.hash = href("chats", "#测试群");
  readRoute();
  location.hash = href("dashboard", "overview");
  readRoute();
  location.hash = href("dashboard", "daemons");
  readRoute();
  assert.equal(lastChat.arg, "#测试群");
  location.hash = href("chats", lastChat.arg);
  readRoute();
  assert.deepEqual({ ...route }, { nav: "chats", arg: "#测试群" });
});

test("a directly opened Dashboard returns to the chat list, and a later chat replaces the destination", () => {
  Object.assign(route, { nav: "chats", arg: "" });
  location.hash = href("dashboard");
  readRoute();
  assert.equal(lastChat.arg, "");
  location.hash = href("chats", "session-2");
  readRoute();
  location.hash = href("dashboard");
  readRoute();
  assert.equal(lastChat.arg, "session-2");
});

test("hashchange wiring remembers a group and follows the Dashboard return link", async () => {
  watchRoute();
  const move = async (hash: string) => {
    const changed = new Promise<void>((resolve) => {
      const hear = (event: HashChangeEvent) => {
        if (new URL(event.newURL).hash !== hash) return;
        window.removeEventListener("hashchange", hear);
        resolve();
      };
      window.addEventListener("hashchange", hear);
    });
    location.hash = hash;
    await changed;
  };
  try {
    await move(href("chats", "#event-test"));
    await move(href("dashboard", "overview"));
    assert.equal(lastChat.arg, "#event-test");
    await move(href("chats", lastChat.arg));
    assert.deepEqual({ ...route }, { nav: "chats", arg: "#event-test" });
  } finally {
    window.removeEventListener("hashchange", readRoute);
  }
});

function daemon(id: string, patch: Partial<Thread> = {}): Thread {
  return {
    id, kind: "daemon", name: id, handle: id, title: "", workspace: "/tmp/test", status: "dead", online: false,
    model: null, effort: null, permission: "safe", pid: 0, started_at: 0, updated_at: 0,
    preview: "", unread: 0, direct: true, locked: false, ...patch,
  };
}

test("restart eligibility and visible blocker agree for every refusal", () => {
  const oldAuth = auth.readOnly;
  const oldSettings = settings.data;
  try {
    auth.readOnly = false;
    settings.data = null;
    assert.equal(canRestart(daemon("ok")), true);
    assert.equal(restartBlocker(daemon("ok")), undefined);
    for (const thread of [undefined, daemon("terminal", { kind: "session" }), daemon("live", { status: "idle" }), daemon("locked", { locked: true })]) {
      assert.equal(canRestart(thread), false);
      assert.ok(restartBlocker(thread));
    }
    auth.readOnly = true;
    assert.equal(canRestart(daemon("read")), false);
    assert.equal(restartBlocker(daemon("read")), "Read-only access cannot restart daemons.");
    auth.readOnly = false;
    // Only this configuration field is read by the eligibility helper.
    settings.data = { allow_full: false } as NonNullable<typeof settings.data>;
    assert.equal(canRestart(daemon("full", { permission: "full" })), false);
    assert.equal(canRestart(daemon("safe")), true);
    assert.match(restartBlocker(daemon("full", { permission: "full" }))!, /Full access/);
  } finally {
    auth.readOnly = oldAuth;
    settings.data = oldSettings;
  }
});

test("batch eligibility keeps the caller's scope and skips running or unavailable sessions", () => {
  const oldThreads = lobby.threads;
  const oldAuth = auth.readOnly;
  try {
    auth.readOnly = false;
    lobby.threads = [daemon("visible"), daemon("pinned", { pinned: true }), daemon("hidden"), daemon("live", { status: "idle", online: true })];
    assert.deepEqual(restartable(["visible", "live", "missing"]).map((thread) => thread.id), ["visible"]);
    assert.deepEqual(restartable(["pinned"]).map((thread) => thread.id), ["pinned"]);
  } finally {
    lobby.threads = oldThreads;
    auth.readOnly = oldAuth;
  }
});

test("restart controls are siblings of conversation links, not nested interactive content", () => {
  const row = readFileSync("src/components/chats/ChatRow.vue", "utf8");
  assert.match(row, /<\/a>\s*<button\b/);
  assert.match(row, /:aria-label="t\('Restart \{name\}'/);
});
