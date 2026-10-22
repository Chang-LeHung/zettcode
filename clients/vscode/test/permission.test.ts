import assert from "node:assert/strict";
import test from "node:test";

import { approvalsFor } from "../src/core/permission.js";

test("each permission level maps to one approval policy", () => {
  assert.deepEqual(approvalsFor("deny"), { mode: "deny" });
  assert.deepEqual(approvalsFor("ask"), { mode: "ask" });
  assert.deepEqual(approvalsFor("safe"), { mode: "ask" }, "the server runs it in the sandbox and never asks");
  assert.deepEqual(approvalsFor("full"), { mode: "auto" });
});

test("auto, the old name of full, still maps to full's policy", () => {
  assert.deepEqual(approvalsFor("auto"), { mode: "auto" });
});
