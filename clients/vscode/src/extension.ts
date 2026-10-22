/** The extension's entry point: one server, one chat view, and the commands around them. */

import * as vscode from "vscode";

import { ChatViewProvider } from "./chat.js";
import { DIFF_SCHEME, DiffContentProvider } from "./diffs.js";
import { ServerManager } from "./server.js";
import { installServer } from "./provision.js";

let server: ServerManager | null = null;

export function activate(context: vscode.ExtensionContext): void {
  const output = vscode.window.createOutputChannel("ZettCode");
  context.subscriptions.push(output);

  const folders = vscode.workspace.workspaceFolders ?? [];
  const workspace = folders[0]?.uri.fsPath ?? "";
  if (folders.length > 1) {
    output.appendLine(`[warn] This window has ${folders.length} folders; ZettCode serves ${folders[0]?.name}.`);
  }
  if (!workspace) {
    output.appendLine("[warn] No workspace folder is open; the agent needs one.");
  }

  // The server is installed once, into the extension's own environment, unless the reader turned that off or named a
  // command of their own somewhere the extension can reach.
  const autoInstall = vscode.workspace.getConfiguration("zettcode").get<boolean>("server.autoInstall", true);
  server = new ServerManager(
    workspace,
    output,
    autoInstall ? () => installServer({ storage: context.globalStorageUri.fsPath, output }) : null,
  );
  const provider = new ChatViewProvider(context.extensionUri, server, context, output);
  context.subscriptions.push(
    server,
    provider,
    vscode.workspace.registerTextDocumentContentProvider(DIFF_SCHEME, new DiffContentProvider(() => provider.ledger)),
  );

  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider("zettcode.chat", provider, {
      webviewOptions: { retainContextWhenHidden: true },
    }),
  );

  const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  status.name = "ZettCode";
  status.command = "zettcode.openChat";
  status.text = "$(comment-discussion) ZettCode";
  status.tooltip = "ZettCode: open the chat";
  status.show();
  context.subscriptions.push(status);

  server.onDidChange((state) => {
    switch (state.status) {
      case "ready":
        status.text = "$(sparkle) ZettCode";
        break;
      case "starting":
        status.text = "$(loading~spin) ZettCode";
        break;
      case "error":
        status.text = "$(warning) ZettCode";
        break;
      default:
        status.text = "$(comment-discussion) ZettCode";
        break;
    }
    status.tooltip = `ZettCode: ${state.message}`;
  });

  const command = (name: string, run: () => Promise<unknown> | unknown): vscode.Disposable =>
    vscode.commands.registerCommand(name, async () => {
      try {
        await run();
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        output.appendLine(`[error] ${name}: ${message}`);
        void vscode.window.showErrorMessage(`ZettCode: ${message}`);
      }
    });

  context.subscriptions.push(
    command("zettcode.openChat", async () => {
      await vscode.commands.executeCommand("workbench.view.extension.zettcode");
      await vscode.commands.executeCommand("zettcode.chat.focus").then(undefined, () => undefined);
    }),
    command("zettcode.newSession", () => provider.newSession()),
    command("zettcode.resumeSession", () => provider.showSessions()),
    command("zettcode.selectModel", () => provider.selectModel()),
    command("zettcode.addModel", () => provider.addModelInteractive()),
    command("zettcode.editModel", () => provider.editModelInteractive()),
    command("zettcode.selectEffort", () => provider.selectEffort()),
    command("zettcode.selectPermission", () => provider.selectPermission()),
    command("zettcode.toggleHarness", () => provider.toggleHarness()),
    command("zettcode.compact", () => provider.compactSession()),
    command("zettcode.forkSession", () => provider.forkSession()),
    command("zettcode.renameSession", () => provider.renameSession()),
    command("zettcode.exportSession", () => provider.exportSession()),
    command("zettcode.stop", () => provider.stop()),
    command("zettcode.find", () => provider.find()),
    command("zettcode.usage", () => provider.showUsage()),
    command("zettcode.doctor", () => provider.showDoctor()),
    command("zettcode.plugins", () => provider.showPlugins()),
    command("zettcode.restartServer", async () => {
      output.appendLine("[server] restart requested");
      await server?.restart();
      await provider.refreshAll();
      void vscode.window.showInformationMessage("ZettCode server restarted.");
    }),
    command("zettcode.showLog", () => {
      output.show(true);
    }),
    command("zettcode.openSettings", () =>
      vscode.commands.executeCommand("workbench.action.openSettings", "zettcode"),
    ),
  );

  output.appendLine(`[extension] activated in ${workspace || "(no folder)"}`);
}

export async function deactivate(): Promise<void> {
  if (server !== null) {
    await server.shutdown();
    server = null;
  }
}
