/** The harness library panel: the page `core/harness-page.ts` builds and the host that answers what it posts. */

import * as vscode from "vscode";

import type { ZettCodeClient } from "../../typescript/src/index.js";
import type { HarnessPreview } from "../../typescript/src/types.js";
import { HARNESS_SCRIPT, harnessesPage } from "./core/harness-page.js";
import { html } from "./usage.js";

let panel: vscode.WebviewPanel | null = null;
/** How the open panel reaches the server: replaced on every show, so a panel kept open follows a restarted server. */
let reach: (() => Promise<ZettCodeClient>) | null = null;

/** What the page may post. Anything else is ignored: the page is ours, but a message is data all the same. */
type Ask =
  | { type: "ready" }
  | { type: "cancel" }
  | { type: "confirm" }
  | { type: "detail"; name: string }
  | { type: "preview-add"; source: string; name: string }
  | { type: "preview-update"; name: string; force: boolean }
  | { type: "fork"; name: string; newName: string }
  | { type: "remove"; name: string };

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/** Read a posted message into an `Ask`, or null when it is not one. */
export function parseAsk(message: unknown): Ask | null {
  if (typeof message !== "object" || message === null) {
    return null;
  }
  const raw = message as Record<string, unknown>;
  switch (raw.type) {
    case "ready":
    case "cancel":
    case "confirm":
      return { type: raw.type };
    case "detail":
    case "remove":
      return text(raw.name) === "" ? null : { type: raw.type, name: text(raw.name) };
    case "preview-add":
      return text(raw.source).trim() === "" ? null : { type: "preview-add", source: text(raw.source).trim(), name: text(raw.name).trim() };
    case "preview-update":
      return text(raw.name) === "" ? null : { type: "preview-update", name: text(raw.name), force: raw.force === true };
    case "fork":
      return text(raw.name) === "" || text(raw.newName) === "" ? null : { type: "fork", name: text(raw.name), newName: text(raw.newName) };
    default:
      return null;
  }
}

/**
 * Show the library and let the reader add, update, fork and remove from it.
 *
 * Adding and updating are two steps and the host keeps the first: the page posts "confirm" and the host sends back the
 * `commit` and `digest` of the preview it showed, so what is kept is exactly what was read, and the page holds nothing
 * to tamper with. The server refuses it when the download has changed since.
 */
export async function showHarnessPanel(
  client: () => Promise<ZettCodeClient>,
  extensionUri: vscode.Uri,
  workspaceName: string,
): Promise<void> {
  reach = client;
  if (panel === null) {
    panel = vscode.window.createWebviewPanel("zettcode.harnesses", "ZettCode: Harnesses", vscode.ViewColumn.Active, {
      enableScripts: true,
      localResourceRoots: [vscode.Uri.joinPath(extensionUri, "media")],
    });
    const target = panel;
    let pending: HarnessPreview | null = null;
    let force = false;
    target.onDidDispose(() => {
      panel = null;
    });
    const send = (message: unknown): void => {
      void target.webview.postMessage(message);
    };
    const refresh = async (library: ZettCodeClient["harnesses"]): Promise<void> => {
      send({ type: "list", harnesses: await library.entries() });
    };
    target.webview.onDidReceiveMessage(async (message: unknown) => {
      const ask = parseAsk(message);
      if (ask === null) {
        return;
      }
      try {
        // Resolved per message: a server restarted under the open panel has a new address and token.
        if (reach === null) {
          return;
        }
        const library = (await reach()).harnesses;
        switch (ask.type) {
          case "ready":
            await refresh(library);
            return;
          case "cancel":
            pending = null;
            return;
          case "detail":
            send({ type: "detail", entry: await library.entry(ask.name) });
            return;
          case "preview-add":
            pending = await library.previewAdd(ask.source, ask.name === "" ? {} : { name: ask.name });
            force = false;
            send({ type: "preview", preview: pending });
            return;
          case "preview-update":
            pending = await library.previewUpdate(ask.name, { force: ask.force });
            force = ask.force;
            send({ type: "preview", preview: pending });
            return;
          case "confirm": {
            const shown = pending;
            if (shown === null) {
              send({ type: "error", text: "There is no preview to keep. Preview it again." });
              return;
            }
            const proof = { commit: shown.commit, digest: shown.digest };
            if (shown.action === "add") {
              await library.add(shown.source, { ...proof, name: shown.name });
            } else {
              await library.update(shown.name, { ...proof, force });
            }
            pending = null;
            await refresh(library);
            send({ type: "done", text: `${shown.action === "add" ? "Added" : "Updated"} ${shown.name}.` });
            return;
          }
          case "fork":
            await library.fork(ask.name, ask.newName);
            await refresh(library);
            send({ type: "done", text: `Copied ${ask.name} to ${ask.newName}.` });
            return;
          case "remove":
            await library.remove(ask.name);
            await refresh(library);
            send({ type: "done", text: `Removed ${ask.name}.` });
            return;
        }
      } catch (failure) {
        send({ type: "error", text: failure instanceof Error ? failure.message : String(failure) });
      }
    });
  }
  panel.webview.html = html(panel.webview, extensionUri, workspaceName, {
    ...harnessesPage(),
    // The editor's channel is named here, not in the page's own file: nothing under core/ may touch the editor's API.
    script: `const api = acquireVsCodeApi();\n${HARNESS_SCRIPT}`,
  });
  panel.reveal(vscode.ViewColumn.Active);
}
