<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, onUpdated, ref } from "vue";

import { currentTheme, ensureDrawn, onDiagramDrawn } from "../../core/diagram.js";
import { renderMarkdown, renderStreaming } from "../../core/markdown.js";
import { openLightbox, post } from "../store.js";

const props = defineProps<{ text: string; live?: boolean }>();
const root = ref<HTMLElement | null>(null);
/** Bumped when a diagram finishes, so the answer is rendered again with the drawing in place of its code. */
const drawn = ref(0);

const html = computed(() => {
  void drawn.value;
  return (props.live ? renderStreaming(props.text) : renderMarkdown(props.text)) + (props.live ? '<span class="caret"></span>' : "");
});

/** Ask for the drawing of every diagram the answer holds that has not been drawn yet. */
function drawPending(): void {
  for (const block of root.value?.querySelectorAll<HTMLElement>(".diagram-pending[data-diagram]") ?? []) {
    const source = block.dataset.diagram;
    if (source) {
      void ensureDrawn(source, currentTheme());
    }
  }
}

let stop: (() => void) | null = null;
onMounted(() => {
  stop = onDiagramDrawn(() => {
    drawn.value += 1;
  });
  drawPending();
});
onUpdated(drawPending);
onBeforeUnmount(() => stop?.());

/**
 * Open a block of the answer larger: a drawing (zoomable), or a code block or table as it is, without the room the
 * column leaves it. The buttons are not carried over, because the copy of the block would not be wired to anything.
 */
function expand(from: Element): void {
  const block = from.closest<HTMLElement>(".code-block, .table-box");
  if (block === null) {
    return;
  }
  const drawing = block.classList.contains("diagram") ? block.querySelector(".diagram-body svg") : null;
  if (drawing !== null) {
    openLightbox({ kind: "drawing", html: drawing.outerHTML, title: "Mermaid diagram" });
    return;
  }
  const copy = (block.classList.contains("table-box") ? block.querySelector(".table-wrap") : block)?.cloneNode(true);
  if (!(copy instanceof HTMLElement)) {
    return;
  }
  copy.querySelectorAll(".code-actions, .diagram-note").forEach((node) => node.remove());
  const title = block.classList.contains("table-box") ? "Table" : (block.querySelector(".code-lang span")?.textContent ?? "Code");
  openLightbox({ kind: "block", html: copy.outerHTML, title });
}

/** Links and copy buttons in rendered Markdown carry data attributes; one handler serves them all. */
function onClick(event: MouseEvent): void {
  const target = event.target as HTMLElement | null;
  if (target === null) {
    return;
  }
  const bigger = target.closest("[data-expand]") ?? target.closest(".diagram-body");
  if (bigger !== null) {
    event.preventDefault();
    expand(bigger);
    return;
  }
  const open = target.closest<HTMLElement>("[data-open]");
  if (open?.dataset.open) {
    event.preventDefault();
    post({ type: "open", target: open.dataset.open });
    return;
  }
  const external = target.closest<HTMLElement>("[data-external]");
  if (external?.dataset.external) {
    event.preventDefault();
    post({ type: "open-external", url: external.dataset.external });
    return;
  }
  const copy = target.closest<HTMLElement>("[data-copy]");
  if (copy) {
    const code = copy.closest(".code-block")?.querySelector("code")?.textContent ?? "";
    post({ type: "copy", text: code });
    // The code is on the clipboard: say so on the button that was pressed (a check and a small "Copied" above it),
    // not in a toast somewhere else.
    copy.classList.add("done");
    window.setTimeout(() => copy.classList.remove("done"), 1600);
    return;
  }
  const wrap = target.closest<HTMLElement>("[data-wrap]");
  if (wrap) {
    const on = wrap.closest(".code-block")?.classList.toggle("wrap") ?? false;
    wrap.classList.toggle("on", on);
    return;
  }
  const source = target.closest<HTMLElement>("[data-source]");
  if (source) {
    // A drawing and its code are two faces of one block.
    const block = source.closest(".code-block");
    const showing = block?.classList.toggle("show-source") ?? false;
    source.classList.toggle("on", showing);
    block?.querySelector(".diagram-source")?.toggleAttribute("hidden", !showing);
  }
}
</script>

<template>
  <div ref="root" class="md" @click="onClick" v-html="html" />
</template>

<style>
.caret {
  display: inline-block;
  width: 7px;
  height: 1.05em;
  margin-left: 2px;
  vertical-align: text-bottom;
  border-radius: 1.5px;
  background: var(--fg);
  opacity: 0.7;
  animation: blink 1s steps(1) infinite;
}

@keyframes blink {
  50% {
    opacity: 0;
  }
}

/* A code block: one soft panel, the language and two small actions on top, no border and no rule under the header. */
.md .code-block {
  --block: color-mix(in srgb, var(--bg) 80%, #000);
  margin: 0.3em 0 1em;
  border: 0;
  border-radius: var(--r-l);
  background: var(--block);
  overflow: visible;
}

body.vscode-light .md .code-block {
  --block: color-mix(in srgb, var(--bg) 94%, #000);
}

.md .code-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 9px 10px 0 16px;
  border: 0;
  color: var(--muted);
  font-size: var(--small);
  letter-spacing: 0;
  text-transform: none;
}

.md .code-lang {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.md .code-actions {
  display: inline-flex;
  gap: 2px;
}

.md .code-btn {
  position: relative;
  display: inline-grid;
  place-items: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--muted);
  transition:
    background 0.12s,
    color 0.12s;
}

.md .code-btn:hover,
.md .code-btn.on {
  background: var(--wash-2);
  color: var(--fg);
}

/* Copy shows a copy glyph, and a check for a moment once the code is on the clipboard. */
.md .code-btn .i[data-icon="check"],
.md .code-btn.done .i[data-icon="copy"] {
  display: none;
}

.md .code-btn.done .i[data-icon="check"] {
  display: block;
}

.md .code-btn.done {
  color: var(--accent);
  background: var(--wash-2);
}

.md .code-btn.done::after {
  content: "Copied";
  position: absolute;
  bottom: calc(100% + 6px);
  right: 0;
  padding: 4px 10px;
  border: 1px solid var(--line-strong);
  border-radius: 8px;
  background: var(--raised);
  box-shadow: var(--shadow);
  color: var(--fg);
  font-size: var(--small);
  white-space: nowrap;
  pointer-events: none;
  z-index: 5;
}

.md pre {
  padding: 10px 16px 16px;
  border-radius: 0 0 var(--r-l) var(--r-l);
}

.md .code-block.wrap pre,
.md .code-block.wrap pre code {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

/* A drawn diagram: the drawing is the block, the code one press behind it. */
.md .diagram-body {
  padding: 14px 16px 16px;
  overflow-x: auto;
  text-align: center;
  cursor: zoom-in;
}

/* The table's own button for opening it larger: beside the table, shown when it is pointed at. */
.md .table-box {
  position: relative;
}

.md .table-expand {
  position: absolute;
  top: 6px;
  right: 6px;
  z-index: 2;
  opacity: 0;
  background: var(--raised);
  transition: opacity 0.12s;
}

.md .table-box:hover .table-expand,
.md .table-expand:focus-visible {
  opacity: 1;
}

.md .diagram-body svg {
  display: inline-block;
  max-width: 100%;
  height: auto;
}

.md .code-block.show-source .diagram-body {
  display: none;
}

.md .diagram-source {
  margin: 0;
}

.md .diagram-source[hidden] {
  display: none;
}

.md .diagram-note {
  padding: 8px 16px 0;
  color: var(--amber);
  font-size: var(--small);
}
</style>
