/** The virtual documents behind "view diff": the text a request replaced, served from memory. */

import * as vscode from "vscode";

import type { ChangeLedger } from "./core/ledger.js";

export const DIFF_SCHEME = "zettcode-diff";

/** `zettcode-diff:/<side>/<turn>/<path>`; the editor shows the path's extension, so highlighting follows. */
export function diffUri(side: "before" | "after", turnId: string, path: string): vscode.Uri {
  const clean = path.replace(/\\/g, "/").replace(/^\/+/, "");
  return vscode.Uri.from({ scheme: DIFF_SCHEME, path: `/${side}/${encodeURIComponent(turnId)}/${clean}` });
}

export class DiffContentProvider implements vscode.TextDocumentContentProvider {
  constructor(private readonly ledger: () => ChangeLedger | null) {}

  provideTextDocumentContent(uri: vscode.Uri): string {
    const match = /^\/(before|after)\/([^/]+)\/(.*)$/.exec(uri.path);
    if (match === null) {
      return "";
    }
    const [, side, turn, path] = match;
    const change = this.ledger()?.find(decodeURIComponent(turn ?? ""), path ?? "");
    return (side === "before" ? change?.before : change?.after) ?? "";
  }
}
