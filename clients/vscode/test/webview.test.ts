import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test, { after } from "node:test";

import { JSDOM } from "jsdom";

import type { Settings, Usage } from "../../typescript/src/types.js";
import type { WebviewState } from "../src/core/protocol.js";
import { applyEvent, createTurn, type Turn } from "../src/core/state.js";
import { chatHtml } from "../src/html.js";

const usage: Usage = {
  input_tokens: 1200,
  output_tokens: 340,
  cache_read_tokens: 800,
  cache_write_tokens: 0,
  reasoning_tokens: 0,
  seconds: 4.2,
  requests: 3,
  context_tokens: 1540,
};

const settings: Settings = {
  model: {
    name: "fast",
    model: "gpt-5",
    context_window: 200_000,
    multimodal: true,
    efforts: ["low", "high"],
    active: true,
    compact_percent: 80,
    web_search: false,
    web_search_name: null,
  },
  effort: "low",
  efforts: ["low", "high"],
  permission: "ask",
  permissions: ["deny", "ask", "safe", "full"],
  harness: false,
};

const state: WebviewState = {
  server: { status: "ready", message: "Ready" },
  loaded: true,
  loading: null,
  ready: true,
  health: {
    status: "ok",
    version: "0.1.8",
    workspace: "/work/project",
    ready: true,
    session: "session-1",
    models: 1,
    busy: false,
  },
  settings,
  models: [settings.model],
  currentModel: "fast",
  session: { id: "session-1", title: "Pagination work", locked: false, usage },
  sessions: [
    {
      id: "session-1",
      title: "Pagination work",
      updatedAt: "2026-10-18T11:59:30Z",
      entries: 12,
      tokens: 1540,
      current: true,
      running: false,
    },
  ],
  busy: false,
  pending: null,
  resumable: null,
  selfCompaction: { choice: null, effective: true },
  context: {
    window: 200_000,
    used: 1540,
    measured_by: "estimate",
    shares: [
      { name: "System prompt", tokens: 400, items: 1 },
      { name: "User messages", tokens: 300, items: 2 },
      { name: "Assistant messages", tokens: 840, items: 3 },
    ],
    partial: false,
    from_provider: false,
  },
  version: "0.1.8",
};

function fixtureTurns(): Turn[] {
  const turn = createTurn("Fix <this>", [], 1000, "turn-1");
  applyEvent(turn, { type: "text_delta", text: "I will **read** it.\n\nSee `src/a.ts:3`." }, 1100);
  applyEvent(turn, { type: "tool_started", call_id: "c1", name: "read_file", arguments: { path: "src/a.ts" } }, 1200);
  applyEvent(
    turn,
    { type: "tool_finished", call_id: "c1", name: "read_file", output: "the file body", ok: true, skipped: false },
    1500,
  );
  applyEvent(turn, { type: "approval_requested", call_id: "c2", command: "pytest -q", approved: null }, 1600);
  turn.usage = usage;

  const question = createTurn("", [], 2000, "turn-2");
  applyEvent(
    question,
    {
      type: "question_asked",
      call_id: "q1",
      question: "Which database?",
      options: ["sqlite", "postgres"],
      allow_multiple: false,
      answered: false,
    },
    2100,
  );
  return [turn, question];
}

interface Harness {
  window: JSDOM["window"];
  messages: Record<string, unknown>[];
  send(message: unknown): Promise<void>;
  click(selector: string): Promise<void>;
  type(value: string): Promise<void>;
  text(selector: string): string;
  all(selector: string): Element[];
  one<T extends Element = HTMLElement>(selector: string): T | null;
}

const opened: JSDOM[] = [];

// A window's timers keep the process alive; the request clock is one while a run is busy.
after(() => {
  for (const dom of opened) {
    dom.window.close();
  }
});

/** Vue applies changes on a microtask; one macrotask later every pending update has landed. */
const settle = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));

async function harness(turns: Turn[] = fixtureTurns(), initial: WebviewState = state): Promise<Harness> {
  const html = chatHtml({
    styles: ["file:///base.css", "file:///webview.css"],
    script: "file:///webview.js",
    cspSource: "https://localhost",
    nonce: "test",
  });
  const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true, url: "https://localhost/" });
  opened.push(dom);
  const { window } = dom;
  const messages: Record<string, unknown>[] = [];
  (window as unknown as { acquireVsCodeApi: () => unknown }).acquireVsCodeApi = () => ({
    postMessage: (message: Record<string, unknown>) => messages.push(JSON.parse(JSON.stringify(message))),
    getState: () => null,
    setState: () => undefined,
  });
  (window.HTMLElement.prototype as unknown as { scrollIntoView: () => void }).scrollIntoView = () => undefined;
  const source = await readFile(process.env.ZETTCODE_WEBVIEW_BUNDLE ?? "build/webview.js", "utf8");
  window.eval(source);
  window.dispatchEvent(new window.MessageEvent("message", { data: { type: "init", state: initial, turns } }));
  await settle();
  const ui: Harness = {
    window,
    messages,
    async send(message) {
      // The host's messages cross a process boundary, so each arrives as a fresh copy.
      window.dispatchEvent(new window.MessageEvent("message", { data: JSON.parse(JSON.stringify(message)) }));
      await settle();
    },
    async click(selector) {
      const node = window.document.querySelector<HTMLElement>(selector);
      assert.ok(node, `missing ${selector}`);
      node.click();
      await settle();
    },
    async type(value) {
      const input = window.document.getElementById("input") as HTMLTextAreaElement;
      input.value = value;
      input.dispatchEvent(new window.Event("input", { bubbles: true }));
      await settle();
    },
    text(selector) {
      return window.document.querySelector(selector)?.textContent ?? "";
    },
    all(selector) {
      return Array.from(window.document.querySelectorAll(selector));
    },
    one<T extends Element = HTMLElement>(selector: string) {
      return window.document.querySelector<T>(selector);
    },
  };
  return ui;
}

test("while the first load runs only the mark shows, never a guess about models", async () => {
  const ui = await harness([], { ...state, loaded: false, ready: false, settings: null, models: [], session: null });
  assert.ok(ui.one("#splash"));
  for (const selector of ["#input", "#session-button", "#welcome", "#setup", "#banner", "#model-chip"]) {
    assert.equal(ui.one(selector), null, `${selector} showed during the load`);
  }
  assert.equal(ui.text("#app").includes("No model"), false);
  await ui.send({ type: "state", state: { ...state, loaded: false, ready: false, server: { status: "starting", message: "Starting…" } } });
  assert.ok(ui.one("#splash"));
  await ui.send({ type: "state", state });
  assert.equal(ui.one("#splash"), null);
  assert.ok(ui.one("#input"));
});

test("a server that failed to start is reported instead of waited for", async () => {
  const ui = await harness([], {
    ...state,
    loaded: false,
    ready: false,
    server: { status: "error", message: "The command was not found" },
  });
  assert.equal(ui.one("#splash"), null);
  assert.ok(ui.text("#banner").includes("not running"));
});

