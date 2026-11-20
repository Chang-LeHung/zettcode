import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { JSDOM } from "jsdom";

import type { HarnessEntry, HarnessPreview } from "../../typescript/src/types.js";
import { parseAsk, showHarnessPanel } from "../src/harnesses.js";
import { lastPanel, posted, receive } from "./vscode-stub.js";

const entry = (name: string, extra: Partial<HarnessEntry> = {}): HarnessEntry => ({
  name,
  origin: `acme/${name}@main`,
  commit: "0123456789abcdef0123456789abcdef01234567",
  state: "",
  in_use: false,
  repositories: [
    { name, version: "1.0", description: "d", tools: ["a", "b"], files: [], error: "", file_count: 3 },
  ],
  ...extra,
});

const preview = (extra: Partial<HarnessPreview> = {}): HarnessPreview => ({
  action: "add",
  name: "fresh",
  source: "acme/fresh",
  commit: "a".repeat(40),
  digest: "b".repeat(64),
  version: "2.0",
  description: "<img src=x onerror=alert(1)>",
  tools: ["run"],
  banned: ["delete_file"],
  files: ["manifest.toml", "tools/run.py", "key"],
  size: 1234,
  changes: [],
  up_to_date: false,
  caution: "This code will run on your machine.",
  links: { key: "/etc/hosts" },
  ...extra,
});

/** A fake server library that records what the host asked of it. */
function fakeClient(options: { fail?: string } = {}) {
  const calls: unknown[][] = [];
  let entries = [entry("todos", { in_use: true })];
  const record =
    <T>(name: string, answer: (...args: any[]) => T) =>
    async (...args: unknown[]): Promise<T> => {
      calls.push([name, ...args]);
      if (options.fail !== undefined && name !== "entries") {
        throw new Error(options.fail);
      }
      return answer(...args);
    };
  const harnesses = {
    entries: record("entries", () => entries),
    entry: record("entry", (name: string) => entry(name, { state: "ok", repositories: [{ ...entry(name).repositories[0]!, files: ["manifest.toml"] }] })),
    previewAdd: record("previewAdd", () => preview()),
    previewUpdate: record("previewUpdate", (name: string) =>
      preview({ action: "update", name, changes: ["version: 1.0 -> 2.0"], links: {}, banned: [] }),
    ),
    add: record("add", (_source: string, options: { name: string }) => {
      entries = [...entries, entry(options.name)];
      return entry(options.name);
    }),
    update: record("update", (name: string) => entry(name)),
    fork: record("fork", (_name: string, newName: string) => {
      entries = [...entries, entry(newName)];
      return entry(newName);
    }),
    remove: record("remove", (name: string) => {
      entries = entries.filter((one) => one.name !== name);
    }),
  };
  return { client: { harnesses } as never, calls };
}

const extension = { toString: () => "file:///extension" } as never;

/** Open the panel, run its script in jsdom, and carry messages both ways like the editor does. */
async function open(client: never) {
  posted.length = 0;
  await showHarnessPanel(async () => client, extension, "zettcode");
  const dom = new JSDOM(lastPanel!.webview.html, {
    runScripts: "outside-only",
    pretendToBeVisual: true,
  });
  const { window } = dom;
  const sent: unknown[] = [];
  (window as unknown as { acquireVsCodeApi: () => unknown }).acquireVsCodeApi = () => ({
    postMessage: (message: unknown) => sent.push(message),
  });
  if ((window as unknown as { CSS?: unknown }).CSS === undefined) {
    (window as unknown as { CSS: unknown }).CSS = { escape: (text: string) => text };
  }
  window.eval(window.document.querySelector("script")?.textContent ?? "");
  let delivered = 0;
  let handled = 0;
  /** Hand the host what the page posted, then the page what the host posted, until both are quiet. */
  const settle = async (): Promise<void> => {
    for (let round = 0; round < 5; round += 1) {
      while (handled < sent.length) {
        await receive(sent[handled++]);
      }
      while (delivered < posted.length) {
        window.dispatchEvent(new window.MessageEvent("message", { data: posted[delivered++] }));
      }
    }
  };
  const $ = (selector: string) => window.document.querySelector(selector);
  const press = async (label: string, within: string = "body"): Promise<void> => {
    const button = [...window.document.querySelectorAll(`${within} button`)].find(
      (candidate) => candidate.textContent === label,
    ) as HTMLButtonElement | undefined;
    assert.ok(button, `a "${label}" button in ${within}`);
    button.click();
    await settle();
  };
  const add = async (source: string, name = ""): Promise<void> => {
    ($("#harness-source") as HTMLInputElement).value = source;
    ($("#harness-name") as HTMLInputElement).value = name;
    $("#harness-add")!.dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
    await settle();
  };
  await settle();
  return { window, $, press, add, settle, sent };
}

