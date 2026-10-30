/** The usage, model-check and plugin pages: the panel around the HTML that `core/usage-page.ts` builds. */

import { randomBytes } from "node:crypto";
import * as vscode from "vscode";

import type { ZettCodeClient } from "../../typescript/src/index.js";
import type { ModelCheck, PluginEntry } from "../../typescript/src/types.js";
import { escapeHtml } from "./core/format.js";
import { doctorPage, PAGE_CSS, pluginsPage, scopeNote, usagePage, type Page } from "./core/usage-page.js";

/** The pages that only show something: one panel, no script. */
let panel: vscode.WebviewPanel | null = null;
/** The plugins page: a panel of its own, because its switches need a script and a panel cannot gain one. */
let pluginPanel: vscode.WebviewPanel | null = null;
/** The client the open plugins page writes through, resolved on every press so a restart is picked up. */
let pluginClient: (() => Promise<ZettCodeClient>) | null = null;

/** Show what every stored session of the workspace spent. */
export async function showUsagePanel(
  client: ZettCodeClient,
  extensionUri: vscode.Uri,
  workspaceName: string,
  workspacePath = "",
): Promise<void> {
  show(extensionUri, workspaceName, usagePage(await client.usageLedger()), workspacePath);
}

/** Show a model check. */
export async function showDoctorPanel(
  _client: ZettCodeClient,
  checks: ModelCheck[],
  extensionUri: vscode.Uri,
  workspaceName: string,
): Promise<void> {
  show(extensionUri, workspaceName, doctorPage(checks));
}

/**
 * Show the plugins the server loaded, the ones that failed, and every one the next start can leave out.
 *
 * The page's switches are written by the host: only it can reach the server, so the script posts what was flipped and
 * waits to be told what came of it. A refusal is shown on the row itself — a name compiled into the program, a plugin
 * the configuration file has already switched off — rather than as a message somewhere behind the panel.
 */
export async function showPluginsPanel(
  client: () => Promise<ZettCodeClient>,
  extensionUri: vscode.Uri,
  workspaceName: string,
): Promise<void> {
  const current = await client();
  const report = await current.plugins();
  pluginClient = client;
  if (pluginPanel === null) {
    pluginPanel = vscode.window.createWebviewPanel("zettcode.plugins", "ZettCode: Plugins", vscode.ViewColumn.Active, {
      enableScripts: true,
      localResourceRoots: [vscode.Uri.joinPath(extensionUri, "media")],
    });
    pluginPanel.onDidDispose(() => {
      pluginPanel = null;
    });
    pluginPanel.webview.onDidReceiveMessage(async (message: unknown) => {
      const asked = message as { type?: string; name?: string; enabled?: boolean } | null;
      if (asked?.type !== "switch" || typeof asked.name !== "string" || asked.name === "") {
        return;
      }
      const target = pluginPanel;
      if (target === null) {
        return;
      }
      let entry: PluginEntry | null = null;
      let error = "";
      const writer = pluginClient;
      if (writer === null) {
        return;
      }
      try {
        // Resolved per press: a server restarted under the open panel has a new address and token.
        entry = await (await writer()).setPluginEnabled(asked.name, asked.enabled === true);
      } catch (failure) {
        error = failure instanceof Error ? failure.message : String(failure);
      }
      void target.webview.postMessage(
        entry === null
          ? { type: "switched", name: asked.name, enabled: asked.enabled === true, error }
          : { type: "switched", name: entry.origin, enabled: entry.enabled, error: "" },
      );
    });
  }
  pluginPanel.title = "ZettCode: Plugins";
  pluginPanel.webview.html = html(pluginPanel.webview, extensionUri, workspaceName, {
    ...pluginsPage(report),
    script: SWITCH_SCRIPT,
  });
  pluginPanel.reveal(vscode.ViewColumn.Active);
}

/**
 * The switch's own script: it posts the flip and lets the host answer, because only the host can write the file. A row
 * is moved on the answer, so the page does not reload and the reader keeps their place.
 *
 * It lives here, beside the handler that answers it, and not with the markup: it is the editor's API the script speaks
 * to, and nothing under `core/` may touch that.
 */
