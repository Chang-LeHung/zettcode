<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";

import { formatDuration, formatTokens, sessionLabel } from "../../core/format.js";
import { openOverlay, post, state, toggleAllTurns } from "../store.js";
import Icon from "./Icon.vue";
import Logo from "./Logo.vue";

const session = computed(() => state.ui?.session ?? null);
const title = computed(() => (session.value === null ? "ZettCode" : sessionLabel(session.value.title)));
const sub = computed(() => {
  const current = session.value;
  if (current === null) {
    return "New session";
  }
  const parts: string[] = [];
  if (current.locked) {
    parts.push("Locked by another process");
  }
  const usage = current.usage;
  if (usage.requests > 0) {
    parts.push(`${formatTokens(usage.input_tokens + usage.output_tokens)} tokens`);
    parts.push(`${formatTokens(usage.requests)} request${usage.requests === 1 ? "" : "s"}`);
    if (usage.seconds > 0) {
      parts.push(formatDuration(Math.round(usage.seconds * 1000)));
    }
  }
  return parts.length ? parts.join(" · ") : "This workspace";
});
const foldable = computed(() => state.turns.filter((turn) => !turn.aside).length >= 2);
const allFolded = computed(() => {
  const turns = state.turns.filter((turn) => !turn.aside);
  return turns.length > 0 && turns.every((turn) => state.collapsed.has(turn.id));
});

const field = ref<HTMLInputElement | null>(null);
const draft = ref("");

watch(
  () => state.renaming,
  async (on) => {
    if (!on) {
      return;
    }
    draft.value = session.value?.title ?? "";
    await nextTick();
    field.value?.focus();
    field.value?.select();
  },
);

function commit(): void {
  if (!state.renaming) {
    return;
  }
  state.renaming = false;
  const value = draft.value.trim();
  if (value && value !== (session.value?.title ?? "")) {
    post({ type: "rename-session", title: value });
  }
}

function cancel(): void {
  state.renaming = false;
}
</script>

<template>
  <header class="topbar">
    <div v-if="state.renaming" class="who editing">
      <Logo :size="20" />
      <input
        ref="field"
        v-model="draft"
        class="session-rename"
        placeholder="Session name"
        aria-label="Session name"
        @keydown.enter.prevent="commit"
        @keydown.esc.stop.prevent="cancel"
        @blur="commit"
      />
    </div>
    <button
      v-else
      id="session-button"
      class="who"
      type="button"
      :title="session ? `${session.id}\n${title}` : 'Recent sessions'"
      @click="openOverlay(state.overlay === 'drawer' ? null : 'drawer')"
    >
      <Logo :size="20" />
      <span class="who-copy">
        <span id="session-name" class="who-title" @dblclick.stop="state.renaming = true">{{ title }}</span>
        <span id="session-sub" class="who-sub">{{ sub }}</span>
      </span>
      <Icon name="down" :size="12" class="who-caret" />
    </button>
    <div class="actions">
      <button
        v-if="session"
        id="rename-button"
        class="icon-btn"
        type="button"
        title="Rename this session (/rename)"
        aria-label="Rename this session"
        :disabled="state.ui?.busy === true"
        @click="state.renaming = true"
      >
        <Icon name="pencil" :size="13" />
      </button>
      <button
        v-if="foldable"
        id="collapse-button"
        class="icon-btn"
        type="button"
        :title="allFolded ? 'Expand every request' : 'Collapse every request'"
        :aria-label="allFolded ? 'Expand every request' : 'Collapse every request'"
        @click="toggleAllTurns"
      >
        <Icon :name="allFolded ? 'unfold' : 'fold'" />
      </button>
      <button
        id="history-button"
        class="icon-btn"
        type="button"
        title="Recent sessions (/resume)"
        aria-label="Recent sessions"
        @click="openOverlay(state.overlay === 'drawer' ? null : 'drawer')"
      >
        <Icon name="history" />
      </button>
      <button
        id="new-button"
        class="icon-btn"
        type="button"
        title="New session (/new)"
        aria-label="New session"
        :disabled="state.ui?.busy === true"
        @click="post({ type: 'new-session' })"
      >
        <Icon name="plus" />
      </button>
    </div>
  </header>
</template>

<style>
.topbar {
  display: flex;
  align-items: center;
  gap: 4px;
  height: 48px;
  padding: 0 8px 0 10px;
  border-bottom: 1px solid var(--line);
  flex-shrink: 0;
}

.who {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 4px 8px 4px 6px;
  margin: 0;
  border: 0;
  border-radius: 8px;
  background: none;
  text-align: left;
}

button.who:hover {
  background: var(--wash);
}

.who.editing {
  padding-right: 4px;
}

.who-copy {
  display: flex;
  flex-direction: column;
  min-width: 0;
  line-height: 1.25;
}

.who-title {
  font-size: 13.5px;
  font-weight: 620;
  letter-spacing: -0.005em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.who-sub {
  color: var(--muted);
  font-size: 11.5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.who-caret {
  margin-left: auto;
  color: var(--faint);
}

.session-rename {
  flex: 1;
  min-width: 0;
  height: 28px;
  padding: 0 9px;
  border: 1px solid color-mix(in srgb, var(--blue) 60%, transparent);
  border-radius: 7px;
  background: var(--input);
  font-size: 13.5px;
  font-weight: 600;
  outline: none;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--blue) 18%, transparent);
}

.actions {
  display: flex;
  align-items: center;
  gap: 1px;
  flex-shrink: 0;
}
</style>
