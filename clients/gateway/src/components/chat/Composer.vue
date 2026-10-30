<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { t } from "../../i18n";
import { chat, draftOf, sendMessage, setDraft, setWantsReply, wantsReply } from "../../stores/chat";
import { prefs } from "../../stores/prefs";
import { lobby } from "../../stores/threads";
import type { Thread } from "../../types";
import Icon from "../common/Icon.vue";
import { confirmAction } from "../sheets/sheets";

const props = defineProps<{ thread: Thread }>();
const field = ref<HTMLTextAreaElement | null>(null);
const text = ref(draftOf(props.thread.id));
const confirmed = new Set<string>();

const typesByEnter = !matchMedia("(pointer: coarse)").matches;
const limits = computed(() => lobby.status?.limits);
const asking = computed(() => wantsReply(props.thread));
const empty = computed(() => text.value.trim() === "");
const nearLimit = computed(() => limits.value !== undefined && text.value.length > limits.value.max_text * 0.8);
const budget = computed(() => {
  const l = limits.value;
  return l && l.used >= l.rate_limit * 0.7 ? t("{used} of {limit} messages used this minute", { used: l.used, limit: l.rate_limit }) : "";
});

function resize(): void {
  const el = field.value;
  if (!el) return;
  el.style.height = "auto";
  el.style.height = `${Math.min(el.scrollHeight, 152)}px`;
}

watch(text, (value) => {
  setDraft(props.thread.id, value);
  void nextTick(resize);
});
watch(
  () => props.thread.id,
  (id) => {
    text.value = draftOf(id);
    void nextTick(resize);
  },
);
onMounted(() => {
  resize();
  if (typesByEnter) field.value?.focus();
});

async function submit(): Promise<void> {
  const body = text.value.trim();
  if (!body) return;
  const thread = props.thread;
  if (thread.kind !== "daemon" && prefs.confirmSession && !confirmed.has(thread.id)) {
    const go = await confirmAction({
      title: t("Write to {name}?", { name: thread.name }),
      text: t("This session may have a person at it. Your message starts a turn there and uses that session's tokens."),
      ok: t("Send"),
    });
    if (!go) return;
    confirmed.add(thread.id);
  }
  text.value = "";
  // Keep the keyboard up, as a messenger does: a person sending several lines in a row does not want it to drop each time.
  field.value?.focus({ preventScroll: true });
  await sendMessage(body, wantsReply(thread));
}

function onKey(event: KeyboardEvent): void {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing && typesByEnter) {
    event.preventDefault();
    void submit();
  }
}
</script>

<template>
  <div v-if="budget" class="composer-note">{{ budget }}</div>
  <form class="composer" @submit.prevent="submit">
    <div class="composer-field">
      <textarea
        ref="field"
        v-model="text"
        rows="1"
        :placeholder="t('Message')"
        :aria-label="t('Message')"
        enterkeyhint="send"
        @keydown="onKey"
      />
      <span v-if="nearLimit" class="composer-count">{{ text.length }}/{{ limits?.max_text }}</span>
      <button
        type="button"
        class="composer-reply"
        :aria-pressed="asking"
        :title="t('Ask the agent to answer with send_message')"
        :aria-label="t('Ask the agent to answer with send_message')"
        @pointerdown.prevent
        @click="setWantsReply(chat.id, !asking)"
      >
        <Icon name="reply" size="sm" />
      </button>
    </div>
    <button class="sendbtn" type="submit" :disabled="empty" :aria-label="t('Send')" @pointerdown.prevent>
      <Icon name="send" />
    </button>
  </form>
</template>

<style>
.composer {
  flex: none; display: flex; align-items: flex-end; gap: 8px;
  padding: 8px calc(var(--safe-right) + 12px) calc(8px + var(--safe-bottom)) calc(var(--safe-left) + 12px);
  background: var(--surface); border-top: 1px solid var(--divider);
}
.composer-field {
  flex: 1; min-width: 0; display: flex; align-items: flex-end; border-radius: 22px; background: var(--surface-2); padding: 0 4px 0 6px;
  box-shadow: inset 0 0 0 1.5px transparent; transition: box-shadow 0.2s ease, background 0.2s ease;
}
.composer-field:focus-within { box-shadow: inset 0 0 0 1.5px var(--accent-soft); }
.composer textarea {
  flex: 1; min-width: 0; resize: none; border: 0; outline: 0; background: none; color: var(--text);
  padding: 11px 6px; line-height: 1.35; max-height: 9.5rem; font-size: 1rem;
}
.composer textarea::placeholder { color: var(--muted); }
.composer-count { align-self: center; font-size: 0.72rem; color: var(--warn); padding: 0 4px; }
.composer-reply { width: 38px; height: 44px; display: grid; place-items: center; border-radius: 50%; color: var(--muted); }
.composer-reply[aria-pressed="true"] { color: var(--accent); }
.sendbtn {
  flex: none; width: 46px; height: 46px; border-radius: 50%; display: grid; place-items: center;
  background: var(--accent); color: var(--accent-text);
  transition: transform 0.28s cubic-bezier(0.34, 1.56, 0.64, 1), background 0.2s, color 0.2s, opacity 0.2s;
}
.sendbtn:active:not(:disabled) { transform: scale(0.88); }
.sendbtn:disabled { background: var(--surface-2); color: var(--muted); transform: scale(0.9); }
.composer-reply { transition: color 0.2s, transform 0.2s cubic-bezier(0.34, 1.56, 0.64, 1); }
.composer-reply:active { transform: scale(0.85); }
.composer-reply[aria-pressed="true"] { transform: rotate(-12deg); }
.sendbtn svg { margin-left: 2px; }
.composer-note { flex: none; padding: 6px 14px; font-size: 0.82rem; background: var(--surface); border-top: 1px solid var(--divider); color: var(--warn); }
</style>
