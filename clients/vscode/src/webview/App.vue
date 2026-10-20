<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from "vue";

import { addFiles } from "./images.js";
import { closeOverlay, openFind, state } from "./store.js";
import Banner from "./components/Banner.vue";
import Composer from "./components/Composer.vue";
import Lightbox from "./components/Lightbox.vue";
import SessionDrawer from "./components/SessionDrawer.vue";
import Splash from "./components/Splash.vue";
import Toasts from "./components/Toasts.vue";
import TopBar from "./components/TopBar.vue";
import Transcript from "./components/Transcript.vue";

let depth = 0;

/**
 * Until the first load finishes nothing is known about the server, the models or the session, so only the mark
 * shows. A server that failed to start is known, and says so instead of waiting.
 */
const booting = computed(() => state.ui === null || (!state.ui.loaded && state.ui.server.status !== "error"));

function hasFiles(event: DragEvent): boolean {
  return event.dataTransfer?.types.includes("Files") === true;
}

function onKeydown(event: KeyboardEvent): void {
  // Ctrl+F (Cmd+F on a Mac) searches the conversation. The webview has no find box of the editor's, so it has its own.
  if ((event.ctrlKey || event.metaKey) && !event.shiftKey && !event.altKey && event.key.toLowerCase() === "f") {
    event.preventDefault();
    openFind(window.getSelection()?.toString() ?? "");
    return;
  }
  if (event.key === "Escape" && state.overlay !== null) {
    closeOverlay();
  }
}

/**
 * A click outside an open menu puts it away. This runs before the click reaches its target, so a control that opens
 * another menu is not undone by the same click, and the controls that own a menu toggle it themselves.
 */
function onClick(event: MouseEvent): void {
  const target = event.target as HTMLElement | null;
  const menus = ["context", "models", "effort", "permission", "add-model"];
  if (state.overlay !== null && menus.includes(state.overlay) && target !== null && !target.closest(".dropdown, .chip, .ctx")) {
    closeOverlay();
  }
}

function onPaste(event: ClipboardEvent): void {
  const files = Array.from(event.clipboardData?.files ?? []).filter((file) => file.type.startsWith("image/"));
  if (files.length) {
    event.preventDefault();
    void addFiles(files);
  }
}

function onDragEnter(event: DragEvent): void {
  if (hasFiles(event)) {
    depth += 1;
    state.dragging = true;
  }
}

function onDragLeave(): void {
  depth = Math.max(0, depth - 1);
  if (depth === 0) {
    state.dragging = false;
  }
}

function onDragOver(event: DragEvent): void {
  if (hasFiles(event)) {
    event.preventDefault();
  }
}

function onDrop(event: DragEvent): void {
  if (!hasFiles(event)) {
    return;
  }
  event.preventDefault();
  depth = 0;
  state.dragging = false;
  void addFiles(event.dataTransfer?.files);
}

const listeners: [string, EventListener, boolean][] = [
  ["keydown", onKeydown as EventListener, false],
  ["click", onClick as EventListener, true],
  ["paste", onPaste as EventListener, false],
  ["dragenter", onDragEnter as EventListener, false],
  ["dragleave", onDragLeave as EventListener, false],
  ["dragover", onDragOver as EventListener, false],
  ["drop", onDrop as EventListener, false],
];

onMounted(() => listeners.forEach(([name, handler, capture]) => document.addEventListener(name, handler, capture)));
onBeforeUnmount(() => listeners.forEach(([name, handler, capture]) => document.removeEventListener(name, handler, capture)));
</script>

<template>
  <div class="app" :class="{ dropping: state.dragging }">
    <Splash v-if="booting" />
    <template v-else>
      <TopBar />
      <Banner />
      <Transcript />
      <Composer />
    </template>

    <div v-if="state.overlay === 'drawer'" id="scrim" class="scrim" @click="closeOverlay" />
    <SessionDrawer v-if="state.overlay === 'drawer'" />
    <Toasts />
    <Lightbox />
    <div v-if="state.dragging" class="drop-hint">Drop a picture to attach it</div>
  </div>
</template>

<style>
.app {
  position: relative;
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
}

.scrim {
  position: absolute;
  inset: 0;
  z-index: 55;
  background: rgba(0, 0, 0, 0.38);
  animation: fade 0.14s ease-out;
}

.app.dropping::after {
  content: "";
  position: absolute;
  inset: 8px;
  z-index: 80;
  border: 1.5px dashed color-mix(in srgb, var(--blue) 70%, transparent);
  border-radius: var(--r-l);
  background: color-mix(in srgb, var(--blue) 6%, transparent);
  pointer-events: none;
}

.drop-hint {
  position: absolute;
  top: 50%;
  left: 50%;
  z-index: 81;
  transform: translate(-50%, -50%);
  padding: 8px 16px;
  border-radius: 999px;
  background: var(--raised);
  box-shadow: var(--shadow);
  font-size: var(--small);
  pointer-events: none;
}
</style>
