<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { t } from "../../i18n";
import { clockTime } from "../../lib/format";
import { closeGroup, groupChat, groupNamed, joinGroup, loadEarlierGroup, membersOf, openGroup, senderName, sendToGroup } from "../../stores/groups";
import { href } from "../../stores/route";
import { lobby } from "../../stores/threads";
import { toast } from "../../stores/ui";
import Avatar from "../common/Avatar.vue";
import Icon from "../common/Icon.vue";
import UserAvatar from "../common/UserAvatar.vue";
import MessageText from "../chat/MessageText.vue";
import GroupMembers from "./GroupMembers.vue";

const props = defineProps<{ name: string }>();

const group = computed(() => groupNamed(props.name));
const members = computed(() => (group.value ? membersOf(group.value) : []));
const online = computed(() => members.value.filter((member) => member.online).length);
const meId = computed(() => lobby.status?.gateway.id ?? "");
const joined = computed(() => group.value?.members.includes(meId.value) ?? false);
const showMembers = ref(false);
const text = ref("");
const field = ref<HTMLTextAreaElement | null>(null);
const scroller = ref<HTMLElement | null>(null);
const following = ref(true);
const typesByEnter = !matchMedia("(pointer: coarse)").matches;

interface Line {
  id: number;
  mine: boolean;
  who: string;
  senderId: string;
  text: string;
  time: string;
  /** The message follows another from the same sender within a moment: no name and no avatar again. */
  cont: boolean;
  tail: boolean;
}

const lines = computed<Line[]>(() => {
  const found: Line[] = [];
  groupChat.messages.forEach((message, at) => {
    const previous = groupChat.messages[at - 1];
    const next = groupChat.messages[at + 1];
    const same = (a?: typeof message, b?: typeof message): boolean =>
      a !== undefined && b !== undefined && a.from.session_id === b.from.session_id && Math.abs(b.ts - a.ts) < 300;
    found.push({
      id: message.id,
      mine: message.from.session_id === meId.value,
      who: senderName(message),
      senderId: message.from.session_id,
      text: message.text,
      time: clockTime(message.ts * 1000),
      cont: same(previous, message),
      tail: !same(message, next),
    });
  });
  return found;
});

function nearBottom(): boolean {
  const el = scroller.value;
  return !el || el.scrollHeight - el.scrollTop - el.clientHeight < 140;
}
function toBottom(smooth: boolean): void {
  void nextTick(() => scroller.value?.scrollTo({ top: scroller.value.scrollHeight, behavior: smooth ? "smooth" : "auto" }));
}

watch(() => props.name, (name) => void openGroup(name), { immediate: true });
watch(
  () => groupChat.messages.length,
  (now, before) => {
    // Older messages added above are not a reason to move; a new one at the bottom is, for a reader who is following.
    if (before === 0 || following.value) toBottom(before !== 0);
  },
  { flush: "post" },
);
onMounted(() => toBottom(false));
onBeforeUnmount(closeGroup);

async function submit(): Promise<void> {
  const body = text.value.trim();
  if (!body || groupChat.sending || !joined.value) return;
  const failure = await sendToGroup(props.name, body);
  if (failure) {
    toast(failure, "bad");
    return;
  }
  text.value = "";
  following.value = true;
  toBottom(true);
  field.value?.focus({ preventScroll: true });
}

async function join(): Promise<void> {
  const failure = await joinGroup(props.name);
  if (failure) toast(failure, "bad");
}

function onKey(event: KeyboardEvent): void {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing && typesByEnter) {
    event.preventDefault();
    void submit();
  }
}

function resize(): void {
  const el = field.value;
  if (!el) return;
  el.style.height = "auto";
  el.style.height = `${Math.min(el.scrollHeight, 152)}px`;
}
watch(text, () => void nextTick(resize));
</script>

