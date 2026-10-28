<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { gateway } from "../../api/gateway";
import { ApiError } from "../../api/http";
import { t } from "../../i18n";
import { duration } from "../../lib/format";
import { go } from "../../stores/route";
import { threadOf } from "../../stores/threads";
import Icon from "../common/Icon.vue";
import PageBar from "../common/PageBar.vue";
import { restartDaemon, stopDaemon } from "../chat/threadActions";

const props = defineProps<{ id: string }>();
const thread = computed(() => threadOf(props.id));
const text = ref("");
const error = ref("");
const box = ref<HTMLElement | null>(null);
let timer: ReturnType<typeof setInterval> | undefined;

const lines = computed(() => text.value.split("\n").filter(Boolean).map((line) => ({ line, bad: /error|fail|traceback|exception/i.test(line) })));

async function load(): Promise<void> {
  try {
    text.value = (await gateway.log(props.id)).text;
    error.value = "";
    await nextTick();
    box.value?.scrollTo({ top: box.value.scrollHeight });
  } catch (failure) {
    error.value = failure instanceof ApiError ? failure.message : String(failure);
  }
}

watch(() => props.id, () => void load());
onMounted(() => {
  void load();
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
      <div ref="box" class="logbox" role="log">
        <template v-if="lines.length"><div v-for="(item, at) in lines" :key="at" :class="{ 'log-bad': item.bad }">{{ item.line }}</div></template>
        <span v-else class="mute">{{ t("The log is empty.") }}</span>
      </div>
    </div>
  </div>
</template>

<style>
.logbox {
  margin: 10px 0; padding: 10px 12px; border-radius: var(--radius); background: var(--surface); font-family: var(--mono);
  font-size: 0.78rem; line-height: 1.5; white-space: pre-wrap; word-break: break-word; min-height: 8rem; max-height: 60dvh; overflow: auto;
}
.log-bad { color: var(--bad); }
.mute { color: var(--muted); }
</style>