test("the view mounts every part the host talks to", async () => {
  const ui = await harness();
  for (const selector of [
    "#session-button",
    "#session-name",
    "#new-button",
    "#history-button",
    "#transcript",
    "#turns",
    "#input",
    "#send",
    "#attach",
    "#model-chip",
    "#effort-chip",
    "#permission-chip",
    "#context-chip",
    "#input-hint",
    "#toasts",
  ]) {
    assert.ok(ui.one(selector), `missing ${selector}`);
  }
  assert.equal(ui.messages[0]?.type, "ready");
});

test("the transcript renders a turn, a connected tool rail and a file link", async () => {
  const ui = await harness();
  assert.equal(ui.text("#session-name"), "Pagination work");
  assert.equal(ui.text("#model-chip").trim(), "fast");
  assert.equal(ui.all(".turn").length, 2);
  assert.equal(ui.all(".rail").length, 2);
  assert.ok(ui.text(".user-text").includes("Fix <this>"));
  assert.ok(ui.text(".md strong").includes("read"));
  const link = ui.one('.md a.file-link[data-open="src/a.ts:3"]');
  assert.ok(link);
  link.click();
  assert.equal(ui.messages.at(-1)?.type, "open");
  assert.equal(ui.messages.at(-1)?.target, "src/a.ts:3");
});

test("a tool row opens and closes its body", async () => {
  const ui = await harness();
  assert.equal(ui.one(".tool-body"), null);
  await ui.click(".tool-head");
  assert.ok(ui.one(".tool-body"));
  assert.ok(ui.text(".tool-body").includes("the file body"));
  await ui.click(".tool-head");
  assert.equal(ui.one(".tool-body"), null);
});

test("a command shows on its row without unfolding, and opens to its output", async () => {
  const ui = await harness();
  const turn = createTurn("Run the tests", [], 9000, "turn-command");
  const command = "pytest -q tests/test_server_api.py tests/test_client_parity.py --maxfail=1 -p no:cacheprovider";
  applyEvent(turn, { type: "tool_started", call_id: "b1", name: "bash", arguments: { command } }, 9100);
  applyEvent(turn, { type: "tool_finished", call_id: "b1", name: "bash", output: "3 passed", ok: true, skipped: false }, 9600);
  await ui.send({ type: "turn", turn });

  const row = ui.one('[data-id="turn-command"] .tool');
  assert.ok(row);
  assert.equal(row.querySelector(".tool-body"), null, "a command's card stays folded until asked for");
  assert.equal(row.querySelector(".tool-verb")?.textContent, "Bash");
  const target = row.querySelector(".tool-target");
  assert.equal(target?.textContent, command, "the command is on the row, whole, so the row can cut it to fit");
  assert.equal(target?.getAttribute("title"), command, "hovering shows it all");

  await ui.click('[data-id="turn-command"] .tool-head');
  assert.ok(ui.text('[data-id="turn-command"] .tool-body').includes("3 passed"), "opening shows the output");
});

test("a running command counts its own time instead of saying running", async () => {
  const ui = await harness();
  const startedAt = Date.now() - 3_000;
  const turn = createTurn("Run it", [], startedAt - 100, "turn-clock");
  applyEvent(turn, { type: "tool_started", call_id: "b1", name: "bash", arguments: { command: "sleep 30" } }, startedAt);
  await ui.send({ type: "turn", turn });

  const row = ui.one('[data-id="turn-clock"] .tool');
  assert.ok(row);
  assert.match(row.querySelector(".tool-status")?.textContent ?? "", /^[34]s$/, "the time it has taken so far");
  assert.equal(row.querySelector(".step-dot")?.classList.contains("pulse"), false, "a dot that holds still");

  applyEvent(turn, { type: "tool_finished", call_id: "b1", name: "bash", output: "ok", ok: true, skipped: false }, startedAt + 1_500);
  await ui.send({ type: "turn", turn });
  assert.equal(ui.one('[data-id="turn-clock"] .tool-status')?.textContent, "1.5s", "and the whole time once it ends");
});

test("a shell step is named for the tool, and the approval card says Bash", async () => {
  const ui = await harness();
  const card = ui.one(".approval.pending");
  assert.ok(card);
  assert.equal(card.querySelector(".approval-head strong")?.textContent, "Bash");
  assert.equal(ui.all(".tool .tool-verb")[0]?.textContent, "Read");
});

test("an approval is answered from the card", async () => {
  const ui = await harness();
  await ui.click(".approval-actions .btn.solid");
  const approval = ui.messages.find((message) => message.type === "approve");
  assert.deepEqual(approval, { type: "approve", callId: "c2", approve: true, remember: false });
});

test("a question offers its options and a free answer", async () => {
  const ui = await harness();
  const option = ui.one(".choice");
  assert.ok(option);
  assert.equal(option.textContent?.trim(), "sqlite");
  await ui.click(".choice");
  assert.deepEqual(ui.messages.at(-1), { type: "answer", callId: "q1", answer: "sqlite" });

  const turn = createTurn("", [], 2000, "turn-2");
  applyEvent(
    turn,
    { type: "question_asked", call_id: "q2", question: "Which one?", options: [], allow_multiple: false, answered: false },
    2100,
  );
  await ui.send({ type: "turn", turn });
  const field = ui.one<HTMLInputElement>(".answer-input");
  assert.ok(field);
  field.value = "sqlite";
  field.dispatchEvent(new ui.window.Event("input", { bubbles: true }));
  await ui.click(".answer-row .btn.solid");
  assert.deepEqual(ui.messages.at(-1), { type: "answer", callId: "q2", answer: "sqlite" });
});

test("a prompt is posted and the composer is cleared", async () => {
  const ui = await harness();
  await ui.type("make the tests pass");
  await ui.click("#send");
  assert.deepEqual(ui.messages.at(-1), { type: "prompt", text: "make the tests pass", images: [] });
  assert.equal((ui.one("#input") as HTMLTextAreaElement).value, "");
});

test("the command list can be scrolled by its scrollbar without the box losing focus", async () => {
  const ui = await harness();
  await ui.type("/");
  const menu = ui.one("#menu");
  assert.ok(menu);
  assert.ok(ui.all("#menu .menu-item").length > 10);
  // A press on the list (its scrollbar included) must not move focus off the input, or the list would close.
  const press = new ui.window.MouseEvent("mousedown", { bubbles: true, cancelable: true });
  menu.dispatchEvent(press);
  assert.equal(press.defaultPrevented, true);
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.ok(ui.one("#menu"));
  const down = new ui.window.KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true, cancelable: true });
  (ui.one("#input") as HTMLElement).dispatchEvent(down);
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.ok(ui.one("#menu .menu-item.active")?.textContent?.includes("/resume"));
});

test("a slash command opens the model menu over the box", async () => {
  const ui = await harness();
  await ui.type("/model");
  assert.ok(ui.one("#menu"));
  await ui.click(".menu-item");
  assert.ok(ui.one(".box #model-menu"));
  assert.equal(ui.one("#modal"), null);
  assert.equal(ui.all("#model-menu .option-row").length, 1);
  assert.ok(ui.text("#model-menu").includes("fast"));
  assert.equal((ui.one("#input") as HTMLTextAreaElement).value, "");
});

