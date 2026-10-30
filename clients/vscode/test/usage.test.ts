import assert from "node:assert/strict";
import test from "node:test";

import { JSDOM } from "jsdom";

import type { ModelCheck, PluginEntry, PluginReport, Totals, WorkspaceUsage } from "../../typescript/src/types.js";
import { usagePage } from "../src/core/usage-page.js";
import { showDoctorPanel, showPluginsPanel, showUsagePanel } from "../src/usage.js";
import { lastPanel, posted, receive } from "./vscode-stub.js";

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

const entries: PluginEntry[] = [
  { ...base("skills", "skills", true), setting: "skills.enabled" },
  { ...base("mcp", "mcp", true), enabled: false, setting: "mcp.enabled" },
  base("lint", "zettcode-lint"),
  { ...base("search", "zettcode-search"), failure: "missing binary" },
  { ...base("acme", "zettcode-acme"), enabled: false },
  // A row the server says cannot be moved: the panel draws why instead of a switch.
  { ...base("held", "zettcode-held"), enabled: false, switchable: false, why: "switched off in the configuration file" },
];

/** One entry with the defaults a fixture does not care about. */
function base(name: string, origin: string, builtin = false): PluginEntry {
  return { name, origin, builtin, enabled: true, failure: "", setting: "", switchable: true, why: "" };
}

const plugins: PluginReport = {
  loaded: ["skills", "mcp", "lint"],
  failures: ["zettcode-search: missing binary"],
  entries,
};