<template>
  <div v-if="!group && !groupChat.loading" class="empty">
    <b>{{ t("This group is not listed") }}</b>
    {{ groupChat.error }}
  </div>
  <div v-else class="chat">
    <header class="bar chat-head">
      <a class="iconbtn back" :href="href('chats')" :aria-label="t('Back')"><Icon name="back" /></a>
      <button class="chat-who" :aria-expanded="showMembers" @click="showMembers = !showMembers">
        <Avatar :thread="{ id: `#${name}`, name, kind: 'external', status: 'idle' }" size="sm" />
        <span class="chat-title">
          <b>#{{ name }}</b>
          <span>{{ t("{count} members", { count: members.length }) }} · {{ t("{count} online", { count: online }) }}</span>
        </span>
      </button>
      <button class="iconbtn" :aria-pressed="showMembers" :aria-label="t('Members')" :title="t('Members')" @click="showMembers = !showMembers">
        <Icon name="users" />
      </button>
    </header>
    <div class="group-body">
      <div class="chat-bg group-main">
        <div ref="scroller" class="messages" role="log" aria-live="polite" @scroll.passive="following = nearBottom()">
          <div class="messages-body">
            <div v-if="groupChat.loading" class="messages-note"><span class="spin" /></div>
            <div v-else-if="groupChat.error" class="errcard">{{ groupChat.error }}</div>
            <button v-if="groupChat.more" class="btn sm ghost messages-more" :disabled="groupChat.loadingOlder" @click="loadEarlierGroup">
              {{ t("Show earlier messages") }}
            </button>
            <div v-for="line in lines" :key="line.id" class="msg" :class="[line.mine ? 'out' : 'in', { cont: line.cont }]">
              <template v-if="!line.mine">
                <Avatar
                  v-if="line.tail"
                  class="msg-avatar"
                  :thread="{ id: line.senderId, name: line.who, kind: 'external', status: 'idle' }"
                  size="sm"
                />
                <div v-else class="msg-avatar" />
              </template>
              <div class="bubble">
                <span v-if="!line.mine && !line.cont" class="group-who">{{ line.who }}</span>
                <MessageText :text="line.text" />
                <span class="group-time">{{ line.time }}</span>
              </div>
              <template v-if="line.mine">
                <UserAvatar v-if="line.tail" class="msg-avatar" size="sm" />
                <div v-else class="msg-avatar" />
              </template>
            </div>
            <div v-if="!groupChat.loading && !lines.length && !groupChat.error" class="messages-note">
              {{ t("Nothing has been said in this group yet.") }}
            </div>
          </div>
        </div>
      </div>
      <GroupMembers v-if="showMembers" :members="members" @close="showMembers = false" />
    </div>
    <div v-if="!joined" class="group-join">
      <span>{{ t("You are not in this group. You can read it; join to write.") }}</span>
      <button class="btn sm" type="button" :disabled="groupChat.sending" @click="join">
        {{ groupChat.sending ? t("Joining…") : t("Join group") }}
      </button>
    </div>
    <form v-else class="composer" @submit.prevent="submit">
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
      </div>
      <button class="sendbtn" type="submit" :disabled="!text.trim() || groupChat.sending" :aria-label="t('Send')" @pointerdown.prevent>
        <Icon name="send" />
      </button>
    </form>
  </div>
</template>

<style>
.group-body { flex: 1; min-height: 0; display: flex; }
.group-main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.group-who { display: block; font-size: 0.8rem; font-weight: 650; color: var(--accent); margin-bottom: 2px; }
.group-time { display: block; text-align: right; margin-top: 3px; font-size: 0.7rem; opacity: 0.6; user-select: none; }
.msg.out .group-time { color: var(--out-meta); opacity: 1; }
.group-join { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 16px calc(10px + var(--safe-bottom)); background: var(--surface); border-top: 1px solid var(--divider); color: var(--muted); font-size: 0.85rem; line-height: 1.35; }
.group-join .btn { flex: none; }
</style>
