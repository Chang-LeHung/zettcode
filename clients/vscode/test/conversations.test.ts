import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { Conversations, newConversation } from "../src/core/conversations.js";
import { applyEvent, createTurn } from "../src/core/state.js";

function running() {
  const conversation = newConversation();
  const turn = createTurn("long task", [], 1000, "turn-a");
  conversation.turns.push(turn);
  conversation.running = turn;
  conversation.busy = true;
  return { conversation, turn };
}

test("a conversation that is running is kept when the reader looks at another one", () => {
  const set = new Conversations();
  const { conversation: first } = running();
  set.current = first;
  set.register("session-a", first);

  const second = newConversation();
  set.show("session-b", second);

  assert.equal(set.current, second);
  assert.equal(set.find("session-a"), first, "its run still has somewhere to write");
  assert.deepEqual(set.runningIds(), ["session-a"]);
});

test("a conversation that is idle is let go when the reader leaves it", () => {
  const set = new Conversations();
  const idle = newConversation();
  set.show("session-a", idle);

  set.show("session-b", newConversation());

  assert.equal(set.find("session-a"), undefined, "the store has all it held; opening it reads it back");
  assert.ok(set.find("session-b"));
});

test("the frames of a run that is not on show are written to its own turns, and coming back finds them", () => {
  const set = new Conversations();
  const { conversation: first, turn } = running();
  set.current = first;
  set.register("session-a", first);
  set.show("session-b", newConversation());

  applyEvent(turn, { type: "text_delta", text: "still working on it" } as never, 2000);

  set.show("session-a", set.find("session-a")!);
  assert.equal(set.current, first);
  const block = set.current.turns[0]?.blocks.find((candidate) => candidate.kind === "text");
  assert.ok(block && "text" in block && block.text.includes("still working on it"), "what the run wrote meanwhile");
});

test("a run that ends in the background is forgotten by identity, so the list stops showing it as running", () => {
  const set = new Conversations();
  const { conversation: first } = running();
  set.current = first;
  set.register("session-a", first);
  set.show("session-b", newConversation());

  first.busy = false;
  set.forget(first);

  assert.equal(set.find("session-a"), undefined);
  assert.deepEqual(set.runningIds(), []);
});

test("showing the conversation that is already on show changes nothing and drops nothing", () => {
  const set = new Conversations();
  const { conversation } = running();
  set.show("session-a", conversation);

  set.show("session-a", conversation);

  assert.equal(set.find("session-a"), conversation);
  assert.equal(set.current, conversation);
});

test("a restarted server has none of the old runs, so nothing is kept", () => {
  const set = new Conversations();
  const { conversation } = running();
  set.show("session-a", conversation);

  set.reset();

  assert.equal(set.find("session-a"), undefined);
  assert.notEqual(set.current, conversation);
  assert.equal(set.current.busy, false);
});

test("the host no longer asks the reader to stop a run before switching or starting a session", async () => {
  const chat = await readFile("src/chat.ts", "utf8");
  assert.ok(!chat.includes("Stop the run before switching sessions"));
  assert.ok(!chat.includes("Stop the run before starting another session"));
  assert.ok(/convs\.register\(this\.session\.id, conv\)/.test(chat), "a run is registered under its session when it starts");
  assert.ok(chat.includes("afterBackgroundRun"), "a run that ends while another session is on show is settled on its own");
});
