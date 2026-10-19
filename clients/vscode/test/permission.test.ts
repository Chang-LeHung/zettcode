import assert from "node:assert/strict";
import test from "node:test";

import { approvalsFor } from "../src/core/permission.js";

test("each permission level maps to one approval policy", () => {
  assert.deepEqual(approvalsFor("deny"), { mode: "deny" });
  assert.deepEqual(approvalsFor("ask"), { mode: "ask" });
  assert.deepEqual(approvalsFor("safe"), { mode: "ask" });
  assert.deepEqual(approvalsFor("auto"), { mode: "auto" });
});
