import assert from "node:assert/strict";
import { test } from "node:test";
import { buildRows, settleLive } from "../src/lib/rows";
import type { ChatItem, LiveTurn } from "../src/types";

const tool = (name: string, ok?: boolean): ChatItem => ({ kind: "tool", name, brief: name, ok });

test("a tool that is stored and still running is drawn once, with the state the live turn knows", () => {
  const items: ChatItem[] = [{ kind: "out", text: "go" }, tool("bash"), tool("bash")];
  const turn: LiveTurn = {
    text: "",
    thinking: false,
    tools: [
      { id: "1", name: "bash", brief: "bash", ok: true },
      { id: "2", name: "bash", brief: "bash", ok: true },
    ],
  };

  const rows = buildRows(items, [], turn);
  const steps = rows.filter((row) => row.type === "steps");

  assert.equal(steps.length, 1);
  assert.deepEqual(steps[0]?.type === "steps" && steps[0].tools.map((one) => one.ok), [true, true]);
});

test("a live tool that is not stored yet joins the steps of its turn", () => {
  const items: ChatItem[] = [{ kind: "out", text: "go" }, tool("read", true)];
  const turn: LiveTurn = {
    text: "",
    thinking: false,
    tools: [
      { id: "1", name: "read", brief: "read", ok: true },
      { id: "2", name: "bash", brief: "bash", ok: null },
    ],
  };

  const steps = buildRows(items, [], turn).filter((row) => row.type === "steps");

  assert.equal(steps.length, 1);
  assert.deepEqual(steps[0]?.type === "steps" && steps[0].tools.map((one) => one.name), ["read", "bash"]);
});

test("the live answer is cut down to what the conversation does not hold yet", () => {
  const items: ChatItem[] = [{ kind: "out", text: "go" }, { kind: "in", text: "First." }, tool("bash", true)];
  const turn: LiveTurn = { text: "First. Second", thinking: false, tools: [{ id: "1", name: "bash", brief: "", ok: true }] };

  assert.equal(settleLive(items, turn).text, "Second");
  assert.equal(settleLive(items, undefined).text, "");
});

test("a turn of the past is not taken for the running one", () => {
  const items: ChatItem[] = [{ kind: "out", text: "one" }, tool("bash", true), { kind: "in", text: "done" }, { kind: "out", text: "two" }];
  const turn: LiveTurn = { text: "ok", thinking: false, tools: [] };

  const settled = settleLive(items, turn);

  assert.equal(settled.text, "ok");
  assert.equal(settled.tools.length, 0);
});
