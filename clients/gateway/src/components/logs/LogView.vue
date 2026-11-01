<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { gateway } from "../../api/gateway";
import { ApiError } from "../../api/http";
import { t } from "../../i18n";
import { duration } from "../../lib/format";
import { counts, parseLog, visible, type LogFilter, type LogLine } from "../../lib/logs";
import { go } from "../../stores/route";
import { threadOf } from "../../stores/threads";
import Icon from "../common/Icon.vue";
import PageBar from "../common/PageBar.vue";
import { restartDaemon, stopDaemon } from "../chat/threadActions";

const props = defineProps<{ id: string }>();
const thread = computed(() => threadOf(props.id));
const lines = ref<LogLine[]>([]);
const error = ref("");
const filter = ref<LogFilter>("all");
const search = ref("");
const box = ref<HTMLElement | null>(null);
/** Whether the box is at its end, so a new line follows only a reader who is already there. */
const atEnd = ref(true);
let timer: ReturnType<typeof setInterval> | undefined;
/** The text last parsed, so a poll that finds the log unchanged leaves the list, and the reader's place, alone. */
let lastText: string | null = null;

const total = computed(() => counts(lines.value));
const shown = computed(() => visible(lines.value, filter.value, search.value));
const chips = computed(() => [
  { id: "all" as const, label: t("All"), count: total.value.all },
  { id: "tools" as const, label: t("Tools"), count: total.value.tools },
  { id: "problems" as const, label: t("Problems"), count: total.value.problems },
]);

function nearEnd(): boolean {
  const el = box.value;
  return !el || el.scrollHeight - el.scrollTop - el.clientHeight < 60;
}

function toEnd(): void {
  void nextTick(() => box.value?.scrollTo({ top: box.value.scrollHeight }));
}

async function load(): Promise<void> {
  // The daemon this call was for: an answer that arrives after the reader moved to another one is not theirs.
  const id = props.id;
  try {
    const follow = nearEnd();
    const text = (await gateway.log(id)).text;
    if (id !== props.id) return;
    error.value = "";
    if (text === lastText) return;
    lastText = text;
    lines.value = parseLog(text);
    if (follow) toEnd();
  } catch (failure) {
    if (id !== props.id) return;
    error.value = failure instanceof ApiError ? failure.message : String(failure);
  }
}

/** The day, shown once above the first line of each day instead of in front of every line. */
function newDay(index: number): boolean {
  const line = shown.value[index];
  return !!line?.date && line.date !== shown.value[index - 1]?.date;
}

watch(() => props.id, () => {
  lastText = null;
  void load();
});
watch([filter, search], toEnd);
onMounted(() => {
  void load();
  toEnd();
  timer = setInterval(() => !document.hidden && void load(), 4000);
});
onBeforeUnmount(() => clearInterval(timer));
</script>