test("the page asks for the library when it opens and draws each harness with its size and whether it is in use", async () => {
  const { client } = fakeClient();
  const page = await open(client);

  assert.equal(lastPanel!.title, "ZettCode: Harnesses");
  assert.equal(page.$("#harness-count")?.textContent, "1 harness");
  const row = page.$('.harness[data-name="todos"]');
  assert.ok(row?.textContent?.includes("in use"));
  assert.ok(row?.textContent?.includes("2 tools · 3 files"), row?.textContent ?? "");
  assert.ok(row?.textContent?.includes("0123456789"), "the commit is shown short");
});

test("adding is a preview first: the caution, the links and the files are on the page, and nothing is kept yet", async () => {
  const { client, calls } = fakeClient();
  const page = await open(client);

  await page.add("acme/fresh", "fresh");

  assert.deepEqual(calls.at(-1), ["previewAdd", "acme/fresh", { name: "fresh" }]);
  const shown = page.$("#harness-preview")!;
  assert.equal(shown.hasAttribute("hidden"), false);
  const text = shown.textContent ?? "";
  assert.ok(text.includes("This code will run on your machine."));
  assert.ok(text.includes("key → /etc/hosts"), "where a link points is shown");
  assert.ok(text.includes("delete_file"), "a name the program does not allow is shown");
  assert.ok(text.includes("tools/run.py") && text.includes("3 files"));
  assert.equal(calls.some((call) => call[0] === "add"), false, "a preview keeps nothing");
});

test("what a downloaded manifest says is text on the page, never markup", async () => {
  const { client } = fakeClient();
  const page = await open(client);

  await page.add("acme/fresh");

  assert.equal(page.$("#harness-preview img"), null);
  assert.ok(page.$("#harness-preview")?.textContent?.includes("<img src=x onerror=alert(1)>"));
});

test("Keep sends back the commit and digest of the preview that was shown, and the list is read again", async () => {
  const { client, calls } = fakeClient();
  const page = await open(client);
  await page.add("acme/fresh", "fresh");

  await page.press("Keep", "#harness-preview");

  assert.deepEqual(calls.filter((call) => call[0] === "add"), [
    ["add", "acme/fresh", { commit: "a".repeat(40), digest: "b".repeat(64), name: "fresh" }],
  ]);
  assert.equal(page.$("#harness-count")?.textContent, "2 harnesses");
  assert.equal(page.$("#harness-preview")?.hasAttribute("hidden"), true);
  assert.equal(page.$("#harness-status")?.textContent, "Added fresh.");
  assert.equal((page.$("#harness-source") as HTMLInputElement).value, "", "the form is ready for the next one");
});

test("Cancel forgets the preview, and a Keep that comes after it is refused by the host", async () => {
  const { client, calls } = fakeClient();
  const page = await open(client);
  await page.add("acme/fresh");
  await page.press("Cancel", "#harness-preview");
  assert.equal(page.$("#harness-preview")?.hasAttribute("hidden"), true);

  await receive({ type: "confirm" });

  assert.equal(calls.some((call) => call[0] === "add"), false);
  assert.deepEqual(posted.at(-1), { type: "error", text: "There is no preview to keep. Preview it again." });
});

