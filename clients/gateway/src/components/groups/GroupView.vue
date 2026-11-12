<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { t } from "../../i18n";
import Skeleton from "../common/Skeleton.vue";
import { clockTime } from "../../lib/format";
import { closeGroup, groupChat, groupNamed, joinGroup, loadEarlierGroup, membersOf, openGroup, deleteGroup, removeFromGroup, senderName, sendToGroup } from "../../stores/groups";
import type { Member } from "../../stores/groups";
import { go, href } from "../../stores/route";
import { lobby } from "../../stores/threads";
import { openSheet, toast } from "../../stores/ui";
import Avatar from "../common/Avatar.vue";
import Icon from "../common/Icon.vue";
import UserAvatar from "../common/UserAvatar.vue";
import MessageText from "../chat/MessageText.vue";
import GroupMembers from "./GroupMembers.vue";
import InviteSheet from "./InviteSheet.vue";
import { confirmAction, showMenu } from "../sheets/sheets";

const props = defineProps<{ name: string }>();

const group = computed(() => groupNamed(props.name));
const members = computed(() => (group.value ? membersOf(group.value) : []));
const online = computed(() => members.value.filter((member) => member.online).length);
const memberLabel = computed(() =>
  members.value.length === 1 ? t("1 member") : t("{count} members", { count: members.value.length }),
);
const onlineLabel = computed(() => (online.value === 1 ? t("1 online") : t("{count} online", { count: online.value })));
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

function invite(): void {
  void openSheet(t("Invite to #{name}", { name: props.name }), InviteSheet, {
    group: props.name,
    members: members.value.map((member) => member.id),
  });
}

/** Leave the group (the person themselves) or take a member out of it; the sheet spins while the broker answers. */
async function takeOut(member: Member): Promise<void> {
  const leaving = member.me;
  const done = await confirmAction({
    title: leaving ? t("Leave #{name}?", { name: props.name }) : t("Remove {name} from #{name2}?", { name: member.name, name2: props.name }),
    text: leaving
      ? t("You stop receiving what is said here and cannot write to it. The conversation stays readable, and you can join again.")
      : t("{name} stops receiving what is said in this group. The session itself keeps running.", { name: member.name }),
    ok: leaving ? t("Leave group") : t("Remove"),
    danger: true,
    run: () => removeFromGroup(props.name, member.id),
  });
  if (!done) return;
  toast(leaving ? t("You left #{name}", { name: props.name }) : t("{name} was removed", { name: member.name }));
  if (members.value.length === 0) showMembers.value = false;
}

async function dissolve(): Promise<void> {
  const done = await confirmAction({
    title: t("Delete #{name}?", { name: props.name }),
    text: t("The group and what was said in it are deleted for everyone. The sessions in it keep running."),
    ok: t("Delete group"),
    danger: true,
    run: () => deleteGroup(props.name),
  });
  if (!done) return;
  toast(t("Deleted #{name}", { name: props.name }));
  go("chats");
}

function menu(): void {
  const me = members.value.find((member) => member.me);
  showMenu(`#${props.name}`, [
    { icon: "users", label: t("Members"), run: () => (showMembers.value = true) },
    joined.value && { icon: "plus", label: t("Invite"), run: invite },
    me && { icon: "logout", label: t("Leave group"), run: () => void takeOut(me), danger: true },
    { icon: "trash", label: t("Delete group"), run: () => void dissolve(), danger: true },
  ]);
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
          <span>{{ memberLabel }} · {{ onlineLabel }}</span>
        </span>
      </button>
      <button class="iconbtn" :aria-pressed="showMembers" :aria-label="t('Members')" :title="t('Members')" @click="showMembers = !showMembers">
        <Icon name="users" />
      </button>
      <button class="iconbtn" :aria-label="t('More')" :title="t('More')" @click="menu"><Icon name="more" /></button>
    </header>
    <div class="group-body">
      <div class="chat-bg group-main">
        <div ref="scroller" class="messages" role="log" aria-live="polite" @scroll.passive="following = nearBottom()">
          <div class="messages-body">
            <Skeleton v-if="groupChat.loading" kind="bubbles" :count="7" />
            <div v-else-if="groupChat.error" class="errcard">{{ groupChat.error }}</div>
            <button v-if="groupChat.more" class="btn sm ghost messages-more" :disabled="groupChat.loadingOlder" @click="loadEarlierGroup">
              <span v-if="groupChat.loadingOlder" class="spin" />{{ t("Show earlier messages") }}
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
            <div v-if="!groupChat.loading && !lines.length && !groupChat.error" class="group-empty">
              <Avatar :thread="{ id: `#${name}`, name, kind: 'external', status: 'idle' }" size="xl" />
              <b>#{{ name }}</b>
              <span>{{ t("No messages yet. Say something to start the group.") }}</span>
              <button v-if="joined" class="btn sm ghost" type="button" @click="invite">{{ t("Invite") }}</button>
            </div>
          </div>
        </div>
      </div>
      <GroupMembers v-if="showMembers" :members="members" :can-invite="joined" @invite="invite" @remove="takeOut" @close="showMembers = false" />
    </div>
    <div v-if="!joined" class="group-join">
      <span>{{ t("You are not in this group. You can read it; join to write.") }}</span>
      <button class="btn sm" type="button" :disabled="groupChat.sending" @click="join">
        <span v-if="groupChat.sending" class="spin" />{{ groupChat.sending ? t("Joining…") : t("Join group") }}
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
.group-empty {
  display: flex; flex-direction: column; align-items: center; gap: 8px; padding: clamp(48px, 14vh, 140px) 20px 32px;
  text-align: center; color: var(--muted);
}
.group-empty .avatar { margin-bottom: 4px; box-shadow: var(--shadow); }
.group-empty b { color: var(--text); font-size: 1.3rem; letter-spacing: -0.02em; }
.group-empty span { max-width: 22rem; font-size: 0.92rem; line-height: 1.5; }
.group-empty .btn { margin-top: 4px; }
.group-join { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 16px calc(10px + var(--safe-bottom)); background: var(--surface); border-top: 1px solid var(--divider); color: var(--muted); font-size: 0.85rem; line-height: 1.35; }
.group-join .btn { flex: none; }
</style>
