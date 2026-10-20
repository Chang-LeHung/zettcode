/** The usage, model-check and plugin pages: the panel around the HTML that `core/usage-page.ts` builds. */

import * as vscode from "vscode";

import type { ZettCodeClient } from "../../typescript/src/index.js";
import type { ModelCheck } from "../../typescript/src/types.js";
import { escapeHtml } from "./core/format.js";
import { doctorPage, PAGE_CSS, pluginsPage, scopeNote, usagePage, type Page } from "./core/usage-page.js";

let panel: vscode.WebviewPanel | null = null;

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

/** Show the plugins the server loaded and the ones that failed. */
export async function showPluginsPanel(
  client: ZettCodeClient,
  extensionUri: vscode.Uri,
  workspaceName: string,
): Promise<void> {
  show(extensionUri, workspaceName, pluginsPage(await client.plugins()));
}

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
  workspacePath: string,
): string {
  const icon = webview.asWebviewUri(vscode.Uri.joinPath(extensionUri, "media", "logo.svg")).toString();
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${webview.cspSource}; style-src 'unsafe-inline';">
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
</body>
</html>`;
}