test("an update shows what would change and keeps only that preview's commit", async () => {
  const { client, calls } = fakeClient();
  const page = await open(client);

  await page.press("Update", ".harness");
  assert.ok(page.$("#harness-preview")?.textContent?.includes("version: 1.0 -> 2.0"));
  await page.press("Update", "#harness-preview");

  assert.deepEqual(calls.filter((call) => call[0] === "previewUpdate"), [["previewUpdate", "todos", { force: false }]]);
  assert.deepEqual(calls.filter((call) => call[0] === "update"), [
    ["update", "todos", { commit: "a".repeat(40), digest: "b".repeat(64), force: false }],
  ]);
  assert.equal(page.$("#harness-status")?.textContent, "Updated todos.");
});

test("removing asks twice, and the first press removes nothing", async () => {
  const { client, calls } = fakeClient();
  const page = await open(client);

  await page.press("Remove", ".harness");
  assert.equal(calls.some((call) => call[0] === "remove"), false);
  assert.ok(page.$(".harness button.danger")?.textContent?.includes("Remove todos?"));

  await page.press("Remove todos?", ".harness");
  assert.deepEqual(calls.filter((call) => call[0] === "remove"), [["remove", "todos"]]);
  assert.equal(page.$("#harness-count")?.textContent, "0 harnesses");
  assert.ok(page.$("#harness-list")?.textContent?.includes("The library is empty"));
});

test("a fork asks for the new name, then copies", async () => {
  const { client, calls } = fakeClient();
  const page = await open(client);

  await page.press("Fork", ".harness");
  (page.$(".harness-ask input") as HTMLInputElement).value = "mine";
  await page.press("Fork", ".harness-ask");

  assert.deepEqual(calls.filter((call) => call[0] === "fork"), [["fork", "todos", "mine"]]);
  assert.equal(page.$('.harness[data-name="mine"]') !== null, true);
});

test("details show the state and the files the list leaves out", async () => {
  const { client } = fakeClient();
  const page = await open(client);

  await page.press("Details", ".harness");

  const detail = page.$(".harness-detail");
  assert.ok(detail?.textContent?.includes("state: ok"));
  assert.ok(detail?.textContent?.includes("manifest.toml"));
});

test("a refusal is the server's own words, shown as an error, and the buttons work again", async () => {
  const { client } = fakeClient({ fail: "a run is in progress" });
  const page = await open(client);

  await page.press("Update", ".harness");

  const status = page.$("#harness-status")!;
  assert.equal(status.textContent, "a run is in progress");
  assert.ok(status.className.includes("error"));
  assert.equal((page.$(".harness button") as HTMLButtonElement).disabled, false);
});

test("the host reads only the messages the page is known to send", () => {
  assert.equal(parseAsk(null), null);
  assert.equal(parseAsk({ type: "other" }), null);
  assert.equal(parseAsk({ type: "remove" }), null, "a name is required");
  assert.equal(parseAsk({ type: "fork", name: "a", newName: "" }), null);
  assert.equal(parseAsk({ type: "preview-add", source: "  " }), null);
  assert.deepEqual(parseAsk({ type: "preview-add", source: " a/b ", name: " x " }), { type: "preview-add", source: "a/b", name: "x" });
  assert.deepEqual(parseAsk({ type: "preview-update", name: "x" }), { type: "preview-update", name: "x", force: false });
});

test("the page builds its markup with text nodes only: no innerHTML or insertAdjacentHTML anywhere in it", async () => {
  const source = await readFile("src/core/harness-page.ts", "utf8");
  assert.equal(/innerHTML|outerHTML|insertAdjacentHTML|document\.write/.test(source), false);
});
