import assert from "node:assert/strict";
import { test } from "node:test";
import { BADGE_LIMIT, badge, seenNow, unreadChats } from "../src/lib/unread";
import { applyThreads, chatsWithUnread, totalUnread } from "../src/stores/threads";
import type { Thread } from "../src/types";

test("a badge is empty for nothing, the number up to the limit, and 99+ past it", () => {
  assert.equal(badge(0), "");
  assert.equal(badge(-3), "");
  assert.equal(badge(Number.NaN), "");
  assert.equal(badge(1), "1");
  assert.equal(badge(BADGE_LIMIT), "99");
  assert.equal(badge(BADGE_LIMIT + 1), "99+");
  assert.equal(badge(5000), "99+");
});

test("new messages are seen only when the page is in front and the reader is at the bottom", () => {
  assert.equal(seenNow({ hidden: false, atBottom: true, unread: 3 }), true);
  assert.equal(seenNow({ hidden: false, atBottom: false, unread: 3 }), false, "scrolled up: not seen yet");
  assert.equal(seenNow({ hidden: true, atBottom: true, unread: 3 }), false, "another tab: not seen");
  assert.equal(seenNow({ hidden: false, atBottom: true, unread: 0 }), false, "nothing to mark");
});

test("the tab counts the conversations with something unread, not the messages", () => {
  assert.equal(unreadChats([]), 0);
  assert.equal(unreadChats([{ unread: 0 }, { unread: 500 }, { unread: 1 }, { unread: 0 }]), 2);
});

test("an archived conversation does not call for attention in the tab or the total", () => {
  const thread = (id: string, unread: number, archived: boolean) => ({ id, unread, archived }) as unknown as Thread;
  applyThreads([thread("a", 3, false), thread("b", 9, true), thread("c", 0, false)]);
  assert.equal(chatsWithUnread.value, 1);
  assert.equal(totalUnread.value, 3);
});
