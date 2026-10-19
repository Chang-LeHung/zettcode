<script setup lang="ts">
import type { DiffRow } from "../../core/diff.js";

defineProps<{ rows: DiffRow[]; truncated?: boolean }>();
</script>

<template>
  <div class="diffview" role="table">
    <div v-for="(row, index) in rows" :key="index" class="drow" :class="row.kind" role="row">
      <template v-if="row.kind === 'gap'">
        <span class="gap-text">⋯ {{ row.text }}</span>
      </template>
      <template v-else>
        <span class="ln">{{ row.oldLine ?? "" }}</span>
        <span class="ln">{{ row.newLine ?? "" }}</span>
        <span class="sign">{{ row.kind === "add" ? "+" : row.kind === "del" ? "−" : "" }}</span>
        <span class="code">{{ row.text || " " }}</span>
      </template>
    </div>
    <div v-if="truncated" class="drow gap"><span class="gap-text">⋯ the rest is in the editor's diff</span></div>
  </div>
</template>

<style>
.diffview {
  max-height: 360px;
  overflow: auto;
  border-top: 1px solid var(--line);
  background: color-mix(in srgb, var(--bg) 60%, transparent);
  font-family: var(--mono);
  font-size: var(--code-size);
  line-height: 1.55;
}

.drow {
  display: grid;
  grid-template-columns: 38px 38px 16px minmax(0, 1fr);
  min-width: max-content;
}

.drow.add {
  background: color-mix(in srgb, var(--green) 13%, transparent);
}

.drow.del {
  background: color-mix(in srgb, var(--red) 12%, transparent);
}

.drow .ln {
  padding-right: 8px;
  text-align: right;
  color: var(--faint);
  user-select: none;
  font-size: 11px;
}

.drow .sign {
  text-align: center;
  user-select: none;
}

.drow.add .sign {
  color: var(--green);
}

.drow.del .sign {
  color: var(--red);
}

.drow .code {
  white-space: pre;
  padding-right: 12px;
}

.drow.gap {
  display: block;
  padding: 2px 0 2px 40px;
  color: var(--faint);
  background: var(--wash);
  font-size: 11px;
}
</style>
