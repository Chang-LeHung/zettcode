<script setup lang="ts">
import { computed } from "vue";
import { t } from "../../i18n";
import type { ToolItem } from "../../lib/rows";
import Icon from "../common/Icon.vue";

const props = defineProps<{ tools: ToolItem[] }>();

const last = computed(() => props.tools[props.tools.length - 1]);
const failed = computed(() => props.tools.filter((tool) => tool.ok === false).length);
const summary = computed(() => {
  const count = props.tools.length;
  const head = count === 1 ? (last.value?.name ?? "") : t("{count} steps", { count });
  return failed.value ? `${head} · ${t("{count} failed", { count: failed.value })}` : head;
});
</script>

<template>
  <details class="steps">
    <summary>
      <Icon name="tool" size="xs" />
      <span>{{ summary }}</span>
      <span v-if="tools.length === 1 && last?.brief" class="steps-brief">{{ last.brief }}</span>
    </summary>
    <ol>
      <li v-for="(tool, at) in tools" :key="at">
        <details>
          <summary class="steps-tool">
            <Icon v-if="tool.ok === false" class="steps-fail" name="warn" size="xs" />
            <Icon v-else-if="tool.ok" class="steps-ok" name="check" size="xs" />
            <Icon v-else name="clock" size="xs" />
            <b>{{ tool.name }}</b>
            <code>{{ tool.brief }}</code>
          </summary>
          <pre v-if="tool.output">{{ tool.output }}</pre>
        </details>
      </li>
    </ol>
  </details>
</template>

<style>
.steps { align-self: flex-start; max-width: min(88%, 38rem); margin: 12px 0 0; }
.steps > summary {
  display: inline-flex; align-items: center; gap: 6px; max-width: 100%; padding: 4px 11px 4px 8px; border-radius: 14px;
  background: var(--chip-bg); color: #fff; font-size: 0.8rem; cursor: pointer; list-style: none; user-select: none;
}
.steps summary::-webkit-details-marker { display: none; }
.steps > summary > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.steps-brief { opacity: 0.75; }
.steps[open] > summary { background: rgba(0, 0, 0, 0.4); }
.steps ol { list-style: none; margin: 4px 0 0; padding: 4px; border-radius: 12px; background: var(--in-bubble); color: var(--in-text); box-shadow: var(--shadow); }
.steps li { padding: 5px 8px; font-size: 0.84rem; }
.steps li + li { border-top: 1px solid var(--divider); }
.steps-tool { display: flex; align-items: center; gap: 6px; cursor: pointer; list-style: none; }
.steps-tool b { font-weight: 600; }
.steps-tool code { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--muted); font-family: var(--mono); font-size: 0.9em; }
.steps-ok { color: var(--ok); }
.steps-fail { color: var(--bad); }
.steps pre {
  margin: 6px 0 2px; max-height: 14rem; overflow: auto; padding: 8px; border-radius: 8px; background: var(--code-bg);
  font-family: var(--mono); font-size: 0.78rem; white-space: pre-wrap; word-break: break-word;
}
</style>