test("model, effort and permission open as menus on their own controls, not as dialogs", async () => {
  const ui = await harness();
  await ui.click("#permission-chip");
  assert.ok(ui.one(".box #permission-menu"));
  assert.equal(ui.all("#permission-menu .option").length, 4);
  assert.equal(ui.one("#modal"), null);
  await ui.click('[data-permission="safe"]');
  assert.deepEqual(ui.messages.at(-1), { type: "set-permission", permission: "safe" });
  assert.equal(ui.one("#permission-menu"), null);

  await ui.click("#effort-chip");
  assert.ok(ui.one("#effort-menu"));
  await ui.click('[data-effort="high"]');
  assert.deepEqual(ui.messages.at(-1), { type: "set-effort", effort: "high" });

  await ui.click("#model-chip");
  assert.ok(ui.one("#model-menu"));
  await ui.click("#effort-chip");
  assert.equal(ui.one("#model-menu"), null);
  assert.ok(ui.one("#effort-menu"));
  await ui.click("#effort-chip");
  assert.equal(ui.one("#effort-menu"), null);
});

test("a click outside, or Escape, puts a menu away", async () => {
  const ui = await harness();
  await ui.click("#model-chip");
  assert.ok(ui.one("#model-menu"));
  await ui.click("#turns");
  assert.equal(ui.one("#model-menu"), null);
  await ui.click("#permission-chip");
  assert.ok(ui.one("#permission-menu"));
  ui.window.document.dispatchEvent(new ui.window.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(ui.one("#permission-menu"), null);
});

test("opening a conversation says so over the one on show, in the words of every other wait, and clears when it is open", async () => {
  const ui = await harness();
  assert.equal(ui.one("#opening"), null, "nothing is loading at rest");

  await ui.send({ type: "state", state: { ...state, loading: "Opening the conversation" } });

  const veil = ui.one("#opening");
  assert.ok(veil, "the view says something is going on, so it does not look stuck");
  assert.equal(veil.getAttribute("role"), "status");
  assert.ok(veil.querySelector(".shimmer"), "the words shimmer, like every other wait; nothing spins");
  assert.equal(veil.querySelector(".spinner"), null);
  assert.ok(veil.textContent?.includes("Opening the conversation"));
  assert.ok(ui.one("#transcript"), "the conversation is still there under it, scroll and all");

  await ui.send({ type: "state", state: { ...state, loading: null } });
  assert.equal(ui.one("#opening"), null);
});

test("the tick in the model menu is on the model the chip names, even when the list still marks another", async () => {
  // A session that is opened puts back the model it last used; a list read before that still says the first is active.
  const stale = [settings.model, { ...settings.model, name: "deep", model: "deepseek-v4", active: false }];
  const ui = await harness(fixtureTurns(), {
    ...state,
    models: stale,
    currentModel: "deep",
    settings: { ...settings, model: { ...stale[1]!, active: true } },
  });
  assert.equal(ui.text("#model-chip").trim(), "deep");
  await ui.click("#model-chip");

  const rows = ui.all("#model-menu .option-row");
  assert.equal(rows[0]?.querySelector(".tick"), null, "no tick on the first model");
  assert.ok(rows[1]?.querySelector(".tick"), "the tick is on the model in use");
  assert.ok(rows[1]?.querySelector(".option.current"));

  // Choosing the one in use sends nothing, and choosing the other does.
  const before = ui.messages.length;
  await ui.click("#model-menu .option-row:nth-child(2) .option");
  assert.equal(ui.messages.length, before);
});

test("removing a model asks inside its own row, with no dialog", async () => {
  const other = { ...settings.model, name: "deep", model: "deepseek-v4", active: false };
  const ui = await harness(fixtureTurns(), { ...state, models: [settings.model, other] });
  await ui.click("#model-chip");
  const rows = ui.all("#model-menu .option-row");
  (rows[1]?.querySelector(".row-remove") as HTMLElement).click();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(ui.messages.some((message) => message.type === "remove-model"), false);
  const confirm = ui.one("#model-menu .confirm");
  assert.ok(confirm);
  assert.ok(confirm.textContent?.includes("Remove deep?"));
  assert.equal(ui.all("#model-menu .confirm").length, 1);

  await ui.click("#model-menu .confirm .btn:not(.danger-solid)");
  assert.equal(ui.one("#model-menu .confirm"), null);
  assert.equal(ui.messages.some((message) => message.type === "remove-model"), false);

  (ui.all("#model-menu .row-remove")[1] as HTMLElement).click();
  await new Promise((resolve) => setTimeout(resolve, 0));
  await ui.click('#model-menu [data-confirm="remove"]');
  assert.deepEqual(ui.messages.at(-1), { type: "remove-model", name: "deep" });
  assert.equal(ui.one("#model-menu .confirm"), null);
});

test("a model is chosen from its menu", async () => {
  const other = { ...settings.model, name: "deep", model: "deepseek-v4", active: false };
  const ui = await harness(fixtureTurns(), { ...state, models: [settings.model, other] });
  await ui.click("#model-chip");
  const rows = ui.all("#model-menu .option-row .option");
  assert.equal(rows.length, 2);
  (rows[1] as HTMLElement).click();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(ui.messages.at(-1), { type: "set-model", name: "deep" });
  assert.equal(ui.one("#model-menu"), null);
});

test("the drawer lists recent sessions and opens one", async () => {
  const ui = await harness();
  await ui.click("#session-button");
  assert.ok(ui.one("#drawer"));
  assert.equal(ui.messages.at(-1)?.type, "refresh-sessions");
  assert.equal(ui.all(".session-row").length, 1);
  await ui.click(".session-row");
  assert.deepEqual(ui.messages.at(-1), { type: "open-session", id: "session-1" });
  assert.equal(ui.one("#drawer"), null);
});

test("the context composition opens from the composer and draws a donut", async () => {
  const ui = await harness();
  assert.ok(ui.one(".composer #context-chip"));
  await ui.click("#context-chip");
  assert.ok(ui.one(".composer #context-popover"));
  assert.equal(ui.one("#modal"), null);
  const card = ui.text("#context-popover");
  assert.ok(card.includes("Context composition"));
  assert.ok(card.includes("1.5k"));
  assert.ok(card.includes("200k"));
  assert.equal(ui.all("#context-popover .donut-slice").length, 3);
  assert.equal(ui.all("#context-popover .legend-row").length, 3);
  assert.equal(ui.messages.at(-1)?.type, "context");

  const row = ui.one('#context-popover [data-share-index="0"]');
  const slice = ui.one('#context-popover .donut-slice[data-slice="0"]');
  assert.ok(row && slice);
  row.dispatchEvent(new ui.window.Event("pointerover", { bubbles: true }));
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.ok(slice.classList.contains("active"));

  await ui.click("#context-chip");
  assert.equal(ui.one("#context-popover"), null);
});

test("the compaction point is a rail: keys move it by 5%, Enter applies it, Esc undoes it", async () => {
  const ui = await harness();
  await ui.click("#context-chip");
  const rail = ui.one("#compaction .rail-slider");
  assert.ok(rail);
  assert.equal(rail.getAttribute("aria-valuenow"), "80");
  assert.ok(ui.text("#compaction").includes("80%"));
  assert.ok(ui.text("#compaction").includes("160k"));
  assert.equal(ui.one<HTMLButtonElement>("#compaction .btn")?.disabled, true);

  const press = async (key: string) => {
    rail.dispatchEvent(new ui.window.KeyboardEvent("keydown", { key, bubbles: true }));
    await new Promise((resolve) => setTimeout(resolve, 0));
  };
  await press("ArrowLeft");
  await press("ArrowLeft");
  assert.equal(rail.getAttribute("aria-valuenow"), "70");
  assert.ok(ui.text("#compaction").includes("140k"));
  assert.equal(ui.messages.some((message) => message.type === "set-compact"), false);

  await press("Escape");
  assert.equal(rail.getAttribute("aria-valuenow"), "80");
  assert.ok(ui.one("#context-popover"));

  await press("ArrowLeft");
  await press("Enter");
  assert.deepEqual(ui.messages.at(-1), { type: "set-compact", percent: 75 });

  for (let step = 0; step < 30; step += 1) await press("ArrowRight");
  assert.equal(rail.getAttribute("aria-valuenow"), "100");
  for (let step = 0; step < 30; step += 1) await press("ArrowLeft");
  assert.equal(rail.getAttribute("aria-valuenow"), "5");
});

test("the Apply button sends the new point, and a run in progress locks the rail", async () => {
  const ui = await harness();
  await ui.click("#context-chip");
  const rail = ui.one("#compaction .rail-slider");
  assert.ok(rail);
  rail.dispatchEvent(new ui.window.KeyboardEvent("keydown", { key: "End", bubbles: true }));
  await new Promise((resolve) => setTimeout(resolve, 0));
  await ui.click("#compaction .btn");
  assert.deepEqual(ui.messages.at(-1), { type: "set-compact", percent: 100 });

  await ui.send({ type: "state", state: { ...state, busy: true } });
  assert.ok(ui.one("#compaction .rail-slider.disabled"));
  assert.equal(ui.one<HTMLButtonElement>("#compaction .btn")?.disabled, true);
  assert.ok(ui.text("#compaction").includes("when the run ends"));
});

test("the context percentage keeps one decimal, in the chip and in the card", async () => {
  const ui = await harness();
  const chip = () => ui.text("#context-chip > span").trim();
  assert.equal(chip(), "0.8%");
  await ui.click("#context-chip");
  assert.ok(ui.text("#context-popover .pop-ring-center").includes("0.8%"));
  assert.ok(ui.text("#context-popover .pill").includes("0.8% used"));
  const more = { ...state.context!, used: 62_000 };
  await ui.send({ type: "state", state: { ...state, context: more } });
  assert.equal(chip(), "31.0%");
  const tiny = { ...state.context!, used: 12 };
  await ui.send({ type: "state", state: { ...state, context: tiny } });
  assert.equal(chip(), "<0.1%");
  const full = { ...state.context!, used: 190_000 };
  await ui.send({ type: "state", state: { ...state, context: full } });
  assert.equal(chip(), "95.0%");
  assert.ok(ui.one("#context-chip.full"));
});

test("tool schemas and environment notes are pending, never lumped into an unattributed row", async () => {
  const partial = { ...state.context!, partial: true, from_provider: true, used: 102_000 };
  const ui = await harness(fixtureTurns(), { ...state, context: partial });
  await ui.click("#context-chip");
  const names = ui.all("#context-popover .legend-name").map((node) => node.textContent);
  assert.deepEqual(names, ["System prompt", "Environment notes", "Tool schemas", "User messages", "Assistant messages"]);
  assert.equal(names.includes("Unattributed"), false);
  const pending = ui.all("#context-popover .legend-row.pending");
  assert.equal(pending.length, 2);
  assert.ok(pending.every((row) => row.textContent?.includes("pending")));
  assert.equal(ui.all("#context-popover .donut-slice").length, 3);
  // The shares still add up to the whole ring.
  const total = ui
    .all("#context-popover .legend-pct:not(.pending)")
    .reduce((sum, node) => sum + Number.parseFloat(node.textContent ?? "0"), 0);
  assert.ok(Math.abs(total - 100) < 0.3, `shares add up to ${total}`);
});

test("once a request has gone out every source has a figure and nothing is unattributed", async () => {
  const full = {
    ...state.context!,
    partial: false,
    from_provider: true,
    used: 2000,
    shares: [
      { name: "System prompt", tokens: 100, items: 1 },
      { name: "Environment notes", tokens: 100, items: 1 },
      { name: "Tool schemas", tokens: 200, items: 14 },
      { name: "User messages", tokens: 100, items: 2 },
      { name: "Tool output", tokens: 500, items: 4 },
    ],
  };
  const ui = await harness(fixtureTurns(), { ...state, context: full });
  await ui.click("#context-chip");
  assert.equal(ui.all("#context-popover .legend-row.pending").length, 0);
  assert.equal(ui.all("#context-popover .legend-row").length, 5);
  assert.ok(ui.text("#context-popover").includes("Tool schemas"));
  assert.equal(ui.text("#context-popover").includes("Unattributed"), false);
});

test("the session's tokens, cache and speed sit under the input", async () => {
  const ui = await harness();
  const stats = ui.one(".composer #session-stats");
  assert.ok(stats);
  const words = stats.textContent ?? "";
  assert.ok(words.includes("↑ 1.2k"));
  assert.ok(words.includes("↓ 340"));
  assert.ok(words.includes("66.7% cached"));
  assert.ok(words.includes("81.0 tok/s"));
  assert.ok(words.includes("3 calls"));
  const empty = await harness(fixtureTurns(), { ...state, session: { ...state.session!, usage: { ...usage, requests: 0 } } });
  assert.equal(empty.one("#session-stats"), null);
});

test("the drawer opens context and keeps the other panels", async () => {
  const ui = await harness();
  await ui.click("#session-button");
  await ui.click('[data-action="context"]');
  assert.ok(ui.one("#context-popover"));
  assert.equal(ui.one("#drawer"), null);
  await ui.click("#session-button");
  await ui.click('[data-action="plugins"]');
  assert.equal(ui.messages.at(-1)?.type, "plugins");
});

test("the header shows the session, renames it in place, and /rename takes the name", async () => {
  const ui = await harness();
  assert.ok(ui.text("#session-sub").includes("3 requests"));
  await ui.click("#rename-button");
  const input = ui.one<HTMLInputElement>(".session-rename");
  assert.ok(input);
  input.value = "Search work";
  input.dispatchEvent(new ui.window.Event("input", { bubbles: true }));
  input.dispatchEvent(new ui.window.KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(ui.messages.at(-1), { type: "rename-session", title: "Search work" });
  assert.equal(ui.one(".session-rename"), null);
  await ui.type("/rename Another name");
  await ui.click("#send");
  assert.deepEqual(ui.messages.at(-1), { type: "rename-session", title: "Another name" });
});

test("an interrupted request offers Continue beside the input, and /continue says so when there is none", async () => {
  const ui = await harness();
  await ui.type("/continue");
  await ui.click("#send");
  assert.notEqual(ui.messages.at(-1)?.type, "resume");
  assert.ok(ui.text("#toasts").includes("no interrupted request"));
  assert.equal(ui.one("#resume-bar"), null);

  await ui.send({
    type: "state",
    state: { ...state, resumable: { resumable: true, kind: "interrupted", description: "cut short" } },
  });
  assert.ok(ui.one(".composer #resume-bar"));
  assert.equal(ui.one("#banner"), null);
  await ui.click("#resume-bar .btn");
  assert.equal(ui.messages.at(-1)?.type, "resume");
  await ui.type("/continue");
  await ui.click("#send");
  assert.equal(ui.messages.at(-1)?.type, "resume");
});

test("a finished request ends in a receipt with its state, time and tokens", async () => {
  const ui = await harness();
  const turn = createTurn("done", [], 5000, "turn-done");
  applyEvent(turn, { type: "text_delta", text: "ok" }, 5100);
  turn.status = "done";
  turn.finishedAt = 9000;
  turn.usage = usage;
  await ui.send({ type: "turn", turn });
  const receipt = ui.one('[data-id="turn-done"] .receipt');
  assert.ok(receipt);
  const state = receipt.querySelector(".receipt-state");
  assert.ok(state);
  assert.equal(state.textContent?.trim(), "Processed");
  assert.equal(receipt.textContent?.includes("Done"), false, "it no longer says Done");
  assert.ok(receipt.textContent?.includes("66.7% cached"));
  assert.ok(receipt.textContent?.includes("4s"));
  assert.ok(receipt.textContent?.includes("↑ 1.2k"));
});

test("thoughts, tools and the narration between them share one unbroken rail", async () => {
  const ui = await harness();
  const turn = createTurn("rail", [], 7000, "turn-rail");
  applyEvent(turn, { type: "reasoning_delta", text: "first thought" }, 7010);
  applyEvent(turn, { type: "tool_started", call_id: "r1", name: "read_file", arguments: { path: "a.ts" } }, 7020);
  applyEvent(turn, { type: "tool_finished", call_id: "r1", name: "read_file", output: "x", ok: true, skipped: false }, 7030);
  applyEvent(turn, { type: "reasoning_delta", text: "second thought" }, 7040);
  applyEvent(turn, { type: "text_delta", text: "Narration between steps." }, 7050);
  applyEvent(turn, { type: "tool_started", call_id: "r2", name: "bash", arguments: { command: "ls" } }, 7060);
  applyEvent(turn, { type: "tool_finished", call_id: "r2", name: "bash", output: "ok", ok: true, skipped: false }, 7070);
  applyEvent(turn, { type: "text_delta", text: "The final answer." }, 7080);
  await ui.send({ type: "turn", turn });
  const node = ui.one('[data-id="turn-rail"]');
  assert.ok(node);
  const rails = node.querySelectorAll(".rail");
  assert.equal(rails.length, 1);
  const rail = rails[0];
  assert.equal(rail?.querySelectorAll(".reasoning").length, 2);
  assert.equal(rail?.querySelectorAll(".tool").length, 2);
  assert.ok(rail?.textContent?.includes("Narration between steps."));
  assert.equal(rail?.textContent?.includes("The final answer."), false);
  assert.ok(node.querySelector(".assistant")?.textContent?.includes("The final answer."));
  assert.equal(node.querySelectorAll(".tool .tool-verb")[0]?.textContent, "Read");
  assert.equal(node.querySelectorAll(".tool .tool-verb")[1]?.textContent, "Bash");
});

test("a request can be folded, and every request folds from the header", async () => {
  const ui = await harness();
  const turn = ui.one('[data-id="turn-1"]');
  assert.ok(turn?.querySelector(".assistant"));
  await ui.click('[data-id="turn-1"] .fold');
  assert.equal(ui.one('[data-id="turn-1"] .assistant'), null);
  assert.ok(ui.one('[data-id="turn-1"] .folded-line'));
  await ui.click("#collapse-button");
  assert.equal(ui.all(".turn .assistant").length, 0);
  await ui.click("#collapse-button");
  assert.equal(ui.all(".turn .assistant").length, 2);
});

test("the live status sits at the end of the conversation while a request runs", async () => {
  const ui = await harness();
  assert.equal(ui.one("#live-status"), null);
  await ui.send({ type: "state", state: { ...state, busy: true } });
  const live = ui.one("#live-status");
  assert.ok(live);
  assert.ok(ui.one("#transcript #live-status"));
  assert.equal(ui.one(".composer #live-status"), null);
  assert.ok(live.textContent?.includes("Processing"));
  assert.equal(live.textContent?.includes("Thinking"), false);
  assert.ok(live.textContent?.includes("esc to stop"));
  await ui.send({ type: "state", state });
  assert.equal(ui.one("#live-status"), null);
});

test("only the thought step says Thinking; the status at the end says Processing", async () => {
  const turn = createTurn("who are you", [], 9000, "turn-live");
  applyEvent(turn, { type: "reasoning_delta", text: "let me think" }, 9010);
  const ui = await harness([turn], { ...state, busy: true });
  const words = ui.all("#app *").filter((node) => node.children.length === 0 && /Thinking/.test(node.textContent ?? ""));
  assert.equal(words.length, 1);
  assert.ok(words[0]?.closest(".rail"));
  assert.ok(ui.text("#transcript #live-status").includes("Processing"));
  await ui.send({
    type: "turn",
    turn: (() => {
      applyEvent(turn, { type: "tool_started", call_id: "p1", name: "bash", arguments: { command: "ls" } }, 9020);
      return turn;
    })(),
  });
  assert.ok(ui.text("#live-status").includes("Processing"));
  assert.equal(ui.one("#live-status .live-detail"), null, "a step's name belongs on its own row, not here");
  assert.ok(ui.text("#live-status .live-time").match(/\d/), "the time it has been going is here");
});

test("a message sent during a run waits as a follow-up, and can be steered in", async () => {
  const ui = await harness();
  await ui.send({ type: "state", state: { ...state, busy: true } });
  assert.ok(ui.one("#stop"));
  assert.equal((ui.one("#input") as HTMLTextAreaElement).placeholder, "Queue a follow-up…");
  await ui.type("also the docs");
  await ui.click("#send");
  assert.equal(ui.messages.some((message) => message.type === "steer"), false);
  assert.equal(ui.all("#queue .queue-item").length, 1);
  assert.ok(ui.text("#queue").includes("also the docs"));
  await ui.click(".queue-steer");
  assert.deepEqual(ui.messages.at(-1), { type: "steer", text: "also the docs" });
  assert.equal(ui.one("#queue"), null);
});

test("a follow-up goes out by itself when the run ends well, and waits when it was stopped", async () => {
  const done = createTurn("first", [], 100, "turn-a");
  done.status = "done";
  done.finishedAt = 200;
  const ui = await harness([done]);
  await ui.send({ type: "state", state: { ...state, busy: true } });
  await ui.type("then this");
  await ui.click("#send");
  await ui.send({ type: "state", state });
  assert.deepEqual(ui.messages.at(-1), { type: "prompt", text: "then this", images: [] });
  assert.equal(ui.one("#queue"), null);

  const stopped = createTurn("second", [], 300, "turn-b");
  stopped.status = "cancelled";
  stopped.finishedAt = 400;
  const held = await harness([stopped]);
  await held.send({ type: "state", state: { ...state, busy: true } });
  await held.type("later");
  await held.click("#send");
  await held.send({ type: "state", state });
  assert.equal(held.messages.some((message) => message.type === "prompt"), false);
  assert.ok(held.text("#queue").includes("Waiting to send"));
});

test("Ctrl+Enter steers a message straight into the run", async () => {
  const ui = await harness();
  await ui.send({ type: "state", state: { ...state, busy: true } });
  await ui.type("use pytest");
  const input = ui.one("#input");
  assert.ok(input);
  input.dispatchEvent(new ui.window.KeyboardEvent("keydown", { key: "Enter", ctrlKey: true, bubbles: true }));
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(ui.messages.at(-1), { type: "steer", text: "use pytest" });
});

test("a notice becomes a toast, and the same notice twice stays one toast", async () => {
  const ui = await harness();
  await ui.send({ type: "notice", level: "info", text: "Copied." });
  assert.equal(ui.text(".toast").trim(), "Copied.");
  await ui.send({ type: "notice", level: "warn", text: "Cannot find “openrouter.ai/api/v1” in this workspace." });
  await ui.send({ type: "notice", level: "warn", text: "Cannot find “openrouter.ai/api/v1” in this workspace." });
  await ui.send({ type: "notice", level: "warn", text: "Cannot find “openrouter.ai/api/v1” in this workspace." });
  assert.equal(ui.all(".toast").length, 2);
});

test("a new session button posts a new session", async () => {
  const ui = await harness();
  await ui.click("#new-button");
  assert.deepEqual(ui.messages.at(-1), { type: "new-session" });
});

test("a delta updates only the text that arrived", async () => {
  const ui = await harness();
  const turn = createTurn("go", [], 1000, "turn-delta");
  applyEvent(turn, { type: "text_delta", text: "Hello" }, 1100);
  await ui.send({ type: "turn", turn });
  const before = ui.one('[data-id="turn-delta"] .md');
  assert.ok(before);
  await ui.send({ type: "turn-delta", turnId: "turn-delta", text: " world" });
  const after = ui.one('[data-id="turn-delta"] .md');
  assert.equal(before, after);
  assert.equal(after?.textContent, "Hello world");
  assert.equal(ui.all('[data-id="turn-delta"] .md').length, 1);
});

test("a delta appends a new block after a tool and keeps an open row open", async () => {
  const ui = await harness();
  const turn = createTurn("go", [], 1000, "turn-mixed");
  applyEvent(turn, { type: "text_delta", text: "Before" }, 1100);
  applyEvent(turn, { type: "tool_started", call_id: "m1", name: "read_file", arguments: { path: "src/a.ts" } }, 1200);
  applyEvent(turn, { type: "tool_finished", call_id: "m1", name: "read_file", output: "body", ok: true, skipped: false }, 1300);
  await ui.send({ type: "turn", turn });
  await ui.click('[data-id="turn-mixed"] .tool-head');
  assert.ok(ui.one('[data-id="turn-mixed"] .tool-body'));
  await ui.send({ type: "turn-delta", turnId: "turn-mixed", text: "After" });
  const blocks = ui.all('[data-id="turn-mixed"] .md');
  assert.equal(blocks.length, 2);
  assert.equal(blocks[1]?.textContent, "After");
  assert.ok(ui.one('[data-id="turn-mixed"] .tool-body'));
});

test("reasoning reads as Thinking only while it is the live step", async () => {
  const ui = await harness();
  const turn = createTurn("go", [], 1000, "turn-thought");
  applyEvent(turn, { type: "reasoning_delta", text: "a plan" }, 1100);
  await ui.send({ type: "turn", turn });
  assert.equal(ui.text('[data-id="turn-thought"] [data-reasoning-label]'), "Thinking");
  assert.ok(ui.one('[data-id="turn-thought"] [data-reasoning-label] .shimmer'), "it shimmers");
  applyEvent(turn, { type: "tool_started", call_id: "c1", name: "read_file", arguments: { path: "src/a.ts" } }, 1200);
  await ui.send({ type: "turn", turn });
  assert.equal(ui.text('[data-id="turn-thought"] [data-reasoning-label]'), "Thought");
  applyEvent(turn, { type: "text_delta", text: "done" }, 1300);
  await ui.send({ type: "turn", turn });
  assert.equal(ui.text('[data-id="turn-thought"] [data-reasoning-label]'), "Thought");
});

test("a step that is thinking carries no class another part of the view lays out", async () => {
  const ui = await harness();
  const turn = createTurn("go", [], 1000, "turn-classes");
  applyEvent(turn, { type: "reasoning_delta", text: "a plan" }, 1100);
  await ui.send({ type: "turn", turn });
  const step = ui.one('[data-id="turn-classes"] .reasoning');
  assert.ok(step?.classList.contains("thinking"), "the live step is marked thinking");
  // `.live` was the status row's class as well, and its `display: flex` laid the thought out beside its label.
  assert.equal(step?.classList.contains("live"), false);
  const status = await readFile("src/webview/components/LiveStatus.vue", "utf8");
  assert.ok(status.includes('class="live-row"'), "the status row keeps a class of its own");
  assert.equal(/^\.live\s*\{/m.test(status), false, "and nothing lays out a bare `.live`");
});

test("what a request changed is listed, opens in the editor, and expands in place", async () => {
  const ui = await harness();
  const turn = createTurn("edit it", [], 8000, "turn-edit");
  applyEvent(turn, { type: "tool_started", call_id: "e1", name: "edit", arguments: { path: "src/a.ts", edits: [{ old_text: "a", new_text: "b" }] } }, 8010);
  applyEvent(turn, { type: "tool_finished", call_id: "e1", name: "edit", output: "ok", ok: true, skipped: false }, 8020);
  turn.status = "done";
  turn.finishedAt = 8100;
  await ui.send({ type: "turn", turn });
  await ui.send({ type: "changes", turnId: "turn-edit", files: [{ path: "src/a.ts", status: "modified", added: 2, removed: 1 }] });
  const card = ui.one('[data-id="turn-edit"] .changes');
  assert.ok(card);
  assert.ok(card.textContent?.includes("1 file changed"));
  assert.ok(card.textContent?.includes("+2"));
  assert.ok(card.textContent?.includes("−1"));
  assert.ok(ui.one('[data-id="turn-edit"] .tool-diff'));

  await ui.click('[data-id="turn-edit"] .change-open');
  assert.deepEqual(ui.messages.at(-1), { type: "open-diff", turnId: "turn-edit", path: "src/a.ts" });

  await ui.click('[data-id="turn-edit"] .change-main');
  assert.deepEqual(ui.messages.at(-1), { type: "view-diff", turnId: "turn-edit", path: "src/a.ts" });
  await ui.send({
    type: "diff-rows",
    turnId: "turn-edit",
    path: "src/a.ts",
    truncated: false,
    rows: [
      { kind: "del", text: "const a = 1;", oldLine: 3 },
      { kind: "add", text: "const a = 2;", newLine: 3 },
    ],
  });
  assert.equal(ui.all('[data-id="turn-edit"] .drow.add').length, 1);
  assert.equal(ui.all('[data-id="turn-edit"] .drow.del').length, 1);
});

test("a server with no model offers the setup form", async () => {
  const cold: WebviewState = {
    ...state,
    ready: false,
    health: state.health === null ? null : { ...state.health, ready: false, session: null, models: 0 },
    settings: null,
    models: [],
    currentModel: null,
    session: null,
    sessions: [],
    context: null,
    selfCompaction: null,
  };
  const ui = await harness([], cold);
  assert.ok(ui.one("#welcome"));
  const setup = ui.one("#setup");
  assert.ok(setup?.textContent?.includes("No model is configured"));
  await ui.click("#setup .btn");
  assert.ok(ui.one(".box #add-model-panel"));
  assert.equal(ui.one("#modal"), null);
  const model = ui.one<HTMLInputElement>("#m-model");
  const token = ui.one<HTMLInputElement>("#m-token");
  assert.ok(model && token);
  model.value = "gpt-5";
  model.dispatchEvent(new ui.window.Event("input", { bubbles: true }));
  token.value = "sk-test";
  token.dispatchEvent(new ui.window.Event("input", { bubbles: true }));
  await ui.click('[data-action="submit-model"]');
  assert.deepEqual(ui.messages.at(-1), {
    type: "add-model",
    model: { model: "gpt-5", token: "sk-test", chat: true },
  });
});

test("the add-model form sends the API it was given as one flag, a temperature, and no key when there is none", async () => {
  const cold: WebviewState = {
    ...state,
    ready: false,
    health: state.health === null ? null : { ...state.health, ready: false, session: null, models: 0 },
    settings: null,
    models: [],
    currentModel: null,
    session: null,
    sessions: [],
    context: null,
    selfCompaction: null,
  };
  const ui = await harness([], cold);
  await ui.click("#setup .btn");
  const fill = (selector: string, value: string): void => {
    const field = ui.one<HTMLInputElement | HTMLSelectElement>(selector);
    assert.ok(field, selector);
    field.value = value;
    field.dispatchEvent(new ui.window.Event(selector === "#m-api" ? "change" : "input", { bubbles: true }));
  };

  fill("#m-model", "llama3");
  fill("#m-url", "http://localhost:11434/v1");
  fill("#m-temperature", "0");
  await ui.click('[data-action="submit-model"]');
  assert.deepEqual(ui.messages.at(-1), {
    type: "add-model",
    model: { model: "llama3", base_url: "http://localhost:11434/v1", temperature: 0, chat: true },
  }, "no token key, and a temperature of zero is sent");

  fill("#m-api", "anthropic");
  fill("#m-temperature", "0.4");
  await ui.click('[data-action="submit-model"]');
  assert.deepEqual(ui.messages.at(-1), {
    type: "add-model",
    model: { model: "llama3", base_url: "http://localhost:11434/v1", temperature: 0.4, anthropic: true },
  }, "one protocol flag, and chat is not sent beside it");

  fill("#m-api", "responses");
  fill("#m-temperature", "");
  await ui.click('[data-action="submit-model"]');
  const sent = ui.messages.at(-1) as { model: Record<string, unknown> };
  assert.equal(sent.model.responses_api, true);
  assert.ok(!("temperature" in sent.model) && !("chat" in sent.model), "an empty temperature sends none");
});

const coldState = (): WebviewState => ({
  ...state,
  ready: false,
  health: state.health === null ? null : { ...state.health, ready: false, session: null, models: 0 },
  settings: null,
  models: [],
  currentModel: null,
  session: null,
  sessions: [],
  context: null,
  selfCompaction: null,
});

test("the add-model form offers web search, shows the default tool name, and sends the flag and a name only when typed", async () => {
  const ui = await harness([], coldState());
  await ui.click("#setup .btn");
  const fill = (selector: string, value: string): void => {
    const field = ui.one<HTMLInputElement | HTMLSelectElement>(selector);
    assert.ok(field, selector);
    field.value = value;
    field.dispatchEvent(new ui.window.Event(selector === "#m-api" ? "change" : "input", { bubbles: true }));
  };
  assert.equal(ui.one("#m-search-name"), null, "the tool name is asked only once search is on");

  fill("#m-model", "claude");
  fill("#m-api", "anthropic");
  await ui.click("#m-search");
  const name = ui.one<HTMLInputElement>("#m-search-name");
  assert.equal(name?.placeholder, "web_search_20260318", "the default for the API is the placeholder");
  await ui.click('[data-action="submit-model"]');
  assert.deepEqual(ui.messages.at(-1), { type: "add-model", model: { model: "claude", web_search: true, anthropic: true } });

  fill("#m-search-name", "web_search_20250305");
  await ui.click('[data-action="submit-model"]');
  assert.deepEqual(ui.messages.at(-1), {
    type: "add-model",
    model: { model: "claude", web_search: true, web_search_name: "web_search_20250305", anthropic: true },
  });

  await ui.click("#m-search");
  await ui.click('[data-action="submit-model"]');
  assert.deepEqual(ui.messages.at(-1), { type: "add-model", model: { model: "claude", anthropic: true } }, "off sends neither key");
});

test("the form refuses web search on DeepSeek's chat endpoint before anything is sent, and allows it over Anthropic", async () => {
  const ui = await harness([], coldState());
  await ui.click("#setup .btn");
  const fill = (selector: string, value: string): void => {
    const field = ui.one<HTMLInputElement | HTMLSelectElement>(selector);
    assert.ok(field, selector);
    field.value = value;
    field.dispatchEvent(new ui.window.Event(selector === "#m-api" ? "change" : "input", { bubbles: true }));
  };
  fill("#m-model", "deepseek-chat");
  await ui.click("#m-search");
  assert.ok(ui.one("#m-search-warning")?.textContent?.includes("Anthropic-compatible"), "the reason shows as it is typed");

  const before = ui.messages.length;
  await ui.click('[data-action="submit-model"]');
  assert.equal(ui.messages.length, before, "nothing was sent");
  assert.ok(ui.one(".toast")?.textContent?.includes("Anthropic"));

  fill("#m-api", "anthropic");
  await settle();
  assert.equal(ui.one("#m-search-warning"), null);
  assert.equal(ui.one<HTMLInputElement>("#m-search-name")?.placeholder, "web_search_20250305", "DeepSeek's own dated type");
  await ui.click('[data-action="submit-model"]');
  assert.deepEqual(ui.messages.at(-1), {
    type: "add-model",
    model: { model: "deepseek-chat", web_search: true, anthropic: true },
  });
});

test("a temperature out of range is refused in the form and nothing is sent", async () => {
  const cold: WebviewState = {
    ...state,
    ready: false,
    health: state.health === null ? null : { ...state.health, ready: false, session: null, models: 0 },
    settings: null,
    models: [],
    currentModel: null,
    session: null,
    sessions: [],
    context: null,
    selfCompaction: null,
  };
  const ui = await harness([], cold);
  await ui.click("#setup .btn");
  const model = ui.one<HTMLInputElement>("#m-model");
  const temperature = ui.one<HTMLInputElement>("#m-temperature");
  assert.ok(model && temperature);
  model.value = "m";
  model.dispatchEvent(new ui.window.Event("input", { bubbles: true }));
  temperature.value = "3";
  temperature.dispatchEvent(new ui.window.Event("input", { bubbles: true }));
  const before = ui.messages.length;
  await ui.click('[data-action="submit-model"]');

  assert.equal(ui.messages.length, before, "nothing was sent");
  assert.ok(ui.one(".toast")?.textContent?.includes("temperature"));
});


test("a model's row opens its own settings and sends the whole entry back", async () => {
  const ui = await harness();
  await ui.click("#model-chip");
  ui.one<HTMLElement>("#model-menu .row-edit")?.click();
  await settle();

  const id = ui.one<HTMLInputElement>("#m-model");
  assert.ok(id && id.value === "gpt-5", "the form is filled in from the entry");
  assert.equal(ui.one<HTMLInputElement>("#m-context")?.value, "200000");
  assert.equal(ui.one<HTMLInputElement>("#m-search")?.checked, false);

  const search = ui.one<HTMLInputElement>("#m-search");
  assert.ok(search);
  search.checked = true;
  search.dispatchEvent(new ui.window.Event("change", { bubbles: true }));
  ui.one<HTMLFormElement>(".form")?.dispatchEvent(new ui.window.Event("submit", { bubbles: true, cancelable: true }));
  await settle();

  const sent = ui.messages.at(-1) as { type: string; name: string; changes: Record<string, unknown> };
  assert.equal(sent.type, "update-model");
  assert.equal(sent.name, "fast", "the entry is named by what the picker shows");
  assert.equal(sent.changes.model, "gpt-5");
  assert.equal(sent.changes.web_search, true);
  assert.equal(sent.changes.context_window, 200_000);
});

test("a setting changed after the bar has gone does not bring it back", async () => {
  const ui = await harness();
  const interrupted = { ...state, resumable: { resumable: true, kind: "interrupted", description: "cut short" } };
  await ui.send({ type: "state", state: interrupted });
  assert.ok(ui.one("#resume-bar"));
  await new Promise((resolve) => setTimeout(resolve, 2100));
  assert.equal(ui.one("#resume-bar"), null);

  // Switching the effort sends the whole state again, with the same interruption in it.
  await ui.send({ type: "state", state: { ...interrupted, settings: { ...interrupted.settings, effort: "high" } } });
  await new Promise((resolve) => setTimeout(resolve, 50));

  assert.equal(ui.one("#resume-bar"), null, "the same interruption is announced once, not on every change");
});

test("the interrupted bar steps aside after a couple of seconds", async () => {
  const ui = await harness();
  await ui.send({
    type: "state",
    state: { ...state, resumable: { resumable: true, kind: "interrupted", description: "cut short" } },
  });
  assert.ok(ui.one("#resume-bar"));

  await new Promise((resolve) => setTimeout(resolve, 2100));

  assert.equal(ui.one("#resume-bar"), null, "the announcement goes; /continue still works");
});

function sentTurn(): Turn {
  const turn = createTurn("你在干什么", [], 3000, "turn-sent");
  turn.sent = { to: "zettdemos", note: "delivered" };
  turn.status = "done";
  turn.finishedAt = 3000;
  return turn;
}

function receivedTurn(): Turn {
  const turn = createTurn("run the tests", [], 4000, "turn-received");
  turn.from = { id: "session-api", name: "api" };
  applyEvent(turn, { type: "text_delta", session_id: "s", text: "On it." } as never, 4100);
  turn.status = "done";
  turn.finishedAt = 4200;
  return turn;
}

test("a message sent to another session shows who it went to and what it said, and nothing is answered under it", async () => {
  const ui = await harness([sentTurn()]);

  assert.ok(ui.text(".user-from").includes("@zettdemos"), "who it went to");
  assert.ok(ui.text(".user-from").includes("delivered"));
  assert.equal(ui.text(".user-text"), "你在干什么", "what was sent");
  assert.equal(ui.all(".assistant").length, 0, "it is not a request to this chat's model: no answer area, no receipt");
  assert.equal(ui.all(".receipt").length, 0);
});

test("a message another session sent is shown with its sender, above the answer it started", async () => {
  const ui = await harness([receivedTurn()]);

  assert.ok(ui.text(".user-from").includes("@api"), "who sent it");
  assert.equal(ui.text(".user-text"), "run the tests", "what it said");
  assert.ok(ui.text(".assistant").includes("On it."), "the reply this chat gave");
});

test("the chat looks for messages from other sessions from the first load, not only after a refresh", async () => {
  const chat = await readFile("src/chat.ts", "utf8");
  const load = /private async load\(\): Promise<void> \{[\s\S]*?\n  \}\n/.exec(chat)?.[0] ?? "";
  const refresh = /async refreshAll\(\): Promise<void> \{[\s\S]*?\n  \}\n/.exec(chat)?.[0] ?? "";

  assert.ok(load.includes("this.watchMessages()"), "the first load starts the watch: a window never refreshed would hear nothing");
  assert.ok(refresh.includes("this.watchMessages()"), "a refresh keeps it going");
  assert.ok(!/takeMessage[\s\S]{0,200}readyForPrompt/.test(chat), "polling must not pop the add-model form every few seconds");
});

test("a message the agent sends to another session is shown with what it said, open without a click", async () => {
  const turn = createTurn("tell the api session to run the tests", [], 5000, "turn-send");
  applyEvent(
    turn,
    {
      type: "tool_started",
      call_id: "m1",
      name: "send_message",
      arguments: { to: "01a15029-7de1-7790-aebe-334c8ce2aa8e", message: "Please run the pagination tests and report back." },
    },
    5100,
  );
  applyEvent(
    turn,
    {
      type: "tool_finished",
      call_id: "m1",
      name: "send_message",
      output: "Delivered to api (id 01a15029); it started on it now.",
      ok: true,
      skipped: false,
    },
    5200,
  );
  const ui = await harness([turn]);

  const body = ui.text(".tool-body");
  assert.ok(body.includes("Please run the pagination tests and report back."), "what was sent");
  assert.ok(body.includes("Delivered to api"), "and whether it was taken");
  assert.ok(ui.text(".tool-verb").includes("Message"));
});

test("the session list shows a spinner on a session that is still running, wherever the reader is", async () => {
  const ui = await harness([], {
    ...state,
    sessions: [
      { id: "session-1", title: "Pagination work", updatedAt: "2026-10-18T11:59:30Z", entries: 12, tokens: 1540, current: true, running: false },
      { id: "session-2", title: "Long refactor", updatedAt: "2026-10-18T11:58:00Z", entries: 40, tokens: 9000, current: false, running: true },
      { id: "session-3", title: "Old idea", updatedAt: "2026-10-17T09:00:00Z", entries: 4, tokens: 300, current: false, running: false },
    ],
  });
  await ui.send({ type: "history", open: true });

  const row = (id: string) => ui.one(`[data-session-id="${id}"]`);
  assert.ok(row("session-2")?.querySelector(".session-running"), "the running one turns");
  assert.ok(row("session-2")?.textContent?.includes("running"), "and says so in words, for those who cannot see it turn");
  assert.equal(row("session-1")?.querySelector(".session-running"), null);
  assert.equal(row("session-3")?.querySelector(".session-running"), null);
  assert.equal(ui.all(".session-running").length, 1);
});
