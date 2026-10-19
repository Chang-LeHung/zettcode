<script setup lang="ts">
import { computed, ref } from "vue";

import { formatTokens } from "../../core/format.js";
import { contextPercent, contextRows, formatPercent } from "../context.js";
import { closeOverlay, post, state } from "../store.js";
import Donut from "./Donut.vue";
import CompactionSlider from "./CompactionSlider.vue";
import Popover from "./Popover.vue";

const report = computed(() => state.ui?.context ?? null);
const percent = computed(() => (report.value ? contextPercent(report.value) : 0));
const composition = computed(() => (report.value ? contextRows(report.value) : null));
const active = ref<number | null>(null);

const source = computed(() => {
  const current = report.value;
  if (current === null) {
    return "";
  }
  const bits = [current.from_provider ? "Counted by the provider" : `Estimated by ${current.measured_by}`];
  if (current.partial) {
    bits.push("partial");
  }
  const usage = state.ui?.session?.usage;
  if (usage && usage.requests > 0) {
    bits.push(`${formatTokens(usage.input_tokens + usage.output_tokens)} tokens this session`);
  }
  return bits.join(" · ");
});
</script>

<template>
  <Popover id="context-popover" align="right" :width="390">
    <template v-if="report && composition">
      <div class="pop-head">
        <div>
          <h2>Context composition</h2>
          <div class="pop-sub">
            Latest model context <span class="pill">{{ formatPercent(percent) }}% used</span>
          </div>
        </div>
        <div class="pop-total">
          <strong>{{ formatTokens(report.used) }}</strong> / {{ formatTokens(report.window) }}
        </div>
      </div>

      <div class="pop-body">
        <div class="pop-ring">
          <Donut :result="composition.ring" :size="116" :radius="48" :stroke="10" :active="active" label="Context composition" />
          <div class="pop-ring-center">
            <strong>{{ formatPercent(percent) }}%</strong><span>used</span>
          </div>
        </div>
        <ul class="legend" @pointerleave="active = null">
          <li
            v-for="row in composition.rows"
            :key="row.name"
            class="legend-row"
            :class="{ active: row.slice !== null && active === row.slice, pending: row.pending }"
            :data-share-index="row.slice ?? undefined"
            :title="row.pending ? `${row.name} · counted once a request has been sent` : `${row.name} · ${formatTokens(row.tokens)} tokens · ${row.items} items`"
            @pointerover="active = row.slice ?? null"
          >
            <span class="swatch" :class="row.tone" />
            <span class="legend-name">{{ row.name }}</span>
            <span v-if="row.pending" class="legend-pct pending">pending</span>
            <span v-else class="legend-pct">{{ (row.percent ?? 0).toFixed(1) }}%</span>
          </li>
          <li v-if="!composition.rows.length" class="legend-empty">Nothing is attributed yet.</li>
        </ul>
      </div>

      <CompactionSlider v-if="state.ui?.settings" :window="report.window" :used-percent="percent" />

      <p class="pop-note">
        Exact values are shown above{{ composition.ring.expanded ? "; tiny ring slices are enlarged for visibility" : "" }}.
      </p>

      <div class="pop-foot">
        <span>{{ source }}</span>
        <div class="pop-actions">
          <button class="btn ghost small" type="button" @click="post({ type: 'context' })">Refresh</button>
          <button class="btn small" type="button" @click="post({ type: 'compact' }); closeOverlay()">Compact now</button>
        </div>
      </div>
    </template>

    <template v-else>
      <div class="pop-head">
        <div>
          <h2>Context composition</h2>
          <div class="pop-sub">Latest model context</div>
        </div>
      </div>
      <div class="pop-empty">
        <strong>No context report yet</strong>
        <span>Send a prompt first; the provider's count or an estimate fills this in.</span>
      </div>
      <CompactionSlider
        v-if="state.ui?.settings"
        :window="state.ui.settings.model.context_window"
        :used-percent="null"
      />
      <div class="pop-foot">
        <span />
        <button class="btn ghost small" type="button" @click="post({ type: 'context' })">Refresh</button>
      </div>
    </template>
  </Popover>
</template>

<style>
#context-popover {
  padding: 12px 12px 8px;
}

.pop-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.pop-head h2 {
  margin: 0;
  font-size: 15px;
  font-weight: 650;
  letter-spacing: -0.015em;
}

.pop-sub {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-top: 3px;
  color: var(--muted);
  font-size: var(--tiny);
}

.pill {
  padding: 0 7px;
  border: 1px solid var(--line-strong);
  border-radius: 999px;
  font-size: 10.5px;
  line-height: 16px;
}

.pop-total {
  color: var(--muted);
  font-size: var(--tiny);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.pop-total strong {
  color: var(--fg);
  font-size: 15px;
  font-weight: 650;
}

.pop-body {
  display: flex;
  align-items: center;
  gap: 18px;
  margin-top: 14px;
}

.pop-ring {
  position: relative;
  width: 116px;
  height: 116px;
  flex-shrink: 0;
}

.pop-ring-center {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}

.pop-ring-center strong {
  font-size: 20px;
  font-weight: 650;
  letter-spacing: -0.03em;
  font-variant-numeric: tabular-nums;
}

.pop-ring-center span {
  color: var(--muted);
  font-size: 10px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.legend {
  flex: 1;
  min-width: 0;
  margin: 0;
  padding: 0;
  list-style: none;
}

.legend-row {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 5px 6px;
  margin: 0 -6px;
  border-radius: 6px;
  font-size: 13px;
  transition: background 0.12s;
}

.legend-row.active {
  background: var(--wash-2);
}

.legend-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.legend-pct {
  min-width: 46px;
  text-align: right;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.legend-pct.pending {
  color: var(--faint);
  font-weight: 400;
  font-style: italic;
}

.legend-row.pending .legend-name {
  color: var(--muted);
}

.legend-row.pending .swatch {
  background: none;
  box-shadow: inset 0 0 0 1.5px var(--faint);
}

.legend-empty {
  color: var(--muted);
  font-size: var(--small);
}

.pop-note {
  margin: 12px 0 0;
  padding-top: 11px;
  border-top: 1px solid var(--line);
  color: var(--faint);
  font-size: var(--tiny);
  line-height: 1.45;
}

.pop-foot {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 10px;
  margin-top: 8px;
  color: var(--faint);
  font-size: 11px;
}

.pop-actions {
  display: flex;
  gap: 2px;
  flex-shrink: 0;
}

.pop-empty {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 14px 0 8px;
  padding: 14px;
  border: 1px dashed var(--line-strong);
  border-radius: var(--r-m);
  font-size: var(--small);
}

.pop-empty span {
  color: var(--muted);
}
</style>