const SWITCH_SCRIPT = `
const api = acquireVsCodeApi();
document.addEventListener("click", (event) => {
  const button = event.target instanceof Element ? event.target.closest(".switch") : null;
  if (button === null) { return; }
  const enabled = button.dataset.enabled !== "true";
  button.disabled = true;
  api.postMessage({ type: "switch", name: button.dataset.name, enabled });
});
function say(row, text) {
  // The reason a switch was refused is the row's own line; the one a plugin failed to load for stays where it is.
  const said = row.querySelector('.plugin-failure[data-why="switch"]') || row.appendChild(document.createElement("span"));
  said.className = "plugin-failure";
  said.dataset.why = "switch";
  said.textContent = text;
}
function count() {
  // The switch carries the state, so a row that could not load is neither on nor off.
  const lit = document.querySelectorAll('.switch[data-enabled="true"]').length;
  const dark = document.querySelectorAll('.switch[data-enabled="false"]').length;
  const failed = document.querySelectorAll(".plugin.failed").length;
  const set = (id, text) => { const node = document.getElementById(id); if (node !== null) { node.textContent = String(text); } };
  set("plugins-on", lit);
  set("plugins-switches", lit + dark);
  set("plugins-failed", failed);
}
window.addEventListener("message", (event) => {
  const message = event.data;
  if (message === null || message.type !== "switched") { return; }
  const row = document.querySelector('.plugin[data-name="' + CSS.escape(message.name) + '"]');
  if (row === null) { return; }
  const button = row.querySelector(".switch");
  const word = row.querySelector(".switch-word");
  if (message.error) {
    if (button !== null) { button.disabled = false; }
    say(row, message.error);
    return;
  }
  if (button !== null) {
    button.dataset.enabled = String(message.enabled);
    button.setAttribute("aria-pressed", String(message.enabled));
    button.setAttribute("aria-checked", String(message.enabled));
    button.disabled = false;
  }
  if (word !== null) { word.textContent = message.enabled ? "on" : "off"; }
  row.classList.toggle("on", message.enabled);
  row.classList.toggle("off", !message.enabled);
  const refused = row.querySelector('.plugin-failure[data-why="switch"]');
  if (refused !== null) { refused.remove(); }
  count();
});
`;

function show(extensionUri: vscode.Uri, workspaceName: string, page: Page, workspacePath = ""): void {
  if (panel === null) {
    panel = vscode.window.createWebviewPanel("zettcode.usage", "ZettCode: Usage", vscode.ViewColumn.Active, {
      enableScripts: false,
      localResourceRoots: [vscode.Uri.joinPath(extensionUri, "media")],
    });
    panel.onDidDispose(() => {
      panel = null;
    });
  }
  panel.title = `ZettCode: ${page.title}`;
  panel.webview.html = html(panel.webview, extensionUri, workspaceName, page, workspacePath);
  panel.reveal(vscode.ViewColumn.Active);
}

function html(
  webview: vscode.Webview,
  extensionUri: vscode.Uri,
  workspaceName: string,
  page: Page,
  workspacePath = "",
): string {
  const icon = webview.asWebviewUri(vscode.Uri.joinPath(extensionUri, "media", "logo.svg")).toString();
  const nonce = randomBytes(16).toString("base64");
  const script =
    page.script === undefined ? "" : `<script nonce="${nonce}">${page.script}</script>`;
  const scriptRule = page.script === undefined ? "" : ` script-src 'nonce-${nonce}';`;
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${webview.cspSource}; style-src 'unsafe-inline';${scriptRule}">
<title>ZettCode: ${escapeHtml(page.title)}</title>
<style>${PAGE_CSS}</style>
</head>
<body>
<div class="page">
  <div class="brand"><img src="${icon}" alt=""><strong>ZettCode</strong><span>· ${escapeHtml(workspaceName)}</span></div>
  <h1>${escapeHtml(page.title)}</h1>
  ${page.scoped === true ? scopeNote(workspacePath) : ""}
  <div class="summary">${page.summary}</div>
  ${page.body}
</div>
${script}
</body>
</html>`;
}
