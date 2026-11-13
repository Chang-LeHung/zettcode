import "./dom-setup";
import assert from "node:assert/strict";
import { test } from "node:test";
import { initial, offered, optionsOf } from "../src/lib/agentFields";
import type { AgentField } from "../src/types";

const access: AgentField = {
  name: "permission",
  label: "Access",
  kind: "choice",
  choices: ["full", "workspace", "read"],
  default: "",
  help: "",
  unrestricted: "full",
};
const folder: AgentField = { name: "cwd", label: "Folder", kind: "directory", choices: [], default: "", help: "", unrestricted: "" };

test("the unrestricted choice is not offered by a gateway that does not allow it, and the rest are", () => {
  assert.deepEqual(offered(access, true), ["full", "workspace", "read"]);
  assert.deepEqual(offered(access, false), ["workspace", "read"]);
  assert.deepEqual(offered({ ...access, unrestricted: "" }, false), ["full", "workspace", "read"]);
});

test("a default that the gateway would refuse is not preselected", () => {
  const cautious = { ...access, default: "full" };
  assert.equal(initial(cautious, true), "full");
  assert.equal(initial(cautious, false), "");
  assert.equal(initial({ ...access, default: "read" }, false), "read");
  assert.equal(initial(folder, true), "");
  assert.equal(initial({ ...folder, default: "/work" }, true), "/work");
});

test("only what was filled in is sent, trimmed, so the plugin's own setting applies to the rest", () => {
  assert.deepEqual(optionsOf([folder, access], { cwd: "  /work/app ", permission: "" }), { cwd: "/work/app" });
  assert.deepEqual(optionsOf([folder, access], {}), {});
  assert.deepEqual(optionsOf([folder], { cwd: "   ", other: "x" }), {});
  assert.deepEqual(optionsOf([access], { permission: "read", cwd: "/ignored" }), { permission: "read" });
});
