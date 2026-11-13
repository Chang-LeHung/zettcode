<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { currentLanguage, t } from "../../i18n";
import Skeleton from "../common/Skeleton.vue";
import { clockTime } from "../../lib/format";
import { copyText } from "../../lib/clipboard";
import { jumpToQuoted } from "../../lib/jump";
import { clearReply, replies, setReply, withReply } from "../../stores/reply";
import ReplyBar from "../chat/ReplyBar.vue";
import { closeGroup, groupChat, groupNamed, joinGroup, loadEarlierGroup, membersOf, openGroup, deleteGroup, removeFromGroup, senderName, sendToGroup } from "../../stores/groups";
import type { Member } from "../../stores/groups";
import { go, href } from "../../stores/route";
import { auth } from "../../stores/auth";
import { lobby } from "../../stores/threads";
import { openSheet, toast } from "../../stores/ui";
import Avatar from "../common/Avatar.vue";
import Icon from "../common/Icon.vue";
import UserAvatar from "../common/UserAvatar.vue";
import MessageText from "../chat/MessageText.vue";
import GroupMembers from "./GroupMembers.vue";
import InviteSheet from "./InviteSheet.vue";
import { confirmAction, showMenu } from "../sheets/sheets";
import { applyErase, backspaceWhole } from "../../lib/erase";
import { longPress } from "../../lib/press";
import { dayName, sameDay } from "../../lib/day";

const props = defineProps<{ name: string }>();

const group = computed(() => groupNamed(props.name));
const members = computed(() => (group.value ? membersOf(group.value) : []));
/** The words an `@` in a message can name: every member's handle, so a mention reads as one whoever is online. This is
 * decoration for the reader, not delivery: an offline member's word is derived from a title (`address` false) and the broker
 * does not resolve it, so colour must never be taken to mean "this person was notified". */
const mentionable = computed(() => members.value.map((member) => member.handle).filter(Boolean));
const myHandle = computed(() => members.value.find((member) => member.me)?.handle ?? "");
const online = computed(() => members.value.filter((member) => member.online).length);
const memberLabel = computed(() =>
  members.value.length === 1 ? t("1 member") : t("{count} members", { count: members.value.length }),
);
const onlineLabel = computed(() => (online.value === 1 ? t("1 online") : t("{count} online", { count: online.value })));
const meId = computed(() => lobby.status?.gateway.id ?? "");
const joined = computed(() => group.value?.members.includes(meId.value) ?? false);
/** The group was listed while this page was open, so its absence now means it was deleted, not that the address is wrong. */
const existed = ref(false);
watch(group, (now) => now && (existed.value = true), { immediate: true });
const showMembers = ref(false);
const text = ref("");
/** Where this group's reply is kept: a group's key is `#name`, never a session id. */
const replyKey = computed(() => `#${props.name}`);
const field = ref<HTMLTextAreaElement | null>(null);
const scroller = ref<HTMLElement | null>(null);
const following = ref(true);
/** Messages that came in at the bottom while the reader was scrolled up reading: counted on the "newest" button. */
const unseen = ref(0);
const typesByEnter = !matchMedia("(pointer: coarse)").matches;

interface Line {
  id: number;
  mine: boolean;
  who: string;
  senderId: string;
  text: string;
  time: string;
  /** Set on the first message of a calendar day: the divider drawn above it ("Today", "Yesterday", a weekday, a date). */
  day?: string;
  /** The message follows another from the same sender within a moment: no name and no avatar again. */
  cont: boolean;
  tail: boolean;
}

