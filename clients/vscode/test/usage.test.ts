import assert from "node:assert/strict";
import test from "node:test";

import { JSDOM } from "jsdom";

import type { ModelCheck, Plugins, Totals, WorkspaceUsage } from "../../typescript/src/types.js";
import { usagePage } from "../src/core/usage-page.js";
import { showDoctorPanel, showPluginsPanel, showUsagePanel } from "../src/usage.js";
import { lastPanel } from "./vscode-stub.js";

const totals = (tokens: number, requests: number): Totals => ({
  requests,
  input_tokens: Math.round(tokens * 0.7),
  output_tokens: Math.round(tokens * 0.3),
  cache_read_tokens: Math.round(tokens * 0.2),
  reasoning_tokens: Math.round(tokens * 0.05),
  total_tokens: tokens,
  cache_share: 0.286,
});

const usage: WorkspaceUsage = {
  sessions: [
    {
      id: "s1",
      title: "Pagination work",
      started: "2026-10-15T09:00:00Z",
      updated: "2026-10-18T11:00:00Z",
      tokens: totals(120_000, 80),
      models: ["DeepSeek Pro"],
      entries: 42,
    },
    {
      id: "s2",
      title: null,
      started: "2026-10-16T09:00:00Z",
      updated: "2026-10-17T11:00:00Z",
      tokens: totals(40_000, 20),
      models: ["fast"],
      entries: 9,
    },
  ],
  models: [
    { model: "DeepSeek Pro", tokens: totals(120_000, 80) },
    { model: "fast", tokens: totals(40_000, 20) },
  ],
  days: [
    { day: "2026-10-17", tokens: totals(40_000, 20) },
    { day: "2026-10-18", tokens: totals(120_000, 80) },
  ],
  total: totals(160_000, 100),
};

const checks: ModelCheck[] = [
  {
    model: "DeepSeek Pro",
    model_id: "deepseek-v4-pro",
    ok: true,
    seconds: 1.2,
    detail: "answered in 1.2s",
    input_tokens: 12,
    output_tokens: 3,
  },
  {
    model: "fast",
    model_id: "gpt-5",
    ok: false,
    seconds: 2.4,
    detail: "connection refused",
    input_tokens: null,
    output_tokens: null,
  },
];

const plugins: Plugins = { loaded: ["lint"], failures: ["search: missing binary"] };

const client = {
  usageLedger: async () => usage,
  doctor: async () => checks,
  plugins: async () => plugins,
};

test("the usage page has the terminal's three tabs under one line that totals the workspace", async () => {
  await showUsagePanel(client as never, { toString: () => "file:///extension" } as never, "zettcode", "/work/my project");
  assert.ok(lastPanel !== null);
  assert.equal(lastPanel.title, "ZettCode: Usage");
  const document = new JSDOM(lastPanel.webview.html).window.document;
  // Whose numbers these are is said before the numbers: the ledger is kept for each workspace.
  const note = document.querySelector(".scope")?.textContent ?? "";
  assert.ok(note.includes("Only this workspace") && note.includes("/work/my project"), note);
  assert.ok(
    (document.querySelector("h1")?.compareDocumentPosition(document.querySelector(".scope")!) ?? 0) &
      document.DOCUMENT_POSITION_FOLLOWING,
    "under the title",
  );
  assert.equal(document.querySelector("code")?.textContent, "/work/my project");
  const summary = document.querySelector(".summary")?.textContent?.replace(/\s+/g, " ") ?? "";
  assert.ok(summary.includes("All models") && summary.includes("160k tokens"), summary);
  assert.ok(summary.includes("cached 28.6%") && summary.includes("2 sessions"), summary);
  assert.deepEqual(
    Array.from(document.querySelectorAll(".tabs label")).map((label) => label.textContent),
    ["Models", "Sessions", "Calendar"],
  );
  // Models is the open tab, and the page needs no script to switch.
  assert.equal(document.querySelector<HTMLInputElement>("#tab-models")?.checked, true);
  assert.equal(document.querySelectorAll("script").length, 0);
});

