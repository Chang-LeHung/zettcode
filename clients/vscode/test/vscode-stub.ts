/** The smallest editor surface `usage.ts` touches, for rendering its page outside VS Code. */

export interface StubWebview {
  html: string;
  cspSource: string;
  asWebviewUri(value: unknown): { toString(): string };
}

export interface StubPanel {
  title: string;
  webview: StubWebview;
  onDidDispose(listener: () => void): void;
  reveal(): void;
}

export let lastPanel: StubPanel | null = null;

export const ViewColumn = { Active: 1 };

export const Uri = {
  joinPath(base: unknown, ...parts: string[]): { toString(): string } {
    const root = typeof base === "string" ? base : "vscode-resource";
    return { toString: () => [root, ...parts].join("/") };
  },
};

export const window = {
  createWebviewPanel(_id: string, title: string): StubPanel {
    const panel: StubPanel = {
      title,
      webview: {
        html: "",
        cspSource: "https://localhost",
        asWebviewUri(value: unknown) {
          return {
            toString: () =>
              typeof value === "object" && value !== null && "toString" in value
                ? String(value)
                : String(value),
          };
        },
      },
      onDidDispose() {
        // The page is rendered before a panel can be closed.
      },
      reveal() {
        // Nothing to reveal outside the editor.
      },
    };
    lastPanel = panel;
    return panel;
  },
};
