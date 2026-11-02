<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { t } from "../../i18n";
import { isPicture, prepare, refusal, roomOf } from "../../lib/pictures";
import { chat, draftOf, sendMessage, setDraft, setWantsReply, wantsReply } from "../../stores/chat";
import { loadConfig, settings } from "../../stores/config";
import { prefs } from "../../stores/prefs";
import { lobby } from "../../stores/threads";
import { toast } from "../../stores/ui";
import type { Picture, Thread } from "../../types";
import Icon from "../common/Icon.vue";
import { confirmAction } from "../sheets/sheets";

const props = defineProps<{ thread: Thread }>();
const field = ref<HTMLTextAreaElement | null>(null);
const text = ref(draftOf(props.thread.id));
const confirmed = new Set<string>();

const typesByEnter = !matchMedia("(pointer: coarse)").matches;
const limits = computed(() => lobby.status?.limits);
const asking = computed(() => wantsReply(props.thread));
const pictures = ref<Picture[]>([]);
const picker = ref<HTMLInputElement | null>(null);
const dragging = ref(false);
const room = computed(() => roomOf(limits.value));
/** A session that runs a chat's text as its own prompt takes pictures if its model reads them. A model this page cannot see
 * (a plugin's) is let through: the gateway and the daemon both refuse a picture they cannot use, with the reason. */
const model = computed(() => settings.data?.models.find((m) => m.name === props.thread.model));
const readsPictures = computed(() => props.thread.direct && (model.value?.multimodal ?? true));
const pictureHint = computed(() =>
  !props.thread.direct
    ? t("This session cannot be sent a picture.")
    : t("{model} does not accept pictures.", { model: props.thread.model ?? "" }),
);
const empty = computed(() => text.value.trim() === "" && pictures.value.length === 0);
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
    pictures.value = [];
    void nextTick(resize);
  },
);
onMounted(() => {
  resize();
  void loadConfig();
  if (typesByEnter) field.value?.focus();
});

/** Take the pictures among some files, one by one, telling the person about each that cannot go. */
async function add(files: Iterable<File>): Promise<void> {
  const found = [...files].filter(isPicture);
  if (!found.length) return;
  if (!readsPictures.value) {
    toast(pictureHint.value, "bad");
    return;
  }
  for (const file of found) {
    try {
      const next = await prepare(file);
      const why = refusal(pictures.value, next, room.value);
      if (why) {
        toast(t(why, { count: room.value.images }), "bad");
        break;
      }
      pictures.value = [...pictures.value, next];
    } catch {
      toast(t("That picture could not be read."), "bad");
    }
  }
}

function picked(): void {
  const input = picker.value;
  if (!input) return;
  void add(Array.from(input.files ?? []));
  input.value = "";
}

function onPaste(event: ClipboardEvent): void {
  const files = Array.from(event.clipboardData?.files ?? []).filter(isPicture);
  if (!files.length) return;
  event.preventDefault();
  void add(files);
}

function onDrop(event: DragEvent): void {
  dragging.value = false;
  void add(Array.from(event.dataTransfer?.files ?? []));
}

async function submit(): Promise<void> {
  const body = text.value.trim();
  if (!body && !pictures.value.length) return;
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
  const sending = pictures.value;
  text.value = "";
  pictures.value = [];
  // Keep the keyboard up, as a messenger does: a person sending several lines in a row does not want it to drop each time.
  field.value?.focus({ preventScroll: true });
  await sendMessage(body, wantsReply(thread), sending);
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
  <div v-if="pictures.length" class="composer-pictures" role="list" :aria-label="t('Pictures to send')">
    <div v-for="(picture, at) in pictures" :key="at" class="composer-picture" role="listitem">
      <img :src="picture.src" :alt="picture.name" />
      <button type="button" :aria-label="t('Remove the picture')" @click="pictures = pictures.filter((_, i) => i !== at)">
        <Icon name="close" size="xs" />
      </button>
    </div>
  </div>
  <form
    class="composer"
    :class="{ dragging }"
    @submit.prevent="submit"
    @dragover.prevent="dragging = true"
    @dragleave="dragging = false"
    @drop.prevent="onDrop"
  >
    <input ref="picker" class="composer-file" type="file" accept="image/png,image/jpeg,image/gif,image/webp" multiple @change="picked" />
    <button
      v-if="thread.direct"
      type="button"
      class="composer-attach"
      :disabled="!readsPictures"
      :title="readsPictures ? t('Attach a picture') : pictureHint"
      :aria-label="t('Attach a picture')"
      @pointerdown.prevent
      @click="picker?.click()"
    >
      <Icon name="image" />
    </button>
    <div class="composer-field">
      <textarea
        ref="field"
        v-model="text"
        rows="1"
        :placeholder="t('Message')"
        :aria-label="t('Message')"
        enterkeyhint="send"
        @keydown="onKey"
        @paste="onPaste"
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
.composer-file { display: none; }
.composer-attach { flex: none; width: 40px; height: 46px; display: grid; place-items: center; border-radius: 50%; color: var(--muted); transition: color 0.2s, transform 0.2s cubic-bezier(0.34, 1.56, 0.64, 1); }
.composer-attach:hover:not(:disabled) { color: var(--accent); }
.composer-attach:active:not(:disabled) { transform: scale(0.88); }
.composer-attach:disabled { opacity: 0.4; }
.composer.dragging { box-shadow: inset 0 0 0 2px var(--accent); }
.composer-pictures { flex: none; display: flex; gap: 8px; overflow-x: auto; padding: 8px calc(var(--safe-right) + 12px) 0 calc(var(--safe-left) + 12px); background: var(--surface); border-top: 1px solid var(--divider); }
.composer-picture { position: relative; flex: none; width: 64px; height: 64px; border-radius: 10px; overflow: hidden; background: var(--surface-2); animation: pop 0.18s ease-out; }
.composer-picture img { width: 100%; height: 100%; object-fit: cover; display: block; }
.composer-picture button { position: absolute; top: 2px; right: 2px; width: 20px; height: 20px; border-radius: 50%; display: grid; place-items: center; background: rgba(0, 0, 0, 0.6); color: #fff; }
</style>