/** The divider's words for the day of `ms`: today and yesterday are translated, the rest is the reader's own calendar. */
function dayLabel(ms: number): string {
  const day = dayName(ms, Date.now(), currentLanguage() === "zh" ? "zh-CN" : undefined);
  return day.kind === "today" ? t("Today") : day.kind === "yesterday" ? t("Yesterday") : day.text;
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
      day: previous && sameDay(previous.ts * 1000, message.ts * 1000) ? undefined : dayLabel(message.ts * 1000),
      cont: same(previous, message) && sameDay(previous!.ts * 1000, message.ts * 1000),
      tail: !same(message, next) || !sameDay(message.ts * 1000, next!.ts * 1000),
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

function onScroll(): void {
  following.value = nearBottom();
  if (following.value) unseen.value = 0;
}

watch(() => props.name, (name) => void openGroup(name), { immediate: true });
let lastId = 0;
watch(
  () => groupChat.messages.length,
  (now, before) => {
    // Older messages added above are not a reason to move; a new one at the bottom is, for a reader who is following.
    const fresh = lastId ? groupChat.messages.filter((message) => message.id > lastId).length : 0;
    lastId = groupChat.messages[now - 1]?.id ?? 0;
    if (before === 0 || following.value) {
      unseen.value = 0;
      toBottom(before !== 0);
    } else {
      unseen.value += fresh;
    }
  },
  { flush: "post" },
);
onMounted(() => toBottom(false));
onBeforeUnmount(closeGroup);

async function submit(): Promise<void> {
  const body = text.value.trim();
  if (!body || groupChat.sending || !joined.value) return;
  const failure = await sendToGroup(props.name, withReply(replyKey.value, body));
  if (failure) {
    toast(failure, "bad");
    return;
  }
  text.value = "";
  clearReply(replyKey.value);
  following.value = true;
  toBottom(true);
  field.value?.focus({ preventScroll: true });
}

/** What can be done with a message: copy it, or quote it, with its sender's name, in the next one. */
function lineMenu(line: Line): void {
  if (!line.text) return;
  showMenu(t("Message"), [
    {
      icon: "copy",
      label: t("Copy text"),
      run: async () => toast((await copyText(line.text)) ? t("Copied") : t("Could not copy")),
    },
    // The composer is drawn only to a member who may write; a reader and a visitor have none to reply from.
    joined.value &&
      !auth.readOnly && {
        icon: "reply",
        label: t("Reply"),
        run: () => {
          setReply(replyKey.value, line.mine ? "" : line.who, line.text);
          void nextTick(() => field.value?.focus({ preventScroll: true }));
        },
      },
  ]);
}

/** A right click, and the long press on Android that becomes one; a reader who has selected words wants the browser's own menu. */
function onLineContext(event: MouseEvent, line: Line): void {
  if (!line.text || window.getSelection()?.toString() || (event.target as HTMLElement).closest("a")) return;
  event.preventDefault();
  // A long press on a touch screen has just opened the menu itself; the browser's own contextmenu after it is not another.
  if (!press.recent()) lineMenu(line);
}

/** A touch screen has no hover and no right click: a long press opens the menu, as in a messenger. A double tap selects a
 * word, so it is left to the browser. */
const touch = matchMedia("(pointer: coarse)").matches;
let pressed: Line | null = null;
const press = longPress((event) => {
  const line = pressed;
  if (line && line.text && !(event.target as HTMLElement).closest("a") && !window.getSelection()?.toString()) lineMenu(line);
});
function pressDown(event: PointerEvent, line: Line): void {
  pressed = line;
  press.down(event);
}

/** A click on a quote: go to the message it was taken from. */
function onQuote(from: HTMLElement): void {
  if (!jumpToQuoted(from)) toast(t("The quoted message is not on this page."));
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
  const writer = !auth.readOnly;
  showMenu(`#${props.name}`, [
    { icon: "users", label: t("Members"), run: () => (showMembers.value = true) },
    writer && joined.value && { icon: "plus", label: t("Invite"), run: invite },
    writer && me && { icon: "logout", label: t("Leave group"), run: () => void takeOut(me), danger: true },
    // Deleting takes the group and what was said in it away from every member, so only a member is offered it.
    writer && joined.value && { icon: "trash", label: t("Delete group"), run: () => void dissolve(), danger: true },
  ]);
}

async function join(): Promise<void> {
  const failure = await joinGroup(props.name);
  if (failure) toast(failure, "bad");
}

function onKey(event: KeyboardEvent): void {
  // The reply bar is one thing above the input: Escape, or Backspace with nothing left to erase, takes it away.
  if (replies[replyKey.value] && !mention.value && !event.isComposing && (event.key === "Escape" || (event.key === "Backspace" && !text.value))) {
    event.preventDefault();
    clearReply(replyKey.value);
    return;
  }
  // A picked mention and a quote are each one thing in a messenger: Backspace right after one takes all of it.
  const el = field.value;
  const whole = el && backspaceWhole(event, el, others.value.map((member) => member.handle));
  if (el && whole) {
    event.preventDefault();
    mention.value = null;
    // Through the browser's own delete when it will, so Ctrl/Cmd+Z brings the mention or quote back.
    if (!applyErase(el, whole)) {
      text.value = whole.value;
      void nextTick(() => el.setSelectionRange(whole.caret, whole.caret));
    }
    return;
  }
  if (mention.value && choices.value.length) {
    const key = event.key;
    if ((key === "ArrowDown" || key === "ArrowUp") && !event.isComposing) {
      event.preventDefault();
      const n = choices.value.length;
      active.value = (active.value + (key === "ArrowDown" ? 1 : n - 1)) % n;
      return;
    }
    if ((key === "Enter" || key === "Tab") && !event.isComposing) {
      event.preventDefault();
      const chosen = choices.value[active.value];
      if (chosen) pick(chosen);
      return;
    }
  }
  if (mention.value && event.key === "Escape") {
    event.preventDefault();
    mention.value = null;
    return;
  }
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing && typesByEnter) {
    event.preventDefault();
    void submit();
  }
}

