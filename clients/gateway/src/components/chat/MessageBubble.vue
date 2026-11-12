<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue";
import { picturePath, pictureUrl } from "../../api/pictures";
import { t } from "../../i18n";
import type { ChatImage } from "../../types";
import type { Row } from "../../lib/rows";
import { dismiss, quoteIntoDraft, retry, wantsReply } from "../../stores/chat";
import { currentKey, find } from "../../stores/chatSearch";
import { canWrite, threadOf } from "../../stores/threads";
import { toast } from "../../stores/ui";
import { copyText } from "../../lib/clipboard";
import { showMenu } from "../sheets/sheets";
import Avatar from "../common/Avatar.vue";
import Icon from "../common/Icon.vue";
import UserAvatar from "../common/UserAvatar.vue";
import MessageText from "./MessageText.vue";

type BubbleRow = Extract<Row, { type: "bubble" }>;
const props = defineProps<{ row: BubbleRow; thread: string }>();

const owner = computed(() => threadOf(props.thread));
// Only a message from another session says who it is from: what you typed needs no label.
const who = computed(() => {
  const item = props.row.item;
  return item.kind === "from" ? `${item.sender} · ${item.via}` : "";
});
const state = computed(() => props.row.pending?.state ?? "stored");
const failure = computed(() => props.row.pending?.error);
/**
 * Where each picture of the message is drawn from: this page's own copy until the gateway has it, then the gateway.
 * An app reads the bytes with its token and draws a blob; the page draws the gateway's address directly.
 */
const pictures = ref<Array<ChatImage & { src: string }>>([]);
let generation = 0;
const blobs: string[] = [];
watch(
  () => props.row.item.images,
  async (images) => {
    const mine = ++generation;
    for (const url of blobs.splice(0)) URL.revokeObjectURL(url);
    const next: Array<ChatImage & { src: string }> = [];
    for (const image of images ?? []) {
      let src = image.src ?? "";
      if (!src) {
        try {
          src = await pictureUrl(picturePath(props.thread, image.id));
          if (src.startsWith("blob:")) blobs.push(src);
        } catch {
          src = "";
        }
      }
      if (mine !== generation) {
        if (src.startsWith("blob:")) URL.revokeObjectURL(src);
        return;
      }
      if (src) next.push({ ...image, src });
    }
    if (mine === generation) pictures.value = next;
  },
  { immediate: true, deep: true },
);
onUnmounted(() => {
  generation += 1;
  for (const url of blobs.splice(0)) URL.revokeObjectURL(url);
});
const zoomed = ref("");

/** The words matching the search that is open, and the one the reader is on. */
const found = computed(() => find.open && find.keys.includes(props.row.key));
const current = computed(() => currentKey.value === props.row.key);

async function copy(): Promise<void> {
  toast((await copyText(props.row.item.text)) ? t("Copied") : t("Could not copy"));
}

/** What can be done with a message: copy it, or quote it in the next one. */
function menu(): void {
  const text = props.row.item.text;
  if (!text) return;
  const thread = owner.value;
  showMenu(t("Message"), [
    { icon: "copy", label: t("Copy text"), run: () => void copy() },
    !!thread && canWrite(thread) && { icon: "reply", label: t("Quote in reply"), run: () => quoteIntoDraft(props.thread, text) },
  ]);
}

// A right click, and the long press on Android that becomes one. A reader who has selected words wants the browser's own menu.
function onContext(event: MouseEvent): void {
  if (!props.row.item.text || window.getSelection()?.toString()) return;
  event.preventDefault();
  menu();
}
// On a touch screen there is no hover: a double tap opens the menu, as there is no mouse to point at the button.
const touch = matchMedia("(pointer: coarse)").matches;
function onDouble(): void {
  if (touch && !window.getSelection()?.toString()) menu();
}

function again(): void {
  const entry = props.row.pending;
  const thread = threadOf(props.thread);
  if (entry && thread) void retry(entry, wantsReply(thread));
}
</script>

<template>
  <div class="msg" :class="[row.side, { cont: row.cont, found, current }]" :data-row="row.key" @contextmenu="onContext" @dblclick="onDouble">
    <template v-if="row.side === 'in'">
      <Avatar v-if="row.tail && owner" class="msg-avatar" :thread="owner" size="sm" />
      <div v-else class="msg-avatar" />
    </template>
    <div class="bubble" :class="{ reply: row.item.kind === 'reply', err: state === 'failed' }">
      <button v-if="row.item.text && !touch" type="button" class="bubble-more" :aria-label="t('Message actions')" :title="t('Message actions')" @click.stop="menu">
        <Icon name="more" size="xs" />
      </button>
      <span v-if="who" class="bubble-who">{{ who }}</span>
      <div v-if="pictures.length" class="bubble-pictures" :class="{ many: pictures.length > 1 }">
        <button
          v-for="(picture, at) in pictures"
          :key="at"
          type="button"
          class="bubble-picture"
          :aria-label="t('Enlarge the picture')"
          @click="zoomed = picture.src"
        >
          <img :src="picture.src" :alt="t('A picture in the message')" loading="lazy" decoding="async" />
        </button>
      </div>
      <MessageText v-if="row.item.text" :text="row.item.text" />
      <span v-if="state === 'sending' || state === 'queued' || state === 'failed'" class="meta">
        <span v-if="state === 'queued'">{{ t("queued") }}</span>
        <Icon v-if="state === 'sending'" name="clock" size="xs" />
        <Icon v-else-if="state === 'failed'" class="meta-bad" name="warn" size="xs" />
      </span>
      <div v-if="failure" class="bubble-retry">
        <span class="bubble-why">
          {{ failure.message }}
          <template v-if="failure.uncertain"> {{ t("It may or may not have arrived; sending again could duplicate it.") }}</template>
        </span>
        <button class="btn sm" @click="again">{{ t("Send again") }}</button>
        <button class="btn sm ghost" @click="row.pending && dismiss(row.pending)">{{ t("Delete") }}</button>
      </div>
    </div>
    <template v-if="row.side === 'out'">
      <UserAvatar v-if="row.tail" class="msg-avatar" size="sm" />
      <div v-else class="msg-avatar" />
    </template>
    <Teleport to="body">
      <button v-if="zoomed" type="button" class="zoom" :aria-label="t('Close')" @click="zoomed = ''" @keydown.esc="zoomed = ''">
        <img :src="zoomed" :alt="t('A picture in the message')" />
      </button>
    </Teleport>
  </div>
