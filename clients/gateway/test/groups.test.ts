import assert from "node:assert/strict";
import { test } from "node:test";
import "./dom-setup";
import { applyGraph, graph, onGraphApplied, resetGraph } from "../src/stores/graph";
import {
  applyGroupTraffic,
  GROUP_NAME,
  groupChat,
  groupList,
  groupArg,
  groupNameOf,
  isGroupArg,
  loadEarlierGroup,
  membersOf,
  openGroup,
  spellGroup,
  unreadOf,
} from "../src/stores/groups";
import { applyThreads } from "../src/stores/threads";
import type { GraphMessage, Thread } from "../src/types";

function say(id: number, group: string, from = "a"): GraphMessage {
  return {
    id,
    ts: id,
    from: { session_id: from, handle: from, title: "" },
    to: { kind: "group", name: group },
    recipients: [],
    text: `m${id}`,
    via: "agent",
    hops: 1,
    mode: "followup",
    status: "delivered",
    disposition: "queued",
  };
}

function thread(id: string, name: string): Thread {
  return {
    id, kind: "daemon", name, handle: name, title: "", workspace: "/w", status: "idle", online: true, model: null, effort: null,
    permission: null, pid: 1, started_at: 1, updated_at: 1, preview: "", unread: 0, direct: true, locked: false,
  };
}

function start(groups: { name: string; members: string[]; created: number; last?: GraphMessage | null }[]): void {
  resetGraph();
  applyGraph({
    sessions: [
      { session_id: "a", handle: "alpha", title: "", workspace: "/w", status: "idle", kind: "zettcode" },
      { session_id: "b", handle: "bravo", title: "", workspace: "/w", status: "working", kind: "zettcode" },
    ],
    groups,
    edges: [],
    recent: [],
  });
}

async function withPages(pages: Record<number, { messages: GraphMessage[]; more: boolean }>, run: (urls: string[]) => Promise<void>): Promise<void> {
  const real = globalThis.fetch;
  const urls: string[] = [];
  globalThis.fetch = (async (u: string) => {
    urls.push(String(u));
    const before = Number(new URL(String(u), "http://x").searchParams.get("before"));
    return new Response(JSON.stringify(pages[before] ?? { messages: [], more: false }), { status: 200 });
  }) as typeof fetch;
  try {
    await run(urls);
  } finally {
    globalThis.fetch = real;
  }
}

test("a group's name may be in any language, one word, and no wider than the broker's rule", () => {
  for (const ok of ["review", "测试群", "équipe-2", "项目_A", "हिन्दी", "தமிழ்"]) assert.ok(GROUP_NAME.test(ok), ok);
  for (const bad of ["", "a b", "测试 群", "-lead", "_x", "a/b", "a#b", "x".repeat(41), "a\u200db", "\u0301x"]) assert.ok(!GROUP_NAME.test(bad), bad);
});

test("a typed name is spelled as the broker spells it where JavaScript can: compatibility form, no #, lower case", () => {
  assert.equal(spellGroup(" ＃Team "), "team");
  assert.equal(spellGroup("cafe\u0301"), "caf\u00e9");
  assert.equal(spellGroup("##Review"), "review");
  assert.equal(spellGroup("Straße"), "strasse", "ß folds to ss as the broker's casefold does");
  assert.equal(spellGroup("ΟΔΥΣΣΕΥΣ"), spellGroup("οδυσσευς"), "a final sigma folds to the same letter");
  assert.equal(groupNameOf("#Straße"), "strasse", "a typed or bookmarked address finds the stored name");
  assert.equal(groupNameOf("01a1-session"), "01a1-session", "a session id is left alone");
});

test("a group is addressed as #name and a session id is not mistaken for one", () => {
  assert.equal(groupArg("team"), "#team");
  assert.ok(isGroupArg("#team") && !isGroupArg("01abc"));
  assert.equal(groupNameOf("#team"), "team");
});

test("groups are listed with the most recently written to first, and an empty one by when it was made", () => {
  start([
    { name: "old", members: ["a"], created: 5, last: say(10, "old") },
    { name: "new", members: ["a"], created: 1, last: say(30, "new") },
    { name: "fresh", members: ["a"], created: 20 },
  ]);
  assert.deepEqual(groupList.value.map((group) => group.name), ["new", "fresh", "old"]);
});

test("members come online first, named from the conversation list, then the roster, then the id", () => {
  applyThreads([thread("c", "carol-daemon")]);
  start([{ name: "team", members: ["c", "b", "a", "zzzzzzzzzzzz"], created: 1 }]);
  const members = membersOf(groupList.value[0]!);
  assert.deepEqual(members.map((member) => member.name), ["alpha", "bravo", "carol-daemon", "zzzzzzzz"]);
  assert.deepEqual(members.map((member) => member.online), [true, true, false, false]);
  assert.equal(members.find((member) => member.id === "b")?.status, "working");
  assert.equal(members.find((member) => member.id === "c")?.chat, true);
});

