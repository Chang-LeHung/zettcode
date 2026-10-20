/** The diagram engine: Mermaid, loaded from its own script the first time an answer holds a diagram. */

import type { DiagramEngine, DiagramTheme } from "../core/diagram.js";

interface MermaidApi {
  initialize(config: Record<string, unknown>): void;
  render(id: string, source: string): Promise<{ svg: string }>;
}

declare global {
  interface Window {
    __zettMermaid?: { default?: MermaidApi } & Partial<MermaidApi>;
  }
}

let loading: Promise<MermaidApi> | null = null;
let configured: DiagramTheme | null = null;
let counter = 0;

/**
 * Mermaid is about three megabytes, so the view does not carry it: a second script, from the same place as the first
 * and with the same nonce (the page allows no other), is added when a diagram is first met.
 */
function load(): Promise<MermaidApi> {
  if (loading !== null) {
    return loading;
  }
  loading = new Promise<MermaidApi>((resolve, reject) => {
    const main = document.querySelector<HTMLScriptElement>("script[src*='webview.js']");
    if (main === null) {
      reject(new Error("The diagram engine cannot be found."));
      return;
    }
    const script = document.createElement("script");
    script.nonce = main.nonce || main.getAttribute("nonce") || "";
    script.src = main.src.replace(/webview\.js(\?.*)?$/, "mermaid.js");
    script.onload = () => {
      const api = window.__zettMermaid?.default ?? window.__zettMermaid;
      if (api && typeof api.render === "function") {
        resolve(api as MermaidApi);
      } else {
        reject(new Error("The diagram engine did not start."));
      }
    };
    script.onerror = () => {
      loading = null;
      reject(new Error("The diagram engine could not be loaded."));
    };
    document.head.appendChild(script);
  });
  return loading;
}

function font(): string {
  return getComputedStyle(document.body).fontFamily || "sans-serif";
}

/** Draw a diagram as SVG in the page's colours. */
export const mermaidEngine: DiagramEngine = async (source, theme) => {
  const mermaid = await load();
  if (configured !== theme) {
    mermaid.initialize({
      startOnLoad: false,
      // Strict: the drawing is put into the page as markup, so the engine must not let a diagram carry script or links.
      securityLevel: "strict",
      theme: theme === "dark" ? "dark" : "default",
      fontFamily: font(),
      themeVariables: { background: "transparent" },
    });
    configured = theme;
  }
  counter += 1;
  const id = `zett-diagram-${counter}`;
  try {
    return (await mermaid.render(id, source)).svg;
  } finally {
    // A diagram that fails leaves its error drawing in the body.
    document.getElementById(id)?.remove();
    document.getElementById(`d${id}`)?.remove();
  }
};
