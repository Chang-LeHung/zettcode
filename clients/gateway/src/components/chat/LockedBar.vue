<script setup lang="ts">
import { computed, ref } from "vue";
import { gateway } from "../../api/gateway";
import { t } from "../../i18n";
import { go } from "../../stores/route";
import { fromThread } from "../../stores/spawn";
import { loadThreads, lobby } from "../../stores/threads";
import { toast } from "../../stores/ui";
import type { Thread } from "../../types";

const props = defineProps<{ thread: Thread }>();
const checking = ref(false);

const reason = computed(() => {
  if (lobby.status?.broker.reachable === false) return t("The session broker is not connected.");
  if (props.thread.locked) return t("This session is open in another ZettCode window, so it is read-only here.");
  if (props.thread.status === "dead") return t("This daemon has stopped.");
  if (props.thread.status === "starting") return t("This daemon is starting.");
  if (props.thread.status === "stopping") return t("This daemon is stopping.");
  return props.thread.kind === "daemon" ? t("This daemon is not connected.") : t("This session is not connected.");
});
const restartable = computed(() => props.thread.kind === "daemon" && props.thread.status === "dead" && !props.thread.locked);

function again(): void {
  fromThread(props.thread);
  go("new");
}

/** Ask again whether the other window still has it open; the person decides when, nothing here polls. */
async function recheck(): Promise<void> {
  checking.value = true;
  try {
    const { thread } = await gateway.recheck(props.thread.id);
    toast(thread.locked ? t("Still open in another window.") : t("No other window has it open now."));
    await loadThreads();
  } catch {
    toast(t("Could not check."), "bad");
  } finally {
    checking.value = false;
  }
}
</script>

<template>
  <div class="locked">
    <span>{{ reason }}</span>
    <button v-if="thread.locked" class="btn sm" :disabled="checking" @click="recheck">{{ t("Check again") }}</button>
    <button v-if="restartable" class="btn sm" @click="again">{{ t("Start it again") }}</button>
  </div>
</template>

<style>
.locked {
  flex: none; display: flex; align-items: center; justify-content: center; gap: 12px; flex-wrap: wrap;
  padding: 12px 14px calc(12px + var(--safe-bottom)); background: var(--surface); border-top: 1px solid var(--divider); color: var(--muted);
}
</style>