test("an offline member can be mentioned by its title as one word, and an online one by its roster handle", () => {
  // As the gateway really lists a stopped daemon: no handle (the roster dropped it), a title.
  applyThreads([
    { ...thread("p", "planner"), handle: "", title: "Release Planner (v2)", online: false },
    { ...thread("n", "nameless"), handle: "", title: "", name: "", online: false },
  ]);
  start([{ name: "team", members: ["a", "p", "n"], created: 1 }]);

  const byId = Object.fromEntries(membersOf(groupList.value[0]!).map((member) => [member.id, member]));

  assert.equal(byId.a?.handle, "alpha", "online: the roster's handle");
  assert.equal(byId.a?.address, true, "a roster handle is an address the broker resolves");
  assert.equal(byId.p?.handle, "Release-Planner-v2", "offline: its title, written as one word");
  assert.equal(byId.p?.address, false, "a word made from a title is a name, not an address, and is not shown as one");
  assert.equal(byId.p?.online, false);
  assert.equal(byId.n?.handle, "", "nothing to call it by: it is not offered, and the picker says so");
  assert.equal(byId.n?.address, false);
});

test("two offline members whose titles make the same word are both listed, and neither claims an address", () => {
  applyThreads([
    { ...thread("p", "one"), handle: "", title: "Planner!", online: false },
    { ...thread("q", "two"), handle: "", title: "planner?", online: false },
  ]);
  start([{ name: "team", members: ["p", "q"], created: 1 }]);

  const found = membersOf(groupList.value[0]!).filter((member) => !member.me);

  assert.deepEqual(found.map((member) => member.name).sort(), ["one", "two"]);
  assert.ok(found.every((member) => !member.address), "so the picker does not show either as @planner");
});

test("opening a group reads its newest messages, and earlier ones are added in front from the oldest held", async () => {
  start([{ name: "team", members: ["a"], created: 1 }]);
  await withPages(
    { 0: { messages: [say(8, "team"), say(9, "team")], more: true }, 8: { messages: [say(6, "team"), say(7, "team")], more: false } },
    async (urls) => {
      await openGroup("team");
      assert.deepEqual(groupChat.messages.map((m) => m.id), [8, 9]);
      assert.equal(groupChat.more, true);
      assert.match(urls[0]!, /group=team/);
      await loadEarlierGroup();
      assert.deepEqual(groupChat.messages.map((m) => m.id), [6, 7, 8, 9]);
      assert.equal(groupChat.more, false);
      await loadEarlierGroup();
      assert.equal(urls.length, 2, "nothing more is asked for once none remain");
    },
  );
});

test("unread counts of a group the graph no longer lists are dropped whenever the graph is read again", async () => {
  start([{ name: "gone", members: ["a", "b"], created: 1 }, { name: "kept", members: ["a", "b"], created: 1 }]);
  applyGroupTraffic(say(1, "gone", "b"));
  applyGroupTraffic(say(2, "kept", "b"));
  assert.equal(unreadOf("gone"), 1);

  applyGraph({ sessions: [], groups: [{ name: "kept", members: ["a", "b"], created: 1 }], edges: [], recent: [] });

  assert.equal(unreadOf("gone"), 0, "a group of that name made later does not start with a stale badge");
  assert.equal(unreadOf("kept"), 1);
});

test("a listener that throws does not break the read, and a reset tells the listeners too", async () => {
  const calls: string[] = [];
  const stop = [
    onGraphApplied(() => {
      throw new Error("a bad listener");
    }),
    onGraphApplied(() => calls.push("after the bad one")),
  ];
  try {
    applyGraph({ sessions: [], groups: [{ name: "kept", members: ["a"], created: 1 }], edges: [], recent: [] });
    assert.equal(graph.groups.length, 1, "the graph is in place");
    assert.deepEqual(calls, ["after the bad one"]);
    resetGraph();
    assert.deepEqual(calls, ["after the bad one", "after the bad one"]);
  } finally {
    for (const off of stop) off();
  }
});

test("a message written in the open group is shown there; in another it is counted as unread and updates the list", async () => {
  start([
    { name: "team", members: ["a", "b"], created: 1 },
    { name: "other", members: ["a", "b"], created: 1 },
  ]);
  await withPages({ 0: { messages: [], more: false } }, async () => {
    await openGroup("team");
  });
  applyGroupTraffic(say(1, "team", "b"));
  applyGroupTraffic(say(1, "team", "b"));
  applyGroupTraffic(say(2, "other", "b"));
  applyGroupTraffic(say(3, "other", "b"));

  assert.deepEqual(groupChat.messages.map((m) => m.id), [1], "once, whatever the number of times it is told");
  assert.equal(unreadOf("team"), 0);
  assert.equal(unreadOf("other"), 2);
  assert.equal(groupList.value[0]!.name, "other");
  assert.equal(groupList.value.find((group) => group.name === "other")?.last?.id, 3);
});

test("a group name is what the broker accepts: letters of any script, digits, - and _, 1 to 40, not starting with a symbol", () => {
  for (const good of ["review", "a", "team-1", "x_y", "0day", "a".repeat(40), "组"]) assert.ok(GROUP_NAME.test(good), good);
  for (const bad of ["", "-lead", "_x", "two words", "a".repeat(41), "#review"]) assert.ok(!GROUP_NAME.test(bad), bad);
});
