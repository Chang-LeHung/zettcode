<script setup lang="ts">
import { computed, ref } from "vue";

import { formatTokens, relativeTime, sessionLabel } from "../../core/format.js";
import { closeOverlay, openOverlay, post, state } from "../store.js";
import Icon from "./Icon.vue";

const query = ref("");
const ui = computed(() => state.ui);

const rows = computed(() => {
  const needle = query.value.trim().toLowerCase();
  return (ui.value?.sessions ?? []).filter(
    (session) =>
      !needle || sessionLabel(session.title).toLowerCase().includes(needle) || session.id.toLowerCase().includes(needle),
  );
});

const selfCompaction = computed(() => {
  const value = ui.value?.selfCompaction ?? null;
  if (value === null) {
    return "unknown";
  }
  if (value.choice === null) {
    return `inherited (${value.effective ? "on" : "off"})`;
  }
  return value.choice ? "on" : "off";
});

function nextSelfCompaction(): boolean | null {
  const current = ui.value?.selfCompaction?.choice ?? null;
  return current === null ? true : current ? false : null;
}

function act(run: () => void): void {
  run();
  closeOverlay();
}

function open(id: string): void {
  post({ type: "open-session", id });
  closeOverlay();
}

function meta(session: {
  updatedAt: string | null;
  title: string | null;
  id: string;
  entries: number;
  tokens: number;
  running: boolean;
}): string {
  return [
    session.running ? "running" : null,
    relativeTime(session.updatedAt),
    session.title ? null : `#${session.id.slice(-6)}`,
    `${session.entries} entries`,
    `${formatTokens(session.tokens)} tokens`,
  ]
    .filter(Boolean)
    .join(" · ");
}
</script>

<template>
  <aside id="drawer" class="drawer" aria-label="Sessions">
    <div class="drawer-head">
      <div class="drawer-title">
        <strong>Sessions</strong>
        <span>{{ ui?.sessions.length ?? 0 }} in this workspace</span>
      </div>
      <button class="icon-btn" type="button" title="New session" aria-label="New session" @click="act(() => post({ type: 'new-session' }))">
        <Icon name="plus" />
      </button>
      <button class="icon-btn" type="button" title="Close" aria-label="Close" @click="closeOverlay">
        <Icon name="x" />
      </button>
    </div>

    <label class="search">
      <Icon name="search" :size="13" />
      <input id="session-search" v-model="query" placeholder="Search sessions" aria-label="Search sessions" />
    </label>

    <div id="session-list" class="session-list">
      <div v-if="state.sessionsLoading && !rows.length" class="empty"><span class="spinner" /> Loading sessions…</div>
      <div v-else-if="!rows.length" class="empty">{{ query ? "No session matches that search." : "No stored sessions yet." }}</div>
      <button
        v-for="session in rows"
        :key="session.id"
        type="button"
        class="session-row"
        :class="{ current: session.current }"
        :data-session-id="session.id"
        @click="open(session.id)"
      >
        <span class="session-title">
          <span class="session-name">{{ sessionLabel(session.title) }}</span>
          <span v-if="session.running" class="spinner session-running" role="status" title="Running" aria-label="Running" />
          <span v-if="session.current" class="dot current-dot" title="Current" />
        </span>
        <span class="session-meta">{{ meta(session) }}</span>
      </button>
    </div>

    <div class="menu-list">
      <button type="button" data-action="rename-session" @click="act(() => (state.renaming = true))"><Icon name="pencil" />Rename</button>
      <button type="button" data-action="name-session" @click="act(() => post({ type: 'name-session' }))"><Icon name="sparkle" />Name with AI</button>
      <button type="button" data-action="fork-session" @click="act(() => post({ type: 'fork-session' }))"><Icon name="fork" />Fork</button>
      <button type="button" data-action="compact" @click="act(() => post({ type: 'compact' }))"><Icon name="fold" />Compact</button>
      <button type="button" data-action="export" @click="act(() => post({ type: 'export' }))"><Icon name="export" />Export</button>
      <button type="button" data-action="context" @click.stop="openOverlay('context')"><Icon name="pulse" />Context</button>
      <button id="self-compaction-button" type="button" data-action="toggle-self-compaction" @click="post({ type: 'set-self-compaction', choice: nextSelfCompaction() })">
        <Icon name="refresh" />Self-compaction<span class="trail">{{ selfCompaction }}</span>
      </button>
    </div>

    <div class="drawer-foot">
      <button type="button" data-action="usage" @click="post({ type: 'usage' })"><Icon name="chart" :size="13" />Usage</button>
      <button type="button" data-action="doctor" @click="post({ type: 'doctor' })"><Icon name="check" :size="13" />Check models</button>
      <button type="button" data-action="plugins" @click="post({ type: 'plugins' })"><Icon name="plug" :size="13" />Plugins</button>
      <button type="button" data-action="open-settings" @click="post({ type: 'open-settings' })"><Icon name="gear" :size="13" />Settings</button>
    </div>
  </aside>
</template>

<style>
.drawer {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 0;
  z-index: 60;
  display: flex;
  flex-direction: column;
  width: min(340px, 92vw);
  border-right: 1px solid var(--line-strong);
  background: var(--raised);
  box-shadow: var(--shadow);
  animation: slide 0.18s ease-out;
}

@keyframes slide {
  from {
    transform: translateX(-12px);
    opacity: 0;
  }
  to {
    transform: none;
    opacity: 1;
  }
}

.drawer-head {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 10px 8px 6px 14px;
}

.drawer-title {
  flex: 1;
  display: flex;
  flex-direction: column;
  line-height: 1.3;
}

.drawer-title strong {
  font-size: 14px;
}

.drawer-title span {
  color: var(--muted);
  font-size: var(--tiny);
}

.search {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 4px 12px 8px;
  padding: 0 10px;
  height: 30px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-s);
  background: var(--input);
  color: var(--muted);
}

.search:focus-within {
  border-color: color-mix(in srgb, var(--fg) 40%, transparent);
}

.search input {
  flex: 1;
  min-width: 0;
  border: 0;
  outline: none;
  background: none;
  font-size: var(--small);
}

.session-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 0 8px;
}

.session-row {
  display: flex;
  flex-direction: column;
  gap: 1px;
  width: 100%;
  padding: 7px 9px;
  border: 0;
  border-radius: var(--r-s);
  background: none;
  text-align: left;
}

.session-row:hover {
  background: var(--wash-2);
}

.session-row.current {
  background: var(--wash);
}

.session-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.session-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13.5px;
  font-weight: 550;
}

.current-dot {
  background: var(--accent);
}

.session-meta {
  color: var(--muted);
  font-size: 11.5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 26px 12px;
  color: var(--muted);
  font-size: var(--small);
}

.menu-list {
  padding: 6px 8px;
  border-top: 1px solid var(--line);
}

.menu-list button {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 6px 9px;
  border: 0;
  border-radius: var(--r-s);
  background: none;
  font-size: 13px;
  text-align: left;
}

.menu-list button:hover {
  background: var(--wash-2);
}

.menu-list .icon {
  color: var(--muted);
}

.menu-list .trail {
  margin-left: auto;
  color: var(--faint);
  font-size: var(--tiny);
}

.drawer-foot {
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
  padding: 6px 8px 10px;
  border-top: 1px solid var(--line);
}

.drawer-foot button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 9px;
  border: 0;
  border-radius: var(--r-s);
  background: none;
  color: var(--muted);
  font-size: var(--small);
}

.drawer-foot button:hover {
  background: var(--wash-2);
  color: var(--fg);
}
</style>