</template>

<style>
.msg { display: flex; align-items: flex-start; gap: 8px; max-width: 100%; margin-top: 12px; }
.msg.out { justify-content: flex-end; }
.msg.out.cont { margin-top: 3px; }
.msg-avatar { flex: none; width: 40px; height: 40px; }
.bubble {
  position: relative; min-width: 0; max-width: min(78%, 34rem); padding: 7px 11px 6px; border-radius: var(--bubble-radius);
  box-shadow: var(--shadow); line-height: 1.38; overflow-wrap: anywhere; word-break: break-word; animation: pop 0.16s ease-out;
}
.msg.in .bubble { max-width: min(92%, 52rem); padding: 9px 14px 8px; background: var(--in-bubble); color: var(--in-text); border-bottom-left-radius: 6px; }
.msg.out .bubble { background: var(--out-bubble); color: var(--out-text); border-bottom-right-radius: 6px; }
.msg.out.cont .bubble { border-top-right-radius: 6px; }
.msg.out .bubble a, .msg.out .bubble .md a { color: #fff; }
.msg.out .bubble .md code { background: rgba(255, 255, 255, 0.2); }
.msg.out .bubble .md blockquote { color: rgba(255, 255, 255, 0.8); border-color: rgba(255, 255, 255, 0.6); }
.msg.out .bubble .msg-code { background: rgba(255, 255, 255, 0.2); }
.bubble.reply { box-shadow: var(--shadow), inset 3px 0 0 var(--accent); }
.bubble-more {
  position: absolute; top: 4px; right: 4px; width: 24px; height: 24px; display: grid; place-items: center; border-radius: 50%;
  background: color-mix(in srgb, var(--surface) 88%, transparent); color: var(--muted); box-shadow: var(--shadow);
  opacity: 0; transition: opacity 0.12s;
}
.bubble:hover .bubble-more, .bubble-more:focus-visible { opacity: 1; }
/* A match for the search: the bubble is outlined, and the one the reader is on is outlined harder and settles in. */
.msg.found .bubble { outline: 2px solid color-mix(in srgb, var(--warn) 55%, transparent); outline-offset: 2px; }
.msg.current .bubble { outline: 3px solid var(--warn); animation: found 0.5s ease-out; }
@keyframes found { from { outline-offset: 10px; outline-color: transparent; } to { outline-offset: 2px; } }
.bubble.err { box-shadow: var(--shadow), inset 0 0 0 1px var(--bad); }
.bubble-who { display: block; font-size: 0.8rem; font-weight: 600; color: rgba(255, 255, 255, 0.85); margin-bottom: 2px; }
.meta { display: inline-flex; align-items: center; gap: 3px; float: right; margin: 5px 0 -2px 10px; font-size: 0.72rem; color: var(--out-meta); user-select: none; }
.meta-read { color: var(--out-meta); }
.meta-bad { color: var(--bad); }
.bubble-retry { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-top: 8px; clear: both; }
.bubble-pictures { display: grid; gap: 4px; margin: 2px 0 6px; grid-template-columns: 1fr; }
.bubble-pictures.many { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.bubble-picture { display: block; padding: 0; border-radius: 12px; overflow: hidden; background: rgba(0, 0, 0, 0.12); cursor: zoom-in; line-height: 0; }
.bubble-picture img { display: block; width: 100%; max-height: 22rem; min-height: 4rem; object-fit: cover; }
.bubble-pictures:not(.many) .bubble-picture img { width: auto; max-width: 100%; margin: 0 auto; object-fit: contain; }
.zoom { position: fixed; inset: 0; z-index: 60; display: grid; place-items: center; padding: 16px; background: rgba(0, 0, 0, 0.82); cursor: zoom-out; animation: pop 0.16s ease-out; }
.zoom img { max-width: 100%; max-height: 100%; object-fit: contain; border-radius: 6px; }
.bubble-why { flex-basis: 100%; font-size: 0.82rem; color: #fff; line-height: 1.35; }
@media (max-width: 719px) {
  .msg { gap: 6px; }
  .msg-avatar { width: 32px; height: 32px; }
  .msg.in .bubble { max-width: calc(100% - 38px); }
  .msg.out .bubble { max-width: calc(86% - 38px); }
}
</style>
