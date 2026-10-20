/**
 * Diagrams written as ```` ```mermaid ```` fences. The text is turned into a drawing by an engine that only exists in
 * the webview (it measures text in a real page), so this module is the part that can be tested without one: what has
 * been drawn is remembered by its source, the markdown renderer asks for it synchronously, and whatever is not drawn
 * yet is asked of the engine once, however often the answer around it is rendered again while it streams.
 */

/** Turns diagram source into an SVG document, for the page's current theme. Rejects with the engine's own message. */
export type DiagramEngine = (source: string, theme: DiagramTheme) => Promise<string>;

export type DiagramTheme = "dark" | "light";

/** What is known of a diagram: its drawing, or why it could not be drawn. */
export type Drawn = { ok: true; svg: string } | { ok: false; message: string };

/** Diagrams kept; an answer that streams asks for the same one many times, a long day for many different ones. */
const MAX_KEPT = 120;

const kept = new Map<string, Drawn>();
const asked = new Map<string, Promise<void>>();
let engine: DiagramEngine | null = null;
let listeners: (() => void)[] = [];

/** Install the engine; the webview does it once, a test with a stand-in. `null` removes it. */
export function setDiagramEngine(next: DiagramEngine | null): void {
  engine = next;
}

/** Forget everything drawn (a test, or a change of theme that makes every drawing wrong). */
export function clearDiagrams(): void {
  kept.clear();
  asked.clear();
}

/** The page's theme as the editor sets it on the body; a page with no body (a test) is dark. */
export function currentTheme(): DiagramTheme {
  const body = (globalThis as { document?: { body?: { classList?: { contains(name: string): boolean } } } }).document?.body;
  return body?.classList?.contains("vscode-light") || body?.classList?.contains("vscode-high-contrast-light") ? "light" : "dark";
}

function keyOf(source: string, theme: DiagramTheme): string {
  return `${theme}\n${source.trim()}`;
}

/** What is already known of a diagram, or `undefined` when it has not been drawn (or refused) yet. */
export function drawnFor(source: string, theme: DiagramTheme): Drawn | undefined {
  return kept.get(keyOf(source, theme));
}

/** Call `listener` whenever a diagram finishes, so a view that showed its source can show the drawing. */
export function onDiagramDrawn(listener: () => void): () => void {
  listeners.push(listener);
  return () => {
    listeners = listeners.filter((item) => item !== listener);
  };
}

/** Draw a diagram unless it is drawn or being drawn; resolves when its outcome is known. Never rejects. */
export function ensureDrawn(source: string, theme: DiagramTheme): Promise<void> {
  const key = keyOf(source, theme);
  if (kept.has(key)) {
    return Promise.resolve();
  }
  const running = asked.get(key);
  if (running !== undefined) {
    return running;
  }
  const work = (async (): Promise<void> => {
    let outcome: Drawn;
    try {
      if (engine === null) {
        throw new Error("The diagram engine is not available.");
      }
      outcome = { ok: true, svg: await engine(source.trim(), theme) };
    } catch (error) {
      outcome = { ok: false, message: error instanceof Error ? error.message : String(error) };
    }
    if (kept.size >= MAX_KEPT) {
      const oldest = kept.keys().next().value;
      if (oldest !== undefined) {
        kept.delete(oldest);
      }
    }
    kept.set(key, outcome);
    asked.delete(key);
    for (const listener of [...listeners]) {
      listener();
    }
  })();
  asked.set(key, work);
  return work;
}

/** The first line of an engine's complaint: the rest is a stack of the engine's own, of no use to a reader. */
export function briefly(message: string): string {
  const line = message.split("\n").find((part) => part.trim() !== "") ?? message;
  return line.trim().slice(0, 240);
}
