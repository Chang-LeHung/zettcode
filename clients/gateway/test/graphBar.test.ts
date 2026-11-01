import assert from "node:assert/strict";
import { test } from "node:test";
import { fractionOf, fromLocalInput, replayGroups, stepTarget, timeAt, toLocalInput } from "../src/lib/graphBar";
import { buildReplay } from "../src/lib/graphReplay";
import type { GraphMessage } from "../src/types";

const msg = (id: number, ts: number, group?: string): GraphMessage =>
  ({
    id,
    ts,
    via: "agent",
    from: { session_id: "a", handle: "a", title: "" },
    to: group ? { kind: "group", name: group } : { kind: "session", session_id: "b" },
    recipients: ["b", "c"],
    text: "x",
  }) as unknown as GraphMessage;

test("local input round-trips to the minute", () => {
  const ts = Math.floor(Date.now() / 60000) * 60;
  assert.equal(fromLocalInput(toLocalInput(ts)), ts);
  assert.equal(fromLocalInput(""), null);
  assert.equal(fromLocalInput("nope"), null);
});

test("fraction and time map both ways and clamp", () => {
  const r = buildReplay([], 100, 200);
  assert.equal(fractionOf(r, 150), 0.5);
  assert.equal(fractionOf(r, 500), 1);
  assert.equal(timeAt(r, 0.25), 125);
  assert.equal(timeAt(r, -1), 100);
  assert.equal(fractionOf(buildReplay([], 5, 5), 5), 0);
});

test("stepTarget finds the neighbouring message or the window's end", () => {
  const r = buildReplay([msg(1, 110), msg(2, 150)], 100, 200);
  assert.equal(stepTarget(r, 100, 1), 110);
  assert.equal(stepTarget(r, 110, 1), 150);
  assert.equal(stepTarget(r, 150, 1), 200);
  assert.equal(stepTarget(r, 150, -1), 110);
  assert.equal(stepTarget(r, 110, -1), 100);
});

test("replayGroups adds a touched group that is not known", () => {
  const groups = replayGroups([msg(1, 110, "dev")], new Set(["dev"]), [{ name: "ops", members: ["a"], created: 1 }]);
  assert.deepEqual(groups.map((g) => g.name), ["ops", "dev"]);
  assert.deepEqual(groups[1]!.members.sort(), ["a", "b", "c"]);
});
