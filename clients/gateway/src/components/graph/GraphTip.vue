<script setup lang="ts">
import { computed } from "vue";
import { t } from "../../i18n";
import { duration, folderName } from "../../lib/format";
import {
  edgeOf,
  groupByName,
  messagePreview,
  nodeOf,
  pairMessages,
  senderLabel,
  statsOf,
  targetLabel,
  tipText,
  type Tip,
} from "../../lib/graphData";
import { graph, graphNodes } from "../../stores/graph";

const props = defineProps<{ tip: Tip; now: number }>();

function ago(ts: number): string {
  const seconds = props.now - ts;
  return seconds < 5 ? t("just now") : t("{time} ago", { time: duration(seconds) });
}

function handleOf(id: string): string {
  const node = nodeOf(graphNodes.value, id);
  return node?.handle || id.slice(0, 8);
}

const node = computed(() => (props.tip.kind === "node" ? nodeOf(graphNodes.value, props.tip.id) : undefined));
const stats = computed(() => (props.tip.kind === "node" ? statsOf(graph, props.tip.id) : null));
const edge = computed(() => (props.tip.kind === "edge" ? edgeOf(graph, props.tip.a, props.tip.b) : undefined));
const latest = computed(() => (props.tip.kind === "edge" ? pairMessages(graph, props.tip.a, props.tip.b, 3) : []));
const group = computed(() => (props.tip.kind === "group" ? groupByName(graph, props.tip.name) : undefined));
</script>

<template>
  <div v-if="tip.kind === 'node' && node" class="gt">
    <div class="gt-head">
      <b>{{ node.handle }}</b>
      <span class="gt-chip" :class="node.status">{{ node.ghost ? t("offline") : t(node.status) }}</span>
      <span v-if="node.kind === 'external'" class="gt-chip">{{ t("external") }}</span>
    </div>
    <div v-if="node.title" class="gt-sub">{{ node.title }}</div>
    <div v-if="node.workspace" class="gt-row"><span>{{ t("Workspace") }}</span><span>{{ folderName(node.workspace) }}</span></div>
    <template v-if="stats">
      <div class="gt-row"><span>{{ t("Sent / received") }}</span><span>{{ stats.sent }} / {{ stats.received }}</span></div>
      <div class="gt-row"><span>{{ t("1:1 messages") }}</span><span>{{ stats.exchanged }}</span></div>
      <div v-if="stats.groups.length" class="gt-row"><span>{{ t("Groups") }}</span><span>{{ stats.groups.map((name) => `#${name}`).join(", ") }}</span></div>
      <div v-if="stats.last" class="gt-msg">
        <span class="gt-meta">{{ ago(stats.last.ts) }} · {{ senderLabel(stats.last) }} → {{ targetLabel(stats.last) }}</span>
        {{ messagePreview(stats.last, 140) }}
      </div>
    </template>
  </div>

  <div v-else-if="tip.kind === 'edge' && edge" class="gt">
    <div class="gt-head"><b>{{ handleOf(edge.a) }}</b><span class="gt-arrow">↔</span><b>{{ handleOf(edge.b) }}</b></div>
    <div class="gt-row"><span>{{ t("Messages") }}</span><span>{{ edge.count }}</span></div>
    <div class="gt-row"><span>{{ t("Last") }}</span><span>{{ ago(edge.last) }}</span></div>
    <div v-for="message in latest" :key="message.id" class="gt-msg">
      <span class="gt-meta">{{ ago(message.ts) }} · {{ senderLabel(message) }} → {{ targetLabel(message) }}</span>
      {{ messagePreview(message, 110) }}
    </div>
  </div>

  <div v-else-if="tip.kind === 'group' && group" class="gt">
    <div class="gt-head"><b>#{{ group.name }}</b><span class="gt-chip">{{ t("{n} members", { n: group.members.length }) }}</span></div>
    <div class="gt-members">
      <span v-for="id in group.members" :key="id" class="gt-chip">{{ handleOf(id) }}</span>
    </div>
  </div>

  <div v-else-if="tip.kind === 'packet'" class="gt">
    <div class="gt-head">
      <b>{{ senderLabel(tip.message) }}</b><span class="gt-arrow">→</span><b>{{ targetLabel(tip.message) }}</b>
    </div>
    <div class="gt-row"><span>{{ t("Via") }}</span><span>{{ t(tip.message.via) }}</span></div>
    <div class="gt-row"><span>{{ t("Time") }}</span><span>{{ new Date(tip.message.ts * 1000).toLocaleTimeString() }}</span></div>
    <div class="gt-row"><span>{{ t("Mode") }}</span><span>{{ t(tip.message.mode) }} · {{ t(tip.message.status) }}</span></div>
    <div v-if="tip.message.hops" class="gt-row"><span>{{ t("Hops") }}</span><span>{{ tip.message.hops }}</span></div>
    <div class="gt-msg gt-full">{{ tipText(tip.message) }}</div>
  </div>
</template>

<style>
.gt { display: flex; flex-direction: column; gap: 5px; }
.gt-head { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; font-size: 0.92rem; }
.gt-head b { font-weight: 650; overflow-wrap: anywhere; }
.gt-arrow { color: var(--muted); }
.gt-sub { color: var(--muted); font-size: 0.8rem; overflow-wrap: anywhere; }
.gt-row { display: flex; justify-content: space-between; gap: 18px; font-size: 0.8rem; }
.gt-row > span:first-child { color: var(--muted); flex: none; }
.gt-row > span:last-child { text-align: right; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
.gt-msg {
  margin-top: 3px; padding: 6px 8px; border-radius: 8px; background: var(--hover);
  font-size: 0.8rem; line-height: 1.4; overflow-wrap: anywhere; display: flex; flex-direction: column; gap: 2px;
}
.gt-full { white-space: pre-wrap; max-height: 220px; overflow: hidden; }
.gt-meta { color: var(--muted); font-size: 0.72rem; }
.gt-members { display: flex; flex-wrap: wrap; gap: 4px; }
.gt-chip {
  display: inline-flex; align-items: center; padding: 1px 7px; border-radius: 999px; font-size: 0.7rem; font-weight: 550;
  background: var(--hover); color: var(--muted); line-height: 1.5;
}
.gt-chip.idle { background: color-mix(in srgb, var(--ok) 18%, transparent); color: var(--ok); }
.gt-chip.working { background: color-mix(in srgb, var(--warn) 20%, transparent); color: var(--warn); }
</style>
