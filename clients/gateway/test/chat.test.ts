// Opening a conversation: where the unread line goes, and the one race that could move it.

import "./dom-setup";
import assert from "node:assert/strict";
import { test } from "node:test";
import { gateway } from "../src/api/gateway";
import { chat, closeChat, openChat, refreshChat } from "../src/stores/chat";
import type { ThreadDetail } from "../src/types";

/** The answer the gateway gives for a thread of one message, with `from` as where its unread stretch begins. */
function detail(from: number | null): ThreadDetail {
  return {
    thread: {},
    items: [{ kind: "in", text: "hi" }],
    total: 1,
    truncated: false,
    unread_from: from,
    live: null,
  } as unknown as ThreadDetail;
}

/** Run `body` with the gateway's thread call replaced, and leave the store as it was found. */
async function withThread(answer: (call: number) => Promise<ThreadDetail>, body: () => Promise<void>): Promise<void> {
  const original = gateway.thread;
  let calls = 0;
  gateway.thread = (() => answer(calls++)) as typeof gateway.thread;
  closeChat();
  try {
    await body();
  } finally {
    gateway.thread = original;
    closeChat();
  }
}

const settle = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));

test("a chat opened with something unread places the line where it begins", async () => {
  await withThread(async () => detail(2), async () => {
    await openChat("t1");

    assert.equal(chat.unreadFrom, 2);
  });
});

test("a chat opened with nothing unread has no line", async () => {
  await withThread(async () => detail(null), async () => {
    await openChat("t1");

    assert.equal(chat.unreadFrom, null);
  });
});

test("a refresh that answers first does not move the line the opening read would place", async () => {
  const waiting: ((answer: ThreadDetail) => void)[] = [];
  await withThread(
    () => new Promise<ThreadDetail>((resolve) => waiting.push(resolve)),
    async () => {
      const opening = openChat("t1");
      // A `thread` event arrives while the opening read is still out, and starts a second read of its own.
      const refresh = refreshChat("t1");
      assert.equal(waiting.length, 2, "both reads are out");

      // The later read answers first, and it counts a message that arrived after the chat was opened.
      waiting[1]?.(detail(1));
      await settle();
      assert.equal(chat.unreadFrom, null, "a read started after the open does not place the line");

      waiting[0]?.(detail(null));
      await Promise.all([opening, refresh]);

      assert.equal(chat.unreadFrom, null, "the chat found nothing unread when it was opened");
    },
  );
});

test("a read that fails leaves the line for the next attempt", async () => {
  let attempt = 0;
  await withThread(
    async () => {
      if (attempt++ === 0) throw new Error("the gateway went away");
      return detail(3);
    },
    async () => {
      await openChat("t1");
      assert.equal(chat.unreadFrom, null, "nothing was read");

      await refreshChat("t1");

      assert.equal(chat.unreadFrom, 3, "the second read is still the first one that answered");
    },
  );
});
