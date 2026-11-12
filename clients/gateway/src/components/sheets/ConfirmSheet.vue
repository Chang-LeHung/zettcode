<script setup lang="ts">
import { ref } from "vue";
import { ApiError } from "../../api/http";
import { t } from "../../i18n";
import { toast } from "../../stores/ui";

const props = defineProps<{ text: string; ok: string; danger?: boolean; run?: () => Promise<void> }>();
const emit = defineEmits<{ close: [answer: boolean]; busy: [on: boolean] }>();
const busy = ref(false);

// With `run`, the sheet stays open and spins while the action is under way, so the answer is seen to be taken;
// a failure is said in a toast and counts as "no".
async function accept(): Promise<void> {
  if (busy.value) return;
  if (!props.run) return emit("close", true);
  busy.value = true;
  emit("busy", true);
  try {
    await props.run();
    emit("busy", false);
    emit("close", true);
  } catch (error) {
    emit("busy", false);
    toast(error instanceof ApiError ? error.message : String(error), "bad");
    emit("close", false);
  }
}
</script>

<template>
  <p class="card-hint confirm-text">{{ text }}</p>
  <div class="actions">
    <button class="btn" :class="{ danger }" :disabled="busy" @click="accept"><span v-if="busy" class="spin" />{{ ok }}</button>
    <button class="btn ghost" :disabled="busy" @click="emit('close', false)">{{ t("Cancel") }}</button>
  </div>
</template>

<style>
.confirm-text { padding-top: 8px; font-size: 0.95rem; color: var(--text); }
</style>
