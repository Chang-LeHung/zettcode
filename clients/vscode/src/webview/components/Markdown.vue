<script setup lang="ts">
import { computed } from "vue";

import { renderMarkdown, renderStreaming } from "../../core/markdown.js";
import { post } from "../store.js";

const props = defineProps<{ text: string; live?: boolean }>();

const html = computed(
  () => (props.live ? renderStreaming(props.text) : renderMarkdown(props.text)) + (props.live ? '<span class="caret"></span>' : ""),
);

/** Links and copy buttons in rendered Markdown carry data attributes; one handler serves them all. */
function onClick(event: MouseEvent): void {
  const target = event.target as HTMLElement | null;
  if (target === null) {
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
  }
}
</script>

<template>
  <div class="md" @click="onClick" v-html="html" />
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
</style>