const client = {
  usageLedger: async () => usage,
  doctor: async () => checks,
  plugins: async () => plugins,
  setPluginEnabled: async (name: string, enabled: boolean): Promise<PluginEntry> => {
    const from = entries.find((entry) => entry.origin === name);
    if (from === undefined) {
      throw new Error(`No plugin is called ${name}`);
    }
    return { ...from, enabled };
  },
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

test("the plugins page separates the program's own from the installed ones, and says what is off", async () => {
  await showPluginsPanel(async () => client as never, { toString: () => "file:///extension" } as never, "zettcode");
  assert.ok(lastPanel !== null);
  assert.equal(lastPanel.title, "ZettCode: Plugins");
  const document = new JSDOM(lastPanel.webview.html).window.document;

  assert.deepEqual(
    Array.from(document.querySelectorAll(".columns .panel h2")).map((node) => node.textContent),
    ["Built in", "Installed"],
  );
  const panelOf = (title: string): Element | undefined =>
    Array.from(document.querySelectorAll(".columns .panel")).find(
      (node) => node.querySelector("h2")?.textContent === title,
    );
  const names = (title: string): (string | null)[] =>
    Array.from(panelOf(title)?.querySelectorAll(".plugin-name") ?? []).map((node) => node.textContent);
  assert.deepEqual(names("Built in"), ["skills", "mcp"]);
  assert.deepEqual(names("Installed"), ["lint", "search", "acme", "held"]);

  const summary = document.querySelector(".summary")?.textContent?.replace(/\s+/g, " ") ?? "";
  assert.ok(
    summary.includes("3 of 5 switches on") && summary.includes("1 failed") && summary.includes("1 without a switch"),
    summary,
  );
  const note = document.querySelector(".scope")?.textContent?.replace(/\s+/g, " ") ?? "";
  assert.ok(note.includes("next start"), "a switch is a promise about the next start");
  assert.ok(note.includes("configuration key") && note.includes("/plugins"), "and says where each one is written");
});

test("a row has a switch when the server says it can move, and says why when it cannot", async () => {
  await showPluginsPanel(async () => client as never, { toString: () => "file:///extension" } as never, "zettcode");
  const document = new JSDOM(lastPanel!.webview.html).window.document;

  assert.equal(
    document.querySelectorAll(".plugin .switch").length,
    entries.filter((entry) => entry.switchable).length,
    "a switch per plugin that can move, and none for the rest",
  );
  const held = document.querySelector('.plugin[data-name="zettcode-held"]');
  assert.equal(held?.querySelector(".switch"), null, "the button would only ever be refused");
  assert.equal(held?.querySelector(".chip")?.textContent, "no switch");
  assert.ok(held?.textContent?.includes("switched off in the configuration file"), "the row says why");

  const skills = document.querySelector('.plugin[data-name="skills"]');
  assert.equal(skills?.querySelector(".switch")?.getAttribute("aria-pressed"), "true");
  assert.equal(skills?.querySelector(".switch")?.getAttribute("title"), "Writes skills.enabled");

  const mcp = document.querySelector('.plugin[data-name="mcp"]');
  assert.equal(mcp?.querySelector(".switch")?.getAttribute("aria-pressed"), "false");
  assert.equal(mcp?.querySelector(".switch-word")?.textContent, "off");

  const lint = document.querySelector('.plugin[data-name="zettcode-lint"]');
  assert.equal(lint?.querySelector(".switch")?.getAttribute("title"), "Writes the plugin switch file");
  assert.ok(lint?.textContent?.includes("zettcode-lint"), "the name a switch is written with is on the row");

  assert.equal(document.querySelector('.plugin[data-name="zettcode-acme"] .switch')?.getAttribute("aria-pressed"), "false");
  assert.ok(document.querySelector('.plugin[data-name="zettcode-search"]')?.textContent?.includes("missing binary"));
});

test("pressing a switch writes through the host and moves the row on the answer", async () => {
  await showPluginsPanel(async () => client as never, { toString: () => "file:///extension" } as never, "zettcode");
  posted.length = 0;

  await receive({ type: "switch", name: "zettcode-acme", enabled: true });

  assert.deepEqual(posted.at(-1), { type: "switched", name: "zettcode-acme", enabled: true, error: "" });
});

test("a switch the server refuses comes back as why, on the row it was pressed on", async () => {
  const refused = {
    ...client,
    setPluginEnabled: async (): Promise<PluginEntry> => {
      throw new Error("acme is switched off in the configuration file");
    },
  };
  await showPluginsPanel(async () => refused as never, { toString: () => "file:///extension" } as never, "zettcode");
  posted.length = 0;

  await receive({ type: "switch", name: "zettcode-acme", enabled: true });

  assert.deepEqual(posted.at(-1), {
    type: "switched",
    name: "zettcode-acme",
    enabled: true,
    error: "acme is switched off in the configuration file",
  });
});

test("the plugins page's script is one its own policy allows, and it speaks the message the host answers", async () => {
  await showPluginsPanel(async () => client as never, { toString: () => "file:///extension" } as never, "zettcode");
  const html = lastPanel!.webview.html;
  const document = new JSDOM(html).window.document;

  const script = document.querySelector("script");
  const nonce = script?.getAttribute("nonce") ?? "";
  assert.ok(nonce.length >= 16, "a nonce long enough not to be guessed");
  const policy = document.querySelector('meta[http-equiv="Content-Security-Policy"]')?.getAttribute("content") ?? "";
  assert.ok(policy.includes(`script-src 'nonce-${nonce}'`), policy);
  assert.equal(document.querySelectorAll("script").length, 1, "the page's one script, and no second");

  // The halves of the protocol are in two languages: a press posts `switch`, and the host answers `switched`.
  assert.ok(script?.textContent?.includes('type: "switch"'), "the script posts the message the host listens for");
  assert.ok(script?.textContent?.includes('message.type !== "switched"'), "and waits for the one it sends back");
});

test("a server that sends no entries gets names without switches, not switches it cannot serve", async () => {
  const old = { ...client, plugins: async () => ({ loaded: ["lint"], failures: ["search: missing binary"] }) };
  await showPluginsPanel(async () => old as never, { toString: () => "file:///extension" } as never, "zettcode");
  const document = new JSDOM(lastPanel!.webview.html).window.document;

  assert.equal(document.querySelectorAll(".switch").length, 0, "nothing to press: that server cannot move one");
  assert.ok(document.body.textContent?.includes("does not report which plugins can be switched"));
});

test("the summary counts what the switches say, and the script recounts on an answer", async () => {
  await showPluginsPanel(async () => client as never, { toString: () => "file:///extension" } as never, "zettcode");
  const document = new JSDOM(lastPanel!.webview.html).window.document;

  assert.equal(document.getElementById("plugins-on")?.textContent, "3");
  assert.equal(document.getElementById("plugins-switches")?.textContent, "5");
  assert.equal(document.getElementById("plugins-failed")?.textContent, "1");
  assert.equal(document.getElementById("plugins-noswitch")?.textContent, "1", "the row the file holds is counted");

  // The script keeps them right after a flip, and counts a switch's own state rather than a row's colour.
  const script = document.querySelector("script")?.textContent ?? "";
  assert.ok(script.includes('set("plugins-on", lit)'), "the counts are rewritten from the switches");
  assert.ok(script.includes(`.switch[data-enabled="true"]`), "a row that failed is neither on nor off");
});

test("an empty catalog is a page with nothing to switch, not an old server", async () => {
  const empty = { ...client, plugins: async () => ({ loaded: [], failures: [], entries: [] }) };
  await showPluginsPanel(async () => empty as never, { toString: () => "file:///extension" } as never, "zettcode");
  const document = new JSDOM(lastPanel!.webview.html).window.document;

  assert.equal(document.querySelectorAll(".plugin").length, 0, "no row was invented from the names");
  assert.equal(document.querySelectorAll(".switch").length, 0);
  const text = document.body.textContent ?? "";
  assert.ok(text.includes("No plugin the program carries can be switched"), text);
  assert.ok(text.includes("No plugin is installed beside the program"), text);
  assert.equal(document.getElementById("plugins-on")?.textContent, "0");
});

test("a flip moves the counters the page shows, from the switches themselves", async () => {
  await showPluginsPanel(async () => client as never, { toString: () => "file:///extension" } as never, "zettcode");
  const dom = new JSDOM(lastPanel!.webview.html, { runScripts: "outside-only" });
  const { window } = dom;
  (window as unknown as { acquireVsCodeApi: () => unknown }).acquireVsCodeApi = () => ({ postMessage: () => undefined });
  if ((window as unknown as { CSS?: unknown }).CSS === undefined) {
    (window as unknown as { CSS: unknown }).CSS = { escape: (text: string) => text };
  }
  window.eval(window.document.querySelector("script")?.textContent ?? "");

  // `skills` is on; the page's own handler turns it off.
  window.dispatchEvent(
    new window.MessageEvent("message", {
      data: { type: "switched", name: "skills", enabled: false, error: "" },
    }),
  );

  assert.equal(window.document.getElementById("plugins-on")?.textContent, "2");
  assert.equal(window.document.getElementById("plugins-switches")?.textContent, "5");
  assert.equal(window.document.getElementById("plugins-failed")?.textContent, "1");
  assert.equal(window.document.querySelector('.plugin[data-name="skills"]')?.className, "plugin off");
});