<template>
  <PageBar :title="thread?.name ?? t('Logs')" back>
    <button class="iconbtn" :aria-label="t('Refresh')" @click="load"><Icon name="refresh" /></button>
  </PageBar>
  <div class="page">
    <div class="page-inner">
      <div v-if="thread" class="card">
        <div class="kv"><span>{{ t("Status") }}</span><span>{{ t(thread.status) }}</span></div>
        <div class="kv"><span>{{ t("Model") }}</span><span>{{ thread.model }}<template v-if="thread.effort"> · {{ thread.effort }}</template></span></div>
        <div class="kv"><span>{{ t("Shell level") }}</span><span>{{ thread.permission }}</span></div>
        <div class="kv"><span>{{ t("Workspace") }}</span><span class="mono">{{ thread.workspace }}</span></div>
        <div class="kv"><span>{{ t("Process") }}</span><span>{{ thread.pid || "–" }}</span></div>
        <div class="kv"><span>{{ t("Running for") }}</span><span>{{ thread.started_at ? duration(Date.now() / 1000 - thread.started_at) : "–" }}</span></div>
        <div class="actions">
          <button class="btn sm ghost" @click="go('chats', thread.id)">{{ t("Open chat") }}</button>
          <button class="btn sm ghost" @click="restartDaemon(thread)">{{ t("Restart with a new configuration") }}</button>
          <button class="btn sm danger" @click="stopDaemon(thread)">{{ thread.status === "dead" ? t("Clear record") : t("Stop") }}</button>
        </div>
      </div>
      <p v-if="error" class="errcard">{{ error }}</p>
      <div class="log-tools">
        <div class="log-chips" role="radiogroup" :aria-label="t('Show')">
          <button
            v-for="chip in chips"
            :key="chip.id"
            type="button"
            role="radio"
            class="log-chip"
            :class="{ 'is-bad': chip.id === 'problems' && chip.count > 0 }"
            :aria-checked="filter === chip.id"
            @click="filter = chip.id"
          >
            {{ chip.label }} <b>{{ chip.count }}</b>
          </button>
        </div>
        <input v-model="search" class="log-search" type="search" :placeholder="t('Search the log')" :aria-label="t('Search the log')" />
      </div>
      <div ref="box" class="logbox" role="log" @scroll.passive="atEnd = nearEnd()">
        <template v-if="shown.length">
          <template v-for="(item, at) in shown" :key="item.at">
            <div v-if="newDay(at)" class="log-day">{{ item.date }}</div>
            <div class="log-row" :class="`is-${item.kind}`">
              <span class="log-time">{{ item.time }}</span>
              <span class="log-kind">{{ item.kind === "turn" ? t("turn") : item.kind === "done" ? t("done") : item.name || "" }}</span>
              <span class="log-text">{{ item.text || (item.kind === "tool" ? "" : item.raw) }}</span>
            </div>
          </template>
        </template>
        <span v-else class="mute">{{ lines.length ? t("Nothing matches.") : t("The log is empty.") }}</span>
      </div>
      <button v-show="!atEnd" class="btn sm ghost log-jump" @click="toEnd">{{ t("Jump to the newest line") }}</button>
    </div>
  </div>
</template>

<style>
.log-tools { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin: 12px 0 0; }
.log-chips { display: flex; gap: 6px; flex-wrap: wrap; }
.log-chip { min-height: 32px; padding: 0 12px; border-radius: 16px; background: var(--surface); color: var(--muted); font-size: 0.86rem; transition: background 0.2s, color 0.2s; }
.log-chip b { font-weight: 650; margin-left: 2px; }
.log-chip[aria-checked="true"] { background: var(--accent); color: var(--accent-text); }
.log-chip.is-bad:not([aria-checked="true"]) { color: var(--bad); }
.log-search { flex: 1; min-width: 9rem; min-height: 34px; padding: 0 12px; border-radius: 17px; background: var(--surface); border: 1px solid transparent; }
.log-search:focus { outline: none; border-color: var(--accent); }
.logbox {
  margin: 10px 0 0; padding: 6px 0; border-radius: var(--radius); background: var(--surface); font-family: var(--mono);
  font-size: 0.78rem; line-height: 1.5; min-height: 8rem; max-height: 60dvh; overflow: auto;
}
.log-day { position: sticky; top: 0; padding: 4px 12px; background: var(--surface-2); color: var(--muted); font-size: 0.72rem; letter-spacing: 0.04em; z-index: 1; }
.log-row { display: grid; grid-template-columns: 4.6rem 5.6rem 1fr; gap: 8px; padding: 2px 12px; align-items: baseline; }
.log-row:hover { background: var(--hover); }
.log-time { color: var(--muted); font-variant-numeric: tabular-nums; }
.log-kind { color: var(--accent); font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.log-text { white-space: pre-wrap; word-break: break-word; min-width: 0; }
.log-row.is-turn { margin-top: 6px; border-top: 1px solid var(--divider); padding-top: 6px; }
.log-row.is-turn .log-kind, .log-row.is-done .log-kind { color: var(--ok); }
.log-row.is-info .log-kind { color: var(--muted); }
.log-row.is-info .log-text { color: var(--muted); }
.log-row.is-error .log-kind, .log-row.is-error .log-text { color: var(--bad); }
.log-jump { margin-top: 8px; }
.mute { display: block; padding: 8px 12px; color: var(--muted); }
@media (max-width: 560px) {
  .log-row { grid-template-columns: 4.2rem 1fr; }
  .log-kind { grid-column: 2; }
  .log-text { grid-column: 2; }
}
</style>