/** The ``@word`` the caret is at the end of, when the caret is in one: where it starts and what has been typed of it. */
const mention = ref<{ start: number; query: string } | null>(null);
const active = ref(0);
/** The members an ``@`` can address: everyone but the person typing, with a name to be called by. An offline member is
 * listed too, marked as offline: the text still names them, even though nothing is delivered until they are back. */
const others = computed(() => members.value.filter((member) => !member.me));
const callable = computed(() => others.value.filter((member) => member.handle));
const choices = computed(() => {
  const found = mention.value;
  if (!found) return [];
  const query = found.query.toLowerCase();
  return callable.value.filter(
    (member) => member.handle.toLowerCase().includes(query) || member.name.toLowerCase().includes(query),
  );
});
/** Why the picker is empty: nobody else is here, someone is but none has a name to be called by, or nothing matches. */
const nobody = computed(() =>
  !others.value.length
    ? t("There is nobody else in this group to mention.")
    : !callable.value.length
      ? t("No member here can be mentioned.")
      : t("No member matches."),
);

/** The ``@word`` the caret is at the end of right now, read from the field itself: where it starts and what was typed. */
function mentionAtCaret(): { start: number; query: string } | null {
  const el = field.value;
  if (!el || el.selectionStart !== el.selectionEnd) return null;
  const before = el.value.slice(0, el.selectionStart);
  const found = /(^|\s)@([\p{L}\p{N}_-]*)$/u.exec(before);
  const word = found?.[2];
  return word === undefined ? null : { start: before.length - word.length - 1, query: word };
}

function watchCaret(): void {
  mention.value = mentionAtCaret();
  active.value = 0;
}