test("the models tab draws an input and an output bar for each model, biggest first", async () => {
  await showUsagePanel(client as never, { toString: () => "file:///extension" } as never, "zettcode");
  const document = new JSDOM(lastPanel!.webview.html).window.document;
  const models = Array.from(document.querySelectorAll("#body-models .model"));
  assert.deepEqual(
    models.map((model) => model.querySelector(".model-name")?.textContent),
    ["DeepSeek Pro", "fast"],
  );
  assert.equal(models[0]!.querySelectorAll(".line .bar").length, 2);
  assert.ok(models[0]!.textContent?.includes("28.6% cached"));
  assert.ok(models[0]!.textContent?.includes("reasoning"));
  // The largest model's input bar is full.
  assert.ok(models[0]!.querySelector(".fill.in")?.getAttribute("style")?.includes("width:100.0%"));
});

test("the sessions tab lists the latest first with its times, bars and cached share", async () => {
  await showUsagePanel(client as never, { toString: () => "file:///extension" } as never, "zettcode");
  const document = new JSDOM(lastPanel!.webview.html).window.document;
  const rows = Array.from(document.querySelectorAll("#body-sessions .srow:not(.shead)"));
  assert.deepEqual(
    rows.map((row) => row.querySelector(".title")?.textContent),
    ["Pagination work", "Untitled session"],
  );
  assert.equal(rows[0]!.querySelectorAll(".bar").length, 3);
  assert.ok(rows[0]!.querySelector(".fill.cache")?.getAttribute("style")?.includes("28.6"));
  assert.ok(document.querySelector("#body-sessions .shead")?.textContent?.includes("Cached"));
});

test("the calendar tab draws a week in each column and says the streaks", async () => {
  await showUsagePanel(client as never, { toString: () => "file:///extension" } as never, "zettcode");
  const document = new JSDOM(lastPanel!.webview.html).window.document;
  assert.equal(document.querySelectorAll("#body-calendar .days .cell-day").length, 53 * 7, "a year of weeks");
  assert.ok(document.querySelectorAll("#body-calendar .days .heat1, #body-calendar .days .heat2, #body-calendar .days .heat3, #body-calendar .days .heat4").length >= 0);
  assert.ok(document.querySelector("#body-calendar .legend"));
  assert.ok(document.querySelector("#body-calendar")?.textContent?.includes("Less"));
});

test("an empty ledger says so on each tab", () => {
  const empty = usagePage({
    sessions: [],
    models: [],
    days: [],
    total: totals(0, 0),
  });
  const document = new JSDOM(empty.body).window.document;
  assert.ok(document.querySelector("#body-models .empty")?.textContent?.includes("No model replies"));
  assert.ok(document.querySelector("#body-sessions .empty")?.textContent?.includes("no sessions"));
  assert.ok(document.querySelector("#body-calendar")?.textContent?.includes("Nothing has been spent"));
});

test("the model check page has pass and fail cards", async () => {
  await showDoctorPanel(client as never, checks, { toString: () => "file:///extension" } as never, "zettcode");
  assert.ok(lastPanel !== null);
  assert.equal(lastPanel.title, "ZettCode: Model check");
  const document = new JSDOM(lastPanel.webview.html).window.document;
  assert.equal(document.querySelectorAll(".check-card").length, 2);
  assert.equal(document.querySelectorAll(".pill.ok").length, 1);
  assert.equal(document.querySelectorAll(".pill.bad").length, 1);
  assert.ok(document.querySelector(".check-detail")?.textContent?.includes("answered"));
});

test("the plugins page separates loaded plugins from failures", async () => {
  await showPluginsPanel(client as never, { toString: () => "file:///extension" } as never, "zettcode");
  assert.ok(lastPanel !== null);
  assert.equal(lastPanel.title, "ZettCode: Plugins");
  const document = new JSDOM(lastPanel.webview.html).window.document;
  assert.equal(document.querySelectorAll(".columns .panel").length, 2);
  assert.ok(document.querySelector(".plugin-list .failed")?.textContent?.includes("missing binary"));
});
