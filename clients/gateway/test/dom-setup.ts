// Imported first by a test that needs a browser: DOMPurify reads `window` when it is loaded.
import { JSDOM } from "jsdom";

const dom = new JSDOM("");
Object.assign(globalThis, { window: dom.window, document: dom.window.document });