function pick(member: Member): void {
  const el = field.value;
  // Read the caret again: Home, End and a click move it without any of the events that update ``mention``.
  const found = mentionAtCaret();
  if (!el || !found) {
    mention.value = null;
    return;
  }
  const end = el.selectionStart;
  const insert = `@${member.handle} `;
  text.value = text.value.slice(0, found.start) + insert + text.value.slice(end);
  mention.value = null;
  void nextTick(() => {
    el.focus({ preventScroll: true });
    const at = found.start + insert.length;
    el.setSelectionRange(at, at);
  });
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
    <b>{{ existed ? t("This group was deleted") : t("This group is not listed") }}</b>
    {{ existed ? "" : groupChat.error }}
    <a class="btn" :href="href('chats')">{{ t("Back to chats") }}</a>
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
        <div ref="scroller" class="messages" role="log" aria-live="polite" @scroll.passive="onScroll">
          <div class="messages-body">
            <Skeleton v-if="groupChat.loading" kind="bubbles" :count="7" />
            <div v-else-if="groupChat.error" class="errcard">{{ groupChat.error }}</div>
            <button v-if="groupChat.more" class="btn sm ghost messages-more" :disabled="groupChat.loadingOlder" @click="loadEarlierGroup">
              <span v-if="groupChat.loadingOlder" class="spin" />{{ t("Show earlier messages") }}
            </button>
            <template v-for="line in lines" :key="line.id">
            <div v-if="line.day" class="day-sep" role="separator"><span>{{ line.day }}</span></div>
            <div
              class="msg"
              :class="[line.mine ? 'out' : 'in', { cont: line.cont }]"
              :data-row="line.id"
              @contextmenu="onLineContext($event, line)"
              @pointerdown="pressDown($event, line)"
              @pointermove="press.move"
              @pointerup="press.end"
              @pointercancel="press.end"
              @pointerleave="press.end"
            >
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
                <button v-if="line.text && !touch" type="button" class="bubble-more" :aria-label="t('Message actions')" :title="t('Message actions')" @click.stop="lineMenu(line)">
                  <Icon name="more" size="xs" />
                </button>
                <span v-if="!line.mine && !line.cont" class="group-who">{{ line.who }}</span>
                <MessageText :text="line.text" :mentions="mentionable" :me="myHandle" @quote="onQuote" />
                <span class="group-time">{{ line.time }}</span>
              </div>
              <template v-if="line.mine">
                <UserAvatar v-if="line.tail" class="msg-avatar" size="sm" />
                <div v-else class="msg-avatar" />
              </template>
            </div>
            </template>
            <div v-if="!groupChat.loading && !lines.length && !groupChat.error" class="group-empty">
              <Avatar :thread="{ id: `#${name}`, name, kind: 'external', status: 'idle' }" size="xl" />
              <b>#{{ name }}</b>
              <span>{{ t("No messages yet. Say something to start the group.") }}</span>
              <button v-if="joined" class="btn sm ghost" type="button" @click="invite">{{ t("Invite") }}</button>
            </div>
          </div>
        </div>
        <button v-show="!following" type="button" class="fab" :aria-label="t('Scroll to the newest message')" @click="toBottom(true)">
          <Icon name="down" />
          <span v-if="unseen" class="badge">{{ unseen }}</span>
        </button>
      </div>
      <GroupMembers v-if="showMembers" :members="members" :can-invite="joined" @invite="invite" @remove="takeOut" @close="showMembers = false" />
    </div>
    <div v-if="auth.readOnly" class="group-join">
      <span>{{ t("You are signed in read-only: you can read everything and change nothing.") }}</span>
    </div>
    <div v-else-if="!joined" class="group-join">
      <span>{{ t("You are not in this group. You can read it; join to write.") }}</span>
      <button class="btn sm" type="button" :disabled="groupChat.sending" @click="join">
        <span v-if="groupChat.sending" class="spin" />{{ groupChat.sending ? t("Joining…") : t("Join group") }}
      </button>
    </div>
    <div v-if="joined && mention && !choices.length" class="mention-list mention-none" role="status">
      {{ nobody }}
    </div>
    <div
      v-if="joined && mention && choices.length"
      id="mention-list"
      class="mention-list"
      role="listbox"
      :aria-label="t('Mention a member')"
      @pointerdown.prevent
    >
      <button
        v-for="(member, at) in choices"
        :id="`mention-${at}`"
        :key="member.id"
        type="button"
        role="option"
        class="mention-row"
        :class="{ on: at === active }"
        :aria-selected="at === active"
        @pointerdown.prevent
        @mouseenter="active = at"
        @click="pick(member)"
      >
        <Avatar :thread="{ id: member.id, name: member.name, kind: 'external', status: 'idle' }" size="sm" />
        <span class="mention-name">{{ member.name }}</span>
        <!-- Only a roster handle is an address the broker resolves; a word made from a title is shown as the name it is. -->
        <span class="mention-handle">{{ member.address ? `@${member.handle}` : "" }}</span>
        <span v-if="!member.online" class="mention-offline">{{ t("offline") }}</span>
        <span class="mention-state" :class="member.status" />
      </button>
    </div>
    <ReplyBar v-if="joined && replies[replyKey]" :who="replies[replyKey]!.who" :text="replies[replyKey]!.text" @cancel="clearReply(replyKey)" />
    <form v-if="joined" class="composer" @submit.prevent="submit">
      <div class="composer-field">
        <textarea
          ref="field"
          v-model="text"
          rows="1"
          :placeholder="t('Message')"
          :aria-label="t('Message')"
          enterkeyhint="send"
          @keydown="onKey"
          @input="watchCaret"
          @click="watchCaret"
          @keyup="(e: KeyboardEvent) => ['ArrowLeft', 'ArrowRight', 'Home', 'End', 'PageUp', 'PageDown'].includes(e.key) && watchCaret()"
          :aria-expanded="Boolean(joined && mention && choices.length)"
          aria-controls="mention-list"
          aria-autocomplete="list"
          :aria-activedescendant="mention && choices.length ? `mention-${active}` : undefined"
          @blur="mention = null"
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
.day-sep { align-self: center; margin: 12px 0 8px; }
.day-sep span { display: inline-block; padding: 3px 12px; border-radius: 12px; background: var(--chip-bg); color: #fff; font-size: 0.78rem; }
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
.mention-list { flex: none; max-height: 220px; overflow-y: auto; padding: 6px calc(var(--safe-right) + 12px) 6px calc(var(--safe-left) + 12px); background: var(--surface); border-top: 1px solid var(--divider); }
.mention-row { width: 100%; display: flex; align-items: center; gap: 10px; padding: 6px 8px; border-radius: 10px; text-align: left; color: var(--text); }
.mention-row.on { background: var(--surface-2); }
.mention-name { font-weight: 600; }
.mention-handle { color: var(--muted); font-size: 0.85rem; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.mention-none { color: var(--muted); font-size: 0.88rem; padding-top: 10px; padding-bottom: 10px; }
.mention-offline { font-size: 0.74rem; color: var(--muted); padding: 1px 7px; border-radius: 9px; background: var(--surface-2); }
.mention-state { width: 8px; height: 8px; border-radius: 50%; background: var(--muted); }
.mention-state.idle { background: var(--ok, #3bb273); }
.mention-state.working { background: var(--accent); }
</style>
