/** Loaded as a script of its own, on demand: it hands Mermaid to the view without the view having to carry it. */

import mermaid from "mermaid";

(window as unknown as { __zettMermaid: unknown }).__zettMermaid = mermaid;
