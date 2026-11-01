import assert from "node:assert/strict";
import { test } from "node:test";
import { counts, parseLine, parseLog, visible } from "../src/lib/logs";

// The wording below is what a daemon writes in zettcode/src/zettcode/daemon/run.py (`Daemon._see` and `_turn`), which
// zettcode/tests/test_daemon.py pins from the other side. Change one side and change the other.

test("a tool line gives the tool and what it was for, and an old one gives only the tool", () => {
  const now = parseLine("2026-11-01 19:49:04 tool bash · git status -s");
  assert.deepEqual([now.kind, now.name, now.text, now.time, now.date], ["tool", "bash", "git status -s", "19:49:04", "2026-11-01"]);
  const old = parseLine("2026-11-01 19:49:04 tool bash");
  assert.deepEqual([old.kind, old.name, old.text], ["tool", "bash", ""]);
});

test("a failed tool is a problem that keeps its tool and its reason; a slow one is information", () => {
  const bad = parseLine("2026-11-01 20:00:00 tool bash failed after 1.0s: exit 1 boom");
  assert.deepEqual([bad.kind, bad.name, bad.text], ["error", "bash", "exit 1 boom"]);
  const older = parseLine("2026-11-01 20:00:00 tool bash failed: exit 1");
  assert.deepEqual([older.kind, older.name, older.text], ["error", "bash", "exit 1"]);
  const slow = parseLine("2026-11-01 20:00:00 tool read finished in 7.0s");
  assert.deepEqual([slow.kind, slow.name, slow.text], ["info", "read", "finished in 7.0s"]);
});

test("a turn starts and ends, and the daemon's own trouble is a problem", () => {
  assert.equal(parseLine("2026-11-01 20:00:00 turn from dawn (agent): hi").kind, "turn");
  assert.equal(parseLine("2026-11-01 20:00:09 turn finished in 9.0s").text, "finished in 9.0s");
  assert.equal(parseLine("2026-11-01 20:00:09 the turn failed (attempt 1 of 4): boom").kind, "error");
  assert.equal(parseLine("2026-11-01 20:00:09 now running fast · effort low").kind, "info");
});

test("a line with no stamp is kept whole", () => {
  const line = parseLine("Traceback (most recent call last):");
  assert.deepEqual([line.kind, line.time, line.text], ["error", "", "Traceback (most recent call last):"]);
});

test("filters and search narrow the lines, and the counts agree with them", () => {
  const lines = parseLog(
    [
      "2026-11-01 20:00:00 turn from dawn (agent): hi",
      "2026-11-01 20:00:01 tool bash · ls",
      "2026-11-01 20:00:02 tool bash failed after 0.1s: no",
      "",
      "2026-11-01 20:00:03 tool read · a.py",
      "2026-11-01 20:00:09 tool read finished in 7.0s",
      "2026-11-01 20:00:10 tool bash skipped: steering took over",
    ].join("\n"),
  );
  assert.equal(lines.length, 6);
  assert.deepEqual(counts(lines), { all: 6, tools: 5, problems: 1 });
  assert.equal(visible(lines, "tools", "").length, 5, "a slow or skipped tool is still about a tool");
  assert.equal(visible(lines, "problems", "").length, 1);
  assert.equal(visible(lines, "all", " A.PY ").length, 1);
  assert.equal(visible(lines, "problems", "a.py").length, 0);
});
