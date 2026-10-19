<script setup lang="ts">
import { computed } from "vue";

import type { ChangeSummary } from "../../core/ledger.js";
import { post, state, toggleIn } from "../store.js";
import DiffView from "./DiffView.vue";
import Icon from "./Icon.vue";

const props = defineProps<{ turnId: string }>();

const files = computed<ChangeSummary[]>(() => state.changes[props.turnId] ?? []);
const added = computed(() => files.value.reduce((sum, file) => sum + file.added, 0));
const removed = computed(() => files.value.reduce((sum, file) => sum + file.removed, 0));
const folded = computed(() => state.openFiles.has(`${props.turnId}::*`));

function key(path: string): string {
  return `${props.turnId}::${path}`;
}

function split(path: string): { dir: string; name: string } {
  const at = path.lastIndexOf("/");
  return at < 0 ? { dir: "", name: path } : { dir: path.slice(0, at + 1), name: path.slice(at + 1) };
}

function toggleFile(path: string): void {
  const id = key(path);
  toggleIn(state.openFiles, id);
  if (state.openFiles.has(id) && state.diffs[id] === undefined) {
    post({ type: "view-diff", turnId: props.turnId, path });
  }
}
</script>

<template>
  <div v-if="files.length" class="changes" :data-changes="turnId">
    <div class="changes-head">
      <button class="changes-title" type="button" @click="toggleIn(state.openFiles, `${turnId}::*`)">
        <Icon :name="folded ? 'right' : 'down'" :size="12" />
        <span>{{ files.length }} file{{ files.length === 1 ? "" : "s" }} changed</span>
        <span class="plus">+{{ added }}</span>
        <span class="minus">−{{ removed }}</span>
      </button>
      <button
        class="btn ghost small"
        type="button"
        title="Open the first file's diff in the editor"
        @click="post({ type: 'open-diff', turnId, path: files[0]!.path })"
      >
        <Icon name="diff" :size="12" />Review
      </button>
    </div>
    <ul v-if="!folded" class="changes-list">
      <li v-for="file in files" :key="file.path" class="change" :class="file.status">
        <div class="change-row">
          <button class="change-main" type="button" :aria-expanded="state.openFiles.has(key(file.path))" @click="toggleFile(file.path)">
            <span class="change-tag" :title="file.status">{{ file.status === "added" ? "A" : file.status === "deleted" ? "D" : "M" }}</span>
            <span class="change-path"
              ><span class="dir">{{ split(file.path).dir }}</span
              >{{ split(file.path).name }}</span
            >
            <span class="plus">+{{ file.added }}</span>
            <span class="minus">−{{ file.removed }}</span>
          </button>
          <button
            class="icon-btn change-open"
            type="button"
            title="Open the diff in the editor"
            aria-label="Open the diff in the editor"
            @click="post({ type: 'open-diff', turnId, path: file.path })"
          >
            <Icon name="diff" :size="13" />
          </button>
        </div>
        <DiffView
          v-if="state.openFiles.has(key(file.path)) && state.diffs[key(file.path)]"
          :rows="state.diffs[key(file.path)]!.rows"
          :truncated="state.diffs[key(file.path)]!.truncated"
        />
      </li>
    </ul>
  </div>
</template>

<style>
.changes {
  margin-top: 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-m);
  overflow: hidden;
}

.changes-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 3px 6px 3px 4px;
  background: var(--wash);
}

.changes-title {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 8px;
  border: 0;
  border-radius: 6px;
  background: none;
  font-size: var(--small);
  font-weight: 600;
}

.changes-title .icon {
  color: var(--faint);
}

.plus {
  color: var(--green);
  font-variant-numeric: tabular-nums;
  font-weight: 500;
}

.minus {
  color: var(--red);
  font-variant-numeric: tabular-nums;
  font-weight: 500;
}

.changes-list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.change {
  border-top: 1px solid var(--line);
}

.change-row {
  display: flex;
  align-items: center;
}

.change-main {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 6px 8px 6px 12px;
  border: 0;
  background: none;
  font-size: 12.5px;
  text-align: left;
}

.change-main:hover {
  background: var(--wash);
}

.change-tag {
  width: 16px;
  height: 16px;
  display: grid;
  place-items: center;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 700;
  color: var(--amber);
  background: color-mix(in srgb, var(--amber) 15%, transparent);
  flex-shrink: 0;
}

.change.added .change-tag {
  color: var(--green);
  background: color-mix(in srgb, var(--green) 15%, transparent);
}

.change.deleted .change-tag {
  color: var(--red);
  background: color-mix(in srgb, var(--red) 15%, transparent);
}

.change-path {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--mono);
  font-size: calc(var(--code-size) * 0.92);
}

.change-path .dir {
  color: var(--faint);
}

.change-open {
  margin-right: 6px;
  opacity: 0;
}

.change-row:hover .change-open,
.change-open:focus-visible {
  opacity: 1;
}
</style>
