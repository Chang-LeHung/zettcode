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
function fakeClient(
  options: {
    fail?: string;
    /** Refuse `previewUpdate` unless it is forced, as the server does for a harness changed since it was installed. */
    refuseUnforced?: string;
    /** Make the list fail once something was kept, like a server restarting a moment after. */
    listFailsAfterKeep?: boolean;
    detail?: Partial<HarnessEntry>;
    upToDate?: boolean;
  } = {},
) {
  const calls: unknown[][] = [];
  let entries = [entry("todos", { in_use: true })];
  let kept = false;
  const record =
    <T>(name: string, answer: (...args: any[]) => T) =>
    async (...args: unknown[]): Promise<T> => {
      calls.push([name, ...args]);
      if (options.fail !== undefined && name !== "entries") {
        throw new Error(options.fail);
      }
      if (name === "entries" && kept && options.listFailsAfterKeep === true) {
        throw new Error("the server is restarting");
      }
      if (["add", "update"].includes(name)) {
        kept = true;
      }
      return answer(...args);
    };
  const harnesses = {
    entries: record("entries", () => entries),
    entry: record("entry", (name: string) =>
      entry(name, {
        state: "ok",
        repositories: [{ ...entry(name).repositories[0]!, files: ["manifest.toml"] }],
        ...options.detail,
      }),
    ),
    previewAdd: record("previewAdd", () => preview()),
    previewUpdate: record("previewUpdate", (name: string, opts: { force?: boolean }) => {
      if (options.refuseUnforced !== undefined && opts.force !== true) {
        throw new Error(options.refuseUnforced);
      }
      return preview({
        action: "update",
        name,
        changes: options.upToDate === true ? [] : ["version: 1.0 -> 2.0"],
        up_to_date: options.upToDate === true,
        links: {},
        banned: [],
      });
    }),
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
  assert.equal(status.textContent, "a run is in progress", "forcing would not help, so no second button");
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

test("the page's own styles are in the document the panel loads", async () => {
  const { client } = fakeClient();
  await open(client);

  const html = lastPanel!.webview.html;
  assert.ok(html.includes(".harness-form") && html.includes(".act.primary") && html.includes(".harness-files"), "harness CSS");
  assert.ok(html.includes(".panel-head"), "and the shared page CSS under it");
});

test("a preview that failed leaves nothing to Keep: the host forgets the one before it", async () => {
  const { client, calls } = fakeClient();
  const page = await open(client);
  await page.add("acme/fresh");
  assert.equal(page.$("#harness-preview")?.hasAttribute("hidden"), false);

  // The same page asks for a different download, which fails; a Keep posted anyway must be refused.
  (client as any).harnesses.previewAdd = async () => {
    throw new Error("could not download");
  };
  await page.add("acme/other");
  await receive({ type: "confirm" });

  assert.equal(calls.some((call) => call[0] === "add"), false);
  assert.deepEqual(posted.at(-1), { type: "error", text: "There is no preview to keep. Preview it again." });
});

test("a fork or a removal also drops the preview, and the page loaded again has none to keep", async () => {
  const { client, calls } = fakeClient();
  const page = await open(client);
  await page.add("acme/fresh");
  await receive({ type: "fork", name: "todos", newName: "mine" });
  await receive({ type: "confirm" });
  assert.deepEqual(posted.at(-1), { type: "error", text: "There is no preview to keep. Preview it again." });

  await page.add("acme/fresh");
  await showHarnessPanel(async () => client, extension, "zettcode");
  await receive({ type: "confirm" });
  assert.deepEqual(posted.at(-1), { type: "error", text: "There is no preview to keep. Preview it again." });
  assert.equal(calls.some((call) => call[0] === "add"), false);
});

test("a fork or a removal keeps the source typed in the form; a kept download empties it", async () => {
  const { client } = fakeClient();
  const page = await open(client);
  ($("#harness-source", page.window) as HTMLInputElement).value = "acme/typed";

  await page.press("Fork", ".harness");
  (page.$(".harness-ask input") as HTMLInputElement).value = "mine";
  await page.press("Fork", ".harness-ask");

  assert.equal((page.$("#harness-source") as HTMLInputElement).value, "acme/typed");
  assert.equal(page.$("#harness-status")?.textContent, "Copied todos to mine.", "and the list that follows does not wipe it");
});

test("a kept harness is reported even when the list cannot be read straight after", async () => {
  const { client } = fakeClient({ listFailsAfterKeep: true });
  const page = await open(client);
  await page.add("acme/fresh", "fresh");

  await page.press("Keep", "#harness-preview");

  assert.equal(page.$("#harness-status")?.textContent, "Added fresh.", "the page ends on the success, not an error");
  assert.equal(page.$("#harness-status")?.className.includes("error"), false);
});

test("Details leaves the preview and its Keep working", async () => {
  const { client, calls } = fakeClient();
  const page = await open(client);
  await page.add("acme/fresh", "fresh");

  await page.press("Details", ".harness");
  await page.press("Keep", "#harness-preview");

  assert.equal(calls.filter((call) => call[0] === "add").length, 1);
});

test("a Keep the server refuses can be pressed again without a new download", async () => {
  const { client, calls } = fakeClient();
  const page = await open(client);
  await page.add("acme/fresh", "fresh");
  const real = (client as any).harnesses.add;
  (client as any).harnesses.add = async () => {
    throw new Error("a run is in progress");
  };
  await page.press("Keep", "#harness-preview");
  assert.equal(page.$("#harness-status")?.textContent, "a run is in progress");

  (client as any).harnesses.add = real;
  await page.press("Keep", "#harness-preview");

  assert.equal(calls.filter((call) => call[0] === "previewAdd").length, 1);
  assert.equal(page.$("#harness-status")?.textContent, "Added fresh.");
});

test("an update the server refuses can be pressed again, forced, and keeps with force", async () => {
  const { client, calls } = fakeClient({ refuseUnforced: "todos was changed since it was installed; `update --force` replaces it" });
  const page = await open(client);

  await page.press("Update", ".harness");
  assert.ok(page.$("#harness-status")?.textContent?.includes("changed since it was installed"));

  await page.press("Update anyway", "#harness-status");
  await page.press("Update", "#harness-preview");

  assert.deepEqual(calls.filter((call) => call[0] === "previewUpdate").map((call) => call[2]), [
    { force: false },
    { force: true },
  ]);
  assert.deepEqual(calls.filter((call) => call[0] === "update"), [
    ["update", "todos", { commit: "a".repeat(40), digest: "b".repeat(64), force: true }],
  ]);
});

test("an update that is already current says so, and a damaged harness shows why", async () => {
  const { client } = fakeClient({
    upToDate: true,
    detail: {
      state: "damaged",
      repositories: [{ name: "todos", version: "", description: "", tools: [], files: [], error: "manifest.toml is not valid TOML", file_count: 0 }],
    },
  });
  const page = await open(client);

  await page.press("Update", ".harness");
  assert.ok(page.$("#harness-preview")?.textContent?.includes("Already at this commit."));
  await page.press("Cancel", "#harness-preview");
  await page.press("Details", ".harness");

  const detail = page.$(".harness-detail");
  assert.ok(detail?.textContent?.includes("state: damaged"));
  assert.ok(detail?.textContent?.includes("manifest.toml is not valid TOML"));
  assert.ok(detail?.textContent?.includes("no tools"));
});

/** `querySelector` on a window, for a test that has the window but not the page helper. */
function $(selector: string, window: { document: Document }): Element | null {
  return window.document.querySelector(selector);
}
